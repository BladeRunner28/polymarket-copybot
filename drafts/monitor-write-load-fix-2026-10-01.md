# Monitor write-load fix — copy-lane dedupe pre-filter

**Applied:** 2026-10-01 08:27 CDT · **Commit:** `fbec056` · **Source:** tuning review #42 rec 1 (cadence axis), user-approved in-thread 2026-10-01
**File changed:** `scripts/monitor-trades.ts` (1 file, +22/−16) · **Revert:** wrap the pre-filter in `if (w.observationOnly)` again

---

## Problem (as measured by the reviewer, and re-measured here)

`MarketSnapshot` was growing by **~156,000 rows/24 h** for **779 real copy-eligible fills** — a **~201×** amplification, ~1,194 re-writes per 10-minute cycle, DB +0.141 GB/day.

Independent read just before the change (08:28:00): **153,387 rows in the trailing 24 h**, total 15,863,653, ~6.4 k rows/h, flat across every hour. Cadence itself was healthy (median gap 11.00 m, duration 0.73 m), so this was purely a write-load / DB-growth problem.

## Root cause

`scripts/monitor-trades.ts::processWallet` built its "already stored" set **only for observation-only wallets**:

```ts
let seen: Set<string> | null = null;
if (w.observationOnly) { /* build `seen` from ObservedTrade */ }
...
if (seen?.has(dedupeKey)) continue;
```

`adapter.fetchWalletActivity()` returns the wallet's **whole trailing-24 h book** every cycle, so the **copy lane re-offered ~1,194 stored fills per cycle**. For each one the code re-paid:

1. `adapter.fetchMarket(marketId)` — a live venue read, and
2. `prisma.marketSnapshot.create(...)` — a **fresh row with no unique constraint** (the only write of the two that could not be de-duplicated), then
3. `prisma.observedTrade.create(...)`, which the unique index refused.

So the snapshot table absorbed the re-offer every cycle while the trade row it accompanied was thrown away.

## Fix

Build the pre-filter for **every** wallet (the reviewer's Rec 1, verbatim: "build the per-wallet `existing` set unconditionally"). The skip key is character-for-character the existing unique index — `@@unique([walletAddress, marketId, outcome, side, timestamp])` (`prisma/schema.prisma::ObservedTrade`) — so a stored fill can only ever end in that rejection.

## Why no decision, count or published number can move

| Check | Evidence |
| --- | --- |
| The skipped key IS the DB's uniqueness contract | `@@unique([walletAddress, marketId, outcome, side, timestamp])`; the old path's only outcomes for a duplicate were a swallowed `Unique constraint` throw (`:170-173`) and a market read nobody consumed |
| `detectedPrice` for a duplicate is unused | It was only ever written into the `observedTrade.create` that the index refused; the market read it came from is gone with the skip |
| No copy path reads `MarketSnapshot` | Consumers are `src/lib/rule-updater.ts:35` (auto-tune, currently suppressed by the Kelly freeze), `src/app/signals/page.tsx` (latest-per-market dashboard view) and a profiling script — none is a decision input. The price a copy is priced from is fetched live at decision time |
| Counters cannot move | `newTrades` / `newObserved` increment only after a **successful** create; a duplicate never incremented them, before or after |
| Journal untouched | The journal is written by `score-trades.ts` from stored `ObservedTrade` rows; no row's existence changes |

## Executed results

| Metric | Before | After (cycles 08:37 → 09:21) |
| --- | --- | --- |
| `MarketSnapshot` rows per cycle | 902 / 947 / 928 (08:26 / 07:31-window reads) | **18 / 15 / 6 / 16 / 37** across five consecutive cycles |
| Rows created | — | exactly **1 per genuinely new copy-eligible fill** (18 fills → 18 rows, 15 → 15, 6 → 6, 16 → 16, 37 → 37) |
| Cycle duration (executions.db, job `626f7189e8d2`) | 0.80 / 0.71 / 0.70 min (3 prior cycles) | **0.25 / 0.25 / 0.24 / 0.27 / 0.26 min** |
| Errors / 429 / FAILED in the cycle | 0 | 0 (0 rate-limit lines after the `2026-10-01T08:37:20` run header; lifetime count still 58) |
| Typecheck | — | `npx tsc --noEmit` exit 0 |

Trailing-24 h read **145,935** at 09:24 CDT and is still falling: the window carries the pre-change hours, which age out at 24 h. The first *clean* 24 h read is available from **2026-10-02 08:37**; steady state is ~780 rows/24 h (one per copy-eligible fill). DB file `prisma/dev.db` = 7.7 GB at the time of writing (the reviewer's 8.308 GB figure is its own books-and-WAL accounting).

**Bookkeeping:** roadmap card `tr42-rec1-monitor-copy-dedupe` (In Progress, carrying these four verify bars) and a standing input appended to the `copybot-tuning-review-daily` prompt so the review stops re-proposing a shipped rec.

## Verification window (7 days, the reviewer's own bars)

Re-read at each tuning review; all four must hold:

1. `sqlite3 -readonly prisma/dev.db "SELECT COUNT(*) FROM MarketSnapshot WHERE collectedAt > (strftime('%s','now')-86400)*1000;"` **≤ 10,000** (⚠️ the *first* window may read slightly over the bar: it still carries the 08:27–08:37 carryover; the clean read is day 2 onward).
2. Monitor median duration **≤ 1.5 min** and median start-to-start gap **≤ 14.0 min**.
3. `grep -cE "Too Many Requests|HTTP 429" logs/cron/copybot-monitor-score.log` **stays 58**, 0 `FAILED`.
4. Journal `paper_copy` rows == `PaperTrade` legs with **0 childless**.

## Rollback

Re-add `if (w.observationOnly)` around the pre-filter block (and drop the now-unneeded `seen.add`). One file, no schema, no rule, no published number — `git revert fbec056` is equivalent.
