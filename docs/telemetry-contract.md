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

### Rates and durations

Most of the vocabulary above is unambiguous gauges and counters. Three pin a
start and an end, and a PromQL query cannot be right unless it means the same
thing the simulator does:

| Metric | Definition |
| --- | --- |
| `render_throughput_fps` | frames completed within the trailing 900 sim-seconds, divided by that window |
| `vfx_delivery_latency_seconds` | per shot, sim time from its render job being queued to `render_completed` — queue wait, retries and render time included |
| `review_wait_seconds` | the longest time any scene currently in the editorial queue has been ready for review but unreviewed |

The throughput window is one nominal job duration. A shorter window is
dominated by completion bursts: twelve workers finishing ~900-second jobs make
a 300-second window read 0 or 4 completions, which inverts the healthy and
degraded rates by luck of sampling.

`render_job_duration_seconds` measures time on the worker, so a slow worker
raises it even when the job eventually succeeds. Its mean moves little under
partial degradation; query the p95, which is where the signal lives.

`editorial_blocked_scenes` counts scenes whose review cannot start because
upstream shots are unfinished. That is a state fact, not a deadline judgement.

Bounded labels only: `project`, `service`, `environment`, `job_type`. Scene and shot identity belongs in logs and traces, where cardinality is free.

Deadline risk is inferred by ReelOps from these signals plus schedule state; it is never published as a source metric.

## Loki structured logs

### Fields

```text
timestamp · level · service · project_id · worker_id · job_id · scene_id
event · error_code · duration_ms · trace_id
```

Propagate `project_id`, `job_id`, `scene_id`, and `trace_id` consistently so an investigation can correlate a log line with its metric series and trace. One job carries one `trace_id` across every event it produces, retries included.

### Events

```text
render_started · render_completed · render_failed
worker_timeout · worker_recovered
job_queued · job_deprioritized
asset_delivery_delayed
```

Error codes stay machine-readable.

`worker_timeout` and `asset_delivery_delayed` are the two events that separate a healthy farm from a degraded one, and both sit at zero in a healthy run. Keep them that way when tuning: `asset_delivery_delayed` fires on a breach of `delivery_sla_seconds`, measured queued-to-delivered, so an SLA set below the healthy latency distribution turns the event into constant noise and costs the Investigator its log signal.

## OpenTelemetry traces

Canonical render path:

```text
editorial.review → vfx.render_request → render.enqueue → worker.render → storage.write
```

Spans carry bounded attributes: service name, job type, scene ID, outcome.

## OTLP naming

All three signals ship over OTLP (`grafana-setup.md`). Grafana Cloud converts OTLP metric names to Prometheus names on ingest, and two conversions decide whether the names above are queryable:

- **`_total` on counters.** A monotonic sum gets `_total` appended unless the name already ends in it. `render_jobs_failed_total` is therefore correct as written — the suffix is not doubled.
- **Unit suffixes.** A unit suffix is appended unless the name already contains it. Name instruments exactly as listed above and leave the instrument `unit` unset; `render_job_duration_seconds` with unit `s` risks arriving as `render_job_duration_seconds_seconds`.

Resource attributes do not become metric labels. `service.name` and `service.instance.id` are promoted to `job` and `instance`; everything else lands on `target_info`, joinable with `metric * on(job, instance) group_left(label) target_info`. Emit `project`, `service`, `environment`, and `job_type` as explicit metric attributes so agent queries can filter on them directly.

Verify a name in Grafana before writing an agent query against it. A renamed metric fails as an empty result, which reads like a healthy system rather than a broken query.
