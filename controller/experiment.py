from __future__ import annotations

import copy
import logging
from collections import deque
from dataclasses import dataclass, field
from typing import Any

from .models import ProposalIntent

logger = logging.getLogger("controller.experiment")


@dataclass
class VariantTracker:
    """Tracks performance metrics for an individual variant."""

    dim: str  # "voice" | "welcome_message"
    value: str  # e.g. "V1", "W2"
    total_dials: int = 0
    total_connected: int = 0
    total_engaged: int = 0
    # Rolling window of recent 100 connected calls for decay detection
    recent_engaged_window: deque[bool] = field(default_factory=lambda: deque(maxlen=100))

    @property
    def engagement_rate(self) -> float:
        if self.total_connected == 0:
            return 0.0
        return self.total_engaged / self.total_connected

    @property
    def rolling_engagement_rate(self) -> float:
        if not self.recent_engaged_window:
            return 0.0
        return sum(self.recent_engaged_window) / len(self.recent_engaged_window)

    def record_call(self, connected: bool, engaged: bool):
        self.total_dials += 1
        if connected:
            self.total_connected += 1
            self.recent_engaged_window.append(engaged)
            if engaged:
                self.total_engaged += 1


class ExperimentEngine:
    """Statistical experimenter for welcome messages and voices.

    Enforces:
    1. Minimum sample size (e.g. >= 80 connected calls per variant) before declaring statistical superiority.
    2. Exploitation with continuous exploration: 70% winner allocation, 30% uniform split across alternatives.
    3. Guardrail protection: disallows any variant that causes the secondary KPI to violate its maximum drop.
    4. Decay detection: if a promoted variant's rolling conversion drops significantly below baseline,
       automatically triggers rollback to balanced exploration.
    """

    def __init__(
        self,
        min_sample_size: int = 80,
        exploit_share: float = 0.70,
        decay_drop_threshold: float = 0.15,
    ):
        self.min_sample_size = min_sample_size
        self.exploit_share = exploit_share
        self.decay_drop_threshold = decay_drop_threshold
        # Tracks promoted winners: (workflow_id, dim) -> winner_variant_value
        self.promoted_winners: dict[tuple[str, str], str] = {}

    def record_call_outcome(
        self,
        variant_trackers: dict[str, dict[str, VariantTracker]],
        dim: str,
        value: str,
        connected: bool,
        engaged: bool,
    ):
        if dim not in variant_trackers:
            variant_trackers[dim] = {}
        if value not in variant_trackers[dim]:
            variant_trackers[dim][value] = VariantTracker(dim=dim, value=value)
        variant_trackers[dim][value].record_call(connected, engaged)

    def evaluate_dimension(
        self,
        wid: str,
        dim: str,
        options: list[str],
        current_alloc: dict[str, float],
        trackers: dict[str, VariantTracker],
        base_guardrail_rate: float,
        current_guardrail_rate: float,
        max_guardrail_drop: float,
    ) -> tuple[dict[str, float] | None, str]:
        """Evaluates a single dimension (e.g. voice) across available options.

        Returns (new_allocation_dict or None, rationale).
        """
        if len(options) <= 1:
            return None, "Only 1 option available"

        # Check guardrail compliance
        guardrail_drop = base_guardrail_rate - current_guardrail_rate
        if guardrail_drop > max_guardrail_drop:
            logger.warning(
                f"Workflow {wid} guardrail violated: drop {guardrail_drop:.3f} > max {max_guardrail_drop:.3f}. Pausing promotions."
            )
            return None, "Guardrail violation"

        active_promoted = self.promoted_winners.get((wid, dim))

        # 1. Decay Check on currently promoted winner
        if active_promoted and active_promoted in trackers:
            winner_tracker = trackers[active_promoted]
            # If rolling conversion drops by > decay_drop_threshold compared to its historical rate
            if len(winner_tracker.recent_engaged_window) >= 40:
                hist_rate = winner_tracker.engagement_rate
                roll_rate = winner_tracker.rolling_engagement_rate
                if hist_rate > 0 and (hist_rate - roll_rate) / hist_rate >= self.decay_drop_threshold:
                    logger.warning(
                        f"Decay detected on {wid} {dim}={active_promoted}: historical={hist_rate:.3f}, rolling={roll_rate:.3f}. Rolling back to balanced exploration."
                    )
                    self.promoted_winners.pop((wid, dim), None)
                    # Roll back to uniform distribution
                    uniform_weight = round(1.0 / len(options), 4)
                    new_alloc = {opt: uniform_weight for opt in options}
                    # Balance rounding
                    rem = round(1.0 - sum(new_alloc.values()), 4)
                    new_alloc[options[0]] = round(new_alloc[options[0]] + rem, 4)
                    return new_alloc, f"Decay detected on {active_promoted}; rollback to balanced exploration"

        # 2. Check if all options have met minimum sample size
        tested_options = [opt for opt in options if opt in trackers and trackers[opt].total_connected >= self.min_sample_size]
        if len(tested_options) < len(options):
            # Still exploring; ensure uniform distribution to gather balanced evidence
            if len(current_alloc) < len(options) or any(current_alloc.get(opt, 0.0) < 0.1 for opt in options):
                uniform_weight = round(1.0 / len(options), 4)
                new_alloc = {opt: uniform_weight for opt in options}
                rem = round(1.0 - sum(new_alloc.values()), 4)
                new_alloc[options[0]] = round(new_alloc[options[0]] + rem, 4)
                return new_alloc, "Gathering balanced statistical samples across all variants"
            return None, "Awaiting minimum sample size on all variants"

        # 3. Find statistical winner by engagement rate
        best_opt = max(tested_options, key=lambda opt: trackers[opt].engagement_rate)
        best_rate = trackers[best_opt].engagement_rate

        # Compare best option against average of others
        other_rates = [trackers[opt].engagement_rate for opt in tested_options if opt != best_opt]
        avg_other_rate = sum(other_rates) / len(other_rates) if other_rates else 0.0

        # Lift threshold: must beat other variants by at least 2% relative
        if best_rate <= avg_other_rate * 1.02:
            return None, "No statistically clear winner yet"

        # If best option is already the promoted winner, nothing to change
        if active_promoted == best_opt and current_alloc.get(best_opt, 0.0) >= self.exploit_share:
            return None, "Winner already actively exploited"

        # 4. Construct 70/30 allocation
        new_alloc = {}
        new_alloc[best_opt] = round(self.exploit_share, 4)

        other_options = [opt for opt in options if opt != best_opt]
        other_share = round((1.0 - self.exploit_share) / len(other_options), 4)
        for opt in other_options:
            new_alloc[opt] = other_share

        # Normalize any rounding discrepancy
        rem = round(1.0 - sum(new_alloc.values()), 4)
        new_alloc[best_opt] = round(new_alloc[best_opt] + rem, 4)

        self.promoted_winners[(wid, dim)] = best_opt
        rationale = (
            f"Statistically promote {dim}={best_opt} (engagement {best_rate:.1%} vs avg {avg_other_rate:.1%}); "
            f"allocating {self.exploit_share:.0%} exploit, {(1.0-self.exploit_share):.0%} explore"
        )
        return new_alloc, rationale

    def evaluate_workflow(
        self,
        wid: str,
        spec: dict[str, Any],
        current_cfg: dict[str, Any],
        trackers: dict[str, dict[str, VariantTracker]],
        recent_metrics: dict[str, Any],
        sim_minute: int,
    ) -> ProposalIntent | None:
        """Evaluates welcome_message and voice dimensions and builds a proposal if changes are warranted."""
        options = spec.get("options", {})
        default_alloc = current_cfg.get("allocations", {}).get("default", {})

        obj = spec.get("objective", {})
        guardrail_spec = obj.get("guardrail", {})
        max_guardrail_drop = guardrail_spec.get("pickup_rate_max_drop", 0.05)

        base_pickup = spec.get("base_pickup", 0.30)
        current_pickup = recent_metrics.get("pickup_rate", base_pickup)

        updated_allocations = copy.deepcopy(current_cfg.get("allocations", {}))
        changed_dims = []
        rationales = []

        # Evaluate welcome_message and voice
        for dim in ["welcome_message", "voice"]:
            dim_opts = options.get(dim, [])
            if not dim_opts:
                continue

            current_dim_alloc = default_alloc.get(dim, {})
            dim_trackers = trackers.get(dim, {})

            new_dim_alloc, rationale = self.evaluate_dimension(
                wid=wid,
                dim=dim,
                options=dim_opts,
                current_alloc=current_dim_alloc,
                trackers=dim_trackers,
                base_guardrail_rate=base_pickup,
                current_guardrail_rate=current_pickup,
                max_guardrail_drop=max_guardrail_drop,
            )

            if new_dim_alloc is not None and new_dim_alloc != current_dim_alloc:
                if "default" not in updated_allocations:
                    updated_allocations["default"] = {}
                updated_allocations["default"][dim] = new_dim_alloc
                changed_dims.append(dim)
                rationales.append(rationale)

        if not changed_dims:
            return None

        new_cfg = copy.deepcopy(current_cfg)
        new_cfg["allocations"] = updated_allocations

        intent = ProposalIntent(
            workflow_id=wid,
            proposed_config=new_cfg,
            rationale="; ".join(rationales),
            changed_dims=changed_dims,
            change_summary=f"Experiment optimization: update {', '.join(changed_dims)}",
            impact_score=0.65,
            created_minute=sim_minute,
        )
        return intent
