"""The ledger's stage 7 fields, the import that brings pull-request decisions in, and the
reports and model cards built from the ledger alone."""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest
import yaml

from gate import cards, cli, ledger

ROOT = Path(__file__).resolve().parent.parent


def suite_line(verdict: str = "pass") -> dict[str, object]:
    return {
        "suite": "gold_complete",
        "paired_items": 100,
        "baseline_accuracy": 0.97,
        "candidate_accuracy": 0.96,
        "difference": -0.01,
        "lo": -0.04,
        "hi": 0.02,
        "delta": 0.1,
        "p_inferior": 0.0,
        "p_adjusted": 0.0,
        "items_needed": 80,
        "under_powered": False,
        "effective_items": None,
        "verdict": verdict,
        "reasons": ["non-inferior"],
    }


def live(model: str = "claude-haiku-4-5-20251001", prompt: str = "a" * 16) -> dict[str, str]:
    return {"kind": "live", "model": f"anthropic/{model}", "prompt_sha": prompt, "extra": "{}"}


def side(accuracy: float = 0.96) -> ledger.SideSuite:
    return ledger.SideSuite(
        suite="gold_complete",
        items=100,
        accuracy=accuracy,
        lo=accuracy - 0.04,
        hi=min(1.0, accuracy + 0.03),
        ungradeable_items=0,
        calls=100,
        latency_p50_ms=812.0,
        cost_usd=0.12,
        uncosted_calls=0,
    )


JUDGE = ledger.JudgeLine(
    suite="gold_complete",
    judge="google-judge-mid",
    task="complete",
    max_tokens=1024,
    kappa=0.924,
    rubric="ef99dca60984ad79",
)


def make(
    *,
    run: str = "https://github.com/o/r/actions/runs/1",
    passed: bool = True,
    judges: list[ledger.JudgeLine] | None = None,
    candidate: dict[str, str] | None = None,
    ts: str = "2026-09-30T12:00:00Z",
) -> ledger.GateRecord:
    body: dict[str, object] = {
        "kind": "compare",
        "gate_version": "0.1.0",
        "spec_name": "demo",
        "spec_hash": "f" * 64,
        "graders_hash": "g" * 16,
        "baseline": live(),
        "candidate": candidate or live(prompt="b" * 16),
        "suites": [suite_line("pass" if passed else "block")],
        "lines": [],
        "passed": passed,
        "reasons": ["gold_complete: non-inferior"],
        "supersedes": None,
    }
    if judges is not None:
        body["judges"] = [j.model_dump(mode="json") for j in judges]
    occasion = ledger.Occasion(
        repository="Peter-A-P/regulated-qa-demo",
        pull_request=9,
        head_sha="0123456789abcdef",
        run_url=run,
        fresh_calls=400,
        cache_hits=400,
        spent_usd=0.61,
        sides={"baseline": [side(0.97)], "candidate": [side(0.96)]},
    )
    return ledger.GateRecord.model_validate(
        {
            **body,
            "record_id": ledger.GateRecord.content_id(body),
            "ts_utc": ts,
            "occasion": occasion,
        }
    )


def test_records_written_before_the_new_fields_read_back_byte_for_byte() -> None:
    """The ledger is append-only and content-addressed. Adding fields must leave every line
    already committed exactly as it is, and its id still the hash of its content."""
    path = ROOT / "gate" / "runs" / ledger.LEDGER_FILE
    lines = path.read_text(encoding="utf-8").splitlines()
    records = list(ledger.read(path))
    assert len(records) == len(lines) >= 2
    for r, line in zip(records, lines, strict=True):
        if r.occasion is None:
            assert r.model_dump_json() == line
        assert ledger.GateRecord.content_id(r.content()) == r.record_id


def test_the_occasion_is_outside_the_id_and_the_judges_inside() -> None:
    a = make(run="https://x/runs/1", judges=[JUDGE])
    b = make(run="https://x/runs/2", judges=[JUDGE])
    assert a.record_id == b.record_id, "the same decision on two occasions is one decision"
    other = make(judges=[JUDGE.model_copy(update={"kappa": 0.7})])
    assert other.record_id != a.record_id, "a different licence is a different decision"
    assert "occasion" not in make().content()


def test_import_appends_new_occasions_and_skips_ones_already_there(tmp_path: Path) -> None:
    path = tmp_path / "ledger.jsonl"
    first, again = make(run="https://x/runs/1"), make(run="https://x/runs/2")
    assert ledger.import_records(path, [first]) == 1
    assert ledger.import_records(path, [first, again]) == 1, "the second occasion is new"
    assert ledger.import_records(path, [first, again]) == 0, "importing twice adds nothing"
    back = list(ledger.read(path))
    assert [r.occasion.run_url for r in back if r.occasion] == [
        "https://x/runs/1",
        "https://x/runs/2",
    ]
    assert back[0].model_dump_json() == first.model_dump_json()


def test_import_refuses_a_record_whose_id_does_not_match_its_content(tmp_path: Path) -> None:
    forged = make().model_copy(update={"passed": False})
    with pytest.raises(ValueError, match="does not match"):
        ledger.import_records(tmp_path / "ledger.jsonl", [forged])
    assert not (tmp_path / "ledger.jsonl").exists()


def test_the_committed_decisions_report_is_the_ledger_rendered() -> None:
    text = cards.render_decisions(list(ledger.read(cli.LEDGER)))
    committed = (cli.REPORTS / cards.DECISIONS_FILE).read_text(encoding="utf-8")
    assert committed == text, "run `uv run gate report decisions --write`"


def test_a_decision_shows_each_side_with_its_interval_and_its_cost() -> None:
    text = cards.render_decisions(
        [make(judges=[JUDGE]), make(passed=False, ts="2026-10-01T00:00:00Z")]
    )
    assert "2 decisions, 1 passed and 1 blocked" in text
    assert "96.0% (92.0 to 99.0)" in text, "accuracy with its interval, never bare"
    assert "US$0.00120" in text and "812 ms" in text
    assert (
        "[Peter-A-P/regulated-qa-demo#9](https://github.com/Peter-A-P/regulated-qa-demo/pull/9)"
        in text
    )
    assert "kappa 0.924" in text and "budget 1024 tokens" in text
    assert text.index("2026-10-01") < text.index("2026-09-30"), "newest first"


def test_a_model_card_comes_from_the_latest_record_that_measured_it() -> None:
    older = make(ts="2026-09-29T00:00:00Z", judges=[JUDGE])
    newer = make(ts="2026-09-30T00:00:00Z", judges=[JUDGE], passed=False)
    found = cards.subjects([older, newer])
    cand = next(s for s in found if s.prompt_sha == "b" * 16)
    card = cards.render_model_card(cand, found[cand])
    assert "2 as the candidate (1 passed, 1 blocked)" in card
    assert f"record `{newer.record_id}`" in card
    assert "96.0% (92.0 to 99.0)" in card
    assert "Not graded here: faithful" in card
    assert cand.slug == "anthropic-claude-haiku-4-5-20251001-bbbbbbbb"


def test_the_action_records_every_decision_with_the_options_gate_check_takes() -> None:
    """The Action is the only caller of `gate check` that matters, and a flag it passes that the
    command does not take fails every pull request at the first step."""
    action = yaml.safe_load((ROOT / "action" / "action.yml").read_text(encoding="utf-8"))
    run = next(s["run"] for s in action["runs"]["steps"] if s.get("id") == "gate")
    for flag in ("--record", "--repository", "--pull-request", "--head-sha"):
        assert flag in run
    params = inspect.signature(cli.check).parameters
    for name in ("record", "repository", "pull_request", "head_sha"):
        assert name in params
    keep = next(s for s in action["runs"]["steps"] if s.get("name") == "Keep the answers")
    assert keep["with"]["retention-days"] == 90, "the ledger workflow harvests from here"


def test_a_judge_corrected_rate_is_kept_beside_the_raw_call_and_absent_when_there_is_none() -> None:
    """Since 2026-10-02 `gate check --record` keeps each side's corrected rate in the occasion,
    so the reports rendered from the ledger show it beside the raw call. A side with none
    serialises exactly as before, so no committed line changes."""
    plain = side(0.96)
    assert "corrected" not in plain.model_dump_json()
    fixed = plain.model_copy(update={"corrected": 0.95, "corrected_lo": 0.9, "corrected_hi": 0.99})
    rec = make(judges=[JUDGE])
    assert rec.occasion is not None
    with_fix = rec.model_copy(
        update={"occasion": rec.occasion.model_copy(update={"sides": {"candidate": [fixed]}})}
    )
    assert with_fix.record_id == rec.record_id, "the corrected rate is the occasion's, not the id's"
    text = cards.render_decisions([with_fix])
    assert "Corrected for the judge" in text and "95.0% (90.0 to 99.0)" in text
    card = cards.render_model_card(
        next(iter(cards.subjects([with_fix]))), [(with_fix, "candidate")]
    )
    assert "95.0% (90.0 to 99.0)" in card and "Rogan-Gladen" in card
    assert "Corrected for the judge" not in cards.render_decisions([make(judges=[JUDGE])])
