# Tracked-set churn: the demoted cohort's +4.95pp does not survive going forward

Card: `crowdintel-track-churn-inversion` (Backlog since 2026-11-09). Read-only measurement —
no rule, size, threshold or gate was touched. Instrument:
`python3 scripts/wallet-churn-forward-read.py` → `data/wallet-churn-forward-read.json`.
Served at <http://localhost:3013/drafts/wallet-churn-forward-20261116>.

**Basis for every number below.** Level = one first-print bet (wallet, conditionId, outcome) priced
at the detection price. Truth = the venue's own settlement, from the shared truth caches (32,001
settled markets in the join). Excess = the bet's edge minus its band's leave-one-wallet-out mean,
taken over the WHOLE joined population once, so no window can move by re-meaning its own bands.
Clock = `ObservedTrade.timestamp`, UTC. Population = 523,547 isDemo=0 BUY first-prints over 1,598
wallets. Mean/t/CI are market-clustered (percentile bootstrap over markets); median/trim10/ex10/
top10% are per-bet and are printed beside them for exactly that reason.

---

## 1. The key insight: the card was right about the arithmetic and wrong about what it means

Two separate questions were tangled in one card, and they answer in opposite directions.

**(a) The +4.95pp is real in-sample and does not survive past the read.** The demoted cohort reads
**+4.48pp** (t 3.74, CI [+1.99, +6.73]) on prints made *before* the parent run — the same
population the card measured. Every window that post-dates the read collapses the interval onto
zero: **+1.28pp** (t 0.63) in the ten days after the parent run, **+1.05pp** (t 0.37) after the
demotion itself. The point estimate keeps its sign and loses all of its evidence.

**(b) The score that dropped them cannot see the thing it is dropping on.** Per-wallet own settled
band-excess vs the stored selection scores, over **1,216 wallets with ≥8 joined bets** (21 of them
currently `track`), Spearman ρ reads **−0.012** (`globalScore`), **−0.006** (`roi30d`) and
**−0.038** (`winRate30d`). The card's own family uses ρ ≥ 0.30 as its bar
(`wallet-fdr-audit.py` RHO_BAR); measured |ρ| is 25× below it, and negative. Note `winRate30d` has
been on the SETTLEMENT basis since 2026-11-11, so this is the repaired score too — the defect is not
the mark-vs-settlement basis the card suspected, it is that the score is not a band-excess ranker at
all.

So the demotion was not "wrong because it discarded winners" (a). It was **arbitrary with respect to
the only thing we would want it to rank on** (b) — which is a weaker and much more useful claim,
because it says a replacement would need a new ranking variable rather than a re-tuned threshold.

## 2. Cohort × window

| cohort | window | bets | markets | excess | t | CI95 |
|---|---|---|---|---|---|---|
| demoted (14) | IN (< 2026-10-29) | 1,803 | 1,686 | **+4.48** | 3.74 | [+1.99, +6.73] |
| demoted (14) | F1 (≥ 2026-10-29) | 606 | 505 | +1.28 | 0.63 | [−2.48, +5.45] |
| demoted (14) | F2 (≥ 2026-11-09T18:13Z) | 299 | 254 | +1.05 | 0.37 | [−4.79, +6.43] |
| kept (11) | IN | 813 | 786 | −2.24 | −1.29 | [−5.69, +1.02] |
| kept (11) | F2 | 133 | 126 | −5.02 | −1.24 | [−12.70, +3.01] |
| added (23) | IN | 10,318 | 9,769 | −0.13 | −0.33 | [−0.94, +0.67] |
| added (23) | F1 | 6,667 | 6,441 | +0.90 | 2.14 | [+0.08, +1.71] |
| added (23) | F2 | 1,628 | 1,564 | +0.54 | 0.65 | [−1.11, +2.24] |

The only interval that excludes zero on a forward window is the ADDED cohort (23 wallets the screen
picked up on 2026-11-09): +0.90pp on 6,667 bets. That is the set the current process *chose*, and it
is the same window the wallet-rank shadow already scores — where both candidate arms read TIE
(`data/wallet-rank-shadow.json`, 2026-11-16T11:54Z). Nothing here re-opens that verdict.

## 3. Reality checks before anyone quotes the +1.05

- **Concentration.** F1: median +2.19, 10%-trimmed +1.72, ex-top-10 **+0.50**, with ten bets carrying
  73% of the sum. F2: median **−2.33**, ex-top-10 **−1.11**, and the top ten exceed the entire sum
  (205%) — i.e. the forward "positive" is ten bets against a negative remainder.
- **Breadth.** Only 10 of the 14 demoted wallets printed at all after demotion (7 of them ≥5 bets);
  **4 of those 10** are positive. This is not a cohort that keeps working; it is a cohort that
  mostly stopped printing.
- **Cross-check.** kept + added on the F2 window = **1,761 bets**, exactly the frozen-baseline
  forward population recorded by the shadow at its own last run. The cohort partition reproduces an
  independently-built set, so the split is not an artifact of this instrument.
- **Split provenance.** The 25-wallet parent set is recovered from `track_flags` in
  `data/wallet-fdr-audit.json` and the 34-wallet arm set from `track_snapshot` in
  `data/wallet-rank-shadow-state.json`; the 11/14/23 partition is ASSERTED at run time, so a moving
  artifact fails loudly instead of silently measuring a different cohort.

## 4. Churn did not stop

The card measured one 10-day window. Seven days later: **25** wallets are `track` (34 at arm);
**15 of the frozen 34** are still track; **10 of the parent 25** are still track. The set has
turned over again at roughly the same rate, and it is being turned over by a score that ranks
band-excess at ρ ≈ 0.

## 5. Verdict, and what it does not license

- **Card closed as measured.** The demoted cohort's positive read is an in-sample property of the
  read, not a forward edge; the card's own caveat ("evidence about what the process DISCARDED, not
  a forecast") is now quantified: +4.48pp in, +1.05pp out with a CI five times wider than the point.
- **No Lane A proposal.** Replacing the drop rule with a band-excess ranker is not justified by this
  instrument: the two ranking arms that would replace it are TIE on their own pre-registered forward
  test, and this measurement found no forward-positive cohort to rank *towards*.
- **What does change:** any future card citing "+4.95pp on the demoted cohort" must label it
  in-sample (this draft is the citation), and a future ranking product has to ship the shadow's
  variables, not `globalScore` — the score is a coin on the quantity that matters.

**Refutation.** If the demoted cohort's F2 excess had come back positive with a market-clustered CI
excluding zero on ≥200 forward settled bets, this instrument would have printed FORWARD-POSITIVE and
the finding would be that the loop discards value — a Lane A proposal, never an application.
**Rollback.** `rm data/wallet-churn-forward-read.json scripts/wallet-churn-forward-read.py`; the
read is repro-only, writes nothing else, and touches neither the RuleSet nor the DB (opened `mode=ro`).
