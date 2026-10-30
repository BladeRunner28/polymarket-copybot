# STANDARD esports bleed — re-cut 2026-10-29: still NOT ESTABLISHED, and the revisit trigger is dead

Lane A proposal. **No RuleSet change is applied or requested today.** What is requested is a
decision on a rail and on a trigger (`standardBlacklist` stays `[]` unless you say otherwise).

Reproduce everything below with one read-only command (no DB write, no apply script):

```
cd /Users/xsnyde2/polymarket-copybot
DATABASE_URL="file:$PWD/prisma/dev.db" npx tsx scripts/esports-bleed-recut.ts
```

Accounting: `src/lib/accounting.ts` (dedupe first leg per wallet|market|outcome, terminal
statuses only, cost = `simulatedPositionSize` in DOLLARS, market-clustered bootstrap CI).
Categories: stored `marketCategoryClass` then the live classifier, as in
`scripts/category-cohort-report.ts`. Population: STANDARD, all time, 3,581 deduped legs,
$43,425 notional, ROI **+3.60%**.

---

## Key insight

The card's own decision rule has now failed twice, for a new reason the first pass could not
see: **the lane has stopped producing esports legs.** The 615-leg sample that produced the
-6.2% was almost entirely booked before v58 (600 of 618 legs). The current era has logged
**18 esports legs total**. So the prescribed remedy — "revisit at ~2,500 esports legs" — is
not slow, it is unreachable: at the last 30 days' cadence that is **~2,300 days (~6.3 years)**.

Second new fact: the loss is *diffuse*, not concentrated. It sits in 507 markets, 255 losing
and 248 winning; the three worst markets carry **4.9%** of the gross loss. So the card's
"a couple of bad bets" refutation does not fire — this is a class-level pattern, not noise
from two bad nights. It just isn't measurable at league granularity.

---

## 1. Pre-registered rule: zero leagues qualify

Rule (from the card, unchanged): *cut only leagues whose deduped 90d ROI has a
market-clustered CI upper bound < 0 AND n ≥ 25 legs.*

```
esports league   legs  mkts   notional      PnL      ROI    95% CI (mkt-clustered)
esports-lol       230   200     $2,537    $-227    -9.0%     [-24.4, +7.0]
esports-cs2       185   151     $2,163    $-235   -10.9%     [-27.5, +6.0]
esports-dota      101    69     $1,160     $114    +9.8%     [-18.9, +39.4]
esports-valorant   73    64       $909     $-86    -9.5%     [-37.6, +21.5]
esports-other      29    23       $269       $1    +0.5%     [-16.6, +15.6]
```

Last 90 days, same rule:

```
esports-lol       163   142     $1,829    $-191   -10.4%     [-26.9, +7.1]
esports-cs2       154   122     $1,807    $-135    -7.5%     [-23.6, +9.7]
esports-dota       71    41       $838     $220   +26.2%     [-12.8, +65.4]
esports-valorant   60    52       $788     $-141  -17.9%     [-49.8, +16.3]
```

Every upper bound is above zero, in both eras. **Zero leagues qualify. No cut.**

## 2. The class itself, and the era split

```
slice        legs  mkts   notional      PnL      ROI    95% CI (mkt-clustered)
esports       618   507     $7,039    $-434    -6.2%     [-15.6, +3.8]
pre-v58       600   491     $6,715    $-414    -6.2%     [-16.1, +3.9]
v58+           18    16       $324     $-20    -6.2%     [-57.9, +57.0]
```

The card's first refutation condition — "if the v58+ era re-cut shows esports at n ≥ 100 and
ROI > 0, the loss is era-driven" — **does not fire**, because there are only 18 current-era
legs. Note the point estimate is identical across eras (-6.2%, -6.2%), which is what you would
expect if the leak were structural rather than era-specific; but 18 legs cannot confirm or
refute anything.

Era is journal `ruleSetVersion` (project convention), not `openedAt`.

## 3. Cadence — why the trigger is dead

```
month      esports legs opened   PnL
2026-07            167          $-172
2026-08            431          $-206
2026-09              9           $-55
2026-10             11            $-1
```

The lane generated 431 esports legs in August and 11 in October. This is not a slow sample;
it is a closed tap (v63/v64 STANDARD band-skip + open-position cap, and the lane's overall
slowdown to 133 legs/30d).

## 4. Sample actually required (measured from the CI width, not assumed)

```
esports CI 19.4pp wide at 618 legs [-15.6, +3.8], point -6.17%
to halve the width (9.7pp)                                   -> 2,472 legs
to push the upper bound to 0 at the same point estimate       -> 1,535 legs
esports legs in the last 30d: 12  -> 2,293 more days (6.3y) at that cadence
```

## 5. Post-hoc pooled cohort — the only test with power today (NOT the pre-registered rule)

Pooling the three individually-negative leagues is a **specification change**. It is reported
here because it is the closest thing to a decision-grade measurement in the book, and hiding
it would be worse than labelling it:

```
cohort                    legs  mkts   notional      PnL      ROI   95% CI (mkt-clustered)
lol + cs2 + valorant       488   415     $5,609    $-549    -9.8%     [-20.2, +0.6]
dota                       101    69     $1,160     $114    +9.8%     [-18.9, +39.4]
```

Upper bound **+0.6** — the tightest negative interval in the whole STANDARD book, still
containing zero. It would clear at roughly double this sample, which the lane will not supply
on its current cadence.

## 6. Reality checks before anyone spends a RuleSet version on this

- **Economic size.** Cutting lol+cs2+valorant historically saves **$549** on a $43,425 book
  (book ROI 3.60% -> 5.58%, but only because the denominator drops by $5,609 too). $549 is
  ~1.3% of cumulative notional and about 5 months of the lane's entire esports activity.
- **Population.** The rail would guard a cohort the lane barely trades: 11 esports legs in
  October, 18 since v58. Even a *correct* cut has almost no live effect.
- **Direction is consistent, magnitude is not.** Three independent league cohorts are negative
  (lol -9.0%, cs2 -10.9%, valorant -9.5%) and dota is +9.8%. That constellation is weak
  evidence of a real class leak, and it is exactly why a *blanket* esports ban stays wrong.
- **Mechanism is ready if you ever want it.** `scripts/score-trades.ts:766` selects
  `standardBlacklist` for STANDARD and matches it against the raw slug (`t.marketCategory`);
  `src/lib/rules.ts:457` defaults it to `[]`. A league cut is one populated field, no code
  change. (`maxMarketSlugPositions` remains C-200-only — `score-trades.ts:776` — a separate
  scoping gap, not part of this decision.)

---

## Verdict

**Do not apply `standardBlacklist`.** The pre-registered rule finds zero qualifying leagues,
the current-era sample is 18 legs, the loss is too diffuse to localise to a league, and the
economic stake ($549, 1.3% of notional, on a cohort that has effectively stopped arriving) is
not worth a RuleSet version.

**And retire the card's trigger.** "Revisit at ~2,500 esports legs" is unreachable at 12
legs/30d (~6.3 years). Keeping it means this card sits in the backlog forever looking like
pending evidence when it is actually closed evidence.

## What is being asked for approval

1. **No cut.** `standardBlacklist` stays `[]`. (No RuleSet version, no code change.)
2. **Re-base the revisit trigger** from a leg count to a cadence-and-era condition:
   re-open only when the *current era* (journal `ruleSetVersion` >= 58) logs **>= 100 esports
   legs**, or when the pooled cohort's market-clustered CI upper bound crosses below 0 at any
   n. Otherwise the question is closed, not pending.
3. **Optional, and explicitly a rule amendment:** adopt the pooled cohort
   (lol+cs2+valorant) as the unit of the rule instead of the per-league unit, with the same
   CI-upper-bound < 0 gate at n >= 400. I recommend **against** doing this today — a
   specification chosen after seeing that pooled +0.6 upper bound is post-hoc, and the honest
   path is to pre-register it *before* more legs arrive, which part (2) already does.

## Refutation conditions (what would make this wrong)

- **Refuted by data:** any esports league reaches n >= 25 in the current era with a 90d
  market-clustered CI upper bound < 0 -> cut that league.
- **Refuted by data:** the pooled lol+cs2+valorant cohort's clustered CI upper bound drops
  below 0 -> escalate the cut for approval at that measurement, regardless of the leg count.
- **Refuted by structure:** if the apparent loss turns out to be concentrated in fewer than 3
  markets it is a couple of bad bets and the whole class question is void. **Checked this run:
  it is diffuse** (507 markets, worst 3 = 4.9% of gross loss), so this refutation does not fire.
- **Refuted by economics:** if STANDARD's esports cadence returns to >= 100 legs/90d, the
  stake grows with it and the decision should be re-priced rather than held.

## Verified

- `npx tsc --noEmit` -> exit 0, zero diagnostics
- `npx vitest run` -> 67 test files / 667 tests passed
- No `apply-v*.ts` run, no write to `prisma/dev.db`, no RuleSet change, nothing merged.

Instrument: `scripts/esports-bleed-recut.ts` (read-only).
