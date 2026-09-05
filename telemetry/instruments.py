"""Contract names to OTLP instruments, one to one.

`docs/telemetry-contract.md` is the authority. Every name below is copied from
it verbatim; a rename here empties an agent's PromQL, which reads as a healthy
system rather than a broken query.

Instrument `unit` is deliberately left unset. Grafana Cloud appends a unit
suffix on ingest unless the name already carries it, so declaring `s` on
`render_job_duration_seconds` would land it as `..._seconds_seconds`.

Labels stay bounded: `project`, `service`, `environment`, `job_type` only.
Per-worker series are available in the snapshot and are not exported — worker
identity belongs in logs and traces, where cardinality is free.
"""

from dataclasses import dataclass

from opentelemetry.metrics import Counter, Histogram, Meter
from opentelemetry.sdk.metrics.view import ExplicitBucketHistogramAggregation, View

RENDER_SERVICE = "render-farm"
VFX_SERVICE = "vfx"
EDITORIAL_SERVICE = "editorial"

# Gauges, grouped by the service that owns them.
GAUGES: dict[str, str] = {
    "render_queue_depth": RENDER_SERVICE,
    "render_jobs_running": RENDER_SERVICE,
    "render_workers_available": RENDER_SERVICE,
    "render_workers_utilization": RENDER_SERVICE,
    "render_throughput_fps": RENDER_SERVICE,
    "vfx_shots_pending": VFX_SERVICE,
    "vfx_shots_ready_for_review": VFX_SERVICE,
    "vfx_shots_blocked": VFX_SERVICE,
    "editorial_review_queue": EDITORIAL_SERVICE,
    "editorial_blocked_scenes": EDITORIAL_SERVICE,
    "review_wait_seconds": EDITORIAL_SERVICE,
}

FAILED_COUNTER = "render_jobs_failed_total"
RENDER_DURATION_HISTOGRAM = "render_job_duration_seconds"
DELIVERY_LATENCY_HISTOGRAM = "vfx_delivery_latency_seconds"

# The SDK default boundaries stop at 10 and then jump in decades, which puts
# every render in one bucket and makes histogram_quantile meaningless.
#
# The two histograms need different scales. Time on a worker is capped by the
# 1800s timeout and clusters around the 900s nominal, so its buckets are fine
# between the two, with a boundary just above the healthy maximum of ~1090s
# so the shoulder between healthy and degraded work is representable at all. Delivery latency adds queue wait and
# retries on top, and runs to hours once capacity is short.
RENDER_DURATION_BUCKETS = (
    300.0,
    600.0,
    750.0,
    900.0,
    1000.0,
    1100.0,
    1250.0,
    1400.0,
    1550.0,
    1700.0,
    1800.0,
    2400.0,
)
DELIVERY_LATENCY_BUCKETS = (
    600.0,
    900.0,
    1200.0,
    1800.0,
    2400.0,
    3000.0,
    3600.0,
    5400.0,
    7200.0,
    10800.0,
    14400.0,
)

JOB_TYPE_RENDER = "render"
JOB_TYPE_REVIEW = "review"


def histogram_views() -> list[View]:
    return [
        View(
            instrument_name=name,
            aggregation=ExplicitBucketHistogramAggregation(boundaries=boundaries),
        )
        for name, boundaries in (
            (RENDER_DURATION_HISTOGRAM, RENDER_DURATION_BUCKETS),
            (DELIVERY_LATENCY_HISTOGRAM, DELIVERY_LATENCY_BUCKETS),
        )
    ]


def attributes(project: str, service: str, environment: str, job_type: str) -> dict[str, str]:
    return {
        "project": project,
        "service": service,
        "environment": environment,
        "job_type": job_type,
    }


@dataclass
class Instruments:
    gauges: dict[str, object]
    gauge_attributes: dict[str, dict[str, str]]
    jobs_failed: Counter
    render_duration: Histogram
    delivery_latency: Histogram
    render_attributes: dict[str, str]
    vfx_attributes: dict[str, str]


def build_instruments(meter: Meter, project: str, environment: str) -> Instruments:
    render_attrs = attributes(project, RENDER_SERVICE, environment, JOB_TYPE_RENDER)
    vfx_attrs = attributes(project, VFX_SERVICE, environment, JOB_TYPE_RENDER)
    gauge_attributes = {
        name: attributes(
            project,
            service,
            environment,
            JOB_TYPE_REVIEW if service == EDITORIAL_SERVICE else JOB_TYPE_RENDER,
        )
        for name, service in GAUGES.items()
    }
    return Instruments(
        gauges={name: meter.create_gauge(name) for name in GAUGES},
        gauge_attributes=gauge_attributes,
        jobs_failed=meter.create_counter(FAILED_COUNTER),
        render_duration=meter.create_histogram(RENDER_DURATION_HISTOGRAM),
        delivery_latency=meter.create_histogram(DELIVERY_LATENCY_HISTOGRAM),
        render_attributes=render_attrs,
        vfx_attributes=vfx_attrs,
    )
