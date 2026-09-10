"""The panel: which model identifiers are called, in which arm. PLAN.md section 2.2.

The panel is part of the data, not a configuration to tune. Identifiers are chosen on the day
of the first run and dated; when a vendor retires one, the runner keeps calling it and the
error is the result.
"""

from __future__ import annotations

import datetime as dt
import re
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

ArmKind = Literal["snapshot", "alias", "control"]

# Where each provider lists the models it currently offers. Paths are relative to the
# provider base_url in the boundary configuration.
MODEL_LIST_PATHS: dict[str, str] = {
    "anthropic": "v1/models?limit=100",
    "openai": "models",
    "google": "v1beta/models?pageSize=200",
    "openweights": "models",
}

# A dated identifier ends in YYYYMMDD or YYYY-MM-DD; stripping the date gives the alias
# candidate, which is a pair only when the vendor also offers that undated identifier.
_DATED = re.compile(r"^(?P<base>.+?)[-@](?P<date>\d{8}|\d{4}-\d{2}-\d{2})$")


class Arm(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    key: str = Field(pattern=r"^[a-z0-9-]+$")
    provider: str
    model: str = Field(min_length=1)
    arm: ArmKind
    # Snapshot and alias arms of one family share a family name so the report can overlay them.
    family: str
    weight_hash: str | None = None  # control arm only: the open-weights checkpoint hash

    @property
    def explicit(self) -> str:
        return f"{self.provider}/{self.model}"


class Panel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    version: int
    chosen: dt.date | None
    notes: str = ""
    arms: list[Arm]

    @model_validator(mode="after")
    def _consistent(self) -> Panel:
        keys = [a.key for a in self.arms]
        if len(keys) != len(set(keys)):
            raise ValueError("arm keys must be unique")
        controls = [a for a in self.arms if a.arm == "control"]
        if len(controls) > 1:
            raise ValueError("at most one control arm")
        return self

    @property
    def ready(self) -> bool:
        """The panel can be run only once identifiers were chosen and dated."""
        return self.chosen is not None and all("CHOOSE" not in a.model for a in self.arms)

    def control(self) -> Arm | None:
        for a in self.arms:
            if a.arm == "control":
                return a
        return None


def parse_model_list(provider: str, body: Any) -> list[str]:
    """Model identifiers from a provider's list endpoint, whatever shape it returns."""
    if provider == "google":
        models = body.get("models", []) if isinstance(body, dict) else []
        return sorted(
            str(m.get("name", "")).removeprefix("models/") for m in models if isinstance(m, dict)
        )
    if isinstance(body, dict) and isinstance(body.get("data"), list):
        return sorted(str(m.get("id", "")) for m in body["data"] if isinstance(m, dict))
    if isinstance(body, list):
        return sorted(str(m.get("id", "")) for m in body if isinstance(m, dict))
    return []


def snapshot_alias_pairs(ids: list[str]) -> list[tuple[str, str]]:
    """(dated snapshot, floating alias) pairs: a dated id whose undated form the vendor
    also offers. A vendor with no such pair has nothing to compare an alias against, which
    is itself a finding for the record."""
    available = set(ids)
    pairs: list[tuple[str, str]] = []
    for i in ids:
        m = _DATED.match(i)
        if m and m.group("base") in available:
            pairs.append((i, m.group("base")))
    return pairs


def load_panel(path: Path) -> Panel:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return Panel.model_validate(data)
