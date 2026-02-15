"""
GovernanceEngine — the brain of the Governance Layer (Stage 3).

Responsibilities:
  - Hot-reload runtime policy from YAML without process restart
  - Evaluate intents with weighted risk aggregation model
  - Integrate with QoS controller for adaptive throttling
  - Circuit breaker integration for subsystem isolation
  - Tamper-evident audit logging for every decision
  - Panic switch support for instant FORENSIC mode transition
  - Policy integrity hash verification
  - Produce DecisionTrace with confidence scoring for every decision
"""

import os
import logging
from typing import Optional

import yaml

from .modes import (
    OperationalMode,
    SecurityPosture,
    PerformanceProfile,
    PERFORMANCE_PRESETS,
    SECURITY_PRESETS,
)
from .policy import RuntimePolicy
from .trace import DecisionTrace
from .qos import AdaptiveQoSController, SystemMetrics, QoSAdjustment, LoadLevel
from .circuit_breaker import CircuitBreaker
from .audit import AuditChain, compute_file_hash


class GovernanceEngine:
    """Central governance controller with hot-reloadable policy.

    Integrates all Stage 3 subsystems:
      - AdaptiveQoSController (load management)
      - CircuitBreaker (failure isolation)
      - AuditChain (tamper-evident logging)
      - PanicSwitch (emergency lockdown) — checked via is_panic flag
    """

    def __init__(
        self,
        config_path: str = "config/policy.yaml",
        audit_path: str = "data/audit_chain.jsonl",
    ) -> None:
        self.config_path = config_path
        self.policy: RuntimePolicy = RuntimePolicy.default()
        self.logger = logging.getLogger("Governance")
        self._reload_count = 0
        self._policy_hash: str = ""

        # Stage 3 subsystems
        self.qos = AdaptiveQoSController()
        self.circuit_breaker = CircuitBreaker()
        self.audit = AuditChain(log_path=audit_path)

        # Last QoS adjustment (cached between evaluations)
        self._last_qos: QoSAdjustment = QoSAdjustment()

        # Register core subsystems for circuit breaking
        for subsystem in ("ssai", "consensus", "p2p", "sandbox", "audit"):
            self.circuit_breaker.register(subsystem)

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

            # Parse enums
            mode = self._parse_enum(data, "mode", OperationalMode, OperationalMode.PRODUCTION)
            security = self._parse_enum(data, "security_posture", SecurityPosture, SecurityPosture.GUARDED)
            performance = self._parse_enum(data, "performance_profile", PerformanceProfile, PerformanceProfile.BALANCED)

            defaults = RuntimePolicy.default(mode)

            self.policy = RuntimePolicy(
                mode=mode,
                security_posture=security,
                performance_profile=performance,
                cognitive_speed=float(data.get("cognitive_speed", defaults.cognitive_speed)),
                ssai_threshold=float(data.get("ssai_threshold", defaults.ssai_threshold)),
                ssai_depth=str(data.get("ssai_depth", defaults.ssai_depth)),
                quorum_ratio=float(data.get("quorum_ratio", defaults.quorum_ratio)),
                consensus_timeout_ms=int(data.get("consensus_timeout_ms", defaults.consensus_timeout_ms)),
                max_fuel_per_intent=int(data.get("max_fuel_per_intent", defaults.max_fuel_per_intent)),
                p2p_rate_limit=int(data.get("p2p_rate_limit", defaults.p2p_rate_limit)),
                require_signed_intents=bool(data.get("require_signed_intents", defaults.require_signed_intents)),
                sandbox_strictness=str(data.get("sandbox_strictness", defaults.sandbox_strictness)),
                min_reputation=float(data.get("min_reputation", defaults.min_reputation)),
                max_parallel_intents=int(data.get("max_parallel_intents", defaults.max_parallel_intents)),
                queue_backpressure_threshold=int(data.get("queue_backpressure_threshold", defaults.queue_backpressure_threshold)),
                adaptive_throttling=bool(data.get("adaptive_throttling", defaults.adaptive_throttling)),
                allow_manual_override=bool(data.get("allow_manual_override", defaults.allow_manual_override)),
                risk_weight_semantic=float(data.get("risk_weight_semantic", defaults.risk_weight_semantic)),
                risk_weight_behavioral=float(data.get("risk_weight_behavioral", defaults.risk_weight_behavioral)),
                risk_weight_reputation=float(data.get("risk_weight_reputation", defaults.risk_weight_reputation)),
            )

            # Update QoS controller with new thresholds
            self.qos.backpressure_threshold = self.policy.queue_backpressure_threshold
            self.qos.adaptive_throttling = self.policy.adaptive_throttling

            # Policy integrity hash
            new_hash = compute_file_hash(self.config_path)
            if self._policy_hash and new_hash != self._policy_hash:
                self.logger.info("Policy file changed (hash: %s...)", new_hash[:16])

            self._policy_hash = new_hash
            self._reload_count += 1

            # Audit the reload
            self.audit.log_policy_reload(
                policy_hash=new_hash,
                mode=mode.name,
            )

            self.logger.info(
                "Policy reloaded (#%d). Mode: %s, Security: %s, Profile: %s",
                self._reload_count,
                mode.name,
                security.name,
                performance.name,
            )
            return True

        except yaml.YAMLError as e:
            self.logger.error("YAML parse error in policy file: %s", e)
            return False
        except Exception as e:
            self.logger.error("Failed to reload policy: %s", e)
            return False

    def update_qos(self, metrics: SystemMetrics) -> QoSAdjustment:
        """Feed system metrics to QoS controller and cache adjustment."""
        self._last_qos = self.qos.evaluate(metrics)
        return self._last_qos

    def evaluate_intent(
        self,
        intent_data: dict,
        actor_reputation: float = 1.0,
        is_panic: bool = False,
    ) -> DecisionTrace:
        """Evaluate an intent against current policy with full Stage 3 pipeline.

        Pipeline:
          1. Panic check
          2. FORENSIC mode gate
          3. Circuit breaker check (SSAI subsystem)
          4. QoS load shedding
          5. Signature / security posture check
          6. Reputation gate (posture-aware)
          7. Semantic risk (SSAI)
          8. Behavioral risk
          9. Resource / fuel limit (QoS-adjusted)
         10. Weighted confidence aggregation
         11. Decision + audit log
        """
        trace = DecisionTrace(
            intent_id=intent_data.get("id", "unknown"),
            mode_snapshot=self.policy.mode.name,
            security_posture=self.policy.security_posture.name,
            performance_profile=self.policy.performance_profile.name,
            actor_reputation=actor_reputation,
            load_level=self._last_qos.load_level.value,
            qos_adjusted=bool(self._last_qos.reasons),
        )

        # 1. Panic override
        if is_panic:
            trace.decision = "REJECTED"
            trace.add_reason("PANIC mode active — all intents blocked")
            self._finalize(trace)
            return trace

        # 2. FORENSIC mode — read-only
        if self.policy.mode == OperationalMode.FORENSIC:
            trace.decision = "REJECTED"
            trace.add_reason("System is in FORENSIC mode (read-only)")
            self._finalize(trace)
            return trace

        # 3. Circuit breaker — is SSAI subsystem healthy?
        if not self.circuit_breaker.is_healthy("ssai"):
            trace.add_reason("SSAI circuit breaker OPEN — using fallback scoring")
            trace.semantic_risk = 0.3

        # 4. QoS load shedding
        if self._last_qos.shed_low_priority:
            priority = intent_data.get("priority", "normal")
            if priority == "low":
                trace.decision = "REJECTED"
                trace.add_reason("Load shedding: low-priority intent rejected during overload")
                self._finalize(trace)
                return trace

        # 5. Signature / security posture check
        sec_preset = SECURITY_PRESETS.get(self.policy.security_posture, {})
        require_sig = sec_preset.get("require_signed_intents", self.policy.require_signed_intents)
        if require_sig and not intent_data.get("signature"):
            trace.decision = "REJECTED"
            trace.risk_score = 1.0
            trace.add_reason(
                f"Missing signature (required by {self.policy.security_posture.name} posture)"
            )
            self._finalize(trace)
            return trace

        # 6. Reputation gate (posture-aware threshold)
        min_rep = sec_preset.get("min_reputation", self.policy.min_reputation)
        if actor_reputation < min_rep:
            trace.decision = "REJECTED"
            trace.risk_score = 0.9
            trace.add_reason(
                f"Actor reputation {actor_reputation:.2f} below "
                f"{self.policy.security_posture.name} minimum {min_rep:.2f}"
            )
            self._finalize(trace)
            return trace

        # 7. Semantic risk assessment
        if self.circuit_breaker.is_healthy("ssai"):
            semantic_risk = self._assess_semantic_risk(intent_data)
            trace.semantic_risk = semantic_risk

        # 8. Behavioral risk
        behavioral_risk = self._assess_behavioral_risk(intent_data)
        trace.behavioral_risk = behavioral_risk

        # 9. Resource / fuel limit (QoS-adjusted)
        effective_fuel = int(self.policy.max_fuel_per_intent * self._last_qos.fuel_multiplier)
        estimated_fuel = intent_data.get("fuel_estimate", 0)
        if estimated_fuel > effective_fuel:
            trace.decision = "REJECTED"
            trace.add_reason(
                f"Fuel limit exceeded ({estimated_fuel:,} > {effective_fuel:,}"
                f" [base {self.policy.max_fuel_per_intent:,} "
                f"* QoS {self._last_qos.fuel_multiplier:.2f}])"
            )
            self._finalize(trace)
            return trace

        # 10. Weighted confidence aggregation
        trace.compute_confidence(
            w_semantic=self.policy.risk_weight_semantic,
            w_behavioral=self.policy.risk_weight_behavioral,
            w_reputation=self.policy.risk_weight_reputation,
            quorum_score=1.0,  # Would come from actual consensus module
        )

        # Decision based on confidence
        if trace.confidence_score >= 0.7:
            trace.decision = "APPROVED"
        elif trace.confidence_score >= 0.4:
            trace.decision = "QUARANTINED"
            trace.add_reason(
                f"Confidence {trace.confidence_score:.2f} — quarantined for review"
            )
        else:
            trace.decision = "REJECTED"
            trace.add_reason(
                f"Confidence {trace.confidence_score:.2f} below threshold"
            )

        self._finalize(trace)
        return trace

    def manual_override(
        self,
        trace: DecisionTrace,
        operator: str,
        new_decision: str,
        justification: str,
    ) -> DecisionTrace:
        """Apply human override to a decision (human-in-the-loop)."""
        if not self.policy.allow_manual_override:
            self.logger.warning(
                "Manual override rejected — not allowed in %s mode",
                self.policy.mode.name,
            )
            return trace

        trace.apply_override(operator, new_decision, justification)
        self.audit.log_manual_override(operator, new_decision, justification)
        self.logger.info(
            "Manual override: %s -> %s by %s",
            trace.intent_id, new_decision, operator,
        )
        return trace

    def _finalize(self, trace: DecisionTrace) -> None:
        """Finalize a decision: compute confidence if needed, log to audit."""
        if trace.confidence_score == 0.0 and trace.decision != "PENDING":
            trace.compute_confidence(
                w_semantic=self.policy.risk_weight_semantic,
                w_behavioral=self.policy.risk_weight_behavioral,
                w_reputation=self.policy.risk_weight_reputation,
            )
        self.audit.log_decision(trace.to_dict())

    def _assess_semantic_risk(self, intent_data: dict) -> float:
        """Assess semantic risk of an intent (SSAI integration point)."""
        risk = 0.0

        action = intent_data.get("action", "")
        high_risk_actions = {"delete", "drop", "kill", "override", "bypass"}
        if action.lower() in high_risk_actions:
            risk += 0.5

        if intent_data.get("requires_admin", False):
            risk += 0.2

        if not intent_data.get("scope"):
            risk += 0.1

        self.circuit_breaker.record_success("ssai")
        return min(risk, 1.0)

    def _assess_behavioral_risk(self, intent_data: dict) -> float:
        """Assess behavioral risk based on intent patterns."""
        risk = 0.0

        if intent_data.get("burst_count", 0) > 10:
            risk += 0.4

        if intent_data.get("off_hours", False):
            risk += 0.2

        return min(risk, 1.0)

    def _parse_enum(self, data: dict, key: str, enum_cls, default):
        """Parse an enum value from YAML data with error handling."""
        raw = data.get(key, default.value if hasattr(default, "value") else str(default))
        try:
            return enum_cls[str(raw).upper()]
        except KeyError:
            self.logger.error(
                "Unknown %s '%s'. Valid: %s",
                key, raw, [m.name for m in enum_cls],
            )
            return default

    @property
    def current_mode(self) -> OperationalMode:
        return self.policy.mode

    @property
    def current_security(self) -> SecurityPosture:
        return self.policy.security_posture

    @property
    def current_performance(self) -> PerformanceProfile:
        return self.policy.performance_profile

    @property
    def reload_count(self) -> int:
        return self._reload_count

    @property
    def policy_hash(self) -> str:
        return self._policy_hash

    def status(self) -> dict:
        """Full engine status for monitoring/dashboard."""
        return {
            "mode": self.policy.mode.name,
            "security_posture": self.policy.security_posture.name,
            "performance_profile": self.policy.performance_profile.name,
            "policy_hash": self._policy_hash[:16] + "..." if self._policy_hash else "none",
            "reload_count": self._reload_count,
            "qos": {
                "load_level": self._last_qos.load_level.value,
                "speed_multiplier": self._last_qos.speed_multiplier,
                "fuel_multiplier": self._last_qos.fuel_multiplier,
                "shedding": self._last_qos.shed_low_priority,
            },
            "circuit_breakers": self.circuit_breaker.get_all_status(),
            "audit_chain_length": self.audit.length,
        }
