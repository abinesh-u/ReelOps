"""Provider wiring, and the only module that knows which exporter is in use.

Production ships OTLP over HTTP. Console and in-memory exporters exist for
local inspection and tests, and are selected here rather than reached for from
the emitter, so the production path never imports a test adapter.
"""

import logging
import uuid
from dataclasses import dataclass

from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk._logs import LoggerProvider, LogRecordProcessor
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor, ConsoleLogExporter
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import (
    ConsoleMetricExporter,
    MetricReader,
    PeriodicExportingMetricReader,
)
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    ConsoleSpanExporter,
    SpanProcessor,
)
from opentelemetry.sdk.trace.sampling import ALWAYS_ON
from opentelemetry.util.re import parse_env_headers

from telemetry.config import TelemetrySettings
from telemetry.instruments import histogram_views

logger = logging.getLogger(__name__)


@dataclass
class Providers:
    meter_provider: MeterProvider
    logger_provider: LoggerProvider
    tracer_provider: TracerProvider

    def force_flush(self) -> None:
        """Push everything buffered. The end of a take is the interesting part."""
        self.meter_provider.force_flush()
        self.logger_provider.force_flush()
        self.tracer_provider.force_flush()

    def shutdown(self) -> None:
        self.force_flush()
        self.meter_provider.shutdown()
        self.logger_provider.shutdown()
        self.tracer_provider.shutdown()


def _resource(settings: TelemetrySettings) -> Resource:
    # service.name and service.instance.id become the `job` and `instance`
    # labels; everything else lands on target_info. The bounded labels agents
    # filter on are set per-metric instead — see telemetry/instruments.py.
    return Resource.create(
        {
            "service.name": settings.otel_service_name,
            "service.instance.id": uuid.uuid4().hex,
            "deployment.environment": settings.deploy_environment,
        }
    )


def _otlp_headers(settings: TelemetrySettings) -> dict[str, str]:
    return dict(parse_env_headers(settings.otel_exporter_otlp_headers.strip(), liberal=True))


def _signal_url(base: str, signal: str) -> str:
    """The HTTP exporters treat an explicit `endpoint=` as the full signal URL.

    Only the env-var path appends `/v1/<signal>`, and settings may come from a
    `.env` file the SDK never reads, so the suffix is added here.
    """
    return f"{base.rstrip('/')}/v1/{signal}"


def build_providers(
    settings: TelemetrySettings,
    *,
    metric_reader: MetricReader | None = None,
    log_processor: LogRecordProcessor | None = None,
    span_processor: SpanProcessor | None = None,
) -> Providers:
    """Build the three providers. Injected components are used as given.

    Tests pass in-memory readers and processors; nothing else changes, so what
    they assert is the same recording path production runs.
    """
    resource = _resource(settings)

    if metric_reader is None:
        exporter = (
            ConsoleMetricExporter()
            if settings.telemetry_console
            else OTLPMetricExporter(
                endpoint=_signal_url(settings.otel_exporter_otlp_endpoint, "metrics"),
                headers=_otlp_headers(settings),
            )
        )
        metric_reader = PeriodicExportingMetricReader(
            exporter, export_interval_millis=settings.otel_export_interval_ms
        )

    if log_processor is None:
        log_exporter = (
            ConsoleLogExporter()
            if settings.telemetry_console
            else OTLPLogExporter(
                endpoint=_signal_url(settings.otel_exporter_otlp_endpoint, "logs"),
                headers=_otlp_headers(settings),
            )
        )
        log_processor = BatchLogRecordProcessor(log_exporter)

    if span_processor is None:
        span_exporter = (
            ConsoleSpanExporter()
            if settings.telemetry_console
            else OTLPSpanExporter(
                endpoint=_signal_url(settings.otel_exporter_otlp_endpoint, "traces"),
                headers=_otlp_headers(settings),
            )
        )
        span_processor = BatchSpanProcessor(span_exporter)

    logger_provider = LoggerProvider(resource=resource)
    logger_provider.add_log_record_processor(log_processor)

    # Spans carry a synthetic remote parent so the simulator's own trace id
    # survives. ParentBased would inherit "not sampled" from that parent and
    # drop every span without raising anything.
    tracer_provider = TracerProvider(resource=resource, sampler=ALWAYS_ON)
    tracer_provider.add_span_processor(span_processor)

    return Providers(
        meter_provider=MeterProvider(
            resource=resource, metric_readers=[metric_reader], views=histogram_views()
        ),
        logger_provider=logger_provider,
        tracer_provider=tracer_provider,
    )
