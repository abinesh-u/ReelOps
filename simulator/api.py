"""HTTP control surface for the simulator.

A thin adapter: routes translate requests into engine calls and snapshots into
JSON, and hold no simulation logic of their own. Phase 6's Action Gateway calls
these same endpoints, so the fault is triggered from the product rather than a
terminal.

The engine's ground truth is not routed here. See `SimulationEngine.ground_truth`.
"""

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Any, Protocol

from fastapi import FastAPI
from pydantic import BaseModel, Field

from simulator.config import SimulatorSettings
from simulator.engine import SimulationEngine

logger = logging.getLogger(__name__)


class TelemetryEmitter(Protocol):
    """What the app needs from telemetry, and no more.

    Structural, so `simulator/` imports no OpenTelemetry and stays runnable
    with telemetry off — and so console and in-memory adapters never sit on the
    production path.
    """

    async def start(self) -> None: ...

    async def stop(self) -> None: ...


class DegradationRequest(BaseModel):
    workers: int = Field(default=5, ge=1, le=64)


class ResetRequest(BaseModel):
    seed: int | None = None


def create_app(
    engine: SimulationEngine | None = None,
    autorun: bool = True,
    telemetry: TelemetryEmitter | None = None,
) -> FastAPI:
    sim = engine or SimulationEngine(SimulatorSettings())

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        task = asyncio.create_task(sim.run()) if autorun else None
        if telemetry is not None:
            await telemetry.start()
        try:
            yield
        finally:
            if task is not None:
                sim.stop()
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
            if telemetry is not None:
                await telemetry.stop()

    app = FastAPI(title="ReelOps simulator", version="0.1.0", lifespan=lifespan)
    app.state.engine = sim

    @app.get("/healthz")
    def healthz() -> dict[str, Any]:
        return {"status": "ok", "tick": sim.clock.tick_index, "sim_time": sim.sim_time.isoformat()}

    @app.get("/sim/state")
    def state() -> dict[str, Any]:
        return sim.snapshot().to_dict()

    @app.post("/sim/inject/render-worker-degradation")
    def inject(request: DegradationRequest) -> dict[str, Any]:
        sim.inject_render_worker_degradation(request.workers)
        logger.info("injected render worker degradation: workers=%s", request.workers)
        return {"accepted": True, "workers_requested": request.workers}

    @app.post("/sim/recover")
    def recover() -> dict[str, Any]:
        sim.recover()
        logger.info("restored render workers")
        return {"accepted": True}

    @app.post("/sim/reset")
    def reset(request: ResetRequest) -> dict[str, Any]:
        sim.reset(request.seed)
        logger.info("simulation reset: seed=%s", sim.seed)
        return {"accepted": True, "seed": sim.seed}

    return app


app = create_app()
