# Convex-hull gap over events we already hold — does the 2.2% combinatorial-arb magnitude touch our book?

**Card:** `c200-exclusive-pair-hull-check` · **Lane:** B (measurement / instrument only) · **Run:** 2026-10-29
**Script:** `scripts/exclusive-pair-hull-check.py` (read-only; SELECTs on `prisma/dev.db` + keyless data-api tape)
**Data:** `drafts/exclusive-pair-hull-check-20261029.json` · **Live link:** `:3013/drafts/exclusive-pair-hull-check-20261029`

No rule, size, gate, booking or threshold was touched. Nothing in `prisma/dev.db` was written.

---

## Key insight

The published magnitude does **not** reproduce at our scale, and the relations we sit inside are **not** mispriced against us.

- On the 239 legs we can actually measure, the guaranteed bundle profit of the three-way winner partition we hold is a **median 0.50% of committed capital** before costs — not 2.2%.
- Charge a **1¢ per leg** spread (three legs) and **1 of 239 legs** still clears 2.2%. At 2¢/leg, **none** do.
- Our fills sat **below** the relation-implied fair value on average (**−0.59¢/share**; **−3.18% of $3,130 stake**), i.e. whatever gap existed was paid *to* us, not by us.
- The card's own named case is **not an arb shape at all**: `swe-org-gais-2026-10-18` carries **no draw market**, so the partition is open and no buy-bundle exists by construction (Org YES + Gais NO is a correlated double-down, not a hedge).

---

## What was measured

Population: every head-to-head fixture slug `<league>-<codeA>-<codeB>-YYYY-MM-DD` where the book holds a leg on a **winner-partition market** (suffix `codeA` | `codeB` | `draw`, each its own binary `marketId` — verified against the venue's `eventSlug` in the data-api tape).

Relation (closed 3-way partition — the concrete instance of the hull condition):

| bundle | cost | payout | guaranteed profit |
|---|---|---|---|
| buy-all-YES | S = p_A+p_B+p_draw | 1 | 1 − S |
| buy-all-NO | 3 − S | 2 | S − 1 |

Prices are the venue's public **trade tape**, last print at or before our entry timestamp, converted to one YES axis (an outcomeIndex-1 print at p is 1−p). That is a mid/last-print proxy, not an executable quote — see Reality checks.

| class | fixtures | legs held | legs measurable |
|---|---|---|---|
| closed 3-way partition | 152 | 452 | 239 (73 clean ≤15 min, 166 stale, 213 dropped) |
| open hull (no draw market) | 49 | 147 | 144 |

`dropped` = a partition member had **no print at or before** our entry, so no simultaneous sum exists.

---

## Partition sum S at our entry times (239 legs)

| basis | median | mean | p25 / p75 | min / max |
|---|---|---|---|---|
| all legs | 1.0000 | 1.0056 | 1.00 / 1.01 | 0.96 / 1.0902 |
| clean (≤15 min staleness) | 1.0000 | 1.0041 | 1.00 / 1.01 | 0.98 / 1.03 |

| threshold | all legs | clean legs |
|---|---|---|
| \|S−1\| > 0.005 | 158/239 (66.1%) | 35/73 |
| \|S−1\| > 0.010 | 90/239 (37.7%) | 20/73 |
| \|S−1\| > 0.020 | 22/239 (9.2%) | 3/73 |

The sums sit on the venue's 1¢ grid. A 66% hit rate at ">0.5¢" is the grid, not an edge: half the mass is exactly 1.00.

## Guaranteed bundle profit, % of committed capital

| basis | median | p75 | max |
|---|---|---|---|
| pre-cost, all legs | 0.50% | 1.01% | 4.73% |

| bar | pre-cost | 1¢/leg spread | 2¢/leg spread |
|---|---|---|---|
| ≥ 1.0% | 91/239 (38.1%) | 4/239 | 1/239 |
| ≥ 2.2% (paper) | 5/239 (2.1%) | 1/239 | 0/239 |
| ≥ 3.2% (paper, at resolution) | 4/239 (1.7%) | – | – |

The five legs at ≥2.2% all sit on **stale prints** (26 min to 12 h old) and are the same handful of thin international fixtures (`fif-chn-tjk`, `fif-sri-mri`, `fif-chn-nzl`). One of them (`argpn-gue-alm-2026-10-18`, S=0.96, 4.17%) is 26 min stale and is the only leg that survives a 1¢/leg charge.

## Were the relations mispriced *against us*?

Entry price minus relation-implied fair value of the same token (positive = we paid above what the other two legs implied).

| book | n | mean/sh | stake | gap-weighted |
|---|---|---|---|---|
| BANKROLL_200 | 145 | −0.0121 | $1,583 | −$113.67 (−7.18%) |
| STANDARD | 94 | +0.0037 | $1,547 | +$14.19 (+0.92%) |
| all | 239 | −0.0059 | $3,130 | −$99.47 (−3.18%) |

The C-200 number is mechanical: the lane books `max(0.01, intent − 0.02)`, so it is structurally ~2¢ below wherever it was handed. STANDARD, which books the detected price, is **+0.9% above** the relation-implied fair — small, and the direction that matters is that neither lane is systematically paying through the relation.

## Open hulls — the card's named case

`swe-org-gais-2026-10-18` has **no draw market** (its markets: org, gais, btts, exact-score, totals, spreads, halftime). With a missing outcome the partition is **not exhaustive**, so no buy-all bundle exists and the only admissible test is the exclusion half: S2 = p_A + p_B must be ≤ 1.

| open-hull read | value |
|---|---|
| legs measurable | 144/147 |
| S2 median / p25–p75 / max | 0.750 / 0.73–0.79 / 0.935 |
| S2 > 1.005 (exclusion violated) | 0/144 |
| S2 > 1.02 | 0/144 |

Zero violations, with the mass ~25¢ below 1 — that 25¢ is the unpriced draw, exactly as the structure implies. `ucl-mnc-aek1-2026-10-20` is not an exclusive pair either: its second leg (`-total-4pt5`) is an independent total, not a member of the winner partition.

---

## Reality checks (what this read is not)

1. **No depth.** `data/l2` holds one file per token, but only **317 of 717** partition-market slots appear in the L2 asset map and **1 of 239 legs** has all three partition books within 15 min of the entry. The recorder's 25-market universe catches a team market here and a draw market there, never the three legs of one fixture at once. An executable, size-aware read is **not possible at our scale today** — this is measured, not assumed.
2. **Last print, not a quote.** Staleness: 166/239 legs rest on a print older than 15 min. Spread is charged as a sensitivity, not extracted from a book.
3. **Scope.** Only head-to-head fixtures with per-code winner markets. Untouched: bracket partitions (weather temperature, tweet-count bands) and candidate sets (`will-<name>-win-…`, LeBron next-team), which are the largest families by market count — they need the same tape method with their own partition rules.
4. **No fees modelled.** Polymarket's sports taker fee would only make the surviving 1 leg worse.

## Verdict

- **The 2.2% figure is a 255k-contract, full-depth number.** At our book's scale the closed three-way relations we hold price at a **0.50% median** guaranteed bundle margin, and the survivors after a realistic 1¢/leg cost are **1 signature in 239** — below the cost of building the machinery.
- **The relations were not mispriced against us.** Our fills averaged *below* the relation-implied fair value; the C-200 −1.21¢/share is the maker-fill model, not a market signal.
- **The card's named cases don't support the hypothesis.** One is an open hull (no draw market), the other pairs a winner market with an independent total.
- **Do not build `phase-c` on this evidence.** Nothing here justifies relation-discovery infrastructure at our scale.

## Recommendations (measurement-only — approval required, nothing applied)

1. **Close the instrument gap before any re-read:** add partition-complete fixture sets (all of A/B/draw, or bracket-exhaustive sets) to the L2 recorder universe so Σ ask and Σ bid can be measured at our sizes. Today's 1/239 coverage makes an executable claim unfalsifiable. This touches a live instrument, so it needs an explicit go-ahead — I did not make the change.
2. **If approved, pre-register the re-read** as: median executable bundle margin at our $20/$100 sizes vs a 1¢/leg cost bar, with the same stale-print exclusion.
3. **Extend to bracket partitions** (weather, tweet bands) only if (1) lands — those families carry 1,000+ of our markets and are the only place where a large-N hull read is possible.

## Verification

```
$ python3 -m py_compile scripts/exclusive-pair-hull-check.py   → COMPILE_OK
$ python3 scripts/exclusive-pair-hull-check.py                → exit 0, figures above
```
`git status` in the worktree: script uncommitted (operator merges); the only repo-tree writes from this card are `drafts/exclusive-pair-hull-check-20261029.{md,json}` and a tape cache outside the repo (`~/.hermes/cache/scratch/hull-tape/`, 554 files).
