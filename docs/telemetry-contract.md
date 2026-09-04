# Telemetry contract

What the simulator emits and what agents query. Grafana holds this plane; Firestore holds production meaning (`domain-model.md`).

## Prometheus metrics

### Render

```text
render_queue_depth · render_jobs_running · render_jobs_failed_total
render_job_duration_seconds · render_workers_available
render_workers_utilization · render_throughput_fps
```

### VFX

```text
vfx_shots_pending · vfx_shots_ready_for_review
vfx_shots_blocked · vfx_delivery_latency_seconds
```

### Editorial

```text
editorial_review_queue · editorial_blocked_scenes · review_wait_seconds
```

Bounded labels only: `project`, `service`, `environment`, `job_type`. Scene and shot identity belongs in logs and traces, where cardinality is free.

Deadline risk is inferred by ReelOps from these signals plus schedule state; it is never published as a source metric.

## Loki structured logs

### Fields

```text
timestamp · level · service · project_id · worker_id · job_id · scene_id
event · error_code · duration_ms · trace_id
```

Propagate `project_id`, `job_id`, `scene_id`, and `trace_id` consistently so an investigation can correlate a log line with its metric series and trace.

### Events

```text
render_started · render_completed · render_failed
worker_timeout · worker_recovered
job_queued · job_deprioritized
asset_delivery_delayed
```

Error codes stay machine-readable.

## OpenTelemetry traces

Canonical render path:

```text
editorial.review → vfx.render_request → render.enqueue → worker.render → storage.write
```

Spans carry bounded attributes: service name, job type, scene ID, outcome.
