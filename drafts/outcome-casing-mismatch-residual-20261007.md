# outcome-casing-mismatch — where the bug actually still lives (2026-10-07)

Card: `FIX — outcome review compares two different casings (roadmap: outcome-casing-mismatch)`
Branch: `wt/outcome-casing-fix` · worktree `.worktrees/t_45a4a56f` · files left for review, not merged.

## TL;DR

1. The comparison the roadmap card names — `OutcomeReview` scoring in the review/benchmark
   path — **is already fixed** (shipped 2026-09-13, commits `9831a5e` + `d87ba1f`) and is
   correct on today's data: **0 historical reviews need rewriting**.
2. The *same* comparison survived, unfixed, in the **hold-to-settlement arm of the
   band-exit counterfactual** (`scripts/analyze-band-exit-exemption.ts`). That one is a real
   live bug: **106 of the 107 market-settlement-priced rows** across the six shipped
   `data/band-exit-exemption*.json` files were valued `0` (a phantom loss).
3. Fixed, failing-test-first. `npx vitest run` 383/383, `tsc` clean.

## Part 1 — the `OutcomeReview` compare is already normalised

Every consumer of the review label goes through `normalizeOutcomeLabel` / `didOutcomeWin`:

| reader | line |
| --- | --- |
| `src/lib/benchmarks.ts` (published Blind-copy / Skipped table) | `63` |
| `src/app/analytics/page.tsx` (cumulative benchmark curves) | `223` |
| `scripts/verify-dashboard-parity.ts` | `52`, `110`, `142` |
| `scripts/review-outcomes.ts` (the writer) | `138` |

Reproduced against `prisma/dev.db` (read-only). Today's table, not the 688 of 2026-09-13:

```
-- OutcomeReview r JOIN DecisionJournal d JOIN ObservedTrade t, finalOutcome not null
rows = 6613
raw      r.finalOutcome  =  t.outcome                ->   123 matches  (the bug signature: 1.9%)
norm     alnum-upper(r.finalOutcome) = alnum-upper(t.outcome) -> 3681 matches
biggest pairs: 'No'->'NO' (2317)  'Yes'->'YES' (204)  'Over'->'OVER' (145) 'Vitality'->'VITALITY' (76)
```

Are the **stored** judgements consistent with the normalised compare? (i.e. does anything
still need a backfill?)

```
watchlist/skip rows: contradiction (normalised says WON, stored wasDecisionGood=1 'avoided loser')
  2026-09  skip        n=200  won=92   good=108  contradictions=0
  2026-09  watchlist   n=544  won=366  good=178  contradictions=0
  2026-10  watchlist   n=665  won=380  good=280  contradictions=0
paper_copy rows: stored good == (simulatedPnl > 0)   5204/5204 consistent
```

**0 rows affected → nothing to backfill, and no history was rewritten.** The 2026-09-13
backfill did its job.

## Part 2 — the surviving instance (this card's fix)

`scripts/analyze-band-exit-exemption.ts` values every cut ticket at settlement with

```ts
if (m.resolved && m.winningOutcome) v = m.winningOutcome === t.outcome ? 1 : 0;   // line 147
if (ev)                             v = ev === t.outcome ? 1 : 0;                 // line 154
```

`winningOutcome` is the venue's own token label (`"No"`, `"Under"`, `"Team Liquid"` —
`src/lib/adapters/polymarket.ts:551`, `dead-market-resolution.ts:94`), while
`PaperTrade.outcome` is uppercased at ingest (`"NO"`, `"UNDER"`,
`adapters/polymarket.ts:201`). A raw `===` can therefore never match a label-cased market:
it stamps every settled one as a loss. `undefined` (the correct "cannot determine") was also
unreachable — the `if (…) v = … ? 1 : 0` always produced a number.

Evidence from the shipped outputs (rows priced by `market-settlement` vs by `own-resolution`,
which is derived from the realised PnL sign and so was never affected):

```
file                                   market-settlement values     own-resolution values
band-exit-exemption-0.2-0.4.json        9 rows  -> {0: 9}           14 -> {1: 6, 0: 8}
band-exit-exemption-20260913-0-0.2.json 1 row   -> {0: 1}           11 -> {1: 3, 0: 8}
band-exit-exemption-20260913-0.2-0.4   9 rows  -> {0: 9}           14 -> {1: 6, 0: 8}
band-exit-exemption-20260913-0.4-0.6  41 rows  -> {0: 41}          98 -> {1: 56, 0: 42}
band-exit-exemption-alltime-0.2-0.4   42 rows  -> {0: 41, 1: 1}    45 -> {1: 22, 0: 23}
band-exit-exemption.json               5 rows  -> {0: 5}           10 -> {1: 3, 0: 7}
                                      --------- 106 / 107 zero
```

The single `1` is a row whose token label is already all-caps (`HULIGANI`) — the only case a
raw compare can pass.

**Live re-check with the fix** (`verify-band-settlement-fix.ts`: re-resolves each
market-settlement row of the all-time 0.20–0.40 arm through the adapter, network, read-only):

```
market-settlement rows re-checked: 42   changed 0->1 = 10   unchanged = 32   no-label-now = 0

stored=NO   venue=No   [gamma] pre-fix=0  fixed=1
stored=YES  venue=No   [gamma] pre-fix=0  fixed=0     <- a genuine loss
stored=KANSAS ... (mixed-case team labels)             pre-fix=0  fixed=1
```

So the arm's settlement picture is `11/42 won`, not `1/42 won`.

## The change

* `src/lib/resolution.ts` — new `settlementValue(tradeOutcome, input): 0 | 1 | undefined`,
  implemented on top of `didOutcomeWin` (null → `undefined`, i.e. leave the ticket unpriced —
  never book a phantom 0).
* `scripts/analyze-band-exit-exemption.ts` — both call sites (Gamma and event fallback) use
  it; `m.winningLabel ?? m.winningOutcome` is preferred, matching every other call site.
* `tests/settlement-value.test.ts` — 4 tests pinning the normalised compare, the genuine-loss
  case, the undeterminable case, and the binary YES-price fallback.

Failing-first evidence (same test file, the extracted call-site body before the fix):

```
× matches a mixed-case venue label against the uppercased stored outcome (win = 1)
    → expected +0 to be 1
× returns undefined — never a phantom 0 — when the labels cannot be compared
    → expected +0 to be undefined
× still uses the YES-price fallback for binary trades
    → expected undefined to be 1
Tests  3 failed | 1 passed (4)
```

After the fix: `tests/settlement-value.test.ts (4 tests)` pass, `npx vitest run` 383/383
(was 379), `npx tsc -p tsconfig.json --noEmit` exit 0.

## Not done — needs a decision

The six `data/band-exit-exemption*.json` files still hold the pre-fix values. Regenerating
them **changes a published number** on the roadmap card `exit-exemption-20-40-decision`
("settle −$333.83 (n=41)" for the 0.20–0.40 all-time arm — most of that is the bug), so it
was left alone rather than silently rewritten. Regenerate with:

```
DATABASE_URL="file:./dev.db?immutable=1" npx tsx scripts/analyze-band-exit-exemption.ts --band-min 0.20 --band-max 0.40
```

No rule, sizing, threshold or schedule change; no DB write; no other worktree touched.
