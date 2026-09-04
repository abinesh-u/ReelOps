from dataclasses import dataclass


@dataclass
class SimulationState:
    mode: str = "healthy"
    degraded_workers: int = 0


class FailureInjector:
    """Reproducible fault controller for hackathon scenarios."""

    def __init__(self, state: SimulationState | None = None) -> None:
        self.state = state or SimulationState()

    def inject_render_worker_degradation(self, workers: int = 5) -> SimulationState:
        self.state.mode = "degraded"
        self.state.degraded_workers = workers
        return self.state

    def recover(self) -> SimulationState:
        self.state.mode = "recovering"
        self.state.degraded_workers = 0
        return self.state
