# PROFIT REVIEW — 2026-11-26

http://localhost:3013/drafts/profit-recs-20261126

**Instrument (committed with this doc):** `scripts/profit-tenor.py`, extended today with **§S27–S30**
(`--selftest` **18/18**). Re-run: `python3 scripts/profit-tenor.py` (DB `mode=ro`, ~40 s).
**Population:** 686 settled legs / 572 markets, `ruleSetVersion ≥ 68`, 2026-10-27…11-25 (29.3 days),
**$13,088 at risk**. **Cost basis = `simulatedPositionSize` = DOLLARS AT RISK**, never size × price.
Dedupe = first leg per `bot|wallet|market|outcome`. CIs = market-clustered bootstrap (2,000 draws);
a *delta* is a sum of per-leg deltas, so it is bootstrapped the same way (`boot_delta`).

---

## The one thing

**The book is not losing to bad prices. It is losing to one clip size, in one cell: 31 legs at $100
that resolve the same day. Everything else is noise around zero.**

§S30 puts every settled leg on one table and the loss has a single address:

| clip tier | legs | notional | PnL | ROI | ex-top-3 | ex-top-10 |
|---|---:|---:|---:|---:|---:|---:|
| <$15 | 433 | $3,975 | +$2.3 | +0.1% | −3.9% | −9.7% |
| $15–30 | 196 | $3,712 | **+$558.4** | **+15.0%** | +1.0% | −12.1% |
| $30–60 | 6 | $300 | +$225.2 | +75.1% | −10.0% | — |
| **$100** | **51** | **$5,100** | **−$991.4** | **−19.4%** | **−33.0%** | **−39.8%** |

There are no clips between $60 and $100 — the Kelly path sizes to its `kellyMaxSizeUsd=100` ceiling
or to something small. So the book is two populations stacked: 635 legs under $60 that make **+$785.9
(+9.8%) on $7,988 of risk**, and 51 legs at $100 that lose **−$991.4 (−19.4%) on 39% of the
notional**. Remove the $100 clip and the book is +9.8%; keep it and the book is −1.6%.

The $100 clip is not uniformly bad — it is bad *where we are wrong*. The same clip at px ≥ 0.80 is
**+6.7% on 13 legs**; at 0.37 it is a bet on a 37c outcome sized as if it were a 90c one. §S30
narrows the loss to its actual address, and this is the ranked table of every rule on the board,
priced on the same 686 legs:

| shadow | blocks/binds | kept notional | kept PnL | kept ROI | $/day | delta CI |
|---|---:|---:|---:|---:|---:|---|
| **(e) BLOCK 2–24h main-path clips ≥ $60** | 31 | $9,988 | **+$939.3** | **+9.4%** | **+39.02** | **[+622, +1,666]** |
| (f) block Kelly clips ≥$60, px<0.60 | 38 | $9,288 | +$872.4 | +9.4% | +36.74 | [−412, +2,095] |
| (c) block 2–24h main path entirely | 199 | $7,934 | +$820.2 | +10.3% | +34.96 | — |
| (d) block Kelly clips ≥$60, any tenor | 51 | $7,988 | +$785.9 | +9.8% | +33.79 | [−530, +2,077] |
| (a2) **block** band 0.0–0.2 with clip > $10 | 42 | $9,120 | +$686.8 | +7.5% | +30.41 | — |
| (a) **band cap 0.0–0.2:10** (approved field) | 42 | $9,540 | +$609.7 | +6.4% | +27.79 | **[−648, +1,826]** |
| (b) Kelly cap $25, lane-wide | 57 | $9,113 | +$425.5 | +4.7% | +21.51 | — |

**One row has a CI that excludes zero: (e).** 31 legs, $3,100, −$1,144.7 (−36.9%), blocked-PnL CI
**[−1,666, −622]**, and stable in both halves (−21.5% then −53.3%) and after its ten best legs
(−39.8% for the whole $100 tier ex-top-10). It keeps 76% of the notional and 100% of the short-TTR
channel, and it is worth **$39/day** against yesterday's first-ranked action at **$28/day**.

**And the rule I ranked first yesterday is not the best of the ones it beats.** (a) is a 42-leg cap
whose delta CI spans zero — yesterday's CI-clean figures were on the tape-*touched* bases, which drop
60% of the legs; on the booked and deployed bases, the ones the ladder and the resolver actually pay
on, the same delta is **+$815 [−648, +1,826]**. Note also that on this population the cheap band
prefers to be **blocked** (+$30.41) rather than capped (+$27.79): its cap curve is monotone to zero.
I am re-pricing (a) down, not defending it.

---

## 1. Why (e) and not the approved floor or the approved band cap

**Not the floor.** `minTimeToResolutionHours` is still **2** in the live RuleSet v73; the approved
2→24h floor has never been applied. Measured today it would block **552 legs / $9,223 / −$700
(−7.6%)** and lift the kept book to +12.8% — but §S9 shows *why that is the wrong instrument*:

| 2–24h, by channel | legs | notional | PnL | ROI |
|---|---:|---:|---:|---:|
| short-TTR channel ($10 lane) | 353 | $4,069 | **+$325.6** | **+8.0%** |
| main path (Kelly) | 199 | $5,154 | **−$1,025.6** | **−19.9%** |

A global floor kills a +8% channel to remove a −20% one. The approved floor is priced on a
STANDARD-only shadow (card `profit-floor-ttr-all-lane-basis`), and on the all-lane basis it is a
*negative* trade on 353 legs of real, if concentrated, profit.

**Not the band cap.** (a) acts on 42 legs and its CI spans zero. After a 2–24h block its *residual*
scope is 17 legs at **+6.7%** (§S15) — i.e. once (e) ships, the cheap-band cap starts cutting a
positive cell. They are substitutes on the same legs and the wrong one has been queued first for 13
days.

**Not the blunt lane-wide cap.** $25 lane-wide (+$21.51/day) is worse than (e) because it also
crushes the **$15–30 tier at +15.0% on 196 legs** — the only cohort in the book with both a real n
and a positive point estimate. Scope matters more than strength.

## 2. The denominator is still lying, and this is the deepest correction of the day

§S27. Since the fill-aware flip, `unfilled` legs stay in the ROI denominator at exactly $0.00:

| class | legs | notional | PnL | ROI |
|---|---:|---:|---:|---:|
| booked (all settled) | 686 | $13,088 | −$205.5 | −1.6% |
| deployed (`filled`) | 146 | $3,231 | **−$833.1** | **−25.8%** |
| unadjudicated (`null`) | 176 | $2,614 | +$284.4 | +10.9% |
| unfilled | 364 | $7,242 | +$343.3 | +4.7% |

**322 of 686 legs (46.9%, $6,148 = 47.0% of notional) settle at exactly $0.00 and every one is
stamped `unfilled`.** A dollar of the booked denominator is **28.7c of a real one**. So C-200's
published **−3.5%** is the same book as a deployed **−25.8%**, and every card in the backlog —
including yesterday's — quotes the 3.5% side. This does not change a rule; it changes which number
any future rule is allowed to be judged on.

## 3. Two things I expected to find and did not

- **"Size is an anti-signal."** It looked that way from the clip table. Measured on 364 nonzero legs,
  Spearman(clip, realised ROI) = **+0.027**. Size carries no information either way. The anti-signal
  is confined to one cell (2–24h main path ≥$60); it is not a law, and no lane-wide re-sizing follows
  from it.
- **"The top band is where the edge is."** §S29: px ≥ 0.80 is the only cell that survives
  concentration — **26 legs / 19 markets / 3 wallets / $814 / +$134.0 (+16.5%) / ex-top-3 +14.8% /
  26 of 26 winners at an average of 0.860**. Two honest caveats before anyone quotes that: the legs
  are only **19 distinct bets** (the two lanes hold the same bet at different sizes, so the binomial
  is P = 0.86^19 = **5.5%**, not the 2.0% the leg count implies), and the last admitted leg opened
  **2026-11-08** — the cell has produced nothing since the price-frame fix. It is a real cell that
  has no flow: the candidate supply in that band is **853 refusals in 29 days at a mean price of
  0.956** (758 with an empty `reasonsJson`), refused by `trade.ts:126 maxEntryPrice 0.88`. A refusal
  at 0.956 is arithmetic (4.6c up, 96c down); a refusal at 0.86 is doctrine. But 19 bets in 29 days
  is not a lever. Reported as a negative, with the branch that would reopen it: if a future read finds
  **≥5 admitted legs/day in the 0.86–0.88 slice**, that cell earns a size card.

## 4. Capital is not the constraint — but 98% of the capital-days are dead

§S3: the open book is **386 legs / $4,215 / 445,908 capital-days**, of which **358 legs (98.4%,
438,616 capital-days) have more than 90 days of term left and are 117 days old on average**. The
entire settled history over these 29 days is **11,960 capital-days**. Cash is $7,049 and the C-200
open book is $80, so the lane is *flow*-constrained, not capital-constrained: releasing those
capital-days buys no capacity and would realise −$342 of marks. It is a reason the `$/1k-capital-day`
headline can never look good, not a lever.

---

# Recommendations, ranked by expected value

### R1 — Block Kelly-path clips ≥ $60 that resolve in 2–24h. **+$939 on the kept book (+$39.02/day), CI [+$622, +$1,666], 76% of notional retained, kept ROI +9.4%. 1–2h. Lane A.**

- **Hypothesis.** The book's entire measured loss is one class — same-day Kelly-path copies sized at
  or above $60 — and removing that class leaves a book that earns, on a delta whose market-clustered
  CI excludes zero and whose sign holds in both halves.
- **Measurement.** `scripts/profit-tenor.py` §S30 arm (e), committed today: 31 legs / $3,100 /
  −$1,144.7 / **−36.9%**, blocked-PnL CI **[−1,665.7, −621.8]** (delta CI [+621.8, +1,665.7]), halves
  **−21.5% (n=16) then −53.3% (n=15)**. Kept book: $9,988 / **+$939.3 / +9.4%**. The class is
  identified by the leg's own journal reasons (`Short-TTR` absent) plus `timeToResolution` from the
  last `MarketSnapshot` at entry+15m — never by price. The same $100 clip at px ≥ 0.80 is +6.7%, which
  is why the scope is the tenor-and-channel, not the clip alone.
- **Decision rule.** Ship as a RuleSet field `mainPathShortTtrSkipClipUsd` (default 0 = off) evaluated
  in the same block as the existing `mainPathShortTtrClipUsd` clamp: if `ttr < 24h` **and** the leg was
  not admitted by the short-TTR lane **and** `size >= 60`, skip the copy and journal the reason.
  Boundary probe at 59.99/60.00/60.01 × ttr 23.9/24.0/24.1. Re-read with
  `python3 scripts/profit-tenor.py | sed -n '/S30/,/S8/p'`.
- **Refutation.** Forward 30 legs in exactly that class reading **ROI ≥ 0** on the booked basis, or a
  kept book **< 0% ex-top-3**, or the short-TTR channel's forward ROI falling below **−5%** (i.e. the
  channel I am preserving is the one that broke) → set the field back to 0, which is byte-identical
  to today.

### R2 — Do not run `apply-v73` with the cheap-band cap. Withdraw it from first place. **$0 spent; $11/day of delta given up versus R1. 0h. Lane A (a decision, nothing applied).**

- **Hypothesis.** The band cap `0.0-0.2:10` is dominated by R1 on CI (spans zero vs excludes zero), on
  magnitude (+$27.79/day vs +$39.02/day), and on post-rule interaction (after a 2–24h block its
  residual scope is +6.7%), so shipping it first spends the operator's one available decision on the
  weaker rule.
- **Measurement.** §S30 (a) `+$815.2 = +$27.79/day` booked with delta CI **[−648.3, +1,825.7]**;
  §S28 the same cell's cap curve is **monotone to zero** ($892 at cap $0 → $707 at $25 → $0 at none),
  i.e. the cell has no measured right to exist at any constant, which is a statement about a block,
  not about $10 vs $25; §S15 the residual after a 2–24h block is **17 legs at +$113.8 (+6.7%)**.
- **Decision rule.** Leave `c200BandClipCaps` absent from RuleSet v73 (it is absent today), re-rank
  card `profit-band-clip-rebalance` to second behind R1, and re-price it only after R1 has 7 forward
  days. If R1 is *not* approved, ship (a) at $10 as previously proposed — it is still positive, just
  not the best available.
- **Refutation.** If R1's forward kept book fails its own refutation (kept book < 0 ex-top-3) while
  the cheap band's forward tape-touch ROI is < −10% on 40 legs, then the band cap was the right
  instrument and this demotion was wrong — restore it to first.

### R3 — Report every ROI on both denominators from today on, and stop quoting booked-only. **$0 direct; it changes which number every future approval is granted on. Lane B, done in the instrument.**

- **Hypothesis.** Because 46.9% of the booked population settles at exactly $0.00 and keeps its
  notional in the denominator, any card quoting a booked-only ROI understates that cell's loss rate
  by up to 3.5x, and the error is largest exactly where the book is worst.
- **Measurement.** §S27: booked −1.6% on $13,088 vs deployed −25.8% on $3,231; C-200 −3.5% vs −25.8%;
  322 zero-PnL legs / $6,148, all `unfilled`; a booked dollar is 28.7c of a deployed one.
- **Decision rule.** Any card or table that quotes ROI must print the deployed ROI and the phantom
  share beside it; the EOD and the ladder keep their own basis but must name it in the header. Applied
  as a read-path change only — **no rule value, no clip, no gate, no booked row moves.**
- **Refutation.** If on the next 28 days the phantom share falls below **10%** (e.g. because fills
  improve), the correction is retired: booked and deployed become the same number and the extra column
  is noise.

---

**IF YOU WEREN'T HERE:** I would build and ship R1's skip field today rather than wait for a 7-day
shadow. It is the only delta on the board whose market-clustered CI excludes zero, it costs 1–2h, and
its revert is a field defaulting to 0 — every day it is not shipped is ~$39 of measured, already
addressed loss. If the build has to wait, the one-value approximation available in the live RuleSet
today is `kellyMaxSizeUsd` 100 → 60 (+$13.52/day, +$33.79 if set low enough to zero the class), which
is strictly weaker and should be treated as a stopgap, not as the decision.

**Lane policy:** Lane B only — one instrument extended (§S27–S30, 18/18 selftests), nothing applied,
no RuleSet read/write, DB `mode=ro`, no prisma write, no `apply-v*`. R1, R2 and the `kellyMaxSizeUsd`
value change how much the bot risks: **Lane A proposals, the operator's call.** R3 is a read-path
repair inside my own instrument and is done.

---

## Corrections and contradictions carried forward

1. **Yesterday's R1 is re-priced down and re-ranked second.** Its +$28.78/day was booked-basis
   arithmetic on a 640-leg window; the same rule today reads +$22.36/day with a delta CI of
   **[−$648, +$1,826]**. It is not withdrawn — it is no longer the best available action, and it
   should not precede R1.
2. **The 07:00 tuning review's "STANDARD 30 d +18.5% (n=281)" does not reproduce on a deduped,
   rule-gated population.** §S15 on this window: STANDARD is **158 legs / $1,837 / +$183.2 (+10.0%)**,
   and the `1–7d` cell alone (+$220.6) is *more* than the lane's entire profit — because one wallet
   carries **94%** of that cell's PnL and it reads **−1.4% ex-top-3**. Do not treat STANDARD as the
   positive lane; the 281 legs are duplicate-inflated.
3. **The approved 2→24h TTR floor would cut a profitable channel.** §S9: short-TTR +8.0% (353 legs)
   vs main path −19.9% (199) inside the same window. The floor is a global gate; the measured
   instrument is a *main-path* block. Card `profit-floor-ttr-all-lane-basis` remains open and now has
   a sharper question: the floor as written is worse than R1 for the same loss.
4. **"Above 0.50 the edge is negative" is not monotone.** 0.40–0.60 is blocked by v63 and holds 2
   legs; 0.60–0.80 is flat (+0.2% on 179 Kelly-path legs); **0.80–1.00 is the only CI-clean positive
   cell in the book** (+16.5%, 26/26). The doctrine has been right about the middle and wrong about
   the top; §S29 prices the supply and shows why the top cannot be scaled yet.
5. Unchanged and still true: the two clip rules are substitutes; the `1–7d` tenor cell is one wallet;
   `Paid-up entry`, `exit exemption` and `lane-wide $25` stay as measured dead ends.

## Reproduce

```bash
python3 scripts/profit-tenor.py --selftest          # 18/18
python3 scripts/profit-tenor.py | sed -n '/S27/,/S8/p'   # S27 deployed basis, S28 clip axis, S29 top band, S30 shadows
python3 scripts/profit-tenor.py | sed -n '/S9\./,/S11/p' # channel split inside 2-24h
grep -n "maxEntryPrice\|minTimeToResolutionHours\|kellyMaxSizeUsd" src/lib/rules.ts   # 0.95 / 2 / 100
```
