import pytest
from controller.governance import (
    GovernanceEngine,
    compute_changed_dims,
    compute_json_diff,
    compute_max_shift,
)
from controller.models import ProposalIntent, ProposalRecord


def test_get_dispatch_slots_and_is_dispatch_time():
    """Verify that dispatch slots are dynamically calculated across approver hours.

    Example:
        approver_hours: [12, 18] -> 720 min to 1080 min.
        close_buffer_minutes: 30 -> effective end at 1050 min (17:30).
        effective_duration = 1050 - 720 = 330 min.
        max_requests_per_24h = 3 -> interval = 110 min.
        Expected slots: [720, 830, 940] (12:00, 13:50, 15:40 IST).
    """
    spec = {
        "governance": {
            "approver_hours": [12, 18],
            "max_requests_per_24h": 3,
        }
    }
    slots = GovernanceEngine.get_dispatch_slots(spec, close_buffer_minutes=30)
    assert len(slots) == 3
    assert slots[0] == 720  # 12:00 PM
    assert slots[1] == 830  # 1:50 PM
    assert slots[2] == 940  # 3:40 PM

    # Test is_dispatch_time within the step window
    assert GovernanceEngine.is_dispatch_time(spec, sim_minute=720, tick_step_minutes=60) is True
    assert GovernanceEngine.is_dispatch_time(spec, sim_minute=750, tick_step_minutes=60) is True
    # 10:00 AM is prior to the 12:00 window opening
    assert GovernanceEngine.is_dispatch_time(spec, sim_minute=600, tick_step_minutes=60) is False


def test_bundle_intents():
    """Verify that multiple intents touching distinct dimensions are bundled into one proposal."""
    base_cfg = {
        "allocations": {
            "default": {
                "voice": {"V1": 1.0},
                "welcome_message": {"W1": 1.0},
            }
        },
        "prompt_version": "P1",
    }
    intent1 = ProposalIntent(
        workflow_id="w1",
        proposed_config={
            "allocations": {"default": {"voice": {"V2": 1.0}}},
            "prompt_version": "P1",
        },
        rationale="Better voice engagement",
        changed_dims=["voice"],
        impact_score=0.3,
    )
    intent2 = ProposalIntent(
        workflow_id="w1",
        proposed_config={
            "allocations": {"default": {"welcome_message": {"W2": 1.0}}},
            "prompt_version": "P1",
        },
        rationale="Better welcome message",
        changed_dims=["welcome_message"],
        impact_score=0.4,
    )
    bundled = GovernanceEngine.bundle_intents([intent1, intent2], base_cfg)
    assert set(bundled.changed_dims) == {"voice", "welcome_message"}
    assert bundled.impact_score == 0.4
    assert bundled.proposed_config["allocations"]["default"]["voice"] == {"V2": 1.0}
    assert bundled.proposed_config["allocations"]["default"]["welcome_message"] == {"W2": 1.0}
    assert "Bundled updates" in bundled.change_summary


def test_compute_changed_dims():
    """Verify that dimension changes are accurately isolated."""
    old_cfg = {
        "cohorts": [],
        "allocations": {
            "default": {
                "welcome_message": {"W1": 1.0},
                "voice": {"V1": 1.0},
                "caller_id": {"D1": 0.5, "D2": 0.5},
            }
        },
        "prompt_version": "P1",
        "schedule": {},
    }

    new_cfg = {
        "cohorts": [],
        "allocations": {
            "default": {
                "welcome_message": {"W1": 1.0},
                "voice": {"V1": 0.5, "V2": 0.5},
                "caller_id": {"D1": 0.5, "D2": 0.5},
            }
        },
        "prompt_version": "P1",
        "schedule": {},
    }
    dims = compute_changed_dims(old_cfg, new_cfg)
    assert dims == ["voice"]


def test_compute_max_shift():
    """Verify Total Variation distance calculation matches platform specification."""
    old_cfg = {
        "cohorts": [],
        "allocations": {"default": {"voice": {"V1": 1.0}}},
    }
    new_cfg = {
        "cohorts": [],
        "allocations": {"default": {"voice": {"V1": 0.7, "V2": 0.3}}},
    }
    shift = compute_max_shift(old_cfg, new_cfg)
    # TV distance = 0.5 * (|1 - 0.7| + |0 - 0.3|) = 0.5 * (0.3 + 0.3) = 0.3
    assert abs(shift - 0.3) < 1e-6


def test_can_auto_apply():
    """Verify that auto-apply enforces allowed dimensions and max shift constraints."""
    spec = {
        "governance": {
            "auto_apply": {
                "enabled": True,
                "allowed_dims": ["caller_id", "schedule"],
                "max_shift": 0.5,
            }
        }
    }
    old_cfg = {
        "cohorts": [],
        "allocations": {"default": {"caller_id": {"D1": 0.5, "D2": 0.5}}},
        "prompt_version": "P1",
    }
    new_cfg_allowed = {
        "cohorts": [],
        "allocations": {"default": {"caller_id": {"D1": 0.3, "D2": 0.3, "D3": 0.4}}},
        "prompt_version": "P1",
    }
    ok, reason, dims = GovernanceEngine.can_auto_apply(spec, old_cfg, new_cfg_allowed)
    assert ok is True
    assert dims == ["caller_id"]


def test_is_quota_available():
    """Verify that request limits per 24 hours are enforced."""
    spec = {"governance": {"max_requests_per_24h": 2}}
    p1 = ProposalRecord(
        proposal_id="p1", workflow_id="w1", base_version=1, status="pending",
        change_summary="s", proposed_config={}, diff={}, affected_leads=10,
        dry_run={}, impact_score=0.2, created_minute=1000
    )
    p2 = ProposalRecord(
        proposal_id="p2", workflow_id="w1", base_version=1, status="pending",
        change_summary="s", proposed_config={}, diff={}, affected_leads=10,
        dry_run={}, impact_score=0.2, created_minute=1500
    )
    assert GovernanceEngine.is_quota_available("w1", spec, [p1, p2], 2000) is False
    assert GovernanceEngine.is_quota_available("w1", spec, [p2], 2000) is True
