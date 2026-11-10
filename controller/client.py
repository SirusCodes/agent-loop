from __future__ import annotations

import json
from abc import ABC, abstractmethod
from typing import Any, Iterator

import httpx


class BaseClient(ABC):
    """Abstract interface defining the universal platform operations.

    In the assignment, this is implemented by SimulatorClient.
    In production, a ProductionClient would talk to real dialler and approval systems.
    """

    @abstractmethod
    def get_state(self) -> dict[str, Any]:
        """Fetch current platform/simulation state."""
        ...

    @abstractmethod
    def advance(self, minutes: int) -> dict[str, Any]:
        """Advance simulation time by the specified minutes."""
        ...

    @abstractmethod
    def get_workflows(self) -> list[dict[str, Any]]:
        """List all workflows and their specifications."""
        ...

    @abstractmethod
    def get_workflow(self, wid: str) -> dict[str, Any]:
        """Get workflow metadata and governance policies."""
        ...

    @abstractmethod
    def get_config(self, wid: str) -> dict[str, Any]:
        """Get active configuration for a workflow."""
        ...

    @abstractmethod
    def get_chunks(self, kind: str = "events", after: int = -1) -> list[dict[str, Any]]:
        """List available event chunks."""
        ...

    @abstractmethod
    def stream_chunk_events(self, chunk_num: int) -> Iterator[dict[str, Any]]:
        """Stream NDJSON events from chunk n."""
        ...

    @abstractmethod
    def request_approval(self, body: dict[str, Any]) -> dict[str, Any]:
        """Submit a proposal for governance review."""
        ...

    @abstractmethod
    def get_approval(self, aid: str) -> dict[str, Any]:
        """Check status of an approval request."""
        ...

    @abstractmethod
    def list_approvals(self, wid: str | None = None, status: str | None = None) -> list[dict[str, Any]]:
        """List approvals with optional filters."""
        ...

    @abstractmethod
    def apply_approval(self, wid: str, aid: str) -> dict[str, Any]:
        """Apply an approved configuration change."""
        ...

    @abstractmethod
    def auto_apply(self, wid: str, body: dict[str, Any]) -> dict[str, Any]:
        """Auto-apply an allowed configuration shift."""
        ...

    @abstractmethod
    def suggest_fixes(self, wid: str, problem: str) -> dict[str, Any]:
        """Request LLM fix suggestions for prompt issues."""
        ...

    @abstractmethod
    def run_validation(self, wid: str, pv: str, n: int) -> dict[str, Any]:
        """Run synthetic validation test on a prompt version."""
        ...


class SimulatorClient(BaseClient):
    """Concrete HTTP adapter for the assignment simulator."""

    def __init__(self, base_url: str = "http://127.0.0.1:8700", timeout: float = 120.0):
        self.base_url = base_url.rstrip("/")
        self.client = httpx.Client(base_url=self.base_url, timeout=timeout)

    def close(self):
        self.client.close()

    def get_state(self) -> dict[str, Any]:
        resp = self.client.get("/sim/state")
        resp.raise_for_status()
        return resp.json()

    def advance(self, minutes: int) -> dict[str, Any]:
        resp = self.client.post("/sim/advance", json={"minutes": minutes})
        resp.raise_for_status()
        return resp.json()

    def get_workflows(self) -> list[dict[str, Any]]:
        resp = self.client.get("/workflows")
        resp.raise_for_status()
        return resp.json()

    def get_workflow(self, wid: str) -> dict[str, Any]:
        resp = self.client.get(f"/workflows/{wid}")
        resp.raise_for_status()
        return resp.json()

    def get_config(self, wid: str) -> dict[str, Any]:
        resp = self.client.get(f"/workflows/{wid}/config")
        resp.raise_for_status()
        return resp.json()

    def get_chunks(self, kind: str = "events", after: int = -1) -> list[dict[str, Any]]:
        resp = self.client.get("/events/chunks", params={"kind": kind, "after": after})
        resp.raise_for_status()
        return resp.json()

    def stream_chunk_events(self, chunk_num: int) -> Iterator[dict[str, Any]]:
        with self.client.stream("GET", f"/events/chunks/{chunk_num}") as resp:
            resp.raise_for_status()
            for line in resp.iter_lines():
                line = line.strip()
                if line:
                    yield json.loads(line)

    def request_approval(self, body: dict[str, Any]) -> dict[str, Any]:
        resp = self.client.post("/approvals", json=body)
        resp.raise_for_status()
        return resp.json()

    def get_approval(self, aid: str) -> dict[str, Any]:
        resp = self.client.get(f"/approvals/{aid}")
        resp.raise_for_status()
        return resp.json()

    def list_approvals(self, wid: str | None = None, status: str | None = None) -> list[dict[str, Any]]:
        params = {}
        if wid:
            params["workflow_id"] = wid
        if status:
            params["status"] = status
        resp = self.client.get("/approvals", params=params)
        resp.raise_for_status()
        return resp.json()

    def apply_approval(self, wid: str, aid: str) -> dict[str, Any]:
        resp = self.client.post(f"/workflows/{wid}/apply", json={"approval_id": aid})
        resp.raise_for_status()
        return resp.json()

    def auto_apply(self, wid: str, body: dict[str, Any]) -> dict[str, Any]:
        resp = self.client.put(f"/workflows/{wid}/config", json=body)
        resp.raise_for_status()
        return resp.json()

    def suggest_fixes(self, wid: str, problem: str) -> dict[str, Any]:
        resp = self.client.post("/llm/suggest-fixes", json={"workflow_id": wid, "problem": problem})
        resp.raise_for_status()
        return resp.json()

    def run_validation(self, wid: str, pv: str, n: int) -> dict[str, Any]:
        resp = self.client.post("/validation/runs", json={"workflow_id": wid, "prompt_version": pv, "n": n})
        resp.raise_for_status()
        return resp.json()
