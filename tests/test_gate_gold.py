"""The gold set's store: what it accepts, what it refuses, and what it drops."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from gate import gold

GOLD = Path(__file__).resolve().parent.parent / "gate" / "gold"


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


def test_a_question_whose_expected_points_are_not_in_its_source_is_caught() -> None:
    """Before a single vendor call is paid for. A question written against a different page, or
    against a passage that was cut before the answer, would make the completeness judgement a
    measurement of the question rather than of the answer."""
    good = question(1, must_mention=("15 business days",))
    bad = question(2, must_mention=("15 business days", "30 calendar days"))
    src = source()
    assert gold.check_question(good, src) == []
    assert gold.check_question(bad, src) == ["expects '30 calendar days', which is not in fcac-001"]
    g = gold.GoldSet(sources=(src,), questions=(good, bad), instances=())
    assert any("30 calendar days" in p for p in g.problems())


def test_an_unanswerable_question_whose_answer_is_in_the_source_is_caught() -> None:
    """The one item type that catches an invented fact is spoiled if the fact is really there."""
    spoiled = question(1, must_mention=("15 business days",), unanswerable=True)
    genuine = question(2, must_mention=("the annual fee",), unanswerable=True)
    src = source()
    assert gold.check_question(genuine, src) == []
    problems = gold.check_question(spoiled, src)
    assert problems and "it is answerable" in problems[0]


def test_the_match_is_whitespace_insensitive_and_case_insensitive() -> None:
    src = source(text="A refund\n  takes 15 BUSINESS days.")
    assert gold.check_question(question(1, must_mention=("15 business days",)), src) == []


def test_a_thin_passage_is_named_rather_than_left_to_be_noticed(tmp_path: Path) -> None:
    """A glossary stub fetches cleanly and is still poor material: there is barely anything in
    it to be unfaithful to. Three of the first thirty documents were stubs, and one of those
    was mostly site banner because its main region was too thin to prefer."""
    fat = source(1, text="A refund takes 15 business days. " * 40)
    thin = source(2, text="A refund takes 15 business days.")
    g = gold.GoldSet(sources=(fat, thin), questions=(), instances=())
    text = gold.summarise(g, [])
    assert "thin passages" in text
    assert "fcac-002" in text and "fcac-001" not in text.split("thin passages")[1]


def test_two_urls_that_redirect_to_one_page_are_reported() -> None:
    """sec-037's URL redirected to the asset allocation page and stored a passage byte for
    byte identical to sec-005's. Questions written from both would have looked independent
    while resting on one document."""
    same = source(1, text="The same words. " * 40)
    twin = same.model_copy(update={"id": "fcac-002", "url": "https://example.invalid/other"})
    g = gold.GoldSet(sources=(same, twin), questions=(), instances=())
    assert any("identical passages under fcac-001, fcac-002" in p for p in g.problems())


def test_the_committed_questions_are_what_the_source_produces() -> None:
    """`questions.jsonl` is generated from `gate/gold_questions.py`. If the two drift apart,
    the file stops being traceable to the phrases that justify each question."""
    from gate import gold_questions

    committed = gold.read_questions(GOLD / gold.QUESTIONS_FILE)
    assert committed == gold_questions.questions()


def test_every_question_fits_the_passage_it_names() -> None:
    """The whole hundred, checked against the stored passages. An answerable question whose
    expected points are not in its passage was written against the wrong page; an unanswerable
    one whose point IS in the passage is not unanswerable."""
    from gate import gold_questions

    assert gold_questions.problems(GOLD) == []


def test_the_gold_set_is_the_shape_the_plan_asked_for() -> None:
    g = gold.load(GOLD)
    questions = g.questions
    assert len(questions) == 100, "PLAN.md B4: 100 questions"
    assert len({q.id for q in questions}) == 100
    unanswerable = [q for q in questions if q.unanswerable]
    assert 10 <= len(unanswerable) <= 20, (
        "a set with no unanswerable question cannot catch a model inventing a fact"
    )
    assert {q.source_id for q in questions} == set(g.by_source), "every document carries a question"
    assert g.problems() == []
