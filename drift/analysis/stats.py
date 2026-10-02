"""Bootstrap intervals and McNemar's test. Plain Python; the inputs are a few hundred items."""

from __future__ import annotations

import math
import random
from collections.abc import Hashable, Sequence
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Estimate:
    point: float
    lo: float
    hi: float
    n: int
    # How many independent units the interval was resampled over, when that is not `n`.
    # Set by `bootstrap_mean_by_cluster`; None for a plain item-level bootstrap.
    clusters: int | None = None

    @property
    def interval_undefined(self) -> bool:
        """A point with no interval: every value came from one cluster, so there is nothing
        to resample. Printed as such rather than as a fabricated zero-width interval, which
        is a bare number wearing brackets."""
        return self.n > 0 and math.isnan(self.lo)

    def _units(self) -> str:
        if self.clusters is None:
            return f"n = {self.n}"
        return f"n = {self.n} in {self.clusters} clusters"

    def fmt(self, pct: bool = True) -> str:
        if self.n == 0:
            return "n/a"
        point = f"{self.point:.1%}" if pct else f"{self.point:.3g}"
        if self.interval_undefined:
            return f"{point} (interval undefined: one cluster, {self._units()})"
        if pct:
            return f"{point} ({self.lo:.1%} to {self.hi:.1%}, {self._units()})"
        return f"{point} ({self.lo:.3g} to {self.hi:.3g}, {self._units()})"

    def compact(self, pct: bool = True) -> str:
        """The same interval, short enough for a seven-column table to stay readable.

        The README table repeats a column's `n` on every row, where it is the same number
        every time; it is stated once beneath the table instead. Dropping it is the
        difference between a cell that reads and a cell that wraps. Never drops the
        interval itself: a bare percentage is a bug.
        """
        if self.n == 0:
            return "n/a"
        if not pct:
            # For a statistic that is not a share, kappa and alpha, printed as the calibration
            # reports print it. The dashboard showed kappa 0.924 as "92.4%" until 2026-09-29.
            if self.interval_undefined:
                return f"{self.point:.3f} (interval undefined: one cluster)"
            return f"{self.point:.3f} ({self.lo:.3f} to {self.hi:.3f})"
        if self.interval_undefined:
            return f"{self.point:.1%} (interval undefined: one cluster)"
        return f"{self.point:.1%} ({self.lo * 100:.1f} to {self.hi * 100:.1f})"


def _unanimous(values: Sequence[float]) -> bool:
    """Every value 0, or every value 1: a share with nothing in it to resample."""
    return all(v == 0.0 for v in values) or all(v == 1.0 for v in values)


def bootstrap_mean(values: Sequence[float], *, resamples: int = 2000, seed: int = 0) -> Estimate:
    """Percentile bootstrap of the mean over items. Never a bare percentage.

    Except where a bootstrap cannot give one: a share whose values are all 0 or all 1 resamples
    to itself and would print "0.0% (0.0 to 0.0)", a bare number wearing an interval. Until
    2026-09-27 it did, in every published report: the error, truncation and "wrongly refused"
    columns of most arms, and per-block accuracy wherever a model scored 100%. Such a share gets
    the Jeffreys interval instead (`jeffreys_proportion`), with the point unchanged.
    """
    n = len(values)
    if n == 0:
        return Estimate(float("nan"), float("nan"), float("nan"), 0)
    point = sum(values) / n
    if _unanimous(values):
        j = jeffreys_proportion(round(point * n), n, seed=seed)
        return Estimate(point, j.lo, j.hi, n)
    rng = random.Random(seed)
    means = sorted(sum(values[rng.randrange(n)] for _ in range(n)) / n for _ in range(resamples))
    lo = means[int(0.025 * resamples)]
    hi = means[min(resamples - 1, int(0.975 * resamples))]
    return Estimate(point, lo, hi, n)


def jeffreys_proportion(successes: int, n: int, *, draws: int = 20000, seed: int = 0) -> Estimate:
    """A share of `n` independent yes/no items, with the Jeffreys interval.

    For a share that can come out at none or all of its items, where `bootstrap_mean` cannot
    be used: resampling fifty identical zeros reproduces them exactly and prints
    "0.0% (0.0% to 0.0%)", a bare number wearing an interval, when 0 of 50 plainly does not
    mean the rate is exactly zero. The refusal classifier's error rate hit this first and
    `drift.labelling` draws from the same Beta(x + 0.5, n - x + 0.5) posterior. The bound on
    the side of an observed 0 or n is pinned at 0 or 1, the usual Jeffreys convention.
    """
    if n == 0:
        return Estimate(float("nan"), float("nan"), float("nan"), 0)
    if not 0 <= successes <= n:
        raise ValueError(f"{successes} successes out of {n}")
    rng = random.Random(seed)
    sample = sorted(rng.betavariate(successes + 0.5, n - successes + 0.5) for _ in range(draws))
    lo = 0.0 if successes == 0 else sample[int(0.025 * draws)]
    hi = 1.0 if successes == n else sample[min(draws - 1, int(0.975 * draws))]
    return Estimate(successes / n, lo, hi, n)


def bootstrap_mean_by_cluster(
    values: Sequence[float],
    clusters: Sequence[Hashable],
    *,
    resamples: int = 2000,
    seed: int = 0,
) -> Estimate:
    """Percentile bootstrap resampling whole clusters, for values that are not independent.

    `clusters[i]` names the unit `values[i]` belongs to: the document a labelled span came
    from, the passage a recall question was planted in, the parent problem a paraphrase
    rephrases. Resampling items one at a time treats every value as fresh evidence, and when
    one document yields forty spans that is forty votes for one fact, so the interval comes
    out far too narrow. Here each resample draws clusters with replacement and takes the mean
    over every value the drawn clusters hold, weighted by size exactly as the point estimate is.

    The point is the plain mean over all values, the same number `bootstrap_mean` gives. Only
    the interval changes. With a single cluster there is nothing to resample and the interval
    is undefined, reported as such; fabricating a zero-width one would be a bare number in
    brackets.

    Written for project 07, whose units are spans within documents, from its description and
    not from its code. 07 then ran both against its real scored corpus on 2026-09-19: identical
    points on four metrics and bounds within 0.13 points, which is the Monte Carlo gap between
    two generators at 2,000 resamples. Both had chosen the size-weighted mean independently. 07
    keeps its own copy, because its CI deliberately installs nothing that can reach a network,
    so this one's callers are here: recall questions share a passage and paraphrases a parent.
    """
    if len(values) != len(clusters):
        raise ValueError(f"{len(values)} values but {len(clusters)} cluster labels")
    n = len(values)
    if n == 0:
        return Estimate(float("nan"), float("nan"), float("nan"), 0, 0)
    point = sum(values) / n
    groups: dict[Hashable, list[float]] = {}
    for v, c in zip(values, clusters, strict=True):
        groups.setdefault(c, []).append(v)
    members = list(groups.values())
    k = len(members)
    if k == 1:
        return Estimate(point, float("nan"), float("nan"), n, 1)
    if _unanimous(values):
        # Nothing to resample, as in `bootstrap_mean`, and the evidence is k clusters, not n
        # values: 0 refusals in 100 answers to 20 questions is 20 questions' worth of "low".
        j = jeffreys_proportion(0 if point == 0.0 else k, k, seed=seed)
        return Estimate(point, j.lo, j.hi, n, k)
    totals = [(sum(g), len(g)) for g in members]
    rng = random.Random(seed)
    means: list[float] = []
    for _ in range(resamples):
        drawn = [totals[rng.randrange(k)] for _ in range(k)]
        means.append(sum(t for t, _ in drawn) / sum(c for _, c in drawn))
    means.sort()
    lo = means[int(0.025 * resamples)]
    hi = means[min(resamples - 1, int(0.975 * resamples))]
    return Estimate(point, lo, hi, n, k)


def percentile(values: Sequence[float], q: float) -> float:
    if not values:
        return float("nan")
    s = sorted(values)
    return s[min(len(s) - 1, round(q * (len(s) - 1)))]


def mcnemar_exact(b: int, c: int) -> float:
    """Two-sided exact McNemar p-value from the discordant counts.

    b: correct last month, incorrect this month. c: the reverse. Under no change the
    discordant pairs split 50/50; the p-value is the two-sided binomial tail.
    """
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    tail = sum(math.comb(n, i) for i in range(k + 1)) / float(2**n)
    return float(min(1.0, 2 * tail))


def _share_draw(rng: random.Random, k: int, n: int) -> float:
    """One draw of a share of k in n: the observed share, or a Jeffreys draw when k is 0 or n,
    so a count of none is never taken as a certainty of none."""
    if k in (0, n):
        return rng.betavariate(k + 0.5, n - k + 0.5)
    return k / n


def paired_change(
    worse: int, better: int, n: int, *, resamples: int = 2000, seed: int = 0
) -> Estimate:
    """The change in accuracy between two runs of the same items, (better - worse) / n, with a
    bootstrap interval over items.

    Paired: each item is -1, 0 or +1, so a resample of n items is a multinomial count of the
    three, drawn here as two binomials. A count of 0 is drawn from its Jeffreys posterior
    rather than held at 0, or two runs that agreed on every item would print "+0.0% (+0.0 to
    +0.0)", a bare number wearing an interval. Until 2026-10-02 the report printed this change
    as a bare number with no interval at all.
    """
    if n == 0:
        nan = float("nan")
        return Estimate(nan, nan, nan, 0)
    point = (better - worse) / n
    rng = random.Random(seed)
    draws = []
    for _ in range(resamples):
        w = rng.binomialvariate(n, _share_draw(rng, worse, n))
        rest = n - w
        b = rng.binomialvariate(rest, _share_draw(rng, better, n - worse)) if rest else 0
        draws.append((b - w) / n)
    draws.sort()
    return Estimate(
        point, draws[int(0.025 * resamples)], draws[min(resamples - 1, int(0.975 * resamples))], n
    )


def difference_of_shares(
    a: Sequence[float], b: Sequence[float], *, resamples: int = 2000, seed: int = 0
) -> Estimate:
    """mean(a) - mean(b) for two independent sets of 0/1 items, with a bootstrap interval that
    resamples each set on its own. A set that is all 0 or all 1 is drawn from its Jeffreys
    posterior instead, for the reason `bootstrap_mean` gives. `n` is the smaller set, which is
    what limits the interval."""
    if not a or not b:
        nan = float("nan")
        return Estimate(nan, nan, nan, 0)
    rng = random.Random(seed)

    def draw(values: Sequence[float]) -> float:
        n = len(values)
        if _unanimous(values):
            return _share_draw(rng, round(sum(values)), n)
        return sum(values[rng.randrange(n)] for _ in range(n)) / n

    point = sum(a) / len(a) - sum(b) / len(b)
    draws = sorted(draw(a) - draw(b) for _ in range(resamples))
    return Estimate(
        point,
        draws[int(0.025 * resamples)],
        draws[min(resamples - 1, int(0.975 * resamples))],
        min(len(a), len(b)),
    )


Z_TWO_SIDED_05 = 1.959964
Z_POWER_80 = 0.841621


def detectable_change(n: int, discordance: float) -> float:
    """The smallest accuracy change a paired test on `n` items can see at 80% power, two-sided
    at 5%, when `discordance` of items already disagree between two runs with nothing changed.

    The paired (McNemar) normal approximation: n d^2 = (z_a sqrt(psi) + z_b sqrt(psi - d^2))^2,
    where psi is the share of discordant items under the change. A real change of d moves d of
    the items one way on top of the noise, so psi = discordance + d. Solved for d by bisection.
    PLAN.md section 4 asks for this figure from the observed same-day disagreement; the
    same-day flip rate counts an item as discordant if any of its repeats disagreed, which is
    more than two single runs disagree, so the figure errs large.
    """
    if n <= 0 or math.isnan(discordance):
        return float("nan")

    def gap(d: float) -> float:
        psi = min(1.0, discordance + d)
        return (
            n * d * d
            - (Z_TWO_SIDED_05 * math.sqrt(psi) + Z_POWER_80 * math.sqrt(max(psi - d * d, 0.0))) ** 2
        )

    lo, hi = 1e-9, 1.0
    if gap(hi) < 0:
        return float("nan")
    for _ in range(80):
        mid = (lo + hi) / 2
        if gap(mid) < 0:
            lo = mid
        else:
            hi = mid
    return hi
