# Why copybot selects what it selects — 2026-10-19

Measurement only. No rule, gate, size or live-lane change was made. Source: `prisma/dev.db`
(DecisionJournal 340,006 / MarketSnapshot 15,887,343), `data/ml/decisions.parquet`, cost = the ask
we would pay for our side (same rail as the EV read).

---

## 0. The answer

**Copybot's selection adds no measurable edge** (acted −0.0106 vs declined −0.0087 per share,
`hit − cost`), and **64.4 % of the volume it acts on sits in price bands whose edge is negative**.
But the deeper cause is not a preference for expensive favourites — it is that **~27 % of the
declined flow was never judged at all**: 12.5 % was stopped by a wallet copy cap and 14.8 % by a
**broken liquidity gate that fires on a reading of $0 while the book says otherwise**. Fixing the
pipeline's non-judgements comes before optimising its judgements.

## 1. Where the volume sits

| cost band | decisions | acted rate | edge (hit − cost) |
|---|---|---|---|
| 0.00–0.10 | 3,675 | 3.1 % | **+0.092** |
| 0.10–0.20 | 1,101 | 12.6 % | **+0.062** |
| 0.20–0.35 | 1,980 | 12.8 % | **+0.064** |
| 0.35–0.50 | 4,406 | **16.9 %** | +0.029 |
| 0.50–0.65 | 5,053 | 16.1 % | −0.042 |
| 0.65–0.80 | 4,227 | 11.5 % | **−0.087** |
| 0.80–0.90 | 3,747 | 6.2 % | −0.064 |
| 0.90–1.00 | **38,979** | 1.9 % | −0.010 |

Two facts: the candidate stream is **half near-certainty** (38,979 of 80,208 decisions are ≥0.90),
and the acted *rate* peaks mid-band while the acted *volume* does not — **64.4 % of the 3,514 acted
trades are above 0.50, where edge is negative**. A 1.9 % take rate on 38,979 candidates still yields
more trades than a 16.9 % take rate on 4,406.

## 2. A correction to what I said earlier

Last message I reported that in the cheap band copybot's selection lift was **−0.128** — that it
picks the *worse* cheap bets. **That does not survive its own sample size.** Merged to cost ≤ 0.35:

| | n | hit rate | market-clustered CI |
|---|---|---|---|
| acted | 507 | 0.199 | [0.161, 0.241] |
| declined | 6,249 | 0.207 | [0.196, 0.218] |

The intervals overlap almost entirely. The −0.128 came from a single 0.00–0.20 cell with **253 acted
rows and 21 wins** — I read a small cell as a signal. What is actually true is narrower and less
dramatic: **the selection is indistinguishable from the band it draws from**, i.e. it is not
concentrating where the edge is.

## 3. What is actually stopping the flow

Sole blockers over 150,000 declined decisions (a row with three gates is not admitted by removing
one, so only single-gate rows are counted):

| sole blocker | n | share of declined flow |
|---|---|---|
| **wallet daily copy cap (10) reached** | 18,724 | **12.5 %** |
| **liquidity $0 < min $1000** | 14,252 | **9.5 %** |
| **liquidity $0 < min $500** | 7,873 | **5.2 %** |
| price drifted 0.005 since entry > max 0.0019 | 5,020 | 3.3 % |
| price 0.999 near certainty (band 0.05–0.95) | 4,792 | 3.2 % |
| resolves in 0.0h < min 2h | 4,416 | 2.9 % |
| wallet daily copy cap (25) reached | 3,456 | 2.3 % |

Also: **68 % of declined cheap rows carry more than one gate** (4,087 of 6,000) — so there is no
single toggle that reopens the cheap region, and a one-gate experiment would understate the effect.

## 4. The liquidity gate is broken

Of 800 decisions whose blockers include `liquidity $0 < min $500`, **746 of 746 that had a snapshot
at decision time (100 %) had liquidity > 0 in the book**. Zero of them had a genuinely zero
liquidity reading. The gate is consuming a value that is not the market's liquidity — most likely a
missing/partial field defaulting to 0 rather than a measured zero. (The snapshot table itself has
`liquidity = 0` on only 7,824 of 15,887,343 rows, 0.05 %, and NULL on 1.5 %.)

**Blast radius: 22,125 decisions = 14.8 % of declined flow blocked solely by a bad reading.**

## 5. What this means

- Copybot is **capacity-bound as much as judgement-bound**: the largest single blocker is the
  per-wallet daily copy cap (10), at 12.5 %. That is a sizing question, not a scoring question, and
  it interacts directly with the ladder's scaling goal.
- The gate set is a **liquidity/stability proxy** (min liquidity, drift ≤ 0.0019, min time to
  resolution, near-certainty band). Cheap longshots systematically fail all of them — that is *why*
  the profitable region is under-sampled, and it is a design consequence, not a bug.
- The pipeline wastes a seventh of its declined flow on a data defect.

## 6. Recommendations (none applied — each needs your approval)

1. **Fix the liquidity source feeding the gate** (data integrity, no rule change). Expected: ~14.8 %
   of declined flow returns to consideration. This should be a shadow read first — measure what
   would have been admitted before anyone changes what is admitted.
2. **Treat the wallet daily copy cap as a first-class decision**, not a background rail: 12.5 % of
   declined flow stops here. Whether to raise it is a sizing/risk call with a ladder interaction.
3. **Do not loosen the longshot gates on the strength of the EV read.** That evidence is n=235–473
   in the decisive cell with fillability unmodelled. Pre-register a shadow lane instead.
4. **Order matters**: repair the non-judgements (§4, §3) before tuning the judgements. A better
   ranker on top of a pipeline that discards a seventh of its flow on a bug changes little.
