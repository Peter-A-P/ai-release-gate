# The labelling rubric

This is the standard. The judge is shown a shortened form of it in its prompt
([`gate/judge/rubric.py`](../gate/judge/rubric.py)); where the two differ, **this document is
what counts**, because the human reading is the measurement and the judge is the thing being
measured against it. A test fails if the prompt's rules and this document's rules drift apart.

Read this once before starting, and again before the second pass. It takes five minutes and it
is the difference between a gold set and 300 opinions.

## What you are doing

For each answer you see a source document, a question, and one model's answer. You give two
independent yes-or-no judgements. You do not see which model wrote it, and you do not see what
the judge said. Both are hidden on purpose: knowing either would make your label a reaction to
it rather than a reading of the answer.

## Judgement 1: FAITHFUL

**Is every factual claim in the answer supported by the source document?**

Say **yes** when:

- Every claim traces to something the document says.
- The answer restates, summarises, or does arithmetic on the document's own figures.
- The answer says the document does not cover something, and it does not.
- The answer is vague but not wrong. Vagueness is a completeness problem, not a faithfulness one.

Say **no** when:

- The answer states a fact the document does not state. **This holds even when the fact is true
  in the world.** The question is whether this document supports it. A model that correctly
  recalls the real deadline from its training data, when the document gives no deadline, is
  unfaithful, and catching that is most of why this gold set exists.
- The answer contradicts the document.
- The answer hedges an unsupported claim into existence: "it is usually around 30 days" when the
  document gives no number is unfaithful. Hedging does not rescue it.
- The answer attributes something to the document that the document does not say.

Edge cases, decided in advance so they are decided the same way every time:

| Case | Judgement |
|---|---|
| Answer is empty, or the model returned nothing | **not faithful**, and not complete |
| Answer is a refusal ("I can't help with that") | **faithful** (it claims nothing), not complete |
| Answer quotes the document accurately and adds nothing | faithful |
| Answer is right but cites a different regulator | not faithful |
| Answer adds a generic safety caveat ("consider speaking to an adviser") | faithful: advice to seek advice is not a factual claim about the document |
| Answer says "the document does not say" when it does say | not faithful |
| Answer gets an arithmetic step wrong on the document's own numbers | not faithful |
| Answer was cut off mid-sentence | judge what is there; a truncated answer that claims nothing false is faithful |

## Judgement 2: COMPLETE

**Does the answer address the question that was asked?**

Say **yes** when:

- The answer covers the substance of the question. Brief is fine. Two accurate sentences that
  answer the question are complete.
- The question is marked unanswerable from the source, and the answer says so.

Say **no** when:

- The answer addresses a different question.
- The answer refuses, or says only that it cannot help.
- The answer is so vague that a reader still does not know the answer.
- The question is answerable from the source and the answer says it is not.
- The answer covers only part of what was asked, and the missing part is the substance rather
  than a detail.

Each question ships with a `must_mention` list, written when the question was written and
before any model had answered it. **Use it as a checklist, not as a scoring rule.** An answer
that covers the substance in different words is complete; an answer that hits every phrase and
still does not answer the question is not.

## The two are independent

This is the rule most often got wrong, so it is worth stating on its own.

- **Complete and unfaithful** is common and important: a confident, well-structured answer full
  of invented specifics. This is the failure the gate exists to catch.
- **Faithful and not complete**: a refusal, or an answer that dodges.
- **Neither**: an empty answer, or one about a different topic entirely.

Judge faithfulness without thinking about whether the answer was useful. Judge completeness
without thinking about whether it was true.

## How to work

- `uv run gate gold label` shows one answer at a time. Two keypresses each: `y` or `n` for
  faithful, then `y` or `n` for complete. `s` skips this one, `q` stops. Anything else is
  treated as a slip and the same instance is asked again.
- **The passage and the answer are always shown whole**, wrapped to your terminal. This is not
  a convenience. The judge's prompt carries the entire source, so a labeller shown a fragment is
  applying this rubric to less evidence than the judge had, and the agreement between the two
  would be measuring the difference in what they were given.
- **Stop whenever you like.** Progress is saved after every label and the queue resumes. A
  skipped instance is unfinished rather than done, so it comes back next time.
- Expect roughly 45 to 75 seconds per instance once you are warmed up. 300 instances is about
  four to five hours, which is why it is spread over a week of evenings rather than a weekend.
- If a case is genuinely unclear, press `n` to attach a note and move on. Notes are read when
  the rubric is revised. Do not agonise; a consistent reading of an ambiguous case is worth more
  than a perfect one.
- **Do not go back and revise earlier labels to match later ones.** If your reading changes
  partway through, finish the pass, then say so. A drifting standard is exactly what the second
  pass is there to detect, and silently smoothing it over destroys that evidence.
- **A slip is not a revision, and it is fixed with `--redo`.** `uv run gate gold label --redo
  1,3,4` reopens those instances, shows you what you said last time, and appends your new
  judgement; the old line stays in the file and the last one wins. This is for the wrong key
  pressed, or an answer you realise you misread, on one instance you can name. It is not for
  sweeping back through a batch to bring it into line with how you are reading things now,
  which is the previous point and still forbidden. The difference is whether you are correcting
  a mistake about one answer or correcting the standard: the first is a repair, the second
  destroys the evidence the second pass exists to produce.

## The second pass

Two weeks after the first pass, 100 of the 300 are served again, in a different order, with no
sign of what you said the first time. `uv run gate gold label --pass 2`.

That number is the intra-rater agreement, and it is published whatever it comes out as. It is
the honest answer to "how much should we trust the gold set", and a gold set without one is
asking to be taken on faith. If a second rater outside work can be found, the same 100 go to
them and both agreements are reported; if not, the write-up says the set is single-rater and
treats that as a limitation.

## What is never done

- **The rubric is never revised to make the judge agree with it.** That is the same error as
  tuning the refusal classifier until every vendor looks safe, and Part A already refuses it.
  If the rubric changes, the version in `gate/judge/rubric.py` is bumped, the affected labels
  are re-read, and the calibration is recomputed from scratch.
- **Labels are never edited.** A correction is a new line appended to `labels.jsonl`; the last
  one wins and the history stays.
- **A label whose answer text has changed is dropped, not carried over.** Every label stores the
  hash of the text that was read, because a judgement is about the words that were in front of
  the reader.

## The distractor stratum (`d-` instances)

Added 2026-09-22, after the first 300 were read.

Some instances serve a question against a document that **does not answer it**. The question
is a real one, answerable from its own page; the page in front of the model is a different one
from the same corpus, checked to contain none of the answer.

Label them exactly as everything else. Nothing changes about the rubric:

- An answer that says the document does not cover this is **faithful**. That is the correct
  behaviour and it is not a failure.
- An answer that states a figure or a rule is **not faithful**, however true the statement
  happens to be in the world, because the document in front of you does not support it. This
  is the one place where the distinction between "true" and "supported" does the whole job,
  and the rubric has always been about supported.
- Completeness is unchanged: did the answer address the question that was asked.

You will not be told which instances these are, and you should not try to work it out. If the
passage does not contain the answer, judge on that, the same as you would for one of the twelve
questions that were written unanswerable from the start.

**Completeness on these is the ordinary rule, and it is the one that catches them.** "Does the
answer address the question that was asked?" A refusal does not, so a distractor answer that
correctly says the passage does not cover it is **faithful but NOT complete**. The user asked
how much of their cheque they can use today and still does not know.

This is the one place where completeness and faithfulness come apart in opposite directions, so
it is worth being slow about:

| what the answer does | faithful | complete |
|---|---|---|
| says the passage does not cover it, and it does not | yes | **no** |
| states the fact anyway, correctly, from somewhere else | **no** | yes |
| states the fact anyway and gets it wrong | **no** | yes |
| answers a different question using the passage it was given | yes | **no** |

Do not confuse these with the twelve questions that were **written** unanswerable. For those,
"the document does not say" IS the complete answer, because that is what the question was asking
and the pass tells you so on screen. For a distractor the question has a real answer, in a
document you are not being shown, so a refusal leaves the question unanswered. If the screen
does not say the question is unanswerable, it has an answer.

Why they exist: read by hand, the first 300 answers were faithful 300 of 300 and complete 298 of
300. A set with no unfaithful and no incomplete answer in it cannot measure whether a judge can
spot either, so a judge calibrated on it would have a number that means nothing.
`gate/distractors.py` says the rest.
