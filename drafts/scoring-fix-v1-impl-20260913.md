# Scoring fix v1 — implementation + pre-registered evaluation (executed 2026-09-13)

**Follow-on to:** `drafts/scoring-fix-methods-20260913.md` (research + ranked shortlist).
**Verdict: v1 price-edge spec FAILS its own pre-registered acceptance test → shadow only, nothing wired.**
**Live behaviour changed: NONE.** `src/lib/scoring/trade.ts` is untouched; no rules, DB schema, or
paper-accounting code was modified; nothing was committed.

---

## 1. What was built

| artifact | purpose |
|---|---|
| `scripts/build-decision-dataset.py` | Builds the labeled decision dataset from the resolved book (read-only). Emits `data/decision-dataset.csv` + `.manifest.json`. |
| `data/decision-dataset.csv` | 3,481 decision rows × 37 columns: entry price, size, raw spread/liquidity/TTR/volume from the latest pre-decision `MarketSnapshot`, all stored component scores, rule-set version, wallet, market, `y_win`, gross and fee-adjusted PnL. |
| `scripts/fit-price-edge.py` | Fits M1/M2/M3 under two fold designs, selects a margin inside each fold, runs the pre-registered acceptance test, emits the portable spec. |
| `data/score-spec-v1.json` | The spec of record: model, parameters, decision rule, margin, measured metrics, acceptance result, deployment status. |
| `data/score-spec-v1-eval.json` | Full evaluation detail (all models × both designs, per-fold rows, margins). |
| `src/lib/scoring/price-edge.ts` | Pure, dependency-free TS implementation: `priceEdgeProbability`, `takerFeePerShare`, `categoryFeeRate`, `priceEdge`. Status `shadow`; **not called from any live path**. |
| `tests/price-edge.test.ts` | 16 tests: reference values from the fit, monotonicity, (0,1) range, null on bad input, fee formula, and **spec-integrity tests that assert the TS constants still equal `data/score-spec-v1.json` and that the spec is still marked FAIL/shadow**. |

Verification: `npm test` **163/163 pass** (13 files, incl. the new 16), `npx tsc --noEmit` clean.

### Correction to the research doc's data inventory

The 9,642 "resolved copies" are **trade rows**, not decisions. Collapsing the documented duplicate
accumulation rows (one position re-opened repeatedly) gives:

- 9,735 raw rows → **3,516 decisions** (6,219 duplicate rows dropped, 64% of the book), then
  **3,481** after excluding the 35 Kalshi rows (phantom-price leg).
- 188 wallets, 2,569 markets, 2026-07-15 → 2026-09-12, win rate 0.5797.
- Fee-adjusted economics per trade: gross **+$0.304**, after the entry-leg taker fee **+$0.085**,
  after both legs **+$0.048**. The cost model removes 72–84% of gross — consistent with the
  standalone fee audit (`drafts/c200-taker-fee-measurement-2026-09-09.md`).

So the *decision*-level effective sample is smaller than the row count suggests; the qualitative
recommendation (label the book, not just the 688-row review table) stands, with the corrected numbers.

---

## 2. The pre-registered test (frozen before looking at results)

- **Models.** M1 `P(win)=σ(a+b·logit(price))` (2 params) · M2 12-band Laplace-smoothed table · M3
  logistic on logit(price)+log(size)+spread+log1p(liquidity)+log1p(TTR).
- **Fold designs (both required; random row-level folds banned).**
  `W` wallet-blocked: 5 folds by wallet hash; coefficients *and* margin fit on the other wallets only.
  `T` walk-forward: fit on strictly earlier months, evaluate on the next (July→August, July+Aug→Sept).
- **Decision rule.** admit iff `P(win) − price − fee_per_share(price) > margin`, with
  `fee_per_share = rate·price·(1−price)` (Polymarket taker formula). Margin chosen on **fit rows
  only**, requiring ≥10% admitted (a margin that admits nothing is not selectable). Final reportable
  margin = median of the per-fold choices.
- **Primary metric.** Fee-adjusted **net $/trade on the admitted subset** vs the same fold's ungated
  mean. Secondary: AUC, Brier (vs base-rate Brier), calibration slope/intercept, share admitted,
  per-bot split.
- **Acceptance (all four).** A1 gate beats ungated on **both** designs · A2 wallet-cluster bootstrap
  95% CI of the improvement excludes 0 · A3 ≥60% of wallets non-negative on admitted trades ·
  A4 calibration slope in [0.8, 1.2].

---

## 3. Results (3,481 decisions, ungated net **+$0.0745/trade**)

**Wallet-blocked** (generalising to unseen wallets):

| model | AUC | Brier | calib slope | admitted | net $/trade | vs ungated |
|---|---|---|---|---|---|---|
| M1 logit-price **(chosen)** | 0.736 | 0.2027 | 0.96 | 16.2% (564) | **+$1.30** | **+$1.23** |
| M2 band table | 0.727 | 0.2035 | 1.10 | 16.4% | +$0.98 | +$0.91 |
| M3 price+execution | 0.734 | 0.2034 | 0.98 | 17.2% | +$1.93 | +$1.86 |

**Walk-forward** (the design that mimics deployment — fit on the past, trade the next month):

| model | AUC | Brier | calib slope | admitted | net $/trade | vs ungated |
|---|---|---|---|---|---|---|
| M1 logit-price **(chosen)** | 0.696 | 0.2195 | 1.40 | 46.6% | **−$0.12** | **−$0.18** |
| M2 band table | 0.670 | 0.2259 | 0.94 | 43.9% | +$0.25 | +$0.19 |
| M3 price+execution | 0.688 | 0.2217 | 1.32 | 49.0% | +$0.75 | +$0.69 |

**Acceptance (chosen M1, margin 0.05):**

| design | improvement | wallet-cluster CI | A1 | A2 | A3 (wallets ≥0) | A4 (slope) |
|---|---|---|---|---|---|---|
| wallet-blocked | +$1.2288 | **[−0.5399, +2.6224]** | ✅ | ❌ | ❌ 0.39 | ✅ 0.96 |
| walk-forward | −$0.1780 | [−1.3060, +0.5597] | ❌ | ❌ | ❌ 0.287 | ❌ 1.40 |

**Result: FAIL.** Not deployable. `data/score-spec-v1.json` records `status: "SHADOW ONLY"` and
`deployment: do not gate on this score`.

**Per-bot view (wallet-blocked selection, for context only — it does not change the verdict):**
BANKROLL_200 (the live C-200 lane) n=864, ungated **+$0.55/trade** → gated **+$2.57/trade** on 172
selected; STANDARD n=2,617, ungated **−$0.08** → gated **+$0.75**. The lane that matters most shows
the strongest signal, but it is drawn from the same 188 wallets that fail A2/A3, so it is a lead to
re-test under the v2 design, not evidence.

---

## 4. What the failure actually says (and what is still good)

**Good, and now measured on 3,481 decisions:**
- Ranking is real and duplicates the earlier finding: price-only AUC **0.736** wallet-blocked /
  **0.696** walk-forward, with calibration slope 0.96 / 1.40 — versus the incumbent composite's 0.417
  on the row-level book. The market's own price is the only feature that carries signal; M3's extra
  execution features did not improve AUC (0.734 ≤ 0.736).
- The gate *direction* is right: admitted trades show positive excess return (+0.074 wallet-blocked).

**Why it still fails:**
1. **Not wallet-robust.** Only 39% of wallets are non-negative on admitted trades, and the
   per-fold spread is violent: fold 0 +$4.92/trade on 26 trades, fold 1 −$0.25/trade on 79. The
   pooled +$1.23 is a few wallets' luck, and the cluster CI admits zero.
2. **Margin selection does not transfer.** Margins chosen by maximising fit-sample $/trade came out
   at 0.05 (wallet folds) but ~0.005–0.02 (time folds), admitting 46% of decisions instead of 16%.
   A high-variance objective on a heavy-tailed payoff selects noise; `choose_margin` is a v1 design
   flaw, not a property of the market.
3. **The improvement is not distinguishable from zero.** On the deduped decision set, per-trade sd
   (net) is **$14.01** with ICC(wallet) = **0.093** (design effect 2.64, effective N ≈ **1,321**), so
   the MDE is ≈**$1.08/trade**. The measured wallet-blocked improvement, +$1.23/trade, is around that
   size — and its own cluster CI [−0.54, +2.62] (SE ≈ $0.81, t ≈ 1.5) spans zero, which is the
   honest statement: *a point estimate near the detection floor with a confidence interval covering
   no-effect*. Note the row-level book (before collapsing duplicates) overstated the clustering:
   ICC(wallet) 0.225 and effective N 784 there, versus 0.093 / 1,321 for decisions.
4. **Regime drift is visible in the folds.** The walk-forward blocks cross rule-set versions 2–52;
   the mapping that ranks well in-sample loses its calibration (slope 1.40) out of sample. Any v2
   must control for rule-set version and refuse to pool across changes.

---

## 5. v2 design (concrete, before any further fitting)

1. **Do not optimise the margin.** Set it a priori: `margin = fee + min_edge` with `min_edge` fixed
   in the spec (e.g. 0.02) and never tuned on outcome data. Report the fixed-margin performance.
2. **Score against a paired, cluster-robust test** per fold (wallet-clustered differences), and make
   the **share of wallets non-negative** a gate criterion with ≥0.60 — the criterion that failed here
   is the one that matters for a panel of wallets.
3. **Objective: excess return with explicit sizing, not binary admission.** The measured lesson is
   that admission thresholds trade $/trade against excess; a fractional-Kelly size on
   `edge = P(win) − price − fee` uses the same calibration without a cliff.
4. **Stratify by rule-set version** and fit only on data from the current version family; keep the
   version as a covariate so a regime change shows up as a coefficient shift, not silent drift.
5. **Add decision-time raw features to the models** now that the dataset carries them (spread,
   liquidity, TTR) with a pre-specified prior that they are second-order: M3 vs M1 here gives no
   evidence they matter, so v2 must show a gain beyond the noise floor to keep them.
6. **Accrue before re-testing.** At the current effective N, nothing below ~$2/trade is detectable.
   Pre-register checkpoints every +500 decisions with always-valid intervals instead of re-fitting
   whenever the number moves.

---

## 6. Shadow plan (what happens next, unchanged live behaviour)

1. `priceEdge(price)` is available to log a shadow score and a counterfactual admit decision for
   every new scored signal. Wiring it into `score-trades.ts` is a **separate, approved step** and is
   deliberately not done here; if it is wired, it must write a shadow column only, behind a flag,
   with `status: "shadow"` asserted in the emitted record.
2. Nothing routes, sizes, or gates on `priceEdge` until A1–A4 pass on the frozen holdout with the v2
   design above. The test `tests/price-edge.test.ts` asserts the shipped spec is still `FAIL`/shadow,
   so an accidental promotion fails CI.
3. The daily report may show the shadow score's distribution and the counterfactual admission set;
   it must not claim an edge until the pre-registered criteria pass.

---

## 7. Reproduce

```bash
./venv-calib/bin/python scripts/build-decision-dataset.py      # labels + features (read-only DB)
./venv-calib/bin/python scripts/fit-price-edge.py              # fit + pre-registered evaluation
npx vitest run tests/price-edge.test.ts                        # 16 tests
npm test && npx tsc --noEmit                                   # 163 tests, clean typecheck
```

Artifacts: `data/decision-dataset.csv`, `data/decision-dataset.manifest.json`,
`data/score-spec-v1.json`, `data/score-spec-v1-eval.json`.

**Known limits.** The dataset's raw execution features come from the latest `MarketSnapshot` at or
before the decision (no post-decision data); 1 of 3,516 rows has no prior snapshot. Category fee rates
are inferred from question text because `MarketSnapshot.category` is NULL. Margins and λ-style
tunables are the v1 procedure's; exit-leg fees are an all-taker upper bound (`status='closed'` only).
The walk-forward design covers months 08–09 only (July is the burn-in fit block), so its metrics are
computed on the covered rows and its ungated baseline differs from the wallet-blocked one.
