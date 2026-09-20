"""The gold set's 100 questions, and the 21 that were written and held back (PLAN.md B4).

The questions are content, not code: they were written by hand against the passages in
`gate/gold/sources.jsonl`, and `questions.jsonl` is generated from this file. Keeping the
source here rather than only the JSON lines does two things. It keeps the 21 spare questions,
which are as good as the hundred and were held back only because every extra question is three
more answers to label and the labelling is the critical path. And it puts each question next to
the phrases that justify it.

Every `must_mention` is a phrase lifted verbatim from the passage, because
`gate.gold.check_question` matches literally: an answerable question whose expected points are
not in its passage is a question written against the wrong page, and an unanswerable one whose
expected point IS in the passage is not unanswerable at all. Both are refused.

Regenerate with `uv run python -m gate.gold_questions`. A test asserts the committed
`questions.jsonl` is exactly what this file produces.
"""

from __future__ import annotations

from pathlib import Path

from gate import gold

ROOT = Path(__file__).resolve().parent / "gold"

# (source_id, question, must_mention, unanswerable)
Q: list[tuple[str, str, tuple[str, ...], bool]] = [
    # ---------------------------------------------------------------- banking
    (
        "fcac-020",
        "I deposited a cheque at a teller today. How much of it can I use straight away?",
        ("first $100", "immediately"),
        False,
    ),
    (
        "fcac-020",
        "What is the longest a bank can hold money I deposit by cheque?",
        ("4 to 8 days",),
        False,
    ),
    (
        "fcac-020",
        "My small company deposits cheques. Does the rule about immediate access apply to us?",
        ("eligible enterprise", "fewer than 500 employees"),
        False,
    ),
    (
        "fcac-020",
        "What fee does the bank charge me if a cheque I deposited turns out to be bad?",
        ("non-sufficient funds fee",),
        True,
    ),
    (
        "fcac-021",
        "What kinds of fee might I pay for using an ATM?",
        ("Regular Account Fee", "Network Access Fee", "Convenience Fee"),
        False,
    ),
    (
        "fcac-021",
        "What is the most a withdrawal at a privately owned ATM might cost me in total?",
        ("$1.50 to $9.00",),
        False,
    ),
    (
        "fcac-021",
        "Is there a network where I can avoid convenience fees at another institution?",
        ("THE EXCHANGE network",),
        False,
    ),
    (
        "fcac-021",
        "How much extra will I be charged for using an ATM while I am abroad?",
        ("foreign exchange fee",),
        True,
    ),
    ("fcac-022", "How much of my savings does deposit insurance cover?", ("$100,000",), False),
    (
        "fcac-022",
        "Are my mutual funds and stocks protected if my bank fails?",
        ("mutual funds", "stocks", "doesn't cover"),
        False,
    ),
    (
        "fcac-022",
        "Do I need to apply for deposit insurance or file a claim?",
        ("don't have to apply", "don't have to file a claim"),
        False,
    ),
    ("fcac-022", "What premium does my bank pay to CDIC for this insurance?", ("premium",), True),
    (
        "fcac-023",
        "Can I cash a Government of Canada cheque at a bank where I have no account?",
        ("even if you're not a customer", "for free"),
        False,
    ),
    (
        "fcac-023",
        "What identification do I need to cash a Government of Canada cheque?",
        ("three ways", "original ID, not photocopies"),
        False,
    ),
    (
        "fcac-023",
        "Is a foreign passport acceptable as one of the two documents?",
        ("foreign passports",),
        False,
    ),
    (
        "fcac-025",
        "My branch is closing. How much notice should I have been given?",
        ("4 months' notice",),
        False,
    ),
    (
        "fcac-025",
        "Is the notice period different for a branch in the countryside?",
        ("6 months' notice", "10 kilometers"),
        False,
    ),
    (
        "fcac-025",
        "When does FCAC not have to hold a meeting about a closure?",
        ("less than 500 metres away",),
        False,
    ),
    (
        "fcac-026",
        "How do I deposit a cheque using my phone?",
        ("taking a picture of the front and back of the cheque",),
        False,
    ),
    (
        "fcac-026",
        "Is my banking information kept on my phone when I deposit this way?",
        ("not stored on your device",),
        False,
    ),
    (
        "fcac-026",
        "Can I deposit a printout or a PDF of a cheque?",
        ("not a photocopy, PDF or printout",),
        False,
    ),
    (
        "fcac-026",
        "What is the largest cheque I am allowed to deposit with my phone in one day?",
        ("daily deposit limit",),
        True,
    ),
    # ---------------------------------------------------------------- credit cards
    (
        "fcac-030",
        "Can a shop charge me extra for paying by credit card, and how much?",
        ("surcharge", "2.4%"),
        False,
    ),
    (
        "fcac-030",
        "Is there an interest-free period on a cash advance?",
        ("no interest-free grace period",),
        False,
    ),
    (
        "fcac-030",
        "How does the interest rate on a cash advance compare with one on a purchase?",
        ("19%", "22%"),
        False,
    ),
    ("fcac-030", "What annual fee will I pay on a credit card?", ("annual fee",), True),
    (
        "fcac-031",
        "I am an additional cardholder on my partner's card. Am I liable for the balance?",
        ("you're not responsible for paying back any money owing",),
        False,
    ),
    (
        "fcac-031",
        "Does being an additional cardholder help me build a credit history?",
        ("won't help you build your credit history",),
        False,
    ),
    (
        "fcac-031",
        "What is the difference between a guarantor and a co-borrower?",
        (
            "A guarantor doesn't have access to the credit card account",
            "Co-borrowers have access to the credit card account",
        ),
        False,
    ),
    (
        "fcac-032",
        "Does cutting up my card or letting it expire close the account?",
        ("cutting up your card", "letting it expire", "doesn't cancel"),
        False,
    ),
    (
        "fcac-032",
        "How long before my cancelled card shows as closed on my credit report?",
        ("about 30 days",),
        False,
    ),
    (
        "fcac-032",
        "Will interest still be charged after I close the account?",
        ("Interest charges will continue to apply",),
        False,
    ),
    (
        "fcac-033",
        "What does credit card balance insurance actually cover?",
        ("lose your job", "are hospitalized"),
        False,
    ),
    (
        "fcac-033",
        "Do I have to take balance insurance to be approved for the card?",
        ("don't need to sign up",),
        False,
    ),
    ("fcac-033", "What does balance insurance cost per month?", ("monthly premium",), True),
    (
        "fcac-034",
        "What is the minimum payment on a credit card usually made up of?",
        ("$10", "3%"),
        False,
    ),
    (
        "fcac-034",
        "My payment is due on a Sunday. Will paying on Monday count as late?",
        ("Monday to Friday", "the following business day"),
        False,
    ),
    (
        "fcac-034",
        "What happens if I only ever pay the minimum?",
        ("takes you longer to pay off your balance", "you pay more interest"),
        False,
    ),
    (
        "fcac-035",
        "Someone used my debit card. What should I do first?",
        (
            "change your passwords and PINs immediately",
            "notify your financial institution or credit card issuer immediately",
        ),
        False,
    ),
    (
        "fcac-035",
        "How long do I have to dispute a transaction on my chequing account?",
        ("30 days",),
        False,
    ),
    (
        "fcac-035",
        "Will I have to pay for a transaction I never made?",
        ("you will not be held responsible",),
        False,
    ),
    # ---------------------------------------------------------------- mortgages
    (
        "fcac-040",
        "I am buying a home for $400,000. What is the smallest down payment I can make?",
        ("$20,000", "5%"),
        False,
    ),
    ("fcac-040", "What about a home priced at $600,000?", ("$35,000",), False),
    (
        "fcac-040",
        "When do I have to buy mortgage loan insurance, and who does it protect?",
        ("less than 20%", "It doesn't protect you"),
        False,
    ),
    (
        "fcac-040",
        "How much does mortgage loan insurance cost as a percentage of the loan?",
        ("insurance premium rate",),
        True,
    ),
    (
        "fcac-041",
        "What would my monthly payment be at an interest rate of 5.00%?",
        ("$1,744.81",),
        False,
    ),
    (
        "fcac-041",
        "Are fixed rates usually higher or lower than variable ones?",
        ("usually higher than variable interest rates",),
        False,
    ),
    (
        "fcac-041",
        "What is the risk with a variable rate mortgage that has fixed payments?",
        ("none of your payment goes toward paying down the principal",),
        False,
    ),
    (
        "fcac-042",
        "Can I make a lump sum payment on an open mortgage without a penalty?",
        ("open mortgage", "without paying a penalty"),
        False,
    ),
    (
        "fcac-042",
        "If I do not use my prepayment allowance this year, can I use it next year?",
        ("can't carry a prepayment amount from one year to the next",),
        False,
    ),
    (
        "fcac-042",
        "What formula do banks use to work out a prepayment penalty?",
        ("interest rate differential",),
        True,
    ),
    (
        "fcac-043",
        "I am a first-time buyer with 10% down. What is the longest amortization I can get?",
        ("30 years", "first-time buyer"),
        False,
    ),
    (
        "fcac-043",
        "And if I am not a first-time buyer and not buying a new build?",
        ("25 years in all other cases",),
        False,
    ),
    ("fcac-043", "What counts as a long-term mortgage?", ("greater than 5 years",), False),
    (
        "fcac-044",
        "What will it cost me to break my mortgage contract?",
        ("prepayment penalty", "administration fees", "appraisal fees"),
        False,
    ),
    (
        "fcac-044",
        "Is there a way to change my mortgage early without a prepayment penalty?",
        ("blend-and-extend", "you don't have to pay a prepayment penalty"),
        False,
    ),
    (
        "fcac-044",
        "Could I have to give back cash back I received?",
        ("repay any cash back you received",),
        False,
    ),
    (
        "fcac-045",
        "How long does a preapproval hold an interest rate for me?",
        ("60 to 130 days",),
        False,
    ),
    (
        "fcac-045",
        "Does a mortgage broker lend me the money, and do they charge me?",
        ("don't lend money directly to you", "generally don't charge fees"),
        False,
    ),
    (
        "fcac-045",
        "Does a preapproval mean I am guaranteed the mortgage?",
        ("does not guarantee your approval",),
        False,
    ),
    ("fcac-045", "What credit score do I need to be preapproved?", ("minimum credit score",), True),
    # ---------------------------------------------------------------- debt
    (
        "fcac-050",
        "A collection agency has written to me. What should that notice contain?",
        ("the name of the collection agency", "the amount you owe"),
        False,
    ),
    (
        "fcac-050",
        "What happens to my credit score once my debt goes to a collection agency?",
        ("your credit score will go down",),
        False,
    ),
    (
        "fcac-050",
        "Can I insist that a collector contacts me only in writing?",
        ("contact you only in writing",),
        False,
    ),
    (
        "fcac-050",
        "After how many years does a debt become too old to collect?",
        ("statute of limitations",),
        True,
    ),
    (
        "fcac-051",
        "What is debt consolidation?",
        ("combine multiple debts into one", "make 1 payment"),
        False,
    ),
    (
        "fcac-051",
        "Could consolidating actually cost me more?",
        ("extend your repayment period, costing more in interest over time",),
        False,
    ),
    (
        "fcac-052",
        "Do my creditors have to deal with a debt settlement company?",
        ("Creditors don't have to work with a debt settlement company",),
        False,
    ),
    (
        "fcac-052",
        "If my creditors refuse the offer, can the company still charge me?",
        ("may still charge you fees even if your creditors refuse",),
        False,
    ),
    (
        "fcac-052",
        "What other names do debt settlement companies trade under?",
        ("debt arbitration", "debt pooling"),
        False,
    ),
    (
        "fcac-053",
        "What should I write down about each of my debts?",
        ("total amount you owe", "minimum monthly payment", "interest rate"),
        False,
    ),
    (
        "fcac-053",
        "Should unpaid utility bills and child support go on my list of debts?",
        ("utility bills", "spousal and/or child support"),
        False,
    ),
    # ---------------------------------------------------------------- SEC: products
    (
        "sec-002",
        "What is a mutual fund?",
        ("open-end investment company that pools money from many investors",),
        False,
    ),
    (
        "sec-002",
        "In what ways can I make money from a mutual fund?",
        ("Dividend Payments", "Capital Gains Distributions", "Increased Net Asset Value"),
        False,
    ),
    ("sec-002", "What sales load will I pay when I buy into a fund?", ("sales load",), True),
    (
        "sec-010",
        "What are the two main kinds of stock?",
        ("common stock and preferred stock",),
        False,
    ),
    (
        "sec-010",
        "If a company is liquidated, who gets paid first, common or preferred holders?",
        ("have priority over common stockholders",),
        False,
    ),
    (
        "sec-010",
        "What is a growth stock, and does it usually pay dividends?",
        ("earnings growing at a faster rate than the market average", "rarely pay dividends"),
        False,
    ),
    (
        "sec-010",
        "How do I open a brokerage account to buy stocks?",
        ("open a brokerage account",),
        True,
    ),
    (
        "sec-011",
        "What am I actually doing when I buy a bond?",
        ("you are lending to the issuer",),
        False,
    ),
    ("sec-011", "How often do bonds usually pay interest?", ("every six months",), False),
    (
        "sec-011",
        "What is the difference between investment-grade and high-yield corporate bonds?",
        ("higher credit rating", "lower credit rating"),
        False,
    ),
    (
        "sec-022",
        "What is an index fund?",
        ("mutual fund, exchange-traded fund (ETF), or unit investment trust (UIT)",),
        False,
    ),
    (
        "sec-022",
        "Why do index funds tend to cost less than actively managed funds?",
        ("Passive management", "less trading of the fund's portfolio"),
        False,
    ),
    ("sec-026", "How much of a certificate of deposit is insured?", ("$250,000",), False),
    (
        "sec-026",
        "I hold three CDs at the same bank. Is each one insured separately?",
        ("not each CD or account you have at the bank",),
        False,
    ),
    (
        "sec-026",
        "Are deposit brokers licensed or approved by a regulator?",
        ("Deposit brokers are not licensed or certified",),
        False,
    ),
    (
        "sec-026",
        "What is the main risk of putting money in a CD?",
        ("inflation will grow faster than your money",),
        False,
    ),
    ("sec-027", "What is an annuity?", ("contract between you and an insurance company",), False),
    (
        "sec-027",
        "What do annuities provide?",
        ("Tax-deferred growth", "Guaranteed Income", "Death benefits"),
        False,
    ),
    (
        "sec-027",
        "When do payments start on an immediate annuity?",
        ("within one year of purchase",),
        False,
    ),
    (
        "sec-028",
        "Where do I find a fund's fees set out?",
        ("standardized fee table", "prospectus"),
        False,
    ),
    (
        "sec-028",
        "Do small differences in fees really matter?",
        ("large differences in returns over time",),
        False,
    ),
    (
        "sec-029",
        "How is net asset value calculated?",
        ("total assets minus its total liabilities",),
        False,
    ),
    (
        "sec-029",
        "A fund has an NAV of $100 million and 10,000,000 shares. What is the per share NAV?",
        ("$10",),
        False,
    ),
    (
        "sec-029",
        "How often must a mutual fund work out its NAV?",
        ("at least once every business day",),
        False,
    ),
    # ---------------------------------------------------------------- SEC: risk and fraud
    (
        "sec-005",
        "What two things does my asset allocation depend on?",
        ("time horizon", "risk tolerance"),
        False,
    ),
    ("sec-005", "How often do experts suggest rebalancing?", ("every six or 12 months",), False),
    (
        "sec-005",
        "Why does rebalancing feel wrong but make sense?",
        ("buy low and sell high",),
        False,
    ),
    (
        "sec-013",
        "What is the SEC's mission?",
        ("Protect investors", "Facilitate capital formation"),
        False,
    ),
    ("sec-013", "Which law created the SEC?", ("Securities Exchange Act of 1934",), False),
    (
        "sec-014",
        "If a company goes bankrupt, where do I stand as an ordinary shareholder?",
        ("common stockholders are the last in line",),
        False,
    ),
    (
        "sec-014",
        "How often have large company stocks lost money as a group?",
        ("one out of every three years",),
        False,
    ),
    (
        "sec-014",
        "Why is inflation a risk if I am paid a fixed rate of interest?",
        ("Inflation reduces purchasing power",),
        False,
    ),
    (
        "sec-015",
        "Why does it matter whether a company is registered with the SEC?",
        ("not registered with the SEC, it could be a red flag",),
        False,
    ),
    ("sec-015", "How many funds does the FINRA Fund Analyzer cover?", ("18,000",), False),
    (
        "sec-017",
        "Why are scams that target a community so hard to spot from outside?",
        ("outsiders may not know about the investment scam",),
        False,
    ),
    (
        "sec-017",
        "Someone at my church recommends an investment. What does the SEC advise?",
        ("Never make an investment based solely on the recommendation",),
        False,
    ),
    (
        "sec-017",
        "What should I make of an offer that will not be put in writing?",
        ("Fraudsters often avoid putting things in writing",),
        False,
    ),
    (
        "sec-018",
        "What is a Ponzi scheme?",
        ("pays existing investors with funds collected from new investors",),
        False,
    ),
    ("sec-018", "Who was it named after, and when?", ("Charles Ponzi", "1920s"), False),
    (
        "sec-018",
        "What are the warning signs of a Ponzi scheme?",
        ("High returns with little or no risk", "Overly consistent returns"),
        False,
    ),
    (
        "sec-032",
        "What are the two halves of a pump and dump?",
        (
            "boost the price of a stock with false or misleading statements",
            "dumping shares into the market",
        ),
        False,
    ),
    (
        "sec-032",
        "What happens to the share price once the fraudsters are finished?",
        ("the price typically falls",),
        False,
    ),
    (
        "sec-033",
        "What marks out a classic pyramid scheme?",
        ("high return in a short period of time", "No genuine product or service is actually sold"),
        False,
    ),
    (
        "sec-033",
        "What document should I ask a company for to check it is not a pyramid scheme?",
        ("financial statements audited by a certified public accountant",),
        False,
    ),
    (
        "sec-033",
        "Do some pyramid schemes survive?",
        ("All pyramid schemes eventually collapse",),
        False,
    ),
    (
        "sec-034",
        "What is the premise of an advance fee fraud?",
        ("you need to give money to get money",),
        False,
    ),
    (
        "sec-034",
        "I was defrauded before and someone says they can recover my money. What is that?",
        ("reload scam",),
        False,
    ),
    (
        "sec-035",
        "What is the most important thing to check before hiring an investment professional?",
        ("whether the person is registered",),
        False,
    ),
    ("sec-035", "What is Form CRS?", ("customer or client relationship summary",), False),
]


# PLAN.md B4 asks for 100 questions and 300 instances. 121 were written and validated; the
# 21 below are held back, because every extra question is three more answers for Peter to
# label and the labelling is the critical path. Each is the third or fourth question on its
# document, so every document keeps at least two and all twelve unanswerable ones stay.
HELD_BACK = {
    ("fcac-022", "Do I need to apply for deposit insurance or file a claim?"),
    ("fcac-023", "Is a foreign passport acceptable as one of the two documents?"),
    ("fcac-026", "Can I deposit a printout or a PDF of a cheque?"),
    ("fcac-030", "How does the interest rate on a cash advance compare with one on a purchase?"),
    ("fcac-031", "What is the difference between a guarantor and a co-borrower?"),
    ("fcac-032", "Will interest still be charged after I close the account?"),
    ("fcac-034", "What happens if I only ever pay the minimum?"),
    ("fcac-035", "Will I have to pay for a transaction I never made?"),
    ("fcac-041", "What is the risk with a variable rate mortgage that has fixed payments?"),
    ("fcac-043", "What counts as a long-term mortgage?"),
    ("fcac-044", "Could I have to give back cash back I received?"),
    ("fcac-045", "Does a preapproval mean I am guaranteed the mortgage?"),
    ("fcac-050", "Can I insist that a collector contacts me only in writing?"),
    ("fcac-052", "What other names do debt settlement companies trade under?"),
    ("sec-010", "What is a growth stock, and does it usually pay dividends?"),
    ("sec-011", "What is the difference between investment-grade and high-yield corporate bonds?"),
    ("sec-026", "What is the main risk of putting money in a CD?"),
    ("sec-027", "When do payments start on an immediate annuity?"),
    ("sec-029", "How often must a mutual fund work out its NAV?"),
    ("sec-005", "Why does rebalancing feel wrong but make sense?"),
    ("sec-017", "What should I make of an offer that will not be put in writing?"),
}


def questions() -> list[gold.GoldQuestion]:
    """The hundred, numbered in the order they appear above."""
    kept = [q for q in Q if (q[0], q[1]) not in HELD_BACK]
    if len(kept) != len(Q) - len(HELD_BACK):
        raise ValueError("a held-back question does not match any written question")
    return [
        gold.GoldQuestion(
            id=f"q-{n:03d}",
            source_id=source_id,
            question=text,
            must_mention=tuple(must),
            unanswerable=unanswerable,
        )
        for n, (source_id, text, must, unanswerable) in enumerate(kept, start=1)
    ]


def problems(root: Path = ROOT) -> list[str]:
    """Every question checked against the passage it names."""
    sources = gold.load(root).by_source
    out: list[str] = []
    for q in questions():
        if q.source_id not in sources:
            out.append(f"{q.id}: no source {q.source_id}")
        else:
            out.extend(f"{q.id}: {p}" for p in gold.check_question(q, sources[q.source_id]))
    return out


def main() -> None:
    g = gold.load(ROOT)
    qs = questions()
    bad = problems()
    print(f"{len(qs)} questions, {sum(1 for q in qs if q.unanswerable)} unanswerable")
    print(f"{len({q.source_id for q in qs})} of {len(g.sources)} documents used")
    if bad:
        print(f"{len(bad)} PROBLEMS:")
        for p in bad:
            print("  " + p)
        raise SystemExit(1)
    gold.write_all(ROOT / gold.QUESTIONS_FILE, qs)
    print("written to questions.jsonl")


if __name__ == "__main__":
    main()
