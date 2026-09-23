"""Calibrating the judge against the human gold set (PLAN.md B2.3, B4, B1).

Everything here answers one question: if this judge says 82% of the answers were faithful,
what do we actually know? The honest answer has three parts, and most published eval numbers
give none of them.

1. **Is it measuring anything at all?** Cohen's kappa and Krippendorff's alpha against the
   human labels, per task, with bootstrap intervals. Raw agreement is not enough: on a set
   where 90% of answers are faithful, a judge that says "faithful" every time agrees 90% of
   the time and has learned nothing. Kappa is agreement above what that judge would get.
2. **Which way does it fail?** Sensitivity and specificity, separately. A judge that never
   catches an invented fact and a judge that cries wolf both have mediocre kappa and need
   opposite fixes.
3. **What is the score once its error is accounted for?** The Rogan-Gladen correction, with an
   interval that propagates the calibration's own uncertainty rather than treating sensitivity
   and specificity as if they were known exactly. That propagation is the part almost everyone
   drops, and it is usually the larger of the two uncertainties.

A judge below kappa 0.6 on a task is refused for that task (B2.3). The threshold is a
convention, not a law of nature, and `TaskCalibration.usable` reports the decision next to the
interval so a reader can see how close it was.
"""

from __future__ import annotations

import math
import random
from collections.abc import Callable, Hashable, Iterable, Mapping, Sequence
from dataclasses import dataclass

from drift.analysis.stats import Estimate, jeffreys_proportion, mcnemar_exact
from gate.gold import TASKS, GoldLabel, Task
from gate.judge.rubric import JudgeVerdict
from gate.stats import bootstrap_share

# PLAN.md B2.3. Below this on a task, the judge is refused for that task and the gate falls
# back to a programmatic grader or to "needs human review".
KAPPA_FLOOR = 0.6


@dataclass(frozen=True, slots=True)
class Counts:
    """The 2x2 table, human by judge. Positive means the judge said yes."""

    true_positive: int  # human yes, judge yes
    false_negative: int  # human yes, judge no
    false_positive: int  # human no, judge yes
    true_negative: int  # human no, judge no

    @property
    def n(self) -> int:
        return self.true_positive + self.false_negative + self.false_positive + self.true_negative

    @property
    def human_positive(self) -> int:
        return self.true_positive + self.false_negative

    @property
    def judge_positive(self) -> int:
        return self.true_positive + self.false_positive

    @property
    def agreed(self) -> int:
        return self.true_positive + self.true_negative


Pair = tuple[bool, bool]  # (human, judge)


def counts_of(pairs: Sequence[Pair]) -> Counts:
    tp = sum(1 for h, j in pairs if h and j)
    fn = sum(1 for h, j in pairs if h and not j)
    fp = sum(1 for h, j in pairs if not h and j)
    tn = sum(1 for h, j in pairs if not h and not j)
    return Counts(tp, fn, fp, tn)


def agreement(pairs: Sequence[Pair]) -> float:
    """Raw agreement. Reported only next to kappa, never on its own: on a lopsided set it is
    the prevalence of the majority class wearing the clothes of a quality measure."""
    if not pairs:
        return float("nan")
    return sum(1 for h, j in pairs if h == j) / len(pairs)


def cohens_kappa(pairs: Sequence[Pair]) -> float:
    """Agreement above chance, where chance is each rater's own marginal rate.

    Undefined when both raters were unanimous and agreed: there is no disagreement to be above
    chance about, and 1.0 would be a claim the data cannot support. Returns NaN, which every
    caller here reports as "no answer" rather than as a number.
    """
    n = len(pairs)
    if n == 0:
        return float("nan")
    observed = agreement(pairs)
    human_yes = sum(1 for h, _ in pairs if h) / n
    judge_yes = sum(1 for _, j in pairs if j) / n
    expected = human_yes * judge_yes + (1 - human_yes) * (1 - judge_yes)
    if math.isclose(expected, 1.0):
        return float("nan")
    return (observed - expected) / (1 - expected)


def krippendorff_alpha(units: Iterable[Sequence[Hashable]]) -> float:
    """Nominal alpha over units of any number of raters, missing values simply absent.

    Kappa takes exactly two raters and every unit rated by both. Alpha does not, which is why
    B1 asks for both: the judge-against-human comparison is a two-rater complete design where
    they agree closely, and the second rater on the gold set, if one is ever found, will have
    rated only some of it.
    """
    coincidence: dict[tuple[Hashable, Hashable], float] = {}
    total = 0.0
    for unit in units:
        values = list(unit)
        m = len(values)
        if m < 2:
            continue  # a unit one rater saw carries no information about agreement
        weight = 1.0 / (m - 1)
        total += m
        for i, a in enumerate(values):
            for k, b in enumerate(values):
                if i != k:
                    coincidence[(a, b)] = coincidence.get((a, b), 0.0) + weight
    if total < 2:
        return float("nan")
    disagreeing = sum(v for (a, b), v in coincidence.items() if a != b)
    observed = disagreeing / total
    marginal: dict[Hashable, float] = {}
    for (a, _), v in coincidence.items():
        marginal[a] = marginal.get(a, 0.0) + v
    expected = sum(marginal[a] * marginal[b] for a in marginal for b in marginal if a != b) / (
        (total - 1) * total
    )
    if math.isclose(expected, 0.0):
        return float("nan")
    return 1.0 - observed / expected


def _bootstrap(
    pairs: Sequence[Pair],
    statistic: Callable[[Sequence[Pair]], float],
    *,
    resamples: int,
    seed: int,
) -> Estimate:
    """Percentile bootstrap of a statistic over the calibration set.

    Resamples where the statistic is undefined (a draw in which one rater was unanimous, which
    happens on a lopsided set) are dropped rather than replaced by a zero or a one. The reported
    `n` is the number of items, and a run that lost more than a tenth of its resamples is worth
    knowing about, which `TaskCalibration.note` says.
    """
    point = statistic(pairs)
    n = len(pairs)
    if n == 0:
        return Estimate(float("nan"), float("nan"), float("nan"), 0)
    rng = random.Random(seed)
    draws: list[float] = []
    for _ in range(resamples):
        sample = [pairs[rng.randrange(n)] for _ in range(n)]
        value = statistic(sample)
        if not math.isnan(value):
            draws.append(value)
    if not draws:
        return Estimate(point, float("nan"), float("nan"), n)
    draws.sort()
    lo = draws[int(0.025 * len(draws))]
    hi = draws[min(len(draws) - 1, int(0.975 * len(draws)))]
    return Estimate(point, lo, hi, n)


def _rate(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else float("nan")


def _share(flags: Sequence[bool], *, seed: int) -> Estimate:
    """A rate with an interval that has width even at none or all.

    The bootstrap resamples 317 agreements into 317 agreements and printed the first
    calibration's completeness sensitivity as "100.0% (100.0% to 100.0%)", which CLAUDE.md
    calls a bare number: 317 of 317 does not mean the judge never misses. At 0 or n the
    interval is Jeffreys, as Part A does for the refusal classifier; everywhere else it is
    the binomial bootstrap, the same distribution as resampling the items. Only here, not in
    `gate.stats.bootstrap_share`, which the gate's decisions use and which B5 says is
    changed only with the reasoning recorded.
    """
    k = sum(1 for f in flags if f)
    if flags and k in (0, len(flags)):
        return jeffreys_proportion(k, len(flags), seed=seed)
    return bootstrap_share(flags, seed=seed)


@dataclass(frozen=True, slots=True)
class TaskCalibration:
    """One judge on one task, measured against the human labels."""

    task: Task
    judge_key: str
    rubric_hash: str
    counts: Counts
    ungradeable: int  # verdicts the judge did not give in the form asked for
    raw_agreement: float
    kappa: Estimate
    alpha: Estimate
    sensitivity: Estimate
    specificity: Estimate
    # The judge's own pass rate on the calibration set, before correction.
    judge_rate: Estimate
    human_rate: Estimate
    note: str

    @property
    def usable(self) -> bool:
        """B2.3: refused for this task below kappa 0.6. A kappa that could not be computed is
        not usable either; an instrument that cannot be shown to work is not an instrument."""
        return not math.isnan(self.kappa.point) and self.kappa.point >= KAPPA_FLOOR

    @property
    def informative(self) -> float:
        """How much of the judge's agreement is not simply the majority class. Reported so a
        high raw agreement on a lopsided set cannot be mistaken for a good judge."""
        return self.raw_agreement - max(self.human_rate.point, 1 - self.human_rate.point)

    def describe(self) -> str:
        verdict = "usable" if self.usable else f"REFUSED for this task (kappa below {KAPPA_FLOOR})"
        kappa = "no answer" if math.isnan(self.kappa.point) else self.kappa.fmt(pct=False)
        return (
            f"{self.judge_key} on {self.task}: kappa {kappa}, {verdict}. "
            f"sensitivity {self.sensitivity.fmt()}, specificity {self.specificity.fmt()} "
            f"over n = {self.counts.n}."
        )


@dataclass(frozen=True, slots=True)
class CorrectedRate:
    """A pass rate with the judge's own error taken out of it (Rogan-Gladen).

    p = (apparent + specificity - 1) / (sensitivity + specificity - 1)

    The interval propagates three things at once: the sampling of the run being scored, and the
    sampling of the calibration set behind each of sensitivity and specificity. Treating the
    last two as known exactly is the usual shortcut and it produces an interval that is too
    narrow, often by more than the correction itself moved the point.
    """

    apparent: Estimate
    corrected: Estimate
    sensitivity: float
    specificity: float
    # True when sensitivity + specificity <= 1: the judge carries no information in the
    # direction claimed, and the correction is a division by something at or below zero.
    degenerate: bool
    # How often a resample had to be clamped into [0, 1]. A high share means the correction is
    # being driven by the clamp rather than by the data, and the report says so.
    clamped_share: float

    def describe(self) -> str:
        if self.degenerate:
            return (
                f"raw {self.apparent.fmt()}; not corrected: sensitivity plus specificity is "
                f"{self.sensitivity + self.specificity:.3f}, at or below 1, so the judge carries "
                "no information to correct with"
            )
        return f"raw {self.apparent.fmt()}, corrected {self.corrected.fmt()}"


def _rogan_gladen(apparent: float, sensitivity: float, specificity: float) -> float:
    denominator = sensitivity + specificity - 1.0
    if denominator <= 0:
        return float("nan")
    return (apparent + specificity - 1.0) / denominator


def corrected_rate(
    *,
    judge_calls: Sequence[bool],
    calibration: TaskCalibration,
    resamples: int = 2000,
    seed: int = 0,
) -> CorrectedRate:
    """The corrected pass rate for a run the judge scored, and the raw rate beside it.

    `judge_calls` is the judge's verdict on each item of the run being reported, which is a
    different set from the calibration set; the two are resampled independently, which is what
    makes the interval honest about where the uncertainty came from.
    """
    judge_calls = [bool(v) for v in judge_calls]
    n = len(judge_calls)
    apparent_point = _rate(sum(1 for v in judge_calls if v), n)
    apparent = Estimate(apparent_point, float("nan"), float("nan"), n)
    se, sp = calibration.sensitivity.point, calibration.specificity.point
    degenerate = math.isnan(se) or math.isnan(sp) or (se + sp) <= 1.0
    if n == 0:
        nan = float("nan")
        return CorrectedRate(apparent, Estimate(nan, nan, nan, 0), se, sp, True, 0.0)

    rng = random.Random(seed)
    c = calibration.counts
    positives = [True] * c.true_positive + [False] * c.false_negative
    negatives = [False] * c.true_negative + [True] * c.false_positive

    def resample_rate(values: Sequence[bool], *, want: bool = True) -> float:
        """The share of a bootstrap draw from `values` equal to `want`."""
        m = len(values)
        if m == 0:
            return float("nan")
        return sum(1 for _ in range(m) if values[rng.randrange(m)] is want) / m

    apparent_draws: list[float] = []
    corrected_draws: list[float] = []
    clamped = 0
    for _ in range(resamples):
        a = resample_rate(judge_calls)
        apparent_draws.append(a)
        if degenerate:
            continue
        # Sensitivity and specificity are resampled from the calibration set, independently of
        # the run being scored. This is the propagation B2.3 asks for: an interval that treats
        # them as known exactly is narrower than the evidence allows.
        se_d = resample_rate(positives, want=True)
        sp_d = resample_rate(negatives, want=False)
        value = _rogan_gladen(a, se_d, sp_d)
        if math.isnan(value):
            continue
        if value < 0.0 or value > 1.0:
            clamped += 1
            value = min(1.0, max(0.0, value))
        corrected_draws.append(value)

    apparent_draws.sort()
    apparent = Estimate(
        apparent_point,
        apparent_draws[int(0.025 * resamples)],
        apparent_draws[min(resamples - 1, int(0.975 * resamples))],
        n,
    )
    if degenerate or not corrected_draws:
        nan = float("nan")
        return CorrectedRate(apparent, Estimate(nan, nan, nan, n), se, sp, True, 0.0)
    point = min(1.0, max(0.0, _rogan_gladen(apparent_point, se, sp)))
    corrected_draws.sort()
    corrected = Estimate(
        point,
        corrected_draws[int(0.025 * len(corrected_draws))],
        corrected_draws[min(len(corrected_draws) - 1, int(0.975 * len(corrected_draws)))],
        n,
    )
    return CorrectedRate(apparent, corrected, se, sp, False, clamped / len(corrected_draws))


def pairs_for(
    task: Task,
    labels: Mapping[str, GoldLabel],
    verdicts: Mapping[str, JudgeVerdict],
) -> tuple[list[Pair], int]:
    """(human, judge) for every instance both judged, and how many the judge left ungradeable.

    An unparseable verdict is absent rather than counted as a disagreement, exactly as an
    errored call is absent from the drift record's accuracy rather than counted wrong. Counting
    it as disagreement would make a judge that sometimes fails to answer look like a judge that
    sometimes answers wrongly, and those need different fixes.
    """
    pairs: list[Pair] = []
    ungradeable = 0
    for iid, label in sorted(labels.items()):
        verdict = verdicts.get(iid)
        if verdict is None:
            continue
        value = verdict.value(task)
        if value is None:
            ungradeable += 1
            continue
        pairs.append((label.value(task), value))
    return pairs, ungradeable


def calibrate_task(
    task: Task,
    labels: Mapping[str, GoldLabel],
    verdicts: Mapping[str, JudgeVerdict],
    *,
    judge_key: str,
    rubric_hash: str,
    resamples: int = 2000,
    seed: int = 0,
) -> TaskCalibration:
    pairs, ungradeable = pairs_for(task, labels, verdicts)
    counts = counts_of(pairs)
    notes: list[str] = []
    if ungradeable:
        notes.append(f"{ungradeable} verdict(s) not in the two-line form, absent rather than wrong")
    if counts.human_positive == 0 or counts.human_positive == counts.n:
        notes.append(
            "the human labelled every item the same way on this task, so sensitivity or "
            "specificity has no denominator and kappa has little to work with"
        )
    return TaskCalibration(
        task=task,
        judge_key=judge_key,
        rubric_hash=rubric_hash,
        counts=counts,
        ungradeable=ungradeable,
        raw_agreement=agreement(pairs),
        kappa=_bootstrap(pairs, cohens_kappa, resamples=resamples, seed=seed),
        alpha=_bootstrap(
            pairs,
            lambda p: krippendorff_alpha([(h, j) for h, j in p]),
            resamples=resamples,
            seed=seed,
        ),
        # Four shares of yes/no outcomes. Through `_share`, not the generic bootstrap, so that
        # a share of none or all gets an interval with width: the first calibration printed
        # completeness sensitivity as "100.0% (100.0 to 100.0)" over 317 agreements.
        sensitivity=_share([j for h, j in pairs if h], seed=seed),
        specificity=_share([not j for h, j in pairs if not h], seed=seed),
        judge_rate=_share([j for _, j in pairs], seed=seed),
        human_rate=_share([h for h, _ in pairs], seed=seed),
        note="; ".join(notes),
    )


@dataclass(frozen=True, slots=True)
class SelfAgreement:
    """What the judge does when shown the identical stored text twice.

    Temperature 0 and a two-word answer, so this is a floor on the approach's noise. Whatever
    the judge disagrees with itself about, it cannot be measuring.
    """

    task: Task
    paired: int
    disagreements: int
    rate: Estimate


@dataclass(frozen=True, slots=True)
class PositionBias:
    """Whether the judge's verdict moves when the prompt's parts are reordered (B4, B13.3).

    Reported as the paired disagreement rate and McNemar's p on the direction. An absolute
    rubric should have almost none; a pairwise preference judge is expected to have a lot,
    which is the argument for the absolute one.
    """

    task: Task
    paired: int
    disagreements: int
    yes_only_first: int  # yes with the source first, no with the answer first
    yes_only_second: int
    mcnemar_p: float
    rate: Estimate


@dataclass(frozen=True, slots=True)
class VerbosityCheck:
    """Whether answer length predicts the judge's verdict once the human's label is held fixed.

    Within each human class separately, so "longer answers really are better" cannot masquerade
    as bias. What is left is the judge rewarding length for its own sake. The statistic is the
    difference in median characters between the answers it said yes to and the ones it said no
    to, with a bootstrap interval, and a difference whose interval crosses zero is no finding.
    """

    task: Task
    human_label: bool
    n_yes: int
    n_no: int
    median_yes: float
    median_no: float
    difference: Estimate


@dataclass(frozen=True, slots=True)
class Calibration:
    """One judge, everything measured about it."""

    judge_key: str
    rubric_hash: str
    tasks: tuple[TaskCalibration, ...]
    self_agreement: tuple[SelfAgreement, ...]
    position_bias: tuple[PositionBias, ...]
    verbosity: tuple[VerbosityCheck, ...]

    def task(self, task: Task) -> TaskCalibration:
        for t in self.tasks:
            if t.task == task:
                return t
        raise KeyError(task)

    @property
    def usable_tasks(self) -> tuple[Task, ...]:
        return tuple(t.task for t in self.tasks if t.usable)

    @property
    def refused_tasks(self) -> tuple[Task, ...]:
        return tuple(t.task for t in self.tasks if not t.usable)


def _median(values: Sequence[float]) -> float:
    if not values:
        return float("nan")
    s = sorted(values)
    mid = len(s) // 2
    return s[mid] if len(s) % 2 else (s[mid - 1] + s[mid]) / 2


def _median_difference(
    yes: Sequence[float], no: Sequence[float], *, resamples: int, seed: int
) -> Estimate:
    if not yes or not no:
        return Estimate(float("nan"), float("nan"), float("nan"), len(yes) + len(no))
    point = _median(yes) - _median(no)
    rng = random.Random(seed)
    draws = sorted(
        _median([yes[rng.randrange(len(yes))] for _ in yes])
        - _median([no[rng.randrange(len(no))] for _ in no])
        for _ in range(resamples)
    )
    return Estimate(
        point,
        draws[int(0.025 * resamples)],
        draws[min(resamples - 1, int(0.975 * resamples))],
        len(yes) + len(no),
    )


def calibrate(
    labels: Mapping[str, GoldLabel],
    verdicts: Sequence[JudgeVerdict],
    *,
    judge_key: str,
    lengths: Mapping[str, int] | None = None,
    resamples: int = 2000,
    seed: int = 0,
) -> Calibration:
    """Everything B4 asks for, from the stored verdicts and the human labels.

    `verdicts` may contain several readings of the same instance: repeat 0 and 1 for the
    test-retest, and the two positions for the order-bias check. The headline calibration uses
    the first reading in the canonical position, so adding a swap run never moves the kappa
    that was already published.
    """
    canonical = {
        v.instance_id: v for v in verdicts if v.repeat == 0 and v.position == "source_first"
    }
    rubric = next((v.rubric_hash for v in verdicts), "")

    tasks = tuple(
        calibrate_task(
            t,
            labels,
            canonical,
            judge_key=judge_key,
            rubric_hash=rubric,
            resamples=resamples,
            seed=seed,
        )
        for t in TASKS
    )

    repeats = {v.instance_id: v for v in verdicts if v.repeat == 1 and v.position == "source_first"}
    swapped = {v.instance_id: v for v in verdicts if v.repeat == 0 and v.position == "answer_first"}

    self_agreement: list[SelfAgreement] = []
    position: list[PositionBias] = []
    for task in TASKS:
        shared = sorted(
            iid
            for iid in canonical
            if iid in repeats
            and canonical[iid].value(task) is not None
            and repeats[iid].value(task) is not None
        )
        flips = [canonical[i].value(task) != repeats[i].value(task) for i in shared]
        self_agreement.append(
            SelfAgreement(
                task=task,
                paired=len(shared),
                disagreements=sum(flips),
                rate=_share(flips, seed=seed),
            )
        )

        both = sorted(
            iid
            for iid in canonical
            if iid in swapped
            and canonical[iid].value(task) is not None
            and swapped[iid].value(task) is not None
        )
        first_only = sum(1 for i in both if canonical[i].value(task) and not swapped[i].value(task))
        second_only = sum(
            1 for i in both if swapped[i].value(task) and not canonical[i].value(task)
        )
        moved = [canonical[i].value(task) != swapped[i].value(task) for i in both]
        position.append(
            PositionBias(
                task=task,
                paired=len(both),
                disagreements=sum(moved),
                yes_only_first=first_only,
                yes_only_second=second_only,
                mcnemar_p=mcnemar_exact(first_only, second_only),
                rate=_share(moved, seed=seed),
            )
        )

    verbosity: list[VerbosityCheck] = []
    if lengths:
        for task in TASKS:
            for human in (True, False):
                yes: list[float] = []
                no: list[float] = []
                for iid, label in labels.items():
                    v = canonical.get(iid)
                    if v is None or label.value(task) is not human or iid not in lengths:
                        continue
                    said = v.value(task)
                    if said is None:
                        continue
                    (yes if said else no).append(float(lengths[iid]))
                verbosity.append(
                    VerbosityCheck(
                        task=task,
                        human_label=human,
                        n_yes=len(yes),
                        n_no=len(no),
                        median_yes=_median(yes),
                        median_no=_median(no),
                        difference=_median_difference(yes, no, resamples=resamples, seed=seed),
                    )
                )

    return Calibration(
        judge_key=judge_key,
        rubric_hash=rubric,
        tasks=tasks,
        self_agreement=tuple(self_agreement),
        position_bias=tuple(position),
        verbosity=tuple(verbosity),
    )
