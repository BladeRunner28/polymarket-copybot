# Sizing: the rails that exist, the rail that binds, and which lane is mis-sized

**Date:** 2026-10-20 · **Lane:** A for the sizing change, Lane B for the dead-field label · **Status:** measured

---

## 1. Three "max size" numbers exist, and the one on display is the one nobody reads

| source | STANDARD | BANKROLL_200 | enforced? |
|---|---|---|---|
| `BotBankroll.minPositionSize` / `maxPositionSize` | 0.25 / 20.00 | 0.10 / **30.00** | **NO — read nowhere** |
| `BOT_LIMITS` in `src/lib/safety.ts:18` | 0.25 / 20.00 | 0.10 / **20.00** | legacy path only |
| `rules.kellyMaxSizeUsd` (`score-trades.ts:837`) | — | **100** | **YES** — overrides the above |

`maxPositionSize` and `minPositionSize` each appear **zero times** in the repo outside the script that
produced this table. They are declared in the Prisma schema, present in `BotBankroll`, and consulted
by nothing.

Meanwhile `clampPaperSize(usd, botId, maxUsd)` at `src/lib/safety.ts:45` computes
`hi = maxUsd !== undefined ? Math.max(limits.min, maxUsd) : limits.max` — so when the Kelly path
passes `maxSizeUsd: 100`, the effective ceiling is **$100**, not the `BOT_LIMITS` $20 and certainly
not the table's $30.

**Observable consequence:** 69 C-200 clips exceed the $30 the table advertises, totalling
**$5,491.37**, with a maximum of **$100.00** — and one of them was booked **today (2026-10-20)**.
Nothing is broken in the book; the *advertised rail* is fiction. A dashboard reading
`BotBankroll.maxPositionSize` would report a $30 cap against a book that routinely books $100.

## 2. C-200's sizing follows edge. STANDARD's runs against it.

ROI by size quintile, realised legs deduped to the first per (wallet, market, outcome), cost basis =
`simulatedPositionSize` (dollars), CIs clustered by market.

**BANKROLL_200** — 1,812 legs, $15,271 cost, $6,512.25 PnL:

| size bucket | n | cost | ROI |
|---|---|---|---|
| < $2.48 | 319 | $375 | −1.43 % |
| $2.48–4.99 | 387 | $1,331 | +11.80 % |
| $4.99–9.97 | 683 | $3,837 | +9.81 % |
| **≥ $9.97** | **423** | **$9,727** | **+61.52 %** CI [+16.3, +66.8] |

Rank correlation across quintiles: **+0.808**. The top size bucket is 64 % of the lane's cost and
**92 % of its PnL**, and its clustered CI excludes zero. C-200's capital is concentrated where the
edge is.

**STANDARD** — 3,198 legs, $39,004 cost, $1,195.23 PnL:

| size bucket | n | cost | ROI |
|---|---|---|---|
| < $8.40 | 637 | $5,107 | +9.07 % |
| $8.40–10.20 | 610 | $5,641 | +7.39 % |
| $10.20–12.20 | 609 | $6,745 | +7.63 % |
| $12.20–18.00 | 580 | $7,771 | **−2.32 %** |
| **≥ $18.00** | **762** | **$13,740** | **−0.14 %** |

Rank correlation: **−0.860**. STANDARD's two largest size buckets hold **55 % of its notional
($21,511)** and produce **−$199.51**. The smaller a STANDARD clip, the better it did.

## 3. So the profit review's claim was half right, and it matters which half

"Volume allocated inversely to edge" is **true for STANDARD and false for C-200** — i.e. true for the
lane carrying 87 % of the book's notional and the lane that loses money, false for the lane that
earns $0.3818 per capital-day.

That reframes the sizing problem: it is not a portfolio-wide misallocation to be fixed by a global
sizing rule. It is **STANDARD's size path**. Whatever produces a STANDARD clip at $18–20 is
systematically choosing the worst opportunities, and whatever produces a C-200 clip above $10 is
systematically choosing the best.

## 4. Reality checks

1. **Every STANDARD quintile CI spans zero** (−11.4 to +20.3, etc.). The −0.860 rank correlation is a
   *directional hint across five buckets*, not an established gradient. Five cells with CIs that all
   span zero cannot individually support a claim; the monotone ordering is suggestive, and the
   $21,511-for-−$199 fact is real arithmetic regardless of significance. **Do not size a rule change
   on this without a fresh forward window.**
2. **C-200's +61.52 % rests on 423 legs and is dollar-weighted** — a few large winners dominate a
   "$100" clip that is itself the Kelly ceiling. The unweighted per-leg clustered CI for the lane as
   a whole is [+7.4, +22.8] while the dollar-weighted ROI is +42.64 %; those are different quantities
   and must not be compared to each other.
3. **An empty quintile appeared** (`[$4.99, $4.99)`, n=0) because percentile ties cluster on a
   repeated clip value. The buckets above are the collapsed four. Any future sizing read must check
   for tie-collapsed edges rather than trusting `np.percentile` blindly.
4. **The $100 clips are not new.** The pattern spans 2026-09-28 → 2026-10-20, so this is a standing
   configuration, not a regression introduced today.

## 5. What this implies

**Lane B (label that lies):** nothing to change in behaviour, but a reader of `BotBankroll` is being
told a rail exists that does not. Either the columns get populated with the *effective* ceilings and
a comment says they are display-only, or they are dropped. Leaving a dead $30 next to a live $100 is
how a dashboard ends up contradicting the book — the same class of defect as the hardcoded ladder
percentages found earlier.

**Lane A (the actual sizing question):** STANDARD's large clips underperform its small ones by a
monotone margin. The candidate change is a STANDARD-specific size ceiling well below the current $20
— but every quintile CI spans zero, so the honest first step is a **forward window**: tag STANDARD
legs by size bucket, hold for ~2 weeks, and require the inverse gradient to reproduce with clustered
CIs before touching a rule. That is a pre-registration, not an implementation.

## Provenance

| figure | source |
|---|---|
| clip distribution, quintile ROI, rank correlations | `scripts/sizing-read.py` |
| dead-field proof | repo-wide grep for `minPositionSize` / `maxPositionSize`: 0 hits outside that script |
| effective clamp | `src/lib/safety.ts:18` `BOT_LIMITS`, `:45` `clampPaperSize`, `score-trades.ts:837` |
| 69 clips > $30, max $100 | `PaperTrade` where `botId='BANKROLL_200'` |
| $0.3818 vs $0.0114 per capital-day | capital-day review 2026-10-20 |
