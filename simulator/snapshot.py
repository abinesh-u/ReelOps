"""The Phase 2 seam.

`SimulationSnapshot` is everything the OTLP exporter will need and nothing
else. Metric keys are the exact names in `docs/telemetry-contract.md`, so the
exporter maps them one-to-one and invents nothing.

The injected fault label is deliberately absent. Worker entries carry only what
an operator could observe from outside — availability and current job — never
`state` or `speed_factor`, so no agent can shortcut the investigation by
reading the answer out of the simulator.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from simulator.models import ShotStatus
from simulator.pipeline import RenderPipeline


@dataclass(frozen=True)
class SimulationSnapshot:
    tick: int
    sim_time: datetime
    metrics: dict[str, float]
    workers: list[dict[str, Any]]
    queue: list[dict[str, Any]]
    scenes: list[dict[str, Any]]
    # Samples backing the histogram instruments in Phase 2.
    render_durations_seconds: list[float]
    vfx_delivery_latency_samples: list[float]
    recent_events: list[dict[str, Any]]
    event_counts: dict[str, int]

    def to_dict(self) -> dict[str, Any]:
        return {
            "tick": self.tick,
            "sim_time": self.sim_time.isoformat(),
            "metrics": self.metrics,
            "workers": self.workers,
            "queue": self.queue,
            "scenes": self.scenes,
            "render_durations_seconds": self.render_durations_seconds,
            "vfx_delivery_latency_samples": self.vfx_delivery_latency_samples,
            "recent_events": self.recent_events,
            "event_counts": self.event_counts,
        }


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def build_snapshot(
    pipeline: RenderPipeline, tick: int, now: datetime, window_seconds: float, event_limit: int = 50
) -> SimulationSnapshot:
    durations = list(pipeline.render_durations)
    latencies = list(pipeline.vfx_latencies)
    worker_count = len(pipeline.workers) or 1

    metrics = {
        # Render
        "render_queue_depth": float(len(pipeline.queue)),
        "render_jobs_running": float(pipeline.busy_workers),
        "render_jobs_failed_total": float(pipeline.jobs_failed_total),
        "render_job_duration_seconds": round(_mean(durations), 3),
        "render_workers_available": float(pipeline.available_workers),
        "render_workers_utilization": round(pipeline.busy_workers / worker_count, 4),
        # Frames completed in the trailing window, per second of that window.
        "render_throughput_fps": round(pipeline.frames_in_window / window_seconds, 4),
        # VFX
        # In-flight only: shots VFX has released and not yet delivered.
        # Shots still ahead of their release time are not work in progress.
        "vfx_shots_pending": float(pipeline.shots_by_status(ShotStatus.RENDERING)),
        "vfx_shots_ready_for_review": float(pipeline.shots_by_status(ShotStatus.READY)),
        "vfx_shots_blocked": float(pipeline.shots_by_status(ShotStatus.BLOCKED)),
        # Queued-to-completed, so queue wait and retries are both included.
        "vfx_delivery_latency_seconds": round(_mean(latencies), 3),
        # Editorial
        "editorial_review_queue": float(pipeline.review_queue_depth()),
        "editorial_blocked_scenes": float(pipeline.blocked_scenes()),
        "review_wait_seconds": round(pipeline.longest_review_wait(now), 3),
    }

    workers = [
        {
            "worker_id": w.worker_id,
            "available": w.available,
            "utilization": w.utilization,
            "current_job_id": w.current_job_id,
        }
        for w in pipeline.workers
    ]
    queue = [
        {
            "job_id": j.job_id,
            "scene_id": j.scene_id,
            "shot_id": j.shot_id,
            "attempts": j.attempts,
            "queued_at": j.queued_at.isoformat() if j.queued_at else None,
        }
        for j in pipeline.queue
    ]
    scenes = [
        {
            "scene_id": s.scene_id,
            "editorial_deadline": s.editorial_deadline.isoformat(),
            "vfx_ready": s.vfx_ready,
            "review_status": s.review_status,
            "shots_total": len(s.shots),
            "ready_at": s.ready_at.isoformat() if s.ready_at else None,
        }
        for s in pipeline.scenes.values()
    ]

    return SimulationSnapshot(
        tick=tick,
        sim_time=now,
        metrics=metrics,
        workers=workers,
        queue=queue,
        scenes=scenes,
        render_durations_seconds=[round(d, 3) for d in durations],
        vfx_delivery_latency_samples=[round(v, 3) for v in latencies],
        recent_events=[e.to_dict() for e in pipeline.event_log.recent(event_limit)],
        event_counts=dict(sorted(pipeline.event_log.counts().items())),
    )
