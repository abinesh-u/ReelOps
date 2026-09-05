"""Offline verification of the OTLP export path.

Everything here runs against in-memory readers and exporters, so the exported
data is asserted rather than eyeballed in Grafana. The recording path is the
same one production runs — only the exporter differs.
"""

import pytest
from opentelemetry.sdk._logs.export import InMemoryLogRecordExporter, SimpleLogRecordProcessor
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from simulator.config import SimulatorSettings
from simulator.engine import SimulationEngine
from telemetry.config import TelemetryConfigError, TelemetrySettings
from telemetry.emitter import TelemetryEmitter
from telemetry.instruments import (
    DELIVERY_LATENCY_HISTOGRAM,
    FAILED_COUNTER,
    GAUGES,
    RENDER_DURATION_HISTOGRAM,
)
from telemetry.providers import build_providers
from telemetry.spans import derive_trace_id

# Far enough in that the backlog has drained and Scene 42 is mid-flight.
RUN_TICKS = 420
INJECT_AT = 120


class Harness:
    """An engine, an emitter, and the three in-memory sinks behind it."""

    def __init__(self, seed: int = 42) -> None:
        self.engine = SimulationEngine(SimulatorSettings(sim_seed=seed))
        self.metrics = InMemoryMetricReader()
        self.logs = InMemoryLogRecordExporter()
        self.spans = InMemorySpanExporter()
        providers = build_providers(
            TelemetrySettings(),
            metric_reader=self.metrics,
            log_processor=SimpleLogRecordProcessor(self.logs),
            span_processor=SimpleSpanProcessor(self.spans),
        )
        self.emitter = TelemetryEmitter(self.engine, providers, TelemetrySettings())
        self._points: dict[str, list] = {}

    def run(self, ticks: int, record_every: int = 30) -> None:
        for tick in range(ticks):
            self.engine.step()
            if tick % record_every == 0:
                self.emitter.record_once()
        self.emitter.record_once()

    def points(self) -> dict[str, list]:
        """Exported points keyed by metric name.

        `get_metrics_data()` drains the reader, so results accumulate here and
        repeated calls stay meaningful.
        """
        data = self.metrics.get_metrics_data()
        for resource in data.resource_metrics:
            for scope in resource.scope_metrics:
                for metric in scope.metrics:
                    self._points.setdefault(metric.name, []).extend(metric.data.data_points)
        return self._points

    def gauge(self, name: str) -> float:
        return self.points()[name][-1].value

    def events(self, name: str) -> list:
        return [
            r.log_record
            for r in self.logs.get_finished_logs()
            if r.log_record.attributes.get("event") == name
        ]


def p95(harness: Harness, metric: str) -> float:
    """The bucket-based quantile Grafana computes, not the mean.

    `docs/telemetry-contract.md` says the signal lives in the p95, so that is
    what this asserts — a mean moves little under partial degradation.
    """
    point = harness.points()[metric][-1]
    bounds = list(point.explicit_bounds)
    target = 0.95 * point.count
    seen = 0
    for index, count in enumerate(point.bucket_counts):
        seen += count
        if seen >= target:
            return bounds[index] if index < len(bounds) else bounds[-1]
    return bounds[-1]


def run_pair() -> tuple[Harness, Harness]:
    """The same seed and tick count, one healthy and one faulted."""
    healthy = Harness()
    healthy.run(RUN_TICKS)

    degraded = Harness()
    degraded.run(INJECT_AT)
    degraded.engine.inject_render_worker_degradation(5)
    degraded.run(RUN_TICKS - INJECT_AT)
    return healthy, degraded


def test_exported_metric_names_match_contract() -> None:
    """Every contract name is exported, under the name the contract uses.

    A rename shows up as an empty PromQL result, which reads as a healthy
    system rather than a broken query — the failure docs/telemetry-contract.md
    exists to prevent.
    """
    harness = Harness()
    harness.run(RUN_TICKS)
    exported = set(harness.points())

    assert set(GAUGES) <= exported
    assert FAILED_COUNTER in exported
    # Histograms carry no series under the bare name; the derived ones are what
    # PromQL must ask for.
    assert {RENDER_DURATION_HISTOGRAM, DELIVERY_LATENCY_HISTOGRAM} <= exported

    # Nothing is exported that the contract does not name.
    assert exported == set(GAUGES) | {
        FAILED_COUNTER,
        RENDER_DURATION_HISTOGRAM,
        DELIVERY_LATENCY_HISTOGRAM,
    }


def test_snapshot_metrics_are_all_exported() -> None:
    """No snapshot key is silently dropped on its way to an instrument."""
    harness = Harness()
    harness.run(60)
    snapshot_keys = set(harness.engine.snapshot().metrics)
    histograms = {RENDER_DURATION_HISTOGRAM, DELIVERY_LATENCY_HISTOGRAM}
    assert snapshot_keys - histograms == set(GAUGES) | {FAILED_COUNTER}


def test_healthy_and_degraded_differ() -> None:
    """The golden scenario's five signals, in the exported data."""
    healthy, degraded = run_pair()

    assert degraded.gauge("render_workers_available") < healthy.gauge("render_workers_available")
    assert degraded.gauge("render_queue_depth") > healthy.gauge("render_queue_depth")
    assert degraded.gauge("render_throughput_fps") < healthy.gauge("render_throughput_fps")

    assert p95(degraded, RENDER_DURATION_HISTOGRAM) > p95(healthy, RENDER_DURATION_HISTOGRAM)
    assert len(degraded.events("worker_timeout")) > 0
    assert len(healthy.events("worker_timeout")) == 0


def test_failed_counter_climbs_only_when_degraded() -> None:
    healthy, degraded = run_pair()
    assert degraded.points()[FAILED_COUNTER][-1].value > 0
    assert healthy.points()[FAILED_COUNTER][-1].value == 0, (
        "a healthy farm must still publish the series, at zero"
    )


def test_no_per_worker_series() -> None:
    """Labels stay bounded: worker identity belongs in logs and traces."""
    harness = Harness()
    harness.run(RUN_TICKS)
    for points in harness.points().values():
        for point in points:
            assert set(point.attributes) == {"project", "service", "environment", "job_type"}


def test_logs_carry_native_trace_id() -> None:
    """The native field, not an attribute, is what drives log-to-trace."""
    harness = Harness()
    harness.run(RUN_TICKS)
    records = [r.log_record for r in harness.logs.get_finished_logs()]
    with_jobs = [r for r in records if r.attributes.get("job_id")]

    assert with_jobs
    assert all(r.trace_id != 0 for r in with_jobs)

    spans = harness.spans.get_finished_spans()
    span_traces = {s.context.trace_id for s in spans}
    log_traces = {r.trace_id for r in with_jobs}
    assert log_traces & span_traces


def test_spans_form_the_canonical_chain() -> None:
    harness = Harness()
    harness.run(RUN_TICKS)
    spans = harness.spans.get_finished_spans()
    by_trace: dict[int, list] = {}
    for span in spans:
        by_trace.setdefault(span.context.trace_id, []).append(span)

    completed = [
        group
        for group in by_trace.values()
        if {s.name for s in group} >= {"vfx.render_request", "worker.render", "storage.write"}
    ]
    assert completed, "no completed render produced a full span chain"

    group = {s.name: s for s in completed[0]}
    root = group["vfx.render_request"]
    assert group["render.enqueue"].parent.span_id == root.context.span_id
    assert group["worker.render"].parent.span_id == root.context.span_id
    assert group["storage.write"].parent.span_id == group["worker.render"].context.span_id
    assert root.start_time <= group["worker.render"].start_time
    assert root.end_time == group["worker.render"].end_time
    assert root.attributes["render.sim_duration_seconds"] > 0


def test_editorial_review_spans_are_emitted() -> None:
    harness = Harness()
    harness.run(RUN_TICKS)
    reviews = [s for s in harness.spans.get_finished_spans() if s.name == "editorial.review"]
    assert reviews
    assert all(s.attributes["scene.shots"] > 0 for s in reviews)


def test_reset_does_not_break_the_failure_counter() -> None:
    """/sim/reset drops the pipeline count to zero; the counter must not go backwards."""
    harness = Harness()
    harness.run(INJECT_AT)
    harness.engine.inject_render_worker_degradation(5)
    harness.run(RUN_TICKS - INJECT_AT)
    before = harness.points()[FAILED_COUNTER][-1].value
    assert before > 0

    harness.engine.reset(42)
    harness.run(RUN_TICKS)
    after = harness.points()[FAILED_COUNTER][-1].value
    assert after >= before


def test_trace_ids_survive_a_reset() -> None:
    """Two takes of one seed must not merge into one trace in Tempo."""
    first = Harness()
    first.run(RUN_TICKS)
    second = Harness()
    second.run(RUN_TICKS)

    def traces(harness: Harness) -> set[int]:
        return {s.context.trace_id for s in harness.spans.get_finished_spans()}

    assert traces(first) and traces(second)
    assert not traces(first) & traces(second)


def test_derived_trace_id_keeps_the_sim_id_in_its_low_bits() -> None:
    sim_id = "366eb16f508ebad7"
    derived = derive_trace_id(0xABCDEF0123456789, sim_id)
    assert derived & ((1 << 64) - 1) == int(sim_id, 16)
    assert derived >> 64 == 0xABCDEF0123456789


def test_missing_endpoint_fails_loudly() -> None:
    # _env_file=None or this asserts nothing once a real .env exists: the
    # populated endpoint would be picked up and the raise would never happen.
    settings = TelemetrySettings(_env_file=None, telemetry_enabled=True)
    with pytest.raises(TelemetryConfigError, match="OTEL_EXPORTER_OTLP_ENDPOINT"):
        settings.require_export_target()


def test_console_mode_needs_no_endpoint() -> None:
    settings = TelemetrySettings(_env_file=None, telemetry_enabled=True, telemetry_console=True)
    settings.require_export_target()


def test_disabled_telemetry_is_not_checked() -> None:
    TelemetrySettings(_env_file=None, telemetry_enabled=False).require_export_target()
