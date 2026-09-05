"""Bounded streams that a consumer can drain without double-counting.

The simulator produces samples and events continuously; the telemetry exporter
reads them on its own real-time interval. A plain ring buffer cannot serve both
— re-reading it each interval exports every sample again — so each stream keeps
a monotonic `recorded_total` and hands out only what a cursor has not seen.

Eviction is the failure mode worth naming: if a consumer falls further behind
than the buffer is deep, the missed items are gone. `since()` says so in the
log rather than under-reporting in silence.
"""

import logging
from collections import deque
from collections.abc import Iterator
from typing import Generic, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


class BoundedStream(Generic[T]):
    def __init__(self, capacity: int, name: str = "stream") -> None:
        self._items: deque[T] = deque(maxlen=capacity)
        self._name = name
        self.recorded_total = 0

    def append(self, item: T) -> None:
        self._items.append(item)
        self.recorded_total += 1

    def since(self, cursor: int) -> tuple[list[T], int]:
        """Items recorded after `cursor`, plus the cursor to pass in next time."""
        oldest_held = self.recorded_total - len(self._items)
        if cursor < oldest_held:
            logger.warning(
                "%s: consumer fell behind, %d items evicted before they were read",
                self._name,
                oldest_held - cursor,
            )
            cursor = oldest_held
        return list(self._items)[cursor - oldest_held :], self.recorded_total

    def __len__(self) -> int:
        return len(self._items)

    def __iter__(self) -> Iterator[T]:
        return iter(self._items)
