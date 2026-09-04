"""The control surface: it drives the engine and exposes nothing more."""

import json

import pytest
from fastapi.testclient import TestClient

from simulator.api import create_app
from simulator.config import SimulatorSettings
from simulator.engine import SimulationEngine

DEGRADED_WORKERS = 5
READ_ROUTES = ("/healthz", "/sim/state")


@pytest.fixture
def engine() -> SimulationEngine:
    return SimulationEngine(SimulatorSettings(sim_seed=42))


@pytest.fixture
def client(engine: SimulationEngine) -> TestClient:
    # autorun off: the test drives ticks itself, so assertions are not racing
    # a background loop.
    with TestClient(create_app(engine, autorun=False)) as test_client:
        yield test_client


def test_healthz(client: TestClient) -> None:
    body = client.get("/healthz").json()
    assert body["status"] == "ok"
    assert body["tick"] == 0


def test_inject_changes_state_and_recover_restores_it(
    client: TestClient, engine: SimulationEngine
) -> None:
    engine.step_many(200)
    assert client.get("/sim/state").json()["metrics"]["render_workers_available"] == 12

    response = client.post("/sim/inject/render-worker-degradation", json={"workers": 5})
    assert response.status_code == 200
    engine.step_many(200)
    degraded = client.get("/sim/state").json()["metrics"]

    # Against an untouched twin at the same tick, so the standing backlog
    # draining is not mistaken for the fault's effect.
    twin = SimulationEngine(SimulatorSettings(sim_seed=42))
    twin.step_many(400)
    baseline = twin.snapshot().metrics

    assert degraded["render_workers_available"] == 12 - DEGRADED_WORKERS
    assert degraded["render_queue_depth"] > baseline["render_queue_depth"]

    assert client.post("/sim/recover").status_code == 200
    engine.step_many(400)
    recovered = client.get("/sim/state").json()["metrics"]
    assert recovered["render_workers_available"] == 12
    assert recovered["render_queue_depth"] < degraded["render_queue_depth"]


def test_reset_returns_a_clean_take(client: TestClient, engine: SimulationEngine) -> None:
    engine.step_many(100)
    engine.inject_render_worker_degradation(DEGRADED_WORKERS)

    body = client.post("/sim/reset", json={"seed": 7}).json()
    assert body == {"accepted": True, "seed": 7}

    state = client.get("/sim/state").json()
    assert state["tick"] == 0
    assert state["metrics"]["render_workers_available"] == 12
    assert engine.ground_truth()["fault"] is None


def test_read_routes_never_expose_the_injected_fault(
    client: TestClient, engine: SimulationEngine
) -> None:
    engine.step_many(100)
    client.post("/sim/inject/render-worker-degradation", json={"workers": 5})
    engine.step_many(300)

    for route in READ_ROUTES:
        payload = json.dumps(client.get(route).json())
        for token in ("ground_truth", "fault", "affected_worker_ids", "degraded", "unhealthy"):
            assert token not in payload, f"{route} leaks the injected fault via {token!r}"


def test_no_route_serves_ground_truth(client: TestClient) -> None:
    """Ground truth has no HTTP path at all, by convention or otherwise."""
    paths = {route.path for route in client.app.routes}
    assert not [p for p in paths if "eval" in p or "truth" in p]
    assert paths >= {"/healthz", "/sim/state", "/sim/reset", "/sim/recover"}


class RecordingEmitter:
    """Stands in for TelemetryEmitter to prove the lifespan actually wires it."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def start(self) -> None:
        self.calls.append("start")

    async def stop(self) -> None:
        self.calls.append("stop")


def test_lifespan_starts_and_stops_telemetry() -> None:
    emitter = RecordingEmitter()
    app = create_app(SimulationEngine(SimulatorSettings()), autorun=False, telemetry=emitter)
    with TestClient(app) as client:
        client.get("/healthz")
        assert emitter.calls == ["start"]
    assert emitter.calls == ["start", "stop"]
