# Profit research — 2026-11-18: the fills now separate the book, and the $100 clip is a longshot-placement bug

**Date:** 2026-11-18 · **Research only** — no rule, size, gate or published figure changed; DB reads are `mode=ro`
**Instruments (committed with this doc):** `scripts/profit-path-research.py`, `scripts/fee-schedule-delta.py`,
both re-run to produce every figure below.
Basis, stated once: cost = `PaperTrade.simulatedPositionSize` (**dollars at risk**); PnL = `realizedPnl`,
`status IN ('closed','resolved')` (TR-15 OR), `isDemo=0`; dedupe = first leg per
(botId, walletAddress, marketId, outcome); clock = **entry vintage** (`openedAt`), never settlement date;
CI = **market-clustered** bootstrap, 2,000 draws, resampling markets not legs.

Yesterday's figures that moved: filled n **278 → 280**, the −19.2% point estimate **→ −21.3%**, and the
per-vertical split is new (the instrument gained a `vertical()` grouping today; the category table it
replaced is unchanged underneath).

---

## The finding

**The book's fill-confirmed loss is not one undifferentiated smear any more. Two verticals are negative
with a CI that excludes zero, and the money that looks positive is three legs deep.**

| filled class | n | at risk | PnL | ROI | cluster CI |
|---|---|---|---|---|---|
| question | 52 | $1,499 | −$867 | **−57.9%** | **[−77.3, −31.6]** |
| esports | 65 | $1,255 | −$751 | **−59.8%** | **[−82.0, −25.6]** |
| other | 59 | $649 | −$344 | −53.0% | n<80, not read |
| sports | 104 | $912 | +$1,045 | +114.7% | [−27.8, +240.6] |
| sports, **ex-top-3 legs** | 101 | $901 | −$247 | **−27.4%** | [−53.1, +4.7] |

Two readings, both mine:

1. **question and esports are proven losers on the only class we can prove we held.** 52 and 65 legs,
   win rate 23.1% and 33.8% against break-evens of 60.2% and 62.2%. This is the first cohort in this book
   where a fill-confirmed ROI separates from zero under market clustering.
2. **sports is not a positive vertical; it is two tennis/soccer wins.** Strip the top three legs and it is
   −27.4%. Any statement of the form "sports carries the book" is a statement about 2–3 legs.

The whole filled class still reads −21.3%, CI [−56.1, +25.5] — because the sports legs offset the rest.
The CI on the *aggregate* spans zero; the CI on the *classes* does not. That is not a contradiction, it is
what happens when one class has three lottery hits in it.

## The $100 clip is not oversizing a good trade — it is the longshot path

21 filled legs at the $100 tier, $2,100 at risk, **−$610 (−29.0%)**, win 9.5% vs break-even 14.2%,
ex-top-3 **−$1,657**. That is 66.5% of the entire filled loss ($917) on 7.5% of the filled legs.

The composition explains it. **19 of the 21 entered at $0.05–$0.19.** The two that did not are the two
winners (+$512 soccer at 0.16, +$552 tennis at 0.15). Excluding those two, the tier is
**19 legs, $1,900 at risk, −$1,675 = −88.1%**, and three of the four vertical cells are near-total losses:

- esports $100: 6 legs, −$600, **−100.0%** (all six lost)
- other $100: 3 legs, −$275, −91.8%
- question $100: 10 legs, −$799, −79.9%
- sports $100: 2 legs, +$1,065, +532% (the two winners)

A longshot at 0.10 needs a ~10% hit rate to break even at zero fee; we deliver 9.5%, and the fee is
another ~2.8% of stake. This is the same mechanism the open card `profit-c200-price-frame-sizing`
described from the other side (13 of 41 $100 clips were favourite-priced): **the clip is sized as if the
position were the favourite while the position is the longshot.** Today's delta is that the filled class
now prices it: −88.1% on 19 legs, rather than a proposal with no proven fills behind it.

Cross-check, because it matters for how the number is used: the **+$552.23 ATP leg at 0.153** is the same
single leg that flipped the clip-cap CI across zero in the 2026-11-12 read. One leg carries this tier in both
directions — which is why the cap is a drawdown rail and not an edge trade, and why the −88% is reported with
the two winners named rather than quietly trimmed.

## External: Polymarket reprices taker fees on Friday, and the maker rebate floor moves out of reach

`docs.polymarket.com/changelog.md`, entry **2026-11-16** (read 2026-11-18); full schedule at
`docs.polymarket.com/programs/fee-and-rebate-changes-november-2026.md`. **Effective 2026-11-20 23:59 UTC.**

Same formula both regimes: `fee = shares × feeRate × p × (1−p)`. Since cost = shares × p, the fee per
dollar at risk is just `feeRate × (1−p)` — independent of clip size. Measured on 5,912 settled legs:

| cell | n | 1−p | fee %, now | fee %, 20 Nov |
|---|---|---|---|---|
| question (politics non-election reading) | 2,930 | 0.351 | 1.77 | **0.44** |
| question (other/general reading) | 2,930 | 0.351 | 2.22 | 2.22 |
| sports | 1,692 | 0.541 | 2.79 | 2.79 |
| esports | 821 | 0.521 | 2.77 | 2.77 |
| other | 469 | 0.556 | 3.06 | 3.06 |

- **Nothing we trade gets materially more expensive.** Politics non-election 0.04→0.01, culture/econ/weather
  0.05→0.01, crypto 0.07→0.01 (except BTC 5/15-minute, 0.05). Sports is unchanged at 0.05, esports sits in
  sports. The only increases are politics-**elections** 0.04→0.05 and finance/tech 0.04→0.05, worth 0.01×(1−p)
  ≈ 0.35% of stake.
- **The fee is not booked anywhere.** `PaperTrade` has no fee column; `realizedPnl` is gross. A 2.8–3.6% of
  stake per leg is therefore missing from every figure in this book — including the ones quoted above.
  Netting it: filled:question −57.9% → −61.1% now / −58.7% after 20 Nov; esports −63.7% either way.
- **The maker rebate becomes unreachable at our size.** Rebates move from a per-market pool share
  (15% sports, 25% politics) to 3–15% of the taker fees your fills generate, and the **first tier starts at
  $200,000 of 30-day maker weighted volume**. Our 30-day weighted volume is **$7,392** — 27.1× short.
  Under the new schedule we earn **$0** in maker rebates until flow grows 27×.
- **`src/lib/scoring/price-edge.ts:65 categoryFeeRate()` hardcodes the old schedule** (crypto 0.07,
  politics/finance 0.04, default 0.05). From 20 Nov it over-charges crypto by 6¢ per (1−p) and
  non-election politics by 3¢. That function feeds the score that decides entries, so correcting it is a
  **Lane A** change, not a repair — it is dated, not urgent, and it is not applied here.

## Kalshi LIP: above-gate programs exist only in history — the live menu is 0 of 7,499

`scripts/lip-ledger.py --fetch` re-read to exhaustion today (232,112 usable liquidity programs, fetched
2026-11-18T14:40Z; paid_out hits the 200-page cap, so the all-status count is a floor). My first pass was
page-capped at 30 and silently truncated the store — the full re-run restored it before anything was quoted.

| population | programs | ≥ gate $0.0131 | max ceiling |
|---|---|---|---|
| whole feed, all statuses (incl. retired) | 232,112 | **77,470 (33.4%)** | p99 0.333 |
| ≤2h windows (historic) | 93,627 | 81.7% | median 0.040 |
| **live menu (active + upcoming)** | **7,499** | **0 (0.0%)** | **0.003526** |
| our quote universe (338 tickers) | 504 | **0** | 0.001120 |
| measured ledger, our universe | 92 | 0 | net **+0.0000890** |

The 33% is the trap: those are **retired** programs. Every above-gate program in the feed sits in a ≤2h
15-minute family — `KXCRYPTOLEAD15M` (22,088), `KXTTELITEMATCH` (12,705), `KXTEMPMIAH` (10,606),
`KXLIGAPROMATCH` (3,873), `KXNATGAS15M`, `KXCOPPER15M`, `KXPLATINUM15M`, `KXPALLADIUM15M`, `KXEURUSD15M`,
`KXGBPUSD15M`, `KXUSDJPY15M` — and **none of them is live today**. The live menu's best ceiling is
0.003526, **3.7× below the gate at 100% share**; our own universe's best is 0.001120 (11.7× below).

Verdict, unchanged and now on one basis: **CLOSE**. Measured net +0.0000890 $/contract-hour is **147× below**
the gate. What the full read adds is the *shape* of the reopening condition: LIP paid, and would pay again,
on 15-minute crypto/commodity/FX/temperature contracts — families we do not quote. That is a new-lane build
question with no live program to build against, so it stays closed until `lip-ledger.py` re-reads a live
≤2h family above gate.

## Progress on the approved five (deltas only)

- **1. maker-vs-taker shadow — measured, nothing shipped.** Today's 07:54 read priced all three arms
  (maker −6.1%/intent-$ , taker −6.8%). No live recorder is emitting a maker arm; this is counterfactual
  replay, so the card's 200-leg forward gate is still at 0 of 200.
- **2. STANDARD fill adjudication — writer runs, merge does not.** `data/standard-fill-stamp-20261118.jsonl`
  is fresh (7 snapshots, 143 legs in scope, book coverage 98.6%), but `PaperTrade.fillStatus` for STANDARD
  is still **0 of 10,027** settled legs. The evidence exists on disk and is not in the book.
- **3. $100 clip cap — not applied.** RuleSet v73 (2026-11-13) predates the 2026-11-16 card; 4 legs ≥$90
  opened 2026-11-16/17. The $100 tier is still live and still being handed longshots.
- **4. ML objective re-point — not started.** `data/ml-ledger.jsonl` last entry (2026-11-18T11:35Z) is still
  the outcome-AUC gate (0.729 vs price 0.7285); no fill/adverse-selection arm exists.
- **5. LIP — re-read, still close.** Live menu **0 of 7,499** programs above gate (max ceiling 0.003526,
  3.7× below); the 33% above-gate rate in the feed is entirely **retired** 15-minute programs.

## Ranking — what to do, in order, each with its refutation

**1. Execute the band-scoped clip cap that is already approved (0.0–0.2 at $25, C-200 only), not the
lane-wide version.** The lane-wide arm was refuted on 2026-11-16 (−$69.21 worse than band-scoped on the same
legs, `drafts/profit-c200-clip-cap-25-20261116.md`); the band-scoped arm was approved 2026-11-12
(`apr-profit-band-clip-rebalance`) as a drawdown rail and is still unapplied. Today's evidence is exactly its
population: **19 of the 19 losing $100 legs entered at 0.05–0.19**, so the rail now has a fill-confirmed loss
(−$1,675 on $1,900) sitting inside its band. Refuted by: a forward 40-leg 0.0–0.2 sample at $25 earning less
than the same legs at $100 — or the ladder's 7-day sum continuing to advance on unproven legs (card
`ladder-credit-positions-only`).

**2. Merge the STANDARD stamp into `fillStatus` (item 2).** 0% coverage on 10,027 settled legs is the only
thing keeping the $9,165 STANDARD PnL (all-time, +7.9%) unfalsifiable, and the evidence is already being
produced daily. Refuted by: merged coverage that shows the question class positive at ≥60% filled — which
would mean the phantom framing was wrong.

**3. Book the taker fee before 20 Nov (new, from the external change).** Every published ROI in this book is
gross; the schedule changes in two days and `categoryFeeRate()` will then overcharge two categories. The
change is a published-figure change → Lane A, proposal only. Refuted by: a fee model that reproduces the
venue's own fee on a matched sample of live fills (we hold no such sample — that is the tell).

**4. Re-price the maker conversion (item 1) against the new rebate floor.** 27.1× short of the first rebate
tier means the maker arm has to stand on spread capture alone. Refuted by: a maker arm that reaches 200
forward legs and ≥5pp over the crossed cohort *without* rebate credit.

**5. LIP — nothing to build, and a re-read condition instead of a project.** 0 of 7,499 live programs clear
the gate and the live ceiling is 3.7× below it; the historic 33% shows what a reopening looks like
(≤2h 15-minute crypto/commodity/FX/temperature families). Refuted by: `lip-ledger.py` re-reading a live ≤2h
family above gate — it already does this on every run, so no work is required to catch it.

## Not changing today, and why that is the answer

No new predictor, no new gate, no new venue. The measured object is unchanged from yesterday in every
respect that matters: the provable class still loses, the profits still sit in legs that never traded
(539 unfilled C-200 legs, $8,344, +$2,297) or were never adjudicated (2,047 NULL legs, $16,752, +$3,789).
What would unlock a change: **merged STANDARD adjudication** (item 2) or a **40-leg forward $100 sample**
(item 3's refutation). Either one converts a point estimate into a decision.
