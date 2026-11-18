# Kalshi keyless history: what is actually retrievable, and what is irreversible

**Card:** `kalshi-settled-history-surface` (Backlog → Done, re-probe gate)
**Run:** 2026-11-18 09:00 · instrument `scripts/kalshi-settled-history-probe.py` (`--self-test` 30/30)
**Artifact:** `data/kalshi-settled-history.json`
**Lane:** B — read-only. No rule, size, threshold or lane touched.

## The claim under test

The card was opened 2026-11-02 off a line in `darup67/market-lab`: *"Kalshi serves roughly the last
two days of settled markets, and trades vanish with them — nothing here can be backfilled."*
The card recorded that FALSE for markets and UNVERIFIED for fills. This run re-probed all four
routes with their own clocks instead of one pooled "retention" number.

## Answer: the surface is two populations, not one retention depth

- **Recent market records** — `GET /markets?status=settled&min_close_ts=..&max_close_ts=..`
  FULL (200-row pages) from **2026-09-11 → today = 69 days**. Window honoured: every returned
  `close_time` lies inside the requested day. The "2-day" premise is false by ~34×.
- **Deep market records** — `GET /historical/markets` still returns full 200-row pages at
  **2024-12-18 (700 days back)**, and that page was *not* exhausted → 700 days is a **lower bound**,
  not the edge. Settled market records are re-fetchable at any depth we probed.
- **Archived fills** — `GET /historical/trades` returns real prints (`taker_side`, yes/no price,
  `count_fp`, `trade_id`) for markets that closed **on or before 2026-09-18** (62 days back), both
  per ticker and by time window. Both filters verified: a per-ticker read contains exactly one
  ticker, `trade_id` is unique (58,578 rows → 58,578 ids on one market).
- **Recent fills do not exist on any keyless route.** `/historical/trades` returns zero rows for
  every day after 2026-09-18, and the three routes the card blamed are simple **404**
  (`/markets/{ticker}/trades`, `/trades`, `/market/{ticker}/history`).

**So the card's fills half is refuted — but only for the archived era.** The venue's own fills stop
~62 days back, and our tape began 2026-10-12. **The two fills populations do not overlap in time.**
For the post-2026-09-18 era, our own tape is the only fills record that will ever exist.

## The number that changes a decision: how blind is our tape?

Population: 8 archived `KXBTC15M` tickers (stratified every k-th, 2026-07-21 → 2026-09-19), each
paged to **exhaustion** — 290,164 venue prints, 0 tickers truncated. Level: one venue print.
Clock: venue `created_time`.

- **83.4% of venue fills are under our tape's 100-contract floor.**
- **18.6% of CONTRACTS are under it.** Median print in that era: **4–15 contracts**.
- Concentration checked: per-ticker median 83.4%, ex-largest ticker 83.0% — not one market's shape.

Quoted on the wrong base this reads "we see a sixth of the fills" or "we see 83% of the flow". Both
are wrong. We see **~17% of fills and ~81% of volume** in that family.

## What this means for queued items (nothing applied)

- `kalshi-maker-read-prereg` (Lane A, **awaiting approval**): its limit C1 assumed the 100-contract
  floor was a detail. It is 83% of fills / 19% of contracts, and its fill model cannot be audited
  against venue fills for the tape era — those do not exist. The proposal itself is unchanged.
- `kalshi-tape-repo-size-policy`: the tape is **not** backfillable. Never prune stands, now measured
  rather than asserted.
- Phase C cross-venue work needing Kalshi resolution history can **read** it at any depth; no
  capture job is required.

## Defects found in this instrument's own first draft (kept, not hidden)

1. **PARTIAL-as-covered.** Days older than the retention edge return a handful of rows from ONE
   long-dated series (2026-09-09: 9 rows, all KXBIGGESTQUAKE; 08-15: 6, all KXHORMUZPEAK;
   07-01: 10, all KXEARTHQUAKE) while multi-series days before the edge return zero. Reading those
   as coverage put the edge 2 days too deep and drew a cliff as a slope. Now FULL / PARTIAL / EMPTY,
   and PARTIAL days are reported with their series names.
2. **Capped-pages bias.** `/historical/trades` is newest-first; a 3-page cap reported 72.5% / 6.4%
   where exhaustion on the same population gives 83.4% / 18.6%. Section D now pages to exhaustion and
   prints whether it truncated.

## Re-open condition

Re-probe when either: (a) a keyless route returns fills for a market that closed **after**
2026-09-18 (that would make the tape era auditable against the venue), or (b) `/historical/markets`
stops paging at a date shallower than 700 days (that would make the archive a decaying asset).
One command: `npm run kalshi:settled-history-probe`.
