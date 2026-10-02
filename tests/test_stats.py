"""Bootstrap and McNemar behave on known inputs."""

from __future__ import annotations

import math

from drift.analysis.stats import (
    bootstrap_mean,
    bootstrap_mean_by_cluster,
    mcnemar_exact,
    percentile,
)


def test_bootstrap_mean_brackets_the_point() -> None:
    e = bootstrap_mean([1.0] * 80 + [0.0] * 20, seed=1)
    assert e.point == 0.8 and e.lo <= 0.8 <= e.hi and e.n == 100
    assert 0.7 < e.lo < 0.8 < e.hi < 0.9
    assert "80.0%" in e.fmt()


def test_bootstrap_degenerate() -> None:
    assert bootstrap_mean([]).n == 0 and bootstrap_mean([]).fmt() == "n/a"
    # All ones resamples to all ones. That used to be returned as a zero-width interval, which
    # is a bare number wearing brackets; it is Jeffreys now, and 3 of 3 does not mean certainty.
    e = bootstrap_mean([1.0, 1.0, 1.0])
    assert e.point == e.hi == 1.0 and 0.3 < e.lo < 0.6


def test_a_unanimous_share_never_prints_a_zero_width_interval() -> None:
    zeros = bootstrap_mean([0.0] * 2100)
    assert zeros.lo == 0.0 and 0.0005 < zeros.hi < 0.002
    assert "(0.0 to 0.0)" not in bootstrap_mean([0.0] * 100).compact()
    # 100 answers to 20 questions: the evidence is 20 questions, so the bound is theirs.
    clustered = bootstrap_mean_by_cluster([0.0] * 100, [i // 5 for i in range(100)])
    assert clustered.compact() == "0.0% (0.0 to 11.7)" and clustered.clusters == 20
    # Anything not unanimous is still an ordinary bootstrap.
    mixed = bootstrap_mean([1.0] * 3 + [0.0] * 97, seed=1)
    assert mixed.lo < 0.03 < mixed.hi


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


def test_cluster_bootstrap_keeps_the_point_and_widens_the_interval() -> None:
    """Forty spans from one document are one piece of evidence, not forty. Ten documents,
    each internally unanimous but split five for and five against: the item bootstrap sees 400
    independent coin flips and reports a tight interval around 50%; the cluster bootstrap sees
    ten and does not."""
    values = [float(d % 2) for d in range(10) for _ in range(40)]
    clusters = [d for d in range(10) for _ in range(40)]
    item = bootstrap_mean(values, seed=1)
    cluster = bootstrap_mean_by_cluster(values, clusters, seed=1)
    assert item.point == cluster.point == 0.5
    assert cluster.n == 400 and cluster.clusters == 10
    assert (cluster.hi - cluster.lo) > 3 * (item.hi - item.lo)
    assert cluster.lo <= 0.5 <= cluster.hi
    assert "in 10 clusters" in cluster.fmt()


def test_cluster_bootstrap_weights_by_cluster_size() -> None:
    """The point is the mean over values, so a big cluster counts for more than a small one,
    and the resamples are weighted the same way rather than averaging cluster means."""
    values = [1.0] * 90 + [0.0] * 10
    clusters = ["big"] * 90 + ["small"] * 10
    e = bootstrap_mean_by_cluster(values, clusters, seed=0)
    assert e.point == 0.9
    # Two clusters, so a resample is one of {big,big}, {big,small}, {small,big}, {small,small}
    # with means 1.0, 0.9, 0.9, 0.0: the interval ends land on those values.
    assert e.lo in (0.0, 0.9) and e.hi in (0.9, 1.0)


def test_cluster_bootstrap_with_one_cluster_has_no_interval() -> None:
    e = bootstrap_mean_by_cluster([1.0, 0.0, 1.0, 1.0], ["doc"] * 4)
    assert e.point == 0.75 and e.n == 4 and e.clusters == 1
    assert e.interval_undefined and math.isnan(e.lo) and math.isnan(e.hi)
    assert "interval undefined" in e.fmt() and "interval undefined" in e.compact()
    assert "%" not in e.fmt().split("(")[1], "no fabricated bounds after the point"


def test_cluster_bootstrap_degenerate_and_mismatched() -> None:
    empty = bootstrap_mean_by_cluster([], [])
    assert empty.n == 0 and empty.fmt() == "n/a"
    try:
        bootstrap_mean_by_cluster([1.0, 0.0], ["a"])
    except ValueError as err:
        assert "2 values" in str(err)
    else:
        raise AssertionError("mismatched lengths must be refused")


def test_plain_estimate_is_unchanged_by_the_cluster_field() -> None:
    e = bootstrap_mean([1.0] * 80 + [0.0] * 20, seed=1)
    assert e.clusters is None and not e.interval_undefined
    assert e.fmt().endswith("n = 100)")


def test_a_change_with_no_flips_still_has_an_interval_either_side_of_zero() -> None:
    from drift.analysis.stats import paired_change

    e = paired_change(0, 0, 420)
    assert e.point == 0.0 and e.lo < 0.0 < e.hi, "never a bare zero wearing brackets"
    worse = paired_change(10, 0, 420)
    assert worse.point < 0 and worse.hi < 0.0 + 1e-9


def test_a_difference_of_two_small_shares_is_wide() -> None:
    from drift.analysis.stats import difference_of_shares

    e = difference_of_shares([1.0] * 18 + [0.0] * 2, [1.0] * 15 + [0.0] * 5)
    assert math.isclose(e.point, 0.15) and e.lo < 0.0 < e.hi and e.n == 20
    same = difference_of_shares([1.0] * 20, [1.0] * 20)
    assert same.point == 0.0 and same.lo < 0.0 < same.hi


def test_the_detectable_change_grows_with_noise_and_shrinks_with_items() -> None:
    from drift.analysis.stats import detectable_change

    assert detectable_change(420, 0.01) < detectable_change(420, 0.05)
    assert detectable_change(1000, 0.03) < detectable_change(420, 0.03)
    # PLAN.md section 4's order of magnitude: about three points on 420 items at a 2% floor.
    assert 0.025 < detectable_change(420, 0.02) < 0.035
