from __future__ import annotations

import logging
import time
from typing import Any

from .client import BaseClient
from .db import Database
from .models import Checkpoint
from .state import StateManager

logger = logging.getLogger("controller.loop")


class ControllerLoop:
    def __init__(self, client: BaseClient, db: Database, tick_step_minutes: int = 60):
        self.client = client
        self.db = db
        self.tick_step_minutes = tick_step_minutes
        self.state_mgr = StateManager(db)
        self.sim_minute = 0
        self.sim_ts = ""
        self.last_chunk_id = -1
        self.last_event_id = -1
        self.is_running = True

    def setup(self):
        """Initialize workflows and recover state from checkpoints or history."""
        # 1. Fetch workflows from platform
        wfs = self.client.get_workflows()
        for w in wfs:
            wid = w["workflow_id"]
            cfg_data = self.client.get_config(wid)
            self.state_mgr.register_workflow(wid, w, cfg_data)
        logger.info(f"Registered {len(wfs)} workflows.")

        # 2. Check for existing checkpoint
        cp = self.db.load_checkpoint()
        if cp:
            self.last_chunk_id = cp.last_chunk_id
            self.last_event_id = cp.last_event_id
            self.sim_minute = cp.sim_minute
            self.sim_ts = cp.sim_ts
            logger.info(f"Resumed from checkpoint: chunk={self.last_chunk_id}, event={self.last_event_id}, minute={self.sim_minute}")
        else:
            # 3. Bootstrap from history chunks if starting fresh
            history_chunks = self.client.get_chunks(kind="history", after=-1)
            logger.info(f"Ingesting {len(history_chunks)} history chunks...")
            for ch in history_chunks:
                self._ingest_chunk(ch)
            state = self.client.get_state()
            self.sim_minute = state.get("sim_minute", 0)
            self.sim_ts = state.get("ts", "")
            self.save_checkpoint()

    def _ingest_chunk(self, chunk_meta: dict[str, Any]):
        cid = chunk_meta["chunk"]
        for ev in self.client.stream_chunk_events(cid):
            self.state_mgr.process_event(ev, self.sim_minute)
            eid = ev.get("event_id")
            if eid is not None and eid > self.last_event_id:
                self.last_event_id = eid
        self.last_chunk_id = max(self.last_chunk_id, cid)

    def save_checkpoint(self):
        cp = Checkpoint(
            last_chunk_id=self.last_chunk_id,
            last_event_id=self.last_event_id,
            sim_minute=self.sim_minute,
            sim_ts=self.sim_ts,
        )
        self.db.save_checkpoint(cp)

    def step(self) -> bool:
        """Advance simulation by tick_step_minutes, process events, and checkpoint. Returns False when finished."""
        # Check simulator state or advance
        adv = self.client.advance(self.tick_step_minutes)
        self.sim_minute = adv.get("sim_minute", self.sim_minute + self.tick_step_minutes)
        self.sim_ts = adv.get("ts", self.sim_ts)
        finished = adv.get("finished", False)

        new_chunks = adv.get("new_chunks", [])
        for ch in new_chunks:
            self._ingest_chunk(ch)

        self.save_checkpoint()
        return not finished

    def run(self):
        self.setup()
        step_count = 0
        start_wall = time.time()
        while self.is_running:
            more = self.step()
            step_count += 1
            if step_count % 24 == 0:  # log every 24 steps (approx 1 day at 60min/step)
                elapsed = time.time() - start_wall
                logger.info(f"[{self.sim_ts}] Day completed. Total steps: {step_count}, Wall-clock: {elapsed:.2f}s, Last Event: {self.last_event_id}")
            if not more:
                logger.info(f"Simulation finished at minute {self.sim_minute} ({self.sim_ts}).")
                break
