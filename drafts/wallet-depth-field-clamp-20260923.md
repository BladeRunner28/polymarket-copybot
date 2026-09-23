# Wallet depth was clamped by the FETCH, not by a rule — fixed, verified

**Card** `wallet-depth-field-clamp` (approved 2026-09-23) · **status** applied + verified · **date** 2026-09-23
**Instrument** `npx tsx scripts/verify-wallet-depth.ts --causal-check | --snapshot → npm run scan:wallets → --compare`

## The finding

`WalletProfile.resolvedTradeCount30d` / `tradeCount30d` looked like scoring settings and read like a cap:
**65.3% of all 3,201 wallets sat at exactly 100 resolved positions and 728 at exactly 200 total**, so a
100-position record was indistinguishable from a 900-position one. Nothing clamped them. The **fetch** did:

- `fetchWalletActivity` takes `/closed-positions` twice (50 best-PnL + 50 worst-PnL) → ≤ 100 closed rows
- and `/positions` once with `limit=100` → ≤ 100 open rows.

Live API surface probed 2026-09-23 (read-only): `/closed-positions` caps a page at **50 rows regardless of
`limit`** and warns `Deprecated: use /v1/closed-positions`; `/positions` honours `limit` ≥ 500; both honour
`offset`; out-of-range offset returns `[]`. A sampled wallet was still returning rows at offset 160,000.

## What shipped

| | |
|---|---|
| `src/lib/scoring/wallet-depth.ts` | `countPaged` / `measureDepth` — pure, tested |
| `DataAdapter.fetchWalletDepth(address, sample)` | live + demo implementations |
| `scripts/scan-wallets.ts` | stores the true counts + `depthCensored` / `depthCapNote` / `depthMeasuredAt` |
| `prisma/schema.prisma` | 3 new WalletProfile columns (applied by `ALTER TABLE ADD COLUMN`; prisma drift diff empty) |
| `tests/wallet-depth.test.ts` | 6 tests: exact-end, budget-bound, empty page, per-side walk, censoring |

**The separation that makes it safe:** the walk is a *separate* read. The scoring sample is untouched, so no
published score can move. A wallet whose sample came back **under** a ceiling is already fully covered and
costs **zero** extra requests; only wallets sitting exactly at a ceiling get walked, and the walk is bounded
(6 pages ≈ 300 closed / 600 open) with `censored=true` stored whenever the budget binds — a capped count is
never presented as the truth.

## Verification (three independent checks)

1. **Causal check — 25 wallets, sample frozen**: fetch the sample once, score it, run the depth walk, score the
   *same* sample again, deep-compare the sample array. **0 score deltas, 0 mutations, 21/25 wallets took the walk.**
   This is the only experiment that isolates the change: two production scans minutes apart see a *moved live
   book*, so their deltas are drift, not the change (measured as context: `max |Δ|` ≈ 0.00–0.03 per score).
2. **Production scan** (the real path, 25/25 profiled): **143 extra API requests** for the cycle,
   **23/25 wallets recorded deeper** than the sample, **21 now store a value above the old 100/200 ceiling**.
   Example moves: `100 → 269` resolved (exact), `200 → 900` total (censored at 9× the old ceiling).
3. **Census**: `resolved > 100` went **0 → 21 wallets**; `depth measured` **0 → 25**. The instrument's own
   BEFORE/AFTER lines are in `data/wallet-depth-verification.json`; the causal pass is in
   `data/wallet-depth-causal-check.json`.

## Reality check

- **The DB is only truthful where the scan has been.** The rotation profiles 25 wallets/hour, so a full cycle is
  ~5 days (3,201 wallets). Anything reading depth today sees truth for the scanned slice and the old ceiling
  elsewhere. The 7-day verification gate is set against the rotation, not the change.
- **Censoring is honest but still censoring.** 14 of 25 walked wallets continue past the budget. `depthCensored`
  names that; the cap follows `DEPTH_MAX_CLOSED_PAGES` / `DEPTH_MAX_OPEN_PAGES` if a deeper read is ever needed.
- **The walk costs API budget**: 143 requests for 25 wallets (~6/wallet, only where the sample was capped). A
  whale-heavy hour is the expensive one.
- **Re-run of the thin-record (floor) instrument on the now-truthful field is a follow-up card.** The null that
  killed the floor was measured on the clamped field; the unclamped field changes that input's resolution but
  nothing else about our book.
