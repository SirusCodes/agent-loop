import copy
import tempfile
from pathlib import Path

from controller.db import Database
from controller.loop import ControllerLoop
from controller.models import ProposalIntent
from sim.scenario import load_scenario
from sim.world import World
from tests.test_controller_ingest import DirectWorldClient


def test_governance_integration_auto_apply_and_approval():
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        sc = load_scenario("scenarios/public_01_dev.yaml")
        sc["days"] = 2
        sc["history_days"] = 1
        world = World(sc, tmp_path / "sim_run")

        client = DirectWorldClient(world)
        db = Database(tmp_path / "test_ctrl.db")

        loop = ControllerLoop(client=client, db=db, tick_step_minutes=60)
        loop.setup()

        wid = "nw_renewal"
        wf = loop.state_mgr.workflows[wid]

        # 1. Test auto-apply path (caller_id shift permitted on nw_renewal)
        cur_cfg = copy.deepcopy(wf.current_config)
        cur_cfg["allocations"]["default"]["caller_id"] = {"D1": 0.4, "D2": 0.4, "D3": 0.2}

        auto_intent = ProposalIntent(
            workflow_id=wid,
            proposed_config=cur_cfg,
            rationale="Rotate and balance caller IDs",
            impact_score=0.2,
        )
        wf.queued_intents.append(auto_intent)

        # Advance one step (60 min)
        loop.step()

        # Verify auto-apply occurred
        assert wf.current_version == 2
        applied_props = db.list_proposals(workflow_id=wid, status="applied")
        assert len(applied_props) >= 1
        assert "caller_id" in applied_props[0].change_summary or "auto_apply" in applied_props[0].dry_run.get("mode", "")

        # 2. Test formal approval path (voice shift not in allowed_dims for auto-apply on nw_renewal)
        v2_cfg = copy.deepcopy(wf.current_config)
        v2_cfg["allocations"]["default"]["voice"] = {"V1": 0.5, "V2": 0.5}

        approval_intent = ProposalIntent(
            workflow_id=wid,
            proposed_config=v2_cfg,
            rationale="A/B test voices V1 and V2",
            change_summary="Explore V1 and V2 voices",
            impact_score=0.4,
        )
        wf.queued_intents.append(approval_intent)

        # Step until approver window opens and approval is decided & applied
        max_steps = 30
        applied_voice = False
        while max_steps > 0 and loop.step():
            max_steps -= 1
            if wf.current_config.get("allocations", {}).get("default", {}).get("voice") == {"V1": 0.5, "V2": 0.5}:
                applied_voice = True
                break

        assert applied_voice, "Expected approved voice change to be applied successfully"
        assert wf.current_version >= 3
