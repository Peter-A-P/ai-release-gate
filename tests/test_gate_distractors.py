"""The distractor stratum: a question served with a document that cannot answer it.

The first 300 instances came back 300 of 300 faithful, so the set had no negative class and a
judge could not be calibrated on it at all. These instances exist to produce real unfaithful
answers rather than invented ones, so what is tested here is mostly that the setup is honest:
the served document really does not contain the answer, the choice is reproducible, and every
downstream reader is shown the document the model was actually given.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from gate import distractors, generate, gold
from gate.judge.rubric import judge_prompt
from tests.test_gate_generate import ARMS

GOLD = Path(__file__).resolve().parent.parent / "gate" / "gold"


@pytest.fixture(scope="module")
def real() -> gold.GoldSet:
    return gold.load(GOLD)


def test_no_distractor_contains_the_answer_it_is_supposed_to_withhold(real: gold.GoldSet) -> None:
    """The whole guarantee of the stratum. If the served document happens to carry the phrase
    the question asks for, then an answer drawn from it is faithful, the instance is not a
    negative, and a specificity computed over it is wrong in the direction that flatters the
    judge."""
    for q in distractors.questions_for(real):
        served = distractors.distractor_for(q, real.by_source)
        assert served.id != q.source_id, f"{q.id} was served its own document"
        haystack = gold.normalised(served.text)
        for point in q.must_mention:
            assert gold.normalised(point) not in haystack, (
                f"{q.id}: {point!r} is in {served.id}, so {served.id} can answer it"
            )


def test_only_answerable_questions_get_a_distractor(real: gold.GoldSet) -> None:
    """An unanswerable question served with the wrong document is still unanswerable and tests
    nothing the first 300 did not already test."""
    chosen = distractors.questions_for(real)
    assert chosen, "the stratum is empty"
    assert not any(q.unanswerable for q in chosen)
    assert len(chosen) == distractors.DISTRACTOR_QUESTIONS


def test_the_choice_is_reproducible_from_the_repository(real: gold.GoldSet) -> None:
    """Which question got which document has to come out the same on any machine, or the
    stratum cannot be re-derived and the labels attached to it are unverifiable."""

    def chosen() -> list[tuple[str, str]]:
        return [
            (q.id, distractors.distractor_for(q, real.by_source).id)
            for q in distractors.questions_for(real)
        ]

    once, twice = chosen(), chosen()
    assert once == twice
    assert len({d for _, d in once}) > 5, "one document served to everything is a weaker test"


def test_a_question_with_no_possible_distractor_is_refused_rather_than_fudged() -> None:
    """If every other document supports the question there is no distractor, and inventing one
    would mean serving a document that can answer it and calling the answer unfaithful."""
    from tests.test_gate_gold import question, source

    everywhere = {
        "fcac-001": source(1, text="A refund takes 15 business days."),
        "fcac-002": source(2, text="Also, a refund takes 15 business days."),
    }
    with pytest.raises(distractors.NoDistractorError):
        distractors.distractor_for(question(source_id="fcac-001"), everywhere)


def test_ids_are_the_d_stratum_and_do_not_collide_with_the_first_300(real: gold.GoldSet) -> None:
    jobs = list(distractors.plan(real, ARMS))
    ids = [j.instance_id for j in jobs]
    assert ids == [f"d-{n:04d}" for n in range(1, len(ids) + 1)]
    assert len(jobs) == distractors.expected_calls(real, ARMS)
    first_300 = {i.id for i in real.instances if i.id.startswith("i-")}
    assert not first_300 & set(ids), "a d- id must never reuse an i- id"
    # Question-major, so the labeller reads each document once rather than once per model.
    assert [j.question.id for j in jobs[:2]] == [jobs[0].question.id] * 2


def test_the_job_carries_the_served_document_not_the_questions_own(real: gold.GoldSet) -> None:
    """The prompt is the ordinary one. Nothing tells the model it is being tested, and nothing
    nudges it towards a mistake; only the document is different."""
    for job in list(distractors.plan(real, ARMS))[:6]:
        assert job.source.id != job.question.source_id
        assert real.by_source[job.question.source_id].text.strip() not in job.prompt
        # Byte-for-byte the prompt the first 300 got, with the served document substituted.
        # Anything extra, a warning or a hint, would make this a measurement of the hint.
        assert job.prompt == generate.answer_prompt(job.source, job.question)


def test_the_judge_is_shown_the_document_the_model_was_given(real: gold.GoldSet) -> None:
    """The regression that would quietly destroy the stratum. Reading the passage off the
    question rather than off the instance would show the judge the document that DOES answer
    the question, so a correct "unfaithful" verdict would be scored as a mistake."""
    from gate.judge import runner

    job = next(iter(distractors.plan(real, ARMS)))
    served = job.source
    own = real.by_source[job.question.source_id]
    instance = gold.AnswerInstance(
        id="d-0001",
        question_id=job.question.id,
        source_id=served.id,
        arm_key="anthropic-a",
        model_requested="anthropic/m",
        model_returned="anthropic/m",
        output="It is 15 business days.",
        output_sha256=gold.sha256_of("It is 15 business days."),
        finish_reason="stop",
        generated_utc="2026-09-22T00:00:00Z",
        run_id="d-1",
    )
    g = gold.GoldSet(
        sources=real.sources, questions=real.questions, instances=(*real.instances, instance)
    )
    plans = [p for p in runner.plan(g, repeats=1, swap=False) if p[0] == "d-0001"]
    assert plans, "the d- instance was not planned for the judge"

    prompt = judge_prompt(
        source=g.by_source[instance.source_id], question=job.question, answer=instance.output
    )
    assert served.text.strip()[:200] in prompt
    assert own.text.strip()[:200] not in prompt
    # And the runner itself must resolve it the same way, not off the question.
    import inspect

    assert "sources[instance.source_id]" in inspect.getsource(runner), (
        "the judge runner must take the document from the instance, not from the question"
    )


def test_the_served_document_is_the_nearest_one_that_cannot_answer(real: gold.GoldSet) -> None:
    """Measured, not asserted. The first six distractors were picked at random from the same
    publisher and gave a cheque question against a page on breaking a mortgage contract; all
    three models declined at once and said the question was unrelated to the document. A
    distractor that announces itself by its vocabulary tests nothing, so the served document is
    now the closest one that still cannot answer the question."""
    for q in distractors.questions_for(real):
        served = distractors.distractor_for(q, real.by_source)
        best = distractors.overlap(q, served)
        for other in distractors.candidates(q, real.by_source):
            if other.publisher == real.by_source[q.source_id].publisher:
                assert distractors.overlap(q, other) <= best, (
                    f"{q.id}: {other.id} is closer than the {served.id} that was served"
                )


def test_the_stratum_is_hard_enough_to_be_worth_labelling(real: gold.GoldSet) -> None:
    """A floor on the whole exercise. If the served documents share almost none of the
    questions' vocabulary then every model will decline on sight, the stratum will produce no
    negatives, and 180 instances of somebody's evening will have bought nothing."""
    scores = [
        distractors.overlap(q, distractors.distractor_for(q, real.by_source))
        for q in distractors.questions_for(real)
    ]
    scores.sort()
    median = scores[len(scores) // 2]
    assert median >= 0.4, f"median overlap {median:.2f}: these distractors are too obvious"
    assert sum(1 for s in scores if s >= 0.5) >= 20, "too few genuinely close documents"
