"""Offline cover for Sentinel's construction. No live model or MCP server:
`McpToolset` connects lazily (inside `get_tools()`, not `__init__` — see
`agents/grafana_mcp.py`), so building the agent needs no network.
"""

import pytest

from agents.config import GrafanaConfigError, GrafanaSettings, ModelConfigError, ModelSettings
from agents.contracts import AnomalyContract
from agents.sentinel.agent import SENTINEL_OUTPUT_KEY, build_sentinel_agent
from agents.tool_budget import tools_for


def grafana_settings(**overrides: str) -> GrafanaSettings:
    return GrafanaSettings(_env_file=None, **overrides)


def model_settings(**overrides: object) -> ModelSettings:
    return ModelSettings(_env_file=None, **overrides)


def complete_grafana_settings() -> GrafanaSettings:
    return grafana_settings(
        grafana_mcp_url="http://localhost:8000/mcp",
        grafana_prom_datasource_uid="prom-uid",
    )


def complete_model_settings() -> ModelSettings:
    return model_settings(
        google_genai_use_vertexai=True,
        google_cloud_project="reelops-agentic-cinema",
        google_cloud_location="us-central1",
    )


def test_build_sentinel_agent_returns_the_expected_shape() -> None:
    agent = build_sentinel_agent(complete_grafana_settings(), complete_model_settings())

    assert agent.name == "sentinel"
    assert agent.output_schema is AnomalyContract
    assert agent.output_key == SENTINEL_OUTPUT_KEY
    assert len(agent.tools) == 1
    assert agent.tools[0].tool_filter == list(tools_for("sentinel"))


def test_build_sentinel_agent_raises_without_grafana_config() -> None:
    with pytest.raises(GrafanaConfigError):
        build_sentinel_agent(grafana_settings(), complete_model_settings())


def test_build_sentinel_agent_raises_without_vertex_config() -> None:
    with pytest.raises(ModelConfigError):
        build_sentinel_agent(
            complete_grafana_settings(),
            model_settings(
                google_genai_use_vertexai=True,
                google_cloud_project="",
                google_cloud_location="",
            ),
        )
