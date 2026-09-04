# Loki structured log contract

Minimum fields:

- `timestamp`
- `level`
- `service`
- `project_id`
- `event`
- `trace_id` when available

Failure examples use events such as `worker_timeout`, `render_failed`, and `asset_delivery_delayed` with machine-readable error codes.

## Fields

```text
timestamp · level · service · project_id · worker_id · job_id · scene_id
event · error_code · duration_ms · trace_id
```

Propagate `project_id`, `job_id`, `scene_id`, and `trace_id` consistently so an investigation can correlate a log line with its metric series and trace.

## Events

```text
render_started · render_completed · render_failed
worker_timeout · worker_recovered
job_queued · job_deprioritized
asset_delivery_delayed
```
