"""Running a side for real: a prompt and a model answering a suite now (PLAN.md B6, stage 4).

Stage 1 compared sides read out of Part A's record. A pull request has no record: its prompt
did not exist until the branch was pushed. So this module makes one side the way the gold set's
answers were made, and grades it the way the judge was calibrated, and hands the decision
exactly the shape stage 1 did, a `Side` of per-item verdicts.

Four rules shape it, each for a failure that would otherwise pass unnoticed:

* **The base branch sets the rules.** `gate.yaml` is read on both sides, but the margin, the
  thresholds and the suites come from the base. Only the prompt and the model come from the
  candidate. A pull request that could edit its own margin could pass itself.
* **A judge grades only under the conditions it was calibrated in.** Same rubric (by hash), same
  output budget, same position, and a kappa at or above the floor on the task it is asked about.
  Anything else is refused before a call is made, not reported afterwards.
* **The judge's error is taken out of the difference, not left in it.** See
  `gate.stats.paired_difference`.
* **A cached reply is the same reply.** The development cache (B6) keys on everything the vendor
  is sent, so an unchanged baseline costs nothing on the second pull request, and a reply is
  reused only for a byte-identical request. It stores the latency and cost the call first had,
  because those describe the configuration, not this run. The monthly drift job never uses it.
"""

from __future__ import annotations

import hashlib
import json
import math
import statistics
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field

from drift.panel import Arm
from gate import generate, gold
from gate.judge import calibration as calib
from gate.judge.rubric import SYSTEM as JUDGE_SYSTEM
from gate.judge.rubric import judge_prompt, parse_verdict, rubric_hash
from gate.judge.runner import read_verdicts
from gate.outcomes import Side, SuiteOutcomes
from gate.spec import EvalSpec, Grader, SuiteSpec

CONFIG_FILE = "gate.yaml"


class Subject(BaseModel):
    """What a pull request changes: the system prompt and the model it is sent to."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    # Relative to the repository root.
    prompt: str = Field(min_length=1)
    provider: str = Field(min_length=1)
    model: str = Field(min_length=1)
    extra: dict[str, Any] = Field(default_factory=dict)
    omit: tuple[str, ...] = ()

    def arm(self) -> Arm:
        return Arm.model_validate(
            {
                "key": "subject",
                "provider": self.provider,
                "model": self.model,
                "arm": "snapshot",
                "family": "subject",
                "extra": self.extra,
                "omit": self.omit,
            }
        )


class ConfigError(ValueError):
    """A repository's gate.yaml, or the judge it names, cannot be used as written."""


def load_repo_config(root: Path, name: str = CONFIG_FILE) -> tuple[EvalSpec, Subject, str]:
    """The spec, the subject, and the text of the prompt it points to."""
    path = root / name
    if not path.is_file():
        raise ConfigError(f"no {name} in {root}")
    with path.open(encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    if "subject" not in raw:
        raise ConfigError(f"{path}: no subject (the prompt and model under test)")
    subject = Subject.model_validate(raw.pop("subject"))
    spec = EvalSpec.model_validate(raw)
    prompt_path = root / subject.prompt
    if not prompt_path.is_file():
        raise ConfigError(f"{path}: prompt {subject.prompt!r} does not exist")
    return spec, subject, prompt_path.read_text(encoding="utf-8").strip()


def sha16(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


# ---------------------------------------------------------------------------- vendor calls


@dataclass(frozen=True, slots=True)
class Request:
    """Everything the vendor is sent. The cache key is the hash of exactly this."""

    model: str  # provider/model
    system: str
    prompt: str
    max_tokens: int
    temperature: float | None
    extra: Mapping[str, Any] = field(default_factory=dict)

    def key(self) -> str:
        body = {
            "model": self.model,
            "system": self.system,
            "prompt": self.prompt,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            "extra": dict(self.extra),
        }
        canon = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return hashlib.sha256(canon.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class Reply:
    text: str
    model_returned: str | None
    finish_reason: str | None
    cost_usd: float | None
    latency_ms: float
    cached: bool = False


Chat = Callable[[Request], Reply]


class Cache:
    """The development cache: an append-only JSON-lines file of replies by request hash."""

    def __init__(self, path: Path | None) -> None:
        self.path = path
        self._replies: dict[str, Reply] = {}
        if path is not None and path.is_file():
            with path.open(encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        d = json.loads(line)
                        key = d.pop("key")
                        self._replies[key] = Reply(**d, cached=True)

    def get(self, request: Request) -> Reply | None:
        return self._replies.get(request.key())

    def put(self, request: Request, reply: Reply) -> None:
        key = request.key()
        stored = Reply(
            reply.text,
            reply.model_returned,
            reply.finish_reason,
            reply.cost_usd,
            reply.latency_ms,
            cached=True,
        )
        self._replies[key] = stored
        if self.path is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8", newline="\n") as f:
            row = {
                "key": key,
                "text": reply.text,
                "model_returned": reply.model_returned,
                "finish_reason": reply.finish_reason,
                "cost_usd": reply.cost_usd,
                "latency_ms": reply.latency_ms,
            }
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


@dataclass
class Spend:
    """What this run actually paid, as against what the configuration costs per call."""

    calls: int = 0
    cache_hits: int = 0
    usd: float = 0.0

    def add(self, reply: Reply) -> None:
        if reply.cached:
            self.cache_hits += 1
        else:
            self.calls += 1
            self.usd += reply.cost_usd or 0.0


def call(chat: Chat, cache: Cache, request: Request, spend: Spend) -> Reply:
    hit = cache.get(request)
    if hit is not None:
        spend.add(hit)
        return hit
    reply = chat(request)
    cache.put(request, reply)
    spend.add(reply)
    return reply


def timed(send: Callable[[Request], Any]) -> Chat:
    """Wrap a gateway-shaped call (a reply with text, model_returned, finish_reason and
    cost_usd) so it also records wall-clock latency, which the latency line is made of."""

    def chat(request: Request) -> Reply:
        started = time.perf_counter()
        r = send(request)
        elapsed = (time.perf_counter() - started) * 1000.0
        return Reply(r.text or "", r.model_returned, r.finish_reason, r.cost_usd, elapsed)

    return chat


# ---------------------------------------------------------------------------- the judge


@dataclass(frozen=True, slots=True)
class Licence:
    """A judge cleared to grade one task, with the numbers that cleared it."""

    grader: Grader
    arm: Arm
    calibration: calib.TaskCalibration

    @property
    def counts(self) -> tuple[int, int, int, int]:
        c = self.calibration.counts
        return (c.true_positive, c.false_negative, c.false_positive, c.true_negative)


def license_judge(grader: Grader, judges: Sequence[Arm], gold_root: Path) -> Licence:
    """Calibrate the named judge from the stored record and clear it for the task, or refuse.

    Every refusal is a condition under which the stored kappa does not describe the judge that
    would be run: a different rubric, a different budget, a task it failed on, no record.
    """
    arms = {a.key: a for a in judges}
    if grader.judge not in arms:
        raise ConfigError(f"no judge {grader.judge!r}; the panel has {', '.join(sorted(arms))}")
    g = gold.load(gold_root)
    labels = gold.usable_labels(
        gold.latest_labels(gold.read_labels(gold_root / gold.LABELS_FILE)), g.by_instance
    )
    mine = [v for v in read_verdicts(gold_root / "verdicts.jsonl") if v.judge_key == grader.judge]
    if not mine:
        raise ConfigError(f"judge {grader.judge!r} has never been calibrated")
    hashes = {v.rubric_hash for v in mine}
    if hashes != {rubric_hash()}:
        raise ConfigError(
            f"judge {grader.judge!r} was calibrated under rubric {sorted(hashes)}, not the "
            f"current {rubric_hash()}; recalibrate before it grades anything"
        )
    budgets = {v.max_tokens for v in mine if v.max_tokens is not None}
    if budgets != {grader.max_tokens}:
        raise ConfigError(
            f"judge {grader.judge!r} was calibrated at max_tokens {sorted(budgets)}, and the "
            f"grader asks for {grader.max_tokens}; a thinking judge is a different judge at "
            "another budget"
        )
    lengths = {i.id: len(i.output) for i in g.instances}
    c = calib.calibrate(labels, mine, judge_key=grader.judge, lengths=lengths)
    task = c.task(grader.task)
    if not task.usable:
        raise ConfigError(
            f"judge {grader.judge!r} is refused for {grader.task}: kappa "
            f"{task.kappa.point:.3f} is below {calib.KAPPA_FLOOR}. The gate does not grade with "
            "an instrument that has not been shown to work (PLAN.md B2.3)."
        )
    return Licence(grader=grader, arm=arms[grader.judge], calibration=task)


# ---------------------------------------------------------------------------- a suite


@dataclass(frozen=True, slots=True)
class LiveSuite:
    outcomes: SuiteOutcomes
    # The judge's verdict per item, for the Rogan-Gladen corrected rate in the report.
    judge_calls: tuple[bool, ...]
    answers: Mapping[str, str]


def _temperature(arm: Arm) -> float | None:
    return None if "temperature" in arm.omit else 0.0


def run_gold_suite(
    suite: SuiteSpec,
    goldset: gold.GoldSet,
    *,
    system_prompt: str,
    subject: Arm,
    licence: Licence,
    chat: Chat,
    cache: Cache,
    spend: Spend,
) -> LiveSuite:
    """Answer every gold question from its own document, then have the judge grade each answer.

    The answer is made exactly as the gold set's were (`gate.generate.answer_prompt`, the same
    token budget) with the side's own system prompt in place of the fixed one, and the judge is
    asked exactly as it was during calibration: same rubric, same budget, source first. A vendor
    error on either call makes the item ungradeable, absent rather than wrong, as in Part A. An
    empty answer is not an error: the rubric says it is neither faithful nor complete, and a
    prompt that makes the model say nothing has regressed.
    """
    grader = licence.grader
    outcomes: dict[str, bool] = {}
    judge_calls: list[bool] = []
    answers: dict[str, str] = {}
    latencies: list[float] = []
    cost = 0.0
    uncosted = 0
    ungradeable = 0
    answer_calls = 0
    sources = goldset.by_source
    for q in sorted(goldset.questions, key=lambda x: x.id):
        source = sources[q.source_id]
        ask = Request(
            model=subject.explicit,
            system=system_prompt,
            prompt=generate.answer_prompt(source, q),
            max_tokens=generate.MAX_TOKENS,
            temperature=_temperature(subject),
            extra=subject.extra,
        )
        try:
            reply = call(chat, cache, ask, spend)
        except Exception:
            ungradeable += 1
            continue
        answer_calls += 1
        latencies.append(reply.latency_ms)
        if reply.cost_usd is None:
            uncosted += 1
        else:
            cost += reply.cost_usd
        answers[q.id] = reply.text
        grade = Request(
            model=licence.arm.explicit,
            system=JUDGE_SYSTEM,
            prompt=judge_prompt(source, q, reply.text),
            max_tokens=grader.max_tokens,
            temperature=_temperature(licence.arm),
            extra=licence.arm.extra,
        )
        try:
            verdict = call(chat, cache, grade, spend)
        except Exception:
            ungradeable += 1
            continue
        value = parse_verdict(verdict.text)[grader.task]
        if value is None:
            ungradeable += 1
            continue
        outcomes[q.id] = value
        judge_calls.append(value)
    return LiveSuite(
        outcomes=SuiteOutcomes(
            suite=suite.key,
            outcomes=outcomes,
            ungradeable_items=ungradeable,
            calls=answer_calls,
            latency_p50_ms=statistics.median(latencies) if latencies else math.nan,
            cost_usd=cost,
            uncosted_calls=uncosted,
        ),
        judge_calls=tuple(judge_calls),
        answers=answers,
    )


def run_side(
    label: str,
    spec: EvalSpec,
    subject: Subject,
    system_prompt: str,
    goldset: gold.GoldSet,
    licences: Mapping[str, Licence],
    *,
    chat: Chat,
    cache: Cache,
    spend: Spend,
) -> tuple[Side, dict[str, LiveSuite]]:
    arm = subject.arm()
    suites: dict[str, SuiteOutcomes] = {}
    live: dict[str, LiveSuite] = {}
    for s in spec.suites:
        if s.source.kind != "gold_questions":
            raise ConfigError(
                f"suite {s.key!r}: a pull request can only be gated on live suites; "
                f"{s.source.kind} outcomes come from the drift record"
            )
        result = run_gold_suite(
            s,
            goldset,
            system_prompt=system_prompt,
            subject=arm,
            licence=licences[s.key],
            chat=chat,
            cache=cache,
            spend=spend,
        )
        suites[s.key] = result.outcomes
        live[s.key] = result
    source = {
        "kind": "live",
        "model": arm.explicit,
        "prompt_sha": sha16(system_prompt),
        "extra": json.dumps(subject.extra, sort_keys=True),
    }
    return Side(label=label, source=source, suites=suites), live
