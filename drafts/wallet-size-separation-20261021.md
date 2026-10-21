# Wallet quality: admission signal, not a size signal (v65)

**Date:** 2026-10-21 · **Approved by:** user ("Do recommendation" on profit-recs #3) · **RuleSet:** v64 → **v65** · **Commit:** see `git log`

---

## 1. The recommendation, and the two things wrong with its premise

The daily profit review proposed: *"Wallet quality stops setting size; admission filter only,"* on the
evidence that per-wallet ROI has no forward information — **Spearman −0.018 (p=0.942)** between
first-half and second-half wallet ROI, with the **H1-WORST third earning +130% in H2 against +31.8 % for
the H1-best**. Routing a 0.30-weight noise term into size is sizing on noise.

Two corrections before anything was applied:

**(a) It never touched Kelly.** The recommendation said wallet quality was *"routed into Kelly sizes."*
It is not. `kellySizeForCopy()` (`src/lib/kelly.ts`) takes price, fraction, caps and edge — it never
receives a wallet score. C-200, the lane Kelly governs, was never exposed. The wallet term enters exactly
one place: the **legacy score→size bucket** at `src/lib/scoring/trade.ts:308-318`, which is STANDARD's
path.

**(b) The first measurement was wrong, and in the alarming direction.** Comparing a size recomputed under
*today's* rules against the `simulatedPositionSize` **stored** at the time suggested removing the wallet
term would **raise notional +34 %**. That was a basis error — stored sizes come from whatever ruleset was
live then. Re-computing **both arms under the same active rules** reverses it.

---

## 2. Measured effect

`scripts/wallet-size-separation-read.py`, 9,043 STANDARD legs whose stored components reconstruct their
`copyScore` exactly (78.1 % of the 11,583 with components; the other 1,198 carry additive adjustments —
cluster +25, regulatory caps — and are excluded rather than folded in). Both arms recomputed under v64:

| | wallet-in-size | wallet-free-size | Δ |
|---|---|---|---|
| notional | $137,895.70 | $130,697.91 | **−$7,197.80 (−5.2 %)** |
| mean clip | $15.25 | $14.45 | −$0.80 |
| $18 sweet-spot bucket | 6,520 legs | 5,801 legs | −719 |

Leg-level: **1,738 down / 632 up / 6,673 unchanged**. The 719 legs leaving the $18 bucket are the ones a
high wallet score was lifting over the 70 floor: they are still admitted (admission keeps the full
composite) but now size on the base curve at ≈$8 instead of $18.

Why removing the term lowers size at all: on this population the wallet score averages **79.04** against
**73.37** for the other components combined, so deleting it removes a **+5.67 pt** lift from most legs.

---

## 3. What shipped

- `src/lib/rules.ts` — new field **`walletQualityInSize`**, **default 1** (legacy). The revert lives in
  the default, so any ruleset lacking the field keeps historical behaviour.
- `src/lib/scoring/trade.ts` — `sizeScore = (copyScore − wallet×0.30) / 0.70` when the flag is 0;
  `sizeConfidence` re-derived from it; bucket and base curve read those. **`copyScore` is untouched**, so
  every admission floor, the confidence gate and the long-shot relaxation still see wallet quality.
  Additive adjustments survive because they ride in `copyScore` and only the wallet term is subtracted.
- `scripts/apply-v65.ts` — dry-run default, `--apply`; reads the field back and throws if activation
  didn't take.
- `scripts/verify-v65-wallet-size.ts` — enforcement probe through the **real scorer** on the **live**
  ruleset. Result: `copyScore` identical at 72.4 and 87.4 across both flag values (admission untouched),
  and wallet score no longer widens the size gap.
- `tests/wallet-quality-in-size.test.ts` — 4 tests; the first pins `DEFAULT_RULES.walletQualityInSize === 1`
  because a default of anything else would silently change every historical and replay ruleset at once.

**Verified:** `tsc -p tsconfig.json --noEmit` clean · **504/504** tests · RuleSet **v65** active,
`walletQualityInSize=0` read back from the active row · audit row `hermes-v65-wallet-admission-only`.

**Revert — one field:** set `walletQualityInSize` back to **1** on the active RuleSet row. The code
default is already 1.

---

## 4. The caveat that must travel with this

The pre-registered trigger required **≥30 overlapping wallets**; there are **16**. This shipped on the
user's explicit approval with the gate **unmet**. The refutation condition stands and is the reason to
revert: at ≥30 wallets, an H1→H2 correlation above **+0.30** means wallet selection is real and the band
thesis is incomplete.

---

## 5. The finding that matters more than the change

**STANDARD has almost no size gradient to begin with.** Under v64, `sweetSpotSizeUsd = highScoreCapUsd =
18` and `minCopyScore = 70`, so every admitted leg is sized **$18.00 flat** — which is exactly why the
self-audit found all 58 recent STANDARD trades at precisely $18.00. Wallet-in-size could only move legs in
two narrow places: those a high wallet score lifts over 70, and the long-shot band admitted on the relaxed
floor below 70.

So the leverage is not "which component sets size" — it is that **the size path is flat** over a score
range that spans 70–100. A 0.30-weight component can only change size where the bucket boundaries are, and
those boundaries are effectively one line at 70.
