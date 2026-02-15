"""
Adaptive QoS Controller — Quality of Service management for Symbioz.

Monitors system load and automatically adjusts runtime parameters
to maintain stability under pressure. Implements:
  - Backpressure detection (queue depth monitoring)
  - Adaptive throttling (graceful speed reduction)
  - Degraded-but-stable mode transitions
  - Load shedding (reject low-priority intents when overloaded)

This is the difference between "crashes under load" and "degrades gracefully".
"""

import time
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class LoadLevel(Enum):
    """Current system load classification."""
    IDLE = "idle"            # < 30% capacity
    NORMAL = "normal"        # 30-70% capacity
    ELEVATED = "elevated"    # 70-85% capacity
    CRITICAL = "critical"    # > 85% capacity
    OVERLOAD = "overload"    # Queue backlog, active shedding


@dataclass
class SystemMetrics:
    """Snapshot of current system state for QoS decisions."""
    cpu_usage: float = 0.0          # 0.0 - 1.0
    memory_usage: float = 0.0       # 0.0 - 1.0
    queue_depth: int = 0            # Pending intents in queue
    avg_latency_ms: float = 0.0     # Rolling average intent latency
    error_rate: float = 0.0         # Errors per second (rolling)
    p2p_packet_loss: float = 0.0    # 0.0 - 1.0
    timestamp: float = field(default_factory=time.time)


@dataclass
class QoSAdjustment:
    """Recommended adjustments from QoS evaluation."""
    speed_multiplier: float = 1.0       # Applied to cognitive_speed
    fuel_multiplier: float = 1.0        # Applied to max_fuel_per_intent
    rate_limit_multiplier: float = 1.0  # Applied to p2p_rate_limit
    shed_low_priority: bool = False     # Drop low-priority intents
    load_level: LoadLevel = LoadLevel.NORMAL
    reasons: list = field(default_factory=list)


class AdaptiveQoSController:
    """Monitors load and produces QoS adjustments.

    Does NOT mutate policy directly — returns QoSAdjustment that the
    GovernanceEngine applies to its effective parameters.
    """

    def __init__(
        self,
        backpressure_threshold: int = 100,
        latency_threshold_ms: float = 200.0,
        cpu_threshold: float = 0.85,
        memory_threshold: float = 0.90,
        adaptive_throttling: bool = True,
    ) -> None:
        self.backpressure_threshold = backpressure_threshold
        self.latency_threshold_ms = latency_threshold_ms
        self.cpu_threshold = cpu_threshold
        self.memory_threshold = memory_threshold
        self.adaptive_throttling = adaptive_throttling
        self.logger = logging.getLogger("QoS")
        self._history: list[SystemMetrics] = []
        self._max_history = 60  # Keep last 60 snapshots

    def evaluate(self, metrics: SystemMetrics) -> QoSAdjustment:
        """Evaluate current metrics and return recommended adjustments."""
        self._history.append(metrics)
        if len(self._history) > self._max_history:
            self._history = self._history[-self._max_history:]

        adj = QoSAdjustment()

        # 1. CPU pressure
        if metrics.cpu_usage > self.cpu_threshold:
            adj.speed_multiplier = min(adj.speed_multiplier, 0.6)
            adj.fuel_multiplier = min(adj.fuel_multiplier, 0.5)
            adj.reasons.append(
                f"CPU {metrics.cpu_usage:.0%} > threshold {self.cpu_threshold:.0%}"
            )

        # 2. Memory pressure
        if metrics.memory_usage > self.memory_threshold:
            adj.fuel_multiplier = min(adj.fuel_multiplier, 0.3)
            adj.reasons.append(
                f"Memory {metrics.memory_usage:.0%} > threshold {self.memory_threshold:.0%}"
            )

        # 3. Queue backpressure
        if metrics.queue_depth > self.backpressure_threshold:
            ratio = metrics.queue_depth / self.backpressure_threshold
            adj.rate_limit_multiplier = min(adj.rate_limit_multiplier, 1.0 / ratio)
            adj.shed_low_priority = ratio > 2.0
            adj.reasons.append(
                f"Queue depth {metrics.queue_depth} > threshold {self.backpressure_threshold}"
            )

        # 4. Latency degradation
        if metrics.avg_latency_ms > self.latency_threshold_ms:
            slowdown = self.latency_threshold_ms / metrics.avg_latency_ms
            adj.speed_multiplier = min(adj.speed_multiplier, slowdown)
            adj.reasons.append(
                f"Latency {metrics.avg_latency_ms:.0f}ms > threshold {self.latency_threshold_ms:.0f}ms"
            )

        # 5. Network degradation
        if metrics.p2p_packet_loss > 0.1:
            adj.rate_limit_multiplier = min(adj.rate_limit_multiplier, 0.5)
            adj.reasons.append(
                f"Packet loss {metrics.p2p_packet_loss:.0%} — reducing P2P rate"
            )

        # Classify load level
        adj.load_level = self._classify_load(metrics, adj)

        if adj.reasons and self.adaptive_throttling:
            self.logger.warning(
                "QoS adjustment: load=%s, speed=%.2f, fuel=%.2f, shedding=%s | %s",
                adj.load_level.value,
                adj.speed_multiplier,
                adj.fuel_multiplier,
                adj.shed_low_priority,
                "; ".join(adj.reasons),
            )

        return adj

    def _classify_load(self, metrics: SystemMetrics, adj: QoSAdjustment) -> LoadLevel:
        """Classify overall load level from metrics."""
        if adj.shed_low_priority:
            return LoadLevel.OVERLOAD
        if metrics.cpu_usage > self.cpu_threshold or metrics.queue_depth > self.backpressure_threshold:
            return LoadLevel.CRITICAL
        if metrics.cpu_usage > 0.70 or metrics.avg_latency_ms > self.latency_threshold_ms * 0.8:
            return LoadLevel.ELEVATED
        if metrics.cpu_usage > 0.30:
            return LoadLevel.NORMAL
        return LoadLevel.IDLE

    def trend(self, window: int = 10) -> Optional[str]:
        """Return load trend over last N snapshots: 'improving', 'stable', 'degrading'."""
        if len(self._history) < window:
            return None
        recent = self._history[-window:]
        first_half = sum(m.cpu_usage for m in recent[:window // 2]) / (window // 2)
        second_half = sum(m.cpu_usage for m in recent[window // 2:]) / (window - window // 2)
        delta = second_half - first_half
        if delta > 0.1:
            return "degrading"
        elif delta < -0.1:
            return "improving"
        return "stable"
