# Telemetry contract

## Prometheus metrics

### Render
- `render_queue_depth`
- `render_jobs_running`
- `render_jobs_failed_total`
- `render_job_duration_seconds`
- `render_workers_available`
- `render_workers_utilization`
- `render_throughput_fps`

### VFX
- `vfx_shots_pending`
- `vfx_shots_ready_for_review`
- `vfx_shots_blocked`
- `vfx_delivery_latency_seconds`

### Editorial
- `editorial_review_queue`
- `editorial_blocked_scenes`
- `review_wait_seconds`

Recommended bounded metric labels: `project`, `service`, `environment`, `job_type`. Put high-cardinality scene/shot IDs primarily in logs/traces.
