"""The rubric the judge is given, and the shape of the answer it must give back.

Two rules shape this prompt, and both are there to make the judge easy to reject rather than
easy to pass.

**Absolute, not pairwise.** The judge sees one answer and the source, and says whether that
answer is faithful and complete. It never sees two answers and picks one. PLAN.md B13
candidate 3 expects pairwise preference judging to carry a strong position bias, and the
swap check in calibration is what measures that; an absolute rubric has no position to be
biased about, which is the point of using one.

**One word per judgement.** The judge answers on two labelled lines and nothing else. A judge
allowed to write a paragraph writes a paragraph that has to be parsed, and the parser becomes
a second uncalibrated instrument sitting between the model and the number.

The human labels against the same rubric, in `docs/judge-rubric.md`. Where the two texts
differ the document is the one that counts, because the human's reading is the standard and
the prompt is the thing being measured against it. A test holds the two to the same rules.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict

from gate.gold import TASKS, AnswerInstance, GoldQuestion, SourceDoc, Task

# Bumped whenever the text below changes. A calibration is only valid for the rubric it was
# measured under, so every stored verdict and every calibration record carries this.
# 2 (2026-09-22): the completeness rule for a refusal matched to the human rubric, which keys
# it off whether the question was written unanswerable; arithmetic on figures the question
# gives made explicit. No verdict had been stored under 1.
RUBRIC_VERSION = "2"

# Shown under the question when it was written unanswerable. The labelling pass prints the
# same line, and a test holds the two to one string.
UNANSWERABLE_NOTE = "(this one is NOT answerable from the passage)"

SYSTEM = (
    "You are grading one answer against one source document. Apply the rules exactly as "
    "written. Answer only in the two-line format requested. Do not explain."
)

RULES = """\
FAITHFUL means every factual claim in the answer is supported by the source document below.
  - A claim the source does not make is unfaithful, even if it is true in general and even if
    it is helpful. The question is whether this document supports it.
  - A claim that contradicts the source is unfaithful.
  - Saying the document does not cover something, when it does not, is faithful.
  - Ordinary restatement, summary and arithmetic over the source's own figures, or over
    figures the question itself gives, are faithful.
  - Hedging does not rescue an unsupported claim: "it may be around 30 days" is unfaithful if
    the source gives no number.

COMPLETE means the answer addresses the question that was asked.
  - An answer that covers the substance of the question is complete even if it is brief.
  - An answer that refuses, or that answers a different question, is not complete.
  - An answer that says the document does not cover the question is COMPLETE only when the
    question is marked below as not answerable from this document. Otherwise the question
    has a real answer, and saying the document does not cover it leaves it unanswered: not
    complete, even when the document indeed does not cover it.
  - Completeness is about coverage, not about correctness: an answer can be complete and
    unfaithful at the same time, and those are two separate judgements.

The two judgements are independent. Judge each on its own."""

TEMPLATE = """\
{rules}

SOURCE DOCUMENT ({title})
---
{source}
---

QUESTION
{question}{answerability}

ANSWER
{answer}

Reply with exactly two lines and nothing else:
FAITHFUL: yes or no
COMPLETE: yes or no"""


def rubric_hash() -> str:
    """The hash of everything the judge is shown besides the case itself."""
    return hashlib.sha256(
        (RUBRIC_VERSION + "\n" + SYSTEM + "\n" + RULES + "\n" + TEMPLATE).encode("utf-8")
    ).hexdigest()[:16]


def judge_prompt(source: SourceDoc, question: GoldQuestion, answer: str) -> str:
    """The user message. Rendered identically every time, so a judge asked the same case twice
    is shown byte-for-byte the same text and any disagreement is its own."""
    return TEMPLATE.format(
        rules=RULES,
        title=source.title,
        source=source.text.strip(),
        question=question.question.strip(),
        # The same fact the labelling pass puts on screen, in the same words, because the
        # completeness of a refusal turns on it and a judge denied it is judging a different
        # case from the human.
        answerability=f"\n{UNANSWERABLE_NOTE}" if question.unanswerable else "",
        answer=answer.strip() or "(the model returned nothing)",
    )


_LINE = re.compile(r"^\s*(faithful|complete)\s*[:\-]\s*(yes|no|true|false)\b", re.IGNORECASE)
_YES = {"yes", "true"}


def parse_verdict(text: str) -> dict[Task, bool | None]:
    """The two judgements, or None for one the judge did not give in the form asked for.

    Deliberately strict about the shape and forgiving about nothing else. A judge that cannot
    answer in two labelled lines is a judge whose output needs interpreting, and an interpreted
    verdict is not the verdict that was calibrated. An unparseable line is None, which is
    ungradeable, which is absent from the calibration rather than counted as a disagreement.
    """
    out: dict[Task, bool | None] = {t: None for t in TASKS}
    for raw in (text or "").splitlines():
        m = _LINE.match(raw)
        if m is None:
            continue
        task: Task = "faithful" if m.group(1).lower() == "faithful" else "complete"
        if out[task] is None:
            out[task] = m.group(2).lower() in _YES
    return out


# Which end of the judge's output is shown first when a case is judged twice with the answer
# and the source swapped in the prompt. Used by the order-bias check (B4).
Position = Literal["source_first", "answer_first"]


@dataclass(frozen=True, slots=True)
class JudgeConfig:
    """One judge: a model, its settings, and the rubric it was shown.

    Temperature 0 and a two-word answer, so that any disagreement the judge has with itself on
    identical stored text is a floor on the approach's noise rather than a ceiling. That is the
    same trick `drift/experiments/judge.py` uses in Part A, and for the same reason: an idea
    should be rejected in its strongest form or not at all.
    """

    key: str
    provider: str
    model: str
    temperature: float = 0.0
    max_tokens: int = 16
    rubric_version: str = RUBRIC_VERSION

    @property
    def rubric_hash(self) -> str:
        return rubric_hash()


class JudgeVerdict(BaseModel):
    """One judge's reading of one instance. Stored; never recomputed from memory."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    instance_id: str
    judge_key: str
    model_requested: str
    model_returned: str | None
    repeat: int = 0
    position: Position = "source_first"
    faithful: bool | None
    complete: bool | None
    raw: str
    rubric_hash: str
    prompt_sha256: str
    finish_reason: str | None = None
    latency_ms: float = 0.0
    cost_usd: float | None = None
    judged_utc: str = ""

    def value(self, task: Task) -> bool | None:
        return self.faithful if task == "faithful" else self.complete

    @property
    def gradeable(self) -> bool:
        return self.faithful is not None and self.complete is not None


def verdict_from_text(
    *,
    instance: AnswerInstance,
    config: JudgeConfig,
    text: str,
    prompt: str,
    model_returned: str | None = None,
    repeat: int = 0,
    position: Position = "source_first",
    finish_reason: str | None = None,
    latency_ms: float = 0.0,
    cost_usd: float | None = None,
    judged_utc: str = "",
) -> JudgeVerdict:
    parsed = parse_verdict(text)
    return JudgeVerdict(
        instance_id=instance.id,
        judge_key=config.key,
        model_requested=config.model,
        model_returned=model_returned,
        repeat=repeat,
        position=position,
        faithful=parsed["faithful"],
        complete=parsed["complete"],
        raw=text,
        rubric_hash=config.rubric_hash,
        prompt_sha256=hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        finish_reason=finish_reason,
        latency_ms=latency_ms,
        cost_usd=cost_usd,
        judged_utc=judged_utc,
    )
