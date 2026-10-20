# Exposure cap porting — priced, and refused

**Date:** 2026-10-20 · **Lane:** A (proposal only, nothing applied) · **Status:** REFUSED after measurement

---

## 1. The question

The exposure cap is the last of five confirmed C-200-only scoping gaps. The other four
(stale exit, band skip, per-slug cap, `maxOpenPositions`) were closed by v62/v63/v64. The
cap is the only remaining rail that would govern **notional per dollar of cash** — the
constraint that actually matters for a book holding $13.5 K of open positions.

Should it be extended to STANDARD?

## 2. Key insight: the cap has no denominator on STANDARD

`effectiveExposureCap(baseUsd, netWorth, principal)` returns **`baseUsd` when
`principal <= 0`** — by design, "can't verify recovery against an unknown baseline."

And `BotBankroll.principal` for STANDARD is **`0.00`**. It has never been set:

| bot | principal | cash | realized |
|---|---|---|---|
| STANDARD | **0.00** | **0.00** | 0.00 |
| BANKROLL_200 | 1,900.00 | 7,763.70 | 5,944.60 |

So porting the cap to STANDARD does not give it a scaled ceiling. It gives it the **bare
base** `maxGrossExposureUsd = $1,000` (the LIVE v64 value — note `DEFAULT_RULES` in
`src/lib/rules.ts` carries 250, which is only a fallback and was wrongly used in the first
draft of this document).

## 3. What that means in dollars

| bot | open legs | open notional | principal | effective cap | exposure vs cap |
|---|---|---|---|---|---|
| STANDARD | 1,263 | **$13,566.00** | 0.00 | **$1,000** | **13.6×** |
| BANKROLL_200 | 7 | $80.90 | 1,900.00 | $1,000 + 50 % above principal | ≪1× |

A $1,000 ceiling against $13,566 of open notional is not a brake. It is a **halt on the next
scoring cycle**, and it cannot recover on its own because the book's median time-to-resolution
is **115.3 days**.

Portfolio context: **$13,646.90 open notional against $7,763.70 cash = 1.76× cash**, with
$15,440.13 realized and $1,542.32 open unrealized across 11,466 finished legs.

## 4. Reality check — it takes the other lane down with it

`isPortfolioGate()` matches `/drawdown gate|gross exposure cap/`, and portfolio gates fire
**before the per-bot leg loop**. When one blocks, the cycle produces:

- no copies,
- no leg-block reasons,
- no other signal that anything is wrong.

That is precisely the September 16–18 freeze, which ran **39.7 hours before a human noticed**
and is the reason `isPortfolioGate` exists at all. Extending a C-200-calibrated absolute
dollar ceiling to a lane holding 168× more notional would recreate that failure deliberately,
and the alert path that would catch it is the same one that missed it the first time.

## 5. Second finding — the capital is not cap-constrained where it matters

The obvious counter-move ("so raise C-200's deployment instead, it has the idle cash") does
not survive contact with the numbers either:

- C-200 holds **$7,763.70 cash** and **$80.90** of open notional — **1.0 % deployed**.
- Its cap is `$1,000 + 50 % × max(0, netWorth − $1,900)`, which with net worth above principal
  works out to roughly **$6 K**, i.e. **~70× headroom**.

**C-200 is not exposure-capped. It has 7 open legs because its gates are rejecting
candidates**, not because a ceiling is holding it back. So idle cash is a *funnel* problem,
not a *rail* problem, and pre-empting the measurement with a cap change would treat the wrong
organ.

## 6. Verdict

**Do not port the exposure cap.** Two independent reasons, either sufficient:

1. With STANDARD's principal at 0, the port yields a **$1,000** ceiling against **$13,566** —
   a 13.6× immediate halt on a 115-day book.
2. As a portfolio gate it would freeze **C-200** as well, silently, which is a known
   undetected-failure mode with a 39.7 h precedent.

## 7. What is actually next (the prerequisite nobody priced)

**Set STANDARD's `principal` and `cashBalance`.** Until that row is populated, *every*
ratio-based rail is undefined for the lane carrying 87 % of the book's notional — the cap, any
notional-per-cash limit, and any per-lane return-on-capital figure. The lane has no accounting
identity, so it cannot be risk-managed by ratio at all.

Candidates for the value, and each is a Lane A decision because it sets the ceiling:

- **Measured contribution** — principal equal to the lane's realised+unrealised contribution,
  which makes the cap self-consistent but also immediately large.
- **Deposited capital** — what was actually funded to STANDARD, if it is recoverable from the
  capital-deposit history (`scripts/capital-deposits-report.ts` already models deposits).
- **Portfolio split** — allocate total principal across lanes by measured edge per
  capital-day (C-200 $0.3818 vs STANDARD $0.0114), which would make the ratio rails express
  the allocation decision rather than contradict it.

The third is the only one that makes the rail and the strategy say the same thing. It is also
the largest change, so it should not be chosen by default.

---

## Numbers used, with provenance

| figure | source |
|---|---|
| principal / cash / realized per bot | `BotBankroll` table |
| open notional per bot | `PaperTrade` where `status='open' AND isDemo=0` |
| 11,466 legs / $15,440.13 realized | same, `status IN ('closed','resolved')` |
| cap formula | `src/lib/exposure-cap.ts` `effectiveExposureCap` |
| portfolio-gate blast radius | `isPortfolioGate`, `scripts/score-trades.ts:198` |
| 115.3 day median TTR | card C re-baseline, 2026-10-20 |
| $0.3818 vs $0.0114 per capital-day | band/capital review, 2026-10-20 |
