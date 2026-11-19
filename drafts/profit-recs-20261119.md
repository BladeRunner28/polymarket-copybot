# Profit review 2026-11-19 — the cheap tail's edge was a label inversion

http://localhost:3013/drafts/profit-recs-20261119

**Instrument:** `scripts/profit-cheap-ask.py` §9 (extended today) + `data/cheap-token-truth.json` (208 markets, fetched keyless from the CLOB archive). Self-tests **18/18 pass**.
**Basis for every figure below:** level = one refused cheap candidate (0.05 ≤ p < 0.20), deduped to the first sighting per (marketId, outcome), `journal.ruleSetVersion ≥ 68`; entry = the **ask** of the snapshot written in the same sweep as the decision (quote age median 10s); cost = dollars at risk; CIs are market-clustered bootstrap. DB opened `mode=ro`.
**Lane:** Lane B instrument repair + Lane A proposals. Nothing applied: no RuleSet read or write, no prisma write, no apply-v*.ts.

---

## Verdict in one line

**The single best number on the table this morning — the "TTR floor is refusing a +455% cell" reading — is the repo's own token-identity defect, still sitting in the measurement layer: on the token-level basis the same 38 legs return −64.2%, and the cheap-refusal card awaiting approval reads −2.1pp of edge, not +10.8pp, with a post-fix subset at −16.0% ROI.**

Everything below is one instrument, one run, in one commit.

---

## 1. What I measured

`profit-cheap-ask.py` has always tested a win as `outcome_label == venue winner` (§9 added today tests it as *did the token this leg was priced on win*). The two questions are the same on a YES/NO market and different on a named one. Split by label class and by the date of the 2026-11-09 price-side fix (`fbf9073`), 209 resolved rows:

| population | n | label basis | token basis | disagree |
|---|---:|---:|---:|---:|
| ALL resolved | 209 | 23.9% | 11.0% | 29 (13.9%) |
| label YES/NO | 103 | 11.7% | 11.7% | **0** |
| label NAMED | 106 | 35.8% | 10.4% | **29 (27.4%)** |
| pre-2026-11-09 fix | 115 | 34.8% | 11.3% | 29 (25.2%) |
| post-2026-11-09 fix | 94 | 10.6% | 10.6% | **0** |

That the label class is what decides it, and that YES/NO rows agree 103 of 103, is the proof that the token join is sound: a broken join (wrong tokens[] index) would flip the YES/NO rows too. It does not.

**The two arms that were about to become recommendations:**

| arm (ask, dollars at risk) | n | hit | breakeven | edge | ROI | CI |
|---|---:|---:|---:|---:|---:|---|
| TTR floor, label basis | 38 | 52.6% | 13.6% | +39.0pp | **+396.6%** | [+232,+577] |
| TTR floor, token basis | 38 | 5.3% | 13.6% | −8.3pp | **−64.2%** | [−100,−7] |
| whole cheap cohort, label | 209 | 23.9% | 13.1% | +10.8pp | **+112.4%** | [+56,+168] |
| whole cheap cohort, token | 209 | 11.0% | 13.1% | **−2.1pp** | **−6.8%** | [−45,+34] |
| **post-fix cohort (both bases)** | **94** | **10.6%** | **13.6%** | **−2.9pp** | **−16.0%** | [−64,+48] |

## 2. Why

On a two-outcome named market the cheap side is the side the label does not name. When the journal's `outcome` names the *other* side, "label == winner" is not a win test — it is a bet that the expensive side won, and on a longshot sample the expensive side usually does. That is why the inflation appears only where the label is not YES/NO, and why it lands exactly on the band whose thesis is "the cheap tail is mispriced".

29 of the 106 named rows carry it, and **all 29 are pre-2026-11-09**. Post-fix the two bases agree on 94 of 94. So this is not a live write-path defect — `fbf9073` fixed it, exactly as the roadmap says it did. It is a **stale measurement basis** that has since been used to justify new rules.

## 3. What this kills

- **Card `profit-cheap-refusal-ask-price`** (Lane A, awaiting approval: re-order the hard-skip checks so cheap refusals are admitted). Its load-bearing number is "+13.9pp / +108.5% on the 189 unpriced rows". On this population the label basis reproduces the shape (+10.8pp / +112.4%) and the token basis is −2.1pp / −6.8%. The card's case is **unsupported**, not reversed: −6.8% CI [−45,+34] and −16.0% CI [−64,+48] both include zero. The honest statement is "there is no measured edge here", and a gate re-ordering cannot be approved on it.
- **The TTR-floor cell** — the most attractive thing I measured today before auditing it (+396.6%, ex-top-10 still +169.7%). It is −64.2% once the leg is marked on the token it is priced on. The 2h floor is doing its job; do not touch it.
- **The standing claim that the cheap band has a positive calibration edge.** Post-fix, the only rows a forward decision could use, read 10.6% hit against a 13.6c ask.

## 4. What this does NOT mean

- **The ledger is not wrong.** Pre-fix book rows were repaired by `d974287` (233 rows, 2026-11-11) and post-fix rows are clean (0 of 94 disagree). This defect lives in `DecisionJournal`/`ObservedTrade` measurement populations — refused candidates, which have no book row at all.
- **It is not a licence to reopen gates.** The liquidity blocker and wallet copy cap closed NO-CHANGE under their own shadow reads; nothing here reopens them.
- **It does not touch yesterday's stop card.** That result (fast adverse stop, +$630/21d) was computed from fill prices and marks, not from outcome labels.

## 5. Recommendations

### R1 — Withdraw the cheap-refusal gate re-ordering; the case for it is a stale basis
- **Hypothesis:** the +10.8-13.9pp excess that card rests on is produced by the label inversion, not by the population.
- **Measurement:** `python3 scripts/profit-cheap-ask.py` §9 (token truth `data/cheap-token-truth.json`, 208 markets; both bases printed side by side).
- **Decision rule:** withdraw when the token-basis cohort edge is ≤ +2pp over breakeven AND the post-fix subset's ROI at the ask is ≤ 0. Measured: −2.1pp and −16.0%.
- **Refutation:** a token-basis re-mark on ≥150 post-fix named rows recovering ≥ +8pp of edge and ≥ +20% ROI at the ask → the population is real, and the card is restored.
- **Effect:** prevents admitting a population priced at −16.0% at the ask (flow there is 6.97 TTR<2h cheap candidates/day). No dollar figure is claimed for the withdrawal itself — the card's proposal was to re-order checks, not to fund.
- **Cost:** 0.5h (withdraw + one-line close note).

### R2 — Re-mark every band/lane ROI that carries named-outcome rows, before anything else is approved off it
- **Hypothesis:** the same inflation sits in every historical band ROI whose population includes named markets (51% of this cohort's resolved rows), and it is entirely pre-fix, so the post-fix rows are the only forward-usable record.
- **Measurement:** §9's two-basis print, generalised over band × lane with the named share per cell printed beside it. Base instrument: `scripts/profit-band-report.py` + the token join in `profit-cheap-ask.py`.
- **Decision rule:** any cell whose token-basis ROI falls below its own breakeven gets restated in the card that cites it, and no card may be approved on a pre-fix named-outcome population.
- **Refutation:** if across bands the label and token bases agree within 2pp — which is what happens on YES/NO rows today (0 disagreements in 103) — the defect is confined to this cohort and R2 collapses to a footnote.
- **Effect:** protects every pending approval from a defect that just moved one number by 119pp of ROI. **Cost:** 2h.

### R3 — Pre-register the long-shot shadow ladder on the token basis before it can be promoted
- **Hypothesis:** the ladder is marked by `didOutcomeWin(outcome, {winningLabel})`, a pure label compare (`src/lib/resolution.ts:73`), on the same defect surface; its headline (`data/longshot-shadow-summary.json`: 155 would-admit, 135 resolved, 26 wins, 19.3%, +$1,891.93 on $20 stakes) is therefore not yet a forward-usable number.
- **Measurement:** re-mark the ladder's resolve records against `tokens[].winner` per market (the same join §9 uses); print both bases and the named share.
- **Decision rule:** promote only if, on the token basis, ≥150 further resolved admits clear +5pp of hit-rate excess over their actual entry price. Until then it stays a shadow.
- **Refutation:** if ≥90% of the ladder's resolved admits are YES/NO rows, the label basis is already the token basis there and the promotion bar can be read off the existing record.
- **Effect:** decides whether the one remaining candidate for a new lane is real. **Cost:** 2h.

**Ranking:** R1 (protects a live approval, costs nothing) → R2 (protects the whole decision record) → R3 (decides the next lane). All three are measurement, not risk: nothing in this review changes a threshold, a clip, a band or a gate.

## 6. Reported, not resolved

- **The "1,269 open legs / 1.03M capital-days" baseline in the standing brief is stale.** The open book today is **384 legs, $4,181, 382 of them STANDARD, average age 104.6 days**, marked −$232.82 (359 of them are past 30 days, holding $3,824). The shrink is v66's 168h exit (2026-10-24, fired once) plus resolutions — and the 168h replay already closed NO-CHANGE (`drafts/standard-168h-exit-replay-20261112.md`: capital-days −78.3% but PnL −$762.62). Capital-days are not the binding constraint while the marginal dollar is ≤0; I am not re-proposing an exit rule.
- **The 2026-11-12..14 admission blackout is explained and already repaired.** Zero `paper_copy` decisions for three days; the skip rows carry `drawdown gate [realized] (net worth $7560 vs peak $11069 = 31.7% > 20%)`. That peak was the pre-repair watermark; it was rebased 11068.58 → 7987.32 on 2026-11-15 (`apr-c200-realized-peak-rebase`), and the gate reads 12.1% today. Nothing to do.
- **The 2026-11-20 23:59 UTC fee repricing is worth 3.5pp of dollars at risk on this cohort and cannot flip it:** 4.40c per dollar at risk at a 12.0c median ask under the old 5% rate, 0.88c under the new 1% rate, against a measured −16.0% ROI. Paper fills pay no fee at all, so it moves no realised number today. No action.
- **A contradiction I am reporting rather than resolving:** the 2026-11-14 card states the refused cheap cohort at +11.1pp / +108.5% at the mid; this run reproduces +10.8pp / +112.4% at the *ask* on a 209-row resolved version of the same population. The population differs slightly (189 vs 209 rows) and the two are not the same measurement, but both sit on the label basis and both are affected by the same 29 rows.

## IF YOU WEREN'T HERE

Do not approve the cheap-refusal gate re-ordering. Its +13.9pp is 29 mislabelled rows: mark those legs on the token they were priced on and the same population reads −2.1pp, −16.0% on the post-fix rows. Before any further band or lane change, re-run `python3 scripts/profit-cheap-ask.py` and read §9 first — if the two bases do not agree on the population in question, the number is not a measurement yet.
