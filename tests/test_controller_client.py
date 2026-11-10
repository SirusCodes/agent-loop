from typing import Any, Iterator

from controller.client import BaseClient


class MockClient(BaseClient):
    def __init__(self):
        self.state = {"sim_minute": 0, "ts": "2027-01-04T00:00:00+05:30", "finished": False}
        self.workflows = [
            {"workflow_id": "wf_test", "governance": {"auto_apply": {"enabled": True}}}
        ]
        self.configs = {"wf_test": {"version": 1, "config": {}}}
        self.chunks = []
        self.events_by_chunk = {}
        self.approvals = {}

    def get_state(self) -> dict[str, Any]:
        return self.state

    def advance(self, minutes: int) -> dict[str, Any]:
        self.state["sim_minute"] += minutes
        return {
            "sim_minute": self.state["sim_minute"],
            "ts": self.state["ts"],
            "finished": self.state["sim_minute"] >= 1440,
            "new_chunks": [],
        }

    def get_workflows(self) -> list[dict[str, Any]]:
        return self.workflows

    def get_workflow(self, wid: str) -> dict[str, Any]:
        return next(w for w in self.workflows if w["workflow_id"] == wid)

    def get_config(self, wid: str) -> dict[str, Any]:
        return self.configs[wid]

    def get_chunks(self, kind: str = "events", after: int = -1) -> list[dict[str, Any]]:
        return [c for c in self.chunks if c.get("chunk", 0) > after]

    def stream_chunk_events(self, chunk_num: int) -> Iterator[dict[str, Any]]:
        for ev in self.events_by_chunk.get(chunk_num, []):
            yield ev

    def request_approval(self, body: dict[str, Any]) -> dict[str, Any]:
        aid = f"apr_{len(self.approvals) + 1}"
        self.approvals[aid] = {"status": "pending", **body}
        return {"approval_id": aid, "status": "pending"}

    def get_approval(self, aid: str) -> dict[str, Any]:
        return self.approvals[aid]

    def list_approvals(self, wid: str | None = None, status: str | None = None) -> list[dict[str, Any]]:
        return list(self.approvals.values())

    def apply_approval(self, wid: str, aid: str) -> dict[str, Any]:
        self.approvals[aid]["status"] = "applied"
        return {"workflow_id": wid, "version": 2}

    def auto_apply(self, wid: str, body: dict[str, Any]) -> dict[str, Any]:
        return {"workflow_id": wid, "version": 2}

    def suggest_fixes(self, wid: str, problem: str) -> dict[str, Any]:
        return {"suggestions": [{"prompt_version": "P3"}]}

    def run_validation(self, wid: str, pv: str, n: int) -> dict[str, Any]:
        return {"validation_run_id": "val_1", "pass_rate": 0.99}


def test_mock_client_contract():
    client = MockClient()
    assert client.get_state()["sim_minute"] == 0
    wfs = client.get_workflows()
    assert len(wfs) == 1
    adv = client.advance(60)
    assert adv["sim_minute"] == 60
    assert not adv["finished"]
