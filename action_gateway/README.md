# Action Gateway

Bounded mutation boundary between the Response Agent and the production simulator.

Planned actions:

- `prioritize_render`
- `reallocate_render_capacity`
- `escalate_vfx`

All consequential actions require explicit human approval. The gateway logs who/what approved the action and the resulting execution status.

## Boundary

```text
Response Planner → Action Gateway → policy check → human approval → simulator/action executor
```

Mutation reaches the simulator and Firestore only through this path; agents hold no direct write access to production documents or simulator internals.

## MVP API

```text
POST /actions/prioritize-render
POST /actions/reallocate-workers
POST /actions/escalate
```
