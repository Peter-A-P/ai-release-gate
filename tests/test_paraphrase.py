"""The paraphrase block: the seeded choice of parents, and the rules a paraphrase must meet."""

from __future__ import annotations

from pathlib import Path

import pytest

from drift.items import Item, check_paraphrase, check_paraphrases, numbers_in, write_items
from drift.sampling.paraphrase import (
    N_PARENTS,
    eligible_parents,
    paraphrase_id,
    parents,
)
from drift.suite import load_suite

from .conftest import SYSTEM_MATH, make_items


def gsm8k(i: int, prompt: str, value: float) -> Item:
    return Item(
        id=f"reason-{i:04d}",
        block="closed_form_reasoning",
        system=SYSTEM_MATH,
        prompt=prompt,
        grader="numeric",
        expected={"value": value},
        held_out=False,
        source=f"openai/gsm8k main/test item {i:05d}; sampled 2026-09-10 seed 1",
        licence="MIT",
    )


def para(parent: Item, which: int, prompt: str, **overrides: object) -> Item:
    fields = dict(
        id=paraphrase_id(parent, which),
        block="paraphrase_robustness",
        system=parent.system,
        prompt=prompt,
        grader=parent.grader,
        expected=parent.expected,
        held_out=False,
        source="test",
        licence="MIT",
        parent_id=parent.id,
    )
    fields.update(overrides)
    return Item.model_validate(fields)


PARENT = gsm8k(1017, "Tom has $5,000 and spends 2.5% of it on 3 books. How much is left?", 4875.0)


def test_numbers_in_reads_commas_decimals_and_fractions() -> None:
    assert numbers_in("$5,000 at 2.5% for 3/4 of 12 months.") == ["12", "2.5", "3", "4", "5000"]
    assert numbers_in("no digits") == []


def test_a_good_paraphrase_passes() -> None:
    p = para(PARENT, 1, "Tom starts with $5,000 and uses 2.5% of it to buy 3 books. What remains?")
    assert check_paraphrase(p, PARENT) == []


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        (
            {"prompt": "Tom has $5,000 and spends 2.5% of it on 4 books. How much is left?"},
            "numbers",
        ),
        (
            {"prompt": "Tom has $5,000 and spends 2.5% of it on 3 books.  How much is left?"},
            "not a paraphrase",
        ),
        ({"expected": {"value": 1.0}}, "expected value"),
        ({"grader": "exact", "expected": {"answer": "x"}}, "grader"),
        ({"system": "Other."}, "system prompt"),
        ({"id": "para-1018-p1"}, "does not name its parent"),
    ],
)
def test_a_paraphrase_that_breaks_a_rule_is_named(
    overrides: dict[str, object], message: str
) -> None:
    good = "Tom starts with $5,000 and uses 2.5% of it to buy 3 books. What remains?"
    fields = dict(overrides)
    p = para(PARENT, 1, str(fields.pop("prompt", good)), **fields)
    assert any(message in problem for problem in check_paraphrase(p, PARENT)), check_paraphrase(
        p, PARENT
    )


def test_suite_level_rules_need_the_parent_and_both_paraphrases_distinct() -> None:
    p1 = para(PARENT, 1, "Tom starts with $5,000 and uses 2.5% of it to buy 3 books. What remains?")
    p2 = para(PARENT, 2, "With $5,000 in hand, Tom pays 2.5% of it for 3 books. What is left over?")
    assert check_paraphrases([PARENT, p1, p2]) == []
    assert check_paraphrases([p1, p2]) == [
        "para-1017-p1: parent 'reason-1017' is not in the suite",
        "para-1017-p2: parent 'reason-1017' is not in the suite",
    ]
    assert any("expected exactly p1 and p2" in m for m in check_paraphrases([PARENT, p1]))
    same = para(PARENT, 2, p1.prompt)
    assert any("same text" in m for m in check_paraphrases([PARENT, p1, same]))


def test_load_suite_enforces_the_paraphrase_rules(tmp_path: Path) -> None:
    bad = para(PARENT, 1, "Tom has $6,000 and spends 2.5% of it on 3 books. How much is left?")
    write_items(tmp_path / "v1" / "a.jsonl", [PARENT, bad])
    with pytest.raises(ValueError, match="paraphrase block: para-1017-p1: numbers"):
        load_suite(tmp_path)


def test_parents_are_seeded_gsm8k_only_and_in_id_order() -> None:
    pool = [
        gsm8k(1000 + i, f"Problem {i} with 2 numbers and 3 words.", float(i)) for i in range(1, 41)
    ]
    math = make_items()[:2]  # closed-form reasoning from another source
    assert eligible_parents([*math, *pool]) == pool
    a = parents([*math, *pool], seed=5)
    assert len(a) == N_PARENTS and a == sorted(a, key=lambda it: it.id)
    assert a == parents(pool, seed=5)
    assert a != parents(pool, seed=6)
    with pytest.raises(ValueError, match="only 5 eligible"):
        parents(pool[:5], seed=5)


def test_repo_paraphrase_file_rephrases_exactly_the_seeded_parents() -> None:
    """The file in the suite was written against `drift paraphrase parents`; if the parents
    ever change, or a pair goes missing, the record's provenance is wrong and this says so."""
    root = Path(__file__).resolve().parent.parent / "drift" / "suite"
    suite = load_suite(root)  # this alone enforces the per-item rules
    want = [it.id for it in parents(suite.items, seed=20260927)]
    paras = [it for it in suite.items if it.block == "paraphrase_robustness"]
    assert sorted({it.parent_id or "" for it in paras}) == want
    assert len(paras) == 2 * N_PARENTS
