"""The eval spec: what a gate run measures and how much worse it tolerates (PLAN.md B3, B5).

A YAML file, small on purpose (B12: "the eval spec stays small"). It names the suites, where
their items come from, the non-inferiority margin, and the thresholds for the cost and latency
lines. Its content hash goes into every ledger record, so a decision can always be traced to
the exact tolerance it was made under.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

# Where a suite's items and outcomes come from. Stage 1 has one kind: a block of Part A's
# frozen suite, read from the drift record. Later kinds (a project's own item file, a
# red-team suite, a gold set) are added here and nowhere else.
SourceKind = Literal["drift_block"]

_KEY = r"^[a-z][a-z0-9_-]*$"


class Source(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: SourceKind = "drift_block"
    block: str = Field(min_length=1)
    held_out: bool = False


class SuiteSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    key: str = Field(pattern=_KEY)
    source: Source
    # The margin for this suite alone, in accuracy points; the spec's default otherwise.
    delta_points: float | None = Field(default=None, gt=0)
    # Which of project 02's benchmarks these items most resemble, so the local-dependence
    # correction can be looked up (`mselect.dependence()`). None means no correction can be
    # claimed for this suite and none is shown.
    benchmark: str | None = None
    # Whether the dependence-corrected interval decides the suite, or is only shown beside the
    # uncorrected one. Off by default: 02's own v0.2.0 caveat is that the correction is a
    # property of the bank and its panel, not of the benchmark, so carrying it to items sampled
    # here is a claim that has to be earned. The A/A study reports the false-block rate both
    # ways, which is how it gets earned or not.
    correct_for_dependence: bool = False
    # A floor on paired items below which the suite warns instead of blocking, overriding the
    # power analysis. None means `mselect.items_needed` decides.
    min_items: int | None = Field(default=None, ge=1)


class PowerSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    target: float = Field(default=0.8, gt=0, lt=1)
    # The regressions the power table is written for (B1: 1, 3 and 5 points).
    effect_points: tuple[float, ...] = (1.0, 3.0, 5.0)
    # The ability the bank is consulted at when the baseline's score cannot be placed on it.
    reference_ability: float = 0.0


class Threshold(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    # A candidate whose median latency or cost per call rises by more than this share fails
    # on that line (B5), separately from accuracy and labelled as such.
    max_increase_pct: float = Field(gt=0)


class EvalSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    version: Literal[1]
    name: str = Field(pattern=_KEY)
    # B2.2: the candidate fails a suite when the lower bound of the 95% bootstrap interval
    # for (candidate minus baseline) is below minus delta. Three points by default.
    delta_points: float = Field(default=3.0, gt=0)
    alpha: float = Field(default=0.05, gt=0, lt=1)
    resamples: int = Field(default=2000, ge=100)
    seed: int = 0
    suites: tuple[SuiteSpec, ...] = Field(min_length=1)
    power: PowerSpec = PowerSpec()
    latency: Threshold | None = None
    cost: Threshold | None = None

    @model_validator(mode="after")
    def _unique_keys(self) -> EvalSpec:
        seen: set[str] = set()
        for s in self.suites:
            if s.key in seen:
                raise ValueError(f"suite key {s.key!r} appears twice")
            seen.add(s.key)
        return self

    def suite(self, key: str) -> SuiteSpec:
        for s in self.suites:
            if s.key == key:
                return s
        raise KeyError(key)

    def delta_for(self, suite: SuiteSpec) -> float:
        """The margin as a proportion, the unit outcomes are in."""
        return (suite.delta_points if suite.delta_points is not None else self.delta_points) / 100

    def with_delta(self, points: float) -> EvalSpec:
        """The same spec at another margin, with every per-suite override cleared so the
        margin is one number. For the A/A study's table across margins."""
        suites = tuple(s.model_copy(update={"delta_points": None}) for s in self.suites)
        return self.model_copy(update={"delta_points": points, "suites": suites})

    def deciding_every_suite(self) -> EvalSpec:
        """The same spec with the power screen off: every suite is decided however few items
        it has. For the A/A study, so the rule's own false-block rate is measured and not
        only the screen's."""
        suites = tuple(s.model_copy(update={"min_items": 1}) for s in self.suites)
        return self.model_copy(update={"suites": suites})

    def canonical(self) -> str:
        return json.dumps(
            self.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), ensure_ascii=False
        )

    def sha256(self) -> str:
        return hashlib.sha256(self.canonical().encode("utf-8")).hexdigest()


def load_spec(path: Path) -> EvalSpec:
    with path.open(encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    return EvalSpec.model_validate(raw)
