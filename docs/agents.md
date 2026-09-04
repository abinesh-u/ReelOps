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
metric anomaly → service health → log/error patterns → slow renders → traces → root-cause hypothesis
```

Every hypothesis cites the evidence that supports it.

The investigator holds five tools — `query_prometheus`, `query_loki_logs`,
`query_loki_patterns`, `tempo_traceql-search` and `tempo_get-trace` — and it is
the only agent given traces. So:

- log and error patterns come from `query_loki_patterns`
- slow renders come from the p95 of `render_job_duration_seconds_bucket`, the
  same query the dashboard's duration panel uses
- traces come from a TraceQL search, then a fetch of one trace by id

**The slow-render step is PromQL, not Sift.** `find_slow_requests` and
`find_error_pattern_logs` each create a Sift investigation, so `--disable-write`
withholds them and a read-only server cannot serve them however the client is
filtered.

**The trace step is real, and verified end to end.** `telemetry/spans.py` emits
the `vfx.render_request → render.enqueue → worker.render → storage.write` chain
to Tempo, log records carry a native `trace_id`, and `tempo_traceql-search`
against `{resource.service.name="reelops-simulator"}` returns those spans
through MCP. A hypothesis may still cite only a span the agent actually
fetched — the tool exists, so there is no excuse for inferring one.

### `impact` — What does this mean for production?

Joins investigation state with Firestore dependencies and schedule (`domain-model.md`). Emits affected scenes/shots/assets, impacted downstream stages, estimated schedule impact, risk level, confidence.

### `response` — What is the best bounded response?

Emits recommendation, action parameters, expected recovery, risk, and whether approval is required. Routes execution through the Action Gateway (`architecture.md`).

Incident creation is Phase 6 and needs the write path. Until then this agent's budget is read-only — `list_incidents` and `get_incident`, so it can see the incident record without being able to change it. `create_incident`, `update_incident` and `add_activity_to_incident` arrive with a second, write-capable server instance reachable only from here.

### `verification` — Did it work?

Re-queries telemetry after execution and compares against pre-action state. Verdict is one of `recovered`, `partially_recovered`, `not_recovered`, `inconclusive`.

## Prompt requirements

Every agent prompt defines: role, allowed tools, evidence requirements, output schema, stop/termination conditions, and the bar for an unsupported claim. Policy and state transitions live in code; prompts interpret evidence.
