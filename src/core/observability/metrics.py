"""
Runtime Metrics & SLA Monitoring for Symbioz.

Collects system-level and governance-level metrics for:
  - QoS decisions (adaptive throttling input)
  - SLA monitoring (degradation detection)
  - Dashboard / CLI reporting
  - Auto-mode switching triggers

Metrics are kept in-memory with a rolling window.
No external dependencies — can be wired to Prometheus/StatsD later.
"""

import time
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


class MetricsCollector:
    """In-memory metrics collector with rolling window."""

    def __init__(self, window_size: int = 300) -> None:
        self.window_size = window_size
        self._counters: Dict[str, float] = {}
        self._gauges: Dict[str, float] = {}
        self._histograms: Dict[str, deque] = {}
        self.logger = logging.getLogger("Metrics")

    def inc_counter(self, name: str, amount: float = 1.0) -> None:
        """Increment a monotonic counter."""
        self._counters[name] = self._counters.get(name, 0.0) + amount

    def set_gauge(self, name: str, value: float) -> None:
        """Set a gauge to an absolute value."""
        self._gauges[name] = value

    def observe(self, name: str, value: float) -> None:
        """Record an observation in a histogram (rolling window)."""
        if name not in self._histograms:
            self._histograms[name] = deque(maxlen=self.window_size)
        self._histograms[name].append((time.time(), value))

    def get_counter(self, name: str) -> float:
        return self._counters.get(name, 0.0)

    def get_gauge(self, name: str) -> float:
        return self._gauges.get(name, 0.0)

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
            "timestamp": time.time(),
        }

    def reset(self) -> None:
        """Reset all metrics (for testing)."""
        self._counters.clear()
        self._gauges.clear()
        self._histograms.clear()


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
                "total_intents": total,
                "approved": self.metrics.get_counter("intents_approved"),
                "rejected": self.metrics.get_counter("intents_rejected"),
                "quarantined": self.metrics.get_counter("intents_quarantined"),
                "errors": self.metrics.get_counter("intents_error"),
            },
            "timestamp": time.time(),
        }
