"""
Panic Switch — emergency mode transition for Symbioz.

Provides instant system lockdown without process restart:
  - File-based trigger: `touch data/panic.lock` → instant FORENSIC mode
  - Programmatic trigger: PanicSwitch.activate("reason")
  - Auto-clear with timeout or manual `PanicSwitch.deactivate()`

When panic is active:
  - GovernanceEngine switches to FORENSIC mode (read-only)
  - All new intents are rejected
  - Audit log records the panic event
  - System remains running for forensic analysis
"""

import os
import time
import json
import logging
from dataclasses import dataclass
from typing import Optional


@dataclass
class PanicState:
    """Current state of the panic switch."""
    active: bool = False
    reason: str = ""
    activated_at: float = 0.0
    activated_by: str = ""    # "file", "api", "auto"
    auto_clear_after_s: float = 0.0  # 0 = manual clear only


class PanicSwitch:
    """Emergency lockdown controller."""

    def __init__(
        self,
        lock_path: str = "data/panic.lock",
        auto_clear_s: float = 0.0,
    ) -> None:
        self.lock_path = lock_path
        self.auto_clear_s = auto_clear_s
        self.logger = logging.getLogger("PanicSwitch")
        self._state = PanicState()
        self._check_file_trigger()

    def activate(self, reason: str = "Manual activation", source: str = "api") -> None:
        """Activate panic mode immediately."""
        self._state = PanicState(
            active=True,
            reason=reason,
            activated_at=time.time(),
            activated_by=source,
            auto_clear_after_s=self.auto_clear_s,
        )
        # Create lock file as persistent indicator
        self._write_lock_file(reason)
        self.logger.critical("PANIC ACTIVATED: %s (source: %s)", reason, source)

    def deactivate(self, operator: str = "system") -> None:
        """Deactivate panic mode (manual recovery)."""
        if not self._state.active:
            return
        self._state.active = False
        self._remove_lock_file()
        self.logger.info(
            "Panic deactivated by %s (was active for %.0fs)",
            operator,
            time.time() - self._state.activated_at,
        )

    def check(self) -> bool:
        """Check if panic is currently active. Also checks file trigger and auto-clear."""
        # Check file-based trigger
        self._check_file_trigger()

        # Check auto-clear timeout
        if (
            self._state.active
            and self._state.auto_clear_after_s > 0
            and time.time() - self._state.activated_at > self._state.auto_clear_after_s
        ):
            self.logger.info("Panic auto-cleared after %.0fs", self._state.auto_clear_after_s)
            self.deactivate(operator="auto_clear")

        return self._state.active

    @property
    def state(self) -> PanicState:
        self.check()  # Refresh state
        return self._state

    @property
    def is_active(self) -> bool:
        return self.check()

    def _check_file_trigger(self) -> None:
        """Check if panic.lock file exists (external trigger)."""
        if os.path.exists(self.lock_path) and not self._state.active:
            # Read reason from file if present
            reason = "External trigger (panic.lock detected)"
            try:
                with open(self.lock_path, "r") as f:
                    content = f.read().strip()
                    if content:
                        reason = content
            except OSError:
                pass
            self._state = PanicState(
                active=True,
                reason=reason,
                activated_at=time.time(),
                activated_by="file",
                auto_clear_after_s=self.auto_clear_s,
            )
            self.logger.critical("PANIC DETECTED via lock file: %s", reason)

    def _write_lock_file(self, reason: str) -> None:
        """Write panic lock file."""
        os.makedirs(os.path.dirname(self.lock_path) or ".", exist_ok=True)
        try:
            with open(self.lock_path, "w") as f:
                f.write(json.dumps({
                    "reason": reason,
                    "activated_at": self._state.activated_at,
                    "source": self._state.activated_by,
                }))
        except OSError as e:
            self.logger.error("Failed to write panic lock: %s", e)

    def _remove_lock_file(self) -> None:
        """Remove panic lock file."""
        try:
            if os.path.exists(self.lock_path):
                os.remove(self.lock_path)
        except OSError as e:
            self.logger.error("Failed to remove panic lock: %s", e)
