"""Offline cover for the Grafana MCP wiring.

Everything here runs without a Grafana stack, a token, or a running server. The
canned payloads below stand in for the mock adapter `AGENTS.md` asks for: they
live in the test module, so no production path can reach them.

`GrafanaSettings` reads `.env`, so every settings test passes `_env_file=None`.
Without it, a populated `.env` would supply the values these tests assert are
missing, and they would quietly stop testing anything.
"""

from itertools import chain
from pathlib import Path

import pytest

from agents.config import GrafanaConfigError, GrafanaSettings
from agents.grafana_mcp import (
    GrafanaToolError,
    grafana_toolset,
    newest_sample_epoch,
    require_series,
    tool_payload,
)
from agents.tool_budget import (
    AGENT_TOOLS,
    ENABLED_TOOLS_FLAG,
    READ_TOOLS,
    WRITE_TOOLS,
    tools_for,
)

SETUP_DOC = Path(__file__).resolve().parent.parent / "docs" / "grafana-setup.md"

# CallToolResult.model_dump(...) as ADK hands it back. The error shapes matter
# most: ADK returns MCP failures rather than raising them.
ERROR_ENVELOPE = {"error": "MCP tool execution failed: 403 Forbidden"}
IS_ERROR_ENVELOPE = {"isError": True, "content": [{"type": "text", "text": "boom"}]}
EMPTY_SERIES = {
    "content": [
        {
            "type": "text",
            "text": '{"status":"success","data":{"resultType":"matrix","result":[]}}',
        }
    ]
}
LIVE_SERIES = {
    "structuredContent": {
        "status": "success",
        "data": {
            "resultType": "matrix",
            "result": [
                {
                    "metric": {"__name__": "render_queue_depth", "project": "reelops-demo"},
                    "values": [[1772798400, "14"], [1772798405, "17"], [1772798410, "21"]],
                }
            ],
        },
    }
}


def settings(**overrides: str) -> GrafanaSettings:
    return GrafanaSettings(_env_file=None, **overrides)


def test_agent_filters_cover_the_read_budget() -> None:
    """No server-side tool goes unused, and no agent reaches outside the budget."""
    assert set(chain.from_iterable(AGENT_TOOLS.values())) == set(READ_TOOLS)


def test_no_agent_reaches_a_write_tool() -> None:
    assert set(chain.from_iterable(AGENT_TOOLS.values())).isdisjoint(WRITE_TOOLS)


def test_supervisor_has_no_toolset() -> None:
    assert tools_for("supervisor") == ()
    with pytest.raises(GrafanaConfigError, match="no Grafana tools"):
        grafana_toolset(
            "supervisor",
            settings(grafana_mcp_url="http://localhost:8000/mcp", grafana_prom_datasource_uid="x"),
        )


def test_enabled_tools_flag_is_documented() -> None:
    """The launch command in the doc and the categories in code cannot drift."""
    assert ENABLED_TOOLS_FLAG in SETUP_DOC.read_text()


def test_missing_datasource_uid_fails_loudly() -> None:
    with pytest.raises(GrafanaConfigError, match="GRAFANA_PROM_DATASOURCE_UID"):
        settings(grafana_prom_datasource_uid="").require_mcp_client()


def test_missing_server_credentials_fail_loudly() -> None:
    with pytest.raises(GrafanaConfigError, match="GRAFANA_SERVICE_ACCOUNT_TOKEN"):
        settings(grafana_url="https://x.grafana.net").require_mcp_server()


@pytest.mark.parametrize("envelope", [ERROR_ENVELOPE, IS_ERROR_ENVELOPE])
def test_error_envelope_raises(envelope: dict) -> None:
    """A failure ADK returned as data must not read as a successful call."""
    from agents.grafana_mcp import _raise_for_error

    with pytest.raises(GrafanaToolError):
        _raise_for_error("query_prometheus", envelope)


def test_empty_series_is_not_a_success() -> None:
    payload = tool_payload(EMPTY_SERIES)
    with pytest.raises(GrafanaToolError, match="no series"):
        require_series(payload, "render_queue_depth")


def test_require_series_returns_the_live_result() -> None:
    series = require_series(tool_payload(LIVE_SERIES), "render_queue_depth")
    assert len(series) == 1
    assert series[0]["metric"]["project"] == "reelops-demo"


def test_newest_sample_epoch_reads_the_last_point() -> None:
    series = require_series(tool_payload(LIVE_SERIES), "render_queue_depth")[0]
    assert newest_sample_epoch(series) == 1772798410


def test_newest_sample_epoch_normalises_milliseconds() -> None:
    assert newest_sample_epoch({"values": [[1772798410000, "21"]]}) == 1772798410
