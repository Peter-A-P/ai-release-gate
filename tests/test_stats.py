"""Bootstrap and McNemar behave on known inputs."""

from __future__ import annotations

import math

from drift.analysis.stats import bootstrap_mean, mcnemar_exact, percentile


def test_bootstrap_mean_brackets_the_point() -> None:
    e = bootstrap_mean([1.0] * 80 + [0.0] * 20, seed=1)
    assert e.point == 0.8 and e.lo <= 0.8 <= e.hi and e.n == 100
    assert 0.7 < e.lo < 0.8 < e.hi < 0.9
    assert "80.0%" in e.fmt()


def test_bootstrap_degenerate() -> None:
    assert bootstrap_mean([]).n == 0 and bootstrap_mean([]).fmt() == "n/a"
    e = bootstrap_mean([1.0, 1.0, 1.0])
    assert e.point == e.lo == e.hi == 1.0


def test_mcnemar_exact_known_values() -> None:
    assert mcnemar_exact(0, 0) == 1.0
    assert mcnemar_exact(5, 5) == 1.0
    # 10 discordant pairs all one way: two-sided p = 2 * (1/2)^10
    assert math.isclose(mcnemar_exact(10, 0), 2 / 1024)
    assert mcnemar_exact(8, 2) > mcnemar_exact(10, 0)


def test_percentile() -> None:
    assert percentile([5, 1, 3], 0.5) == 3
    assert percentile([1, 2, 3, 4], 0.95) == 4
    assert math.isnan(percentile([], 0.5))
