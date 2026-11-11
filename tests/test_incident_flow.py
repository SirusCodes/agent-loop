import tempfile
from pathlib import Path

from controller.db import Database
from controller.loop import ControllerLoop
from sim.scenario import load_scenario
from sim.world import World
from tests.test_controller_ingest import DirectWorldClient


def test_public_02_incidents_remediation():
    """Integration test verifying incident handling on public_02_incidents.

    In public_02_incidents:
    - At D2 10:00: DID D2 on ks_cancel is spam-flagged (health drops to 0.35).
    - At D3 11:30: Supervisor ships prompt P2 on ks_cancel (hallucination rate spikes to 5.5%).
    We advance through D4 and verify that the controller remediates both incidents cleanly.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        sc = load_scenario("scenarios/public_02_incidents.yaml")
        # Run 5 days to cover D2 DID flag and D3 supervisor edit
        sc["days"] = 5
        world = World(sc, tmp_path / "sim_run")

        client = DirectWorldClient(world)
        db = Database(tmp_path / "test_ctrl.db")

        loop = ControllerLoop(client=client, db=db, tick_step_minutes=30)
        loop.setup()

        # Step through simulation
        while loop.step():
            pass

        # 1. Verify DID rotation on ks_cancel occurred (rotated traffic away from degraded D2)
        ks_wf = loop.state_mgr.workflows["ks_cancel"]
        cur_did_alloc = ks_wf.current_config.get("allocations", {}).get("default", {}).get("caller_id", {})
        assert cur_did_alloc.get("D2", 0.0) == 0.0, "Expected degraded DID D2 to be rotated away"

        # 2. Verify prompt remediation occurred on ks_cancel
        # P2 was shipped by supervisor at D3 11:30 (5.5% hallucination rate).
        # Controller detected the spike and replaced P2 with a validated safe prompt (e.g. P3, P5).
        cur_prompt = ks_wf.current_config.get("prompt_version")
        assert cur_prompt != "P2", "Expected hallucinating prompt P2 to be remediated"
        assert cur_prompt in ("P1", "P3", "P4", "P5"), f"Expected safe prompt, got {cur_prompt}"

        # 3. Verify proposals were recorded in DB
        proposals = db.list_proposals(workflow_id="ks_cancel")
        applied_prompts = [
            p for p in proposals
            if "prompt_version" in p.diff and p.status == "applied"
        ]
        assert len(applied_prompts) >= 1, "Expected applied prompt remediation proposal in audit DB"
