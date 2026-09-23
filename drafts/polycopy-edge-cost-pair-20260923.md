# Edge vs cost of copying — published as a pair, and the cause of C-200's negative cost (2026-09-23)

**Card:** `polycopy-edge-cost-pair` (from the Polycopy research review; baseline measured 2026-09-23).
**Status:** shipped — **measurement only**. No RuleSet change, no threshold, no sizing, no gate consumes
any number below. Files: `src/lib/copy-cost.ts` (new), `src/lib/report.ts`, `scripts/edge-copy-cost.ts`
(new, read-only), `tests/copy-cost.test.ts` (new, 19 cases), `~/.hermes/scripts/copybot-eod.sh`
(report tail `-20` → `-30` + one appended read-only line).

**Why the card existed:** the daily report quoted realized PnL and implicitly treated our modelled fill as
free. Polycopy's Sep-8 report makes the opposite point on the top-100 of both Polymarket boards (median
per-position edge 1.39% 30d / 2.07% all-time vs median modelled cost of copying 4.12% / 3.51%; 77% of
measurable traders go negative once costs apply). An edge quoted without its cost term is not readable —
and every later sizing/Kelly decision inherits the error.

---

## 1. What the daily report now prints

```
**📐 Edge vs cost of copying** — settled legs (closed|resolved); both numbers per lane run on the
SAME legs (lifetime since 2026-07-15 → last 30d), n given per window:
• C-200: edge +16.3% of cost (n=1,960) → +23.3% (n=1,270) | copy cost -3.0%/leg → -4.5% | detection drag +1.3% → +2.0%
• STANDARD: edge +9.0% of cost (n=8,693) → +0.1% (n=1,682) | copy cost +0.7%/leg → +1.4% | detection drag +0.9% → +2.2%
⚠️ A NEGATIVE copy cost means our booked entry sat BELOW the wallet's own fill. Cause is measured on
C-200: the Rust sidecar books every BUY 2¢ better (maker_improvement, rust-sidecar/src/main.rs) — worth
≈$1,526 of the $2,426 lifetime C-200 PnL. Ex that assumption C-200 reads +6.1% of cost (lifetime) /
+9.5% (30d). Neither lane crosses a spread or pays a fee, so both cost terms are a LOWER BOUND.
```

One line per lane, **both** numbers on the **same** legs (the card's requirement: neither may be quoted
alone), population and window stated on the header, plus the third term that makes the sign readable.

### Definitions (both worth arguing about, so both are written down)

| term | definition | reads |
|---|---|---|
| **edge** | `SUM(realizedPnl) / SUM(simulatedPositionSize)` over settled legs — aggregate, not per-leg average: C-200 sizes winners up, and the question is what the book earned on the money it committed | % of cost |
| **copy cost** | mean per leg of `(our booked entry − the wallet's own fill) / the wallet's own fill`. POSITIVE = we paid above the wallet (a real cost) | % per leg |
| **detection drag** | mean per leg of `(detected price − the wallet's fill) / the wallet's fill` — the adverse move between the wallet's fill and our detection of it | % per leg |

Settled = `status IN ('closed','resolved')` bucketed by `closedAt ?? resolvedAt` (TR-15: early exits only
carry `closedAt`). `isDemo = 0`. Legs with no wallet fill are dropped from **both** terms and counted in
`droppedNoFill` (0 of 12,110 legs, checked today), so the pair always shares one population.

### Reconciliation with the card's baseline

| population | lane | card baseline (all legs) | measured today | today's legs |
|---|---|---|---|---|
| all legs (open + settled) | C-200 | −3.03% | **−3.03%** | 1,983 (baseline 1,982) |
| all legs (open + settled) | STANDARD | +0.84% | **+0.82%** | 10,110 (baseline 9,863) |
| all legs, detected vs wallet | C-200 / STANDARD | +1.27% / +1.06% | **+1.27% / +1.03%** | — |

Exact on C-200, 0.02–0.03pp on STANDARD; leg counts grew by the day's settlements. The shipped numbers
use the **settled** population (so the edge term exists for every leg counted), which is why the
report's copy-cost figure is −3.0% / +0.7% rather than the all-legs −3.03% / +0.82%.

---

## 2. The finding: C-200's copy cost is negative, and the cause is a modelled fill

A negative copy cost means our booked entry sat **below** the wallet's own fill — the opposite sign a real
copier sees. That is not capture; it is the fill model. Root cause, in three steps:

1. **C-200 fills are not written by our code.** `src/lib/paper.ts` routes every `BANKROLL_200` leg to the
   Rust sidecar (`POST 127.0.0.1:3014/execute`) and *returns* — the sidecar's webhook writes the
   `PaperTrade` row. STANDARD writes directly.
2. **The sidecar books 2¢ better than the price it was handed.** `rust-sidecar/src/main.rs`, "Phase 6
   ImMike's Maker Copying": `maker_improvement = 0.02`, then for BUYs
   `executed_price = max(0.01, executed_price - 0.02)` and `entryPrice: executed_price` in the webhook
   payload. It models a maker limit order parked inside the spread; the log line calls it "avoided 2¢ taker fee".
3. **Our own book shows it.** For the 1,121 decisions that both lanes booked (same decision, same
   `openedAt`): 893 pairs booked **2026-07-22 → 2026-08-30** carry *identical* entries, and 228 pairs
   booked **2026-08-28 → 2026-09-23** carry different ones — **221 of them by exactly $0.02**
   (C-200 = STANDARD − $0.02); the other 7 are pairs whose two price reads themselves differed.

### Measured, before vs after the maker path

| C-200, all legs | legs | copy cost (mean/leg) | detected-vs-wallet |
|---|---|---|---|
| opened before 2026-08-28 (no maker path) | 827 | **−0.09%** | +0.04% |
| opened 2026-08-28 onward | 1,157 | **−5.13%** | +2.14% |

Before the maker path the C-200 copy cost is **zero** — the lane booked exactly what it read. After it,
the whole negative term appears. The arithmetic closes: on the maker-era legs `0.02 / entry` averages
**6.89%** (2¢ is 4% of a $0.50 token but 40% of a $0.05 token, and C-200 trades a lot of cheap tokens),
minus the +2.14% adverse latency drag predicts **−4.7%** against a measured **−5.13%**.

### What it costs the C-200 PnL

| C-200, settled legs opened ≥ 2026-08-28 | value |
|---|---|
| realized PnL / committed notional | +$2,534.58 / $10,386.84 = **+24.4%** |
| value of the 2¢ maker assumption | **$1,525.76 — 60% of the realized PnL** |
| same edge excluding the assumption | **+9.7%** |

Lifetime it is $1,526 of $2,426 realized (**+16.3% → +6.1%** of cost); last 30d the assumption is
$1,526 of ~$2.57k (**+23.3% → +9.5%**). So the headline C-200 edge is roughly **one quarter** of what it
reads, and roughly **60–100%** of the recent C-200 PnL is a fill assumption rather than a traded result.

---

## 3. Window sensitivity (why the report prints two windows)

| settled month | lane | n | edge (% of cost) | copy cost |
|---|---|---|---|---|
| 2026-07 | C-200 | 81 | −64.3% | −0.07% |
| 2026-08 | C-200 | 1,005 | +3.2% | −0.93% |
| 2026-09 | C-200 | 874 | +29.3% | −5.63% |
| 2026-07 | STANDARD | 4,282 | +21.6% | −0.08% |
| 2026-08 | STANDARD | 3,226 | −3.9% | +1.56% |
| 2026-09 | STANDARD | 1,185 | +5.1% | +1.25% |

The lifetime figure is era-mixed (49% of STANDARD's settled legs are July, whose +21.6% carries the
whole lifetime +9.0%), and ruleset versions differ (C-200 books through the sidecar only from 08-28).
Hence lifetime **and** trailing-30d, each with its own n, in the same line.

## 4. What this does and does not do

- Does **not** touch the copy path, sizing, thresholds, caps or the paper-fill model. `maker_improvement`
  is unchanged. Nothing reads these numbers.
- Does mean the C-200 edge is **not comparable to a real copier's** wherever it is quoted (this report,
  the dashboard, tuning reviews, Kelly/sizing reasoning) until the assumption is either removed from the
  fill model or explicitly justified.
- Both cost terms are a **LOWER BOUND** on the true cost of copying: our paper fill crosses no spread and
  pays no taker fee, so even the +2.14% latency drag understates what a real taker pays (Polycopy models
  3.5–4.1% all-in). The fee side already has a shadow spec (`src/lib/scoring/price-edge.ts`, not wired).

## 5. Follow-up carded (recommendation only — needs a decision)

`c200-maker-fill-assumption` (Scheduled): decide whether the sidecar's fixed 2¢ maker improvement stays in
the C-200 fill model. The options as I see them — (a) keep it and declare it a *sizing hypothesis*
(the maker fills are assumed, not measured), (b) try to measure it (do C-200 entries actually fill 2¢
inside the spread? we hold the intent price only in logs), (c) remove it and re-read every C-200 number.
That is a PnL/sizing-model change, so it waits for approval; nothing in this card depends on it.

## 6. Verify (7d, from 2026-09-30)

```bash
# the report prints both numbers, per lane, with n and window (4 lines per EOD report)
grep -c "Edge vs cost of copying" logs/cron/copybot-eod.log                 # ≥ 7 (one per EOD)
grep "Edge vs cost of copying" logs/cron/copybot-eod.log | tail -1          # carries "n=" and "last 30d"
# the stored report is the immovable record, same convention as the EOD prints
sqlite3 prisma/dev.db "SELECT date, substr(summary, instr(summary,'Edge vs cost of copying'), 260) FROM DailyReport WHERE date >= '2026-09-23' ORDER BY date;"
# the re-runnable form agrees with the report on the same day
npx tsx scripts/edge-copy-cost.ts
```

No red line is required: the block is display-only. A missing block means the EOD report did not run
(already alerting).

## 7. Reproduce the numbers

```bash
npx tsx scripts/edge-copy-cost.ts     # lifetime + 30d per lane, the all-legs baseline form, and a SQL hint
sqlite3 -readonly prisma/dev.db "SELECT p.botId, COUNT(*),
  ROUND(100.0*AVG((p.entryPrice-o.walletEntryPrice)/o.walletEntryPrice),3)
  FROM PaperTrade p JOIN DecisionJournal d ON d.id=p.decisionJournalId
  JOIN ObservedTrade o ON o.id=d.observedTradeId WHERE p.isDemo=0 GROUP BY 1"
```

Dates in `prisma/dev.db` are Unix-ms: `datetime(col/1000,'unixepoch')`.
