"""
DecisionTrace — Security Decision Trace for explainability.

Every governance decision produces a trace that can be:
  - Logged to the tamper-evident audit chain
  - Queried via CLI: `symbioz explain <intent_id>`
  - Replayed in FORENSIC mode for post-incident analysis

Stage 3 additions:
  - Weighted confidence aggregation
  - Recommended action field
  - Uncertainty metric
  - QoS context (load level at decision time)
  - Human override tracking
"""

import json
import time
from dataclasses import dataclass, field
from typing import List


@dataclass
class DecisionTrace:
    intent_id: str
    timestamp: float = field(default_factory=time.time)
    mode_snapshot: str = "unknown"
    security_posture: str = "unknown"
    performance_profile: str = "unknown"
    risk_score: float = 0.0

    # Risk factors
    semantic_risk: float = 0.0
    behavioral_risk: float = 0.0
    actor_reputation: float = 1.0

    # Weighted confidence (Stage 3)
    confidence_score: float = 0.0   # Aggregated confidence (0.0-1.0)
    uncertainty: float = 0.0        # How uncertain the decision is
    recommended_action: str = ""    # "safe_execution", "monitor", "manual_review", "block"

    # QoS context
    load_level: str = "unknown"     # From QoS controller at decision time
    qos_adjusted: bool = False      # Whether QoS throttling was active

    decision: str = "PENDING"       # APPROVED, REJECTED, QUARANTINED
    reasons: List[str] = field(default_factory=list)

    # Human override tracking
    overridden: bool = False
    override_by: str = ""
    override_justification: str = ""

    def add_reason(self, reason: str) -> None:
        self.reasons.append(reason)

    def compute_confidence(
        self,
        w_semantic: float = 0.5,
        w_behavioral: float = 0.3,
        w_reputation: float = 0.2,
        quorum_score: float = 1.0,
    ) -> None:
        """Compute weighted confidence score from risk factors.

        confidence = weighted_sum * quorum_factor
        uncertainty = spread between risk factors (std dev)
        """
        weighted_risk = (
            w_semantic * self.semantic_risk
            + w_behavioral * self.behavioral_risk
            + w_reputation * (1.0 - self.actor_reputation)
        )
        self.risk_score = min(max(weighted_risk, 0.0), 1.0)
        self.confidence_score = (1.0 - self.risk_score) * quorum_score

        # Uncertainty = standard deviation of risk factors
        factors = [self.semantic_risk, self.behavioral_risk, 1.0 - self.actor_reputation]
        mean = sum(factors) / len(factors)
        variance = sum((f - mean) ** 2 for f in factors) / len(factors)
        self.uncertainty = variance ** 0.5

        # Recommended action based on confidence
        if self.confidence_score >= 0.8:
            self.recommended_action = "safe_execution"
        elif self.confidence_score >= 0.6:
            self.recommended_action = "monitor"
        elif self.confidence_score >= 0.4:
            self.recommended_action = "manual_review"
        else:
            self.recommended_action = "block"

    def apply_override(self, operator: str, new_decision: str, justification: str) -> None:
        """Record a human override of this decision."""
        self.overridden = True
        self.override_by = operator
        self.override_justification = justification
        self.decision = new_decision
        self.add_reason(f"HUMAN OVERRIDE by {operator}: {justification}")

    def explain(self) -> str:
        """Return structured JSON for `symbioz explain <id>` CLI command."""
        result = {
            "id": self.intent_id,
            "decision": self.decision,
            "confidence": f"{self.confidence_score * 100:.1f}%",
            "uncertainty": f"{self.uncertainty:.3f}",
            "recommended_action": self.recommended_action,
            "context": {
                "mode": self.mode_snapshot,
                "security_posture": self.security_posture,
                "performance_profile": self.performance_profile,
                "load_level": self.load_level,
                "qos_adjusted": self.qos_adjusted,
                "timestamp": self.timestamp,
                "reasons": self.reasons,
            },
            "metrics": {
                "semantic_risk": self.semantic_risk,
                "behavioral_risk": self.behavioral_risk,
                "actor_reputation": self.actor_reputation,
                "composite_risk": self.risk_score,
                "confidence_score": self.confidence_score,
            },
        }
        if self.overridden:
            result["override"] = {
                "by": self.override_by,
                "justification": self.override_justification,
            }
        return json.dumps(result, indent=2)

    def to_dict(self) -> dict:
        """Serialize for audit log storage."""
        return {
            "intent_id": self.intent_id,
            "timestamp": self.timestamp,
            "mode": self.mode_snapshot,
            "security_posture": self.security_posture,
            "performance_profile": self.performance_profile,
            "decision": self.decision,
            "risk_score": self.risk_score,
            "confidence_score": self.confidence_score,
            "uncertainty": self.uncertainty,
            "recommended_action": self.recommended_action,
            "semantic_risk": self.semantic_risk,
            "behavioral_risk": self.behavioral_risk,
            "actor_reputation": self.actor_reputation,
            "load_level": self.load_level,
            "qos_adjusted": self.qos_adjusted,
            "overridden": self.overridden,
            "override_by": self.override_by,
            "reasons": self.reasons,
        }
