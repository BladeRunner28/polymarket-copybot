# Single-loss concentration: the test ran, both clauses fired, the rail is armed at 20%

**Card:** `kelly-single-loss-concentration-test` (kelly rec 4, approved 2026-10-21 as the TEST only)
**Approval of the change:** approvals inbox `apr-kelly-single-loss-concentration-test`, decided
2026-11-13T16:07:22Z → kanban `t_e0a4c4ad`
**Instrument:** `scripts/kelly-single-loss-read.py` (`--self-test` 10/10, mutated arm proven RED)
**Shipped:** one RuleSet field, `maxConcurrentLongshotPctOfNetWorth = 20`, RuleSet **v73**
**Revert:** `npx tsx scripts/apply-longshot-concurrency.ts --apply --revert` (writes 0), or set the
field to 0 on the active RuleSet. No booking, ledger or PnL path is touched.

---

## 1. What was pre-registered, and what it asked

The card was written on 2026-10-21 with a test and a decision rule, and its own wording gated the
*rule change* on a separate yes. Verbatim:

- **HYPOTHESIS** — the $100 Kelly clip binds on every long-shot position (= 1.3% of net worth per
  full loss), so a cluster of concurrent long-shots can produce a correlated drawdown the 20%
  drawdown gate is too coarse to catch.
- **DECISION RULE** — propose a per-position cap *or* a concurrent-long-shot limit ONLY if
  concurrent full-loss exposure exceeded 10% of net worth on ≥1 day in the read window, **or** a
  single leg lost >1.3% of net worth twice in 30 days.
- **REFUTATION** — if it never exceeded 10%, close the card with that null.

Both clauses fired. That is a "propose" result, not a "ship" result — §6 is why the level is 20%
and not 10%.

## 2. Reproduction (re-run 2026-11-13, independent of the session that first measured it)

Re-running the instrument reproduces the committed read exactly; nothing below is quoted from the
card. Population `PaperTrade.isDemo = 0`: **2,830 C-200 legs / 10,396 STANDARD**, window
2026-07-14..2026-11-13. Bases: level = one open-position set at one entry instant; days = UTC
calendar days of entry; clock = `openedAt`, exit = `closedAt ?? resolvedAt`; at-risk =
`simulatedPositionSize` (dollars at risk, **never** size × price); net worth = principal + realised
PnL of legs closed before the instant (**realised-only** — unrealised marks would raise NW and
loosen the percentage).

Live net worth at the read: **C-200 $7,570.95** (principal $1,900.00 + realised $5,670.95);
**STANDARD $20,580.25** (principal $11,092.91 + realised $9,487.34).

## 3. Clause 1 — concurrency (FIRED)

| lane | entry-days | median | p90 | p99 / max | days >5% | >10% | >15% |
|---|---|---|---|---|---|---|---|
| BANKROLL_200 | 90 | 4.41% | 25.18% | 60.85% | 40 (44%) | **22 (24%)** | 13 |
| STANDARD | 116 | 13.58% | 18.77% | 21.33% | 115 (99%) | **103 (89%)** | 36 |

Worst C-200 days: 2026-09-14 **60.85%** (25 legs, $1,121 at risk on NW $1,842), 09-15 60.2%,
09-16 57.5%, 09-12 55.2%, 09-13 53.7%. Concurrent leg count: median 11, p90 27, max 35.
STANDARD peak: 2026-08-31 **21.33%** (396 legs, $4,172 on NW $19,563).

**Trailing 30 days pulls the number down hard on C-200**: 29 entry-days, median **1.60%**, max
14.79%, 2 days over 10%. That is why the peak is a September artefact of a $1,842 net worth, not
a description of today's risk. STANDARD's trailing 30d is median 12.86% / max 13.63% — **every one
of its 27 entry-days is over 10%**, because its book is 169-396 concurrent long-shot legs at a ~$11
clip, not a cluster.

## 4. Clause 2 — single-leg loss (FIRED, and nearly tautological)

C-200: 340 settled long-shot legs, 87 of them full losses. **30 all-time lost more than 1.3% of net
worth; 11 of those closed inside the last 30 days** (2026-10-17 ×3, 10-28, 11-01, 11-06, …).
STANDARD: 548 settled long-shot legs, median loss 0.04% of NW, max **0.11%**, **zero** breaches.

Honest label: the clause is close to tautological at the current clip. The $100 Kelly cap **is**
1.32% of realised NW, so any two full $100 long-shot losses inside 30 days fire it. It answers
"did two maximum-size long-shots go to zero", not "is the book concentrated". Clause 1 is the
clause that carries the finding.

## 5. What the peak-exposure days actually realised — the case against a tight cap

| lane | days with peak >10% | realised on those days | opened on those days |
|---|---|---|---|
| BANKROLL_200 | 21 | **+$4,544.73** | $6,055.30 |
| STANDARD | 69 | **+$3,128.46** | $5,130.78 |

High-concurrency days were, on average, **profitable**. Two more facts point the same way:

- **The per-position cap is not the instrument.** The 60 C-200 legs at the $100 clip book
  **+$3,141.77** lifetime, but the top 10 carry **+$5,749.83** and the other 50 are **−$2,608.06**.
  The clip's apparent profitability is a top-10 artefact, so tightening it is not supported and
  was not proposed.
- **STANDARD's concentration is diversification, not clustering.** 13.6% of net worth spread over
  169-396 legs, per-leg maximum loss 0.11% of NW, worst realised day −$176 (0.86% of NW).

## 6. The level: why 20% and not 10 or 15

Counterfactual: admit long-shot legs in entry order; block any leg that would push the concurrent
long-shot book above the level; a blocked leg never happens, so it never raises the net worth the
cap is measured against (the bug class that once loosened this very rail). "Net effect" is the
realised PnL of the blocked legs — i.e. what the rail would have prevented. It does **not** model
redeploying the freed capital, so it is not a claim about what the book would have earned instead.

| level | C-200 blocked / realised | STANDARD blocked / realised | verdict |
|---|---|---|---|
| 10% | 74 legs / **+$1,594.98** | 338 / **+$1,667.42** | blocks net winners on both lanes |
| 15% | 58 / **+$1,451.81** | 132 / **+$744.94** | blocks net winners on both lanes |
| **20%** | 33 / **−$849.76** (saves $849.76) | 23 / +$182.20 (costs $182.20) | **chosen** |
| 25% | 30 / −$643.32 | 0 / none | looser, binds on nothing in STANDARD |

20% is the tightest level that is value-positive on the lane where the peak occurred, and it keeps
the two rails coherent: a total wipeout of a lane's long-shot book can then *reach* the 20%
drawdown gate but cannot overshoot it. Net across lanes: **+$667.56** avoided.

## 7. What shipped

One field, `maxConcurrentLongshotPctOfNetWorth`, default **0 = disabled** (a ruleset lacking it
behaves byte-identically to pre-v74). RuleSet **v73**, written by
`scripts/apply-longshot-concurrency.ts`, read back through `getActiveRules()`.

Rule, enforced at admission next to the v55 per-market and v58 per-wallet rails, on the FINAL size
and immediately before booking:

> refuse a new leg whose entry price is `< longshotMaxPrice` when
> (open long-shot notional **on this lane**) + (this leg) **> 20% × (this lane's realised net worth)**

Design decisions that matter:

- **Per lane, not portfolio.** It reads one lane's own book against that lane's own net worth, so
  it can never freeze both books the way `isPortfolioGate()` reasons do (those fire before the
  per-bot loop and leave no leg-block trail). Locked by a test.
- **Realised net worth** (`principal + realisedPnl`), the basis `ddBasis` already declares — the
  strict direction.
- **Boundary inclusive** (fires only above the cap), like v55/v58.
- **Not a lane brake.** A leg that is not a long-shot is never blocked, even when the long-shot
  book is already over its cap — the rail bounds the cluster, not the lane.
- **The dollar is consumed at the booking point**, not when the candidate passes the gate, so a
  refusal later in the same run cannot eat headroom (the v41 category-seat defect, fixed
  2026-11-12).
- **A no-identity lane is not halted.** If a lane's realised net worth is ≤ 0 the cap is undefined
  and the rail is inert rather than refusing every leg.

Verification (all executed):

| check | result |
|---|---|
| `npx vitest run` | **1,029 passed / 97 files** (11 new in `tests/longshot-concurrency-cap.test.ts`) |
| `npx tsc --noEmit` | clean except the pre-existing `scripts/apply-v73-c200-cheap-band-clip.ts` error (another session's file, untouched) |
| live loader probe (`getActiveRules` → field → helper) | v73 reads **20**; at-cap allowed, +1¢ blocked, per-lane caps $1,514.19 / $4,116.05; a ruleset lacking the field reads 0 and blocks nothing |
| DB | v73 active, v72 inactive; `RuleChange` row is **one field**, before `{0}` → after `{20}`; v73's JSON is identical to v72's apart from that key |
| first live scoring cycle after arming (10:11:44) | printed, with no error in the run: `[LONGSHOT-CONCURRENCY] BANKROLL_200 open long-shot $350.00 = 4.62% of realised NW $7570.95 \| rail 20%` and `[LONGSHOT-CONCURRENCY] STANDARD open long-shot $2496.32 = 12.13% of realised NW $20580.25 \| rail 20%` — the armed value is being read in production, not merely stored |

Nothing else moved: the $100 Kelly clip, every band/entry/exit rule, the v55/v58 rails, the
drawdown gate and every booking/PnL path are untouched.

## 8. Headroom at activation (nothing was blocked by arming)

| lane | open long-shot | share of realised NW | cap | headroom |
|---|---|---|---|---|
| BANKROLL_200 | $350.00 | 4.62% | $1,514.19 | $1,164.19 |
| STANDARD | $2,496.32 | 12.13% | $4,116.05 | $1,619.73 |

C-200 is currently **halted by its own drawdown gate** (realised basis: NW $7,571 vs peak $11,069 =
31.6% > 20%), so the new rail cannot bind there until that clears; STANDARD is the lane with
headroom to watch.

## 9. The forward read, and what would refute this

- **Pre-registered retirement:** unless it has bound, retire by **2027-01-31**. An inert rail must
  not live forever.
- **Refutation:** if the next 60 days of C-200 long-shot concurrency stay under 20%, the 60.85% was
  a small-net-worth artefact of the September ladder and this closes with that null. Also refuted
  if any forward leg the rail blocks settles profitably at a better rate than the blocked
  population's record (33 legs, 20 net losses, −$849.76).
- **The number is printed every scoring cycle** — `[LONGSHOT-CONCURRENCY] <lane> open long-shot $X =
  Y% of realised NW $Z | rail 20%` — whether or not the rail binds, so an inert rail can be told
  apart from an unmeasured one.

## 10. Files

| file | role |
|---|---|
| `src/lib/exposure-cap.ts` | `longshotConcurrencyDecision()` — the pure predicate (boundary, per-lane, disable-on-unknown-NW) |
| `src/lib/rules.ts` | `maxConcurrentLongshotPctOfNetWorth` field + default 0 + the measurement that justifies the level |
| `scripts/score-trades.ts` | per-lane open long-shot book + realised NW, the admission gate, the booking-point increment, the shadow line |
| `scripts/apply-longshot-concurrency.ts` | writes/removes the value, dry-run by default, prints headroom and the row version |
| `tests/longshot-concurrency-cap.test.ts` | 11 tests: defaults, boundary, non-long-shot inertness, unknown-NW, per-lane, not-a-portfolio-gate |
| `scripts/kelly-single-loss-read.py` | the instrument (pre-existing, re-run today) |

**Revert everything:** `npx tsx scripts/apply-longshot-concurrency.ts --apply --revert` — one
field, no data migration, no booking change.
