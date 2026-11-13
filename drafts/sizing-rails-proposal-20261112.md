# Sizing rails: the dead fields are real, "allocated against edge" is a five-bucket artefact, and the ceiling question is settled NEGATIVE

**Card** `t_f0836393` · approval `apr-sizing-rails-dead-and-inverse` (Lane A) · **2026-11-12**
**Lane A — PROPOSAL ONLY.** Nothing below was applied: no `scripts/apply-v*.ts` run, no write to
`prisma/dev.db`, nothing merged. Every number is reproducible with one read-only command (§8).

**Verdict up front**

1. **The dead-field half of the card is real and is now closed** — `BotBankroll.minPositionSize` /
   `maxPositionSize` have **zero enforcement readers** in `src/`, as the card says. What changed since
   2026-10-20 is that both *trading* lanes' rows now carry their effective ceilings, so the row no longer
   contradicts the book. One row is still wrong (`ML_LANE`), and it has been failing its own verifier for
   22 days because that verifier runs on no cadence.
2. **The sizing half does not survive re-measurement as written.** `+0.81 / −0.86` are rank correlations
   across **five clip buckets**. At the leg level both lanes read **≈ 0** (−0.081 C-200, −0.036 STANDARD).
   The bucket orderings reproduce; the *claim* that size tracks edge for one lane and runs against it for
   the other does not. What survives is arithmetic, not a gradient: C-200 puts **73% of its notional** in
   the ≥$9.97 bucket for **+33.7%** (CI excludes zero), and **5 legs carry 78% of that bucket**;
   STANDARD puts **53.6% of its notional** in the top two buckets for **+$240 in total**, and that cohort
   is **−4.3% ex-top-5**.
3. **A STANDARD size ceiling is settled negative, not "awaiting a forward window."** Capping STANDARD's
   clip at $12/14/16/18 prices at **−$89 / −$80 / −$52 / −$15** all-time, and the current sample bounds the
   whole question to **±$564 all-time**. Resolving it to a CI that excludes zero would need **~122,000
   markets** against the 3,047 we have. Recommendation: **no size change; do not build the forward window.**

---

## 1. The card's numbers, re-measured today

Population: `PaperTrade` `closed|resolved` (TR-15 OR), `isDemo=0`, deduped to the first leg per
(wallet, market, outcome), cost = `simulatedPositionSize` (**dollars at risk**, never × `entryPrice`),
CIs market-clustered, regime = `DecisionJournal.ruleSetVersion`.

| Card claim (2026-10-20) | Re-measured 2026-11-12 | Verdict |
|---|---|---|
| C-200: 1,812 legs / $15,271 / +$6,512.25 | **2,133 legs / $23,151 / +$6,210.65** | grew; PnL flat |
| C-200 rank correlation **+0.808** | bucket-level **+0.900**, leg-level **−0.081** | claim is bucket-only |
| STANDARD: 3,198 legs / $39,004 / +$1,195.23 | **3,710 legs / $44,935 / +$1,511.03** | grew |
| STANDARD rank correlation **−0.860** | bucket-level **−0.800**, leg-level **−0.036** | claim is bucket-only |
| 69 C-200 clips above the advertised $30, $5,491.37 | **120 clips above $30, $10,241.37** (raw rows), max $100 | worse, still standing config |
| Three "max size" numbers, one binds | still three; the rows are now honest for both trading lanes | see §2 |

Lane totals on one shared denominator (the comparison the card was built on):

| Lane | legs | cost | PnL | dollar-weighted | unweighted (clustered CI) |
|---|---|---|---|---|---|
| BANKROLL_200 | 2,133 | $23,151 | +$6,210.65 | +26.83% | +12.80% **[+6.1, +19.8]** |
| STANDARD | 3,710 | $44,935 | +$1,511.03 | +3.36% | +3.97% **[−0.3, +8.6]** |

C-200's unweighted CI excludes zero and STANDARD's does not. **That is the first-order fact about this
book's sizing: one lane is proven to earn and the other is not proven to.** Any sizing argument that
treats them as one population averages a real edge with a zero.

## 2. The dead fields — closed, with proof

Read from each rail's own source, not retyped (the script parses `BOT_LIMITS` out of `src/lib/safety.ts`
and `kellyMaxSizeUsd` out of the ACTIVE RuleSet):

```
bot             table min  table max  BOT_LIMITS      kellyMax   effective
BANKROLL_200        $0.10    $100.00  $20.00/$0.10    $100.00    min $0.10  max $100.00
ML_LANE             $0.10    $100.00   NO ENTRY            -      min $0.25  max $20.00  <- STANDARD fallback
STANDARD            $0.25     $20.00  $20.00/$0.25          -      min $0.25  max $20.00
```

- **Zero enforcement readers.** `grep -rn "minPositionSize\|maxPositionSize" src/` returns one match and it
  is a *comment* (`src/lib/capital-data.ts:23`). The columns are declared, populated, annotated
  DISPLAY-ONLY in `prisma/schema.prisma:317-328`, and consulted by nothing that sizes or gates a trade.
- **`clampPaperSize` raises the ceiling, it does not clamp it down**: `hi = maxUsd !== undefined ?
  Math.max(limits.min, maxUsd) : limits.max`. The Kelly path passes `kellyMaxSizeUsd` (v72: **100**), so
  C-200's ceiling is $100 — not the code's $20 and not the table's old $30. C-200 is the only lane whose
  path can pass `maxUsd` (`isKellyCandidate` gates on `botId === "BANKROLL_200"`), so the override is worth
  nothing to STANDARD.
- **The rows are now honest where it matters.** Both trading lanes match their effective ceilings, so the
  "$30 beside a live $100" misreading hazard the card documented is gone. The remaining drift is a lane
  with **zero trades** (§6).
- One non-enforcement reader exists and is worth naming: `scripts/profit-velocity.py:358-361` prints
  `clip $min-$max` straight off the row. It is a description of the row, not a rail claim, and today it
  happens to be correct — but it is the path by which a future stale row becomes a published number.

## 3. Does size follow edge? Per lane, at the level the decision is made

The card's two correlations are computed on **five bucket means**. Five points cannot distinguish "size
follows edge" from "one bucket got lucky", and the leg-level statistic says they did:

| Lane | bucket-level rank corr | **leg-level Spearman** |
|---|---|---|
| C-200 | +0.900 | **−0.081** |
| STANDARD | −0.800 | **−0.036** |

C-200's bucket table (clip bucket, deduped realised legs):

| clip | n | cost | PnL | dwROI | unweighted CI |
|---|---|---|---|---|---|
| <$2.49 | 422 | $626 | +$9.03 | +1.44% | [−8.3, +9.3] |
| $2.49–4.99 | 317 | $1,192 | +$130.75 | +10.97% | [−0.1, +22.3] |
| $4.99–6.09 | 530 | $2,710 | +$135.13 | +4.99% | [−2.4, +14.1] |
| $6.09–9.97 | 209 | $1,678 | +$223.62 | +13.33% | [−4.8, +38.0] |
| **≥$9.97** | **655** | **$16,945** | **+$5,712.12** | **+33.71%** | **[+10.7, +46.3]** |

So C-200 really does concentrate capital in the cohort that pays: 73% of cost, 92% of PnL, CI excludes
zero. **And the concentration is thin**: the top quartile of C-200 clips reads +36.2% dollar-weighted and
+7.9% after dropping its five best legs — those five legs carry 79% of that cohort's PnL. The ordering is
real; the magnitude is five positions.

STANDARD's bucket table:

| clip | n | cost | PnL | dwROI | unweighted CI |
|---|---|---|---|---|---|
| $4.00–8.40 | 727 | $5,805 | +$333.22 | +5.74% | [−2.5, +15.4] |
| $8.40–10.00 | 670 | $6,097 | +$460.67 | +7.56% | [−2.3, +18.0] |
| $10.00–12.20 | 821 | $8,937 | +$476.68 | +5.33% | [−2.7, +13.7] |
| $12.20–18.00 | 617 | $8,270 | **−$70.40** | −0.85% | [−10.4, +9.5] |
| $18.00–20.00 | 875 | $15,826 | +$310.86 | +1.96% | [−8.0, +13.5] |

**Every quintile bucket CI spans zero** — as it did on 2026-10-20. The durable statement is arithmetic,
not a gradient: the two largest buckets hold **$24,096 of $44,935 (53.6%) and return +$240 (1.0%)**, and
both of those buckets are negative once their five best legs are removed (−5.9% on $12.20–18, −4.3% on
$18–20). The smaller clips did better in both reads; nothing here can say whether that is the clip or the
selection that produced it, because the clip was chosen by a score that has since been neutralised (§4).

One cell does clear zero and it is worth stating separately, because it is the only one: pooled over the
**$8.00–12.20 band** (n=2,211, $20,810 cost, +$1,271.02) STANDARD reads **+6.11% with CI [+0.6, +11.6]**;
that cell falls to +2.85% once its five best legs are removed, so it is a thin positive, not a strong one.
Above $12.20 the lane has no cell whose CI excludes zero in either direction.

**Label basis** (stated because it changes the numbers): `realizedPnl` on `closed|resolved`. A leg's own
result — not the market outcome. `resolved`-only populations are winner-skewed here (base win rate 48.4%
vs 62.7% on resolved only), so every arm below that reads resolved-only says so on its line.

## 4. What actually moves STANDARD's size today (and it is not edge)

The card asked why the biggest clips pick the worst opportunities. The answer is in the code and it is
now trivial:

- `src/lib/scoring/trade.ts:363-372` sizes from `sizeScore`. With `walletQualityInSize=0` the score is
  renormalised by `(copyScore − wallet×0.3) / 0.7`, and `sweetSpotSizeUsd` (18) **equals**
  `highScoreCapUsd` (18) while the admission floor sits at 70 — so both score bands book the same $18.00
  and the bucket carries no information. (Measured: 92.7% of v68+ clips are exactly $9/$18/$20; the four
  exceptions at $4 are legs sized off the base curve.)
- `src/lib/paper.ts:187-198` then multiplies by the v68 maturity schedule and clamps to BOT_LIMITS:
  `$18 × {0.5 short, 1.0 medium, 1.5 long, 1.0 huge}` → `{9, 18, 27→20, 18}`.

So STANDARD's size is a **clock on time-to-resolution and nothing else**. The score contributes zero
variation. If you want STANDARD's sizing to reflect edge, the instrument that must change is the clip
path itself — not a weight, not a band factor.

What the clock is currently buying, on the resolved-only arm (`resolvedAt − openedAt` as the TTR proxy;
n=1,014 of 3,710 — **winner-skewed, CIs all span zero**):

| TTR at entry | v68 factor | n | cost | dwROI |
|---|---|---|---|---|
| <24h | ×0.5 | 310 | $4,815 | +2.83% |
| **24–72h** | **×1.0** | **434** | **$7,463** | **−1.66%** |
| 72–168h | ×1.5 | 51 | $758 | +21.60% |
| >168h | ×1.0 | 219 | $2,731 | +24.83% |

The one cohort taking a **full** clip and losing is 24–72h. That is the only STANDARD sizing hypothesis
with a mechanism behind it today, and it is under-powered (n=434, CI [−12.8, +7.9]). It is worth a
pre-registration; it is not worth a rule change.

## 5. The ceiling question, priced and bounded

Counterfactual: rescale each leg by `min(cap, size)/size` (paper PnL is linear in size — no re-selection,
no clamp re-entry, so this prices a **ceiling**, not a rule).

| cap | legs cut | cost | PnL | delta | ex-top-10 delta | dwROI |
|---|---|---|---|---|---|---|
| $12 | 1,492 | $44,935 → $38,743 | $1,511 → $1,422 | **−$88.82** | **+$245.29** | 3.36% → 3.67% |
| $14 | 1,006 | → $41,214 | $1,511 → $1,431 | −$79.95 | +$140.50 | 3.36% → 3.47% |
| $16 | 892 | → $43,096 | $1,511 → $1,459 | −$52.25 | +$57.98 | 3.36% → 3.38% |
| $18 | 43 | → $44,859 | $1,511 → $1,496 | −$14.92 | −$14.92 | 3.36% → 3.34% |

In the v68+ era the same caps read −$106.31 / −$75.69 / −$49.67 / −$23.64.

**And the question is bounded, not merely under-sampled.** Market-clustered delta distribution:

| cap | mean delta / market | SD | MDE at n=3,047 mkts | CI would exclude zero at |
|---|---|---|---|---|
| $12 | −$0.029 | $5.21 | **±$0.18/mkt = ±$564 all-time** | ~122,713 markets |
| $14 | −$0.026 | $3.46 | ±$0.12/mkt = ±$374 | ~66,762 markets |
| $16 | −$0.017 | $1.77 | ±$0.06/mkt = ±$191 | ~40,775 markets |

We hold 3,047 STANDARD markets. **The cap question is already answered to a precision of ±$564 on the
lane's whole realised PnL, and the point estimate is negative at every level.** A forward window cannot
move this: at the observed effect size it needs two orders of magnitude more flow than the lane generates.

Same test on the other lane's live ceiling (C-200, `kellyMaxSizeUsd` 100 → the legacy $20):

| population | n | cost | PnL | ex-top-5 |
|---|---|---|---|---|
| $20–50 | 134 | $2,889 | +$1,252.78 (+43.4%) | −$308.65 (−11.1%) |
| $50–99 | 21 | $1,369 | +$143.43 (+10.5%) | −$620.25 (−60.3%, CI [−77,−36]) |
| $100 (= ceiling) | 73 | $7,300 | +$3,241.09 (+44.4%) | −$1,251.61 (−18.4%) |

**Every cohort above $20 is negative ex-top-5, and capping them at $20 would have cost −$2,624.30.** So:
the override's measured value is real but is carried by a handful of legs; it is not a rail worth raising,
and lowering it is refuted by its own number.

## 6. Recommendations, ranked

**R1 — RECOMMENDED: change no sizing rule; record this question closed.**
Delete nothing, ship nothing. The card's own 2026-10-20 decision was "leave the lane to sit until the
sizing picture has more evidence"; the evidence now exists and says the lever is worth ±$564. Close
against the measured null and stop re-opening it. *Revert: n/a (nothing changes).*

**R2 — RECOMMENDED, Lane B, one operator command: fix the last drifting row.**
`ML_LANE` advertises `$0.10 / $100` while its effective rails are `$0.25 / $20` (no `BOT_LIMITS` entry →
`clampPaperSize` falls back to STANDARD; the lane is not Kelly-eligible and has booked 0 trades). Found
2026-10-29, still failing today:

```
npx tsx scripts/verify-botbankroll-limits.ts     # exits 1: ML_LANE min 0.1/0.25, max 100/20
npx tsx scripts/apply-ml-lane.ts --apply         # display-only row: sets 0.25 / 20
```

It drifts because the check runs on no cadence — nothing but `package.json` references it. One cron line
makes it permanent (monthly is enough for a display column). *Revert: re-run the row writer with the old
values; the check is read-only.*

**R3 — NOT RECOMMENDED, priced anyway: lower `kellyMaxSizeUsd` 100 → 20.**
−$2,624.30 realised, and the $100 cohort is the lane's most profitable bucket. Rejected by its own number.

**R4 — OPTIONAL, only if you want less tail concentration: cap STANDARD at $12.**
−$88.82 all-time (−$106.31 in the v68 era), ex-top-10 +$245.29, 1,492 of 3,710 legs resized, notional
−$6,192. This is a **variance trade at ~zero expected cost**, not an edge improvement, and it cannot be
validated as one (§5). Its only supporting measurement is that the cohort left under the cap is the lane's
single CI-excluding-zero cell (+6.11%, thin, §3). It would also re-open the five-band map question the
2026-10-29 re-cut said was untestable at the $18 clip — the only argument for it that is about information
rather than risk.

**Override flags for R1 (each one line, each carries the number that changes):**
`keep-kelly-ceiling=100` (default; R3 costs −$2,624.30) · `keep-standard-cap=20` (default; R4 costs −$88.82)
· `close-sizing-question=yes` (default; the alternative is another window that needs 122k markets).

## 7. Lane B items found while measuring (not applied — this card may not write the DB)

1. **`ML_LANE` row drift** — §6 R2, 22 days old, one command.
2. **`verify:bankroll-limits` on no cadence** — a drift detector that only runs when a human remembers is
   the same class of defect as the field it guards.
3. **`scripts/profit-velocity.py:358-361` reads the display row** and prints it as `clip $min-$max` beside
   the realised clip distribution. Correct today; it is the reader that will make a stale row a published
   number.

## 8. Why this card was worked at all — the queue, not a new decision

The roadmap card carries a **user decision dated 2026-10-20** ("LEAVE THIS LANE TO SIT … do NOT re-surface
this as a recommendation until there is materially more evidence") and a **`no-resurface` gate dated
2026-10-27** that exists to keep it out of approval alerts. It surfaced in the approvals inbox anyway
(item created 2026-11-11T02:07, approved 2026-11-12T16:03).

That is the documented coupling of the queue swap: `no-resurface` lives on the roadmap card and is **not**
carried in the approvals store, so a store-signed queue re-pings exactly the decisions the tag gate used to
silence. This draft is therefore written as the card's Lane A constraint asks (proposal only), but the
recommendation it lands on is the one the existing decision already implies — so nothing here should read
as a reopened question. If the click *was* meant to re-open it, the lever is **R4** plus a pre-registration
of the 24–72h cell in §4; say so and I will write both.

## 9. Reproduce / refute

```
.venv-ml/bin/python scripts/sizing-rails-read.py      # read-only; opens the DB immutable=1; exit 0
npx tsx scripts/verify-botbankroll-limits.ts          # exits 1 today on ML_LANE, by design
```

The script parses the rails from `src/lib/safety.ts` and the active RuleSet rather than restating them, and
it collapses percentile ties so a repeated clip value cannot create an empty bucket (the card's own
"$4.99–$4.99, n=0" artefact).

**Refutation of this draft:** it fails if (a) any leg-level size↔edge statistic on this population
reproduces the card's ±0.8–0.86 at the leg level rather than across five buckets; or (b) a STANDARD cap
change is shown to move all-time PnL by more than the ±$564 MDE; or (c) the 24–72h cell's −1.66% survives a
larger sample with a CI excluding zero — in which case §4 becomes an actionable sizing change and R1 is
superseded.

**Not done, on purpose:** no `scripts/apply-v*.ts` run, no RuleSet change, no write to `prisma/dev.db`, no
merge. Files added: `scripts/sizing-rails-read.py` (the instrument) and this draft — both uncommitted.
