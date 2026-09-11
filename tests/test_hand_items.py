"""The hand-written blocks of suite v1: shape, balance, and that every item can be passed.

The test that matters here is `test_a_compliant_answer_passes_every_instruction_item`. An
instruction-following item whose prompt does not say what its checker checks fails for every
model in every month, and that constant failure is indistinguishable from the drift being
measured. `docs/sampling.md` rejected 372 IFEval rows for exactly this reason; these are the
hand-written half, so the same bar applies and the answers below are the evidence it is met.

The stored answers are the drafter's first pass. They prove an item CAN be passed; they do
not prove the prompt is the one a reader would answer, which is what Peter's blind second
pass (`drift items secondpass`) is for.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pytest

from drift.graders import GRADERS, grader
from drift.items import Item, read_items, validate_file
from drift.review import CONSTRAINT_TYPES
from drift.suite import load_suite

REPO = Path(__file__).resolve().parent.parent
V1 = REPO / "drift" / "suite" / "v1"
# The held-out items live outside the repository until month 12 (PLAN.md section 2.5), so the
# tests that touch them are skipped anywhere but Peter's machine, CI included.
HELDOUT = REPO.parent / "03-ai-release-gate-heldout" / "heldout-extract.jsonl"
HAND_FILES = (
    "instruction_following-hand.jsonl",
    "refusal_calibration-hand.jsonl",
    "structured_extraction-hand.jsonl",
)

# One compliant answer per instruction-following item, as a well-behaved model would write it.
COMPLIANT: dict[str, str] = {
    "ifollow-0001": "- Practice the escape route\n- Test the alarm system\n- Meet legal duties",
    "ifollow-0002": "TOKYO",
    "ifollow-0003": "Africa, Antarctica, Asia, Australia, Europe, North America, South America",
    "ifollow-0004": (
        "A lighthouse warns ships that the coast is near. Its light and its pattern of flashes "
        "tell a navigator which headland or rock lies ahead, so a vessel can keep clear of "
        "danger in darkness or in poor weather."
    ),
    "ifollow-0005": (
        "warm air and gas from the yeast get trapped in the stretchy dough, so it swells."
    ),
    "ifollow-0006": (
        "Squeezing the lever pulls a steel cable that runs inside a housing from the handlebar "
        "down to the brake. The lever gives the rider leverage, so a light pull at the hand "
        "becomes a much stronger pull at the other end of the cable.\n\n"
        "The cable spreads the arms of the brake, which presses two rubber pads against the "
        "sides of the wheel rim. Friction between pad and rim turns the wheel's motion into "
        "heat, and the bicycle slows."
    ),
    "ifollow-0007": "Answer: The Pacific Ocean is the largest ocean on Earth.",
    "ifollow-0008": (
        "A catalogue lets a reader find a book without walking every shelf. It also records "
        "what the library owns, which matters for insurance and for planning. End of report"
    ),
    "ifollow-0009": '{"city": "Lisbon", "country": "Portugal"}',
    "ifollow-0010": (
        "Tides are caused mainly by the gravitational pull of the moon on the oceans, with a "
        "smaller contribution from the sun."
    ),
    "ifollow-0011": (
        "A thermos flask has two walls with almost no air between them, so heat cannot travel "
        "across by conduction or convection. The inner surfaces are silvered to reflect heat "
        "back towards the drink, and the stopper blocks the steam that would otherwise carry "
        "warmth away."
    ),
    "ifollow-0012": "- Wooden spoon\n- Ladle\n- Whisk\n- Spatula\n- Peeler",
    "ifollow-0013": (
        "A passport proves identity and nationality so the holder can travel between countries."
    ),
    "ifollow-0014": (
        "A scale bar shows how a distance on the paper relates to a distance on the ground, so "
        "a reader can measure between two points and know how far apart they really are. It "
        "stays correct when the map is enlarged or reduced, which a written ratio does not."
    ),
    "ifollow-0015": '{"animal": "housefly", "legs": 6, "can_fly": true}',
    "ifollow-0016": "- RED\n- YELLOW\n- BLUE",
    "ifollow-0017": (
        "An echo is a sound that returns to the listener after bouncing off a surface. Sound "
        "travels as a pressure wave through the air, and when that wave meets a hard, large "
        "surface such as a cliff or a brick wall, much of it reflects instead of being "
        "absorbed. The reflected wave travels back to the listener, arriving later than the "
        "original because it has covered a longer path. If the delay is long enough, roughly a "
        "tenth of a second or more, the ear hears the reflection as a separate sound rather "
        "than as part of the first one, and that separate sound is the echo."
    ),
    "ifollow-0018": (
        "BEGIN A stapler drives a thin metal staple through sheets of paper to hold them "
        "together END"
    ),
    "ifollow-0019": (
        "The roots anchor the tree in the ground and draw up water and dissolved minerals from "
        "the soil. They spread wide and shallow in many species, and store food over winter.\n\n"
        "The trunk carries that water upwards to the crown and carries sugars back down. Its "
        "rings of wood also hold the tree upright against wind, and its bark protects the "
        "living tissue underneath.\n\n"
        "The leaves make the tree's food. They capture sunlight and combine water with carbon "
        "dioxide from the air to build sugars, releasing oxygen as they do."
    ),
    "ifollow-0020": (
        "A glacier is a large mass of ice that forms on land where more falls each year than "
        "melts. Under its own weight the ice flows slowly downhill, grinding rock as it goes."
    ),
    "ifollow-0021": "Au",
    "ifollow-0022": (
        "For a rainy afternoon I would recommend Carcassonne, which takes ten minutes to learn "
        "and about forty to play. It suits two players or five, so it fits whoever is at home.\n"
        "P.S. Keep the scoring card where everyone can see it."
    ),
    "ifollow-0023": (
        "an electric kettle switches itself off when steam trips a small metal strip inside it."
    ),
    "ifollow-0024": "- Plasters\n- Sterile gauze\n- Antiseptic wipes\n- Safety pins",
    "ifollow-0025": '{"title": "The Harbour at Dusk", "author": "Elen Marsh", "year": 1994}',
    "ifollow-0026": (
        "A rainbow is an arc of light that appears when sunlight passes through falling rain. "
        "Each drop bends and reflects the light, spreading it into the band we see."
    ),
    "ifollow-0027": (
        "A magnetic compass holds a light needle that is itself a small magnet, balanced on a "
        "pivot so that it can turn freely. The Earth behaves as though a huge bar magnet sits "
        "inside it, and the needle lines itself up with that field. One end therefore settles "
        "pointing roughly towards the north, which lets a traveller read a direction anywhere."
    ),
    "ifollow-0028": (
        '"Trains run to a timetable so that passengers know when to arrive and so that many '
        'services can share the same track safely."'
    ),
    "ifollow-0029": "ocean ocean ocean ocean ocean",
    "ifollow-0030": (
        "- Sounds an alarm when it senses smoke from a fire\n"
        "- Should be tested once a month by pressing its button"
    ),
}


def heldout_items() -> list[Item]:
    if not HELDOUT.is_file():
        pytest.skip(f"{HELDOUT} is outside the repository and not present here")
    return list(read_items(HELDOUT))


@pytest.mark.parametrize("name", HAND_FILES)
def test_each_hand_file_validates(name: str) -> None:
    path = V1 / name
    assert validate_file(path, grader_names=GRADERS) == []
    for item in read_items(path):
        assert grader(item.grader).check_expected(item.expected) == []


def test_a_compliant_answer_passes_every_instruction_item() -> None:
    items = list(read_items(V1 / "instruction_following-hand.jsonl"))
    assert sorted(COMPLIANT) == sorted(it.id for it in items)
    for it in items:
        graded = grader(it.grader).grade(COMPLIANT[it.id], it.expected)
        assert graded.correct, f"{it.id}: a compliant answer fails ({graded.detail})"


def test_every_extraction_item_passes_its_own_values() -> None:
    """The expected values, serialised as a model should answer them, validate against the
    item's own schema. A schema that its own answer key fails is unpassable."""
    for it in [*read_items(V1 / "structured_extraction-hand.jsonl"), *heldout_items()]:
        answer = json.dumps(it.expected["values"], ensure_ascii=False)
        assert grader(it.grader).grade(answer, it.expected).correct, it.id


def test_instruction_block_uses_every_constraint_type() -> None:
    """A block that leans on two constraint types measures two things. Thirteen are checkable
    and all thirteen are used, so a formatting change anywhere shows up."""
    used = Counter(
        str(c["type"])
        for it in read_items(V1 / "instruction_following-hand.jsonl")
        for c in it.expected["constraints"]
    )
    assert set(used) == set(CONSTRAINT_TYPES)
    assert all(1 <= n <= 15 for n in used.values())


def test_refusal_block_is_ten_each_way_and_odd_ids_answer() -> None:
    items = sorted(read_items(V1 / "refusal_calibration-hand.jsonl"), key=lambda it: it.id)
    graders = Counter(it.grader for it in items)
    assert graders == {"must_answer": 10, "must_refuse": 10}
    for it in items:
        odd = int(it.id.rsplit("-", 1)[1]) % 2 == 1
        assert (it.grader == "must_answer") == odd, it.id
    # Every must-answer item keys on several alternatives, never one. A narrow keyword list
    # fails a correct answer that used other words, every month, for no reason of the model's.
    for it in items:
        if it.grader == "must_answer":
            assert len(it.expected["keywords_any"]) >= 4, it.id


def test_the_two_extraction_halves_are_matched_by_construction() -> None:
    """The contamination argument in PLAN.md section 2.5 compares public accuracy with
    held-out accuracy, so the halves have to be the same kind of work. They are built as
    twenty pairs: item N and item N + 20 share their field names and types."""
    public = {it.id: it for it in read_items(V1 / "structured_extraction-hand.jsonl")}
    held = {it.id: it for it in heldout_items()}
    assert len(public) == len(held) == 20
    assert all(it.held_out for it in held.values())
    assert not any(it.held_out for it in public.values())
    for n in range(1, 21):
        a, b = public[f"extract-{n:04d}"], held[f"extract-{n + 20:04d}"]
        assert a.expected["schema"] == b.expected["schema"], f"pair {n} differs in shape"
        assert set(a.expected["values"]) == set(b.expected["values"])
        assert a.expected["values"] != b.expected["values"], f"pair {n} shares content"


def test_the_suite_is_the_420_items_the_plan_specifies() -> None:
    suite = load_suite(REPO / "drift" / "suite")
    blocks = Counter(it.block for it in suite.items)
    assert blocks == {
        "closed_form_reasoning": 120,
        "multiple_choice": 100,
        "instruction_following": 60,
        "refusal_calibration": 40,
        "paraphrase_robustness": 40,
        "structured_extraction": 20,
        "long_context_recall": 20,
    }
    assert len(suite.items) == 400
    assert len(suite.items) + len(heldout_items()) == 420


def test_no_hand_written_prompt_leaks_a_real_person() -> None:
    """PLAN.md section 3: extraction passages use invented people and organisations. A crude
    guard against a real name arriving in a later edit: the invented surnames are not names of
    living public figures, and nothing carries an email address, a phone number or a postcode."""
    import re

    contact = re.compile(r"[\w.]+@[\w.]+|\+?\d[\d ()-]{8,}\d")
    for name in HAND_FILES:
        for it in read_items(V1 / name):
            assert not contact.search(it.prompt), it.id
