# Tuning #28 recs applied (2026-09-17) — watchlist labels · connector-fault retry

**Approver:** user ("I approve") in the tuning-review thread
**Source:** `logs/cron/tuning-review.md` Cycle #28, recs 1–2. RuleSet unchanged (v55).

---

## Rec 1 — price the gate's cost: the OutcomeReview sample now includes `watchlist`

`watchlist` decisions **never open a leg** — the risk gates fire before booking — so the
settled-leg selection can never see them. The drawdown gate alone blocked **459 decisions** in #28
and its cost was literally unpriced: **0 watchlist labels, ever** (baseline confirmed before the
change: 1,327 `paper_copy` + 200 `skip`, 0 `watchlist`). The judge already handles non-copy
decisions correctly (`good = the market went against the wallet`); it simply never had them in the
pool.

**Design:** a second candidate pool unioned with the settled-leg pool —
`decision='watchlist'`, `createdAt` between **2h and 30d** old, **oldest-first**, `take WATCH_TAKE`
(env, default 100).

- Oldest-first is **self-clearing**: an older market is likelier to have settled, and the frontier
  advances as they do.
- The **30-day floor** is what stops the July-era long-dated rows from rebuilding the head-of-line
  block that #26 rec 3 fixed — the same trap, one level up.

The run logs the pool size and how many it took, so selection health is visible.

## Rec 2 — connector faults no longer abort the hourly mark

Two `update-pnl` runs aborted (Sep 16 14:36, Sep 17 02:48) on
`Failed to convert JavaScript value 'Undefined' into rust type 'String'`, each within 8 minutes of a
monitor `ruleSet.findFirst()` timeout. `withDbRetry`'s transient regex didn't match it, so no retry
fired and the whole hourly mark died.

**Fix (two parts):**

1. **Regex** now covers `into rust type` / `Failed to convert JavaScript value` **and**
   `timed out` — connection-pool exhaustion was *also* unmatched, because
   `Timed out fetching a new connection` contains no substring `timeout`. Verified against sample
   strings: the fault signatures retry; `Insufficient capital` and `unmapped outcome label` still
   rethrow, so genuine logic errors are not masked into blind retries.
2. **Write guards** in `paper.ts` for all three writers (`updatePaperTradePrice`,
   `resolvePaperTrade`, `closePaperTrade`): an undefined id or a non-finite price now throws a
   message that **names the field**, which `update-pnl` records as a per-trade failure and steps
   over — one bad row can no longer kill the hourly mark.

---

## 🔴 The thing that outranks both recs: the gate has both lanes frozen

Cycle #28's real finding is operational. State at the time of writing (it moves — recompute):

| | value |
|---|---|
| realized NW | $2,414.32 → **realized DD 1.1%** |
| MTM NW | $2,548.01 (unrealized $133.69) → **MTM DD 25.3%**, gate fires >20% |
| peak | mtm $3,409.47 (set 09-12 on marks, since given back) / realized $2,441.69 |
| cap | $1,324.00 on mtm vs $1,257.16 on realized (open gross $471.45) |
| freeze | both lanes halted ~17 h, no opens since 13:30, **459 decisions blocked** |

Clearing on MTM needs ≈**$180** of mark recovery, obtainable only from PnL out of the frozen lane —
the Sep 7/8 deadlock, second occurrence. **The book is being halted at its best-ever realized
equity, by marks that were given back.**

`scripts/apply-v56-drawdown-basis.ts` is written and **not run** (no default action by design —
this is a sizing/live-lane change). Options:

- **`--basis realized`** — clears immediately (1.1%), costs only **−$66.84** of cap against a
  $471.45 book, and removes the deadlock *mechanism* instead of resetting it. **Recommended.**
- **`--basis min`** — behaves identically here (min peak $2,441.69 / min NW $2,414.32 = 1.1%).
- **`--reseed-peak`** — keeps MTM, clears now, but the freeze returns on the next mark spike.

## Files

`scripts/review-outcomes.ts` (watchlist pool) · `scripts/update-pnl.ts` (transient regex) ·
`src/lib/paper.ts` (write guards) · `scripts/apply-v56-drawdown-basis.ts` (awaiting a pick) ·
`data/roadmap.json` (3 cards). tsc clean.
