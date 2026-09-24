# Tuning #35 Rec 1 applied — the copybot DB now runs in WAL mode

**Card** `tr35-rec1-db-contention-wal` (tuning review #35 rec 1, user-approved 2026-09-24) · **status**
APPLIED + VERIFIED 2026-09-24; telemetry gate opens 09-25 · **date** 2026-09-24

## Why

Review #35's red headline: a **~40-minute shared-DB outage (00:47–03:38)** that killed **6 monitor sweeps**
(4 consecutive), produced a hard `score:trades FAILED`, crashed scan-wallets at `getActiveRules`, and left
update-pnl at `PARTIAL 1/1437 covered (0%)`. Four different call sites dying in the same window = contention,
not one job: `journal_mode` was **`delete`** on a **7.59 GB** file held open by **two long-lived readers**
(`next-server` :3013 + a `tsx` process).

## The mechanism, measured (not asserted)

`journal_mode=delete` blocks writers while a reader holds a read transaction; WAL does not. Fixture test, same
code shape, two modes — a reader holds a read transaction for 6 s while a writer tries `BEGIN IMMEDIATE` + DML
with the app's 5 s busy timeout:

- `journal_mode=delete`: writer waited **6.05 s** — i.e. **past the 5 s timeout, which is exactly the failure
  signature** ("Operations timed out after `N/A`").
- `journal_mode=wal`: writer committed in **0.00 s**.

**Prod proof on the live 7.59 GB DB:** a read-only connection held a read transaction (12,124 `PaperTrade` rows)
while a real Prisma transaction took the write lock and rolled back intentionally — **6 ms**, non-blocking.
Under `delete` that same shape waits out the timeout.

## What changed

1. **`prisma/dev.db` → `journal_mode=wal`** (persistent, stored in the DB header — every connection picks it up,
   including the ones already open; no data rewrite, the main file is untouched in size).
2. **`busy_timeout` — already satisfied, measured rather than assumed.** `scripts/probe-sqlite-pragmas.ts` reads
   the pragmas through the app's own Prisma connection: `busy_timeout = 5000` **before** any change (Prisma's
   default), so no URL change was made. The rec's clause is met; the probe is the evidence.
3. **`~/.hermes/scripts/copybot-git-backup.sh` (22:30 daily)** now runs `PRAGMA wal_checkpoint(TRUNCATE)` and
   logs `journal_mode` *before* the backup loop, so the WAL is folded back into the main file nightly, the
   `-wal` is truncated to zero, and the overnight snapshot is one consistent file. Non-fatal by design (prints
   `busy|log|checkpointed`; `busy>0` just means a reader pinned pages and the next checkpoint clears them).
4. **`scripts/verify-market-category.py`: dropped `immutable=1`.** `immutable=1` tells SQLite the file can never
   change, so it **skips the WAL entirely** and would read a stale pre-checkpoint snapshot — a silent
   wrong-answer path opened by the mode switch. It now opens `mode=ro`. (Grep confirms it was the only
   `immutable=1` user; the other 15 read-only instruments already use `mode=ro`, which reads WAL content fine.)

## Verification (all run today, after the switch)

- `PRAGMA journal_mode` → **`wal`** at the file level (CLI) **and** through the app connection (probe).
- **First live cycle after the switch (08:37:45)**: monitor ran end to end — **1 paper copy**, scoring complete,
  `rollup-pnl incremental` wrote 6 hour-rows, **0 errors, 0 timeout lines**.
- `-wal` is live (**4.16 MB** at 08:37) → writes are going through WAL as designed; `-shm` 32 KB.
- A read-only `mode=ro` reader sees the **newest row written at 08:37:41** → readers include WAL content, so no
  instrument goes blind or stale.
- `PRAGMA wal_checkpoint(TRUNCATE)` → **`0|0|0`** (busy 0, log 0); the backup script's snippet verified
  standalone and `bash -n` clean.
- Dashboard :3013 → HTTP 200 serving live data; `tsc` clean; **250/250 tests pass**.
- Baseline for the record: `journal_mode = delete`, `busy_timeout = 5000`, `foreign_keys = 1`, 1,852,762 pages ×
  4096 B = 7.59 GB.

## Gate handed to review #36

- `journal_mode` stays `wal` (persistent — only an explicit `PRAGMA journal_mode=delete` or a new file reverts it).
- **0** timeout/FAILED lines in the monitor/scan/update-pnl logs after **2026-09-25**.
- update-pnl coverage back to **≥150** with no `PARTIAL` line.
- The 22:30 backup prints `sqlite: journal_mode=wal wal_checkpoint(TRUNCATE)=…`.

## Caveats / what this does NOT fix

- The DB is now **three files** (`dev.db`, `dev.db-wal`, `dev.db-shm`). Any DB copy or cold backup must take
  the WAL too, or run a checkpoint first — the 22:30 job now does the latter. WAL is also **not** safe on a
  network filesystem; this is local disk (the storage fabric has no mount here).
- WAL removes **lock** contention, not **I/O volume**. The observation lane is now writing ~40,000 rows/24 h
  (2× the old bar) — that volume clause is Rec 2's subject, and if contention returns it will point at volume,
  not at the journal mode. The 5 s Prisma query timeout still applies to genuinely long transactions.
