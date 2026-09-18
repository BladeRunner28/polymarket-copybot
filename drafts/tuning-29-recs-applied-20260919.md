# Tuning #29 recs applied (2026-09-19) — dust floor · pre-loop halt · basis in the RuleSet

**Approver:** user ("approved") in the tuning-review thread · RuleSet v55 → **v56**.

---

## Rec 1 — dust floor on the drift counterfactual — APPLIED

A $0.0005 entry settling at 1.0 returns 2000×, so **two** such marks made the gate's headline read
$23.03/trade while the rest of the sample averaged $1.29 — roughly the bot's own +$0.94. The Oct 9
decision would have been made by two unexecutable rows.

`summarizeDrift` now reports `avgPnlPerTradeExDust` (excluding entries below `DRIFT_DUST_MIN_ENTRY`,
default $0.10, env-overridable) plus `dustExcluded` and the floor; the raw figure is kept for
continuity but must never be the headline.

**Verified:** `avgPnlPerTradeExDust = $1.17` (target ≤ $1.50) vs headline `$21.31`, **548 of 1,754**
settled rows excluded below the floor.

**Also fixed while verifying:** the feed reached **5,930 candidates / 4,176 awaiting** in 24h and the
hourly marker was spending its entire slot walking the backlog. `MARK_LIMIT` (default 300/run,
oldest-first) now drains it steadily, and the log line carries the backlog size.

## Rec 2 — pre-loop halt detection — APPLIED

Portfolio gates (drawdown, gross exposure) fire **before** the per-bot leg loop, so the Sep 16–18
halt produced no copies, no leg-block reasons and **no log signal** — 39.7h to detection.

`score-trades` now counts candidates vetoed by `isPortfolioGate()` and, when a cycle ends with
**0 copies and any portfolio veto**, logs:

```
[PRE-LOOP HALT] 0 copies this cycle — N candidate(s) vetoed by a PORTFOLIO gate
(drawdown/exposure) before any leg loop ran. Entries are HALTED, not quiet.
declared basis=realized, DD x.x%, gross $X vs cap $Y
```

plus **one Discord alert per 6h** while halted (`data/pre-loop-halt.json` throttles).

**Verified:** `grep -c "PRE-LOOP HALT"` → **0** right now (healthy — the lane thawed on 09-18 05:11).
Because I can't safely force a real freeze, the fragile part — classifying a veto reason as
portfolio-level — is a pure exported function pinned by `tests/pre-loop-halt.test.ts` against the
real gate strings, including the negatives (category cap, token breaker, per-market cap, slug cap,
hour blackout, wallet cap, drift).

## Rec 3 — basis recorded in the RuleSet (v56) — APPLIED

The 09-18 switch wrote only `data/c200-drawdown.json`, so "v56" was a narrative version: the DB
couldn't tell a reader — or the Oct 8 window audit — why the drawdown gate stopped firing.

`ddBasis` is now a first-class RuleSet field with precedence **RuleSet → state file → "mtm"**, and
`score-trades` writes the resolved value back to the state file so they cannot disagree. This needed
string-valued rule fields, which `applyRuleChanges` now supports alongside numbers and `string[]`.

**Verified exactly as specified:**
```
sqlite3 prisma/dev.db "SELECT version, json_extract(rulesJson,'$.ddBasis') FROM RuleSet ORDER BY version DESC LIMIT 1;"
→ 56|realized
```

---

## 🔴 Flagged: the v55 ceiling is vetoing Kelly-sized admits

Not one of the three recs, but it surfaced the moment the freeze thawed and it matters more than any
of them: **11 of 12 Kelly admits vetoed** ($200 notional vs a $125.12 cap).

Kelly sizes the long-shot band at up to `kellyMaxSizeUsd` $100, so **two** legs in one market
legally exceed 10% of the cap — the rule makes its own 2-leg allowance unusable wherever Kelly is
doing the sizing. Net effect: the ceiling binds hardest on the one lane the book's only |z|≥2
positive edge runs through.

**Recommendation: raise `maxMarketNotionalPctOfCap` 0.10 → 0.20** ($250 on the current $1,251 cap —
exactly `maxMarketLegsPerMarketId × kellyMaxSizeUsd`). It keeps the concentration intent (no market
ever takes more than a fifth of the book) while making the leg allowance coherent. One field, your
call — I haven't touched it. (Alternatives: exempt the <0.20 band from the ceiling, or accept that
Kelly can only ever hold one leg per market.)

## Files

`src/lib/shadow-drift.ts` · `scripts/mark-shadow-longshot.ts` · `src/lib/exposure-cap.ts`
(`isPortfolioGate`) · `scripts/score-trades.ts` · `src/lib/rules.ts` (string rule fields) ·
`scripts/apply-v56.ts` · `tests/pre-loop-halt.test.ts`. tsc clean · **180/180** tests.
