"""The sampler: which public sources feed which block, and the one-off draw from each.

PLAN.md section 3. Sampling happens once, before the freeze. Everything about the draw is
recorded so a stranger can repeat it: the seed, the exact bytes each source was read from,
how many rows were eligible, why the rest were not, and how many items came from each
stratum. The record is `drift/suite/v1/SOURCES.json`, written beside the items.

Determinism does not rely on upstream row order. Candidates are sorted by their own upstream
id before shuffling, and the shuffle is seeded per source, so adding a source does not
reshuffle the others and a re-ordered upstream file yields the same draw.

Ids: hand-written items own 0001 to 0999 in each block, sampled items 1001 upward. The two
halves of a block therefore never collide, and they live in separate files
(`<block>-<source>.jsonl` here, `<block>-hand.jsonl` for the written ones), which the suite
loader merges. The suite hash is independent of that split.
"""

from __future__ import annotations

import json
import random
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import partial
from pathlib import Path
from typing import Any

from drift.graders import GRADERS, grader
from drift.items import BLOCK_PREFIX, SYSTEM_PROMPTS, Block, Item, check_item, write_items
from drift.runner.run import RunConfig
from drift.sampling.fetch import Fetched, Row, csv_rows, hf_rows
from drift.sampling.sources import (
    Built,
    Candidate,
    build_arc,
    build_gsm8k,
    build_ifeval,
    build_math,
    build_mmlu,
    build_xstest_safe,
    build_xstest_unsafe,
)

SAMPLER_VERSION = 1
DEFAULT_SEED = 20260927  # the first run's date, the same seed the runner shuffles with
SAMPLED_ID_START = 1001
MANIFEST_FILE = "SOURCES.json"
SUITE_HASH_FILE = "SUITE_HASH"

MATH_TYPES = (
    "algebra",
    "counting_and_probability",
    "geometry",
    "intermediate_algebra",
    "number_theory",
    "prealgebra",
    "precalculus",
)
# Ten MMLU subjects, chosen once and written down rather than sampled, so the spread across
# domains is inspectable: two humanities, two law, two medicine and science, two social
# science, two mathematics and computing.
MMLU_SUBJECTS = (
    "abstract_algebra",
    "anatomy",
    "college_computer_science",
    "econometrics",
    "high_school_geography",
    "international_law",
    "jurisprudence",
    "machine_learning",
    "professional_medicine",
    "world_religions",
)
XSTEST_URL = "https://raw.githubusercontent.com/paul-rottger/xstest/main/xstest_prompts.csv"
# The instruction-following block's fixed output budget, read from the runner so the sampler
# cannot draw an item the run could never satisfy (PLAN.md section 2.3 fixes max_tokens).
IFEVAL_MAX_TOKENS = RunConfig().max_tokens["instruction_following"]


class SamplingError(RuntimeError):
    """The draw cannot be made as specified: too few eligible rows, or a frozen suite."""


@dataclass(frozen=True, slots=True)
class HfSplit:
    dataset: str
    config: str
    split: str

    @property
    def part(self) -> str:
        return self.config


@dataclass(frozen=True, slots=True)
class CsvFile:
    url: str
    part: str = "csv"


Fetchable = HfSplit | CsvFile


@dataclass(frozen=True, slots=True)
class SourceSpec:
    name: str
    block: Block
    licence: str
    origin: str  # how the item's `source` field names the upstream set
    target: int
    fetches: tuple[Fetchable, ...]
    build: Callable[[Sequence[tuple[str, Row]]], Built]


SOURCES: tuple[SourceSpec, ...] = (
    SourceSpec(
        name="gsm8k",
        block="closed_form_reasoning",
        licence="MIT",
        origin="openai/gsm8k main/test",
        target=60,
        fetches=(HfSplit("openai/gsm8k", "main", "test"),),
        build=build_gsm8k,
    ),
    SourceSpec(
        name="math",
        block="closed_form_reasoning",
        licence="MIT",
        origin="EleutherAI/hendrycks_math test",
        target=60,
        fetches=tuple(HfSplit("EleutherAI/hendrycks_math", t, "test") for t in MATH_TYPES),
        build=build_math,
    ),
    SourceSpec(
        name="mmlu",
        block="multiple_choice",
        licence="MIT",
        origin="cais/mmlu test",
        target=60,
        fetches=tuple(HfSplit("cais/mmlu", s, "test") for s in MMLU_SUBJECTS),
        build=build_mmlu,
    ),
    SourceSpec(
        name="arc",
        block="multiple_choice",
        licence="CC-BY-SA-4.0",
        origin="allenai/ai2_arc ARC-Challenge/test",
        target=40,
        fetches=(HfSplit("allenai/ai2_arc", "ARC-Challenge", "test"),),
        build=build_arc,
    ),
    SourceSpec(
        name="ifeval",
        block="instruction_following",
        licence="Apache-2.0",
        origin="google/IFEval train",
        target=30,
        fetches=(HfSplit("google/IFEval", "default", "train"),),
        build=partial(build_ifeval, max_tokens=IFEVAL_MAX_TOKENS),
    ),
    SourceSpec(
        name="xstest-safe",
        block="refusal_calibration",
        licence="CC-BY-4.0",
        origin="XSTest v1 safe",
        target=10,
        fetches=(CsvFile(XSTEST_URL),),
        build=build_xstest_safe,
    ),
    SourceSpec(
        name="xstest-unsafe",
        block="refusal_calibration",
        licence="CC-BY-4.0",
        origin="XSTest v1 unsafe",
        target=10,
        fetches=(CsvFile(XSTEST_URL),),
        build=build_xstest_unsafe,
    ),
)


def source(name: str) -> SourceSpec:
    for spec in SOURCES:
        if spec.name == name:
            return spec
    raise KeyError(f"unknown source {name!r}; known: {', '.join(s.name for s in SOURCES)}")


def load_parts(
    spec: SourceSpec, cache: Path, *, refresh: bool = False
) -> tuple[list[tuple[str, Row]], list[Fetched]]:
    """Every row of every fetch this source needs, tagged with the part it came from."""
    parts: list[tuple[str, Row]] = []
    provenance: list[Fetched] = []
    for f in spec.fetches:
        match f:
            case HfSplit(dataset=dataset, config=config, split=split):
                rows, fetched = hf_rows(
                    f"{spec.name}:{config}", dataset, config, split, cache, refresh=refresh
                )
            case CsvFile(url=url):
                rows, fetched = csv_rows(spec.name, url, cache, refresh=refresh)
        parts.extend((f.part, r) for r in rows)
        provenance.append(fetched)
    return parts, provenance


def select(candidates: Sequence[Candidate], target: int, rng: random.Random) -> list[Candidate]:
    """A balanced draw of `target` candidates: round-robin across strata, shuffled within
    each. Balanced by construction rather than in expectation, which matters at these sizes:
    a simple random draw of 60 across 21 MATH strata would leave some empty."""
    by_stratum: dict[str, list[Candidate]] = {}
    for c in sorted(candidates, key=lambda c: c.upstream_id):
        by_stratum.setdefault(c.stratum, []).append(c)
    for stratum in sorted(by_stratum):
        rng.shuffle(by_stratum[stratum])
    chosen: list[Candidate] = []
    while len(chosen) < target:
        took = 0
        for stratum in sorted(by_stratum):
            if len(chosen) >= target:
                break
            if by_stratum[stratum]:
                chosen.append(by_stratum[stratum].pop(0))
                took += 1
        if took == 0:
            break
    if len(chosen) < target:
        raise SamplingError(
            f"only {len(chosen)} eligible candidates for a target of {target}; "
            "widen the source or lower the target in the plan, do not loosen a filter quietly"
        )
    return sorted(chosen, key=lambda c: c.upstream_id)


def rng_for(seed: int, source_name: str) -> random.Random:
    """One generator per source, derived from the run seed by name, so the draw for one
    source never depends on which other sources were sampled."""
    return random.Random(f"{seed}:{source_name}")


@dataclass(frozen=True, slots=True)
class Draw:
    """One source's draw: what was built, what was chosen, and where it came from."""

    spec: SourceSpec
    built: Built
    chosen: tuple[Candidate, ...]
    provenance: tuple[Fetched, ...]

    def strata(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for c in self.chosen:
            counts[c.stratum] = counts.get(c.stratum, 0) + 1
        return dict(sorted(counts.items()))


def draw(
    spec: SourceSpec,
    parts: Sequence[tuple[str, Row]],
    provenance: Sequence[Fetched],
    *,
    seed: int,
) -> Draw:
    built = spec.build(parts)
    chosen = select(built.candidates, spec.target, rng_for(seed, spec.name))
    return Draw(spec=spec, built=built, chosen=tuple(chosen), provenance=tuple(provenance))


def items_for(draws: Sequence[Draw], *, seed: int, sampled_on: str) -> dict[str, list[Item]]:
    """The items for each draw, keyed by source name, with ids assigned.

    Ids run from 1001 per block, in source order then upstream id, so they are stable for a
    given draw and never collide with the hand-written 0001 to 0999.
    """
    counters: dict[str, int] = {}
    out: dict[str, list[Item]] = {}
    for d in draws:
        prefix = BLOCK_PREFIX[d.spec.block]
        n = counters.get(d.spec.block, SAMPLED_ID_START)
        items: list[Item] = []
        for c in d.chosen:
            item = Item(
                id=f"{prefix}-{n:04d}",
                block=d.spec.block,
                system=SYSTEM_PROMPTS[d.spec.block],
                prompt=c.prompt,
                grader=c.grader,
                expected=c.expected,
                held_out=False,
                source=f"{d.spec.origin} item {c.upstream_id}; sampled {sampled_on} seed {seed}",
                licence=d.spec.licence,
            )
            problems = check_item(item, grader_names=GRADERS)
            problems += grader(item.grader).check_expected(item.expected)
            if problems:
                raise SamplingError(f"{item.id} from {d.spec.name}: {'; '.join(problems)}")
            items.append(item)
            n += 1
        counters[d.spec.block] = n
        out[d.spec.name] = items
    return out


def suite_file(root: Path, spec: SourceSpec, version: str = "v1") -> Path:
    return root / version / f"{spec.block}-{spec.name}.jsonl"


def manifest(
    draws: Sequence[Draw], items: dict[str, list[Item]], *, seed: int, sampled_on: str
) -> dict[str, Any]:
    """The record of the draw, written beside the items as SOURCES.json."""
    return {
        "sampler_version": SAMPLER_VERSION,
        "sampled_on": sampled_on,
        "seed": seed,
        "items_total": sum(len(v) for v in items.values()),
        "sources": [
            {
                "name": d.spec.name,
                "block": d.spec.block,
                "licence": d.spec.licence,
                "origin": d.spec.origin,
                "target": d.spec.target,
                "sampled": len(items[d.spec.name]),
                "ids": [items[d.spec.name][0].id, items[d.spec.name][-1].id]
                if items[d.spec.name]
                else [],
                "eligible": len(d.built.candidates),
                "punctuation_normalised": d.built.normalised,
                "rejected": dict(sorted(d.built.rejected.items())),
                "strata": d.strata(),
                "fetches": [f.as_record() for f in d.provenance],
            }
            for d in draws
        ],
    }


def is_frozen(root: Path, version: str = "v1") -> bool:
    return (root / version / SUITE_HASH_FILE).is_file()


def write_draws(
    root: Path,
    draws: Sequence[Draw],
    items: dict[str, list[Item]],
    *,
    seed: int,
    sampled_on: str,
    version: str = "v1",
) -> Path:
    """Write each source's items and the manifest. Refuses on a frozen suite."""
    if is_frozen(root, version):
        raise SamplingError(
            f"{root / version / SUITE_HASH_FILE} exists: suite {version} is frozen and its files "
            "are never edited. A change means a new suite version and a bridging month"
        )
    for d in draws:
        write_items(suite_file(root, d.spec, version), items[d.spec.name])
    path = root / version / MANIFEST_FILE
    path.write_text(
        json.dumps(manifest(draws, items, seed=seed, sampled_on=sampled_on), indent=2) + "\n",
        encoding="utf-8",
    )
    return path


def differences(root: Path, items: dict[str, list[Item]], version: str = "v1") -> list[str]:
    """How the items on disk differ from a fresh draw: the audit path for a frozen suite.

    A source whose file matches line for line says nothing; anything else is listed.
    """
    problems: list[str] = []
    for name, drawn in items.items():
        path = suite_file(root, source(name), version)
        if not path.is_file():
            problems.append(f"{path.name}: missing")
            continue
        on_disk = path.read_text(encoding="utf-8").splitlines()
        fresh = [it.canonical() for it in drawn]
        if on_disk == fresh:
            continue
        same = sum(1 for a, b in zip(on_disk, fresh, strict=False) if a == b)
        problems.append(
            f"{path.name}: {len(on_disk)} lines on disk, {len(fresh)} drawn, {same} identical"
        )
    return problems


def today() -> str:
    return datetime.now(UTC).date().isoformat()
