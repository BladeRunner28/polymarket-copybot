# DRAFT — RuleSet v29: Invert Sizing Curve + Capital Recycling

**Status:** ✅ IMPLEMENTED & ACTIVATED 2026-08-28 19:50 CT (RuleSet v29 active, RuleChange audit row by `hermes-v29-daily-report`; 52/52 tests green, `tsc --noEmit` clean). Rollback = deactivate v29 / reactivate v28. → **v30 2026-08-28:** `maxOpenPositions` raised 100→150 per user request (`apply-v30.ts`, audit row `hermes-v29-tweak`).
**Source:** C-200 daily report 2026-08-28 (score→PnL inverted; 276 open positions stranding $1,529).
**Author:** Hermes (drafted from report recommendations + codebase reading)

---

## 0. The two recommendations, restated precisely

1. **Invert the sizing curve.** v28 sizes linearly with confidence (`baseSizeUsd 8` + `confidenceSizeBonus 20`, plus a ×3 boost in `score-trades.ts` for confidence > 0.90). The data says the only +EV band is copyScore **70–79** (+$0.27/trade, 358 trades) while **≥80** is the worst bucket (−$0.77/trade, 240 trades) — the current code puts the *largest* sizes on the *worst* trades. Also raise `minCopyScore` 45 → 55 (45–59 tail is −$1.12/trade) and disqualify high-score late entries (score ≥80 with drift > 0.004).
2. **Capital recycling.** Cap open positions (~100) and force-close stale ones (no ≥5% move toward the winning outcome within 72h), freeing ~$500–900 back to cash for the 70–79 band and the short-TTR lane.

## 1. New rule fields (Rules interface + DEFAULT_RULES in `src/lib/rules.ts`)

| Field | Type | v29 value | Meaning |
|---|---|---|---|
| `sweetSpotMinScore` | number | 70 | lower bound of the +EV band |
| `sweetSpotMaxScore` | number | 79 | upper bound of the +EV band |
| `sweetSpotSizeUsd` | number | 18 | allocation for the 70–79 band (STANDARD scale) |
| `highScoreCapMin` | number | 80 | scores ≥ this get the capped size |
| `highScoreCapUsd` | number | 10 | capped size for ≥80 (STANDARD scale) |
| `highScoreMaxDrift` | number | 0.004 | drift ceiling for ≥80 (stricter than `maxPriceDrift` 0.008) |
| `maxOpenPositions` | number | 100 | open-position cap for BANKROLL_200 copies |
| `staleExitHours` | number | 72 | age after which a position is exit-eligible |
| `staleExitMinMove` | number | 0.05 | min relative move toward win required to stay open |

Plus `minCopyScore` **45 → 55** (existing field). All are plain numbers → `applyRuleChanges()` works unchanged and every value lands in the RuleChange audit row.

## 2. Sizing curve (`src/lib/scoring/trade.ts`, lines ~190–196)

**Current:**
```ts
const confidence = Math.round(((copyScore - rules.watchlistScore) / (100 - rules.watchlistScore)) * 100) / 100;

if (copyScore >= rules.minCopyScore) {
  // Higher confidence -> larger simulated size, always clamped to $.25..$20.
  const size = clampPaperSize(
    rules.baseSizeUsd + Math.max(0, confidence - 0.5) * rules.confidenceSizeBonus
  );
```

**Proposed (band sizing):**
```ts
const confidence = Math.round(((copyScore - rules.watchlistScore) / (100 - rules.watchlistScore)) * 100) / 100;

// v29: band sizing — the data says 70–79 is the only +EV region; scores ≥80
// (worst bucket) get the capped size instead of the largest one.
let size: number;
if (copyScore >= rules.highScoreCapMin) {
  size = rules.highScoreCapUsd;                                   // ≥80 → $10 flat
} else if (copyScore >= rules.sweetSpotMinScore && copyScore <= rules.sweetSpotMaxScore) {
  size = rules.sweetSpotSizeUsd;                                  // 70–79 → $18
} else {
  size = rules.baseSizeUsd + Math.max(0, confidence - 0.5) * rules.confidenceSizeBonus; // 55–69 → base curve
}

if (copyScore >= rules.minCopyScore) {
  const clamped = clampPaperSize(size);
```

## 3. High-score late-entry filter (`trade.ts`, after confidence is computed, before the `minCopyScore` branch)

```ts
// v29: late entries can't masquerade as high confidence — score ≥80 with
// drift beyond the strict ceiling is rejected (lane-eligible signals are
// exempt: the short-TTR lane has its own drift window by design).
if (copyScore >= rules.highScoreCapMin && drift > rules.highScoreMaxDrift && !laneEligible) {
  return {
    decision: "skip",
    copyScore: Math.round(copyScore * 10) / 10,
    confidence: 0,
    simulatedPositionSize: null,
    reasons: [],
    risks: [`score ${copyScore.toFixed(0)} ≥ ${rules.highScoreCapMin} but drift ${drift.toFixed(3)} > ${rules.highScoreMaxDrift} — late entry`],
    breakdown,
  };
}
```

## 4. Neutralize the ×3 confidence boost for the ≥80 band (`scripts/score-trades.ts`, lines ~185–196)

**Current:**
```ts
if (botId === "BANKROLL_200" && result.confidence > 0.90) {
  // Apply recommended max allocation increase strictly for high-confidence trades
  if (positionSize) {
    positionSize = Math.min(positionSize * 3, 45.00);
  }
  executionVenue = "Kalshi";
}
```
> ⚠️ This is the hole: confidence > 0.90 ⇒ copyScore ≥ 93.5, which sits inside the ≥80 band the cap targets. Unchanged, it would re-inflate sizes to the $10 hard cap for the worst bucket.

**Proposed:**
```ts
if (botId === "BANKROLL_200" && result.confidence > 0.90 && result.copyScore < rules.highScoreCapMin) {
  // v29: boost only applies below the capped band; scores ≥ highScoreCapMin
  // keep the flat capped size (high-confidence = worst bucket per Aug data).
  if (positionSize) {
    positionSize = Math.min(positionSize * 3, 45.00);
  }
  executionVenue = "Kalshi";
}
```

## 5. Open-position cap (`scripts/score-trades.ts`, inside the bot loop before `openPaperTrade`)

```ts
for (const botId of ["STANDARD", "BANKROLL_200"]) {
  if (result.lane === "short_ttr" && botId === "STANDARD") continue;

  // v29 capital recycling: stop opening new C-200 copies when the open book
  // is full — 276 opens were stranding $1,529 at ~$5.54 avg.
  if (botId === "BANKROLL_200") {
    const openCount = await prisma.paperTrade.count({
      where: { botId: "BANKROLL_200", status: "open" },
    });
    if (openCount >= rules.maxOpenPositions) {
      log(`[BANKROLL_200] open-position cap (${rules.maxOpenPositions}) reached — skipping copy ${t.marketId}`);
      continue;
    }
  }
  ...
```

## 6. Time-decay exit sweep (`scripts/update-pnl.ts`, after `updatePaperTradePrice(t.id, price)` at line ~84)

```ts
await updatePaperTradePrice(t.id, price);
updated++;

// v29 capital recycling: force-close C-200 positions older than staleExitHours
// that haven't moved ≥ staleExitMinMove toward the winning outcome. BUY-side
// model → win direction is price up. Reuses the existing closePaperTrade
// (same path as the dead-market expiry) so cash + realized PnL are booked
// consistently.
if (t.botId === "BANKROLL_200") {
  const ageHours = (Date.now() - t.openedAt.getTime()) / 3_600_000;
  const winMove = (price - t.entryPrice) / t.entryPrice;
  if (ageHours >= rules.staleExitHours && winMove < rules.staleExitMinMove) {
    await closePaperTrade(
      t.id,
      price,
      `stale ${ageHours.toFixed(0)}h, winMove ${(winMove * 100).toFixed(1)}% < ${(rules.staleExitMinMove * 100).toFixed(0)}% — v29 capital recycling`
    );
    expired++;  // or a new counter
  }
}
```
(update-pnl.ts already imports `closePaperTrade` and `getActiveRules` can be added — it currently doesn't load rules, so add `const { rules } = await getActiveRules();` at the top of main().)

## 7. Exact v29 rulesJson (delta vs v28)

```json
{
  "minCopyScore": 55,
  "sweetSpotMinScore": 70,
  "sweetSpotMaxScore": 79,
  "sweetSpotSizeUsd": 18,
  "highScoreCapMin": 80,
  "highScoreCapUsd": 10,
  "highScoreMaxDrift": 0.004,
  "maxOpenPositions": 100,
  "staleExitHours": 72,
  "staleExitMinMove": 0.05
}
```
Everything else carries over from v28 verbatim (short-TTR lane stays enabled: 2–72h, minCopyScore 35, drift 0.05, size 10, 10/cycle).

## 8. Effective sizes on BANKROLL_200 (after the 0.10–10 scaling in `openPaperTrade`)

| Score band | v28 (effective) | v29 (effective) |
|---|---|---|
| 55–69 | $4.0 – 4.8 | $4.0 – 4.8 (unchanged curve) |
| 70–79 | $4.4 – 5.8 | **$9.00** (≈2× allocation to the +EV band) |
| 80–93 | $5.9 – 7.5 | **$4.99** (capped) |
| 94+ (conf > 0.90) | up to $10.00 (×3 boost) | **$4.99** (boost neutralized) |

> Note: `sweetSpotSizeUsd 18` and `highScoreCapUsd 10` are STANDARD-scale (the scale `trade.ts` rules already use — `baseSizeUsd 8`); `openPaperTrade` maps that band onto the bot's 0.10–10 range. The report's "cap ≥80 at ~$10" is therefore achieved in *effective* terms by the 70–79 band taking the $9.00 max allocation while ≥80 drops to ~$5. If you want ≥80 at the full $10 effective cap, set `highScoreCapUsd: 20` (STANDARD scale) — flagged as the more aggressive option.

## 9. Tests to add (implementation phase)

- `tests/trade-scoring.test.ts` (pure function):
  1. score ≥80 → size exactly $10 (STANDARD scale), independent of confidence.
  2. score 70–79 → size exactly $18.
  3. score 55–69 → base curve formula.
  4. score ≥80 + drift 0.005 (not lane-eligible) → `skip` with late-entry risk.
  5. score ≥80 + drift 0.005 + lane-eligible → NOT skipped (lane path).
- Smoke test after deploy: one monitor cycle → verify open count ≤ 100, log lines, and that a stale 72h+ position closes with cash booked.

## 10. Rollback

- RuleSet is versioned: deactivate v29, reactivate v28 (one transaction, audit trail in RuleChange).
- Code changes are additive + gated by new fields; a ruleset without the new fields falls back to DEFAULT_RULES values. If `sweetSpotSizeUsd` etc. were ever removed, `{ ...DEFAULT_RULES, ...parsed }` restores v28-equivalent behavior.
- `closePaperTrade` path is already proven in production (dead-market expiry).

## 11. RuleChange audit strings (proposal → applyRuleChanges)

- reason: `Invert sizing: cap ≥80 at $10 (worst bucket −$0.77/trade), 70–79 to $18 (+$0.27/trade only +EV band); minCopyScore 45→55 (45–59 tail −$1.12/trade); ≥80 drift ceiling 0.004 | Capital recycling: cap 100 opens + 72h/5% stale exit (276 opens stranding $1,529)`
- evidence: `Aug 28 report: score≥80 240 trades −$185.03; 70–79 358 trades +$95.78; 697 closed 48.9% win −$194.58 realized`
