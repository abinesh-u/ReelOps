"""Sim time. Ticks are the only source of time; wall clock never appears here."""

from datetime import datetime, timedelta


class SimClock:
    """Converts a tick count into simulated wall time.

    Pacing against real time is the caller's job (see `SimulationEngine.run`),
    which keeps simulated state a pure function of the tick index.
    """

    def __init__(self, start: datetime, tick_seconds: float) -> None:
        self._start = start
        self._tick_seconds = tick_seconds
        self.tick_index = 0

    @property
    def tick_seconds(self) -> float:
        return self._tick_seconds

    @property
    def elapsed_seconds(self) -> float:
        return self.tick_index * self._tick_seconds

    @property
    def now(self) -> datetime:
        return self._start + timedelta(seconds=self.elapsed_seconds)

    def advance(self) -> None:
        self.tick_index += 1
