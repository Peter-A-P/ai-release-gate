# Not rejected: an LLM judge for measuring drift

Judge `anthropic/claude-haiku-4-5-20251001`, 50 stored answers from the 2026-09 run, judged 5 times each at temperature 0 over identical input. 250 judge calls, US$0.35.

The judge saw the item, the reference answer and one stored model answer, and was asked for one word. Nothing about its input varied between repeats.

## The measurement

| Measure | Value |
|---|---|
| Judge disagrees with itself across repeats | 0.0% (0.0% to 4.9%, n = 50) |
| Programmatic grader disagrees with itself | 0%, by construction |
| Judge majority agrees with the programmatic grader | 98.0% (90.9% to 99.8%, n = 50) |
| Pass rate the judge would report | 88.0% (77.0% to 94.8%, n = 50) |
| Pass rate the programmatic grader reports | 90.0% (79.4% to 96.1%, n = 50) |
| Replies that were not the single word asked for | 0 of 250 |
| Replies that could not be read as either word | 0 of 250 |

Shares are of items, with 95% Jeffreys intervals, which stay honest at a share of none or all where a bootstrap collapses to a point.

Drift is declared when a model's month-over-month flip rate exceeds the upper bound of its same-day flip rate (PLAN.md section 1). Judging identical text repeatedly is the cleanest possible case, with nothing changed at all, and on this evidence the judge's own disagreement stays below the 5% effect this suite is powered to detect, interval and all. On this evidence the approach is NOT rejected, and the finding to publish is that it survived the test.

The same-day flip rate the record actually reports comes from a grader that returns the same verdict on the same text every time, so all of it belongs to the model.

## Where the judge is least reliable

| Block | Judge self-disagreement |
|---|---|
| closed_form_reasoning | 0.0% (0.0% to 26.7%, n = 8) |
| instruction_following | 0.0% (0.0% to 29.7%, n = 7) |
| long_context_recall | 0.0% (0.0% to 29.7%, n = 7) |
| multiple_choice | 0.0% (0.0% to 29.7%, n = 7) |
| paraphrase_robustness | 0.0% (0.0% to 29.7%, n = 7) |
| refusal_calibration | 0.0% (0.0% to 29.7%, n = 7) |
| structured_extraction | 0.0% (0.0% to 29.7%, n = 7) |

Items where the judge's majority verdict differs from the programmatic grader's: recall-1016. A disagreement the judge repeats every time is a bias rather than noise, and no number of repeats will reveal it.

## What this does not claim

It does not claim a judge is fit to measure drift. It measures one of the two ways a judge adds noise, disagreeing with itself over identical input on one day, under the conditions most favourable to it. The other is the judge's own vendor changing it between months, which is exactly what this project exists to detect in other models, and a same-day test cannot see it. The drift record keeps its programmatic graders, whose verdict on the same text cannot change at all.

Reproduce with `uv run drift rulec judge --month 2026-09 --replay`, which recomputes every number above from the stored verdicts without calling any vendor.
