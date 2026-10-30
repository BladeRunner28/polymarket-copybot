# STANDARD band size factor — the map cannot express itself at the live clip

**Card:** `standard-band-size-shadow` (roadmap, Lane A) · **Run:** `t_e17694f2`, 2026-10-29
**Instrument:** `scripts/profit-velocity.py` §AM.7 (`--only-am`, exit 0, 10.6s) + four read-only probes in this run
**Status:** PROPOSED, NOT APPLIED. No RuleSet change, no DB write, no `apply-v*.ts`, nothing merged.

---

## Bottom line

The card asks to shadow a five-band STANDARD size map (2.0 / 1.5 / 0.5 / 0.4 / 0.2) before shipping it.
Re-measured on today's book, the map cannot do what the card claims, for three independent reasons:

1. **The live clip and the live clamp erase the map.** STANDARD books a median $18.00 in every populated
   band against `BOT_LIMITS.STANDARD.max = $20.00`. Any factor ≥ 1.112 books $20. The map's 2.0 and 1.5
   are the *same trade* live; only the down-weights do anything, and they are a de-risking, not a
   reallocation.
2. **The arm the card quotes (+$5,067) is not a book anyone can hold.** Its "notional-neutral"
   renormalisation puts 886 of 3,731 all-time legs back *above* the $20 clamp. The bookable (as-is) arm
   is +$3,770 all-time and +$83 live-era, and its market-clustered CI spans zero in all three windows.
3. **The pre-registered gate is ~8x underpowered.** At the measured live-era effect (+$0.45 per market),
   a CI excluding zero needs ~1,211 legs. At 150 legs, 2% of 400 simulated forward windows clear. The
   card's own ship rule cannot fire on a true-positive map inside the horizon it budgets.

What survives is a **single-factor** claim, not a schedule: up-weight `<0.20` only (×2.0). All-time,
below the live ceiling, it is +$4,094 with CI **[+637, +8,900]**, and it still clears zero after dropping
the three biggest winners (+$3,904, CI [+478, +8,357]). But the effect collapses as the clip rose:
90d is +$783 **[−394, +2,171]**, live era +$75 **[−33, +198]**. That decay is itself the evidence for
Finding 1 — the only interval that excludes zero belongs to a $10-clip regime the bot no longer operates in.

**Recommendation: do not build the five-band shadow.** Either close the card for the quarter (my
preference) or amend it to the single `<0.20` factor with a power-feasible decision rule. Details and
the exact refutation conditions are below.

---

## What was re-measured, and how it differs from the card

`python3 scripts/profit-velocity.py --only-am`, run against the live `prisma/dev.db` read-only
(`file:...?mode=ro`). Section AM.7 in full:

| window | legs (below 0.85 ceiling) | flat PnL | notional |
| --- | --- | --- | --- |
| all-time | 6,130 (3,731) | +$5,620 | $66,529 |
| 90d | 2,635 (2,153) | +$1,586 | $34,320 |
| live era ≥ 2026-09-15 | 204 (204) | +$699 | $3,627 |

The reproduction is faithful: 2,399 all-time legs sit above the live 0.85 gate, exactly the count the
card names. The live ruleset is now **v70** (card says v67); `deadZoneSizeFactor` and
`longshotSizeFactor` are still 1.0, `sweetSpotSizeUsd` / `highScoreCapUsd` are 18, `standardMaxEntryPrice`
0.85, `standardSkipBandRange` "0.4-0.6", `kellyEnabled` 1 but C-200-only. STANDARD is still band-blind.

Two card statements do **not** reproduce:

- "median clip is $18.00 in all five bands" — there are four populated bands. The 0.4–0.6 band is
  skipped live, so the map's middle factor (0.5) is dead code on this lane.
- "ex-top-10 ROI improves in all three" — it improves all-time (+10.6 → +19.4) and over 90d
  (−0.6 → +1.9) and **worsens in the live era (−14.6 → −21.9)**. That is the window a forward shadow
  would measure, and it is the clause the card pre-registered as its own refutation.

---

## Finding 1 — the clamp eats the factor (the decisive one)

Live-era band table from AM.7: 38 legs `<0.20`, 69 at 0.2–0.4, 84 at 0.6–0.8, 13 at 0.8–1.0 —
**median clip $18.00 in every one**.

| live clip | × 2.0 | × 1.5 | × 1.25 | booked after clamp |
| --- | --- | --- | --- | --- |
| $18.00 | $36.00 | $27.00 | $22.50 | **$20.00 — identical** |
| $10.00 (all-time median, cheap band) | $20.00 | $15.00 | $12.50 | factors differ |

So the measured all-time benefit is an artefact of a $10.00 median clip that no longer exists. At $18.00
the up-weight is worth +11%, and **every factor at or above 1.112 is the same order**. Confirmation from
the run itself: mild and strong produce live-era deltas of +$76 and +$83 — the entire difference is the
down-weight on 0.6–1.0, not the up-weight on cheap.

Any decision about STANDARD band sizing is therefore downstream of a bigger question the card does not
ask: **does the $20 leg cap rise?** Until it does, the schedule is not testable as specified.

## Finding 2 — the quoted arm is not bookable

AM.7's "notional-neutral" arm renormalises *after* clamping, which pushes legs back through the cap:

| arm (strong map, below ceiling) | notional | ΔPnL all-time | legs above $20 |
| --- | --- | --- | --- |
| neutral (as printed by AM.7) | $44,326 | +$5,161 [+155, +11,305] | **886** |
| as-is (what would actually book) | $39,058 | **+$3,770 [−168, +9,070]** | 0 |

Same shape over 90d (+$1,970 [−454, +4,580] neutral vs +$1,409 [−189, +3,173] as-is) and live era
(+$329 [−120, +809] vs +$83 [−110, +301]). The card's +$5,067 belongs to the unbookable arm. The
bookable arm spans zero in **every** window, including the all-time one whose interval the instrument
now prints as excluding zero (+$5,161 [+155, +11,305]) — that interval moved from [−294, +11,134] to
[+155, +11,305] on ~20 new legs, which is exactly the fragility the card says not to quote.

The bookable arm is also a **de-risking**, not a reallocation: −12% notional all-time, −24% live-era.
If the operator's objective is capital deployment, the map moves the wrong way.

## Finding 3 — the effect is one band and three legs

Bookable (as-is) delta decomposed by band:

| band | all-time Δ (share) | live-era Δ (share) |
| --- | --- | --- |
| <0.20 | +$4,094 (109%) | +$75 (90%) |
| 0.2–0.4 | +$218 (6%) | +$1 (1%) |
| 0.6–0.8 | **−$507 (−13%)** | +$11 |
| 0.8–1.0 | −$35 (−1%) | −$3 |

The 0.6–0.8 down-weight *costs* $507 all-time, because that band returns +4.2% and the map shrinks it.
The 0.8–1.0 factor is noise. The schedule is one cheap-band factor wearing four decorative ones.

Dominance, which is the failure mode the repo's own shadow-read convention exists to catch:

| window | Δ | drop top-3 winners | drop top-10 winners |
| --- | --- | --- | --- |
| all-time below ceiling | +$3,770 | +$3,518 [−490, +8,491] | +$2,941 [−885, +7,929] |
| live era | +$83 | +$17 [−174, +203] | **−$56 [−221, +97]** |

Live era, the top 3 legs are 116% of the delta.

## Finding 4 — the ship rule cannot fire at 150 legs

The gate is "delta > 0 with market-clustered CI excluding zero on ≥150 forward shadowed legs". Market-level
delta on the live-era population: mean +$0.45, SD $7.61 (CV 16.9). A 95% CI therefore excludes zero only at
**~1,098 markets ≈ 1,211 legs**. Simulating forward windows by resampling markets and bootstrapping each
window's clustered delta:

| window size | P(delta > 0) | CI excludes zero (ship rule fires) |
| --- | --- | --- |
| 150 legs | 74% | **2.0%** of 400 windows |
| 300 legs | 82% | 0.2% |

At the all-time effect the fire rate is 13% at 150 legs. Cadence from the DB: 2.4–4.3 eligible legs/day
(median hold 0.5–1.1d), so 150 legs is **35–62 days** and 1,211 legs is **~9–17 months**. A two-month
shadow that reports "not met" by construction is not a test; it is a delay.

## Finding 5 — what actually survives

One factor, not five. Up-weight `<0.20` only (×2.0), everything else flat, live clamp:

| window | notional | ΔPnL | CI | after dropping top 3 winners |
| --- | --- | --- | --- | --- |
| all-time below ceiling | $44,326 → $47,752 (+7.7%) | **+$4,094** | **[+637, +8,900]** | +$3,904 [+478, +8,357] |
| 90d | $28,605 → $30,254 | +$783 | [−394, +2,171] | +$593 [−525, +2,102] |
| live era | $3,627 → $3,711 (+2.3%) | +$75 | [−33, +198] | +$8 [−69, +114] |

The all-time exclusion of zero does not survive dropping ten winners (+$3,265 [−111, +7,766]), and it does
not survive the regime change at all: the 90d window already spans zero. Read the three rows as a
dose–response to the clip ($10 → $12 → $18), which is the mechanism in Finding 1, not as three attempts at
the same test.

Cheap-band ROI is the only band in this book whose all-time clustered interval excludes zero:
+87.9% [+14.7, +202.6] on 207 markets. Live era it is +95.0% **[−12.1, +231.0]** on 34 markets — an
interval 243pp wide, which is the honest statement of how little the current era says.

Note that even this single factor is largely inert live: +$84 of notional across 204 legs. And the
inverse control loses in every window (+$83 → −$233 live era, etc.), so the *ordering* is real in sign.
It is the size that is not established, and the clamp is why.

---

## Decision rule (if the operator wants the question kept open)

Replace the card's gate, which is not falsifiable at 150 legs:

- **Arm:** single factor, `<0.20` only, factor 2.0, clamp untouched. No 0.6–0.8 or 0.8–1.0 factor —
  the first costs $507 all-time, the second is noise.
- **Sample:** ≥150 forward **cheap-band** legs (not 150 legs of any band), which at 0.86 cheap legs/day
  is ~175 days. Alternatively 300 legs of any band with the cheap-band delta reported separately.
- **Statistic:** delta on the **bookable** (as-is) arm, market-clustered bootstrap, after dropping the
  top 3 delta-contributing legs. Ship only if that trimmed CI excludes zero.
- **Guard:** (a) `npx vitest run` on the factor module; (b) the factor must leave `entryPrice ≥ 0.20`
  byte-identical; (c) C-200 untouched.

**Pre-registered refutation** (any one kills it):
1. trimmed forward delta CI includes zero at ≥150 cheap-band legs;
2. the inverse control (+2.0 on 0.8–1.0) matches or beats the forward arm;
3. the cheap band's forward ROI falls below +10% (the fillability break-even is 6.1¢/share, so a band
   earning less than that is paying the spread);
4. the lane's cheap-band cadence falls below 0.5 legs/day, making the sample unreachable.

**What would refute this proposal itself:** a STANDARD base-size change that lifts the cheap band above
$20 (removing the clamp), which would make the five-band map testable again and this recommendation moot.

---

## Recommendation

**Close `standard-band-size-shadow` for the quarter.** Grounds: the card's own ex-top-10 refutation
clause fired on the live era; the arm it quotes is not bookable; the effect is 90% one band and 116% three
legs; its gate cannot fire inside the card's horizon; and the one interval that excludes zero belongs to a
$10-clip regime that the $20 cap has since abolished — the 90d window already spans zero. Record the re-open
trigger as **"the cheap band's live-era market-clustered ROI CI excludes zero at ≥150 cheap-band legs"**
(currently 38 legs, [−12.1, +231.0]).

If the operator would rather keep it alive, the only version worth running is the single-factor arm in the
section above — 2h, default-off, byte-identical when off — and it should be understood as a bet on the
$10-clip-era evidence transferring forward, which the 90d and live-era rows say is unlikely.

- `src/lib/rules.ts`: new `standardBandSizeFactors: string` (default `""` = inert), parsed as
  `lo:hi:factor` triples. Empty ⇒ every factor 1.0 ⇒ byte-identical legacy behaviour.
- `src/lib/band-size.ts`: pure `applyStandardBandSizeFactor(size, entryPrice, factors)`, boundary
  semantics matching §AM.7's `band_of` (`lo ≤ px < hi`, top band closed at 1.0), **no clamp** —
  `clampPaperSize` stays downstream exactly as the v68 maturity factor documents.
- `src/lib/paper.ts`: apply it in the existing `botId !== "BANKROLL_200"` branch, after
  `applyMaturitySizeFactor`. Legacy `deadZoneSizeFactor` / `longshotSizeFactor` stay 1.0 (they are
  shared with C-200's map; re-arming them is the double-sizing v41 neutralised).
- Tests: inert on empty; 0.199 vs 0.200 boundary; clamp applied after the factor; C-200 unchanged.
- `RuleSet` v71 via `scripts/apply-v71.ts` — **operator runs it**. Not me, not this card.

## Reproduce

```
cd ~/polymarket-copybot
python3 scripts/profit-velocity.py --only-am          # §AM.7, read-only, 11s
```
Probes used for the arms AM.7 does not print (bookable arm, band decomposition, dominance trim,
single-factor arm, forward-window power) are in `~/.hermes/cache/scratch/band_*_t_e17694f2.py`; each
opens `prisma/dev.db` with `mode=ro`.

## Verified

- `python3 scripts/profit-velocity.py --only-am` → **exit 0**, 165 lines of output (quoted above).
- `python3 -m py_compile scripts/profit-velocity.py` → **exit 0**.
- `npx tsc --noEmit` → **exit 0, 0 diagnostics**.
- `npx vitest run` → **67 files / 667 tests passed, 10.7s**.
- No `apply-v*.ts` executed. No write to `prisma/dev.db` (every probe opens `file:...?mode=ro`).
- Nothing committed, nothing merged. Worktree `wt/standard-band-size-shadow` left clean;
  deliverables live uncommitted in the main tree (`drafts/`, `data/roadmap.json`), which is where the
  dashboard reads them.
- Dashboard link live: `http://localhost:3013/drafts/standard-band-size-shadow-20261029` → 200.
