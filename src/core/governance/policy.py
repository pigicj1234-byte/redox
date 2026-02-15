"""
RuntimePolicy — typed configuration structure for the Governance Engine.

Eliminates magic numbers from code. Every threshold, limit, and mode
parameter is declared here with strict typing and sensible defaults
per operational mode.
"""

from dataclasses import dataclass
from .modes import OperationalMode


@dataclass(frozen=True)
class RuntimePolicy:
    # Operational mode
    mode: OperationalMode

    # Service quality
    cognitive_speed: float          # 0.5 (low power) to 4.0 (stress)

    # Consensus & SSAI
    ssai_threshold: float           # Min confidence for auto-decision (0.0-1.0)
    quorum_ratio: float             # Required % of nodes (0.51, 0.67, 0.90...)
    consensus_timeout_ms: int       # Max wait for consensus

    # Resource governor
    max_fuel_per_intent: int        # Computation limit (Wasm fuel units)
    p2p_rate_limit: int             # Requests/sec per peer

    # Security
    require_signed_intents: bool    # Reject unsigned intents
    sandbox_strictness: str         # 'soft', 'hard', 'vm'

    @classmethod
    def default(cls, mode: OperationalMode = OperationalMode.PRODUCTION) -> "RuntimePolicy":
        """Create a policy with sensible defaults for the given mode."""
        presets = {
            OperationalMode.DEVELOPMENT: cls(
                mode=mode,
                cognitive_speed=1.0,
                ssai_threshold=0.4,
                quorum_ratio=0.51,
                consensus_timeout_ms=5000,
                max_fuel_per_intent=1_000_000,
                p2p_rate_limit=1000,
                require_signed_intents=False,
                sandbox_strictness="soft",
            ),
            OperationalMode.PRODUCTION: cls(
                mode=mode,
                cognitive_speed=1.0,
                ssai_threshold=0.6,
                quorum_ratio=0.67,
                consensus_timeout_ms=3000,
                max_fuel_per_intent=500_000,
                p2p_rate_limit=100,
                require_signed_intents=True,
                sandbox_strictness="hard",
            ),
            OperationalMode.PARANOID: cls(
                mode=mode,
                cognitive_speed=2.0,
                ssai_threshold=0.85,
                quorum_ratio=0.90,
                consensus_timeout_ms=2000,
                max_fuel_per_intent=50_000,
                p2p_rate_limit=10,
                require_signed_intents=True,
                sandbox_strictness="vm",
            ),
            OperationalMode.FORENSIC: cls(
                mode=mode,
                cognitive_speed=0.5,
                ssai_threshold=0.95,
                quorum_ratio=1.0,
                consensus_timeout_ms=10000,
                max_fuel_per_intent=0,
                p2p_rate_limit=5,
                require_signed_intents=True,
                sandbox_strictness="vm",
            ),
        }
        return presets.get(mode, presets[OperationalMode.PRODUCTION])
