"""Telemetry configuration, with a fail-loud export target.

`AGENTS.md`: a missing token surfaces as an error, not a silent fallback. An
exporter pointed at nothing still accepts every record and drops it, so the
check happens once at startup rather than never.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class TelemetryConfigError(RuntimeError):
    """Telemetry was switched on without somewhere to send it."""


class TelemetrySettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    telemetry_enabled: bool = False
    # Print to stdout instead of shipping. For local work without a Grafana stack.
    telemetry_console: bool = False

    # Copied from the Grafana Cloud OpenTelemetry tile; see docs/grafana-setup.md.
    otel_exporter_otlp_endpoint: str = ""
    otel_exporter_otlp_headers: str = ""
    otel_service_name: str = "reelops-simulator"

    # Real milliseconds between exports. The SDK default of 60s would produce a
    # single point across a 90-second demo window.
    otel_export_interval_ms: int = 5000
    deploy_environment: str = "demo"
    project_id: str = "reelops-demo"

    def require_export_target(self) -> None:
        if not self.telemetry_enabled or self.telemetry_console:
            return
        missing = [
            name
            for name, value in (
                ("OTEL_EXPORTER_OTLP_ENDPOINT", self.otel_exporter_otlp_endpoint),
                ("OTEL_EXPORTER_OTLP_HEADERS", self.otel_exporter_otlp_headers),
            )
            if not value.strip()
        ]
        if missing:
            raise TelemetryConfigError(
                f"TELEMETRY_ENABLED is set but {', '.join(missing)} is empty. "
                "Copy the values from your Grafana Cloud OpenTelemetry tile "
                "(docs/grafana-setup.md), or set TELEMETRY_CONSOLE=true to print locally."
            )
