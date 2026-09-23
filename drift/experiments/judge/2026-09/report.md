# Rejected: an LLM judge for measuring drift

Judge `anthropic/claude-haiku-4-5-20251001`, 2 stored answers from the 2026-09 run, judged 5 times each at temperature 0 over identical input. 6 judge calls, US$0.00.

The judge saw the item, the reference answer and one stored model answer, and was asked for one word. Nothing about its input varied between repeats.

## The number that rejects it

| Measure | Value |
|---|---|
| Judge disagrees with itself across repeats | 0.0% (0.0% to 0.0%, n = 1) |
| Programmatic grader disagrees with itself | 0%, by construction |
| Judge majority agrees with the programmatic grader | 100.0% (100.0% to 100.0%, n = 2) |
| Pass rate the judge would report | 50.0% (0.0% to 100.0%, n = 2) |
| Pass rate the programmatic grader reports | 50.0% (0.0% to 100.0%, n = 2) |
| Replies that were not the single word asked for | 0 of 6 |
| Replies that could not be read as either word | 0 of 6 |

Drift is declared when a model's month-over-month flip rate exceeds the upper bound of its same-day flip rate (PLAN.md section 1). Judging identical text repeatedly is the cleanest possible case, with nothing changed at all, and on this evidence the judge's own disagreement stays below the 5% effect this suite is powered to detect, interval and all. On this evidence the approach is NOT rejected, and the finding to publish is that it survived the test.

The same-day flip rate the record actually reports comes from a grader that returns the same verdict on the same text every time, so all of it belongs to the model.

## Where the judge is least reliable

| Block | Judge self-disagreement |
|---|---|
| multiple_choice | 0.0% (0.0% to 0.0%, n = 1) |

## What this does not claim

It does not claim a judge is useless. It claims a judge cannot be the instrument for this measurement, where the effect is a few points and the whole design rests on separating a real change from same-day noise. Part B calibrates a judge against human labels for open-ended quality, which programmatic grading cannot reach at all, and reports its kappa with every run for exactly this reason.

Reproduce with `uv run drift rulec judge --month 2026-09 --replay`, which recomputes every number above from the stored verdicts without calling any vendor.
