# Architecture

## Decision

Use a workflow-oriented multi-agent topology with explicit structured state.

## Why

A hackathon system needs deterministic control over authorization and stage transitions while preserving agentic reasoning and tool selection.

## Boundaries

- **Firestore** — semantic production state (`domain-model.md`).
- **Grafana Cloud** — empirical telemetry and operational record (`telemetry-contract.md`).
- **ADK** — agent orchestration (`agents.md`).
- **Gemini** — interpretation, correlation, planning.
- **Action Gateway** — mutation boundary.
- **Human approval** — consequential action authorization.

## Golden loop

```text
Observe → Investigate → Correlate → Predict → Decide → Approve → Act → Verify
```

## Modules

### `simulator/`

Simulates the minimum distributed workflow the golden scenario needs:

```text
VFX → Render Queue → Render Workers → Editorial Review
```

Emits metrics, structured logs, and traces while keeping ground-truth fault labels inside the simulator, where agents cannot read them. Deterministic under a seed.

**Ticks, not wall clock.** State is a pure function of `(seed, tick index, injected events)`. A tick advances `SIM_TICK_SECONDS` of sim time; `SIM_SPEED` decides how many real seconds that takes, so a 90 sim-minute window plays in 90 seconds at `SIM_SPEED=60` while durations stay realistic. Tests step ticks directly and never sleep. All randomness comes from one `Random(seed)` owned by the engine — module-level `random` would silently break replay.

**`engine.py` is the deep module**; `api.py` is a thin adapter over it, and `POST /sim/inject/render-worker-degradation` is what the Action Gateway will call. The fault only changes worker speed and availability: queue growth, timeouts and throughput collapse are consequences, not scripted values, which is what makes the Sentinel's detection worth anything.

**`SimulationSnapshot` is the Phase 2 seam.** It carries the metric names in `telemetry-contract.md` verbatim, plus worker, queue and scene entities and the duration samples behind the histograms. The exporter maps it one-to-one and adds nothing.

Ground truth — which workers were faulted, and when — lives on the engine behind `ground_truth()` and has no HTTP route at all. A `/sim/_eval/…` path would be a naming convention rather than a boundary, reachable by anything holding the base URL.

A fault of five workers takes two down outright and leaves three crawling (`unhealthy_fraction`), matching the golden scenario's "degrade or become unhealthy". A worker that goes down mid-job hands that job back to the queue.

**Calibration.** Sim starts 14:30; Scene 42 is 24 shots against a 16:00 editorial deadline, contending with a standing backlog and continuous background work. Measured across 25 seeds:

| | healthy margin | with 5 of 12 workers faulted |
| --- | --- | --- |
| best / median / worst | +30.2 / +22.8 / +12.5 min | −28.2 / −65.0 / −163.8 min |
| default seed (42) | +28.2 min | −101.8 min |

Every seed makes the window healthy and misses it faulted. The deadline test asserts only the sign, so these figures move with tuning — the spread is wide because a queue that loses capacity degrades non-linearly, not because the run is noisy. Phase 9 scores the Impact Analyst's predicted delay against the achieved figure.

Two limitations to carry into Phase 4. The backlog drains over the first ~80 sim-minutes, so the healthy baseline falls rather than sitting flat — detection should compare against the trajectory, not a fixed threshold. And `render_throughput_fps` is quantised by frames-per-job, so at a single tick two runs can tie; the queue, duration and log signals separate cleanly where it does not.

### `telemetry/`

Turns `SimulationSnapshot`, the event log and per-job timelines into OTLP
metrics, logs and traces. It imports `simulator/`; nothing in `simulator/`
imports it. `create_app` takes an optional emitter matching a small structural
protocol, so the simulator runs unchanged with telemetry off and no
OpenTelemetry import sits on its path.

**Recording is pushed from the simulation's own event loop.** The obvious
alternative — observable instruments whose callbacks the SDK invokes — runs
those callbacks on the metric reader's thread, where they would iterate the
queue deque and the scenes dict while `tick()` mutates both. The failure is an
intermittent `RuntimeError` on a background thread. An asyncio task in the same
loop awaits only between records and cannot interleave with a tick.

Each buffer the exporter reads from is a `BoundedStream` with a monotonic
`recorded_total`, so a consumer drains by cursor rather than re-reading a ring
buffer and exporting every sample twice. Falling further behind than the buffer
is deep logs a warning instead of quietly under-reporting.

Timestamps are wall-clock and sim durations are compressed by `SIM_SPEED` — see
`telemetry-contract.md` for why, and for what that costs. Traces reuse the
simulator's own `trace_id`, widened to 128 bits with a per-process nonce so
re-running a seed produces fresh traces rather than merging into the last take.

Configuration is fail-loud: `TELEMETRY_ENABLED=true` with no OTLP endpoint
raises before the port opens, because an exporter pointed at nothing accepts
every record and drops it. `TELEMETRY_CONSOLE=true` prints locally instead.

### `action_gateway/`

The bounded mutation boundary between the Response agent and the simulator:

```text
Response Planner → Action Gateway → policy check → human approval → simulator/action executor
```

Mutation reaches the simulator and Firestore only through this path; agents hold no direct write access to production documents or simulator internals. The gateway records who approved what, and the resulting execution status.

MVP surface:

```text
POST /actions/prioritize-render      prioritize_render
POST /actions/reallocate-workers     reallocate_render_capacity
POST /actions/escalate               escalate_vfx
```

### `frontend/`

Control-tower workflow first; chat is secondary. The main screen makes eight things immediately obvious:

```text
PROJECT HEALTH · PIPELINE STATE · ACTIVE RISK · ROOT CAUSE
DOWNSTREAM IMPACT · RECOMMENDED ACTION · APPROVAL STATE · RECOVERY STATE
```

The investigation view renders the evidence chain:

```text
1. Metric anomaly          4. Trace slowdown         7. Risk prediction
2. Worker health           5. Production dependency   8. Recommended response
3. Log pattern             6. Schedule constraint     9. Verification result
```

A judge should understand the system from this view alone, without reading a prompt transcript.

### `backend/`

API and session layer between the UI and the ADK supervisor.

### `infra/`

Cloud Run for web/API and agent runtime, Firestore for production-domain state, Secret Manager for credentials, Grafana Cloud MCP for runtime observability access. Keep infrastructure intentionally small; Kubernetes needs a demonstrated requirement.

Dependencies are declared in `../pyproject.toml`. `requirements.txt` is generated from the lock for the Cloud Run Python buildpack, which reads that file rather than `pyproject.toml`:

```sh
uv lock && uv export --no-dev --no-hashes --no-emit-project --format requirements-txt -o requirements.txt
```

Secrets are mounted as environment variables by Cloud Run, so no Secret Manager client library is needed at runtime.
