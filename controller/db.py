from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from .models import AuditEntry, Checkpoint, ProposalRecord


class Database:
    def __init__(self, db_path: str | Path):
        self.db_path = str(db_path)
        self._conn: sqlite3.Connection | None = None
        self.init_db()

    def get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(self.db_path)
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL;")
            self._conn.execute("PRAGMA synchronous=NORMAL;")
        return self._conn

    def close(self):
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def init_db(self):
        conn = self.get_conn()
        with conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS checkpoints (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    last_chunk_id INTEGER NOT NULL,
                    last_event_id INTEGER NOT NULL,
                    sim_minute INTEGER NOT NULL,
                    sim_ts TEXT NOT NULL,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS audit_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts TEXT NOT NULL,
                    sim_minute INTEGER NOT NULL,
                    workflow_id TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    action TEXT NOT NULL,
                    changed_dims TEXT NOT NULL,
                    diff_json TEXT NOT NULL,
                    rationale TEXT NOT NULL,
                    impact_score REAL NOT NULL,
                    evidence_json TEXT NOT NULL,
                    before_metrics_json TEXT NOT NULL,
                    after_metrics_json TEXT NOT NULL
                );
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_audit_wf_ts
                ON audit_log (workflow_id, sim_minute);
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS proposals (
                    proposal_id TEXT PRIMARY KEY,
                    approval_id TEXT,
                    workflow_id TEXT NOT NULL,
                    base_version INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    change_summary TEXT NOT NULL,
                    proposed_config_json TEXT NOT NULL,
                    diff_json TEXT NOT NULL,
                    affected_leads INTEGER NOT NULL,
                    dry_run_json TEXT NOT NULL,
                    impact_score REAL NOT NULL,
                    evidence_json TEXT,
                    created_minute INTEGER NOT NULL,
                    decide_minute INTEGER,
                    expires_minute INTEGER,
                    applied_version INTEGER,
                    reasons_json TEXT
                );
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_proposals_wf_status
                ON proposals (workflow_id, status);
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS metrics_rolling (
                    workflow_id TEXT NOT NULL,
                    metric_key TEXT NOT NULL,
                    window_start_minute INTEGER NOT NULL,
                    dials INTEGER NOT NULL DEFAULT 0,
                    connected INTEGER NOT NULL DEFAULT 0,
                    engaged INTEGER NOT NULL DEFAULT 0,
                    hallucination_flags INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY (workflow_id, metric_key, window_start_minute)
                );
                """
            )

    # ---------------- Checkpoints ----------------
    def save_checkpoint(self, cp: Checkpoint):
        conn = self.get_conn()
        with conn:
            conn.execute(
                """
                INSERT INTO checkpoints (id, last_chunk_id, last_event_id, sim_minute, sim_ts, updated_at)
                VALUES (1, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(id) DO UPDATE SET
                    last_chunk_id = excluded.last_chunk_id,
                    last_event_id = excluded.last_event_id,
                    sim_minute = excluded.sim_minute,
                    sim_ts = excluded.sim_ts,
                    updated_at = CURRENT_TIMESTAMP;
                """,
                (cp.last_chunk_id, cp.last_event_id, cp.sim_minute, cp.sim_ts),
            )

    def load_checkpoint(self) -> Checkpoint | None:
        conn = self.get_conn()
        cur = conn.execute("SELECT last_chunk_id, last_event_id, sim_minute, sim_ts FROM checkpoints WHERE id = 1;")
        row = cur.fetchone()
        if not row:
            return None
        return Checkpoint(
            last_chunk_id=row["last_chunk_id"],
            last_event_id=row["last_event_id"],
            sim_minute=row["sim_minute"],
            sim_ts=row["sim_ts"],
        )

    # ---------------- Audit Log ----------------
    def record_audit(self, entry: AuditEntry) -> int:
        conn = self.get_conn()
        with conn:
            cur = conn.execute(
                """
                INSERT INTO audit_log (
                    ts, sim_minute, workflow_id, actor, action,
                    changed_dims, diff_json, rationale, impact_score,
                    evidence_json, before_metrics_json, after_metrics_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    entry.ts,
                    entry.sim_minute,
                    entry.workflow_id,
                    entry.actor,
                    entry.action,
                    json.dumps(entry.changed_dims),
                    json.dumps(entry.diff),
                    entry.rationale,
                    entry.impact_score,
                    json.dumps(entry.evidence),
                    json.dumps(entry.before_metrics),
                    json.dumps(entry.after_metrics),
                ),
            )
            return int(cur.lastrowid or 0)

    def query_audit(
        self,
        workflow_id: str | None = None,
        at_ts: str | None = None,
        limit: int = 50,
    ) -> list[AuditEntry]:
        conn = self.get_conn()
        clauses = []
        params: list[Any] = []
        if workflow_id:
            clauses.append("workflow_id = ?")
            params.append(workflow_id)
        if at_ts:
            clauses.append("ts LIKE ?")
            params.append(f"%{at_ts}%")

        where_sql = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        sql = f"""
            SELECT id, ts, sim_minute, workflow_id, actor, action,
                   changed_dims, diff_json, rationale, impact_score,
                   evidence_json, before_metrics_json, after_metrics_json
            FROM audit_log
            {where_sql}
            ORDER BY sim_minute DESC, id DESC
            LIMIT ?
        """
        params.append(limit)

        cur = conn.execute(sql, params)
        results = []
        for row in cur.fetchall():
            results.append(
                AuditEntry(
                    id=row["id"],
                    ts=row["ts"],
                    sim_minute=row["sim_minute"],
                    workflow_id=row["workflow_id"],
                    actor=row["actor"],
                    action=row["action"],
                    changed_dims=json.loads(row["changed_dims"]),
                    diff=json.loads(row["diff_json"]),
                    rationale=row["rationale"],
                    impact_score=row["impact_score"],
                    evidence=json.loads(row["evidence_json"]),
                    before_metrics=json.loads(row["before_metrics_json"]),
                    after_metrics=json.loads(row["after_metrics_json"]),
                )
            )
        return results

    # ---------------- Proposals ----------------
    def upsert_proposal(self, p: ProposalRecord):
        conn = self.get_conn()
        with conn:
            conn.execute(
                """
                INSERT INTO proposals (
                    proposal_id, approval_id, workflow_id, base_version, status,
                    change_summary, proposed_config_json, diff_json, affected_leads,
                    dry_run_json, impact_score, evidence_json, created_minute,
                    decide_minute, expires_minute, applied_version, reasons_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(proposal_id) DO UPDATE SET
                    approval_id = excluded.approval_id,
                    status = excluded.status,
                    decide_minute = excluded.decide_minute,
                    expires_minute = excluded.expires_minute,
                    applied_version = excluded.applied_version,
                    reasons_json = excluded.reasons_json;
                """,
                (
                    p.proposal_id,
                    p.approval_id,
                    p.workflow_id,
                    p.base_version,
                    p.status,
                    p.change_summary,
                    json.dumps(p.proposed_config),
                    json.dumps(p.diff),
                    p.affected_leads,
                    json.dumps(p.dry_run),
                    p.impact_score,
                    json.dumps(p.evidence) if p.evidence is not None else None,
                    p.created_minute,
                    p.decide_minute,
                    p.expires_minute,
                    p.applied_version,
                    json.dumps(p.reasons),
                ),
            )

    def get_proposal(self, proposal_id: str) -> ProposalRecord | None:
        conn = self.get_conn()
        cur = conn.execute("SELECT * FROM proposals WHERE proposal_id = ?", (proposal_id,))
        row = cur.fetchone()
        if not row:
            return None
        return ProposalRecord(
            proposal_id=row["proposal_id"],
            approval_id=row["approval_id"],
            workflow_id=row["workflow_id"],
            base_version=row["base_version"],
            status=row["status"],
            change_summary=row["change_summary"],
            proposed_config=json.loads(row["proposed_config_json"]),
            diff=json.loads(row["diff_json"]),
            affected_leads=row["affected_leads"],
            dry_run=json.loads(row["dry_run_json"]),
            impact_score=row["impact_score"],
            evidence=json.loads(row["evidence_json"]) if row["evidence_json"] else None,
            created_minute=row["created_minute"],
            decide_minute=row["decide_minute"],
            expires_minute=row["expires_minute"],
            applied_version=row["applied_version"],
            reasons=json.loads(row["reasons_json"]) if row["reasons_json"] else [],
        )

    def list_proposals(self, workflow_id: str | None = None, status: str | None = None) -> list[ProposalRecord]:
        conn = self.get_conn()
        clauses = []
        params: list[Any] = []
        if workflow_id:
            clauses.append("workflow_id = ?")
            params.append(workflow_id)
        if status:
            clauses.append("status = ?")
            params.append(status)
        where_sql = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        sql = f"SELECT * FROM proposals {where_sql} ORDER BY created_minute DESC"
        cur = conn.execute(sql, params)
        records = []
        for row in cur.fetchall():
            records.append(
                ProposalRecord(
                    proposal_id=row["proposal_id"],
                    approval_id=row["approval_id"],
                    workflow_id=row["workflow_id"],
                    base_version=row["base_version"],
                    status=row["status"],
                    change_summary=row["change_summary"],
                    proposed_config=json.loads(row["proposed_config_json"]),
                    diff=json.loads(row["diff_json"]),
                    affected_leads=row["affected_leads"],
                    dry_run=json.loads(row["dry_run_json"]),
                    impact_score=row["impact_score"],
                    evidence=json.loads(row["evidence_json"]) if row["evidence_json"] else None,
                    created_minute=row["created_minute"],
                    decide_minute=row["decide_minute"],
                    expires_minute=row["expires_minute"],
                    applied_version=row["applied_version"],
                    reasons=json.loads(row["reasons_json"]) if row["reasons_json"] else [],
                )
            )
        return records

    # ---------------- Metrics ----------------
    def record_metrics_batch(self, items: list[tuple[str, str, int, int, int, int, int]]):
        if not items:
            return
        conn = self.get_conn()
        with conn:
            conn.executemany(
                """
                INSERT INTO metrics_rolling (
                    workflow_id, metric_key, window_start_minute, dials, connected, engaged, hallucination_flags
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(workflow_id, metric_key, window_start_minute) DO UPDATE SET
                    dials = dials + excluded.dials,
                    connected = connected + excluded.connected,
                    engaged = engaged + excluded.engaged,
                    hallucination_flags = hallucination_flags + excluded.hallucination_flags;
                """,
                items,
            )
