"""The Grafana MCP tool budget, as data.

`AGENTS.md` sets a least-privilege budget and `docs/threat-model.md` names
over-privileged Grafana tools as a threat. Two levers enforce it: the server's
`--enabled-tools`/`--disable-write` flags are the boundary, and ADK's
`tool_filter` is what each agent is handed. Both are derived from the tables
below, so the boundary and the filters cannot drift apart.

The category tokens are the ones `mcp-grafana --help` accepts, verified against
the 1.3.0 binary.
"""

from itertools import chain
from typing import Literal

AgentName = Literal[
    "supervisor",
    "sentinel",
    "investigator",
    "impact",
    "response",
    "verification",
]

# Category -> the tools ReelOps uses from it. mcp-grafana 1.3.0 enables 23
# categories by default; naming these four drops the other nineteen.
#
# `sift` is deliberately absent. `AGENTS.md` once listed find_error_pattern_logs
# and find_slow_requests on the read path, but both create a Sift investigation,
# so `--disable-write` strips them: a read-only server serves neither. What
# remains of the category (list_sift_investigations, get_sift_investigation,
# get_sift_analysis) is read-only but unused, so the category stays off.
# Log-pattern evidence comes from query_loki_patterns instead.
READ_TOOLS_BY_CATEGORY: dict[str, tuple[str, ...]] = {
    "incident": ("list_incidents", "get_incident"),
    "loki": ("query_loki_logs", "query_loki_patterns"),
    "oncall": ("get_current_oncall_users",),
    "prometheus": ("query_prometheus", "list_prometheus_metric_names"),
}

# Phase 6 only, and only from a second server started without --disable-write.
# No entry here may appear in AGENT_TOOLS while the read path is the only one.
WRITE_TOOLS: tuple[str, ...] = (
    "create_incident",
    "update_incident",
    "add_activity_to_incident",
)

READ_TOOLS: tuple[str, ...] = tuple(sorted(chain.from_iterable(READ_TOOLS_BY_CATEGORY.values())))

# Sorted so the generated string is stable and can be asserted verbatim against
# the launch command in docs/grafana-setup.md.
ENABLED_TOOLS_FLAG: str = "--enabled-tools=" + ",".join(sorted(READ_TOOLS_BY_CATEGORY))

# Derived from the access column of the agent table in `AGENTS.md`. The
# supervisor orchestrates and holds no tools; impact's Firestore read is not MCP.
AGENT_TOOLS: dict[AgentName, tuple[str, ...]] = {
    "supervisor": (),
    "sentinel": ("query_prometheus", "list_prometheus_metric_names"),
    "investigator": ("query_prometheus", "query_loki_logs", "query_loki_patterns"),
    "impact": ("query_prometheus",),
    "response": (
        "query_prometheus",
        "list_incidents",
        "get_incident",
        "get_current_oncall_users",
    ),
    "verification": ("query_prometheus", "query_loki_logs"),
}


def tools_for(agent: AgentName) -> tuple[str, ...]:
    """The tools `agent` may see. Empty means the agent gets no toolset at all."""
    return AGENT_TOOLS[agent]
