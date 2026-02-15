"""
Circuit Breaker — subsystem failure isolation for Symbioz.

Prevents cascading failures by tracking error rates per subsystem
and temporarily disabling unhealthy components.

States:
  CLOSED  → normal operation, errors are counted
  OPEN    → subsystem disabled, all calls fail-fast
  HALF_OPEN → single probe allowed to test recovery

Based on the classic Circuit Breaker pattern (Michael Nygard, "Release It!").
"""

import time
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Optional


class BreakerState(Enum):
    CLOSED = "closed"        # Normal — traffic flows
    OPEN = "open"            # Tripped — traffic blocked
    HALF_OPEN = "half_open"  # Recovery probe — single request allowed


@dataclass
class BreakerStatus:
    """Status of a single circuit breaker."""
    name: str
    state: BreakerState = BreakerState.CLOSED
    failure_count: int = 0
    success_count: int = 0
    last_failure_time: float = 0.0
    last_state_change: float = field(default_factory=time.time)
    total_trips: int = 0     # How many times this breaker has opened


class CircuitBreaker:
    """Manages circuit breakers for all subsystems."""

    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout_s: float = 30.0,
        half_open_max_probes: int = 1,
    ) -> None:
        self.failure_threshold = failure_threshold
        self.recovery_timeout_s = recovery_timeout_s
        self.half_open_max_probes = half_open_max_probes
        self.logger = logging.getLogger("CircuitBreaker")
        self._breakers: Dict[str, BreakerStatus] = {}

    def register(self, subsystem: str) -> None:
        """Register a subsystem for circuit breaking."""
        if subsystem not in self._breakers:
            self._breakers[subsystem] = BreakerStatus(name=subsystem)
            self.logger.info("Registered circuit breaker: %s", subsystem)

    def allow_request(self, subsystem: str) -> bool:
        """Check if a request to this subsystem should be allowed."""
        breaker = self._get_or_create(subsystem)
        now = time.time()

        if breaker.state == BreakerState.CLOSED:
            return True

        if breaker.state == BreakerState.OPEN:
            # Check if recovery timeout has elapsed
            elapsed = now - breaker.last_state_change
            if elapsed >= self.recovery_timeout_s:
                self._transition(breaker, BreakerState.HALF_OPEN)
                return True  # Allow one probe
            return False

        if breaker.state == BreakerState.HALF_OPEN:
            # Only allow limited probes
            return breaker.success_count < self.half_open_max_probes

        return False

    def record_success(self, subsystem: str) -> None:
        """Record a successful call to a subsystem."""
        breaker = self._get_or_create(subsystem)

        if breaker.state == BreakerState.HALF_OPEN:
            breaker.success_count += 1
            if breaker.success_count >= self.half_open_max_probes:
                self._transition(breaker, BreakerState.CLOSED)
                breaker.failure_count = 0
                self.logger.info("Circuit CLOSED: %s recovered", subsystem)

        elif breaker.state == BreakerState.CLOSED:
            # Reset failure count on success (consecutive failure tracking)
            breaker.failure_count = 0

    def record_failure(self, subsystem: str) -> None:
        """Record a failed call to a subsystem."""
        breaker = self._get_or_create(subsystem)
        breaker.failure_count += 1
        breaker.last_failure_time = time.time()

        if breaker.state == BreakerState.HALF_OPEN:
            # Probe failed — back to OPEN
            self._transition(breaker, BreakerState.OPEN)
            self.logger.warning(
                "Circuit OPEN (probe failed): %s — will retry in %.0fs",
                subsystem, self.recovery_timeout_s,
            )

        elif breaker.state == BreakerState.CLOSED:
            if breaker.failure_count >= self.failure_threshold:
                self._transition(breaker, BreakerState.OPEN)
                breaker.total_trips += 1
                self.logger.warning(
                    "Circuit OPEN: %s — %d consecutive failures (trip #%d)",
                    subsystem, breaker.failure_count, breaker.total_trips,
                )

    def get_status(self, subsystem: str) -> Optional[BreakerStatus]:
        """Get current status of a subsystem's breaker."""
        return self._breakers.get(subsystem)

    def get_all_status(self) -> Dict[str, dict]:
        """Get status of all breakers as a serializable dict."""
        return {
            name: {
                "state": b.state.value,
                "failures": b.failure_count,
                "total_trips": b.total_trips,
                "last_failure": b.last_failure_time,
            }
            for name, b in self._breakers.items()
        }

    def is_healthy(self, subsystem: str) -> bool:
        """Quick check: is this subsystem currently available?"""
        breaker = self._breakers.get(subsystem)
        if breaker is None:
            return True  # Unknown subsystem → assume healthy
        return breaker.state != BreakerState.OPEN

    def force_open(self, subsystem: str) -> None:
        """Manually trip a circuit breaker (emergency isolation)."""
        breaker = self._get_or_create(subsystem)
        self._transition(breaker, BreakerState.OPEN)
        breaker.total_trips += 1
        self.logger.warning("Circuit FORCE-OPENED: %s", subsystem)

    def force_close(self, subsystem: str) -> None:
        """Manually close a circuit breaker (manual recovery)."""
        breaker = self._get_or_create(subsystem)
        self._transition(breaker, BreakerState.CLOSED)
        breaker.failure_count = 0
        self.logger.info("Circuit FORCE-CLOSED: %s", subsystem)

    def _get_or_create(self, subsystem: str) -> BreakerStatus:
        if subsystem not in self._breakers:
            self.register(subsystem)
        return self._breakers[subsystem]

    def _transition(self, breaker: BreakerStatus, new_state: BreakerState) -> None:
        breaker.state = new_state
        breaker.success_count = 0
        breaker.last_state_change = time.time()
