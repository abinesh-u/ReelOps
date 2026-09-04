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
