"""Sides cut from Part A records, and the A/A study over them, on records built by the test.
The bank is never consulted: `min_items` is set on the spec."""

from __future__ import annotations

import random

from drift.runner.records import CallRecord
from gate import aa, ledger, report
from gate.decision import decide
from gate.outcomes import side_from_records, suite_outcomes
from gate.spec import EvalSpec, Source, SuiteSpec


def record(
    item_id: str,
    *,
    correct: bool | None,
    repeat: int,
    block: str = "closed_form_reasoning",
    held_out: bool = False,
    arm: str = "openweights-control",
    month: str = "2026-09",
    latency: float = 100.0,
    cost: float | None = 0.001,
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
        block=block,
        grader="numeric",
        repeat=repeat,
        held_out=held_out,
        output="x",
        finish_reason="stop" if correct is not None else "max_tokens",
        status=200,
        error_type=None,
        latency_ms=latency,
        input_tokens=1,
        output_tokens=1,
        cost_usd=cost,
        costed=cost is not None,
        ledger_id=repeat,
        request_id=None,
        correct=correct,
        normalised="x",
        detail=None,
    )


SPEC = EvalSpec(
    version=1,
    name="t",
    delta_points=3.0,
    suites=(
        SuiteSpec(key="reason", source=Source(block="closed_form_reasoning"), min_items=10),
        SuiteSpec(
            key="extract_heldout",
            source=Source(block="structured_extraction", held_out=True),
            min_items=10,
        ),
    ),
)


def steady(n: int, repeats: int, *, flaky: int = 0, month: str = "2026-09") -> list[CallRecord]:
    """`n` items right every time except `flaky`, which alternate right and wrong by repeat."""
    out: list[CallRecord] = []
    for i in range(n):
        for k in range(repeats):
            c = (k % 2 == 0) if i < flaky else True
            out.append(record(f"reason-{i:04d}", correct=c, repeat=k, month=month))
    return out


def test_suite_outcomes_reduce_like_the_record_and_filter_by_block() -> None:
    recs = steady(10, 5, flaky=2)
    recs.append(
        record("extract-0001", correct=True, repeat=0, block="structured_extraction", held_out=True)
    )
    recs.append(record("extract-0002", correct=True, repeat=0, block="structured_extraction"))
    reason = suite_outcomes(SPEC.suites[0], recs)
    assert reason.items == 10 and reason.calls == 50
    assert reason.outcomes["reason-0000"] is True, "3 of 5 right is a majority"
    heldout = suite_outcomes(SPEC.suites[1], recs)
    assert set(heldout.outcomes) == {"extract-0001"}, "the public item is another suite"


def test_ungradeable_items_are_absent_not_wrong_and_repeats_can_be_restricted() -> None:
    recs = [record("reason-0000", correct=None, repeat=k) for k in range(3)]
    recs += [record("reason-0001", correct=True, repeat=k) for k in range(3)]
    so = suite_outcomes(SPEC.suites[0], recs)
    assert so.items == 1 and so.ungradeable_items == 1
    two = suite_outcomes(SPEC.suites[0], recs, repeats=(0, 1))
    assert two.calls == 4


def test_uncosted_calls_are_counted_not_priced() -> None:
    recs = [record("reason-0000", correct=True, repeat=0, cost=None)]
    recs += [record("reason-0001", correct=True, repeat=0, cost=0.002)]
    so = suite_outcomes(SPEC.suites[0], recs)
    assert so.uncosted_calls == 1 and so.cost_per_call_usd == 0.002


def test_repeat_splits_are_every_ordered_disjoint_pair() -> None:
    splits = aa.repeat_splits([0, 1, 2, 3, 4], 2)
    assert len(splits) == 30
    assert all(not set(a) & set(b) for a, b in splits)
    assert ((0, 1), (2, 3)) in splits and ((2, 3), (0, 1)) in splits
    assert aa.repeat_splits([0, 1, 2], 2) == []


def test_a_study_on_a_steady_arm_never_blocks_and_the_point_rule_never_fires() -> None:
    recs = {"openweights-control": steady(60, 5)}
    pairs = aa.within_run_pairs(SPEC, recs, month="2026-09", size=2)
    assert len(pairs) == 30
    st = aa.study(SPEC, pairs, with_power=False)
    assert st.n == 30 and st.false_block_rate().point == 0.0 and st.point_rule_rate().point == 0.0
    assert st.blocks_by_arm() == {"openweights-control": (30, 0)}
    text = report.render_aa([("delta 3", st)])
    assert "30 pairs" in text and "0.0% (0.0 to 0.0)" in text


def noisy(n: int, repeats: int, *, p_wrong: float, seed: int) -> list[CallRecord]:
    """Every call independently wrong with probability `p_wrong`: a model that is a little
    unsure of itself, which is what the same-day floor measures on the real panel."""
    rng = random.Random(seed)
    return [
        record(f"reason-{i:04d}", correct=rng.random() >= p_wrong, repeat=k)
        for i in range(n)
        for k in range(repeats)
    ]


def test_a_noisy_arm_shows_the_point_rule_costing_more_than_the_interval_rule() -> None:
    """Nothing changed between the two sides of any pair, only which calls were kept. The
    point rule blocks whenever the candidate's calls happened to land lower, which is about
    half the time. The interval rule blocks less, though not never: two calls per side on a
    model wrong one call in a hundred still leaves a few dozen items disagreeing between the
    sides, and on some splits that lands far enough below zero that a three-point drop cannot
    be ruled out. That is the same thing the real study shows on the open-weights control, and
    it is why the repeat count is a lever B5 names."""
    recs = {"openweights-control": noisy(400, 5, p_wrong=0.005, seed=7)}
    pairs = aa.within_run_pairs(SPEC, recs, month="2026-09", size=2)
    st = aa.study(SPEC, pairs, with_power=False)
    assert st.point_rule_rate().point > 0.3
    assert 0.0 < st.false_block_rate().point < st.point_rule_rate().point


def test_between_run_pairs_go_both_ways_and_only_for_shared_arms() -> None:
    first = {"a": steady(20, 2), "b": steady(20, 2)}
    second = {"a": steady(20, 2, month="2026-09-run2")}
    pairs = aa.between_run_pairs(
        SPEC, first, second, first_month="2026-09", second_month="2026-09-run2"
    )
    assert [p.arm for p in pairs] == ["a", "a"]
    assert pairs[0].baseline.label == "2026-09/a" and pairs[1].baseline.label == "2026-09-run2/a"
    st = aa.study(SPEC, pairs, with_power=False)
    assert st.of_kind("between").n == 2 and st.of_kind("within").n == 0
    assert st.kinds == ("between",)


def test_ledger_records_are_content_addressed_and_append_only(tmp_path: object) -> None:
    from pathlib import Path

    recs = steady(60, 5)
    a = side_from_records(SPEC, recs, label="a", source={"kind": "test", "which": "a"})
    d = decide(SPEC, a, a, with_power=False)
    r1 = ledger.record_for(d, baseline=dict(a.source), candidate=dict(a.source))
    r2 = ledger.record_for(d, baseline=dict(a.source), candidate=dict(a.source))
    assert r1.record_id == r2.record_id, "the same decision is the same record"
    assert r1.passed and r1.spec_hash == SPEC.sha256()
    assert r1.graders_hash and len(r1.suites) == 2
    path = Path(str(tmp_path)) / "ledger.jsonl"
    ledger.append(path, r1)
    r3 = ledger.record_for(
        d, baseline=dict(a.source), candidate=dict(a.source), supersedes=r1.record_id
    )
    assert r3.record_id != r1.record_id
    ledger.append(path, r3)
    back = list(ledger.read(path))
    assert [r.record_id for r in back] == [r1.record_id, r3.record_id]
    assert back[1].supersedes == r1.record_id
    assert path.read_text(encoding="utf-8").count("\n") == 2


def test_rendered_decision_carries_no_bare_percentage_in_its_table() -> None:
    recs = steady(60, 5, flaky=6)
    a = side_from_records(SPEC, recs, label="a", source={"kind": "test"})
    b = side_from_records(SPEC, recs, label="b", source={"kind": "test"}, repeats=(0, 2))
    d = decide(SPEC, a, b, with_power=False)
    for line in report.render_decision(d).splitlines():
        if not line.startswith("| reason"):
            continue
        cells = [c.strip() for c in line.split("|")]
        for cell in cells[3:6]:
            assert "(" in cell, f"bare number in the table: {cell!r}"
