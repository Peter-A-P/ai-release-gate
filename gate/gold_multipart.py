"""A DRAFT stratum of multi-part questions, for a suite a short answer fails. Not in use yet.

Why it exists. On the demo repository, #3 cut every answer to one sentence of at most 15 words
and passed at 99% against 100%, because the gold set's 100 questions are at their ceiling: 66 of
them ask for one fact, and the rubric rightly says a brief answer that states it is complete.
A suite on which brevity cannot fail cannot gate brevity (docs/gate-action.md). The fix is
never to change the rubric until the demo comes out as expected. It is questions whose
substance has several parts, so an answer that drops a part is incomplete by the rubric as
written: "covers only part of what was asked, and the missing part is the substance rather than
a detail".

How they were written, 2026-09-28, by the assistant, for Peter to review before anything is
generated or labelled. Each question asks for two or three things out loud, or for a list the
passage gives in full, and names at least three expected points. Every point is a phrase taken
exactly from the passage and checked there by `gate.gold.check_question`, as for the first 100.
They use the same 40 committed passages, so nothing new is fetched. All are answerable: this
stratum measures completeness, and the first 100 keep the unanswerable ones. None repeats one of
the 100 word for word, and where one overlaps it asks for the whole of what the older one asked
for part of.

71 were drafted and 21 are held back, leaving 50, which is 150 answers to label at three models
a question. Every held-back one is the second or third on its document, so every document keeps
at least one. Ids start at q-201 so they can never collide with the first set.

Nothing reads this file yet. After review it becomes part of `questions.jsonl`, tagged as its own
stratum, and the live suite that gates the demo is kept to the first 100 unless a spec asks for
it by name. Adding it must not change what an existing spec gates on.

Check with `uv run python -m gate.gold_multipart`, and rewrite the review document,
`docs/gold-multipart-draft.md`, by adding `--write-doc`.
"""

from __future__ import annotations

import sys
from pathlib import Path

from gate import gold

ROOT = Path(__file__).resolve().parent / "gold"
REVIEW_DOC = Path(__file__).resolve().parent.parent / "docs" / "gold-multipart-draft.md"
FIRST_ID = 201

# (source_id, question, must_mention). All answerable.
Q: list[tuple[str, str, tuple[str, ...]]] = [
    # ---------------------------------------------------------------- banking
    (
        "fcac-020",
        "I'm depositing a cheque at an ATM tonight. How much of it can I use before the rest "
        "clears, from when, and what is the longest the bank can hold the rest?",
        ("first $100", "on the business day after the day of the deposit", "4 to 8 days"),
    ),
    (
        "fcac-020",
        "Why would my bank put a hold on a cheque I deposit? What are all the reasons?",
        ("has enough money to cover it", "stop payment", "has not been altered", "still open"),
    ),
    (
        "fcac-020",
        "What makes a business an eligible enterprise that does not get immediate access to the "
        "first $100?",
        ("less than $1 million", "less than $50 million", "fewer than 500 employees"),
    ),
    (
        "fcac-021",
        "I'm taking cash out at a privately owned ATM. Which fees get added together, and what "
        "might the whole withdrawal cost?",
        ("regular account fee", "network access fee", "convenience fee", "$1.50 to $9.00"),
    ),
    (
        "fcac-021",
        "What is the difference between a network access fee and a convenience fee, and who "
        "charges each one?",
        (
            "financial institution doesn't own",
            "privately-owned ATM operators",
            "where you don't have a bank account",
        ),
    ),
    (
        "fcac-022",
        "Which of my accounts does CDIC cover, up to how much, and do I need to file a claim if "
        "my bank fails?",
        (
            "$100,000",
            "savings and chequing accounts",
            "Guaranteed Investment Certificates",
            "don't have to file a claim",
        ),
    ),
    (
        "fcac-022",
        "My credit union is provincially regulated. Who insures my deposits there, and who "
        "should I ask about how they are protected?",
        (
            "Provincial deposit insurance plans",
            "provincially regulated credit unions",
            "Contact your provincial deposit insurer",
        ),
    ),
    (
        "fcac-022",
        "What will deposit insurance not protect, and does it cover money I hold in US dollars?",
        ("mutual funds", "cryptocurrencies", "losses due to fraud or theft", "foreign currency"),
    ),
    (
        "fcac-023",
        "Where can I cash my Government of Canada cheque, will it cost me anything, and what "
        "single piece of ID would be enough?",
        (
            "any branch of a bank in Canada",
            "for free",
            "even if you're not a customer",
            "signature and photograph",
        ),
    ),
    (
        "fcac-023",
        "If I prove who I am with two documents, what must each one show, and can I bring "
        "photocopies?",
        ("name and address", "name and date of birth", "original ID, not photocopies"),
    ),
    (
        "fcac-025",
        "My rural branch is closing and there is no other branch within 10 km. How much notice "
        "must the bank give, and who else must it tell?",
        (
            "6 months' notice",
            "notify your local government",
            "publish a notice in a local newspaper",
        ),
    ),
    (
        "fcac-025",
        "What details must the notice that my branch is closing include?",
        (
            "the location of the branch that's closing",
            "the date of the closure",
            "the address of the branch to which they'll transfer your accounts",
        ),
    ),
    (
        "fcac-025",
        "When will FCAC's Commissioner hold a meeting about a branch closing, and what must be "
        "true of the request for one?",
        (
            "writes to FCAC asking for such a meeting",
            "failed to properly consult the community",
            "frivolous",
            "vexatious",
        ),
    ),
    (
        "fcac-026",
        "Which cheques can I deposit with my phone, and what should I do with the paper cheque "
        "afterwards?",
        (
            "made out to you",
            "joint account",
            "issued by any level of government in Canada",
            "storing your cheque until it has cleared",
        ),
    ),
    (
        "fcac-026",
        "If I deposit a cheque with my phone, can I be charged a fee, and can the money be held?",
        (
            "may charge a fee to deposit cheques electronically",
            "Hold periods",
            "may apply to electronic cheque deposits",
        ),
    ),
    # ---------------------------------------------------------------- credit cards
    (
        "fcac-030",
        "A shop wants to add a surcharge for paying by credit card. How much can it be, when "
        "must they tell me, and how can I avoid it?",
        ("2.4%", "before processing your payment", "cash or debit", "another merchant"),
    ),
    (
        "fcac-030",
        "Why is a cash advance on my credit card so expensive? Give me the interest details.",
        (
            "no interest-free grace period",
            "from the date you get a cash advance",
            "usually higher than for regular purchases",
        ),
    ),
    (
        "fcac-030",
        "How do I catch mistakes on my credit card statement, who do I contact first, and what "
        "if they do not fix it?",
        ("keep receipts", "contact the merchant", "contact your financial institution"),
    ),
    (
        "fcac-031",
        "Who is responsible for the balance: an additional cardholder, a co-borrower, or a "
        "guarantor?",
        (
            "additional cardholder: not responsible for paying back any money owing",
            "Co-borrowers have access to the credit card account and are equally responsible for "
            "the balance",
            "A guarantor doesn't have access to the credit card account but is responsible for "
            "the balance",
        ),
    ),
    (
        "fcac-031",
        "As the primary cardholder, what can I do about other people on my card, and what am I "
        "responsible for?",
        (
            "add and remove additional cardholders",
            "responsible for paying your credit card balance",
            "responsible for paying for these purchases",
        ),
    ),
    (
        "fcac-032",
        "How do I properly cancel a credit card, and what should I get and check afterwards?",
        ("ask to cancel your account", "confirmation in writing", "Check your credit report"),
    ),
    (
        "fcac-032",
        "After I cancel my card, what charges can still appear, and what happens to payments I "
        "set up to come off it automatically?",
        (
            "transactions you approved before you closed your account",
            "recurring transactions",
            "the company will continue to bill you",
        ),
    ),
    (
        "fcac-033",
        "When might someone offer me balance insurance, and do I have to take it to get the card?",
        (
            "apply for a credit card",
            "activate your card",
            "credit limit increase",
            "don't need to sign up",
        ),
    ),
    (
        "fcac-033",
        "When might I not need credit card balance insurance at all?",
        (
            "enough savings to pay your balance",
            "pay your balance in full each month",
            "coverage from another insurance policy",
        ),
    ),
    (
        "fcac-034",
        "How is my credit card's minimum payment worked out, and what does paying only the "
        "minimum cost me?",
        ("$10", "3%", "takes you longer to pay off your balance", "pay more interest"),
    ),
    (
        "fcac-034",
        "If I do not pay my full balance by the due date, what happens with interest, and what "
        "does it do to my credit score?",
        (
            "interest from the date you made the purchase",
            "increase the cost of everything you buy",
            "hurt your credit score",
        ),
    ),
    (
        "fcac-035",
        "Someone stole my phone and could get into my banking. What should I do?",
        (
            "change your passwords and PINs immediately",
            "notify your financial institution",
            "report any transactions",
            "check your credit report",
            "continue to monitor your accounts",
        ),
    ),
    (
        "fcac-035",
        "If I report an unauthorized transaction, does my bank have to investigate, will I have "
        "to pay it, and is there a time limit?",
        (
            "must always investigate",
            "will not be held responsible",
            "30 days after the date of your statement",
        ),
    ),
    # ---------------------------------------------------------------- mortgages
    (
        "fcac-040",
        "I want to buy a $1.6 million home. What is the minimum down payment, could I still "
        "need mortgage loan insurance, and who would that insurance protect?",
        (
            "20% of the purchase price",
            "Your lender may require that you get mortgage loan insurance, even if you have a 20% "
            "down payment",
            "protects the mortgage lender",
        ),
    ),
    (
        "fcac-040",
        "I'm self-employed. Could that change the down payment I need, and where is that money "
        "normally expected to come from?",
        ("self-employed", "larger down payment", "from your own funds"),
    ),
    (
        "fcac-041",
        "From the table, compare a 2.50% and a 5.00% mortgage rate: the monthly payment and the "
        "interest over 25 years at each.",
        ("$1,343.90", "$103,169.61", "$1,744.81", "$223,444.49"),
    ),
    (
        "fcac-041",
        "When is a fixed rate mortgage the better fit, and what is the danger of a variable rate "
        "with fixed payments?",
        (
            "keep your payments the same",
            "market interest rates will go up",
            "none of your payment goes toward paying down the principal",
        ),
    ),
    (
        "fcac-042",
        "In what situations can my lender charge me a prepayment penalty?",
        (
            "pay more than the allowed additional amount",
            "break your mortgage contract",
            "transfer your mortgage to another lender",
            "including when you sell your home",
        ),
    ),
    (
        "fcac-042",
        "What do prepayment privileges let me do, and what should I check in my contract about "
        "them?",
        (
            "increase your regular payments by a certain percentage",
            "make lump-sum payments",
            "if there's a minimum or a maximum amount",
        ),
    ),
    (
        "fcac-043",
        "What is the difference between a mortgage term and the amortization period, and what "
        "happens at the end of a term?",
        (
            "time your mortgage contract is in effect",
            "time it takes to pay your mortgage",
            "renew your mortgage",
        ),
    ),
    (
        "fcac-043",
        "I'm putting 25% down. Who sets my maximum amortization, and what is the downside of "
        "stretching it to lower my payments?",
        (
            "your lender sets your maximum amortization period",
            "interest costs that you'll need to pay will be higher",
            "thousands or tens of thousands of dollars",
        ),
    ),
    (
        "fcac-044",
        "Why might I break my mortgage early, and apart from a prepayment penalty, what other "
        "fees could I face?",
        (
            "interest rates have gone down",
            "appraisal fees",
            "reinvestment fees",
            "mortgage discharge fee",
        ),
    ),
    (
        "fcac-044",
        "How does blend-and-extend work, and does it cost anything?",
        (
            "extend the length of your mortgage before the end of your term",
            "blend your old interest rate and the new term's interest rate",
            "administrative fees",
        ),
    ),
    (
        "fcac-045",
        "What can a mortgage preapproval do for me, and does it guarantee I get the mortgage?",
        (
            "maximum amount of a mortgage",
            "estimate your mortgage payments",
            "60 to 130 days",
            "does not guarantee",
        ),
    ),
    (
        "fcac-045",
        "Should I go to a lender or a broker? How do they differ in who lends the money and "
        "what they can offer?",
        (
            "lend money directly to you",
            "don't lend money directly to you",
            "wider range of mortgage products",
            "ask which lenders they work with",
        ),
    ),
    # ---------------------------------------------------------------- debt
    (
        "fcac-050",
        "A debt collector just called me. What should I write down about them, and what should "
        "I ask about the debt?",
        (
            "the agent's name",
            "the company they work for",
            "the amount you owe",
            "when you started owing it",
        ),
    ),
    (
        "fcac-050",
        "My creditor says it will send my debt to a collection agency. What can I do to stop "
        "that, and what would it do to my credit score?",
        (
            "contact your creditor immediately",
            "pay a portion of the amount",
            "alternative arrangements",
            "your credit score will go down",
        ),
    ),
    (
        "fcac-050",
        "Beyond borrowing, what can a low credit score mean for me?",
        (
            "insurance companies may charge you more",
            "landlords may refuse to rent to you",
            "employers may not hire you",
        ),
    ),
    (
        "fcac-051",
        "Could debt consolidation help my credit score, and when could it make my debt worse?",
        (
            "make your payments on time",
            "reduce the number of high balance accounts",
            "higher interest rate than your current products",
        ),
    ),
    (
        "fcac-052",
        "How does a debt settlement company make its money, and what should I make sure of "
        "before I sign a power of attorney for one?",
        (
            "operate for profit",
            "fees they charge their clients",
            "inform you of all payments they make to your creditors",
        ),
    ),
    (
        "fcac-053",
        "How does making a budget help me pay off my debts?",
        (
            "identify your debts",
            "balance your income with your savings and expenses",
            "prioritize debt repayment",
            "track your progress",
        ),
    ),
    # ---------------------------------------------------------------- investing
    (
        "sec-002",
        "Why do people buy mutual funds? What are the main features?",
        ("Professional Management", "Diversification", "Low Minimum Investment", "Liquidity"),
    ),
    (
        "sec-005",
        "How do my time horizon and my risk tolerance each affect my asset allocation?",
        (
            "longer time horizon",
            "riskier or more volatile investments",
            "high risk tolerance is willing to risk losing money",
        ),
    ),
    (
        "sec-005",
        "My portfolio started at 60% stocks and is now 80%. What should I do, why, and how often?",
        (
            "rebalance",
            "sell some of your stocks",
            "buy low and sell high",
            "every six or 12 months",
        ),
    ),
    (
        "sec-010",
        "How do common and preferred stock differ on voting, on dividends, and if the company "
        "goes bankrupt?",
        (
            "Common stock entitles owners to vote at shareholder meetings",
            "Preferred stockholders usually don't have voting rights",
            "receive dividend payments before common stockholders",
            "priority over common stockholders",
        ),
    ),
    (
        "sec-010",
        "What are growth, income and value stocks, and does each tend to pay dividends?",
        ("rarely pay dividends", "pay dividends consistently", "low price-to-earnings (PE) ratio"),
    ),
    (
        "sec-011",
        "Why do investors buy bonds?",
        (
            "predictable income stream",
            "preserve capital",
            "offset exposure to more volatile stock holdings",
        ),
    ),
    (
        "sec-011",
        "How do investment-grade and high-yield corporate bonds differ in rating, risk and "
        "interest?",
        (
            "Investment-grade: higher credit rating, implying less credit risk",
            "High-yield: lower credit rating, implying higher credit risk",
            "High-yield: higher interest rates in return for the increased risk",
        ),
    ),
    (
        "sec-013",
        "What is the SEC's three-part mission, and what two ideas are the securities laws "
        "based on?",
        (
            "Protect investors",
            "Maintain fair, orderly, and efficient markets",
            "Facilitate capital formation",
            "must tell the truth",
            "treat investors fairly and honestly",
        ),
    ),
    (
        "sec-014",
        "If a company goes bankrupt, in what order are bondholders, preferred stockholders and "
        "common stockholders paid?",
        (
            "bondholders will be paid first",
            "then holders of preferred stock",
            "common stockholders are the last in line",
        ),
    ),
    (
        "sec-014",
        "How do interest rates affect a bond I hold, depending on whether I keep it to maturity "
        "or sell it early?",
        (
            "held to maturity the investor will receive the face value, plus interest",
            "may be worth more or less than the face value",
            "Rising interest rates will make newly issued bonds more appealing",
        ),
    ),
    (
        "sec-015",
        "When must companies give investors information, and what does it mean if a company is "
        "not registered with the SEC?",
        (
            "when they initially offer stocks or bonds",
            "periodically",
            "If a company is not registered with the SEC, it could be a red flag",
            "not registered with the SEC: Scams often involve unregistered companies",
        ),
    ),
    (
        "sec-017",
        "Someone I trust has brought me an investment. What does the SEC advise me to do?",
        (
            "research the person's background",
            "Never make an investment based solely on the recommendation",
            "Fraudsters often avoid putting things in writing",
            "Don't be pressured or rushed",
        ),
    ),
    (
        "sec-018",
        "Why do Ponzi schemes collapse, and which red flags about registration and payouts "
        "should I watch for?",
        (
            "require a constant flow of new money to survive",
            "Unregistered investments",
            "Unlicensed sellers",
            "Difficulty receiving payments",
        ),
    ),
    (
        "sec-022",
        "What does an index fund try to do, and what are the cost and tax advantages of passive "
        "management?",
        (
            "same return as a particular index",
            "lower transaction costs",
            "lower realized capital gains",
            "lower fees and expenses",
        ),
    ),
    (
        "sec-026",
        "What should a CD's disclosure statement tell me?",
        (
            "interest rate on the CD",
            "fixed or variable",
            "when the bank pays interest",
            "maturity date",
            "early withdrawal",
        ),
    ),
    (
        "sec-026",
        "What is a brokered CD, and how should I check out a deposit broker?",
        (
            "negotiate a higher rate of interest",
            "bring a certain amount of deposits",
            "history of complaints or fraud",
            "state's consumer protection office",
        ),
    ),
    (
        "sec-027",
        "How can I pay for an annuity, when do payments to me start, and what happens if I take "
        "the value as a lump sum instead?",
        (
            "single lump-sum payment or series of payments",
            "beginning immediately or at some future date",
            "may subject you to surrender charges, taxes, and tax penalties",
        ),
    ),
    (
        "sec-027",
        "What happens if the insurance company behind my annuity gets into trouble, and who are "
        "annuities suitable for?",
        (
            "financial strength and claims-paying ability",
            "may not be able to pay you",
            "long-term investment time horizon",
        ),
    ),
    (
        "sec-028",
        "What costs does running a mutual fund involve, and where are the fees set out?",
        (
            "investment advisory fees",
            "marketing and distribution expenses",
            "standardized fee table",
            "prospectus",
        ),
    ),
    (
        "sec-029",
        "How often must a mutual fund calculate its NAV, at what time of day, and which kind of "
        "fund does not have to?",
        (
            "at least once every business day",
            "after the major U.S. exchanges close",
            "closed-end fund",
        ),
    ),
    (
        "sec-029",
        "How does NAV decide what I pay when I buy mutual fund shares and what I get when I "
        "redeem them?",
        (
            "per share NAV, plus any fees",
            "sales loads or purchase fees",
            "minus any fees",
            "redemption fees",
        ),
    ),
    (
        "sec-032",
        "How does a pump and dump work, where does it usually happen, and what do promoters "
        "often claim?",
        (
            "false or misleading statements",
            "dumping shares into the market",
            "on the Internet",
            'claim to have "inside" information',
        ),
    ),
    (
        "sec-033",
        "What are the hallmarks of a pyramid scheme?",
        (
            "Emphasis on recruiting",
            "No genuine product or service is sold",
            "Promises of high returns in a short time period",
            "Easy money or passive income",
            "No demonstrated revenue from retail sales",
        ),
    ),
    (
        "sec-034",
        "What can the up-front payment in an advance fee fraud be called, and how does it tie in "
        "with relationship scams?",
        (
            "fee, tax, commission, validation fee",
            "relationship investment scams",
            "deposit funds to get the funds released",
        ),
    ),
    (
        "sec-035",
        "How should I think about what an investment professional costs me, and what should I "
        "check before hiring one?",
        (
            "no such thing as a free lunch",
            "how and how much your adviser is being paid",
            "what that translates to in dollars",
            "registered with us or with a state securities regulator",
        ),
    ),
]

# Held back: written, checked and kept, but not in the fifty. Each is the second or third on its
# document, so every document keeps one.
HELD_BACK: set[tuple[str, str]] = {
    ("fcac-020", Q[2][1]),
    ("fcac-021", Q[4][1]),
    ("fcac-022", Q[7][1]),
    ("fcac-023", Q[9][1]),
    ("fcac-025", Q[12][1]),
    ("fcac-026", Q[14][1]),
    ("fcac-030", Q[17][1]),
    ("fcac-031", Q[19][1]),
    ("fcac-032", Q[21][1]),
    ("fcac-033", Q[22][1]),
    ("fcac-034", Q[25][1]),
    ("fcac-035", Q[27][1]),
    ("fcac-040", Q[29][1]),
    ("fcac-041", Q[30][1]),
    ("fcac-042", Q[33][1]),
    ("fcac-043", Q[35][1]),
    ("fcac-044", Q[36][1]),
    ("fcac-045", Q[39][1]),
    ("fcac-050", Q[42][1]),
    ("sec-010", Q[50][1]),
    ("sec-027", Q[63][1]),
}


def questions() -> list[gold.GoldQuestion]:
    """The fifty, numbered from q-201 in the order they appear above."""
    kept = [q for q in Q if (q[0], q[1]) not in HELD_BACK]
    if len(kept) != len(Q) - len(HELD_BACK):
        raise ValueError("a held-back question does not match any written question")
    return [
        gold.GoldQuestion(id=f"q-{n:03d}", source_id=source_id, question=text, must_mention=must)
        for n, (source_id, text, must) in enumerate(kept, start=FIRST_ID)
    ]


def problems(root: Path = ROOT) -> list[str]:
    """Every question, the held-back ones too, checked against the passage it names."""
    sources = gold.load(root).by_source
    out: list[str] = []
    for n, (source_id, text, must) in enumerate(Q):
        q = gold.GoldQuestion(id="q-999", source_id=source_id, question=text, must_mention=must)
        if source_id not in sources:
            out.append(f"#{n}: no source {source_id}")
            continue
        out.extend(f"#{n} ({source_id}): {p}" for p in gold.check_question(q, sources[source_id]))
        if len(must) < 3:
            out.append(f"#{n} ({source_id}): only {len(must)} expected points; a part needs three")
    return out


def review_markdown(root: Path = ROOT) -> str:
    """The draft as a document to review: each question under its passage's title, the points
    it expects, and whether it is in the fifty. Generated, so it cannot drift from this file."""
    g = gold.load(root)
    kept = {(q.source_id, q.question): q.id for q in questions()}
    lines = [
        "# Multi-part questions: draft for review",
        "",
        "Generated by `uv run python -m gate.gold_multipart --write-doc` from",
        "`gate/gold_multipart.py`; edit that file, never this one. Why the stratum exists and how",
        "the questions were written is in that file's docstring. Nothing here is in the gold set",
        "yet.",
        "",
        f"{len(Q)} drafted over {len({s for s, _, _ in Q})} passages. {len(kept)} are kept, marked",
        f"with an id, and {len(Q) - len(kept)} are held back as spares. Every expected point is a",
        "phrase from the passage, checked there.",
        "",
        "**To review, run `uv run gate gold review-draft`.** It shows one question at a time,",
        "each point inside its sentence of the passage, and takes one key: y keep, n drop,",
        "c change. It saves as you go, resumes where you stopped, and offers spares for any",
        "page that loses a question. This file is the same list, for reading.",
        "",
        "What to look for:",
        "",
        "- Does each question read like something a person would ask?",
        "- Does it ask for everything its points list, so that an answer missing one really has",
        "  left out part of what was asked, and not just a detail?",
        "- Is any point a detail rather than the substance? That would make a complete, brief",
        "  answer look incomplete, which is the error this stratum must not introduce.",
        "- Should a spare replace a kept one?",
    ]
    current = ""
    for source_id, text, must in Q:
        if source_id != current:
            current = source_id
            lines += ["", f"## {source_id}: {g.by_source[source_id].title}"]
        qid = kept.get((source_id, text))
        tag = f"**{qid}**" if qid else "*held back*"
        lines += ["", f"{tag}. {text}", ""]
        lines += [f"- {m}" for m in must]
    return "\n".join(lines) + "\n"


def main() -> None:
    qs = questions()
    bad = problems()
    docs = {q.source_id for q in qs}
    print(
        f"{len(Q)} drafted, {len(HELD_BACK)} held back, {len(qs)} kept, over {len(docs)} documents"
    )
    if bad:
        print(f"{len(bad)} PROBLEMS:")
        for p in bad:
            print("  " + p)
        raise SystemExit(1)
    print("every expected point is in its passage")
    if "--write-doc" in sys.argv:
        REVIEW_DOC.write_text(review_markdown(), encoding="utf-8", newline="\n")
        print(f"written to {REVIEW_DOC}")


if __name__ == "__main__":
    main()
