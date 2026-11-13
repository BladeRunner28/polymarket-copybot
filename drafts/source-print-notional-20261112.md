# Source-print notional as an admission feature — measured, not added (2026-11-12)

**Verdict: the gap is real on no basis I can defend. Dropped.** The card's own decision
rule required the controlled gap to be ≥ $1.50/leg **with 2SE below it**; the 2SE is 1.7×
the gap, the gap has no stable sign across regimes, and the big-print bucket's entire
mean is one leg. Nothing was added to scoring; no rule, size, gate or published figure
changed.

Card: `research-source-print-notional` (APPROVED 2026-10-23, decision date 2026-11-06).
Instrument: `scripts/source-print-notional-read.py` (`--self-test` 7/7) · artifact
`data/source-print-notional-read.json` · fixtures `tests/fixtures/source-print-notional-fixture.py`
· suite guard `tests/source-print-notional-read.test.ts`.

## Basis (every number below carries this)

| item | value |
|---|---|
| population | non-demo C-200 legs (`botId=BANKROLL_200`, `isDemo=0`, status closed∪resolved, `realizedPnl` NOT NULL) joined to their admitting `DecisionJournal` row and the `ObservedTrade` print that triggered them (`isDemo=0`, `observationOnly=0`) |
| level | one leg (302 big / 1,334 small) |
| clock | leg clock, `openedAt >= 2026-09-04`; regime = `journal.ruleSetVersion` |
| return | `realizedPnl / simulatedPositionSize` = per **$1 staked**, gross of fees |
| notional | `ObservedTrade.size`, which the adapter writes as **USDC** (`usdcSize`), never `size × price` |

## The card's read, reproduced and then decomposed

| basis | big (≥ $250) | small (< $250) | gap (small − big) |
|---|---|---|---|
| per leg (card's unit) | +$1.95 | +$3.87 | **+$1.92/leg** |
| per $1 staked | +0.056 | +0.150 | **+0.094/$1** |
| matched ATT, per $1 | — | — | **+0.129/$1, 2SE 0.216, CI [−0.047, +0.367]** |
| matched ATT, per leg | — | — | +$4.59, 2SE $7.69 |

Matched cells = regime × entry band × TTR band × stake band (this repo's regime definition is
the admitting rule version); 298 of 302 big legs matched (98.7%). Mean C-200 stake is $11.66
on big prints vs $13.45 on small, so **$/leg is stake-confounded**: the card's own $5.22 vs
$0.33 was partly a stake difference, and the per-$1 read is the one that survives that.

## Concentration check before believing either arm

| bucket | median | 10% trimmed | ex-top-10 | top-10 share of sum |
|---|---|---|---|---|
| big per leg | −$0.04 | −$1.58 | −$3.31 | **264%** |
| small per leg | −$0.22 | −$1.70 | −$0.80 | 120% |

One leg — 0x565c09… , $100 staked at 0.153, won, +$552.23 — is **93.7%** of the big bucket's
entire +$589.52. Without it the big bucket is **+$0.12/leg**. Both buckets are negative
ex-top-10, i.e. the C-200 book's positive mean is top-10-carried on either side of the cut.
The big bucket also sits in 55 wallets, largest 21.2% of its legs (the card said 78 wallets /
12% — both were the smaller 159-leg snapshot).

## The $250 cut is not load-bearing

| print size | n | per leg | per $1 | median/$1 |
|---|---|---|---|---|
| $0–25 | 972 | +$5.24 | +0.161 | −0.152 |
| $25–250 | 362 | +$0.21 | +0.120 | 0.000 |
| $250–1k | 149 | −$2.12 | −0.001 | −0.184 |
| $1k+ | 153 | +$5.92 | +0.111 | 0.000 |

Non-monotone: the `$250–1k` band is the negative one and `$1k+` is positive. A monotone
"big prints are worse" story cannot be read off this ladder.

## Sign is not stable across regimes (regime = admitting rule version)

| regime | big n / per $1 | small n / per $1 |
|---|---|---|
| v≤50 | 25 / +0.463 | 184 / +0.207 |
| v51–55 | 45 / +0.103 | 364 / +0.083 |
| v56–60 | 125 / +0.155 | 452 / +0.201 |
| v61–65 | 38 / −0.018 | 91 / +0.198 |
| v66–70 | 30 / −0.459 | 59 / +0.106 |
| v71+ | 39 / −0.111 | 184 / +0.088 |

Four regimes say big-print legs did *better*, two say worse. The whole-book gap is a mixture,
not an effect.

## Controls that could have rescued it, and did not

- **Print-cluster arm** (prints summed ±300 s on the same wallet/market/outcome, so a whale
  splitting one order cannot read as several small prints; 1.9 prints/leg mean, 78.2% of legs
  are single prints): big n=381 / +0.073 vs small n=1,255 / +0.151 → matched gap **+0.143/$1,
  2SE 0.242**. Same story, still not significant.
- **Wallet arm** (16 wallets with ≥3 legs on each side): median gap **−0.011**, 8 wallets
  big-worse / 8 big-better. No wallet-level pattern to rank on.

## The card's pre-registered rule, condition by condition

| condition | result |
|---|---|
| n_big ≥ 60 | **pass** (302) |
| matched coverage ≥ 80% | **pass** (98.7%) |
| controlled gap ≥ $1.50/leg | pass on the point estimate ($1.51/leg at the big bucket's mean stake) |
| 2SE below the gap | **FAIL** (gap 0.129/$1, 2SE 0.216/$1) |
| literal raw $/leg ≥ $1.50 | pass ($1.92) — the stake-confounded basis |
| literal matched 2SE below gap | **FAIL** |

**FIRES: no.** By the rule's own wording and its 2026-11-06 clock: record print notional as a
liquidity/era proxy and drop the axis. Nothing is scored, nothing is tagged.

## What this does NOT say

The CI still admits an effect as large as **−35¢/$1** on big prints; the read is
**underpowered**, not a proof of zero. At the observed dispersion (sd 1.19/$1) the big arm
needs ~338 legs for 2SE to fall below the current gap and holds 302, i.e. ~36 more. That is a
fact worth recording, not a reason to re-open: the deadline that would have admitted the
feature has passed, and three independent robustness arms (ladder, regime, wallet) each
refuse to show the sign.

## Rollback

Nothing live was touched. `git revert` of the commit that adds the instrument, artifact,
fixture, test and this draft restores the tree exactly; `data/source-print-notional-read.json`
is a read-only artifact and can be deleted without affecting any decision path.
