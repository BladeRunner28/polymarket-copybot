# Tuning #31 — approval execution (2026-09-20)

**Approved 2026-09-20 in-thread ("approved").** Window: 09-19 06:52 → 09-20 06:53
CDT, 97 monitor runs. Report: `logs/cron/tuning-review.md` (cycle #31).
Builds on `drafts/tuning30-approval-execution-20260919.md` and
`drafts/daily-report-recs-wallet-cap-20260920.md`.

Four proposals: rec 1 (as-recorded snapshot), rec 2 (pre-register a drift decay bar),
rec 3 (loud `[SCAN PARTIAL]`), rec 4 (promote the ML doctrine card + era-addressable
export). All four shipped. **Rec 1's premise did not survive re-derivation** — the
instrument shipped anyway, because the auditability gap behind it is real.

## A · Recon — the one premise that failed

| Claim in #31 | Measured 2026-09-20 | Verdict |
|---|---|---|
| "Sep 18 reads +$1,005.21 (18 legs) in #30 and +$993.70 (12 legs) today **under the same declared convention**" | Sep 18 **local** = 12 legs / **+$993.70**; Sep 18 **UTC** = 18 legs / **+$1,005.21** — both computed now, both stable | **Convention mix, third occurrence** (same class as #30 rec 2 and #22's withdrawn duplicate-opens finding) |
| "a row can gain a `closedAt` *after* it already carried the `resolvedAt` that bucketed it, and the bucket then moves forward a day" | `SELECT COUNT(*) … WHERE closedAt IS NOT NULL AND resolvedAt IS NOT NULL` → **0 rows** (lifetime, both books) | **Mechanism cannot exist** — `closedAt ?? resolvedAt` never switches for a row that already has a `resolvedAt` |

So the T+0 read is not unstable; it was being read on two different day boundaries.
The rec's *ask* still shipped: the per-day map `data/phase-streak-history.json`
**overwrites** each day's entry, so "what did the day read at 18:00" genuinely is
lost by the next run — which is what leaves this class of question unfalsifiable.

## B · Rec 1 — immutable as-recorded series (SHIPPED, measurement only)

- **`data/phase-streak-log.jsonl`** — append-only, one row per `query_bankroll.js` run
  per recent day: `{ts, day, localPnl, localLegs, utcPnl, utcLegs, convention}`.
  Both conventions in every row, so a future review can tell instantly which basis it
  is quoting. (4 rows on the first run; the daily report writes it once a day.)
- **Printed in the report**: `As-recorded vs now (declared basis = local …)` with the
  first logged value for each recent day beside the live re-read, marked `⇐ MOVED`
  when they differ, and a separate `Cross-check, UTC basis (… do NOT compare it to
  the line above)` line.
- No gate, threshold or bucket change.

## C · Rec 2 — the decay bar, pre-registered before any number was read

Rule now fixed in the artifact and on the card:

> A `maxPriceDrift` / `longshotDriftPct` relaxation is brought forward **only if**
> `avgPnlPerTradeExDust ≤ $0.50` on **7 consecutive days** *and* the **trailing-7d
> cohort mean** is also ≤ $0.50 — attributed by `ruleSetVersion` (v55–v59
> sub-windows), never as one total. Until it trips, the gate keeps its value.

Two reads are required on purpose: the cumulative ex-dust mean drifts **mechanically**
as settled rows accumulate (it can cross $0.50 because the sample grew, not because
the edge died), while the trailing cohort — settled candidates *decided* in the last
7 days, 1,819 rows today — is the honest "is the edge gone now" figure. Live status:
`{'thresholdUsd': 0.5, 'consecutiveDaysAtOrBelow': 0, 'cohort7d': 0.56, 'tripped': False}`.
Series: `data/drift-decay-series.jsonl` (a day's last row is that day's value).

## D · Rec 3 — the partial scan is loud now

`scripts/scan-wallets.ts` emits, **after** the completion line so the runner's
`tail -6` keeps it:

```
[SCAN PARTIAL] profiled 23/25 — 2 wallet(s) NOT profiled this run (first failure: …)
```

plus one row per partial in `data/scan-partials.jsonl`, the latest run in
`data/scan-wallets-state.json`, and a Discord ping rate-limited to one per 6h (same
pattern as `[PRE-LOOP HALT]`). The EOD report gained
`• Wallet scan: 25/25 profiled (last run 14:04) · 0 partials in 7d` — verified in a
dry run, and a live scan run today profiled 25/25 and printed **0** `[SCAN PARTIAL]`
lines, which is the identity the rec's verify asserts.

## E · Rec 4 — the export is era-addressable, and the era split already pays

`training_data.csv` header is now
`…,was_good,ruleSetVersion,era,decision_at,simulated_pnl` (2,638 rows), so a fit can
be time-ordered and era-scoped instead of inheriting a boundary; `eraOf()` boundaries
are documented in the file (v<49 pre-kelly · v49–57 kelly-window · v≥58 exposure;
unversioned stays `unknown`). The card `ml-doctrine-time-and-era-splits` moved
**Backlog → Scheduled**.

**New finding from the split itself** (printed into the EOD log):

| era | n | good% | avg PnL |
|---|---|---|---|
| pre-kelly-v1-48 | 1,855 | **60.2%** | **+$0.22** |
| kelly-window-v49-57 | 782 | **44.9%** | **−$0.24** |
| exposure-v58plus | 1 | — | — |

The era the live policy actually ran in is the worst cohort on good-rate and the only
negative-average one, while the retired era looks best. A random-row fold averages
the two and reports the *retirement* as the improvement — which is the doctrine's
whole point, now measurable in one command instead of argued.

## F · Verification

```
node query_bankroll.js            → as-recorded vs now + UTC cross-check lines; log +4 rows
mark-shadow-longshot.ts           → jq .decayBar → {thresholdUsd .5, cohort7d 0.56, tripped false, rule …}
scan-wallets.ts (live run)        → 25/25 profiled, state written, 0 [SCAN PARTIAL] lines
report-daily.ts --dry-run         → "• Wallet scan: 25/25 profiled (last run 14:04) · 0 partials in 7d"
export-training-data.ts           → header carries era/ruleSetVersion/decision_at/simulated_pnl; per-era block printed
npx tsc --noEmit                  → clean
npm test                          → 215/215
roadmap                           → 200; 3 new cards + the promoted doctrine card (Scheduled)
cron prompt                       → 9,702 → 11,622 chars, four standing inputs (backup jobs.json.bak-tuning31-standing-inputs-20260920)
```

## G · Deliberate non-actions

- **No `maxPriceDrift` change** — rec 2 is a pre-registration; the gate keeps its
  value until the bar trips (and the Oct 8 read is benchmarked at drift 0.004).
- **No scan-wallets retry/schedule change** — instrumentation only, per the rec.
- Nothing re-litigated from #30 (v58/v59 grandfather, the parity identities), and the
  annotation leak stays a watch item rather than a fourth consecutive proposal.
