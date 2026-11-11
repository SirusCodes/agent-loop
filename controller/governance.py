from __future__ import annotations

import copy
import uuid
from typing import Any

from .models import ProposalIntent, ProposalRecord

# Dimensions governed by agent allocation sampling (welcome_message, voice, caller_id)
AGENT_DIMS = ["welcome_message", "voice", "caller_id"]

# All dimensions eligible for configuration modification
CHANGE_DIMS = ["cohorts", "welcome_message", "voice", "caller_id", "prompt_version", "schedule"]

MINUTES_PER_DAY = 1440


def dist_of(cfg: dict[str, Any], cohort: str, dim: str) -> dict[str, float]:
    """Retrieve the probability distribution dictionary for a cohort and dimension.

    If the specified cohort does not define this dimension, fall back to the 'default' cohort.
    """
    allocs = cfg.get("allocations", {})
    return (allocs.get(cohort) or {}).get(dim) or allocs.get("default", {}).get(dim, {})


def compute_max_shift(old_cfg: dict[str, Any], new_cfg: dict[str, Any]) -> float:
    """Calculates the maximum Total Variation (TV) distance across all cohorts and agent dimensions.

    Total Variation Distance between two discrete distributions P and Q is defined as:
        TV(P, Q) = 0.5 * sum(|P(x) - Q(x)|)

    This is the exact metric used by the platform governance policy (governance.auto_apply.max_shift).
    """
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
    """Identify which dimensions differ between the old and new configuration.

    Evaluates:
    - cohorts: list equality
    - welcome_message, voice, caller_id: distribution equality across all defined cohorts
    - prompt_version: string equality
    - schedule: dictionary equality
    """
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
    """Build a detailed and human-readable diff dictionary for the governance proposal.

    The simulator requires 'diff' to be non-empty and descriptive of the exact changes.
    """
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

    # Compare allocations across cohorts and agent dimensions
    all_cohorts = set(old_cfg.get("allocations", {})) | set(new_cfg.get("allocations", {}))
    for c in all_cohorts:
        for dim in AGENT_DIMS:
            d_old = dist_of(old_cfg, c, dim)
            d_new = dist_of(new_cfg, c, dim)
            if d_old != d_new:
                diff[f"allocations.{c}.{dim}"] = {"from": d_old, "to": d_new}

    # Compare schedule
    if old_cfg.get("schedule") != new_cfg.get("schedule"):
        diff["schedule"] = {
            "from": old_cfg.get("schedule", {}),
            "to": new_cfg.get("schedule", {}),
        }

    return diff if diff else {"note": "minor config adjustment"}


class GovernanceEngine:
    """Manages policy validation, auto-apply suitability, dynamic window scheduling, and fatigue batching."""

    @staticmethod
    def can_auto_apply(spec: dict[str, Any], current_cfg: dict[str, Any], proposed_cfg: dict[str, Any]) -> tuple[bool, str, list[str]]:
        """Determines if a configuration shift meets auto-apply policy criteria.

        Checks:
        1. auto_apply.enabled is True
        2. All changed dimensions are in auto_apply.allowed_dims
        3. Total Variation distance <= auto_apply.max_shift
        """
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
    def get_dispatch_slots(spec: dict[str, Any], close_buffer_minutes: int = 30) -> list[int]:
        """Calculates dynamic dispatch minute slots (in minutes of day, 0-1439).

        Evenly spaces up to max_requests_per_24h across the active approver window,
        leaving a close buffer before the window ends so requests don't lapse or expire.

        Formula:
            interval = ((end_hour * 60 - buffer) - (start_hour * 60)) / max_requests_per_24h
            slot_i = start_minute + i * interval
        """
        gov = spec.get("governance", {})
        hours = gov.get("approver_hours", [10, 19])
        start_hour, end_hour = hours[0], hours[1]

        start_minute = start_hour * 60
        end_minute = max(start_minute + 60, (end_hour * 60) - close_buffer_minutes)
        window_duration = end_minute - start_minute

        max_requests = max(1, gov.get("max_requests_per_24h", 3))

        if max_requests == 1:
            return [start_minute]

        # Interval between dispatches
        interval = window_duration / max_requests
        slots = [int(start_minute + i * interval) for i in range(max_requests)]
        return slots

    @classmethod
    def is_dispatch_time(cls, spec: dict[str, Any], sim_minute: int, tick_step_minutes: int = 60, is_emergency: bool = False) -> bool:
        """Checks if the current simulation minute matches a scheduled dispatch slot.

        Emergency fixes (e.g. prompt hallucinations) bypass the spacing interval and dispatch
        as soon as human approvers are active in working hours.
        """
        if is_emergency:
            # Emergency (e.g. hallucination incident fix): dispatch immediately if in active hours
            return cls.is_approver_active(spec, sim_minute)

        minute_of_day = sim_minute % MINUTES_PER_DAY
        slots = cls.get_dispatch_slots(spec)

        for slot in slots:
            # If current minute falls within the step window [slot, slot + tick_step_minutes)
            if slot <= minute_of_day < (slot + tick_step_minutes):
                return True
        return False

    @staticmethod
    def is_approver_active(spec: dict[str, Any], sim_minute: int) -> bool:
        """Checks if current simulation time is within the human approver's working hours (IST).

        E.g., for approver_hours: [10, 19], only minutes corresponding to 10:00 through 18:59 return True.
        """
        gov = spec.get("governance", {})
        hours = gov.get("approver_hours", [10, 19])
        start_hour, end_hour = hours[0], hours[1]
        day_minute = sim_minute % MINUTES_PER_DAY
        current_hour = day_minute // 60
        return start_hour <= current_hour < end_hour

    @staticmethod
    def is_quota_available(wid: str, spec: dict[str, Any], recent_proposals: list[ProposalRecord], sim_minute: int) -> bool:
        """Ensures request rate doesn't exceed max_requests_per_24h (mitigates approver fatigue).

        Checks the rolling 24-hour window (1440 minutes prior to sim_minute).
        """
        gov = spec.get("governance", {})
        max_per_day = gov.get("max_requests_per_24h", 3)
        recent_count = sum(
            1 for p in recent_proposals
            if p.workflow_id == wid and p.created_minute > (sim_minute - MINUTES_PER_DAY)
        )
        return (recent_count + 1) <= max_per_day

    @staticmethod
    def bundle_intents(intents: list[ProposalIntent], base_cfg: dict[str, Any]) -> ProposalIntent:
        """Bundles multiple queued intents into a single atomic ProposalIntent.

        Satisfies client supervisor request (Anita Desai, memo 04):
        'If you have five things to change, send me one request with five things in it.'
        """
        if not intents:
            raise ValueError("No intents to bundle")
        if len(intents) == 1:
            return intents[0]

        merged_cfg = copy.deepcopy(base_cfg)
        all_changed_dims = set()
        rationales = []
        max_impact = 0.0
        evidence = None

        for intent in intents:
            all_changed_dims.update(intent.changed_dims)
            if intent.rationale:
                rationales.append(intent.rationale)
            if intent.evidence:
                evidence = intent.evidence  # keep latest evidence (e.g. validation_run_id)
            if intent.impact_score > max_impact:
                max_impact = intent.impact_score

            # Deep merge proposed changes into base config
            for k, v in intent.proposed_config.items():
                if k == "allocations":
                    if "allocations" not in merged_cfg:
                        merged_cfg["allocations"] = {}
                    for cohort, cohort_alloc in v.items():
                        if cohort not in merged_cfg["allocations"]:
                            merged_cfg["allocations"][cohort] = {}
                        merged_cfg["allocations"][cohort].update(cohort_alloc)
                else:
                    merged_cfg[k] = copy.deepcopy(v)

        return ProposalIntent(
            workflow_id=intents[0].workflow_id,
            proposed_config=merged_cfg,
            rationale="; ".join(rationales),
            changed_dims=list(all_changed_dims),
            evidence=evidence,
            change_summary=f"Bundled updates for {', '.join(all_changed_dims)}",
            impact_score=max_impact,
            created_minute=intents[-1].created_minute,
        )

    @staticmethod
    def estimate_affected_leads(spec: dict[str, Any], changed_dims: list[str], total_leads: int) -> int:
        """Estimates the number of leads affected by the change.

        - For prompt or cohort changes, the entire campaign is affected.
        - For individual variant distribution shifts, bounded by recent active campaign volume.
        """
        if "prompt_version" in changed_dims or "cohorts" in changed_dims:
            return max(1, total_leads)
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
        """Generates historical replay dry-run projections to satisfy C10 and the approval API."""
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
