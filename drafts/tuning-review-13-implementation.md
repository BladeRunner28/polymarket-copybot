# Tuning Review #13 — Approved Implementation (2026-09-02)

Source: copybot-tuning-review-daily cycle #13 (job 34d312687d17) → user: "Approved for all 6".

## Rec 1 — Hold v43 (no-op)
Drift 0.004 window under evaluation 3–5 days; minCopyScore 80→~75 trigger (C-200 daily <$150
with idle cash over the window) not met at approval time.

## Rec 2 — Cadence: API_DELAY_MS trim + monitor parallelism
- `~/.hermes/scripts/copybot-monitor-score.sh`: **150 → 100ms**, now also applied to
  `monitor:trades` (was inheriting .env 250ms).
- `scripts/monitor-trades.ts`: wallet-activity loop parallelized with a **bounded pool of 4**
  (was strictly serial over 25 wallets). Per-wallet work stays serial inside each task.

## Rec 3 — Hold spread 0.06 / liquidity 750 (no-op)
Evidence strong (wide −4.12 vs tight +4.43; lowLiq −3.36); hold until Sep 15 refit.

## Rec 4 — STANDARD protections (Phase B prep, Kelly deferred to Sep 15 refit)
- **STANDARD high-side entry cap 0.85** — new rule field `standardMaxEntryPrice`
  (**RuleSet v44**, changedBy `hermes-v44-tuning-review13`, audit row written), enforced
  per-leg in `scripts/score-trades.ts`.
  ⚠ NOT via the shared `maxEntryPrice` rule: that gate is symmetric
  `[1−max, max]` (trade.ts) — lowering it to 0.85 would block entries < 0.15 and kill the
  long-shot edge (z=+4.13, ×1.5 sized). The per-leg gate caps STANDARD only; C-200 keeps
  band sizing (≥0.60 ×0.5).
- **Worst-hour blackout extended to STANDARD**: the 20:00/23:00 ET blackout moved from the
  BANKROLL_200-only branch to the top of the per-bot loop — both books now skip those hours
  (`[${botId}] hour blackout …`). The 10:00 ET ×0.5 haircut stays C-200-only (no STANDARD
  evidence). `hour-policy.ts` comment updated.
- **Executable-quote Kelly: NOT implemented now** — the review's own wording defers it
  ("Kelly sizing at the Sep 15 refit"), matching the roadmap gate (ships with the Sep 15 λ̂
  refit). Roadmap card exists.

## Rec 5 — Governance: 48h auto-tune lockout after user-approved changes
`src/lib/rule-updater.ts` `runRuleUpdate()`: skips the whole auto pass when the most recent
RuleChange with `changedBy != "hermes"` (manual applies use `hermes-*` labels) is < 48h old.
**Verified live**: `update:rules` → "auto rule update SKIPPED: user-approved change
hermes-v44-tuning-review13 0.0h ago — 48h lockout". Prevents v42-style overnight over-tighten
8h before an approved loosen (v26 déjà vu).

## Rec 6 — 404 cache in update-pnl: ALREADY DONE (v41, #12)
Verified live: `data/dead-slug-cache.json` at the 24-slug cap. The reviewer's "14 404
failures" were first-time dead slugs being discovered → recovered → cached (the mechanism
working as designed), not uncached retries. Code comment annotated; no change needed.

## Verification
- 93/93 tests · `tsc --noEmit` clean.
- RuleSet v44 active (standardMaxEntryPrice 0.85) + RuleChange audit row.
- Lockout functional check passed (update:rules skipped).
- monitor:trades pool run in background (results in monitor log).

## Rollback
- Rules: reactivate v43 (drops standardMaxEntryPrice to DEFAULT 0.85 — field persists; set 0 to
  disable the STANDARD cap per-leg). Code: remove the STANDARD cap block + revert blackout to
  C-200-only; revert monitor pool to serial; restore API_DELAY_MS; remove lockout block.
