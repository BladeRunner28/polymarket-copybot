# v41 category seats: the seat is now consumed at the booking point

**Card:** `category-seats-never-released` · **approval:** `apr-category-seats-never-released`
(operator, approvals inbox, 2026-11-12T19:32Z) · **applied:** 2026-11-12

**Verdict: APPLIED AS A BASIS FIX.** `c200CategoryCounts` no longer counts candidates that
passed the v41 gate and were refused later in the same run; the seat is consumed only where a
C-200 leg is actually dispatched. Measured admissions delta today: **0**. The printed refusal
string changed with it, so it can no longer claim a count it does not have.

## 1. What was wrong

`scripts/score-trades.ts` seeded `c200CategoryCounts` from the C-200 open rows at the top of a
run, then incremented it in the **ELSE** branch of the v41 category check — i.e. the moment a
candidate **passed** that gate. Nothing ever decremented it, and the gate is checked *before*
the per-leg loop, so every refusal that fires later in the same run left its seat consumed for
the rest of that run:

| later refusal | where it fires |
|---|---|
| open-position cap (C-200 / STANDARD) | per-leg loop, before the booking call |
| v45 slug blacklist, per-slug cap | per-leg loop |
| STANDARD / C-200 band skips | per-leg loop |
| v47 C-200 high-entry cap | per-leg loop |
| v55 per-market (legs / notional) | per-leg loop |
| v58 per-wallet notional | per-leg loop |

So `maxCategoryPositions` could read as reached while the category held fewer open legs — and
the journal line `category concentration (<cat> would be N/M)` described attempts, not positions.

## 2. Evidence (measured, not asserted)

Instrument: `scripts/category-cap-blocked-legs.ts` (+ `src/lib/category-cap-blocks.ts`), read-only.
Re-run today for this change (all-time, non-demo decisions carrying a category-concentration
refusal; true open reconstructed from booked C-200 legs' own open/close intervals through
`researchCategoryFor`; settlement = the market's own winning label).

```
refused 7 copies across 5 distinct market+question outcomes
class: genuine 0 / phantom 7 / unknown 0
basis form: attempts-unlabelled 7 / labelled 0 / open-position 0 (post-fix violations: 0)
other decision-level blocker present on 7/7 -> releasing the seat alone would admit 0
settlement known 7/7 (market 7; 0 undetermined)
priced 7: mean +$0.14 per $1, sum +$0.96, ex-top-10 $0.00, wins 6
REACHABILITY: post-v41 peak concurrent open legs in any category = 15 vs cap 40
```

All 7 lifetime refusals landed in one 0.6 s burst on 2026-09-17T15:08:43Z, all
`Defense/Geopolitics would be 41/40`, with a true concurrent open book of **0** in that category —
7/7 phantom, the purest form of this leak. All 7 also carried the drawdown gate in the same
`risksJson`, so releasing the seat admits **nothing** today.

Both clauses of the card's decision rule pass: **0.0 admissions/day** (< 1/day) and the released
legs are **not net-negative** (+$0.14 per $1, though the value arm is moot). Value was never the
argument — the argument is that a gate number that describes attempts is not a measurement.

## 3. The change

`scripts/score-trades.ts`

- the gate now reads the counter **as a position count** and asks a single helper whether one more
  leg would exceed the cap (`categorySeatDecision`); it no longer mutates the counter:
  ```ts
  const seat = categorySeatDecision(c200CategoryCounts.get(tradeCat) ?? 0, rules.maxCategoryPositions);
  if (seat.blocked) riskGates.push(formatCategoryCapBlock(tradeCat, seat.openPositions, rules.maxCategoryPositions));
  ```
- the counter is incremented **only at the booking point**, beside `legsOpened++`, and only for
  `BANKROLL_200` (the counter's seed is the C-200 open rows):
  ```ts
  if (botId === "BANKROLL_200" && tradeCat) c200CategoryCounts.set(tradeCat, (… ?? 0) + 1);
  ```
- no decrement path exists to maintain against gate order: the seat is never taken until the leg
  books.

`src/lib/category-cap-blocks.ts`

- `formatCategoryCapBlock(category, openPositions, cap)` now writes
  `category concentration (<cat> open 40/40 on an open-position basis)` — the number IS the open
  leg count, so the string cannot lie about its basis again.
- the parser reads **three** forms (historical `would be N/M`, the 2026-11-06
  `… on an attempts basis; true open K`, and the new position form) with separate regexes so
  neither can absorb the other; on the position form `wouldBe` is derived as `open + 1` so every
  form answers `wouldBe > cap` identically.
- `categorySeatDecision(open, cap)` is the gate arithmetic in one tested place.
- `positionBasisViolation(block)` is the card's own refutation, machine-checkable: a post-fix
  refusal that states an open count **below** the cap means the counter went back to counting
  attempts. `scripts/category-cap-blocked-legs.ts` prints that count.

## 4. Verification

- `npx tsc --noEmit` — clean on every touched file (one pre-existing error remains in the
  untracked `scripts/apply-v73-c200-cheap-band-clip.ts`, from a sibling session's work in the
  same tree; untouched here).
- `npx vitest run` — **1,003 tests / 93 files pass** (was 999/93 before this commit's new tests:
  +4 seat-decision tests; the file went 12 → 23 tests across the two passes).
- The defect is pinned by a test **with a working negative control**: 41 candidates that pass the
  gate and die downstream produce zero refusals on the new counter, while the same loop under the
  OLD mutation (consume on pass) produces exactly one — `expect(legacyBlocked).toBe(1)`.
- The read-only instrument was re-run **after** the parser change and reproduces its published
  numbers unchanged (7 refusals, 7 phantom, 0 admissions), so the basis repair did not break the
  measurement that justified it.

## 5. Refutation (pre-registered, unchanged from the card)

The change is wrong if any of these appears:

1. a post-fix refusal printing an open count **below** the cap — counted by
   `positionBasisViolation` and printed by the instrument;
2. any category holding **> 40 concurrent C-200 legs** (the rail stopped binding);
3. a forward week in which the repair admits ≥ 1 leg that loses at settlement.

Given the reachability number (post-v41 peak 15 vs cap 40), (2) is also the reason a *genuine*
refusal is not expected to reappear at this cap — that is a property of the book, not of the fix.

## 6. Rollback

`git revert <this commit>` — no RuleSet version, no threshold, no sizing field, no schema change.
The revert also restores the previous printed form; historical rows keep parsing either way.

## 7. Deliberately NOT changed (still open, not approved)

The counter seeds from **C-200** rows while the gate blocks the **decision**, which is scored for
both lanes — so a STANDARD leg in a category at its C-200 cap is still gated by C-200 state. That
is a lane-scope question and rescoping it would change what the bot admits; it stays on the card
as a known, unapproved follow-up rather than being folded into a basis fix.
