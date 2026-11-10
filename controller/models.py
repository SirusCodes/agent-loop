from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class Checkpoint:
    last_chunk_id: int
    last_event_id: int
    sim_minute: int
    sim_ts: str


@dataclass
class AuditEntry:
    ts: str
    sim_minute: int
    workflow_id: str
    actor: str  # supervisor | controller_approved | controller_auto
    action: str
    changed_dims: list[str] = field(default_factory=list)
    diff: dict[str, Any] = field(default_factory=dict)
    rationale: str = ""
    impact_score: float = 0.0
    evidence: dict[str, Any] = field(default_factory=dict)
    before_metrics: dict[str, Any] = field(default_factory=dict)
    after_metrics: dict[str, Any] = field(default_factory=dict)
    id: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ProposalRecord:
    proposal_id: str
    workflow_id: str
    base_version: int
    status: str  # pending | approved | rejected | applied | lapsed | expired
    change_summary: str
    proposed_config: dict[str, Any]
    diff: dict[str, Any]
    affected_leads: int
    dry_run: dict[str, Any]
    impact_score: float
    approval_id: str | None = None
    evidence: dict[str, Any] | None = None
    created_minute: int = 0
    decide_minute: int | None = None
    expires_minute: int | None = None
    applied_version: int | None = None
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
