# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Start with AGENTS.md

`AGENTS.md` is the project contract: hard constraints, working rules, agent permissions, the Grafana MCP tool budget, the phase order, and a table telling you which `docs/` file to read for the area you are touching. Read it before changing anything. This file covers only what it does not: commands, environment traps, and the invariants that span several modules.

## Commands

Everything runs through `uv`. The repo's venv is Python 3.13; the system `python3` is 3.14 with no dev dependencies installed, so a bare `python3 -m pytest` fails.

```sh
uv sync --extra dev                      # install
uv run pytest -q                         # full suite
uv run pytest tests/test_simulator.py::test_determinism    # one test
uv run pytest -k degradation             # by name
uv run ruff check simulator tests
uv run ruff format simulator tests

uv run python -m simulator               # simulator + control API on :8090
SIM_SPEED=600 uv run python -m simulator # 600 sim-seconds per real second

# Telemetry to stdout, no Grafana account needed
TELEMETRY_ENABLED=true TELEMETRY_CONSOLE=true uv run python -m simulator
```

`requirements.txt` is generated for the Cloud Run buildpack, never hand-edited. After changing `pyproject.toml`:

```sh
uv lock && uv export --no-dev --no-hashes --no-emit-project --format requirements-txt -o requirements.txt
```

Ports: simulator `8090`, Action Gateway `8080`, Grafana MCP `8000`.

## Environment traps

- **The `[mcp]` extra on `google-adk` is load-bearing.** Bare `google-adk` does not declare `mcp`, so the resolver picks mcp 2.x, which dropped `ProgressFnT` and breaks `McpToolset` at import. The extra pins `mcp>=1.24,<2`.
- **Packages have no `__init__.py`.** `[tool.uv] package = false` plus pytest's `pythonpath = ["."]` is what makes `simulator` and `agents` importable from the repo root. Adding a `[tool.setuptools]` packages list breaks test collection.
- `timeout` is not available in this shell.

## Code map

| Directory | State |
| --- | --- |
| `simulator/` | Phase 1, complete |
| `telemetry/` | Phase 2, complete — OTLP metrics, logs and traces; live Grafana confirmation still pending credentials |
| `agents/` | typed contracts and shared state only; no agent implementations yet |
| `evals/` | scenario definitions and scoring notes |
| `action_gateway/`, `backend/`, `frontend/`, `infra/` | empty placeholders |

## Simulator invariants

These span `config.py`, `engine.py`, `pipeline.py` and `snapshot.py`, and are easy to break without noticing. `docs/architecture.md` has the full design and the measured calibration.

- **All randomness comes from the single `Random(seed)` the engine owns.** Simulated state is a pure function of `(seed, tick index, injected events)`. A module-level `random` call silently destroys replay, and nothing fails loudly when it happens.
- **Ground truth never leaves the engine.** `SimulationEngine.ground_truth()` is in-process for evals. It must stay out of `SimulationSnapshot` and off every HTTP route — a `/sim/_eval/...` path would be a naming convention, not a boundary.
- **`SimulationSnapshot.metrics` keys are the `docs/telemetry-contract.md` names verbatim.** Phase 2's OTLP exporter maps them one-to-one. Renaming one here silently empties an agent's PromQL, which reads as a healthy system rather than a broken query.
- **Faults change only worker speed and availability.** Queue growth, timeouts and throughput collapse must stay consequences of the simulation. Writing a demo figure into the pipeline defeats the point of the Sentinel detecting it.
- **Tuning constants live in `SimulatorSettings`, and they are calibrated.** Scene 42 must make its 16:00 deadline healthy and miss it faulted, on every seed. After changing any of them, re-run the multi-seed sweep — the test only asserts the sign of the margin, so it will not catch a calibration that has quietly gone one-sided.
- `tests/test_failure_injector.py` predates the engine and pins the public shape: `FailureInjector()` stays constructible with no arguments.

## Telemetry invariants

`docs/telemetry-contract.md` is the authority; these are the ways to break it quietly.

- **`telemetry/` imports `simulator/`, never the reverse.** `create_app` takes an emitter matching a structural protocol, so no OpenTelemetry import reaches the simulator's path and console/in-memory adapters stay off it.
- **Never record from an observable-instrument callback.** The SDK runs those on the metric reader's thread, and `build_snapshot` iterates structures `tick()` mutates. Recording is pushed from an asyncio task in the simulator's own loop.
- **The two duration metrics are histograms**, so neither exists as a series under its own name. PromQL against the bare name returns empty, which reads as a healthy system.
- **Exported labels are `project`, `service`, `environment`, `job_type` and nothing else.** The snapshot carries per-worker entries; exporting them would be unbounded cardinality.
- **Do not widen the simulator's 64-bit `trace_id`.** `getrandbits(128)` consumes a different amount of the seeded stream and destroys the calibration. The exporter prepends a per-process nonce instead.
- **Anything the exporter drains needs a cursor.** The sample and event buffers are ring buffers; re-reading one exports every entry again.
