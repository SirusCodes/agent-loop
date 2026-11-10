import tempfile
from pathlib import Path

from controller.db import Database
from controller.loop import ControllerLoop
from sim.scenario import load_scenario
from sim.world import World


class DirectWorldClient:
    """Adapter bridging Controller's BaseClient directly to in-memory sim World for fast integration tests."""

    def __init__(self, world: World):
        self.world = world

    def get_state(self):
        return self.world.state()

    def advance(self, minutes: int):
        return self.world.advance(minutes)

    def get_workflows(self):
        return [self.world.workflow_public(wid) for wid in self.world.wfs]

    def get_workflow(self, wid: str):
        return self.world.workflow_public(wid)

    def get_config(self, wid: str):
        return self.world.get_config(wid)

    def get_chunks(self, kind: str = "events", after: int = -1):
        return [c for c in self.world.chunks if c["kind"] == kind and c["chunk"] > after]

    def stream_chunk_events(self, chunk_num: int):
        import json
        c = self.world.chunks[chunk_num]
        path = Path(self.world.run_dir) / c["path"]
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line:
                    yield json.loads(line)

    def request_approval(self, body):
        return self.world.request_approval(body)

    def get_approval(self, aid: str):
        return self.world.get_approval(aid)

    def list_approvals(self, wid=None, status=None):
        return self.world.list_approvals(wid, status)

    def apply_approval(self, wid: str, aid: str):
        return self.world.apply_approval(wid, aid)

    def auto_apply(self, wid: str, body):
        return self.world.auto_apply(wid, body)

    def suggest_fixes(self, wid: str, problem: str):
        return self.world.suggest_fixes({"workflow_id": wid, "problem": problem})

    def run_validation(self, wid: str, pv: str, n: int):
        return self.world.run_validation({"workflow_id": wid, "prompt_version": pv, "n": n})


def test_ingestion_with_sim_world():
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        sc = load_scenario("scenarios/public_01_dev.yaml")
        sc["days"] = 1
        sc["history_days"] = 1
        world = World(sc, tmp_path / "sim_run")

        client = DirectWorldClient(world)
        db = Database(tmp_path / "test_ctrl.db")

        loop = ControllerLoop(client=client, db=db, tick_step_minutes=60)
        loop.setup()

        # Verify bootstrap ingested history
        assert loop.last_chunk_id >= 0
        assert loop.last_event_id > 0

        # Step through the 1-day simulation
        while loop.step():
            pass

        # Check DB checkpoint
        cp = db.load_checkpoint()
        assert cp is not None
        assert cp.sim_minute >= 1440
        assert cp.last_event_id > 0

        # Verify workflow stats were populated
        for wid, wf_state in loop.state_mgr.workflows.items():
            metrics = wf_state.get_metrics_snapshot()
            assert metrics["total_dials"] > 0
            assert metrics["total_connected"] > 0
