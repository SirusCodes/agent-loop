import pytest
from controller.detector import DidHealthDetector, HallucinationDetector
from controller.state import CallOutcome


def test_hallucination_detector():
    """Verify that hallucination spikes above threshold are flagged."""
    detector = HallucinationDetector(threshold=0.048, min_sample=40)

    # Below min sample
    calls_small = [
        CallOutcome(
            ts="", sim_minute=0, connected=True, engaged=True,
            hallucination_flag=True, caller_id="D1", voice="V1",
            welcome="W1", prompt_version="P1", cohort_id="c1"
        ) for _ in range(10)
    ]
    is_inc, rate, sample = detector.check(calls_small)
    assert not is_inc
    assert sample == 10

    # 50 calls, 1 hallucination = 2.0% (below 4.8% threshold)
    calls_safe = [
        CallOutcome(
            ts="", sim_minute=0, connected=True, engaged=True,
            hallucination_flag=(i == 0), caller_id="D1", voice="V1",
            welcome="W1", prompt_version="P1", cohort_id="c1"
        ) for i in range(50)
    ]
    is_inc, rate, sample = detector.check(calls_safe)
    assert not is_inc
    assert rate == 0.02

    # 50 calls, 3 hallucinations = 6.0% (spike! above 4.8%)
    calls_spike = [
        CallOutcome(
            ts="", sim_minute=0, connected=True, engaged=True,
            hallucination_flag=(i < 3), caller_id="D1", voice="V1",
            welcome="W1", prompt_version="P2", cohort_id="c1"
        ) for i in range(50)
    ]
    is_inc, rate, sample = detector.check(calls_spike)
    assert is_inc
    assert rate == 0.06


def test_did_health_detector():
    """Verify that caller IDs with severely degraded connection rates are identified."""
    detector = DidHealthDetector(min_calls_per_did=40, drop_ratio_threshold=0.55)

    calls = []
    # D1: 60 calls, 24 connects (40% pickup)
    for i in range(60):
        calls.append(
            CallOutcome(
                ts="", sim_minute=0, connected=(i < 24), engaged=True,
                hallucination_flag=False, caller_id="D1", voice="V1",
                welcome="W1", prompt_version="P1", cohort_id="c1"
            )
        )
    # D2: 60 calls, 6 connects (10% pickup -> degraded)
    for i in range(60):
        calls.append(
            CallOutcome(
                ts="", sim_minute=0, connected=(i < 6), engaged=True,
                hallucination_flag=False, caller_id="D2", voice="V1",
                welcome="W1", prompt_version="P1", cohort_id="c1"
            )
        )

    degraded = detector.check_recent(calls)
    assert degraded == ["D2"]
