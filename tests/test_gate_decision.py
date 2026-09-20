"""The gate's verdict on sides built by the test. `min_items` is set on every suite so no test
here consults the bank; the power path has its own tests."""

from __future__ import annotations

from collections.abc import Mapping

from gate.decision import decide
from gate.outcomes import Side, SuiteOutcomes
from gate.spec import EvalSpec, Source, SuiteSpec


def spec(**overrides: object) -> EvalSpec:
    base: dict[str, object] = {
        "version": 1,
        "name": "test",
        "delta_points": 3.0,
        "suites": (
            SuiteSpec(key="alpha", source=Source(block="a"), min_items=10),
            SuiteSpec(key="beta", source=Source(block="b"), min_items=10),
        ),
    }
    base.update(overrides)
    return EvalSpec.model_validate(base)


def suite(
    key: str,
    outcomes: Mapping[str, bool],
    *,
    latency: float = 100.0,
    cost: float = 0.001,
    calls: int | None = None,
) -> SuiteOutcomes:
    n = calls if calls is not None else len(outcomes)
    return SuiteOutcomes(
        suite=key,
        outcomes=dict(outcomes),
        ungradeable_items=0,
        calls=n,
        latency_p50_ms=latency,
        cost_usd=cost * n,
        uncosted_calls=0,
    )


def side(label: str, **suites: SuiteOutcomes) -> Side:
    return Side(label=label, source={"kind": "test", "label": label}, suites=suites)


def all_right(n: int) -> dict[str, bool]:
    return {f"i{k}": True for k in range(n)}


def test_identical_sides_pass_with_a_reason_for_every_suite() -> None:
    a = side("a", alpha=suite("alpha", all_right(50)), beta=suite("beta", all_right(50)))
    d = decide(spec(), a, a)
    assert d.passed and not d.blocked
    assert all(s.verdict == "pass" for s in d.suites)
    assert d.reasons[0].startswith("pass: 2 of 2 suites decided")
    assert all("non-inferior" in s.reasons[0] for s in d.suites)


def test_a_real_regression_blocks_and_names_the_suite() -> None:
    a = side("a", alpha=suite("alpha", all_right(200)), beta=suite("beta", all_right(50)))
    worse = {f"i{k}": k >= 40 for k in range(200)}  # 20 points down on alpha
    b = side("b", alpha=suite("alpha", worse), beta=suite("beta", all_right(50)))
    d = decide(spec(), a, b)
    assert d.blocked
    alpha = d.suites[0]
    assert alpha.verdict == "block" and d.suites[1].verdict == "pass"
    assert d.reasons[0].startswith("alpha: cannot rule out a 3% drop")
    assert "40 worse and 0 better" in d.reasons[0]


def test_under_powered_suites_warn_and_are_not_in_the_holm_family() -> None:
    a = side("a", alpha=suite("alpha", all_right(50)), beta=suite("beta", all_right(4)))
    dropped = {"i0": False, "i1": False, "i2": True, "i3": True}  # beta halves, on 4 items
    b = side("b", alpha=suite("alpha", all_right(50)), beta=suite("beta", dropped))
    d = decide(spec(), a, b)
    assert d.passed, "a suite too small to see the margin cannot block"
    beta = d.suites[1]
    assert beta.verdict == "warn" and beta.under_powered and beta.p_adjusted is None
    assert "under-powered" in beta.reasons[0]
    assert d.suites[0].p_adjusted == d.suites[0].test.p_inferior, (
        "Holm over one suite is that suite"
    )
    assert any(r.startswith("under-powered, not decided: beta") for r in d.reasons)


def test_holm_makes_the_second_suite_harder_to_pass() -> None:
    """Two suites, each on its own comfortably non-inferior but not overwhelmingly so. Holm
    doubles the smaller p and the larger one is raised to meet it."""
    n = 120
    a = side("a", alpha=suite("alpha", all_right(n)), beta=suite("beta", all_right(n)))
    wobble = {f"i{k}": k >= 1 for k in range(n)}
    b = side("b", alpha=suite("alpha", wobble), beta=suite("beta", wobble))
    d = decide(spec(), a, b)
    for s in d.suites:
        assert s.p_adjusted is not None
        assert s.p_adjusted >= s.test.p_inferior
    assert d.suites[0].p_adjusted == d.suites[1].p_adjusted


def test_the_point_rule_blocks_where_the_interval_rule_does_not() -> None:
    """B13 candidate 2, computed alongside so the A/A study can price it."""
    n = 400
    a = side("a", alpha=suite("alpha", all_right(n)), beta=suite("beta", all_right(n)))
    one_down = {f"i{k}": k >= 1 for k in range(n)}
    b = side("b", alpha=suite("alpha", one_down), beta=suite("beta", all_right(n)))
    d = decide(spec(), a, b)
    assert d.passed and d.point_rule_blocks
    assert d.suites[0].point_rule_blocks and not d.suites[1].point_rule_blocks


def test_latency_and_cost_lines_block_on_their_own_and_say_so() -> None:
    a = side(
        "a",
        alpha=suite("alpha", all_right(50), latency=100.0, cost=0.001),
        beta=suite("beta", all_right(50), latency=100.0, cost=0.001),
    )
    b = side(
        "b",
        alpha=suite("alpha", all_right(50), latency=250.0, cost=0.001),
        beta=suite("beta", all_right(50), latency=250.0, cost=0.001),
    )
    from gate.spec import Threshold

    s = spec(latency=Threshold(max_increase_pct=50), cost=Threshold(max_increase_pct=50))
    d = decide(s, a, b)
    assert d.blocked
    assert all(su.verdict == "pass" for su in d.suites), "accuracy is fine; the block is latency"
    assert [ln.verdict for ln in d.lines] == ["block", "pass"]
    assert "latency p50: 250 ms against 100 ms, up 150%" in d.reasons[0]
    assert "US$0.00100 against US$0.00100" in d.lines[1].reason


def test_a_line_not_measured_on_both_sides_warns_rather_than_guessing() -> None:
    from gate.spec import Threshold

    a = side(
        "a",
        alpha=suite("alpha", all_right(50), calls=0),
        beta=suite("beta", all_right(50), calls=0),
    )
    d = decide(spec(cost=Threshold(max_increase_pct=50)), a, a)
    assert d.passed and d.lines[0].verdict == "warn"


def test_nothing_in_common_is_not_decided() -> None:
    a = side("a", alpha=suite("alpha", {"x": True}), beta=suite("beta", all_right(50)))
    b = side("b", alpha=suite("alpha", {"y": True}), beta=suite("beta", all_right(50)))
    d = decide(spec(), a, b)
    assert d.passed and d.suites[0].verdict == "warn"
    assert d.suites[0].reasons[0] == "no item was graded on both sides"


def test_the_corrected_interval_is_shown_but_does_not_decide_unless_asked() -> None:
    """Needs the bank. gsm8k items carry a heavy correction; with it deciding, a difference the
    plain interval clears comfortably can no longer be told from a three-point drop."""
    n = 400
    plain = SuiteSpec(key="alpha", source=Source(block="a"), min_items=10, benchmark="gsm8k")
    strict = plain.model_copy(update={"correct_for_dependence": True})
    a = side("a", alpha=suite("alpha", all_right(n)))
    b = side("b", alpha=suite("alpha", {f"i{k}": k >= 2 for k in range(n)}))
    shown = decide(spec(suites=(plain,)), a, b)
    used = decide(spec(suites=(strict,)), a, b)
    r_shown, r_used = shown.suites[0], used.suites[0]
    assert r_shown.corrected is not None and not r_shown.decides_on_corrected
    assert r_shown.verdict == "pass" and shown.passed
    assert r_used.decides_on_corrected and r_used.verdict == "block"
    assert r_used.corrected is not None and 8 < r_used.corrected.effective_items < 14
    assert any("shown, not used" in r for r in r_shown.reasons)
    assert any(" decides" in r for r in r_used.reasons)
