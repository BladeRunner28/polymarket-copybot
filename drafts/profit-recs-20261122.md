# Profit review 2026-11-22 — one price tier holds the entire loss, the approved cap is its shadow, and the exit is not the problem

http://localhost:3013/drafts/profit-recs-20261122

**Instruments, committed with this doc:** `scripts/profit-clip-tier.py` (new; `--selftest` 5/5) and
`scripts/profit-exit-counterfactual.py` (new; tape arms, 5 checks PASS). Every figure below re-runs
from those two files. DB opened `mode=ro`; no RuleSet read or write, no prisma write, no apply-vNN.

**Basis, stated once:** `PaperTrade` isDemo=0, settled (`status != open`),
`DecisionJournal.ruleSetVersion >= 68`, deduped to the first leg per `bot|wallet|market|outcome`.
**547 legs / 450 markets / 32 wallets / 25.2 days / $11,125 at risk / −$281.09 (−2.5%) / −$11.17/day.**
Cost = `simulatedPositionSize` = **dollars at risk**, never shares. Every ROI is PnL / dollars at risk.
CIs are market-clustered bootstraps (2,000 draws). Tenor = `MarketSnapshot.timeToResolution` at
dispatch, the same reader as `profit-tenor.py`.

---

## Verdict

1. **The book has six cells and one of them is the whole loss.** The $40-and-up clip tier is 53 legs,
   **$5,000 = 45% of notional, −$766.19 (−15.3%)**. Every other cell is positive or flat: the five
   cells below $40 are 494 legs / $6,125 / **+$485.10 (+7.9%)**. This is not a band story, a score
   story or a wallet story — it is a **clip-tier** story, and it survives the concentration cuts
   (ex-top-1 **−26.9%**, ex-top-3 **−33%**).
2. **Inside that tier sit two different businesses.** `px < 0.20`: 37 legs, $3,550, **−24.6%**,
   venue-filled 1/17 wins against a **14.3% break-even**. `px >= 0.60`: 16 legs, $1,450, **+7.5%,
   CI [+3.5,+11.9]** — the only CI-excludes-zero-positive cell I can find in the book. The tier is
   not "big clips lose". It is "big clips on lottery tickets lose, big clips on favourites pay".
3. **The exit is doing its job, and it is not a lever.** On the 63 legs it actually closed,
   hold-to-resolution is **−60.2%** against the exit's **−22.7%**: the exit saved **$922** over the
   window. Only **8 of 63** held outcomes won against a 32.8% break-even price — the class is bad
   because it was *selected* for being bad, not because we sold early.
4. **And the cap everyone approved is a shadow of the floor flip, not a complement.** After a 24h
   floor the cap reaches **17 legs that are +$94.65** and capping them **costs $75.77**. Yesterday's
   "don't stack the cap" now has a mechanism and a sign: the cap is not neutral post-floor, it is
   negative. **S5's own headline (+$28.09/day) is a double count of the floor's dollars** — I print
   it because it is the number an operator would act on, and I refute it in §4.

---

## 1. The six cells (S1, S2)

| cell | legs | $ at risk | PnL | ROI | clustered 95% CI | $/day |
|---|---|---|---|---|---|---|
| short-TTR lane, clip < $20 | 232 | $2,177 | +$0.70 | +0.0% | [−9.8,+11.0] | +0.03 |
| short-TTR lane, clip $20-40 | 54 | $1,080 | +$266.27 | +24.7% | [−23.4,+95.7] | +10.57 |
| main lane, clip < $20 | 71 | $1,242 | +$72.15 | +5.8% | [−16.5,+29.8] | +2.86 |
| **main lane, clip >= $40** | **53** | **$5,000** | **−$766.19** | **−15.3%** | **[−38.6,+14.7]** | **−30.41** |
| STANDARD, clip < $20 | 114 | $1,166 | −$50.45 | −4.3% | [−28.5,+22.4] | −2.00 |
| STANDARD, clip $20-40 | 23 | $460 | +$196.43 | +42.7% | [−8.1,+104.9] | +7.80 |

Lane roll-up: **short-TTR 286 legs / $3,257 / +$266.97 (+8.2%, +$10.61/day)** vs
**main 261 legs / $7,868 / −$548.06 (−7.0%, −$21.79/day)**. The notional split is the wrong way round:
the lane that earns gets 29% of the dollars, the lane that loses gets 71%.

Read the CIs honestly: the two $20-40 cells (+$266, +$196) are the book's best dollars-per-day after
the lane, and **both CIs include zero**. I am not proposing a size-up on them (§R3).

## 2. Is the tier a size problem or a price problem? (S3, S3b)

| cut of the >=$40 tier | legs | $ at risk | PnL | ROI | CI | venue-filled wins vs break-even |
|---|---|---|---|---|---|---|
| `px < 0.20` | 37 | $3,550 | −$874.26 | −24.6% | [−56.3,+22.2] | **1/17 vs 14.3%** (Wilson95 [1,27]) |
| `px >= 0.60` | 16 | $1,450 | +$108.07 | +7.5% | **[+3.5,+11.9]** | 0/0 (no fill stamp; 15/16 resolved) |

47 of the 53 legs sit at exactly the **$100** clip: **−$991.40 on $4,700**. Twelve of them are full
−$100 losses on tickets bought at 0.05-0.19 (`dota2-*`, `will-bitcoin-dip-*`, `ufc-jproch-nav-*`),
against one +$552.23 winner at 0.153 (`atp-shevche-ruud-2026-11-11`). That is the book's payoff
asymmetry in one line: **a 0.15 ticket needs >15% accuracy and got 7.7%.**

## 3. The exit: measured, not assumed (S1-S5 of the counterfactual, 100% tape coverage)

The book's loss is entirely on legs *our exit* closed — this split is why every band table this month
pointed somewhere different:

- legs the **market** decided (resolved): 497 legs, $8,886, **+$411.28 (+4.6%)**
- legs **our exit** closed: 63 legs, $2,455, **−$556.27 (−22.7%)**

That is a selection statement, not a verdict. The verdict is the counterfactual (dollars at risk held
constant, venue minute tape, `prices-history`, keyless, retroactive):

- actual exit: **−22.7%**
- hold +24h: −21.4% (delta CI [−36.3,+56.8] — indistinguishable)
- hold +7d: −28.3%
- **hold to resolution: −60.2%** (delta CI [−77.5,+27.1]; 8/63 held outcomes won vs a 32.8% break-even)

**The exit is worth +$922 on this window (≈ +$36.6/day of avoided loss) and should not be touched.**
17% of the closed legs did come back above our entry by +7d (+$812.70 of "left on the table"), but the
other 83% went to zero, and the aggregate arm says holding is 37.5pp worse.

Two negative results with teeth:

- **Do not "simplify" the exit to a fixed +24h mark.** Replaying `close if price <= 0.85 x entry at
  exactly entry+24h` on all 410 settled C-200 legs: **−$379.69 (−4.0%), CI [−7.9,−1.0], 29 fires.**
  The live rule is better precisely because it fires on a *later* hourly check, so a leg that dips
  15% at 24h and recovers is not sold. The rule's value is its persistence, not its threshold.
- **Extending the rule's scope to STANDARD is worth nothing.** Replayed on STANDARD's 137 settled
  legs: **+$11.02 (+0.7%), CI [+0.0,+2.0], 5 fires.** The 381 stranded STANDARD legs / $4,171 are a
  mark-quality and capital-days problem, **not a P&L problem** — only 5 of them ever went adverse at
  the 24h check, and capital is not scarce (open book is 13.5% of the $3,595 cap).

## 4. The substitution proof, and the contradiction I have to report (S5, S6)

Cap shadows on the pre-floor book look great and are real on their own terms:

- cap $25 on `px < 0.20`: 37 legs touched, **+$706.60 = +$28.09/day**
- cap $40 on all prices: 53 legs touched, +$549.80 = +$21.86/day

Now put the pending floor flip in front of them. The floor removes **32 of the 53** >=$40 legs — the
entire **−$904.44** at ttr 2-24h. What a cap can still reach afterwards:

- cap $25, `px < 0.20`: **17 legs, +$94.65, $1,600 → capping them costs −$75.77**
- cap $40, `px < 0.20`: 17 legs, +$94.65 → **−$64.44**
- cap $25, all prices: 21 legs, +$138.25 → **−$107.46**
- cap $40, all prices: 21 legs, +$138.25 → **−$88.98**

**Contradiction reported, not quietly resolved:** yesterday's brief valued the cap at "$0, don't
ship"; today's S5 values it at +$28.09/day and today's S6 at −$75.77 post-floor. All three are the
same computation on different populations. The resolution: **+$28.09/day is the floor's dollars
counted a second time** (20 of the 37 legs the cap touches, 54%, are also blocked by a 24h floor),
and post-floor the residual is not zero but *negative*. Yesterday's call was right; today's sign is
worse than "neutral", which is a stronger reason not to ship it.

One refinement to yesterday's framing that matters for how the floor is written: the floor's
+$780.31 comes **entirely** from the >=$40 subset. The 388 small-clip legs inside 2-24h are
**+$124 (+2.8%)** and a blanket floor gives them up. Net is still strongly positive — the book's
2-24h block is −$780.31 (−10.3%) against **+$499.22 (+13.9%)** outside it, which reproduces
yesterday's "+14.9% kept book" independently — but the floor is a **clip-tier fix at short tenor**,
not a tenor fix, and it should be described that way when it is approved.

---

## Recommendations, ranked by expected value

### R1 — Approve the pending floor flip as the ONE clip/tenor change; do not add a cap. **+$30.96/day. Cost 0h (decision).**

- **Hypothesis.** The book's 2-24h block loses its entire deficit on legs sized >= $40, so flipping
  the 24h floor removes that deficit net of the small-clip flow it also removes.
- **Measurement.** `scripts/profit-clip-tier.py` S4/S6 on the 547-leg basis above: BOOK 2-24h =
  420 legs / $7,542 / **−$780.31** (CI [−24.1,+5.5] on ROI); BOOK outside 2-24h = 127 legs / $3,582 /
  **+$499.22** (+13.9%); the >=$40 / 2-24h subset is 32 legs / $3,050 / **−$904.44 (CI [−51.9,−3.3],
  ex-top-1 −38%)**; the small-clip 2-24h remainder is ≈ +$124.
- **Decision rule.** Approve when blocking ttr<24h moves the settled-7d sum by >= +$150/week at the
  measured rate (here +$780.31 / 25.2 days = **+$216.8/week**) AND the kept book stays positive
  (here +13.9%). Both hold. Add nothing else in the same window: post-floor cap delta is −$64 to
  −$107 (§4).
- **Refutation.** A forward 40-leg sample of >=$40 legs at ttr 2-24h earning >= 0 with a CI excluding
  zero → the −$904.44 is a 32-draw artefact and the floor is a coin flip; or blocking leaves the
  kept book below +5% → the flip moved the loss rather than removing it.

### R2 — Cap C-200 at $40 only where the floor cannot reach: `px < 0.20` AND ttr >= 168h. **+$5.27/day. Cost 1h (Lane A, propose only).**

- **Hypothesis.** The one losing block that survives a 24h floor is big clips on long-dated cheap
  tickets, and capping those clips removes two thirds of that loss without touching anything else.
- **Measurement.** `scripts/profit-clip-tier.py` S4: >=$40 / ttr 7d+ = **13 legs, $1,200, −$221.45
  (−18.5%), CI [−36.1,−5.3], 0/13 won, ex-top-3 −25%, mean price 0.16** (break-even 16%). A $40 cap
  rescales those legs to 40% of their risk → **+$132.87 = +$5.27/day**. S6 confirms no overlap with
  the floor (all 13 are ttr >= 168h).
- **Decision rule.** Ship the field defaulted OFF, apply when this cell's forward 30 legs earn <= −10%
  with a cluster CI excluding zero, or immediately if the operator prefers to stop the bleed (the
  measured basis already clears −10%; the n is what is thin).
- **Refutation.** 0/13 at a 16% break-even has a 10.4% chance under fair pricing — so a forward 30
  legs at >= 0 EV withdraws this; **and if the λ̂ refit card (`profit-lambda-owned-population`, which
  corrects the 28% q to the owned 13%) lands first, withdraw this entirely** — that card fixes the
  funding input, this cap only truncates its output. Approve one, not both.

### R3 — Do not touch the exit, and do not scope it to STANDARD. **$0 direct; it protects R1 and R2. Cost 0h.**

- **Hypothesis.** The stale adverse exit is the reason the closed class is −22.7% instead of −60.2%;
  changing its schedule or widening its scope cannot add money at this n.
- **Measurement.** `scripts/profit-exit-counterfactual.py` S1-S7: 63 closed legs / $2,455, 100% tape
  coverage; arms actual −22.7%, +24h −21.4%, +7d −28.3%, resolution −60.2%; mechanical-24h replay on
  C-200 −$379.69 (CI [−7.9,−1.0]); STANDARD scope replay +$11.02 (CI [+0.0,+2.0], 5/137 fires).
- **Decision rule.** Leave `staleExitHours` / `staleExitAdverseMove` / `staleExitHardHours` and the
  `botId === "BANKROLL_200"` scope unchanged while the STANDARD replay delta is under +2% of notional.
- **Refutation.** >=100 forward STANDARD legs whose replay delta clears +2% with a CI excluding zero,
  or >=30 forward legs going adverse at the 24h check on STANDARD → the scope is a live lever and this
  becomes a real proposal.

**Not recommending:** any size-up on the $20-40 cells (+24.7% / +42.7% but CIs [−23,+96] and
[−8,+105]); any band cut (0.4-0.6 is already skipped); any entry-price change (measured closed
2026-11-18); any gate change (measured exhausted); any credit for the >=$40 favourite cell as an edge
— 16 legs, CI [+3.5,+11.9], and the 2026-11-20 card's 5.7%-under-fair-pricing warning still applies.

**IF YOU WEREN'T HERE:** approve the floor flip **alone**. It is +$216.8/week, the cap is its shadow
and would *cost* $64-107/day once stacked, and the exit already saves $922 a window without help.

---

## Reproduce

```
python3 scripts/profit-clip-tier.py            # S1-S8, 6 self-checks, exit 1 on a failure
python3 scripts/profit-clip-tier.py --selftest # payoff identity, tier bounds, Wilson
python3 scripts/profit-exit-counterfactual.py  # S1-S8, tape arms, 100% coverage (cached)
python3 scripts/profit-exit-counterfactual.py --no-fetch   # cache-only; reports coverage
```

Both scripts: `COPYBOT_DB="file:$PWD/prisma/dev.db?mode=ro"` is honoured; read-only by construction.
