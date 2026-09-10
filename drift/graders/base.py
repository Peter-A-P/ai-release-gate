"""The Grader protocol. Programmatic only; no model ever grades in Part A."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar, Protocol


@dataclass(frozen=True, slots=True)
class Grade:
    correct: bool
    normalised: str
    detail: str = ""


class Grader(Protocol):
    name: ClassVar[str]

    def grade(self, output: str, expected: Any) -> Grade: ...

    def check_expected(self, expected: Any) -> list[str]:
        """Problems with an item's `expected` for this grader; empty when acceptable."""
        ...
