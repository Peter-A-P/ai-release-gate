"""The second pass: the independent check that a hand-written item's answer key is right.

`docs/writing-items.md` rule 7: write the item, write the expected value, then a day later
check it again without leaning on the first answer. A disagreement means the item is
rewritten or dropped, and the date of the pass goes in `source`, which is what
`drift suite freeze` refuses to proceed without.

The point of this module is that the check is cheap enough to actually do. Each block gets
the cheapest question that still proves what that block needs proved, which is a different
question in each case:

| Block | Question | What agreement proves | Blind |
|---|---|---|---|
| structured_extraction | Type the value for each key, reading the passage | Two careful readers extract the same values | yes |
| instruction_following | Does the prompt state each of these rules? | The prompt says what the checker checks | no |
| refusal_calibration | Answer or refuse? | The expected direction is the obvious one | yes |
| paraphrase_robustness | Do these two ask the same thing? | The rewording did not change the problem | no |

**Extraction is the one that has to stay blind**, and it is the only one. Whether two careful
readers pull the same value out of a passage is exactly the question, and seeing the answer
key first destroys the evidence. So that block prompts key by key with the expected values
withheld, and the item's own grader judges what was typed.

**The other three are comparisons, not derivations.** For instruction following there is no
value to re-derive: the constraints are written down. What can be wrong is the prompt, which
may fail to state what the checker will check, and then every model fails that item every
month for a reason that is not the model's, which is the defect `docs/sampling.md` rejected
372 IFEval rows to avoid. Reading the prompt against the constraints in plain English tests
that directly, and faster than writing an answer would. Satisfiability, the thing writing an
answer would prove, is already proved by machine: `tests/test_hand_items.py` grades a stored
compliant answer against every one of those items.

For paraphrases the parent is the ground truth and it is right there, so the question is
whether the two ask for the same thing. The loader already refuses a paraphrase that changed a
number, the grader or the answer.

`--blind` restores the stronger, slower form for the two comparison blocks: write a compliant
answer, or work out the paraphrase's answer, and let the grader judge it. Worth spending on a
sample rather than on all seventy.

Nothing here calls a model. The judgement is the reviewer's and the grading is the item's own
programmatic grader, exactly as in a run.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from drift.graders import grader
from drift.items import PENDING_MARKER, Item

# The phrase a drafted item carries until it has been through a second pass, and what it is
# replaced by. `PENDING_MARKER` (in drift.items) is the looser word the freeze gate looks for,
# so an item marked pending in any wording cannot reach a frozen suite.
PENDING = "second pass pending"
_PASSED = re.compile(r"second pass \d{4}-\d{2}-\d{2}")
# Drafts were marked in two wordings: the hand-written items say "second pass pending" and the
# paraphrases say "review pending". Both have to clear, or an item can never leave the freeze
# gate however many times it is passed.
_ANY_PENDING = re.compile(r"(?:second pass|review) pending", re.IGNORECASE)
ANSWER, REFUSE = "answer", "refuse"
YES, NO = "yes", "no"
_YES = frozenset({"y", "yes", "t", "true"})
_NO = frozenset({"n", "no", "f", "false"})

# The blocks this tool knows how to ask about: the hand-written ones, plus the paraphrases,
# whose second pass is comparing the rewording with its parent. The sampled and generated
# blocks carry their provenance in the manifests instead.
REVIEWABLE: tuple[str, ...] = (
    "structured_extraction",
    "instruction_following",
    "refusal_calibration",
    "paraphrase_robustness",
)

Kind = Literal["fields", "confirm", "choice", "json", "text"]

# How a JSON type is described when the value is asked for, so nothing has to be typed as JSON.
TYPE_HINT: dict[str, str] = {
    "string": "text",
    "integer": "whole number",
    "number": "number",
    "boolean": "true or false",
    "array": "comma-separated list",
}


class NotReviewableError(ValueError):
    """A block this tool has no sensible question for."""


class FieldError(ValueError):
    """A typed value that is not of the type its key needs."""


@dataclass(frozen=True, slots=True)
class FieldSpec:
    key: str
    json_type: str

    @property
    def hint(self) -> str:
        return TYPE_HINT.get(self.json_type, self.json_type)


@dataclass(frozen=True, slots=True)
class Question:
    """What to put in front of the reviewer for one item, with the answer key withheld."""

    item_id: str
    block: str
    ask: str
    prompt: str
    kind: Kind
    choices: tuple[str, ...] = ()
    # Extraction: the keys to ask for, in the order the item lists them.
    fields: tuple[FieldSpec, ...] = ()
    # Instruction following: the constraints in plain English, including how the checker
    # actually applies them, which is the part a prompt most often fails to say.
    rules: tuple[str, ...] = ()
    # Paraphrase: the parent's prompt, shown beside the reworded one.
    context: str = ""


@dataclass(frozen=True, slots=True)
class Outcome:
    item_id: str
    agreed: bool
    detail: str


def needs_second_pass(item: Item) -> bool:
    return PENDING_MARKER in item.source.casefold()


# --- plain English for the constraint checker ---------------------------------------------


def constraint_sentence(constraint: dict[str, Any]) -> str:
    """One constraint as the checker will actually apply it.

    The parenthetical asides are the point: a prompt that says "at most 40 words" without
    saying the count includes any preamble is a prompt that will fail a well-behaved model.
    """
    kind = str(constraint.get("type"))
    text = str(constraint.get("text", ""))
    n = constraint.get("n")
    match kind:
        case "max_words":
            return f"at most {n} words in the whole reply, counting any preamble or sign-off"
        case "min_words":
            return f"at least {n} words in the whole reply"
        case "contains":
            return f"contains {text!r} somewhere, as a substring (so 'travelling' would count for 'travel')"
        case "not_contains":
            return f"does not contain {text!r} anywhere, as a substring"
        case "contains_word":
            return (
                f"uses {text!r} as a whole word, matched on word boundaries, so a longer word "
                "that merely contains it does NOT count"
            )
        case "not_contains_word":
            return (
                f"never uses {text!r} as a whole word, matched on word boundaries, so a longer "
                "word that merely contains it IS still allowed"
            )
        case "all_caps":
            return "every letter is a capital"
        case "all_lower":
            return "every letter is lowercase, including the first"
        case "json_valid":
            return "the reply parses as JSON (a code fence is stripped first, so a fenced object passes)"
        case "starts_with":
            return f"starts with exactly {text!r}, case-sensitive"
        case "ends_with":
            return f"ends with exactly {text!r}, case-sensitive, with nothing after it, not even a full stop"
        case "n_bullets":
            return f"has exactly {n} bullet lines (a line opening with -, * or '1.' counts as one)"
        case "n_paragraphs":
            return f"has exactly {n} paragraphs, separated by blank lines"
    return f"{kind} {constraint}"


def constraint_sentences(expected: Any) -> tuple[str, ...]:
    return tuple(constraint_sentence(c) for c in expected.get("constraints", []))


# --- extraction fields --------------------------------------------------------------------


def schema_fields(item: Item) -> tuple[FieldSpec, ...]:
    """The keys of an extraction item, in the order the item requires them."""
    schema = item.expected["schema"]
    properties = schema.get("properties", {})
    order = schema.get("required") or list(properties)
    return tuple(
        FieldSpec(key, str(properties.get(key, {}).get("type", "string"))) for key in order
    )


def coerce_field(spec: FieldSpec, text: str) -> Any:
    """A typed value as the JSON value its key needs, so nothing is typed as JSON.

    Thousands separators are accepted on numbers: whether the passage says 14,200 or 14200 is
    a question about writing, not about what the reader read.
    """
    raw = text.strip()
    if spec.json_type == "integer":
        try:
            return int(raw.replace(",", "").replace(" ", ""))
        except ValueError as e:
            raise FieldError(f"{spec.key} needs a whole number, not {raw!r}") from e
    if spec.json_type == "number":
        try:
            return float(raw.replace(",", "").replace(" ", ""))
        except ValueError as e:
            raise FieldError(f"{spec.key} needs a number, not {raw!r}") from e
    if spec.json_type == "boolean":
        if raw.casefold() in _YES:
            return True
        if raw.casefold() in _NO:
            return False
        raise FieldError(f"{spec.key} needs true or false, not {raw!r}")
    if spec.json_type == "array":
        return [part.strip() for part in raw.split(",") if part.strip()]
    return raw


# --- the question -------------------------------------------------------------------------


def default_kind(item: Item, *, blind: bool = False) -> Kind:
    if item.block == "structured_extraction":
        return "fields"
    if item.block == "refusal_calibration":
        return "choice"
    if item.block == "instruction_following":
        return "text" if blind else "confirm"
    if item.block == "paraphrase_robustness":
        return "text" if blind else "confirm"
    raise NotReviewableError(
        f"{item.id}: no second-pass question for block {item.block!r}; "
        f"reviewable blocks are {', '.join(REVIEWABLE)}"
    )


def question_for(item: Item, *, parent: Item | None = None, blind: bool = False) -> Question:
    """The question to ask about this item, with its expected value withheld."""
    kind = default_kind(item, blind=blind)
    if item.block == "structured_extraction":
        return Question(
            item.id,
            item.block,
            "Read the passage and type the value for each key.",
            item.prompt,
            kind,
            fields=schema_fields(item),
        )
    if item.block == "refusal_calibration":
        return Question(
            item.id,
            item.block,
            "Should a well-behaved assistant answer this request, or refuse it?",
            item.prompt,
            kind,
            choices=(ANSWER, REFUSE),
        )
    if item.block == "instruction_following":
        if kind == "text":
            return Question(
                item.id,
                item.block,
                "Write an answer you believe obeys every instruction. The item's own checker"
                " grades it, so if your honest answer fails, the prompt is at fault.",
                item.prompt,
                kind,
            )
        return Question(
            item.id,
            item.block,
            "Does the prompt above state every one of these rules clearly enough that a"
            " careful model would follow them?",
            item.prompt,
            kind,
            rules=constraint_sentences(item.expected),
        )
    if item.block == "paraphrase_robustness":
        if kind == "text":
            return Question(
                item.id,
                item.block,
                "Work out the answer to this problem and type the number, nothing else.",
                item.prompt,
                kind,
            )
        return Question(
            item.id,
            item.block,
            "Do these two ask for the same thing, so that the same answer is correct for both?",
            item.prompt,
            kind,
            context=parent.prompt if parent is not None else "",
        )
    raise NotReviewableError(
        f"{item.id}: no second-pass question for block {item.block!r}; "
        f"reviewable blocks are {', '.join(REVIEWABLE)}"
    )


def judge(item: Item, answer: str, *, kind: Kind | None = None) -> Outcome:
    """Whether what the reviewer said agrees with the item.

    For `fields`, `json` and `text` the item's own grader decides, so agreement means the same
    thing it will mean on run day. For `choice` and `confirm` the reviewer decides and this
    only records it.
    """
    kind = kind or default_kind(item)
    if kind == "choice":
        want = ANSWER if item.grader == "must_answer" else REFUSE
        got = answer.strip().casefold()
        got = ANSWER if got in ("a", ANSWER) else REFUSE if got in ("r", REFUSE) else got
        if got not in (ANSWER, REFUSE):
            return Outcome(item.id, False, f"type a or r, not {answer.strip()!r}")
        return Outcome(item.id, got == want, f"you said {got}, the item expects {want}")
    if kind == "confirm":
        got = answer.strip().casefold()
        if got in _YES:
            return Outcome(item.id, True, "confirmed")
        if got in _NO:
            return Outcome(item.id, False, "you said the item is wrong")
        return Outcome(item.id, False, f"type y or n, not {answer.strip()!r}")
    if not answer.strip():
        return Outcome(item.id, False, "no answer given")
    graded = grader(item.grader).grade(answer, item.expected)
    return Outcome(item.id, graded.correct, graded.detail)


# --- recording ----------------------------------------------------------------------------


def mark_second_pass(item: Item, on: str) -> Item:
    """The item with the pass recorded in `source`, clearing whichever pending marker it
    carried. A marker left behind would keep the item in front of the freeze gate for ever."""
    source = (
        _ANY_PENDING.sub(f"second pass {on}", item.source)
        if _ANY_PENDING.search(item.source)
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


# --- the one-screen view ------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Progress:
    """How much of a file is done, so a session can be stopped and picked up again."""

    total: int
    done: int
    pending: tuple[str, ...] = field(default_factory=tuple)

    @property
    def left(self) -> int:
        return len(self.pending)


def progress_of(items: Sequence[Item]) -> Progress:
    pending = tuple(it.id for it in items if needs_second_pass(it))
    return Progress(total=len(items), done=len(items) - len(pending), pending=pending)


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
