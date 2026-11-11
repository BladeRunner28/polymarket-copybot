# One counterfactual-ledger primitive (four bespoke shadows → one write path, one read)

**Card:** `phil-counterfactual-ledger-primitive` · lane B (instrument repair) · approved 2026-11-11T18:36:42Z
**Branch:** `wt/phil-counterfactual-ledger-primitive-2`
**Gate:** `npx tsx scripts/reconcile-counterfactual-ledger.ts` — **PASS, 4/4 lanes, 0 field mismatches on 128 golden fields**

---

## Why

Every declined-decision shadow was built as its own writer plus its own summary math:
late-drift gate, minConfidence bar, per-wallet ceiling, long-shot ladder. The cost is not
hypothetical — when tuning #29 rec 1 added a dust floor to the drift feed on 2026-09-19,
the minConfidence feed (same dust-dominated population, same defect) did not get one for
six weeks, and when it finally did on 2026-10-31 the arithmetic had to be written a second
time, lane-locally. Same bug class; the fix lived inside one lane's private summary.

## What now exists

`src/lib/counterfactual-ledger.ts` — the single implementation:

| Concern | One place |
|---|---|
| Append-only write path (candidate + resolve rows, canonical schema) | `appendCounterfactualCandidate` / `appendCounterfactualResolve` |
| Fill rule: a declined ticket priced at its entry, paying `stake·(settled−entry)/entry` | `counterfactualPnl` (one copy; a ≤0 entry returns 0, never a 2000× windfall) |
| Row-level read: wins, PnL, trailing cohort, per-signal basis | `summarizeLedger` |
| Dust floor at all three levels + concentration + banned-tail cut | `settledDustRead` |
| Dedupe key and tie-break: `marketId\|outcome\|wallet`, earliest poll | `dedupeSignals` / `dedupeBy` |
| Pre-registered read adapter (phil trial A), so an era-less feed is UNVERIFIABLE | `toShadowReadRows` |

Each lane is now a **view**: it passes its own stake/fill model and floor, then picks field
names. `summarizeDrift`, `summarizeLowConf`, `summarizeWalletCap` and `summarizeShadow`
contain no fill rule, no dedupe rule and no dust arithmetic of their own.

Nothing here is imported by a decision path. No gate, rule, size or threshold reads it,
and no lane's headline number moves — that is what the diff below proves.

## The gate: table-vs-ledger diff on one frozen window

`data/counterfactual-ledger-golden.json` was captured on **pre-port** code (the four lane
modules as they stood on main) over the live feeds frozen at `2026-11-11T18:40:07.964Z`.
The golden stores the candidate window **and the resolve set as it stood at capture**, so
the marker appending new settlements cannot move the comparison — verified by appending a
resolve row and re-running: digest unchanged, still PASS.
`scripts/reconcile-counterfactual-ledger.ts` then re-derives the candidate window from the
same files (SHA-256 digest must match, else it reports `window_moved` instead of pretending)
and compares every published field:

| Lane | Candidates in window (+ resolves replayed) | Fields compared | Mismatches |
|---|---|---|---|
| `late_drift_gate` | 45,421 (+8,803) | 23 | 0 |
| `min_confidence_gate` | 34,803 (+5,318) | **84** (incl. the whole `dust` block) | 0 |
| `per_wallet_cap` | **0** (+0) | 10 | 0 |
| `longshot_shadow_ladder` | 9,256 (+47) | 11 | 0 |

Two independent cross-checks ran as well:

* `scripts/lowconf-dust-read.ts` rebuilds the market-level ledger by hand and **exits 1 on
  any divergence** from `summarizeLowConf`. It passes on the live file: 4,899 settled
  markets, dust-inclusive $277,302.82 → ex-dust $5,663.41, ex-top-10 $4,772.93.
* `npx vitest run` (full suite) and `npx tsc --noEmit` are clean; `tests/counterfactual-ledger.test.ts`
  now pins the shared dust read (earliest-settled-poll semantics, all three levels,
  the top-N cut) and the cross-lane equality that the card is about.

Reproduce: `npm run shadow:reconcile` (writes `data/counterfactual-reconcile.json`).
Re-taking the golden is `npm run shadow:golden -- --cutoff <iso>`, which must be run on a
tree that still has the pre-port lane modules (a ported tree would compare against itself).

## Honest caveats

1. **The per-wallet-cap lane is empty.** `data/wallet-cap-shadow.jsonl` does not exist and
   has never been committed: the ceiling has blocked nothing since the shadow was added on
   2026-09-19. Its 10/10 "match" is therefore vacuous — the port is proven on three
   populated lanes. Filed as a follow-up card (a counterfactual writer that has never
   written is exactly the silent-instrument class).
2. The `era` field is now written by the primitive, but **historical rows carry no era**, so
   the pre-registered read still reports `UNVERIFIABLE` for every lane. That is the read
   working as designed, not a regression — it becomes verifiable as post-port rows settle.
3. The golden window is a snapshot of live feeds; the reconcile re-derives a digest and
   refuses to compare if the window content moved.

## Rollback

Pure refactor on one branch: `git revert <merge>` restores the four lane-local
implementations. No schema migration, no data rewrite — the row shape keeps every legacy
field (`currentPrice`, `sizeUsd`, `band`, `confidenceOnly`, …), and readers tolerate both
shapes, which is what let the diff read the same files on both sides.
