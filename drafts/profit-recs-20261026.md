# Profit review — 2026-10-26

http://localhost:3013/drafts/profit-recs-20261026

**Cost basis on every ROI below: `simulatedPositionSize` = dollars at risk, never shares.**
Every figure computed by `scripts/profit-velocity.py` §AL (this commit). Reproduce:
`DATA_MODE=live python3 scripts/profit-velocity.py --only-al` (also runs in the default pass).

---

## The lane that carries the book books 2.7× the positions it would own, and the ones it would own are the losers

The 2026-10-10 fix corrected the maker credit's **price** (2¢ flat → 2¢ × measured reach share, now
0.06–0.46¢ per band). It never touched the maker model's **volume**: every dispatched intent still
becomes a `PaperTrade` at p(fill) = 1. I verified the price half landed — post-fix legs book a mean
credit of **0.38¢** against **1.92¢** before, and the sidecar log carries 144 `mode=measured` lines
booking 0.17–0.46¢. That closes the roadmap's open "first live dispatch still owed" clause.

The volume half is what nobody has priced, and it is now measurable on 353 intents (§AL.2):

- **at the pre-fix flat-2¢ rest**: reachable within 1h on **18.4%** of legs on our own 5s L2 book
  (19.2% on the public tape — two independent instruments, 0.8pp apart), **15.4% dollar-weighted**.
  Booking assumed 100%. That is **6.5× the dollars** it would own.
- **at the live 0.06–0.46¢ rest**: **36.8%** raw, **25.7% dollar-weighted** → **3.9× the dollars,
  2.7× the positions**.

Both far below the pre-registered 74.3%/81.1% archive bar, and the mechanism is measured, not
inferred: the intent is the detection **mid** on 336/354 legs and the wallet's own print on 5/354,
detection lags the leader by a median **5.3 min**, and the resting level sits **below the first
covered best bid on 278/353 legs**. We are not posting inside the spread; we are posting through it,
and the market only comes to us when it is going the other way.

**That asymmetry is the whole finding.** Among 258 settled legs that have print-through evidence,
split by whether the modelled fill was reachable:

- **reached (n=42, $227.68): −33.0%**, and **−$110.50 even after removing the single best leg**. The
  only fills a resting bid would have owned are, uniformly, the losers.
- **not reached (n=204, $1,333.85): +78.1% booked**, +40.1% at the ask — and ex-top-1 still
  **+$115.03**, so the money is real in sign but 2–3 legs deep.

Win rates are 45.2% vs 40.2% — nearly identical. So this is **not** "we'd win more often if we
filled"; it is payoff shape: the legs that run away from our bid are the ones that carry the book,
and the booking counts them at 100% even though the fill rule that produced them is defined by
them running away. A maker copy of a directional signal owns precisely the part of the signal that
was wrong.

**What the lane actually is worth.** Era (openedAt ≥ 2026-08-28, settled): 1,698 legs, $16,170.55
booked, **+36.9%** — an edge **5.17¢ per share wide** (§AL.7: +2¢ entry still leaves +18.5%, +5¢
leaves +0.8%). Post-fix: 126 legs, $1,827.94, **+1.6%**, of which one wallet is **+$532.17** — ex-top-1
that window is **−36.5%**. Divide the booked number by the over-booking factor and the per-intended-copy
expectation is **≈ +9.5% era / +0.4% post-fix**, before applying the fill-conditional result, which is
negative. The lane is not a +37% machine; it is a spread-capture claim on fills it gets a quarter of.

---

## The two execution arms are both unproven, so the only change I can quantify is the booking

Ranked by expected value, and one of them is a correction rather than a gain. I am not presenting a
menu; #1 is the action.

## #1 — Book only what a resting bid would own: no reachable level, no position. Lane A.

**Hypothesis.** C-200's booked PnL overstates what the lane would own by 2.7× in positions and 3.9× in
dollars, so every per-copy expectation the ladder compounds (booked PnL, the "7 consecutive days at
goal" rung, the EOD headline) is inflated by that factor.

**Measurement.** `scripts/profit-velocity.py` §AL.2/§AL.2b — `data/c200-printthrough.jsonl` (latest
snapshot, 353 book-analysable intents) joined to `PaperTrade`/`FillIntent` settled legs, read-only.
Reach = a best ask at/below the resting level within 1h of dispatch on our own L2 corpus, with the
public tape as an independent second instrument. Both instruments agree within 0.8pp.

**Decision rule.** Ship when the live-model reach is **≤50% dollar-weighted** on ≥300 intents — i.e.
the model's implicit p(fill)=1 is wrong by more than 2×. Measured: **25.7%** → met with room.

**Refutation.** Revert if, on the first 150 forward legs booked fill-aware, the fill-aware PnL lands
**within 20%** of today's 100%-fill PnL on the *same* legs — that would say the over-booking is
immaterial. Also refuted if reach measured **at dispatch** (rather than from the 1h minimum) comes in
**≥80%**, which would mean my proxy is too strict — reachability from a 1-hour minimum understates
fills that happen on prints the tape never records.

**Expected effect.** C-200's booked leg count falls ~63%, its booked notional ~74%, and its
contribution to the ladder falls from **~$101/day booked (era) to ~$26/day** — and to ~$0–6/day once
the fill-conditional return is applied. This **does not add dollars**; it stops the capital plan from
compounding a number that is 3.9× too big, which is the difference between "we are 20% of the way to
$500/day" and "we are 5%".

**Cost: 3h.** Phase D2's gate ("~2 weeks of L2 book history, ≈ mid-Sep") is now open, and the v62
recorder already pins the copied market at dispatch — so the book is in hand at the moment the
decision is made. The leg needs a `pending` state that expires unfilled rather than a new model.

---

## #2 — The take-vs-make question cannot be settled from realised PnL. Settle it with a same-leg shadow. Lane A.

This is the rec I would have written as "switch to taking" an hour ago, and it does not survive its own
arithmetic. The 18% fill rate makes taking look obvious, and the take arm does look strong on paper:
same 250 coverage-clean legs, booked **+56.5%**, at-mid **+34.7%**, at-ask **+23.3%** — 33pp of drag
from a ~2.4¢ price shift, and the drag is concentrated on the cheap longshots where a few cents is a
third of the payoff.

But that comparison is not a comparison. **The booked arm's sample is chosen by its own fill rule.**
The legs a resting bid owns are the ones where the price came to it, and those lose **−33.0%**
(n=42, still −$110 after removing the best leg) — so the maker arm's *achievable* return is nothing
like the +56.5% it books. And the take arm's **ex-top-1 is −$9.17 on $1,756.34**: remove one leg and
taking earns zero. Neither number estimates the other policy, and quoting the 33pp as "the cost of
taking" would be exactly the error this review is supposed to catch.

**Hypothesis.** On the same intents, same window, the take arm's realised ROI (with an ex-top-3 cut)
is distinguishable from the fill-aware maker book's, so the execution policy can be decided on
evidence rather than on the fill-rate headline.

**Measurement.** A write-only shadow leg per C-200 intent booked at the best ask at dispatch, never
sized, never counted in any published number, excluded from `day-pnl` and the ladder — the same
contract `FillIntent` shipped under on 2026-09-25. Read both arms on the same leg identity after 150
settlements. §AL.3 already prints the two arms side by side; it cannot fix the selection, only a
forward sample can.

**Decision rule.** Switch to taking when the shadow's ROI **exceeds the fill-aware maker book's by
≥5pp with the top-3 legs removed**. Otherwise keep resting.

**Refutation.** If the shadow earns **less** than the fill-aware maker book on 150 legs, the maker
rest stands and this question is closed for a quarter — and I will not re-open it on the booked
headline (that is what produced the 2026-10-10 credit and what produced today's 3.9×).

**Expected effect.** Unlocks a policy worth **±5pp of C-200 ROI or nothing**, and — more to the point
— it is the only construction that can answer the question at all. **Cost: 2.5h** (a nullable column
plus a shadow booking in the same path `FillIntent` already hooks).

---

## #3 — The sub-0.20 band carries 57% of the lane's intended notional and 7.6% of its reachable dollars. Measured; no separate action.

Not a proposal, because #1 retires it: I am recording the number so the next reader does not
re-propose it as a band factor.

- **<0.20**: 48 intents, **$1,584.81** (57% of the sample's notional), reach **4.2%** raw /
  **7.6% dollar-weighted**, median spread 2¢. A 2¢ improvement on a 0.10 contract is 20% of the entry,
  so the level is not a resting bid, it is a wish.
- **0.2–0.4**: 81 intents, $872.21, reach **27.2% / 28.4%** — the one band where a bid at the touch
  actually trades.
- **0.4–0.6**: 177 intents, only **$206.28** (Kelly's dead-zone cap), reach 18.1% / 18.7%.

The lane's dollars and its fills are in different bands, and that is a **sizing** statement, not a
band statement: v67 already blocks sub-0.05, and a band factor cannot fix a level that the book never
touches. **Unlock for a real band decision:** a fill-aware book (#1) with ≥60 owned legs in the
sub-0.20 band — until then the 7.6% is the only number that survives.

---

## Also measured, no action

- **The rest-depth frontier is not estimable** (§AL.4). Fill rate falls monotonically with depth
  (39.3% at the touch → 17.9% at 2¢), but **ROI|fill is negative ex-top-2 at every depth** (−31.1% at
  2¢, −6.1% at 0.5¢). The fill *rate* is the only column this n can estimate; the conditional *return*
  cannot be estimated from a book whose sample is chosen by its own fill rule. Do not quote a
  preferred depth from this table.
- **The 2026-10-10 credit fix is verified live** — post-fix mean credit **0.38¢** (range 0.06–0.46),
  pre-fix **1.92¢** (range 0.38–2.00). The roadmap's "first live dispatch owed" clause can close.
- **Post-fix wallet shape**: 20 wallets, **7 positive**, one at **+$532.17** against a **+$29.39** total
  (ex-top-1 −36.5%). The era is broader — 81 wallets, 42 positive, top wallet 25.5% of PnL, ex-top-1
  **+29.5%**. I am not carding anything on 126 legs; recording it because the two windows disagree and
  a review that quoted one would have "found" either a one-wallet bet or a diversified book.
- **Detection lag 5.3 min** costs **0.5¢** per share (67% of legs enter above the leader's print).
  There is no monotone decay in the buckets (0–1 min is the *worst* bucket, n=20), so I am not
  proposing a latency project on it.

---

**IF YOU WEREN'T HERE:** make C-200's booking fill-aware today. Not one of the execution knobs — the
booking itself. The lane is 3.9× the dollars it would own and the fills it would own lose money
uniformly (−33%, still −$110 after removing the best leg), so every number the ladder reads is a
measurement of positions that do not exist.

---

*Lane B, applied directly: `scripts/profit-velocity.py` §AL (+~300 lines: `fill_reality` covering the
anchor/lag read, per-band reach, the live-model reach, the four entry arms with ex-top-N, the rest-depth
frontier, the pre/post-credit-fix split, wallet concentration, and the era entry-sensitivity with a
bisected break-even), wired into the **default** run with `--only-al` for a subset. Read-only DB. **No
RuleSet row touched, no rule edited, no `prisma/dev.db` write.***

*Two defects in my own work caught before any number shipped: (1) my first pre/post split used a cut of
2026-10-08 and reported that the measured-credit fix had never landed — the DB (`0.38¢` mean post-fix)
and the sidecar log (`mode=measured`) both say it did, and the "finding" was my own date constant;
(2) I nearly shipped "the edge lives in the legs we cannot fill" as an adverse-selection result — the
hit rates are 45.2% vs 40.2%, so the gap is payoff shape, not accuracy, and the unreached arm is
2–3 legs deep. Both corrected above, and §AL prints the ex-top-N cut beside every arm so the next
reader cannot quote the headline without seeing it.*
