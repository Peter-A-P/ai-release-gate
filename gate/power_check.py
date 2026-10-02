"""The power function, checked against this panel (PLAN.md B1: "items needed per effect size,
from `mselect`, validated empirically here").

`mselect.items_needed(delta, 0.8, ability)` says how many items a paired comparison needs to see
a `delta`-point difference four times in five. The gate uses it as its power screen: a suite with
fewer items warns instead of deciding. This asks the same question of real answers instead of
the bank's model.

Where nothing changed, the gate should pass, and the share of times it does is its power at
that margin: a paired test that clears a margin of delta when the truth is 0 has the same
probability as one that detects a difference of delta when the truth is delta, under the normal
approximation the function rests on. So the check is an A/A study by size: for each arm, one
run's repeats split two against two (`gate.aa.within_run_pairs`), the suites' items pooled, and
`n` items drawn at random again and again, each draw put through the gate's own paired test.
The smallest `n` that passes four times in five is the empirical answer, set beside the bank's.

Offline. Calls no vendor and spends nothing.
"""

from __future__ import annotations

import random
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

from drift.analysis.stats import Estimate
from drift.runner.records import CallRecord
from gate.aa import within_run_pairs
from gate.decision import ONE_SIDED
from gate.outcomes import Side
from gate.spec import EvalSpec
from gate.stats import bootstrap_share, items_needed, paired_difference

SIZES: tuple[int, ...] = (40, 60, 80, 120, 160, 240, 320, 400)
DELTAS: tuple[float, ...] = (3.0, 5.0)


@dataclass(frozen=True, slots=True)
class Cell:
    arm: str
    delta_points: float
    items: int
    passed: int
    draws: int
    rate: Estimate  # the share of draws that passed, with its interval


@dataclass(frozen=True, slots=True)
class PowerCheck:
    month: str
    spec_name: str
    spec_hash: str
    cells: tuple[Cell, ...]
    # What the bank asks for at each margin, at the spec's reference ability: the whole bank,
    # and the bank with items of discrimination 0.3 or less dropped.
    predicted: Mapping[float, tuple[int | None, int | None]]

    def arms(self) -> list[str]:
        return sorted({c.arm for c in self.cells})

    def cell(self, arm: str, delta: float, items: int) -> Cell:
        return next(
            c for c in self.cells if (c.arm, c.delta_points, c.items) == (arm, delta, items)
        )

    def smallest_powered(self, arm: str, delta: float, target: float = 0.8) -> int | None:
        """The fewest items at which the gate passed at least `target` of its draws, and kept
        doing so at every larger size tried. None when no size did."""
        sizes = sorted({c.items for c in self.cells if c.arm == arm and c.delta_points == delta})
        best: int | None = None
        for n in reversed(sizes):
            if self.cell(arm, delta, n).rate.point >= target:
                best = n
            else:
                break
        return best


def _pooled(side: Side) -> dict[str, bool]:
    return {f"{k}|{i}": v for k, s in side.suites.items() for i, v in s.outcomes.items()}


def check(
    spec: EvalSpec,
    records_by_arm: Mapping[str, Iterable[CallRecord]],
    *,
    month: str,
    sizes: Sequence[int] = SIZES,
    deltas: Sequence[float] = DELTAS,
    draws: int = 100,
    resamples: int = 400,
    seed: int = 0,
) -> PowerCheck:
    rng = random.Random(seed)
    level = spec.alpha * ONE_SIDED
    by_arm: dict[str, list[tuple[dict[str, bool], dict[str, bool]]]] = {}
    for p in within_run_pairs(spec, records_by_arm, month=month):
        by_arm.setdefault(p.arm, []).append((_pooled(p.baseline), _pooled(p.candidate)))
    cells: list[Cell] = []
    for arm, pairs in sorted(by_arm.items()):
        for delta in deltas:
            for n in sizes:
                outcomes: list[bool] = []
                for _ in range(draws):
                    base, cand = pairs[rng.randrange(len(pairs))]
                    common = sorted(set(base) & set(cand))
                    if len(common) < n:
                        break
                    keys = rng.sample(common, n)
                    test = paired_difference(
                        {k: base[k] for k in keys},
                        {k: cand[k] for k in keys},
                        delta=delta / 100,
                        resamples=resamples,
                        seed=rng.randrange(2**31),
                    )
                    outcomes.append(test.p_inferior <= level)
                if not outcomes:
                    continue
                cells.append(
                    Cell(
                        arm,
                        delta,
                        n,
                        sum(outcomes),
                        len(outcomes),
                        bootstrap_share(outcomes, seed=seed),
                    )
                )

    def asks(d: float, m: float | None) -> int | None:
        return items_needed(
            d,
            power=spec.power.target,
            accuracy=None,
            reference_ability=spec.power.reference_ability,
            min_discrimination=m,
        ).items

    predicted = {d: (asks(d, None), asks(d, 0.3)) for d in deltas}
    return PowerCheck(month, spec.name, spec.sha256()[:16], tuple(cells), predicted)


def render(pc: PowerCheck) -> str:
    out = [
        "## The power function, checked against this panel",
        "",
        f"Spec `{pc.spec_name}` ({pc.spec_hash}), run `{pc.month}`. Generated by "
        "`gate power-check`; offline.",
        "",
        "Each cell is how often the gate passed a comparison in which nothing changed, one run's "
        "repeats split two against two, on that many items drawn at random from the suite's "
        "420. That is the gate's power at the margin: the share should reach 80% at the number "
        "of items `mselect.items_needed` asks for. Intervals are 95% over the draws.",
        "",
    ]
    for delta in sorted({c.delta_points for c in pc.cells}):
        whole, filtered = pc.predicted[delta]
        out += [
            f"### A {delta:g}-point margin",
            "",
            f"The bank asks for **{whole}** items at the reference ability, and **{filtered}** "
            "with its items of discrimination 0.3 or less dropped.",
            "",
        ]
        sizes = sorted({c.items for c in pc.cells if c.delta_points == delta})
        out.append("| Arm | " + " | ".join(f"{n} items" for n in sizes) + " | Reaches 80% at |")
        out.append("|---|" + "---|" * len(sizes) + "---:|")
        for arm in pc.arms():
            cells = [pc.cell(arm, delta, n) for n in sizes]
            got = pc.smallest_powered(arm, delta)
            out.append(
                f"| {arm} | "
                + " | ".join(c.rate.compact() for c in cells)
                + f" | {got if got is not None else f'more than {sizes[-1]}'} |"
            )
        out.append("")
    return "\n".join(out)
