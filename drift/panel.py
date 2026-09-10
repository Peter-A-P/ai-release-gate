"""The panel: which model identifiers are called, in which arm. PLAN.md section 2.2.

The panel is part of the data, not a configuration to tune. Identifiers are chosen on the day
of the first run and dated; when a vendor retires one, the runner keeps calling it and the
error is the result.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

ArmKind = Literal["snapshot", "alias", "control"]


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


def load_panel(path: Path) -> Panel:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return Panel.model_validate(data)
