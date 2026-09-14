"""Grader registry. Names are what items reference in their `grader` field."""

from drift.graders.base import Grade, Grader
from drift.graders.basic import ExactGrader, LetterGrader, NumericGrader
from drift.graders.constraints import ConstraintsGrader
from drift.graders.refusal import MustAnswerGrader, MustRefuseGrader, is_refusal
from drift.graders.structured import JsonSchemaExactGrader
from drift.graders.version import GRADERS_HASH

GRADERS: dict[str, Grader] = {
    g.name: g
    for g in (
        NumericGrader(),
        LetterGrader(),
        ExactGrader(),
        ConstraintsGrader(),
        JsonSchemaExactGrader(),
        MustAnswerGrader(),
        MustRefuseGrader(),
    )
}


def grader(name: str) -> Grader:
    try:
        return GRADERS[name]
    except KeyError as e:
        raise KeyError(f"unknown grader {name!r}; known: {', '.join(sorted(GRADERS))}") from e


__all__ = ["GRADERS", "GRADERS_HASH", "Grade", "Grader", "grader", "is_refusal"]
