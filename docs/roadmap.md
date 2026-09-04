# Roadmap

Phase order and current phase live in `AGENTS.md`. This file holds the completion bar and what comes after the MVP.

## Definition of done — MVP

From a clean environment, all of the following work:

1. Production simulator starts healthy.
2. Failure injector triggers render-worker degradation.
3. Metrics, logs, and traces reach Grafana Cloud.
4. Sentinel detects the anomaly without being told the injected fault.
5. Investigator independently gathers cross-source Grafana evidence.
6. Impact Analyst maps the fault to Scene 42 and its downstream chain.
7. System produces a quantified schedule-risk estimate.
8. Response Planner proposes a bounded action.
9. User approves the action in the UI.
10. Action Gateway executes it.
11. Grafana incident/audit record is updated where appropriate.
12. Verifier confirms recovery using fresh telemetry.
13. UI shows the complete evidence chain.
14. Tests cover the failure injector and critical state transitions.
15. README explains how to reproduce the demo.

## After the golden path is stable

### Asset/version drift

```text
new VFX version available → downstream still consuming old version → agent identifies stale dependency
```

### Ingest degradation

```text
camera ingest falls behind → dailies delayed → editorial risk
```

### QC failures

```text
QC error pattern → delivery package risk → incident + escalation
```

### Self-observability

Instrument ReelOps itself:

```text
agent.investigation.duration
agent.tool_calls.total
agent.tool_errors.total
agent.root_cause_confidence
agent.prediction_error
agent.approval_latency
```

Long-term goal: a system that observes both film production and its own agents.
