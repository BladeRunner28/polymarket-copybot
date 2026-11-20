# Profit review 2026-11-20 — the money is not in the band we keep boosting

http://localhost:3013/drafts/profit-recs-20261120

**Instrument:** `scripts/profit-marginal-cell.py` (**new**, committed with this doc; `--selftest` 6/6).
It multiplies each cell's measured EV *rate* by its measured *weight*, which no existing band table
does: `profit-velocity.py` ranks bands by $/capital-day, `profit-taker-entry.py` prices entries, and
`profit-band-report.py` reports ROI per dollar risked. EV **dollars per day** by cell was the missing
column, and it is the one a rule can move.
**Basis:** `PaperTrade` isDemo=0, opened ≥ 2026-09-01, `journal.ruleSetVersion ≥ 68`, settled, deduped
to the first leg per `bot|wallet|market|outcome` — **462 legs, $9,971 of intent notional, 23.6 days**.
Cost = `simulatedPositionSize` = **dollars at risk**. Ownership = venue minute tape (touch ≤ entry+0.1c
inside 3600s) via `profit-fill-tape.py`, reused verbatim; entry = booked price paid; the ask arm
re-prices the same exit at the quoted ask from the dispatch snapshot (±300s, 462/462 mapped).
CIs are market-clustered bootstraps, 1,500 draws. DB `mode=ro`; no RuleSet read or write.

---

## Verdict in one line

**The book loses $17.03/day, and 43% of its intent dollars sit in one cell that loses $30/day while
14% sits in the cell that earns $8.6 — and that earning cell is a 19-bet streak that the adjacent
price band, which the entry ceiling refuses, contradicts at −7.6% per dollar.**

---

## 1. The cell table (rate × weight, the number that decides allocation)

| lane / band | n | intent $/day | fill | ROI@own | EV/int | **EV$/day** | CI(EV/int) |
|---|---:|---:|---:|---:|---:|---:|---|
| B-200 0.00-0.20 | 83 | 181.7 | 65% | −23.8% | −16.5% | **−30.0** | [−46.4,+22.4] |
| B-200 0.20-0.40 | 127 | 68.1 | 54% | −18.3% | −10.0% | **−6.8** | [−27.6,+9.1] |
| B-200 0.60-0.80 | 106 | 47.3 | 67% | +7.5% | +5.5% | +2.6 | [−6.6,+16.1] |
| B-200 0.80-1.01 | 16 | 60.2 | 94% | +15.3% | +14.3% | **+8.6** | [+10.6,+17.4] |
| STANDARD 0.00-0.20 | 18 | 8.8 | 89% | +74.7% | +65.0% | +5.7 | [−59.1,+205.9] |
| STANDARD 0.20-0.40 | 43 | 21.7 | 93% | +14.6% | +13.2% | +2.9 | [−31.0,+59.5] |
| STANDARD 0.60-0.80 | 48 | 25.6 | 94% | −6.9% | −6.6% | −1.7 | [−28.1,+13.3] |
| STANDARD 0.80-1.01 | 19 | 9.1 | 89% | +18.2% | +16.1% | +1.5 | [+11.6,+19.5] |
| **B-200 total** | 334 | 357.5 | 63% | −10.0% | −7.1% | **−25.4** | — |
| **STANDARD total** | 128 | 65.1 | 92% | +14.0% | +12.9% | **+8.4** | — |

Two facts fall out that no prior table showed together:

- **The lane split is inverted against the measured edge.** C-200 carries 87% of the notional and
  loses $25.4/day at a 63% fill rate; STANDARD carries 13% at a 92% fill rate and earns $8.4/day.
- **The allocation is inverted inside C-200.** 43.0% of the intent dollars go to the one cell losing
  $30/day; 14.2% go to the only cell whose CI excludes zero on the positive side.

## 2. Inside the losing cell: the loss is a clip tier, not a price class

C-200 0.00-0.20, tape-owned only, split by clip:

| tier | legs | owned | intent $ | EV/int | hit rate | avg price paid |
|---|---:|---:|---:|---:|---:|---:|
| < $25 | 48 | 29 | 937 | **+39.5%** | 17% | 0.104 |
| ≥ $50 | 35 | 25 | 3,350 | **−32.1%** | 8% | 0.119 |

The ≥$50 tier is **78% of the cell's notional** and it buys 11.9c longshots that win 8% of the time —
against a 11.9% break-even. The <$25 tier buys 10.4c longshots that win 17% and makes +39.5%. Same
band, same wallets, opposite signs, and the sizing model is putting four times the money into the
bad half. This is the payoff asymmetry in its purest form: at 0.10 a two-point hit-rate error is worth
+40%, at 0.50 the same error is invisible.

Why the big clips: `data/premium-calibration.json` (refit 2026-11-15) carries λ̂ = **−0.5308** for
0.00-0.20, which prices q ≈ **28%** at a 13.5c ask. `kellyMaxSizeUsd` is 100 and Kelly funds these legs
to that ceiling. The owned population's hit rate in the same band is **13.0% pooled (7/54)** — tier
split 17.2% under $25 and 8.0% at $50+ — with a 95% upper bound of **24.9%**, below the 28% the table
asserts but not comfortably. The sizing input is not supported by the population the book owns.

## 3. The "only positive cell" is contradicted by the band the ceiling refuses

`c200MaxEntryPrice` = 0.80 and `standardMaxEntryPrice` = 0.85, so candidates priced above the cap are
never acted and never marked. 131 deduped skip decisions at price ≥ 0.85 exist in the regime; the venue
archive resolves **115 of 131 (88%)**:

| price bucket | n bets | hit | avg price | break-even | EV/$1 | at +1c |
|---|---:|---:|---:|---:|---:|---:|
| all ≥ 0.85 | 115 | 95.7% | 0.962 | 96.2% | −0.6% | −1.0% |
| 0.85-0.90 | 21 | **81.0%** | 0.879 | 87.9% | **−7.6%** | −8.7% |
| 0.90-0.95 | 21 | 95.2% | 0.926 | 92.6% | +2.8% | +1.7% |
| 0.95+ | 73 | 100.0% | 0.996 | 99.6% | +0.4% | +0.4% |

The acted 0.80-1.01 cell shows +14.3% EV/int with **26 wins and 0 losses** — but that is **26 legs
over 19 distinct bets from 3 wallets, all sports**, and 19/19 at an 0.86 average has a 5.7% chance
under fair pricing. One price bucket higher, on a *larger* and fully independent sample (21 bets),
the same trade shape wins 81% against an 87.9% break-even. **The favourite cell is a streak, not an
edge, and the ceiling is not censoring a paying population.** The 0.95+ row is the already-decided
class: 73 bets at 100%, +0.4% per dollar, i.e. nothing after any fee.

## 4. What the cap is actually worth (corrected from yesterday's $57/day)

The approved $25 cap on C-200 0.00-0.20 (approved 2026-11-12, field never written — v73's rulesJson
carries no `c200ClipCapUsd`) rescales the ≥$50 tier, which is $3,350 of the cell's $4,287:

- applied at the **tier's own rate** (−32.1%): 75% of $3,350 removed → **+$34.2/day**
- applied at the **cell's pooled rate** (−16.5%): **+$17.7/day**
- realised rescale on the same legs: **+$34.03/day**, but its **ex-top-3 remainder is −$22.32/day**

So the honest underwriting range is **+$17 to +$34/day, and the low end is the one to believe** — the
top of the range is carried by three legs. A $15 cap reads +$34.59/day with an ex-top-3 remainder of
−$14.74/day, i.e. strictly better on every line, but the difference is inside noise.

## 5. Capital velocity says the same thing

| band | owned $ | EV $ | capital-days | $/capital-day |
|---|---:|---:|---:|---:|
| 0.00-0.20 | 3,154 | −571.7 | 3,446 | **−0.17** |
| 0.20-0.40 | 1,343 | −93.6 | 758 | −0.12 |
| 0.60-0.80 | 1,404 | +22.3 | 1,411 | +0.02 |
| 0.80-1.01 | 1,510 | +237.0 | 876 | **+0.27** |

The book puts the majority of its capital-time into a band that returns −17 cents per $100 of capital
per day, and the band that returns +27 cents gets 15% of the capital. Turnover is not the constraint
here (hold times are 0.6-1.1 days on the owned class); the sign per capital-day is.

## 6. Stability

Split at the window median: 0.00-0.20 reads −18.7% then −9.5% (same sign), 0.20-0.40 −8.5% then
−0.9%, 0.80-1.01 +14.8% then +13.4% (n=6 in the second half — the streak is 88% first-half).
Nothing flips sign, and nothing in the second half is large enough to promote.

---

## Recommendations

### R1 — Ship the approved $25 cap on C-200 0.00-0.20; underwrite it at +$17/day, not +$34
- **Hypothesis:** the cheap band's loss is a clip-tier effect, so capping the tier removes most of the
  loss without touching which candidates are admitted.
- **Measurement:** `python3 scripts/profit-marginal-cell.py` §S9 (tier table) and §S4 (cap shadow with
  the tail removed). Reads `PaperTrade` + the fill-tape cache; DB `mode=ro`.
- **Decision rule:** ship when the ≥$50 tier is ≥50% of the cell's notional AND its EV/int is ≤ the
  <$25 tier's by ≥30pp. Measured: 78% of notional, −32.1% vs +39.5%, a 71.6pp gap.
- **Refutation:** 100 forward cheap legs with clip ≥ $50 earning ≥ the <$25 tier's ROI → the tier
  split is noise and the cap is withdrawn.
- **Effect:** +$17.7/day at the cell's rate, +$34/day at the tier's, −$22/day ex-top-3 on the realised
  rescale. Cost **1h** (the four call-site edits are already specified in the card).
- **Honest caveat:** this is variance reduction with a positive expected sign, not an edge creation.
  The band at $25 is still a coin-flip loser on its own record; the cell should not be sized up again
  on the strength of the <$25 tier's +39.5% (29 owned legs).

### R2 — Keep the entry-price ceiling where it is; stop crediting the favourite cell as an edge
- **Hypothesis:** the 0.80-1.01 cell's +14.3% EV/int is a 19-bet streak, and the population the ceiling
  refuses at 0.85-0.90 loses money.
- **Measurement:** §S8 of the same script — 131 deduped skips ≥0.85 marked against
  `clob.polymarket.com/markets/<conditionId>` `tokens[].winner` (115 resolvable, 88%).
- **Decision rule:** keep `c200MaxEntryPrice` 0.80 / `standardMaxEntryPrice` 0.85 while any forward
  sample at 0.85-0.90 fails to clear price + 5pp at the ask. Measured: 81.0% hit vs 87.9%, −7.6%/$1.
- **Refutation:** ≥100 acted bets in 0.85-0.90 clearing price+5pp at the ask → the ceiling is
  censoring value and this recommendation is wrong.
- **Effect:** $0 today; it stops a $8.6/day extrapolation that a single extra 5pp of price would have
  turned into a real size increase in a −7.6% population. Cost **0h** (decision, no code).
- **Reported, not resolved:** the journal records `reasonsJson: []` on 27,106 skips, so this is the
  *price*-conditional population, not the *cap*-conditional one. Some of these 131 would have been
  refused by the score or liquidity gates anyway; the price evidence is what a cap raise would buy.

### R3 — Refit the cheap band's λ̂ on the population the book owns, not on wallet prints
- **Hypothesis:** λ̂ = −0.5308 (q ≈ 28% at a 13.5c ask) is fitted on wallet prints and does not survive
  the fill filter; on owned legs the same band prices at 8-17%, which is why Kelly funds $100 clips
  into a −32% tier.
- **Measurement:** `scripts/calibrate-premium.py` refit restricted to tape-owned legs (`filled_tape`
  from the fill-tape cache), printing the printed-population and owned-population λ̂ side by side per
  band, with n and the implied q at the band median price.
- **Decision rule:** if the owned-population λ̂ for 0.00-0.20 is ≥ −0.20 (q ≤ ~20%), the Kelly input is
  over-betting by ~3x and the cheap-band size must be re-derived from the owned λ̂ rather than capped
  ad hoc; ship as a new λ̂ table (one file, one field, revert = restore `premium-calibration.json`).
- **Refutation:** an owned cheap-band sample of ≥100 legs hitting ≥ 28% → the printed λ̂ stands, the
  gap is fill noise, and only R1 (a cap) is justified.
- **Effect:** makes R1 permanent instead of a band-aid, and stops the next refit (2026-12-01) from
  re-inflating the clip. Cost **2h**.

**Ranking:** R1 (the only measured dollar gain, and already approved) → R2 (free, and it prevents the
one change that today's data would otherwise invite) → R3 (removes the cause R1 only caps).

## IF YOU WEREN'T HERE

Ship the $25 cap on C-200 0.00-0.20 and do **not** lift the 0.85 entry ceiling. The cheap band's
≥$50 tier is 78% of that cell's notional and loses 32 cents per intent-dollar on 25 owned legs; the
band just above the ceiling, measured on 21 independent bets, wins 81% against an 87.9% break-even.
The first is a leak you can close today; the second is a streak that would become a size increase.
