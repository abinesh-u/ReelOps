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
uv run ruff check simulator telemetry agents tests
uv run ruff format simulator telemetry agents tests

uv run python -m simulator               # simulator + control API on :8090
SIM_SPEED=600 uv run python -m simulator # 600 sim-seconds per real second

# Telemetry to stdout, no Grafana account needed
TELEMETRY_ENABLED=true TELEMETRY_CONSOLE=true uv run python -m simulator

# The live Grafana MCP gate. Needs mcp-grafana and the simulator both running;
# the launch command for mcp-grafana lives in docs/grafana-setup.md.
REELOPS_LIVE_MCP=1 uv run pytest tests/test_grafana_live.py -q
```

`requirements.txt` is generated for the Cloud Run buildpack, never hand-edited. After changing `pyproject.toml`:

```sh
uv lock && uv export --no-dev --no-hashes --no-emit-project --format requirements-txt -o requirements.txt
```

Ports: simulator `8090`, Action Gateway `8080`, Grafana MCP `8000`.

## Environment traps

- **The `[mcp]` extra on `google-adk` is load-bearing.** Bare `google-adk` does not declare `mcp`, so the resolver picks mcp 2.x, which dropped `ProgressFnT` and breaks `McpToolset` at import. The extra pins `mcp>=1.24,<2`.
- **Packages have no `__init__.py`.** `[tool.uv] package = false` plus pytest's `pythonpath = ["."]` is what makes `simulator` and `agents` importable from the repo root. Adding a `[tool.setuptools]` packages list breaks test collection.
- **`mcp-grafana` is a separate process that reads process environment, never `.env`** — and `.env` must not be shell-sourced. `set -a; . ./.env` exits **0** and silently truncates `OTEL_EXPORTER_OTLP_HEADERS` to `Authorization=Basic`, because the value contains a space: the rest is parsed as a command. The credential is dropped with no error anywhere. Use the prefix-scoped extraction in the launch line in `docs/grafana-setup.md`, which is the only place that command lives.
- **No `asyncio_mode` is configured.** Async tests need an explicit `@pytest.mark.asyncio`, and async *fixtures* need `@pytest_asyncio.fixture` — a plain `@pytest.fixture` on an async fixture errors at setup rather than running.
- **Settings tests must pass `_env_file=None`.** `GrafanaSettings` and `TelemetrySettings` read `.env`; once it is populated, a fail-loud test that omits this picks up real values and silently stops asserting anything.
- `timeout` is not available in this shell.

## Code map

| Directory | State |
| --- | --- |
| `simulator/` | Phase 1, complete |
| `telemetry/` | Phase 2, complete — OTLP metrics, logs and traces, confirmed live in Grafana Cloud |
| `agents/` | Phase 3, complete — typed contracts, shared state, and the Grafana MCP wiring; no agent implementations yet |
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

## Grafana MCP invariants

`docs/grafana-setup.md` is the runbook; `AGENTS.md` sets the budget. These are the ways to widen privilege or hide a failure without noticing.

- **The budget lives in `agents/tool_budget.py`, and the launch command lives in `docs/grafana-setup.md`.** The `--enabled-tools` value is generated from the same dict the per-agent filters are checked against, and a test asserts it appears verbatim in that doc. If that test fails, fix whichever side is wrong — do not loosen it to a set comparison, which is the only thing keeping the server boundary and the documented command in sync.
- **Two levers, and both are load-bearing.** Server flags are the boundary; `tool_filter` is what each agent is handed. A filter alone leaves the tool reachable on the server.
- **`--disable-write` withholds the two Sift search tools**, because creating a Sift investigation is a write. A read-only server serves neither `find_error_pattern_logs` nor `find_slow_requests`, however the client is filtered.
- **Proxied tools exist only against a real Grafana Cloud stack, and `--enabled-tools` does not reach them.** Nine `tempo_*` tools are relayed from Cloud's own MCP server: the read server exposes 22 tools locally and 31 against Cloud. The only server-side lever is `--disable-proxied`, all-or-nothing, so for the two the investigator uses the client-side `tool_filter` is the *only* narrowing. Measure the tool list against the real stack, never against a local Grafana.
- **ADK returns MCP failures as data, not exceptions** — `except McpError: return {"error": ...}`, and a backend failure arrives as `{"content": [...], "isError": True}`. Anything calling a tool directly must go through `call_tool`, which raises on both shapes; otherwise a 403 reads as a successful call.
- **An empty PromQL result is a well-formed success.** Use `require_series`, never the raw payload. This is the same trap as the histogram names: `render_job_duration_seconds` has no series under its bare name.
- **Metrics label the project `project`; logs label it `project_id`.** LogQL filtering on `project` matches nothing, silently.
- **The live gate is opt-in via `REELOPS_LIVE_MCP=1`, and fails rather than skips when set with incomplete config.** Keying it off the presence of `GRAFANA_URL` would make every ordinary test run reach for a server that is not up.
