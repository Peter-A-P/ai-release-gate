"""Markdown for a decision, a side, and an A/A study. The same text goes to the terminal, to
a file, and later to the pull-request comment (B6), so a reader sees one rendering everywhere.
Every share carries its interval; a bare percentage is a bug here as in the record.
"""

from __future__ import annotations

from collections.abc import Sequence

from drift.analysis.stats import Estimate
from gate.aa import AAStudy
from gate.decision import Decision
from gate.judge.calibration import CorrectedRate
from gate.outcomes import Side
from gate.stats import PowerLine


def _pct(e: Estimate) -> str:
    return e.compact()


def _diff(e: Estimate) -> str:
    if e.n == 0:
        return "n/a"
    return f"{e.point:+.1%} ({e.lo * 100:+.1f} to {e.hi * 100:+.1f})"


def render_side(side: Side, *, resamples: int = 2000, seed: int = 0) -> str:
    out = [f"### {side.label}", ""]
    out.append("| Suite | Items | Accuracy | Ungradeable items | Latency p50 | Cost / call |")
    out.append("|---|---:|---|---:|---:|---:|")
    for key, s in side.suites.items():
        acc = s.accuracy(resamples=resamples, seed=seed)
        cost = f"US${s.cost_per_call_usd:.5f}" if s.cost_per_call_usd is not None else "n/a"
        out.append(
            f"| {key} | {s.items} | {_pct(acc)} | {s.ungradeable_items} | "
            f"{s.latency_p50_ms:.0f} ms | {cost} |"
        )
    out.append("")
    out.append("Intervals are 95% bootstrap intervals over items.")
    return "\n".join(out)


def render_decision(d: Decision) -> str:
    verdict = "PASS" if d.passed else "BLOCK"
    out = [f"## Gate: {verdict}", "", f"Spec `{d.spec_name}` ({d.spec_hash[:16]}).", ""]
    out.append(f"Baseline `{d.baseline}`, candidate `{d.candidate}`.")
    out.append("")
    out.append(
        "| Suite | Paired items | Baseline | Candidate | Difference | Margin | Holm p | Verdict |"
    )
    out.append("|---|---:|---|---|---|---:|---:|---|")
    for s in d.suites:
        t = s.decisive
        holm = f"{s.p_adjusted:.3f}" if s.p_adjusted is not None else "not decided"
        out.append(
            f"| {s.suite} | {t.paired_items} | {_pct(s.baseline)} | {_pct(s.candidate)} | "
            f"{_diff(t.difference)} | -{t.delta:.0%} | {holm} | {s.verdict} |"
        )
    out.append("")
    out.append(
        "Difference is candidate minus baseline, paired by item, with its 95% bootstrap "
        "interval. A suite passes when the whole interval sits above the margin after Holm's "
        "adjustment across the decided suites; an under-powered suite warns and is not decided."
    )
    corrected = [s for s in d.suites if s.corrected is not None]
    if corrected:
        out.append("")
        out.append("| Suite | Items | Worth about | Corrected difference | Used |")
        out.append("|---|---:|---:|---|---|")
        for s in corrected:
            assert s.corrected is not None
            out.append(
                f"| {s.suite} | {s.test.paired_items} | {s.corrected.effective_items:.0f} | "
                f"{_diff(s.corrected.difference)} | {'yes' if s.decides_on_corrected else 'shown only'} |"
            )
        out.append("")
        out.append(
            "Local dependence from project 02's bank: items that resemble one benchmark are not "
            "independent evidence, and the corrected interval is what the uncorrected one would "
            "be over that many independent items."
        )
    if d.lines:
        out.append("")
        for ln in d.lines:
            out.append(f"- {ln.verdict}: {ln.reason}")
    out.append("")
    out.append("**Reasons**")
    out.append("")
    for r in d.reasons:
        out.append(f"- {r}")
    return "\n".join(out)


def render_power(lines: list[tuple[str, int, list[PowerLine]]]) -> str:
    """suite -> (paired items, one line per effect size)."""
    if not lines:
        return "No suites."
    effects = [f"{pl.effect_points:g} pt" for pl in lines[0][2]]
    out = ["| Suite | Items in suite | " + " | ".join(f"Needed, {e}" for e in effects) + " |"]
    out.append("|---|---:|" + "---:|" * len(effects))
    for suite, n, pls in lines:
        cells = []
        for pl in pls:
            if pl.items is None:
                cells.append("no answer")
            else:
                mark = " (ok)" if n >= pl.items else ""
                cells.append(f"{pl.items}{mark}")
        out.append(f"| {suite} | {n} | " + " | ".join(cells) + " |")
    out.append("")
    first = lines[0][2][0]
    out.append(
        f"Items per side at {first.power:.0%} power from `mselect.items_needed`; {first.note}. "
        '"(ok)" marks a suite that has at least that many.'
    )
    return "\n".join(out)


def render_aa(studies: list[tuple[str, AAStudy]], *, seed: int = 0) -> str:
    """The first study is the one the spec asks for; the rest are the same pairs under other
    settings (another margin, every suite decided), for the table across them."""
    if not studies:
        return "No pairs."
    _, s = studies[0]
    out = [
        "## A/A study: the gate against itself",
        "",
        f"Spec `{s.spec_name}` ({s.spec_hash[:16]}). {s.n} pairs, nothing changed in any of them, "
        "so every block below is a false block.",
        "",
        "| Setting | Kind | Pairs | Suites decided | False-block rate, interval rule | "
        "Block rate, point rule |",
        "|---|---|---:|---:|---|---|",
    ]
    for label, st in studies:
        rows: list[tuple[str, AAStudy]] = [(k, st.of_kind(k)) for k in st.kinds]
        if len(rows) > 1:
            rows.append(("all", st))
        for kind, sub in rows:
            out.append(
                f"| {label} | {kind} | {sub.n} | {sub.mean_decided():.1f} of {sub.suites} | "
                f"{sub.false_block_rate(seed=seed).compact()} | "
                f"{sub.point_rule_rate(seed=seed).compact()} |"
            )
    out.append("")
    out.append(
        'Intervals are 95% bootstrap intervals over pairs. "Suites decided" is how many '
        "suites per pair had enough items for the margin and so reached a verdict: a setting "
        "that decides no suite cannot block, and its zero is the screen's, not the rule's."
    )
    out.append("")
    out.append(
        "Within: one arm's repeats in one run split into two disjoint sets, every ordered pair. "
        "Between: the same arm in two runs four days apart, both ways round. The interval rule is "
        "the gate's (B2.2); the point rule blocks whenever the candidate scores lower, and is "
        "here to show what it would cost."
    )
    by_suite = s.blocks_by_suite()
    point_by_suite = s.point_blocks_by_suite()
    if by_suite or point_by_suite:
        out.append("")
        out.append("| Suite | Blocks, interval rule | Blocks, point rule |")
        out.append("|---|---:|---:|")
        for suite in sorted(set(by_suite) | set(point_by_suite)):
            out.append(f"| {suite} | {by_suite.get(suite, 0)} | {point_by_suite.get(suite, 0)} |")
    by_arm = s.blocks_by_arm()
    if by_arm:
        out.append("")
        out.append("| Arm | Pairs | Blocks, interval rule |")
        out.append("|---|---:|---:|")
        for arm, (n, b) in by_arm.items():
            out.append(f"| {arm} | {n} | {b} |")
    up = s.under_powered_suites()
    if up:
        out.append("")
        out.append(
            "Under-powered in at least one pair, so warned rather than decided: "
            + ", ".join(up)
            + "."
        )
    return "\n".join(out)


# The marker the Action looks for to edit its own comment rather than add a new one on every
# push, so a pull request carries one gate verdict, the current one.
PR_MARKER = "<!-- ai-release-gate -->"


def render_pr_comment(
    d: Decision,
    *,
    judged: Sequence[tuple[str, str, str, float, CorrectedRate, CorrectedRate]],
    spent_usd: float,
    fresh_calls: int,
    cache_hits: int,
    rules_changed: bool,
    run_url: str | None = None,
) -> str:
    """The pull-request comment: the decision, then what a judge-graded number means.

    `judged` is one row per judge-graded suite: (suite, judge, task, kappa, baseline corrected
    rate, candidate corrected rate). The rates in the main table are the judge's raw calls; the
    corrected ones are the rates with the judge's own error taken out (Rogan-Gladen), and they
    are shown because a reader deciding whether to merge needs the second, not the first.
    """
    out = [PR_MARKER, render_decision(d)]
    detail = [(s.suite, r) for s in d.suites for r in s.reasons[1:]]
    if detail:
        out += ["", "**Per suite**", ""]
        out += [f"- {suite}: {reason}" for suite, reason in detail]
    if judged:
        out += [
            "",
            "**Graded by a calibrated judge.** The rates above are what the judge said. Its own",
            "error, measured against 480 hand labels, is taken out below, and taken out of the",
            "difference the verdict rests on.",
            "",
            "| Suite | Judge | Task | Kappa | Baseline, corrected | Candidate, corrected |",
            "|---|---|---|---:|---|---|",
        ]
        for suite, judge, task, kappa, base, cand in judged:
            out.append(
                f"| {suite} | {judge} | {task} | {kappa:.2f} | {base.corrected.fmt()} | "
                f"{cand.corrected.fmt()} |"
            )
        out += [
            "",
            "Faithfulness is not gated: no judge passed calibration on it (kappa 0.07 and 0.11",
            "against a floor of 0.6), and this gate does not grade with an instrument that has",
            "not been shown to work. A faithfulness regression needs a human reading.",
        ]
    if rules_changed:
        out += [
            "",
            "> **This pull request edits the gate's own rules in `gate.yaml`.** They were not",
            "> applied: the margins, thresholds and suites always come from the base branch, or a",
            "> change could pass itself. They take effect once merged.",
        ]
    out += [
        "",
        f"This run made {fresh_calls} vendor calls for US${spent_usd:.2f} and reused "
        f"{cache_hits} identical requests from the development cache.",
    ]
    if run_url:
        out.append(f"[Run log]({run_url})")
    return "\n".join(out)
