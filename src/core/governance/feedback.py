"""
Telemetry Feedback Loop with EMA-based anomaly detection.

Closes the control loop: Observe -> Decide -> Act -> Observe.
Uses Exponential Moving Average for streaming statistics instead of
windowed buffers, giving better spike smoothing and faster recovery.

Key components:
  - EMATracker: streaming mean/variance/z-score with warmup period
  - FeedbackLoop: evaluates telemetry and recommends policy adjustments
  - FeedbackAction: immutable action descriptor applied by the caller
  - EpochRecord: snapshot of each adaptation for history/forensics

Design decisions (from debugging):
  - EMA-based latency tracking (not reservoir p95) — recovers faster after spikes
  - z-score guard for zero variance (constant samples → zscore returns 0)
  - Hysteresis thresholds (enter lockdown at 40%, exit at 5%)
  - Cooldown uses monotonic clock, _last_action_time=0 allows first evaluation
  - Minimum observation count before any decision
"""

import time
import logging
import threading
from dataclasses import dataclass, field
from typing import Optional, List

from .modes import SecurityPosture, PerformanceProfile


class EMATracker:
    """Exponential Moving Average with variance tracking and z-score anomaly detection.

    Maintains a streaming estimate of mean and variance using the
    Welford-like EMA update rule. Supports warmup period — z-score
    returns 0.0 until enough samples have been observed.

    Args:
        alpha: Smoothing factor (0..1). Higher = more reactive, less smooth.
        warmup: Minimum samples before is_warm and z-score are active.
    """

    def __init__(self, alpha: float = 0.1, warmup: int = 10) -> None:
        self.alpha = alpha
        self.warmup = warmup
        self._mean: float = 0.0
        self._variance: float = 0.0
        self._count: int = 0
        self._initialized: bool = False

    def update(self, value: float) -> None:
        """Feed a new observation."""
        self._count += 1
        if not self._initialized:
            self._mean = value
            self._variance = 0.0
            self._initialized = True
            return
        delta = value - self._mean
        self._mean += self.alpha * delta
        self._variance = (1.0 - self.alpha) * (self._variance + self.alpha * delta * delta)

    @property
    def mean(self) -> float:
        return self._mean

    @property
    def stddev(self) -> float:
        return max(self._variance, 0.0) ** 0.5

    @property
    def is_warm(self) -> bool:
        return self._count >= self.warmup

    @property
    def count(self) -> int:
        return self._count

    def zscore(self, value: float) -> float:
        """Compute z-score of a value against current distribution.

        Returns 0.0 if not warm or if variance is near-zero (constant signal).
        """
        if not self.is_warm:
            return 0.0
        if self.stddev < 1e-9:
            return 0.0
        return (value - self._mean) / self.stddev


@dataclass
class FeedbackConfig:
    """Tunable thresholds for the feedback loop."""
    # Performance
    cpu_overload: float = 0.85
    cpu_idle: float = 0.20
    latency_overload_ms: float = 2000.0
    latency_healthy_ms: float = 500.0

    # Security (hysteresis: enter != exit)
    rejection_rate_lockdown: float = 0.40
    rejection_rate_recovery: float = 0.05

    # Timing
    cooldown_s: float = 60.0
    min_observations: int = 20

    # EMA
    ema_alpha: float = 0.1
    ema_warmup: int = 10

    # Spike filtering — observations beyond this z-score are dampened
    zscore_spike_threshold: float = 4.0


@dataclass
class FeedbackAction:
    """Immutable action descriptor returned by FeedbackLoop.evaluate().

    The caller applies this to GovernanceEngine.update_axes().
    """
    name: str
    performance: Optional[PerformanceProfile] = None
    security: Optional[SecurityPosture] = None
    reason: str = ""


@dataclass
class EpochRecord:
    """Snapshot of a single feedback adaptation."""
    timestamp: float
    action: str
    avg_latency: float
    rejection_rate: float
    cpu_usage: float
    performance: str
    security: str


@dataclass
class FeedbackState:
    """Current state of the feedback loop for monitoring."""
    last_adaptation_time: float = 0.0
    total_adaptations: int = 0
    last_action: str = "none"
    current_avg_latency_ms: Optional[float] = None
    current_rejection_rate: Optional[float] = None
    current_cpu_usage: Optional[float] = None
    in_cooldown: bool = False


class FeedbackLoop:
    """Adaptive controller that adjusts GovernanceEngine parameters
    based on real-time telemetry.

    Thread-safe: all state mutations are protected by a reentrant lock.

    Uses EMA for streaming statistics — no windowed buffers, no reservoir
    p95 dependency. EMA recovers faster after spikes than reservoir-based
    percentiles (which keep all historical samples).

    Z-score spike filtering: extreme latency outliers (|z| > threshold) are
    dampened before updating EMA, preventing a single spike from dominating
    the mean. The raw value is still recorded in MetricsCollector.

    Does NOT import GovernanceEngine — returns FeedbackAction objects
    that the caller applies, avoiding circular dependency.
    """

    def __init__(
        self,
        metrics,
        config: Optional[FeedbackConfig] = None,
        audit=None,
    ) -> None:
        self.metrics = metrics
        self.config = config or FeedbackConfig()
        self.audit = audit
        self.logger = logging.getLogger("FeedbackLoop")
        self._lock = threading.RLock()

        self._latency_ema = EMATracker(
            alpha=self.config.ema_alpha,
            warmup=self.config.ema_warmup,
        )
        self._rejection_ema = EMATracker(
            alpha=self.config.ema_alpha,
            warmup=self.config.ema_warmup,
        )
        self._observation_count: int = 0
        self._spike_count: int = 0
        self._last_action_time: float = 0.0  # 0 = never acted, allows first eval
        self._total_adaptations: int = 0
        self._last_action_name: str = "none"
        self._epochs: List[EpochRecord] = []

    def observe(self, latency_ms: float, rejected: bool) -> None:
        """Feed a single observation. Call after every intent.

        Z-score spike filtering: if the EMA is warm and the latency has
        |z-score| > threshold, the EMA receives a clamped value instead
        of the raw outlier. MetricsCollector always gets the raw value.
        """
        with self._lock:
            self._observation_count += 1

            # Spike filtering for latency EMA
            damped_latency = latency_ms
            if self._latency_ema.is_warm:
                mean = self._latency_ema.mean
                sd = self._latency_ema.stddev
                if sd < 1e-9:
                    # Near-constant baseline: any large deviation is a spike
                    # Use 1% of mean as minimum stddev proxy
                    sd_proxy = max(abs(mean) * 0.01, 1.0)
                    z = (latency_ms - mean) / sd_proxy
                else:
                    z = (latency_ms - mean) / sd

                if abs(z) > self.config.zscore_spike_threshold:
                    self._spike_count += 1
                    # Clamp to threshold boundary instead of feeding raw spike
                    clamp_sd = sd if sd >= 1e-9 else max(abs(mean) * 0.01, 1.0)
                    damped_latency = (
                        mean
                        + self.config.zscore_spike_threshold * clamp_sd
                        * (1.0 if z > 0 else -1.0)
                    )

            self._latency_ema.update(damped_latency)
            self._rejection_ema.update(1.0 if rejected else 0.0)

        # Feed MetricsCollector with raw value (outside lock — no shared state)
        self.metrics.observe("intent_latency_ms", latency_ms)
        self.metrics.inc_counter("intents_total")
        if rejected:
            self.metrics.inc_counter("intents_rejected")
        else:
            self.metrics.inc_counter("intents_approved")

    def evaluate(
        self,
        current_performance: PerformanceProfile,
        current_security: SecurityPosture,
        cpu_usage: float = 0.0,
    ) -> Optional[FeedbackAction]:
        """Evaluate telemetry and return action if adaptation needed.

        Returns None if: not enough data, in cooldown, or no change needed.
        Thread-safe: reads state under lock.
        """
        with self._lock:
            now = time.monotonic()

            # Cooldown: skip if last action was recent (but allow first-ever evaluation)
            if self._last_action_time > 0 and (now - self._last_action_time) < self.config.cooldown_s:
                return None

            # Minimum observations
            if self._observation_count < self.config.min_observations:
                return None

            avg_latency = self._latency_ema.mean
            rejection_rate = self._rejection_ema.mean

            # --- Performance adaptation ---
            # Overload → ECO
            if cpu_usage > self.config.cpu_overload or avg_latency > self.config.latency_overload_ms:
                if current_performance != PerformanceProfile.ECO:
                    reason = (
                        f"Overload (CPU={cpu_usage:.0%}, latency={avg_latency:.0f}ms)"
                    )
                    self.logger.warning(reason)
                    return self._make_action(
                        "performance_downshift", now,
                        avg_latency, rejection_rate, cpu_usage,
                        current_performance.name, current_security.name,
                        performance=PerformanceProfile.ECO, reason=reason,
                    )

            # Idle → BALANCED (only from ECO, conservative)
            if (
                cpu_usage < self.config.cpu_idle
                and avg_latency < self.config.latency_healthy_ms
                and current_performance == PerformanceProfile.ECO
            ):
                reason = (
                    f"Idle (CPU={cpu_usage:.0%}, latency={avg_latency:.0f}ms)"
                )
                self.logger.info(reason)
                return self._make_action(
                    "performance_upshift", now,
                    avg_latency, rejection_rate, cpu_usage,
                    current_performance.name, current_security.name,
                    performance=PerformanceProfile.BALANCED, reason=reason,
                )

            # --- Security adaptation ---
            # High rejection → LOCKDOWN
            if rejection_rate > self.config.rejection_rate_lockdown:
                if current_security != SecurityPosture.LOCKDOWN:
                    reason = f"High rejection rate ({rejection_rate:.0%})"
                    self.logger.critical(reason)
                    return self._make_action(
                        "security_lockdown", now,
                        avg_latency, rejection_rate, cpu_usage,
                        current_performance.name, current_security.name,
                        security=SecurityPosture.LOCKDOWN, reason=reason,
                    )

            # Recovery → GUARDED (only from LOCKDOWN, hysteresis)
            if (
                rejection_rate < self.config.rejection_rate_recovery
                and current_security == SecurityPosture.LOCKDOWN
            ):
                reason = f"Rejection rate normalized ({rejection_rate:.0%})"
                self.logger.info(reason)
                return self._make_action(
                    "security_recovery", now,
                    avg_latency, rejection_rate, cpu_usage,
                    current_performance.name, current_security.name,
                    security=SecurityPosture.GUARDED, reason=reason,
                )

            return None

    def _make_action(
        self, name, now, avg_latency, rejection_rate, cpu_usage,
        perf_name, sec_name,
        performance=None, security=None, reason="",
    ) -> FeedbackAction:
        """Create action, record epoch, audit."""
        self._last_action_time = now
        self._total_adaptations += 1
        self._last_action_name = name

        self._epochs.append(EpochRecord(
            timestamp=now,
            action=name,
            avg_latency=avg_latency,
            rejection_rate=rejection_rate,
            cpu_usage=cpu_usage,
            performance=perf_name,
            security=sec_name,
        ))

        if self.audit:
            self.audit.append("feedback_action", {
                "action": name,
                "reason": reason,
                "avg_latency": avg_latency,
                "rejection_rate": rejection_rate,
            })

        return FeedbackAction(
            name=name,
            performance=performance,
            security=security,
            reason=reason,
        )

    @property
    def epochs(self) -> List[EpochRecord]:
        return list(self._epochs)

    @property
    def total_adaptations(self) -> int:
        return self._total_adaptations

    @property
    def state(self) -> FeedbackState:
        return FeedbackState(
            last_adaptation_time=self._last_action_time,
            total_adaptations=self._total_adaptations,
            last_action=self._last_action_name,
            current_avg_latency_ms=self._latency_ema.mean if self._latency_ema.is_warm else None,
            current_rejection_rate=self._rejection_ema.mean if self._rejection_ema.is_warm else None,
        )

    @property
    def spike_count(self) -> int:
        with self._lock:
            return self._spike_count

    def status(self) -> dict:
        """Status snapshot for monitoring/dashboard."""
        with self._lock:
            return {
                "total_adaptations": self._total_adaptations,
                "last_action": self._last_action_name,
                "observations": self._observation_count,
                "spikes_dampened": self._spike_count,
                "avg_latency": self._latency_ema.mean if self._latency_ema.is_warm else None,
                "rejection_rate": self._rejection_ema.mean if self._rejection_ema.is_warm else None,
                "epochs": len(self._epochs),
            }
