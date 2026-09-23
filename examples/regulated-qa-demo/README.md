# Regulated Q&A demo

A prompt for answering consumer questions from financial-regulator guidance, and nothing else.
It exists to be changed in pull requests, so that the release gate in
[ai-release-gate](https://github.com/Peter-A-P/ai-release-gate) has something real to decide on.

Every pull request that touches `prompts/` or `gate.yaml` is answered live on the gate's 100
gold questions by both the base branch's prompt and the pull request's, graded for completeness
by a judge calibrated against 480 hand labels, and blocked unless the drop is shown to be smaller
than ten points. The gate's comment on each pull request is the record.

What the gate does not check: faithfulness. No judge passed calibration on it, so the gate
does not pretend to grade it, and says so in every comment.
