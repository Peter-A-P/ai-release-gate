"""The second pass: a blind re-derivation of a hand-written item's expected value.

`docs/writing-items.md` rule 7: write the item, write the expected value, then a day later
re-derive the expected value from the prompt without looking at the first answer. Any
disagreement means the item is rewritten or dropped, and the date of the pass goes in
`source`. This module is the machinery for that, so the discipline is cheap enough to
actually do and its result is recorded rather than remembered.

What the reviewer is asked for depends on the block, because "re-derive the expected value"
means a different thing in each:

| Block | What the reviewer is asked | What agreement proves |
|---|---|---|
| structured_extraction | Read the passage and type the JSON you expect back | Two readings of the passage agree |
| instruction_following | Write an answer you believe obeys the instructions | The prompt says what the checker checks |
| refusal_calibration | Say whether an assistant should answer or refuse | The expected direction is the obvious one |
| paraphrase_robustness | Work out the answer and type the number | The rewording did not change the problem |

The instruction-following case is the one worth explaining, because there is no value to
re-derive: the constraints are written down in the item. What can be wrong is the prompt,
which may not state what the checker will check. Then every model fails that item every
month for a reason that has nothing to do with the model, and the grader's error is
indistinguishable from the drift being measured, which is the failure `docs/sampling.md`
rejected 372 IFEval rows to avoid. So the reviewer writes an honest answer and the item's own
grader judges it: a failure is the item's fault, not the answer's.

Nothing here calls a model. The judgement is the reviewer's and the grading is the item's own
programmatic grader, exactly as in a run.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from drift.graders import grader
from drift.items import PENDING_MARKER, Item

# The phrase a drafted item carries until it has been through a second pass, and what it is
# replaced by. `PENDING_MARKER` (in drift.items) is the looser word the freeze gate looks for,
# so an item marked pending in any wording cannot reach a frozen suite.
PENDING = "second pass pending"
_PASSED = re.compile(r"second pass \d{4}-\d{2}-\d{2}")
ANSWER, REFUSE = "answer", "refuse"

# The blocks this tool knows how to ask about: the hand-written ones, plus the paraphrases,
# whose second pass is working out the parent's answer from the reworded problem. The sampled
# and generated blocks carry their provenance in the manifests instead.
REVIEWABLE: tuple[str, ...] = (
    "structured_extraction",
    "instruction_following",
    "refusal_calibration",
    "paraphrase_robustness",
)

Kind = Literal["json", "text", "choice"]


class NotReviewableError(ValueError):
    """A block this tool has no sensible question for."""


@dataclass(frozen=True, slots=True)
class Question:
    """What to put in front of the reviewer for one item, with the expected value withheld."""

    item_id: str
    block: str
    ask: str
    prompt: str
    kind: Kind
    choices: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Outcome:
    item_id: str
    agreed: bool
    detail: str


def needs_second_pass(item: Item) -> bool:
    return PENDING_MARKER in item.source.casefold()


def question_for(item: Item) -> Question:
    """The question to ask about this item, without revealing its expected value."""
    if item.block == "structured_extraction":
        return Question(
            item.id,
            item.block,
            "Read the passage and type the JSON object you expect back: the keys and values"
            " exactly as a model should answer them.",
            item.prompt,
            "json",
        )
    if item.block == "instruction_following":
        return Question(
            item.id,
            item.block,
            "Write an answer you believe obeys every instruction. The item's own checker will"
            " grade it, so if your honest answer fails, the prompt does not say what the"
            " checker checks and the item is at fault, not the answer.",
            item.prompt,
            "text",
        )
    if item.block == "refusal_calibration":
        return Question(
            item.id,
            item.block,
            "Should a well-behaved assistant answer this request, or refuse it?",
            item.prompt,
            "choice",
            (ANSWER, REFUSE),
        )
    if item.block == "paraphrase_robustness":
        return Question(
            item.id,
            item.block,
            "Work out the answer to this problem and type the number, nothing else.",
            item.prompt,
            "text",
        )
    raise NotReviewableError(
        f"{item.id}: no second-pass question for block {item.block!r}; "
        f"reviewable blocks are {', '.join(REVIEWABLE)}"
    )


def judge(item: Item, answer: str) -> Outcome:
    """Whether the reviewer's answer agrees with the item, by the item's own grader."""
    if item.block == "refusal_calibration":
        want = ANSWER if item.grader == "must_answer" else REFUSE
        got = answer.strip().casefold()
        if got not in (ANSWER, REFUSE):
            return Outcome(item.id, False, f"type {ANSWER} or {REFUSE}, not {answer.strip()!r}")
        return Outcome(item.id, got == want, f"you said {got}, the item expects {want}")
    if not answer.strip():
        return Outcome(item.id, False, "no answer given")
    graded = grader(item.grader).grade(answer, item.expected)
    return Outcome(item.id, graded.correct, graded.detail)


def mark_second_pass(item: Item, on: str) -> Item:
    """The item with the pass recorded in `source`, replacing the pending marker if present."""
    source = (
        item.source.replace(PENDING, f"second pass {on}")
        if PENDING in item.source
        else f"{item.source}; second pass {on}"
    )
    return item.model_copy(update={"source": source})


def clear_second_pass(item: Item) -> Item:
    """The item marked pending again.

    A later pass that disagrees withdraws the earlier agreement: the item is in doubt, and
    leaving it marked as passed would carry that doubt silently into a frozen suite. Clearing
    it puts the item back in front of the freeze gate, where a person has to settle it.
    """
    if needs_second_pass(item):
        return item
    source = (
        _PASSED.sub(PENDING, item.source)
        if _PASSED.search(item.source)
        else f"{item.source}; {PENDING}"
    )
    return item.model_copy(update={"source": source})


def summary_lines(items: Sequence[Item]) -> list[str]:
    """A one-screen view of a file: what is in it, how it is graded, and what is still
    pending. Used to see at a glance whether a block leans on one constraint type."""
    if not items:
        return ["no items"]
    blocks = Counter(it.block for it in items)
    graders = Counter(it.grader for it in items)
    constraints = Counter(
        str(c.get("type"))
        for it in items
        if it.grader == "constraints"
        for c in it.expected.get("constraints", [])
    )
    fields = Counter(
        str(spec.get("type"))
        for it in items
        if it.grader == "json_schema_exact"
        for spec in it.expected["schema"].get("properties", {}).values()
    )
    held = sum(1 for it in items if it.held_out)
    pending = [it.id for it in items if needs_second_pass(it)]
    lines = [
        f"{len(items)} items, {held} held out, {len(pending)} awaiting a second pass",
        "  blocks:  " + ", ".join(f"{k} {v}" for k, v in sorted(blocks.items())),
        "  graders: " + ", ".join(f"{k} {v}" for k, v in sorted(graders.items())),
    ]
    if constraints:
        lines.append(
            f"  constraint types ({len(constraints)} of {len(CONSTRAINT_TYPES)} used): "
            + ", ".join(f"{k} {v}" for k, v in sorted(constraints.items()))
        )
        unused = sorted(set(CONSTRAINT_TYPES) - set(constraints))
        if unused:
            lines.append("  constraint types not used: " + ", ".join(unused))
    if fields:
        lines.append(
            "  schema field types: " + ", ".join(f"{k} {v}" for k, v in sorted(fields.items()))
        )
    if pending:
        lines.append(
            "  pending: " + ", ".join(pending[:12]) + (" ..." if len(pending) > 12 else "")
        )
    return lines


def _constraint_types() -> tuple[str, ...]:
    from drift.graders.constraints import CHECKS

    return tuple(sorted(CHECKS))


CONSTRAINT_TYPES: tuple[str, ...] = _constraint_types()
