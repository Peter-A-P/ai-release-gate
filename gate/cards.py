"""Reports and model cards from the gate's ledger alone (PLAN.md B10 stage 7).

    uv run gate report decisions      gate/reports/decisions.md
    uv run gate report model-cards    gate/reports/model-cards/<model>-<prompt>.md

Nothing here calls a vendor, reads an answer, or recomputes a statistic. Every figure is the one
the record holds, formatted by `Estimate.compact`, so a page and the record cannot disagree. A
record written before a field existed shows that field as absent, never a filled-in guess: the
two drift-block records of 2026-09-20 have no occasion, so they have no cost line and no
per-side interval, and their pages say so.

A model card describes one subject: a model identifier, its request settings, and the hash of
the system prompt it ran under. Its figures come from the latest record that measured it. The
cost and latency are per call of that configuration: a reply reused from the development cache
carries the cost and latency it was first paid for, because the question a card answers is what
the configuration costs to run, not what one pull request happened to spend.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from drift.analysis.stats import Estimate
from gate.gold import TASKS
from gate.ledger import GateRecord, SideSuite

DECISIONS_FILE = "decisions.md"
CARDS_DIR = "model-cards"


def _estimate(s: SideSuite) -> str:
    if s.accuracy is None or s.lo is None or s.hi is None:
        return "n/a"
    return Estimate(s.accuracy, s.lo, s.hi, s.items).compact()


def _diff(point: float | None, lo: float | None, hi: float | None) -> str:
    if point is None or lo is None or hi is None:
        return "n/a"
    return f"{point:+.1%} ({lo * 100:+.1f} to {hi * 100:+.1f})"


def _side_name(source: dict[str, str]) -> str:
    if source.get("kind") == "live":
        return f"`{source.get('model', '?')}`, prompt `{source.get('prompt_sha', '?')[:8]}`"
    if source.get("kind") == "drift_block":
        return f"drift `{source.get('month', '?')}` `{source.get('arm', '?')}`"
    return f"`{source.get('kind', '?')}`"


def _where(r: GateRecord) -> str:
    o = r.occasion
    if o is None or not o.repository:
        return "this repository"
    if o.pull_request is None:
        return f"`{o.repository}`"
    url = f"https://github.com/{o.repository}/pull/{o.pull_request}"
    return f"[{o.repository}#{o.pull_request}]({url})"


def _verdict(r: GateRecord) -> str:
    return "pass" if r.passed else "**block**"


def _operating_table(sides: dict[str, list[SideSuite]]) -> list[str]:
    out = [
        "| Side | Suite | Items | Accuracy | Ungradeable | Calls | Latency p50 | Cost / call |",
        "|---|---|---:|---|---:|---:|---:|---:|",
    ]
    for side, suites in sides.items():
        for s in suites:
            costed = s.calls - s.uncosted_calls
            cost = f"US${s.cost_usd / costed:.5f}" if costed else "n/a"
            lat = f"{s.latency_p50_ms:.0f} ms" if s.latency_p50_ms is not None else "n/a"
            out.append(
                f"| {side} | {s.suite} | {s.items} | {_estimate(s)} | {s.ungradeable_items} | "
                f"{s.calls} | {lat} | {cost} |"
            )
    return out


def render_record(r: GateRecord) -> str:
    out = [f"### `{r.record_id}`: {_verdict(r)}", ""]
    out.append(f"- **When**: {r.ts_utc}. **Where**: {_where(r)}.")
    o = r.occasion
    if o is not None and o.head_sha:
        out.append(f"- **Commit gated**: `{o.head_sha[:12]}`.")
    if o is not None and o.run_url:
        out.append(f"- **Run**: [log]({o.run_url}).")
    out.append(
        f"- **Baseline**: {_side_name(r.baseline)}. **Candidate**: {_side_name(r.candidate)}."
    )
    out.append(
        f"- **Spec** `{r.spec_name}` ({r.spec_hash[:16]}), graders `{r.graders_hash}`, "
        f"gate {r.gate_version}."
    )
    if r.supersedes:
        out.append(f"- **Supersedes** `{r.supersedes}`.")
    if r.judges:
        for j in r.judges:
            out.append(
                f"- **Judge** on {j.suite}: `{j.judge}` for {j.task}, kappa {j.kappa:.3f}, "
                f"rubric `{j.rubric}`, budget {j.max_tokens} tokens."
            )
    out += [
        "",
        "| Suite | Paired items | Difference | Margin | Verdict |",
        "|---|---:|---|---:|---|",
    ]
    for s in r.suites:
        out.append(
            f"| {s.suite} | {s.paired_items} | {_diff(s.difference, s.lo, s.hi)} | "
            f"-{s.delta:.0%} | {s.verdict} |"
        )
    out.append("")
    if o is not None and o.sides:
        out += _operating_table(o.sides)
        out.append("")
        out.append(
            f"This run made {o.fresh_calls} vendor calls for US${o.spent_usd:.2f} and reused "
            f"{o.cache_hits} from the development cache."
        )
    else:
        out.append(
            "Recorded before the ledger kept each side's interval, cost and latency: the "
            "difference above is what this record holds."
        )
    out += ["", "Reasons:", ""]
    out += [f"- {reason}" for reason in r.reasons]
    return "\n".join(out)


def render_decisions(records: Sequence[GateRecord]) -> str:
    rs = sorted(records, key=lambda r: r.ts_utc, reverse=True)
    blocks = sum(1 for r in rs if not r.passed)
    out = [
        "# Gate decisions",
        "",
        "Generated by `gate report decisions` from `gate/runs/ledger.jsonl` and nothing else. "
        "Do not edit by hand.",
        "",
        f"{len(rs)} decisions, {len(rs) - blocks} passed and {blocks} blocked. A decision "
        "made twice on two occasions is one record id on two lines.",
        "",
        "| When (UTC) | Where | Baseline | Candidate | Verdict | Record |",
        "|---|---|---|---|---|---|",
    ]
    for r in rs:
        out.append(
            f"| {r.ts_utc} | {_where(r)} | {_side_name(r.baseline)} | "
            f"{_side_name(r.candidate)} | {_verdict(r)} | `{r.record_id}` |"
        )
    out.append("")
    out.append(
        "Differences are candidate minus baseline, paired by item, with 95% bootstrap intervals. "
        "Accuracies are 95% bootstrap intervals over items."
    )
    for r in rs:
        out += ["", render_record(r)]
    return "\n".join(out) + "\n"


# ---------------------------------------------------------------------------- model cards


@dataclass(frozen=True, slots=True)
class Subject:
    model: str
    prompt_sha: str
    extra: str

    @property
    def slug(self) -> str:
        name = re.sub(r"[^a-z0-9.-]+", "-", self.model.lower()).strip("-")
        return f"{name}-{self.prompt_sha[:8]}"


def _subject(source: dict[str, str]) -> Subject | None:
    if source.get("kind") != "live":
        return None
    return Subject(source["model"], source["prompt_sha"], source.get("extra", "{}"))


def subjects(records: Sequence[GateRecord]) -> dict[Subject, list[tuple[GateRecord, str]]]:
    """Every live subject in the ledger, with each record it appears in and on which side."""
    out: dict[Subject, list[tuple[GateRecord, str]]] = {}
    for r in records:
        for side, source in (("baseline", r.baseline), ("candidate", r.candidate)):
            s = _subject(source)
            if s is not None:
                out.setdefault(s, []).append((r, side))
    return out


def render_model_card(subject: Subject, seen: Sequence[tuple[GateRecord, str]]) -> str:
    seen = sorted(seen, key=lambda rs: rs[0].ts_utc)
    measured = [
        (r, side) for r, side in seen if r.occasion is not None and side in r.occasion.sides
    ]
    as_candidate = [r for r, side in seen if side == "candidate"]
    out = [
        f"# Model card: `{subject.model}`, prompt `{subject.prompt_sha[:8]}`",
        "",
        "Generated by `gate report model-cards` from `gate/runs/ledger.jsonl` and nothing else. "
        "Do not edit by hand.",
        "",
        f"- **Model**: `{subject.model}`, request settings `{subject.extra}`.",
        f"- **System prompt**: sha256 prefix `{subject.prompt_sha}`. The text is in the gated "
        "repository at the commit named below; the ledger holds only its hash.",
        f"- **Gate history**: in {len(seen)} decisions, {len(as_candidate)} as the candidate "
        f"({sum(1 for r in as_candidate if r.passed)} passed, "
        f"{sum(1 for r in as_candidate if not r.passed)} blocked).",
    ]
    if not measured:
        out += ["", "No record measured this subject's own figures, so there is no table."]
        return "\n".join(out) + "\n"
    r, side = measured[-1]
    assert r.occasion is not None
    out.append(f"- **Last measured**: {r.ts_utc}, record `{r.record_id}`, at {_where(r)}.")
    if r.occasion.head_sha:
        out.append(f"- **Commit**: `{r.occasion.head_sha[:12]}`.")
    out += [
        "",
        "## Measured",
        "",
        "| Suite | Items | Accuracy | Ungradeable | Latency p50 | Cost / call |",
        "|---|---:|---|---:|---:|---:|",
    ]
    for s in r.occasion.sides[side]:
        costed = s.calls - s.uncosted_calls
        cost = f"US${s.cost_usd / costed:.5f}" if costed else "n/a"
        lat = f"{s.latency_p50_ms:.0f} ms" if s.latency_p50_ms is not None else "n/a"
        out.append(
            f"| {s.suite} | {s.items} | {_estimate(s)} | {s.ungradeable_items} | {lat} | {cost} |"
        )
    out += [
        "",
        "Accuracy is a 95% bootstrap interval over items. Cost and latency are per answer of "
        "this configuration, as first paid for; the judge's calls are not in them.",
    ]
    judges = r.judges or []
    graded = {j.task for j in judges}
    out += ["", "## Graded by", ""]
    if judges:
        for j in judges:
            out.append(
                f"- {j.suite}: `{j.judge}` for {j.task}, kappa {j.kappa:.3f} against hand "
                f"labels, rubric `{j.rubric}`, budget {j.max_tokens} tokens."
            )
    else:
        out.append("- Programmatic graders only.")
    out += ["", "## Limitations", ""]
    if judges:
        out.append(
            "- A judge-graded accuracy is the judge's raw call. Its own error is taken out of "
            "the difference the gate decides on, not out of this table."
        )
    ungraded = [t for t in TASKS if t not in graded]
    if judges and ungraded:
        out.append(
            f"- Not graded here: {', '.join(ungraded)}. No suite in this record grades it, so "
            "a regression in it would not be seen by this gate."
        )
    out.append(
        "- One occasion's measurement. How the vendors' models move from month to month is the "
        "drift record's subject, not this card's."
    )
    return "\n".join(out) + "\n"
