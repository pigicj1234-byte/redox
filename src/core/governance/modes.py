"""
Operational modes, security postures, and performance profiles for Symbioz Governance.

Three independent axes of system behavior:
  - OperationalMode: what the system *does* (dev/prod/paranoid/forensic)
  - SecurityPosture: how *defensive* the system is (open → lockdown)
  - PerformanceProfile: how *fast* vs *thorough* (eco → turbo)

These can be combined independently:
  mode=PRODUCTION + security=HARDENED + performance=ECO  (low-power secure server)
  mode=DEVELOPMENT + security=OPEN + performance=TURBO   (local dev machine)
"""

from enum import Enum


class OperationalMode(Enum):
    DEVELOPMENT = "development"
    PRODUCTION = "production"
    PARANOID = "paranoid"
    FORENSIC = "forensic"


class SecurityPosture(Enum):
    """Independent security level — can change without affecting mode or performance."""
    OPEN = "open"            # No signature checks, minimal validation
    GUARDED = "guarded"      # Signatures required, basic reputation checks
    HARDENED = "hardened"     # Strict validation, elevated thresholds
    LOCKDOWN = "lockdown"    # Maximum restrictions, minimal trust radius


class PerformanceProfile(Enum):
    """CPU/AI speed profile — controls depth vs throughput tradeoff."""
    ECO = "eco"              # Minimal resource usage, shallow analysis
    BALANCED = "balanced"    # Default operating point
    TURBO = "turbo"          # Deep analysis, high throughput, more fuel


# Linked parameters per performance profile
PERFORMANCE_PRESETS = {
    PerformanceProfile.ECO: {
        "cognitive_speed": 0.5,
        "ssai_depth": "shallow",
        "fuel_multiplier": 0.5,
        "consensus_timeout_ms": 4000,
        "log_verbosity": "error",
    },
    PerformanceProfile.BALANCED: {
        "cognitive_speed": 1.0,
        "ssai_depth": "normal",
        "fuel_multiplier": 1.0,
        "consensus_timeout_ms": 2500,
        "log_verbosity": "info",
    },
    PerformanceProfile.TURBO: {
        "cognitive_speed": 2.0,
        "ssai_depth": "deep",
        "fuel_multiplier": 2.0,
        "consensus_timeout_ms": 1500,
        "log_verbosity": "debug",
    },
}

# Security posture → parameter overrides
SECURITY_PRESETS = {
    SecurityPosture.OPEN: {
        "require_signed_intents": False,
        "min_reputation": 0.0,
        "sandbox_strictness": "soft",
    },
    SecurityPosture.GUARDED: {
        "require_signed_intents": True,
        "min_reputation": 0.2,
        "sandbox_strictness": "hard",
    },
    SecurityPosture.HARDENED: {
        "require_signed_intents": True,
        "min_reputation": 0.4,
        "sandbox_strictness": "hard",
    },
    SecurityPosture.LOCKDOWN: {
        "require_signed_intents": True,
        "min_reputation": 0.6,
        "sandbox_strictness": "vm",
    },
}


class RiskLevel(Enum):
    NEGLIGIBLE = 0.0
    LOW = 0.25
    MEDIUM = 0.50
    HIGH = 0.75
    CRITICAL = 1.0
