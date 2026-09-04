"""Simulator configuration.

Every knob that changes simulated behaviour lives here so a run is fully
described by its settings plus its seed. Tuning constants are settings rather
than module constants so tests can build variants without patching.
"""

from datetime import UTC, datetime

from pydantic_settings import BaseSettings, SettingsConfigDict


class SimulatorSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- Clock ---------------------------------------------------------
    sim_seed: int = 42
    # Sim seconds advanced per tick.
    sim_tick_seconds: float = 10.0
    # Sim seconds per real second. 60 => a 90 sim-minute day runs in 90s.
    sim_speed: float = 60.0
    # Anchored, not "today", so a replay is identical on any date.
    sim_start_time: datetime = datetime(2026, 3, 12, 14, 30, tzinfo=UTC)
    sim_api_port: int = 8090

    # --- Fleet ---------------------------------------------------------
    render_workers: int = 12
    render_timeout_seconds: float = 1800.0
    max_job_attempts: int = 3
    degraded_speed_min: float = 0.35
    degraded_speed_max: float = 0.65
    # Chance a degraded worker stalls outright on a job instead of merely
    # running slow. Keeps the timeout rate independent of the slowdown depth.
    degraded_stall_probability: float = 0.25
    # Of the workers a fault affects, this fraction stop taking work
    # entirely; the rest run slow. Rounded down, so small faults only degrade.
    # The golden scenario is "degrade or become unhealthy": 0.4 of five is two
    # workers down and three crawling.
    unhealthy_fraction: float = 0.4

    # --- Work ----------------------------------------------------------
    job_duration_seconds: float = 900.0
    # Expected duration is drawn from +/- this fraction of the nominal.
    job_duration_jitter: float = 0.2
    shot_frames: int = 240
    # Editorial's delivery SLA per shot, measured queued-to-delivered. Set
    # above the healthy latency distribution so a breach means something.
    delivery_sla_seconds: float = 3600.0

    # --- Scene 42 ------------------------------------------------------
    hero_scene_id: str = "scene-42"
    hero_scene_shots: int = 24
    # VFX releases the hero scene's shots evenly across this span.
    hero_submission_seconds: float = 900.0
    scene_deadline: datetime = datetime(2026, 3, 12, 16, 0, tzinfo=UTC)

    # --- Background contention -----------------------------------------
    # Shots already queued when the run starts.
    background_backlog_jobs: int = 18
    # Mean gap between background shot releases, drawn exponentially.
    background_interval_seconds: float = 140.0
    # A background scene closes at this many shots and a new one opens.
    background_shots_per_scene: int = 8

    # --- Derived signal windows -----------------------------------------
    # One nominal job duration, so the rate is not dominated by completion bursts.
    throughput_window_seconds: float = 900.0
    event_buffer_size: int = 2000
    sample_buffer_size: int = 200

    project_id: str = "reelops-demo"
