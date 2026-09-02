# DRAFT — RuleSet v32: Regulatory-Boost Clamp (unvalidated signal can't manufacture 80+ copies)

**Status:** ✅ IMPLEMENTED as RuleSet v34, 2026-08-29 21:33 CT (`regulatoryScoreCap` 79; RuleChange audit row `hermes-v34-regulatory-clamp`). Code: `trade.ts` boost tracking + clamp after the late-entry filter; a scoring boundary bug found during testing (raw 79.01–79.99 fell through the sweet-spot band) fixed by rounding once before banding and making the sweet spot `< highScoreCapMin`. 55/55 tests green, tsc clean. Rollback = deactivate v34 / reactivate v33.
**Source:** Phase-8 signal audit (same session): 34 boosted decisions in 7 days, **all 13 copies landed in the 80+ band** (worst historical band for C-200: −$0.78/trade), and **zero boosted trades have ever resolved** — the boost is running unvalidated at full strength.

## The problem

`trade.ts` Phase 8 adds **+25/+10/−20** to copyScore from Quiver/Congress sentiment. A raw score of 55–70 + 25 lands in the 80+ band — the band v29 just capped for being the worst bucket, and the band v31's sweet-spot bet explicitly avoids. We're manufacturing high-confidence copies from an unvalidated signal.

## The change (2 parts)

### 1. New rule field — `regulatoryScoreCap` (default **79** = `sweetSpotMaxScore`)

`src/lib/rules.ts`:
```ts
// v32: regulatory boosts are unvalidated (0 resolved trades) — a positive
// boost may never manufacture a copy in the ≥80 band (worst PnL bucket).
regulatoryScoreCap: number;   // interface
...
regulatoryScoreCap: 79,       // DEFAULT_RULES
```

### 2. Clamp in `trade.ts` — applied AFTER the v29 drift filter, BEFORE sizing

```ts
  // Phase 8: ... (existing boost block, + track whether a positive boost applied)
  let regulatoryBoosted = false;
  if (input.regulatoryAgreement !== undefined) {
    if (input.regulatoryAgreement >= 0.7) {
      copyScore += 25; regulatoryBoosted = true;
      reasons.push("Regulatory sentiment aligns strongly");
    } else if (input.regulatoryAgreement >= 0.3) {
      copyScore += 10; regulatoryBoosted = true;
      reasons.push("Regulatory sentiment aligns");
    } else if (input.regulatoryAgreement <= -0.3) {
      copyScore -= 20;
      risks.push("Regulatory sentiment opposes");
    }
  }

  // v32: never let an unvalidated boost push a copy into the ≥80 band.
  // The v29 late-entry filter above already ran on the PRE-clamp score, so
  // late entries can't ride a boost past the 0.004 drift quality gate.
  if (regulatoryBoosted && copyScore > rules.regulatoryScoreCap) {
    copyScore = rules.regulatoryScoreCap;
  }
```

**Ordering is deliberate:** the v29 filter (`copyScore ≥ 80 && drift > 0.004 → skip`) evaluates the unclamped score first — a boosted late entry is still rejected. Then the clamp lands boosted signals in the 70–79 sweet spot for sizing.

## Why clamping into the sweet spot is still +EV

| Outcome | Size (eff) | Edge (all-time) | Expected/trade |
|---|---|---|---|
| Status quo: boosted 80+ | $4.99 | −11.9% | **−$0.59** |
| v32: boosted 70–79 | $9.00 | +2.2% | **+$0.20** |

Even if the boost is pure noise, the trade is now governed by the sweet-spot band's (weak, unproven) positive edge instead of the proven-losing band.

## Deliberately NOT changed

- Boost magnitudes stay (+25/+10/−20) — the clamp solves the band problem; magnitudes are a follow-up if resolution data shows the signal has no edge.
- Negative agreement (−20) untouched — penalizing opposition is directionally sound.
- The short-TTR lane's own handling unchanged.

## Tests (implementation phase)

1. Update "boosts copyScore when regulatory strongly aligns": boosted final score **clamped at `regulatoryScoreCap` (79)**, still `> base`, reason present, size = `sweetSpotSizeUsd`.
2. New: boosted + late entry (drift > 0.004, not lane-eligible) → **skip** (pre-clamp filter still fires).
3. New: boosted clean entry (drift ≤ 0.004) → paper_copy, `copyScore === 79`, size $18 (sweet).
4. New: unboosted high score (no regulatoryAgreement) → NOT clamped (85 stays 85, capped $10).

## Rollback

- Remove/raise `regulatoryScoreCap` (or set 100) in next ruleset; code clamp is additive + gated by the field.

## RuleChange audit strings

- reason: `Clamp regulatory-boosted copyScore at 79: all 13 boosted copies (7d) landed in the ≥80 band (−$0.78/trade for C-200); 0 boosted trades resolved — signal unvalidated`
- evidence: `34 boosted decisions / 13 copies all ≥80; band PnL: 80+ −$0.78/trade (242), 70–79 +$0.115/trade (396)`
