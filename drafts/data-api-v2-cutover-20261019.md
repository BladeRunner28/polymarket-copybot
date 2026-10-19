# Data API v1 → v2 — CUT OVER 2026-10-19

**`DATA_API_VERSION` now defaults to `v2`. Rollback is one env var: `DATA_API_VERSION=v1`.**
Applied on your `go data-api-v2`. v1 retires **2026-10-24** (5 days).

Scope as finally measured: **5 routes / 7 call sites** — `adapters/polymarket.ts` ×6
(leaderboard, closed-positions ×2, positions ×2, activity) and `c200-printthrough.py:150`
(`/trades`, the route yesterday's brief was missing, and the one that feeds a *published* number).

---

## What was built

1. **`row.offset`-only → cursor walks.** v2 rejects `offset` outright. Every walker now follows
   `pagination.next_cursor` and terminates on `null`.
2. **A shape-translation layer, not 40 rewritten call sites.** `V2_TO_V1_ALIASES` copies each
   snake_case field onto its v1 name, so every downstream reader is untouched and `raw` still
   carries the venue's own shape.
3. **Envelope handling.** v2 wraps lists in `{data, pagination}`; `data: null` is a documented
   *miss*, not an error, and must not be retried as one.
4. **Sort enums.** `CURRENT`→`CURRENT_VALUE`, `REALIZEDPNL`→`REALIZED_PNL`.

## Where the migration nearly went wrong (all caught by the gate, not by luck)

**`entry_cost_usdc`, not `initial_value`.** The open-positions reader requires `initialValue`. v2
has **no `initial_value`** field at all, so every v2 open row was silently skipped for lack of a
price basis: the dual-read showed **200 v1 rows vs 100 v2 rows** on every active wallet. The
equivalent is `entry_cost_usdc` (verified equal on 3/3 live rows: 322814.2853 / 12347.4084 /
140048.5646). It is **not** `totalBought × avgPrice` — that product misses the fees (12320.00 vs
12347.41 on one row) — so it must be mapped, never recomputed. **Without this the bot would have
gone live blind to every open position.**

**A null test that looked clean.** The first depth-walk check returned `0/0` on both versions.
`measureDepth` only walks when the scoring sample is *at its ceiling* (100), so passing `0`
returned without issuing a single request. Fixed to pass 100/100 — the check now proves cursor
completeness (300/300 closed, 600/600 open, 12/12 requests on a censored wallet) instead of
proving nothing.

## Dual-read result — `scripts/data-api-v2-dual-read.ts`

| surface | result |
|---|---|
| **leaderboard** (60) | wallet sets identical (0 only-v1, 0 only-v2), **PnL sums identical to the cent** (50,813,081.96898 both), rank mismatches **0** |
| **wallet profiling** (8 wallets) | deduped position counts match on 7/8; realized-PnL sums match on 7/8 (one wallet +$3.37 on $440,858 = **0.0008 %**) |
| **cursor completeness** | exact: 19/19, 300/300 + 600/600 censored, 202/202 closed |
| **print tape `/trades`** (24 conditions, 1,500 rows each) | **18/24 exact key-set parity**; every divergence is v2-only |

## Three accepted deviations (measured, not assumed)

1. **v2 strips punctuation from outcome names.** v1 `"Anyone's Legend"` → v2 `"Anyones Legend"`.
   **This is the one real hazard:** any historical join keyed on outcome *text*
   (`DecisionJournal`, `ObservedTrade`, `PaperTrade`, the ML decision book) breaks across the
   cutover. Live decisions are unaffected because a cycle reads one version consistently; only
   cross-version joins and dedupe keys are at risk.
2. **Dust residues become extra OPEN rows.** v2 keeps a sub-0.2-share remainder open after a
   position closes (measured 0.0893 and 0.1108 shares), where v1 folds it in. Some positions are
   therefore returned **twice** (closed record + dust open). Economically nil — `initialValue`
   ≈ $0.09 — but it shifts row counts (21 on one wallet).
3. **~1 % of profiling rows aggregate to a 4th-decimal difference** in `avg_price`/`realized_pnl`
   (e.g. 0.3231 vs 0.3227). Repeated reads are **bit-stable within a version**, so this is a
   venue-side aggregation difference, not churn and not our bug.

## The print tape got BETTER

At depth (5,000 rows per condition) the comparison is one-sided: **0 fills appear only in v1, 7
appear only in v2**. v1's offset paging was dropping fills; the cursor walk does not. Since a
missing fill makes a maker fill-rate look *worse* than it is, this cuts in favour of the
print-through instrument's published number.

## Verification actually run

- `tsc -p tsconfig.json --noEmit` — clean.
- `npm test` — **484/484 passing** with v2 as the default.
- Live smoke with no env var set: `leaderboard 10 wallets, activity 22 rows, depth 19 closed / 3 open`
  → `SMOKE PASS` (`scripts/smoke-data-api-v2.ts`).
- Artefacts: `data/data-api-v2-dual-read.json`, `data/data-api-v2-trades-parity.json`.

## Rollback and the one open item

`DATA_API_VERSION=v1` restores v1 in one env var with no deploy. Keep it until 10-24, then delete
the switch.

**Open, carded (`data-api-v2-outcome-normalisation`):** decide whether to normalise outcome
strings (strip punctuation on both sides) so pre- and post-cutover rows join. That changes values
the live path writes, so it needs its own approval — it is not part of this cutover.
