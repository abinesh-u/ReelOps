"""Fault control.

The injector flips worker health on the live pipeline and nothing else. Queue
growth, timeouts and throughput collapse follow from the simulation, so what
the agents detect is a consequence rather than a script.

Constructed bare (`FailureInjector()`) it still tracks state, which keeps it
usable as a pure state object.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from random import Random

from simulator.pipeline import RenderPipeline


@dataclass
class SimulationState:
    mode: str = "healthy"
    degraded_workers: int = 0


class FailureInjector:
    """Reproducible fault controller for hackathon scenarios."""

    def __init__(
        self,
        state: SimulationState | None = None,
        pipeline: RenderPipeline | None = None,
        rng: Random | None = None,
    ) -> None:
        self.state = state or SimulationState()
        self.affected_worker_ids: list[str] = []
        self._pipeline = pipeline
        self._rng = rng or Random(0)

    def inject_render_worker_degradation(self, workers: int = 5) -> SimulationState:
        self.state.mode = "degraded"
        self.state.degraded_workers = workers
        if self._pipeline is not None:
            self.affected_worker_ids = self._pipeline.degrade_workers(workers, self._rng)
        return self.state

    def recover(self, now: datetime | None = None) -> SimulationState:
        self.state.mode = "recovering"
        self.state.degraded_workers = 0
        if self._pipeline is not None:
            self._pipeline.restore_workers(now or datetime.now(UTC))
        self.affected_worker_ids = []
        return self.state
