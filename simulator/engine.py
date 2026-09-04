"""The simulation engine: clock, pipeline, randomness and ground truth.

Determinism is the property everything else rests on. State is a pure function
of `(seed, tick index, injected events)`; wall time only paces `run()`. All
randomness is drawn from one `Random` owned here, never module-level `random`,
which would silently break replay.
"""

import asyncio
import logging
from datetime import datetime
from random import Random
from typing import Any

from simulator.clock import SimClock
from simulator.config import SimulatorSettings
from simulator.events import EventLog
from simulator.failure_injector import FailureInjector, SimulationState
from simulator.pipeline import RenderPipeline
from simulator.snapshot import SimulationSnapshot, build_snapshot

logger = logging.getLogger(__name__)


class SimulationEngine:
    def __init__(self, settings: SimulatorSettings | None = None) -> None:
        self.settings = settings or SimulatorSettings()
        self.seed = self.settings.sim_seed
        self._running = False
        self.reset(self.seed)

    # -- lifecycle --------------------------------------------------------

    def reset(self, seed: int | None = None) -> None:
        """Rebuild every piece of state from a seed. A clean take, on demand."""
        self.seed = self.seed if seed is None else seed
        self._rng = Random(self.seed)
        self.clock = SimClock(self.settings.sim_start_time, self.settings.sim_tick_seconds)
        self.event_log = EventLog(capacity=self.settings.event_buffer_size)
        self.pipeline = RenderPipeline(self.settings, self._rng, self.event_log)
        self.injector = FailureInjector(pipeline=self.pipeline, rng=self._rng)
        self._ground_truth: dict[str, Any] = {
            "fault": None,
            "affected_worker_ids": [],
            "injected_at_tick": None,
            "recovered_at_tick": None,
        }

    def step(self) -> None:
        self.pipeline.tick(
            now=self.clock.now,
            dt=self.clock.tick_seconds,
            elapsed=self.clock.elapsed_seconds,
        )
        self.clock.advance()

    def step_many(self, ticks: int) -> None:
        for _ in range(ticks):
            self.step()

    async def run(self) -> None:
        """Advance forever, pacing sim time against real time by `SIM_SPEED`."""
        self._running = True
        interval = self.settings.sim_tick_seconds / self.settings.sim_speed
        logger.info(
            "simulator running: seed=%s speed=%sx tick=%ss",
            self.seed,
            self.settings.sim_speed,
            self.settings.sim_tick_seconds,
        )
        try:
            while self._running:
                self.step()
                await asyncio.sleep(interval)
        except asyncio.CancelledError:
            self._running = False
            raise

    def stop(self) -> None:
        self._running = False

    # -- observation ------------------------------------------------------

    def snapshot(self) -> SimulationSnapshot:
        return build_snapshot(
            self.pipeline,
            tick=self.clock.tick_index,
            now=self.clock.now,
            window_seconds=self.settings.throughput_window_seconds,
        )

    # -- fault control ----------------------------------------------------

    def inject_render_worker_degradation(self, workers: int = 5) -> SimulationState:
        state = self.injector.inject_render_worker_degradation(workers)
        self._ground_truth = {
            "fault": "render_worker_degradation",
            "affected_worker_ids": list(self.injector.affected_worker_ids),
            "injected_at_tick": self.clock.tick_index,
            "recovered_at_tick": None,
        }
        return state

    def recover(self) -> SimulationState:
        state = self.injector.recover(self.clock.now)
        self._ground_truth["recovered_at_tick"] = self.clock.tick_index
        return state

    def ground_truth(self) -> dict[str, Any]:
        """In-process accessor for evals only.

        Deliberately not routed over HTTP: a `/sim/_eval/...` path would be a
        naming convention, not a boundary, and anything holding the base URL
        could read the answer the agents are supposed to derive.
        """
        return dict(self._ground_truth)

    # -- schedule ---------------------------------------------------------

    def hero_scene_margin_seconds(self) -> float | None:
        """Sim seconds between the hero scene becoming ready and its deadline.

        Positive means it made the window. `None` while it is still rendering.
        """
        ready_at = self.pipeline.scene_completion(self.settings.hero_scene_id)
        if ready_at is None:
            return None
        return (self.settings.scene_deadline - ready_at).total_seconds()

    @property
    def sim_time(self) -> datetime:
        return self.clock.now
