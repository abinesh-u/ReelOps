"""The Grafana MCP client seam: a filtered toolset, and guards against quiet failure.

Two things make a broken query look like a healthy system, and both are handled
here rather than left to callers:

- ADK converts MCP failures into a *return value* (`except McpError: return
  {"error": ...}`), so a 403 arrives looking like a call that succeeded and
  returned a dict. `call_tool` raises on that envelope.
- An empty PromQL result is a well-formed success. `AGENTS.md`: "a metric that
  returns nothing reads as a healthy system." `require_series` raises rather
  than handing back an empty list.

`agents/tool_budget.py` decides what each agent may see; this module only wires
it up.
"""

import json
import logging
from typing import Any

from google.adk.tools.mcp_tool.mcp_toolset import (
    McpToolset,
    StreamableHTTPConnectionParams,
)

from agents.config import GrafanaConfigError, GrafanaSettings
from agents.tool_budget import AgentName, tools_for

logger = logging.getLogger(__name__)


class GrafanaToolError(RuntimeError):
    """An MCP tool call failed, or returned nothing where data was required."""


def grafana_toolset(agent: AgentName, settings: GrafanaSettings | None = None) -> McpToolset:
    """A toolset exposing only the tools `agent` is budgeted for.

    Raises `GrafanaConfigError` for an agent that holds no tools, so "the
    supervisor has no toolset" is enforced in code rather than in prose.
    """
    settings = settings or GrafanaSettings()
    settings.require_mcp_client()

    allowed = tools_for(agent)
    if not allowed:
        raise GrafanaConfigError(
            f"{agent!r} is budgeted for no Grafana tools and must not be given a toolset; "
            "see the agent table in AGENTS.md."
        )

    # No client-side auth: the service account token lives in the mcp-grafana
    # process, which is reached over loopback or a Cloud Run sidecar.
    return McpToolset(
        connection_params=StreamableHTTPConnectionParams(url=settings.grafana_mcp_url),
        tool_filter=list(allowed),
    )


async def call_tool(toolset: McpToolset, name: str, args: dict[str, Any]) -> Any:
    """Run one MCP tool and return its decoded payload, or raise.

    Raises `GrafanaToolError` if the tool is outside the toolset's filter, or if
    the server reported an error in any of the shapes ADK passes through.
    """
    tools = {tool.name: tool for tool in await toolset.get_tools()}
    if name not in tools:
        raise GrafanaToolError(
            f"{name!r} is not in this toolset ({', '.join(sorted(tools))}). "
            "Either the agent is not budgeted for it, or the server was started "
            "without its category; see agents/tool_budget.py."
        )

    result = await tools[name].run_async(args=args, tool_context=None)
    _raise_for_error(name, result)
    return tool_payload(result)


def _raise_for_error(name: str, result: Any) -> None:
    if not isinstance(result, dict):
        return
    if result.get("isError"):
        raise GrafanaToolError(f"{name} reported isError: {result}")
    if "error" in result:
        # ADK's graceful-error path. A permission failure lands here, not as an
        # exception: check the service account's datasource access first.
        raise GrafanaToolError(f"{name} failed: {result['error']}")


def tool_payload(result: Any) -> Any:
    """Unwrap an MCP CallToolResult into the payload the tool actually returned."""
    if not isinstance(result, dict):
        return result
    if "structuredContent" in result:
        return result["structuredContent"]

    content = result.get("content")
    if isinstance(content, list) and content:
        text = content[0].get("text") if isinstance(content[0], dict) else None
        if isinstance(text, str):
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                return text
    return result


def require_series(payload: Any, expr: str) -> list[dict[str, Any]]:
    """The result list for `expr`, guaranteed non-empty.

    An empty series is the failure this project is most likely to misread, so
    the message names its three causes in the order they should be checked.
    """
    result = _result_list(payload, expr)
    if not result:
        raise GrafanaToolError(
            f"{expr!r} returned no series. In order of likelihood: telemetry never "
            "arrived (check the OTLP exporter and credentials, not MCP — try "
            "list_prometheus_metric_names first); the simulator is not currently "
            "running, so the points are older than the query window; or the "
            "`project` label does not match PROJECT_ID."
        )
    return result


def _result_list(payload: Any, expr: str) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        status = payload.get("status")
        if status is not None and status != "success":
            raise GrafanaToolError(f"{expr!r} returned status {status!r}: {payload}")
        for candidate in (payload.get("result"), payload.get("data")):
            if isinstance(candidate, list):
                return candidate
            if isinstance(candidate, dict) and isinstance(candidate.get("result"), list):
                return candidate["result"]
    raise GrafanaToolError(f"{expr!r} returned an unrecognised payload shape: {payload!r}")


def newest_sample_epoch(series: dict[str, Any]) -> float:
    """The Unix timestamp of the most recent point in one range-query series.

    Freshness is what separates live telemetry from data that arrived once and
    has been sitting in Mimir ever since.
    """
    points = series.get("values") or series.get("value") or []
    if (
        isinstance(points, (list, tuple))
        and points
        and not isinstance(points[0], (list, tuple, dict))
    ):
        # A single instant-query sample: [timestamp, value].
        points = [points]

    timestamps = [_point_epoch(point) for point in points]
    timestamps = [ts for ts in timestamps if ts is not None]
    if not timestamps:
        raise GrafanaToolError(f"series carried no readable timestamps: {series!r}")
    return max(timestamps)


def _point_epoch(point: Any) -> float | None:
    if isinstance(point, (list, tuple)) and point:
        candidate = point[0]
    elif isinstance(point, dict):
        candidate = point.get("timestamp", point.get("time"))
    else:
        return None
    try:
        epoch = float(candidate)
    except (TypeError, ValueError):
        return None
    # Grafana's Go model reports milliseconds; the Prometheus API reports seconds.
    return epoch / 1000 if epoch > 1e11 else epoch
