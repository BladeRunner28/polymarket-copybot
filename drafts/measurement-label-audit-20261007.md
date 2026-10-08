# Measurement-label audit — every arm's TARGET basis

**Source:** kanban card `t_1a96fb7a` on board `medusa` (read-only worker, no writes)
**Date:** 2026-10-07 · run 1 · ~3 min · workspace `dir:~/polymarket-copybot`
**Roadmap card:** `measurement-label-integrity`

**Headline:** 28 in-band + 11 out-of-band measurement arms tabled. **5 declared-vs-implemented
mismatches** and **3 MARK-not-settled flags**. All five shadow lanes and `OutcomeReview.finalOutcome`
are clean on `didOutcomeWin`.

**Independent re-run:** `scripts/label-basis-audit.py` reproduces the finding —
label disagreement **401/5204 = 7.7%**; C-200 all-finished `wr 0.484 / Brier 0.2373 / AUC 0.6508`
vs `resolvedAt`-only `0.626 / 0.2067 / 0.7427`.

**Most consequential (needs your decision, not a worker's):**
1. `src/lib/benchmarks.ts:63,69` — the bot-vs-blind comparison mixes bases: bot arm is EXIT
   (`realizedPnl`), blind arm is OUTCOME (hold-to-resolution). The headline comparison is not
   apples-to-apples.
2. `src/lib/rule-updater.ts:28-46,106-112` — `minCopyScore` is **gated on an exit-contaminated win
   rate**. This is a rule input, so it is an override-class item, not a measurement tidbit.

---

## Verbatim worker report (card comment)

## AUDIT — every arm's TARGET basis (read-only, no writes)

Scope: the EOD read (`~/.hermes/scripts/copybot-eod.sh`, cron `copybot-eod` 22:00 → `logs/cron/copybot-eod.log`) and the daily read (`copybot-c200-daily-report` 18:00, `kelly-window-report` 18:45, `kalshi-shadow-report` 18:30, `capital-report` 18:50), plus the five hourly shadow markers whose summaries the EOD consumes.

Basis vocabulary: **OUTCOME** = did the held token win (`didOutcomeWin`) · **EXIT** = our own `realizedPnl > 0` (exit policy) · **MARK** = a price/unrealized value, not a settled outcome · **n/a** = no target (counts, coverage, cost).

### Table: arm → declared basis → implemented basis → file:line → agreement

| arm (where it prints) | declared basis | implemented basis | file:line | agree |
|---|---|---|---|---|
| EOD "PnL Today" (both lanes) | realized PnL | `SUM(realizedPnl)` over `closed\|resolved`, bucketed `closedAt ?? resolvedAt` | `src/lib/report.ts:165,173` | YES |
| EOD "Total PnL" / "Current Net Worth" | total PnL | settled realized **+ open `unrealizedPnl`** (a MARK) | `src/lib/report.ts:166-168,174-176,186` | PARTIAL (mark inside a settled-looking total) |
| EOD "Win Rate" (STANDARD & C-200) | "Win Rate" | share of `realizedPnl > 0` over **all finished** legs (exit policy) | `src/lib/report.ts:169-171,177-179` | NAME-ONLY ("Win Rate" = exit win rate, not market outcome) |
| EOD "Bot vs blind copy" + `beatBlind` | bot vs blind copying (one comparison) | bot arm = copies' `realizedPnl` (**EXIT**); blind arm = `computePnl(finalOutcome==outcome)` hold-to-resolution (**OUTCOME**) | `src/lib/benchmarks.ts:63,69`; consumed `src/lib/report.ts:245,290` | **NO — mixed bases in one comparison** |
| EOD "Net of legacy duplicate stacks" | PnL | `realizedPnl` (exit) | `src/lib/report.ts:221-223,274` | YES |
| EOD "Edge vs cost of copying" | edge = realized PnL % of notional (settled legs); copy cost / drag = MARK vs wallet fill | exactly that; mark terms explicitly labelled LOWER BOUND; `makerCreditUsd` a named assumption | `src/lib/copy-cost.ts:226-266,317-367` | YES (documented marks) |
| EOD "Drift gate counterfactual" + decay bar | gate counterfactual edge | would-have rows marked to settlement via `didOutcomeWin` → **OUTCOME**; `(v−entry)/entry` | `src/lib/shadow-drift.ts:131-172`; marker `scripts/mark-shadow-longshot.ts:130-159`; read `src/lib/report.ts:44-61` | YES |
| EOD "Wallet scan" line | — (coverage) | profiled count + partial count | `src/lib/report.ts:72-98` | n/a |
| EOD `review:outcomes` → `OutcomeReview.finalOutcome` | "check whether the market resolved" | venue winning token label (`CLOB tokens[].winner` / adapter `winningLabel`) → **OUTCOME** | `scripts/review-outcomes.ts:21-38,135-138,173` | YES |
| EOD `review:outcomes` → `wasDecisionGood` / `simulatedPnl` | "record whether the decision was good" | copy rows: `good = simulatedPnl > 0` (**EXIT**); `simulatedPnl` **MIXES** the leg's `realizedPnl` (exit MARK) with a hold-to-resolution counterfactual in the same column | `scripts/review-outcomes.ts:145-148,150-178` | **NO — exit label + mixed column** |
| EOD `export:training` → `training_data.csv.was_good` | "their final outcomes (wasDecisionGood)" | copies = exit PnL sign; watchlist/skip = outcome → **MIXED label in one file** | `scripts/export-training-data.ts:36-67` | **NO — mixed** |
| EOD `analyze-calibration.py` (also 18:00 C-200 report, dashboard Performance) | `excess_return (win_rate − mean entry price)` — a probability/calibration metric | `won = pnl > 0` over `closed\|resolved` (**EXIT**); z/p on that | `scripts/analyze-calibration.py:104-112,129-131` (won at `:130`) | **NO — declared metric is outcome-based, implemented on the exit label** |
| EOD `score:insiders` → `winRate`/`brier`/`marketSelectionEdge` | "win_rate", "brier" (probability metrics) | `won = (realizedPnl ?? 0) > 0` (**EXIT**), population `closed\|resolved` | `src/lib/insider.ts:95,99-103,107-111` | **NO** |
| EOD `wallet-status-split.ts` | realized PnL by current wallet status (as-of-print) | `realizedPnl` over `closed\|resolved`, snapshot marked as such | `scripts/wallet-status-split.ts:32-41,59-64` | YES |
| EOD `edge-copy-cost.ts` | re-runnable twin of the EOD edge/cost block | same code path | `scripts/edge-copy-cost.ts:60-91` | YES |
| EOD `event-family-concentration.ts` | open-book cost concentration by family/wallet | cost MARKS only, no outcome label | `scripts/event-family-concentration.ts:49-51,79-115` | n/a (MARK by design, declared) |
| EOD `update:rules` → `rule-updater.ts` | "avg PnL" / "win rate" | `realizedPnl` over `closed\|resolved` (v52 widened population) | `src/lib/rule-updater.ts:28-46,106-112` | YES as a PnL arm — but it **GATES** `minCopyScore` on an exit-contaminated win rate |
| 18:00 `query_bankroll.js` (phase streak) | realized PnL; T+0 provisional vs settled T+3 | exactly that, convention printed | `query_bankroll.js:81-104,127-144,284-296` | YES |
| 18:45 `kelly-window-report.ts` | realized PnL / band realized | `realizedPnl` per band, `closed\|resolved` | `scripts/kelly-window-report.ts:65,80,133-134` | YES |
| 18:50 `capital-deposits-report.ts` | total capital = principal + realized + open MTM | exactly that, mark declared | `scripts/capital-deposits-report.ts:59`; `src/lib/capital.ts:158-171` | YES (mark declared) |
| 18:30 `kalshi-shadow.py` | counterfactual ledger priced at the Polymarket reference (not a venue P&L) | `win_rate_pct = pnl > 0` on settled rows | `scripts/kalshi-shadow.py:1-18,143-156` | YES as declared (EXIT label) |
| `kalshi-venue-shadow.ts` | "win/loss is derived from realizedPnl sign … both legs approximate" | `won = realizedPnl > 0`, legs re-priced | `scripts/kalshi-venue-shadow.ts:222-233,280` | YES (approximation declared) |
| weekly `odds-gaps.py` / `manifold-gaps.py` / `gaps-digest.py` | cross-venue probability gaps (SHADOW ONLY) | MARK comparisons; no outcome label | `scripts/odds-gaps.py:1-18`, `manifold-gaps.py:1-18`, `gaps-digest.py:1-12` | n/a (MARK by design) |
| hourly `mark-shadow-longshot.ts` → admitted book | admits marked to settlement | `didOutcomeWin` → OUTCOME, `(v−entry)/entry` | `scripts/mark-shadow-longshot.ts:84-115`; `src/lib/shadow-longshot.ts:138-161` | YES |
| hourly per-wallet-ceiling shadow | ceiling counterfactual | `didOutcomeWin` → OUTCOME | `src/lib/shadow-wallet-cap.ts:120-160` | YES |
| hourly minConfidence shadow | confidence-gate counterfactual | `didOutcomeWin` → OUTCOME | `src/lib/shadow-lowconf.ts:138-186` | YES |
| hourly `mark-shadow-jev.ts` → PRICE/JEV AUC-Brier + gate | "Brier/AUC/log-loss for the PRICE arm and the JEV arm" | label = `v > entry ? 1 : 0` (≡ won while 0<entry<1; pure `won = v===1` exists at :580 but feeds only `pnlPerStake`) | `scripts/mark-shadow-jev.ts:283-311`; `src/lib/shadow-jev.ts:570-620` (label `:583`) | YES (outcome-equivalent; breaks if entry ≥ 1, not filtered) |
| `shadow-forward-read.ts` (pre-registered verdict) | hold-to-settlement counterfactual | resolves from the same `didOutcomeWin` values, `ret=(v−entry)/entry` | `scripts/shadow-forward-read.ts:100-131` | YES |

### Out-of-band arms (not in the daily/EOD read, same defect class — flagged, not fixed)

| arm | declared | implemented | file:line | agree |
|---|---|---|---|---|
| `analyze-band-exit-exemption.ts` | "settlement value: own resolution" | `settlement = (realizedPnl ?? 0) > 0 ? 1 : 0` for `status='resolved'` (**MARK/EXIT presented as settlement**) **and** a raw case-sensitive `m.winningOutcome === t.outcome` compare for closed rows (no `didOutcomeWin`/`normalizeOutcomeLabel`) | `:139-147`, `:154` | **NO** (+ case-sensitive-compare bug class) |
| `rag-vs-price-baseline.py` | label = `resolvedAt IS NOT NULL AND realizedPnl > 0`, survivorship block printed | exactly that (settlement-only + exit label) | `:14-15,38,52` | YES (caveat documented) |
| `pilot-score-separation-papers.py` | "Target: did the copied position make money (realizedPnl > 0)" | `realizedPnl > 0` on resolved\|closed | `:11,49-56,79` | YES (EXIT, declared) |
| `pilot-score-separation.py` | excess = winRate − price (outcome) | `won` from `OutcomeReview.finalOutcome` vs `outcome` (normalised) → OUTCOME | `:107,130,135,472` | YES |
| `analyze-score-separation.py` | "t-stats on the composite" | `win = 1.0 if pnl > 0`; population `closed\|resolved` (right population, exit label) | `:75,94` | declared-as-PnL; EXIT label |
| `wallet-selection-score-information.py` | "AUC on 'leg won'" + cohort caveat | `won = 1 if pnl > 0` | `:132-135,188,205,227,291` | YES (EXIT, declared) |
| `shadow-expectancy-model.py` | settled C-200 copies | `realizedPnl` on `closed\|resolved` | `:37-47` | YES (EXIT) |
| `psmi-regime-measure.py` | local-day `closedAt ?? resolvedAt`, status closed\|resolved | `realizedPnl` | `:16,138-142` | YES |
| `adapters/polymarket.ts` (wallet close-positions → wallet winRate30d/roi30d → copyScore) | resolved position won | `won = (curPrice > 0.5) \|\| (realizedPnl > 0)` — **MARK OR PnL-sign** | `:206-208` | **NO — a MARK decides a wallet's resolved-win flag** |
| `day-pnl.ts` (Overview/day cards) | PnL + day win rate | `wins = pnl > 0`, `residualUnrealized += unrealizedPnl` (MIXED) | `:95-99` | PARTIAL |
| `rule-updater.ts` (in EOD) | avg PnL / win rate | `realizedPnl`, `winRate = pnl>0` | `:40,106` | YES as PnL arm; gates `minCopyScore` on the exit label |

### Flags (summary)

1. **Declared probability metric, implemented on the exit label (EXIT, not OUTCOME):** `analyze-calibration.py` (`:130`) — the only arm whose *declared* definition (`excess_return = win_rate − mean entry price`) is mathematically an outcome label; `src/lib/insider.ts` (`brier`, `winRate`, `marketSelectionEdge`); `src/lib/report.ts` "Win Rate"; `analyze-band-exit-exemption.ts` ("settlement").
2. **Two bases inside one comparison:** the EOD headline `Bot vs blind copy` (`benchmarks.ts:63,69`) compares an exit-policy number against a hold-to-resolution number and drives the "✅ bot beat blind copying" line; `export-training-data.ts` `was_good` mixes exit and outcome labels in one training file; `OutcomeReview.simulatedPnl` mixes an early-exit mark with a hold-to-resolution counterfactual in one column.
3. **MARK, not a settled outcome:** `report.ts` "Total PnL"/"Net Worth" fold open `unrealizedPnl` into a total that reads as settled; `day-pnl.ts` residual unrealized; `adapters/polymarket.ts:207` resolved-win flag; `event-family` + `odds/manifold gaps` + `copy-cost` + `capital` marks (all *declared* as marks → not defects).
4. **Correct (OUTCOME) and already clean:** all five shadow lanes (`longshot`, `drift`, `wallet-cap`, `lowconf`, `jev` label), `OutcomeReview.finalOutcome`, `shadow-forward-read.ts`, `pilot-score-separation.py`. Matches the card's own "WHAT IS ALREADY CLEAN" list — do not "fix".

### Fresh numbers (read-only re-run, 2026-10-07, `python3 scripts/label-basis-audit.py`)

- Populations: 12,484 legs · 11,170 finished · 2,933 `resolvedAt` · 8,237 early exit · 1,314 open · 5,204 with an `OutcomeReview`.
- Label disagreement (PnL sign vs `finalOutcome` on legs carrying both): **401 / 5,204 = 7.7%** (card quoted 371 / 5,037 = 7.4%).
- C-200: all-finished n=2,294 wr 0.484 / Brier 0.2373 / AUC 0.6508 vs `resolvedAt`-only n=721 wr 0.626 / 0.2067 / 0.7427 (+14.2pp wr, +9.2pp AUC). STANDARD: 0.635/0.1947/0.7551 → 0.708/0.1937/0.7756. Early-exit share of finished legs: **73.7%**.

### Card gate check (item 1 of the `gate` field)

Arms that report a probability metric but do **NOT** name their label column in stdout: `analyze-calibration.py` (prints "win%" only), `score-insiders` line (prints `wr=`/`brier=` only), the EOD report's Win Rate, `benchmarks` "bot vs blind copy", `edge-copy-cost`. Arms that DO name it: `rag-vs-price-baseline.py:14-15`, `pilot-score-separation-papers.py:11`, `wallet-selection-score-information.py:291`, `kalshi-venue-shadow.ts:280`, `label-basis-audit.py` header.

Fixes not applied (read-only card). Proposed fix cards, per the card's "fixes become their own cards": (a) name the label basis in each of the 5 stdout arms above; (b) split `benchmarks.ts` into an outcome-basis blind arm vs an outcome-basis bot arm (or print both bases); (c) relabel `insider.ts`/`analyze-calibration.py` metrics as exit-based vs add an outcome-based twin; (d) `analyze-band-exit-exemption.ts` route through `didOutcomeWin` and stop calling a PnL sign "settlement"; (e) `adapters/polymarket.ts:207` drop the mark from the resolved-win flag.

---

*Generated by kanban worker run 1 on board `medusa`; findings only, no fixes applied.*
