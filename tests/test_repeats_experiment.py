"""Rule C candidate 3: k = 1, no repeats. Offline, on records built by the test, so every
number the module reports can be checked against an answer known in advance.

The arm these tests lean on is a control: something whose verdicts are laid down by the test
and therefore cannot have changed between the two runs. Any drift a rule declares on it is a
false positive by construction, which is the whole argument.
"""

from __future__ import annotations

from drift.analysis.stats import Estimate
from drift.experiments.repeats import (
    ArmRepeats,
    RepeatsReport,
    accuracy_spread,
    analyse,
    grades,
    majority_outcomes,
    render,
    repeats_in,
    single_draw_outcomes,
)
from drift.runner.records import CallRecord


def record(
    item_id: str,
    *,
    correct: bool | None,
    repeat: int,
    arm: str = "openweights-control",
    month: str = "2026-09",
    finish_reason: str | None = "stop",
) -> CallRecord:
    return CallRecord(
        ts_utc="2026-09-13T06:00:00Z",
        run_id=f"drift-{month}",
        month=month,
        arm_key=arm,
        provider="openweights",
        model_requested="openweights/fixed",
        model_returned="fixed",
        item_id=item_id,
        block="closed_form_reasoning",
        grader="numeric",
        repeat=repeat,
        held_out=False,
        output="x",
        finish_reason=finish_reason,
        status=200,
        error_type=None,
        latency_ms=1.0,
        input_tokens=1,
        output_tokens=1,
        cost_usd=0.0,
        costed=True,
        ledger_id=repeat,
        request_id=None,
        correct=correct,
        normalised="x",
        detail=None,
    )


def run(verdicts: dict[str, list[bool | None]], month: str) -> list[CallRecord]:
    """One arm's records: item id -> the verdict of each repeat, in order."""
    return [
        record(item_id, correct=c, repeat=i, month=month)
        for item_id, per_repeat in verdicts.items()
        for i, c in enumerate(per_repeat)
    ]


def steady(n: int, repeats: int, *, flaky: int = 0) -> dict[str, list[bool | None]]:
    """`n` items answered correctly every time, except `flaky` of them which alternate:
    self-contradiction inside one sitting, which is exactly what the floor measures."""
    out: dict[str, list[bool | None]] = {}
    for i in range(n):
        if i < flaky:
            out[f"item-{i:03d}"] = [j % 2 == 0 for j in range(repeats)]
        else:
            out[f"item-{i:03d}"] = [True] * repeats
    return out


def test_a_single_draw_leaves_no_floor_to_clear() -> None:
    """The heart of it: a floor needs two calls on one item, so k = 1 has none. Not a noisier
    floor, no floor, and the published rule refuses rather than guessing one."""
    verdicts = steady(60, 5, flaky=12)
    report = analyse(
        {"openweights-control": run(verdicts, "2026-09")},
        {"openweights-control": run(verdicts, "2026-09-run2")},
        month="2026-09-run2",
        baseline_month="2026-09",
        control_key="openweights-control",
    )
    arm = report.arms[0]
    assert arm.k5_floor.n == 60, "five repeats give every item a floor"
    assert arm.k1_floor.n == 0, "one call per item can contribute no flip at all"
    assert arm.k1_published_rule_declared is False
    assert report.arms_without_a_floor == 1
    assert report.k1_published_rule_declared == 0


def test_k1_declares_drift_on_an_arm_that_cannot_have_changed() -> None:
    """The false positive, on a control whose verdicts the test fixes. Both runs hold the
    identical pattern, so the only thing that differs between two single draws is which call
    was kept."""
    verdicts = steady(200, 5, flaky=60)
    report = analyse(
        {"openweights-control": run(verdicts, "2026-09")},
        {"openweights-control": run(verdicts, "2026-09-run2")},
        month="2026-09-run2",
        baseline_month="2026-09",
        control_key="openweights-control",
    )
    arm = report.arms[0]
    assert arm.k5_declared is False, "the published rule holds its nerve"
    assert arm.k1_flagged > 0, "k = 1 calls drift on a model that cannot have drifted"
    assert report.rejected is True
    assert "Rejected" in render(report)


def test_the_verdict_can_come_out_the_other_way() -> None:
    """Rule C is worth nothing if the answer was written in advance. Given a record where no
    single draw disagrees with another, the module says the approach was not rejected.

    The missing floor deliberately does not enter this verdict: it is true of every k = 1
    record ever, so a verdict counting it could not fail, and a Rule C item that cannot fail
    proves nothing."""
    verdicts = steady(40, 5)  # nothing flaky, so no draw can differ from any other
    report = analyse(
        {"openweights-control": run(verdicts, "2026-09")},
        {"openweights-control": run(verdicts, "2026-09-run2")},
        month="2026-09-run2",
        baseline_month="2026-09",
        control_key="openweights-control",
    )
    assert report.arms[0].k1_flagged == 0
    assert report.arms_without_a_floor == 1, "no floor, yet the verdict is still open"
    assert report.rejected is False
    assert "Not rejected" in render(report)


def test_the_control_is_named_in_the_verdict_because_it_carries_the_argument() -> None:
    report = analyse(
        {"openweights-control": run(steady(200, 5, flaky=60), "2026-09")},
        {"openweights-control": run(steady(200, 5, flaky=60), "2026-09-run2")},
        month="2026-09-run2",
        baseline_month="2026-09",
        control_key="openweights-control",
    )
    text = render(report)
    assert "openweights-control" in text
    assert "false by construction" in text


def test_no_share_is_reported_without_an_interval() -> None:
    """The record's own rule (CLAUDE.md): a bare percentage is a bug. Every percentage in the
    rendered table carries its interval, including the median draw."""
    report = analyse(
        {"openweights-control": run(steady(100, 5, flaky=30), "2026-09")},
        {"openweights-control": run(steady(100, 5, flaky=30), "2026-09-run2")},
        month="2026-09-run2",
        baseline_month="2026-09",
        control_key="openweights-control",
    )
    for line in render(report).splitlines():
        if not line.startswith("| openweights-control"):
            continue
        for cell in [c.strip() for c in line.split("|")]:
            if cell.endswith("%"):
                raise AssertionError(f"bare percentage in the table: {cell!r}")


def test_the_median_draw_is_a_draw_that_happened() -> None:
    """With an even number of pairings the median is the lower middle draw, not an average of
    two: an averaged point would carry an interval belonging to neither."""
    flips = tuple(Estimate(p, p - 0.01, p + 0.01, 10) for p in (0.01, 0.02, 0.03, 0.04))
    arm = ArmRepeats(
        arm_key="a",
        is_control=False,
        paired_items=10,
        k5_floor=flips[0],
        k5_flip=flips[0],
        k5_declared=False,
        k1_flips=flips,
        k1_flagged=0,
        k1_floor=flips[0],
        k1_published_rule_declared=False,
    )
    assert arm.k1_median_flip in flips
    assert arm.k1_median_flip.point == 0.02


def test_an_ungradeable_call_is_absent_rather_than_counted_wrong() -> None:
    """An error or a truncation is not evidence about the model, and a single draw that lands
    on one has no verdict at all: it drops out of that draw instead of scoring zero."""
    verdicts: dict[str, list[bool | None]] = {
        "item-000": [True, True, None],
        "item-001": [True, True, True],
    }
    g = grades(run(verdicts, "2026-09"))
    assert repeats_in(g) == 3
    assert single_draw_outcomes(g, 2) == {"item-001": True}, "the errored call is not there"
    assert majority_outcomes(g) == {"item-000": True, "item-001": True}


def test_a_tie_counts_as_incorrect_like_the_record_does() -> None:
    g = grades(run({"item-000": [True, False]}, "2026-09"))
    assert majority_outcomes(g) == {"item-000": False}


def test_the_score_barely_moves_which_is_why_the_idea_is_tempting() -> None:
    """The honest half of the finding: k = 1 does not wreck the accuracy, so the rejection
    cannot rest on that. `accuracy_spread` is what keeps the doc from overclaiming."""
    records = run(steady(100, 5, flaky=20), "2026-09")
    k5, low, high = accuracy_spread(records)
    assert k5 == 1.0, "the majority over five repeats calls every flaky item correct"
    assert high - low <= 0.2, "a single draw moves the score, but not by much"


def test_an_empty_report_says_nothing_rather_than_dividing_by_zero() -> None:
    report = RepeatsReport(month="m", baseline="b", repeats=0, arms=())
    assert report.pairings == 0
    assert report.k1_flagged_worst == 0
    assert report.rejected is False
