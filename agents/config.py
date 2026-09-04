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
            raise GrafanaConfigError(
                f"{problem}: {', '.join(missing)} is empty. "
                f"Run infra/setup-grafana.sh, or see {_SETUP_DOC}."
            )
