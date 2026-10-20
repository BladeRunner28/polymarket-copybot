# The drift gate rejects better prices — priced, with the fix

**Date:** 2026-10-20 · **Lane:** A (proposal — nothing applied) · **Status:** PROPOSED, measurement-driven

---

## 1. The finding

`src/lib/scoring/trade.ts:75` computes the copied-entry drift as an **absolute** value:

```ts
const drift = Math.abs(input.currentPrice - input.walletEntryPrice);
```

and line 101 rejects the candidate when it exceeds the tolerance, under the label *"too late"*:

```ts
if (drift > driftTolerance)
  hardSkips.push(`price drifted ${drift} since entry > max ${driftTolerance} (too late)`);
```

For a **BUY**, a `currentPrice` *below* `walletEntryPrice` is a **better** entry — the bot pays less
for the same position. The absolute value cannot tell the two apart, so the gate rejects bargains
under the same rule, and the same number, as it rejects chasing.

The identical absolute value also feeds `entryTimingScore` at line 138
(`clamp(100 - (drift / maxPriceDrift) * 80)`), so a favourable move is **scored down twice** — once
as a hard skip, and once as a worse entry-timing signal.

## 2. What the gate is actually blocking

Measured from `data/drift-shadow.jsonl` (the gate counterfactual, marked to settlement), settled and
ex-dust (entry ≥ $0.10), deduped to one row per wallet/market/outcome, CIs clustered by market:

| cohort | n | net ROI | 95 % CI |
|---|---|---|---|
| **FAVOURABLE** (price fell below wallet entry) | 4,043 | **+29.9 %** | **[+25.8, +34.1]** |
| **ADVERSE** (price rose — genuinely late) | 3,616 | **−19.0 %** | **[−22.3, −15.7]** |
| all blocked | 7,659 | +6.8 % | [+4.1, +9.6] |

**52.8 % of the candidates the gate blocks were available at a better price than the wallet paid,
and that cohort returns +29.9 % net of the taker fee.** The adverse half returns −19.0 %, which is
the gate doing its job.

The blended +6.8 % is the number the existing instrument reports, and it is meaningless — it is a
+29.9 % cohort and a −19.0 % cohort added together. That averaging is why the summary's
`avgPnlPerTradeExDust` of $0.31/±$0.85 per trade never pointed at anything actionable.

### The tail confirms the direction, and it is not symmetric

Within **adverse**, drift scale predicts damage monotonically at the extreme:

- `[0.004, 0.006)` → +4.7 % [−5.5, +15.3]
- `[0.01, 0.02)` → −3.0 % [−11.5, +6.0]
- **`[0.05, ∞)` → −31.7 % [−35.2, −27.9]**

Within **favourable**, the same far tail is the *best* cohort in the file:

- `[0.02, 0.05)` → +3.4 % [−2.1, +8.6]
- **`[0.05, ∞)` → +71.1 % [+62.2, +80.2]**

So the earlier "raise `maxPriceDrift` to infinity earns +11.5 %" reading from
`gate-pricing-read.py` was **two opposite populations averaged**. Raising the tolerance is the wrong
instrument; it would admit the −31.7 % chasing tail along with the bargains.

## 3. The other gate is not priceable

`confidence < min` looked like the second-biggest blocker (5,139 reason-instances, 25 % of skips).
It cannot be priced, and the reason is structural:

- settled low-confidence candidates ex-dust: **3,923**
- of which confidence was the **only** blocker (`confidenceOnly`): **14**

**99.6 % of "low confidence" skips were co-blocked by other gates.** Relaxing the confidence floor
alone would admit ~14 candidates, not thousands. My earlier framing — that ~25 % of the funnel is
the confidence gate — was wrong: it is a *co-blocker*, not a standalone gate, so it is not a lever.
Example row from the shadow: `rawConfidence 0.26`, `otherBlocks 3`.

No change is proposed for confidence. It needs no change; it needs to stop being counted as one.

## 4. Proposal

**Make the drift comparison directional, and leave the adverse bar where it is.**

For a BUY of the copied outcome:

```
adverse = currentPrice - walletEntryPrice      // positive = we would pay more
favourable = walletEntryPrice - currentPrice   // positive = we would pay less

if (adverse > driftTolerance) reject          // UNCHANGED bar, now correctly signed
```

- **Adverse tolerance stays 0.004.** The measurement does not license loosening it — the adverse
  tail is −31.7 %. The gate is right about chasing; it is only wrong about bargains.
- **Favourable drift is admitted**, not merely tolerated. The +29.9 % cohort is the point.
- `entryTimingScore` should use the adverse component only, so a better price stops being a penalty.

This is deliberately **not** "raise `maxPriceDrift`". That change would be both less effective and
in direct conflict with the standing pre-registration.

## 5. Reality checks, stated before any apply

1. **The pre-registered decay bar (2026-09-20) does not license a `maxPriceDrift` relaxation** —
   `tripped: false`, `cohort7d: $0.85` vs the $0.50 bar, `consecutiveDaysAtOrBelow: 15` on the
   cumulative series but the trailing-7d cohort is above the bar. A directional fix that *leaves the
   adverse bar unchanged* is arguably outside that pre-registration, because it does not relax the
   chasing tolerance at all — but it does change what the lane buys, so it is Lane A and it needs an
   explicit yes either way. **Flagging the tension rather than exploiting it.**
2. **Settlement skew.** Only 8,114 of 33,848 drift-shadow candidates have resolved (24 %). Resolved
   markets are the fast ones, so this population over-represents short-TTR markets. The favourable
   cohort may not generalise to long-dated markets.
3. **Co-blocking kills the standalone value of the fix, and this is the finding that matters most.**
   `drift-shadow.jsonl` DOES carry `otherBlocks` (added 2026-10-11 as "Instrument v2"); my first pass
   read a pre-2026-10-11 row, saw null, and wrongly reported the field as missing. Measured properly
   on the **6,838** rows that carry it:

   - distribution: 1 other blocker 2,559 · 2 → 3,845 · 3 → 141 · 4 → 293
   - **`otherBlocks == 0`: ZERO rows. Minimum is 1.**

   **The drift gate is never the sole blocker.** A directional fix would therefore admit *zero*
   additional copies on its own — the candidates would be rejected by another gate anyway. The
   favourable cohort's +29.9 % is real, but it is not reachable by fixing the sign alone.

   Caveat in the other direction: `result.risks` may mix hard gates with soft/informational penalties,
   so `otherBlocks > 0` does not prove a second *hard* gate fires. The number of extra copies is
   therefore bounded above by 4,043 and could be zero — **not established either way**, and the
   stored data cannot settle it because only the COUNT was recorded.
4. **Throughput caps still bind.** `maxCopiesPerCycle = 50` and current flow is ~15 copies/day, so
   admitting ~122 favourable candidates/day would not produce 122 copies/day.
5. **A falling price can be information.** Sometimes the market is telling you the wallet was wrong.
   The counterfactual cannot distinguish "cheap because unloved" from "cheap because informed", which
   is why the +29.9 % is a population average and not a guarantee. A directional gate should be
   followed by a forward read, not trusted on the backtest alone.

## 6. Verdict

**The sign defect is real, and it is a correctness bug rather than a lever.** 26 % of all skip
reason-instances sit behind a comparison that cannot distinguish a discount from a chase, and the
directional split is unambiguous (n=7,659 settled, market-clustered CIs, both cohorts tight and on
opposite sides of zero). It should be fixed because a rule that refuses better prices is wrong.

**But it is not the profit unlock I first presented it as.** Zero of 6,838 field-carrying rows have
the drift gate as the sole blocker, so fixing the sign alone admits nothing. My earlier estimate of
~$356/day from the favourable cohort (`122 candidates/day × +29.9 % × $10`) was **an upper bound
presented as an expectation, and the co-blocking measurement shows it is very likely to be zero in
practice.** Retracted.

The honest sequence is therefore: fix the sign (correctness), name the co-blockers (instrument), and
only then price whether relieving the *bundle* of gates that reject favourable-drift candidates is
worth it. Fixing the sign and measuring no change in copy count would be the expected outcome.

**Nothing is applied.** This is Lane A: it changes what the bot buys.

## 7. Instrument gap closed (Lane B, done)

`otherBlocks` already existed (2026-10-11). What was genuinely missing is the **identities** of the
co-blockers: the feed could say "2 other risks fired" but never *which*, which is exactly why
requirement 3 above cannot be resolved from history.

**Applied 2026-10-20 (Lane B, no approval needed):** `otherRiskKinds: string[]` added to
`DriftShadowCandidate` and to the row written by `appendDriftShadow`, populated at
`score-trades.ts` from the non-drift entries of `result.risks`. `tsc` clean, 500/500 tests pass.
Future rows can be attributed by co-blocker; historical rows cannot, and must not be read as if
"2 other blockers" meant the same two every time.

---

## Provenance

| figure | source |
|---|---|
| absolute drift computation | `src/lib/scoring/trade.ts:75`, comparison `:101`, score penalty `:138` |
| 33,848 candidates / 8,114 settled | `data/drift-shadow.jsonl` + `data/drift-shadow-summary.json` |
| directional split and CIs | `scripts/drift-direction-read.py` |
| admitted-set sweep | `scripts/gate-pricing-read.py` |
| confidence co-blocking | `data/lowconf-shadow.jsonl` (`confidenceOnly`, `otherBlocks`) |
| decay bar state | `data/drift-shadow-summary.json` |
| live thresholds | active RuleSet v64 (`maxPriceDrift 0.004`, `minConfidence 0.7`, `longshotMinConfidence 0.55`) |
