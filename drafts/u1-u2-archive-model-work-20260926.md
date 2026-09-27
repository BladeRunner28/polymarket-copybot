# U1 + U2 — the archive → ML workstream, first instruments and first readings (2026-09-26)

**Status:** measurement + offline model only. No rule, size, gate, routing or booked figure moves; no live
path is touched. Approved work: `Recommendation approved` on `drafts/archive-ml-bridge-20260926.md` §8
option 1 (**U1 + U2 now, U3/U4 carded behind the engine**). Cards:
`ml-u1-conditional-fill-model`, `ml-u2-wallet-feature-priors` (both In Progress).

**Why these two first** (from the bridge brief): U2 stops us spending our scarce 3,966 labels on a question
the archive has already answered; U1 is the only item that changes what the model can *learn*, because the
model's target is net-of-fee per-leg PnL and its largest unresolved term is whether the maker entry filled
at all (the 2¢ credit is **75.7% of settled C-200 PnL**).

---

## U2 — wallet-side feature priors: **veto, not selector**

**Instruments (read-only):** `scripts/wallet-feature-priors.py` → `data/wallet-feature-priors.json`;
archive side `scripts/archive-wallet-*.py` (archive venv) → `data/archive-analysis/archive-wallet-*.json`
(+ `archive-wallet-inputs.manifest.json`). Reproduce in 30 s.

**Populations.** Three, and they answer different questions:

| population | n | what it can say |
|---|---|---|
| our **acted** book (`data/decision-dataset.csv`) | 3,516 legs / 2,576 markets / 188 wallets, 2026-07-15→09-12 | which of **our own picks** were good — selection-biased by construction |
| our **skip** set (`data/skip-edge-probe-20260916.json`) | 77,353 counterfactually-labelled decisions | ranking on rows the policy never acted on (exit-blind, in-sample) |
| the **archive** (Polymarket-v1) | 1.2B fills, 2022-12→2026-04, 3,273 of our wallets | does wallet skill persist at all, on 3.4 years of pre-era history |

**Result 1 — nothing on the wallet side beats price, and most of it is inverted.** Acted book, target =
leg won, 95% CI from a 1,000-rep **market-clustered** bootstrap (`cluster=market_id`, seed 20260926):

| feature | AUC | 95% CI | verdict |
|---|---|---|---|
| entry price (BASELINE) | **0.735** | 0.714 – 0.755 | the bar |
| entry timing | 0.570 | 0.550 – 0.592 | PRICE-PROXY (3/5 price quintiles) |
| spread score | 0.536 | 0.516 – 0.558 | PRICE-PROXY (3/5) |
| time to resolution | 0.535 | 0.510 – 0.559 | PRICE-PROXY (2/5) |
| wallet's own size | 0.491 | 0.467 – 0.514 | KILL (CI includes 0.5) |
| liquidity score | 0.480 | 0.466 – 0.494 | VETO-CANDIDATE |
| raw spread | 0.474 | 0.455 – 0.494 | VETO-CANDIDATE |
| category fit | 0.452 | 0.433 – 0.474 | VETO-CANDIDATE |
| our stake | 0.445 | 0.425 – 0.465 | VETO-CANDIDATE |
| confidence | 0.438 | 0.416 – 0.461 | VETO-CANDIDATE |
| wallet quality | **0.420** | 0.399 – 0.444 | VETO-CANDIDATE |
| **composite copyScore** | **0.418** | 0.397 – 0.441 | VETO-CANDIDATE |
| thesis | **0.370** | 0.348 – 0.394 | VETO-CANDIDATE |

*VETO-CANDIDATE* = the CI sits **entirely below 0.5**: the high end of the feature is the **bad** end. It is
usable as a veto against its top tercile and **never** as a selector. Power: median CI half-width **0.022**,
i.e. an AUC of ≈0.522 is detectable here — so the KILL verdicts are nulls, not underpowered nulls.

**Result 2 — the inversion is era-dependent, and that matters.** The composite is *policy output* and its
semantics moved across `ruleSetVersion`s, so the pooled number can hide a regime flip. Stratified:

| stratum | n | entry price | copyScore | wallet quality | entry timing |
|---|---|---|---|---|---|
| STANDARD \| pre-Kelly (v1–48) | 2,537 | 0.761 | **0.382** | 0.397 | 0.587 |
| BANKROLL_200 \| pre-Kelly (v1–48) | 673 | 0.668 | 0.451 | 0.523 | 0.483 |
| BANKROLL_200 \| Kelly window (v49–57) | 226 | 0.628 | **0.503** | 0.485 | 0.540 |

So the headline inversion is **carried by the retired STANDARD era**; in the live C-200 Kelly-window slice
copyScore is **at chance (0.503, n=226)** and price itself is weak (0.628). Both readings agree on the
operational question — *not a selector* — but they disagree on *"the score is anti-predictive"*, which is an
era story, not a live one. Anyone quoting 0.418 as "the live score runs backwards" is over-reading it.

**Result 3 — the archive's 3.4-year answer, on the complete wallet list.** Half-vs-half persistence,
1.2B fills, 3,273 wallets (this supersedes the truncated-list pass — see the bridge brief's correction note):

- r **0.144** all buys (920 wallets) · **0.206** taker buys (438) · **0.240** taker, band-neutral (376);
- **worst decile stays worst** (−16.3% → −5.1%) while the **best decile flips negative in every variant**
  (+14.1% → −1.3%);
- the average wallet is **fair-priced**: +0.02% excess on 3.2M aggressive buys (51.82% win vs 51.81% mean price).

**Verdict (U2).** Wallet skill enters ML-1 as a **veto** — exclude the bottom tercile and nothing more.
Promotion to a selector requires **≥200 of our own forward legs** where top-tercile selection beats
price-only with a market-clustered CI excluding zero. The archive says it will not: skill persists at the
bottom and decays to zero-or-negative at the top, on a sample three orders of magnitude larger than ours.
**Labels saved: the whole "which wallet feature picks winners" search**, which the archive has now answered
null with a veto-shaped caveat.

---

## U1 — conditional maker-fill model

### What was already known (do not re-derive)

From `drafts/fee-maker-calibration-20260925.md` §5–6: at δ=0.02 a bid 2¢ inside is touched **71.1% @5m /
76.1% @30m / 77.6% @1h** (783M fills, 2026-01…04), **74.3% / 81.1%** weighted to C-200's own entry prices —
*and* those fills are adversely selected (−0.0296 pts at 1h in band 0.4–0.5), while the ~20% we miss are the
up-moves (+0.2354). A fill model that books the 2¢ without the selection is booking the upside only.

### The instrument

`scripts/archive-fill-hazard-conditional.py` (archive venv, duckdb only — the venv has **no numpy/pandas**;
the fit lives in `scripts/fit-fill-model.py` under `venv-calib`). It keeps the **conditioning** the flat
number throws away: per print it records the tape's minimum at ≤5m/30m/1h, the last print at each horizon
(markout), prior-hour volatility and fill count, trade size, time-to-resolution, aggressor side, category and
ET hour — aggregated to **one row per feature cell** (not per fill: 6.6M fills/shard-minute is not a fit set).

**Sharding is mandatory, and it was validated rather than assumed.** A whole-file window over a monthly
partition is OOM-killed with an EMPTY log (which reads as "never ran"), so the pass runs
`hash(token_asset_id) % 20` with a 14 GB memory limit. Validation on one unsharded month is queued as the
same instrument with `--validate-month`; the sharded single-month run already reproduces the published flat
rates and band profile on 9.69M fills (1/20 of 2026-04):

| quantity | this instrument | published |
|---|---|---|
| P(≤ p−0.02) @5m | **69.2%** | 71.1% |
| P(≤ p−0.02) @30m | **74.6%** | 76.1% |
| P(≤ p−0.02) @1h | **76.2%** | 77.6% |
| band 0 / 4 / 5 / 9 (1h) | 49.8 / 85.1 / 82.2 / 49.8% | 45.9 / 86.7 / 84.5 / 48.8% |

Differences are explained and small: the price window is [0.02, 0.98], the horizon frame is
`RANGE BETWEEN 1 FOLLOWING AND h FOLLOWING` (same-second batched prints excluded), and the shard is 1/20 of
one month.

**Adverse selection reproduces independently, and gains a conditional shape** (same shard, δ=0.02):

| arm | @5m | @1h |
|---|---|---|
| filled | **−0.0403** pts | **−0.0413** pts |
| missed | +0.0916 pts | +0.1316 pts |

By band at 1h, the filled arm's drift is monotone in price — **−0.001 (band 0) → −0.001 (0.0–0.1) …
−0.048 (0.4–0.5) · −0.053 (0.5–0.6) · −0.062 (0.8–0.9)** — while the missed arm's upside peaks mid-book
(+0.25–0.28 in bands 3–5). The 2¢ is cheapest exactly where we trade most, and most expensive in the
favourite bands. Same signs as the published table (−0.0296 / −0.0350 filled; +0.2354 / +0.2088 missed),
slightly larger in magnitude on this population.

### The fit and the gate

`scripts/fit-fill-model.py` fits a weighted logistic model on the cells
(`p(fill | band, band², hour bucket, size, prior-hour volatility, prior-hour activity, TTR bucket, aggressor
side, category)`), with three baselines printed on the same holdout: **flat** (one number), **band-flat**
(per-price-band — the honest bar, since price explains most of it) and **C-200-weighted** (band-flat
re-weighted onto our own settled entry-price mix, which is how 74.3% was derived). Holdout = deterministic
hash split of cells (70/30), labelled a **weak** check: the real test is the card's forward gate, ≥50
measured C-200 legs with an L2/tape-anchored level check, which is time-ordered by construction.

> **RESULT — filled in below after the full 4-month scan (see §Results).**

### Anchor discipline — the part that decides whether any of this transfers

The archive's rate is anchored on a **PRINT** at `p`. Our intent price is the **detection mid**
(`ObservedTrade.detectedPrice`), so `intent − 2¢` sits ~1.5¢ **through** the prevailing best bid — a deeper,
different event. The archive cannot resolve that (no quotes, no depth, no cancellations), which is why the
forward arm must read reachability `best_ask <= L` on **our** token from `data/l2/`, with
coverage-missing legs excluded rather than scored as negatives, and must state the anchor beside every rate.
First live read stands at **0/6 reachable on our own book, 0/3 on the public tape** (`takerOnly=false`) —
against 74.3%/81.1% here. Either the anchor gap is much larger than estimated, or those 6 legs are simply
too few: that is exactly what the ≥50-leg gate exists to settle, and the intent watcher keeps accumulating
(26 legs stamped as of this run, up from 8).

---

## Results

*← U1 fit results appended here once the 20-shard scan completes; nothing above changes on their account.*

## Follow-ups this creates

- **U1 forward arm**: keep `FillIntent`/`PaperTrade.intentPrice` accumulating; at ≥50 legs, run
  `scripts/fill-vs-intent.ts` and `scripts/c200-printthrough.py` and read the gate. Simulator-only even then.
- **U3/U4** (price-only baseline surfacing; era/drift machinery) stay carded behind the backtest engine's
  conventions — building them first produces a second, divergent evaluation stack.
- **Labels saved by U2** are the deliverable: the "which wallet feature picks winners" search is closed as
  a selector and open only as a bottom-tercile veto.
