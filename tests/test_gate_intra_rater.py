"""The gold set's second reading against its first (gate/judge/intra_rater.py): the hundred
compared are the intra-rater sample, each reading is the last label of its pass about the text
stored now, and the published document is what the command prints."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from gate import gold
from gate.cli import app
from gate.judge import intra_rater
from gate.judge import runner as judge_runner
from gate.judge.calibration import cohens_kappa
from gate.judge.rubric import rubric_hash

ROOT = Path(__file__).resolve().parent.parent
GOLD = ROOT / "gate" / "gold"


def _result() -> intra_rater.IntraRater:
    return intra_rater.intra_rater(
        gold.load(GOLD),
        gold.read_labels(GOLD / gold.LABELS_FILE),
        judge_runner.read_verdicts(GOLD / judge_runner.VERDICTS_FILE),
        rubric_hash=rubric_hash(),
    )


def test_the_two_readings_are_compared_on_the_sample_alone() -> None:
    g = gold.load(GOLD)
    labels = gold.read_labels(GOLD / gold.LABELS_FILE)
    first = gold.latest_labels(labels, pass_no=1)
    second = gold.latest_labels(labels, pass_no=2)
    sample = gold.intra_rater_sample(g.instance_ids_in("core"))
    assert set(second) <= set(sample)
    r = _result()
    assert r.read == len(set(second) & set(first))
    for t in r.tasks:
        pairs = [(first[i].value(t.task), second[i].value(t.task)) for i in sorted(second)]
        assert t.kappa.point == cohens_kappa(pairs)
        changed = {i for i, (a, b) in zip(sorted(second), pairs, strict=True) if a != b}
        assert set(t.yes_then_no) | set(t.no_then_yes) == changed


def test_a_second_reading_of_changed_text_is_not_counted(tmp_path: Path) -> None:
    labels = gold.read_labels(GOLD / gold.LABELS_FILE)
    second = [label for label in labels if label.pass_no == 2]
    stale = second[0].model_copy(update={"output_sha256": "0" * 64})
    r = intra_rater.intra_rater(gold.load(GOLD), [*labels, stale], [], rubric_hash=rubric_hash())
    assert r.read == _result().read - 1


def test_the_published_document_is_what_the_command_prints(tmp_path: Path) -> None:
    out = CliRunner().invoke(app, ["gold", "intra-rater"])
    assert out.exit_code == 0, out.output
    published = (ROOT / "docs" / "judge-intra-rater.md").read_text(encoding="utf-8")
    assert published.rstrip("\n") in out.output
