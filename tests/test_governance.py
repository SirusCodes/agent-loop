import pytest
from controller.governance import (
    GovernanceEngine,
    compute_changed_dims,
    compute_json_diff,
    compute_max_shift,
)
from controller.models import ProposalIntent, ProposalRecord


def test_compute_changed_dims():
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

    # Voice changed
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

    # Prompt changed
    new_cfg_p = dict(old_cfg)
    new_cfg_p["prompt_version"] = "P3"
    dims_p = compute_changed_dims(old_cfg, new_cfg_p)
    assert dims_p == ["prompt_version"]


def test_compute_max_shift():
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
    # Permitted caller ID change within shift limit
    new_cfg_allowed = {
        "cohorts": [],
        "allocations": {"default": {"caller_id": {"D1": 0.3, "D2": 0.3, "D3": 0.4}}},
        "prompt_version": "P1",
    }
    ok, reason, dims = GovernanceEngine.can_auto_apply(spec, old_cfg, new_cfg_allowed)
    assert ok is True
    assert dims == ["caller_id"]

    # Disallowed dimension (voice)
    new_cfg_disallowed = {
        "cohorts": [],
        "allocations": {
            "default": {
                "caller_id": {"D1": 0.5, "D2": 0.5},
                "voice": {"V1": 0.5, "V2": 0.5},
            }
        },
        "prompt_version": "P1",
    }
    ok, reason, dims = GovernanceEngine.can_auto_apply(spec, old_cfg, new_cfg_disallowed)
    assert ok is False
    assert "not permitted" in reason


def test_is_approver_active():
    spec = {"governance": {"approver_hours": [10, 19]}}
    # 09:00 = 540 min -> inactive
    assert GovernanceEngine.is_approver_active(spec, 540) is False
    # 10:00 = 600 min -> active
    assert GovernanceEngine.is_approver_active(spec, 600) is True
    # 18:30 = 1110 min -> active
    assert GovernanceEngine.is_approver_active(spec, 1110) is True
    # 19:00 = 1140 min -> inactive
    assert GovernanceEngine.is_approver_active(spec, 1140) is False


def test_is_quota_available():
    spec = {"governance": {"max_requests_per_24h": 2}}
    # Sim minute 2000
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
    # 2 requests already in last 24h (2000 - 1440 = 560)
    assert GovernanceEngine.is_quota_available("w1", spec, [p1, p2], 2000) is False
    # Only 1 request in last 24h
    assert GovernanceEngine.is_quota_available("w1", spec, [p2], 2000) is True


def test_package_proposal():
    intent = ProposalIntent(
        workflow_id="nw_renewal",
        proposed_config={
            "cohorts": [],
            "allocations": {"default": {"voice": {"V2": 1.0}}},
            "prompt_version": "P1",
        },
        rationale="Optimize voice for better engagement",
        impact_score=0.45,
    )
    current_cfg = {
        "cohorts": [],
        "allocations": {"default": {"voice": {"V1": 1.0}}},
        "prompt_version": "P1",
    }
    spec = {
        "daily_batch": {"size": 1100},
        "governance": {"proposal_ttl_hours": 12},
    }
    body = GovernanceEngine.package_proposal(
        intent=intent,
        current_version=1,
        current_cfg=current_cfg,
        spec=spec,
        total_leads=2000,
        recent_metrics={"pickup_rate": 0.3, "engagement_rate": 0.55},
    )
    assert body["workflow_id"] == "nw_renewal"
    assert body["base_version"] == 1
    assert body["diff"] != {}
    assert body["affected_leads"] > 0
    assert 0 <= body["impact_score"] <= 1
    assert body["dry_run"] != {}
    assert body["expires_in_hours"] == 12
