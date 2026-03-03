"""
Runtime Metrics & SLA Monitoring for Symbioz.

Collects system-level and governance-level metrics for:
  - QoS decisions (adaptive throttling input)
  - SLA monitoring (degradation detection)
  - Dashboard / CLI reporting
  - Auto-mode switching triggers

Metric types:
  - Counters: monotonically increasing (intents_total, intents_rejected)
  - Gauges: absolute values (cpu_usage, memory_usage)
  - Histograms: timestamped observations with rolling window
  - Reservoir: streaming approximate percentile (p95, p99) via reservoir sampling
  - Events: timestamped structured events for recent activity

No external dependencies — can be wired to Prometheus/StatsD later.
"""

import time
import random
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from collections import deque


@dataclass
class MetricPoint:
    """Single metric observation."""
    name: str
    value: float
    timestamp: float = field(default_factory=time.time)
    labels: Dict[str, str] = field(default_factory=dict)


class ReservoirSampler:
    """Vitter's Algorithm R for streaming approximate percentile computation.

    Maintains a fixed-size sample from a potentially infinite stream.
    Every element has equal probability of being in the sample.

    Use for p95/p99 when you can't keep all observations in memory.
    """

    def __init__(self, capacity: int = 1000) -> None:
        self._samples: List[float] = []
        self._capacity = capacity
        self._count: int = 0

    def add(self, value: float) -> None:
        """Add an observation to the reservoir."""
        self._count += 1
        if len(self._samples) < self._capacity:
            self._samples.append(value)
        else:
            idx = random.randint(0, self._count - 1)
            if idx < self._capacity:
                self._samples[idx] = value

    def percentile(self, p: float) -> float:
        """Get approximate percentile (0-100). Returns 0.0 if empty."""
        if not self._samples:
            return 0.0
        sorted_samples = sorted(self._samples)
        idx = int(len(sorted_samples) * p / 100.0)
        return sorted_samples[min(idx, len(sorted_samples) - 1)]

    def p95(self) -> float:
        return self.percentile(95)

    def p99(self) -> float:
        return self.percentile(99)

    @property
    def count(self) -> int:
        return self._count

    @property
    def size(self) -> int:
        return len(self._samples)

    def reset(self) -> None:
        self._samples.clear()
        self._count = 0


@dataclass
class Event:
    """Structured event for recent activity tracking."""
    name: str
    data: dict
    timestamp: float = field(default_factory=time.time)


class MetricsCollector:
    """In-memory metrics collector with rolling window, reservoir sampling, and event log."""

    def __init__(self, window_size: int = 300, reservoir_capacity: int = 1000) -> None:
        self.window_size = window_size
        self.reservoir_capacity = reservoir_capacity
        self._counters: Dict[str, float] = {}
        self._gauges: Dict[str, float] = {}
        self._histograms: Dict[str, deque] = {}
        self._reservoirs: Dict[str, ReservoirSampler] = {}
        self._events: deque = deque(maxlen=1000)
        self.logger = logging.getLogger("Metrics")

    # --- Counters ---

    def inc_counter(self, name: str, amount: float = 1.0) -> None:
        """Increment a monotonic counter."""
        self._counters[name] = self._counters.get(name, 0.0) + amount

    def get_counter(self, name: str) -> float:
        return self._counters.get(name, 0.0)

    # --- Gauges ---

    def set_gauge(self, name: str, value: float) -> None:
        """Set a gauge to an absolute value."""
        self._gauges[name] = value

    def get_gauge(self, name: str) -> float:
        return self._gauges.get(name, 0.0)

    # --- Histograms (time-windowed) ---

    def observe(self, name: str, value: float) -> None:
        """Record an observation in histogram AND reservoir."""
        if name not in self._histograms:
            self._histograms[name] = deque(maxlen=self.window_size)
        self._histograms[name].append((time.time(), value))

        # Also feed reservoir for percentile tracking
        if name not in self._reservoirs:
            self._reservoirs[name] = ReservoirSampler(capacity=self.reservoir_capacity)
        self._reservoirs[name].add(value)

    def get_histogram_avg(self, name: str, window_s: float = 60.0) -> Optional[float]:
        """Get average of histogram observations within time window."""
        hist = self._histograms.get(name)
        if not hist:
            return None
        cutoff = time.time() - window_s
        values = [v for ts, v in hist if ts >= cutoff]
        if not values:
            return None
        return sum(values) / len(values)

    def get_histogram_p99(self, name: str, window_s: float = 60.0) -> Optional[float]:
        """Get p99 of histogram observations within time window."""
        hist = self._histograms.get(name)
        if not hist:
            return None
        cutoff = time.time() - window_s
        values = sorted(v for ts, v in hist if ts >= cutoff)
        if not values:
            return None
        idx = int(len(values) * 0.99)
        return values[min(idx, len(values) - 1)]

    # --- Reservoir percentiles ---

    def get_percentile(self, name: str, p: float) -> float:
        """Get approximate percentile from reservoir sampler."""
        reservoir = self._reservoirs.get(name)
        if not reservoir:
            return 0.0
        return reservoir.percentile(p)

    def get_p95(self, name: str) -> float:
        return self.get_percentile(name, 95)

    def get_p99(self, name: str) -> float:
        return self.get_percentile(name, 99)

    # --- Events ---

    def record_event(self, name: str, data: Optional[dict] = None) -> None:
        """Record a structured event."""
        self._events.append(Event(name=name, data=data or {}))

    def get_recent_events(self, limit: int = 50) -> List[Event]:
        """Get most recent events."""
        return list(self._events)[-limit:]

    # --- Snapshot & Reset ---

    def snapshot(self) -> dict:
        """Return full metrics snapshot for reporting."""
        return {
            "counters": dict(self._counters),
            "gauges": dict(self._gauges),
            "histograms": {
                name: {
                    "count": len(hist),
                    "avg": self.get_histogram_avg(name),
                    "p99": self.get_histogram_p99(name),
                }
                for name, hist in self._histograms.items()
            },
            "reservoirs": {
                name: {
                    "count": r.count,
                    "p95": r.p95(),
                    "p99": r.p99(),
                }
                for name, r in self._reservoirs.items()
            },
            "events": len(self._events),
            "timestamp": time.time(),
        }

    def reset(self) -> None:
        """Reset all metrics (for testing)."""
        self._counters.clear()
        self._gauges.clear()
        self._histograms.clear()
        self._reservoirs.clear()
        self._events.clear()


class SLAMonitor:
    """Monitors service-level indicators and triggers alerts.

    Tracks:
      - Intent processing latency (avg, p99)
      - Approval / rejection rates
      - Error rates
      - Consensus delays
      - P2P packet loss

    When SLA thresholds are breached, returns degradation signals
    that the GovernanceEngine can use for auto-mode switching.
    """

    def __init__(
        self,
        metrics: MetricsCollector,
        latency_sla_ms: float = 200.0,
        error_rate_sla: float = 0.05,
        approval_rate_floor: float = 0.3,
    ) -> None:
        self.metrics = metrics
        self.latency_sla_ms = latency_sla_ms
        self.error_rate_sla = error_rate_sla
        self.approval_rate_floor = approval_rate_floor
        self.logger = logging.getLogger("SLAMonitor")

    def check(self) -> Dict[str, bool]:
        """Check all SLA conditions. Returns dict of {indicator: is_healthy}."""
        results = {}

        # Latency SLA
        avg_latency = self.metrics.get_histogram_avg("intent_latency_ms")
        results["latency"] = avg_latency is None or avg_latency <= self.latency_sla_ms

        # Error rate SLA
        total = self.metrics.get_counter("intents_total")
        errors = self.metrics.get_counter("intents_error")
        if total > 0:
            error_rate = errors / total
            results["error_rate"] = error_rate <= self.error_rate_sla
        else:
            results["error_rate"] = True

        # Approval rate floor (too many rejections = something wrong)
        approved = self.metrics.get_counter("intents_approved")
        if total > 10:  # Need minimum sample size
            approval_rate = approved / total
            results["approval_rate"] = approval_rate >= self.approval_rate_floor
        else:
            results["approval_rate"] = True

        return results

    def is_degraded(self) -> bool:
        """True if any SLA is breached."""
        return not all(self.check().values())

    def report(self) -> dict:
        """Full SLA report for dashboard/CLI."""
        checks = self.check()
        total = self.metrics.get_counter("intents_total")
        return {
            "healthy": all(checks.values()),
            "checks": checks,
            "metrics": {
                "avg_latency_ms": self.metrics.get_histogram_avg("intent_latency_ms"),
                "p99_latency_ms": self.metrics.get_histogram_p99("intent_latency_ms"),
                "p95_latency_ms": self.metrics.get_p95("intent_latency_ms"),
                "total_intents": total,
                "approved": self.metrics.get_counter("intents_approved"),
                "rejected": self.metrics.get_counter("intents_rejected"),
                "quarantined": self.metrics.get_counter("intents_quarantined"),
                "errors": self.metrics.get_counter("intents_error"),
            },
            "timestamp": time.time(),
        }
