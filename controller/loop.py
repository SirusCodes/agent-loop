from __future__ import annotations

import logging
import time
from typing import Any

from .client import BaseClient
from .db import Database
from .governance import GovernanceEngine, compute_changed_dims, compute_json_diff
from .models import AuditEntry, Checkpoint, ProposalIntent, ProposalRecord
from .state import StateManager

logger = logging.getLogger("controller.loop")


class ControllerLoop:
    def __init__(self, client: BaseClient, db: Database, tick_step_minutes: int = 60):
        self.client = client
        self.db = db
        self.tick_step_minutes = tick_step_minutes
        self.state_mgr = StateManager(db)
        self.sim_minute = 0
        self.sim_ts = ""
        self.last_chunk_id = -1
        self.last_event_id = -1
        self.is_running = True

    def setup(self):
        """Initialize workflows and recover state from checkpoints or history."""
        wfs = self.client.get_workflows()
        for w in wfs:
            wid = w["workflow_id"]
            cfg_data = self.client.get_config(wid)
            self.state_mgr.register_workflow(wid, w, cfg_data)
        logger.info(f"Registered {len(wfs)} workflows.")

        cp = self.db.load_checkpoint()
        if cp:
            self.last_chunk_id = cp.last_chunk_id
            self.last_event_id = cp.last_event_id
            self.sim_minute = cp.sim_minute
            self.sim_ts = cp.sim_ts
            logger.info(f"Resumed from checkpoint: chunk={self.last_chunk_id}, event={self.last_event_id}, minute={self.sim_minute}")

            pending_props = self.db.list_proposals(status="pending")
            for p in pending_props:
                if p.approval_id and p.workflow_id in self.state_mgr.workflows:
                    wf = self.state_mgr.workflows[p.workflow_id]
                    wf.pending_approvals[p.approval_id] = p
            logger.info(f"Loaded {len(pending_props)} pending approvals from DB.")
        else:
            history_chunks = self.client.get_chunks(kind="history", after=-1)
            logger.info(f"Ingesting {len(history_chunks)} history chunks...")
            for ch in history_chunks:
                self._ingest_chunk(ch)
            state = self.client.get_state()
            self.sim_minute = state.get("sim_minute", 0)
            self.sim_ts = state.get("ts", "")
            self.save_checkpoint()

    def _ingest_chunk(self, chunk_meta: dict[str, Any]):
        cid = chunk_meta["chunk"]
        for ev in self.client.stream_chunk_events(cid):
            self.state_mgr.process_event(ev, self.sim_minute)
            eid = ev.get("event_id")
            if eid is not None and eid > self.last_event_id:
                self.last_event_id = eid
        self.last_chunk_id = max(self.last_chunk_id, cid)

    def save_checkpoint(self):
        cp = Checkpoint(
            last_chunk_id=self.last_chunk_id,
            last_event_id=self.last_event_id,
            sim_minute=self.sim_minute,
            sim_ts=self.sim_ts,
        )
        self.db.save_checkpoint(cp)

    def reconcile_approvals(self):
        """Check status of pending approvals, apply approved ones, handle expiration/rejection."""
        for wid, wf in self.state_mgr.workflows.items():
            for aid, prop in list(wf.pending_approvals.items()):
                try:
                    ap_info = self.client.get_approval(aid)
                except Exception as e:
                    logger.warning(f"Error fetching approval {aid}: {e}")
                    continue

                status = ap_info.get("status")
                prop.status = status
                prop.reasons = ap_info.get("reasons", [])

                if status == "approved":
                    try:
                        cfg_now = self.client.get_config(wid)
                        wf.current_version = cfg_now["version"]
                        wf.current_config = cfg_now["config"]

                        if prop.base_version != wf.current_version:
                            logger.warning(f"Approval {aid} stale: base {prop.base_version} != current {wf.current_version}")
                            prop.status = "stale"
                            prop.reasons.append("Base version changed before apply")
                            self.db.upsert_proposal(prop)
                            wf.pending_approvals.pop(aid, None)
                            continue

                        res = self.client.apply_approval(wid, aid)
                        applied_v = res.get("version", wf.current_version + 1)
                        prop.status = "applied"
                        prop.applied_version = applied_v
                        self.db.upsert_proposal(prop)
                        wf.pending_approvals.pop(aid, None)
                        wf.current_version = applied_v
                        wf.current_config = prop.proposed_config
                        logger.info(f"[{self.sim_ts}] Applied approval {aid} for {wid} -> v{applied_v}")
                    except Exception as e:
                        logger.error(f"Failed to apply approval {aid}: {e}")
                        if "stale_base_version" in str(e):
                            prop.status = "stale"
                        elif "lapsed" in str(e):
                            prop.status = "lapsed"
                        self.db.upsert_proposal(prop)
                        wf.pending_approvals.pop(aid, None)

                elif status in ("rejected", "expired", "lapsed"):
                    logger.info(f"[{self.sim_ts}] Approval {aid} concluded with status '{status}': {prop.reasons}")
                    self.db.upsert_proposal(prop)
                    wf.pending_approvals.pop(aid, None)

    def process_queued_proposals(self):
        """Evaluate queued proposal intents for auto-apply or scheduled dynamic window approval submission."""
        all_proposals = self.db.list_proposals()

        for wid, wf in self.state_mgr.workflows.items():
            if not wf.queued_intents:
                continue

            try:
                cfg_info = self.client.get_config(wid)
                wf.current_version = cfg_info["version"]
                wf.current_config = cfg_info["config"]
            except Exception as e:
                logger.warning(f"Could not refresh config for {wid}: {e}")

            # 1. Process auto-apply intents immediately (they don't fatigue human approvers)
            remaining_intents = []
            for intent in wf.queued_intents:
                can_auto, auto_reason, changed_dims = GovernanceEngine.can_auto_apply(
                    wf.spec, wf.current_config, intent.proposed_config
                )
                if can_auto:
                    try:
                        pid = f"auto_{int(time.time()*1000)}"
                        res = self.client.auto_apply(
                            wid,
                            {
                                "proposal_id": pid,
                                "base_version": wf.current_version,
                                "proposed_config": intent.proposed_config,
                                "rationale": intent.rationale,
                                "evidence": intent.evidence,
                            },
                        )
                        applied_v = res.get("version", wf.current_version + 1)
                        wf.current_version = applied_v
                        wf.current_config = intent.proposed_config

                        diff = compute_json_diff(wf.current_config, intent.proposed_config)
                        prop_rec = ProposalRecord(
                            proposal_id=pid,
                            workflow_id=wid,
                            base_version=wf.current_version - 1,
                            status="applied",
                            change_summary=intent.change_summary or f"Auto-apply {', '.join(changed_dims)}",
                            proposed_config=intent.proposed_config,
                            diff=diff,
                            affected_leads=0,
                            dry_run={"mode": "auto_apply"},
                            impact_score=intent.impact_score,
                            applied_version=applied_v,
                            created_minute=self.sim_minute,
                        )
                        self.db.upsert_proposal(prop_rec)
                        logger.info(f"[{self.sim_ts}] Auto-applied config for {wid} -> v{applied_v} ({changed_dims})")
                    except Exception as e:
                        logger.error(f"Auto-apply failed for {wid}: {e}. Retaining for approval.")
                        remaining_intents.append(intent)
                else:
                    remaining_intents.append(intent)

            wf.queued_intents = remaining_intents
            if not wf.queued_intents:
                continue

            # 2. For human approvals: check dynamic dispatch window and fatigue quota
            is_emergency = any(intent.evidence is not None for intent in wf.queued_intents)
            if not GovernanceEngine.is_dispatch_time(wf.spec, self.sim_minute, self.tick_step_minutes, is_emergency=is_emergency):
                logger.debug(f"[{self.sim_ts}] Holding {len(wf.queued_intents)} intents for {wid} until scheduled dispatch slot.")
                continue

            if not GovernanceEngine.is_quota_available(wid, wf.spec, all_proposals, self.sim_minute):
                logger.info(f"[{self.sim_ts}] Approver 24h quota reached for {wid}. Holding bundled changes in queue.")
                continue

            # 3. Bundle all pending intents into a single atomic proposal payload
            bundled_intent = GovernanceEngine.bundle_intents(wf.queued_intents, wf.current_config)
            wf.queued_intents.clear()

            body = GovernanceEngine.package_proposal(
                intent=bundled_intent,
                current_version=wf.current_version,
                current_cfg=wf.current_config,
                spec=wf.spec,
                total_leads=self.state_mgr.leads_count.get(wid, 1000),
                recent_metrics=wf.get_metrics_snapshot(),
            )

            try:
                res = self.client.request_approval(body)
                aid = res.get("approval_id")
                prop_rec = ProposalRecord(
                    proposal_id=body["proposal_id"],
                    workflow_id=wid,
                    base_version=body["base_version"],
                    status="pending",
                    change_summary=body["change_summary"],
                    proposed_config=body["proposed_config"],
                    diff=body["diff"],
                    affected_leads=body["affected_leads"],
                    dry_run=body["dry_run"],
                    impact_score=body["impact_score"],
                    approval_id=aid,
                    evidence=body.get("evidence"),
                    created_minute=self.sim_minute,
                )
                self.db.upsert_proposal(prop_rec)
                if aid:
                    wf.pending_approvals[aid] = prop_rec
                logger.info(f"[{self.sim_ts}] Dispatched bundled approval {aid} for {wid} at scheduled slot: {body['change_summary']}")
            except Exception as e:
                logger.error(f"Failed to submit approval for {wid}: {e}")

    def step(self) -> bool:
        """Advance simulation by tick_step_minutes, process events, reconcile approvals and checkpoint."""
        adv = self.client.advance(self.tick_step_minutes)
        self.sim_minute = adv.get("sim_minute", self.sim_minute + self.tick_step_minutes)
        self.sim_ts = adv.get("ts", self.sim_ts)
        finished = adv.get("finished", False)

        new_chunks = adv.get("new_chunks", [])
        for ch in new_chunks:
            self._ingest_chunk(ch)

        self.reconcile_approvals()
        self.process_queued_proposals()
        self.save_checkpoint()
        return not finished

    def run(self):
        self.setup()
        step_count = 0
        start_wall = time.time()
        while self.is_running:
            more = self.step()
            step_count += 1
            if step_count % 24 == 0:
                elapsed = time.time() - start_wall
                logger.info(f"[{self.sim_ts}] Day completed. Total steps: {step_count}, Wall-clock: {elapsed:.2f}s, Last Event: {self.last_event_id}")
            if not more:
                logger.info(f"Simulation finished at minute {self.sim_minute} ({self.sim_ts}).")
                break
