# Shadow reads: both approved items measure NO-CHANGE — 2026-10-19

You approved (1) fixing the liquidity read and (2) acting on the copy cap. Before changing
anything I ran the shadow reads I said would come first. **Both come back negative, and both of my
previous claims were wrong.** No live path was changed.

`scripts/shadow-liquidity-unknown.py`. Populations are stated for every number because the two
findings died on exactly that distinction.

---

## 1. Liquidity gate — the gate is right, its log line is a lie

**What I got wrong first.** I reported that 14.8 % of declined flow was "discarded on a bad read"
and that **"746 of 746 (100 %) had liquidity > 0"**. Both were artifacts:

- the 14.8 % denominator was the **broad 340 k journal**, not the labelled 80,208-row decision book;
- the "100 %" came from a loop that **skipped every decision with no snapshot** (`if r is None:
  continue`) — 54 of my 800 sample, and **39 % of the true population**. I conditioned on the very
  variable I was testing, then reported 100 %.

**The real shape of it:**

| | n | has a MarketSnapshot |
|---|---|---|
| decisions carrying `liquidity $0` | 40,941 | **61.1 %** |
| every other decision | 299,066 | **100.0 %** |

**39 % of the affected decisions are in markets our collector never saw at all** — dead slugs,
delisted markets, markets with no book. The gate is correctly refusing markets we cannot trade. It
is only *misreporting why*: `scoring/trade.ts:77` does `input.liquidity ?? 0`, so a **failed or
skipped fetch** (`score-trades.ts:428–455`) becomes the sentence "liquidity $0 < min $500".

I predicted the `spread ?? 0.1` fallback would co-occur on ~100 % of them. It co-occurs on **21.2 %**
— so most of these are not failed fetches but markets where the adapter's
`num(m.liquidityNum) ?? num(m.liquidity)` returned undefined while spread came through.

**Shadow read — what fixing it would actually admit** (rows whose *only* blockers were the
data-availability fallbacks):

| | n | hit | cost | edge | ROI | CI |
|---|---|---|---|---|---|---|
| newly admitted | **742** | 0.495 | 0.496 | **−0.0015** | **−0.2294** | [−0.514, +0.152] |

And they are **bimodal junk**: 369 rows at cost ≈0.01 (hit 0.005 — dead markets) and 364 at cost
≈0.99 (hit 0.995, ROI +0.6 % — already-decided markets). The edge is nil; the fee makes 0.01
longshots a −46 % proposition.

**Verdict: NO-CHANGE on admission.** The fix is worth nothing economically. 1.2 % of the labelled
declined book, zero edge, and half of it is uninvestable by construction.

## 2. Copy cap — the constraint is real and it is saving money

| selection | n | hit | cost | edge | ROI |
|---|---|---|---|---|---|
| blocked by **any** copy cap | 1,029 | 0.550 | 0.552 | **−0.0015** | −0.0186 |
| cap (10) specifically | 418 | 0.514 | 0.517 | −0.0031 | +0.0044 |
| cap (25) specifically | 609 | 0.575 | 0.575 | −0.0003 | −0.0341 |
| **acted baseline** | 3,514 | 0.604 | 0.615 | **−0.0106** | −0.0399 |

Capped-out flow is **not** better than what gets through — it is slightly *less bad* and still
non-positive. Raising either cap would admit more zero-edge flow, and it would do it at a size cost.

By band it is negative nearly everywhere (−0.020, −0.010, −0.026, −0.042) with two positive cells at
0.65–0.80 (+0.075, n=143) and 0.80+ (+0.042, n=155) — too small and too high-priced to make a cap
change on.

**Verdict: NO-CHANGE.** I framed this last message as "capacity-bound as much as judgement-bound" and
implied unlocking 12.5 % of flow was a decision worth making. **It isn't.** The cap is protective,
not costly.

## 3. What survives

Nothing about gate tuning. The honest position after three measurement passes:

- **Gate tuning is exhausted as a hypothesis.** The two largest "non-judgement" blockers both guard
  worthless flow. There is no cheap fix hiding in the admission layer.
- **Copybot's whole selection has negative edge** (acted −0.0106 per share, ROI −0.0399) and that is
  the actual problem, not which gate fires.
- **The only region with positive measured edge remains the cheap longshot tail** (cost ≤ 0.20:
  blind +36.8 %, model-selected half +106.8 %), which is blocked by the *compound* of drift, min-TTR
  and near-certainty gates — not by the two I investigated — and which still carries the unmodelled
  fillability risk.
- **One real defect survives, and it is diagnostics-only**: the blocker text states a market fact
  ("liquidity $0") when the cause is a data absence. It cost this session a cycle and would mislead
  the next one. Worth fixing for honesty, provided the string change is checked against the tuning
  reviewers' greps first — those counts are load-bearing analytics here.

## 4. Recommendation

Close both cards as measured NO-CHANGE with the evidence attached so neither is re-opened casually.
Do not touch admission. The remaining question with evidence behind it is the cheap-tail shadow lane
— pre-registered, sized at zero, fill assumption tested against book depth before a single dollar
moves.
