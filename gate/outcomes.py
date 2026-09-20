"""One side of a comparison: for each suite, what every item scored.

The gate never sees raw text. It sees, per side, a mapping from item id to a verdict, which is
the unit the paired test works on. In stage 1 both sides come from Part A's stored records:
one arm in one run, reduced to one verdict per item exactly as the drift report reduces it
(the majority over gradeable repeats, ties incorrect, `drift.analysis.metrics.item_outcome`).
Later sources (a live run through the runner, a judge's labels) produce the same shape.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Collection, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

from drift.analysis.metrics import item_outcome
from drift.analysis.stats import Estimate, percentile
from drift.runner.records import (
    CallRecord,
    arms_recorded,
    load_meta,
    read_records,
    records_path,
)
from gate.spec import EvalSpec, SuiteSpec
from gate.stats import bootstrap_share


@dataclass(frozen=True, slots=True)
class SuiteOutcomes:
    suite: str
    # Gradeable items only. An item every repeat of which errored or was truncated is absent,
    # not wrong (the record's rule), and is counted in `ungradeable_items` instead.
    outcomes: Mapping[str, bool]
    ungradeable_items: int
    calls: int
    latency_p50_ms: float
    cost_usd: float
    uncosted_calls: int

    @property
    def items(self) -> int:
        return len(self.outcomes)

    def accuracy(self, *, resamples: int = 2000, seed: int = 0) -> Estimate:
        values = [v for _, v in sorted(self.outcomes.items())]
        return bootstrap_share(values, resamples=resamples, seed=seed)

    @property
    def cost_per_call_usd(self) -> float | None:
        costed = self.calls - self.uncosted_calls
        return self.cost_usd / costed if costed else None


@dataclass(frozen=True, slots=True)
class Side:
    """A baseline or a candidate: a label for the report and a description for the ledger."""

    label: str
    source: Mapping[str, str]
    suites: Mapping[str, SuiteOutcomes]


def _matches(spec: SuiteSpec, r: CallRecord) -> bool:
    return r.block == spec.source.block and r.held_out is spec.source.held_out


def suite_outcomes(
    spec: SuiteSpec, records: Iterable[CallRecord], *, repeats: Collection[int] | None = None
) -> SuiteOutcomes:
    """Reduce an arm's records to one verdict per item for this suite. `repeats` restricts
    which repeats vote, which is how the A/A study cuts one run into two."""
    by: dict[str, list[CallRecord]] = defaultdict(list)
    calls = 0
    cost = 0.0
    uncosted = 0
    latencies: list[float] = []
    for r in records:
        if not _matches(spec, r) or (repeats is not None and r.repeat not in repeats):
            continue
        by[r.item_id].append(r)
        calls += 1
        if r.costed:
            cost += r.cost_usd or 0.0
        elif r.gradeable:
            uncosted += 1
        if r.gradeable:
            latencies.append(r.latency_ms)
    outcomes: dict[str, bool] = {}
    ungradeable = 0
    for iid, recs in by.items():
        o = item_outcome(recs)
        if o is None:
            ungradeable += 1
        else:
            outcomes[iid] = o
    return SuiteOutcomes(
        suite=spec.key,
        outcomes=outcomes,
        ungradeable_items=ungradeable,
        calls=calls,
        latency_p50_ms=percentile(latencies, 0.50),
        cost_usd=cost,
        uncosted_calls=uncosted,
    )


def side_from_records(
    spec: EvalSpec,
    records: Iterable[CallRecord],
    *,
    label: str,
    source: Mapping[str, str],
    repeats: Collection[int] | None = None,
) -> Side:
    recs = list(records)
    return Side(
        label=label,
        source=dict(source),
        suites={s.key: suite_outcomes(s, recs, repeats=repeats) for s in spec.suites},
    )


class NoSuchArmError(LookupError):
    """The month has no records for that arm."""


def part_a_side(
    runs_root: Path,
    spec: EvalSpec,
    *,
    month: str,
    arm: str,
    repeats: Collection[int] | None = None,
) -> Side:
    """One arm of one Part A run as a side, with the run's own hashes carried into the
    source description so a ledger record names the suite and grader it was scored by."""
    path = records_path(runs_root, month, arm)
    if not path.is_file():
        known = ", ".join(arms_recorded(runs_root, month)) or "none"
        raise NoSuchArmError(f"no records for {arm!r} in {month!r}; arms recorded: {known}")
    recs = list(read_records(path))
    meta = load_meta(runs_root, month, arm)
    generations = sorted({r.graded_by for r in recs if r.graded_by is not None})
    source: dict[str, str] = {
        "kind": "drift_block",
        "month": month,
        "arm": arm,
        "repeats": "all" if repeats is None else ",".join(str(k) for k in sorted(repeats)),
        "graded_by": ";".join(generations) if generations else "unstamped",
    }
    if meta is not None:
        source["run_id"] = meta.run_id
        source["suite_hash"] = meta.suite_hash
        source["suite_version"] = meta.suite_version
    label = f"{month}/{arm}" if repeats is None else f"{month}/{arm}@{source['repeats']}"
    return side_from_records(spec, recs, label=label, source=source, repeats=repeats)
