# C-200 Execution-Leak — Step 2 Findings (Execution-Path Audit)

**Date:** 2026-09-03. **Status:** COMPLETE.
**Source:** scripts/score-trades.ts + src/lib/scoring/trade.ts read-through + DB cross-checks.

---

## Step 1 corrections (this audit overturned two Step-1 claims)

1. **"world executes at 0%" is an era artifact — NOT a live routing bug.** All 1,429
   world paper_copy decisions are ruleset **v2/v3 (Jul 15–19)**. C-200 did not
   exist until **v6 (Jul 22)**. Zero world signals ever reached C-200's gate
   because world stopped producing copies before C-200 was born. Retracted as
   evidence of gate mis-selection.
2. **The short-TTR lane is NOT the loser funnel — it is ~breakeven.**
   Lane trades (n=111 resolved): **−$0.026/trade**. The bleed is entirely in
   the **regular funnel** (n=1,018): **−$0.26/trade**, −$267 total.

## What the execution path actually does (verified in source)

**score-trades.ts loop** (runs every 10 min over unscored observed trades):
1. Score → `paper_copy` if copyScore ≥ 80 (minCopyScore) OR lane-eligible (TTR 2–72h, drift ≤5%, score ≥ 35).
2. **Lane copies**: fixed $10, Polymarket-only, scoped to C-200. **Regular copies**: both bots.
3. Risk gates (v40/v41): daily loss limit, gross exposure, drawdown, per-category concentration (max 40 open per research category), token circuit breaker.
4. **Venue routing**: conf > 0.8 → Kalshi **if** `kalshiEligible` (score ≥ bar AND venue realized ≥ circuit-breaker floor; floor currently tripped → Polymarket-only in practice).
5. Sizing: 70–79 sweet spot $5–10; ≥80 band capped; ×3 boost only conf > 0.9 BELOW the cap band; premium overlay; hour policy.

**The category-concentration gate (v41) is research-category based** — it caps
open positions per *research* category (Crypto/Finance/…), NOT per market
category (lol/cs2/nfl). Esports markets map to "Other" (unmapped →
heterogeneous → **uncapped**). So lol/cs2 can pile up 40+ open positions with
no gate — confirmed: the gate that should have stopped the esports
concentration structurally cannot see it.

## Mechanism of the bleed (confirmed)

- Both bots lose in lol/cs2: STANDARD −$3,945, C-200 −$495 on those two
  categories alone. **The categories are structurally −EV for the whole
  system, regardless of bot or venue.**
- C-200's regular funnel executes **the exact same decisions** STANDARD does
  (89/89 lol decisions copied by both). Same score, same signal, same
  categories — C-200 is not being routed somewhere worse; the *category mix*
  of the funnel is the problem.
- Score band of the bleed: 80–89 band = **−$3.81/trade** (n=105) in
  lol/cs2 — the worst cell in the whole system. STANDARD's 80–89 is its best
  band overall (+$1.97) because STANDARD's 80–89 is dominated by world/epl/
  dota2, NOT lol/cs2. Same band, different contents.
- Wallet sizes differ by funnel: lane copies follow small wallets (avg $40
  trade), regular copies follow **large wallets (avg $608 trade)** — the
  esports-pro whale trades that score 78–82 via wallet/category-fit
  components but don't move markets (they're the liquidity, not the edge).

## Venue (H1) — re-scoped

- Kalshi leg all-time: −$108 over 82 trades (−$1.32/t). Still the worst
  venue cell, and the v37 circuit breaker (floor tripped → Polymarket-only)
  is already doing its job — post-Aug-30 Kalshi routing is paused.
- BUT: C-200 loses on **Polymarket** in lol/cs2 too (−$420 on 268 trades).
  Venue is not the primary leak; category is. Dropping Kalshi alone saves
  ~$108; fixing the category funnel saves ~$810 (Step 1 counterfactual).

## Why the capital question and this audit connect

Capital was never the constraint (Step-1 memo: $1,504 idle, $10 size cap).
The Step-2 audit shows why even *unlimited* capital wouldn't help: the
regular funnel's per-trade expectancy is −$0.26, driven by a category mix
(lol/cs2/nfl/val) that is −EV for everyone, gated by a concentration rule
that cannot see it (research-category "Other" = uncapped). More capital
scales a negative-expectancy funnel linearly.

## Recommended rule changes (v45 candidates — recommendations only)

1. **Market-category blacklist** (both bots): `lol, cs2, nfl, val, swe2,
   clacton, bitcoin, sea, itf, mls, clf, what, nevada` — the shared structural
   −EV set. C-200 impact ≈ +$810 (its 423 blacklisted trades were −$810);
   STANDARD impact ≈ +$4,600 (cs2/lol alone −$3,945).
2. **Add a per-market-category concentration cap** (not just research-category)
   so esports can't pile up uncapped in "Other" — e.g. max 10 open per market
   category for C-200.
3. **Suspect the large-wallet esports whale lane**: consider excluding
   category-fit score component (or capping it) when wallet size > ~$300 and
   category is esports — the whales are liquidity, not signal.
4. Kalshi: keep the v37 breaker (already Polymarket-only). Revisit only if
   the category fix lands and Kalshi's own leg is re-measured clean.
5. 90+ tail clamp at 89 (STANDARD loses −$1,889 there; C-200 90+ lol/cs2
   −$1.60/t) — carryover from Step 1.

## Verification of claims

- Lane vs regular split: reasonsJson contains "Short-TTR lane" marker —
  lane n=111 −$2.89 total; regular n=1,018 −$266.55. ✔
- Era artifact: world decisions all v2/v3; C-200 first trade v6 Jul 22. ✔
- Both-bot overlap: 89/89 lol decisions copied by STANDARD AND C-200. ✔
- 80–89 lol/cs2 C-200 cell: −$3.81/t (n=105). ✔
- Concentration gate blindness: researchCategoryFor maps lol/cs2 → uncapped. ✔ (code)
