http://localhost:3013/drafts/profit-research-20261127

# Profit research — 2026-11-27

**The copy source has no measured forward signal: the wallet score the bot selects on ranks live ROI at ρ = −0.045 (17 wallets, p = 0.57), the pre-v68 wallet rank carries forward at ρ = −0.25 (9 pairs, perm CI spans the full range), and the live era is structurally too thin to decide either way (57 % power at ρ = 0.6; 20 pairs needed). Meanwhile the one live loss accumulator is filling today: three $100 clips opened at 5.9c / 16.3c / 10.8c with TTR 8 h / 12 h / 23 h — every one inside the block already proposed this morning.**

Instruments: `scripts/profit-path-research.py` (fresh numbers) and **`scripts/profit-wallet-persistence.py` (new today, `--selftest` PASS)**. Basis: cost = `simulatedPositionSize` = dollars at risk; PnL = `realizedPnl`, `status IN ('closed','resolved')` TR-15 OR, `isDemo=0`; dedupe = first leg per (bot|wallet|market|outcome); clock = entry vintage; CI = market-clustered bootstrap, 2000 draws, `n/a` below 6 clusters.

---

## 1. Fresh measurement — the basis moves 5.6× on the denominator, so it is quoted first

| basis (same dedupe, same day) | legs | at risk | PnL | ROI | mkt CI |
|---|---|---|---|---|---|
| booked (all cost>0) | 6,169 | $73,156 | +$7,227 | **+9.9 %** | [+1.8, +19.0] |
| carried (`fillStatus=filled`) | **328** | **$4,990** | **−$772** | **−15.5 %** | [−47.0, +27.1] |
| unfilled | 705 | $10,749 | +$2,270 | +21.1 % | [+2.6, +44.5] |
| unstamped (STANDARD, never adjudicated) | 5,136 | $57,417 | +$5,730 | +10.0 % | [+1.5, +20.6] |

The positive number is the two classes with **no fill evidence** (60 % of at-risk is unstamped, and STANDARD is 0/10,067 adjudicated, tenth day). The provable class is unchanged in kind: **−15.5 %, CI spans zero**, ex-$100-clip **306 legs, −2.2 %, CI [−26.2, +24.0]**.

- **$100 clip: 22 legs, $2,200, −$709.85, −32.3 %, 9.1 % win vs 14.3 % break-even → 92.0 % of the entire filled loss.** Cartoonishly concentrated and unmoved for nine days.
- **Verticals (filled):** question 55 legs **−50.4 %** CI [−73.3, −17.3]; esports 70 **−58.6 %** CI [−80.6, −27.0]; sports 128 **+92.5 %** CI [−12.1, +192.9], **ex-top-3 −5.3 %**. Two classes provably negative, one positive only through three legs.
- **Delta vs yesterday:** 320 → 328 legs, $4,875.89 → $4,990 at risk, −$826.75 → −$772.00 (8 new legs, +$54.75 — one ordinary win, no basis change).
- **Coverage by lane:** BANKROLL_200 1,040/3,087 = **33.7 %** (100 %/day since 2026-11-09 vintage); STANDARD **0/10,067 = 0.0 %**.

## 2. New instrument — is the wallets' past record worth anything?

`profit-band-report.py --v4` §E6 returned *UNMEASURED* (5 repeat wallets). This file runs it where repeat wallets exist: **pre-v68 as FIT, v68+ (live, started 2026-10-27) as TEST**, same dedupe, era from `DecisionJournal.ruleSetVersion ≥ 68`. The live era holds **702 deduped settled legs / $13,297 / −1.2 %** across **33 wallets** — 13 have ≥8 legs, 7 have ≥8 in *both* eras.

**P3 — rank persistence.** 9 wallet pairs (≥8 fit legs, ≥3 live legs): **ρ = −0.25**, permutation CI **[−0.667, +0.667]**, p(ρ≥obs) = **0.753**. On stake-independent headroom (hit% − paid%): **ρ = −0.333**. Top third by fit ROI → live **+3.0 %** (n=407); bottom third → live **+7.1 %** (n=96). *Inverted, and both CIs span zero.*

**P3b — the honest bound (simulated, not asserted).** One-sided α = 0.05, null critical value at n=9 is ρ = +0.533:

- n=9 → **57 %** power at ρ=0.6, 36 % at ρ=0.4
- n=20 → 85 % at ρ=0.6 · n=30 → 97 % · n=45 → 99 %

**20 repeat wallets** are needed for 80 % power at ρ=0.6. We have 9. At 13 wallets with ≥8 live legs and ~23 live legs/day, that is weeks away, not days.

**P4 — selection counterfactual** (pick on the fit era, read the live era):

- take-all live: −1.2 % (n=702)
- top-5 by fit ROI → **−11.1 %** CI [−35.7, +18.7]; top-10 → **−9.7 %**; top-25 → +2.8 % CI [−9.4, +18.1]
- best 10 live wallets with **hindsight** (≥10 live legs): **−3.9 %** — even choosing after the fact does not produce a positive book.

**P7 — the actual selection variable.** `WalletProfile.globalScore` vs live ROI across the 17 wallets with ≥5 live legs: **ρ = −0.045, p = 0.565**. Power at n=17 is 78 % for ρ=0.6 and 45 % for ρ=0.4 — so *a strong ordering would have shown; a moderate one can hide.* The score's own top wallet (94.9) reads −11.1 % live; the 86.1-score wallet carries 276 of 702 live legs at a −28.7 pp headroom.

**P5 — is the selected 25 better than the watch list?** Live era, booked basis: **track 508 legs +1.1 % CI [−9.8, +14.2] vs watch 194 legs −5.8 % CI [−33.9, +35.1]** — overlapping intervals, and the "better" set is inside noise of zero. Split by lane: B-200 track +0.8 % / watch −10.4 %; STANDARD track +2.6 % / watch **+26.5 %** (41 legs — the smaller set is better).

## 3. Approved path — deltas only

- **Item 1, maker shadow:** still **no Polymarket-dispatch writer** on disk (only `kalshi-maker-shadow-sim`, different venue). Day 10 of the 30-day clock; its own refutation already fired 2026-11-24 (0/32 fills at the mid).
- **Item 2, STANDARD adjudication:** today's stamp (01:44Z) — **179 legs in scope, 176 book-stamped (98.3 %), tape arm 0**, mean mid delta **−1.44c** (attainable ask sat *below* our booked price → conservative booking), refutation gate 300 legs **not met → NOT EVALUABLE**. Still **0 %** in `fillStatus`; no merge.
- **Item 3, clip cap:** `c200BandClipCaps` still absent from `src/` and from RuleSet **v73**. **Three $100 clips opened today** at 0.0594 / 0.1083 / 0.1633, TTR 8 / 23 / 12 h — all inside the px<0.20 band, all inside the 2–24 h window of the block proposed at 07:57. **90 $100 legs opened since approval** (87 settled, 3 open today, $9,000 booked); the 22 fill-adjudicated ones carry the −$710.
- **Item 4, ML re-point:** no shipped change — and its premise is now measured (§2): wallet-conditioned selection has no detected forward signal at 78 % power.
- **Item 5, LIP:** **CLOSE, seventh reading.** 514 programs on the 357 tickers we quote, **0 above the $0.0131 gate**; best measured ceiling **$0.00112** (11.7× below); measured net **+$0.0000881/contract-hour**. Global feed is 236,168 programs, 31.3 % above gate — all of it ≤2 h families we do not trade.

## 4. External (change detection; every claim dated)

- **Polymarket changelog** — no entry since **2026-11-25** (the market-clarifications endpoint, measured and refuted yesterday). Nothing new: no fee, endpoint, or liquidity-program change. docs.polymarket.com/changelog.md
- **Kalshi changelog, 2026-11-27** — decimal order entry on 58 equities markets, perps rollouts moved (metals/energy to 12-10, crypto 12-17), margin `sort_by` and corporate-action payment history. **No prediction-market fee, incentive, or liquidity change.** docs.kalshi.com/changelog
- **LIP ledger** — `scripts/lip-ledger.py --fetch` run today, verdict CLOSE (numbers in §3).
- **arXiv, q-fin.TR** — newest is unchanged since **2026-11-22**: `2611.29576` *Political Orientation and Participation in Prediction Markets* (1.14 B Polymarket transactions, 3.1 M wallets, 764 k events), already named as no-transfer yesterday. The one figure read today that sharpens the prior: **1 % of wallets account for 79.2 % of financial participation, 1 % of events 64 % of volume.** **Transfer review: still no** — descriptive network paper, no fill model, no P&L, no exclusion filter comparable to ours. It supports one prior only: the wallets we can copy are the visible tail of an extremely concentrated population, which is consistent with a crowded entry price and is *not* evidence for any rule.
- **GitHub** — no new tooling worth reading: `onchain-signals` (MIT, x402 pay-per-call agent API), `quant-polymarket-trackrecord` (public 15-day demo ledger, no licence), `alphaline-data` (Kalshi research bundles). Nothing on microstructure or wallet persistence.
- **Reddit** — r/Polymarket 404, r/Kalshi and r/algotrading 429 **sixth consecutive day**. Community signal unsampled; no forum claim used.

## 5. Ranking (expected value, not preference)

1. **Carry R1 (the ≥$60 / ttr 2–24 h block) to the operator — unchanged from 07:57, now with live evidence.** Three $100 clips opened today, all in scope. Refutation unchanged: 20 forward carried legs in the blocked class ≥0 → withdraw; or a positive book ex-top-1 is required (it reads −13.35 %). Cost 1 h. *This is Lane A: proposal, not applied.*
2. **Re-scope item 4 before anyone builds it.** Hypothesis: wallet-conditioned selection is the alpha (ML lane's durable finding). Measurement: ρ(globalScore, live ROI) = −0.045 (p=0.57, 78 % power at ρ=0.6); rank persistence ρ = −0.25 (p=0.75); fit-era selection makes the live book *worse* (−11.1 % at top-5 vs −1.2 % take-all). Decision rule: keep item 4 **open but gated** — do not re-point the objective to wallet selection until 20 wallet pairs exist; if at 20 pairs ρ < 0.4, wallet selection is not a lever and **the copy lane has no validated alpha**, which sends the remaining path to item 1 (Kalshi maker, fee 0) or to stopping. Refutation: at 20 pairs, ρ ≥ 0.6 with a CI excluding zero → the gate passes and the re-point is justified on evidence.
3. **Pre-register the item-2 reading now.** The stamp's mean mid delta is −1.44c at n=176 and the refutation only fires at 300 legs (≈ +3 legs/day → ~40 days). Record today that a negative mean means the attainable ask sat *below* our booked price — conservative booking — so day 300 is not read as a failure of the book after the fact. No rule change.
4. **Explicitly refused today:** any new predictor, any band/price floor, any wallet blacklist or promotion rule, any LIP or rebate workstream, any "pick better wallets" card. Each fails either on the fair-price test (2026-11-26), on the era cut (11-27), or on the null measured above.

## 6. Negative result

**No change is justified today on the strength of a new signal, because no signal survives measurement.** The two levers that remain are (a) a variance stop on a loss cell that is *currently filling* and already priced (+$853/60d, −13.35 % ex-top-1) and (b) a decision to *stop building* on wallet selection until the live era can test it.

The measurement that would unlock the next real decision is **20 wallet pairs with ≥8 fit and ≥8 live legs, and a forward-read of ρ at that n**. At current flow (~23 live legs/day, 13 wallets with ≥8 live legs) that is roughly a month away, which means the honest plan between now and go-live is execution and adjudication, not new predictors.

---

*Numbers re-run today from `scripts/profit-path-research.py` (artifact `data/profit-path.json`) and `scripts/profit-wallet-persistence.py` (artifact `data/wallet-persistence.json`). Both read-only; neither writes a rule, threshold, or DB column.*
