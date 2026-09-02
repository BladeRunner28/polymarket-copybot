# Tuning Review #12 — Approved Implementation (2026-09-01)

Source: copybot-tuning-review-daily cycle #12 (job 34d312687d17) → user: "approved".
Rules active at approval: v40 (Homerun audit risk gates, per-market only).

## Implemented (6 recs)

### Rec 1 — Hold v40 (no-op)
No rule changes to drift/quality bars. 9h of v40 data; resolutions need to accumulate.

### Rec 2 — Watch C-200 throughput (no-op, condition not met)
C-200 open book is 30/225 (not slot-starved) — the conditional ("loosen drift →0.004
only if C-200 stagnates") is not met. Drift stays 0.0034.

### Rec 3 — Trim API_DELAY_MS
- `~/.hermes/scripts/copybot-monitor-score.sh`: **300 → 150ms** (score:trades; 4th clean
  429 window; cadence was 56% of scheduled).
- `~/.hermes/scripts/copybot-scan-wallets.sh`: 300 → 200ms (hourly, gamma-heavy — less aggressive).

### Rec 4 — Phase B risk gates (octagon-audit §4), shipped early
New rule fields (`src/lib/rules.ts`, **RuleSet v41**, changedBy `hermes-v41-risk-gates`,
audit row written):
- **`maxCategoryPositions: 40`** — per-category concentration gate: max open C-200
  positions per research category (Crypto, Tech/AI, Defense/Geopolitics, Healthcare,
  Energy/Climate, Finance, Macro/Politics via `researchCategoryFor`). Unmapped markets
  ("Other") are heterogeneous → uncapped (weather/sports bundles are not correlated risk).
  Current book: Tech/AI 4, Defense 3, Macro/Politics 3, Crypto 1, Finance 1 — no bind.
- **`maxDrawdownPct: 0.20`** — portfolio drawdown gate: net worth = principal +
  realizedPnl + Σ open unrealized; peak seeded from principal ($1,900) and persisted in
  `data/c200-drawdown.json` (written only on a new high); trip when
  (peak − netWorth)/peak > 20%. Verified: netWorth $1,709.23 → 10.0% drawdown, clear.
- Wired into `scripts/score-trades.ts` risk-gates block (same journaled-watchlist pattern
  as the v40 gates). 0 = disabled sentinel on both fields.
- Kelly port itself stays on the Sep 15 track (roadmap: ships with the Sep 15 λ̂ refit).

### Rec 5 — ML-1 review/export visibility in EOD
`~/.hermes/scripts/copybot-eod.sh`: `review:outcomes` + `export:training` changed
`| tail -1` → `| tail -5` — the label-count lines were being swallowed.

### Rec 6 — 404-cache + Kalshi breaker state
- `scripts/update-pnl.ts`: persistent dead-slug negative-cache
  (`data/dead-slug-cache.json`, last 24, FIFO). Cached slugs skip the doomed
  `fetchMarket` and go straight to `fetchEventResolution` recovery. (The adapter's own
  cache is process-lifetime — useless across the hourly runs; this one survives.)
- Kalshi breaker state confirmed: realized **−$107.93** < −$50 floor → breaker TRIPPED →
  Kalshi routing stays paused (Polymarket-only) via the v37 gate.

## Verification
- 93/93 tests, `tsc --noEmit` clean.
- RuleSet v41 active + RuleChange audit row (before/after JSON).
- Drawdown gate math verified live: $1,709.23 net worth, 10.0% drawdown, peak $1,900.
- update-pnl run exercising the new cache path (background, results in the monitor log).

## Rollback
- Rules: deactivate v41, reactivate v40 (`active=1`). Gates revert to disabled (0).
- Code: remove the gate block + precompute in score-trades.ts; revert update-pnl.ts cache;
  restore API_DELAY_MS 300/300; restore `tail -1` in eod.sh; delete data/c200-drawdown.json.
