"""Gating a pull request live, with no network: `gate check` end to end on a fake vendor.

The fake answers a question well or badly depending on the system prompt it is given, and
plays the judge by reading the answer, so every path through the real command is exercised:
the base branch's rules governing, the judge licensed from the real calibration record, the
judge's error taken out of the difference, the cache, and the exit codes.
"""

from __future__ import annotations

import textwrap
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest
from typer.testing import CliRunner

import gate.cli as cli
from gate import gold, live
from gate.judge.rubric import SYSTEM as JUDGE_SYSTEM
from gate.judge.rubric import judge_prompt
from gate.report import PR_MARKER

CONFIG = """\
version: 1
name: regulated-qa
delta_points: {delta}
resamples: 400
suites:
  - key: regulated_qa
    source: {{ kind: gold_questions }}
    grader: {{ judge: google-judge-mid, task: {task}, max_tokens: {budget} }}
latency: {{ max_increase_pct: 50 }}
cost: {{ max_increase_pct: 50 }}
subject:
  prompt: prompts/answer.txt
  provider: anthropic
  model: {model}
"""


def repo(
    root: Path,
    prompt: str,
    *,
    delta: float = 10,
    task: str = "complete",
    budget: int = 1024,
    model: str = "claude-haiku-4-5-20251001",
) -> Path:
    (root / "prompts").mkdir(parents=True, exist_ok=True)
    (root / "prompts" / "answer.txt").write_text(prompt, encoding="utf-8")
    (root / "gate.yaml").write_text(
        CONFIG.format(delta=delta, task=task, budget=budget, model=model), encoding="utf-8"
    )
    return root


class FakeVendor:
    """Answers GOOD under a prompt containing 'careful', BAD on every third question otherwise;
    as the judge, calls an answer complete when it says GOOD. Slow for a model named 'slow'."""

    def __init__(self) -> None:
        self.requests: list[live.Request] = []

    def __call__(self, r: live.Request) -> live.Reply:
        self.requests.append(r)
        slow = 3000.0 if "slow" in r.model else 1000.0
        if r.system == JUDGE_SYSTEM:
            complete = "GOOD" in r.prompt.split("ANSWER")[-1]
            text = f"FAITHFUL: yes\nCOMPLETE: {'yes' if complete else 'no'}"
            return live.Reply(text, r.model, "stop", 0.001, 500.0)
        n = len([x for x in self.requests if x.system != JUDGE_SYSTEM])
        good = "careful" in r.system or n % 3 != 0
        return live.Reply("GOOD answer" if good else "BAD answer", r.model, "stop", 0.002, slow)


@pytest.fixture
def vendor(monkeypatch: pytest.MonkeyPatch) -> FakeVendor:
    fake = FakeVendor()

    @contextmanager
    def opened(work: Path, run_id: str) -> Iterator[live.Chat]:
        yield fake

    monkeypatch.setattr(cli, "_open_chat", opened)
    monkeypatch.setenv("COLUMNS", "200")
    return fake


def run(base: Path, cand: Path, tmp: Path, *extra: str) -> tuple[int, str]:
    args = ["check", "--base", str(base), "--candidate", str(cand), "--work", str(tmp / "w")]
    result = CliRunner().invoke(cli.app, [*args, *extra])
    return result.exit_code, result.output


FLAG = cli.VENDOR_FLAG


def test_a_regression_is_blocked_and_the_comment_says_why(
    tmp_path: Path, vendor: FakeVendor
) -> None:
    base = repo(tmp_path / "base", "Be careful and complete.")
    cand = repo(tmp_path / "cand", "Be quick.")
    comment = tmp_path / "comment.md"
    code, out = run(base, cand, tmp_path, FLAG, "--comment", str(comment))
    assert code == 1, out
    text = comment.read_text(encoding="utf-8")
    assert text.startswith(PR_MARKER), "the Action finds its own comment by this marker"
    assert "## Gate: BLOCK" in text
    assert "cannot rule out a 10% drop" in text
    assert "sensitivity + specificity - 1 = 0.89" in text, "the correction is stated, not hidden"
    assert "Baseline, corrected" in text
    assert "Faithfulness is not gated" in text


def test_an_unchanged_prompt_passes_and_costs_nothing_the_second_time(
    tmp_path: Path, vendor: FakeVendor
) -> None:
    base = repo(tmp_path / "base", "Be careful and complete.")
    cand = repo(tmp_path / "cand", "Be careful and complete.")
    cache = tmp_path / "cache.jsonl"
    code, out = run(base, cand, tmp_path, FLAG, "--cache", str(cache))
    assert code == 0, out
    first = len(vendor.requests)
    assert first == 200, "100 answers and 100 judgements; the candidate's are cache hits"
    code, out = run(base, cand, tmp_path, FLAG, "--cache", str(cache))
    assert code == 0
    assert len(vendor.requests) == first, "a byte-identical request is never paid for twice"
    assert "made 0 vendor calls" in out


def test_a_pull_request_cannot_loosen_its_own_margin(tmp_path: Path, vendor: FakeVendor) -> None:
    """The candidate sets a 90-point margin, which would pass anything. The base's 10 applies."""
    base = repo(tmp_path / "base", "Be careful and complete.", delta=10)
    cand = repo(tmp_path / "cand", "Be quick.", delta=90)
    code, out = run(base, cand, tmp_path, FLAG)
    assert code == 1, "the regression is still blocked at the base branch's margin"
    assert "edits the gate's own rules" in out


def test_a_refused_judge_is_refused_before_a_single_call(
    tmp_path: Path, vendor: FakeVendor
) -> None:
    """Both judges failed calibration on faithfulness (kappa 0.07 and 0.11)."""
    base = repo(tmp_path / "base", "p", task="faithful")
    cand = repo(tmp_path / "cand", "p", task="faithful")
    code, out = run(base, cand, tmp_path, FLAG)
    assert code == 2
    assert "refused for faithful" in out
    assert vendor.requests == []


def test_a_judge_at_a_budget_it_was_not_calibrated_at_is_refused(
    tmp_path: Path, vendor: FakeVendor
) -> None:
    base = repo(tmp_path / "base", "p", budget=64)
    cand = repo(tmp_path / "cand", "p", budget=64)
    code, out = run(base, cand, tmp_path, FLAG)
    assert code == 2
    assert "calibrated at max_tokens [1024]" in out
    assert vendor.requests == []


def test_nothing_is_spent_without_the_flag(tmp_path: Path, vendor: FakeVendor) -> None:
    base = repo(tmp_path / "base", "p")
    cand = repo(tmp_path / "cand", "p")
    code, out = run(base, cand, tmp_path)
    assert code == 2
    assert FLAG in out
    assert vendor.requests == []


def test_a_slower_model_fails_on_latency_alone(tmp_path: Path, vendor: FakeVendor) -> None:
    """B6's demo wants a pull request that fails only on latency: same answers, 3x slower."""
    base = repo(tmp_path / "base", "Be careful and complete.")
    cand = repo(tmp_path / "cand", "Be careful and complete.", model="slow-model")
    code, out = run(base, cand, tmp_path, FLAG)
    assert code == 1, out
    assert "- block: latency p50" in out
    assert "| regulated_qa |" in out and "| pass |" in out


def test_the_judge_is_asked_exactly_as_it_was_calibrated(
    tmp_path: Path, vendor: FakeVendor
) -> None:
    """Same system, same rubric prompt, same budget, source first: the conditions the stored
    kappa describes. A judge asked any other way is a judge nobody measured."""
    base = repo(tmp_path / "base", "Be careful and complete.")
    run(base, base, tmp_path, FLAG)
    g = gold.load(cli.GOLD)
    judge_calls = [r for r in vendor.requests if r.system == JUDGE_SYSTEM]
    first = sorted(g.questions, key=lambda q: q.id)[0]
    expected = judge_prompt(g.by_source[first.source_id], first, "GOOD answer")
    assert judge_calls[0].prompt == expected
    assert {r.max_tokens for r in judge_calls} == {1024}
    assert {r.model for r in judge_calls} == {"google/gemini-3.8-flash"}


def test_an_unparseable_verdict_is_absent_not_wrong() -> None:
    g = gold.load(cli.GOLD)
    from drift.panel import load_panel
    from gate.spec import Grader, Source, SuiteSpec

    lic = live.license_judge(
        Grader(judge="google-judge-mid", task="complete", max_tokens=1024),
        load_panel(cli.JUDGE_PANEL).arms,
        cli.GOLD,
    )
    suite = SuiteSpec(key="s", source=Source(kind="gold_questions"), grader=lic.grader)

    def chat(r: live.Request) -> live.Reply:
        text = "I think it is fine." if r.system == JUDGE_SYSTEM else "an answer"
        return live.Reply(text, r.model, "stop", 0.0, 1.0)

    result = live.run_gold_suite(
        suite,
        g,
        system_prompt="p",
        subject=live.Subject(prompt="p", provider="anthropic", model="m").arm(),
        licence=lic,
        chat=chat,
        cache=live.Cache(None),
        spend=live.Spend(),
    )
    assert result.outcomes.outcomes == {}
    assert result.outcomes.ungradeable_items == len(g.questions)


def test_the_cache_key_is_everything_the_vendor_is_sent() -> None:
    a = live.Request("p/m", "system one", "prompt", 400, 0.0)
    assert a.key() == live.Request("p/m", "system one", "prompt", 400, 0.0).key()
    for changed in (
        live.Request("p/m2", "system one", "prompt", 400, 0.0),
        live.Request("p/m", "system two", "prompt", 400, 0.0),
        live.Request("p/m", "system one", "prompt!", 400, 0.0),
        live.Request("p/m", "system one", "prompt", 401, 0.0),
        live.Request("p/m", "system one", "prompt", 400, None),
        live.Request("p/m", "system one", "prompt", 400, 0.0, {"reasoning_effort": "none"}),
    ):
        assert changed.key() != a.key()


def test_a_config_without_a_subject_or_a_prompt_is_refused(tmp_path: Path) -> None:
    (tmp_path / "gate.yaml").write_text(
        textwrap.dedent(
            """\
            version: 1
            name: x
            suites:
              - key: s
                source: { kind: gold_questions }
                grader: { judge: google-judge-mid, task: complete }
            """
        ),
        encoding="utf-8",
    )
    with pytest.raises(live.ConfigError, match="no subject"):
        live.load_repo_config(tmp_path)
    repo(tmp_path, "p")
    (tmp_path / "prompts" / "answer.txt").unlink()
    with pytest.raises(live.ConfigError, match="does not exist"):
        live.load_repo_config(tmp_path)


def test_the_simulated_false_block_rate_falls_as_the_margin_widens() -> None:
    """The shape the ten-point margin rests on, small enough to run in the suite."""
    from gate.live_aa import simulate

    (row,) = simulate(uncertain=(0.04,), margins=(0.03, 0.10), trials=60, resamples=200)
    (_, tight), (_, wide) = row.false_block
    assert tight > 0.3, "three points on 100 judged items blocks an unchanged prompt often"
    assert wide < 0.1
    assert 0.01 < row.discordance < 0.08


def test_the_demo_repository_config_loads_and_its_judge_is_licensed() -> None:
    """The demo is what the pull requests run on; it must not rot away from the gate."""
    from drift.panel import load_panel

    root = Path(__file__).resolve().parent.parent / "examples" / "regulated-qa-demo"
    spec, subject, prompt = live.load_repo_config(root)
    assert spec.delta_points == 10 and prompt
    assert subject.model == "claude-haiku-4-5-20251001"
    (suite,) = spec.suites
    assert suite.grader is not None
    lic = live.license_judge(suite.grader, load_panel(cli.JUDGE_PANEL).arms, cli.GOLD)
    assert lic.calibration.usable and lic.grader.task == "complete"
