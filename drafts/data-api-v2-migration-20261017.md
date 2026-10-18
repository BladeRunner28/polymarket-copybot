# Data API v1 → v2 migration — parity probe result and the exact diff

**Read-only probe complete 2026-10-17. Nothing in `src/` has been touched.** Probe:
`scripts/data-api-v2-parity-probe.py` → `data/data-api-v2-parity.json`. Card: `data-api-v2-migration`.

**The deadline is real.** Polymarket's migration guide (read today):
> **"Data API v1 is retired on October 24, 2026."**

The Sep 4 release note ("`/v1` keeps serving unchanged but is frozen") is the release-day framing; the
migration guide is the operative one. v1 still answers today (probe: HTTP 200).

## The good news: values are identical, so this is a shape migration

Row-level parity on live data, matched by `conditionId|outcomeIndex`:

| Field | v1 | v2 | Delta |
|---|---|---|---|
| realized PnL | `realizedPnl` | `realized_pnl` | **0.0 on 5/5 rows** |
| avg price | `avgPrice` | `avg_price` | identical |
| shares | `totalBought` | `total_size` | **identical (5/5)** |
| settlement price | `curPrice` | `current_price` | equal (0↔0.0, 1↔1.0) |
| leaderboard PnL | `pnl` | `pnl` | identical 5/5, same order/ranks |
| activity size | `usdcSize` | `usdc_size` | identical |

**No scoring input changes value.** Every change below is envelope, pagination, or field *naming*.

## Four hard blockers, each verified by live HTTP

1. **`offset` is rejected outright.**
   `400 invalid_request` — *"'offset' is not a query param on this API: pages are cursor-only, pass 'cursor'
   from a prior response's next_cursor"*. Every offset walker must become a cursor loop.
2. **Sort enums renamed.** `400` — *"invalid position sortBy: CURRENT"* and *"invalid position sortBy:
   REALIZEDPNL"*. v2 accepts `CURRENT_VALUE | PRICE | TOKENS | UNREALIZED_PNL | REALIZED_PNL`.
   So `sortBy=CURRENT` → `sort_by=CURRENT_VALUE`, `REALIZEDPNL` → `REALIZED_PNL`.
3. **The leaderboard's wallet key changed — and it is NOT `proxy_wallet`.** `/v2/leaderboard` rows are
   `[pnl, profile_image, rank, user_id, user_name, verified, volume, x_username]`. There is **no
   `proxy_wallet` field on this route**: the address is `user_id` (verified: `user_id` =
   `0xf0318c32…`, the same address v1 returns as `proxyWallet`). A blind `proxyWallet`→`proxy_wallet`
   rename would silently produce **null wallets for every leaderboard row**.
4. **`/closed-positions` is folded away.** It becomes `/v2/positions?status=CLOSED`; the row grows to 36
   fields (`entry_cost_usdc`, `total_pnl`, `percent_realized_pnl`, `redeemable`, `mergeable`, `status`,
   `first_entry_at`, …).

Bonus: **v2's leaderboard has no 50-row page cap** (verified `limit=100` → 100 rows), so that walker
collapses to a single request. And **activity `start` still works**, with `cursor` for paging.

## The diff — `src/lib/adapters/polymarket.ts`

**A. `fetchLeaderboard` (L115–L141)**
- L121 URL → `${DATA_API}/v2/leaderboard?time_period=month&order_by=PNL&limit=${limit}` — **delete the
  `for (let offset…)` loop at L119**, one request now covers the intake.
- L122 parse → `res.data` (envelope), rows at `res.data`, cursor at `res.pagination.next_cursor`.
- L129 `row.proxyWallet ?? row.address ?? row.wallet` → **`row.user_id ?? row.proxy_wallet ?? row.address`**
  (the `user_id` first-ordering is the fix for blocker 3).
- L135 `row.userName ?? row.name` → `row.user_name ?? row.name`; L138 `row.vol ?? row.volume` →
  `row.volume`; `verifiedBadge`→`verified`, `xUsername`→`x_username` wherever consumed.
- L136 rank fallback `offset + i + 1` → running index (no offset in scope any more).

**B. Wallet profiling reads (L152–L240)**
- L174 → `${DATA_API}/v2/positions?user=${address}&status=CLOSED&limit=50&sort_by=REALIZED_PNL&sort_direction=${dir}`
- L217 → `${DATA_API}/v2/positions?user=${address}&status=OPEN&limit=100&sort_by=CURRENT_VALUE&sort_direction=DESC`
- L175/L218 parse → `.data` from the envelope.
- Field maps (both routes): `asset`→`token_id`, `conditionId`→`condition_id`, `avgPrice`→`avg_price`,
  `totalBought`→`total_size`, `realizedPnl`→`realized_pnl`, `curPrice`→`current_price`,
  `eventSlug`→`event_slug`, `outcomeIndex`→`outcome_index`. `slug`, `title`, `outcome`, `icon` unchanged.
- L192 `sizeUsd = totalBought * avgPrice` — **stays as-is**; `total_size` is numerically identical.
- L207 `won: (num(curPrice) ?? 0) > 0.5 || realizedPnl > 0` — logic unchanged, renamed fields only.

**C. Depth walkers (L257–L300)**
- `fetchClosedPage(offset)` / `fetchOpenPage(offset)` → `(cursor)`; pass `cursor=` and terminate on
  `pagination.next_cursor === null` instead of "empty page / out-of-range offset".
- The empirical page-cap comment (L257–L260) is now obsolete for v2 — keep it as history, note v2 paginates.

**D. Activity pager (L312–L375)**
- L319 → `${DATA_API}/v2/activity?user=${address}&type=TRADE&limit=${pageSize}&start=${since}` + `cursor`
- L372 terminator `data.length < pageSize` → `pagination.next_cursor == null`
- L347 `row.usdcSize ?? row.size` → `row.usdc_size ?? row.size`; plus `conditionId`→`condition_id`,
  `asset`→`token_id`, `transactionHash`→`transaction_hash`, `outcomeIndex`→`outcome_index`,
  `eventSlug`→`event_slug`.

**E. Error/load handling**
- v2 errors are `{code, error, parameter, retryable, trace_id}` with HTTP 400 (bad request) / 429 (load,
  plus `Retry-After`). The existing retry loop at L67 must honour `Retry-After` and must **not** treat
  `data: null` as an error — v2 documents a miss as `data: null` or `[]`.

**F. Cutover control**
- Add a `DATA_API_VERSION` env switch (default `v2`) with a v1 fallback path, so a bad cutover is one env
  change and not a revert. Remove the switch after 2026-10-24.

## Verification plan before v1 is removed

1. **Dual-read**: run one full cycle (monitor 30m + scan-wallets 2h + 06:00 leaderboard) with both versions
   in the same process; diff the wallet sets and the realized-PnL sums. Pass = identical wallet sets and
   PnL sums within float tolerance.
2. **Cursor completeness**: prove the paged wallet walk returns the same row count as the old offset walk
   for one high-activity wallet (the probe's wallet has 5+ closed rows and 3-cursor activity pages).
3. **Ledger reconciliation**: `update-pnl` after cutover must reproduce the same realized totals as the
   pre-cutover run on the same day.
4. Cut v1 after a clean cycle; keep the env switch until 10-24.

## Residual risks

- **Rate limits are per-family and unspecified beyond "429 + Retry-After"** — the leaderboard walker going
  from N requests to 1 *reduces* pressure, but `/v2/positions?status=CLOSED` now returns a 36-field row
  (more bytes per row) for the same page count.
- **`status=OPEN` defaults** may include `REDEEMABLE`/`MERGEABLE` rows that v1's `/positions` also returned;
  the dual-read diff is what settles it.
- **Nothing here changes scoring inputs** — but that claim rests on the parity table above, which is why the
  dual-read must run before the switch flips, not after.
