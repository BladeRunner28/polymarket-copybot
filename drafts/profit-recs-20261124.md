# PROFIT REVIEW — 2026-11-24

http://localhost:3013/drafts/profit-recs-20261124

**Instrument (committed with this doc):** `scripts/profit-tenor.py`, extended today with **§S20–S23**
(`--selftest` **13/13** PASS). Re-run: `python3 scripts/profit-tenor.py` (DB `mode=ro`; tape cached
under `data/fill-tape-cache`, no writes, 2 s warm). Every figure below prints from that run.
**Population:** 603 settled deduped legs / 497 markets, `ruleSetVersion ≥ 68`, 2026-09-01…2026-11-24
(27.1 days), **cost = `simulatedPositionSize` = dollars at risk** (never size × price), dedupe = first
leg per `bot|wallet|market|outcome`, tenor = `timeToResolution` at entry, CIs = market-clustered
bootstrap (2,000 draws). Fees are **not** netted here (a fee is ~2–4% of notional against 5–20%
effects; `profit-fee-net.py` owns the law — it moves levels, not this ranking).
**Fill basis, stated once.** `touch(W)` = the venue minute tape (`clob.polymarket.com/prices-history`,
keyless, retroactive) printed a MID at or below the price we bid inside W of dispatch. Necessary, not
sufficient (queue position unmodelled): the reachable class is an upper bound on what we own. Three
bases are printed for every rule — **booked** (the ledger as filed), **touched 1h** (a resting bid's
hour, the headline), **touched 5min** (the strict variant).

---

## The one thing

**The defect is not the band. It is the tenor — and the approved card is a proxy that pays less.**

A **main-path leg resolving inside 24 hours** is where the book loses everything: 184 legs / 122 markets /
$4,906 at risk / **−$998.6 (−20.4%)** — and C-200's 83 of those legs carry **−$957.9** while STANDARD's
101 carry −$40.7 (its clips are capped at $20, so it cannot take the big position). It is the only cell
in the entire book whose market-clustered PnL CI excludes zero on the loss side (booked
**CI [−1,883.5, −11.9]**). Inside it the $60+ clip tier is **−38.2%** (30 legs / $3,000 / −$1,144.7)
while the same book's $15–30 tier is **+13.2%** (115 legs / 24 wallets / ex-top-3 still +3.1%).

Capping that scope at **$10** — the size the short-TTR lane already uses — is worth **+$861.77 over
27.1 days (+$31.74/day) booked**, **+$1,049.15 (+$38.65/day)** at 1h, **+$744.78 (+$27.43/day)** at
5min. It is the **only** rule in today's matrix whose delta CI excludes zero on all three bases
([+169,+1589] / [+494,+1697] / [+280,+1288]), and it is broad — the top single leg is 10% of the delta,
ex-top-5 is still +$411 booked.

The approved $25 cheap-band cap, priced on the same run, is **+$706.60 (+$26.03/day) booked**,
+$805.77 (+$29.68/day) at 1h, +$943.21 (+$34.74/day) at 5min — its CI excludes zero on **one** basis
out of three. And the two rules are **substitutes, not complements**: shipped together the book earns
+$721.3 booked, *less* than the tenor rule alone (+$797.1). Adding the approved cap on top of the tenor
cap is worth **−$2.79/day booked, −$3.24/day at 1h**. It is a partial proxy for the same legs, priced
$5/day worse.

**Yesterday's ranking was an ordering artifact and I own it.** I priced the tenor cap only *after* the
approved cap and got +$5.72/day at 1h, so I ranked it second. Priced standalone on today's larger
population it is **$38.65/day at 1h** — bigger than the rule that has been approved for thirteen days.
The right comparison is standalone *and* marginal; I printed only the marginal.

---

## 1. The clip is the anti-signal, and it is broad and stable

`§S11`. Main path (non-lane), booked, clip tiers — cost = dollars at risk:

| clip tier | legs | wallets | $ at risk | PnL | ROI | ex-top-1 | halves |
|---|---:|---:|---:|---:|---:|---:|---|
| < $15 | 333 | — | $3,042 | +$27.9 | +0.9% | — | — |
| $15–30 | 115 | 24 | $2,116 | +$279.5 | **+13.2%** | +8.1% | +13.0 / +13.4% |
| $30–60 | 3 | — | $150 | +$240.3 | +160.2% | — | n=3, ignore |
| ≥ $60 | 48 | 16 | $4,800 | **−$991.4** | **−20.7%** | **−32.8%** | −21.1 / −20.2% |

Three things make this a rule rather than a tail: the loss **deepens** when the best leg is removed
(−20.7% → −32.8%), it is **identical in both halves** of the window (−21.1% / −20.2%), and the winning
tier is broader (24 wallets) than the losing one (16). The sizer puts **$26.7** on the average
main-path short-dated leg and **$11.5** on the average short-TTR lane leg — and the lane earns
**+12.1%** while the Kelly copy earns **−20.4%** (`§S9`). Volume is allocated inverse to edge inside
the same 24 hours.

## 2. One matrix settles both clip cards — and the lane-wide card is wrong on its premise

`§S20`. $/day in the cell's own PnL, 27.1-day window. Three bases per cell: booked / 1h / 5min.

| scope | $10 | $20 | $25 | $40 |
|---|---|---|---|---|
| C-200 Kelly path, lane-wide | +25.1 / +32.6 / +36.4 | +24.2 / +28.7 / +34.1 | +23.2 / +26.9 / +32.0 | +20.3 / +21.5 / +25.7 |
| approved: px < 0.20 | +28.6 / +34.3 / **+42.9** | +27.3 / +31.7 / +37.1 | +26.0 / +29.7 / +34.7 | +22.3 / +23.6 / +27.7 |
| **2–24h C-200 Kelly** | **+31.7 / +38.7 / +27.4** | +28.4 / +33.4 / +24.5 | +27.2 / +31.3 / +23.0 | +23.5 / +25.2 / +18.5 |
| px<0.20 AND 2–24h | +33.2 / +39.8 / +29.9 | +30.2 / +35.1 / +26.3 | +28.8 / +32.9 / +24.6 | +24.7 / +26.3 / +19.7 |
| every leg, incl. the $10 lane | +14.4 / +22.8 / +28.5 | — | — | — |

- **Level:** $10 is the best level in every scope except lane-wide ($20 there). On the approved scope $10
  beats $25 on **all three** bases (+$28.6 vs +$26.0, +$34.3 vs +$29.7, +$42.9 vs +$34.7).
- **Scope:** lane-wide $25 is **dominated** by the band-scoped $25 on all three bases. The Backlog card
  `profit-c200-clip-cap-25` argued the defect is *clip-specific, so the band-scoped cap under-reaches*
  (+$102.9 over 17.8d). On the 27.1-day / 603-leg population the opposite holds: the extra non-cheap
  $100 clips the lane-wide cap reaches are **net profitable** (capping them costs $75.7). Band-scoping
  is correct; the card's premise is falsified.
- **Do not cap the lane.** "Every leg" at $10 is **$6–7/day worse** than the same cap on the Kelly path:
  the short-TTR lane pays (+10.3%, S11), and shaving its $11.5 clips cuts winners.
- **Delta CIs, booked / 1h / 5min:** tenor $10 **[+169,+1589] / [+494,+1697] / [+280,+1288]**;
  tenor $25 [+225,+1332] / [+392,+1380] / [+242,+1074]; approved $25 [−432,+1595] / [−265,+1679] /
  [+500,+1464]; lane-wide $10 [−746,+1782] / [−415,+1935] / [+438,+1626]. **Tenor-scoping is what
  buys the CI; the level buys $2–4/day.**

## 3. Recency: this is the live regime, not a historical artefact

`§S21`. Median-split of `openedAt`, plus the trailing 7 days:

| cell | half 1 | half 2 | last 7d |
|---|---|---|---|
| main-path 2–24h (all) | 112 legs, −5.5% | 72 legs, **−43.0%** | 36 legs, **−36.6%** |
| main-path 2–24h, $60+ clips | 18, −24.7% | 12, −58.3% | 6, −66.7% |
| cheap $100 clips (px<0.20, >$25) | 21, −30.0% | 17, −16.7% | 6, −66.7% |
| main-path $15–30 clips | 75, +13.8% | 40, +12.1% | 16, **+2.8%** |

The short-dated Kelly loss is **accelerating**; the cheap-band loss is stable-to-improving (it is the
same legs, arriving earlier). The one positive tier is **decaying** (+13.8% → +2.8%). So the tenor cap
is not a fix for a past mistake — it is the only rule here pointing the same way the current regime is.

## 4. The refusals — three shapes that look right and are not

- **Per-event cap instead of per-leg.** `§S22`, exact port of the pre-registered family rule
  (`src/lib/event-family.ts`). Per-event $25 = +$640.16 (+$23.58/day) vs per-leg lane-wide $25
  +$630.95 (+$23.24/day) — the same rule wearing a different name, and it resizes 216 legs. The reason
  is decisive: the cheap cap's target class is **27 legs in 24 families, max 3 legs/family**. There is
  no correlated block to cap. Do not build it.
- **Upsize the $15–30 clip tier** (+13.2%, 24 wallets, stable halves). Refused on two numbers: ex-top-10
  is **−11.7%** (ten legs carry it) and the trailing 7 days read **+2.8%**. Unlocks on: 150 forward
  $15–30 legs at ≥ +10% with ex-top-10 ≥ 0.
- **Tight-scope stacking.** The `px<0.20 AND 2–24h` intersection is the best cell in the matrix on all
  three bases (+$33.2 / +$39.8 / +$29.9 per day) — but it beats the one-condition tenor rule by only
  **$1.2–2.4/day** on 22 binds instead of 81, inside the CI width. Two conditions bought for a rounding
  error; I do not recommend it.
- Unchanged from yesterday and still not stackable: upsize the short-TTR lane (one wallet carries
  $352 of $350; ex-top-3 −8.5%), upsize 0.80–0.85 favourites (0 losses in 32 legs is n=32), the
  long-dated $20 cap (+$11.21 after the approved cap = +$0.41/day).

## 5. Ladder arithmetic: the rung is gated on the tier we are now cutting

`§S23`. Post-rule the book turns over **$319/day of risk** (22.2 settled legs/day × $14.36) at **+9.2%**
= **$29.36/day**.

- $250/day at +9.2% needs **$2,715/day of risk**: 272 legs/day at $10, 109 at $25, or **27 at $100**.
- $500/day needs 543 / 217 / **54**.

Today's flow is 22.2 legs/day. So rung 1 is arithmetically reachable **only** through the $100 clip tier
— the tier measured at **−20.7%** — or through ~12× the current flow. That is the honest strategic
statement: sizing cannot produce the rung, and the one configuration that could is the one the data says
to stop funding. Everything in this review is worth ~10–12% of rung 1; the rung itself is a flow problem,
and the gates that would have to move are the gates that closed NO-CHANGE under their own shadow reads.

Related, unmeasured-but-not-new: the open book carries **358 open 90d+ legs / $3,841 / 430,943
capital-days** against −$319 of booked unrealised. At the settled 7d+ base rate (−13.8%) that is ≈−$530
(3,841 × 13.8%) of unrealised expected loss arriving over 4–14 months. Capacity is still not the
constraint — `§S23` prints cash $7,122 vs $4,181 open on STANDARD and $6,717 vs $489 on C-200 — so this
stays a scoreboard fact, not a lever.

---

# Recommendations, ranked by expected value

### R1 — Cap C-200 Kelly clips at $10 when the leg resolves inside 24h. **+$31.74/day booked. 1h. Lane A.**

- **Hypothesis.** A Kelly-sized leg with under 24h to resolution has no time for the price to converge
  on our thesis; flat-sizing it at the lane's $10 removes a loss concentrated in the $60+ tier without
  touching the $15–30 tier that pays.
- **Measurement.** `scripts/profit-tenor.py` §S20/§S21/§S23 (committed today). Scope
  `botId = BANKROLL_200 AND lane ≠ short_ttr AND 0 < ttr < 24h` — the exact population
  `score-trades.ts:921` sends through the Kelly sizer. Delta **+$861.77 booked (+$31.74/day), CI
  [+169,+1589]**; **+$1,049.15 (+$38.65/day), CI [+494,+1697]** at 1h; **+$744.78 (+$27.43/day), CI
  [+280,+1288]** at 5min; 81 / 55 / 41 legs resized; post-rule book **+9.2% / +9.6% / +2.0%** from
  −0.5% / −5.5% / −9.8%. Top single leg is 10% of the delta, ex-top-5 still +$411 booked.
- **Decision rule.** Ship `mainPathShortTtrClipUsd` (already specified on card
  `profit-mainpath-short-tenor-clip`, default `0` = off) at **10**, applied in `openPaperTrade`
  **after** `clampPaperSize` — so it lands after the v57-B long-shot rail that *floors* cheap legs, which
  is the one real ordering hazard. `maturityTtrHours` is already passed for every lane
  (`score-trades.ts:1286`), so the edit is one Rules field, one parser branch, one clamp. Then a boundary
  probe at ttr 23.99/24.00/24.01 × clip 9.99/10.00/10.01, plus one live cycle proving a $100 main-path
  2–24h leg books $10 while a $100 25–48h leg books $100 and the lane's $10 legs are untouched.
- **Refutation.** A forward 150 main-path 2–24h legs (tape-touch basis) at **≥ 0 ROI**, or ex-top-5 ≥ 0,
  or the capped book trailing its uncapped shadow by **≥ $150 with a CI excluding zero** over 30 days →
  revert the field to `0` (byte-identical).

### R2 — If the approved cheap-band field ships, ship it at **$10, not $25** — and not alongside R1. **+$2.6/day. 1h. Lane A.**

- **Hypothesis.** The approved card's *shape* is right (band-scoped, defaulted empty) and its *level* is
  wrong: the band's $25–100 legs lose so much that the deeper cut pays more, on every fill basis.
- **Measurement.** `§S20`: px<0.20 at $10 = **+$776.28 (+$28.59/day)** / **+$931.84 (+$34.33)** /
  **+$1,165.46 (+$42.93)** vs $25 = +$706.60 / +$805.77 / +$943.21. $10 strictly dominates $25 on all
  three bases, is the strongest single rule on the strict 5-min basis (CI **[+619,+1805]**), and binds
  45 legs. Against R1 it is a **substitute**: given the tenor cap it adds **−$2.79/day booked**
  (−$3.24 at 1h, +$10.11 at 5min).
- **Decision rule.** If the 24h condition is judged too invasive for the sizer, ship the same four edits
  the 2026-11-12 draft already specifies with `c200BandClipCaps = "0.0-0.2:10"` instead of `"0.0-0.2:25"`,
  via `apply-v73 --yes`, with the boundary probe at px 0.1999/0.2000/0.2001 × clip 9.99/10.00/10.01.
  **Never in the same window as R1** — the pair is measured to be worth less than R1 alone.
- **Refutation.** A forward 40 settled cheap-band legs clipped at $10 whose tape-touch ROI is ≥ +10%, or
  the $10-capped book underperforming its $25-capped shadow by ≥ $100 with a CI excluding zero → revert.

### R3 — Nothing else. The ladder arithmetic is the finding, not a task.

- **Hypothesis.** No remaining sizing change can move the book toward rung 1, and the rung is gated on
  flow or on the $100 tier that loses.
- **Measurement.** `§S23` (post-R1 $319/day of risk at +9.2% = $29.36/day; 272 legs/day at $10 or 27 at
  $100 for $250/day; the $100 tier at −20.7%). `§S22` per-event cap null. `§S20` lane-wide $25 dominated.
- **Decision rule.** Do not open a new sizing proposal until one of: (a) forward flow exceeds 60 settled
  legs/day for 14 days, (b) a cell with ≥100 legs and ex-top-5 ≥ +5% appears, or (c) the $100 tier's
  forward 40 legs clear +0% on the tape-touch basis. Until then, sizing work is variance, not edge.
- **Refutation.** A 14-day forward window at ≥ 60 legs/day whose book still reads < +5% on the 1h basis —
  that would mean flow is not the binding constraint either, and the whole ladder model needs re-opening.

**IF YOU WEREN'T HERE:** implement `mainPathShortTtrClipUsd = 10` and apply it — the only scope in this
book whose loss CI excludes zero on all three fill bases, and the only one that pays more than the card
that has been sitting approved and unbuilt for thirteen days.

---

## Corrections and contradictions carried forward

1. **Yesterday's ordering was wrong.** The tenor cap was priced only *after* the approved cap
   (+$5.72/day at 1h) and ranked second. Standalone it is **+$38.65/day** at 1h — the biggest single
   lever in the book. Corrected here; the card `profit-mainpath-short-tenor-clip` still quotes +$5.91/day.
2. **`profit-c200-clip-cap-25`'s premise is falsified** on the 27.1-day population: the lane-wide $25 cap
   is worth *less* than the band-scoped $25 (+$23.24 vs +$26.03/day booked), because the non-cheap $100
   clips it reaches are net profitable. The card should be withdrawn, not approved.
3. **The approved card's level is wrong, not its shape.** $10 beats $25 on all three bases. Yesterday's
   draft defended $25 as "the approved design"; it is the approved design, not the best one.
4. **Stability check:** yesterday's approved-cap headline (+$805.77 at 1h / 27 clips) reproduces exactly
   on today's run — no new cheap $100 clip settled in 24 h, and the instrument is unchanged.
5. **Per-event capping is a null**, measured for the first time: 27 target legs spread over 24 families.
6. Unresolved and unchanged: the `filled`/`unfilled`/`null` resolver classes still disagree with the tape
   (the `null` class is 92.6% touched at 1h), so every booked-basis number here remains an upper bound on
   what we own.

## Reproduce

```bash
python3 scripts/profit-tenor.py --selftest          # 13/13
python3 scripts/profit-tenor.py | sed -n '/S20/,/S23/p'
grep -rn mainPathShortTtrClipUsd src/                 # (nothing) — the field does not exist yet
```

**Lane policy:** Lane B only today — one instrument extended, no RuleSet read/write, no prisma write, DB
opened `mode=ro`, nothing applied. R1 and R2 change what the bot risks: **Lane A proposals, operator's call.**
