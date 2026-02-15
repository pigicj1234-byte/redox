"""
DecisionTrace — Security Decision Trace for explainability.

Every governance decision produces a trace that can be:
  - Logged to the audit trail
  - Queried via CLI: `symbioz explain <intent_id>`
  - Replayed in FORENSIC mode for post-incident analysis
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
    risk_score: float = 0.0

    # Risk factors
    semantic_risk: float = 0.0
    behavioral_risk: float = 0.0
    actor_reputation: float = 1.0

    decision: str = "PENDING"   # APPROVED, REJECTED, QUARANTINED
    reasons: List[str] = field(default_factory=list)

    def add_reason(self, reason: str) -> None:
        self.reasons.append(reason)

    def explain(self) -> str:
        """Return structured JSON for `symbioz explain <id>` CLI command."""
        return json.dumps(
            {
                "id": self.intent_id,
                "decision": self.decision,
                "confidence": f"{(1 - self.risk_score) * 100:.1f}%",
                "context": {
                    "mode": self.mode_snapshot,
                    "timestamp": self.timestamp,
                    "reasons": self.reasons,
                },
                "metrics": {
                    "semantic_risk": self.semantic_risk,
                    "behavioral_risk": self.behavioral_risk,
                    "actor_reputation": self.actor_reputation,
                    "composite_risk": self.risk_score,
                },
            },
            indent=2,
        )

    def to_dict(self) -> dict:
        """Serialize for audit log storage."""
        return {
            "intent_id": self.intent_id,
            "timestamp": self.timestamp,
            "mode": self.mode_snapshot,
            "decision": self.decision,
            "risk_score": self.risk_score,
            "semantic_risk": self.semantic_risk,
            "behavioral_risk": self.behavioral_risk,
            "actor_reputation": self.actor_reputation,
            "reasons": self.reasons,
        }
