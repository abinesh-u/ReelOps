from simulator.failure_injector import FailureInjector


def test_render_degradation_is_reproducible() -> None:
    injector = FailureInjector()
    state = injector.inject_render_worker_degradation(5)
    assert state.mode == "degraded"
    assert state.degraded_workers == 5


def test_recovery() -> None:
    injector = FailureInjector()
    injector.inject_render_worker_degradation()
    state = injector.recover()
    assert state.mode == "recovering"
    assert state.degraded_workers == 0
