# kalshi-reprice-92 — 2026-09-05 (tuning review #16 rec 1, user-approved "I approve")

## What was wrong

The pre-TR-16 Rust sidecar Kalshi adapter returned a hardcoded `Ok(0.52)` stub
(booked ≈$0.50 after the 2¢ maker tweak) whenever its Kalshi depth fetch
failed, so every such BANKROLL_200 row opened at a **phantom 0.50 regardless of
the true market price**. Rows whose fetch succeeded were booked at the
Polymarket reference price at detection time (`ObservedTrade.detectedPrice`) —
visible in the DB as `entryPrice == detectedPrice`. TR-16 (Sep 3) killed the
stub for new rows; the 92 legacy rows stayed phantom.

## The correction

`scripts/reprice-kalshi-92.ts` (run `DATABASE_URL="file:./dev.db" npx tsx
scripts/reprice-kalshi-92.ts`; audit: `data/kalshi-reprice-audit.json`,
73 rows + 19 skipped with full before/after).

- **Stub row** = `|entryPrice − 0.50| < 0.005` while the honest reference
  differs by > 1¢. **73 rows** (54 closed + 18 resolved + 1 open).
- **Honest entry = `ObservedTrade.detectedPrice`** — the PM reference price at
  the moment the signal fired, i.e. the same convention the non-stub sibling
  rows were booked at. (Kalshi-side historical prices are not recoverable
  keyless; the roadmap card and kalshi-whale-review.md appendix both sanction
  the PM-reference proxy.)
- **Exits untouched** — they are real Polymarket marks (update-pnl marks both
  books from the PM adapter; resolved rows already settled at 1/0). Only the
  phantom ENTRY was the lie.
- PnL recomputed with the `computePnl` convention (shares = S/entry,
  pnl = shares·exit − S) at the **same risked dollars S** — S is the executed
  risk decision.
- Open row (`will-taylor-fritz-win-the-2026-mens-us-open`, NO): entry
  0.50 → 0.9210, unrealized recomputed (+$7.19 phantom → −$0.21 honest).

## Results (verified)

| metric | before | after |
|---|---|---|
| kalshiRealized (closed+resolved) | −$50.70 | **−$37.99** (Δ +$12.71) |
| Kalshi breaker floor (−$50, v37) | tripped (by $0.70) | **clear** |
| BotBankroll realized / cash | −$282.58 / $1,223.68 | −$269.87 / $1,236.39 (Δ +$12.71) |
| Ledger invariant gap | 0.0 | **0.0** |

The `score-trades.ts` Kalshi routing gate reads `kalshiRealized` from rows each
run → **auto-recovers** (no code change): Kalshi routing is eligible again per
the v37 design once a signal clears kalshiMinCopyScore / kalshiMinConfidence.

## Code changes

- `query_bankroll.js`: TR-17 venue exclusion + `kalshiExcluded` note removed —
  Kalshi re-joins the C-200 realized series / phase streak. Live output clean
  (Today's PnL now includes the re-priced Kalshi rows).
- `src/lib/report.ts`: TR-17 filters removed from compoundOpen /
  cmpResolvedToday / cmpAllResolved — EOD C-200 PnL / win rate / open counts
  include Kalshi again. Ledger-invariant check unchanged (venue-blind).
- `analyze-calibration.py` venue filter **kept** (v48-approved; band/hour stats
  stay Kalshi-clean until the Sep-15 refit decides re-inclusion — rec 3, no
  churn).

## Caveats (documented, bounded)

1. **Sizing not re-derived**: `simulatedPositionSize` was band-sized
   (`mapBankroll200Size`, ×0.5/×1.5/×1.0) against the phantom 0.50; the parent
   standard-scale size is not stored per row, so S is kept as executed. The
   residual distortion is bounded by the band factor (≤ ×2) and only affects
   the dollar scale of the corrected rows, never the sign or the direction of
   the correction.
2. Early-exit rows keep their real PM exit marks (capital-recycling closes are
   legitimate paper behavior, not phantom pricing).
3. Rows where the reference ≈ 0.50 (whale genuinely traded ~50¢) were skipped
   (19 untouched incl. all real-entry rows) — no distortion to correct.

## Verification

tsc clean · 95/95 tests · query_bankroll exclusion note gone · ledger invariant
0.0 · kalshiRealized ≥ −$50.
