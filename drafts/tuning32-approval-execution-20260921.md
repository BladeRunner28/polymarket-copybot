# Tuning #32 — approval execution (2026-09-21)

**Approved 2026-09-21 in-thread ("I approve").** Window: 09-20 06:53 → 09-21 07:00 CDT,
109 monitor runs / 218 passes. Report: `logs/cron/tuning-review.md` (cycle #32).

Two recs: **1** stop the rate-limit regression (10 data-api 429s across 7/109 runs after
six clean windows), **2** single-line the scan-wallets failure summary. Both shipped.
Plus one loose end the report flagged: **#31 rec 2's EOD clause**, now closed.

## A · Rec 1 — the 429s were a duplicated sweep, and the "paced" call was inert

Recon before editing found the mechanism is worse than the rec assumed:

- The runner called `npm run --silent monitor:trades` **twice** per cycle, and the call
  with `API_DELAY_MS=100` was **inert**: `monitor-trades.ts` never reads
  `API_DELAY_MS` (only `src/lib/dead-market-resolution.ts` does), so both calls issued
  **identical requests at identical pacing**.
- The monitor's lookback is **24 h** (`MONITOR_HOURS`), so the second sweep re-fetched
  the same window and every fill hit `ObservedTrade`'s unique constraint — pure
  duplicate load, zero new rows.
- The pool is what sets burst width: `CONCURRENCY = 4` runs four wallets' `/activity`
  pages at once, and `API_DELAY_MS` only paces pagination *inside* one wallet.

**Fix (both halves of the rec):**

| | before | after |
|---|---|---|
| `monitor:trades` invocations per cycle | 2 (one inert prefix) | **1** |
| wallet pool width | 4 | **2** (`MONITOR_CONCURRENCY`, env-overridable) |

Deleting the sweep loses nothing: a fill that lands mid-cycle is still inside the next
cycle's 24 h window. The run is no longer the cadence bind (13.0 m median against a 10 m
schedule), so trading burst width for API headroom is the right side of that trade.

Verify (7 d, 2026-09-28): `grep -c 'Too Many Requests'` on the monitor log = **0**
(baseline 10) and median gap **≤ 14.0 m** (baseline 13.0 m).

## B · Rec 2 — the partial that looked clean, confirmed in the artifacts

The report said 06:08:59 produced `[SCAN PARTIAL]` but only 1 log line for 2 events.
Measured independently, the two sides disagree exactly as claimed:

```
data/scan-partials.jsonl (2 events)
  2026-09-21T03:56:01Z  24/25  ← data-api 408 on closed-positions
  2026-09-21T11:11:05Z  23/25  ← "Invalid `prisma.walletProfile.updat…"  (multi-line dump)
logs/cron/copybot-scan-wallets.log
  grep -c '[SCAN PARTIAL]' → 1        ← the 11:11 event's line was pushed out of `tail -6`
```

**Fix:** every interpolated failure string collapses whitespace and entries join with
` | `, so a run emits one line per concern — the completion line and the `[SCAN PARTIAL]`
line can no longer be evicted by a Prisma stack dump. Instrumentation only.

Verify (7 d): run-header count **==** completion-line count (baseline 162/161 in the
window; 1,318/1,289 lifetime) and every `N/25` with N<25 carries exactly one
`[SCAN PARTIAL]` in the same run.

## C · Loose end closed — the decay bar is in the EOD report

#31 rec 2's verify expected the ex-dust figure in `copybot-eod.log`, but it is written by
the hourly shadow marker into `copybot-shadow-longshot.log`, so the number the bar is
judged on never reached the report. `report.ts` now prints (read-only):

```
• Drift gate counterfactual: −$0.17/trade ex-dust (2702 marked) · decay bar 2/7 days at ≤$0.50 (cohort7d $-0.17)
```

Note the cohort value has moved from the report's $0.49 to **−$0.17** as settlements
accumulated — the cumulative figure drifts mechanically, which is exactly why the bar
requires *both* reads to hold.

## D · Verification

```
runner                  → exactly 1 `monitor:trades` invocation (grep -c = 1); bash -n clean
monitor-trades.ts:42    → CONCURRENCY = Number(process.env.MONITOR_CONCURRENCY ?? 2)
scan-wallets.ts:132     → single-line `Failures (N): a | b | c`
report-daily --dry-run  → drift decay line + wallet-scan line both render
npx tsc --noEmit        → clean
npm test                → 221/221
roadmap                 → 200; 2 new cards + the #31-2 EOD clause recorded
```

**First production sample — verified by a hand-run of the fixed runner (09:16:04 →
09:18:56 CDT, exit 0):**

| | before (08:40 / 08:55 / 09:09 cycles) | after |
|---|---|---|
| `monitor:trades` sweeps per cycle | 2 | **1** |
| cycle runtime | ~12–15 min (duration-bound) | **2 min 52 s** |
| 429s in the run | 10 across 7/109 runs | **0** (lifetime counter unchanged at 37) |
| scoring pass | — | 1 `Scoring complete` (35 skips, 1 shadow, 21 drift counterfactuals) |

The runtime collapse is the load effect: with the duplicate sweep gone the requests
stop tripping the data-api limiter, so the surviving sweep finishes in a fraction of the
time despite the narrower pool — i.e. the run is no longer the cadence bind, which is
what the rec's `median gap ≤ 14.0 m` clause is really asking for.

**Incident, recorded (no data loss).** The 09:09:18 cycle aborted with
`line 21: …300ms: command not found`: the runner had been rewritten (truncate + write of
the same inode) while bash was reading it incrementally, so the shell resumed at a stale
byte offset and died on what was, in the current file, a comment line. The abort landed
**after** the monitor sweep and **before** the scorer, so that cycle lost its scoring
pass; its 14 observed trades were picked up unscored by the 09:16:04 hand-run (35 skips
scored). Lesson recorded in the ops skill: check the lock/run header before editing a
cron script, and prefer write-temp-then-rename.

## E · Not done

- Nothing from the report's "not re-proposed" list: `API_DELAY_MS` is not re-tightened
  (and this change showed its monitor-scope was a no-op all along), the cadence axis
  stays QUIET, and no threshold moves (v59/v60 stand; the mid-window attribution rule on
  the Kelly pre-commit card already names them).
