from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum


class WorkerState(StrEnum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class ShotStatus(StrEnum):
    PENDING = "pending"
    RENDERING = "rendering"
    READY = "ready"
    BLOCKED = "blocked"


@dataclass
class RenderWorker:
    worker_id: str
    utilization: float = 0.0
    state: WorkerState = WorkerState.HEALTHY
    speed_factor: float = 1.0
    current_job_id: str | None = None
    # Sim seconds the current job has occupied this worker, used for timeouts.
    job_elapsed_seconds: float = 0.0
    # This attempt makes no progress at all and will trip the timeout.
    stalled: bool = False

    @property
    def available(self) -> bool:
        """Observably able to take work at full rate.

        Degraded workers are excluded: `render_workers_available` is the signal
        the golden scenario expects to fall, and a worker crawling at a third
        of its rate is not capacity a scheduler can count on.
        """
        return self.state is WorkerState.HEALTHY

    @property
    def accepts_work(self) -> bool:
        return self.state is not WorkerState.UNHEALTHY


@dataclass
class RenderJob:
    job_id: str
    scene_id: str
    duration_seconds: float = 900.0
    status: JobStatus = JobStatus.QUEUED
    shot_id: str | None = None
    frames: int = 240
    priority: int = 0
    attempts: int = 0
    queued_at: datetime | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    worker_id: str | None = None
    # Ties this job's logs to its trace, per docs/telemetry-contract.md.
    trace_id: str = ""
    # Work seconds accrued so far; a degraded worker accrues them slower.
    progress_seconds: float = 0.0


@dataclass
class Shot:
    shot_id: str
    scene_id: str
    frames: int = 240
    status: ShotStatus = ShotStatus.PENDING
    job_id: str | None = None
    queued_at: datetime | None = None
    completed_at: datetime | None = None


@dataclass
class Scene:
    scene_id: str
    editorial_deadline: datetime
    vfx_ready: bool = False
    review_status: str = "pending"
    shots: list[str] = field(default_factory=list)
    ready_at: datetime | None = None
