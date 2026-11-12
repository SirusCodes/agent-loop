import pytest
from controller.experiment import ExperimentEngine, VariantTracker


def test_experiment_engine_min_sample_size():
    """Verify that promotions are held until the minimum sample size is met across variants."""
    engine = ExperimentEngine(min_sample_size=80, exploit_share=0.70)

    options = ["V1", "V2"]
    trackers = {
        "V1": VariantTracker("voice", "V1", total_dials=100, total_connected=85, total_engaged=50),
        "V2": VariantTracker("voice", "V2", total_dials=60, total_connected=40, total_engaged=20),  # < 80 connected
    }
    current_alloc = {"V1": 0.5, "V2": 0.5}

    alloc, rationale = engine.evaluate_dimension(
        wid="nw_renewal",
        dim="voice",
        options=options,
        current_alloc=current_alloc,
        trackers=trackers,
        base_guardrail_rate=0.30,
        current_guardrail_rate=0.30,
        max_guardrail_drop=0.05,
    )
    # V2 has only 40 connected calls, so it should not promote yet
    assert alloc is None
    assert "sample size" in rationale


def test_experiment_engine_winner_promotion():
    """Verify that when sufficient samples exist, the winner is allocated 70% and alternatives 30%."""
    engine = ExperimentEngine(min_sample_size=80, exploit_share=0.70)

    options = ["V1", "V2"]
    # V1: 50 / 100 = 50% engagement
    # V2: 65 / 100 = 65% engagement (clear winner)
    trackers = {
        "V1": VariantTracker("voice", "V1", total_dials=120, total_connected=100, total_engaged=50),
        "V2": VariantTracker("voice", "V2", total_dials=120, total_connected=100, total_engaged=65),
    }
    current_alloc = {"V1": 0.5, "V2": 0.5}

    alloc, rationale = engine.evaluate_dimension(
        wid="nw_renewal",
        dim="voice",
        options=options,
        current_alloc=current_alloc,
        trackers=trackers,
        base_guardrail_rate=0.30,
        current_guardrail_rate=0.30,
        max_guardrail_drop=0.05,
    )
    assert alloc is not None
    assert alloc["V2"] == 0.70
    assert alloc["V1"] == 0.30
    assert "Statistically promote" in rationale


def test_experiment_engine_guardrail_protection():
    """Verify that promotions are halted if the guardrail KPI experiences excessive drop."""
    engine = ExperimentEngine(min_sample_size=80, exploit_share=0.70)

    options = ["V1", "V2"]
    trackers = {
        "V1": VariantTracker("voice", "V1", total_dials=100, total_connected=90, total_engaged=40),
        "V2": VariantTracker("voice", "V2", total_dials=100, total_connected=90, total_engaged=65),
    }
    current_alloc = {"V1": 0.5, "V2": 0.5}

    # Baseline pickup = 0.30, current pickup = 0.22 -> drop of 0.08 exceeds max drop of 0.05
    alloc, rationale = engine.evaluate_dimension(
        wid="nw_renewal",
        dim="voice",
        options=options,
        current_alloc=current_alloc,
        trackers=trackers,
        base_guardrail_rate=0.30,
        current_guardrail_rate=0.22,
        max_guardrail_drop=0.05,
    )
    assert alloc is None
    assert "Guardrail violation" in rationale


def test_experiment_engine_decay_and_rollback():
    """Verify that when a promoted winner's conversion drops, rollback to balanced exploration is triggered."""
    engine = ExperimentEngine(min_sample_size=80, exploit_share=0.70, decay_drop_threshold=0.15)
    # Register V2 as previously promoted
    engine.promoted_winners[("nw_renewal", "voice")] = "V2"

    options = ["V1", "V2"]
    v2_tracker = VariantTracker("voice", "V2", total_dials=300, total_connected=250, total_engaged=150)  # historical = 60%
    # But recent 50 calls yielded only 20% engagement (decay from wear-out)
    for _ in range(50):
        v2_tracker.recent_engaged_window.append(False)
    for _ in range(10):
        v2_tracker.recent_engaged_window.append(True)
    # Rolling engagement = 10 / 60 = 16.7%

    trackers = {
        "V1": VariantTracker("voice", "V1", total_dials=100, total_connected=80, total_engaged=40),
        "V2": v2_tracker,
    }
    current_alloc = {"V2": 0.70, "V1": 0.30}

    alloc, rationale = engine.evaluate_dimension(
        wid="nw_renewal",
        dim="voice",
        options=options,
        current_alloc=current_alloc,
        trackers=trackers,
        base_guardrail_rate=0.30,
        current_guardrail_rate=0.30,
        max_guardrail_drop=0.05,
    )
    assert alloc is not None
    # Reverted to 50/50 uniform
    assert alloc["V1"] == 0.50
    assert alloc["V2"] == 0.50
    assert "Decay detected" in rationale
