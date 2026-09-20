"""The verdict, with its reasons (PLAN.md B2.2, B5).

A candidate passes when every powered suite is non-inferior after Holm's adjustment across the
suites, and its cost and latency lines stay inside their thresholds. A suite with too few
paired items to see the margin warns rather than blocks. Every line of the verdict names the
number it turned on, because a block with no reason is an argument nobody can have.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from drift.analysis.stats import Estimate
from gate.outcomes import Side, SuiteOutcomes
from gate.spec import EvalSpec, SuiteSpec
from gate.stats import (
    PairedTest,
    PowerLine,
    holm,
    items_needed,
    paired_difference,
    variance_inflation,
)

Verdict = Literal["pass", "block", "warn"]

# The candidate is judged against a two-sided 95% interval (B2.2), so the one-sided p-value it
# is equivalent to is tested at half the spec's alpha. Holm is applied at the same level.
ONE_SIDED = 0.5


@dataclass(frozen=True, slots=True)
class SuiteResult:
    suite: str
    baseline: Estimate
    candidate: Estimate
    test: PairedTest
    # The same test with the dependence correction applied, when the suite names a benchmark
    # the bank knows. Shown beside `test` always; it decides only when the spec says so.
    corrected: PairedTest | None
    decides_on_corrected: bool
    power: PowerLine | None
    under_powered: bool
    # Holm-adjusted p_inferior across the powered suites; None for a suite outside the family.
    p_adjusted: float | None
    verdict: Verdict
    reasons: tuple[str, ...]

    @property
    def decisive(self) -> PairedTest:
        if self.decides_on_corrected and self.corrected is not None:
            return self.corrected
        return self.test

    @property
    def point_rule_blocks(self) -> bool:
        """B13 candidate 2, the rule this gate does not use: block whenever the candidate's
        point estimate is lower. Computed so the A/A study can show what it would cost."""
        return self.test.paired_items > 0 and self.test.difference.point < 0


@dataclass(frozen=True, slots=True)
class LineResult:
    """A cost or latency line: the candidate against the baseline, as a share."""

    name: str
    baseline: float | None
    candidate: float | None
    increase_pct: float | None
    max_increase_pct: float
    verdict: Verdict
    reason: str


@dataclass(frozen=True, slots=True)
class Decision:
    spec_name: str
    spec_hash: str
    baseline: str
    candidate: str
    suites: tuple[SuiteResult, ...]
    lines: tuple[LineResult, ...]
    passed: bool
    reasons: tuple[str, ...]

    @property
    def blocked(self) -> bool:
        return not self.passed

    @property
    def point_rule_blocks(self) -> bool:
        return any(s.point_rule_blocks for s in self.suites)


def _line(
    name: str,
    base: float | None,
    cand: float | None,
    *,
    max_increase_pct: float,
    fmt: Callable[[float], str],
) -> LineResult:
    if base is None or cand is None or base <= 0:
        return LineResult(
            name, base, cand, None, max_increase_pct, "warn", f"{name}: not measured on both sides"
        )
    increase = (cand - base) / base * 100
    if increase > max_increase_pct:
        return LineResult(
            name,
            base,
            cand,
            increase,
            max_increase_pct,
            "block",
            f"{name}: {fmt(cand)} against {fmt(base)}, up {increase:.0f}%, more than the "
            f"{max_increase_pct:g}% allowed",
        )
    return LineResult(
        name,
        base,
        cand,
        increase,
        max_increase_pct,
        "pass",
        f"{name}: {fmt(cand)} against {fmt(base)} ({increase:+.0f}%)",
    )


def _suite(
    spec: EvalSpec,
    suite: SuiteSpec,
    base: SuiteOutcomes,
    cand: SuiteOutcomes,
    *,
    with_power: bool,
) -> tuple[SuiteResult, PairedTest]:
    delta = spec.delta_for(suite)
    test = paired_difference(
        base.outcomes, cand.outcomes, delta=delta, resamples=spec.resamples, seed=spec.seed
    )
    corrected: PairedTest | None = None
    if suite.benchmark is not None and test.paired_items > 0:
        infl = variance_inflation(suite.benchmark, test.paired_items)
        if infl is not None:
            corrected = paired_difference(
                base.outcomes,
                cand.outcomes,
                delta=delta,
                resamples=spec.resamples,
                seed=spec.seed,
                inflation=infl,
            )
    decisive = corrected if (suite.correct_for_dependence and corrected is not None) else test

    baseline_acc = base.accuracy(resamples=spec.resamples, seed=spec.seed)
    power: PowerLine | None = None
    needed = suite.min_items
    if needed is None and with_power:
        power = items_needed(
            spec.delta_points if suite.delta_points is None else suite.delta_points,
            power=spec.power.target,
            accuracy=baseline_acc.point if baseline_acc.n else None,
            reference_ability=spec.power.reference_ability,
        )
        needed = power.items
    under_powered = test.paired_items == 0 or (needed is not None and test.paired_items < needed)

    reasons: list[str] = []
    if test.paired_items == 0:
        reasons.append("no item was graded on both sides")
    elif under_powered:
        reasons.append(
            f"{test.paired_items} paired items, fewer than the {needed} needed to see a "
            f"{delta:.0%} drop at {spec.power.target:.0%} power: under-powered, warns only"
        )
    if corrected is not None:
        reasons.append(
            f"local dependence ({suite.benchmark}): {test.paired_items} items are worth about "
            f"{corrected.effective_items:.0f}; corrected interval "
            f"{corrected.difference.lo:+.1%} to {corrected.difference.hi:+.1%}"
            + (" decides" if decisive is corrected else " shown, not used")
        )
    result = SuiteResult(
        suite=suite.key,
        baseline=baseline_acc,
        candidate=cand.accuracy(resamples=spec.resamples, seed=spec.seed),
        test=test,
        corrected=corrected,
        decides_on_corrected=decisive is corrected,
        power=power,
        under_powered=under_powered,
        p_adjusted=None,
        verdict="warn",
        reasons=tuple(reasons),
    )
    return result, decisive


def decide(spec: EvalSpec, baseline: Side, candidate: Side, *, with_power: bool = True) -> Decision:
    """The gate. `with_power=False` skips the bank lookup, for a caller that has set
    `min_items` on every suite or is running the A/A study thousands of times."""
    drafts: list[tuple[SuiteResult, PairedTest]] = []
    for s in spec.suites:
        drafts.append(
            _suite(spec, s, baseline.suites[s.key], candidate.suites[s.key], with_power=with_power)
        )

    powered = [i for i, (r, _) in enumerate(drafts) if not r.under_powered]
    adjusted = holm([drafts[i][1].p_inferior for i in powered])
    level = spec.alpha * ONE_SIDED
    results: list[SuiteResult] = []
    for i, (draft, decisive) in enumerate(drafts):
        if i not in powered:
            results.append(draft)
            continue
        p_adj = adjusted[powered.index(i)]
        d = decisive.difference
        if p_adj <= level:
            verdict: Verdict = "pass"
            why = (
                f"non-inferior: {d.point:+.1%} ({d.lo:+.1%} to {d.hi:+.1%}) over "
                f"{decisive.paired_items} items stays above -{decisive.delta:.0%}"
                f" (p {decisive.p_inferior:.3f}, Holm {p_adj:.3f})"
            )
        else:
            verdict = "block"
            why = (
                f"cannot rule out a {decisive.delta:.0%} drop: {d.point:+.1%} "
                f"({d.lo:+.1%} to {d.hi:+.1%}) over {decisive.paired_items} items, "
                f"{decisive.worse} worse and {decisive.better} better"
                f" (p {decisive.p_inferior:.3f}, Holm {p_adj:.3f})"
            )
        results.append(
            SuiteResult(
                suite=draft.suite,
                baseline=draft.baseline,
                candidate=draft.candidate,
                test=draft.test,
                corrected=draft.corrected,
                decides_on_corrected=draft.decides_on_corrected,
                power=draft.power,
                under_powered=False,
                p_adjusted=p_adj,
                verdict=verdict,
                reasons=(why, *draft.reasons),
            )
        )

    lines: list[LineResult] = []
    if spec.latency is not None or spec.cost is not None:
        base_lat = [s.latency_p50_ms for s in baseline.suites.values() if s.calls]
        cand_lat = [s.latency_p50_ms for s in candidate.suites.values() if s.calls]
        if spec.latency is not None:
            lines.append(
                _line(
                    "latency p50",
                    _median(base_lat),
                    _median(cand_lat),
                    max_increase_pct=spec.latency.max_increase_pct,
                    fmt=lambda v: f"{v:,.0f} ms",
                )
            )
        if spec.cost is not None:
            lines.append(
                _line(
                    "cost per call",
                    _per_call(baseline),
                    _per_call(candidate),
                    max_increase_pct=spec.cost.max_increase_pct,
                    fmt=lambda v: f"US${v:.5f}",
                )
            )

    blocks = [r for r in results if r.verdict == "block"]
    line_blocks = [ln for ln in lines if ln.verdict == "block"]
    reasons = [f"{r.suite}: {r.reasons[0]}" for r in blocks] + [ln.reason for ln in line_blocks]
    warned = [r.suite for r in results if r.under_powered]
    if warned:
        reasons.append("under-powered, not decided: " + ", ".join(warned))
    passed = not blocks and not line_blocks
    if passed:
        n = len(powered)
        reasons.insert(0, f"pass: {n} of {len(results)} suites decided, none inferior")
    return Decision(
        spec_name=spec.name,
        spec_hash=spec.sha256(),
        baseline=baseline.label,
        candidate=candidate.label,
        suites=tuple(results),
        lines=tuple(lines),
        passed=passed,
        reasons=tuple(reasons),
    )


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    s = sorted(values)
    return s[(len(s) - 1) // 2]


def _per_call(side: Side) -> float | None:
    calls = sum(s.calls - s.uncosted_calls for s in side.suites.values())
    cost = sum(s.cost_usd for s in side.suites.values())
    return cost / calls if calls else None
