# Agents

ADK topology. Six purposeful agents; the workflow between them is deterministic application code. Access boundaries are in `../AGENTS.md`, and `../agents/tool_budget.py` is the machine-readable copy — the per-agent tool sets there are what each agent is actually handed.

```text
supervisor — deterministic workflow orchestration
sentinel — detects anomalies from telemetry
investigator — correlates metrics and logs into a root-cause hypothesis
impact — joins operational evidence with Firestore production dependencies
response — proposes bounded actions and creates/updates Grafana incidents
verification — checks telemetry after remediation
```

Gemini interprets evidence and selects investigation steps; application code owns stage transitions and authorization.

## Responsibilities

Each agent answers one question and emits structured output (`../agents/contracts.py`, `../agents/state.py`). Evidence before explanation: every conclusion cites concrete telemetry.

### `sentinel` — Is something abnormal?

Telemetry reads only. Emits anomaly flag, severity, affected service/signal, observed value, baseline, confidence, evidence references. Detection only; incident creation and state mutation belong elsewhere.

### `investigator` — Why is it happening?

Evidence sequence:

```text
metric anomaly → service health → log/error patterns → slow renders → related events → root-cause hypothesis
```

Every hypothesis cites the evidence that supports it.

**The slow-render step is PromQL, not Sift.** `find_slow_requests` and
`find_error_pattern_logs` each create a Sift investigation, so `--disable-write`
withholds them and a read-only server cannot serve them however the client is
filtered; mcp-grafana has no Tempo category at all. The investigator's three
tools are `query_prometheus`, `query_loki_logs` and `query_loki_patterns`. So:

- log and error patterns come from `query_loki_patterns`
- slow renders come from the p95 of `render_job_duration_seconds_bucket`, the
  same query the dashboard's duration panel uses

Traces are still exported and still correlate — `telemetry/spans.py` emits the
`vfx.render_request → render.enqueue → worker.render → storage.write` chain to
Tempo, and log records carry a native `trace_id`. They are reachable in the
Grafana UI, and so remain available to *show* in the demo; they are simply not
reachable as an MCP tool call, so no hypothesis may cite a span the agent did
not actually fetch. Whether to give the investigator Sift through a separate
write-capable instance is an open Phase 4 decision — see `grafana-setup.md`.

### `impact` — What does this mean for production?

Joins investigation state with Firestore dependencies and schedule (`domain-model.md`). Emits affected scenes/shots/assets, impacted downstream stages, estimated schedule impact, risk level, confidence.

### `response` — What is the best bounded response?

Emits recommendation, action parameters, expected recovery, risk, and whether approval is required. Routes execution through the Action Gateway (`architecture.md`).

Incident creation is Phase 6 and needs the write path. Until then this agent's budget is read-only — `list_incidents` and `get_incident`, so it can see the incident record without being able to change it. `create_incident`, `update_incident` and `add_activity_to_incident` arrive with a second, write-capable server instance reachable only from here.

### `verification` — Did it work?

Re-queries telemetry after execution and compares against pre-action state. Verdict is one of `recovered`, `partially_recovered`, `not_recovered`, `inconclusive`.

## Prompt requirements

Every agent prompt defines: role, allowed tools, evidence requirements, output schema, stop/termination conditions, and the bar for an unsupported claim. Policy and state transitions live in code; prompts interpret evidence.
