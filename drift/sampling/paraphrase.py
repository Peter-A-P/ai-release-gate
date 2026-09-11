"""Paraphrase robustness: which reasoning items get rephrased, and the check on the result.

PLAN.md section 3: forty items, two paraphrases each of twenty closed-form reasoning items,
graded exactly as their parents. The paraphrases themselves are written, not generated
(drafted by the assistant, reviewed by Peter; `docs/writing-items.md`). What this module
fixes from the seed is *which* twenty parents, so the choice is not a hand-pick and can be
re-derived by anyone: `drift paraphrase parents` prints them, and a test asserts the file in
the suite rephrases exactly those.

Only GSM8K parents are eligible (decided 2026-09-11). A GSM8K problem is prose, so a
paraphrase is a rewording of the same situation and the block measures sensitivity to
wording, which is what the plan asks. A MATH problem is mostly notation; rewording it either
changes nothing ("Let $f(x)=2x-4$" has no synonyms) or risks changing the problem.

The rules a paraphrase must meet are in `drift.items.check_paraphrase`, enforced when the
suite loads: same grader, same expected value, every number kept, not the parent verbatim.
The number check is the guard that matters: it catches a paraphrase that quietly changed
a quantity, which would turn a wording item into a different problem.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from drift.items import Item
from drift.sampling.sample import rng_for

N_PARENTS = 20
PARENT_SOURCE_PREFIX = "openai/gsm8k"
SUITE_FILE = "paraphrase_robustness-gsm8k.jsonl"


def eligible_parents(items: Iterable[Item]) -> list[Item]:
    """The GSM8K items of the closed-form reasoning block, in id order."""
    return sorted(
        (
            it
            for it in items
            if it.block == "closed_form_reasoning" and it.source.startswith(PARENT_SOURCE_PREFIX)
        ),
        key=lambda it: it.id,
    )


def parents(items: Iterable[Item], *, seed: int, n: int = N_PARENTS) -> list[Item]:
    """The seeded choice of parents from the eligible items, in id order. The generator is
    derived from the seed and this block's name, like every source in the sampler."""
    pool = eligible_parents(items)
    if len(pool) < n:
        raise ValueError(f"only {len(pool)} eligible parents for {n} paraphrase pairs")
    chosen = rng_for(seed, "paraphrase").sample(pool, n)
    return sorted(chosen, key=lambda it: it.id)


def parent_ids_in(paraphrases: Sequence[Item]) -> list[str]:
    return sorted({it.parent_id for it in paraphrases if it.parent_id})


def paraphrase_id(parent: Item, which: int) -> str:
    """`para-1017-p1` for parent `reason-1017`."""
    return f"para-{parent.id.rsplit('-', 1)[1]}-p{which}"
