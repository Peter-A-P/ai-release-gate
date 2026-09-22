"""Generating the gold set's answers (PLAN.md B4, B10 stage 2).

Three models of different sizes answer the same 100 questions from the same source documents.
The point is not to find the best model. It is to produce **300 answers of genuinely mixed
quality**, because a gold set on which every answer is good cannot tell a working judge from
one that says "fine" to everything.

The prompt the models get is deliberately ordinary. No chain-of-thought instruction, no
"be careful not to hallucinate", nothing that would make the answers better than the answers a
real application gets. A judge calibrated on unusually careful answers is calibrated for a
distribution that will never arrive.

Like Part A's runner, every call goes through `boundary` and nothing is retried: a failed call
becomes an instance with empty text, which is a real thing a judge has to handle, and which the
labelling rubric already has a rule for.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator, Sequence
from dataclasses import dataclass

from drift.panel import Arm
from gate.gold import AnswerInstance, GoldQuestion, GoldSet, SourceDoc, sha256_of, utc_now
from gate.judge.runner import Reply

# Fixed for the life of the gold set. Changing it means regenerating every instance and
# relabelling, because the answers would come from a different distribution.
ANSWER_SYSTEM = "Answer the customer's question using the document provided. Be brief and direct."

ANSWER_TEMPLATE = """\
DOCUMENT ({title})
---
{source}
---

QUESTION
{question}"""

# Enough for a real answer to a consumer question and not enough for an essay. A truncated
# answer is a fact about the model, is recorded as such, and the rubric says how to label one.
MAX_TOKENS = 400
TEMPERATURE = 0.0


def answer_prompt(source: SourceDoc, question: GoldQuestion) -> str:
    return ANSWER_TEMPLATE.format(
        title=source.title, source=source.text.strip(), question=question.question.strip()
    )


@dataclass(frozen=True, slots=True)
class Job:
    """One call to make: one question to one model."""

    instance_id: str
    question: GoldQuestion
    source: SourceDoc
    arm: Arm

    @property
    def prompt(self) -> str:
        return answer_prompt(self.source, self.question)


def plan(
    questions: Sequence[GoldQuestion],
    sources: dict[str, SourceDoc],
    arms: Sequence[Arm],
) -> Iterator[Job]:
    """Every (question, model) pair, with a stable instance id.

    The id is assigned by position, question-major, so `i-0001` is always the first question
    answered by the first model whatever order the calls are actually made in. A gold set whose
    ids move when a run is repeated is a gold set whose labels cannot be trusted.
    """
    n = 0
    for question in sorted(questions, key=lambda q: q.id):
        for arm in arms:
            n += 1
            yield Job(f"i-{n:04d}", question, sources[question.source_id], arm)


AnswerCaller = Callable[[Job], Reply]


def generate(
    jobs: Iterable[Job],
    caller: AnswerCaller,
    *,
    run_id: str,
    skip: set[str] | None = None,
    on_instance: Callable[[AnswerInstance], None] | None = None,
) -> list[AnswerInstance]:
    """Make the calls for jobs that are not already stored.

    Takes the jobs rather than building them, because there are now two ways to build them:
    `plan` here, and `gate.distractors.plan`, which serves a question with a document that
    cannot answer it.
    """
    done = skip or set()
    out: list[AnswerInstance] = []
    for job in jobs:
        if job.instance_id in done:
            continue
        reply = caller(job)
        text = reply.text or ""
        instance = AnswerInstance(
            id=job.instance_id,
            question_id=job.question.id,
            source_id=job.source.id,
            arm_key=job.arm.key,
            model_requested=job.arm.explicit,
            model_returned=reply.model_returned,
            output=text,
            output_sha256=sha256_of(text),
            finish_reason=reply.finish_reason,
            generated_utc=utc_now(),
            run_id=run_id,
            cost_usd=reply.cost_usd,
        )
        out.append(instance)
        if on_instance is not None:
            on_instance(instance)
    return out


def expected_calls(questions: Sequence[GoldQuestion], arms: Sequence[Arm]) -> int:
    return len(questions) * len(arms)


def coverage(gold: GoldSet) -> str:
    """Which models answered how many questions, for the run's own summary."""
    by_arm: dict[str, int] = {}
    empty: dict[str, int] = {}
    for i in gold.instances:
        by_arm[i.arm_key] = by_arm.get(i.arm_key, 0) + 1
        if not i.output.strip():
            empty[i.arm_key] = empty.get(i.arm_key, 0) + 1
    lines = []
    for arm in sorted(by_arm):
        line = f"  {arm}: {by_arm[arm]} answers"
        if arm in empty:
            line += f", {empty[arm]} empty"
        lines.append(line)
    return "\n".join(lines)
