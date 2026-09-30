"""The adapter for downstream projects (PLAN.md B9): a side read from a file another project wrote.

    uv run gate compare --spec spec.yaml --baseline baseline.json --candidate candidate.json \\
        --ledger their/ledger.jsonl

A project that grades its own outcomes, with graders the gate knows nothing about, hands over
two things: a spec whose suites have source kind `outcomes_file`, and one JSON file per side, in
the shape of the gate's own `Side` and `SuiteOutcomes`:

    {"label": "...", "source": {"run_id": "...", ...},
     "suites": {"<block>": {"suite": "<block>", "outcomes": {"<item id>": true, ...},
                            "ungradeable_items": 0, "calls": 705, "latency_p50_ms": 812.0,
                            "cost_usd": 1.23, "uncosted_calls": 0}}}

The gate does the rest: the paired test, the power screen, Holm's adjustment across suites, the
cost and latency lines, and the ledger record. It grades nothing and it trusts the file's
grades, so the record names the file by the hash of its bytes, and what a decision was made on
can be checked afterwards by anyone holding the file.

The loader is strict on purpose. An unknown key, a grade that is not a boolean, a suite the
spec names that the file lacks, or a file suite whose own name disagrees with its key is
refused, not guessed at: a comparison of two files read loosely is a comparison of whatever
the loose reading made of them. Project 06 (fraction-of-the-bill) is the first user; its
`smallprint gate export` writes these files.
"""

from __future__ import annotations

import hashlib
import math
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, StrictBool, ValidationError

from gate.outcomes import Side, SuiteOutcomes
from gate.spec import EvalSpec

KIND = "outcomes_file"


class AdapterError(ValueError):
    """A side file that cannot be read as the spec asks."""


class SuiteFile(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    suite: str
    outcomes: dict[str, StrictBool]
    ungradeable_items: int = Field(ge=0)
    calls: int = Field(ge=0)
    latency_p50_ms: float = Field(ge=0)
    cost_usd: float = Field(ge=0)
    uncosted_calls: int = Field(ge=0)


class SideFile(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    label: str = Field(min_length=1)
    source: dict[str, str] = {}
    suites: dict[str, SuiteFile]


def is_side_file(text: str) -> bool:
    """A side argument that names a file rather than MONTH/ARM."""
    return text.endswith(".json")


def load_side(path: Path, spec: EvalSpec) -> Side:
    """One side from a downstream project's file, for every suite of the spec."""
    kinds = {s.source.kind for s in spec.suites}
    if kinds != {KIND}:
        raise AdapterError(
            f"spec {spec.name!r} mixes source kinds {sorted(kinds)}; a side read from a file "
            f"needs every suite to be {KIND}"
        )
    try:
        raw = path.read_bytes()
    except OSError as e:
        raise AdapterError(f"{path}: {e}") from e
    try:
        data = SideFile.model_validate_json(raw)
    except ValidationError as e:
        raise AdapterError(f"{path} is not a side file: {e}") from e
    for key, sf in data.suites.items():
        if sf.suite != key:
            raise AdapterError(f"{path}: suite {key!r} calls itself {sf.suite!r}")
        if sf.uncosted_calls > sf.calls:
            raise AdapterError(f"{path}: suite {key!r} has more uncosted calls than calls")
    missing = [s.source.block for s in spec.suites if s.source.block not in data.suites]
    if missing:
        raise AdapterError(f"{path} has no suite for {missing}")
    suites = {}
    for s in spec.suites:
        f = data.suites[s.source.block]
        suites[s.key] = SuiteOutcomes(
            suite=s.key,
            outcomes=dict(f.outcomes),
            ungradeable_items=f.ungradeable_items,
            calls=f.calls,
            # A side with no answers has no median. The file writes 0 for it; the gate's own
            # sides write NaN, which is what every figure downstream expects.
            latency_p50_ms=f.latency_p50_ms if f.outcomes else math.nan,
            cost_usd=f.cost_usd,
            uncosted_calls=f.uncosted_calls,
        )
    reserved = {"kind", "file", "file_sha256", "label"} & data.source.keys()
    if reserved:
        raise AdapterError(f"{path}: source keys {sorted(reserved)} are the gate's to write")
    source = {
        "kind": KIND,
        "file": path.name,
        "file_sha256": hashlib.sha256(raw).hexdigest(),
        "label": data.label,
        **data.source,
    }
    return Side(label=data.label, source=source, suites=suites)
