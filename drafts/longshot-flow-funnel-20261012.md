# Long-shot FLOW funnel — where the <0.20 legs die, with counts

**Card:** `longshot-flow-funnel` · **Read:** 2026-10-12 · **Window:** 2026-10-05 → 2026-10-11 local (7 complete days, America/Chicago)
**Basis:** C-200 candidates = `ObservedTrade.observationOnly = 0`; candidate price = `ObservedTrade.detectedPrice` (the price the gates actually see); booked legs = `PaperTrade` `botId='BANKROLL_200'`, banded on `entryPrice`; blockers = `DecisionJournal.risksJson`.
**Artifact:** `data/longshot-flow-funnel.json` · **Script:** `scripts/longshot-flow-funnel.py` (read-only)

> **This window deliberately ENDS the day before v62.** v62 activated 2026-10-12 06:20 CDT, so everything below is the clean **pre-v62 baseline** for v62's own 7-day read at 2026-10-19.

---

## Key insight

**The long-shot band is not threshold-limited — it is multiply-gated, and the arithmetic caps it far below the gate.**

Three independent facts, all measured here:

1. **No single gate change admits meaningful flow.** Of the 386 `<0.20` skip rows in the week, **only 105 carry a single blocker** — and 68 of those are the dedupe (we already hold the position, no loss). Strip those and the entire one-gate-removable admission loss on the band is **37 candidates/week ≈ 5/day**.
2. **Drift is never the sole blocker.** It appears on 275 rows and is the *only* blocker on **zero** of them. 256 are drift **+** confidence, 123 drift **+** near-certainty, 121 drift **+** TTR. The gates fire in unison, and they agree: these candidates are late, thin and low-confidence.
3. **Even a perfect v62 caps the band at ~$157/day.** The band staked $769.95 and realised **+$783.75** in the week = **$111.96/day** at a **101.8%** settled ROI. v62's +40% size at unchanged flow ⇒ **~$157/day** against a **$500/day** gate.

So more sizing cannot close the gap, and neither can any one threshold.

---

## 1. The candidate funnel by band (7d)

| band | copy-eligible candidates | scored | copied | skip | conversion |
|---|---|---|---|---|---|
| 0.00–0.20 | 406 | 406 | 20 | 386 | **4.9%** |
| 0.20–0.40 | 2,220 | 2,217 | 33 | 2,184 | 1.5% |
| 0.40–0.60 | 2,987 | 2,987 | 102 | 2,885 | 3.4% |
| 0.60–0.80 | 1,918 | 1,919 | 18 | 1,901 | 0.9% |
| 0.80–1.01 | 661 | 661 | 1 | 660 | 0.2% |

Detected in the window: **785,638 rows** — 8,192 copy-eligible, 777,446 observation-only, across 942 wallets. Containment: **8,192 eligible / 8,190 decided** (the 2-row gap is the window-edge border, not a leak).

**The <0.20 band gets 58 candidates/day and converts 3.14/day.** It is a thin flow of a high-value signal, not a starved queue of good copies.

## 2. What actually got booked (C-200, 7d)

| band | legs | legs/day | notional | % of notional | avg clip | settled ROI |
|---|---|---|---|---|---|---|
| **0.00–0.20** | 22 | **3.14** | **$769.95** | **61.5%** | **$35.00** | **+101.8%** |
| 0.20–0.40 | 33 | 4.71 | $339.20 | 27.1% | $10.28 | −13.3% |
| 0.40–0.60 | 89 | 12.71 | $104.06 | 8.3% | $1.17 | +11.1% |
| 0.60–0.80 | 15 | 2.14 | $38.47 | 3.1% | $2.56 | +4.1% |
| 0.80–1.01 | 0 | 0.0 | $0.00 | 0.0% | — | — |
| **total** | **159** | **22.71** | **$1,251.68** | | | |

**13.8% of the legs carry 61.5% of the money and all of the edge.** Nothing else in the book pays.

## 3. Where the `<0.20` candidates die

**Co-occurrence (all blockers on the row — a row can carry several):**

| blocker | rows |
|---|---|
| DRIFT (price drifted since wallet entry) | 275 |
| CONFIDENCE (**long-shot floor** variant) | 263 |
| NEAR-CERTAINTY (`detectedPrice < 0.05`) | 129 |
| TTR (resolves sooner than min) | 122 |
| DEDUPE (already open — **not a loss**) | 68 |
| SPREAD | 65 |
| BLACKLIST (v45 category) | 34 |
| LIQUIDITY | 33 |
| HOUR BLACKOUT | 6 |

**Sole blockers — the count a one-gate change would actually admit:**

| sole blocker | rows |
|---|---|
| DEDUPE (not a loss) | 68 |
| BLACKLIST (v45 category) | 31 |
| HOUR BLACKOUT | 3 |
| NEAR-CERTAINTY | 2 |
| CONFIDENCE | 1 |
| **total single-gate rows** | **105** |

Blocker-set size: **1 gate = 105 · 2 = 62 · 3 = 137 · 4 = 55 · 5 = 27** ⇒ **281 of 386 rows (73%) carry two or more gates.** The modal candidate is rejected by three at once.

**Contrast by band** (share of that band's rows where the gate appears at all): DRIFT 47% (<0.20) → 41% (0.20–0.40) → 56% (0.40–0.60) → 79% (0.60–0.80) → 82% (0.80+). The drift gate is *least* involved in the band we care about.

## 4. Two sub-mechanisms worth naming

- **Every confidence block on this band is the long-shot floor**, not the standard `minConfidence` bar: **263 of 263**. The long-shot-specific floor is the actor, so any read of "minConfidence is/isn't binding" must use this variant.
- **The near-certainty gate rejects 100% of the sub-0.05 tail.** All **129** rows with `detectedPrice < 0.05` are hard-skipped by the symmetric `maxEntryPrice` rule (0.95 ⇒ reject `price < 0.05`, `src/lib/scoring/trade.ts:107`), and **2** C-200 legs were booked below 0.05 in the week. The deepest slice of the only +EV band is behind a wall that nothing has ever priced.

## 5. Drift magnitude — **counts only, no threshold proposed**

| drift at rejection | rows |
|---|---|
| > 0.1000 | 216 |
| 0.0500–0.1000 | 26 |
| 0.0100–0.0500 | 20 |
| 0.0040–0.0100 (would pass today) | 13 |
| **median** | **0.359** |

**78% of drift-blocked candidates died past a 10-cent move; the median is 36 cents.** With `detectedPrice < 0.20` and drift ≈ 0.36, the wallet's own entry was ≈ 0.36–0.56 — i.e. these are markets that collapsed *against* the wallet's position and we are being shown the wreckage. They are not good copies rejected by four-tenths of a cent.

## 6. Wallet depth of candidates reaching the band

| `resolvedTradeCount30d` | candidates |
|---|---|
| censored at the 300 cap | 225 |
| 10–49 | 73 |
| 50–99 | 41 |
| 100–299 | 41 |
| < 10 | 26 |

**225 of 406 (55%) come from depth-censored wallets** and only 26 from shallow ones — the wallet-depth floor is not what limits this band (and per `wallet-depth-ceiling-300-finding`, the censoring itself is unresolved).

---

## Reality checks — what this read does NOT say

- **"Primary blocker" is check ORDER, not priority.** `risksJson[0]` is the scorer's own sequence (`src/lib/scoring/trade.ts` checks drift early, line 101), so the headline "drift is the #1 primary blocker at 47%" is an artifact. The sole-blocker and co-occurrence tables are the honest view, and they are why this report leads with them instead.
- **68 dedupe rows are not lost opportunities.** They are the same wallet/market/outcome we already hold. Excluding them, the band loses 318 rows/wk to gates, not 386.
- **No threshold is proposed here, and none may be derived from it.** The drift bar carries its own pre-registered decision (`tr31-rec2-drift-decay-bar` = HOLD) and `drift-band-winrate-shadow` already recorded that its forgone value is price-scaled. The card's gate forbids taking a lever from this read.
- **The band edges shift by 2¢** against the booked ledger: C-200 fills are written at `intent − $0.02`, so a candidate at 0.19 can book at 0.17. Candidate rows are banded on `detectedPrice`, legs on `entryPrice` — deliberately, since each is what its own mechanism sees.
- **This is a flow census, not a value claim.** $111.96/day is this window's realised <0.20 PnL, not a forecast; the band's 7d ROI (101.8%) is a small sample (22 legs) with lottery-shaped tails, and one $100 clip moves it materially.
- **Annotation strings share `risksJson`** with the gates ("Mean Reversion Risk", "Spread eats into edge", "Price already near certainty"). They are classified separately and excluded from gate counts so they cannot displace a real blocker.

## Verdict

The card closes on the measurement, and the measurement says: **the long-shot band's ceiling is 3.1 legs/day of structurally-gated flow, and no single-mechanism change raises it.** Sizing is already answered by v62 (+40% ⇒ ~$157/day). A one-gate admission change is worth ≈ 4–5 candidates/day. What remains unmeasured is the **sub-0.05 near-certainty wall** (129 candidates/week, 0 admitted, never priced) — that is the next thing to *measure*, not to change, and it needs its own pre-registered shadow card before any lever is discussed.

**Reproduce:**
```
python3 scripts/longshot-flow-funnel.py
```
