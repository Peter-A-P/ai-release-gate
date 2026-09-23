"""The gate's statistics on inputs with known answers. Nothing here touches the bank except
the two tests that say so, which need the `gate` extra."""

from __future__ import annotations

import math
import random

import pytest

from drift.analysis.stats import bootstrap_mean
from gate.stats import (
    bootstrap_share,
    holm,
    items_needed,
    paired_difference,
    variance_inflation,
)


def test_bootstrap_share_matches_the_item_bootstrap_in_distribution() -> None:
    """Same point, and interval ends within a resample's worth of each other: the binomial
    draw is the item bootstrap over binary values, not an approximation to it."""
    values = [True] * 80 + [False] * 20
    fast = bootstrap_share(values, seed=1)
    slow = bootstrap_mean([1.0 if v else 0.0 for v in values], seed=1)
    assert fast.point == slow.point == 0.8 and fast.n == slow.n == 100
    assert abs(fast.lo - slow.lo) <= 0.02 and abs(fast.hi - slow.hi) <= 0.02


def test_bootstrap_share_degenerate() -> None:
    assert bootstrap_share([]).n == 0
    e = bootstrap_share([True, True, True])
    assert e.point == e.lo == e.hi == 1.0
    e = bootstrap_share([False, False])
    assert e.point == e.lo == e.hi == 0.0


def test_paired_difference_on_identical_sides_is_exactly_zero() -> None:
    side = {f"i{k}": k % 3 != 0 for k in range(60)}
    t = paired_difference(side, side, delta=0.03)
    assert t.paired_items == 60
    assert t.difference.point == t.difference.lo == t.difference.hi == 0.0
    assert t.worse == t.better == 0 and t.mcnemar_p == 1.0
    assert t.p_inferior == 0.0 and t.non_inferior


def test_paired_difference_counts_the_discordant_pairs_and_pairs_by_item() -> None:
    base = {"a": True, "b": True, "c": False, "d": False, "only-base": True}
    cand = {"a": True, "b": False, "c": True, "d": False, "only-cand": True}
    t = paired_difference(base, cand, delta=0.03)
    assert t.paired_items == 4, "an item one side did not grade is dropped from both"
    assert t.worse == 1 and t.better == 1 and t.difference.point == 0.0


def test_a_clear_regression_is_inferior() -> None:
    base = {f"i{k}": True for k in range(200)}
    cand = {f"i{k}": k >= 40 for k in range(200)}  # 20% drop, 40 worse, 0 better
    t = paired_difference(base, cand, delta=0.03, seed=2)
    assert t.difference.point == -0.2
    assert t.difference.hi < -0.03 and not t.non_inferior
    assert t.p_inferior > 0.99
    assert t.mcnemar_p < 1e-6


def test_a_small_wobble_on_enough_items_is_non_inferior() -> None:
    base = {f"i{k}": True for k in range(400)}
    cand = {f"i{k}": k >= 2 for k in range(400)}  # half a point down
    t = paired_difference(base, cand, delta=0.03, seed=2)
    assert -0.03 < t.difference.lo < 0.0 and t.non_inferior
    assert t.p_inferior < 0.025


def test_inflation_widens_the_interval_and_leaves_the_point_alone() -> None:
    base = {f"i{k}": True for k in range(120)}
    cand = {f"i{k}": k >= 3 for k in range(120)}
    plain = paired_difference(base, cand, delta=0.03, seed=3)
    wide = paired_difference(base, cand, delta=0.03, seed=3, inflation=4.0)
    assert plain.difference.point == wide.difference.point
    assert wide.difference.hi - wide.difference.lo > 1.8 * (
        plain.difference.hi - plain.difference.lo
    )
    assert math.isclose(wide.effective_items, 30.0)
    assert wide.p_inferior >= plain.p_inferior


def test_paired_difference_with_nothing_in_common() -> None:
    t = paired_difference({"a": True}, {"b": True}, delta=0.03)
    assert t.paired_items == 0 and not t.non_inferior and t.p_inferior == 1.0


def test_holm_is_step_down_monotone_and_capped() -> None:
    assert holm([]) == []
    assert holm([0.01]) == [0.01]
    adj = holm([0.01, 0.04, 0.03])
    # sorted: 0.01*3 = 0.03; 0.03*2 = 0.06; 0.04*1 = 0.04 -> raised to 0.06
    assert adj == [0.03, 0.06, 0.06]
    assert holm([0.5, 0.9]) == [1.0, 1.0]


def test_variance_inflation_from_the_bank() -> None:
    """The numbers PLAN.md quotes from 02: a hundred MATH items are worth about six, a hundred
    MMLU items about forty-seven. An unknown benchmark has no correction rather than a guess."""
    math_infl = variance_inflation("math", 100)
    mmlu_infl = variance_inflation("mmlu", 100)
    assert math_infl is not None and mmlu_infl is not None
    assert 5.5 < 100 / math_infl < 7.5
    assert 45 < 100 / mmlu_infl < 48
    assert variance_inflation("no-such-benchmark", 100) is None


def test_items_needed_never_falls_below_the_reference_answer() -> None:
    """The plan's own figures at the reference: 118 items for three points, 33 for five. A
    baseline the bank cannot place uses them; a baseline it places near its flat top would get
    an absurdly small number, and gets the reference instead."""
    off_scale = items_needed(3.0, power=0.8, accuracy=0.95, reference_ability=0.0)
    assert off_scale.items == 118 and off_scale.saturated
    assert "off the bank's scale" in off_scale.note
    unknown = items_needed(5.0, power=0.8, accuracy=None, reference_ability=0.0)
    assert unknown.items == 33 and not unknown.saturated
    near_top = items_needed(3.0, power=0.8, accuracy=0.80, reference_ability=0.0)
    assert near_top.items == 118 and not near_top.saturated
    assert "is the larger and holds" in near_top.note
    low = items_needed(3.0, power=0.8, accuracy=0.45, reference_ability=0.0)
    assert low.items is not None and low.items > 118, "a weak model needs more items, not fewer"


def test_paired_bootstrap_matches_the_item_bootstrap_in_distribution() -> None:
    """The two-binomial draw against the plain resample of items, on a mix of 3 worse and 1
    better out of 120, which is the control between the two September runs. Interval ends
    equal to the resolution of 2,000 resamples; p within Monte Carlo noise."""
    base = {f"i{k}": k >= 0 for k in range(120)}
    cand = {f"i{k}": k >= 3 for k in range(120)}
    base["i3"] = False  # one item the candidate gets right and the baseline wrong
    t = paired_difference(base, cand, delta=0.03, seed=0)
    assert t.worse == 3 and t.better == 1
    ids = sorted(base)
    diffs = [float(cand[i]) - float(base[i]) for i in ids]
    n = len(diffs)
    rng = random.Random(0)
    naive = sorted(sum(diffs[rng.randrange(n)] for _ in range(n)) / n for _ in range(2000))
    assert abs(t.difference.lo - naive[50]) <= 1 / n
    assert abs(t.difference.hi - naive[1949]) <= 1 / n
    p_naive = sum(1 for m in naive if m <= -0.03) / 2000
    assert abs(t.p_inferior - p_naive) < 0.03


# ------------------------------------------------------ correcting a judge-graded difference


def _sides(n: int, worse: int, better: int) -> tuple[dict[str, bool], dict[str, bool]]:
    base = {f"q{i}": True for i in range(n)}
    cand = dict(base)
    for i in range(worse):
        cand[f"q{i}"] = False
    for i in range(worse, worse + better):
        base[f"q{i}"] = False
    return base, cand


def test_a_judge_shrinks_a_regression_and_the_correction_undoes_it() -> None:
    """Sensitivity 0.9 and specificity 0.6 make se + sp - 1 = 0.5, so a judge sees half of any
    true difference. An observed drop of 5 points is a true drop of 10, and the gate must
    decide on the 10: deciding on the 5 is a gate that gets more lenient the worse its judge."""
    base, cand = _sides(400, worse=30, better=10)  # observed -5.0 points
    raw = paired_difference(base, cand, delta=0.03, resamples=1000, seed=1)
    fixed = paired_difference(
        base, cand, delta=0.03, resamples=1000, seed=1, judge_counts=(90, 10, 40, 60)
    )
    assert math.isclose(raw.difference.point, -0.05)
    assert math.isclose(fixed.difference.point, -0.10)
    assert fixed.judge_youden is not None and math.isclose(fixed.judge_youden, 0.5)
    assert raw.judge_youden is None


def test_the_correction_carries_the_calibrations_own_uncertainty() -> None:
    """Dividing the raw interval by 0.5 would treat se and sp as known exactly. They were
    measured on a few hundred labels, so the corrected interval is wider than that."""
    base, cand = _sides(400, worse=30, better=10)
    raw = paired_difference(base, cand, delta=0.03, resamples=2000, seed=3)
    fixed = paired_difference(
        base, cand, delta=0.03, resamples=2000, seed=3, judge_counts=(90, 10, 40, 60)
    )
    raw_width = raw.difference.hi - raw.difference.lo
    fixed_width = fixed.difference.hi - fixed.difference.lo
    assert fixed_width > raw_width / 0.5, "the calibration's sampling error has to widen it"


def test_a_perfect_judge_changes_nothing_but_the_stream() -> None:
    base, cand = _sides(300, worse=12, better=4)
    raw = paired_difference(base, cand, delta=0.03, resamples=2000, seed=5)
    same = paired_difference(
        base, cand, delta=0.03, resamples=2000, seed=5, judge_counts=(200, 0, 0, 100)
    )
    assert same.judge_youden == 1.0
    assert math.isclose(same.difference.point, raw.difference.point)
    assert abs(same.difference.lo - raw.difference.lo) < 0.01


def test_a_judge_that_carries_no_information_is_refused_not_divided_by() -> None:
    base, cand = _sides(100, worse=5, better=1)
    with pytest.raises(ValueError, match="noise"):
        paired_difference(base, cand, delta=0.03, judge_counts=(50, 50, 50, 50))
    with pytest.raises(ValueError, match="no positives or no negatives"):
        paired_difference(base, cand, delta=0.03, judge_counts=(317, 0, 0, 0))
