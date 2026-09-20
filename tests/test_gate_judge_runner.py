"""Driving a judge with no network, and the prompt it is driven with."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from gate import gold
from gate.judge import report as judge_report
from gate.judge import runner
from gate.judge.calibration import calibrate
from gate.judge.rubric import RULES, JudgeConfig, judge_prompt, rubric_hash
from tests.test_gate_calibration import verdict
from tests.test_gate_gold import instance, label, question, source

CONFIG = JudgeConfig(key="small", provider="vendor", model="vendor/small")
RUBRIC_DOC = Path(__file__).resolve().parent.parent / "docs" / "judge-rubric.md"


@dataclass(frozen=True)
class FakeReply:
    text: str | None
    model_returned: str | None = "vendor/small-dated"
    finish_reason: str | None = "stop"
    cost_usd: float | None = 0.00002


def gold_set(n_instances: int = 3) -> gold.GoldSet:
    return gold.GoldSet(
        sources=(source(),),
        questions=(question(),),
        instances=tuple(
            instance(k, arm=f"arm-{k}", output=f"answer number {k}")
            for k in range(1, n_instances + 1)
        ),
    )


def test_the_prompt_carries_the_rules_the_source_the_question_and_the_answer() -> None:
    g = gold_set(1)
    text = judge_prompt(g.sources[0], g.questions[0], g.instances[0].output)
    assert "FAITHFUL means" in text and "COMPLETE means" in text
    assert "A refund takes 15 business days." in text
    assert "How long does a refund take?" in text
    assert "answer number 1" in text
    assert text.rstrip().endswith("COMPLETE: yes or no")
    assert "15 business days" in text
    # must_mention is the human's checklist and is never shown to the judge, or the judge would
    # be marking against an answer key the model never had.
    assert "must_mention" not in text


def test_an_empty_answer_is_shown_as_empty_rather_than_as_nothing() -> None:
    g = gold_set(1)
    text = judge_prompt(g.sources[0], g.questions[0], "   ")
    assert "(the model returned nothing)" in text


def test_the_swap_moves_the_answer_above_the_source_and_keeps_everything_else() -> None:
    g = gold_set(1)
    text = judge_prompt(g.sources[0], g.questions[0], g.instances[0].output)
    swapped = runner.swap_positions(text)
    assert swapped.index("ANSWER") < swapped.index("SOURCE DOCUMENT")
    assert text.index("SOURCE DOCUMENT") < text.index("\nANSWER\n")
    for fragment in (
        "A refund takes 15 business days.",
        "How long does a refund take?",
        "answer number 1",
    ):
        assert fragment in swapped
    assert swapped.rstrip().endswith("COMPLETE: yes or no")
    assert RULES.splitlines()[0] in swapped


def test_the_plan_is_one_instance_at_a_time_and_covers_repeats_and_positions() -> None:
    g = gold_set(2)
    plain = list(runner.plan(g))
    assert plain == [("i-0001", 0, "source_first"), ("i-0002", 0, "source_first")]
    full = list(runner.plan(g, repeats=2, swap=True))
    assert full[:3] == [
        ("i-0001", 0, "source_first"),
        ("i-0001", 1, "source_first"),
        ("i-0001", 0, "answer_first"),
    ]
    assert len(full) == 6
    assert list(runner.plan(g, instance_ids=["i-0002"])) == [("i-0002", 0, "source_first")]


def test_a_run_stores_what_the_judge_said_and_the_hash_of_what_it_was_shown() -> None:
    g = gold_set(2)
    seen: list[str] = []

    def caller(*, system: str, prompt: str, config: JudgeConfig) -> FakeReply:
        seen.append(prompt)
        assert "grading one answer" in system
        return FakeReply("FAITHFUL: yes\nCOMPLETE: no")

    verdicts = runner.run(g, CONFIG, caller)
    assert len(verdicts) == 2 and len(seen) == 2
    v = verdicts[0]
    assert v.faithful is True and v.complete is False and v.gradeable
    assert v.judge_key == "small" and v.rubric_hash == rubric_hash()
    assert v.model_returned == "vendor/small-dated" and v.cost_usd == 0.00002
    # Two different instances must not produce the same prompt hash, or the record could not
    # prove which case a verdict is about.
    assert verdicts[0].prompt_sha256 != verdicts[1].prompt_sha256


def test_a_judge_that_will_not_answer_in_the_form_is_ungradeable_not_wrong() -> None:
    g = gold_set(1)

    def caller(*, system: str, prompt: str, config: JudgeConfig) -> FakeReply:
        return FakeReply("Honestly it depends on how you read the question.")

    v = runner.run(g, CONFIG, caller)[0]
    assert v.faithful is None and v.complete is None and not v.gradeable
    assert v.raw.startswith("Honestly")


def test_a_run_resumes_instead_of_paying_for_the_first_half_again() -> None:
    g = gold_set(3)
    calls: list[str] = []

    def caller(*, system: str, prompt: str, config: JudgeConfig) -> FakeReply:
        calls.append(prompt[:20])
        return FakeReply("FAITHFUL: yes\nCOMPLETE: yes")

    done = runner.run(g, CONFIG, caller, instance_ids=["i-0001"])
    assert len(calls) == 1
    skip = runner.already_done(done, "small")
    runner.run(g, CONFIG, caller, skip=skip)
    assert len(calls) == 3, "the two that were left, and not the one already stored"


def test_verdicts_round_trip_through_the_file(tmp_path: Path) -> None:
    g = gold_set(2)
    path = tmp_path / runner.VERDICTS_FILE

    def caller(*, system: str, prompt: str, config: JudgeConfig) -> FakeReply:
        return FakeReply("FAITHFUL: no\nCOMPLETE: yes")

    runner.run(g, CONFIG, caller, on_verdict=lambda v: runner.append_verdict(path, v))
    back = runner.read_verdicts(path)
    assert [v.instance_id for v in back] == ["i-0001", "i-0002"]
    assert all(v.faithful is False and v.complete is True for v in back)
    assert runner.read_verdicts(tmp_path / "nothing.jsonl") == []


def test_the_rendered_calibration_names_the_refusal_when_the_judge_is_no_good() -> None:
    """A judge that says yes to everything on a set the human split evenly: kappa 0, refused
    for both tasks, and the document has to say so rather than print a pass rate."""
    labels = {
        f"i-{n:04d}": label(f"i-{n:04d}", faithful=n % 2 == 0, complete=n % 2 == 0)
        for n in range(20)
    }
    verdicts = [verdict(k) for k in labels]
    c = calibrate(labels, verdicts, judge_key="small", resamples=200)
    text = judge_report.render(c, gold_instances=20, labelled=20)
    assert "Refused for: faithful, complete." in text
    assert "Usable for no task." in text
    assert "random number generator with good manners" in text
    assert c.usable_tasks == ()


def test_the_prompt_and_the_document_agree_on_the_rules_that_matter() -> None:
    """The judge's prompt is a shortened form of docs/judge-rubric.md. If one is edited without
    the other, the human and the judge are applying different standards and the kappa between
    them measures the edit rather than the judge."""
    # Whitespace-normalised, because the document is wrapped for reading and the prompt is not.
    doc = " ".join(RUBRIC_DOC.read_text(encoding="utf-8").split()).lower()
    rules = " ".join(RULES.split()).lower()
    for claim in (
        "even when the fact is true in the world",  # a true fact the source does not support
        "hedging does not rescue",  # a hedge is not a licence to invent
        "the two are independent",  # faithful and complete are judged apart
    ):
        assert claim in doc, f"the document lost: {claim}"
    for claim in ("true in general", "hedging does not rescue", "independent", "refuses"):
        assert claim in rules, f"the prompt lost: {claim}"
    assert "refuses" in doc
