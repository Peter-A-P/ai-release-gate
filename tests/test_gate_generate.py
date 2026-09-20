"""Generating the gold set's answers, with no network, and the two panels that ship."""

from __future__ import annotations

import contextlib
from pathlib import Path

from drift.panel import Arm, load_panel
from gate import generate, gold
from tests.test_gate_gold import question, source
from tests.test_gate_judge_runner import FakeReply

SPECS = Path(__file__).resolve().parent.parent / "gate" / "specs"


def arm(key: str, provider: str = "anthropic", model: str = "m", **kw: object) -> Arm:
    return Arm.model_validate(
        {"key": key, "provider": provider, "model": model, "arm": "snapshot", "family": key, **kw}
    )


ARMS = [arm("anthropic-a"), arm("anthropic-b", model="bigger")]


def test_the_answering_prompt_is_ordinary_on_purpose() -> None:
    text = generate.answer_prompt(source(), question())
    assert "A refund takes 15 business days." in text
    assert "How long does a refund take?" in text
    # Nothing that would make the answers better than the answers a real application gets.
    for coaching in ("step by step", "do not hallucinate", "be careful", "think"):
        assert coaching not in text.lower()
    assert "must_mention" not in text
    assert "brief and direct" in generate.ANSWER_SYSTEM


def test_instance_ids_are_question_major_and_do_not_move() -> None:
    questions = [question(2), question(1)]  # deliberately out of order
    sources = {"fcac-001": source()}
    jobs = list(generate.plan(questions, sources, ARMS))
    assert [j.instance_id for j in jobs] == ["i-0001", "i-0002", "i-0003", "i-0004"]
    assert [j.question.id for j in jobs] == ["q-001", "q-001", "q-002", "q-002"]
    assert [j.arm.key for j in jobs] == ["anthropic-a", "anthropic-b"] * 2
    again = list(generate.plan(list(reversed(questions)), sources, ARMS))
    assert [(j.instance_id, j.question.id, j.arm.key) for j in again] == [
        (j.instance_id, j.question.id, j.arm.key) for j in jobs
    ], "a repeated run assigns the same ids, or every label is orphaned"


def test_a_failed_call_is_stored_as_an_empty_answer_rather_than_dropped() -> None:
    sources = {"fcac-001": source()}

    def caller(job: generate.Job) -> FakeReply:
        if job.arm.key == "anthropic-b":
            return FakeReply(None, finish_reason=None, cost_usd=None)
        return FakeReply("15 business days.")

    out = generate.generate([question()], sources, ARMS, caller, run_id="g1")
    assert [i.id for i in out] == ["i-0001", "i-0002"]
    assert out[1].output == "" and out[1].output_sha256 == gold.sha256_of("")
    assert out[1].cost_usd is None
    assert out[0].model_requested == "anthropic/m" and out[1].model_requested == "anthropic/bigger"


def test_generation_resumes_and_does_not_pay_twice() -> None:
    sources = {"fcac-001": source()}
    calls: list[str] = []

    def caller(job: generate.Job) -> FakeReply:
        calls.append(job.instance_id)
        return FakeReply("ok")

    first = generate.generate([question()], sources, ARMS, caller, run_id="g1", skip={"i-0001"})
    assert calls == ["i-0002"] and [i.id for i in first] == ["i-0002"]


def test_coverage_names_the_empty_answers() -> None:
    g = gold.GoldSet(
        sources=(source(),),
        questions=(question(),),
        instances=(
            gold.AnswerInstance(
                id="i-0001",
                question_id="q-001",
                source_id="fcac-001",
                arm_key="small",
                model_requested="p/m",
                model_returned=None,
                output="",
                output_sha256=gold.sha256_of(""),
                finish_reason=None,
                generated_utc="2026-09-20T00:00:00Z",
                run_id="g1",
            ),
            gold.AnswerInstance(
                id="i-0002",
                question_id="q-001",
                source_id="fcac-001",
                arm_key="big",
                model_requested="p/n",
                model_returned="p/n",
                output="fine",
                output_sha256=gold.sha256_of("fine"),
                finish_reason="stop",
                generated_utc="2026-09-20T00:00:00Z",
                run_id="g1",
            ),
        ),
    )
    text = generate.coverage(g)
    assert "big: 1 answers" in text
    assert "small: 1 answers, 1 empty" in text


def test_expected_calls_is_the_bill_before_it_is_paid() -> None:
    assert generate.expected_calls([question(), question(2)], ARMS) == 4


# ---------------------------------------------------------------- the panels that ship


def test_the_shipped_panels_load_and_refuse_to_run_until_confirmed() -> None:
    answers = load_panel(SPECS / "gold-answers.yaml")
    judges = load_panel(SPECS / "gold-judges.yaml")
    assert len(answers.arms) == 3, "three models of different sizes (B4)"
    assert len(judges.arms) == 2, "a small judge and a mid-tier one (B4)"
    assert answers.ready and judges.ready, (
        "a panel is ready only once every identifier is filled in and `chosen` is dated; both "
        "were confirmed against the vendors' own model lists on 2026-09-20, run 35529080046"
    )
    assert all("CHOOSE" not in a.model for a in [*answers.arms, *judges.arms])
    assert {a.family for a in answers.arms} == {"small", "mid", "large"}
    small = next(a for a in answers.arms if a.family == "small")
    assert "-Turbo" in small.model, (
        "this provider's serverless serving is marked -Turbo; Qwen2.5-3B-Instruct was in its "
        "model list and returned 400 'Unable to access non-serverless model' on the first call"
    )
    assert "7B" in small.model or "3B" in small.model, (
        "the small arm's job is to produce real faithfulness failures; a gold set on which "
        "every answer is good cannot tell a working judge from one that says fine to everything"
    )


def test_no_model_and_no_vendor_both_answers_and_judges() -> None:
    """A model grading its own homework is the easiest way to get a flattering kappa that means
    nothing. A vendor's judge preferring its own family's house style is the subtler version of
    the same thing, so the panels are separated by vendor as well as by model.

    This test caught exactly that on 2026-09-20: Haiku 4.5 was written into both panels.
    """
    answers = load_panel(SPECS / "gold-answers.yaml").arms
    judges = load_panel(SPECS / "gold-judges.yaml").arms
    shared_models = {a.model for a in answers} & {a.model for a in judges}
    assert not shared_models, f"a model is on both panels: {sorted(shared_models)}"
    shared_vendors = {a.provider for a in answers} & {a.provider for a in judges}
    assert not shared_vendors, f"a vendor is on both panels: {sorted(shared_vendors)}"


def test_the_judges_are_pinned_to_dated_identifiers_where_the_vendor_offers_one() -> None:
    """A calibration belongs to the model it was measured on. A floating alias would let a
    vendor invalidate every corrected rate in the repository without anyone noticing."""
    for a in load_panel(SPECS / "gold-judges.yaml").arms:
        assert a.arm == "snapshot", f"{a.key} is not a pinned snapshot"


def test_answers_already_paid_for_survive_a_failure_midway() -> None:
    """The first real run died on call one of 300 with a vendor 400. Had it died on call 250,
    every one of those answers would have been paid for and thrown away, so each is handed
    over as it arrives rather than collected and returned at the end."""
    sources = {"fcac-001": source()}
    kept: list[gold.AnswerInstance] = []

    def caller(job: generate.Job) -> FakeReply:
        if job.instance_id == "i-0002":
            raise RuntimeError("openweights returned 400")
        return FakeReply("15 business days.")

    with contextlib.suppress(RuntimeError):
        generate.generate([question()], sources, ARMS, caller, run_id="g1", on_instance=kept.append)
    assert [i.id for i in kept] == ["i-0001"], "the answer before the failure is kept"
