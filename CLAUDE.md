# Symbioz Pro — Governance Runtime

## Project Structure

This is a Redox OS project with a Python-based governance and observability layer.

### Rust (core OS tooling)
```
src/cook/         # Package cookbook
src/bin/          # CLI binaries (repo, repo_builder, cookbook_redoxer)
Cargo.toml        # Rust manifest
```

### Python (governance runtime)
```
src/core/
├── governance/
│   ├── modes.py              # OperationalMode, SecurityPosture, PerformanceProfile
│   ├── policy.py             # RuntimePolicy (frozen dataclass, 23 typed fields)
│   ├── engine.py             # GovernanceEngine (11-step pipeline, hot-reload)
│   ├── trace.py              # DecisionTrace (weighted confidence, explainability)
│   ├── feedback.py           # FeedbackLoop + EMATracker (auto-tuning)
│   ├── qos.py                # AdaptiveQoSController (backpressure, throttling)
│   ├── circuit_breaker.py    # CircuitBreaker (CLOSED/OPEN/HALF_OPEN)
│   └── audit.py              # AuditChain (tamper-evident SHA-256 hash chain)
└── observability/
    ├── metrics.py            # MetricsCollector + ReservoirSampler + SLAMonitor
    └── panic.py              # PanicSwitch (file-based emergency lockdown)

config/policy.yaml            # Runtime-editable policy (hot-reload without restart)
tests/test_feedback.py        # 28-test suite with custom runner
```

## Running Tests

```bash
# From repo root
pip install pyyaml
python tests/test_feedback.py
```

Expected output: `PASSED: 28  FAILED: 0`

## Key Commands

```bash
# Rust tests
cargo test --locked

# Python governance tests
python tests/test_feedback.py

# Full CI (Rust + Python)
# Handled by .gitlab-ci.yml
```

## Architecture: Three Independent Axes

The governance system uses three orthogonal axes that can be combined independently:

| Axis | Values | Controls |
|------|--------|----------|
| **OperationalMode** | DEVELOPMENT, PRODUCTION, PARANOID, FORENSIC | What the system *does* |
| **SecurityPosture** | OPEN, GUARDED, HARDENED, LOCKDOWN | How *defensive* it is |
| **PerformanceProfile** | ECO, BALANCED, TURBO | Speed vs thoroughness |

Example combinations:
- `PRODUCTION + HARDENED + ECO` — secure low-power IoT
- `DEVELOPMENT + OPEN + TURBO` — local dev machine
- `PARANOID + LOCKDOWN + BALANCED` — under active threat

## Feedback Loop

The system self-regulates via `FeedbackLoop`:

```
Intent → Engine → Trace → Audit
                     ↓
                  Metrics
                     ↓
                 FeedbackLoop (EMA-based)
                     ↓
              update_axes() → Engine
```

Triggers:
- CPU > 85% or latency > 2000ms → ECO downshift
- CPU < 20% and latency < 500ms (from ECO) → BALANCED upshift
- Rejection rate > 40% → LOCKDOWN
- Rejection rate < 5% (from LOCKDOWN) → GUARDED recovery

## Configuration

Edit `config/policy.yaml` and call `governor.reload_policy()`. No restart needed.

## Dependencies

- Python 3.10+
- `pyyaml` (for policy YAML parsing)
- No other external dependencies
