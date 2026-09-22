# Tuning review #33 — approval execution (2026-09-22)

**Approved:** the two enumerated recommendations of tuning review #33 (07:00 cycle): **rec 1** (split
observation from copy) and **rec 2** (print the tracked-vs-demoted C-200 split in the EOD). Both are
executed and measured below. Nothing else in that message was a recommendation — the v45 slug-cap
shadow instrument lives in the separate *c200-daily-report* message and is **not** covered by this
approval.

- Version label: **v61** (code change; **no RuleSet change** — no threshold, no sizing, no gate moved).
- Files: `src/lib/wallet-universe.ts` (new), `scripts/monitor-trades.ts`, `scripts/scan-wallets.ts`,
  `scripts/score-trades.ts`, `src/lib/insider.ts`, `scripts/record-l2.ts`,
  `scripts/backfill-last-tracked.ts` (new), `scripts/wallet-status-split.ts` (new), `prisma/schema.prisma`,
  `~/.hermes/scripts/copybot-eod.sh` (appended step).

---

## Rec 1 — split OBSERVATION from COPY (shipped, v61)

### Problem and root cause

The review measured the detected-trade funnel at **6,515 → 1,211 rows/24h** (distinct markets 1,627 →
489) and attributed 58% of the lost window to four wallets the hourly cap had rotated out.

Root cause, in code:

- `scripts/scan-wallets.ts` re-derives the `status` of every profiled wallet each hour and then caps the
  tracked set: `kept top 25, demoted N to watch`.
- `scripts/monitor-trades.ts` fetched **only** `status = 'track'`, top-25 by `globalScore`.
- A demoted wallet therefore stopped being observed entirely — not because it stopped trading. All four
  wallets named by the review are still active on-chain, and all four are in the restored observation set
  (below).

### Design — two universes, one source of truth

`src/lib/wallet-universe.ts` is now the only definition of both:

| universe | predicate | may book a copy? |
|---|---|---|
| **COPY** | `status='track'`, top `MAX_TRACKED` (25) by `globalScore` | yes — unchanged, still 25 |
| **OBSERVE** | `status≠'track'` **and** `lastTrackedAt` within the trailing 7d, most-recently-tracked first, cap 40 | no, never |

- New column `WalletProfile.lastTrackedAt`, stamped by `scan:wallets` on every scan that leaves a wallet
  at `status='track'`. After the cap demotes it, the wallet keeps the timestamp of its last tracked scan,
  so it stays observable for the window and then ages out on its own — the observation set is
  self-expiring, not a second permanent tier.
- Discovered trades from that set are stored as `ObservedTrade.observationOnly = 1`. They are **not
  scored, not journaled, never copied.**
- Cost control: an observation-only wallet gets one `/activity` page and **no** per-trade market read
  (that read + its `MarketSnapshot` write is what makes a cycle ~12 min long). Its rows carry the wallet's
  own fill price as `detectedPrice` instead of a detection-time market price, which is stated here because
  it is a second price convention in the table — and is exactly why the flash-move breaker filters these
  rows out.
- A busy observation wallet re-offers its whole 24h book every cycle, so the sweep pre-filters in memory
  against rows already stored (one indexed read per wallet) instead of re-attempting thousands of inserts
  that end in a unique-constraint rejection.

### Containment — every reader that feeds a decision or a published number

| reader | change |
|---|---|
| `score-trades.ts` unscored queue | `observationOnly: false` (the whole point) |
| `score-trades.ts` swarm count | filtered — swarm is a **copy** signal |
| `score-trades.ts` flash-move breaker | filtered — risk gate on real candidates |
| `score-trades.ts` new copy gate | a row whose wallet is no longer in the top-25 is journaled as a skip tagged `observation-only` (covers a demotion landing between the monitor sweep and the scoring run) |
| `src/lib/insider.ts` (per-wallet 60d + cross-wallet 24h cluster) | filtered |
| `scripts/record-l2.ts` (L2 watch list) | filtered — otherwise observation markets displace real candidates under `MAX_MARKETS` |
| measurement scripts (`analyze-score-separation`, `build-decision-dataset`, `shadow-expectancy-model`, `skip-edge-probe`, calibration) | no change needed — they JOIN `ObservedTrade` via `DecisionJournal`, and observation rows never get a journal row. Verified: **0 of 5,484** observation rows have a decision row. |

### Bootstrap

`scripts/backfill-last-tracked.ts` (read-only without `--apply`, idempotent — only NULL rows). The
pre-v61 proxy for "last held track" is `MAX(ObservedTrade.createdAt)`: the monitor only ever fetched
`status='track'` wallets over a 24h window, so that stamp is the last moment the wallet was demonstrably
in the copy set.

```
Applied: 25 tracked stamped now, 27 demoted stamped with their last stored fill.
Copy set: 25 | observation set: 27
```

The four wallets the review named as the ratio of the collapse are all inside it:
`0xcfff4295@09-21`, `0xc5187cb6@09-21`, `0xb0c85813@09-20`, `0xd06c49e1@09-20`.

### RESULTS (measured, 2026-09-22)

Trailing-24h window, same query both sides (by `createdAt`, i.e. detection time):

| metric | before 14:26 | after | rec's bar |
|---|---|---|---|
| detected rows / 24h | **968** | **6,455** | ≥ 4,000 (base 1,211) |
| — copy-eligible | 968 | 971 | — |
| — observation-only | — | **5,484** | — |
| distinct markets | 243 | 2,212 | — |
| distinct wallets | 16 | 33 | — |
| copies opened since 14:30 | — | **0** | paper_copy/24h ≤ 45 (base 25) |
| `DecisionJournal` rows since 14:30 | — | 12 (= the 6+6 copy-eligible rows scored) | — |
| observation rows journaled / scored | — | **0 / 5,484** | — |
| monitor cadence | 11.0 min | **11.0 min** (14:19:13 → 14:30:13 → 14:41:13) | no cadence cost |
| new 429s after the change | — | **0** | "429 lifetime still 38" |

Per-cycle detail:

```
=== run 2026-09-22T14:30:13 ===   Monitoring 25 copy-eligible tracked + 27 observation-only (demoted within 7d, copy cap 25) wallets…
                                  Trade monitor complete: 5438 new observed trades (6 copy-eligible, 5432 observation-only).
                                  Scoring 6 observed trades with rules v60…
=== run 2026-09-22T14:41:13 ===   Trade monitor complete: 58 new observed trades (6 copy-eligible, 52 observation-only).
```

The first cycle carries a one-off catch-up (the last 24h those wallets were never observed); the second
cycle is the steady state, **52 observation rows/cycle ≈ 5.4k/day** at the 11-minute cadence. The 24h
figure above therefore overstates the steady rate by exactly the catch-up burst and should be re-read
after 2026-09-23.

**Correction to the rec's third bar:** the count basis "monitor 429 lifetime = 38" is not reproducible —
`grep -cE "Too Many Requests|HTTP 429" logs/cron/copybot-monitor-score.log` returns **57** lifetime
occurrences. The metric that matters is unchanged either way: **0** of them fall after the first v61 run
header (line 62,687). The corrected form is the one to reuse: zero 429 lines *after* the run header where
the change landed.

---

## Rec 2 — EOD tracked-vs-demoted split (shipped)

`scripts/wallet-status-split.ts` — **read-only**, one greppable line plus the SQL that reproduces it, run
as the final (non-fatal) step of the EOD:

```
C-200 realized by wallet status: track -$434.17 (201) | watch +$2075.80 (1740) | total +$1641.63 (1941)
```

- Filter is the TR-15 OR form (`closedAt IS NOT NULL OR resolvedAt IS NOT NULL`) **and** it reconciles:
  the same 1,941 rows / +$1,641.63 come back from `status IN ('closed','resolved')`, and no row carries
  `status='open'` with a stamp.
- The rec's premise re-derived before shipping: it quoted `track −$420.97` vs `watch +$2,060.51`; the same
  query now returns `−$434.17 / +$2,075.80` on a total that moved `+$1,639.54 → +$1,641.63` — the
  difference is today's settlements, not a different query.
- **What the line makes visible and must not be misread:** the split is by the wallet's **current** status
  over a **frozen** history. A wallet can be `track` when it is copied and `watch` a day later, so "the
  tracked lose and the demoted win" is a statement about the cap and the selection, not a verdict on the
  strategy. It gates nothing.
- Verify: `grep -c "by wallet status" logs/cron/copybot-eod.log` ≥ 7 — exactly **one** line per EOD run
  (the phrase appears in no other artifact; the appending step's shell comment is not echoed), and the
  second line carries the SQL for a same-day re-run. First EOD run after the change: **tonight 22:00**
  (count is 0 until then).

---

## What deliberately did not change

- No RuleSet version, no threshold, no sizing factor, no gate. The **copy set is still 25 wallets** and the
  copy path is byte-identical apart from the two filters above.
- The observation window is bounded: 7 days, 40 wallets, most-recently-tracked first; hitting the cap logs
  `[OBSERVE-CAP]` rather than silently truncating.
- `minConfidence` / `minCopyScore` still wait for the Oct 8 close; the drift-decay bar, the wallet-cap
  basis and the 23:00 ET hour gate are untouched.

## Follow-ups

1. **Re-read the funnel after 2026-09-23** (once the catch-up burst has aged out of the 24h window): the
   steady-state number is the one to compare against the pre-collapse 6,515 and against the observation
   split — `SELECT observationOnly, COUNT(*) FROM ObservedTrade WHERE createdAt > <now-24h> GROUP BY 1`.
2. **Observation rows are a measurement pool, not a copy pool.** If a future review wants to price
   "should the copy set be wider / should it be re-selected on evidence", the data now exists
   (5.4k rows/day from demoted-but-recently-tracked wallets) — but reading it requires joining those rows
   to settlement, which is a new instrument, not a threshold change.
3. Standing inputs for the daily reviewer cron were updated in the same change so #34 does not re-propose
   the split and does not quote `ObservedTrade/24h` as a single number.
