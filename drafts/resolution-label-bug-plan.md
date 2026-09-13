# Resolution label bug — plan + execution record

**Status:** approved by user 2026-09-13 · executed same day
**Roadmap card:** `resolution-label-bug` · **Related:** `outcome-casing-mismatch` (same root cause class, fixed by the same change)

## 1. Problem

Polymarket markets are binary *token* markets, but sports/esports/handicap/total markets carry
token labels that are not `Yes`/`No` — `Vitality`, `9z`, `Dynasty`, `Under`, `Team Liquid`.

`src/lib/adapters/polymarket.ts` parsed only `outcomePrices` and **guessed** the winner:

```ts
winningOutcome = yesPrice > 0.5 ? "YES" : "NO";   // was: line 322
```

`scripts/update-pnl.ts` then booked the result as `m.winningOutcome === t.outcome`. For any
position whose `outcome` is a token label, that comparison can **never** be true, so
`resolvePaperTrade(id, false)` booked a **full-stake loss** no matter what actually happened.

The same guess was used in four other places: the wallet-activity PnL enrichment
(`polymarket.ts:282`), `exit-recovery.ts:146` (final mark), `mark-shadow-longshot.ts:41`
(shadow ladder), and — with a third casing — `review-outcomes.ts:72` (see §2b).

## 2. Evidence (measured before the fix)

`scripts/audit-misresolved-trades.py` (read-only; classifies every resolved trade whose label is
not `YES`/`NO` against the keyless CLOB token/winner data):

| verdict | trades | booked PnL |
|---|---|---|
| **PHANTOM_LOSS** (bought token was the winner) | 70 | −$828.38 |
| correct_loss | 79 | −$912.75 |
| unresolvable (conditionId is an event id, 404 at CLOB) | 40 | −$412.97 |

Correct settlement of the 70 phantom losses is **+$942.34**, i.e. **+$1,770.72 of realized PnL was
missing**. Spot checks: `DYNASTY` (winner `DYNASTY`) booked −$10.00 ×3; `UNDER` on *Games Total
O/U 2.5* (winner `Under`) booked −$9.00 ×3.

### 2b. The same class in outcome reviews

`OutcomeReview.finalOutcome` is stored in API casing (`No`, `Yes`, `Over`) while
`ObservedTrade.outcome` is uppercased (`NO`, `YES`, `OVER`) — 0/688 exact matches, 509/688
case-insensitive. Consequences: all 200 reviewed watchlist/skip rows were stamped
`wasDecisionGood=1` with an "Avoided loser" lesson (`good = !won`), `simulatedPnl` for uncopied
decisions was always `computePnl(entry, 0) = −$10`, and the `/performance` + `/analytics`
benchmark sections showed *Blind copy −$6,880 @ 0.0%* with *Missed Winners* structurally 0.
Normalising the comparison fixes both bugs at once.

## 3. Blast radius

- **Kelly window** (`scripts/kelly-window-report.ts`): reads `PaperTrade.realizedPnl`, so the
  in-window main-lane figure (−$629.77) contained **−$56.02** of this class. Kelly *sizing* is
  unaffected — it is driven by the Wang premium model (λ̂) vs market price, not by resolutions.
- **C-200 drawdown gate** (live): net worth $2,069 vs the $2,070.66 threshold — tripped by
  **~$1.66** — while the book carried $224.11 of corrections on BANKROLL_200 alone.
- **Benchmarks / journal / training export**: via `wasDecisionGood` + `simulatedPnl` (§2b).

## 4. Fix design

1. **`src/lib/resolution.ts`** (new) — one place that answers "did this token win?":
   - `normalizeOutcomeLabel(s)` → alphanumeric uppercase (`"Team Liquid"` → `TEAMLIQUID`).
   - `didOutcomeWin(tradeOutcome, { winningLabel, yesPrice })` → `boolean | null`.
     `null` means *undeterminable* and callers must **not** book a loss (fail loud, never a wrong
     close). Legacy `YES`/`NO` + `yesPrice > 0.5` behaviour is preserved as the fallback when a
     market exposes no labels, so binary behaviour is bit-identical.
2. **Adapter** (`polymarket.ts`, `demo.ts`) — parse `outcomes` next to `outcomePrices`, expose
   `outcomeLabels` and `winningLabel` (the label at the winning price index) on `MarketState`.
   `winningOutcome` stays populated (now with the true label) for backward compatibility.
3. **`fetchEventResolution`** (`dead-market-resolution.ts`) — return the winning *label* from the
   parent event's child market instead of guessing `YES`/`NO`; type becomes `string | null`.
4. **Call sites** — `update-pnl.ts` (2 sites), `exit-recovery.ts`, `mark-shadow-longshot.ts`,
   `review-outcomes.ts`, and the adapter's wallet-activity enrichment all route through
   `didOutcomeWin`. `null` ⇒ skip resolution this cycle (log `[RESOLVE] unmapped outcome label`),
   never book a loss.
5. **Tests** — `tests/resolution.test.ts` covering label equality, casing, the legacy binary path,
   the multi-token path, and the `null` (fail-loud) cases.
6. **`scripts/backfill-misresolved.ts`** — `--dry-run` (default) prints corrected PnL per trade and
   the net-worth/drawdown impact; `--apply` writes, after dumping the affected rows to
   `data/backfill-misresolved-<date>.json`. Deltas: a corrected win pays `computePnl(entry, 1, size)`
   and credits `size/entry` back to `BotBankroll.cashBalance` and `.realizedPnl` (STANDARD has no
   bankroll row, so only BANKROLL_200 is adjusted).

## 5. Policy decisions

- **The 70 phantom losses are corrected** (evidence: CLOB token/winner).
- **The 40 unresolvable rows are left alone.** Their `conditionId` is an event id and both
  `marketId` and `outcome` are empty strings — no market identity exists to resolve against, so
  there is no evidence either way. They stay booked as losses and are recorded as
  *known-unreliable* rows for reporting (see §7). Making them disappear would be inventing data.
- **Drawdown high-water mark:** the peak (`data/c200-drawdown.json`) is a scalar high-water mark,
  not a series, so it cannot be *recomputed* exactly. Instead the corrected drawdown is **bounded**:
  `peak_lower = stored peak` (all corrections land after the peak) and
  `peak_upper = stored peak + corrections of trades resolved before the peak was last raised`
  (worst case). The gate decision is only trusted if **both** bounds clear `maxDrawdownPct`.
  The stored peak is left unchanged: raising it would make the gate stricter without evidence.
- **Historical reports are not relabelled** (repo convention): `DailyReport` rows and EOD numbers
  already emitted keep their old basis; the correction applies to the live tables.

## 6. Verification plan

1. `scripts/audit-misresolved-trades.py` → 0 phantom losses after the fix (independent
   implementation, so it is a real cross-check, not a restatement).
2. `scripts/backfill-misresolved.ts --dry-run` must agree with the Python audit row-for-row.
3. `npm test` (incl. new `tests/resolution.test.ts`) + `npx tsc --noEmit`.
4. `scripts/verify-dashboard-parity.ts` + `scripts/verify-chart-geometry.ts` still pass.
5. Drawdown gate state re-read from the dashboard/root page and the next `score:trades` run's
   `[RISK-GATE]` line.
6. Before/after re-baseline of the Kelly window report and the benchmark table (§7).

## 7. Results (executed 2026-09-13)

**Code**
- `src/lib/resolution.ts` (new) — `normalizeOutcomeLabel` + `didOutcomeWin` (true/false/**null**, null = undeterminable, callers must not book a loss).
- `src/lib/adapters/polymarket.ts` — parses `outcomes` next to `outcomePrices`, exposes `outcomeLabels`/`winningLabel`; wallet-activity enrichment is label-aware (SELL flips to the sibling token label).
- `src/lib/dead-market-resolution.ts` — `fetchEventResolution` returns the winning **label**; new `fetchWinningLabelViaClob(conditionId)` third route.
- Call sites routed through the helper: `scripts/update-pnl.ts` (all 3), `src/lib/exit-recovery.ts`, `scripts/mark-shadow-longshot.ts`, `scripts/review-outcomes.ts`, adapter enrichment.
- `tests/resolution.test.ts` (new, 9 cases) — 147 tests pass, `tsc --noEmit` clean.

**Backfill** (`scripts/backfill-misresolved.ts`, dry-run then `--apply`; backup at
`data/backfill-misresolved-2026-09-13.json`):

| bot | rows | booked | corrected | delta |
|---|---|---|---|---|
| BANKROLL_200 | 24 | −$100.78 | +$123.33 | **+$224.11** |
| STANDARD | 46 | −$727.60 | +$819.01 | **+$1,546.61** |
| ALL | **70** | −$828.38 | +$942.34 | **+$1,770.72** |

40 rows left untouched (no market identity — event-id `conditionId`, empty `marketId`/`outcome`), 493 confirmed
correct losses, 1,422 already right. Resolution routes used: `gamma-event` 400, `clob-conditionId` 37.

**Verification**
- `scripts/audit-misresolved-trades.py` (independent, CLOB-based): **0 phantom losses remaining** — 70 now read `corrected_win`.
- Row-level cross-check: the TS fix list and the Python audit are **identical sets**, 0 rows in either direction; corrected PnL recomputed two ways, 0 mismatches; per-bot deltas match to the cent.
- Ledger invariant: `BotBankroll.realizedPnl` ($48.86) == `SUM(realizedPnl)` of BANKROLL_200 resolved/closed trades ($48.86).
- `npm test` 147 pass · `tsc --noEmit` clean · `verify-dashboard-parity.ts` ALL PASS · `verify-chart-geometry.ts` IDENTICAL.

**Re-baseline (before → after)**

| metric | before | after |
|---|---|---|
| BANKROLL_200 realized | −$175.25 | **+$48.86** |
| BANKROLL_200 cash | $651.10 | **$875.21** |
| C-200 net worth | $2,069.07 | **$2,293.18** |
| drawdown vs peak $2,588.33 | **20.1% (gate TRIPPED)** | **11.4% (gate clear)** |
| worst case (peak rises by the correction) | — | 18.5% — still clears |
| equity-linked exposure cap | $1,085 | $1,197 |

Kelly window report: the main-lane band table is **unchanged** (−$414 / −$216) — the in-window corrections
landed in the short-TTR **lane** (+$57), so the Phase-B evidence is untouched. Lane realized $481 → $538;
last-24h realized $196.38 → $211.52; the "drawdown EXCEEDS the gate" warning line disappears.

Benchmark table (this also required fixing the *comparison* in `benchmarks.ts` + the Analytics page, since
stored `finalOutcome` is API-cased and a raw `===` scored every review as a loss):

| bucket | before | after |
|---|---|---|
| Bot-filtered paper trades | 8,658 res · +$5,680.42 · 62.3% | 8,658 res · **+$7,358.44** · 63.1% |
| Blind leaderboard copy | 688 res · **−$6,880.00 · 0.0%** | 688 res · **+$672.99 · 74.0%** |
| Skipped (hypo) | 200 res · −$2,000 · 0.0% | 200 res · **+$205.98** · 46% |
| Missed winners | **0** | **92** |

Reality check worth keeping in view: per resolved decision the bot now averages **+$0.85** against blind
copy's **+$0.98** (flat $10 at detection price) — the filtering edge is much thinner than the broken table
implied, and "Missed Winners" was structurally zero before, not genuinely zero.

**Policy notes / not done**
- The stored peak was **not** raised: the corrections only increase net worth, and raising the high-water
  mark without a reconstructed series would make the gate stricter on no evidence. The bounded worst case
  (peak + $224 → 18.5%) still clears, so the un-trip is robust.
- Historical `DailyReport`/EOD rows keep their old basis (repo convention); only live tables were corrected.
- The 40 unresolvable rows stay booked as losses — there is no market identity to resolve, and inventing one
  would be fabricating data. They are called out here and in the audit output as known-unreliable.
- The 688 existing `OutcomeReview` rows still carry the old stored judgements (`wasDecisionGood`, `simulatedPnl`).
  The benchmark/analytics numbers no longer depend on them, but `/journal`'s "judged good/bad" flags and
  `export-training-data.ts` still do — parked as the `outcome-casing-mismatch` card for a separate approval.

