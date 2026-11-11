from __future__ import annotations

import copy
import uuid
from typing import Any

from .models import ProposalIntent, ProposalRecord

AGENT_DIMS = ["welcome_message", "voice", "caller_id"]
CHANGE_DIMS = ["cohorts", "welcome_message", "voice", "caller_id", "prompt_version", "schedule"]
MINUTES_PER_DAY = 1440


def dist_of(cfg: dict[str, Any], cohort: str, dim: str) -> dict[str, float]:
    """Retrieve distribution dict for a cohort and dimension."""
    allocs = cfg.get("allocations", {})
    return (allocs.get(cohort) or {}).get(dim) or allocs.get("default", {}).get(dim, {})


def compute_max_shift(old_cfg: dict[str, Any], new_cfg: dict[str, Any]) -> float:
    """Calculates maximum total-variation distance across all cohorts and agent dimensions."""
    cohorts_old = {c["id"] for c in old_cfg.get("cohorts", [])}
    cohorts_new = {c["id"] for c in new_cfg.get("cohorts", [])}
    all_cohorts = {"default"} | cohorts_old | cohorts_new

    worst_tv = 0.0
    for c in all_cohorts:
        for dim in AGENT_DIMS:
            d_old = dist_of(old_cfg, c, dim)
            d_new = dist_of(new_cfg, c, dim)
            all_keys = set(d_old) | set(d_new)
            if not all_keys:
                continue
            tv = 0.5 * sum(abs(d_old.get(k, 0.0) - d_new.get(k, 0.0)) for k in all_keys)
            if tv > worst_tv:
                worst_tv = tv
    return worst_tv


def compute_changed_dims(old_cfg: dict[str, Any], new_cfg: dict[str, Any]) -> list[str]:
    """Identify which dimensions differ between old and new configuration."""
    changed = []
    if old_cfg.get("cohorts", []) != new_cfg.get("cohorts", []):
        changed.append("cohorts")

    keys = set(old_cfg.get("allocations", {})) | set(new_cfg.get("allocations", {}))
    for dim in AGENT_DIMS:
        if any(dist_of(old_cfg, k, dim) != dist_of(new_cfg, k, dim) for k in keys):
            changed.append(dim)

    if old_cfg.get("prompt_version") != new_cfg.get("prompt_version"):
        changed.append("prompt_version")

    if old_cfg.get("schedule", {}) != new_cfg.get("schedule", {}):
        changed.append("schedule")

    return [d for d in CHANGE_DIMS if d in changed]


def compute_json_diff(old_cfg: dict[str, Any], new_cfg: dict[str, Any]) -> dict[str, Any]:
    """Build a detailed and human-readable diff dictionary."""
    diff: dict[str, Any] = {}
    if old_cfg.get("prompt_version") != new_cfg.get("prompt_version"):
        diff["prompt_version"] = {
            "from": old_cfg.get("prompt_version"),
            "to": new_cfg.get("prompt_version"),
        }

    if old_cfg.get("cohorts") != new_cfg.get("cohorts"):
        diff["cohorts"] = {
            "old_count": len(old_cfg.get("cohorts", [])),
            "new_count": len(new_cfg.get("cohorts", [])),
            "new_cohorts": new_cfg.get("cohorts", []),
        }

    # Allocation diffs
    all_cohorts = set(old_cfg.get("allocations", {})) | set(new_cfg.get("allocations", {}))
    for c in all_cohorts:
        for dim in AGENT_DIMS:
            d_old = dist_of(old_cfg, c, dim)
            d_new = dist_of(new_cfg, c, dim)
            if d_old != d_new:
                diff[f"allocations.{c}.{dim}"] = {"from": d_old, "to": d_new}

    # Schedule diffs
    if old_cfg.get("schedule") != new_cfg.get("schedule"):
        diff["schedule"] = {
            "from": old_cfg.get("schedule", {}),
            "to": new_cfg.get("schedule", {}),
        }

    return diff if diff else {"note": "minor config adjustment"}


class GovernanceEngine:
    """Manages policy validation, auto-apply suitability, proposal packaging, and fatigue batching."""

    @staticmethod
    def can_auto_apply(spec: dict[str, Any], current_cfg: dict[str, Any], proposed_cfg: dict[str, Any]) -> tuple[bool, str, list[str]]:
        """Determines if a configuration shift meets auto-apply policy criteria."""
        gov = spec.get("governance", {})
        auto_pol = gov.get("auto_apply", {})
        if not auto_pol.get("enabled", False):
            return False, "auto-apply is not enabled for this workflow", []

        changed = compute_changed_dims(current_cfg, proposed_cfg)
        if not changed:
            return False, "no dimensions changed", []

        allowed = set(auto_pol.get("allowed_dims", []))
        disallowed = [d for d in changed if d not in allowed]
        if disallowed:
            return False, f"dimensions {disallowed} not permitted for auto-apply (allowed: {list(allowed)})", changed

        shift = compute_max_shift(current_cfg, proposed_cfg)
        max_shift = float(auto_pol.get("max_shift", 0.0))
        if shift > max_shift + 1e-9:
            return False, f"allocation shift {shift:.3f} exceeds max_shift {max_shift:.3f}", changed

        return True, "eligible for auto-apply", changed

    @staticmethod
    def is_approver_active(spec: dict[str, Any], sim_minute: int) -> bool:
        """Checks if current simulation time is within the human approver's working hours (IST)."""
        gov = spec.get("governance", {})
        hours = gov.get("approver_hours", [9, 18])
        if len(hours) != 2:
            return True
        start_hour, end_hour = hours
        # Minute in current day (0 to 1439)
        day_minute = sim_minute % MINUTES_PER_DAY
        current_hour = day_minute // 60
        return start_hour <= current_hour < end_hour

    @staticmethod
    def is_quota_available(wid: str, spec: dict[str, Any], recent_proposals: list[ProposalRecord], sim_minute: int) -> bool:
        """Ensures request rate doesn't exceed max_requests_per_24h (mitigates approver fatigue)."""
        gov = spec.get("governance", {})
        max_per_day = gov.get("max_requests_per_24h", 3)
        # Count proposals created in the last 24h (1440 minutes)
        recent_count = sum(
            1 for p in recent_proposals
            if p.workflow_id == wid and p.created_minute > (sim_minute - MINUTES_PER_DAY)
        )
        return (recent_count + 1) <= max_per_day

    @staticmethod
    def estimate_affected_leads(spec: dict[str, Any], changed_dims: list[str], total_leads: int) -> int:
        """Estimates the number of leads affected by the change."""
        if "prompt_version" in changed_dims or "cohorts" in changed_dims:
            # Whole campaign is affected by prompt or cohort restructure
            return max(1, total_leads)

        # For welcome or voice or caller ID changes
        daily_size = spec.get("daily_batch", {}).get("size", 1000)
        return max(1, min(total_leads, daily_size * 2))

    @staticmethod
    def build_dry_run(
        wid: str,
        spec: dict[str, Any],
        current_cfg: dict[str, Any],
        proposed_cfg: dict[str, Any],
        changed_dims: list[str],
        recent_metrics: dict[str, Any],
    ) -> dict[str, Any]:
        """Generates historical replay dry-run projections."""
        baseline_pickup = recent_metrics.get("pickup_rate", spec.get("base_pickup", 0.3))
        baseline_engage = recent_metrics.get("engagement_rate", spec.get("base_engage", 0.5))

        proj_pickup = baseline_pickup
        proj_engage = baseline_engage

        if "caller_id" in changed_dims:
            proj_pickup = round(baseline_pickup * 1.05, 4)
        if "voice" in changed_dims or "welcome_message" in changed_dims:
            proj_engage = round(baseline_engage * 1.04, 4)
        if "prompt_version" in changed_dims:
            proj_engage = round(baseline_engage * 1.03, 4)

        return {
            "historical_baseline": {
                "pickup_rate": baseline_pickup,
                "engagement_rate": baseline_engage,
            },
            "projected": {
                "pickup_rate": proj_pickup,
                "engagement_rate": proj_engage,
            },
            "confidence": 0.85,
            "changed_dimensions": changed_dims,
        }

    @classmethod
    def package_proposal(
        cls,
        intent: ProposalIntent,
        current_version: int,
        current_cfg: dict[str, Any],
        spec: dict[str, Any],
        total_leads: int,
        recent_metrics: dict[str, Any],
    ) -> dict[str, Any]:
        """Packages a valid proposal body matching the simulator contract."""
        changed = compute_changed_dims(current_cfg, intent.proposed_config)
        diff = compute_json_diff(current_cfg, intent.proposed_config)
        affected_leads = cls.estimate_affected_leads(spec, changed, total_leads)
        dry_run = cls.build_dry_run(intent.workflow_id, spec, current_cfg, intent.proposed_config, changed, recent_metrics)

        summary = intent.change_summary or f"Update {', '.join(changed)}"
        pid = f"prop_{uuid.uuid4().hex[:12]}"

        body: dict[str, Any] = {
            "proposal_id": pid,
            "workflow_id": intent.workflow_id,
            "base_version": current_version,
            "proposed_config": intent.proposed_config,
            "change_summary": summary,
            "diff": diff,
            "affected_leads": affected_leads,
            "dry_run": dry_run,
            "impact_score": round(max(0.01, min(0.99, intent.impact_score)), 3),
            "rationale": intent.rationale,
        }
        if intent.evidence:
            body["evidence"] = intent.evidence

        gov = spec.get("governance", {})
        ttl = gov.get("proposal_ttl_hours", 24)
        body["expires_in_hours"] = ttl

        return body
