# Re-audit — YichengYang-Ethan/oracle3-prediction-market-agent (re-surface check)

**Date:** 2026-11-13 · **Standing audit:** `drafts/oracle3-audit-2026-09-07.md` (2026-09-07, v1.1.2) + `drafts/coinjure-audit-2026-09-09.md` (matcher provenance)
**Revision note:** not a fresh audit. The 2026-09-07 audit is still the primary document and its component verdicts are unchanged except where marked **AMENDED** below. This pass re-checks (a) what moved upstream, (b) what moved in `data/roadmap.json` since, and (c) three modules that did not exist at audit time. No clone, no install, no execution of candidate code — everything below is read off the GitHub API and repo source.
**Licence:** Apache-2.0 for post-2026-02-28 code, **MIT** for the U Lab original and the bundled `coinjure` (NOTICE, 2026-09-27). `grep` over LICENSE: no NonCommercial / CC BY-NC / directory carve-outs — all boilerplate Apache. Borrowable with attribution.

---

## 1. What changed upstream since the audit

| | 2026-09-07 audit | today (API) |
|---|---|---|
| stars / forks | 253 / 33 | **569 / 66** |
| version | v1.1.2 (2026-05-07) | **v1.2.2** (2026-09-30) — v1.2.0/1.2.1 also shipped |
| main activity | dormant 122 d ("treat as frozen") | **30 commits** since 09-07, 7 PRs merged, main at 2026-10-12 |
| development | none | branch `feat/ml-calibration-layer`, **11 commits ahead / 0 behind**, pushed today, CI green |
| tests | 45 files | **60 files / 557 KB** vs 1,416 KB of `oracle3/` source |
| name | oracle3 | renamed `oracle3-prediction-market-agent` (2026-09-28) |

**"Frozen upstream" is no longer true** — that was the standing justification for vendoring `wang_mle.py` once and never re-checking. Re-checked today anyway: **the vendored copy is STILL byte-identical** to upstream (`git hash-object scripts/vendor/oracle3/wang_mle.py` = `af622b29…`, the same blob GitHub reports at `main` and at `v1.2.2`; 21,768 B; zero commits to that path since 09-07). So: no upgrade needed, but the vendor-refresh is now a real cadence item rather than a closed question.

**Unchanged:** `coinjure/matching/` — 1,559 LOC, exactly the Sep-7 count, **0 commits** since 2026-09-07. The matcher the phase-c card proposes to vendor has not drifted.

**CI (reported, not my run):** `pytest.yml` 5/5 `completed/success` on `main` (last 2026-10-12) and 5/5 on `feat/ml-calibration-layer` (last 2026-11-13 06:50). mypy / ruff / codespell / docs / PyPI-publish workflows all active.

## 2. What changed on our side (the only thing that can move a verdict)

- `phase-c` still **Backlog**, its gate (`Kalshi circuit breaker ≥ −$50`) has been clear since 2026-09-05, and the 2026-09-07 AUDIT INPUT asking for the coinjure matcher is still the plan of record.
- **`kalshi-lane-ontology-not-coverage` (new, 2026-09-18) is the card that moves the verdict.** Measured against the complete Kalshi event index (14,766 events): 144 of 202 in-window markets clear 0.25 token overlap (62.9% of stake), **ZERO clear 0.60**, and every sampled 0.40–0.59 candidate is a different market. That does not refute the matcher — it refutes *text-similarity* matching, and it fixes the acceptance test as **precision over verified contract-equivalent pairs, never coverage %**.
- `paper-ledger-fee-fidelity` + `fee-booking-net-ledger` (2026-11-02) — fee work is now live-wired (venue rate preferred, labelled `feeRateSource`), with **coverage** named as the binding gap, not code.
- `ml1-price-baseline-drift` / ML-1 gate: the bar is now **RELATIVE** (`AUC ≥ price-on-the-same-rows + 0.0005 AND Brier ≤ price + 0.0005`, market-clustered CI, frozen boundary 2026-08-21) since commit `815ecda` (2026-10-28).

## 3. New material, verified in source

### 3a. `oracle3/fees.py` (v1.2.0, 2026-09-28) — venue fee schedules
- Kalshi: `round_up(M · k · C · P · (1−P))`, taker k=0.07, maker k=0.0175, `M` = API `fee_multiplier`, rounding increment **$0.0001** (centicent), maker fees only when `fee_type` contains `maker`. Raises `UnsupportedFeeSchedule` on `combo` series / unknown `fee_type` / null multiplier — it **refuses rather than guesses**.
- Polymarket: `C · rate · p · (1−p)`, 5 dp, min 0.00001, makers free; `PolymarketSchedule.from_gamma_market` reads the venue's **`feeSchedule.rate`** and returns 0 on `feesEnabled=false`, raising on undocumented `exponent ≠ 1` or `takerOnly=false`. Category fallbacks: 11 documented rates (crypto .07, sports/economics/culture/weather/other .05, finance/politics/mentions/tech .04, **geopolitics 0.0**).
- **We already have this law.** `src/lib/scoring/price-edge.ts::takerFeePerShare(price, feeRate) = rate·p·(1−p)` is the identical formula, and the venue-truth rate path is wired (`training-export.ts::feeRateTruth` / `feeRateSource`). The gap this card names is **coverage** (40 captured markets vs 3,987 in the export), which oracle3 does not solve: it ships no per-market rate feed.
- The one thing in the file we have never modelled: **Kalshi's `fee_multiplier`** (some series are 0). `scripts/kalshi-maker-read.py` hardcodes `0.07·P·(1−P)` with no multiplier and no centicent round-up. Only Phase C Kalshi legs would consume this — the Kalshi copy lane is retired.
- **Do NOT adopt the category table as a fallback**: our card's gate explicitly requires per-market `feeType` + `feeSchedule.rate` over slug/keyword text. Its `geopolitics → 0.0` and sports `.05` do show our 3-bucket proxy (crypto .07 / politics-fin .04 / default .05, no zero class) is coarser than the documented set — a fact for the proxy's obituary, not a reason to swap it in.

### 3b. `oracle3/arbitrage.py` (v1.2.0) — static no-arbitrage baskets
Math checked line by line, all five relations correct as written:
- `implication (A⇒B)`: NO(A)+YES(B), guaranteed payoff **1** (2 if B without A) ✓
- `exclusivity`: NO on all n, payoff **n−1** ✓ · `complement`: YES both or NO both, payoff **1** ✓
- `same_event`: YES(A)+NO(B) / NO(A)+YES(B), payoff **1** ✓ · `event_sum`: YES all → 1, NO all → n−1 ✓
- `cost = Σ p_i·C`; `gross = payoff·C − cost`; `net = gross − Σ fee_i`, fees from **per-leg venue schedules** ✓. Missing ask is derived from the opposite side's bid (exact for a linked binary book) ✓. Duplicate `(venue, market_id)` refused ✓. `violated` keys on **gross** and `profitable_after_fees` on **net** — the right split.
- Declares its own assumptions in every payload: `relation_verified: false`, `execution_verified: false`, full fill at quote, no partial/legging risk, no cost of capital.
- **Not a missing capability on our side**: `drafts/phase-c-design-notes.md` already specifies these invariants, the post-fee 0.03 floor and both-leg taker fees; `grep` for `basket|exclusivity|implication` over `src/` finds no detector, i.e. unimplemented-by-plan, carded in `phase-c`. What it genuinely gives: a clean reference for the basket-economics record, and a correction to the design notes' prose ("Polymarket taker fee ~0.02–0.03 on CLOB" is the flat approximation the donor's own changelog stopped calling conservative — the venue formula is `rate·p·(1−p)`, max 1.75¢/share at rate .07, and our code already does it).

### 3c. `oracle3/ml/` — calibration benchmark (branch `feat/ml-calibration-layer`, **unmerged**)
The substantive new contribution, and the only part of this repo that speaks to our ML-1 lane. Claim-vs-artifact checked: `evidence/ml_calibration/REPORT.md` and `results.json` agree on sample (964,103 snapshots / 349,297 contracts / 112,401 events), design (5 event-grouped purged walk-forward folds, **24 h embargo**, 3 inner blocks, 1000 event-cluster resamples) and headline numbers.

| method | OOS Brier | vs market |
|---|---|---|
| market price | 0.11851 | — |
| market price + **isotonic** | 0.11406 | **+3.8%** |
| Wang (paper), hierarchical λ | 0.11493 | +3.0% |
| LightGBM | 0.11200 | +5.5% |
| ensemble (logistic stack) | 0.11199 | +5.5% |

**The load-bearing number for us:** price-only isotonic recalibration recovers 0.00445 of the 0.00652 Brier the best model buys — **68% of the apparent ML gain is recalibration, not new information** (ECE 0.0413 → 0.0022 from isotonic alone). Their ablation says the same: price-only features +3.6%, +venue/category +4.0%, all features +5.5%, and *always* applying isotonic raised Brier in 3/3 rows.

Also worth recording: their reliability table shows population-level longshot/mid-range overpricing (0.4–0.5 bin: price 0.466 → resolves 0.318, n=115,010). **That is the opposite direction to our copy-selected cheap band (+9.1pp at 0.0–0.2)** — selection, not contradiction. It must not be used to size anything of ours.

**Not adoptable:** the served bundle (`model_probability` MCP tool) — unmerged branch, LightGBM dump + isotonic map, features require Kalshi spread/volume history we do not collect, and it is a probability estimate by its own docs ("a better-calibrated probability is not by itself a profitable trade"). `taxonomy.py` is a **coarse category map** (venue category → 9 labels), **not** the strike/settlement ontology `kalshi-lane-ontology-not-coverage` needs — do not mistake it for a fix to that card.

**One thing we cannot measure today, and that is itself the finding:** their CV purges events, not markets. Ours clusters by `market_id`. `MarketSnapshot` has **no `eventId`**, and a `SELECT` over all **15,920,338** rows finds **0** whose `rawMarketJson` carries an `events` key — so an event-grouped re-read of our ML-1 gate is not a read-only replay over stored data; it would need capture-side work first. Recorded, not recommended today (see §5).

## 4. Fit table, re-mapped to the CURRENT roadmap

| component | card | verdict |
|---|---|---|
| `coinjure/matching` staged matcher (1,559 LOC, unchanged) | `phase-c` (Backlog; gate met) | ✅ **ADOPT unchanged** — **AMENDED gate**: precision over **verified contract-equivalent pairs**, per `kalshi-lane-ontology-not-coverage`. Template stage must carry the match; text similarity alone is already measured at 0/202 above 0.60 |
| `arbitrage.py` basket economics | `phase-c` | ⚪ concept — invariants already in `drafts/phase-c-design-notes.md`; take the gross/net split + `relation_verified:false` honesty + the per-leg fee object shape. Nothing to vendor into a TS stack |
| `fees.py` schedules | `paper-ledger-fee-fidelity`, `fee-booking-net-ledger` | ⚪ concept — law already identical in our code; **no** capability gap; binding gap stays **coverage** (40 vs 3,987 markets). Carries one never-modelled input: Kalshi `fee_multiplier` + centicent round-up (Phase C legs only) |
| `ml/` calibration benchmark | `ml1-price-baseline-drift`, ML-1 gate (`src/lib/ml1-read.ts`) | ⚪ **concept, and the useful one** — ship the *baseline*, not the model: price + isotonic as the comparator. See REC below |
| `ml/taxonomy.py` | `kalshi-lane-ontology-not-coverage` | ❌ not a fix — 9 coarse categories, no settlement/strike semantics |
| ML bundle / `model_probability` MCP tool | — | ❌ not portable (unmerged, feature-hungry, third-party probability in a live path) |
| `WangMLE` | `calibrate-premium.py` (vendored) | ✅ unchanged, still byte-identical; vendor-refresh now a cadence item |
| agent layer, MCP server, dashboards, Solana/DFlow, `PaperTrader` fills | — | ❌ unchanged from the 2026-09-07 NOT-portable list |

## 5. Recommendation (pre-registered; Lane A — propose only)

```
REC — price+isotonic comparator for the ML-1 gate
  Hypothesis:   an isotonic map fitted on TRAIN legs (price → pnl_net_entry>0) lowers TEST-leg
                Brier by >= 0.002 vs raw price on the frozen 2026-08-21 boundary, i.e. part of
                any measured ML-1 "edge over price" is recalibration.
  Measurement:  read-only replay on data/decision-dataset.csv + training_data.csv at BOUNDARY
                2026-08-21: fit isotonic on train only, score test Brier/AUC for raw price,
                isotonic-price and the stored candidate; report deltas with the existing
                market-clustered bootstrap (scripts/ml1-gate-read.ts harness, no new data).
  Decision rule: if isotonic-price beats raw price by >= 0.002 Brier on the test legs, restate
                BAR in src/lib/ml1-read.ts as candidate-vs-price+isotonic and re-read the gate;
                else record raw price as defended and close the question.
  Cost:         ~1h, read-only, artifact only.
  Reversibility: delete the artifact; BAR is untouched unless the measurement passes.
```
Why this and not the coinjure trial: the matcher adopt is already carded and unchanged, and `phase-c` is unstarted — a trial there would be re-opening a Backlog card. This one is a 1-hour replay that can only sharpen or retire a bar we are about to judge models against, and its doubt comes from a verified out-of-sample result (964k snapshots) rather than from a README.

## 6. What I could not verify (stated, not hidden)

- **No clone, no install, no execution** (this job's read-only constraint): the test suite and the ML benchmark are graded off their **reported** CI state and their own `results.json`, which I did check for internal consistency against the REPORT — I did not re-derive a Brier score.
- `docs/research/fee-frontier.md` and `evidence/runtime-regressions.json` exist (v1.2.0 "reproducible runtime evidence"); neither is load-bearing for any verdict above and neither was adopted.
- The ML branch is **unmerged** — 11 commits ahead, 0 behind, green CI as of today. Anything from it is a lead, not a shipped capability; re-read on merge.

---

## Registry block — ready to paste (NOT applied; this job may not write `data/roadmap.json`)

Append to card **`phase-c`** `note`:

```
AUDIT INPUT (2026-11-13, reaudit; drafts/oracle3-reaudit-20261113.md): re-surface check of the
2026-09-07 audit. Upstream moved (569★ vs 253, main 2026-10-12, v1.2.2, active
feat/ml-calibration-layer branch) — "frozen upstream" is retired, but coinjure/matching is
UNCHANGED (1,559 LOC, 0 commits since 2026-09-07) and the vendored wang_mle.py is STILL
byte-identical (git blob af622b29 at main and v1.2.2). Verdict on the matcher STANDS with one
AMENDMENT driven by kalshi-lane-ontology-not-coverage (2026-09-18): the vendor gate is precision
over VERIFIED contract-equivalent pairs, never coverage %, and the template stage must carry the
match because token/text similarity is already measured at 0/202 above 0.60. NEW, concept-only:
oracle3/fees.py (venue fee schedules — our takerFeePerShare is the identical law; the only
never-modelled input is Kalshi fee_multiplier + centicent round-up) and oracle3/arbitrage.py
(5 relations verified in source; gross-vs-net split + relation_verified:false honesty pattern;
our design notes already specify the invariants, so it is a reference, not a gap).
```
