# Agents

ADK topology. Six purposeful agents; the workflow between them is deterministic application code. Access boundaries are in `../AGENTS.md`.

```text
supervisor — deterministic workflow orchestration
sentinel — detects anomalies from telemetry
investigator — correlates metrics, logs, traces, and Sift evidence
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
metric anomaly → service health → log/error patterns → slow requests/traces → related events → root-cause hypothesis
```

Every hypothesis cites the evidence that supports it.

### `impact` — What does this mean for production?

Joins investigation state with Firestore dependencies and schedule (`domain-model.md`). Emits affected scenes/shots/assets, impacted downstream stages, estimated schedule impact, risk level, confidence.

### `response` — What is the best bounded response?

Emits recommendation, action parameters, expected recovery, risk, and whether approval is required. Routes execution through the Action Gateway (`architecture.md`).

### `verification` — Did it work?

Re-queries telemetry after execution and compares against pre-action state. Verdict is one of `recovered`, `partially_recovered`, `not_recovered`, `inconclusive`.

## Prompt requirements

Every agent prompt defines: role, allowed tools, evidence requirements, output schema, stop/termination conditions, and the bar for an unsupported claim. Policy and state transitions live in code; prompts interpret evidence.
