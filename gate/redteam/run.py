"""Asking the panel the red-team suite, and keeping what came back (PLAN.md B7).

Every call goes through `boundary`, nothing is retried, and a run that stops keeps every answer
already paid for, exactly as the gold set's generation does. The store is append-only JSON
lines, one answer per (item, arm), so running again continues where the last run stopped.

**A jailbreak answer's text is never committed.** A model that complies with a HarmBench
behaviour has written the harmful thing, and this repository is public. So for that suite the
answer is graded as it arrives, and the record keeps the grade, the grader stamp, the length and
the hash of the text, and not the text. The text itself goes to `withheld/`, which is gitignored
and which the workflow keeps only as a short-lived artifact, for the hand-labelling pass that
measures the refusal classifier. This is the rule Part A already has for held-out items: their
text was never stored, so they keep their run-time grade and cannot be regraded.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from collections.abc import Callable, Iterable, Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict

from drift.panel import Arm
from gate.redteam.graders import REDTEAM_GRADERS_HASH, grade
from gate.redteam.suite import RedTeamItem

RUNS_DIR = Path(__file__).resolve().parent / "runs"
ANSWERS_FILE = "answers.jsonl"
WITHHELD_DIR = "withheld"
# Suites whose answer text stays out of the repository.
WITHHELD_SUITES = frozenset({"jailbreak"})
# Part A's refusal block budget, for Part A's reason (drift/runner/run.py): a budget must be
# large enough that no arm reaches it, or the suite measures how much a model says. The largest
# refusal-block answer any arm has produced is 645 tokens. A leak or an obeyed injection that
# lands after a budget would be missed, which is the worse failure here.
MAX_TOKENS = 4096
TEMPERATURE = 0.0


class Answer(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    item_id: str
    item_sha256: str
    suite: str
    arm_key: str
    model_requested: str
    model_returned: str | None
    # None when the call failed, or when the suite's text is withheld from the repository.
    text: str | None
    text_sha256: str | None
    chars: int | None
    withheld: bool
    finish_reason: str | None
    error: str | None
    cost_usd: float | None
    latency_ms: float | None
    generated_utc: str
    run_id: str
    # The grade as it was when the answer arrived. The report regrades every answer whose text
    # is stored, and uses this only for the withheld ones.
    passed_at_run: bool | None
    detail_at_run: str
    graded_by: str

    @property
    def ok(self) -> bool:
        return self.error is None


@dataclass(frozen=True, slots=True)
class Reply:
    text: str | None
    model_returned: str | None
    finish_reason: str | None
    cost_usd: float | None
    latency_ms: float | None


Caller = Callable[[RedTeamItem, Arm], Reply]


def utc_now() -> str:
    return dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def run_dir(run_id: str, root: Path = RUNS_DIR) -> Path:
    return root / run_id


def read_answers(path: Path) -> list[Answer]:
    if not path.is_file():
        return []
    with path.open(encoding="utf-8") as f:
        return [Answer.model_validate_json(line) for line in f if line.strip()]


def append(path: Path, answer: Answer) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(answer.model_dump(mode="json"), ensure_ascii=False) + "\n")


def _keep_withheld(root: Path, answer: Answer, text: str) -> None:
    path = root / WITHHELD_DIR / f"{answer.arm_key}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps({"item_id": answer.item_id, "text": text}, ensure_ascii=False) + "\n")


def jobs(items: Sequence[RedTeamItem], arms: Sequence[Arm]) -> Iterator[tuple[RedTeamItem, Arm]]:
    """Arm-major, so a run stopped by `--limit` has finished whole arms rather than a slice of
    every arm, and the first arm's rates can be read before the rest is paid for."""
    for arm in arms:
        for item in items:
            yield item, arm


def record(
    item: RedTeamItem, arm: Arm, reply: Reply | None, error: str | None, run_id: str
) -> Answer:
    text = reply.text if reply is not None else None
    ok = error is None
    outcome = grade(item, text=text, ok=ok, finish_reason=reply.finish_reason if reply else None)
    withheld = item.suite in WITHHELD_SUITES and text is not None
    return Answer(
        item_id=item.id,
        item_sha256=item.sha256(),
        suite=item.suite,
        arm_key=arm.key,
        model_requested=arm.explicit,
        model_returned=reply.model_returned if reply else None,
        text=None if withheld else text,
        text_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest() if text is not None else None,
        chars=len(text) if text is not None else None,
        withheld=withheld,
        finish_reason=reply.finish_reason if reply else None,
        error=error,
        cost_usd=reply.cost_usd if reply else None,
        latency_ms=reply.latency_ms if reply else None,
        generated_utc=utc_now(),
        run_id=run_id,
        passed_at_run=outcome.passed,
        detail_at_run=outcome.detail,
        graded_by=REDTEAM_GRADERS_HASH,
    )


class LimitReachedError(RuntimeError):
    """`--limit` calls have been made. Raised through the caller and caught by `run`."""


def run(
    work: Iterable[tuple[RedTeamItem, Arm]],
    caller: Caller,
    *,
    root: Path,
    run_id: str,
    limit: int = 0,
) -> tuple[int, bool]:
    """Make every call not already stored, appending each answer as it arrives.

    Returns (calls made, whether the limit stopped it). A call that raises is stored as an
    errored answer, ungradeable and absent from every rate, and the run goes on: one vendor's
    bad minute must not cost the rest of the panel its answers.
    """
    path = root / ANSWERS_FILE
    done = {(a.item_id, a.arm_key) for a in read_answers(path)}
    made = 0
    for item, arm in work:
        if (item.id, arm.key) in done:
            continue
        if limit and made >= limit:
            return made, True
        made += 1
        try:
            reply: Reply | None = caller(item, arm)
            error = None
        except Exception as e:
            reply, error = None, f"{type(e).__name__}: {e}"[:500]
        answer = record(item, arm, reply, error, run_id)
        if answer.withheld and reply is not None and reply.text is not None:
            _keep_withheld(root, answer, reply.text)
        append(path, answer)
        done.add((item.id, arm.key))
    return made, False


def summary(answers: Sequence[Answer]) -> dict[str, Any]:
    by_arm: dict[str, dict[str, int]] = {}
    for a in answers:
        row = by_arm.setdefault(a.arm_key, {"answers": 0, "errors": 0})
        row["answers"] += 1
        row["errors"] += 0 if a.ok else 1
    return {
        "answers": len(answers),
        "cost_usd": round(sum(a.cost_usd or 0.0 for a in answers), 4),
        "arms": by_arm,
    }
