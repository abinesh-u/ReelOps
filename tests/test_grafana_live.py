"""The Phase 3 gate: a real MCP tool call against live telemetry.

Opt-in with `REELOPS_LIVE_MCP=1`, and only that — keying off `GRAFANA_URL`
would make an ordinary `uv run pytest -q` reach for a server that is not
running once `.env` is populated.

When the flag *is* set, incomplete configuration fails rather than skips. A gate
that quietly excuses itself is the same bug as an empty series reading as a
healthy system.

Prerequisites, all in docs/grafana-setup.md: mcp-grafana running, and the
simulator emitting *right now* — `TELEMETRY_ENABLED=true SIM_SPEED=20 uv run
python -m simulator`. The freshness assertion means a finished run does not
count.
"""

import logging
import os
import time
from collections.abc import AsyncIterator
from typing import Any

import pytest
import pytest_asyncio

from agents.config import GrafanaSettings
from agents.grafana_mcp import (
    call_tool,
    grafana_toolset,
    newest_sample_epoch,
    require_series,
)
from agents.tool_budget import READ_TOOLS, WRITE_TOOLS, tools_for

pytestmark = pytest.mark.skipif(
    os.getenv("REELOPS_LIVE_MCP") != "1",
    reason="live gate; set REELOPS_LIVE_MCP=1 with mcp-grafana and the simulator running",
)

logger = logging.getLogger(__name__)

# Wide enough to survive a slow start, tight enough that yesterday's data fails.
QUERY_WINDOW = "now-15m"
MAX_SAMPLE_AGE_SECONDS = 300


@pytest.fixture(scope="module")
def settings() -> GrafanaSettings:
    return GrafanaSettings()


# pytest_asyncio.fixture, not pytest.fixture: no asyncio_mode is configured, so
# a plain async fixture errors at setup rather than running.
@pytest_asyncio.fixture
async def sentinel_tools(settings: GrafanaSettings) -> AsyncIterator[Any]:
    toolset = grafana_toolset("sentinel", settings)
    try:
        yield toolset
    finally:
        await toolset.close()


def test_live_settings_are_complete(settings: GrafanaSettings) -> None:
    """Fail, do not skip: the flag was set, so the operator intends to run the gate."""
    settings.require_mcp_client()
    settings.require_mcp_server()


@pytest.mark.asyncio
async def test_server_exposes_the_read_budget_and_no_writes(settings: GrafanaSettings) -> None:
    """The server-side boundary: every budgeted tool present, every write tool gone."""
    from google.adk.tools.mcp_tool.mcp_toolset import (
        McpToolset,
        StreamableHTTPConnectionParams,
    )

    toolset = McpToolset(
        connection_params=StreamableHTTPConnectionParams(url=settings.grafana_mcp_url)
    )
    try:
        names = {tool.name for tool in await toolset.get_tools()}
    finally:
        await toolset.close()

    logger.info("mcp-grafana exposes %d tools: %s", len(names), sorted(names))
    assert set(READ_TOOLS) <= names, f"missing from the server: {set(READ_TOOLS) - names}"
    assert names.isdisjoint(WRITE_TOOLS), "--disable-write is not in effect"


@pytest.mark.asyncio
async def test_sentinel_filter_is_enforced(sentinel_tools: Any) -> None:
    """The client-side lever. Only a live server can prove tool_filter works."""
    names = {tool.name for tool in await sentinel_tools.get_tools()}
    assert names == set(tools_for("sentinel"))


@pytest.mark.asyncio
async def test_metric_names_reach_grafana(sentinel_tools: Any, settings: GrafanaSettings) -> None:
    """Ingest happened at all — and the histogram carries no bare-name series."""
    payload = await call_tool(
        sentinel_tools,
        "list_prometheus_metric_names",
        {"datasourceUid": settings.grafana_prom_datasource_uid, "regex": "render_.*"},
    )
    names = payload if isinstance(payload, list) else payload.get("data", payload)
    logger.info("render_* metric names in Mimir: %s", names)

    assert "render_queue_depth" in names
    assert "render_job_duration_seconds_bucket" in names, (
        "the duration histogram exports only _bucket/_sum/_count; a query against "
        "the bare name returns empty, which reads as a healthy system"
    )


@pytest.mark.asyncio
async def test_render_queue_depth_returns_a_live_series(
    sentinel_tools: Any, settings: GrafanaSettings
) -> None:
    """THE PHASE 3 GATE. A PromQL query through MCP returning live, non-empty data."""
    expr = f'render_queue_depth{{project="{settings.project_id}"}}'

    # call_tool raises on an error envelope, so reaching the next line means the
    # call itself succeeded rather than failing into a returned dict.
    payload = await call_tool(
        sentinel_tools,
        "query_prometheus",
        {
            "datasourceUid": settings.grafana_prom_datasource_uid,
            "expr": expr,
            "queryType": "range",
            "startTime": QUERY_WINDOW,
            "endTime": "now",
            "stepSeconds": 5,
        },
    )

    series = require_series(payload, expr)
    logger.info("%s returned %d series", expr, len(series))

    newest = max(newest_sample_epoch(entry) for entry in series)
    longest = max(len(entry.get("values") or []) for entry in series)

    assert longest >= 2, f"only {longest} datapoint(s): a stale point, not a live stream"

    labels = {
        key: value
        for entry in series
        for key, value in (entry.get("metric") or {}).items()
        if key == "project"
    }
    assert labels.get("project") == settings.project_id, (
        f"series carries project={labels.get('project')!r}, expected "
        f"{settings.project_id!r} — PROJECT_ID disagrees with what was exported"
    )

    age = time.time() - newest
    assert age < MAX_SAMPLE_AGE_SECONDS, (
        f"newest sample is {age:.0f}s old; the simulator is not currently emitting. "
        "The gate must run during a take, not after one."
    )


@pytest.mark.asyncio
async def test_investigator_can_fetch_a_trace(settings: GrafanaSettings) -> None:
    """The third leg of the evidence chain: metrics, logs, and now spans.

    The tempo_* tools are proxied from Grafana Cloud's own MCP server, so they
    appear only against a real stack — a local Grafana serves none of them.
    That makes this the one budget entry no offline test can cover.
    """
    toolset = grafana_toolset("investigator", settings)
    try:
        found = await call_tool(
            toolset,
            "tempo_traceql-search",
            {
                "datasourceUid": settings.grafana_tempo_datasource_uid,
                "query": '{resource.service.name="reelops-simulator"}',
            },
        )
        traces = found.get("traces") if isinstance(found, dict) else None
        assert traces, "no simulator traces in Tempo; check the span exporter"

        trace_id = traces[0]["traceID"]
        detail = await call_tool(
            toolset,
            "tempo_get-trace",
            {"datasourceUid": settings.grafana_tempo_datasource_uid, "trace_id": trace_id},
        )
    finally:
        await toolset.close()

    logger.info("fetched trace %s (%d found)", trace_id, len(traces))
    assert len(trace_id) == 32, (
        f"expected a 128-bit trace id, got {len(trace_id)} hex chars — the "
        "exporter's per-process nonce prepends 64 bits to the simulator's own id"
    )
    assert detail, "tempo_get-trace returned nothing for a trace search had just listed"


@pytest.mark.asyncio
async def test_simulator_logs_reach_loki(settings: GrafanaSettings) -> None:
    """The stream selector only — the part that does not depend on structured metadata."""
    toolset = grafana_toolset("investigator", settings)
    try:
        payload = await call_tool(
            toolset,
            "query_loki_logs",
            {
                "datasourceUid": settings.grafana_loki_datasource_uid,
                "logql": '{service_name="reelops-simulator"}',
                "startRfc3339": QUERY_WINDOW,
                "limit": 10,
            },
        )
    finally:
        await toolset.close()

    entries = payload if isinstance(payload, list) else payload.get("data", payload)
    assert entries, "no log lines in Loki; check the OTLP log exporter"


@pytest.mark.asyncio
async def test_loki_structured_metadata_filter(settings: GrafanaSettings) -> None:
    """The dashboard's log panel query.

    Separate from the gate on purpose: `| event =~` assumes Grafana Cloud lands
    OTLP log attributes as queryable structured metadata. If that assumption is
    wrong, the failure should read as "fix the log panel in
    dashboards/reelops-render.json", not as a broken exporter.
    """
    toolset = grafana_toolset("investigator", settings)
    try:
        payload = await call_tool(
            toolset,
            "query_loki_logs",
            {
                "datasourceUid": settings.grafana_loki_datasource_uid,
                "logql": (
                    '{service_name="reelops-simulator"} '
                    "| event =~ `render_started|render_completed|job_queued`"
                ),
                "startRfc3339": QUERY_WINDOW,
                "limit": 10,
            },
        )
    finally:
        await toolset.close()

    entries = payload if isinstance(payload, list) else payload.get("data", payload)
    assert entries, (
        "the `| event =~` filter matched nothing. The stream selector works "
        "(see test_simulator_logs_reach_loki), so `event` is not queryable as "
        "structured metadata and the dashboard's log panel needs a different filter."
    )
