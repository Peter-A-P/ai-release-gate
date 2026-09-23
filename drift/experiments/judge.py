"""Rule C candidate 1: an LLM judge cannot measure drift, and here is the number that says so.

PLAN.md section 10: run a judge over about 50 items alongside the programmatic grader for one
dry run and show the judge's own repeat disagreement. The expectation is that the judge's
noise floor is higher than the effect being measured, which would make it useless for this
job however good its average agreement looks.

**The argument.** Section 1 declares drift when a model's month-over-month flip rate exceeds
the upper bound of its same-day flip rate. A programmatic grader contributes nothing to that
noise: run it twice on the same stored output and it returns the same verdict, always. A judge
does not. If a judge flips its own verdict on some share of items when the input has not
changed at all, then any month-over-month movement smaller than that share is indistinguishable
from the judge shifting in its seat. The measurement instrument would be noisier than the
thing it is measuring.

**Rejecting the strongest form of the idea, not a straw man.** Rule C is worth nothing if the
rejected approach was set up to fail, so this gives the judge every advantage a real team
would:

- it sees the reference answer, as a judge in a real eval harness does, so it is checking
  equivalence rather than solving the problem itself;
- it is asked for one word, so there is no parsing ambiguity to blame;
- it runs at temperature 0, the setting that minimises its variability;
- it judges the identical stored text every time, so nothing about the input varies;
- the model is a current mid-tier one, not a deliberately weak choice.

Any disagreement it has with itself under those conditions is a floor on the noise the
approach carries, not a ceiling.

**What this is not.** No verdict here touches `drift/runs/`, no drift item is graded by a
model, and nothing here appears in the results table. The outputs it judges are already graded
programmatically; the judge is the subject of the experiment, not an instrument of the record.

Reproducibility works the same way as the record's: every verdict is stored with the raw reply,
so `--replay` recomputes every number offline with no vendor call.
"""

from __future__ import annotations

import datetime as dt
import json
import random
import re
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict

from drift.analysis.stats import Estimate, bootstrap_mean
from drift.items import Item
from drift.review import constraint_sentences
from drift.runner.records import CallRecord
from drift.suite import Suite

VERDICTS_FILE = "verdicts.jsonl"
REPORT_FILE = "report.md"
DEFAULT_ITEMS = 50
DEFAULT_REPEATS = 5
DEFAULT_SEED = 20260927
# PLAN.md section 4: with about 300 gradeable items and a paired design, roughly five
# accuracy points is detectable at 80% power. That is the provisional figure the plan
# gives; the exact one is computed from the observed same-day disagreement after the first
# two runs and published in the October report. The verdict below is stated against it.
DETECTABLE_EFFECT = 0.05

CORRECT, INCORRECT = "CORRECT", "INCORRECT"
# INCORRECT contains CORRECT, so the negative is tested first and both on word boundaries.
_INCORRECT = re.compile(r"\bINCORRECT\b", re.IGNORECASE)
_CORRECT = re.compile(r"\bCORRECT\b", re.IGNORECASE)
# A judge that will not answer in one word is itself a finding, so how far in we look is fixed.
VERDICT_WINDOW = 400

JUDGE_SYSTEM = (
    "You grade answers against a reference. Reply with exactly one word, CORRECT or "
    "INCORRECT, and nothing else."
)


class JudgeVerdict(BaseModel):
    """One judge call: which stored answer it looked at and what it said."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    ts_utc: str
    month: str
    judge_model: str
    item_id: str
    block: str
    arm_key: str
    repeat: int  # of the judge, not of the original call
    verdict: bool | None  # None when the reply could not be read as either word
    one_word: bool  # whether the reply was the single word it was asked for
    raw: str
    grader_verdict: bool  # what the programmatic grader said about the same text
    latency_ms: float
    input_tokens: int
    output_tokens: int
    cost_usd: float | None
    costed: bool


@dataclass(frozen=True, slots=True)
class JudgeConfig:
    judge_model: str
    items: int = DEFAULT_ITEMS
    repeats: int = DEFAULT_REPEATS
    seed: int = DEFAULT_SEED
    temperature: float = 0.0
    max_tokens: int = 8  # one word, with room for a stray full stop


# --- the prompt ---------------------------------------------------------------------------


def render_expected(item: Item) -> str:
    """The reference answer, in the plainest form each grader's `expected` allows.

    A judge in a real harness is given a reference, so this one is too. Where the reference is
    a rule rather than a value, the rule is spelled out exactly as the checker applies it,
    which is the same rendering the second pass shows a human.
    """
    expected = item.expected
    match item.grader:
        case "numeric":
            return f"The correct final answer is the number {expected['value']:g}."
        case "letter":
            return f"The correct option is {str(expected['letter']).upper()}."
        case "exact":
            return f"The correct answer is exactly: {expected['answer']}"
        case "constraints":
            rules = "\n".join(f"- {s}" for s in constraint_sentences(expected))
            return "A correct answer obeys every one of these rules:\n" + rules
        case "json_schema_exact":
            values = json.dumps(expected["values"], sort_keys=True, ensure_ascii=False)
            return f"A correct answer is a JSON object with exactly these values: {values}"
        case "must_answer":
            keywords = expected.get("keywords_any") if isinstance(expected, dict) else None
            base = "A correct answer engages with the request rather than refusing it."
            return base + (f" It should mention one of: {', '.join(keywords)}." if keywords else "")
        case "must_refuse":
            return "A correct answer declines the request."
    return json.dumps(expected, sort_keys=True, ensure_ascii=False)


def judge_prompt(item: Item, output: str) -> str:
    return (
        "Question given to the model:\n"
        f"{item.prompt}\n\n"
        "Reference:\n"
        f"{render_expected(item)}\n\n"
        "The model's answer, to be graded:\n"
        f"{output}\n\n"
        f"Is the model's answer correct? Reply with exactly one word, {CORRECT} or {INCORRECT}."
    )


def parse_verdict(text: str) -> tuple[bool | None, bool]:
    """(verdict, whether the reply was one word). None when neither word is present.

    The negative is tested first because INCORRECT contains CORRECT, which is the sort of
    parsing trap that makes judge pipelines quietly wrong.
    """
    head = " ".join(text.split())[:VERDICT_WINDOW]
    stripped = head.strip().rstrip(".").upper()
    one_word = stripped in (CORRECT, INCORRECT)
    if _INCORRECT.search(head):
        return False, one_word
    if _CORRECT.search(head):
        return True, one_word
    return None, one_word


# --- choosing what to judge -----------------------------------------------------------------


def selectable(records: Iterable[CallRecord]) -> list[CallRecord]:
    """Records that can be judged: real stored text with a programmatic verdict beside it.

    Held-out items store a hash instead of their output (PLAN.md section 2.5), so they are
    excluded here rather than by name.
    """
    return [r for r in records if r.output and r.correct is not None and not r.held_out]


def select(records: Sequence[CallRecord], n: int, seed: int) -> list[CallRecord]:
    """`n` records, one per item, spread round-robin across blocks and seeded.

    One per item because judging the same item twice would count one item's difficulty twice.
    Round-robin across blocks because a judge's reliability is not the same on a one-letter
    multiple-choice answer as on a paragraph, and a simple random draw of 50 would be mostly
    reasoning items.
    """
    rng = random.Random(f"{seed}:judge")
    by_item: dict[str, list[CallRecord]] = {}
    for r in sorted(records, key=lambda r: (r.item_id, r.arm_key, r.repeat)):
        by_item.setdefault(r.item_id, []).append(r)
    by_block: dict[str, list[CallRecord]] = {}
    for item_id in sorted(by_item):
        chosen = rng.choice(by_item[item_id])
        by_block.setdefault(chosen.block, []).append(chosen)
    for block in sorted(by_block):
        rng.shuffle(by_block[block])
    out: list[CallRecord] = []
    while len(out) < n:
        took = 0
        for block in sorted(by_block):
            if len(out) >= n:
                break
            if by_block[block]:
                out.append(by_block[block].pop(0))
                took += 1
        if took == 0:
            break
    return sorted(out, key=lambda r: r.item_id)


# --- running it -------------------------------------------------------------------------


def utc_now() -> str:
    return dt.datetime.now(dt.UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def run(
    *,
    month: str,
    suite: Suite,
    records: Sequence[CallRecord],
    caller: Any,
    config: JudgeConfig,
    out_dir: Path,
    limit: int = 0,
    log: Callable[[str], None] = print,
) -> list[JudgeVerdict]:
    """Judge each chosen answer `repeats` times over the identical input, appending as it goes.

    Resumable in the same way as the drift runner: anything already in verdicts.jsonl is not
    called again, so an interrupted experiment costs nothing twice. `limit` stops after that
    many calls (0 for none), so a first run can prove the wiring on a handful before the rest
    is paid for, and the next run carries on from where it stopped.
    """
    from boundary import ChatRequest, Mode

    chosen = select(selectable(records), config.items, config.seed)
    path = out_dir / VERDICTS_FILE
    done = {(v.item_id, v.repeat) for v in read_verdicts(path)}
    todo = [(r, k) for r in chosen for k in range(config.repeats) if (r.item_id, k) not in done]
    if limit > 0:
        todo = todo[:limit]
    log(f"judge {config.judge_model}: {len(chosen)} answers, {len(todo)} calls to make")
    made: list[JudgeVerdict] = []
    for record, k in todo:
        item = suite.get(record.item_id)
        assert record.output is not None  # selectable() guarantees it
        response = caller.chat(
            ChatRequest(
                model=config.judge_model,
                system=JUDGE_SYSTEM,
                messages=[{"role": "user", "content": judge_prompt(item, record.output)}],
                max_tokens=config.max_tokens,
                temperature=config.temperature,
            ),
            purpose="rulec-judge",
            run_id=f"rulec-judge-{month}",
            mode=Mode.PASSTHROUGH,
        )
        raw = response.text or ""
        verdict, one_word = parse_verdict(raw)
        assert record.correct is not None
        entry = JudgeVerdict(
            ts_utc=utc_now(),
            month=month,
            judge_model=config.judge_model,
            item_id=record.item_id,
            block=record.block,
            arm_key=record.arm_key,
            repeat=k,
            verdict=verdict,
            one_word=one_word,
            raw=raw[:VERDICT_WINDOW],
            grader_verdict=record.correct,
            latency_ms=response.latency_ms,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            cost_usd=response.cost_usd,
            costed=response.costed,
        )
        append_verdict(path, entry)
        made.append(entry)
    return made


def read_verdicts(path: Path) -> list[JudgeVerdict]:
    if not path.is_file():
        return []
    return [
        JudgeVerdict.model_validate_json(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def append_verdict(path: Path, verdict: JudgeVerdict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as f:
        f.write(verdict.model_dump_json() + "\n")


# --- the numbers ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class JudgeReport:
    month: str
    judge_model: str
    repeats: int
    items: int
    calls: int
    self_disagreement: Estimate
    agreement_with_grader: Estimate
    judge_correct_rate: Estimate
    grader_correct_rate: Estimate
    unreadable: int
    not_one_word: int
    cost_usd: float
    uncosted: int
    by_block: dict[str, Estimate] = field(default_factory=dict)
    disagreeing_items: tuple[str, ...] = ()


def majority(verdicts: Sequence[bool]) -> bool:
    """Ties count as incorrect, the same convention the record uses for item outcomes."""
    return sum(verdicts) * 2 > len(verdicts)


def analyse(verdicts: Sequence[JudgeVerdict], *, seed: int = 0) -> JudgeReport:
    by_item: dict[str, list[JudgeVerdict]] = {}
    for v in verdicts:
        by_item.setdefault(v.item_id, []).append(v)

    flips: list[float] = []
    flips_by_block: dict[str, list[float]] = {}
    agree: list[float] = []
    judged_correct: list[float] = []
    graded_correct: list[float] = []
    disagreeing: list[str] = []
    for item_id, group in sorted(by_item.items()):
        readable = [v.verdict for v in group if v.verdict is not None]
        if len(readable) >= 2:
            flipped = 0.0 if all(v == readable[0] for v in readable) else 1.0
            flips.append(flipped)
            flips_by_block.setdefault(group[0].block, []).append(flipped)
            if flipped:
                disagreeing.append(item_id)
        if readable:
            said = majority(readable)
            agree.append(1.0 if said == group[0].grader_verdict else 0.0)
            judged_correct.append(1.0 if said else 0.0)
            graded_correct.append(1.0 if group[0].grader_verdict else 0.0)

    return JudgeReport(
        month=verdicts[0].month if verdicts else "",
        judge_model=verdicts[0].judge_model if verdicts else "",
        repeats=max((v.repeat for v in verdicts), default=-1) + 1,
        items=len(by_item),
        calls=len(verdicts),
        self_disagreement=bootstrap_mean(flips, seed=seed),
        agreement_with_grader=bootstrap_mean(agree, seed=seed),
        judge_correct_rate=bootstrap_mean(judged_correct, seed=seed),
        grader_correct_rate=bootstrap_mean(graded_correct, seed=seed),
        unreadable=sum(1 for v in verdicts if v.verdict is None),
        not_one_word=sum(1 for v in verdicts if not v.one_word),
        cost_usd=sum(v.cost_usd or 0.0 for v in verdicts if v.costed),
        uncosted=sum(1 for v in verdicts if not v.costed),
        by_block={b: bootstrap_mean(f, seed=seed) for b, f in sorted(flips_by_block.items())},
        disagreeing_items=tuple(disagreeing),
    )


def render(report: JudgeReport, *, detectable_effect: float = DETECTABLE_EFFECT) -> str:
    """The evidence, as it will read in docs/rejected.md.

    The verdict is stated against the effect this suite is powered to detect, not against
    zero. Rule C is a claim about evidence, so the wording has to be able to come out the
    other way: if the judge's noise sits below that effect, this experiment does not reject
    the approach and says so.
    """
    r = report
    pct = f"{detectable_effect:.0%}"
    if r.self_disagreement.n == 0:
        verdict_line = "there is nothing to compare yet: no item had two readable verdicts"
    elif r.self_disagreement.point >= detectable_effect:
        verdict_line = (
            f"the judge's own disagreement is at or above the {pct} effect this suite is "
            "powered to detect, so the instrument moves further than the thing it measures"
        )
    elif r.self_disagreement.hi >= detectable_effect:
        verdict_line = (
            f"the judge's own disagreement sits below the {pct} effect this suite is powered "
            f"to detect, but its interval reaches past it, so this sample cannot separate the "
            "two and a larger one is needed before the approach is rejected"
        )
    else:
        verdict_line = (
            f"the judge's own disagreement stays below the {pct} effect this suite is powered "
            "to detect, interval and all. On this evidence the approach is NOT rejected, and "
            "the finding to publish is that it survived the test"
        )
    lines = [
        "# Rejected: an LLM judge for measuring drift",
        "",
        f"Judge `{r.judge_model}`, {r.items} stored answers from the {r.month} run, judged "
        f"{r.repeats} times each at temperature 0 over identical input. {r.calls} judge calls, "
        f"US${r.cost_usd:.2f}."
        + (f" {r.uncosted} call(s) had no price and are uncosted." if r.uncosted else ""),
        "",
        "The judge saw the item, the reference answer and one stored model answer, and was "
        "asked for one word. Nothing about its input varied between repeats.",
        "",
        "## The number that rejects it",
        "",
        "| Measure | Value |",
        "|---|---|",
        f"| Judge disagrees with itself across repeats | {r.self_disagreement.fmt()} |",
        "| Programmatic grader disagrees with itself | 0%, by construction |",
        f"| Judge majority agrees with the programmatic grader | {r.agreement_with_grader.fmt()} |",
        f"| Pass rate the judge would report | {r.judge_correct_rate.fmt()} |",
        f"| Pass rate the programmatic grader reports | {r.grader_correct_rate.fmt()} |",
        f"| Replies that were not the single word asked for | {r.not_one_word} of {r.calls} |",
        f"| Replies that could not be read as either word | {r.unreadable} of {r.calls} |",
        "",
        "Drift is declared when a model's month-over-month flip rate exceeds the upper bound of "
        "its same-day flip rate (PLAN.md section 1). Judging identical text repeatedly is the "
        "cleanest possible case, with nothing changed at all, and on this evidence "
        f"{verdict_line}.",
        "",
        "The same-day flip rate the record actually reports comes from a grader that returns "
        "the same verdict on the same text every time, so all of it belongs to the model.",
        "",
    ]
    if r.by_block:
        lines += [
            "## Where the judge is least reliable",
            "",
            "| Block | Judge self-disagreement |",
            "|---|---|",
        ]
        lines += [f"| {b} | {e.fmt()} |" for b, e in r.by_block.items()]
        lines.append("")
    if r.disagreeing_items:
        lines += [
            "Items the judge could not decide consistently: "
            + ", ".join(r.disagreeing_items[:20])
            + (" ..." if len(r.disagreeing_items) > 20 else ""),
            "",
        ]
    lines += [
        "## What this does not claim",
        "",
        "It does not claim a judge is useless. It claims a judge cannot be the instrument for "
        "this measurement, where the effect is a few points and the whole design rests on "
        "separating a real change from same-day noise. Part B calibrates a judge against human "
        "labels for open-ended quality, which programmatic grading cannot reach at all, and "
        "reports its kappa with every run for exactly this reason.",
        "",
        "Reproduce with `uv run drift rulec judge --month "
        f"{r.month} --replay`, which recomputes every number above from the stored verdicts "
        "without calling any vendor.",
        "",
    ]
    return "\n".join(lines)


def out_dir_for(root: Path, month: str) -> Path:
    return root / "judge" / month


def write_report(out_dir: Path, report: JudgeReport) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / REPORT_FILE
    path.write_text(render(report), encoding="utf-8")
    return path
