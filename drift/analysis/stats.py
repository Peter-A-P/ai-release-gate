"""Bootstrap intervals and McNemar's test. Plain Python; the inputs are a few hundred items."""

from __future__ import annotations

import math
import random
from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Estimate:
    point: float
    lo: float
    hi: float
    n: int

    def fmt(self, pct: bool = True) -> str:
        if self.n == 0:
            return "n/a"
        if pct:
            return f"{self.point:.1%} ({self.lo:.1%} to {self.hi:.1%}, n = {self.n})"
        return f"{self.point:.3g} ({self.lo:.3g} to {self.hi:.3g}, n = {self.n})"


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
