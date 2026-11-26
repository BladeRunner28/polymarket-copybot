# 2026-11-26 — the filled loss is two boxes, and neither is a forecast

http://localhost:3013/drafts/profit-research-20261126

**Instrument (committed with this doc):** `scripts/fill-price-truth.py` (new) on top of
`scripts/profit-path-research.py`. Every figure below re-runs from those two; nothing hand-computed.

**Basis.** Same as `profit-path-research.py` unless stated: cost = `simulatedPositionSize`
(**dollars at risk**), PnL = `realizedPnl` where `status IN ('closed','resolved')` (TR-15 OR),
`isDemo=0`, dedupe = first leg per `botId|walletAddress|marketId|outcome`, clock = entry vintage,
CI = market-clustered bootstrap (2,000 draws, resample **markets**).

**New basis, stated once, because it disagrees with yesterday:** `fill-price-truth.py` keeps only
`status='resolved'` for anything it calls a *price*, because an early exit's payout is an exit
price and "was this contract worth what we paid" is undefined on it. So the cents-per-contract
cells read on n=2,364 resolved legs, not the TR-15 n=6,153. The ROI table stays on TR-15 and is
quoted from `profit-path-research.py` unchanged.

---

## The one thing

**Win rates in this book match the prices they paid. Everywhere.** So the loss cannot be a
forecasting defect — there is nothing left for a predictor to fix — and the money that is
missing is in two mechanical boxes: one clip size, and the exit path.

The proof is a per-contract measure the ROI column cannot show:

> realised payout per share − entry price, in cents, dollar-weighted.
> 0c = we paid exactly what the contract was worth. Negative = we overpaid.

| cohort | legs | cost | PnL | ROI | cents/contract | CI95 |
|---|---:|---:|---:|---:|---:|---|
| filled, natural settlement | 273 | $3,989 | −$376 | −9.4% | **−1.51c** | [−7.72, +7.04] |
| filled, closed early | 47 | $887 | −$450 | −50.8% | **−7.13c** | [−10.24, −5.29] |
| unfilled (never traded) | 568 | — | — | +31.4% | +6.06c | [+1.32, +11.18] |
| unadjudicated | 1,523 | — | — | +10.9% | +2.76c | [−0.31, +7.00] |

Two things fall out. First, the whole "we make money" story is **+6.06c on the legs we never
traded** and **−1.51c on the legs we did** — the same 7.6c swing that every day since 11-17 has
described, now priced per contract instead of per dollar of stake. Second, the filled number
spans zero: **the point estimate says we overpaid 1.5c; the data cannot reject that we paid fair.**

And the win-rate check says we paid fair. Filled legs won 44.7% of the time at a leg-mean price
of 39.8% — one-sided binomial p = 0.96. Every filled cell is the same story:

| filled cell | n | won | price implied | p(fair) |
|---|---:|---:|---:|---:|
| all filled | 273 | 44.7% | 39.8% | 0.96 |
| 0.20–0.40 | 114 | 30.7% | 30.9% | 0.53 |
| 0.40–0.60 | 67 | 58.2% | 48.7% | 0.95 |
| 0.60–0.80 | 53 | 81.1% | 67.6% | 0.99 |
| $100 clip | 17 | 11.8% | 13.9% | 0.57 |

**No cell in this book forecasts differently from its own price.** That is the fifth independent
route to the same conclusion as the ML lane (0/15 hits, every arm ≤ price): the price contains it.

One cell *does* reject fair pricing, and it rejects the other way: unfilled 0.20–0.40, 211 legs,
20.9% won against 30.9% implied, p = 0.001 — **fewer wins than the price, and still +20.8%**. That
can only be a payoff mix (a few cheap winners at 3–5x), i.e. variance, not skill. It is the
cleanest single proof that this book's profits are draws, not edges.

## The loss has two addresses, and they add up

The filled book splits 2×2 and reconciles to the headline exactly:

| box | legs | cost | PnL | ROI |
|---|---:|---:|---:|---:|
| natural settlement, ordinary clips | 256 | $2,289 | **+$59** | **+2.6%** |
| natural settlement, $100 clip | 17 | $1,700 | −$435 | −25.6% |
| closed early, ordinary clips | 42 | $387 | **−$176** | **−45.5%** |
| closed early, $100 clip | 5 | $500 | −$274 | −54.9% |
| **total (TR-15 OR)** | **320** | **$4,876** | **−$827** | **−17.0%** |

- **80% of filled legs (256) are flat: +$59 on $2,289.** Not profitable, not losing — dead even.
- **$100 clips: 22 legs, −$710 = 86% of the filled loss.** Unchanged from yesterday.
- **Early exits: 47 legs, −$450 = 54% of the loss, on 18% of the risk.** This is the box nobody
  has been ranking. It is not a small-n artifact: 42 of those 47 are ordinary clips, −8.67c per
  contract, CI [−13.58, −4.93], and the sign holds after its three best legs (−10.02c).

The $100 cap and the exit path overlap on 5 legs (−$274). They are not additive substitutions;
together they cover the entire provable loss.

## What this changes about the $100 cap

Not the action — the reason, and therefore the decision rule.

The cap has been argued as "the $100 tier is a bad bet". Per contract it is not: **−2.99c,
CI [−12.40, +10.88], p(fair) = 0.57** on 17 settled legs. It is the *same* bet as the ordinary
clip, 8.5x bigger (855 contracts at px 0.117 vs ~55 at px 0.33). A cap on it therefore buys
**drawdown, not edge**, and any forward gain it books is a variance selection.

That matters because today's review (0de1e2d4) prices a variant of this at **+$39.02/day, delta CI
[+622, +1,666]**, on a different population (ruleSetVersion ≥ 68, 686 legs, booked basis, both
fill classes). It is the best-priced rule on that board and I am not arguing against its
arithmetic. I am flagging what would let it down: **a rule whose gain comes from removing
fair-odds high-variance legs keeps its gain only if the removed class keeps losing per contract.**
Falsifier, forward: over the next 40 settled $100-tier legs, per-contract gap ≥ +2.99c — then the
tier is fair-priced and the +$39/day was the draw. This is the §3 refutation, restated in the unit
that can actually settle it.

## Approved path — deltas only

| # | item | state today | delta |
|---|---|---|---|
| 1 | maker-vs-taker shadow | **no writer in repo, day 9 of 30** | none. And its own refutation already fired: 0/32 fills at the mid (2026-11-24) |
| 2 | STANDARD fill adjudication | DB **0 / 10,065 legs (0.0%), day 9**; today's stamp `standard-fill-stamp-20261126.jsonl` = **174/177 book arm, tape arm 0**, `NOT EVALUABLE` (gate n≥300) | stamp advanced +3 legs; nothing merged |
| 3 | $100 clip cap | RuleSet **v73, written 2026-11-13**, no cap field, no reader in `src/` — day 14 | none |
| 4 | ML objective re-point | not started; daily gate still outcome AUC | none |
| 5 | LIP | live menu **9,095 programs, 0 above gate**, max ceiling 0.003529 | menu +1,249 programs (7,846 yesterday), still 0. Verdict CLOSE |

Item 2 is still the gate and it is now the *only* gate: every cents-per-contract number above and
every ROI on the filled side reads on **one lane** (`filled_by_lane` returns BANKROLL_200 only).
STANDARD is 77% of settled legs and contributes zero fills, so nothing here can be tested against
the class that carries the booked profit.

## External — change detection, no imports

- **Polymarket changelog** — no new entry since **2026-11-25** (market-clarifications endpoint,
  measured and refuted yesterday at 2.3% of risk, worth ≤$160). The 2026-11-20 fee/rebate repricing
  is in force; no further fee change. `docs.polymarket.com/changelog.md`, checked 2026-11-26.
- **Kalshi changelog** — 2026-11-26 and 2026-11-27 entries are all Margin/equities/perp plumbing
  and on-request market mechanics (decimal order entry rollout, `sort_by=event_ticker`,
  corporate-action payments, RFQ listener mode). **No fee change, no liquidity-program change, no
  wallet-attribution surface.** One line is mildly useful and not to us: `GET /historical/fills`
  now takes 100 tickers — our own account fills, and we hold no Kalshi key.
- **Kalshi LIP** — `lip-ledger.py --fetch`, 2026-11-26: feed 234,377 programs, **live menu
  (active+upcoming) 9,095, above gate 0 (0.0%)**, max live ceiling **0.003529**; measured net
  **+0.0000884 $/contract-hour** vs a **0.0131** gate — 148x below; best measured program ceiling
  0.001120 is 11.7x below even at 100% share. **DECISION: CLOSE.** Unchanged for the 6th reading.
- **Forums** — **blocked, third day**: `reddit.com/r/Polymarket/new/.rss` → 404, `r/Kalshi` and
  `r/algotrading` → 429, `old.reddit.com` → 302 to login. Recorded as a gap, not as "no discussion".
- **arXiv q-fin.TR** (25 newest, 2026-11-26) — nothing on prediction-market microstructure. Two
  worth naming as *hypotheses only*: `2611.29576` (2026-11-22) political orientation vs stake size
  in prediction markets — participation, not execution, no transfer to a 0.05–0.60 copy book; and
  `2611.18934` (2026-11-13), a pre-registered audit of 91 LLM-trading papers finding short windows,
  unmodelled costs and unknown cutoffs. That one is a mirror of our own ML-lane result and argues
  for keeping the AUC gate where it is, not for relaxing it.
- **GitHub** — `topic:prediction-markets` query returned 0 items; `q=kalshi&sort=updated` returns
  ~10 repos all pushed 2026-11-26, every one a dashboard/feed/ledger bot with no licence stated.
  Read-only, nothing to adopt.

## Ranking — where the money can actually be made

1. **Merge the STANDARD stamp into `fillStatus`** (item 2, approved, Lane B). It is the only action
   that increases the measurable population; 174 stamped legs at 98.3% book coverage are sitting
   unmerged on day 9, and every cents-per-contract figure in this doc is single-lane until they
   land. Nothing else on the board can be validated without it. *Refuted by:* a merge that moves
   the STANDARD filled ROI into the same band as C-200's — which would mean the lane is fine and the
   gate was never the problem.
2. **Execute the $100 cap** (item 3, approved, Lane A) — 22 legs, −$710, 86% of the filled loss,
   and the field still does not exist in v73 after 14 days. Ship it as drawdown control at EV≈0
   (per-contract −2.99c, CI spans zero), not as an edge fix. *Refuted by:* 40 forward settled
   $100-tier legs at ≥ +2.99c/contract.
3. **Do not add a price floor.** Measured and refused today: the floor counterfactual is
   non-monotone (+9.4% at 0.10, +4.7% at 0.20, +1.2% at 0.30, +15.1% at 0.40) and **every CI spans
   zero** on 273 legs. The one negative cell with an excluding CI (`0.00–0.10`, −6.70c) is 13 legs
   with 0 wins at a 0.067 price — p(fair) = 0.41, so it is an accounting fact, not an edge. A floor
   here would be fitted to a draw.
4. **Do not start the ML lane on fill prediction yet.** The win rates above are already at price;
   a fill model has nothing to beat that a price does not already say, and item 4's own refutation
   (cannot beat a constant fill-rate baseline) is the only test that would justify it. Waiting on
   #1 costs nothing.
5. **Do not build a LIP lane.** 0 of 9,095 live programs clear the gate; 6th consecutive reading.

The exit box (54% of the loss, CI excludes zero) is already priced: `profit-fast-adverse-stop-20261118.md`
puts an improved stop at ~**+$5/day** and explicitly ranks it behind the clip. Today's 2×2 is
consistent with that read and does not move it up.

## What would unlock a change tomorrow

- Item 2 merge lands → the same 2×2 re-run on the full filled class across both lanes instead of
  one, and the first cents-per-contract read on the question-market class that carries the +$6,212.
- Or the $100 tier's forward per-contract gap turning negative with a CI that excludes zero on
  ≥40 settled legs — that converts the cap from variance control to an edge claim.

Absent one of those, no change is justified today.

---

**Basis deltas vs prior days, so nothing is read as a trend:**
`filled ROI −17.0% (n=320)` vs yesterday `−17.2% (n=315)` — same basis, 5 new settled legs.
`$100 clip −$710 / 22 legs` — unchanged since 11-21.
`cents-per-contract` is a **new measure**, not a restatement: it is PnL per share, so it cannot be
inflated by stake size, and it re-reads the book as fair-priced where the ROI column reads as a
loss. That is a basis change in the strict sense — the 2×2 above and yesterday's ROI sentence are
not measuring the same thing, and the difference between them *is* the finding.
