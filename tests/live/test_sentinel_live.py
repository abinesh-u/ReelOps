"""Live gate: Sentinel against the real Grafana Cloud stack.

Needs both `REELOPS_LIVE_MODEL=1` (a real Gemini/Vertex call) and
`REELOPS_LIVE_MCP=1` (a real MCP server + simulator), and fails rather than
skips once both are set, matching `tests/live/test_grafana_live.py`'s convention.

No assertion here depends on the simulator being in any particular health
state — `tests/live/test_golden_scenario_live.py` may run before or after
this file and leaves the simulator faulted, so this test only checks that a
real run produces a valid, evidenced verdict backed by an actual tool call,
not that the verdict is `anomaly=False`.

Runs the agent directly (not through `run_sentinel`) so the event stream is
available to check a tool was actually called — the same fabrication guard
as `tests/live/test_agent_smoke.py`, now against the real production prompt.
"""

import os

import pytest
from google.adk.runners import InMemoryRunner
from google.genai import types

from agents.config import GrafanaSettings, ModelSettings
from agents.contracts import AnomalyContract
from agents.sentinel.agent import SENTINEL_APP_NAME, SENTINEL_OUTPUT_KEY, build_sentinel_agent
from tests._adk_events import called_tool

pytestmark = pytest.mark.skipif(
    os.getenv("REELOPS_LIVE_MODEL") != "1" or os.getenv("REELOPS_LIVE_MCP") != "1",
    reason="live gate; set REELOPS_LIVE_MODEL=1 and REELOPS_LIVE_MCP=1, with "
    "mcp-grafana and the simulator both running",
)


def test_live_settings_are_complete() -> None:
    """Fail, do not skip: both flags were set, so the operator intends to run this."""
    ModelSettings().require_vertex()
    GrafanaSettings().require_mcp_client()


@pytest.mark.asyncio
async def test_sentinel_produces_an_evidenced_verdict() -> None:
    grafana_settings = GrafanaSettings()
    agent = build_sentinel_agent(grafana_settings, ModelSettings())

    events = []
    async with InMemoryRunner(agent=agent, app_name=SENTINEL_APP_NAME) as runner:
        session = await runner.session_service.create_session(
            app_name=SENTINEL_APP_NAME, user_id="reelops"
        )
        message = types.Content(
            role="user",
            parts=[
                types.Part(
                    text=f"project_id={grafana_settings.project_id}\n"
                    f"prometheus_datasource_uid={grafana_settings.grafana_prom_datasource_uid}"
                )
            ],
        )
        async for event in runner.run_async(
            user_id="reelops", session_id=session.id, new_message=message
        ):
            events.append(event)

        final = await runner.session_service.get_session(
            app_name=SENTINEL_APP_NAME, user_id="reelops", session_id=session.id
        )
        raw = final.state[SENTINEL_OUTPUT_KEY]

    result = AnomalyContract.model_validate(raw)

    assert isinstance(result.anomaly, bool)
    assert 0.0 <= result.confidence <= 1.0
    assert result.evidence, "no evidence cited — a verdict with no query behind it"

    assert called_tool(events, "query_prometheus"), (
        "sentinel produced a schema-valid verdict but never called "
        "query_prometheus — see the fallback pattern in the Phase 4 plan"
    )
