from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Any

from .db import Database
from .models import AuditEntry


@dataclass
class CallOutcome:
    ts: str
    sim_minute: int
    connected: bool
    engaged: bool
    hallucination_flag: bool
    caller_id: str
    voice: str
    welcome: str
    prompt_version: str
    cohort_id: str


class WorkflowRuntimeState:
    def __init__(self, wid: str, spec: dict[str, Any], initial_config: dict[str, Any]):
        self.wid = wid
        self.spec = spec
        self.current_version = initial_config.get("version", 1)
        self.current_config = initial_config.get("config", {})
        self.actor = initial_config.get("actor", "business_default")

        # Rolling window of recent calls for incident detection (e.g., last 300 calls)
        self.recent_calls: deque[CallOutcome] = deque(maxlen=500)

        # Totals
        self.total_dials = 0
        self.total_connected = 0
        self.total_engaged = 0
        self.total_hallucinations = 0

        # Per DID stats: did -> [dials, connected]
        self.did_stats: dict[str, list[int]] = {}

    def record_call(self, ev: dict[str, Any], sim_minute: int):
        self.total_dials += 1
        connected = bool(ev.get("connected", False))
        engaged = bool(ev.get("engaged", False))
        qa = ev.get("qa") or {}
        hallucination = bool(qa.get("hallucination_flag", False))

        variant = ev.get("variant") or {}
        did = variant.get("caller_id", "")
        if did:
            if did not in self.did_stats:
                self.did_stats[did] = [0, 0]
            self.did_stats[did][0] += 1
            if connected:
                self.did_stats[did][1] += 1

        if connected:
            self.total_connected += 1
        if engaged:
            self.total_engaged += 1
        if hallucination:
            self.total_hallucinations += 1

        outcome = CallOutcome(
            ts=ev.get("ts", ""),
            sim_minute=sim_minute,
            connected=connected,
            engaged=engaged,
            hallucination_flag=hallucination,
            caller_id=did,
            voice=variant.get("voice", ""),
            welcome=variant.get("welcome_message", ""),
            prompt_version=variant.get("prompt_version", ""),
            cohort_id=ev.get("cohort_id", "default"),
        )
        self.recent_calls.append(outcome)

    def get_metrics_snapshot(self) -> dict[str, Any]:
        pickup_rate = (self.total_connected / self.total_dials) if self.total_dials > 0 else 0.0
        engage_rate = (self.total_engaged / self.total_connected) if self.total_connected > 0 else 0.0
        halluc_rate = (self.total_hallucinations / self.total_connected) if self.total_connected > 0 else 0.0

        # Rolling window rates
        recent_dials = len(self.recent_calls)
        recent_conn = sum(1 for c in self.recent_calls if c.connected)
        recent_eng = sum(1 for c in self.recent_calls if c.engaged)
        recent_halluc = sum(1 for c in self.recent_calls if c.hallucination_flag)

        return {
            "total_dials": self.total_dials,
            "total_connected": self.total_connected,
            "total_engaged": self.total_engaged,
            "pickup_rate": round(pickup_rate, 4),
            "engagement_rate": round(engage_rate, 4),
            "hallucination_rate": round(halluc_rate, 4),
            "window_size": recent_dials,
            "window_pickup_rate": round(recent_conn / recent_dials, 4) if recent_dials > 0 else 0.0,
            "window_engagement_rate": round(recent_eng / recent_conn, 4) if recent_conn > 0 else 0.0,
            "window_hallucination_rate": round(recent_halluc / recent_conn, 4) if recent_conn > 0 else 0.0,
        }


class StateManager:
    def __init__(self, db: Database):
        self.db = db
        self.workflows: dict[str, WorkflowRuntimeState] = {}
        self.active_campaigns: dict[str, dict[str, Any]] = {}
        self.leads_count: dict[str, int] = {}  # workflow_id -> lead count

    def register_workflow(self, wid: str, spec: dict[str, Any], config_data: dict[str, Any]):
        self.workflows[wid] = WorkflowRuntimeState(wid, spec, config_data)

    def process_event(self, ev: dict[str, Any], sim_minute: int):
        ev_type = ev.get("type")
        wid = ev.get("workflow_id")

        if ev_type == "campaign_created":
            cid = ev.get("campaign_id")
            if cid:
                self.active_campaigns[cid] = ev
            if wid:
                self.leads_count[wid] = self.leads_count.get(wid, 0) + ev.get("leads", 0)

        elif ev_type == "call":
            if wid and wid in self.workflows:
                self.workflows[wid].record_call(ev, sim_minute)

        elif ev_type == "config_changed":
            actor = ev.get("actor", "unknown")
            new_v = ev.get("version")
            changed_dims = ev.get("changed_dims", [])
            if wid and wid in self.workflows:
                wf = self.workflows[wid]
                before_m = wf.get_metrics_snapshot()
                wf.current_version = new_v
                wf.actor = actor

                # Record in audit log
                self.db.record_audit(
                    AuditEntry(
                        ts=ev.get("ts", ""),
                        sim_minute=sim_minute,
                        workflow_id=wid,
                        actor=actor,
                        action="config_changed",
                        changed_dims=changed_dims,
                        diff={"new_version": new_v, "proposal_id": ev.get("proposal_id")},
                        rationale=f"Config changed to version {new_v} by {actor}",
                        impact_score=0.0,
                        evidence={"approval_id": ev.get("approval_id")},
                        before_metrics=before_m,
                        after_metrics={},
                    )
                )

        elif ev_type == "approval_decided":
            aid = ev.get("approval_id")
            status = ev.get("status")
            reasons = ev.get("reasons", [])
            # Update proposal if present in DB
            props = self.db.list_proposals(workflow_id=wid)
            for p in props:
                if p.approval_id == aid:
                    p.status = str(status)
                    p.reasons = reasons
                    self.db.upsert_proposal(p)
                    break
