"""
RuntimePolicy — typed configuration structure for the Governance Engine.

Eliminates magic numbers from code. Every threshold, limit, and mode
parameter is declared here with strict typing and sensible defaults
per operational mode.

Stage 3 additions:
  - SecurityPosture (independent from OperationalMode)
  - PerformanceProfile (linked parameter sets)
  - QoS parameters (backpressure, adaptive throttling)
  - Human override controls
  - Weighted risk aggregation model
"""

from dataclasses import dataclass
from .modes import OperationalMode, SecurityPosture, PerformanceProfile


@dataclass(frozen=True)
class RuntimePolicy:
    # --- Core axes ---
    mode: OperationalMode
    security_posture: SecurityPosture
    performance_profile: PerformanceProfile

    # --- Service quality ---
    cognitive_speed: float              # 0.5 (low power) to 4.0 (stress)

    # --- Consensus & SSAI ---
    ssai_threshold: float               # Min confidence for auto-decision (0.0-1.0)
    ssai_depth: str                     # "shallow", "normal", "deep"
    quorum_ratio: float                 # Required % of nodes (0.51, 0.67, 0.90...)
    consensus_timeout_ms: int           # Max wait for consensus

    # --- Resource governor ---
    max_fuel_per_intent: int            # Computation limit (Wasm fuel units)
    p2p_rate_limit: int                 # Requests/sec per peer

    # --- Security ---
    require_signed_intents: bool        # Reject unsigned intents
    sandbox_strictness: str             # 'soft', 'hard', 'vm'
    min_reputation: float               # Minimum actor reputation (0.0-1.0)

    # --- QoS ---
    max_parallel_intents: int           # Concurrency limit
    queue_backpressure_threshold: int   # Queue depth before throttling
    adaptive_throttling: bool           # Auto-reduce speed under load

    # --- Human override ---
    allow_manual_override: bool         # Permit human-in-the-loop decisions

    # --- Risk weights (weighted aggregation model) ---
    risk_weight_semantic: float         # Weight for semantic risk
    risk_weight_behavioral: float       # Weight for behavioral risk
    risk_weight_reputation: float       # Weight for (1 - reputation)

    @classmethod
    def default(cls, mode: OperationalMode = OperationalMode.PRODUCTION) -> "RuntimePolicy":
        """Create a policy with sensible defaults for the given mode."""
        presets = {
            OperationalMode.DEVELOPMENT: cls(
                mode=mode,
                security_posture=SecurityPosture.OPEN,
                performance_profile=PerformanceProfile.TURBO,
                cognitive_speed=1.0,
                ssai_threshold=0.4,
                ssai_depth="normal",
                quorum_ratio=0.51,
                consensus_timeout_ms=5000,
                max_fuel_per_intent=1_000_000,
                p2p_rate_limit=1000,
                require_signed_intents=False,
                sandbox_strictness="soft",
                min_reputation=0.0,
                max_parallel_intents=50,
                queue_backpressure_threshold=200,
                adaptive_throttling=False,
                allow_manual_override=True,
                risk_weight_semantic=0.5,
                risk_weight_behavioral=0.3,
                risk_weight_reputation=0.2,
            ),
            OperationalMode.PRODUCTION: cls(
                mode=mode,
                security_posture=SecurityPosture.GUARDED,
                performance_profile=PerformanceProfile.BALANCED,
                cognitive_speed=1.0,
                ssai_threshold=0.6,
                ssai_depth="normal",
                quorum_ratio=0.67,
                consensus_timeout_ms=3000,
                max_fuel_per_intent=500_000,
                p2p_rate_limit=100,
                require_signed_intents=True,
                sandbox_strictness="hard",
                min_reputation=0.2,
                max_parallel_intents=20,
                queue_backpressure_threshold=100,
                adaptive_throttling=True,
                allow_manual_override=True,
                risk_weight_semantic=0.5,
                risk_weight_behavioral=0.3,
                risk_weight_reputation=0.2,
            ),
            OperationalMode.PARANOID: cls(
                mode=mode,
                security_posture=SecurityPosture.LOCKDOWN,
                performance_profile=PerformanceProfile.BALANCED,
                cognitive_speed=2.0,
                ssai_threshold=0.85,
                ssai_depth="deep",
                quorum_ratio=0.90,
                consensus_timeout_ms=2000,
                max_fuel_per_intent=50_000,
                p2p_rate_limit=10,
                require_signed_intents=True,
                sandbox_strictness="vm",
                min_reputation=0.5,
                max_parallel_intents=5,
                queue_backpressure_threshold=20,
                adaptive_throttling=True,
                allow_manual_override=False,
                risk_weight_semantic=0.6,
                risk_weight_behavioral=0.25,
                risk_weight_reputation=0.15,
            ),
            OperationalMode.FORENSIC: cls(
                mode=mode,
                security_posture=SecurityPosture.LOCKDOWN,
                performance_profile=PerformanceProfile.ECO,
                cognitive_speed=0.5,
                ssai_threshold=0.95,
                ssai_depth="deep",
                quorum_ratio=1.0,
                consensus_timeout_ms=10000,
                max_fuel_per_intent=0,
                p2p_rate_limit=5,
                require_signed_intents=True,
                sandbox_strictness="vm",
                min_reputation=0.8,
                max_parallel_intents=1,
                queue_backpressure_threshold=5,
                adaptive_throttling=False,
                allow_manual_override=True,
                risk_weight_semantic=0.5,
                risk_weight_behavioral=0.3,
                risk_weight_reputation=0.2,
            ),
        }
        return presets.get(mode, presets[OperationalMode.PRODUCTION])
