# Architecture decision record

## Decision
Use a workflow-oriented multi-agent topology with explicit structured state.

## Why
A hackathon system needs deterministic control over authorization and stage transitions while preserving agentic reasoning and tool selection.

## Boundaries

- Firestore: semantic production state.
- Grafana: empirical telemetry and operational record.
- ADK: agent orchestration.
- Gemini: interpretation, correlation, planning.
- Action Gateway: mutation boundary.
- Human approval: consequential action authorization.

## Golden loop

`Observe → Investigate → Correlate → Predict → Decide → Approve → Act → Verify`
