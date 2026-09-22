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
import re
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


# Function words carry no topic, so matching on them would rank every document alike. Short
# and deliberately unclever: a stemmer or a stop list tuned per corpus would be one more thing
# that has to be reproduced to re-derive which document was served.
STOPWORDS = frozenset(
    [
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "can",
        "do",
        "does",
        "for",
        "from",
        "have",
        "how",
        "i",
        "if",
        "in",
        "is",
        "it",
        "long",
        "me",
        "much",
        "my",
        "of",
        "on",
        "or",
        "so",
        "that",
        "the",
        "their",
        "there",
        "they",
        "this",
        "to",
        "use",
        "was",
        "what",
        "when",
        "where",
        "which",
        "who",
        "will",
        "with",
        "you",
        "your",
    ]
)


class NoDistractorError(ValueError):
    """Raised when every other document in the corpus happens to support the question."""


def _terms(text: str) -> list[str]:
    return [t for t in re.findall(r"[a-z]{4,}", text.casefold())]


def _rank(source_id: str) -> str:
    """Tie-break key. Reversed so `max` prefers the lowest id, which reads as "the first one"."""
    return "".join(chr(0x10FFFF - ord(c)) for c in source_id)


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


def overlap(question: GoldQuestion, source: SourceDoc) -> float:
    """How much of the question's vocabulary the document already uses, 0 to 1.

    The crudest possible similarity, and deliberately so: it has to be re-derivable by anyone
    reading the repository, and a sentence embedding would make which document was served
    depend on a model version. Content words only, because matching on "what" and "the" would
    rank every document the same.
    """
    terms = {t for t in _terms(question.question) if t not in STOPWORDS}
    if not terms:
        return 0.0
    present = set(_terms(source.text))
    return sum(1 for t in terms if t in present) / len(terms)


def distractor_for(question: GoldQuestion, sources: dict[str, SourceDoc]) -> SourceDoc:
    """The document this question is served with: the NEAREST one that still cannot answer it.

    Changed 2026-09-22 after the first six were measured. Picking at random from the same
    publisher gave a cheque question against a page on breaking a mortgage contract, and all
    three models declined immediately and said so in as many words ("This question isn't
    related to the document"). A distractor that announces itself by its vocabulary tests
    nothing; the model never has to decide anything.

    So the served document is the one with the most of the question's own words in it, among
    those verified to contain none of its answer points. That is the hard case and the
    realistic one: retrieval returns a page about the right topic that does not happen to carry
    the fact, which is exactly when a model is tempted to fill the gap from memory. Ties break
    on document id so the choice stays reproducible.
    """
    pool = candidates(question, sources)
    if not pool:
        raise NoDistractorError(f"{question.id}: every other document supports it")
    own = sources.get(question.source_id)
    if own is not None:
        # Same publisher first: a retrieval miss inside one corpus is the realistic failure,
        # and one house style removes a cue that has nothing to do with the content.
        same = [s for s in pool if s.publisher == own.publisher]
        pool = same or pool
    return max(pool, key=lambda s: (overlap(question, s), _rank(s.id)))


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
