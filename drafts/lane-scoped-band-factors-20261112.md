# Lane-scoped C-200 band factors — the change already shipped, half of it dead on arrival, and the live half is up-weighting a cell that fails its own bar

**Card:** `lane-scoped-band-factors` (approval `apr-lane-scoped-band-factors`, lane A, approved 2026-11-12T16:10:31Z)
**Written:** 2026-11-12 ~16:20Z · **Instrument:** `scripts/lane-scoped-band-factors-postread.py` (read-only, `immutable=1`)
**Status: NOTHING APPLIED.** No `apply-vNN.ts` run, no `prisma/dev.db` write, no merge, no commit. RuleSet still **v72**.

---

## 0. Verdict

The card asks for a **proposal to make the C-200 band factors lane-scoped**. That change is already in production and has been since **2026-11-03 14:54:07** (RuleSet **v71**, `hermes-v71-lane-scoped-band-factors`). The roadmap card was never closed, which is why the approvals inbox re-surfaced it nine days later.

Reading it as a live change rather than a pending one produces three findings, and they do not point where the card does:

| # | Finding | Evidence |
|---|---|---|
| 1 | The `deadZone` half of v71 is **unreachable** — `c200SkipBandRange = "0.4-0.6"` (v62, 2026-10-12) hard-skips every C-200 leg in that band, both lanes, *before* the band map can size it | 1 admitted mid-band leg in 8.1 days and it never filled; 2 in total since v62 |
| 2 | The premise is a **resolved-only** read. On the full finished book the cell is +9.8% (CI [−1.2,+20.6]), not the +22.6% / z=+2.52 the card quotes — and the ≥0.60 cell's hit rate is **significantly below its break-even hurdle** (z = −2.51) | §3 |
| 3 | The `premium` half is **live**, multiplied the ≥0.60 short-TTR clip 2.3×, and that cell reads **−14.6%** on 31 positions since activation | §4 |

**Recommendation: revert `shortTtrPremiumBandFactor` 2.0 → 0.5** (one field, the shipped constant). Hold `shortTtrDeadZoneBandFactor` at 0.5 — it is inert and harmless. Do **not** clear the mid-band skip on this evidence.

---

## 1. What the card asked for vs what is in the repo

`src/lib/paper.ts::mapBankroll200Size` (line 85) takes `{longshot, deadZone, premium, longshotFloor}` and applies them by entry band. The card's claim — one `deadZone` and one `premium` for every lane — was true of v70 and is **false of the code in `main` today**:

```ts
// scripts/score-trades.ts:1182-1193 (v71, 2026-11-03)
bandFactors: {
  longshot: rules.c200LongshotBandFactor,
  deadZone:  result.lane === "short_ttr" ? rules.shortTtrDeadZoneBandFactor  : rules.c200DeadZoneBandFactor,
  premium:   result.lane === "short_ttr" ? rules.shortTtrPremiumBandFactor   : C200_BAND_DEFAULTS.premium,
  longshotFloor: rules.c200LongshotBandFloor,
}
```

Live RuleSet **v72** (2026-11-11 18:41:05), read from `RuleSet.rulesJson WHY='active'`:

| field | value | reader |
|---|---|---|
| `shortTtrDeadZoneBandFactor` | **0.5** | short-TTR 0.4–0.6 (v71) |
| `shortTtrPremiumBandFactor` | **2.0** | short-TTR ≥0.60 (v71) |
| `c200DeadZoneBandFactor` | 0.125 | main-lane legacy map + Kelly rail (`legacyEquiv`) |
| `c200LongshotBandFactor` / floor | 3.5 / 0.05 | both lanes’ <0.20 |
| `c200BandSizeFactor` @ range | 0.5 @ `0.6-0.8` | **both** lanes, final size (v60) |
| `c200SkipBandRange` | **`0.4-0.6`** | **both** lanes, hard skip (v62) |
| `c200MaxEntryPrice` | 0.8 | both lanes |

`RuleChange` row: `hermes-v71-lane-scoped-band-factors`, 2026-11-03 14:54:07, v70→v71; v72 (wallet-category basis) preserved both fields.

**A note on the word “lane-scoped”.** The main lane is Kelly-sized today (`kellyEnabled = 1` in v72), and `openPaperTrade` bypasses `mapBankroll200Size` for Kelly copies. So the `premium` field in that map has exactly **one** live reader: the short-TTR lane. v71 did not scope a shared factor — it changed the only value that had any effect, 4×.

Root cause of this task: `data/roadmap.json` still lists the card in **Backlog** tagged `proposed`/`awaiting-approval` with `NOT APPROVED` in `dates`, while the change shipped on the day it was proposed. A card that lies about its own state is the mechanism that makes a reviewer cron re-litigate shipped work; corrected in §7.

---

## 2. Enforcement — the stored fields are live, and the mid band cannot be reached

`booked size ÷ $10 decision size`, bet-level, regime v49+, by lane and band:

| lane | band | n pre | pre | n post | post | post/pre | map expects |
|---|---|---|---|---|---|---|---|
| shortttr | <0.20 | 128 | 1.86 | 39 | 1.95 | 1.05 | 1.00 |
| shortttr | 0.2–0.4 | 234 | 0.88 | 56 | 0.97 | 1.11 | 1.00 |
| shortttr | 0.4–0.6 | 454 | 0.19 | **1** | 0.49 | 2.63 | 2.00 |
| shortttr | 0.6–0.8 | 270 | 0.41 | **59** | 0.94 | **2.29** | 4.00 |
| main | 0.6–0.8 | 161 | 0.97 | 21 | 0.63 | 0.66 | — (Kelly) |

The two bands v71 touches moved 2.3–2.6× while the two it does not moved 1.05–1.11× — a clean difference-in-differences, so the fields are **enforcing**, not merely stored. (The main lane is not a control: it is Kelly-sized and never reads `premium`.)

The 0.4–0.6 half has **no reach**. `scripts/score-trades.ts:1071`:

```ts
// v62 (2026-10-11 C-200 daily report change 2, user-approved): HARD-SKIP a band.
if (botId === "BANKROLL_200" && isInBandRange(currentPrice, rules.c200SkipBandRange)) { … continue; }
```

`c200SkipBandRange` has been `0.4-0.6` since **v62 (2026-10-12 11:20:21)** and is checked *after* the Kelly/lane sizing, so it bites whichever lane would have booked the leg. In the 8.1 days after v71 the whole BANKROLL_200 book produced **1** mid-band leg (2026-11-10) and it never filled (`fillStatus='unfilled'`); since v62 landed there have been **2** in total (10-28, 11-10), both explained by the sidecar booking at `mid − credit` (≈2¢), which pushes a 0.60–0.62 decision into the 0.40–0.60 bucket by *booked* price even though the gate and the map saw ≥0.60. Short-TTR legs opened per band per month:

| band | 2026-09 | 2026-10 | 2026-11 (12d) |
|---|---|---|---|
| <0.20 | 83 | 50 | 41 |
| 0.2–0.4 | 121 | 117 | 65 |
| **0.4–0.6** | **319** | **150** | **1** |
| 0.6–0.8 | 218 | 53 | 71 |

So the field v71 raised 0.25→0.5 sizes a band the bot stopped entering five weeks ago. Its reach is zero, which makes the card's headline sentence — “the rule's harshest discount lands on the only mid-band cell that clears its confidence interval” — moot: there is no clip there to discount.

---

## 3. The premise, re-cut on the full book

The card's numbers come from `scripts/profit-robustness-alloc.py`, which reads `status = 'resolved'` as its primary population. `resolved` is **natural settlement**. `closed` is an **early exit**, and realised PnL ORs both — 419 of the 1,086 pre-v71 short-TTR bets are `closed`. In exactly these cells the two classes disagree in sign:

| short-TTR cell (pre-v71, positions only) | n | ROI | hit | early-exit class |
|---|---|---|---|---|
| 0.4–0.6, **settled only** | 238 | **+30.3%** | 62.6% | — |
| 0.4–0.6, early exits | 138 | −18.8% | 29.0% | the loss bucket |
| **0.4–0.6, full book** | **361** | **+9.8%** | **49.6%** | CI [−1.2, +20.6], z −0.51 |
| 0.6–0.8, **settled only** | 120 | +26.8% | 87.5% | — |
| 0.6–0.8, early exits | 118 | −17.0% | 36.4% | the loss bucket |
| **0.6–0.8, full book** | **229** | **+4.7%** | **62.0%** | CI [−2.9, +12.0], **z −2.51** |

Full cells, both exit classes, cost = `simulatedPositionSize` (dollars at risk), hurdle = p·(1+0.05·(1−p)), CI = market-clustered 2,000 draws:

| lane | band | era | n | mkts | clip$ | pnl$ | ROI | px | hit | edge | z | CI | ex-top-5 | slip tol |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| shortttr | 0.4–0.6 | pre-v71 | 361 | 335 | 2.04 | +72.07 | +9.8% | .497 | .496 | −1.3pp | −0.51 | [−1.2,+20.6] | +4.7% | −0.1c |
| shortttr | 0.4–0.6 | post-v71 | **0** | — | — | — | — | — | — | — | — | — | — | — |
| shortttr | 0.6–0.8 | pre-v71 | 229 | 215 | 4.40 | +47.11 | +4.7% | .690 | .620 | −8.1pp | −2.51 | [−2.9,+12.0] | +2.7% | −7.0c |
| shortttr | 0.6–0.8 | post-v71 | 31 | 31 | 9.44 | −42.78 | **−14.6%** | .694 | .516 | −18.8pp | −2.10 | [−37.9,+8.2] | −29.8% | −17.7c |
| main | 0.4–0.6 | pre-v71 | 213 | 178 | 18.00 | −372.15 | −9.7% | .504 | .451 | −6.6pp | −1.93 | [−24.5,+5.2] | −16.1% | −5.3c |
| main | 0.6–0.8 | pre-v71 | 161 | 147 | 17.45 | −51.28 | −1.8% | .689 | .671 | −2.9pp | −0.79 | [−13.6,+8.7] | −5.2% | −1.9c |

**The card's own adoption rule was: “adopt per cell when (a) market-clustered CI excludes zero, (b) ex-top-5 ≥ +10%, (c) n ≥ 140.”** On the full book, **neither cell passes any of the three**: mid CI includes zero and ex-top-5 is +4.7%; the ≥0.60 cell includes zero, ex-top-5 is +2.7%, and its hit rate is 8.1pp *below* break-even at z = −2.51. The resolved-only cut passed because it drops the early-exit half of the book, which is the half that loses.

Caveats stated rather than buried: (i) my re-cut of the settled-only mid cell is +30.3% on n=238, not the card's +22.6% on n=307 — same sign and size, different dedupe scope, so the card's number reproduces directionally, not exactly; (ii) 0 of 453 pre-v71 short-TTR legs in 0.2–0.8 classify INVERTED against the wallet's own fill (`ObservedTrade` provenance join), so this lane's banding is clean — but [0.40,0.60) is complement-invariant anyway, which is why the mid band was always the trustworthy half; (iii) the early-exit class is a policy under separate review (v70 retired the STANDARD stale exit); it is included here because it is part of the book, not because this card proposes touching it.

---

## 4. The live half: post-apply read (8.1 days, 156 short-TTR bets)

| short-TTR ≥0.60, post-v71 | n | clip$ | pnl$ | ROI | hit | z | CI |
|---|---|---|---|---|---|---|---|
| positions, both classes | 31 | 9.44 | −42.78 | −14.6% | .516 | −2.10 | [−37.9,+8.2] |
| … of which settled | 23 | 9.71 | −3.77 | −1.7% | .696 | — | — |
| … of which early exit | 8 | 8.67 | −39.01 | −56.2% | .000 | — | — |

Per-leg, not a single-market artifact: 7 losses at $9.92 across NBA, UCL, UEL, CPI and temperature markets (`nba-cle-nyk`, `ucl-aek1-rma`, `uel-lev-olm`, `nba-mia-gsw`, `will-core-cpi`, `nba-mem-tor`, `nba-sas-chi`); bit-by-bit it reads 16/23 settled wins against a pre-v71 rate of 105/120.

Counterfactual — the same 31 positions re-priced at the pre-v71 factors (0.5 premium, re-clamped $0.25/$20, linear in size by construction):

- actual (lane-scoped, 2.0): **$292.71** notional → **−$42.78**
- pre-v71 factors (0.5): $73.18 notional → −$10.70
- **delta: −$32.09** for +$219.53 of notional added. Eight days.

**v71's pre-registered refutation** (over the next 150 short-TTR bets: CI lower bound < 0, OR ex-top-5 < +8%, OR median entry slippage > 4c):

| cell | n | CI low < 0 | ex-top-5 < 8% | breakeven slip < 4c | verdict |
|---|---|---|---|---|---|
| 0.4–0.6 | 0 | — | — | — | **untestable (no flow)** |
| 0.6–0.8 | 31 | fires (−37.9%) | fires (−29.8%) | fires (−17.7c) | **REVERT** |

Two of three conditions fire, but **n = 31 against a 150-bet trigger**, so the bar is not formally met — the honest statement is *the cell is not holding up and the window is a fifth of the way to its own trigger*. The mid cell can never reach 150 while the skip stands, so v71's refutation clause as written has become half-unexecutable.

Mechanically, note what the factor can and cannot cause: **size does not move a hit rate**. The ≥0.60 drop from 87.5% to 69.6% (settled) is either market mix or noise (≈2.9 SE), not the 4×. What the 4× does is what the counterfactual prices: it turned a −$10.70 cell into a −$42.78 one.

---

## 5. What is actually wrong, in one line each

1. **v71 was priced on a population the bot had already stopped entering.** v62 hard-skips 0.4–0.6 for the entire C-200 book; the card was written 2026-11-03 about a cell that had been closed since 2026-10-12. Reachability, not cohort size, is what a gate change is worth — and the reach here was zero for one of the two fields.
2. **The evidence was resolved-only.** Settlement is the winner-skewed subset of this book; the early-exit half loses in both cells.
3. **The live half multiplied an unproven cell.** ≥0.60 short-TTR fails its own hurdle on the full book (z −2.51) and reads −14.6% since the up-weight.

---

## 6. Decision set — ranked, each with the number it changes

**FLAG 1 (recommended) — revert `shortTtrPremiumBandFactor` 2.0 → 0.5.**
Changes: short-TTR ≥0.60 clip from **0.94×** to **~0.41×** the $10 decision size (≈$9.4 → ≈$4.1; 59 legs since v71). Revert: set the field back to 2.0 (one field, one apply script). Alternative if you want the cell at neutral size instead of discounted: **1.0** (≈$8.9 after v60's 0.5 band factor is not affected — the map and v60 multiply independently, so 1.0 books ≈$10).

**FLAG 2 — leave `shortTtrDeadZoneBandFactor` at 0.5.**
Reach is 0 while `c200SkipBandRange = "0.4-0.6"`. Reverting it changes nothing today; leaving it changes nothing today. Do not count it as a win either way.

**FLAG 3 — do not clear the mid-band skip on this evidence.**
Re-opening 0.4–0.6 is a separate Lane A decision. The full-book mid cell is +9.8% with CI [−1.2,+20.6] and ex-top-5 +4.7% — below the standard this repo uses to adopt a band, and its hit rate is at break-even.

**FLAG 4 (do nothing, logged) — the `premium` field has one reader.**
While `kellyEnabled = 1` the main lane is Kelly-sized and never reaches the map, so this field is a short-TTR-only lever wearing a shared name. Any future proposal about it should be written as a short-TTR proposal.

---

## 7. What I did / did not do

- **Did not** run `apply-vNN.ts`, did not write `prisma/dev.db`, did not merge to `main`, did not commit. `RuleSet` still reads **v72 / shortTtr 0.5 / 2.0** with no `RuleChange` row after 2026-11-11 18:41. (The DB file itself moves hourly under the live crons — mtime 10:10 → 10:11 during this read — which is why every figure here comes from an `immutable=1` snapshot.)
- **Wrote** `scripts/lane-scoped-band-factors-postread.py` (new, read-only) — every number above comes from it: `python3 scripts/lane-scoped-band-factors-postread.py`.
- **Corrected** the `lane-scoped-band-factors` roadmap card: it read `NOT APPROVED / awaiting-approval` while the change had shipped on the day it was proposed, which is why the approvals inbox re-surfaced it. Card moved to Done with the post-apply read and this document's link; the open question (FLAG 1) is named in the note, not left implicit.
- Files left **uncommitted** on the `main` working tree (`drafts/lane-scoped-band-factors-20261112.md`, the instrument, `data/roadmap.json`): the repo carries live cron churn and a Lane A proposal must not put sizing changes on `main`.

## 8. Reproduce

```bash
cd ~/polymarket-copybot
python3 scripts/lane-scoped-band-factors-postread.py       # S1..S6, the tables above
sqlite3 'file:prisma/dev.db?immutable=1' \
  "SELECT version, json_extract(rulesJson,'$.shortTtrDeadZoneBandFactor'),
          json_extract(rulesJson,'$.shortTtrPremiumBandFactor'),
          json_extract(rulesJson,'$.c200SkipBandRange')
   FROM RuleSet WHERE active=1;"
```
