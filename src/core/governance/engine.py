"""
GovernanceEngine — the brain of the Governance Layer.

Responsibilities:
  - Hot-reload runtime policy from YAML without process restart
  - Evaluate intents against current policy (security, resources, reputation)
  - Produce DecisionTrace for every decision (explainability)
  - Enforce operational mode constraints (FORENSIC = read-only, etc.)
"""

import os
import logging
from typing import Optional

import yaml

from .modes import OperationalMode, RiskLevel
from .policy import RuntimePolicy
from .trace import DecisionTrace


class GovernanceEngine:
    """Central governance controller with hot-reloadable policy."""

    def __init__(self, config_path: str = "config/policy.yaml") -> None:
        self.config_path = config_path
        self.policy: RuntimePolicy = RuntimePolicy.default()
        self.logger = logging.getLogger("Governance")
        self._reload_count = 0
        self.reload_policy()

    def reload_policy(self) -> bool:
        """Hot-reload policy from YAML. Returns True on success."""
        if not os.path.exists(self.config_path):
            self.logger.warning(
                "No policy file at %s, using defaults (%s).",
                self.config_path,
                self.policy.mode.name,
            )
            return False

        try:
            with open(self.config_path, "r") as f:
                data = yaml.safe_load(f)

            if not isinstance(data, dict):
                self.logger.error("Policy file is not a valid YAML mapping.")
                return False

            mode_str = data.get("mode", "production").upper()
            try:
                mode = OperationalMode[mode_str]
            except KeyError:
                self.logger.error(
                    "Unknown mode '%s'. Valid: %s",
                    mode_str,
                    [m.name for m in OperationalMode],
                )
                return False

            # Build policy from file, falling back to mode defaults
            defaults = RuntimePolicy.default(mode)
            self.policy = RuntimePolicy(
                mode=mode,
                cognitive_speed=float(data.get("cognitive_speed", defaults.cognitive_speed)),
                ssai_threshold=float(data.get("ssai_threshold", defaults.ssai_threshold)),
                quorum_ratio=float(data.get("quorum_ratio", defaults.quorum_ratio)),
                consensus_timeout_ms=int(data.get("consensus_timeout_ms", defaults.consensus_timeout_ms)),
                max_fuel_per_intent=int(data.get("max_fuel_per_intent", defaults.max_fuel_per_intent)),
                p2p_rate_limit=int(data.get("p2p_rate_limit", defaults.p2p_rate_limit)),
                require_signed_intents=bool(data.get("require_signed_intents", defaults.require_signed_intents)),
                sandbox_strictness=str(data.get("sandbox_strictness", defaults.sandbox_strictness)),
            )

            self._reload_count += 1
            self.logger.info(
                "Policy reloaded (#%d). Mode: %s, SSAI: %.2f, Quorum: %.2f",
                self._reload_count,
                mode.name,
                self.policy.ssai_threshold,
                self.policy.quorum_ratio,
            )
            return True

        except yaml.YAMLError as e:
            self.logger.error("YAML parse error in policy file: %s", e)
            return False
        except Exception as e:
            self.logger.error("Failed to reload policy: %s", e)
            return False

    def evaluate_intent(
        self,
        intent_data: dict,
        actor_reputation: float = 1.0,
    ) -> DecisionTrace:
        """Evaluate an intent against current policy. Always returns a DecisionTrace."""
        trace = DecisionTrace(
            intent_id=intent_data.get("id", "unknown"),
            mode_snapshot=self.policy.mode.name,
            actor_reputation=actor_reputation,
        )

        # 1. FORENSIC mode — read-only, reject all mutations
        if self.policy.mode == OperationalMode.FORENSIC:
            trace.decision = "REJECTED"
            trace.add_reason("System is in FORENSIC mode (read-only)")
            return trace

        # 2. Signature requirement
        if self.policy.require_signed_intents and not intent_data.get("signature"):
            trace.decision = "REJECTED"
            trace.risk_score = 1.0
            trace.add_reason(
                f"Missing signature (required in {self.policy.mode.name} mode)"
            )
            return trace

        # 3. Actor reputation gate
        min_reputation = 0.2
        if actor_reputation < min_reputation:
            trace.decision = "REJECTED"
            trace.risk_score = 0.9
            trace.add_reason(
                f"Actor reputation {actor_reputation:.2f} below minimum {min_reputation}"
            )
            return trace

        # 4. Semantic risk assessment (SSAI integration point)
        semantic_risk = self._assess_semantic_risk(intent_data)
        trace.semantic_risk = semantic_risk

        risk_threshold = 1.0 - self.policy.ssai_threshold
        if semantic_risk > risk_threshold:
            trace.add_reason(
                f"Semantic risk {semantic_risk:.2f} exceeds threshold {risk_threshold:.2f}"
            )
            trace.risk_score += 0.4

        # 5. Behavioral risk (pattern-based)
        behavioral_risk = self._assess_behavioral_risk(intent_data)
        trace.behavioral_risk = behavioral_risk
        if behavioral_risk > 0.5:
            trace.add_reason(f"Behavioral anomaly detected (score: {behavioral_risk:.2f})")
            trace.risk_score += 0.3

        # 6. Resource / fuel limit
        estimated_fuel = intent_data.get("fuel_estimate", 0)
        if estimated_fuel > self.policy.max_fuel_per_intent:
            trace.decision = "REJECTED"
            trace.add_reason(
                f"Fuel limit exceeded ({estimated_fuel:,} > {self.policy.max_fuel_per_intent:,})"
            )
            return trace

        # 7. Composite risk decision
        trace.risk_score = min(trace.risk_score, 1.0)

        if trace.risk_score > 0.7:
            trace.decision = "REJECTED"
            trace.add_reason(f"Composite risk {trace.risk_score:.2f} too high")
        elif trace.risk_score > 0.5:
            trace.decision = "QUARANTINED"
            trace.add_reason(
                f"Composite risk {trace.risk_score:.2f} — quarantined for review"
            )
        else:
            trace.decision = "APPROVED"

        return trace

    def _assess_semantic_risk(self, intent_data: dict) -> float:
        """Assess semantic risk of an intent.

        This is the integration point for the SSAI module.
        Current implementation uses heuristic scoring.
        """
        risk = 0.0

        # Check for dangerous action types
        action = intent_data.get("action", "")
        high_risk_actions = {"delete", "drop", "kill", "override", "bypass"}
        if action.lower() in high_risk_actions:
            risk += 0.5

        # Privilege escalation indicator
        if intent_data.get("requires_admin", False):
            risk += 0.2

        # Unknown scope
        if not intent_data.get("scope"):
            risk += 0.1

        return min(risk, 1.0)

    def _assess_behavioral_risk(self, intent_data: dict) -> float:
        """Assess behavioral risk based on intent patterns.

        Future: integrate with historical pattern analysis.
        """
        risk = 0.0

        # Rapid-fire detection (would need state tracking in production)
        if intent_data.get("burst_count", 0) > 10:
            risk += 0.4

        # Off-hours flag
        if intent_data.get("off_hours", False):
            risk += 0.2

        return min(risk, 1.0)

    @property
    def current_mode(self) -> OperationalMode:
        return self.policy.mode

    @property
    def reload_count(self) -> int:
        return self._reload_count
