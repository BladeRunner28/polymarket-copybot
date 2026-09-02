# v41 — Calibration-Band Sizing + Hour Policy (2026-08-31, user-approved)

Source: C-200 daily report (job 84e37616f39a) → user: "Proceed with both changes".

## Change 1 — Reallocate notional by calibration band

**Implementation:** `src/lib/paper.ts` `mapBankroll200Size(size, entryPrice)`
- Mapping raised: parent 0.25–20 → **$0.20–$20** (overall cap $10 → $20; `src/lib/safety.ts` BOT_LIMITS.BANKROLL_200 max 10.00 → 20.00).
- Band multipliers (N=1,076 C-200 calibration, 2026-08-31):
  - entry < 0.20 → ×1.5 (only significant positive edge, excess +0.31, z=+4.47)
  - 0.20–0.40 → ×1.0 (positive excess z=+2.72 but dollar-negative — watch, don't chase)
  - 0.40–0.60 → ×0.75 (dead zone: half the volume, −$305)
  - entry ≥ 0.60 → ×0.5 (premium drag on favorites, z=−2.49/−2.42)
- **Anti-double-count:** the v37 rules-layer factors (`deadZoneSizeFactor`, `longshotSizeFactor`) are neutralized to 1.0 via RuleSet v39 (`scripts/apply-v41.ts`, changedBy `hermes-v41-band-sizing`) — RuleChange audit row written. `src/lib/scoring/trade.ts` keeps the fields (re-enabling = explicit rule change that would double-count).
- Effective caps per band (STANDARD-scale 18 copy): <0.20 → $20 (clamped), 0.20–0.40 → ~$18, 0.40–0.60 → ~$13.50, ≥0.60 → ~$9. Works with the existing ×3 confidence boost and v38 premium overlay (both pre-mapping, capped at 45 STANDARD-scale).

## Change 2 — Gate the drain hours (ET)

**Implementation:** `src/lib/hour-policy.ts` (pure, DST-aware via `America/New_York`) + `scripts/score-trades.ts`
- Blackout new C-200 entries at **20:00 ET** (excess −0.27, z=−3.31, −$91) and **23:00 ET** (z=−2.90, −$98).
- **50% size haircut at 10:00 ET** (largest single-hour dollar drain, −$178, z=−1.74).
- 21:00 ET untouched (z=+2.80 positive edge). STANDARD long-dated book unaffected (analysis is C-200-only).
- Gate placement: blackout checked at the top of the BANKROLL_200 branch (before the open-position cap); haircut applied to positionSize right before `openPaperTrade`. Skips are logged `[BANKROLL_200] hour blackout …` / `[BANKROLL_200] … size haircut …`.

## Tests
- `tests/paper-sizing.test.ts` (new) — mapping, band multipliers, boundaries, clamp-overflow, NaN safety.
- `tests/hour-policy.test.ts` (new) — blackout set, haircut hour, 21:00 open, DST conversions (Aug EDT / Jan EST / Mar switch).
- `tests/trade-scoring.test.ts` — updated 5 assertions for the neutralized rules-layer factors.
- Verified: `npx vitest run` (full suite) + `npx tsc --noEmit` (typecheck).

## Rollback
- Rules: deactivate RuleSet v39, reactivate v38 (`UPDATE RuleSet SET active = 0 WHERE version = 39; UPDATE RuleSet SET active = 1 WHERE version = 38;`) — factors 0.5/1.5 return.
- Code: revert paper.ts mapping to 0.10–10 (delete `mapBankroll200Size`); BOT_LIMITS.BANKROLL_200 max back to 10.00; remove hour-policy import/gates in score-trades.ts; delete `src/lib/hour-policy.ts`.
