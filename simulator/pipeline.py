"""The render pipeline state machine.

```text
VFX shot release -> render queue -> render workers -> editorial review
```

Nothing here is scripted against a scenario. Injecting a fault changes worker
speed and availability only; queue growth, timeouts and throughput collapse are
consequences the agents are meant to reason about.
"""

from collections import deque
from datetime import datetime, timedelta
from random import Random

from simulator import events as ev
from simulator.config import SimulatorSettings
from simulator.events import EventLog, SimEvent
from simulator.models import (
    JobStatus,
    RenderJob,
    RenderWorker,
    Scene,
    Shot,
    ShotStatus,
    WorkerState,
)

SERVICE = "render-farm"
EDITORIAL_SERVICE = "editorial"
# Sim seconds a reviewer spends on one scene.
EDITORIAL_REVIEW_SECONDS = 600.0


class RenderPipeline:
    def __init__(self, settings: SimulatorSettings, rng: Random, event_log: EventLog) -> None:
        self._settings = settings
        self._rng = rng
        self.event_log = event_log

        self.workers: list[RenderWorker] = [
            RenderWorker(worker_id=f"render-{i + 1:02d}") for i in range(settings.render_workers)
        ]
        self.queue: deque[RenderJob] = deque()
        self.jobs: dict[str, RenderJob] = {}
        self.shots: dict[str, Shot] = {}
        self.scenes: dict[str, Scene] = {}

        self.jobs_failed_total = 0
        self.jobs_completed_total = 0
        self.frames_completed_total = 0

        self._job_seq = 0
        # (elapsed_seconds, frames) pairs inside the throughput window.
        self._frame_events: deque[tuple[float, int]] = deque()
        self.render_durations: deque[float] = deque(maxlen=settings.sample_buffer_size)
        self.vfx_latencies: deque[float] = deque(maxlen=settings.sample_buffer_size)

        self._reviewing_scene: str | None = None
        self._review_remaining = 0.0
        self._elapsed = 0.0

        self._background_scene_seq = 0
        self._background_scene_id = ""
        self._background_released = 0
        self._next_background_at = 0.0

        self._build_scenes()
        self._background_scene_id = self._open_background_scene().scene_id
        self._hero_plan: deque[tuple[float, str]] = deque(self._hero_release_plan())

    # -- construction ---------------------------------------------------

    def _build_scenes(self) -> None:
        s = self._settings
        hero = Scene(scene_id=s.hero_scene_id, editorial_deadline=s.scene_deadline)
        self.scenes[hero.scene_id] = hero
        for i in range(s.hero_scene_shots):
            shot = Shot(
                shot_id=f"{s.hero_scene_id}-shot-{i + 1:02d}",
                scene_id=hero.scene_id,
                frames=s.shot_frames,
            )
            self.shots[shot.shot_id] = shot
            hero.shots.append(shot.shot_id)

    def _hero_release_plan(self) -> list[tuple[float, str]]:
        """When each of the hero scene's shots enters the queue.

        Finite by nature: the scene has a fixed shot list. Background work is
        released separately and without end, so the farm is contended for as
        long as the run lasts.
        """
        s = self._settings
        step = s.hero_submission_seconds / max(s.hero_scene_shots, 1)
        return [(i * step, shot_id) for i, shot_id in enumerate(self.scenes[s.hero_scene_id].shots)]

    def _open_background_scene(self) -> Scene:
        self._background_scene_seq += 1
        scene = Scene(
            scene_id=f"scene-{50 + self._background_scene_seq:d}",
            # Downstream of the hero scene in the day; data, not a judgement.
            editorial_deadline=self._settings.scene_deadline
            + timedelta(minutes=30 * self._background_scene_seq),
        )
        self.scenes[scene.scene_id] = scene
        return scene

    def _next_background_shot(self) -> Shot:
        """Background scenes fill up, close, and are replaced.

        A fixed roster would never finish, leaving every background scene
        permanently mid-render and the editorial metrics stuck flat.
        """
        scene = self.scenes[self._background_scene_id]
        if len(scene.shots) >= self._settings.background_shots_per_scene:
            scene = self._open_background_scene()
            self._background_scene_id = scene.scene_id
        shot = Shot(
            shot_id=f"{scene.scene_id}-shot-{len(scene.shots) + 1:02d}",
            scene_id=scene.scene_id,
            frames=self._settings.shot_frames,
        )
        self.shots[shot.shot_id] = shot
        scene.shots.append(shot.shot_id)
        return shot

    # -- per-tick ---------------------------------------------------------

    def tick(self, now: datetime, dt: float, elapsed: float) -> None:
        self._elapsed = elapsed
        self._release_due_shots(now, elapsed)
        self._advance_workers(now, dt)
        self._assign_idle_workers(now)
        self._advance_editorial(now, dt)
        self._trim_frame_window(elapsed)

    def _release_due_shots(self, now: datetime, elapsed: float) -> None:
        # Background first, so the hero scene contends with a standing backlog
        # rather than an empty farm.
        while self._next_background_at <= elapsed:
            self._queue_shot(self._next_background_shot(), now)
            self._background_released += 1
            if self._background_released >= self._settings.background_backlog_jobs:
                self._next_background_at += self._rng.expovariate(
                    1.0 / self._settings.background_interval_seconds
                )

        while self._hero_plan and self._hero_plan[0][0] <= elapsed:
            _, shot_id = self._hero_plan.popleft()
            self._queue_shot(self.shots[shot_id], now)

    def _queue_shot(self, shot: Shot, now: datetime) -> None:
        s = self._settings
        jitter = self._rng.uniform(-s.job_duration_jitter, s.job_duration_jitter)
        self._job_seq += 1
        job = RenderJob(
            job_id=f"job-{self._job_seq:04d}",
            scene_id=shot.scene_id,
            shot_id=shot.shot_id,
            duration_seconds=s.job_duration_seconds * (1.0 + jitter),
            frames=shot.frames,
            queued_at=now,
            trace_id=f"{self._rng.getrandbits(64):016x}",
        )
        self.jobs[job.job_id] = job
        shot.job_id = job.job_id
        shot.queued_at = now
        shot.status = ShotStatus.RENDERING
        self.queue.append(job)
        self._log(ev.JOB_QUEUED, now, job=job)

    def _advance_workers(self, now: datetime, dt: float) -> None:
        for worker in self.workers:
            if worker.current_job_id is None:
                worker.utilization = 0.0
                continue

            job = self.jobs[worker.current_job_id]

            if worker.state is WorkerState.UNHEALTHY:
                self._release_job(worker, job, now, ev.RENDER_FAILED, "worker_unavailable")
                continue

            worker.utilization = 1.0
            worker.job_elapsed_seconds += dt
            if not worker.stalled:
                job.progress_seconds += dt * worker.speed_factor

            if job.progress_seconds >= job.duration_seconds:
                self._complete_job(worker, job, now)
            elif worker.job_elapsed_seconds >= self._settings.render_timeout_seconds:
                self._time_out_job(worker, job, now)

    def _complete_job(self, worker: RenderWorker, job: RenderJob, now: datetime) -> None:
        duration = worker.job_elapsed_seconds
        job.status = JobStatus.COMPLETED
        job.completed_at = now
        self.jobs_completed_total += 1
        self.frames_completed_total += job.frames
        self.render_durations.append(duration)
        self._frame_events.append((self._elapsed, job.frames))
        self._log(ev.RENDER_COMPLETED, now, job=job, worker=worker, duration_s=duration)

        shot = self.shots[job.shot_id] if job.shot_id else None
        if shot is not None:
            shot.status = ShotStatus.READY
            shot.completed_at = now
            latency = (now - shot.queued_at).total_seconds() if shot.queued_at else duration
            self.vfx_latencies.append(latency)
            if latency > self._settings.delivery_sla_seconds:
                self._log(
                    ev.ASSET_DELIVERY_DELAYED,
                    now,
                    job=job,
                    level="warn",
                    duration_s=latency,
                    error_code="delivery_late",
                )
        self._free(worker)

    def _time_out_job(self, worker: RenderWorker, job: RenderJob, now: datetime) -> None:
        self.jobs_failed_total += 1
        job.attempts += 1
        self._log(
            ev.WORKER_TIMEOUT,
            now,
            job=job,
            worker=worker,
            level="warn",
            error_code="render_timeout",
            duration_s=worker.job_elapsed_seconds,
        )
        if job.attempts >= self._settings.max_job_attempts:
            # The shot is in trouble and says so, but the work is still needed:
            # abandoning it would strand the scene forever and make the
            # deadline signal meaningless. It keeps retrying at lower standing.
            if job.shot_id:
                self.shots[job.shot_id].status = ShotStatus.BLOCKED
            self._log(
                ev.RENDER_FAILED,
                now,
                job=job,
                worker=worker,
                level="error",
                error_code="max_attempts_exceeded",
            )
            job.attempts = 0
        self._requeue(worker, job)

    def _release_job(
        self, worker: RenderWorker, job: RenderJob, now: datetime, event: str, code: str
    ) -> None:
        self._log(event, now, job=job, worker=worker, level="error", error_code=code)
        self._requeue(worker, job)

    def _requeue(self, worker: RenderWorker, job: RenderJob) -> None:
        job.status = JobStatus.QUEUED
        job.progress_seconds = 0.0
        job.worker_id = None
        job.started_at = None
        self.queue.append(job)
        self._free(worker)

    def _free(self, worker: RenderWorker) -> None:
        worker.current_job_id = None
        worker.job_elapsed_seconds = 0.0
        worker.utilization = 0.0
        worker.stalled = False

    def _assign_idle_workers(self, now: datetime) -> None:
        for worker in self.workers:
            if worker.current_job_id is not None or not worker.accepts_work:
                continue
            if not self.queue:
                break
            job = self.queue.popleft()
            job.status = JobStatus.RUNNING
            job.started_at = now
            job.worker_id = worker.worker_id
            worker.current_job_id = job.job_id
            worker.job_elapsed_seconds = 0.0
            worker.stalled = (
                worker.state is WorkerState.DEGRADED
                and self._rng.random() < self._settings.degraded_stall_probability
            )
            worker.utilization = 1.0
            self._log(ev.RENDER_STARTED, now, job=job, worker=worker)

    def _advance_editorial(self, now: datetime, dt: float) -> None:
        for scene in self.scenes.values():
            if scene.vfx_ready or not scene.shots:
                continue
            if all(self.shots[s].status is ShotStatus.READY for s in scene.shots):
                scene.vfx_ready = True
                scene.ready_at = now

        if self._reviewing_scene is not None:
            self._review_remaining -= dt
            if self._review_remaining <= 0:
                self.scenes[self._reviewing_scene].review_status = "approved"
                self._reviewing_scene = None

        if self._reviewing_scene is None:
            waiting = self._review_queue()
            if waiting:
                scene = min(waiting, key=lambda sc: sc.ready_at or now)
                self._reviewing_scene = scene.scene_id
                self._review_remaining = EDITORIAL_REVIEW_SECONDS
                scene.review_status = "in_review"

    def _review_queue(self) -> list[Scene]:
        return [s for s in self.scenes.values() if s.vfx_ready and s.review_status == "pending"]

    def _trim_frame_window(self, elapsed: float) -> None:
        cutoff = elapsed - self._settings.throughput_window_seconds
        while self._frame_events and self._frame_events[0][0] < cutoff:
            self._frame_events.popleft()

    # -- fault control ----------------------------------------------------

    def degrade_workers(self, count: int, rng: Random) -> list[str]:
        healthy = [w for w in self.workers if w.state is WorkerState.HEALTHY]
        chosen = rng.sample(healthy, min(count, len(healthy)))
        s = self._settings
        unhealthy_count = int(len(chosen) * s.unhealthy_fraction)
        for i, worker in enumerate(chosen):
            if i < unhealthy_count:
                worker.state = WorkerState.UNHEALTHY
                worker.speed_factor = 0.0
            else:
                worker.state = WorkerState.DEGRADED
                worker.speed_factor = rng.uniform(s.degraded_speed_min, s.degraded_speed_max)
        return [w.worker_id for w in chosen]

    def restore_workers(self, now: datetime) -> list[str]:
        restored: list[str] = []
        for worker in self.workers:
            if worker.state is WorkerState.HEALTHY:
                continue
            worker.state = WorkerState.HEALTHY
            worker.speed_factor = 1.0
            worker.stalled = False
            restored.append(worker.worker_id)
            self._log(ev.WORKER_RECOVERED, now, worker=worker)
        return restored

    # -- derived views ----------------------------------------------------

    @property
    def frames_in_window(self) -> int:
        return sum(frames for _, frames in self._frame_events)

    @property
    def busy_workers(self) -> int:
        return sum(1 for w in self.workers if w.current_job_id is not None)

    @property
    def available_workers(self) -> int:
        return sum(1 for w in self.workers if w.available)

    def review_queue_depth(self) -> int:
        return len(self._review_queue())

    def longest_review_wait(self, now: datetime) -> float:
        waits = [(now - s.ready_at).total_seconds() for s in self._review_queue() if s.ready_at]
        return max(waits, default=0.0)

    def blocked_scenes(self) -> int:
        """Scenes whose review cannot start because upstream shots are unfinished.

        A state fact, not a deadline judgement: schedule risk is inferred by
        ReelOps, never published as a source metric.
        """
        return sum(
            1
            for s in self.scenes.values()
            if s.shots and not s.vfx_ready and s.review_status == "pending"
        )

    def shots_by_status(self, status: ShotStatus) -> int:
        return sum(1 for s in self.shots.values() if s.status is status)

    def scene_completion(self, scene_id: str) -> datetime | None:
        scene = self.scenes.get(scene_id)
        if scene is None or not scene.vfx_ready:
            return None
        return scene.ready_at

    # -- internals --------------------------------------------------------

    def _log(
        self,
        event: str,
        now: datetime,
        *,
        job: RenderJob | None = None,
        worker: RenderWorker | None = None,
        level: str = "info",
        error_code: str | None = None,
        duration_s: float | None = None,
    ) -> None:
        service = EDITORIAL_SERVICE if event == ev.ASSET_DELIVERY_DELAYED else SERVICE
        self.event_log.record(
            SimEvent(
                timestamp=now,
                level=level,
                event=event,
                service=service,
                project_id=self._settings.project_id,
                worker_id=worker.worker_id if worker else None,
                job_id=job.job_id if job else None,
                scene_id=job.scene_id if job else None,
                trace_id=job.trace_id if job else None,
                error_code=error_code,
                duration_ms=round(duration_s * 1000, 3) if duration_s is not None else None,
            )
        )
