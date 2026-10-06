"""How far the gold set's one rater agrees with their own earlier reading (docs/judge-rubric.md,
"The second pass").

The gold set is labelled by one person, and every judge is licensed by its agreement with those
labels. So the labels' own consistency is the ceiling on what a judge's agreement can mean: a
judge cannot be shown to agree with the standard more closely than the standard agrees with
itself. A hundred of the first pass's answers were served again weeks later, in a different
order, with nothing to show what was said the first time (`gate gold label --pass 2`); this
compares the two readings.

The figures are computed by the same functions that license a judge (`cohens_kappa`, its
bootstrap, `agreement`), with the first reading in the human's place and the second in the
judge's. Each judge with verdicts under the current rubric is then measured on the same hundred
against both readings, so its published kappa can be read against the rater's.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from drift.analysis.stats import Estimate
from gate import gold
from gate.gold import TASKS, GoldLabel, Task
from gate.judge.calibration import (
    Counts,
    Pair,
    _bootstrap,
    agreement,
    cohens_kappa,
    counts_of,
    pairs_for,
)
from gate.judge.rubric import JudgeVerdict


@dataclass(frozen=True, slots=True)
class TaskAgreement:
    task: Task
    counts: Counts  # first reading in the human's place, second in the judge's
    agreement: float
    kappa: Estimate
    # Instances read differently, by direction.
    yes_then_no: tuple[str, ...]
    no_then_yes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class JudgeOnSample:
    judge_key: str
    task: Task
    against_first: Estimate
    against_second: Estimate
    n: int


@dataclass(frozen=True, slots=True)
class IntraRater:
    sample: int  # the instances served for the second pass
    read: int  # read on both passes, about the same text
    tasks: tuple[TaskAgreement, ...]
    judges: tuple[JudgeOnSample, ...]
    first_utc: str  # when the sample's first readings and second readings were made
    second_utc: str


def _span(labels: Sequence[GoldLabel]) -> str:
    days = sorted(label.labelled_utc[:10] for label in labels)
    if not days:
        return ""
    return days[0] if days[0] == days[-1] else f"{days[0]} to {days[-1]}"


def intra_rater(
    gold_set: gold.GoldSet,
    labels: Sequence[GoldLabel],
    verdicts: Sequence[JudgeVerdict],
    *,
    rubric_hash: str,
    resamples: int = 2000,
    seed: int = 0,
) -> IntraRater:
    sample = gold.intra_rater_sample(gold_set.instance_ids_in("core"))
    first = gold.usable_labels(gold.latest_labels(labels, pass_no=1), gold_set.by_instance)
    second = gold.usable_labels(gold.latest_labels(labels, pass_no=2), gold_set.by_instance)
    ids = [i for i in sample if i in first and i in second]
    tasks = []
    for task in TASKS:
        pairs: list[Pair] = [(first[i].value(task), second[i].value(task)) for i in ids]
        tasks.append(
            TaskAgreement(
                task=task,
                counts=counts_of(pairs),
                agreement=agreement(pairs),
                kappa=_bootstrap(pairs, cohens_kappa, resamples=resamples, seed=seed),
                yes_then_no=tuple(i for i in ids if first[i].value(task) > second[i].value(task)),
                no_then_yes=tuple(i for i in ids if first[i].value(task) < second[i].value(task)),
            )
        )
    # A judge's headline reading: the first, in the canonical position, under this rubric, as
    # `calibration.calibrate` takes it.
    canonical: dict[str, dict[str, JudgeVerdict]] = {}
    for v in verdicts:
        if v.rubric_hash == rubric_hash and v.repeat == 0 and v.position == "source_first":
            canonical.setdefault(v.judge_key, {})[v.instance_id] = v
    judges = []
    for key in sorted(canonical):
        mine = {i: v for i, v in canonical[key].items() if i in set(ids)}
        if not mine:
            continue
        for task in TASKS:
            a, _ = pairs_for(task, {i: first[i] for i in ids}, mine)
            b, _ = pairs_for(task, {i: second[i] for i in ids}, mine)
            judges.append(
                JudgeOnSample(
                    judge_key=key,
                    task=task,
                    against_first=_bootstrap(a, cohens_kappa, resamples=resamples, seed=seed),
                    against_second=_bootstrap(b, cohens_kappa, resamples=resamples, seed=seed),
                    n=len(a),
                )
            )
    return IntraRater(
        sample=len(sample),
        read=len(ids),
        tasks=tuple(tasks),
        judges=tuple(judges),
        first_utc=_span([first[i] for i in ids]),
        second_utc=_span([second[i] for i in ids]),
    )


def _k(e: Estimate) -> str:
    if e.n == 0 or e.point != e.point:
        return "undefined"
    return f"{e.point:.3f} ({e.lo:.3f} to {e.hi:.3f})"


def render(r: IntraRater, *, licensed: Mapping[str, Mapping[str, Estimate]] | None = None) -> str:
    """`licensed` is each judge's published kappa per task on the whole core stratum, for
    comparison, as `gate judge calibrate` prints it."""
    out = [
        "# The gold set's rater, read twice",
        "",
        f"Generated by `gate gold intra-rater`; offline. {r.read} of the {r.sample} answers in the "
        f"intra-rater sample read twice: first {r.first_utc}, again {r.second_utc}, in a "
        "different order and with nothing to show the first reading. Cohen's kappa with a 95% "
        "bootstrap interval, computed by the functions that license a judge.",
        "",
        "| Task | Same both times | Kappa | Yes, then no | No, then yes |",
        "|---|---:|---|---:|---:|",
    ]
    for t in r.tasks:
        out.append(
            f"| {t.task} | {round(t.agreement * t.counts.n)} of {t.counts.n} | {_k(t.kappa)} | "
            f"{len(t.yes_then_no)} | {len(t.no_then_yes)} |"
        )
    out += [""]
    for t in r.tasks:
        changed = sorted(t.yes_then_no + t.no_then_yes)
        if changed:
            out.append(f"- {t.task}, read differently: {', '.join(changed)}.")
    if r.judges:
        out += [
            "",
            "## The judges on the same answers",
            "",
            "Each judge's kappa on these answers against each reading. A judge cannot be shown "
            "to agree with the standard more closely than the standard agrees with itself.",
            "",
            "| Judge | Task | Against the first reading | Against the second |"
            + (" Published, whole stratum |" if licensed else ""),
            "|---|---|---|---|" + ("---|" if licensed else ""),
        ]
        for j in r.judges:
            pub = (licensed or {}).get(j.judge_key, {}).get(j.task)
            out.append(
                f"| {j.judge_key} | {j.task} | {_k(j.against_first)} | {_k(j.against_second)} |"
                + ((f" {_k(pub)} |" if pub is not None else " |") if licensed else "")
            )
    return "\n".join(out)
