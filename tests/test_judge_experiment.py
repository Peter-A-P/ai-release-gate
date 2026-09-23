"""Rule C candidate 1: the judge harness. Offline, with a fake judge whose behaviour is
dialled in by the test, so the statistics can be checked against a known answer."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from drift.experiments.judge import (
    CORRECT,
    INCORRECT,
    JudgeConfig,
    JudgeVerdict,
    analyse,
    judge_prompt,
    majority,
    out_dir_for,
    parse_verdict,
    read_verdicts,
    render,
    render_expected,
    run,
    select,
    selectable,
    write_report,
)
from drift.items import Item
from drift.runner.records import CallRecord
from drift.suite import Suite

from .conftest import make_items


def record(item: Item, *, output: str | None, correct: bool | None, repeat: int = 0) -> CallRecord:
    return CallRecord(
        ts_utc="2026-09-27T06:00:00Z",
        run_id="drift-2026-09",
        month="2026-09",
        arm_key="anthropic-snapshot",
        provider="anthropic",
        model_requested="anthropic/x",
        model_returned="x",
        item_id=item.id,
        block=item.block,
        grader=item.grader,
        repeat=repeat,
        held_out=False,
        output=output,
        finish_reason="stop",
        status=200,
        error_type=None,
        latency_ms=100.0,
        input_tokens=10,
        output_tokens=5,
        cost_usd=0.0001,
        costed=True,
        ledger_id=1,
        request_id="r",
        correct=correct,
        normalised=(output or "").casefold(),
        detail="",
    )


# --- the prompt -----------------------------------------------------------------------------


def test_the_judge_is_given_the_reference_which_is_the_fair_version_of_the_idea() -> None:
    """Rule C is worth nothing against a straw man, so the judge gets what a real harness
    would give it: the question, the reference answer and the answer to grade."""
    item = make_items()[3]  # a numeric reasoning item
    text = judge_prompt(item, "the answer is 6")
    assert item.prompt in text
    assert "6" in render_expected(item)
    assert "the answer is 6" in text
    assert CORRECT in text and INCORRECT in text


@pytest.mark.parametrize(
    ("grader", "expected", "must_contain"),
    [
        ("numeric", {"value": 42}, "42"),
        ("letter", {"letter": "c"}, "C"),
        ("exact", {"answer": "Bramblewick"}, "Bramblewick"),
        ("must_refuse", {}, "declines"),
        ("must_answer", {"keywords_any": ["toxic"]}, "toxic"),
        (
            "json_schema_exact",
            {"schema": {"type": "object"}, "values": {"year": 1902}},
            '"year": 1902',
        ),
    ],
)
def test_every_grader_renders_a_reference_a_judge_could_use(
    grader: str, expected: Any, must_contain: str
) -> None:
    item = make_items()[0].model_copy(update={"grader": grader, "expected": expected})
    assert must_contain in render_expected(item)


def test_constraints_render_as_the_rules_the_checker_applies() -> None:
    item = make_items()[0].model_copy(
        update={
            "grader": "constraints",
            "expected": {"constraints": [{"type": "max_words", "n": 40}]},
        }
    )
    rendered = render_expected(item)
    assert "40 words" in rendered and "preamble" in rendered


# --- reading the verdict ----------------------------------------------------------------------


def test_incorrect_is_not_read_as_correct() -> None:
    """INCORRECT contains CORRECT. Getting this wrong would silently invert half the verdicts,
    which is exactly the kind of defect that makes judge pipelines quietly useless."""
    assert parse_verdict("INCORRECT") == (False, True)
    assert parse_verdict("CORRECT") == (True, True)
    assert parse_verdict("incorrect.") == (False, True)
    assert parse_verdict("  Correct  ") == (True, True)
    # A verbose reply still parses, but is flagged as not the one word asked for.
    assert parse_verdict("I would say this answer is INCORRECT because the sum is wrong.") == (
        False,
        False,
    )
    assert parse_verdict("The answer looks fine to me.") == (None, False)
    assert parse_verdict("") == (None, False)


# --- choosing what to judge -------------------------------------------------------------------


def test_only_answers_with_text_and_a_grade_can_be_judged() -> None:
    items = make_items()
    records = [
        record(items[0], output="six", correct=True),
        record(items[1], output=None, correct=None),  # errored call
        record(items[2], output="", correct=True),  # empty answer
    ]
    heldout = record(items[3], output="x", correct=True).model_copy(update={"held_out": True})
    assert [r.item_id for r in selectable([*records, heldout])] == [items[0].id]


def test_the_sample_is_one_per_item_seeded_and_spread_across_blocks() -> None:
    items = make_items()  # 6 reasoning, 4 multiple choice, 2 refusal
    records = [record(it, output="a", correct=True, repeat=k) for it in items for k in range(3)]
    chosen = select(selectable(records), 6, seed=1)
    assert len(chosen) == 6
    assert len({r.item_id for r in chosen}) == 6  # never the same item twice
    blocks = {r.block for r in chosen}
    assert len(blocks) == 3  # round-robin reached every block
    assert [r.item_id for r in chosen] == [r.item_id for r in select(selectable(records), 6, 1)]
    assert [r.item_id for r in chosen] != [r.item_id for r in select(selectable(records), 6, 2)]


def test_a_short_pool_returns_what_there_is() -> None:
    items = make_items()[:2]
    records = [record(it, output="a", correct=True) for it in items]
    assert len(select(selectable(records), 50, seed=1)) == 2


# --- running it ------------------------------------------------------------------------------


@dataclass
class FakeResponse:
    text: str
    ok: bool = True
    latency_ms: float = 12.0
    cost_usd: float | None = 0.00002
    costed: bool = True
    model_returned: str = "judge"

    @property
    def usage(self) -> Any:
        return type("U", (), {"input_tokens": 200, "output_tokens": 1})()


class SimpleJudge:
    """Replies from a list, in call order. Enough for the statistics tests."""

    def __init__(self, replies: list[str]) -> None:
        self.replies = list(replies)
        self.calls = 0

    def chat(self, request: Any, **kwargs: Any) -> FakeResponse:
        reply = self.replies[self.calls % len(self.replies)]
        self.calls += 1
        return FakeResponse(reply)


def test_run_writes_a_verdict_per_call_and_resumes_without_repeating_one(tmp_path: Path) -> None:
    items = make_items()[:3]
    suite = Suite(version="v1", items=tuple(items), hash="h")
    records = [record(it, output="six", correct=True) for it in items]
    caller = SimpleJudge([CORRECT])
    config = JudgeConfig(judge_model="anthropic/x", items=3, repeats=2)
    made = run(
        month="2026-09",
        suite=suite,
        records=records,
        caller=caller,
        config=config,
        out_dir=tmp_path,
        log=lambda _: None,
    )
    assert len(made) == 6 and caller.calls == 6
    stored = read_verdicts(tmp_path / "verdicts.jsonl")
    assert len(stored) == 6
    assert {v.repeat for v in stored} == {0, 1}
    assert all(v.grader_verdict is True and v.verdict is True for v in stored)
    # Running again calls nothing: the experiment is resumable and never pays twice.
    again = run(
        month="2026-09",
        suite=suite,
        records=records,
        caller=caller,
        config=config,
        out_dir=tmp_path,
        log=lambda _: None,
    )
    assert again == [] and caller.calls == 6


def test_a_limited_run_stops_early_and_the_next_run_carries_on(tmp_path: Path) -> None:
    """A probe of a few calls proves the wiring; the full run then pays only for the rest."""
    items = make_items()[:3]
    suite = Suite(version="v1", items=tuple(items), hash="h")
    records = [record(it, output="six", correct=True) for it in items]
    caller = SimpleJudge([CORRECT])
    config = JudgeConfig(judge_model="anthropic/x", items=3, repeats=2)
    kwargs: dict[str, Any] = dict(
        month="2026-09", suite=suite, records=records, caller=caller, config=config
    )
    probe = run(**kwargs, out_dir=tmp_path, limit=2, log=lambda _: None)
    assert len(probe) == 2 and caller.calls == 2
    rest = run(**kwargs, out_dir=tmp_path, log=lambda _: None)
    assert len(rest) == 4 and caller.calls == 6
    stored = read_verdicts(tmp_path / "verdicts.jsonl")
    assert len({(v.item_id, v.repeat) for v in stored}) == 6


def test_the_command_refuses_to_call_a_vendor_without_being_told_it_may() -> None:
    """The work network inspects TLS, so a paid call is opt-in, as it is for the gold set."""
    from typer.testing import CliRunner

    from drift import cli

    result = CliRunner().invoke(cli.app, ["rulec", "judge", "--month", "2026-09"])
    assert result.exit_code == 2
    assert "--i-am-allowed-to-call-vendors" in result.output


def test_the_judge_is_asked_at_temperature_zero_over_identical_input(tmp_path: Path) -> None:
    """The experiment has to be the most favourable case for the judge, or it proves nothing."""
    captured: list[Any] = []

    class Recorder(SimpleJudge):
        def chat(self, request: Any, **kwargs: Any) -> FakeResponse:
            captured.append((request, kwargs))
            return super().chat(request, **kwargs)

    item = make_items()[0]
    run(
        month="2026-09",
        suite=Suite(version="v1", items=(item,), hash="h"),
        records=[record(item, output="six", correct=True)],
        caller=Recorder([CORRECT]),
        config=JudgeConfig(judge_model="anthropic/x", items=1, repeats=3),
        out_dir=tmp_path,
        log=lambda _: None,
    )
    assert len(captured) == 3
    assert {r.temperature for r, _ in captured} == {0.0}
    assert len({r.messages[0]["content"] for r, _ in captured}) == 1  # identical input
    assert {k["mode"].name for _, k in captured} == {"PASSTHROUGH"}


# --- the statistics ----------------------------------------------------------------------------


def verdict(
    item_id: str, repeat: int, said: bool | None, graded: bool, block: str = "b"
) -> JudgeVerdict:
    return JudgeVerdict(
        ts_utc="2026-09-27T06:00:00Z",
        month="2026-09",
        judge_model="anthropic/x",
        item_id=item_id,
        block=block,
        arm_key="a",
        repeat=repeat,
        verdict=said,
        one_word=said is not None,
        raw=CORRECT if said else INCORRECT,
        grader_verdict=graded,
        latency_ms=1.0,
        input_tokens=1,
        output_tokens=1,
        cost_usd=0.001,
        costed=True,
    )


def test_majority_counts_a_tie_as_incorrect_like_the_record_does() -> None:
    assert majority([True, True, False]) is True
    assert majority([True, False]) is False
    assert majority([False, False]) is False


def test_self_disagreement_is_the_headline_and_counts_items_not_calls() -> None:
    """Two items of four flip, so the judge disagrees with itself on half of them."""
    verdicts = [
        *[verdict("a", k, True, True) for k in range(4)],  # steady
        *[verdict("b", k, False, False) for k in range(4)],  # steady
        verdict("c", 0, True, True),
        verdict("c", 1, False, True),  # flipped
        verdict("c", 2, True, True),
        verdict("c", 3, True, True),
        verdict("d", 0, False, False),
        verdict("d", 1, True, False),  # flipped
        verdict("d", 2, False, False),
        verdict("d", 3, False, False),
    ]
    report = analyse(verdicts)
    assert report.items == 4 and report.calls == 16 and report.repeats == 4
    assert report.self_disagreement.point == 0.5
    assert report.self_disagreement.n == 4
    assert set(report.disagreeing_items) == {"c", "d"}
    # The majority verdict still matches the grader on every item, which is the point: an
    # instrument can look accurate on average and still be too noisy to detect a small change.
    assert report.agreement_with_grader.point == 1.0


def test_agreement_with_the_grader_is_measured_separately_from_noise() -> None:
    verdicts = [
        *[verdict("a", k, True, False) for k in range(3)],  # steady but wrong
        *[verdict("b", k, True, True) for k in range(3)],  # steady and right
    ]
    report = analyse(verdicts)
    assert report.self_disagreement.point == 0.0
    assert report.agreement_with_grader.point == 0.5
    assert report.judge_correct_rate.point == 1.0
    assert report.grader_correct_rate.point == 0.5


def test_unreadable_and_verbose_replies_are_counted_not_silently_dropped() -> None:
    verdicts = [
        verdict("a", 0, True, True),
        verdict("a", 1, None, True),
        verdict("a", 2, True, True),
        verdict("b", 0, None, True).model_copy(update={"one_word": False}),
    ]
    report = analyse(verdicts)
    assert report.unreadable == 2
    assert report.not_one_word == 2
    # Item b has no readable verdict at all, so it is out of the disagreement denominator.
    assert report.self_disagreement.n == 1


def test_every_reported_share_carries_an_interval() -> None:
    """A bare percentage is a bug in this repository (CLAUDE.md)."""
    report = analyse([verdict("a", k, k == 1, True) for k in range(4)])
    for estimate in (
        report.self_disagreement,
        report.agreement_with_grader,
        report.judge_correct_rate,
        report.grader_correct_rate,
    ):
        assert estimate.lo <= estimate.point <= estimate.hi
        assert "to" in estimate.fmt()


@pytest.mark.parametrize(
    ("flipped_of_ten", "must_say"),
    [
        (3, "at or above the 5% effect"),
        (0, "NOT rejected"),
    ],
)
def test_the_verdict_is_stated_against_the_effect_the_suite_can_detect(
    flipped_of_ten: int, must_say: str
) -> None:
    """Rule C is a claim about evidence, so the report has to be able to come out the other
    way. A judge quieter than the effect being measured does not reject the approach."""
    verdicts = []
    for i in range(10):
        for k in range(5):
            said = not (i < flipped_of_ten and k == 2)
            verdicts.append(verdict(f"i{i}", k, said, True))
    assert must_say in render(analyse(verdicts))


def test_a_wide_interval_refuses_to_call_it_either_way() -> None:
    """One flip in thirty is about 3%, under the 5% effect, but the interval reaches past it.
    The honest reading is that the sample is too small, not that the judge passed."""
    verdicts = [
        verdict(f"i{i}", k, not (i == 0 and k == 2), True) for i in range(30) for k in range(5)
    ]
    report = analyse(verdicts)
    assert report.self_disagreement.point < 0.05 <= report.self_disagreement.hi
    text = render(report)
    assert "cannot separate the two" in text and "larger one is needed" in text


def test_the_report_states_the_comparison_that_rejects_the_approach(tmp_path: Path) -> None:
    verdicts = [
        *[verdict("a", k, k != 2, True, block="closed_form_reasoning") for k in range(4)],
        *[verdict("b", k, True, True, block="multiple_choice") for k in range(4)],
    ]
    report = analyse(verdicts)
    text = render(report)
    assert "0%, by construction" in text  # the grader's own noise, the thing being compared
    assert "Judge disagrees with itself across repeats" in text
    assert "closed_form_reasoning" in text and "multiple_choice" in text
    assert "--replay" in text
    assert "does not claim a judge is useless" in text
    written = write_report(tmp_path, report)
    assert written.name == "report.md" and written.read_text(encoding="utf-8") == text


def test_results_live_apart_from_the_record() -> None:
    """No number from this experiment may reach the drift record (PLAN.md section 10)."""
    out = out_dir_for(Path("drift/experiments"), "2026-09")
    assert out == Path("drift/experiments/judge/2026-09")
    assert "runs" not in out.parts


def test_verdicts_round_trip_so_replay_needs_no_vendor(tmp_path: Path) -> None:
    path = tmp_path / "verdicts.jsonl"
    original = [verdict("a", k, True, True) for k in range(3)]
    path.write_text("\n".join(v.model_dump_json() for v in original) + "\n", encoding="utf-8")
    assert read_verdicts(path) == original
    assert json.loads(path.read_text(encoding="utf-8").splitlines()[0])["raw"] == CORRECT
