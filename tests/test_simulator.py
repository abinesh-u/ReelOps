"""Phase 1 checks: the simulation is deterministic, and the golden scenario's
signals emerge from it rather than being scripted."""

import pytest

from simulator.config import SimulatorSettings
from simulator.engine import SimulationEngine
from simulator.events import (
    ASSET_DELIVERY_DELAYED,
    RENDER_COMPLETED,
    RENDER_FAILED,
    WORKER_RECOVERED,
    WORKER_TIMEOUT,
)
from simulator.models import WorkerState

DEGRADED_WORKERS = 5
# 14:30 + 540 ticks x 10s = 16:00, the editorial deadline: the instant the
# scenario is actually judged on, and late enough for the log plane to have
# accumulated events rather than one or two.
COMPARE_TICK = 540


def build(seed: int = 42, **overrides) -> SimulationEngine:
    return SimulationEngine(SimulatorSettings(sim_seed=seed, **overrides))


def p95(samples: list[float]) -> float:
    if not samples:
        return 0.0
    ordered = sorted(samples)
    return ordered[min(len(ordered) - 1, int(0.95 * len(ordered)))]


def run_to(engine: SimulationEngine, tick: int) -> None:
    engine.step_many(tick - engine.clock.tick_index)


@pytest.fixture
def healthy() -> SimulationEngine:
    engine = build()
    run_to(engine, COMPARE_TICK)
    return engine


@pytest.fixture
def degraded() -> SimulationEngine:
    engine = build()
    engine.inject_render_worker_degradation(DEGRADED_WORKERS)
    run_to(engine, COMPARE_TICK)
    return engine


def test_determinism() -> None:
    a, b = build(), build()
    a.step_many(500)
    b.step_many(500)
    assert a.snapshot() == b.snapshot()


def test_determinism_survives_injection() -> None:
    """Replaying a take with the same seed and the same fault timing matches."""
    engines = []
    for _ in range(2):
        engine = build()
        engine.step_many(120)
        engine.inject_render_worker_degradation(DEGRADED_WORKERS)
        engine.step_many(200)
        engines.append(engine)
    assert engines[0].snapshot() == engines[1].snapshot()
    assert engines[0].ground_truth() == engines[1].ground_truth()


def test_a_different_seed_produces_a_different_run() -> None:
    a, b = build(seed=42), build(seed=7)
    a.step_many(300)
    b.step_many(300)
    assert a.snapshot() != b.snapshot()


def test_baseline_is_steady(healthy: SimulationEngine) -> None:
    metrics = healthy.snapshot().metrics
    assert metrics["render_workers_available"] == healthy.settings.render_workers
    assert metrics["render_jobs_failed_total"] == 0
    assert metrics["render_queue_depth"] < 60
    assert metrics["render_throughput_fps"] > 0
    assert healthy.event_log.count(RENDER_COMPLETED) > 0
    assert healthy.event_log.count(WORKER_TIMEOUT) == 0


def test_degradation_signals(healthy: SimulationEngine, degraded: SimulationEngine) -> None:
    """Every signal docs/golden-scenario.md expects, at the same tick."""
    before = healthy.snapshot()
    after = degraded.snapshot()

    assert after.metrics["render_workers_available"] < before.metrics["render_workers_available"]
    assert after.metrics["render_workers_available"] == (
        healthy.settings.render_workers - DEGRADED_WORKERS
    )
    assert after.metrics["render_queue_depth"] > before.metrics["render_queue_depth"]
    assert p95(after.render_durations_seconds) > p95(before.render_durations_seconds)
    assert after.metrics["render_jobs_failed_total"] > before.metrics["render_jobs_failed_total"]
    assert after.metrics["render_throughput_fps"] < before.metrics["render_throughput_fps"]

    # The log plane has to discriminate too: the golden scenario asks for a
    # correlated investigation, not one spiking metric.
    #
    # A healthy worker cannot time out — its longest job is well inside
    # render_timeout_seconds — so that count is structurally zero. Delivery
    # breaches are an SLA, not an impossibility, so only the rise is asserted.
    assert healthy.event_log.count(WORKER_TIMEOUT) == 0
    assert degraded.event_log.count(WORKER_TIMEOUT) > 0
    assert degraded.event_log.count(ASSET_DELIVERY_DELAYED) > healthy.event_log.count(
        ASSET_DELIVERY_DELAYED
    )


def test_recovery() -> None:
    engine = build()
    engine.inject_render_worker_degradation(DEGRADED_WORKERS)
    engine.step_many(300)
    at_recovery = engine.snapshot().metrics

    engine.recover()
    engine.step_many(400)
    after = engine.snapshot().metrics

    assert after["render_workers_available"] == engine.settings.render_workers
    assert after["render_queue_depth"] < at_recovery["render_queue_depth"]
    assert engine.event_log.count(WORKER_RECOVERED) == DEGRADED_WORKERS


def test_scene_42_deadline() -> None:
    """The fault is what costs Scene 42 its editorial window.

    Only the sign is asserted; the size of the margin is a tuning outcome and
    is recorded in docs/architecture.md.
    """
    healthy_margin = run_until_hero_ready(build())
    degraded_engine = build()
    degraded_engine.inject_render_worker_degradation(DEGRADED_WORKERS)
    degraded_margin = run_until_hero_ready(degraded_engine)

    assert healthy_margin > 0, "healthy run should make the 16:00 review"
    assert degraded_margin < 0, "degraded run should miss the 16:00 review"


def run_until_hero_ready(engine: SimulationEngine, max_ticks: int = 4000) -> float:
    for _ in range(max_ticks):
        engine.step()
        margin = engine.hero_scene_margin_seconds()
        if margin is not None:
            return margin
    raise AssertionError("hero scene never completed")


def test_ground_truth_is_reachable_in_process() -> None:
    engine = build()
    engine.step_many(50)
    assert engine.ground_truth()["fault"] is None

    engine.inject_render_worker_degradation(DEGRADED_WORKERS)
    truth = engine.ground_truth()
    assert truth["fault"] == "render_worker_degradation"
    assert len(truth["affected_worker_ids"]) == DEGRADED_WORKERS
    assert truth["injected_at_tick"] == 50


def test_snapshot_carries_no_fault_label(degraded: SimulationEngine) -> None:
    """The snapshot never says a fault was injected, or which kind.

    It is not an anonymity claim. `workers[].available` marks exactly the
    workers in `ground_truth()["affected_worker_ids"]`, because a real fleet
    reports which of its workers are healthy and ReelOps has to be able to see
    that. What stays hidden is that the loss was injected rather than organic.
    Phase 9 should score root-cause reasoning, not worker identification,
    which is readable from `/sim/state` by design.
    """
    import json

    payload = json.dumps(degraded.snapshot().to_dict())
    for token in (
        "ground_truth",
        "fault",
        "affected_worker_ids",
        "injected_at_tick",
        "speed_factor",
        "stalled",
        "degraded",
        "unhealthy",
    ):
        assert token not in payload, f"snapshot leaks the injected fault via {token!r}"


def test_unhealthy_workers_stop_taking_work() -> None:
    """`unhealthy_fraction` of a fault takes workers down outright.

    The golden scenario is "degrade or become unhealthy", and a worker that
    goes down mid-job has to hand that job back to the queue.
    """
    engine = build()
    engine.step_many(100)  # every worker is busy by now
    engine.inject_render_worker_degradation(DEGRADED_WORKERS)

    expected_down = int(DEGRADED_WORKERS * engine.settings.unhealthy_fraction)
    assert expected_down > 0, "settings should exercise the unhealthy path"

    down = [w for w in engine.pipeline.workers if w.state is WorkerState.UNHEALTHY]
    assert len(down) == expected_down

    engine.step_many(5)
    assert all(w.current_job_id is None for w in down)
    assert engine.event_log.count(RENDER_FAILED) >= expected_down

    engine.step_many(200)
    assert all(w.current_job_id is None for w in down), "a downed worker takes no new work"


def test_events_carry_trace_id(degraded: SimulationEngine) -> None:
    """Logs join to traces, per docs/telemetry-contract.md."""
    job_events = [e for e in degraded.event_log.recent(200) if e.job_id]
    assert job_events
    assert all(e.trace_id for e in job_events)

    by_job: dict[str, set[str]] = {}
    for event in job_events:
        by_job.setdefault(e_job := event.job_id, set()).add(event.trace_id)
        assert len(by_job[e_job]) == 1, "one job, one trace"
