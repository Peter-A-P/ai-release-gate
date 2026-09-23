"""How often the live, judge-graded suite would block a pull request that changed nothing.

`uv run python -m gate.live_aa` prints the table in docs/gate-statistics.md, "A live,
judge-graded suite". It is a simulation, not a measurement: no two live runs of one prompt
exist yet, and the demo repository's A/A pull request is what will measure the one number this
depends on. What the simulation settles is the shape: how large the margin has to be before an
unchanged prompt passes, as a function of how often an item's verdict differs between two runs.

Both runs are drawn independently from the SAME per-item propensities, so the true rates are
equal and every block is a false block. A share of items are genuinely uncertain (a coin flip
each run); the rest are settled, nine passing to one failing, which is roughly the gold set's
completeness rate. The judge is the licensed one, and its error correction is applied exactly as
`gate check` applies it, because that correction widens the interval and is part of the cost.
"""

from __future__ import annotations

import random
from collections.abc import Sequence
from dataclasses import dataclass

from gate.stats import paired_difference

# google-judge-mid on completeness: true positive, false negative, false positive, true negative.
JUDGE_COUNTS = (317, 0, 18, 145)


@dataclass(frozen=True, slots=True)
class Row:
    uncertain: float
    discordance: float  # observed share of items whose verdict differed between the two runs
    false_block: tuple[tuple[float, float], ...]  # (margin, share of trials blocked)


def simulate(
    *,
    items: int = 100,
    uncertain: Sequence[float] = (0.04, 0.10, 0.20),
    margins: Sequence[float] = (0.03, 0.05, 0.08, 0.10),
    trials: int = 400,
    resamples: int = 500,
    judge_counts: tuple[int, int, int, int] = JUDGE_COUNTS,
    seed: int = 7,
) -> list[Row]:
    rng = random.Random(seed)
    rows = []
    for u in uncertain:
        disc: list[float] = []
        blocked = []
        for delta in margins:
            blocks = 0
            for t in range(trials):
                props = [
                    0.5 if rng.random() < u else (0.99 if rng.random() < 0.9 else 0.01)
                    for _ in range(items)
                ]
                base = {f"q{i}": rng.random() < p for i, p in enumerate(props)}
                cand = {f"q{i}": rng.random() < p for i, p in enumerate(props)}
                disc.append(sum(base[k] != cand[k] for k in base) / items)
                test = paired_difference(
                    base, cand, delta=delta, resamples=resamples, seed=t, judge_counts=judge_counts
                )
                blocks += not test.non_inferior
            blocked.append((delta, blocks / trials))
        rows.append(Row(u, sum(disc) / len(disc), tuple(blocked)))
    return rows


def main() -> None:
    rows = simulate()
    margins = [m for m, _ in rows[0].false_block]
    print("| items differing between two runs | " + " | ".join(f"{m:.0%}" for m in margins) + " |")
    print("|---|" + "---:|" * len(margins))
    for r in rows:
        cells = " | ".join(f"{b:.1%}" for _, b in r.false_block)
        print(f"| {r.discordance:.1%} | {cells} |")


if __name__ == "__main__":
    main()
