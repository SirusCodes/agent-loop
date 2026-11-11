from __future__ import annotations

from typing import Any


class HallucinationDetector:
    """Detects statistically significant spikes in LLM hallucination rate.

    Normal baseline prompts (P1: 0.006, P3: 0.004, P5: 0.003) have imperfect QA
    detector noise with occasional false flags up to 3-4%.
    When an unsafe prompt (such as P2 with 0.055 hallucination) is active,
    the hallucination rate spikes above 5%.
    Threshold is set to 0.048 (4.8%) over at least 50 calls to avoid false alarms.
    """

    def __init__(self, threshold: float = 0.048, min_sample: int = 50):
        self.threshold = threshold
        self.min_sample = min_sample

    def check(self, recent_calls: list[Any]) -> tuple[bool, float, int]:
        """Evaluates recent connected calls for genuine hallucination spikes.

        Returns:
            (is_incident, current_rate, sample_size)
        """
        connected_calls = [c for c in recent_calls if getattr(c, "connected", False)]
        sample_size = len(connected_calls)
        if sample_size < self.min_sample:
            return False, 0.0, sample_size

        hallucinations = sum(
            1 for c in connected_calls if getattr(c, "hallucination_flag", False)
        )
        rate = hallucinations / sample_size

        is_incident = rate >= self.threshold
        return is_incident, round(rate, 4), sample_size


class DidHealthDetector:
    """Monitors per-caller-ID pickup performance in a rolling call window.

    Instead of lifetime all-time dials (which dilute recent spam flagging),
    we inspect recent calls (e.g. last 300 calls). If a DID's recent pickup rate
    is significantly below the other DIDs, it flags that DID.
    """

    def __init__(self, min_calls_per_did: int = 40, drop_ratio_threshold: float = 0.55):
        self.min_calls_per_did = min_calls_per_did
        self.drop_ratio_threshold = drop_ratio_threshold

    def check_recent(self, recent_calls: list[Any]) -> list[str]:
        """Evaluates recent call attempts grouped by caller ID.

        Returns list of degraded caller ID strings.
        """
        did_counts: dict[str, list[int]] = {}  # did -> [dials, connected]
        for c in recent_calls:
            did = getattr(c, "caller_id", "")
            if not did:
                continue
            if did not in did_counts:
                did_counts[did] = [0, 0]
            did_counts[did][0] += 1
            if getattr(c, "connected", False):
                did_counts[did][1] += 1

        total_dials = sum(d[0] for d in did_counts.values())
        total_conn = sum(d[1] for d in did_counts.values())
        if total_dials < 100 or total_conn == 0:
            return []

        avg_rate = total_conn / total_dials
        degraded = []
        for did, (dials, conn) in did_counts.items():
            if dials >= self.min_calls_per_did:
                did_rate = conn / dials
                if did_rate < (avg_rate * self.drop_ratio_threshold):
                    degraded.append(did)
        return degraded
