# C-200 Execution-Leak Investigation Plan

**Status:** PLAN — for approval, then execute step-by-step.
**Trigger:** Same scorer, wildly different outcomes by bot: STANDARD is +EV in EVERY band (80+ **+$1.95/trade**, 2,515 trades; 70–79 +$0.57; <70 +$1.15) while BANKROLL_200 is negative everywhere except 70–79 (+$0.115). The score/signal layer is fine — the leak is in C-200's execution path.

## Hypothesis stack (ranked by likelihood × value)

| # | Hypothesis | Why | How to test |
|---|---|---|---|
| H1 | **Venue/routing is worse for C-200** | score-trades routes conf > 0.8 C-200 trades to "Kalshi"; Rust sidecar (:3014) executes with its own price logic; when the sidecar is down the scorer *silently skips* (zero trades, no alert) | PnL split by `venue` per bot; execution-rate vs skipped logs; compare sidecar-executed vs direct fills |
| H2 | **C-200 entries are systematically later (drift)** | The short-TTR lane (2–72h) + 10-min cycle means C-200 chases fast markets; v29's own data says late entries are the top failure mode | PnL by drift-at-entry decile, per bot; entry-price vs wallet-entry delta |
| H3 | **Category mix differs — C-200 is in losing categories** | Lane pulls sports/events (EPL, UFC, weather); STANDARD holds politics/crypto long-dated | PnL by `marketCategory` for BANKROLL_200 vs STANDARD |
| H4 | **STANDARD's +EV is partly unrealized/measurement** | STANDARD holds weeks-months; its "gains" may be paper. C-200 realizes daily (fast markets) — the comparison may overstate the gap | STANDARD realized vs unrealized split; resolve the open book value; cash-flow check |
| H5 | **Sizing/scaling distortion** | openPaperTrade rescales sizes 0.25–20 → 0.10–10; ×3 boost + venue routing concentrate C-200 capital in the conf > 0.9 tail | PnL vs effective size; check the conf > 0.9 tail specifically |

## Step 1 — quick diagnostics (one batch, read-only, ~5 min)

```sql
-- H1: PnL by venue
SELECT venue, botId, COUNT(*), ROUND(SUM(realizedPnl),2) FROM PaperTrade
WHERE status IN ('closed','resolved') GROUP BY venue, botId ORDER BY botId, venue;

-- H2: PnL by drift-at-entry decile (drift = |currentPrice - entryPrice| at open)
SELECT botId, ROUND((ABS(detectedPrice - entryPrice) * 20),0) AS drift_bucket,  -- rough
       COUNT(*), ROUND(AVG(realizedPnl),3)
FROM PaperTrade JOIN ObservedTrade ON ...  -- join on observedTradeId via DecisionJournal
WHERE status IN ('closed','resolved') GROUP BY botId, drift_bucket;

-- H3: PnL by category
SELECT marketCategory, botId, COUNT(*), ROUND(SUM(realizedPnl),2)
FROM PaperTrade WHERE status IN ('closed','resolved') GROUP BY marketCategory, botId;

-- H4: STANDARD realized vs unrealized + open book
SELECT botId, status, COUNT(*), ROUND(SUM(realizedPnl),2) realized,
       ROUND(SUM(unrealizedPnl),2) unrealized FROM PaperTrade GROUP BY botId, status;
```

## Step 2 — execution-path audit (the sidecar)

- Grep monitor/score logs for `Rust Execution Engine offline` counts per day; correlate with low-trade days.
- Check `logs/cron/*` for skipped-execution lines; count `Skipped execution` vs successes in score-trades output.
- Verify the :3014 sidecar's fill-price logic vs Polymarket's actual price at decision time (is C-200 filling at materially worse prices?).

## Step 3 — decision tree (what each finding implies)

| Finding | Likely fix |
|---|---|
| Kalshi/PredictIt legs lose badly | Drop cross-venue routing for C-200; stay Polymarket-only |
| Later drift deciles lose | Entry-time gate (e.g., only copy signals < X minutes old) — but ONLY for C-200 |
| Specific categories lose | Category blacklist / lane category filter |
| STANDARD gains are mostly unrealized | Reporting fix + re-baseline the comparison; the leak may be smaller than it looks |
| conf > 0.9 tail loses even capped | Remove the ×3 boost entirely; flat sizing for C-200 |

## Step 4 — report

One-page findings + recommended rule changes (v33 candidates). Deliver to Discord via the daily report channel per the usual recommendations-only workflow.

---
**Do not start Step 1 until approved.** (It's read-only, but I want the audit to land as one coherent pass.)
