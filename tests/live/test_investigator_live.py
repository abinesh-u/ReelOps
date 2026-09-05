"""Live gate: Investigator against the real Grafana Cloud stack.

Same two-flag gate as `tests/live/test_sentinel_live.py`. Feeds a hand-built
`AnomalyContract` fixture rather than the Sentinel's live output, so this
test's outcome is independent of what the Sentinel happens to report in the
same run — it only needs live telemetry to exist, not a specific state.
"""

import os
import re

import pytest
from google.adk.runners import InMemoryRunner
from google.genai import types

from agents.config import GrafanaSettings, ModelSettings
from agents.contracts import AnomalyContract, RootCauseContract
from agents.investigator.agent import (
    INVESTIGATOR_APP_NAME,
    INVESTIGATOR_OUTPUT_KEY,
    build_investigator_agent,
)
from tests._adk_events import called_tool

pytestmark = pytest.mark.skipif(
    os.getenv("REELOPS_LIVE_MODEL") != "1" or os.getenv("REELOPS_LIVE_MCP") != "1",
    reason="live gate; set REELOPS_LIVE_MODEL=1 and REELOPS_LIVE_MCP=1, with "
    "mcp-grafana and the simulator both running",
)

FIXTURE_ANOMALY = AnomalyContract(
    anomaly=True,
    severity="high",
    service="render-farm",
    signal="render_workers_available",
    current=7.0,
    baseline=12.0,
    confidence=0.8,
    evidence=["render_workers_available: observed=7 vs baseline_plateau=12"],
)


def test_live_settings_are_complete() -> None:
    """Fail, do not skip: both flags were set, so the operator intends to run this."""
    ModelSettings().require_vertex()
    GrafanaSettings().require_mcp_client()


@pytest.mark.asyncio
async def test_investigator_produces_an_evidenced_hypothesis() -> None:
    grafana_settings = GrafanaSettings()
    agent = build_investigator_agent(grafana_settings, ModelSettings())

    events = []
    async with InMemoryRunner(agent=agent, app_name=INVESTIGATOR_APP_NAME) as runner:
        session = await runner.session_service.create_session(
            app_name=INVESTIGATOR_APP_NAME, user_id="reelops"
        )
        message = types.Content(
            role="user",
            parts=[
                types.Part(
                    text=(
                        f"project_id={grafana_settings.project_id}\n"
                        f"prometheus_datasource_uid={grafana_settings.grafana_prom_datasource_uid}\n"
                        f"loki_datasource_uid={grafana_settings.grafana_loki_datasource_uid}\n"
                        f"tempo_datasource_uid={grafana_settings.grafana_tempo_datasource_uid}\n"
                        f"sentinel flagged: service={FIXTURE_ANOMALY.service} "
                        f"signal={FIXTURE_ANOMALY.signal} severity={FIXTURE_ANOMALY.severity} "
                        f"current={FIXTURE_ANOMALY.current} baseline={FIXTURE_ANOMALY.baseline}\n"
                        "Confirm this independently before treating it as fact, "
                        "then follow the evidence sequence."
                    )
                )
            ],
        )
        async for event in runner.run_async(
            user_id="reelops", session_id=session.id, new_message=message
        ):
            events.append(event)

        final = await runner.session_service.get_session(
            app_name=INVESTIGATOR_APP_NAME, user_id="reelops", session_id=session.id
        )
        raw = final.state[INVESTIGATOR_OUTPUT_KEY]

    result = RootCauseContract.model_validate(raw)

    assert 0.0 <= result.confidence <= 1.0
    assert result.evidence, "no evidence cited — a hypothesis with no query behind it"

    assert called_tool(events, "query_prometheus"), (
        "investigator never re-confirmed the metric via query_prometheus — the "
        "first, mandatory step of the evidence sequence regardless of outcome"
    )

    # This fixture claims a degradation, but runs against whatever state the
    # simulator actually happens to be in — which may be healthy. When
    # re-confirming the metric refutes the premise, correctly stopping there
    # rather than hunting logs for a fault that is not real is the prompt's
    # own "unsupported claims" guidance working as intended, so the deeper
    # evidence-sequence stages are not asserted here unconditionally.
    # tests/live/test_golden_scenario_live.py exercises the full sequence against
    # telemetry it has actually put into a degraded state, where the deeper
    # stages are the correct behaviour rather than an optional one.

    # The strictest check, per docs/agents.md's own emphasis: a hypothesis may
    # cite a span only if the agent actually fetched one. Look for something
    # that reads as an actual trace/span id, not just the word "trace" —
    # "a TraceQL search returned no results" mentions "trace" too, and
    # correctly did not fetch anything because there was nothing to fetch.
    hex_id = re.compile(r"\b[0-9a-f]{16,32}\b", re.IGNORECASE)
    mentions_a_span = any(hex_id.search(entry) for entry in result.evidence)
    if mentions_a_span:
        assert called_tool(events, "tempo_get-trace"), (
            "evidence references a trace/span, but tempo_get-trace was never called"
        )
