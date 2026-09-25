"""The red-team suites (PLAN.md B7, stage 5): PII leakage, prompt injection, jailbreak and
over-refusal, each a frozen suite graded by a program, each reported as a rate with an interval.

Every item comes from a published, public source or is generated from a seed; nothing here is
novel adversarial content. The suite is built once (`gate redteam build`), hashed, and never
edited, for the reason Part A's is: a rate compared across models or months on a test that
moved is measuring the edit.
"""
