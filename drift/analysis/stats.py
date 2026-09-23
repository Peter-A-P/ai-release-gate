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

    def compact(self) -> str:
        """The same interval, short enough for a seven-column table to stay readable.

        The README table repeats a column's `n` on every row, where it is the same number
        every time; it is stated once beneath the table instead. Dropping it is the
        difference between a cell that reads and a cell that wraps. Never drops the
        interval itself: a bare percentage is a bug.
        """
        if self.n == 0:
            return "n/a"
        if self.interval_undefined:
            return f"{self.point:.1%} (interval undefined: one cluster)"
        return f"{self.point:.1%} ({self.lo * 100:.1f} to {self.hi * 100:.1f})"


def bootstrap_mean(values: Sequence[float], *, resamples: int = 2000, seed: int = 0) -> Estimate:
    """Percentile bootstrap of the mean over items. Never a bare percentage."""
    n = len(values)
    if n == 0:
        return Estimate(float("nan"), float("nan"), float("nan"), 0)
    point = sum(values) / n
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
