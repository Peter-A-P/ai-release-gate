"""Rule C candidate 3: one call per item, no repeats, and the number that rejects it.

PLAN.md section 10 names this the committed Rule C item: `k = 1, no repeats`, with the
expectation that "every month looks like drift", to be shown by a pair of runs close enough
together that nothing can have changed between them.

**Why anyone would want it.** Repeats are four fifths of the bill. The suite is 420 items
against 8 arms; at k = 5 that is 16,800 calls and about US$20 a month, and at k = 1 it is
3,360 calls and about US$4. A team told that its eval costs five times what it needs to
will ask why, and "we run everything five times" is not an answer by itself. This is the
number that answers it.

**What k = 1 actually costs you.** Not precision in the score, which is the obvious guess
and the wrong one. It is the same-day flip rate: the share of items where a model
contradicts itself across its own repeats in one sitting, with nothing changed. That is the
floor every drift claim in this project has to clear (PLAN.md sections 1 and 4), and it
cannot be computed at all from one call per item. There is nothing to compare a call
against. So a team running k = 1 does not get a noisy floor, it gets no floor, and the only
test left to it is whether the change between two runs is distinguishable from zero.

That test is what this module applies. It takes two runs of the record, reduces each to a
single call per item, and asks the k = 1 question of every arm: is the between-run change
above zero? The runs it is given are four days apart, which is far too short for a vendor
to have shipped anything, and one of the arms is the open-weights control, whose weights
physically cannot change. Every arm the k = 1 rule flags is therefore a false positive, and
every one it flags on the control is false by construction rather than by argument.

**Not a straw man.** The comparison gives k = 1 every advantage that is honestly available:

- the same frozen suite, the same items, the same programmatic graders;
- a real interval rather than a bare point estimate, so it is not rejected for a sin the
  published rule would share;
- every possible single draw, all `repeats x repeats` pairings of which call you happened
  to keep, rather than one arbitrary draw that might have been unlucky;
- the published k = 5 verdict computed by the project's own `drift_declared`, not by a
  reimplementation of it here.

**It can come out the other way.** If the k = 1 rule flags no arm, the report says the
approach was not rejected. The verdict is computed from the counts, not asserted.

Nothing here calls a vendor or touches `drift/runs/`: it reads stored records and reduces
them. No number from it reaches the results table.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from drift.analysis.metrics import (
    ArmMetrics,
    arm_metrics,
    drift_declared,
    item_outcome,
    month_over_month,
)
from drift.analysis.stats import Estimate, bootstrap_mean
from drift.runner.records import CallRecord

# item_id -> repeat index -> the grader's verdict, gradeable calls only
Grades = dict[str, dict[int, bool]]


def grades(records: Iterable[CallRecord]) -> Grades:
    """The gradeable verdicts, by item and repeat. Ungradeable calls are absent rather than
    counted as wrong: an error or a truncation is not evidence about the model (see
    `drift.analysis.metrics`), and a k = 1 draw that lands on one has no verdict at all."""
    by_item: dict[str, dict[int, bool]] = defaultdict(dict)
    for r in records:
        if r.correct is not None:
            by_item[r.item_id][r.repeat] = r.correct
    return dict(by_item)


def majority_outcomes(g: Grades) -> dict[str, bool]:
    """One outcome per item the way the record does it: the majority over the item's
    gradeable repeats, ties counting as incorrect."""
    out: dict[str, bool] = {}
    for item_id, by_repeat in g.items():
        votes = [by_repeat[k] for k in sorted(by_repeat)]
        if votes:
            out[item_id] = sum(votes) * 2 > len(votes)
    return out


def single_draw_outcomes(g: Grades, repeat: int) -> dict[str, bool]:
    """What the record would hold if only this one call had been made."""
    return {item_id: by_repeat[repeat] for item_id, by_repeat in g.items() if repeat in by_repeat}


def flip_rate(prev: dict[str, bool], cur: dict[str, bool], *, seed: int = 0) -> Estimate:
    """The share of paired items whose outcome differs between the two runs."""
    paired = sorted(set(prev) & set(cur))
    return bootstrap_mean([1.0 if prev[i] != cur[i] else 0.0 for i in paired], seed=seed)


def repeats_in(g: Grades) -> int:
    return max((r for by_repeat in g.values() for r in by_repeat), default=-1) + 1


@dataclass(frozen=True, slots=True)
class ArmRepeats:
    arm_key: str
    is_control: bool
    paired_items: int
    # The published rule: majority over repeats, floor and control comparison, from
    # drift.analysis.metrics.
    k5_floor: Estimate
    k5_flip: Estimate
    k5_declared: bool
    # Every single-draw pairing: which call was kept in the baseline run, which in this one.
    k1_flips: tuple[Estimate, ...]
    k1_flagged: int
    # The same-day floor a k = 1 run can offer, and what the published rule then does with
    # it. `arm_metrics` only counts an item towards the floor when it has two or more
    # gradeable calls, so at k = 1 this comes back with n = 0 and `drift_declared` refuses.
    k1_floor: Estimate
    k1_published_rule_declared: bool

    @property
    def pairings(self) -> int:
        return len(self.k1_flips)

    @property
    def k1_median_flip(self) -> Estimate:
        """The middle draw, kept as an estimate rather than reduced to its point: a bare
        percentage is a bug here as much as anywhere else in the record. With an even number
        of pairings this is the lower of the two middle draws, not an average of them, so the
        interval reported belongs to a draw that actually happened."""
        if not self.k1_flips:
            return Estimate(float("nan"), float("nan"), float("nan"), 0)
        ordered = sorted(self.k1_flips, key=lambda e: e.point)
        return ordered[(len(ordered) - 1) // 2]


@dataclass(frozen=True, slots=True)
class RepeatsReport:
    month: str
    baseline: str
    repeats: int
    arms: tuple[ArmRepeats, ...]

    @property
    def pairings(self) -> int:
        return max((a.pairings for a in self.arms), default=0)

    @property
    def k5_declared(self) -> int:
        return sum(1 for a in self.arms if a.k5_declared)

    @property
    def control(self) -> ArmRepeats | None:
        for a in self.arms:
            if a.is_control:
                return a
        return None

    def k1_flagged_at(self, pairing: int) -> int:
        """How many arms the k = 1 rule flags, if this was the draw you happened to keep."""
        return sum(1 for a in self.arms if a.k1_flips[pairing].lo > 0)

    @property
    def k1_flagged_worst(self) -> int:
        return max((self.k1_flagged_at(p) for p in range(self.pairings)), default=0)

    @property
    def k1_flagged_best(self) -> int:
        return min((self.k1_flagged_at(p) for p in range(self.pairings)), default=0)

    @property
    def pairings_with_a_false_call(self) -> int:
        return sum(1 for p in range(self.pairings) if self.k1_flagged_at(p) > 0)

    @property
    def arms_without_a_floor(self) -> int:
        """Arms for which a k = 1 run can state no same-day flip rate at all."""
        return sum(1 for a in self.arms if a.k1_floor.n == 0)

    @property
    def k1_published_rule_declared(self) -> int:
        """What the published rule does when it is handed k = 1 data: with no floor to clear,
        `drift_declared` refuses, so this is the number of arms on which a k = 1 record could
        ever declare drift, however far a model moved."""
        return sum(1 for a in self.arms if a.k1_published_rule_declared)

    @property
    def rejected(self) -> bool:
        """k = 1 is rejected when it declares drift on runs where nothing changed. Read off the
        counts: if no pairing flags an arm, this is False and the report says the approach was
        not rejected.

        Deliberately not folded in here: the missing floor. That one is true by construction
        for any k = 1 record whatsoever, so a verdict that counted it could never come out the
        other way, and a Rule C item that cannot fail is not evidence. It is reported beside
        this as the structural half of the argument and confirmed against the data, not used
        to decide the verdict.
        """
        return self.pairings_with_a_false_call > 0


def analyse(
    baseline: dict[str, list[CallRecord]],
    current: dict[str, list[CallRecord]],
    *,
    month: str,
    baseline_month: str,
    control_key: str | None = None,
    seed: int = 0,
) -> RepeatsReport:
    """Both runs, arm by arm, under the published rule and under k = 1."""
    keys = sorted(set(baseline) & set(current))
    prev_metrics: dict[str, ArmMetrics] = {}
    cur_metrics: dict[str, ArmMetrics] = {}
    for key in keys:
        prev_metrics[key] = arm_metrics(key, baseline[key], seed=seed)
        cur_metrics[key] = arm_metrics(key, current[key], seed=seed)

    moms = {k: month_over_month(prev_metrics[k], cur_metrics[k], seed=seed) for k in keys}
    control_mom = moms.get(control_key) if control_key is not None else None

    arms: list[ArmRepeats] = []
    repeats = 0
    for key in keys:
        prev_g, cur_g = grades(baseline[key]), grades(current[key])
        repeats = max(repeats, repeats_in(prev_g), repeats_in(cur_g))
        prev_majority, cur_majority = majority_outcomes(prev_g), majority_outcomes(cur_g)
        k1: list[Estimate] = []
        for pa in range(repeats_in(prev_g)):
            for pb in range(repeats_in(cur_g)):
                k1.append(
                    flip_rate(
                        single_draw_outcomes(prev_g, pa),
                        single_draw_outcomes(cur_g, pb),
                        seed=seed,
                    )
                )
        # What a k = 1 run hands the published rule: the first call of each item, in both
        # runs, put through exactly the same code path the record uses.
        k1_prev = arm_metrics(key, [r for r in baseline[key] if r.repeat == 0], seed=seed)
        k1_cur = arm_metrics(key, [r for r in current[key] if r.repeat == 0], seed=seed)
        k1_mom = month_over_month(k1_prev, k1_cur, seed=seed)
        arms.append(
            ArmRepeats(
                arm_key=key,
                is_control=key == control_key,
                paired_items=len(set(prev_majority) & set(cur_majority)),
                k5_floor=cur_metrics[key].same_day_flip_rate,
                k5_flip=moms[key].flip_rate,
                k5_declared=drift_declared(
                    moms[key],
                    cur_metrics[key],
                    control_mom if key != control_key else None,
                ),
                k1_flips=tuple(k1),
                k1_flagged=sum(1 for e in k1 if e.lo > 0),
                k1_floor=k1_cur.same_day_flip_rate,
                k1_published_rule_declared=drift_declared(k1_mom, k1_cur, None),
            )
        )
    return RepeatsReport(month=month, baseline=baseline_month, repeats=repeats, arms=tuple(arms))


def _verdict(report: RepeatsReport) -> list[str]:
    n = len(report.arms)
    control = report.control
    lines = [
        "*The structural half, true of any k = 1 record and confirmed here.* A k = 1 run "
        f"states no same-day flip rate on {report.arms_without_a_floor} of {n} arms, because "
        "a floor needs a second call on the same item to compare against and there is none. "
        "`drift_declared` refuses without one, so a k = 1 record can declare drift on "
        f"{report.k1_published_rule_declared} of {n} arms however far a model actually moves. "
        "This one is an argument rather than a finding: it would hold on any two runs, so it "
        "is not what the verdict below turns on.",
        "",
        "*The measured half, which could have come out the other way.* With no floor, the "
        "only test left to a k = 1 team is whether the change is distinguishable from zero. "
        "Between these two runs nothing changed that any vendor could have shipped, and the "
        f"published k = 5 rule agrees: it declared drift on {report.k5_declared} of {n} arms. "
        "Under the k = 1 rule the same record declares drift on "
        f"{report.k1_flagged_best} to {report.k1_flagged_worst} of {n} arms, depending only "
        "on which call you happened to keep, and on "
        f"{report.pairings_with_a_false_call} of {report.pairings} pairings it declares it on "
        "at least one arm.",
        "",
    ]
    if not report.rejected:
        lines.append(
            f"**Not rejected.** Across all {report.pairings} single-draw pairings, k = 1 "
            f"declared drift on no arm of {n}. The expectation in PLAN.md section 10 is not "
            "borne out by these two runs, and the approach is not rejected on this evidence."
        )
        return lines
    lines.append(
        "**Rejected.** Every one of those calls is a false positive: there was nothing "
        "between the two runs for a rule to be right about."
    )
    if control is not None and control.k1_flagged:
        lines += [
            "",
            f"The decisive one is `{control.arm_key}`: fixed weights on fixed hardware, so a "
            "drift call on it is false by construction and not by argument. k = 1 declares "
            f"drift on it in {control.k1_flagged} of {control.pairings} pairings. The "
            "published rule declares it in none.",
        ]
    return lines


def render(report: RepeatsReport) -> str:
    """The Rule C section, in the shape the record's own reports use."""
    n = len(report.arms)
    out: list[str] = [
        f"# Rule C: one call per item, no repeats ({report.month} against {report.baseline})",
        "",
        f"Two full runs of the frozen suite, {report.repeats} calls per item per run, reduced "
        f"to one call per item in every one of the {report.pairings} ways that reduction can "
        "be made. Nothing changed between the runs.",
        "",
        "## What each rule concludes",
        "",
        "| Arm | Paired items | k = 5 same-day floor | k = 5 flip rate (95% CI) | k = 5 drift declared | k = 1 same-day floor | k = 1 flip rate, median draw | k = 1 declares drift |",
        "|---|---:|---|---|---|---|---:|---|",
    ]
    for a in report.arms:
        control = " (control)" if a.is_control else ""
        floor = a.k1_floor.fmt() if a.k1_floor.n else "none, n = 0"
        out.append(
            f"| {a.arm_key}{control} | {a.paired_items} | {a.k5_floor.fmt()} | "
            f"{a.k5_flip.fmt()} | {'yes' if a.k5_declared else 'no'} | {floor} | "
            f"{a.k1_median_flip.fmt()} | {a.k1_flagged} of {a.pairings} draws |"
        )
    out += [
        "",
        "k = 5 declares drift when the between-run flip rate exceeds the upper bound of the "
        "arm's own same-day flip rate and the control's flip rate (PLAN.md sections 1 and 4). "
        "The `k = 1 same-day floor` column is that rule's first input, computed by the same "
        "`arm_metrics` the record uses, from a run reduced to one call per item. An item needs "
        "two gradeable calls before it can contribute a flip, so the column is empty and "
        "`drift_declared` refuses for want of a floor. The last two columns are what is left "
        "once the rule is abandoned: the change, and whether it is distinguishable from zero, "
        "on the same bootstrap interval the record uses.",
        "",
        f"Across all {report.pairings} pairings: k = 1 with the published rule declares drift "
        f"on {report.k1_published_rule_declared} of {n} arms and can never declare more, "
        f"k = 1 without it flags {report.k1_flagged_best} to {report.k1_flagged_worst} of {n}, "
        f"and k = 5 flags {report.k5_declared}.",
        "",
        "## Verdict",
        "",
    ]
    out += _verdict(report)
    out += [
        "",
        "## What this does not say",
        "",
        "It does not say k = 1 produces a worse score. It does not: the accuracy an arm "
        "reports barely moves under a single draw, which is why the idea is tempting. What "
        "k = 1 removes is the floor that says what a movement means. The score survives; the "
        "ability to interpret it does not.",
        "",
        f"Reproduce with `uv run drift rulec repeats --month {report.month} "
        f"--baseline {report.baseline}`. No vendor is called.",
    ]
    return "\n".join(out) + "\n"


def accuracy_spread(records: Sequence[CallRecord], *, seed: int = 0) -> tuple[float, float, float]:
    """The accuracy at k = 5, and the lowest and highest accuracy over the single draws.

    Reported to keep the rejection honest: the argument against k = 1 is not that it moves
    the score around, and this is the number that shows it does not move it much.
    """
    by_item: dict[str, list[CallRecord]] = defaultdict(list)
    for r in records:
        by_item[r.item_id].append(r)
    outcomes = [o for recs in by_item.values() if (o := item_outcome(recs)) is not None]
    k5 = sum(outcomes) / len(outcomes) if outcomes else float("nan")
    g = grades(records)
    accuracies: list[float] = []
    for repeat in range(repeats_in(g)):
        drawn = single_draw_outcomes(g, repeat)
        if drawn:
            accuracies.append(sum(drawn.values()) / len(drawn))
    if not accuracies:
        return k5, float("nan"), float("nan")
    return k5, min(accuracies), max(accuracies)
