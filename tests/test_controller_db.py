import tempfile
from pathlib import Path

import pytest
from controller.db import Database
from controller.models import AuditEntry, Checkpoint, ProposalRecord


@pytest.fixture
def temp_db():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        db = Database(db_path)
        yield db
        db.close()


def test_checkpoint_roundtrip(temp_db):
    assert temp_db.load_checkpoint() is None

    cp = Checkpoint(last_chunk_id=5, last_event_id=120, sim_minute=600, sim_ts="2027-01-04T10:00:00+05:30")
    temp_db.save_checkpoint(cp)

    loaded = temp_db.load_checkpoint()
    assert loaded is not None
    assert loaded.last_chunk_id == 5
    assert loaded.last_event_id == 120
    assert loaded.sim_minute == 600
    assert loaded.sim_ts == "2027-01-04T10:00:00+05:30"

    # Update checkpoint
    cp2 = Checkpoint(last_chunk_id=6, last_event_id=150, sim_minute=720, sim_ts="2027-01-04T12:00:00+05:30")
    temp_db.save_checkpoint(cp2)

    loaded2 = temp_db.load_checkpoint()
    assert loaded2.last_chunk_id == 6
    assert loaded2.last_event_id == 150


def test_audit_log(temp_db):
    entry = AuditEntry(
        ts="2027-01-04T11:00:00+05:30",
        sim_minute=660,
        workflow_id="nw_renewal",
        actor="supervisor",
        action="config_changed",
        changed_dims=["voice"],
        diff={"voice": "V2"},
        rationale="Supervisor manual change",
        impact_score=0.2,
        evidence={"approval_id": None},
        before_metrics={"pickup": 0.3},
        after_metrics={"pickup": 0.35},
    )
    row_id = temp_db.record_audit(entry)
    assert row_id > 0

    results = temp_db.query_audit(workflow_id="nw_renewal")
    assert len(results) == 1
    assert results[0].workflow_id == "nw_renewal"
    assert results[0].actor == "supervisor"
    assert results[0].changed_dims == ["voice"]
    assert results[0].diff == {"voice": "V2"}


def test_proposals_upsert(temp_db):
    prop = ProposalRecord(
        proposal_id="p-001",
        workflow_id="nw_renewal",
        base_version=1,
        status="pending",
        change_summary="Explore voices",
        proposed_config={"allocations": {}},
        diff={"voice": "V2"},
        affected_leads=500,
        dry_run={"score": 0.1},
        impact_score=0.4,
    )
    temp_db.upsert_proposal(prop)

    fetched = temp_db.get_proposal("p-001")
    assert fetched is not None
    assert fetched.status == "pending"
    assert fetched.affected_leads == 500

    # Update status
    prop.status = "approved"
    prop.approval_id = "apr_001"
    temp_db.upsert_proposal(prop)

    fetched2 = temp_db.get_proposal("p-001")
    assert fetched2.status == "approved"
    assert fetched2.approval_id == "apr_001"
