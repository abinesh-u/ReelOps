"""`python -m simulator` — run the simulator and its control API."""

import logging

import uvicorn

from simulator.api import create_app
from simulator.config import SimulatorSettings


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    settings = SimulatorSettings()
    uvicorn.run(create_app(), host="0.0.0.0", port=settings.sim_api_port, log_level="info")


if __name__ == "__main__":
    main()
