"""Asking a judge, and storing what it said (PLAN.md B4).

The vendor call is behind a narrow protocol, `Caller`, exactly as Part A's runner puts every
vendor call behind `boundary`. Two consequences, both deliberate:

* every test in this repository drives a judge without a network, and
* the real caller is wired in one place, in the CLI, on the machine that is allowed to make
  vendor calls, which is never this laptop.

A verdict is stored, never recomputed from memory. The calibration is read back from the
stored verdicts, so a judge run once can be re-analysed any number of times for nothing, and
the kappa published in a report can be reproduced from the repository.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterable, Iterator, Sequence
from pathlib import Path
from typing import Protocol

from gate.gold import GoldSet, utc_now
from gate.judge.rubric import (
    SYSTEM,
    JudgeConfig,
    JudgeVerdict,
    Position,
    judge_prompt,
    verdict_from_text,
)

VERDICTS_FILE = "verdicts.jsonl"


class Reply(Protocol):
    """What a caller gives back. Structural, so `boundary.ChatResponse` satisfies it as is."""

    @property
    def text(self) -> str | None: ...
    @property
    def model_returned(self) -> str | None: ...
    @property
    def finish_reason(self) -> str | None: ...
    @property
    def cost_usd(self) -> float | None: ...


class Caller(Protocol):
    """One judge call. The CLI passes a boundary gateway; tests pass a function."""

    def __call__(self, *, system: str, prompt: str, config: JudgeConfig) -> Reply: ...


def swap_positions(prompt: str) -> str:
    """The order-bias check (B4): the same case with the answer shown before the source.

    Both orderings are otherwise byte-for-byte the rubric's own text, so a judge whose verdict
    moves between them moved for a reason that is not the case.
    """
    head, _, rest = prompt.partition("SOURCE DOCUMENT")
    source_block, _, tail = rest.partition("\nQUESTION\n")
    question_block, sep, answer_block = tail.partition("\nANSWER\n")
    if not sep:
        return prompt
    answer_text, _, instructions = answer_block.partition("\nReply with exactly two lines")
    return (
        f"{head}ANSWER\n{answer_text.rstrip()}\n\n"
        f"SOURCE DOCUMENT{source_block.rstrip()}\n\n"
        f"QUESTION\n{question_block.strip()}\n"
        f"\nReply with exactly two lines{instructions}"
    )


def plan(
    gold: GoldSet,
    *,
    repeats: int = 1,
    swap: bool = False,
    instance_ids: Sequence[str] | None = None,
) -> Iterator[tuple[str, int, Position]]:
    """Every (instance, repeat, position) a run will ask about, in a fixed order.

    Ordered by instance then repeat then position, so a run stopped halfway leaves a prefix
    that is a complete reading of some instances rather than a scatter across all of them.
    """
    wanted = set(instance_ids) if instance_ids is not None else None
    for instance in sorted(gold.instances, key=lambda i: i.id):
        if wanted is not None and instance.id not in wanted:
            continue
        for repeat in range(repeats):
            yield instance.id, repeat, "source_first"
        if swap:
            yield instance.id, 0, "answer_first"


def already_done(verdicts: Iterable[JudgeVerdict], judge_key: str) -> set[tuple[str, int, str]]:
    return {(v.instance_id, v.repeat, v.position) for v in verdicts if v.judge_key == judge_key}


def run(
    gold: GoldSet,
    config: JudgeConfig,
    caller: Caller,
    *,
    repeats: int = 1,
    swap: bool = False,
    instance_ids: Sequence[str] | None = None,
    skip: set[tuple[str, int, str]] | None = None,
    on_verdict: Callable[[JudgeVerdict], None] | None = None,
) -> list[JudgeVerdict]:
    """Ask the judge about each planned case once, and return what it said.

    Resumable through `skip`, which the CLI fills from the verdicts already stored, so a run
    interrupted halfway does not pay for the first half again. Nothing is retried: a failed
    call is a stored verdict with no judgement, which is ungradeable and therefore absent from
    the calibration rather than counted as a disagreement.
    """
    sources, questions, instances = gold.by_source, gold.by_question, gold.by_instance
    done = skip or set()
    out: list[JudgeVerdict] = []
    for instance_id, repeat, position in plan(
        gold, repeats=repeats, swap=swap, instance_ids=instance_ids
    ):
        if (instance_id, repeat, position) in done:
            continue
        instance = instances[instance_id]
        question = questions[instance.question_id]
        # The document that was SERVED, which is the question's own for the first 300
        # and a distractor for the d- stratum. Reading it off the question would show
        # the judge a document the model never saw.
        source = sources[instance.source_id]
        prompt = judge_prompt(source, question, instance.output)
        if position == "answer_first":
            prompt = swap_positions(prompt)
        started = time.perf_counter()
        reply = caller(system=SYSTEM, prompt=prompt, config=config)
        elapsed = (time.perf_counter() - started) * 1000.0
        verdict = verdict_from_text(
            instance=instance,
            config=config,
            text=reply.text or "",
            prompt=prompt,
            model_returned=reply.model_returned,
            repeat=repeat,
            position=position,
            finish_reason=reply.finish_reason,
            latency_ms=elapsed,
            cost_usd=reply.cost_usd,
            judged_utc=utc_now(),
        )
        out.append(verdict)
        if on_verdict is not None:
            on_verdict(verdict)
    return out


def read_verdicts(path: Path) -> list[JudgeVerdict]:
    if not path.is_file():
        return []
    out: list[JudgeVerdict] = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                out.append(JudgeVerdict.model_validate_json(line))
    return out


def append_verdict(path: Path, verdict: JudgeVerdict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as f:
        f.write(verdict.model_dump_json() + "\n")
