"""The gold set's store: what it accepts, what it refuses, and what it drops."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from gate import gold


def source(n: int = 1, text: str = "A refund takes 15 business days.") -> gold.SourceDoc:
    return gold.SourceDoc(
        id=f"fcac-{n:03d}",
        publisher="fcac",
        title="Refunds",
        url="https://example.invalid/refunds",
        retrieved_utc="2026-09-20T00:00:00Z",
        bytes_sha256="0" * 64,
        text=text,
        licence="Open Government Licence - Canada",
    )


def question(n: int = 1, source_id: str = "fcac-001", **kw: object) -> gold.GoldQuestion:
    base: dict[str, object] = {
        "id": f"q-{n:03d}",
        "source_id": source_id,
        "question": "How long does a refund take?",
        "must_mention": ("15 business days",),
    }
    base.update(kw)
    return gold.GoldQuestion.model_validate(base)


def instance(
    n: int = 1, *, question_id: str = "q-001", arm: str = "small", output: str = "15 days."
) -> gold.AnswerInstance:
    return gold.AnswerInstance(
        id=f"i-{n:04d}",
        question_id=question_id,
        source_id="fcac-001",
        arm_key=arm,
        model_requested="vendor/model",
        model_returned="vendor/model-dated",
        output=output,
        output_sha256=gold.sha256_of(output),
        finish_reason="stop",
        generated_utc="2026-09-20T00:00:00Z",
        run_id="gold-1",
    )


def label(
    instance_id: str,
    *,
    faithful: bool = True,
    complete: bool = True,
    pass_no: int = 1,
    text: str = "15 days.",
) -> gold.GoldLabel:
    return gold.GoldLabel(
        instance_id=instance_id,
        faithful=faithful,
        complete=complete,
        output_sha256=gold.sha256_of(text),
        pass_no=1 if pass_no == 1 else 2,
        labelled_utc="2026-09-20T00:00:00Z",
    )


def test_ids_are_checked_and_unknown_fields_refused() -> None:
    with pytest.raises(ValidationError):
        source().model_copy(update={"id": "fcac-1"}).model_validate(
            {**source().model_dump(), "id": "fcac-1"}
        )
    with pytest.raises(ValidationError):
        gold.GoldQuestion.model_validate(
            {
                "id": "q-001",
                "source_id": "fcac-001",
                "question": "?",
                "must_mention": ["x"],
                "extra": 1,
            }
        )
    with pytest.raises(ValidationError):
        question(must_mention=())  # a question with nothing to check against is not a question


def test_a_gold_set_reports_every_problem_rather_than_the_first() -> None:
    g = gold.GoldSet(
        sources=(source(),),
        questions=(question(), question(2, source_id="fcac-999")),
        instances=(
            instance(1),
            instance(2, question_id="q-404"),
            instance(3, arm="small"),  # a second answer for q-001 from the same model
        ),
    )
    problems = g.problems()
    assert any("fcac-999" in p for p in problems)
    assert any("q-404" in p for p in problems)
    assert any("a second answer" in p for p in problems)
    assert len(problems) == 3


def test_a_rewritten_answer_invalidates_its_own_hash() -> None:
    bad = instance(1).model_copy(update={"output": "something else"})
    g = gold.GoldSet(sources=(source(),), questions=(question(),), instances=(bad,))
    assert any("stored hash does not match" in p for p in g.problems())


def test_the_last_label_wins_and_the_passes_never_merge() -> None:
    labels = [
        label("i-0001", faithful=True),
        label("i-0001", faithful=False),  # a correction, appended
        label("i-0001", faithful=True, pass_no=2),
    ]
    first = gold.latest_labels(labels, pass_no=1)
    second = gold.latest_labels(labels, pass_no=2)
    assert first["i-0001"].faithful is False, "the later line wins"
    assert second["i-0001"].faithful is True, "the second pass is not touched by the first"


def test_a_label_whose_answer_changed_is_dropped() -> None:
    instances = {"i-0001": instance(1, output="a new answer")}
    labels = {"i-0001": label("i-0001", text="15 days.")}
    assert gold.usable_labels(labels, instances) == {}
    matching = {"i-0001": label("i-0001", text="a new answer")}
    assert set(gold.usable_labels(matching, instances)) == {"i-0001"}


def test_the_intra_rater_sample_is_the_same_hundred_every_time() -> None:
    ids = [f"i-{n:04d}" for n in range(300)]
    a = gold.intra_rater_sample(ids)
    b = gold.intra_rater_sample(list(reversed(ids)))
    assert a == b and len(a) == gold.INTRA_RATER_SAMPLE
    assert a == sorted(a)
    assert gold.intra_rater_sample(ids[:50]) == sorted(ids[:50]), (
        "fewer than the sample: all of them"
    )


def test_round_trip_through_files(tmp_path: Path) -> None:
    gold.write_all(tmp_path / gold.SOURCES_FILE, [source()])
    gold.write_all(tmp_path / gold.QUESTIONS_FILE, [question()])
    gold.write_all(tmp_path / gold.INSTANCES_FILE, [instance(1), instance(2, arm="big")])
    gold.append_label(tmp_path / gold.LABELS_FILE, label("i-0001"))
    gold.append_label(tmp_path / gold.LABELS_FILE, label("i-0002", complete=False))
    g = gold.load(tmp_path)
    assert g.problems() == []
    assert g.arms == ("big", "small")
    labels = gold.read_labels(tmp_path / gold.LABELS_FILE)
    assert len(labels) == 2 and labels[1].complete is False
    text = gold.summarise(g, labels)
    assert "instances  2 from 2 models" in text
    assert "labelled   2 of 2 (pass 1)" in text


def test_summary_counts_the_dropped_labels_out_loud(tmp_path: Path) -> None:
    gold.write_all(tmp_path / gold.SOURCES_FILE, [source()])
    gold.write_all(tmp_path / gold.QUESTIONS_FILE, [question()])
    gold.write_all(tmp_path / gold.INSTANCES_FILE, [instance(1, output="a new answer")])
    gold.append_label(tmp_path / gold.LABELS_FILE, label("i-0001", text="15 days."))
    g = gold.load(tmp_path)
    text = gold.summarise(g, gold.read_labels(tmp_path / gold.LABELS_FILE))
    assert "labelled   0 of 1" in text
    assert "1 label(s) dropped" in text


def test_an_empty_gold_set_says_so_rather_than_dividing_by_zero(tmp_path: Path) -> None:
    g = gold.load(tmp_path)
    assert g.problems() == [] and g.arms == ()
    assert "instances  0" in gold.summarise(g, [])
