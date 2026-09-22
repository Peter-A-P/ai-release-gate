"""The distractor stratum: questions served against a document that cannot answer them.

Why this exists. The first 300 instances came back faithful 300 of 300 and complete 298 of 300
when read by hand. That is a real measurement of current models on extractive QA over a clean
regulator passage, and it is also fatal to the thing the gold set was built for. With no
unfaithful answer in the set there is no negative class, so a judge's specificity cannot be
measured at all, Cohen's kappa is undefined, and the Rogan-Gladen correction has nothing to
correct with. Driving the project's own `calibration.cohens_kappa` over the 300 labels with a
judge that says "faithful" to everything, and again with a judge that agrees with the human on
every instance, returns the same thing both times: agreement 1.000, kappa NaN. The set cannot
tell those two judges apart, which is exactly the failure `gate/specs/gold-answers.yaml`
warned about in writing before any call was paid for.

What this does about it. Take a question that IS answerable from its own document, and serve
it with a different document instead. A faithful answer now has only one form: say the
document does not cover it. Any actual figure or rule in the answer had to come from the
model's own memory rather than from the text in front of it, and that is an unfaithful answer
by the rubric's first line.

Why this rather than corrupting the 300 answers by hand. A corrupted answer is a defect this
project invented and then measured a judge against, so the specificity would describe the
corruptions. A distractor answer is the model's own behaviour, unprompted, and it is the
failure that actually matters in production: a retrieval step returns the wrong passage and
the model answers anyway. Nothing here writes an answer or nudges a model towards a mistake.
The prompt is byte-for-byte the one the first 300 got. Only the document changes.

The label is NOT known by construction. A model that correctly declines gets a faithful answer
and is labelled faithful, exactly as in the first 300. This stratum is expected to produce
negatives, and if it produces none that is a finding too, not a failure of the method.
"""

from __future__ import annotations

import random
from collections.abc import Iterator, Sequence

from drift.panel import Arm
from gate.generate import Job
from gate.gold import GoldQuestion, GoldSet, SourceDoc, normalised

# How many of the answerable questions get a distractor. 60 of the 88 available, three models
# each, so 180 instances. Sized against the labelling rather than the money: the calls cost
# about 20 cents, and 180 instances is roughly three quarters of an hour of reading, against
# four hours for a second full set. It is enough that a specificity of even 0.8 comes with an
# interval worth quoting.
DISTRACTOR_QUESTIONS = 60

# Fixed for the life of the stratum. Which question gets which document has to be reproducible
# from the repository, or the stratum is a story rather than a measurement.
DISTRACTOR_SEED = 20260922


class NoDistractorError(ValueError):
    """Raised when every other document in the corpus happens to support the question."""


def candidates(question: GoldQuestion, sources: dict[str, SourceDoc]) -> list[SourceDoc]:
    """Documents that are NOT the question's own and that contain none of its answer points.

    The literal check is the whole guarantee. A document that happens to carry the phrase the
    question is asking for is not a distractor, it is a second correct source, and an answer
    drawn from it would be faithful. Same normalisation as `check_question`, so the rule that
    admits a document here is the rule that validated the question in the first place.
    """
    banned = [normalised(point) for point in question.must_mention]
    out = []
    for source in sorted(sources.values(), key=lambda d: d.id):
        if source.id == question.source_id:
            continue
        haystack = normalised(source.text)
        if any(point in haystack for point in banned):
            continue
        out.append(source)
    return out


def distractor_for(question: GoldQuestion, sources: dict[str, SourceDoc]) -> SourceDoc:
    """The document this question is served with. Deterministic, seeded on the question id."""
    pool = candidates(question, sources)
    if not pool:
        raise NoDistractorError(f"{question.id}: every other document supports it")
    own = sources.get(question.source_id)
    if own is not None:
        # Prefer the same publisher. A retrieval miss inside one corpus is the realistic
        # failure, and a document in the same register and house style is a harder distractor
        # than one that announces itself as off-topic by its vocabulary alone.
        same = [s for s in pool if s.publisher == own.publisher]
        pool = same or pool
    rng = random.Random(f"{DISTRACTOR_SEED}:{question.id}")
    return pool[rng.randrange(len(pool))]


def questions_for(gold: GoldSet, *, n: int = DISTRACTOR_QUESTIONS) -> list[GoldQuestion]:
    """Which questions get a distractor: answerable ones only, sampled with a fixed seed.

    An unanswerable question served with the wrong document is still unanswerable, so it tests
    nothing the first 300 did not already test. The sample is seeded and then re-sorted, so the
    same sixty are chosen every time and their order does not depend on the draw.
    """
    answerable = [q for q in sorted(gold.questions, key=lambda q: q.id) if not q.unanswerable]
    if len(answerable) <= n:
        return answerable
    rng = random.Random(DISTRACTOR_SEED)
    return sorted(rng.sample(answerable, n), key=lambda q: q.id)


def plan(gold: GoldSet, arms: Sequence[Arm], *, n: int = DISTRACTOR_QUESTIONS) -> Iterator[Job]:
    """Every (question, distractor, model) triple, with a stable `d-` instance id.

    Question-major like the first 300, so the three answers to one case sit together and the
    labeller reads each document once rather than three times.
    """
    sources = gold.by_source
    made = 0
    for question in questions_for(gold, n=n):
        served = distractor_for(question, sources)
        for arm in arms:
            made += 1
            yield Job(f"d-{made:04d}", question, served, arm)


def expected_calls(gold: GoldSet, arms: Sequence[Arm], *, n: int = DISTRACTOR_QUESTIONS) -> int:
    return len(questions_for(gold, n=n)) * len(arms)
