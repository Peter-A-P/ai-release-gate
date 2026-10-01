"""The read model: everything the pages show, built once from the files in the repository.

Built at start and rebuilt when the repository's commit changes (the VPS pulls nightly, B8), in
the background, with the previous model serving until the new one is ready: computing the
published intervals takes about twenty seconds a run, and a page should not wait for that.
"""

from __future__ import annotations

import datetime as dt
import subprocess
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import duckdb

from drift.analysis.metrics import ArmMetrics
from drift.analysis.report import (
    ClassifierCheck,
    classifier_check,
    metrics_for_month,
    previous_month,
)
from drift.panel import load_panel
from drift.runner.records import (
    RECORDS_FILE,
    RunMeta,
    arms_recorded,
    load_meta,
    read_records,
    records_path,
)
from gate import aa as gate_aa
from gate import gold
from gate import ledger as gate_ledger
from gate.judge import calibration as calib
from gate.judge import runner as judge_runner
from gate.judge.rubric import rubric_hash
from gate.redteam import report as rt_report
from gate.redteam import run as rt_run
from gate.redteam import suite as rt_suite
from gate.spec import load_spec

# A run directory with "dry" in its name is a rehearsal: its records exist so the official run
# could be trusted, and it is never shown as part of the record.
REHEARSAL = "dry"

# The columns DuckDB reads from each call record. Everything but the text: the pages never
# show an answer, and the jailbreak suite's are not in the repository at all.
CALL_COLUMNS = {
    "run_id": "VARCHAR",
    "month": "VARCHAR",
    "arm_key": "VARCHAR",
    "block": "VARCHAR",
    "held_out": "BOOLEAN",
    "finish_reason": "VARCHAR",
    "error_type": "VARCHAR",
    "latency_ms": "DOUBLE",
    "input_tokens": "BIGINT",
    "output_tokens": "BIGINT",
    "cost_usd": "DOUBLE",
    "costed": "BOOLEAN",
    "correct": "BOOLEAN",
}


@dataclass(frozen=True, slots=True)
class Run:
    """One official drift run: its RUN.json and the report's own metrics for every arm."""

    label: str  # the directory name, "2026-09" or "2026-09-run2"
    meta: RunMeta
    arms: dict[str, ArmMetrics]
    # The refusal classifier's error rate on this run, read by hand; None if nobody has yet.
    refusal_check: ClassifierCheck | None = None
    # The run this one's report is paired against (`baseline_for`); None for the first.
    baseline: str | None = None


@dataclass
class ReadModel:
    root: Path
    commit: str | None
    built_utc: str
    runs: list[Run]
    decisions: list[gate_ledger.GateRecord]
    judges: dict[str, calib.Calibration]  # on the first hundred, as published
    # On the multi-part stratum alone, licensed separately (gate.live.license_judge).
    judges_multipart: dict[str, calib.Calibration]
    redteam: dict[str, rt_report.Scored]  # run id -> scored
    redteam_suite_hash: str | None
    # The open-weights arm whose weights cannot change, read from drift/panel.yaml as the
    # report reads it: its movement is the measurement's own noise.
    control_key: str | None
    # The gate run against itself, as `gate/reports/aa-2026-09.md` publishes it: `gate aa
    # --month SECOND --baseline FIRST` under the shipped spec, on the first two official runs.
    # Those are the between-run baseline, four days apart, where nothing can have changed, so
    # every block is a false block. A later month is a month apart and a vendor may have moved
    # its model in between, so pairing the latest two runs would stop being an A/A study the day
    # the October run lands. None when not built (most of a minute) or there is no run.
    aa: gate_aa.AAStudy | None
    aa_runs: tuple[str, ...]
    db: duckdb.DuckDBPyConnection = field(repr=False)
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def query(self, sql: str, params: Sequence[Any] = ()) -> list[dict[str, Any]]:
        """Rows as dicts. The connection is shared, so queries are serialised."""
        with self.lock:
            cur = self.db.execute(sql, list(params))
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, row, strict=True)) for row in cur.fetchall()]


def git_commit(root: Path) -> str | None:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True, check=True
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return out.stdout.strip() or None


def official_runs(runs_root: Path) -> list[str]:
    """The run directories that are part of the record, oldest first by start time."""
    found: list[tuple[str, str]] = []
    for d in sorted(runs_root.iterdir()) if runs_root.is_dir() else []:
        if not d.is_dir() or REHEARSAL in d.name:
            continue
        meta = load_meta(runs_root, d.name)
        if meta is not None:
            found.append((meta.started_utc, d.name))
    return [name for _, name in sorted(found)]


def _judges(root: Path, seed: int, stratum: gold.Stratum = "core") -> dict[str, calib.Calibration]:
    """Every judge's calibration on one stratum, computed exactly as `gate judge calibrate
    --stratum` computes it. Over every label at once it would be neither published figure: the
    page read 0.844 for a judge published at 0.914 the day the multi-part labels arrived."""
    gold_root = root / "gate" / "gold"
    if not (gold_root / gold.LABELS_FILE).is_file():
        return {}
    g = gold.load(gold_root)
    ids = set(g.instance_ids_in(stratum))
    labels = {
        k: v
        for k, v in gold.usable_labels(
            gold.latest_labels(gold.read_labels(gold_root / gold.LABELS_FILE), pass_no=1),
            g.by_instance,
        ).items()
        if k in ids
    }
    # Under the current rubric only, the one a judge is licensed under.
    current = rubric_hash()
    verdicts = [
        v
        for v in judge_runner.read_verdicts(gold_root / judge_runner.VERDICTS_FILE)
        if v.instance_id in ids and v.rubric_hash == current
    ]
    if not labels:
        return {}
    lengths = {i.id: len(i.output) for i in g.instances}
    out: dict[str, calib.Calibration] = {}
    for key in sorted({v.judge_key for v in verdicts}):
        mine = [v for v in verdicts if v.judge_key == key]
        out[key] = calib.calibrate(labels, mine, judge_key=key, lengths=lengths, seed=seed)
    return out


def _redteam(root: Path) -> tuple[dict[str, rt_report.Scored], str | None]:
    suite_root = root / "gate" / "redteam" / "suite" / "v1"
    items = rt_suite.load_suite(suite_root)
    if not items:
        return {}, None
    scored: dict[str, rt_report.Scored] = {}
    runs_root = root / "gate" / "redteam" / "runs"
    for d in sorted(runs_root.iterdir()) if runs_root.is_dir() else []:
        answers = rt_run.read_answers(d / rt_run.ANSWERS_FILE)
        if answers:
            scored[d.name] = rt_report.score(items, answers)
    return scored, rt_suite.suite_hash(items)


def baseline_for(label: str, labels: Sequence[str]) -> str | None:
    """The run `label`'s report compares it against, so a page's "change vs previous run" is the
    README's and the report's. The monthly job pairs a month with the calendar month before
    (`drift.analysis.report.previous_month`); a run with no such month, like the September
    between-run baseline `2026-09-run2`, was paired by hand with the run before it. The record
    does not remember a baseline (drift/cli.py), so this is the rule both reports follow.

    Pairing with the previous run in time instead put October against `2026-09-run2`, which no
    report does, and the front page printed a largest move the README table did not contain."""
    earlier = list(labels[: list(labels).index(label)])
    if not earlier:
        return None
    month = previous_month(label)
    return month if month in earlier else earlier[-1]


def aa_study(root: Path, labels: Sequence[str]) -> gate_aa.AAStudy | None:
    """The A/A study the gate's report publishes, computed by the functions `gate aa` calls:
    within-run pairs from the last of `labels`, and between-run pairs against the one before."""
    if not labels:
        return None
    runs_root = root / "drift" / "runs"
    spec = load_spec(root / "gate" / "specs" / "drift-blocks.yaml")

    def records(label: str) -> dict[str, list[Any]]:
        return {
            k: list(read_records(records_path(runs_root, label, k)))
            for k in arms_recorded(runs_root, label)
        }

    cur = records(labels[-1])
    pairs = gate_aa.within_run_pairs(spec, cur, month=labels[-1], size=2)
    if len(labels) > 1:
        pairs += gate_aa.between_run_pairs(
            spec, records(labels[-2]), cur, first_month=labels[-2], second_month=labels[-1]
        )
    return gate_aa.study(spec, pairs) if pairs else None


def _calls_table(db: duckdb.DuckDBPyConnection, runs_root: Path, labels: Sequence[str]) -> None:
    cols = ", ".join(f"{k} {v}" for k, v in CALL_COLUMNS.items())
    db.execute(f"CREATE TABLE calls (run_label VARCHAR, {cols})")
    for label in labels:
        pattern = str(runs_root / label / "*" / RECORDS_FILE)
        db.execute(
            "INSERT INTO calls SELECT ?, * FROM read_json(?, format='newline_delimited', "
            "columns=?)",
            [label, pattern, CALL_COLUMNS],
        )


def build(
    root: Path, *, runs: Sequence[str] | None = None, seed: int = 0, aa: bool = True
) -> ReadModel:
    """Everything, from the repository at `root`. `runs` limits the drift runs read and `aa`
    skips the A/A study, both for tests."""
    runs_root = root / "drift" / "runs"
    labels = list(runs) if runs is not None else official_runs(runs_root)
    built: list[Run] = []
    for label in labels:
        meta = load_meta(runs_root, label)
        if meta is None:
            continue
        check = classifier_check(label, root / "drift")
        built.append(
            Run(
                label,
                meta,
                metrics_for_month(runs_root, label, seed=seed),
                check,
            )
        )
    built = [
        Run(
            r.label,
            r.meta,
            r.arms,
            r.refusal_check,
            baseline_for(r.label, [b.label for b in built]),
        )
        for r in built
    ]
    aa_runs = tuple(r.label for r in built[:2])
    db = duckdb.connect(":memory:")
    _calls_table(db, runs_root, [r.label for r in built])
    redteam, rt_hash = _redteam(root)
    panel_path = root / "drift" / "panel.yaml"
    control = load_panel(panel_path).control() if panel_path.is_file() else None
    return ReadModel(
        root=root,
        commit=git_commit(root),
        built_utc=dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        runs=built,
        decisions=list(gate_ledger.read(root / "gate" / "runs" / gate_ledger.LEDGER_FILE)),
        judges=_judges(root, seed),
        judges_multipart=_judges(root, seed, "multipart"),
        redteam=redteam,
        redteam_suite_hash=rt_hash,
        control_key=control.key if control is not None else None,
        aa=aa_study(root, aa_runs) if aa else None,
        aa_runs=aa_runs if aa else (),
        db=db,
    )


class Holder:
    """The current read model, swapped for a new one when the repository's commit moves.

    Checked at most once a `check_every` seconds, from a request. The rebuild runs in a thread
    and the old model keeps serving meanwhile, so no request ever waits for one.
    """

    def __init__(
        self,
        root: Path,
        *,
        builder: Callable[[Path], ReadModel] = build,
        check_every: float = 60.0,
    ) -> None:
        self.root = root
        self.builder = builder
        self.check_every = check_every
        self.model = builder(root)
        self._checked = time.monotonic()
        self._rebuilding = threading.Lock()

    def current(self) -> ReadModel:
        now = time.monotonic()
        if now - self._checked >= self.check_every:
            self._checked = now
            if git_commit(self.root) != self.model.commit and self._rebuilding.acquire(False):
                threading.Thread(target=self._rebuild, daemon=True).start()
        return self.model

    def _rebuild(self) -> None:
        try:
            self.model = self.builder(self.root)
        finally:
            self._rebuilding.release()
