# Ladder credit basis — positions only, not booked rows

**Status:** PROPOSAL (Lane A). Nothing applied: no `scripts/apply-vNN.ts` run, no `prisma/dev.db`
write, no RuleSet row, no merge to main. The apply belongs to the operator after he reads this.

**Approval:** `apr-ladder-credit-positions-only` (roadmap `ladder-credit-positions-only`), approved
2026-11-16T16:54:04Z.

**Instrument:** `python3 scripts/ladder-credit-positions-only.py` (read-only, sqlite `mode=ro`), committed
with this file. Reference date 2026-11-16, local calendar days, settle clock `COALESCE(closedAt, resolvedAt)`,
cost = `simulatedPositionSize` (dollars at risk), `SETTLE_DAYS=3`, `GATE_DAYS=7` — the same constants
`query_bankroll.js` runs.

---

## 1. Verdict

**The card's mechanism is real and I reproduced it exactly. Its leg counts are stale, and two of its
per-day rates were read off a different clock than the one the ladder uses. Neither changes the fix.**

1. **Confirmed: the advance gate credits legs that were never positions.** Every surface that publishes a
   C-200 PnL sums the stored `realizedPnl` column with no fill filter. Only the write path applies
   `bookedPnl()`. A leg that settled *before* the resolver stamped it `fillStatus='unfilled'` keeps the money
   it was booked with, and the ladder counts it forever.
2. **The class is 376 legs carrying +$2,297.07** on $4,521 of notional, all-time — 41% of the published
   all-time realized figure of +$5,659.57.
3. **The advance itself does not move today.** Settled 7d sum (11-07 .. 11-13): **+$207.01 → +$106.14**
   against Phase 1's $1,750 (11.8% → 6.1%). Both fail; the rung is unchanged. What moves is the *rate*, and
   on the 14-day window it moves the sign: **+$18.31/day → −$12.30/day**.
4. **The card's `+$370.8` is exactly right and is the regime (v68+) class sum** (+$370.83 measured). Its
   "182 rows" is the *population* of unfilled legs at an earlier read (now **191**); only **43** of those 191
   carry money — the other 148 already book 0 because they were stamped before they settled. The `$4,469`
   notional is now $4,753. So: right defect, right dollar, wrong row count attached to it.
5. **The fix is one predicate on four read paths**, plus printing all four credit bases beside the number so
   no reader can quote one without the others. That second half is not decoration: today's profit review
   (`drafts/profit-recs-20261116.md`, §1–2) measured that "positions only" is itself a second unadjudicated
   basis — the regime's +$35.5 sits entirely inside the 141 `fillStatus IS NULL` legs, and the 89 provable
   fills are −$455.4. Crediting positions-only without printing that split would publish $1.8/day as if it
   were a measurement.

---

## 2. Root cause (file:line, one sentence each)

| Where | What it does | Why the phantom survives |
|---|---|---|
| `src/lib/paper.ts:47` `bookedPnl()` | returns 0 when `fillStatus === 'unfilled'` | correct, and **only** called from the three PnL-WRITE sites (`:360`, `:381`, `:493`) |
| `scripts/c200-fill-resolve.ts:177` | stamps `fillStatus` / `fillBasis` / `fillResolvedAt` | **never recomputes `realizedPnl`** on a leg it is stamping — so a settled leg keeps its booked money |
| `query_bankroll.js:115` | selects `{ realizedPnl, closedAt, resolvedAt }` for the 14-day series | no `fillStatus` in the select → the gate cannot apply the predicate even if it wanted to |
| `query_bankroll.js:321` | the printed reproduction SQL | `SUM(realizedPnl)` with no fill filter — re-running the line the report prints reproduces a number the report is about to change |
| `src/app/page.tsx:316-336` | builds `c200Daily` then walks `C200_PHASES` | sums raw `realizedPnl` |
| `src/app/analytics/page.tsx:52-74`, `:167` | `activePhase()` on the raw daily series | same |
| `src/lib/report.ts:640-660` | EOD `cmpRealized` / `cmpPnlToday` / win rate | same |

Measured proof of the ordering defect — the split is clean:

- **150** unfilled legs carry **zero**, and **149** of them were stamped **before** they settled
  (`fillResolvedAt <= COALESCE(closedAt,resolvedAt)`): `bookedPnl()` ran at settle time and did its job.
- **376** unfilled legs carry money, and **376 of 376** were stamped **after** they settled: the stamp
  arrived too late to be applied to a stored settlement.

The stamp event is **batched**, not continuous. The largest phantom legs carry `fillResolvedAt = 2026-11-15`
while settling days earlier:

| settled | market | PnL | risk | stamped |
|---|---|---|---|---|
| 2026-11-12 | `cbb-utsa-sea-2026-11-11` (UTSA ROADRUNNERS) | **+$268.02** | $20 | 2026-11-15 |
| 2026-11-03 | `ucl-vil-psg-2026-11-03-spread-away-2pt5` (PSG) | +$222.75 | $50 | 2026-11-15 |
| 2026-11-06 | `col-kob-sab-2026-11-05-btts-first-half` (YES) | +$124.59 | $20 | 2026-11-15 |
| 2026-11-10 | `dota2-huliga-ic-2026-11-09` (INNER CIRCLE) | +$41.07 | $10 | 2026-11-15 |
| 2026-11-01 | `ufc-dhope-fra8-2026-10-31` (DAKOTA HOPE) | +$39.06 | $18 | 2026-11-15 |
| … 371 more | | | | |

The top 3 legs are **$615.36 = 27%** of the entire all-time phantom. So the defect is not a slow leak
spread evenly over the book; it is one sweep's worth of pre-stamped-settlement history, plus whatever the
next sweep adds.

---

## 3. What the gate reads today, both bases

`query_bankroll.js` semantics: 14 local days, settled window = days[3..10), advance at
`sum >= target × 7`.

| basis | settled 7d sum (11-07 .. 11-13) | need (Phase 1) | % of rung | rung | T+0 7d sum | legs |
|---|---|---|---|---|---|---|
| **BOOKED ROWS (live today)** | **+$207.01** | $1,750 | **11.8%** | Phase 1 (0 cleared) | +$459.78 | 163 |
| **POSITIONS ONLY (proposed)** | **+$106.14** | $1,750 | **6.1%** | Phase 1 (0 cleared) | +$321.44 | 163 |

Leg count is identical: the predicate zeroes a leg's *credit*, it does not delete the leg. Anything that
prints a leg count off this window is unaffected.

### 3.1 The windows the card quoted, on the ladder's own clock

| window | legs | notional | BOOKED | $/day | POSITIONS | $/day | phantom |
|---|---|---|---|---|---|---|---|
| last 7d (11-10 .. 11-16) | 99 | $2,475 | +$459.78 | +$65.68 | +$321.44 | +$45.92 | +$138.34 |
| last 14d (11-03 .. 11-16) | 259 | $6,595 | +$256.31 | +$18.31 | **−$172.13** | **−$12.30** | +$428.44 |
| regime v68+ (10-27 .. 11-16, 21d) | 299 | $7,655 | +$52.23 | +$2.49 | **−$318.60** | **−$15.17** | +$370.83 |
| whole book | 2,839 | $28,724 | +$5,659.57 | — | +$3,362.50 | — | +$2,297.07 |

The 14-day figure is the one that matters for a reader: **the lane's published 14-day run-rate is positive
only because of legs it does not own.** Take them out and the lane is −$12.30/day over two weeks.

### 3.2 Payoff figures on the same column (these move too)

| population | win rate | PnL | ROI | → positions only |
|---|---|---|---|---|
| whole book | 44.5% (1,262/2,839) | +$5,659.57 | +19.70% | **39.4%** / **+$3,362.50** / **+11.71%** |
| trailing 14d | 18.9% (49/259) | +$256.31 | +3.89% | **12.7%** / **−$172.13** / **−2.61%** |
| regime v68+ | 20.4% (61/299) | +$52.23 | +0.68% | **13.7%** / **−$318.60** / **−4.16%** |

Win rate falls because 143 phantom *winners* stop counting as wins while the 233 phantom *losers* were
already non-wins. Any surface that prints a win rate next to a realized total has to move with it or the
pair stops reconciling — the exact defect class the 2026-11-16 self-audit fixed on the EOD.

### 3.3 The class, precisely

| cut | legs | PnL | notional |
|---|---|---|---|
| stamped `unfilled`, finished, all-time | 526 | — | — |
| … of which carry non-zero `realizedPnl` | **376** | **+$2,297.07** | $4,521 |
| … of which carry zero (stamped before settling) | 150 | $0 | — |
| sign split of the 376 | 143 winners / 233 losers | +$4,845.18 / −$2,548.11 | — |
| by settle month | 09: 54 · 10: 283 · 11: 39 | +$251.72 · +$1,668.72 · +$376.63 | — |
| regime v68+ subset | 191 unfilled, **43 carrying** | **+$370.83** | $4,753 |

---

## 4. Correction table — the card vs a reproducible read

| card claim | reproduced today | why it differs |
|---|---|---|
| last 7d BOOKED **169 legs $3,843 +$424 = $60.6/day** | same query family now: **143 legs $3,219 +$412.44**; on the **ladder's clock** (local days, T+3 lag): **99 legs $2,475 +$459.78** | the card's arm is `profit-supply-ladder.py` §S5 — a 7×24h roll from the last settle, re-run at an earlier timestamp. The ladder is local-calendar and excludes the 3 un-settled days. Two different windows, quoted as one. |
| last 7d POSITIONS **82 legs $1,645 +$303 = $43.4/day** | 70 legs $1,312 +$243.43 (S5 clock) / 99 legs +$321.44 (ladder clock) | same, plus: the positions arm *drops* the unfilled legs from the count, so its leg count differs from the booked arm. Under this proposal the count stays and only the credit zeroes. |
| last 14d BOOKED **350 $7,631 +$293 = +$20.9/day** | 259 legs $6,595 **+$256.31 = +$18.31/day** | same clock mismatch |
| last 14d POSITIONS **182 $3,406 −$84 = −$6.0/day** | 259 legs **−$172.13 = −$12.30/day** | same; the sign agrees, the size is 2× |
| regime BOOKED **404 $8,757 +$505 = $26.8/day** | C-200-only: 299 legs $7,655 **+$52.23 = +$2.49/day**; all-lane 421 legs $9,141 **+$406.3** (`profit-recs-20261116` §1) | the card's regime figure is the **two-lane** population divided by 17.8 days; the ladder only ever reads C-200. Recomputed on the ladder's own lane the booked regime rate is +$2.49/day, not $26.8. |
| regime POSITIONS **222 $4,288 +$134 = $7.1/day** | C-200-only: **−$318.60 = −$15.17/day** | same lane/window cause, and the sign flips once the window is the ladder's |
| **182 rows stamped unfilled still carry +$370.8 on $4,469** | **191 rows**, **$4,753** notional, **+$370.83**; of the 191, **43 carry money** | the +$370.8 reproduces to the cent. 182→191 is one more resolver sweep; the row *count* is the population, not the money-carrying subset — quote 43/191 or a reader thinks 191 legs are inflating the book. |

**None of these corrections weakens the card.** Every one of them is the same defect measured on a
different clock, and the one number the card hinged on (+$370.8) is exact. The corrections matter because
the ladder's advance is decided on the ladder's clock, and that is the window this proposal changes.

---

## 5. Fix design

### 5.1 One predicate, one owner

Reuse `src/lib/paper.ts::bookedPnl()` — do **not** fork a second predicate. Export it (already exported) and
have every read path call it with the row's `fillStatus`:

```ts
// src/lib/paper.ts — unchanged, already the single source of truth
export function bookedPnl(leg: { fillStatus?: string | null }, pnl: number): number {
  if (!fillAwareBookingEnabled()) return pnl;
  if (leg.fillStatus === "unfilled") return 0;
  return pnl;
}
```

`FILL_AWARE_BOOKING` is the existing opt-out (default ON since 2026-10-28), read per call. The read paths
reuse it, so the ladder's basis and the booking basis cannot diverge again — which is the whole reason this
defect exists.

### 5.2 The four surfaces that must move together

| # | file | change |
|---|---|---|
| 1 | `query_bankroll.js:112` | add `fillStatus: true` to the `select`; bucket `bookedPnl(t, t.realizedPnl ?? 0)` |
| 2 | `query_bankroll.js:321` | reproduction SQL gains `AND (fillStatus IS NULL OR fillStatus <> 'unfilled')` so the printed line reproduces the printed number |
| 3 | `src/app/page.tsx:316-336` | `c200Daily` and the ladder walk use the predicate; the C-200 realized card (`cmpRealizedPnl`, `:108`) does too |
| 4 | `src/app/analytics/page.tsx:150-170` | the daily series feeding `activePhase()` uses the predicate; `:313` aggregate likewise |
| 5 | `src/lib/report.ts:640-660` | `cmpRealized`, `cmpPnlToday`, and the C-200 payoff rows (`:530-534`) use the predicate; the printed line names the basis |
| 6 | both reviewer prompts (`copybot-c200-daily-report` 18:00, `copybot-tuning-review-daily` 07:00) | the advance-basis text is duplicated across both prompts — **5 occurrences of `rolling 7d`** in `~/.hermes/cron/jobs.json`. Update in the same change or the reviewers re-litigate the old basis the next morning. |
| 7 | `data/phase-streak-log.jsonl` rows | new rows carry `creditBasis: "positions-only"`; rows written before 2026-11-16 carry no basis and must be read as booked-rows. The file is append-only and **must not be rewritten**. |

### 5.3 Print all four bases (the 11-16 review's requirement)

Beside the gate figure, print the same settled 7d window split four ways. Measured today:

| basis | legs | cost | PnL | ROI | $/day (regime) |
|---|---|---|---|---|---|
| booked rows | 421 (both lanes) | $9,141 | +$406.3 | +4.4% | +$20.5 |
| positions only | 230 | $4,387 | +$35.5 | +0.8% | +$1.8 |
| unadjudicated (`fillStatus IS NULL`) | 141 | $2,281 | +$490.9 | +21.5% | +$24.8 |
| confirmed filled | 89 | $2,106 | −$455.4 | −21.6% | −$23.0 |

Four lines cost nothing and they are the difference between "the ladder is honest now" and "the ladder is
honest about one of its two inflators". **Do not adopt positions-only as the sole printed basis.**

---

## 6. Before/after — every published figure that moves

| surface | line | before | after | delta |
|---|---|---|---|---|
| `query_bankroll.js` → 18:00 report | Phase gate, settled 7d | +$207.01 (11.8%) | +$106.14 (6.1%) | −$100.87 |
| `query_bankroll.js` | T+0 7d sum | +$459.78 | +$321.44 | −$138.34 |
| `query_bankroll.js` | 14-day daily series | 14 numbers | 14 numbers: 7 lower, 4 higher, 3 unchanged (a day can move up when a phantom leg was a loser) | see §3.1 |
| `query_bankroll.js` | Today's realized | +$17.66 (3 legs) | +$17.66 | **no change today** |
| `query_bankroll.js` | Phase stability streaks | 0/7 both | 0/7 | none |
| `page.tsx` overview | C-200 realized (all-time) | +$5,659.57 | +$3,362.50 | −$2,297.07 |
| `page.tsx` overview | ladder `c200GoalIdx` | 0 (Phase 1 active) | 0 | **rung unchanged** |
| `page.tsx` overview | Today's PnL card | +$17.66 | +$17.66 | none today |
| `analytics/page.tsx` | gate sum / "short by" | +$207.01 / −$1,542.99 | +$106.14 / −$1,643.86 | −$100.87 |
| `analytics/page.tsx` | all-time realized | +$5,659.57 | +$3,362.50 | −$2,297.07 |
| EOD `report.ts` | C-200 Total PnL (settled half) | +$5,659.57 | +$3,362.50 | −$2,297.07 |
| EOD `report.ts` | C-200 win rate | 44.5% | 39.4% | −5.1pp |
| EOD `report.ts` | C-200 ROI | +19.70% | +11.71% | −7.99pp |
| EOD `report.ts` | PnL today | +$17.66 | +$17.66 | none today |
| `BotBankroll.realizedPnl` | ledger | +$5,659.57 | **unchanged** | 0 |
| exposure cap (`netWorth`-linked) | cap | $3,826 | **unchanged** | 0 |

The ledger row and the row-sum happen to be identical (`gap −0.00`), which is why a *read-path* change is the
safe move: it moves the published figures without touching the accounting identity, the drawdown peak, or
the equity-linked cap.

---

## 7. Scope — what this proposal deliberately does NOT include

**(a) Restating the 376 stored rows.** Would move the same +$2,297.07 out of the ledger itself. Not proposed
now because the second channel it feeds is **not binding**: `netWorth` $7,551.45 → cap $3,826; on positions
$5,254.38 → cap $2,677; **open C-200 notional is $82.86, i.e. 2.2% of the booked cap**. There is no live risk
consequence to defer, and a row rewrite is irreversible history with no measured benefit today. It becomes
worth doing only if open notional approaches ~$2.6k.

**(b) The two DECISION paths that read the same column.** Same bug, different blast radius, needs its own
approval each:

- `scripts/score-trades.ts:65` — `kalshiRealized` (venue circuit breaker) and `:75` `todayC200Pnl` (the
  v40 daily-loss limit). Removing phantom profit makes the daily-loss gate fire **sooner** on a losing day
  (phantom was net +), i.e. it changes what the bot decides. Lane A, separate card.
- `src/lib/rule-updater.ts:228` — wallet downgrade at `realizedPnl < −$10` over ≥3 copies. Phantom legs can
  hold a bad wallet above the threshold. Lane A, separate card.

**(c) STANDARD.** `fillStatus` is NULL on every STANDARD leg (no stamping booth — `src/lib/c200-fill-resolve.ts`
is scoped `botId: "BANKROLL_200"`), so the predicate is a **no-op** there today. Applying it is still correct
(it becomes live the day STANDARD gets stamped) but it changes no number now.

**(d) Rewriting `data/phase-streak-log.jsonl`.** Append-only history; the basis is recorded per row instead.

---

## 8. Overridable flags (each one line, the number it changes, how to revert)

- **F1 — basis:** credit = `fillStatus === 'unfilled' ? 0 : realizedPnl` (keep `NULL` credited at p(fill)=1).
  Changes: gate **$207.01 → $106.14**; all-time **+$5,659.57 → +$3,362.50**; 14d rate **+$18.31 → −$12.30/day**.
  Revert: `FILL_AWARE_BOOKING=0` in the dashboard/sidecar env, or revert the one-line predicate.
- **F2 — print all four bases:** adds 3 lines to the report, moves no number. Revert: drop the block.
- **F3 — leave the ledger alone** (recommended for now): cap stays $3,826 instead of $2,677. Revert: run a
  restatement pass (needs its own approval; §7a).
- **F4 — risk gates and the wallet downgrade** stay on booked rows: daily-loss gate and Kalshi breaker keep
  today's optimism. Revert: apply the same predicate there (§7b, own approval).

**If any of these is wrong, the number that changes is named above; say the flag letter and I re-cut it.**

---

## 9. Apply checklist (operator)

1. Land the predicate in the four read paths (§5.2 items 1-5) in **one** commit — a partial landing leaves the
   dashboard contradicting the 18:00 report, and the report's own reproduction SQL contradicting both.
2. Update both reviewer prompts in the same change (5 occurrences of `rolling 7d` in `jobs.json`).
3. Tag new `phase-streak-log.jsonl` rows with `creditBasis: "positions-only"`; leave history byte-identical.
4. Dashboard ship: `npm run build` → `launchctl kickstart -k gui/$(id -u)/com.sxnyde2.copybot-dashboard` →
   poll `curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:3013/drafts` until 200. Do **not** `rm -rf
   .next` under launchd.
5. Verify against this document, not against the diff: report gate sum **+$106.14**, all-time **+$3,362.50**,
   win rate **39.4%**. If the report prints +$207.01 after the change, the select was not widened (the
   predicate cannot fire without `fillStatus` in the row).
6. Cheapest regression guard: `python3 scripts/ladder-credit-positions-only.py` prints both arms from the DB;
   the report's gate line must equal the POSITIONS arm, not the BOOKED arm.

---

## 10. Refutation conditions — what would make this proposal wrong

1. **If a later read shows ≥95% of unfilled legs stamped BEFORE they settle**, the read-path fix only cleans
   history and the durable fix is the write path (recompute at stamp time). Measured today: 149/150 zero-carry
   legs are pre-settle stamps, 376/376 money-carrying are post-settle — the post-settle path is alive, so this
   refutes only if that ratio inverts.
2. **If the operator restates the rows instead (§7a)**, the read predicate is redundant — harmless, but the
   proposal's value collapses to the four-basis print (F2).
3. **If a rung would clear on booked rows but fail on positions**, the fix changes an ADVANCE DECISION and needs
   to be treated as a rules change, not a measurement change. Measured today: 11.8% vs 6.1% of Phase 1 — no
   rung is close, so this is a measurement change.
4. **If `FILL_AWARE_BOOKING` is ever set to 0 in production**, both the write path and the new read paths revert
   together and the published number goes back up — by design, but it means the flag is now a published-number
   switch. Check the flag state before quoting any figure after a deploy.

---

## 11. Reproduce

```
python3 scripts/ladder-credit-positions-only.py                    # today
python3 scripts/ladder-credit-positions-only.py --reference 2026-11-14
cd ~/polymarket-copybot && DATABASE_URL="file:./dev.db" node query_bankroll.js    # the surface being changed
sqlite3 prisma/dev.db "SELECT COALESCE(fillStatus,'NULL'), COUNT(*), ROUND(SUM(simulatedPositionSize)), ROUND(SUM(realizedPnl),2) FROM PaperTrade WHERE botId='BANKROLL_200' AND isDemo=0 AND status IN ('closed','resolved') GROUP BY 1;"
```

Related, not superseded: `scripts/c200-ladder-fill-basis.py` (the unresolved-class read),
`scripts/profit-supply-ladder.py` §S5/§S6 (the four-basis table), `drafts/profit-fill-reachable-basis-20261113.md`
(the booking-basis contract this proposal finally enforces on the read side),
`drafts/profit-recs-20261116.md` §1–2 (why positions-only must not be printed alone).
