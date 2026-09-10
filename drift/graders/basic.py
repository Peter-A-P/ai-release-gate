"""Numeric, letter and exact-match graders."""

from __future__ import annotations

import math
import re
from typing import Any, ClassVar

from drift.graders.base import Grade
from drift.graders.normalise import answer_letter, last_number, normalise

_EDGE_PUNCT = re.compile(r"^[\s\.\,\;\:\!\?\"'\(\)\[\]]+|[\s\.\,\;\:\!\?\"'\(\)\[\]]+$")


class NumericGrader:
    """expected: {"value": number, "abs_tol"?: number, "rel_tol"?: number}"""

    name: ClassVar[str] = "numeric"

    def check_expected(self, expected: Any) -> list[str]:
        if not isinstance(expected, dict) or not isinstance(expected.get("value"), int | float):
            return ["expected must be {'value': number, 'abs_tol'?, 'rel_tol'?}"]
        return []

    def grade(self, output: str, expected: Any) -> Grade:
        got = last_number(output)
        want = float(expected["value"])
        abs_tol = float(expected.get("abs_tol", 1e-6))
        rel_tol = float(expected.get("rel_tol", 0.0))
        if got is None:
            return Grade(False, normalise(output), "no number found")
        ok = math.isclose(got, want, abs_tol=abs_tol, rel_tol=rel_tol)
        return Grade(ok, str(got), f"got {got}, want {want}")


class LetterGrader:
    """expected: {"letter": "A" to "E"}"""

    name: ClassVar[str] = "letter"

    def check_expected(self, expected: Any) -> list[str]:
        if not isinstance(expected, dict) or str(expected.get("letter", "")).upper() not in set(
            "ABCDE"
        ):
            return ["expected must be {'letter': 'A'..'E'}"]
        return []

    def grade(self, output: str, expected: Any) -> Grade:
        got = answer_letter(output)
        want = str(expected["letter"]).upper()
        if got is None:
            return Grade(False, normalise(output), "no option letter found")
        return Grade(got == want, got, f"got {got}, want {want}")


class ExactGrader:
    """expected: {"answer": str}. Compared after normalisation and edge-punctuation removal."""

    name: ClassVar[str] = "exact"

    def check_expected(self, expected: Any) -> list[str]:
        if not isinstance(expected, dict) or not isinstance(expected.get("answer"), str):
            return ["expected must be {'answer': str}"]
        return []

    @staticmethod
    def _form(text: str) -> str:
        return _EDGE_PUNCT.sub("", normalise(text))

    def grade(self, output: str, expected: Any) -> Grade:
        got = self._form(output)
        want = self._form(str(expected["answer"]))
        return Grade(got == want, got, f"want {want!r}")
