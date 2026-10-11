# /paper-trades perf — latest-snapshot-per-market was the cost (card `dashboard-latest-snapshot-cost`)

**Date:** 2026-10-11 · **Status:** SHIPPED + VERIFIED · **Gate:** page `<1.5s` with all open markets present → **MET**

## Problem

`/paper-trades` was the dashboard's slowest page: **ttfb 4.57 / 6.89 / 7.84 s** over three reads this morning,
against a card gate of `<1.5 s`. `/analytics`, the previous worst page, sits at 0.87 s after its own fix.

The whole delta is the open-MTM horizon block. It asks, for each market holding an open leg, for the **latest
MarketSnapshot row** — and the retired shape did it in one statement:

```sql
SELECT marketId, MAX(collectedAt) AS collectedAt, timeToResolution, question, isDemo
FROM MarketSnapshot
WHERE marketId IN (<349 ids>)
GROUP BY marketId
```

## Root cause

`MAX(collectedAt)` with **bare columns** cannot be answered from an index. SQLite finds the group's maximum from
the `(marketId, collectedAt)` index but must then fetch a **table row** for every snapshot each market holds —
with 349 open STANDARD markets that is ~860k row fetches, all to keep 349 of them.

Measured with the composite index installed, same data, fresh process (n=5, `scripts/latest-snapshot-shape-probe.ts`):

| Step | median |
|---|---|
| aggregate only, `SELECT marketId, MAX(collectedAt) … GROUP BY marketId` | **45 ms** |
| row fetch by `(marketId, collectedAt)` pairs — one indexed seek each | **2 ms** |
| retired single statement (bare columns) | **579 ms** |

So the index alone did **not** fix the page: the single statement measured 576–606 ms with it installed. The split
is the load-bearing change; the index is what makes the second step an individual seek instead of a scan.

## Fix

`src/lib/open-mtm-horizon.ts::loadOpenMtmHorizon()` now reads in two steps:

1. index-only `MAX(collectedAt)` per market (45 ms),
2. `WHERE (marketId = ? AND collectedAt = ?) OR …` row fetch — **chunked at ≤200 pairs per query** (2 ms).

The chunk is not cosmetic: SQLite rejects an OR-chain of ~1000 pairs with
`Expression tree is too large (maximum depth 1000)`. Measured: **n=900 OK, n=1200 ERROR**. A chunk of 200 keeps
~5x headroom and stays safe if the open book grows past today's 349 markets.

Backing index (already built in a quiet window; `scripts/build-market-snapshot-composite-index.sh`, idempotent):

```sql
CREATE INDEX IF NOT EXISTS MarketSnapshot_marketId_collectedAt_idx ON MarketSnapshot(marketId, collectedAt);
```

## Verification

- **Data-layer parity** — the shipped loader's output is compared market by market against the retired statement's
  rows (stamp, timeToResolution, question, isDemo): **349 rows vs 349 groups, 0 mismatches**, and the raw row sets
  were already proven field-identical. `npx tsx scripts/latest-snapshot-shape-probe.ts` (read-only; exits 1 on any
  mismatch, so it is re-runnable as the card's permanent check).
- **Render parity** — page text before vs after the rebuild is **byte-identical**; STANDARD still shows all
  **349 open markets** (DB: 349 markets / 1,283 legs), so the fail condition "a fix that drops markets" is not met.
- **Wiring tests** — `tests/open-mtm-horizon-load.test.ts` (5 tests, stubbed transport): chunk boundary at 449
  markets → 1 aggregate + 3 pair fetches; empty aggregate emits **no** second query (no malformed `WHERE`);
  a missing snapshot row lands in `unknown` instead of being dropped; an empty book touches the DB not at all.
- **Suite** — 429/429 tests, `tsc --noEmit` clean.

## Live result

`/paper-trades` **ttfb 0.77 / 0.80 / 0.82 / 0.85 / 0.90 s** (5 reads) — gate met. Ship cycle used:
`npm run build` → `launchctl kickstart -k gui/$UID/com.xsnyde2.copybot-dashboard` → curl poll to 200.

**Honest caveat:** the live reads follow a restart, so that figure mixes the code fix with a fresh V8 heap; the
**11x is the same-process number**, and the live improvement will be re-read once the process has aged.

## Still open — the bigger lever

The LaunchAgent runs at **`spawn type = background (5)`** (Apple-Silicon background QoS). Measured on the same
build/DB/moment: `/analytics` 556 ms fresh vs **3,323 ms** live, `/journal` 400 vs **2,088 ms**, while non-DB pages
matched. That is worth more than anything left in the query path — and `/signals` (2.63 s) and `/journal` (2.42 s)
are now the slowest pages. `launchctl kickstart -k` does **not** re-read the plist, which is why removing
`ProcessType` on 2026-10-10 changed nothing. Carded as `dashboard-launchd-qos`; the reload is a human shell step
(the gateway blocks `launchctl bootstrap`) and the plist edit was proposed, not applied.

## Reproduce

```bash
npx tsx scripts/latest-snapshot-shape-probe.ts                       # timings + parity, writes nothing
curl -s -o /dev/null -w 'ttfb=%{time_starttransfer}\n' http://127.0.0.1:3013/paper-trades
launchctl print gui/$UID/com.xsnyde2.copybot-dashboard | grep 'spawn type'
```
