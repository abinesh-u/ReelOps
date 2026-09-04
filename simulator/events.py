"""Structured events: the Loki plane of `docs/telemetry-contract.md`.

Held in a bounded ring buffer so a long run cannot grow without limit, with
cumulative counters kept alongside so eviction never rewrites history.
"""

from collections import Counter, deque
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any

# Event vocabulary from docs/telemetry-contract.md.
RENDER_STARTED = "render_started"
RENDER_COMPLETED = "render_completed"
RENDER_FAILED = "render_failed"
WORKER_TIMEOUT = "worker_timeout"
WORKER_RECOVERED = "worker_recovered"
JOB_QUEUED = "job_queued"
JOB_DEPRIORITIZED = "job_deprioritized"
ASSET_DELIVERY_DELAYED = "asset_delivery_delayed"


@dataclass(frozen=True)
class SimEvent:
    timestamp: datetime
    level: str
    event: str
    service: str
    project_id: str
    worker_id: str | None = None
    job_id: str | None = None
    scene_id: str | None = None
    error_code: str | None = None
    duration_ms: float | None = None
    trace_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["timestamp"] = self.timestamp.isoformat()
        return payload


class EventLog:
    def __init__(self, capacity: int = 2000) -> None:
        self._events: deque[SimEvent] = deque(maxlen=capacity)
        self._counts: Counter[str] = Counter()

    def record(self, event: SimEvent) -> None:
        self._events.append(event)
        self._counts[event.event] += 1

    def recent(self, limit: int = 50) -> list[SimEvent]:
        if limit >= len(self._events):
            return list(self._events)
        return list(self._events)[-limit:]

    def count(self, event_name: str) -> int:
        """Cumulative occurrences, including entries evicted from the buffer."""
        return self._counts[event_name]

    def counts(self) -> dict[str, int]:
        return dict(self._counts)
