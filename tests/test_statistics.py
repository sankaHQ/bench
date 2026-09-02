from __future__ import annotations

import math

import pytest

from sanka_bench.statistics import (
    Interval,
    bootstrap_interval,
    paired_difference_interval,
    weighted_score,
    wilson_interval,
)


def test_wilson_matches_reference_values() -> None:
    # 7 of 10 at 95 %: Wilson (0.3968, 0.8922) to four decimals (Brown, Cai, DasGupta 2001).
    interval = wilson_interval(7, 10)
    assert interval.estimate == pytest.approx(0.7)
    assert interval.low == pytest.approx(0.3968, abs=5e-4)
    assert interval.high == pytest.approx(0.8922, abs=5e-4)
    # extremes stay inside [0, 1] and never collapse to a point
    zero = wilson_interval(0, 11)
    assert zero.low == 0.0 and 0 < zero.high < 0.3
    full = wilson_interval(33, 33)
    assert full.high == 1.0 and 0.85 < full.low < 1.0
    assert wilson_interval(0, 0) == Interval(0.0, 0.0, 1.0)


def test_wilson_rejects_impossible_counts() -> None:
    with pytest.raises(ValueError):
        wilson_interval(3, 2)
    with pytest.raises(ValueError):
        wilson_interval(1, 1, confidence=1.0)


def test_weighted_score_averages_samples_per_task() -> None:
    outcomes = [[True, True, True], [True, False, False], [False, False, False]]
    weights = [10, 20, 30]
    # 10·1 + 20·(1/3) + 30·0 = 16.67 of 60
    assert weighted_score(outcomes, weights) == pytest.approx(16.6667 / 60, abs=1e-4)
    assert weighted_score([], []) == 0.0
    with pytest.raises(ValueError):
        weighted_score([[True]], [1, 2])


def test_bootstrap_interval_is_deterministic_and_brackets_the_estimate() -> None:
    outcomes = [[True] * 3, [True, True, False], [False] * 3, [True] * 3, [True, False, False]]
    weights = [16, 22, 12, 30, 20]
    first = bootstrap_interval(outcomes, weights, resamples=500)
    second = bootstrap_interval(outcomes, weights, resamples=500)
    assert first == second
    assert first.low <= first.estimate <= first.high
    assert first.low < first.high
    # a suite where every task passes every sample has no spread
    certain = bootstrap_interval([[True] * 3] * 4, [1, 2, 3, 4], resamples=200)
    assert certain.low == certain.high == certain.estimate == 1.0


def test_paired_difference_cancels_task_difficulty() -> None:
    control = [[True, False, False], [False] * 3, [True] * 3, [False, False, True]]
    treatment = [[True, True, False], [True, False, False], [True] * 3, [True, True, True]]
    weights = [10, 10, 10, 10]
    interval = paired_difference_interval(treatment, control, weights, resamples=500)
    assert interval.estimate == pytest.approx(
        weighted_score(treatment, weights) - weighted_score(control, weights)
    )
    assert interval.low <= interval.estimate <= interval.high
    # identical arms give exactly zero everywhere
    same = paired_difference_interval(control, control, weights, resamples=100)
    assert same == Interval(0.0, 0.0, 0.0)
    with pytest.raises(ValueError):
        paired_difference_interval(treatment, control[:-1], weights)


def test_interval_serialises_for_reports() -> None:
    payload = wilson_interval(3, 4).to_dict()
    assert set(payload) == {"estimate", "low", "high", "confidence"}
    assert all(math.isfinite(value) for value in payload.values())
