# v52 — Tuning Review #19 defect fixes (user-approved 2026-09-08; Kelly window starts today)

Four linked fixes, all approved as defect/state corrections (NOT regime changes)
— the Kelly window (Sep 8–Oct 8) now measures an honest, unfrozen, non-duplicate
book. Code-only: no RuleSet bump.

## ① Sweep-fill duplicate coalescing — `scripts/score-trades.ts` (the root cause)

**Bug:** one wallet sweeping one market+outcome in seconds is ONE economic
intent (exchange-level order splits), but every fill scored independently as a
full-size copy. Evidence: bkfibaw 4 fills/1s → 4×$91.49@0.04 → −$361.40 (Sep 8);
ucl-rma-draw 18-fill in-batch cluster (153 pairwise ≤30s pairs, still open);
7d history: gemini −$359, elon-160 −$360, val-m8gc −$378 cluster losses.

**Fix:** per-run `recentCopyKeys` set of (walletAddress|marketId|outcome) for
copies opened within the last 15 min (one monitor cycle + margin, any status),
extended in-loop after each successful open. Any observed trade matching an
existing key is skipped with a `[DEDUPE]` log line and a run counter
(`N sweep-duplicates coalesced` in the completion log). Collapses an N-fill
sweep to exactly one copy regardless of batch ordering (batch is timestamp-desc;
the first-processed fill opens and anchors the rest).

## ② Drawdown peak reset — `data/c200-drawdown.json`

Peak $2,680.66 was artifact-contaminated (written 2026-09-07T17:59Z by the
intraday markup of the 4 duplicate bkfibaw copies, resolved at full loss → NW
$1,773.74 = 41% off the fake peak → 0 opens since 01:13 Sep 8). The tracker is
DESIGN-seeded from principal (apply-risk-gates 2026-09-01) and the gate's NW
(principal + ledger realized + open unrealized) never legitimately exceeded
$1,900. Reset to **$1,900**; verified: NW $1,773.74 < peak → reset sticks;
drawdown 6.6% < 20% cap → book unfrozen for the window. Note carried in-file.

## ③ EOD lifetime totals include 'closed' — `src/lib/report.ts`

Lifetime query filtered `status: "resolved"` only, but realized PnL books at
closedAt for early exits — C-200 EOD NW overstated ~$960 (its closed-at-a-loss
early exits were missing), STANDARD understated ~$1,082 (closed winners
missing). Query now `status: { in: ["resolved", "closed"] }`; locals renamed
allResolved → allFinished (stdFinished/cmpFinished). Verified arithmetically:
cmpTotalPnl now reconciles to the gate NW ($1,773.74 ± rounding).

## ④ query_bankroll day/bankroll math — `query_bankroll.js`

Two bugs: (a) "Today's PnL" mixed today's realized with TOTAL open unrealized
(mostly older positions' mark-to-market) → misleading ON TRACK reads (e.g.
$752.51 with 0/7 streak days); (b) "Current Bankroll" = cashBalance +
realizedToday, but closes already increment cash by (size+pnl) → double-count.
Now: Today's **realized** PnL (matches the streak definition), open unrealized
reported on its own labeled line, Status vs realized only, Bankroll = cash.
Live output verified (realized −$310.24 / unrealized +$310.44 / cash $909.83).

## Verification

tsc clean · 118/118 tests · query_bankroll live-verified · NW/drawdown
DB-verified · commit `…` (git log). Tuning-review verifies to confirm next
window: 0 clusters with n>1 (7d SQL), ≥1 C-200 open within 24h with 0 drawdown
vetoes, EOD NW ≈ honest SQL ±$50.
