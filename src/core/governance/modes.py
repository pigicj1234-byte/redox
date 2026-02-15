"""
Operational modes and risk levels for Symbioz Governance.

OperationalMode is the system's "gear shift":
  - DEVELOPMENT: max logging, auto-replay, relaxed thresholds
  - PRODUCTION:  strict invariants, rate-limiting, signed intents
  - PARANOID:    high consensus quorum, VM sandbox, minimal trust
  - FORENSIC:   read-only, deep analysis, replay-only
"""

from enum import Enum


class OperationalMode(Enum):
    DEVELOPMENT = "development"
    PRODUCTION = "production"
    PARANOID = "paranoid"
    FORENSIC = "forensic"


class RiskLevel(Enum):
    NEGLIGIBLE = 0.0
    LOW = 0.25
    MEDIUM = 0.50
    HIGH = 0.75
    CRITICAL = 1.0
