"""
Symbioz Pro Governance Layer (Stage 3 — Adaptive System)

Runtime policy management, decision tracing, operational mode control,
adaptive QoS, circuit breaking, and tamper-evident audit logging.

Usage:
    from src.core.governance.engine import GovernanceEngine

    governor = GovernanceEngine("config/policy.yaml")
    trace = governor.evaluate_intent(intent_data, actor_reputation=0.8)
    print(trace.explain())
    print(governor.status())
"""

from .modes import (
    OperationalMode,
    SecurityPosture,
    PerformanceProfile,
    RiskLevel,
    PERFORMANCE_PRESETS,
    SECURITY_PRESETS,
)
from .policy import RuntimePolicy
from .trace import DecisionTrace
from .engine import GovernanceEngine
from .qos import AdaptiveQoSController, SystemMetrics, QoSAdjustment, LoadLevel
from .circuit_breaker import CircuitBreaker, BreakerState
from .audit import AuditChain, AuditEntry, compute_file_hash
from .feedback import FeedbackLoop, FeedbackAction, FeedbackConfig, FeedbackState

__all__ = [
    # Core
    "OperationalMode",
    "SecurityPosture",
    "PerformanceProfile",
    "RiskLevel",
    "PERFORMANCE_PRESETS",
    "SECURITY_PRESETS",
    "RuntimePolicy",
    "DecisionTrace",
    "GovernanceEngine",
    # QoS
    "AdaptiveQoSController",
    "SystemMetrics",
    "QoSAdjustment",
    "LoadLevel",
    # Circuit Breaker
    "CircuitBreaker",
    "BreakerState",
    # Audit
    "AuditChain",
    "AuditEntry",
    "compute_file_hash",
    # Feedback Loop
    "FeedbackLoop",
    "FeedbackAction",
    "FeedbackConfig",
    "FeedbackState",
]
