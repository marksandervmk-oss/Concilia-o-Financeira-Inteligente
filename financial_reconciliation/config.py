from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class ReconciliationConfig:
    """Tunable parameters used by the audit matching engine."""

    date_tolerance_days: int = 0
    value_tolerance: float = 0.0
    partial_date_window_days: int = 0
    partial_value_window: float = 0.0
    partial_value_percent: float = 0.0
    max_candidates_per_transaction: int = 250
    high_confidence_threshold: float = 0.82
    medium_confidence_threshold: float = 0.62
    minimum_match_score: float = 0.50
    duplicate_score_gap: float = 0.04
    learn_min_score: float = 0.86

    def value_review_window(self, amount: float) -> float:
        return max(self.partial_value_window, abs(amount) * self.partial_value_percent)

    def normalized(self) -> "ReconciliationConfig":
        self.date_tolerance_days = max(0, int(self.date_tolerance_days))
        self.partial_date_window_days = max(
            self.date_tolerance_days, int(self.partial_date_window_days)
        )
        self.value_tolerance = max(0.0, float(self.value_tolerance))
        self.partial_value_window = max(self.value_tolerance, float(self.partial_value_window))
        self.partial_value_percent = max(0.0, float(self.partial_value_percent))
        self.max_candidates_per_transaction = max(20, int(self.max_candidates_per_transaction))
        return self
