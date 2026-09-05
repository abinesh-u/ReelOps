"""Grafana MCP configuration, with a fail-loud contract on both halves.

`AGENTS.md`: a missing token surfaces as an error, not a silent fallback. The
two halves live in different processes — on Cloud Run the agent container holds
the MCP URL and no token, the mcp-grafana sidecar holds the token and no MCP
URL — so they are checked separately.

A client that can list tools but cannot query is the silent half-working state
this exists to prevent, which is why the datasource UID is part of the client
check rather than discovered at run time.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict

_SETUP_DOC = "docs/grafana-setup.md"


class GrafanaConfigError(RuntimeError):
    """Grafana MCP was used without the configuration it needs."""


class GrafanaSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # The stack, and the token the mcp-grafana process authenticates with.
    grafana_url: str = ""
    grafana_service_account_token: str = ""

    # Where that process listens; the agent side needs only this.
    grafana_mcp_url: str = "http://localhost:8000/mcp"

    # query_prometheus and query_loki_logs both require a datasourceUid.
    # Pinned rather than discovered: discovery would mean re-enabling the
    # `datasource` category for one call per run.
    grafana_prom_datasource_uid: str = ""
    grafana_loki_datasource_uid: str = ""
    # Only the investigator needs this one, so it is not part of the client
    # check: an agent that never queries traces should still start without it.
    grafana_tempo_datasource_uid: str = ""

    # The `project` label every exported metric carries; queries filter on it.
    project_id: str = "reelops-demo"

    def require_mcp_client(self) -> None:
        """Raise unless this process can reach the MCP server *and* query through it."""
        self._require(
            {
                "GRAFANA_MCP_URL": self.grafana_mcp_url,
                "GRAFANA_PROM_DATASOURCE_UID": self.grafana_prom_datasource_uid,
            },
            "Cannot query Grafana through MCP",
        )

    def require_mcp_server(self) -> None:
        """Raise unless this process can start mcp-grafana against the stack."""
        self._require(
            {
                "GRAFANA_URL": self.grafana_url,
                "GRAFANA_SERVICE_ACCOUNT_TOKEN": self.grafana_service_account_token,
            },
            "Cannot start mcp-grafana",
        )

    @staticmethod
    def _require(values: dict[str, str], problem: str) -> None:
        missing = [name for name, value in values.items() if not value.strip()]
        if missing:
            raise GrafanaConfigError(f"{problem}: {', '.join(missing)} is empty. See {_SETUP_DOC}.")


class ModelConfigError(RuntimeError):
    """Gemini was used without the Vertex configuration it needs."""


class ModelSettings(BaseSettings):
    """Which Gemini model to call, and whether it can authenticate.

    `google.genai.Client` (built internally by ADK's `Gemini` model class)
    reads `GOOGLE_GENAI_USE_VERTEXAI`/`GOOGLE_CLOUD_PROJECT`/
    `GOOGLE_CLOUD_LOCATION` from the environment itself — this class is a
    fail-loud pre-check called before `LlmAgent` construction, not a value
    threaded into the client, exactly parallel to how `grafana_toolset()`
    calls `GrafanaSettings.require_mcp_client()` first.
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    gemini_model: str = "gemini-2.5-flash"
    google_genai_use_vertexai: bool = False
    google_cloud_project: str = ""
    google_cloud_location: str = ""

    def require_vertex(self) -> None:
        """Raise unless Vertex-mode Gemini has what it needs to authenticate."""
        if not self.google_genai_use_vertexai:
            return  # AI Studio mode reads GOOGLE_API_KEY directly; not this project's path.
        missing = [
            name
            for name, value in {
                "GOOGLE_CLOUD_PROJECT": self.google_cloud_project,
                "GOOGLE_CLOUD_LOCATION": self.google_cloud_location,
            }.items()
            if not value.strip()
        ]
        if missing:
            raise ModelConfigError(f"Cannot call Gemini via Vertex: {', '.join(missing)} is empty.")
