#!/usr/bin/env python3
"""
Symbioz Governance — Stage 3 Test Suite.

28 tests covering:
  - EMATracker: streaming statistics, z-score, warmup
  - Engine: update_axes atomic policy swap
  - Percentiles: reservoir sampling p95
  - Collector: MetricsCollector EMA/percentile/gauge/event integration
  - FeedbackLoop: adaptive control (ECO/BALANCED/LOCKDOWN/GUARDED)
  - Integration: full pipeline GovernanceEngine + FeedbackLoop

Run: python tests/test_feedback.py
  or: PYTHONPATH=. python tests/test_feedback.py
"""

import os
import sys
import time
import tempfile
import random

# Ensure imports work from repo root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.core.governance.feedback import (
    EMATracker, FeedbackLoop, FeedbackConfig, FeedbackAction, EpochRecord,
)
from src.core.governance.modes import (
    OperationalMode, SecurityPosture, PerformanceProfile,
)
from src.core.governance.audit import AuditChain
from src.core.observability.metrics import MetricsCollector, ReservoirSampler

# ---------------------------------------------------------------------------
# Minimal test runner
# ---------------------------------------------------------------------------

_passed = 0
_failed = 0


def section(name):
    print(f"=== {name} ===")


def test(name, fn):
    global _passed, _failed
    try:
        fn()
        print(f"  \u2713 {name}")
        _passed += 1
    except Exception as e:
        print(f"  \u2717 {name}: {e}")
        _failed += 1


# ===========================================================================
# EMATracker
# ===========================================================================
section("EMATracker")


def _ema_init():
    t = EMATracker(alpha=0.1, warmup=5)
    assert t.mean == 0.0
    assert t.count == 0
    assert not t.is_warm

test("init", _ema_init)


def _ema_converge():
    t = EMATracker(alpha=0.3, warmup=5)
    for _ in range(100):
        t.update(42.0)
    assert abs(t.mean - 42.0) < 0.01

test("converge", _ema_converge)


def _ema_smooth_spike():
    t = EMATracker(alpha=0.1, warmup=5)
    for _ in range(30):
        t.update(100.0)
    baseline = t.mean
    t.update(10000.0)
    # EMA smooths: should not jump to 10000
    assert t.mean < 1200.0
    assert t.mean > baseline

test("smooth_spike", _ema_smooth_spike)


def _ema_zscore_cold():
    t = EMATracker(alpha=0.1, warmup=20)
    for _ in range(15):
        t.update(100.0)
    # Not warm yet → z-score must return 0
    assert t.zscore(9999.0) == 0.0

test("zscore_cold", _ema_zscore_cold)


def _ema_zscore_anomaly():
    # Need varied samples so variance > 0
    t = EMATracker(alpha=0.1, warmup=10)
    rng = random.Random(42)
    for _ in range(30):
        t.update(100.0 + rng.gauss(0, 15))
    z = t.zscore(300.0)
    assert z > 2.0, f"expected z > 2.0, got {z}"

test("zscore_anomaly", _ema_zscore_anomaly)


def _ema_not_warm():
    t = EMATracker(warmup=10)
    for _ in range(5):
        t.update(1.0)
    assert not t.is_warm

test("not_warm", _ema_not_warm)


def _ema_warm():
    t = EMATracker(warmup=10)
    for _ in range(10):
        t.update(1.0)
    assert t.is_warm

test("warm", _ema_warm)


# ===========================================================================
# Engine — update_axes
# ===========================================================================
section("Engine")


def _make_engine():
    """Create a GovernanceEngine with a temp policy file."""
    import yaml
    tmpdir = tempfile.mkdtemp()
    policy_path = os.path.join(tmpdir, "policy.yaml")
    audit_path = os.path.join(tmpdir, "audit.jsonl")
    with open(policy_path, "w") as f:
        yaml.dump({
            "mode": "production",
            "security_posture": "guarded",
            "performance_profile": "balanced",
        }, f)
    from src.core.governance.engine import GovernanceEngine
    return GovernanceEngine(config_path=policy_path, audit_path=audit_path)


def _engine_multi():
    gov = _make_engine()
    assert gov.policy.performance_profile == PerformanceProfile.BALANCED
    assert gov.policy.security_posture == SecurityPosture.GUARDED

    gov.update_axes(
        performance=PerformanceProfile.ECO,
        security=SecurityPosture.LOCKDOWN,
        reason="test multi-axis update",
    )
    assert gov.policy.performance_profile == PerformanceProfile.ECO
    assert gov.policy.security_posture == SecurityPosture.LOCKDOWN
    # ECO preset should change cognitive_speed
    assert gov.policy.cognitive_speed == 0.5

test("multi", _engine_multi)


def _engine_none():
    gov = _make_engine()
    old_policy = gov.policy
    gov.update_axes()  # No changes
    assert gov.policy is old_policy  # Same object, not replaced

test("none", _engine_none)


# ===========================================================================
# Percentiles — ReservoirSampler
# ===========================================================================
section("Percentiles")


def _percentile_p95():
    r = ReservoirSampler(capacity=10000)
    # Insert 1..1000
    for i in range(1, 1001):
        r.add(float(i))
    p95 = r.p95()
    # p95 of 1..1000 should be around 950
    assert 940.0 <= p95 <= 960.0, f"expected ~950, got {p95}"

test("p95", _percentile_p95)


# ===========================================================================
# Collector — MetricsCollector
# ===========================================================================
section("Collector")


def _collector_ema():
    mc = MetricsCollector()
    for _ in range(20):
        mc.observe("lat", 100.0)
    avg = mc.get_histogram_avg("lat", window_s=9999)
    assert avg is not None
    assert abs(avg - 100.0) < 1.0

test("ema", _collector_ema)


def _collector_pct():
    mc = MetricsCollector()
    for i in range(1, 101):
        mc.observe("lat", float(i))
    p95 = mc.get_p95("lat")
    assert p95 >= 90.0, f"expected p95 >= 90, got {p95}"

test("pct", _collector_pct)


def _collector_gauge():
    mc = MetricsCollector()
    mc.set_gauge("cpu", 0.75)
    assert mc.get_gauge("cpu") == 0.75
    mc.set_gauge("cpu", 0.50)
    assert mc.get_gauge("cpu") == 0.50

test("gauge", _collector_gauge)


def _collector_event():
    mc = MetricsCollector()
    mc.record_event("deploy", {"version": "3.0"})
    mc.record_event("restart", {})
    events = mc.get_recent_events()
    assert len(events) == 2
    assert events[0].name == "deploy"

test("event", _collector_event)


# ===========================================================================
# FeedbackLoop
# ===========================================================================
section("FeedbackLoop")


def _make_loop(cooldown=0.0, min_obs=5, **kw):
    mc = MetricsCollector()
    cfg = FeedbackConfig(cooldown_s=cooldown, min_observations=min_obs, **kw)
    return FeedbackLoop(metrics=mc, config=cfg), mc


def _fb_cold():
    fl, _ = _make_loop(min_obs=100)
    for _ in range(10):
        fl.observe(100.0, False)
    # Not enough observations → None
    action = fl.evaluate(PerformanceProfile.BALANCED, SecurityPosture.GUARDED, 0.5)
    assert action is None

test("cold", _fb_cold)


def _fb_eco():
    fl, _ = _make_loop()
    # Feed high-latency data
    for _ in range(30):
        fl.observe(3000.0, False)
    action = fl.evaluate(PerformanceProfile.BALANCED, SecurityPosture.GUARDED, 0.90)
    assert action is not None
    assert action.performance == PerformanceProfile.ECO
    assert action.name == "performance_downshift"

test("eco", _fb_eco)


def _fb_recovery():
    fl, _ = _make_loop(ema_alpha=0.3, ema_warmup=5)
    # Phase 1: overload
    for _ in range(20):
        fl.observe(3000.0, False)
    action = fl.evaluate(PerformanceProfile.BALANCED, SecurityPosture.GUARDED, 0.90)
    assert action is not None and action.performance == PerformanceProfile.ECO

    # Phase 2: recovery (many low-latency samples, EMA decays)
    for _ in range(80):
        fl.observe(100.0, False)
    action = fl.evaluate(PerformanceProfile.ECO, SecurityPosture.GUARDED, 0.10)
    assert action is not None
    assert action.performance == PerformanceProfile.BALANCED
    assert action.name == "performance_upshift"

test("recovery", _fb_recovery)


def _fb_cpu_no_eco():
    fl, _ = _make_loop()
    for _ in range(20):
        fl.observe(100.0, False)
    # High CPU but already ECO → no action
    action = fl.evaluate(PerformanceProfile.ECO, SecurityPosture.GUARDED, 0.95)
    assert action is None

test("cpu_no_eco", _fb_cpu_no_eco)


def _fb_lockdown():
    fl, _ = _make_loop(ema_alpha=0.5, ema_warmup=3)
    # Feed mostly rejected intents
    for _ in range(20):
        fl.observe(100.0, True)
    action = fl.evaluate(PerformanceProfile.BALANCED, SecurityPosture.GUARDED, 0.30)
    assert action is not None
    assert action.security == SecurityPosture.LOCKDOWN
    assert action.name == "security_lockdown"

test("lockdown", _fb_lockdown)


def _fb_guarded():
    fl, _ = _make_loop(ema_alpha=0.3, ema_warmup=3)
    # Phase 1: lockdown trigger
    for _ in range(15):
        fl.observe(100.0, True)
    action = fl.evaluate(PerformanceProfile.BALANCED, SecurityPosture.GUARDED, 0.30)
    assert action is not None and action.security == SecurityPosture.LOCKDOWN

    # Phase 2: recovery (many approved)
    for _ in range(80):
        fl.observe(100.0, False)
    action = fl.evaluate(PerformanceProfile.BALANCED, SecurityPosture.LOCKDOWN, 0.30)
    assert action is not None
    assert action.security == SecurityPosture.GUARDED
    assert action.name == "security_recovery"

test("guarded", _fb_guarded)


def _fb_cooldown_first():
    # First evaluation should NOT be blocked by cooldown
    fl, _ = _make_loop(cooldown=9999.0, min_obs=5)
    for _ in range(10):
        fl.observe(3000.0, False)
    action = fl.evaluate(PerformanceProfile.BALANCED, SecurityPosture.GUARDED, 0.95)
    assert action is not None, "first eval should not be blocked by cooldown"
    assert action.performance == PerformanceProfile.ECO

test("cooldown_first", _fb_cooldown_first)


def _fb_cooldown_block():
    fl, _ = _make_loop(cooldown=9999.0, min_obs=5)
    for _ in range(10):
        fl.observe(3000.0, False)
    # First eval: passes
    a1 = fl.evaluate(PerformanceProfile.BALANCED, SecurityPosture.GUARDED, 0.95)
    assert a1 is not None
    # Second eval: blocked by cooldown
    for _ in range(10):
        fl.observe(3000.0, False)
    a2 = fl.evaluate(PerformanceProfile.BALANCED, SecurityPosture.GUARDED, 0.95)
    assert a2 is None, "second eval should be blocked by cooldown"

test("cooldown_block", _fb_cooldown_block)


def _fb_epoch():
    fl, _ = _make_loop()
    for _ in range(10):
        fl.observe(3000.0, False)
    fl.evaluate(PerformanceProfile.BALANCED, SecurityPosture.GUARDED, 0.95)
    epochs = fl.epochs
    assert len(epochs) == 1
    assert epochs[0].action == "performance_downshift"
    assert epochs[0].cpu_usage == 0.95

test("epoch", _fb_epoch)


def _fb_audit():
    tmpdir = tempfile.mkdtemp()
    audit = AuditChain(log_path=os.path.join(tmpdir, "audit.jsonl"))
    mc = MetricsCollector()
    cfg = FeedbackConfig(cooldown_s=0.0, min_observations=5)
    fl = FeedbackLoop(metrics=mc, config=cfg, audit=audit)

    for _ in range(10):
        fl.observe(3000.0, False)
    fl.evaluate(PerformanceProfile.BALANCED, SecurityPosture.GUARDED, 0.95)

    assert audit.length >= 1
    entry = audit.get_entry(audit.length - 1)
    assert entry.event_type == "feedback_action"

test("audit", _fb_audit)


def _fb_config():
    cfg = FeedbackConfig(
        cpu_overload=0.50,
        latency_overload_ms=500.0,
        min_observations=3,
        cooldown_s=0.0,
    )
    mc = MetricsCollector()
    fl = FeedbackLoop(metrics=mc, config=cfg)
    for _ in range(5):
        fl.observe(100.0, False)
    # CPU 0.60 > custom threshold 0.50 → should trigger ECO
    action = fl.evaluate(PerformanceProfile.BALANCED, SecurityPosture.GUARDED, 0.60)
    assert action is not None
    assert action.performance == PerformanceProfile.ECO

test("config", _fb_config)


# ===========================================================================
# Integration — GovernanceEngine + FeedbackLoop
# ===========================================================================
section("Integration")


def _int_stable():
    gov = _make_engine()
    mc = MetricsCollector()
    fl = FeedbackLoop(metrics=mc, config=FeedbackConfig(cooldown_s=0.0, min_observations=5))

    for _ in range(20):
        fl.observe(100.0, False)
    action = fl.evaluate(gov.current_performance, gov.current_security, cpu_usage=0.40)
    assert action is None  # Stable system → no change

test("stable", _int_stable)


def _int_eco():
    gov = _make_engine()
    mc = MetricsCollector()
    fl = FeedbackLoop(metrics=mc, config=FeedbackConfig(cooldown_s=0.0, min_observations=5))

    for _ in range(20):
        fl.observe(3000.0, False)
    action = fl.evaluate(gov.current_performance, gov.current_security, cpu_usage=0.90)
    assert action is not None
    gov.update_axes(performance=action.performance, reason=action.reason)
    assert gov.current_performance == PerformanceProfile.ECO

test("int_eco", _int_eco)


def _int_balanced():
    gov = _make_engine()
    mc = MetricsCollector()
    cfg = FeedbackConfig(cooldown_s=0.0, min_observations=5, ema_alpha=0.3, ema_warmup=3)
    fl = FeedbackLoop(metrics=mc, config=cfg)

    # Overload → ECO
    for _ in range(15):
        fl.observe(3000.0, False)
    action = fl.evaluate(gov.current_performance, gov.current_security, cpu_usage=0.90)
    gov.update_axes(performance=action.performance, reason=action.reason)
    assert gov.current_performance == PerformanceProfile.ECO

    # Recovery → BALANCED
    for _ in range(80):
        fl.observe(100.0, False)
    action = fl.evaluate(gov.current_performance, gov.current_security, cpu_usage=0.10)
    assert action is not None
    gov.update_axes(performance=action.performance, reason=action.reason)
    assert gov.current_performance == PerformanceProfile.BALANCED

test("int_balanced", _int_balanced)


def _int_history():
    gov = _make_engine()
    mc = MetricsCollector()
    cfg = FeedbackConfig(cooldown_s=0.0, min_observations=5, ema_alpha=0.3, ema_warmup=3)
    fl = FeedbackLoop(metrics=mc, config=cfg)

    # Trigger two actions
    for _ in range(15):
        fl.observe(3000.0, False)
    fl.evaluate(gov.current_performance, gov.current_security, cpu_usage=0.90)

    for _ in range(80):
        fl.observe(100.0, False)
    fl.evaluate(PerformanceProfile.ECO, gov.current_security, cpu_usage=0.10)

    assert fl.total_adaptations == 2
    assert len(fl.epochs) == 2

test("int_history", _int_history)


# ===========================================================================
# Summary
# ===========================================================================

print(f"\n{'═' * 18}")
print(f"  PASSED: {_passed}  FAILED: {_failed}")
print(f"{'═' * 18}")
sys.exit(0 if _failed == 0 else 1)
