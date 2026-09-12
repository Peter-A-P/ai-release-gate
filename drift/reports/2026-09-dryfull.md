# Drift record, 2026-09-dryfull

Run `drift-2026-09-dryfull`: complete. Started 2026-09-12T13:56:08Z, finished 2026-09-12T18:04:49Z.
Suite v1, hash `72f780dfb525d84d`; 420 items (20 held out), 5 repeats; boundary 0.1.0, drift 0.1.0.dev1; 16800 calls, US$19.48 spent against an expected US$20.35.

## Per arm

| Arm | Items | Accuracy (95% CI) | Same-day flip rate (noise floor) | Output stability | Errors | Truncated | Refused, should answer | Refused, should refuse | Latency p50 / p95 ms | Cost per 1,000 calls |
|---|---:|---|---|---|---|---|---|---|---|---:|
| anthropic-alias | 420 | 95.0% (92.9% to 96.9%, n = 420) | 0.2% (0.0% to 0.7%, n = 420) | 91.7% (89.0% to 94.3%, n = 420) | 0.0% (0.0% to 0.0%, n = 2100) | 0.0% (0.0% to 0.0%, n = 2100) | 0.0% (0.0% to 0.0%, n = 100) | 70.0% (61.0% to 78.0%, n = 100) | 1690 / 4418 | US$1.32 |
| anthropic-snapshot | 420 | 95.0% (92.9% to 96.9%, n = 420) | 0.5% (0.0% to 1.2%, n = 420) | 91.2% (88.6% to 93.8%, n = 420) | 0.0% (0.0% to 0.0%, n = 2100) | 0.0% (0.0% to 0.0%, n = 2100) | 0.0% (0.0% to 0.0%, n = 100) | 70.0% (61.0% to 79.0%, n = 100) | 1698 / 4466 | US$1.32 |
| anthropic-sonnet-snapshot | 420 | 97.4% (95.7% to 98.8%, n = 420) | 2.9% (1.4% to 4.5%, n = 420) | 71.2% (66.7% to 75.7%, n = 420) | 0.0% (0.0% to 0.0%, n = 2100) | 0.1% (0.0% to 0.2%, n = 2100) | 0.0% (0.0% to 0.0%, n = 100) | 94.0% (89.0% to 98.0%, n = 100) | 1498 / 7497 | US$2.78 |
| google-alias | 420 | 97.4% (95.7% to 98.8%, n = 420) | 3.6% (1.9% to 5.5%, n = 420) | 69.0% (64.5% to 73.3%, n = 420) | 0.0% (0.0% to 0.0%, n = 2100) | 0.0% (0.0% to 0.0%, n = 2100) | 0.0% (0.0% to 0.0%, n = 100) | 100.0% (100.0% to 100.0%, n = 100) | 1215 / 4661 | US$1.15 |
| google-snapshot | 420 | 96.9% (95.2% to 98.3%, n = 420) | 3.3% (1.7% to 5.0%, n = 420) | 70.0% (65.5% to 74.5%, n = 420) | 0.0% (0.0% to 0.0%, n = 2100) | 0.0% (0.0% to 0.0%, n = 2100) | 0.0% (0.0% to 0.0%, n = 100) | 100.0% (100.0% to 100.0%, n = 100) | 1172 / 4640 | US$1.16 |
| openai-alias | 420 | 95.2% (93.1% to 97.1%, n = 420) | 3.1% (1.7% to 5.0%, n = 420) | 71.7% (67.6% to 75.7%, n = 420) | 0.0% (0.0% to 0.0%, n = 2100) | 0.0% (0.0% to 0.0%, n = 2100) | 6.0% (2.0% to 11.0%, n = 100) | 100.0% (100.0% to 100.0%, n = 100) | 832 / 1844 | US$0.45 |
| openai-snapshot | 420 | 95.2% (93.1% to 97.1%, n = 420) | 2.1% (1.0% to 3.6%, n = 420) | 72.4% (68.1% to 76.7%, n = 420) | 0.0% (0.0% to 0.0%, n = 2100) | 0.0% (0.0% to 0.0%, n = 2100) | 6.0% (2.0% to 11.0%, n = 100) | 100.0% (100.0% to 100.0%, n = 100) | 811 / 1753 | US$0.48 |
| openweights-control | 420 | 91.7% (88.8% to 94.3%, n = 420) | 3.8% (2.1% to 5.7%, n = 420) | 74.3% (70.0% to 78.3%, n = 420) | 0.0% (0.0% to 0.1%, n = 2100) | 0.1% (0.0% to 0.2%, n = 2100) | 0.0% (0.0% to 0.0%, n = 100) | 89.0% (83.0% to 95.0%, n = 100) | 1163 / 4882 | US$0.60 |

## Month over month

No records for 2026-08; the first paired comparison comes next month.

## Accuracy by block

| Arm | closed_form_reasoning | instruction_following | long_context_recall | multiple_choice | paraphrase_robustness | refusal_calibration | structured_extraction | structured_extraction (held out) |
|---|---|---|---|---|---|---|---|---|
| anthropic-alias | 100.0% (100.0% to 100.0%, n = 120) | 95.0% (88.3% to 100.0%, n = 60) | 100.0% (100.0% to 100.0%, n = 20) | 93.0% (88.0% to 98.0%, n = 100) | 100.0% (100.0% to 100.0%, n = 40) | 85.0% (75.0% to 95.0%, n = 40) | 90.0% (75.0% to 100.0%, n = 20) | 85.0% (70.0% to 100.0%, n = 20) |
| anthropic-snapshot | 100.0% (100.0% to 100.0%, n = 120) | 95.0% (88.3% to 100.0%, n = 60) | 100.0% (100.0% to 100.0%, n = 20) | 93.0% (88.0% to 98.0%, n = 100) | 100.0% (100.0% to 100.0%, n = 40) | 85.0% (72.5% to 95.0%, n = 40) | 90.0% (75.0% to 100.0%, n = 20) | 85.0% (70.0% to 100.0%, n = 20) |
| anthropic-sonnet-snapshot | 99.2% (97.5% to 100.0%, n = 120) | 98.3% (95.0% to 100.0%, n = 60) | 100.0% (100.0% to 100.0%, n = 20) | 95.0% (90.0% to 99.0%, n = 100) | 100.0% (100.0% to 100.0%, n = 40) | 95.0% (87.5% to 100.0%, n = 40) | 95.0% (85.0% to 100.0%, n = 20) | 95.0% (85.0% to 100.0%, n = 20) |
| google-alias | 99.2% (97.5% to 100.0%, n = 120) | 100.0% (100.0% to 100.0%, n = 60) | 100.0% (100.0% to 100.0%, n = 20) | 97.0% (93.0% to 100.0%, n = 100) | 100.0% (100.0% to 100.0%, n = 40) | 100.0% (100.0% to 100.0%, n = 40) | 80.0% (60.0% to 95.0%, n = 20) | 85.0% (70.0% to 100.0%, n = 20) |
| google-snapshot | 99.2% (97.5% to 100.0%, n = 120) | 100.0% (100.0% to 100.0%, n = 60) | 100.0% (100.0% to 100.0%, n = 20) | 97.0% (93.0% to 100.0%, n = 100) | 100.0% (100.0% to 100.0%, n = 40) | 100.0% (100.0% to 100.0%, n = 40) | 75.0% (55.0% to 95.0%, n = 20) | 80.0% (60.0% to 95.0%, n = 20) |
| openai-alias | 98.3% (95.8% to 100.0%, n = 120) | 98.3% (95.0% to 100.0%, n = 60) | 100.0% (100.0% to 100.0%, n = 20) | 88.0% (81.0% to 94.0%, n = 100) | 95.0% (87.5% to 100.0%, n = 40) | 97.5% (92.5% to 100.0%, n = 40) | 95.0% (85.0% to 100.0%, n = 20) | 95.0% (85.0% to 100.0%, n = 20) |
| openai-snapshot | 97.5% (94.2% to 100.0%, n = 120) | 98.3% (95.0% to 100.0%, n = 60) | 100.0% (100.0% to 100.0%, n = 20) | 88.0% (81.0% to 94.0%, n = 100) | 97.5% (92.5% to 100.0%, n = 40) | 97.5% (92.5% to 100.0%, n = 40) | 95.0% (85.0% to 100.0%, n = 20) | 95.0% (85.0% to 100.0%, n = 20) |
| openweights-control | 95.0% (90.8% to 98.3%, n = 120) | 95.0% (90.0% to 100.0%, n = 60) | 100.0% (100.0% to 100.0%, n = 20) | 81.0% (73.0% to 88.0%, n = 100) | 95.0% (87.5% to 100.0%, n = 40) | 95.0% (87.5% to 100.0%, n = 40) | 95.0% (85.0% to 100.0%, n = 20) | 90.0% (75.0% to 100.0%, n = 20) |

## Held-out check

Held-out items are never published, so a model cannot have seen them. Public accuracy
rising while held-out accuracy does not is evidence of contamination, not capability.

| Arm | Block | Public accuracy | Held-out accuracy | Public minus held-out |
|---|---|---|---|---:|
| anthropic-alias | structured_extraction | 90.0% (75.0% to 100.0%, n = 20) | 85.0% (70.0% to 100.0%, n = 20) | +5.0% |
| anthropic-snapshot | structured_extraction | 90.0% (75.0% to 100.0%, n = 20) | 85.0% (70.0% to 100.0%, n = 20) | +5.0% |
| anthropic-sonnet-snapshot | structured_extraction | 95.0% (85.0% to 100.0%, n = 20) | 95.0% (85.0% to 100.0%, n = 20) | +0.0% |
| google-alias | structured_extraction | 80.0% (60.0% to 95.0%, n = 20) | 85.0% (70.0% to 100.0%, n = 20) | -5.0% |
| google-snapshot | structured_extraction | 75.0% (55.0% to 95.0%, n = 20) | 80.0% (60.0% to 95.0%, n = 20) | -5.0% |
| openai-alias | structured_extraction | 95.0% (85.0% to 100.0%, n = 20) | 95.0% (85.0% to 100.0%, n = 20) | +0.0% |
| openai-snapshot | structured_extraction | 95.0% (85.0% to 100.0%, n = 20) | 95.0% (85.0% to 100.0%, n = 20) | +0.0% |
| openweights-control | structured_extraction | 95.0% (85.0% to 100.0%, n = 20) | 90.0% (75.0% to 100.0%, n = 20) | +5.0% |
