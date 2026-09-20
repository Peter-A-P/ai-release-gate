"""The A/A study: the gate run against itself (PLAN.md B5).

Same prompt, same model, both sides, many times. Nothing changed, so every block is a false
block, and the share of blocks is the false-block rate. Target under 5%. A gate that blocks
changes that changed nothing is not a gate; it is a coin.

Part A's record makes this free. Two kinds of pair are cut from it:

- **within** a run: one arm's five repeats split into two disjoint sets, each reduced to one
  verdict per item, one set the baseline and the other the candidate. Same sitting, nothing
  changed but which calls were kept. Every ordered pair of disjoint subsets is used.
- **between** two runs: the same arm in the run of 2026-09-13 and the run of 2026-09-16, four
  days apart, which is too short for any vendor to have changed a model. This is the closer
  cousin of a real gate run: two sittings on two days.

Both rules are scored on every pair: the gate's interval rule, and the rule the gate does not
use, "block whenever the candidate's point estimate is lower" (B13 candidate 2), so the cost
of gating on a point is a measured number rather than an assertion.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from itertools import combinations
from typing import Literal

from drift.analysis.stats import Estimate, bootstrap_mean
from drift.runner.records import CallRecord
from gate.decision import decide
from gate.outcomes import Side, side_from_records
from gate.spec import EvalSpec

Kind = Literal["within", "between"]


@dataclass(frozen=True, slots=True)
class Pair:
    kind: Kind
    arm: str
    baseline: Side
    candidate: Side


@dataclass(frozen=True, slots=True)
class PairOutcome:
    kind: Kind
    arm: str
    label: str
    blocked: bool
    point_rule_blocked: bool
    blocked_suites: tuple[str, ...]
    point_blocked_suites: tuple[str, ...]
    under_powered_suites: tuple[str, ...]
    suites: int

    @property
    def decided(self) -> int:
        return self.suites - len(self.under_powered_suites)


@dataclass(frozen=True, slots=True)
class AAStudy:
    spec_name: str
    spec_hash: str
    pairs: tuple[PairOutcome, ...]

    @property
    def n(self) -> int:
        return len(self.pairs)

    def of_kind(self, kind: Kind) -> AAStudy:
        return AAStudy(
            self.spec_name, self.spec_hash, tuple(p for p in self.pairs if p.kind == kind)
        )

    @property
    def kinds(self) -> tuple[Kind, ...]:
        order: tuple[Kind, ...] = ("within", "between")
        return tuple(k for k in order if any(p.kind == k for p in self.pairs))

    def false_block_rate(self, *, seed: int = 0) -> Estimate:
        return bootstrap_mean([1.0 if p.blocked else 0.0 for p in self.pairs], seed=seed)

    def point_rule_rate(self, *, seed: int = 0) -> Estimate:
        return bootstrap_mean([1.0 if p.point_rule_blocked else 0.0 for p in self.pairs], seed=seed)

    def mean_decided(self) -> float:
        """How many suites the power screen let through to a decision, on average per pair.
        The false-block rate of a setting that decides nothing is zero and means nothing,
        which is why this stands next to it."""
        return sum(p.decided for p in self.pairs) / self.n if self.n else float("nan")

    @property
    def suites(self) -> int:
        return self.pairs[0].suites if self.pairs else 0

    def blocks_by_suite(self) -> dict[str, int]:
        return dict(sorted(Counter(s for p in self.pairs for s in p.blocked_suites).items()))

    def point_blocks_by_suite(self) -> dict[str, int]:
        return dict(sorted(Counter(s for p in self.pairs for s in p.point_blocked_suites).items()))

    def blocks_by_arm(self) -> dict[str, tuple[int, int]]:
        """arm -> (pairs, blocks)."""
        out: dict[str, tuple[int, int]] = {}
        for p in self.pairs:
            n, b = out.get(p.arm, (0, 0))
            out[p.arm] = (n + 1, b + (1 if p.blocked else 0))
        return dict(sorted(out.items()))

    def under_powered_suites(self) -> tuple[str, ...]:
        seen: set[str] = set()
        for p in self.pairs:
            seen.update(p.under_powered_suites)
        return tuple(sorted(seen))


def repeat_splits(
    repeats: Sequence[int], size: int
) -> list[tuple[tuple[int, ...], tuple[int, ...]]]:
    """Every ordered pair of disjoint `size`-subsets of the repeats. Ordered, because the rule
    is one-sided: a pair that blocks one way round need not block the other."""
    out: list[tuple[tuple[int, ...], tuple[int, ...]]] = []
    for a in combinations(sorted(repeats), size):
        rest = [k for k in repeats if k not in a]
        for b in combinations(rest, size):
            out.append((a, b))
    return out


def within_run_pairs(
    spec: EvalSpec,
    records_by_arm: Mapping[str, Iterable[CallRecord]],
    *,
    month: str,
    size: int = 2,
) -> list[Pair]:
    pairs: list[Pair] = []
    for arm, recs in sorted(records_by_arm.items()):
        recs = list(recs)
        repeats = sorted({r.repeat for r in recs})
        for a, b in repeat_splits(repeats, size):
            src = {"kind": "drift_block", "month": month, "arm": arm}
            pairs.append(
                Pair(
                    "within",
                    arm,
                    side_from_records(
                        spec,
                        recs,
                        label=f"{month}/{arm}@{','.join(map(str, a))}",
                        source={**src, "repeats": ",".join(map(str, a))},
                        repeats=a,
                    ),
                    side_from_records(
                        spec,
                        recs,
                        label=f"{month}/{arm}@{','.join(map(str, b))}",
                        source={**src, "repeats": ",".join(map(str, b))},
                        repeats=b,
                    ),
                )
            )
    return pairs


def between_run_pairs(
    spec: EvalSpec,
    first: Mapping[str, Iterable[CallRecord]],
    second: Mapping[str, Iterable[CallRecord]],
    *,
    first_month: str,
    second_month: str,
) -> list[Pair]:
    """Each arm present in both runs, both ways round."""
    pairs: list[Pair] = []
    for arm in sorted(set(first) & set(second)):
        a = side_from_records(
            spec,
            first[arm],
            label=f"{first_month}/{arm}",
            source={"kind": "drift_block", "month": first_month, "arm": arm, "repeats": "all"},
        )
        b = side_from_records(
            spec,
            second[arm],
            label=f"{second_month}/{arm}",
            source={"kind": "drift_block", "month": second_month, "arm": arm, "repeats": "all"},
        )
        pairs.append(Pair("between", arm, a, b))
        pairs.append(Pair("between", arm, b, a))
    return pairs


def study(spec: EvalSpec, pairs: Iterable[Pair], *, with_power: bool = True) -> AAStudy:
    outcomes: list[PairOutcome] = []
    for p in pairs:
        d = decide(spec, p.baseline, p.candidate, with_power=with_power)
        outcomes.append(
            PairOutcome(
                kind=p.kind,
                arm=p.arm,
                label=f"{p.baseline.label} vs {p.candidate.label}",
                blocked=d.blocked,
                point_rule_blocked=d.point_rule_blocks,
                blocked_suites=tuple(s.suite for s in d.suites if s.verdict == "block"),
                point_blocked_suites=tuple(s.suite for s in d.suites if s.point_rule_blocks),
                under_powered_suites=tuple(s.suite for s in d.suites if s.under_powered),
                suites=len(d.suites),
            )
        )
    return AAStudy(spec.name, spec.sha256(), tuple(outcomes))
