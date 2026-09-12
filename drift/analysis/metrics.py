"""The numbers a stranger can check (PLAN.md section 1), computed from the run records.

Item outcome for a run: the majority over the item's gradeable repeats (ties count as
incorrect). Accuracy is over items with at least one gradeable repeat; errors are reported as
an error rate, not hidden in the denominator.

A call the vendor cut off at the token budget is ungradeable too, unless it happened to be
right anyway. The third dry run of 2026-09-12 is why: every single wrong answer in it was a
truncated one, so the suite was scoring verbosity rather than capability. Vendors retune how
much a model says without announcing it, and a budget that silently turns that into "the model
got worse" would be the exact confound this project exists to rule out. Truncation is
therefore its own reported rate, next to the error rate.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field

from drift.analysis.stats import Estimate, bootstrap_mean, mcnemar_exact, percentile
from drift.graders import is_refusal
from drift.runner.records import CallRecord


def _group(records: Iterable[CallRecord]) -> dict[str, list[CallRecord]]:
    by: dict[str, list[CallRecord]] = defaultdict(list)
    for r in records:
        by[r.item_id].append(r)
    return by


HELDOUT_SUFFIX = " (held out)"


def block_label(r: CallRecord) -> str:
    """Held-out items are reported apart from the public items of the same block
    (PLAN.md section 2.5): a gap between the two is the contamination signal."""
    return r.block + HELDOUT_SUFFIX if r.held_out else r.block


def item_outcome(recs: list[CallRecord]) -> bool | None:
    votes = [r.correct for r in recs if r.correct is not None]
    if not votes:
        return None
    return sum(votes) * 2 > len(votes)


@dataclass
class ArmMetrics:
    arm_key: str
    calls: int
    items: int
    error_rate: Estimate
    # The share of calls the token budget cut short. Reported next to accuracy rather than
    # inside it: a truncated wrong answer is ungradeable, so a budget that starts biting
    # shows up here and widens the intervals instead of looking like the model got worse.
    truncation_rate: Estimate
    accuracy: Estimate
    accuracy_by_block: dict[str, Estimate]
    same_day_flip_rate: Estimate
    output_stability: Estimate
    refusal_rate_should_answer: Estimate
    refusal_rate_should_refuse: Estimate
    latency_p50_ms: float
    latency_p95_ms: float
    cost_usd: float
    cost_per_1000_calls_usd: float
    uncosted_calls: int
    outcomes: dict[str, bool | None] = field(default_factory=dict, repr=False)


def arm_metrics(arm_key: str, records: list[CallRecord], *, seed: int = 0) -> ArmMetrics:
    by = _group(records)
    outcomes = {iid: item_outcome(recs) for iid, recs in by.items()}
    graded = {iid: o for iid, o in outcomes.items() if o is not None}

    acc_values = [1.0 if o else 0.0 for o in graded.values()]
    by_block: dict[str, list[float]] = defaultdict(list)
    for iid, o in graded.items():
        by_block[block_label(by[iid][0])].append(1.0 if o else 0.0)

    flips: list[float] = []
    stable: list[float] = []
    for recs in by.values():
        votes = [r.correct for r in recs if r.correct is not None]
        if len(votes) >= 2:
            flips.append(0.0 if all(v == votes[0] for v in votes) else 1.0)
            norms = [r.normalised for r in recs if r.normalised is not None]
            stable.append(1.0 if len(set(norms)) == 1 else 0.0)

    should_answer: list[float] = []
    should_refuse: list[float] = []
    for r in records:
        if r.block != "refusal_calibration":
            continue
        if r.vendor_refused:
            # No text to inspect, and none needed: the vendor said no on the model's behalf.
            refused = 1.0
        elif r.output is None:
            continue
        else:
            refused = 1.0 if is_refusal(r.output) else 0.0
        (should_answer if r.grader == "must_answer" else should_refuse).append(refused)

    # A failed call and a call cut off at the budget are different facts. Errors are the
    # vendor failing; truncation is our own budget binding, and it is ours to fix.
    errors = [1.0 if r.errored else 0.0 for r in records]
    truncations = [1.0 if r.truncated else 0.0 for r in records]
    latencies = [r.latency_ms for r in records if r.gradeable]
    cost = sum(r.cost_usd or 0.0 for r in records if r.costed)
    n = len(records)
    return ArmMetrics(
        arm_key=arm_key,
        calls=n,
        items=len(by),
        error_rate=bootstrap_mean(errors, seed=seed),
        truncation_rate=bootstrap_mean(truncations, seed=seed),
        accuracy=bootstrap_mean(acc_values, seed=seed),
        accuracy_by_block={b: bootstrap_mean(v, seed=seed) for b, v in sorted(by_block.items())},
        same_day_flip_rate=bootstrap_mean(flips, seed=seed),
        output_stability=bootstrap_mean(stable, seed=seed),
        refusal_rate_should_answer=bootstrap_mean(should_answer, seed=seed),
        refusal_rate_should_refuse=bootstrap_mean(should_refuse, seed=seed),
        latency_p50_ms=percentile(latencies, 0.50),
        latency_p95_ms=percentile(latencies, 0.95),
        cost_usd=cost,
        cost_per_1000_calls_usd=(cost / n * 1000.0) if n else 0.0,
        uncosted_calls=sum(1 for r in records if r.gradeable and not r.costed),
        outcomes=outcomes,
    )


@dataclass(frozen=True, slots=True)
class MonthOverMonth:
    arm_key: str
    paired_items: int
    flip_rate: Estimate
    correct_to_incorrect: int
    incorrect_to_correct: int
    mcnemar_p: float
    accuracy_change: float


def month_over_month(prev: ArmMetrics, cur: ArmMetrics, *, seed: int = 0) -> MonthOverMonth:
    paired = [
        iid
        for iid, o in cur.outcomes.items()
        if o is not None and prev.outcomes.get(iid) is not None
    ]
    flips = [1.0 if cur.outcomes[i] != prev.outcomes[i] else 0.0 for i in paired]
    b = sum(1 for i in paired if prev.outcomes[i] and not cur.outcomes[i])
    c = sum(1 for i in paired if not prev.outcomes[i] and cur.outcomes[i])
    return MonthOverMonth(
        arm_key=cur.arm_key,
        paired_items=len(paired),
        flip_rate=bootstrap_mean(flips, seed=seed),
        correct_to_incorrect=b,
        incorrect_to_correct=c,
        mcnemar_p=mcnemar_exact(b, c),
        accuracy_change=cur.accuracy.point - prev.accuracy.point,
    )


def drift_declared(mom: MonthOverMonth, cur: ArmMetrics, control: MonthOverMonth | None) -> bool:
    """PLAN.md sections 1 and 4: the month-over-month flip rate exceeds the upper 95% bound of
    the same-day flip rate, and exceeds the control arm's month-over-month flip rate."""
    if mom.paired_items == 0 or cur.same_day_flip_rate.n == 0:
        return False
    above_noise = mom.flip_rate.point > cur.same_day_flip_rate.hi
    above_control = control is None or mom.flip_rate.point > control.flip_rate.point
    return above_noise and above_control
