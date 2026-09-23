"""The judge calibration, on tables with answers worked out by hand.

Every statistic here has a closed form on a small table, so the tests check the number rather
than a property of it. A calibration that is only tested for plausibility is a calibration
nobody can rely on to condemn a judge.
"""

from __future__ import annotations

import math

from drift.analysis.stats import Estimate
from gate.judge.calibration import (
    KAPPA_FLOOR,
    Counts,
    TaskCalibration,
    agreement,
    calibrate,
    calibrate_task,
    cohens_kappa,
    corrected_rate,
    counts_of,
    krippendorff_alpha,
    pairs_for,
)
from gate.judge.rubric import JudgeVerdict, parse_verdict, rubric_hash
from tests.test_gate_gold import label


def verdict(
    instance_id: str,
    *,
    faithful: bool | None = True,
    complete: bool | None = True,
    repeat: int = 0,
    position: str = "source_first",
    judge_key: str = "small",
) -> JudgeVerdict:
    return JudgeVerdict(
        instance_id=instance_id,
        judge_key=judge_key,
        model_requested="vendor/model",
        model_returned="vendor/model",
        repeat=repeat,
        position="source_first" if position == "source_first" else "answer_first",
        faithful=faithful,
        complete=complete,
        raw="FAITHFUL: yes\nCOMPLETE: yes",
        rubric_hash=rubric_hash(),
        prompt_sha256="0" * 64,
    )


# ------------------------------------------------------------------ the statistics themselves


def test_kappa_on_a_table_worked_out_by_hand() -> None:
    """4 items: agree 3 of 4. Human yes 3/4, judge yes 2/4, so chance agreement is
    0.75*0.5 + 0.25*0.5 = 0.5, and kappa is (0.75 - 0.5) / 0.5 = 0.5."""
    pairs = [(True, True), (True, True), (False, False), (True, False)]
    assert agreement(pairs) == 0.75
    assert math.isclose(cohens_kappa(pairs), 0.5)


def test_kappa_punishes_a_judge_that_always_says_yes() -> None:
    """Nine of ten answers are faithful and the judge says yes to everything. Raw agreement is
    90%, which looks excellent and is worth nothing; kappa is 0."""
    pairs = [(True, True)] * 9 + [(False, True)]
    assert agreement(pairs) == 0.9
    assert cohens_kappa(pairs) == 0.0
    flat = Estimate(0.0, 0.0, 0.0, 10)
    assert not TaskCalibration(
        task="faithful",
        judge_key="k",
        rubric_hash="h",
        counts=counts_of(pairs),
        ungradeable=0,
        raw_agreement=0.9,
        kappa=flat,
        alpha=flat,
        sensitivity=Estimate(1.0, 1.0, 1.0, 9),
        specificity=Estimate(0.0, 0.0, 0.0, 1),
        judge_rate=Estimate(1.0, 1.0, 1.0, 10),
        human_rate=Estimate(0.9, 0.9, 0.9, 10),
        note="",
    ).usable, "raw agreement of 90% on a set that is 90% one class is not a usable judge"


def test_kappa_is_undefined_when_nobody_disagreed_about_anything() -> None:
    assert math.isnan(cohens_kappa([(True, True)] * 20))
    assert math.isnan(cohens_kappa([]))


def test_krippendorff_alpha_on_the_same_hand_table() -> None:
    """Four units, two coders. o[A][A]=4, o[B][B]=2, o[A][B]=o[B][A]=1, total 8.
    D_o = 2/8 = 0.25. n_A = 5, n_B = 3, D_e = (15+15)/(7*8) = 0.535714.
    alpha = 1 - 0.25/0.535714 = 0.5333."""
    units = [("A", "A"), ("A", "A"), ("B", "B"), ("A", "B")]
    assert math.isclose(krippendorff_alpha(units), 0.5333333333333333, rel_tol=1e-9)
    assert krippendorff_alpha([("A", "A"), ("B", "B")]) == 1.0
    assert krippendorff_alpha([("A", "B"), ("B", "A")]) == -0.5


def test_alpha_ignores_a_unit_only_one_rater_saw() -> None:
    both = [("A", "A"), ("B", "B"), ("A", "B")]
    assert krippendorff_alpha([*both, ("A",)]) == krippendorff_alpha(both)
    assert math.isnan(krippendorff_alpha([("A",)]))


def test_counts_split_the_two_kinds_of_error() -> None:
    c = counts_of([(True, False), (True, False), (False, True), (True, True)])
    assert (c.true_positive, c.false_negative, c.false_positive, c.true_negative) == (1, 2, 1, 0)
    assert c.n == 4 and c.human_positive == 3 and c.judge_positive == 2 and c.agreed == 1


# ------------------------------------------------------------------ the Rogan-Gladen correction


def make_calibration(*, tp: int, fn: int, fp: int, tn: int) -> TaskCalibration:
    pairs = (
        [(True, True)] * tp + [(True, False)] * fn + [(False, True)] * fp + [(False, False)] * tn
    )
    labels = {f"i-{n:04d}": label(f"i-{n:04d}", faithful=h) for n, (h, _) in enumerate(pairs)}
    verdicts = {f"i-{n:04d}": verdict(f"i-{n:04d}", faithful=j) for n, (_, j) in enumerate(pairs)}
    return calibrate_task(
        "faithful", labels, verdicts, judge_key="k", rubric_hash="h", resamples=400, seed=1
    )


def test_the_correction_moves_the_point_the_way_the_arithmetic_says() -> None:
    """Sensitivity 0.9, specificity 0.8. A run the judge calls 70% faithful:
    (0.70 + 0.80 - 1) / (0.90 + 0.80 - 1) = 0.50 / 0.70 = 0.714."""
    cal = make_calibration(tp=90, fn=10, fp=20, tn=80)
    assert math.isclose(cal.sensitivity.point, 0.9)
    assert math.isclose(cal.specificity.point, 0.8)
    calls = [True] * 70 + [False] * 30
    c = corrected_rate(judge_calls=calls, calibration=cal, resamples=600, seed=2)
    assert math.isclose(c.apparent.point, 0.70)
    assert math.isclose(c.corrected.point, 0.5 / 0.7, rel_tol=1e-9)
    assert not c.degenerate


def test_the_corrected_interval_is_wider_than_the_raw_one() -> None:
    """The whole point of B2.3: an interval that treats sensitivity and specificity as known
    exactly is narrower than the evidence allows. Here the calibration set is small, so the
    correction's own uncertainty dominates."""
    cal = make_calibration(tp=18, fn=2, fp=4, tn=16)
    calls = [True] * 70 + [False] * 30
    c = corrected_rate(judge_calls=calls, calibration=cal, resamples=1000, seed=3)
    raw_width = c.apparent.hi - c.apparent.lo
    corrected_width = c.corrected.hi - c.corrected.lo
    assert corrected_width > raw_width * 1.5


def test_a_judge_that_carries_no_information_is_not_corrected() -> None:
    """Sensitivity plus specificity at or below 1 means the judge is no better than a coin in
    the direction claimed. The correction would divide by zero or flip the sign, so it is
    refused and the raw rate is reported with the reason."""
    cal = make_calibration(tp=50, fn=50, fp=50, tn=50)
    c = corrected_rate(judge_calls=[True] * 60 + [False] * 40, calibration=cal, resamples=200)
    assert c.degenerate and math.isnan(c.corrected.point)
    assert "no information to correct with" in c.describe()


def test_the_correction_stays_inside_zero_and_one_and_says_when_it_had_to() -> None:
    cal = make_calibration(tp=60, fn=40, fp=5, tn=95)  # sens 0.6, spec 0.95
    calls = [True] * 95 + [False] * 5  # apparent far above what the judge can support
    c = corrected_rate(judge_calls=calls, calibration=cal, resamples=600, seed=4)
    assert 0.0 <= c.corrected.point <= 1.0
    assert 0.0 <= c.corrected.lo <= c.corrected.hi <= 1.0
    assert c.clamped_share > 0.0


def test_an_empty_run_is_not_corrected() -> None:
    cal = make_calibration(tp=9, fn=1, fp=2, tn=8)
    c = corrected_rate(judge_calls=[], calibration=cal)
    assert c.degenerate and c.apparent.n == 0


# ------------------------------------------------------------------ assembling a calibration


def test_an_unparseable_verdict_is_absent_rather_than_a_disagreement() -> None:
    labels = {f"i-{n:04d}": label(f"i-{n:04d}") for n in range(4)}
    verdicts = {
        "i-0000": verdict("i-0000"),
        "i-0001": verdict("i-0001"),
        "i-0002": verdict("i-0002", faithful=None),
        "i-0003": verdict("i-0003"),
    }
    pairs, ungradeable = pairs_for("faithful", labels, verdicts)
    assert len(pairs) == 3 and ungradeable == 1
    cal = calibrate_task(
        "faithful", labels, verdicts, judge_key="k", rubric_hash="h", resamples=200
    )
    assert cal.counts.n == 3 and cal.ungradeable == 1
    assert "absent rather than wrong" in cal.note


def test_a_task_the_human_never_said_no_to_says_so() -> None:
    labels = {f"i-{n:04d}": label(f"i-{n:04d}", faithful=True) for n in range(10)}
    verdicts = {k: verdict(k) for k in labels}
    cal = calibrate_task(
        "faithful", labels, verdicts, judge_key="k", rubric_hash="h", resamples=200
    )
    assert cal.specificity.n == 0
    assert "no denominator" in cal.note
    assert not cal.usable, "a kappa that cannot be computed is not a usable judge"


def test_kappa_floor_is_the_published_one() -> None:
    assert KAPPA_FLOOR == 0.6


def test_self_agreement_and_order_bias_come_from_the_extra_readings() -> None:
    labels = {f"i-{n:04d}": label(f"i-{n:04d}") for n in range(6)}
    verdicts = [verdict(k) for k in labels]
    # The judge changes its mind about one instance on a second reading of identical text,
    # and about a different one when the prompt's parts are reordered.
    verdicts += [verdict(k, repeat=1) for k in labels if k != "i-0000"]
    verdicts += [verdict("i-0000", faithful=False, repeat=1)]
    verdicts += [verdict(k, position="answer_first") for k in labels if k != "i-0005"]
    verdicts += [verdict("i-0005", faithful=False, position="answer_first")]
    c = calibrate(labels, verdicts, judge_key="small", resamples=200)
    self_faithful = next(s for s in c.self_agreement if s.task == "faithful")
    assert self_faithful.paired == 6 and self_faithful.disagreements == 1
    bias = next(b for b in c.position_bias if b.task == "faithful")
    assert bias.paired == 6 and bias.disagreements == 1
    assert bias.yes_only_first == 1 and bias.yes_only_second == 0


def test_the_headline_calibration_ignores_the_extra_readings() -> None:
    """Adding a swap run or a second reading must never move a kappa that was published."""
    labels = {f"i-{n:04d}": label(f"i-{n:04d}", faithful=n % 3 != 0) for n in range(12)}
    canonical = [verdict(k, faithful=labels[k].faithful) for k in labels]
    before = calibrate(labels, canonical, judge_key="small", resamples=200)
    noisy = canonical + [verdict(k, faithful=False, repeat=1) for k in labels]
    noisy += [verdict(k, faithful=False, position="answer_first") for k in labels]
    after = calibrate(labels, noisy, judge_key="small", resamples=200)
    assert before.task("faithful").counts == after.task("faithful").counts
    assert before.task("faithful").kappa.point == after.task("faithful").kappa.point


def test_verbosity_is_checked_inside_each_human_class() -> None:
    """The judge here says yes to every long answer and no to every short one, whatever the
    human said, which is exactly the bias the check exists to find."""
    labels = {}
    verdicts = []
    lengths = {}
    for n in range(20):
        iid = f"i-{n:04d}"
        human = n % 2 == 0
        long = n % 4 in (0, 1)
        labels[iid] = label(iid, faithful=human)
        verdicts.append(verdict(iid, faithful=long))
        lengths[iid] = 2000 if long else 100
    c = calibrate(labels, verdicts, judge_key="small", lengths=lengths, resamples=200)
    checks = [v for v in c.verbosity if v.task == "faithful"]
    assert len(checks) == 2, "one per human class"
    for v in checks:
        assert v.difference.point == 1900
        assert v.difference.lo > 0, "an interval clear of zero is a finding"


def test_parse_verdict_is_strict_about_the_shape() -> None:
    assert parse_verdict("FAITHFUL: yes\nCOMPLETE: no") == {"faithful": True, "complete": False}
    assert parse_verdict("faithful : YES\ncomplete - true") == {"faithful": True, "complete": True}
    # Prose instead of the form asked for: no verdict, rather than a guessed one.
    assert parse_verdict("I think the answer is mostly fine.") == {
        "faithful": None,
        "complete": None,
    }
    assert parse_verdict("FAITHFUL: yes") == {"faithful": True, "complete": None}
    assert parse_verdict("") == {"faithful": None, "complete": None}
    # The first answer for a task wins, so a judge that argues with itself does not get to
    # have the parser pick its best line.
    assert parse_verdict("FAITHFUL: no\nFAITHFUL: yes")["faithful"] is False


def test_counts_are_a_plain_dataclass_so_a_ledger_can_store_them() -> None:
    c = Counts(1, 2, 3, 4)
    assert c.n == 10 and c.agreed == 5


def test_a_rate_of_all_or_none_still_has_an_interval_with_width() -> None:
    """The first real calibration printed a sensitivity of "100.0% (100.0% to 100.0%)" over 317
    agreements. A bootstrap of identical outcomes reproduces them, and an interval of no width
    is a bare number, which CLAUDE.md calls a bug. 317 of 317 bounds the miss rate; it does not
    make it zero."""
    from gate.judge.calibration import _share

    every = _share([True] * 317, seed=0)
    assert every.point == 1.0 and every.hi == 1.0
    assert 0.98 < every.lo < 1.0, "317 of 317 cannot rule out missing one in a hundred"
    none = _share([False] * 9, seed=0)
    assert none.point == 0.0 and none.lo == 0.0 and none.hi > 0.1
    mixed = _share([True] * 5 + [False] * 4, seed=0)
    assert mixed.lo < mixed.point < mixed.hi


def test_a_judge_that_never_misses_is_still_reported_with_an_interval() -> None:
    """The real case, Gemini on completeness: 317 human-yes, all 317 agreed. Through
    calibrate_task, not the helper alone, because the first fix went into a helper the
    sensitivity figure never called."""
    cal = make_calibration(tp=317, fn=0, fp=18, tn=145)
    assert cal.sensitivity.point == 1.0
    assert cal.sensitivity.lo < 0.995, "an interval with no width is a bare number"
    assert cal.specificity.lo < cal.specificity.point < cal.specificity.hi
