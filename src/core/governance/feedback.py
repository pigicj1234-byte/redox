"""
Telemetry Feedback Loop — the autonomy layer for Symbioz.

Closes the control loop: observes system telemetry, detects sustained
anomalies, and triggers automatic policy adjustments.

This is what makes the system adaptive rather than just reactive:
  - Sustained CPU/latency pressure → downshift to ECO
  - Idle conditions → upshift to BALANCED
  - High rejection rate spike → auto-LOCKDOWN
  - Threat subsides → revert to GUARDED

Design principles:
  - Cooldown prevents oscillation (no flip-flopping)
  - Hysteresis thresholds (different enter/exit thresholds)
  - All transitions are audited
  - Minimum observation window before acting (no single-sample reactions)
"""

import time
import logging
from dataclasses import dataclass, field
from collections import deque
from typing import Optional

from .modes import SecurityPosture, PerformanceProfile, PERFORMANCE_PRESETS
from ..observability.metrics import MetricsCollector


@dataclass
class FeedbackConfig:
    """Tunable thresholds for the feedback loop."""
    # Performance thresholds
    cpu_overload_threshold: float = 0.85        # CPU usage to trigger downshift
    cpu_idle_threshold: float = 0.20            # CPU usage to allow upshift
    latency_overload_ms: float = 2000.0         # Avg latency to trigger downshift
    latency_healthy_ms: float = 500.0           # Avg latency to allow upshift

    # Security thresholds (hysteresis: enter != exit)
    rejection_rate_lockdown: float = 0.40       # Rejection rate to trigger lockdown
    rejection_rate_recovery: float = 0.05       # Rejection rate to allow recovery

    # Timing
    cooldown_s: float = 60.0                    # Min seconds between adjustments
    min_observations: int = 20                  # Min samples before acting
    observation_window_s: float = 300.0         # Window for metric aggregation (5 min)


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
    based on real-time telemetry from MetricsCollector.

    Does NOT import GovernanceEngine to avoid circular dependency.
    Instead, it returns FeedbackAction objects that the caller applies.
    """

    def __init__(
        self,
        metrics: MetricsCollector,
        config: Optional[FeedbackConfig] = None,
    ) -> None:
        self.metrics = metrics
        self.config = config or FeedbackConfig()
        self.logger = logging.getLogger("FeedbackLoop")
        self._state = FeedbackState()

        # Observation buffers (separate from MetricsCollector for feedback-specific tracking)
        self._latency_buffer: deque = deque(maxlen=500)
        self._rejection_buffer: deque = deque(maxlen=500)

    def observe(self, latency_ms: float, rejected: bool) -> None:
        """Feed a single observation into the loop. Call after every intent."""
        now = time.time()
        self._latency_buffer.append((now, latency_ms))
        self._rejection_buffer.append((now, 1.0 if rejected else 0.0))

        # Also feed into MetricsCollector for dashboard visibility
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
    ) -> Optional["FeedbackAction"]:
        """Evaluate telemetry and return an action if adaptation is needed.

        Returns None if no change is needed or cooldown is active.
        The caller (daemon loop) applies the action to the GovernanceEngine.
        """
        now = time.time()

        # Cooldown check
        elapsed = now - self._state.last_adaptation_time
        if elapsed < self.config.cooldown_s and self._state.last_adaptation_time > 0:
            self._state.in_cooldown = True
            return None
        self._state.in_cooldown = False

        # Compute windowed averages
        cutoff = now - self.config.observation_window_s
        recent_latencies = [v for ts, v in self._latency_buffer if ts >= cutoff]
        recent_rejections = [v for ts, v in self._rejection_buffer if ts >= cutoff]

        # Need minimum observations
        if len(recent_latencies) < self.config.min_observations:
            return None

        avg_latency = sum(recent_latencies) / len(recent_latencies)
        rejection_rate = sum(recent_rejections) / len(recent_rejections)

        # Update state for monitoring
        self._state.current_avg_latency_ms = avg_latency
        self._state.current_rejection_rate = rejection_rate
        self._state.current_cpu_usage = cpu_usage

        # --- Performance adaptation ---
        perf_action = self._evaluate_performance(
            current_performance, cpu_usage, avg_latency
        )
        if perf_action:
            return perf_action

        # --- Security adaptation ---
        sec_action = self._evaluate_security(
            current_security, rejection_rate
        )
        if sec_action:
            return sec_action

        return None

    def _evaluate_performance(
        self,
        current: PerformanceProfile,
        cpu_usage: float,
        avg_latency: float,
    ) -> Optional["FeedbackAction"]:
        """Check if performance profile needs adjustment."""
        # Overload → downshift
        if cpu_usage > self.config.cpu_overload_threshold or avg_latency > self.config.latency_overload_ms:
            if current != PerformanceProfile.ECO:
                reason = (
                    f"System overload detected (CPU={cpu_usage:.0%}, "
                    f"latency={avg_latency:.0f}ms) — downshifting to ECO"
                )
                self.logger.warning(reason)
                return self._make_action("performance_downshift", performance=PerformanceProfile.ECO, reason=reason)

        # Idle → upshift (only from ECO to BALANCED, conservative)
        if (
            cpu_usage < self.config.cpu_idle_threshold
            and avg_latency < self.config.latency_healthy_ms
            and current == PerformanceProfile.ECO
        ):
            reason = (
                f"System idle (CPU={cpu_usage:.0%}, "
                f"latency={avg_latency:.0f}ms) — upshifting to BALANCED"
            )
            self.logger.info(reason)
            return self._make_action("performance_upshift", performance=PerformanceProfile.BALANCED, reason=reason)

        return None

    def _evaluate_security(
        self,
        current: SecurityPosture,
        rejection_rate: float,
    ) -> Optional["FeedbackAction"]:
        """Check if security posture needs adjustment."""
        # High rejection rate → lockdown
        if rejection_rate > self.config.rejection_rate_lockdown:
            if current != SecurityPosture.LOCKDOWN:
                reason = (
                    f"High rejection rate ({rejection_rate:.0%}) — "
                    f"initiating LOCKDOWN"
                )
                self.logger.critical(reason)
                return self._make_action("security_lockdown", security=SecurityPosture.LOCKDOWN, reason=reason)

        # Threat subsiding → revert (only from LOCKDOWN, with hysteresis)
        if (
            rejection_rate < self.config.rejection_rate_recovery
            and current == SecurityPosture.LOCKDOWN
        ):
            reason = (
                f"Rejection rate normalized ({rejection_rate:.0%}) — "
                f"reverting to GUARDED"
            )
            self.logger.info(reason)
            return self._make_action("security_recovery", security=SecurityPosture.GUARDED, reason=reason)

        return None

    def _make_action(self, name: str, **kwargs) -> "FeedbackAction":
        """Create an action and update internal state."""
        self._state.last_adaptation_time = time.time()
        self._state.total_adaptations += 1
        self._state.last_action = name
        return FeedbackAction(name=name, **kwargs)

    @property
    def state(self) -> FeedbackState:
        return self._state

    def status(self) -> dict:
        """Status snapshot for monitoring/dashboard."""
        return {
            "last_action": self._state.last_action,
            "total_adaptations": self._state.total_adaptations,
            "in_cooldown": self._state.in_cooldown,
            "avg_latency_ms": self._state.current_avg_latency_ms,
            "rejection_rate": self._state.current_rejection_rate,
            "cpu_usage": self._state.current_cpu_usage,
            "observation_count": len(self._latency_buffer),
        }


@dataclass
class FeedbackAction:
    """An adaptation action recommended by the FeedbackLoop.

    The caller applies this to the GovernanceEngine via update_axes().
    """
    name: str
    performance: Optional[PerformanceProfile] = None
    security: Optional[SecurityPosture] = None
    reason: str = ""
