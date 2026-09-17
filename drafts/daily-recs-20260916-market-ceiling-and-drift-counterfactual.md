# Daily-report recs applied (2026-09-16): v55 per-market ceiling · drift-gate counterfactual

**Approver:** user ("i approve of these recommendations") in the C-200 daily-report thread
**Source:** C-200 daily report 2026-09-16, Change 1 + Change 2.

---

## Change 1 — per-market concentration ceiling — **APPLIED** (RuleSet v54 → **v55**)

| field | value |
|---|---|
| `maxMarketLegsPerMarketId` | **2** |
| `maxMarketNotionalPctOfCap` | **0.10** (= $135.54 at today's $1,355 cap) |
| revert | both fields → 0 (defaults in `DEFAULT_RULES` = legacy semantics) |

**Why the slug cap wasn't enough:** `maxMarketSlugPositions` counts the research **category** — a
slug wraps many markets — so nothing bounded legs inside one `marketId`. With v54's 2.5× long-shot
factor the band's average clip is ~$33 (vs $2.48 in the dead zone), so a single binary can absorb
$250+.

**The replay the report asked for** (`scripts/replay-market-cap.ts --days 7`, run *before* applying):

```
298 legs booked in the window; the ceiling would have blocked 13 legs across 7 markets
blocked notional $283.12 | blocked PnL −$144.01
actual window PnL −$441.53 -> counterfactual −$297.52 (delta +$144.01)
  worst blocked legs (all leg-3+ accumulations):
    will-the-fed-increase-interest-rates-by-25-bps  $50.30 -> −$50.04  (closed)
    elon-musk-of-tweets-september-14-…             $22.22 -> −$22.22  (resolved)
    elon-musk-of-tweets-september-10-…             $19.95 -> −$19.95  (resolved)
    will-dtf-stpt-louis-win-emmys-2026-…           $19.95 -> −$18.32  (closed)
    will-the-fed-increase-interest-rates-by-25-bps $65.40 -> −$10.46  (closed)
```

That is the streak-killer the report identified — the Fed market was −$92.18 of a −$218.19
two-market week — being chopped at the leg level.

**Scope/design notes:** C-200 only; enforced **per leg on the final size** (after Kelly/band sizing)
so a late resize can't slip past it; expressed as a **pct of the cap** rather than a fixed $135 so it
scales with equity instead of silently loosening as the book recovers. Predicate extracted to
`marketCapDecision()` with **6 tests** (`tests/market-cap.test.ts`) — one of my first-cut assertions
was self-contradictory and the test caught it.

## Change 2 — late-drift gate counterfactual — **INSTRUMENTED, behaviour unchanged**

The `price drifted X > max 0.004 (too late)` gate is the book's largest volume blocker (~2,000
skips/24h, 905 of a day's skips at copyScore ≥ 80) and had **never been measured**. Now write-only:

- every blocked would-have entry goes to `data/drift-shadow.jsonl` with its would-have price, drift,
  score/confidence, TTR, spread and liquidity;
- the existing hourly shadow marker now marks that feed to settlement and publishes
  `data/drift-shadow-summary.json`.

**Verified live:** first scorer run logged **44 drift-gate counterfactuals** (summary line now reads
`… 44 drift-gate counterfactuals logged`); the marker run reports
`shadow-drift: 44 would-have entries, 0 settled`.

**Decision gate:** `maxPriceDrift` must **not** move before Oct 9 — the Oct 8 Kelly-window read is
benchmarked against the pre-Kelly baseline measured *at* drift 0.004, so moving the gate now would
contaminate the comparison. Read the summary at the close.

## Flagged item — duplicate-open dry run (read-only, nothing written)

`dedupe-open-copies.ts --report`: **225 duplicate OPEN keys = 1 post-guard leak + 224 legacy
pre-v52 accumulations**. The legacy set is STANDARD-heavy (×63 Barcelona, ×58 Bolsonaro, ×39
ETH-1500); the script deliberately leaves it alone (closing them is portfolio surgery). The 1 leak is
actionable via `--clean-leaks` — **write needs your approval**. The partial unique index still can't
be created while any duplicate open key exists.

## Not actioned (correctly)

Restoring the 0.20–0.40 dead-zone factor: the band's edge is positive (excess +0.0664, z=+2.41) but
the post-v53 sample (26 closes, $274.69 staked, −$84.37) doesn't yet confirm the churn fix — re-test
at ≥75 closes. Also held: any positive-hour uplift (06:00/22:00 are thin-N), and phase advancement
(0/7).

## Files

`src/lib/rules.ts`, `src/lib/exposure-cap.ts` (`marketCapDecision`), `scripts/score-trades.ts`,
`scripts/apply-v55.ts`, `scripts/replay-market-cap.ts`, `src/lib/shadow-drift.ts`,
`scripts/mark-shadow-longshot.ts`, `tests/market-cap.test.ts`. tsc clean · 177/177 tests.
