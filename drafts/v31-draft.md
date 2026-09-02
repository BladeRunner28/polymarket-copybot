# DRAFT — RuleSet v31: Sweet-Spot-Only Book (minCopyScore → 70)

**Status:** ✅ IMPLEMENTED & ACTIVATED 2026-08-28 20:00 CT (RuleSet v31 active, `minCopyScore` 70; tuner-floor patch in `rule-updater.ts`; 53/53 tests green, `tsc --noEmit` clean; audit row `hermes-v31-sweet-spot-only`). Rollback = deactivate v31 / reactivate v30.
**Source:** Post-v29 trajectory review (same session): the 55–69 band is the biggest leak — all-time **−$0.99/trade** (110 trades, −24% edge) and it's ~25% of copy volume. v29 left it on the base curve; its drain swamps the 70–79 gains (net expected ≈ −$13/day). Raising the main-lane bar to 70 makes the book sweet-spot-only: expected ≈ **+$14/day** at current volume if the 70–79 edge holds.

## Change

| Field | v30 | v31 |
|---|---|---|
| `minCopyScore` | 55 | **70** (= `sweetSpotMinScore`) |

- Main lane: only scores ≥70 copy → 70–79 @ $18 (→ $9.00 eff), ≥80 @ $10 cap (→ $4.99 eff) — v29 bands unchanged.
- 55–69 signals → journaled as watchlist (reviewable, not lost).
- **Short-TTR lane unchanged** (floor 35, fixed $10 → $4.99 eff): deliberate permissive fast channel; watch its band PnL separately before touching it.
- Late-entry filter (≥80 / drift 0.004) unchanged.

## Supporting code change: auto-tuner can't erode v31

`src/lib/rule-updater.ts` rule 5 ("winning comfortably → relax minCopyScore") relaxed toward a floor of 55. With v31 at 70, a hot streak (winRate > 60%) would ratchet the bar back down to 55 over successive nightly `update:rules` runs. Patch: relax floor = `max(sweetSpotMinScore, 55)` and only fire when above the floor. Rule 4 (losing streak → raise) already caps at 85 — compatible.

## Expected impact

- Volume: ~100 → ~70 copies/day (55–69 share dropped).
- Daily PnL: ≈ −$13 → ≈ **+$14/day** (all-time 70–79 edge +$0.115/trade @ $5.22 → +$0.20 @ $9.00, × ~70 copies).
- Phase-1 ($500/day) still needs 25× volume + confirmed edge — v31 is the "stop the bleeding" step, not the finish line.

## Rollback

- Deactivate v31 / reactivate v30 (one transaction, RuleChange audit trail).
- Tuner patch is additive; revert restores old relax floor.

## RuleChange audit strings

- reason: `Raise minCopyScore 55→70 (sweet-spot-only main book): 55–69 is the biggest leak, all-time −$0.99/trade (−24% edge) at ~25% of volume; v29 band sizing already favors 70–79`
- evidence: `BANKROLL_200 band PnL (all-time): 55–69 110 trades −$108.94; 70–79 396 trades +$45.46; 80+ 242 trades −$189.39. Post-v29 expected daily ≈ −$13/day → +$14/day`
