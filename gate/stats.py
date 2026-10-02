"""The gate's statistics (PLAN.md B2.2, B5): paired non-inferiority, Holm, power.

Built on Part A's `drift.analysis.stats` for the interval machinery and on project 02's
`mselect` for the power function and the local-dependence correction. Nothing here is
reimplemented that either already provides.
"""

from __future__ import annotations

import math
import random
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from functools import cache
from typing import Any

from drift.analysis.stats import Estimate, jeffreys_proportion, mcnemar_exact


def rate_draw(rng: random.Random, k: int, n: int) -> float:
    """The rate to resample `k` successes in `n` at, for one bootstrap replicate.

    The observed k / n, exactly as a percentile bootstrap uses it, except at 0 or n. There the
    bootstrap can only ever redraw the same 0 or n, so it reports a zero-width interval, and in
    a paired comparison a zero "worse" count becomes a certainty that nothing got worse. An
    observed 0 is not a known 0. So at 0 or n the rate is drawn from its Jeffreys posterior,
    Beta(k + 1/2, n - k + 1/2), the interval Part A and the calibration already use for the same
    case. Only those replicates change, and no random number is drawn otherwise, so a
    comparison with no zero count gives the identical interval it gave before 2026-09-27.
    """
    if n <= 0:
        return 0.0
    if 0 < k < n:
        return k / n
    return rng.betavariate(k + 0.5, n - k + 0.5)


def bootstrap_share(values: Sequence[bool], *, resamples: int = 2000, seed: int = 0) -> Estimate:
    """Percentile bootstrap of a share of binary values: the same distribution as
    `drift.analysis.stats.bootstrap_mean` over 0/1 items, drawn in one binomial variate per
    resample instead of n draws. Resampling n binary items with replacement gives a count of
    successes that is Binomial(n, k/n) exactly, so nothing is approximated; the A/A study runs
    the gate several hundred times and this is what makes that a few minutes rather than an
    hour. The stream differs from `bootstrap_mean`'s, so the two are not compared bit for bit.
    """
    n = len(values)
    if n == 0:
        return Estimate(float("nan"), float("nan"), float("nan"), 0)
    k = sum(1 for v in values if v)
    if k in (0, n):
        # Nothing to resample: 100 of 100 does not mean a rate of exactly one (see rate_draw).
        return jeffreys_proportion(k, n, seed=seed)
    rng = random.Random(seed)
    p = k / n
    means = sorted(rng.binomialvariate(n, p) / n for _ in range(resamples))
    lo = means[int(0.025 * resamples)]
    hi = means[min(resamples - 1, int(0.975 * resamples))]
    return Estimate(p, lo, hi, n)


@dataclass(frozen=True, slots=True)
class PairedTest:
    """Candidate minus baseline over the items both sides scored."""

    paired_items: int
    # The 95% two-sided percentile interval of the mean paired difference, as a proportion.
    difference: Estimate
    # The margin, as a proportion. Non-inferior means the whole interval sits above -delta.
    delta: float
    # The one-sided p-value against inferiority: the share of resamples at or below -delta.
    # Small means the candidate is very unlikely to be worse by delta or more. This is what
    # Holm adjusts when several suites are decided together.
    p_inferior: float
    worse: int  # correct on the baseline, incorrect on the candidate
    better: int  # the reverse
    mcnemar_p: float
    # The variance inflation applied for local dependence, 1.0 when none was.
    inflation: float
    # For a judge-graded suite: sensitivity + specificity - 1 at the calibration's point, the
    # factor a judge's own error shrinks every true difference by. None when outcomes came from
    # a programmatic grader and need no correction.
    judge_youden: float | None = None
    # Resamples dropped because the resampled calibration left the judge with no information
    # (sensitivity + specificity at or below 1). Reported, because a lot of them means the
    # interval rests on the lucky draws.
    dropped_resamples: int = 0

    @property
    def non_inferior(self) -> bool:
        return self.paired_items > 0 and self.difference.lo > -self.delta

    @property
    def effective_items(self) -> float:
        return self.paired_items / self.inflation if self.inflation else float("nan")


def paired_difference(
    baseline: Mapping[str, bool],
    candidate: Mapping[str, bool],
    *,
    delta: float,
    resamples: int = 2000,
    seed: int = 0,
    inflation: float = 1.0,
    judge_counts: tuple[int, int, int, int] | None = None,
) -> PairedTest:
    """Percentile bootstrap over items of the mean of (candidate - baseline).

    Paired by item, always (B2.2): items differ far more than prompts do, and an unpaired test
    throws that away. Items one side did not grade are dropped from both.

    `inflation` is the design effect for locally dependent items, from
    `mselect.dependence()`: the bootstrap replicates are spread about the point by its square
    root, which widens the interval exactly as if the items were that many fewer. The point
    does not move.

    A paired difference on binary outcomes is -1, 0 or +1 per item, so a resample of n items
    is a multinomial count of the three, drawn here as two binomials rather than n item draws.
    Same distribution, a fraction of the time; see `bootstrap_share`.

    `judge_counts` is (true positive, false negative, false positive, true negative) from the
    judge's calibration, for a suite whose outcomes a judge gave rather than a programmatic
    grader. A judge with sensitivity se and specificity sp reports a pass with probability
    (se + sp - 1) p + (1 - sp) when the true rate is p, so on both sides of a paired
    comparison the difference it sees is the true difference times (se + sp - 1), whatever
    the two rates are. Uncorrected, that shrinks every regression towards zero and makes the
    gate lenient in exact proportion to how bad the judge is. So each resample divides by that
    factor, with se and sp themselves resampled from the calibration counts, which is what
    carries the calibration's own uncertainty into the interval. It assumes the judge errs the
    same way on both sides, which is the assumption a calibration over three answering models
    of different capability is there to support, and which is stated wherever the figure is.
    """
    paired = sorted(set(baseline) & set(candidate))
    n = len(paired)
    if n == 0:
        nan = float("nan")
        return PairedTest(0, Estimate(nan, nan, nan, 0), delta, 1.0, 0, 0, 1.0, inflation)
    youden: float | None = None
    se_n = sp_n = 0
    se_p = sp_p = 0.0
    if judge_counts is not None:
        tp, fn, fp, tn = judge_counts
        se_n, sp_n = tp + fn, fp + tn
        if se_n == 0 or sp_n == 0:
            raise ValueError(
                "a judge calibration with no positives or no negatives corrects nothing"
            )
        se_p, sp_p = tp / se_n, tn / sp_n
        youden = se_p + sp_p - 1.0
        if youden <= 0:
            raise ValueError(f"sensitivity + specificity - 1 is {youden:.3f}: the judge is noise")
    worse = sum(1 for i in paired if baseline[i] and not candidate[i])
    better = sum(1 for i in paired if candidate[i] and not baseline[i])
    raw_point = (better - worse) / n
    point = raw_point / youden if youden is not None else raw_point
    rng = random.Random(seed)
    spread = math.sqrt(inflation)
    tp = round(se_p * se_n)
    tn = round(sp_p * sp_n)

    def one() -> float:
        # Every rate through rate_draw: the observed rate, or a Jeffreys draw when a count is 0
        # or all, so no discordance and a flawless judge are never taken as certainties.
        w = rng.binomialvariate(n, rate_draw(rng, worse, n))
        b = rng.binomialvariate(n - w, rate_draw(rng, better, n - worse)) if n > w else 0
        raw = raw_point + ((b - w) / n - raw_point) * spread
        if youden is None:
            return raw
        se_d = rng.binomialvariate(se_n, rate_draw(rng, tp, se_n)) / se_n
        sp_d = rng.binomialvariate(sp_n, rate_draw(rng, tn, sp_n)) / sp_n
        y = se_d + sp_d - 1
        return raw / y if y > 0 else float("nan")

    drawn = [one() for _ in range(resamples)]
    means = sorted(m for m in drawn if not math.isnan(m))
    dropped = resamples - len(means)
    if not means:
        raise ValueError("every resample left the judge with no information")
    kept = len(means)
    lo = means[int(0.025 * kept)]
    hi = means[min(kept - 1, int(0.975 * kept))]
    p = sum(1 for m in means if m <= -delta) / kept
    return PairedTest(
        paired_items=n,
        difference=Estimate(point, lo, hi, n),
        delta=delta,
        p_inferior=p,
        worse=worse,
        better=better,
        mcnemar_p=mcnemar_exact(worse, better),
        inflation=inflation,
        judge_youden=youden,
        dropped_resamples=dropped,
    )


def holm(pvalues: Sequence[float]) -> list[float]:
    """Holm's step-down adjustment. Returned in the input order, each capped at 1 and
    monotone in the sorted order, so a smaller raw p never ends with a larger adjusted one."""
    m = len(pvalues)
    order = sorted(range(m), key=lambda i: pvalues[i])
    adjusted = [0.0] * m
    running = 0.0
    for rank, i in enumerate(order):
        running = max(running, min(1.0, (m - rank) * pvalues[i]))
        adjusted[i] = running
    return adjusted


def variance_inflation(benchmark: str, n_items: int) -> float | None:
    """The design effect for `n_items` that resemble one of 02's benchmarks, or None when the
    bank has no such block. 1 + (n - 1) r with r the mean residual correlation 02 measured."""
    import mselect

    dep = mselect.dependence()
    if benchmark not in dep:
        return None
    return float(dep[benchmark].variance_inflation(n_items))


@dataclass(frozen=True, slots=True)
class PowerLine:
    """Items per side to see a regression of `effect_points` at the target power."""

    effect_points: float
    power: float
    items: int | None  # None when the bank cannot answer at this ability
    ability: float
    # True when the baseline's score lies above the bank's own ceiling, so the ability could
    # not be read off the curve and the reference ability was used instead.
    saturated: bool
    note: str

    def describe(self) -> str:
        head = (
            f"{self.items} items" if self.items is not None else "no answer from the bank"
        ) + f" for a {self.effect_points:g} point drop at {self.power:.0%} power"
        return f"{head}; {self.note}"


@cache
def bank(min_discrimination: float | None = None) -> Any:
    """02's default bank, without the items whose discrimination is at or below
    `min_discrimination` when one is given.

    An item that barely discriminates has a difficulty that is a division by nearly zero: 02
    found its two banks' difficulties for the same 998 questions correlate -0.04 over all of
    them and +0.71 over the 532 that discriminate above 0.3 in both. At 0.3 this keeps 16,103
    of the 20,365 items."""
    import mselect
    import numpy as np

    items = mselect.default_items()
    if min_discrimination is None:
        return items
    return items.subset(np.flatnonzero(np.asarray(items.a) > min_discrimination))


@cache
def _curve(
    min_discrimination: float | None = None,
) -> tuple[tuple[float, ...], tuple[float, ...]]:
    import numpy as np
    from mselect.power import expected_score_curve

    grid = np.linspace(-4.0, 4.0, 161)
    scores = expected_score_curve(bank(min_discrimination), grid)
    return tuple(float(g) for g in grid), tuple(float(s) for s in scores)


def ability_for(accuracy: float, *, min_discrimination: float | None = None) -> tuple[float, bool]:
    """Where on 02's bank a full-suite accuracy sits, by inverting the bank's expected score
    curve, and whether it sat off the top of it. The bank tops out near 83%, and the drift
    panel scores in the nineties, so the second value is usually the interesting one."""
    grid, scores = _curve(min_discrimination)
    if accuracy >= scores[-1]:
        return grid[-1], True
    if accuracy <= scores[0]:
        return grid[0], True
    best = min(range(len(grid)), key=lambda i: abs(scores[i] - accuracy))
    return grid[best], False


@cache
def _items_needed(
    effect: float, power: float, ability: float, min_discrimination: float | None = None
) -> int | None:
    import mselect

    try:
        items = bank(min_discrimination) if min_discrimination is not None else None
        return int(mselect.items_needed(effect, power, ability, items=items).items)
    except ValueError:
        # The curve is flat there: no number of items from this bank resolves the difference.
        return None


def items_needed(
    effect_points: float,
    *,
    power: float,
    accuracy: float | None,
    reference_ability: float,
    min_discrimination: float | None = None,
) -> PowerLine:
    """B5: minimum items per suite from `mselect.items_needed`, with ability set from the
    baseline's score when the bank can place it and from the spec's reference otherwise.

    Treat the answer as a floor. 02 validated the function against its own simulation and
    found it well calibrated for small gaps and optimistic for large ones, and it assumes
    items chosen adaptively from the bank, which a fixed suite is not.

    The bank's expected score tops out near 83%, and near its top the curve is nearly flat, so
    a three-point drop there is a large jump in ability and the bank answers with a handful of
    items: 17 for three points at ability +4, against 118 at the reference. Seventeen items
    cannot show a three-point drop of anything, so the answer at the placed ability is never
    allowed below the answer at the reference. The larger of the two is the floor, and the
    note says which one it was.
    """
    at_ref = _items_needed(effect_points, power, reference_ability, min_discrimination)
    if accuracy is None or math.isnan(accuracy):
        note = f"at the reference ability {reference_ability:+.1f}"
        return PowerLine(effect_points, power, at_ref, reference_ability, False, note + FLOOR)
    ability, saturated = ability_for(accuracy, min_discrimination=min_discrimination)
    if saturated:
        note = (
            f"baseline accuracy {accuracy:.1%} is off the bank's scale, so the reference "
            f"ability {reference_ability:+.1f} was used"
        )
        return PowerLine(effect_points, power, at_ref, reference_ability, True, note + FLOOR)
    placed = _items_needed(effect_points, power, ability, min_discrimination)
    if placed is None or (at_ref is not None and placed < at_ref):
        note = (
            f"baseline accuracy {accuracy:.1%} places at ability {ability:+.2f}, where the bank "
            f"asks for {placed if placed is not None else 'no number of'} items; the "
            f"{at_ref} at the reference ability {reference_ability:+.1f} is the larger and holds"
        )
        return PowerLine(effect_points, power, at_ref, reference_ability, False, note + FLOOR)
    note = f"at ability {ability:+.2f}, read from baseline accuracy {accuracy:.1%}"
    return PowerLine(effect_points, power, placed, ability, False, note + FLOOR)


FLOOR = "; a floor, from adaptively chosen bank items"
