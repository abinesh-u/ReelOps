"""Snapshot, events and job timelines to OTLP.

Recording is pushed from the simulation's own event loop, never pulled by an
observable-instrument callback. `PeriodicExportingMetricReader` runs callbacks
on its own thread, and `build_snapshot` iterates the queue deque and the scenes
dict while `tick()` mutates both — a callback would raise "mutated during
iteration" intermittently, on a thread where it is easy to miss. This task
awaits only between records, so it can never interleave with a tick.

Every record carries wall-clock time. Sim time starts months away from now and
Mimir, Loki and Tempo all reject samples that far outside their window, so sim
time is mapped onto the real clock, compressed by `SIM_SPEED`, and the true sim
figures travel as attributes. One consequence worth stating: tick state is
reproducible, but the exported series is not, because export cadence is
wall-clock. No test should assert series equality across runs.
"""

import asyncio
import logging
import time
import uuid
from datetime import datetime

from opentelemetry import trace
from opentelemetry._logs import SeverityNumber
from opentelemetry.trace import NonRecordingSpan, SpanContext, TraceFlags

from simulator.engine import SimulationEngine
from telemetry.config import TelemetrySettings
from telemetry.instruments import (
    JOB_TYPE_RENDER,
    RENDER_SERVICE,
    Instruments,
    build_instruments,
)
from telemetry.providers import Providers, build_providers
from telemetry.spans import (
    derive_trace_id,
    emit_job_trace,
    emit_review_trace,
    job_anchor_span_id,
)

logger = logging.getLogger(__name__)

_SEVERITY = {
    "info": (SeverityNumber.INFO, "INFO"),
    "warn": (SeverityNumber.WARN, "WARN"),
    "error": (SeverityNumber.ERROR, "ERROR"),
}

INSTRUMENTATION_SCOPE = "reelops.simulator"


class TelemetryEmitter:
    def __init__(
        self,
        engine: SimulationEngine,
        providers: Providers,
        settings: TelemetrySettings | None = None,
    ) -> None:
        self._engine = engine
        self._providers = providers
        self._settings = settings or TelemetrySettings()
        self._instruments: Instruments = build_instruments(
            providers.meter_provider.get_meter(INSTRUMENTATION_SCOPE),
            project=self._settings.project_id,
            environment=self._settings.deploy_environment,
        )
        self._logger = providers.logger_provider.get_logger(INSTRUMENTATION_SCOPE)
        self._tracer = providers.tracer_provider.get_tracer(INSTRUMENTATION_SCOPE)

        # Unique per process, so re-shooting a take with the same seed produces
        # fresh trace ids instead of merging into the previous run's traces.
        self._run_nonce = uuid.uuid4().int >> 64
        self._base_attributes = {
            "project": self._settings.project_id,
            "service": RENDER_SERVICE,
            "environment": self._settings.deploy_environment,
            "job_type": JOB_TYPE_RENDER,
        }
        self._task: asyncio.Task[None] | None = None
        self._anchor()
        self._reset_cursors()

    # -- clock ------------------------------------------------------------

    def _anchor(self) -> None:
        self._wall_origin_ns = time.time_ns()
        self._sim_origin = self._engine.sim_time

    def _wall_ns(self, sim_time: datetime) -> int:
        offset = (sim_time - self._sim_origin).total_seconds() / self._engine.settings.sim_speed
        return self._wall_origin_ns + int(offset * 1_000_000_000)

    def _reset_cursors(self) -> None:
        self._events_cursor = 0
        self._durations_cursor = 0
        self._latencies_cursor = 0
        self._attempts_cursor = 0
        self._reviews_cursor = 0
        self._failed_seen = 0
        self._last_tick = 0

    # -- lifecycle --------------------------------------------------------

    async def start(self) -> None:
        interval = min(1000, self._settings.otel_export_interval_ms) / 1000
        self._task = asyncio.create_task(self._loop(interval))
        logger.info(
            "telemetry emitting every %ss, exporting every %sms",
            interval,
            self._settings.otel_export_interval_ms,
        )

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        # The end of a take is the interesting part; a buffered batch would lose it.
        self.record_once()
        self._providers.shutdown()

    async def _loop(self, interval: float) -> None:
        while True:
            self.record_once()
            await asyncio.sleep(interval)

    # -- recording --------------------------------------------------------

    def record_once(self) -> None:
        """One pass over every signal. Synchronous, so tests drive it directly."""
        if self._engine.clock.tick_index < self._last_tick:
            # /sim/reset rebuilt the pipeline: streams restart at zero and the
            # failure count drops, which a counter would read as a negative delta.
            self._reset_cursors()
            self._anchor()
        self._last_tick = self._engine.clock.tick_index

        self._record_metrics()
        self._record_traces()
        self._record_logs()

    def _record_metrics(self) -> None:
        pipeline = self._engine.pipeline
        instruments = self._instruments
        for name, value in self._engine.snapshot().metrics.items():
            gauge = instruments.gauges.get(name)
            if gauge is not None:
                gauge.set(value, instruments.gauge_attributes[name])

        # Recorded even when the delta is zero: a counter that has never been
        # added to has no series at all, and an empty PromQL result reads as a
        # healthy farm rather than a missing metric.
        failed = pipeline.jobs_failed_total
        instruments.jobs_failed.add(
            max(failed - self._failed_seen, 0), instruments.render_attributes
        )
        self._failed_seen = failed

        durations, self._durations_cursor = pipeline.render_durations.since(self._durations_cursor)
        for duration in durations:
            instruments.render_duration.record(duration, instruments.render_attributes)

        latencies, self._latencies_cursor = pipeline.vfx_latencies.since(self._latencies_cursor)
        for latency in latencies:
            instruments.delivery_latency.record(latency, instruments.vfx_attributes)

    def _record_traces(self) -> None:
        pipeline = self._engine.pipeline
        attempts, self._attempts_cursor = pipeline.job_attempts.since(self._attempts_cursor)
        for attempt in attempts:
            emit_job_trace(
                self._tracer, attempt, self._run_nonce, self._wall_ns, self._base_attributes
            )
        reviews, self._reviews_cursor = pipeline.scene_reviews.since(self._reviews_cursor)
        for review in reviews:
            emit_review_trace(
                self._tracer, review, self._run_nonce, self._wall_ns, self._base_attributes
            )

    def _record_logs(self) -> None:
        events, self._events_cursor = self._engine.pipeline.event_log.since(self._events_cursor)
        for event in events:
            severity, severity_text = _SEVERITY.get(event.level, _SEVERITY["info"])
            attributes = {
                "event": event.event,
                "service": event.service,
                "project_id": event.project_id,
                "environment": self._settings.deploy_environment,
                "sim_time": event.timestamp.isoformat(),
            }
            for key, value in (
                ("worker_id", event.worker_id),
                ("job_id", event.job_id),
                ("scene_id", event.scene_id),
                ("error_code", event.error_code),
            ):
                if value is not None:
                    attributes[key] = value
            if event.duration_ms is not None:
                attributes["duration_ms"] = event.duration_ms

            self._logger.emit(
                timestamp=self._wall_ns(event.timestamp),
                observed_timestamp=time.time_ns(),
                severity_number=severity,
                severity_text=severity_text,
                body=f"{event.event} {event.job_id or event.worker_id or ''}".strip(),
                attributes=attributes,
                context=self._log_context(event.job_id, event.trace_id),
            )

    def _log_context(self, job_id: str | None, sim_trace_id: str | None) -> trace.Context | None:
        """Populate the record's native trace_id — the field Grafana correlates on.

        An attribute of the same name does not drive log-to-trace navigation.
        """
        if not job_id or not sim_trace_id:
            return None
        context = SpanContext(
            trace_id=derive_trace_id(self._run_nonce, sim_trace_id),
            span_id=job_anchor_span_id(job_id),
            is_remote=True,
            trace_flags=TraceFlags(TraceFlags.SAMPLED),
        )
        return trace.set_span_in_context(NonRecordingSpan(context))


def create_emitter(
    engine: SimulationEngine, settings: TelemetrySettings | None = None
) -> TelemetryEmitter | None:
    """The emitter, or `None` when telemetry is switched off.

    Raises rather than returning `None` when it is switched on with nowhere to
    export to — a silent no-op looks exactly like a healthy pipeline.
    """
    settings = settings or TelemetrySettings()
    if not settings.telemetry_enabled:
        return None
    settings.require_export_target()
    return TelemetryEmitter(engine, build_providers(settings), settings)
