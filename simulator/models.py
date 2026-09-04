from dataclasses import dataclass
from datetime import datetime


@dataclass
class RenderWorker:
    worker_id: str
    available: bool = True
    utilization: float = 0.7


@dataclass
class RenderJob:
    job_id: str
    scene_id: str
    duration_seconds: float = 900
    status: str = "running"


@dataclass
class Scene:
    scene_id: str
    editorial_deadline: datetime
    vfx_ready: bool = True
    review_status: str = "pending"
