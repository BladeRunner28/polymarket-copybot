# Polyterm P3 — the pre-registered hygiene read: the score does not rank realized copy outcomes

**Verdict: NO RANK INFORMATION — no promotion, nothing wired.** Read run 2026-11-09, reproduced 2026-11-11 on a larger population with the same rule and the same answer. `src/lib/market-hygiene.ts` stays advisory; no live path reads it.

## The rule, fixed before the first run

`PASS` = Spearman(riskScore, per-$1 return) **< 0 in all three ruleSetVersion eras** AND the pooled **market-clustered bootstrap 95% CI upper bound < 0**. Risk score is higher = riskier, so a real hygiene signal must rank *lower* returns. Anything else is `NO RANK INFORMATION`. Kill rule (audit): fewer than ~150 settled rows per arm is "too few decisions to price the gate", not a verdict — every era clears it.

## Basis (stated, not implied)

| Item | Value |
|---|---|
| population | 12,767 settled non-demo PaperTrade legs / 4,288 markets |
| level | the leg; bootstrap clusters on **market** (legs in one market are not independent) |
| clock | as-of MarketSnapshot at or before `openedAt`, ≤12h stale — never a value fetched today |
| outcome | realizedPnl / simulatedPositionSize (per $1 staked) |
| volume24hr | reconstructed from our own cumulative-volume delta on 4,629 legs (36.3%); absent on 8,138, where the volume factor is **dropped and weights renormalised** (never scored as an observed zero) |

## The read

| era | legs | risk rho | 95% CI (market-clustered) |
|---|---|---|---|
| pre-kelly-v1-48 | 10,557 | −0.142 | [−0.319, +0.036] |
| kelly-window-v49-57 | 992 | **+0.129** | [−0.073, +0.332] |
| exposure-v58plus | 1,218 | **+0.057** | [−0.003, +0.119] |
| pooled | 12,767 | −0.101 | [−0.260, +0.045] |

- **The sign is not just absent, it is wrong in both live eras.** +0.129 (v49–57) and +0.057 (v58+) mean higher-risk-graded markets realized *slightly better* returns. Neither is significant; a coin flip is the generous reading.
- **Pooled CI includes zero** (hi = +0.045). Negative point estimate driven entirely by the pre-Kelly era.
- **Per-ruleSetVersion, at the audit's 150-row floor: 11 of 22 negative (50.0%)** — v2 −0.412 and v3 −0.323 against v50 +0.332 and v26 +0.219. Not a gradient, a coin flip.
- **Grade bands, live era (v58+): the safest markets were the worst.** A (n=170) mean −$0.13 / median −$0.89; B (n=761) +$0.32 / −$0.15; C (n=287) +$0.57 / $0.00. In v49–57 same inversion: A −$0.35, C +$0.05.
- **Settlement-only arm flips too** (−0.332 / **+0.135** / +0.051): early exits are our policy, and a market-quality rank should survive on natural resolutions. It does not.
- **Price-band control:** no consistent sign inside any band in either live era (v58+: +0.224, +0.143, −0.045, −0.005, −0.515).
- **Sensitivity:** the ported as-is score (missing volume → "no recent volume" 40) gives rho −0.100 — the renormalisation is not producing the result.

## Reproduced, not re-litigated

| run | legs / markets | pooled rho | CI | verdict |
|---|---|---|---|---|
| 2026-11-09 (first, pre-registered) | 12,685 / 4,220 | −0.101 | [−0.260, +0.048] | NO RANK INFORMATION |
| 2026-11-11 (re-run, +82 settled legs) | 12,767 / 4,288 | −0.101 | [−0.260, +0.045] | NO RANK INFORMATION |

The population has effectively stopped growing, so this answer is stable rather than preliminary. Artefacts: `data/market-hygiene-rank.json` (first run, left untouched), `data/market-hygiene-rank-rerun-20261111.json`.

## What the wash arm says — and why it is not a result

`washSpearman` is negative in all three eras (−0.100 / −0.120 / −0.169), which looks like the only consistent signal in the file. It is not readable as one: the wash profile was **assessable on 16.5% / 17.1% / 3.5%** of legs, and every unassessable leg carries score 0 — tied with "perfectly clean". The rho is therefore dominated by *whether we could measure anything at all* (legs with volume+liquidity on record), not by wash-trade evidence. Reading the wash arm properly needs a subset read on assessed legs only, with its own CI — that is a different, un-pre-registered measurement and was not run here.

## Disposition

- No promotion, no gate, no size or rule change. The hygiene module remains advisory shadow output.
- The 2026-11-09 Lane B repair stands: a missing `volume24hr` used to be scored as an observed "no recent volume" (40) on 8,067 of 12,685 legs; the factor is now omitted and `RiskGrade.omitted` reports it.
- What would change the answer: the sign negative in all three eras **and** a clustered CI clearing zero — but v49–57 and v58+ together are ~2,200 legs and shrinking (the regime's settled flow is nearly exhausted), so this is unlikely to accumulate the power to say so. Treat the hygiene grade as unmeasured against outcomes, not as "probably fine".
- Rollback: `git revert` of the read commits; everything is additive and read-only.
