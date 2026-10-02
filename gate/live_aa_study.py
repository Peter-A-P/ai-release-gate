"""The A/A study at full size, on the live suite (PLAN.md B10 stage 7).

`gate.live_aa` simulates how often the judge-graded suite would block a pull request that
changed nothing, as a function of one number it could not measure: how many of the 100 items
get a different verdict when the same prompt is answered and judged twice. This measures it.

The demo repository's base prompt and model are answered and judged live, `K` times, each time
with no cache, so every run is a fresh draw from the vendors. Every ordered pair of distinct
runs is then put through the gate exactly as `gate check` would put a pull request through it,
with the base branch's spec and the judge's error divided out. Nothing changed between any two
runs, so every block is a false block.

The pairs are not independent: each run appears in `2(K - 1)` of them. So the intervals here
resample runs, not pairs: draw K runs with replacement, take every ordered pair of distinct
draws, and repeat. That is what makes the interval honest about having only K runs behind it.

Making the runs spends money and refuses without the vendor flag; it belongs in the `live-aa`
workflow, and it is resumable. Reading them back is offline.
"""

from __future__ import annotations

import json
import random
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from drift.analysis.stats import Estimate
from gate.decision import decide
from gate.live import LiveSuite
from gate.outcomes import Side, SuiteOutcomes
from gate.spec import EvalSpec

SIDES_FILE = "sides.jsonl"


def side_row(
    index: int, side: Side, live: Mapping[str, LiveSuite], *, spent_usd: float
) -> dict[str, object]:
    """One run, as stored: per suite, each item's verdict, and what the run cost, the judge's
    calls included."""
    return {
        "run": index,
        "spent_usd": spent_usd,
        "label": side.label,
        "source": dict(side.source),
        "suites": {
            key: {
                "outcomes": dict(sorted(s.outcomes.items())),
                "ungradeable_items": s.ungradeable_items,
                "calls": s.calls,
                "latency_p50_ms": s.latency_p50_ms
                if s.latency_p50_ms == s.latency_p50_ms
                else None,
                "cost_usd": s.cost_usd,
                "uncosted_calls": s.uncosted_calls,
                "judge_calls": list(live[key].judge_calls) if key in live else [],
            }
            for key, s in side.suites.items()
        },
    }


def append_side(path: Path, row: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def total_spent(path: Path) -> float:
    """What every stored run paid, answers and judge together."""
    if not path.is_file():
        return 0.0
    with path.open(encoding="utf-8") as f:
        return sum(float(json.loads(line)["spent_usd"]) for line in f if line.strip())


def read_sides(path: Path) -> list[Side]:
    sides: list[Side] = []
    if not path.is_file():
        return sides
    with path.open(encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            d = json.loads(line)
            suites = {
                key: SuiteOutcomes(
                    suite=key,
                    outcomes={k: bool(v) for k, v in s["outcomes"].items()},
                    ungradeable_items=s["ungradeable_items"],
                    calls=s["calls"],
                    latency_p50_ms=(
                        float("nan") if s["latency_p50_ms"] is None else s["latency_p50_ms"]
                    ),
                    cost_usd=s["cost_usd"],
                    uncosted_calls=s["uncosted_calls"],
                )
                for key, s in d["suites"].items()
            }
            sides.append(Side(label=f"run {d['run']}", source=d["source"], suites=suites))
    return sides


@dataclass(frozen=True, slots=True)
class LivePair:
    baseline: int
    candidate: int
    blocked: bool
    # Share of items graded on both sides whose verdict differed.
    discordance: float


@dataclass(frozen=True, slots=True)
class LiveAAStudy:
    spec_name: str
    spec_hash: str
    runs: int
    pairs: tuple[LivePair, ...]
    spent_usd: float

    def _by_runs(self, value: Mapping[tuple[int, int], float], *, seed: int) -> Estimate:
        """A mean over ordered pairs of distinct runs, with an interval that resamples runs."""
        point = sum(value.values()) / len(value)
        rng = random.Random(seed)
        draws: list[float] = []
        for _ in range(2000):
            picked = [rng.randrange(self.runs) for _ in range(self.runs)]
            vals = [
                value[(a, b)]
                for i, a in enumerate(picked)
                for j, b in enumerate(picked)
                if i != j and a != b
            ]
            if vals:
                draws.append(sum(vals) / len(vals))
        draws.sort()
        nan = float("nan")
        if not draws:
            return Estimate(point, nan, nan, len(value))
        return Estimate(
            point,
            draws[int(0.025 * len(draws))],
            draws[min(len(draws) - 1, int(0.975 * len(draws)))],
            len(value),
            clusters=self.runs,
        )

    def false_block_rate(self, *, seed: int = 0) -> Estimate:
        return self._by_runs(
            {(p.baseline, p.candidate): 1.0 if p.blocked else 0.0 for p in self.pairs}, seed=seed
        )

    def discordance(self, *, seed: int = 0) -> Estimate:
        return self._by_runs(
            {(p.baseline, p.candidate): p.discordance for p in self.pairs}, seed=seed
        )


def _discordance(a: Side, b: Side) -> float:
    differ = graded = 0
    for key, s in a.suites.items():
        other = b.suites.get(key)
        if other is None:
            continue
        for item, v in s.outcomes.items():
            w = other.outcomes.get(item)
            if w is None:
                continue
            graded += 1
            differ += v != w
    return differ / graded if graded else float("nan")


def study(
    spec: EvalSpec,
    sides: Sequence[Side],
    *,
    judges: Mapping[str, tuple[int, int, int, int]],
    spent_usd: float = 0.0,
) -> LiveAAStudy:
    pairs = []
    for i, a in enumerate(sides):
        for j, b in enumerate(sides):
            if i == j:
                continue
            d = decide(spec, a, b, judges=judges)
            pairs.append(LivePair(i, j, not d.passed, _discordance(a, b)))
    return LiveAAStudy(spec.name, spec.sha256()[:16], len(sides), tuple(pairs), spent_usd)


def render(s: LiveAAStudy, *, prompt_sha: str, model: str, seed: int = 0) -> str:
    fb = s.false_block_rate(seed=seed)
    disc = s.discordance(seed=seed)
    blocked = sum(p.blocked for p in s.pairs)
    out = [
        "## The A/A study at full size: the live suite against itself",
        "",
        f"Spec `{s.spec_name}` ({s.spec_hash}), model `{model}`, prompt `{prompt_sha}`. "
        f"{s.runs} runs of the same prompt, each answered and judged live with no cache, "
        f"US${s.spent_usd:.2f} in all. Generated by `gate live-aa report`; offline.",
        "",
        "| | |",
        "|---|---|",
        f"| Ordered pairs of distinct runs | {len(s.pairs)} |",
        f"| Blocked, every one a false block | {blocked} |",
        f"| False-block rate | {fb.compact()} |",
        f"| Items whose verdict differed between two runs | {disc.compact()} |",
        "",
        f"Intervals are 95% and resample the {s.runs} runs, not the pairs: every run is in "
        f"{2 * (s.runs - 1)} pairs, so the pairs are not independent evidence. The margin's "
        "reasoning in docs/gate-statistics.md assumed about 4% of items would differ between "
        "two runs, and set ten points from it; the second row is that number, measured.",
    ]
    return "\n".join(out)
