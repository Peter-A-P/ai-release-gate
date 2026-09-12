"""Numeric, letter and exact-match graders."""

from __future__ import annotations

import math
import re
from typing import Any, ClassVar

from drift.graders.base import Grade
from drift.graders.normalise import (
    after_answer_marker,
    all_numbers,
    answer_letter,
    last_number,
    normalise,
)

_EDGE_PUNCT = re.compile(r"^[\s\.\,\;\:\!\?\"'\(\)\[\]]+|[\s\.\,\;\:\!\?\"'\(\)\[\]]+$")
# Anything in an expected answer that is not part of a plain number, so that "41" takes the
# numeric path and "41 pounds" or "Dunmorrow" does not.
_NON_NUMERIC = re.compile(r"[^0-9.,\s-]")


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
        """Equality first, then two narrow allowances, because strict equality was measuring
        the wrong thing.

        The first dry run, 2026-09-12: every arm answered `recall-1014` with "41 pounds"
        against an expected "41" and every arm was marked wrong. Nine of the twenty
        long-context items are a bare number, so strict equality made almost half the block a
        test of whether a model repeats the unit, not of whether it found the fact. The item's
        own system prompt already asks for the answer alone; a model that obeys it and adds
        the unit anyway has still recalled the fact.

        So: an answer marker is stripped, and then
        * a numeric expected value matches when the output contains that number and no other.
          "41 pounds" passes; "not 41 but 42" does not, because nothing there says which was
          meant.
        * a worded expected value matches when it appears as a whole word. These are invented
          proper nouns, unique in their passage, so "the village is Dunmorrow" passes.

        The cost is a model naming two candidates and being credited for the right one, which
        this accepts for worded answers and refuses for numeric ones. The benefit is not
        recording a correct answer as wrong, which was happening to every arm at once.
        """
        want = self._form(str(expected["answer"]))
        for candidate in (output, after_answer_marker(output)):
            if self._form(candidate) == want:
                return Grade(True, self._form(candidate), f"want {want!r}")

        got = self._form(after_answer_marker(output))
        wanted_numbers = all_numbers(want)
        if len(wanted_numbers) == 1 and not _NON_NUMERIC.search(want):
            found = all_numbers(got)
            ok = found == wanted_numbers
            return Grade(ok, got, f"want the number {want!r} and no other")
        ok = re.search(rf"(?<!\w){re.escape(want)}(?!\w)", got) is not None
        return Grade(ok, got, f"want {want!r}")
