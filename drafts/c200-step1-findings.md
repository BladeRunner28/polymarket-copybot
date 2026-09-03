# C-200 Execution-Leak — Step 1 Diagnostic Findings

**Date:** 2026-09-03. **Status:** COMPLETE (read-only DB batch, approved).
**Source plan:** `drafts/c200-execution-leak-investigation.md`.

---

## TL;DR

The leak is **not** execution timing (drift), **not** venue alone, and
STANDARD's edge is real. The dominant, quantified cause is **category
selection**: C-200's executed trades concentrate in categories that lose for
*everyone* (lol, cs2, nfl — STANDARD bleeds there too), while it executes 0%
of the categories where STANDARD prints money (world, fifwc). Fixing the lane
= +$810 swing on the historical sample (from −$269 to ≈ +$540) before
touching venue or sizing.

---

## Findings by hypothesis

### H1 — Venue/routing: CONFIRMED as a contributor, not the whole story
- Kalshi: 82 trades, **−$107.93** (−$1.32/trade) — 8.6× worse than Polymarket per trade.
- Polymarket (C-200): 1,047 trades, −$161.51 (−$0.15/trade) — includes the
  Jul 23–Aug 3 starvation era; post-Aug-4 Polymarket alone is **+$86.98**.
- Kalshi leg is a genuine bleed (−$108) but Polymarket C-200 was also net
  negative all-time, so venue is not the primary cause.

### H2 — Entry drift: REFUTED
- C-200 loses even at <1pp drift: 767 trades, **−$0.30/trade** (−$231).
- STANDARD wins at <1pp drift (+$1.15/trade, 6,378 trades). Same fills,
  opposite outcomes → the loss is NOT where/when C-200 enters.
- (>30pp bucket is +$2.20 but n=19; noise.)

### H3 — Category mix: **STRONGLY SUPPORTED — the primary leak**
- C-200 biggest bleeders are **shared-loser categories**: lol −$312 (−$3.5/t),
  cs2 −$183 (−$1.07/t), nfl −$70 (−$8.8/t), val −$64 (−$1.57/t).
- STANDARD loses in the SAME categories: cs2 −$2,255 (−$3.28/t), lol −$1,690
  (−$3.27/t), nfl −$115, val resolved −$55. **Not C-200-specific routing —
  these categories are structurally −EV for the whole system.**
- **The counterfactual:** C-200 executed 423 trades in STANDARD-loser
  categories → **−$809.68**; 706 trades elsewhere → **+$540.24**. Skipping the
  loser categories alone flips C-200 from −$269 to ≈ **+$540**.

### H4 — STANDARD's edge is real (not paper): REFUTED
- STANDARD resolved: 1,474 trades, **+$6,069 realized**. Closed: +$548.
  Open book: +$563 unrealized. The +EV is realized cash-flow, not mark-to-market.
- The STANDARD-vs-C-200 comparison stands on solid ground.

### H5 — Sizing/confidence: PARTIAL, and inverted vs expectation
- C-200 best band is **70–79 (+$0.22/t)**; worst is **80–89 (−$1.13/t, −$320)**.
- STANDARD 80–89 is its BEST band (+$1.97/t) — same scorer, same band,
  opposite result ⇒ the 80–89 difference is *what sits inside the band*
  (category/venue mix), not the band itself.
- Both bots LOSE in the 90+ tail (STANDARD −$5.37/t × 352 = −$1,889). The
  boost-to-90 problem flagged in v32 discussion is real for STANDARD too.
- C-200 avg size $5.55, max $10 — sizing is not binding (see capital memo).

### NEW — Closed-vs-resolved asymmetry (worth Step-3 follow-up)
- C-200 `closed` (early exit) trades: 995, **−$578.95** (−$0.58/t).
- C-200 `resolved` (held to resolution): 134, **+$309.51** (+$2.31/t).
- Winners are disproportionately held to resolution (epl +$133 resolved,
  highest +$135 resolved); the bleed is in closed trades. Suggests an
  exit-side question: is C-200 closing losers early on the Kalshi leg or via
  a stop that STANDARD doesn't have?

### NEW — Execution-rate asymmetry (lane pull)
- 11,447 `paper_copy` decisions → only **1,144 executed (10%)**.
- Categories with 0% execution: **world (1,429 signals), fifwc (249)** —
  STANDARD's two biggest winners (+$9,977 and +$466).
- Categories with 15–21% execution: cs2, lol, mlb, atp — the losers.
- Whatever gate decides C-200 execution (confidence > 0.8 + venue routing?)
  is selecting *into* shared-loser categories and *out of* winner categories.
  This is the routing question to audit in Step 2 (sidecar + score-trades gate).

---

## Recommended rule changes (v43 candidates — recommendations only)

1. **C-200 category blacklist** (biggest lever, ~+$810 historical swing):
   `lol, cs2, nfl, val, swe2, clacton, bitcoin, sea, itf, mls, clf, what, nevada`
   — or a shared "structural −EV categories" blacklist applied to BOTH bots
   (STANDARD loses $4,000+ in lol/cs2 alone).
2. **Flip the execution gate**: investigate why `world`/`fifwc` signals
   execute at 0% while loser categories execute at 15–20%. Likely the
   conf>0.8 + Kalshi routing funnel — audit in Step 2.
3. **Kalshi leg**: drop cross-venue routing for C-200 (Polymarket-only),
   matching where its +$87 post-Aug-4 comes from. −$108 bleed gone.
4. **90+ tail**: clamp boosted scores at 89 for both bots (STANDARD loses
   −$1,889 in the 90+ tail).

## Next step

Step 2 (execution-path audit — sidecar logs, execution gate logic in
score-trades.ts, fill-price vs decision-time) is the read to confirm WHY the
gate selects into losers — but candidates 1 and 3 are implementable now on
this data alone. Awaiting approval; recommendations-only per workflow.
