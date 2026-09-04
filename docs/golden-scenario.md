# Golden scenario — INC-0042, Render Capacity Degradation

The one incident ReelOps must run end-to-end. Everything in the MVP exists to serve this path.

## Ground truth

Five of twelve render workers degrade or become unhealthy. The fault label stays inside the simulator; agents must reach it from telemetry alone.

## Expected telemetry pattern

```text
render_workers_available     ↓
render_job_duration_seconds  ↑
render_queue_depth           ↑↑
worker_timeout log events    ↑
render_throughput_fps        ↓
```

Multi-signal by design: a correct investigation correlates metrics, logs, and traces rather than reading one spiking metric.

## Production impact chain

```text
Scene 42 → VFX render → editorial review @ 16:00 → color → final assembly
```

The Impact Analyst should derive something equivalent to:

> Render capacity degradation is causing queue growth and is projected to push Scene 42's editorial review beyond the planned window.

The delay figure comes from simulated state at run time.

## Bounded responses

- prioritize Scene 42 render jobs
- reallocate available render capacity
- escalate to the VFX on-call owner

A human approves before execution. See `architecture.md`.

## Verification

Re-query telemetry after execution and confirm:

- `render_queue_depth` falling
- `render_workers_available` recovered
- `render_job_duration_seconds` improving
- schedule risk reduced

Verdicts: `recovered`, `partially_recovered`, `not_recovered`, `inconclusive`.
