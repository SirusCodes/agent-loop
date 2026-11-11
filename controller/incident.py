from __future__ import annotations

import copy
import logging
from dataclasses import dataclass
from typing import Any

from .client import BaseClient
from .models import ProposalIntent

logger = logging.getLogger("controller.incident")


@dataclass
class IncidentState:
    workflow_id: str
    incident_type: str  # "hallucination_spike" | "did_flagged"
    detected_minute: int
    details: dict[str, Any]
    status: str = "active"  # "active" | "resolving" | "resolved" | "rolled_back"
    remediation_proposal_id: str | None = None
    applied_remediation_version: int | None = None
    verification_calls_checked: int = 0


class IncidentManager:
    """Orchestrates incident resolution: queries LLM fixes, runs validations, and triggers emergency governance."""

    def __init__(self, client: BaseClient, min_credits_buffer: float = 10.0):
        self.client = client
        self.min_credits_buffer = min_credits_buffer
        self.active_incidents: dict[str, list[IncidentState]] = (
            {}
        )  # wid -> list[IncidentState]

    def has_active_incident(self, wid: str, incident_type: str) -> bool:
        """Check if an unresolved incident of this type already exists for the workflow."""
        incidents = self.active_incidents.get(wid, [])
        return any(
            inc.incident_type == incident_type and inc.status in ("active", "resolving")
            for inc in incidents
        )

    def handle_hallucination_incident(
        self,
        wid: str,
        spec: dict[str, Any],
        current_cfg: dict[str, Any],
        sim_minute: int,
        rate: float,
        last_safe_prompt: str,
    ) -> ProposalIntent | None:
        """Resolves a hallucination spike by requesting LLM fixes, validating candidates, and packaging a proposal."""
        if self.has_active_incident(wid, "hallucination_spike"):
            logger.debug(f"Hallucination incident for {wid} is already being handled.")
            return None

        current_prompt = current_cfg.get("prompt_version")
        logger.warning(
            f"Handling hallucination incident on {wid} (prompt={current_prompt}, rate={rate:.4f}) at minute {sim_minute}."
        )
        incident = IncidentState(
            workflow_id=wid,
            incident_type="hallucination_spike",
            detected_minute=sim_minute,
            details={
                "rate": rate,
                "initial_prompt": current_prompt,
                "last_safe_prompt": last_safe_prompt,
            },
            status="active",
        )
        if wid not in self.active_incidents:
            self.active_incidents[wid] = []
        self.active_incidents[wid].append(incident)

        # 1. Check available credits
        state = self.client.get_state()
        credits_remaining = state.get("credits_remaining", 0.0)
        logger.info(f"Credits remaining for {wid} remediation: {credits_remaining}")

        chosen_prompt = None
        evidence = None
        gov = spec.get("governance", {})
        min_pass_rate = gov.get("min_validation_pass_rate", 0.97)

        # If we have sufficient credits for LLM suggestion (cost: 3) + validation run (cost: 2)
        if credits_remaining >= (3.0 + 2.0 + self.min_credits_buffer):
            try:
                # 2. Ask LLM for fix suggestions
                sug_res = self.client.suggest_fixes(
                    wid, "Severe hallucination rate spike detected on current prompt"
                )
                suggestions = sug_res.get("suggestions", [])
                logger.info(
                    f"LLM suggested {len(suggestions)} fixes for {wid}: {[s.get('prompt_version') for s in suggestions]}"
                )

                # 3. Test suggestions with synthetic validation (n=200, cost: 2 credits each)
                for cand in suggestions[:2]:
                    pv = cand.get("prompt_version")
                    if not pv or pv == current_prompt:
                        continue
                    val_res = self.client.run_validation(wid, pv, n=200)
                    pass_rate = val_res.get("pass_rate", 0.0)
                    logger.info(
                        f"Validation run for candidate {pv}: pass_rate={pass_rate:.4f} (needed >= {min_pass_rate})"
                    )

                    if pass_rate >= min_pass_rate:
                        chosen_prompt = pv
                        evidence = {
                            "validation_run_id": val_res.get("validation_run_id")
                        }
                        break
            except Exception as e:
                logger.error(f"Error calling LLM or validation for {wid}: {e}")

        # If LLM suggestions didn't meet criteria or insufficient credits, fallback to last known safe prompt
        if not chosen_prompt:
            chosen_prompt = (
                last_safe_prompt if last_safe_prompt != current_prompt else "P1"
            )
            logger.info(f"Falling back to safe prompt '{chosen_prompt}' for {wid}.")
            try:
                val_res = self.client.run_validation(wid, chosen_prompt, n=200)
                evidence = {"validation_run_id": val_res.get("validation_run_id")}
            except Exception as e:
                logger.error(
                    f"Failed validation on fallback safe prompt {chosen_prompt}: {e}"
                )

        # 4. If chosen prompt is same as current prompt, we cannot propose a change
        if chosen_prompt == current_prompt:
            logger.warning(
                f"Chosen prompt '{chosen_prompt}' is identical to current prompt for {wid}. Cannot propose."
            )
            incident.status = "resolved"
            return None

        # 5. Construct proposed configuration
        new_cfg = copy.deepcopy(current_cfg)
        new_cfg["prompt_version"] = chosen_prompt

        incident.status = "resolving"
        intent = ProposalIntent(
            workflow_id=wid,
            proposed_config=new_cfg,
            rationale=f"Remediate hallucination spike ({rate:.1%}); deploy validated prompt {chosen_prompt}",
            changed_dims=["prompt_version"],
            evidence=evidence,
            change_summary=f"Incident fix: switch prompt to {chosen_prompt}",
            impact_score=0.9,
            created_minute=sim_minute,
        )
        return intent

    def handle_did_degradation(
        self,
        wid: str,
        current_cfg: dict[str, Any],
        degraded_dids: list[str],
        sim_minute: int,
    ) -> ProposalIntent | None:
        """Remediates degraded caller IDs by auto-applying a traffic shift to healthy numbers."""
        if not degraded_dids:
            return None

        allocs = current_cfg.get("allocations", {}).get("default", {})
        did_alloc = allocs.get("caller_id", {})
        if not did_alloc:
            return None

        # If already shifted away from degraded DIDs, skip
        if all(did_alloc.get(d, 0.0) == 0.0 for d in degraded_dids):
            return None

        logger.warning(
            f"Rotating away from degraded caller IDs on {wid}: {degraded_dids}"
        )
        healthy_dids = [d for d in did_alloc if d not in degraded_dids]
        if not healthy_dids:
            logger.error(f"All caller IDs are degraded on {wid}. Cannot rebalance.")
            return None

        # Distribute weight equally across healthy DIDs
        new_cfg = copy.deepcopy(current_cfg)
        share = round(1.0 / len(healthy_dids), 4)
        new_did_alloc = {d: share for d in healthy_dids}
        # Balance rounding so sum equals 1.0
        rem = round(1.0 - sum(new_did_alloc.values()), 4)
        new_did_alloc[healthy_dids[0]] = round(new_did_alloc[healthy_dids[0]] + rem, 4)

        new_cfg["allocations"]["default"]["caller_id"] = new_did_alloc

        incident = IncidentState(
            workflow_id=wid,
            incident_type="did_flagged",
            detected_minute=sim_minute,
            details={"degraded_dids": degraded_dids},
            status="resolving",
        )
        if wid not in self.active_incidents:
            self.active_incidents[wid] = []
        self.active_incidents[wid].append(incident)

        intent = ProposalIntent(
            workflow_id=wid,
            proposed_config=new_cfg,
            rationale=f"Caller ID health degradation detected on {degraded_dids}; rotate to healthy DIDs",
            changed_dims=["caller_id"],
            change_summary=f"Rotate traffic away from degraded DIDs {degraded_dids}",
            impact_score=0.8,
            created_minute=sim_minute,
        )
        return intent

    def verify_incidents(
        self, wid: str, recent_hallucination_rate: float, current_prompt: str
    ):
        """Verifies whether an applied incident fix has resolved the issue."""
        for inc in self.active_incidents.get(wid, []):
            if inc.incident_type == "hallucination_spike" and inc.status == "resolving":
                if recent_hallucination_rate < 0.015:
                    inc.status = "resolved"
                    logger.info(
                        f"Hallucination incident for {wid} successfully resolved with prompt {current_prompt} (rate={recent_hallucination_rate:.4f})."
                    )
