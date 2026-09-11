# The generated items: long-context recall and paraphrase robustness

Sixty of the 420 items in suite v1 are neither sampled from a public benchmark nor written by
hand. Twenty are long-context recall passages, cut by a script from public-domain novels with
one invented fact planted in each. Forty are paraphrases of twenty sampled reasoning items,
two per item. Both were done on 2026-09-11 with the suite's seed, `20260927`. This page is the
record of how, what was decided along the way, and how anyone can check the result. The
machine-readable record for the passages is `drift/suite/v1/LONGCONTEXT.json`.

Two commands, neither needing a vendor key:

```powershell
uv run drift longcontext            # generate the recall block and its manifest
uv run drift longcontext --check    # regenerate into memory and compare with the file
uv run drift paraphrase parents     # the seeded choice of the twenty items to rephrase
uv run drift paraphrase check       # the paraphrase file rephrases exactly those, two each
```

Like `drift sample`, both writers refuse a frozen suite, and `--check` is the audit path
afterwards: it re-cuts every passage from the cached texts and lists any that differ.

## Long-context recall

### What an item is

A passage of about 8,000 tokens from one novel, one invented sentence planted at a paragraph
boundary somewhere in the middle, and a question at the end that only that sentence answers.
The system prompt is `Answer the question at the end using only the passage. Reply with the
answer only.` and the grader is `exact`: the answer after normalisation (fences removed,
whitespace collapsed, casefolded, edge punctuation stripped) must equal the planted one.

### Where the passages come from

Twenty novels on Project Gutenberg, one passage each, so no author's style dominates the
block. The generator downloads each plain-text file once into the gitignored cache, keeps the
text between the `*** START` and `*** END` markers, maps typographic punctuation to ASCII
exactly as the sampler does, joins Gutenberg's hard-wrapped lines back into paragraphs, and
records the SHA-256 of the bytes it read. Every book was written in English and published
before 1930, so the text is public domain in the United States; the Gutenberg boilerplate,
which carries the Gutenberg trademark licence, is not reproduced.

| Item | Book | Paragraphs | Words | Fact | Depth |
|---|---|---|---:|---|---:|
| recall-1001 | Great Expectations (Charles Dickens), Gutenberg #1400 | 2118 to 2225 of 3915 | 5,764 | bridge | 0.13 |
| recall-1002 | Pride and Prejudice (Jane Austen), Gutenberg #1342 | 1462 to 1589 of 2509 | 5,857 | strongbox | 0.45 |
| recall-1003 | Moby-Dick; or, The Whale (Herman Melville), Gutenberg #2701 | 2288 to 2386 of 2802 | 5,775 | millwheel | 0.68 |
| recall-1004 | Jane Eyre (Charlotte Bronte), Gutenberg #1260 | 2078 to 2158 of 4115 | 5,753 | packet | 0.17 |
| recall-1005 | The Adventures of Sherlock Holmes (Arthur Conan Doyle), Gutenberg #1661 | 1163 to 1301 of 2546 | 5,816 | printer | 0.18 |
| recall-1006 | Frankenstein; or, The Modern Prometheus (Mary Shelley), Gutenberg #84 | 151 to 224 of 797 | 5,749 | physician | 0.80 |
| recall-1007 | A Tale of Two Cities (Charles Dickens), Gutenberg #98 | 2320 to 2418 of 3327 | 5,731 | bell | 0.55 |
| recall-1008 | Dracula (Bram Stoker), Gutenberg #345 | 308 to 373 of 2190 | 5,792 | horse | 0.17 |
| recall-1009 | Middlemarch (George Eliot), Gutenberg #145 | 3171 to 3258 of 4786 | 5,826 | coach | 0.82 |
| recall-1010 | Wuthering Heights (Emily Bronte), Gutenberg #768 | 1139 to 1264 of 1978 | 5,794 | signpainter | 0.32 |
| recall-1011 | Treasure Island (Robert Louis Stevenson), Gutenberg #120 | 851 to 970 of 1436 | 5,779 | buoy | 0.42 |
| recall-1012 | The Picture of Dorian Gray (Oscar Wilde), Gutenberg #174 | 180 to 334 of 1525 | 5,757 | village | 0.73 |
| recall-1013 | Emma (Jane Austen), Gutenberg #158 | 1725 to 1795 of 2382 | 5,859 | strongroom | 0.44 |
| recall-1014 | Anne of Green Gables (L. M. Montgomery), Gutenberg #45 | 1614 to 1688 of 1831 | 5,746 | marrow | 0.58 |
| recall-1015 | The War of the Worlds (H. G. Wells), Gutenberg #36 | 622 to 687 of 921 | 5,825 | telescope | 0.13 |
| recall-1016 | Persuasion (Jane Austen), Gutenberg #105 | 765 to 859 of 1040 | 5,859 | ferry | 0.21 |
| recall-1017 | The Secret Garden (Frances Hodgson Burnett), Gutenberg #113 | 1843 to 1948 of 2166 | 5,773 | apothecary | 0.74 |
| recall-1018 | David Copperfield (Charles Dickens), Gutenberg #766 | 6542 to 6636 of 7192 | 5,724 | apprentice | 0.39 |
| recall-1019 | Little Women (Louisa May Alcott), Gutenberg #514 | 3492 to 3614 of 3869 | 5,727 | daughter | 0.84 |
| recall-1020 | The Wind in the Willows (Kenneth Grahame), Gutenberg #289 | 516 to 589 of 934 | 5,761 | cat | 0.53 |

"Paragraphs" are 0-based indices into the book's paragraph list after the boilerplate is
removed; "Depth" is the share of the passage's words that come before the planted sentence.

### How a passage is cut

- **One generator per book**, derived from the seed and the Gutenberg id, so adding or
  replacing a book never moves another book's passage. The facts are assigned to books by a
  seeded permutation of the fact list.
- **The window starts at a seeded paragraph** in the body of the book: after the first tenth
  of its paragraphs (title page, contents, preface) and ending before the last twentieth. It
  runs forward until it holds at least the target number of words, so every passage is a run
  of whole paragraphs.
- **Sized in words, not tokens.** The repository has no tokenizer, and none is going to be
  added for this. The plan's 8,000 tokens at the sampler's conservative 1.4 tokens per word is
  5,714 words; the passages came out between 5,724 and 5,859 words, which is 7,500 to 8,200
  tokens on the vendors' current tokenizers. The target and the ratio are in the manifest.
- **A window is rejected and the next seeded start tried** when the planted answer already
  occurs anywhere in it (so the question has exactly one source), when a markdown fence or a
  typographic character survives the mapping, or when it has too few paragraphs to plant in.
  The generator stops with the reasons if it cannot find a window in 200 attempts, rather than
  relaxing a rule.
- **The fact is planted at a seeded paragraph boundary** whose depth lies between 10% and 90%
  of the passage. Never the first or last paragraph, where recall is trivially easy, and the
  depth is recorded so a change on this block can be read against position: models are known
  to recall the middle of a long context worse than its ends.

### The facts

Twenty invented sentences, each in the past tense and the third person so it reads like the
prose around it, each answered by a single made-up proper noun or a bare number:
"The lighthouse keeper's cat was called Bramblewick", "The bridge over the lower river had 19
arches", "The password for the clerk's strongroom was quillbarrow". They are listed in full
in `drift/sampling/longcontext.py` and a test asserts that every answer passes the exact
grader, appears in its own sentence and not in its own question, and contains no typographic
character.

**Why invented facts rather than questions about the book.** Every model on the panel has
read these novels. Asking what Pip's sister was called would measure memory of the training
set, and a change in that score month over month would say nothing about context handling. A
question about a sentence that exists only in this passage cannot be answered from memory,
which is the point of the block.

### Decisions taken while building it

**Three books were replaced after the first pass.** The first list had Kafka's Metamorphosis,
whose Gutenberg file is David Wyllie's 2002 translation, distributed with permission and
marked copyrighted in its header, so not public domain and not publishable here. The
generator now reads that header line and refuses any such file. Ulysses and Heart of Darkness
were dropped because their sampled passages carried language that PLAN.md section 8 says the
suite should not publish, and that could put a passage in front of a vendor's safety filter,
where a refusal would be graded as a failed recall and be indistinguishable from drift. The
replacements (The Wind in the Willows, Little Women, The War of the Worlds, The Secret Garden)
were chosen for plain prose and were checked the same way. The sixteen other passages did not
move, because each book has its own generator.

**Exact match is strict, on purpose.** "Bramblewick." passes, "The cat was called
Bramblewick" fails. The system prompt asks for the answer only and the output budget is 64
tokens, so a compliant model passes; a model that pads its answer fails every month in the
same way, which lowers that arm's baseline on this block rather than creating a false signal.
This is the same argument [sampling.md](sampling.md) makes for the case-sensitive `ends_with`
constraint. Softening the match to "contains the answer" would let a model that lists several
candidate names pass, which is worse.

**Numbers as answers are allowed, with a guard.** Seven facts have a bare number as the
answer. A number is more likely than an invented name to occur in a novel by chance (a
chapter number, a year), so the answer-absent check matters most for those: it is a substring
check over the whole window, so "19" is refused even when the window only contains "1900".

### Cost

Twenty items, five repeats, eight arms: 800 calls of about 8,000 input tokens each, roughly
6.4M input tokens a run, which is what PLAN.md section 6 assumed when it put the block in
("long-context block raises the mean"). The runner's expected-cost estimate uses a flat 700
tokens per call across the suite, and this block is why that figure is as high as it is.

## Paraphrase robustness

### What an item is

A closed-form reasoning item from the sampled GSM8K set, rewritten in other words twice. Each
paraphrase carries its parent's id in `parent_id`, the same system prompt, the same `numeric`
grader and the same expected value, and its own id names the parent: `para-1017-p1` and
`para-1017-p2` rephrase `reason-1017`. A gap between a parent's accuracy and its paraphrases'
is sensitivity to wording, and a large gap is itself a finding.

### Which twenty

`drift paraphrase parents` draws them from the seed, from the GSM8K items only, with a
generator derived from the seed and the block name, exactly as the sampler draws each source.
The file in the suite was written against that list, and a test asserts it still rephrases
exactly those twenty, two each. The chosen parents are reason-1001, 1004, 1006, 1009, 1011,
1014, 1016, 1018, 1022, 1030, 1032, 1033, 1035, 1037, 1038, 1041, 1050, 1051, 1052 and 1053.

**Why GSM8K only, not MATH.** A GSM8K problem is prose about a situation, so a paraphrase is
the same situation in different words, and that is what the block is meant to vary. A MATH
problem is mostly notation: "Let $f(x)=2x-4$ and $g(x)=x^2+3$" has no synonyms, and rewording
what little prose surrounds it either changes nothing or risks changing the problem. The plan
said "20 reasoning items above" without choosing; this is the choice, recorded here and in
PLAN.md section 3.

### Who wrote them, and what the loader enforces

The forty paraphrases were drafted by the assistant (Claude Code) on 2026-09-11, as
[writing-items.md](writing-items.md) said they would be, and their `source` field says so
and says "review pending". They are Peter's to approve before the freeze, and the review has
one job: read each paraphrase against its parent and confirm it asks the same question. When
that is done, the "review pending" note is replaced by the review date, which changes the
suite hash, which is fine before the freeze and impossible after it.

The suite loader will not accept a paraphrase that breaks any of these rules, so a bad edit
fails every command that loads the suite, including the tests:

- the parent is in the suite and is a closed-form reasoning item;
- the grader, the expected value and the system prompt equal the parent's;
- **every number in the parent appears in the paraphrase and no other number does**, compared
  as digit strings with thousands separators removed, so "$5,000" and "$5000" agree and
  "$6,000" does not. This is the guard that matters: a paraphrase that changes a quantity is a
  different problem, and this makes that impossible to do quietly;
- the text is not the parent's verbatim, and the two paraphrases of one parent differ.

Two things the rules do not catch, which is what the review is for: a paraphrase that keeps
every number but changes what is asked (the total instead of the difference), and a paraphrase
that resolves an ambiguity the parent left open. The drafts were written to preserve the
parent's ambiguities rather than settle them (reason-1052's "another 1/4 of his land" is kept
as written, because GSM8K's answer depends on one reading of it and settling it would change
the item's difficulty).

### Ids and files

Paraphrase items live in `drift/suite/v1/paraphrase_robustness-gsm8k.jsonl`, the recall
items in `long_context_recall-gutenberg.jsonl`; both follow the `<block>-<source>.jsonl`
convention and are merged by the suite loader with everything else in the folder. Recall
items take ids from `recall-1001`, in book order. The suite hash is independent of the split
across files.
