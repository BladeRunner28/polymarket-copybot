# Tuning #34 — approvals executed (2026-09-23)

**Approved in-thread:** both recommendations from the Cycle #34 tuning review (2026-09-23 07:07 CDT).
**Shipped:** v62 — code-only, **no RuleSet change** (v60 remains the newest/active row). Copy set, thresholds, sizing, caps: untouched.

Live link: http://localhost:3013/drafts/tuning34-approval-execution-20260923

---

## Rec 1 — the OBSERVE sweep now rotates

**The problem it fixes (measured by the review).** The observation lane (v61) took the 40 *most recently demoted* wallets every cycle (`orderBy lastTrackedAt desc`). Against 199 eligible wallets whose demotion ages were `<4 h: 39 · 4–24 h: 117 · 1–3 d: 6 · 3–7 d: 13`, the 40th award went to a wallet demoted **~3.2–4.2 h earlier** — so the declared "trailing 7 d" window behaved as a **~4 h window**, and because a deferred wallet's `lastTrackedAt` is never refreshed, **the deferral was permanent**: 108 of 175 eligible wallets got **zero** observation rows in 24 h (68 distinct wallets observed in total). The four wallets #33 built the lane for went dark within 5 h of the 14:30 cutover and stayed silent 12–16 h while a live keyless probe showed them still trading.

**Chosen knob: (a) cost-neutral rotation** — not (b) `MAX_OBSERVE_WALLETS ≥ 175`, which buys coverage with ~4.4× per-cycle fetch volume (unmeasured 429 burst risk). Rotation keeps per-cycle fetch volume identical.

| What | Before (v61) | After (v62) |
|---|---|---|
| Ordering | `lastTrackedAt desc` | `lastObservedAt ASC, NULLs first, address ASC` |
| Rotation stamp | none | `WalletProfile.lastObservedAt` (nullable) |
| Effective window | ~4 h | whole eligible pool, ~5 cycles ≈ 55 min |
| Deferred wallet | starved forever | front of the next cycle |

**Files:** `prisma/schema.prisma` (+`lastObservedAt`, `prisma db push`, 28 ms, no data loss) · `src/lib/wallet-universe.ts` (`observeOnlyWallets` ordering, `observeEligibleCount`, `stampObserved`) · `scripts/monitor-trades.ts` (stamps only wallets whose `/activity` fetch succeeded → a failed fetch is retried next cycle, not after a full rotation; new `[OBSERVE-ROTATION]` line; `[OBSERVE-CAP]` reworded to "waits its turn") · `tests/observe-rotation.test.ts` (new).

**Verification done now**
- `npm test` → **225/225 pass** (4 new DB-backed cases: pool membership, NULL-first → oldest-first ordering, a stamped sweep pushes the newest demotions to the **back**, and the whole 45-wallet pool is covered in `ceil(45/40)` cycles).
- First live cycle (09:12:14 run): `[OBSERVE-ROTATION] swept 40/199 eligible (least-recently-observed first, stamped 40); full pool every ~5 cycles ≈ 55 min` — 40 rows stamped in `WalletProfile`.
- Second live cycle (09:23:14 run): `[OBSERVE-ROTATION] swept 40/198 eligible (stamped 40)` → **80 wallets stamped in two cycles, the two sweeps disjoint** (the next batch shares 0 wallets with the stamped set, so the cap is genuinely walking the pool, not re-taking it).
- Coverage moving already: distinct observation wallets/24 h **68 → 79**, observation rows **19,113/24 h** (still inside the 20,000 bar; the 24 h window still carries ~5.4 k of yesterday's one-off cutover catch-up, so both figures should settle rather than drift up — re-read after 2026-09-24).
- Both cycles: **0** `Too Many Requests`/429, **0** `FAILED`, **0** lockfile-skip.

**Verify 7 d (2026-09-30)** — distinct observation wallets/24 h **≥150** (baseline 68); observation volume **≤20,000/24 h** (baseline 16,834); at most **1** new 429 after the first post-v62 run header (2026-09-23T09:12:14).

```
sqlite3 -readonly prisma/dev.db "SELECT COUNT(DISTINCT walletAddress) FROM ObservedTrade WHERE observationOnly=1 AND createdAt > (strftime('%s','now')-86400)*1000;"
sqlite3 -readonly prisma/dev.db "SELECT COUNT(*) FROM ObservedTrade WHERE observationOnly=1 AND createdAt > (strftime('%s','now')-86400)*1000;"
```

## Rec 2 — the EOD wallet-status split declares itself an as-of-print snapshot

The line (from #33 rec 2) joins `WalletProfile.status` **live**, and the hourly cap re-derives that status — so its own verify clause ("equals a same-day re-run") was unachievable, and the reviewer could never close it. Measured across the first two reads: `track 207 −$432.55 | watch 1,745 +$2,817.90` at the 22:00 EOD vs `track 186 −$342.51 | watch 1,770 +$2,718.37` at 07:00 (21 legs / $90 reclassified). Clause retired; the EOD print is now the immovable record.

Printed now (read-only test run at 09:12):

```
C-200 realized by wallet status: track -$299.51 (187) | watch +$2716.51 (1771) | total +$2417.00 (1958)
  (as-of 09:12 print — WalletProfile.status is live, a later re-run of this SQL can differ)
```

**Files:** `scripts/wallet-status-split.ts` (marker + header note). Nothing written; still non-fatal.

**Verify 7 d (2026-09-30):** `grep "by wallet status" logs/cron/copybot-eod.log | tail -1` carries the marker, and `grep -c` ≥ 7 (one per EOD).

---

## Bookkeeping

- **Roadmap:** `tr34-rec1-observe-rotation` and `tr34-rec2-eod-asof-marker` created (`In Progress`, both with 7-day gates); `tr33-rec1-observation-copy-split` re-scoped to `In Progress` — its **volume** clause is met (17,136 rows/24 h post-cutover) but its **coverage** premise was refuted, and coverage now belongs to the #34 card.
- **Tuning-review standing inputs:** two bullets appended to the daily reviewer's prompt (rotation is applied — do not re-propose; coverage baseline 68 → target ≥150; the EOD split is an as-of snapshot — do not re-open the retired clause). `jobs.json` backed up first to `jobs.json.bak-tuning34-standing-inputs-20260923`.
- **Untouched:** copy set (top-25 `track`), every threshold, Kelly sizing, exposure caps, the Oct 8 Kelly read. Observation rows are never scored, journaled or copied (0 of 16,834 carry a decision row), so this cannot move the Oct 8 attribution.
