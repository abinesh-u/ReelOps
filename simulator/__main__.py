"""`python -m simulator` — run the simulator and its control API."""

import logging

import uvicorn

from simulator.api import create_app
from simulator.config import SimulatorSettings
from simulator.engine import SimulationEngine
from telemetry.emitter import create_emitter


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    settings = SimulatorSettings()
    engine = SimulationEngine(settings)
    # Raises if telemetry is on with nowhere to export to, before the port opens.
    app = create_app(engine, telemetry=create_emitter(engine))
    uvicorn.run(app, host="0.0.0.0", port=settings.sim_api_port, log_level="info")


if __name__ == "__main__":
    main()
