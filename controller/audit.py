from __future__ import annotations

import argparse
import json
from .db import Database


def main():
    parser = argparse.ArgumentParser(description="Query Controller Audit Log (C12)")
    parser.add_argument("--db", default="controller_state.db", help="Path to SQLite database")
    parser.add_argument("--workflow", "-w", default=None, help="Workflow ID to filter by")
    parser.add_argument("--at", default=None, help="Filter by date or timestamp substring (e.g. '2027-01-07')")
    parser.add_argument("--limit", "-n", type=int, default=20, help="Number of records to show")
    parser.add_argument("--json", action="store_true", help="Output raw JSON")
    args = parser.parse_args()

    db = Database(args.db)
    entries = db.query_audit(workflow_id=args.workflow, at_ts=args.at, limit=args.limit)

    if args.json:
        print(json.dumps([e.to_dict() for e in entries], indent=2))
        return

    print("=" * 90)
    print(f"AUDIT LOG ({len(entries)} entries found)")
    print("=" * 90)
    if not entries:
        print("No audit entries found matching criteria.")
        return

    for e in entries:
        print(f"[{e.ts}] (Minute {e.sim_minute}) Workflow: {e.workflow_id} | Actor: {e.actor} | Action: {e.action}")
        if e.changed_dims:
            print(f"  Changed Dims: {', '.join(e.changed_dims)}")
        if e.diff:
            print(f"  Diff: {json.dumps(e.diff)}")
        if e.rationale:
            print(f"  Rationale: {e.rationale}")
        if e.impact_score:
            print(f"  Impact Score: {e.impact_score:.3f}")
        if e.evidence:
            print(f"  Evidence: {json.dumps(e.evidence)}")
        if e.before_metrics:
            print(f"  Before Metrics: {json.dumps(e.before_metrics)}")
        print("-" * 90)


if __name__ == "__main__":
    main()
