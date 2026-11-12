# STANDARD fill chain — the booth now has a writer

**Card:** `t_1b33d26a` (Lane B, instrument repair) · **date:** 2026-11-12 · **scope:** the artifact writer only.
No rule, size, gate, RuleSet or published figure changed. No DB write, no schema change, no `bookedPnl`
change, no `fillStatus`/`fillEntryPrice` stamp — that is the Lane A half and it still waits for you.

---

## What was broken

`scripts/standard-fill-stamp.ts` (the STANDARD fill booth) had **no scheduled writer**. `data/standard-fill-stamp.jsonl`
held exactly one snapshot — `2026-10-29T17:14:29Z`, 880 legs, 251 of them stamped — for 14 days. Meanwhile
130 STANDARD legs opened on/after 10-29 and **0 of them carried a stamp anywhere**. The evidence was never
missing: one manual `--book-only` pass stamped 122 of 124 legs in 26 s off the retained L2 corpus.

This is the `c6222f7` lesson one layer down — *an artifact with no writer is a card that lies.* The C-200 lane
already had its chain (`copybot-c200-fill-chain.sh`, every 2 h); STANDARD did not.

## What shipped

| piece | path |
|---|---|
| the chain (2 stages + watchdog + state) | `scripts/cron-scripts/copybot-standard-fill-chain.sh` |
| deployed entry point (cron resolves under `~/.hermes/scripts/`) | `~/.hermes/scripts/copybot-standard-fill-chain.sh` (exec shim → repo copy) |
| union merge, hardened (atomic write, evidence never erased by absence, machine line) | `scripts/standard-fill-stamp-merge.py` |
| cron job | `3e760d8c8a01` — `copybot-standard-fill-chain`, every 120 m, `no_agent=true`, `deliver: local`, `failure_deliver: origin`, enabled |

Each tick: `npx tsx scripts/standard-fill-stamp.ts --book-only --since-ms <last run − 2 min> --out
data/standard-fill-stamp-<UTC day>.jsonl` (offline, ~33 s, no tape fetches) → merge into
`data/standard-fill-stamp.jsonl` → one line of output, or silence. It writes **only**
`data/standard-fill-stamp*.jsonl` and `logs/standard-fill-chain-state.json`.

Three deliberate choices worth knowing:

1. **The union, not the last run, is the artifact.** Each tick only re-stamps its own `--since` window, so
   `data/standard-fill-stamp.jsonl` is the union of every snapshot (1004 legs after the first tick). The merge
   keeps the newest snapshot's aggregate blocks but labels them `aggregatesCover` so the file cannot be misread
   as aggregates over the whole union.
2. **Evidence beats absence.** A leg the new run could *not* stamp never overwrites a leg the old snapshot
   *did* stamp (`keptOldEvidence`). The naive newer-wins rule would silently shrink coverage whenever one tick
   misses the L2 window.
3. **The 10-29 snapshot is preserved** as `data/standard-fill-stamp-20261029.jsonl` before the first merge — it
   was measured on the **pre-repair** price basis (`d974287` later rewrote 183 STANDARD entries), so it is the
   record the basis-split needs, not something to fold away.

The watchdog models `report()` in the C-200 chain: it speaks when a tick adds stamped legs, when a stage fails,
when the booth prints no `book arm: N/M legs stamped` line (**interface drift**, not a clean no-op), when the
merge prints no `MERGE …` line, and when a tick stamps 0 of a non-empty pending set (rate-limited to a change
in the pending count, else weekly). A healthy no-op tick prints nothing.

## Evidence (real scheduler fires, not hand-runs)

| check | reading |
|---|---|
| cron job | `3e760d8c8a01`, enabled, `every 120m`, two executions through the scheduler, `last_status ok` both |
| fire 1 (10:42 CDT) stdout | `standard fill-aware: stamped 122 new STANDARD leg(s) (124 new leg(s) in this snapshot, 128/130 in scope this tick (98%)) — union now 1004 legs` |
| fire 2 (10:43 CDT) stdout | *(empty)* — `Status: silent (empty output)`; union unchanged at 1004 legs, `mergeStats {}` |
| union artifact | `data/standard-fill-stamp.jsonl` · `ranAt 2026-11-12T16:43:24.926Z` · 1004 legs · 373 stamped · mergedFrom `{old: 2026-10-29T17:14:29.176Z, new: 2026-11-12T16:43:24.926Z}` |
| legs opened **after the previous snapshot's `ranAt`** | **124** of the 1004 (all opened 10-29 17:15Z → 11-11 17:15Z) |
| `python3 scripts/standard-fill-aware-basis-split.py --artifact data/standard-fill-stamp.jsonl` | `clean/as-booked 291 legs −4.42pp · taker60-clean −5.84 · forward-clean 62 −6.84` — **unchanged** |
| `SELECT COUNT(*) FROM PaperTrade WHERE botId='STANDARD' AND fillStatus IS NOT NULL` | **0** (BANKROLL_200 still 582; the chain did not start stamping booking columns) |

## The one clause that is NOT met, and why

**"A snapshot file exists whose legs include ones opened after 2026-11-12" — 0 such legs exist to stamp.**
Entries are halted, not quiet: the scorer's portfolio gate has vetoed every candidate before the leg loop since
**2026-11-11T18:43Z** (`[PRE-LOOP HALT] … Entries are HALTED, not quiet. declared basis=realized, DD 32.0% …
gross $427.64 vs cap $3815.97`), and the newest leg in the whole paper book is `2026-11-11T18:10:56Z`
(BANKROLL_200) / `2026-11-11T17:15:56Z` (STANDARD). A drawdown of 32 % against the $11,069 realized peak is
above the 20 % gate, so nothing new has opened for ~23 h. No writer can create that leg; the gate has to clear
first (or you have to decide the gate should not stand — that is a Lane A call, carded separately).

The chain is built for exactly that moment: the first post-halt leg falls inside the next tick's `--since`
window, gets merged, and produces the one-line notification. Confirm with:

```
cd ~/polymarket-copybot && sqlite3 -readonly prisma/dev.db \
 "SELECT MAX(openedAt), datetime(MAX(openedAt)/1000,'unixepoch') FROM PaperTrade WHERE botId='STANDARD';"
grep -oE '"ranAt": *"[^"]+"|"unionLegs": *[0-9]+' data/standard-fill-stamp.jsonl | head -2
tail -1 logs/standard-fill-chain-state.json
```

— `MAX(openedAt)` later than the union's `ranAt`, with that leg's id present in the union, is the clause met.

## Revert (one command + two deletes)

```
hermes cron remove 3e760d8c8a01
rm ~/.hermes/scripts/copybot-standard-fill-chain.sh
rm ~/polymarket-copybot/scripts/cron-scripts/copybot-standard-fill-chain.sh
rm ~/polymarket-copybot/logs/standard-fill-chain-state.json
# artifacts (keep or delete; nothing reads them unless you ask it to):
git -C ~/polymarket-copybot checkout -- data/standard-fill-stamp.jsonl
rm -f ~/polymarket-copybot/data/standard-fill-stamp-20261029.jsonl \
      ~/polymarket-copybot/data/standard-fill-stamp-20261112.jsonl
```

Reverting the chain changes nothing about the book: it never wrote a booking column, so there is no data to undo.

## What this unlocks

The STANDARD fill-aware booking decision (`drafts/standard-fill-aware-booking-20261112.md`) needed a live stamp
stream to be adoptable on *any* branch you pick. As of today that stream exists and advances every 2 h, so the
population clause (291/300 clean legs) accrues on its own instead of being frozen at one 10-29 snapshot — once
the entry halt clears, ~8.7 stamped legs/day is the rate the 10-29→11-11 window measured.
