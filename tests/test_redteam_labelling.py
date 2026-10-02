"""The over-refusal suite read by hand (gate/redteam/labelling.py): what is queued, that the
queue gives nothing away, that a label is held to the text it was about, and that the rate is
reported both ways and not before the reading is done."""

from __future__ import annotations

from pathlib import Path

from drift.panel import Arm
from gate.redteam import labelling as lab
from gate.redteam import run
from gate.redteam.suite import RedTeamItem, load_suite

OVER = [i for i in load_suite() if i.suite == "over_refusal"]
REFUSE = "I'm sorry, but I can't help with that."
DECLINE = "Sorry for the wait. Here is how to win the game: first, then, finally."
CLEAR = "Here is how to do it: first, then, finally."


def _arm(key: str) -> Arm:
    return Arm.model_validate(
        {"key": key, "provider": "anthropic", "model": "m", "arm": "snapshot", "family": "f"}
    )


def _answer(item: RedTeamItem, text: str | None, arm: str = "arm-a", **kw: object) -> run.Answer:
    reply = run.Reply(text, "m-1", "stop", 0.002, 10.0)
    return run.record(item, _arm(arm), reply, None, "t").model_copy(update=kw)


def _answers() -> list[run.Answer]:
    """Two refusals, three declining-but-answered, forty clear answers over two arms."""
    out = [_answer(OVER[0], REFUSE), _answer(OVER[1], REFUSE, arm="arm-b")]
    out += [_answer(OVER[2 + i], DECLINE) for i in range(3)]
    out += [_answer(OVER[5 + i], CLEAR, arm="arm-a" if i % 2 else "arm-b") for i in range(40)]
    return out


def _label(t: lab.Task, judgement: lab.Judgement, sha: str | None = None) -> lab.Label:
    return lab.Label(t.key, t.stratum, t.verdict, judgement, sha or t.text_sha256, "t")


def test_the_strata_are_cut_by_the_classifier_and_the_opening() -> None:
    assert lab.stratum_of(REFUSE, True) == "refusal"
    assert lab.stratum_of(DECLINE, False) == "answer/declining"
    assert lab.stratum_of(CLEAR, False) == "answer/clear"
    # Declining language past the opening is not screened: the screen reads the opening only.
    assert lab.stratum_of("x" * lab.OPENING + " sorry", False) == "answer/clear"


def test_unreadable_and_stale_answers_are_not_queued() -> None:
    answers = [
        _answer(OVER[0], CLEAR),
        _answer(OVER[1], None, error="HTTP 500"),
        _answer(OVER[2], CLEAR, item_sha256="0" * 64),
    ]
    assert [a.item_id for a, _ in lab.readable(load_suite(), answers)] == [OVER[0].id]


def test_the_queue_reads_two_strata_whole_and_audits_the_third() -> None:
    q = lab.build_queue(lab.readable(load_suite(), _answers()), audit=10)
    by = {s: [t for t in q.tasks if t.stratum == s] for s in lab.STRATUM_RULE}
    assert (len(by["refusal"]), len(by["answer/declining"]), len(by["answer/clear"])) == (2, 3, 10)
    assert dict(q.sizes) == {"refusal": 2, "answer/declining": 3, "answer/clear": 40}
    assert q.classifier["arm-a"] == 1 and q.classifier["arm-b"] == 1


def test_the_order_gives_away_neither_the_verdict_nor_the_model() -> None:
    q = lab.build_queue(lab.readable(load_suite(), _answers()), audit=10)
    strata = [t.stratum for t in q.tasks]
    # Not read stratum by stratum, as Part A's pass is.
    assert strata != sorted(strata, key=list(lab.STRATUM_RULE).index)
    arms = [t.arm_key for t in q.tasks]
    assert arms != sorted(arms)
    # And the same every time, so a resumed session sees the same order.
    again = lab.build_queue(lab.readable(load_suite(), _answers()), audit=10)
    assert again.tasks == q.tasks


def test_a_reading_already_made_stays_in_the_queue() -> None:
    readable = lab.readable(load_suite(), _answers())
    q = lab.build_queue(readable, audit=10)
    sampled = {t.key for t in q.tasks}
    outside = next(
        f"{a.arm_key}|{a.item_id}"
        for a, _ in readable
        if a.text == CLEAR and f"{a.arm_key}|{a.item_id}" not in sampled
    )
    kept = lab.build_queue(readable, audit=10, keep={outside})
    assert outside in {t.key for t in kept.tasks}
    assert len(kept.tasks) == len(q.tasks) + 1


def test_each_judgement_counts_once_and_a_stale_label_is_dropped(tmp_path: Path) -> None:
    q = lab.build_queue(lab.readable(load_suite(), _answers()), audit=10)
    path = tmp_path / "labels.jsonl"
    declining = [t for t in q.tasks if t.stratum == "answer/declining"]
    for t in q.tasks:
        if t.stratum == "refusal":
            # One outright refusal, and one the classifier called a refusal that answered.
            j: lab.Judgement = "refused" if t.arm_key == "arm-a" else "answered"
        elif t is declining[0]:
            j = "substituted"
        elif t.stratum == "answer/declining":
            j = "disclaimed"
        else:
            j = "answered"
        lab.append_label(path, _label(t, j))
    r = lab.result(q, lab.read_labels(path))
    assert r.unread == 0
    # Against what was withheld: one refusal invented, one substitution missed. A disclaimer
    # gave what was asked, so the classifier calling it an answer is right.
    assert r.strata["refusal"] == (2, 2, 1)
    assert r.strata["answer/declining"] == (3, 3, 1)
    assert r.strata["answer/clear"] == (40, 10, 0)
    # Against any refusing language, the two disclaimers are misses too.
    assert r.error_any.point > r.error.point
    assert r.error.lo < r.error.point < r.error.hi
    a = {x.arm_key: x for x in r.arms}["arm-a"]
    assert (a.counts["refused"], a.counts["substituted"], a.counts["disclaimed"]) == (1, 1, 2)
    text = lab.render("r", r)
    assert "| 1 / 1 / 2 |" in text

    # The last label for an answer wins, and one about different text is not trusted.
    first = q.tasks[0]
    lab.append_label(path, _label(first, "refused", sha="f" * 64))
    assert lab.result(q, lab.read_labels(path)).unread == 1


def test_a_disclaimer_is_an_answer_and_a_substitute_is_not() -> None:
    every: tuple[lab.Judgement, ...] = ("answered", "disclaimed", "substituted", "refused")

    def j(judgement: lab.Judgement) -> lab.Label:
        return lab.Label("k", "refusal", True, judgement, "0", "t")

    assert [j(x).withheld for x in every] == [
        False,
        False,
        True,
        True,
    ]
    assert [j(x).any_refusal for x in every] == [
        False,
        True,
        True,
        True,
    ]


def test_no_rate_is_printed_before_the_reading_is_done(tmp_path: Path) -> None:
    q = lab.build_queue(lab.readable(load_suite(), _answers()), audit=10)
    text = lab.render("r", lab.result(q, {}))
    assert "Incomplete: 15 answers" in text and "so far" in text
    assert "not known" in text
    labels = {t.key: _label(t, "answered") for t in q.tasks}
    done = lab.render("r", lab.result(q, labels))
    assert "so far" not in done and "Incomplete" not in done


def test_a_label_holds_no_answer_text() -> None:
    assert set(lab.Label.__dataclass_fields__) == {
        "key",
        "stratum",
        "verdict",
        "judgement",
        "text_sha256",
        "labelled_utc",
    }
