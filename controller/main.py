from __future__ import annotations

import argparse
import logging
import os
import signal
import sys

from .client import SimulatorClient
from .db import Database
from .loop import ControllerLoop

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("controller.main")


def main():
    parser = argparse.ArgumentParser(description="Autonomous Outcome Controller Loop")
    parser.add_argument("--url", default=os.environ.get("SIM_URL", "http://127.0.0.1:8700"), help="Simulator base URL")
    parser.add_argument("--db", default=os.environ.get("CONTROLLER_DB", "controller_state.db"), help="SQLite state DB path")
    parser.add_argument("--step-minutes", type=int, default=60, help="Advance step minutes (multiple of 15)")
    args = parser.parse_args()

    logger.info(f"Starting controller: URL={args.url}, DB={args.db}, step={args.step_minutes}m")
    db = Database(args.db)
    client = SimulatorClient(base_url=args.url)
    loop = ControllerLoop(client=client, db=db, tick_step_minutes=args.step_minutes)

    def handle_signal(sig, frame):
        logger.warning(f"Received signal {sig}. Saving checkpoint and shutting down gracefully...")
        loop.is_running = False
        loop.save_checkpoint()
        db.close()
        client.close()
        sys.exit(0)

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    try:
        loop.run()
    finally:
        db.close()
        client.close()


if __name__ == "__main__":
    main()
