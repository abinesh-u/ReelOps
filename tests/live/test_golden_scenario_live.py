"""The Phase 4 integration checkpoint: inject the golden-scenario fault, then
confirm Sentinel and Investigator independently reach it through telemetry
alone — neither is told the fault label.

Needs `REELOPS_LIVE_MODEL=1`, `REELOPS_LIVE_MCP=1`, and the simulator's HTTP
API reachable on `SIMULATOR_URL` (default `http://localhost:8090`) so this
test can call `/sim/inject/render-worker-degradation` itself.

Qualitative only, by design: `docs/telemetry-contract.md` documents that
export cadence is wall-clock, so exact metric values are not reproducible
run to run. This test checks the *shape* of the result — anomaly true, a
render-pipeline signal, a worker-degradation-shaped root cause — not exact
figures, and does not score against `evals/scenarios.yaml`'s ground truth
vocabulary (that scorer is Phase 9).

Leaves the simulator in its faulted state afterward — matching how
`docs/grafana-setup.md`'s "leave it running" pattern already works for the
live MCP gate.

Recovers to the healthy worker ceiling before injecting, so the additive
fault injector (repeated calls degrade further currently-healthy workers
rather than resetting) doesn't make this compound across runs. That guards
the *current* reading, but the Sentinel's own baseline is a 30-60 sim-minute
lookback (90-180 real seconds at the documented `SIM_SPEED=20`) — running
this test twice back to back can still leave a just-recovered, near-empty
plateau inside that window and produce a spurious `anomaly=False`. Space
repeated runs a few minutes apart in real time if you hit that.
"""

import asyncio
import os
import time
from collections.abc import Callable

import httpx
import pytest

from agents.config import GrafanaSettings
from agents.grafana_mcp import GrafanaToolError, call_tool, grafana_toolset, require_series
from agents.investigator.agent import run_investigator
from agents.sentinel.agent import run_sentinel

pytestmark = pytest.mark.skipif(
    os.getenv("REELOPS_LIVE_MODEL") != "1" or os.getenv("REELOPS_LIVE_MCP") != "1",
    reason="live gate; set REELOPS_LIVE_MODEL=1 and REELOPS_LIVE_MCP=1, with "
    "mcp-grafana and the simulator both running",
)

SIMULATOR_URL = os.getenv("SIMULATOR_URL", "http://localhost:8090")
FAULT_PROPAGATION_TIMEOUT_SECONDS = 90
FAULT_PROPAGATION_POLL_SECONDS = 5
# simulator/config.py's SimulatorSettings.render_workers default — the fleet
# size a healthy run holds steady at. The injector is additive (each call
# degrades further currently-healthy workers rather than resetting), so this
# test recovers to this ceiling first; otherwise repeated runs compound and
# the scenario drifts away from the one docs/golden-scenario.md describes.
HEALTHY_WORKER_CEILING = 12


def test_simulator_is_reachable() -> None:
    """Fail, do not skip: both flags were set, so the operator intends to run this."""
    response = httpx.get(f"{SIMULATOR_URL}/healthz", timeout=5)
    response.raise_for_status()


@pytest.mark.asyncio
async def test_golden_scenario_is_detected_end_to_end() -> None:
    grafana_settings = GrafanaSettings()

    # Recover to the healthy ceiling first: the injector is additive, so
    # without this step repeated runs compound (12 -> 7 -> ... -> 0) instead
    # of reproducing the documented 5-workers-down scenario each time.
    async with httpx.AsyncClient() as client:
        response = await client.post(f"{SIMULATOR_URL}/sim/recover", timeout=5)
    response.raise_for_status()
    await _wait_for_workers_available(
        grafana_settings, lambda available: available >= HEALTHY_WORKER_CEILING
    )

    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{SIMULATOR_URL}/sim/inject/render-worker-degradation",
            json={"workers": 5},
            timeout=5,
        )
    response.raise_for_status()

    await _wait_for_workers_available(
        grafana_settings, lambda available: available < HEALTHY_WORKER_CEILING
    )

    anomaly = await run_sentinel(grafana_settings.project_id, grafana_settings=grafana_settings)
    assert anomaly.anomaly is True, (
        f"sentinel did not flag the injected fault: {anomaly.model_dump()}"
    )
    assert "render" in anomaly.service.lower() or "render" in anomaly.signal.lower(), (
        f"sentinel flagged an anomaly but not on the render pipeline: {anomaly.model_dump()}"
    )

    root_cause = await run_investigator(
        grafana_settings.project_id, anomaly, grafana_settings=grafana_settings
    )
    # agents/investigator/prompts.py asks the investigator to pick from a small, stable
    # vocabulary rather than free English, exactly so this can be an equality
    # check instead of a substring guess — and so it lines up with
    # evals/scenarios.yaml's ground_truth.root_cause for this fault.
    assert root_cause.category in {"worker_degradation", "worker_unavailable"}, (
        f"investigator's root cause does not look worker-degradation-shaped: {root_cause.model_dump()}"
    )
    assert root_cause.evidence, "investigator's hypothesis cites no evidence"


async def _wait_for_workers_available(
    settings: GrafanaSettings, satisfied: Callable[[float], bool]
) -> None:
    """Poll Prometheus directly (not through an agent) until `satisfied`
    holds for the minimum observed value, so the agent run below (or the
    next step of this test) queries a state that has actually changed.

    Uses an instant query at `endTime=now`, so a moment where the state just
    changed cannot be satisfied by a stale reading from before it — there is
    no historical window to leak through.
    """
    toolset = grafana_toolset("sentinel", settings)
    expr = f'render_workers_available{{project="{settings.project_id}"}}'
    deadline = time.monotonic() + FAULT_PROPAGATION_TIMEOUT_SECONDS
    try:
        while time.monotonic() < deadline:
            try:
                payload = await call_tool(
                    toolset,
                    "query_prometheus",
                    {
                        "datasourceUid": settings.grafana_prom_datasource_uid,
                        "expr": expr,
                        "queryType": "instant",
                        "endTime": "now",
                    },
                )
                series = require_series(payload, expr)
            except GrafanaToolError:
                # A cold-start simulator, or a query landing between export
                # cycles, returns an empty series — the same shape as a real
                # failure. Treat it as "not yet" and keep polling within the
                # timeout instead of failing on the first empty read.
                await asyncio.sleep(FAULT_PROPAGATION_POLL_SECONDS)
                continue
            values = [float(v) for entry in series for _, v in [entry.get("value", (0, "12"))]]
            if values and satisfied(min(values)):
                return
            await asyncio.sleep(FAULT_PROPAGATION_POLL_SECONDS)
    finally:
        await toolset.close()
    raise AssertionError(
        f"render_workers_available never satisfied the expected condition "
        f"within {FAULT_PROPAGATION_TIMEOUT_SECONDS}s"
    )
