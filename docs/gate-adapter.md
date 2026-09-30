# Using the gate from another project

A project that grades its own outcomes can have the gate decide on them. The gate provides the
paired non-inferiority test, the power screen, Holm's adjustment across suites, the cost and
latency lines, and a ledger record. The project provides two kinds of file, and nothing else.

## The spec

It is the gate's own eval spec. Every suite has source kind `outcomes_file`, and its `block`
names the suite in the side files:

```yaml
version: 1
name: fraction-of-the-bill
delta_points: 3.0
suites:
  - key: revenue
    source: {kind: outcomes_file, block: revenue}
```

An `outcomes_file` suite takes no grader, because its outcomes arrive already graded. A spec
cannot mix it with the drift record's `drift_block` suites.

## One side file per side

The file is JSON, in the shape of the gate's `Side` and `SuiteOutcomes`:

```json
{"label": "selfhosted/2b-r16-bf16",
 "source": {"run_id": "r-20261004", "directory": "runs/2b"},
 "suites": {"revenue": {"suite": "revenue",
                        "outcomes": {"test-0": true, "test-1": false},
                        "ungradeable_items": 1, "calls": 705,
                        "latency_p50_ms": 812.0, "cost_usd": 1.23, "uncosted_calls": 0}}}
```

- `outcomes` holds one boolean per item. Items are paired across the two files by id.
- An item that could not be graded is left out of `outcomes` and counted in
  `ungradeable_items`. It is not written as false.

## Running it

```bash
uv run gate compare --spec spec.yaml --baseline baseline.json --candidate candidate.json \
    --ledger ledger.jsonl
```

It exits 1 on a block. `--ledger` puts the record in the calling project's repository. The
gate's own ledger holds only the gate's own decisions.

## What the gate checks, and what it trusts

It refuses a file it cannot read exactly as written:

- an unknown key;
- a grade that is not a boolean;
- a suite the spec names that the file lacks;
- a suite whose name disagrees with its key;
- more uncosted calls than calls.

It does not re-grade anything, so the grades are the calling project's responsibility. That is
why the record names each side file by the SHA-256 of its bytes. Anyone holding the files can
check what a decision was made on.

## Users

- Project 06, *fraction-of-the-bill*: `smallprint gate export` writes the spec and both sides,
  with one suite per extracted field.
