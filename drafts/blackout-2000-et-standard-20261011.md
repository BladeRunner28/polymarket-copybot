# Re-test — STANDARD 20:00 ET blackout finding

**Card id:** `standord-2000-shared-blackout-finding` (column: Backlog)
**Measurements only. No rule, threshold, gate or size change is proposed.**

## Gate text (verbatim, binding)

> Findings-only until the Oct 8 window close (window purity). Post-close: gate if STANDARD 20:00 stays positive on a post-v52 slice with n >= 40.

**Deliverable asked:** does STANDARD 20:00 ET stay POSITIVE at n >= 40 on the post-v52 slice?

## VERDICT (one line)

**GATE FAILS — post-v52 STANDARD 20:00 ET has n = 0 legs** (n >= 40 required): the shared `C200_BLACKOUT_HOURS_ET = {20}` set (applied to BOTH books since v44, 2026-09-02) blocks every STANDARD entry at 20:00 ET, so the all-time +$887.61 / 252 rows is 100% pre-v44 legacy (2026-07-15 → 2026-09-01) and cannot be re-confirmed on any post-v52 data.

---

## 1. Environment / basis facts

- Live DB: `prisma/dev.db` (10.36 GB), read-only via `file:...?mode=ro&immutable=1`. Repo-root `dev.db` is a 0-byte decoy (confirmed).
- All reads taken while the DB is a point-in-time view; numbers date-stamped **2026-10-11 ~16:00 UTC**.
- PaperTrade vocabulary: `status` ∈ {closed 8267, open 1288, resolved 3040}; `venue` ∈ {Polymarket 12503, Kalshi 92}; `botId` ∈ {STANDARD 10191, BANKROLL_200 2404}. Data range openedAt = 2026-06-18 → 2026-10-11.
- **Timezone bases (stated for every number below):**
  - DATETIME columns are Unix **ms** integers; `datetime(col/1000,'unixepoch')` renders **UTC**.
  - The card's SQL converts to **ET with `'-4 hours'`** (EDT). That is correct for these rows — every STANDARD 20:00 leg is dated Jul–Aug 2026 (EDT season) — but the literal is **wrong after 2026-11-01** (EST = UTC-5), and the hard-coded `strftime('%s','<date>')` + `'-4 hours'` idiom has known traps here.
  - The **UTC** basis is given too; it selects a *different* hour (20:00 UTC = 16:00 ET) and is shown only to make the convention's effect visible — do NOT compare it to the ET line.

## 2. v52 apply date

`RuleSet` has **no `appliedAt` column** (contra the task brief). Schema columns: `id, version, active, rulesJson, createdAt, updatedAt`. The per-version wall-clock is recoverable from the chained timestamps (each row's `updatedAt` == next row's `createdAt`).

Command / raw output:

```
sqlite3 'file:.../prisma/dev.db?mode=ro' "SELECT version, active, createdAt, updatedAt FROM RuleSet ORDER BY version"
51|0|1788922926885|1788963571287
52|0|1788963571287|1789292076461
53|0|1789292076461|1789547142431
...
61|1|1791617166074|1791617166074
```

```
v44.created 1788364891254 2026-09-02 16:01:31 UTC   <- shared 20:00 blackout applied to BOTH books
v45.created 1788417839841 2026-09-03 06:43:59 UTC
v52.created 1788963571287 2026-09-09 14:19:31 UTC   <- POST-v52 boundary
v53.created 1789292076461 2026-09-13 09:34:36 UTC   <- v52 active until here
v61.created 1791617166074 2026-10-10 07:26:06 UTC   <- ACTIVE ruleset
```

- **v52 applied 2026-09-09 14:19:31 UTC** (`1788963571287`). Git commit `43f5fc4` "v52 (TR-20): revert v51 auto-tune…" dated 2026-09-09 09:20:05 -0500 (= 14:20:05 UTC) matches. Active `RuleSet` = **v61**.
- `scripts/apply-v52.ts` exists; it restores the pre-registered Kelly-window config (drift 0.004, minLiquidity 750) and does **not** touch the hour policy.

## 3. WHERE the blackout lives (config quote)

The hour blackout is **NOT in the RuleSet at all** — no hour/blackout key exists in the active v61 `rulesJson`:

```
sqlite3 ... "SELECT json_extract(rulesJson,'$.blackoutHoursEt'), ... WHERE active=1"
||                                                    (all three NULL/empty)
```
The full key list of v61's rulesJson contains no `*blackout*` key.

It lives entirely in **code**: `src/lib/hour-policy.ts`.

```
export const C200_BLACKOUT_HOURS_ET: ReadonlySet<number> = new Set([20]); // v48: 23:00 un-gated (phantom-Kalshi artifact)
// ... this one must NOT [apply to STANDARD] — 08:00 ET is C-200-negative but STANDARD-positive ...
export const C200_ONLY_BLACKOUT_HOURS_ET: ReadonlySet<number> = new Set([8]);
export const C200_HAIRCUT_HOUR_ET = 10;

export function isHourBlackedOut(botId: string, etHour: number): boolean {
  if (C200_BLACKOUT_HOURS_ET.has(etHour)) return true;                 // <- SHARED: BOTH books
  return botId === "BANKROLL_200" && C200_ONLY_BLACKOUT_HOURS_ET.has(etHour);  // <- C-200 only
}
```

Call site: `scripts/score-trades.ts:14` (import) and ~line 706, inside `for (const botId of ["STANDARD", "BANKROLL_200"])`:

```
// v44 (tuning review #13, approved): hour blackout now covers BOTH books ...
if (isHourBlackedOut(botId, etHour)) {
  log(`[${botId}] hour blackout ${etHour}:00 ET (significant drain) — skipping copy ${t.marketId}`);
  legBlocks.push(`${botId}: hour blackout ${etHour}:00 ET`);
  continue;
}
```

**Answer to Q2: YES — 20:00 ET is still applied to BOTH books** (`C200_BLACKOUT_HOURS_ET = {20}`, shared, no `botId` guard), while **08:00 ET is C-200-only** (`C200_ONLY_BLACKOUT_HOURS_ET = {8}`). The two sets are exactly as the card describes. The comment in the file even flags this finding in-line ("the shared 20:00 gate is C-200-only in spirit … flagged, not changed here").

## 4. All-time figures re-derived (card basis, ET = `'-4 hours'`)

Command (the card's figure, but with the date filter dropped so it is genuinely all-time):

```
sqlite3 'file:.../prisma/dev.db?mode=ro&immutable=1' "SELECT botId, COUNT(*), ROUND(SUM(realizedPnl),2) FROM PaperTrade WHERE status IN ('resolved','closed') AND realizedPnl IS NOT NULL AND isDemo=0 AND venue!='Kalshi' AND CAST(strftime('%H',openedAt/1000,'unixepoch','-4 hours') AS INT)=20 GROUP BY botId;"
```
Raw output:
```
BANKROLL_200|31|-80.43
STANDARD|261|898.33
```

Control hour 08:00 ET (same predicate, hour = 8):
```
BANKROLL_200|34|-71.12
STANDARD|271|906.77
```

| hour ET | book | all-time n | all-time ΣrealizedPnl | card (2026-09-13) | delta |
|---|---|---|---|---|---|
| 20:00 | BANKROLL_200 | 31 | **−$80.43** | 31 / −$80.43 | exact |
| 20:00 | STANDARD | 261 | **+$898.33** | 252 / +$887.61 | +9 legs / +$10.72 |
| 08:00 | BANKROLL_200 | 34 | **−$71.12** | 34 / −$71.12 | exact |
| 08:00 | STANDARD | 271 | **+$906.77** | 250 / +$1,048.17 | +21 legs / −$141.40 |

C-200 matches the card **exactly** for both hours. The STANDARD deltas are genuine movement since the card's 2026-09-13 snapshot, not a predicate difference (re-derivation under `no isDemo`, `no venue`, `resolved-only`, `closed-only` all tracked the same 261). Reconciliation of the 20:00 STANDARD delta:

```
hour-20 STANDARD rows whose exit stamp is BEFORE 2026-09-13: 252   (= the card's count)
hour-20 STANDARD rows whose exit stamp is AFTER  2026-09-13:   9   (= the +9)
```
So the card's `252 / +$887.61` was the as-of-2026-09-13 read; 9 slow-settling legs landed afterwards. **The card's figures are reproducible** — they are simply a 2026-09-13 point-in-time snapshot.

### The card's own verify SQL returns EMPTY (a real result, not a bad predicate)

```
sqlite3 ... "SELECT botId, COUNT(*), ROUND(SUM(realizedPnl),2) FROM PaperTrade WHERE ... AND openedAt >= strftime('%s','2026-09-06')*1000 GROUP BY botId;"
(no rows; exit 0)
```
The predicate itself is sound (`strftime('%s','2026-09-06')*1000` = integer `1788652800000`; `openedAt >= 1788652800000` matches 1,665 rows overall). It returns nothing **because every STANDARD 20:00 row is dated on/before 2026-09-01** — i.e. the hour had already been shut off before Sep 6. Confirmed: `openedAt >= 1788652800000 AND hour-20 ET` = **0 rows**. This is the finding, not a query fault (re-ran with filters dropped — still 0).

## 5. POST-v52 slice (the gate population)

Command:
```
... AND CAST(strftime('%H',openedAt/1000,'unixepoch','-4 hours') AS INT)=20 AND openedAt >= 1788963571287 GROUP BY botId;
```
Raw output (**empty**).

Filter-dropped confirmation (any status, any demo, any venue), and the sibling hours:

```
-- ALL filters dropped, hour-20 ET, post-v52:
SELECT COUNT(*) ... WHERE hour=20 ET AND openedAt >= 1788963571287;   -> 0

-- post-v44 (2026-09-02), STANDARD hour-20:
SELECT COUNT(*) ... WHERE botId='STANDARD' AND hour=20 ET AND openedAt >= 1788364891254;  -> 0

-- STANDARD post-v52 rows per ET hour (histogram):
0:18  1:14  2:8  3:12  4:19  5:12  6:22  7:21  8:18  9:20  10:15  11:25  12:25
13:18  14:35  15:21  16:15  17:31  18:20  19:10  [20: ABSENT]  21:18  22:9  23:11
```

**Every ET hour except 20:00 has post-v52 STANDARD legs; hour 20 has none.** The hour is structurally blacked out for BOTH books since v44 (2026-09-02), so "post-v52" = "post-v44" for this hour and the population is empty.

Control (08:00, the C-200-only hour — STANDARD still allowed):

```
all-time: BANKROLL_200 34 -71.12 ; STANDARD 271 906.77
post-v52: BANKROLL_200  7   0.48 ; STANDARD  16 -93.69
```

Note the control's implication: for the hour that IS measurable post-v52 (08:00), the STANDARD all-time **+$906.77 / 271** does **not** stay positive — it collapses to **−$93.69 / 16** post-v52. (The gate for the 20:00 finding is never reached, but the sibling hour is a caution against reading the all-time STANDARD hour positives as durable.)

## 6. Slice hygiene (all required)

### (a) Timezone basis of every number
Stated in §1 and beside each figure. Summary of the same STANDARD hour-20 population under each basis:

| basis | n | ΣrealizedPnl | meaning |
|---|---|---|---|
| ET via `'-4 hours'` (card basis) | **261** | **+$898.33** | 20:00 ET (correct for these EDT-season rows) |
| ET via `'-5 hours'` | 119 | +$30.85 | actually selects 21:00 ET — not the same hour; shown only to expose the literal's fragility post-2026-11-01 |
| UTC (`datetime(...,'unixepoch')`) | 482 | **−$245.60** | selects 16:00 ET — a DIFFERENT population; do not compare to the ET row |

The UTC read flips the sign (−$245.60) purely because it is a different hour. **Quote the ET basis with the number**; after 2026-11-01 the `'-4 hours'` literal must become `'-5 hours'`.

### (b) Concentration — top 5 rows by |realizedPnl| (STANDARD 20:00, all-time)

| # | marketId | outcome | openedAt (ET) | realizedPnl |
|---|---|---|---|---|
| 1 | `will-argentina-score-the-most-goals-at-the-2026-fifa-world-cup` | NO | 2026-07-15 20:38:36 | **+107.88** |
| 2 | `will-haley-stevens-win-wayne-county-in-the-michigan-senate-democratic-primary-...` | YES | 2026-07-31 20:57:07 | +55.74 |
| 3 | `will-lamine-yamal-win-the-young-player-award-at-the-2026-fifa-world-cup-...` | NO | 2026-07-15 20:36:08 | +34.08 |
| 4 | `will-lamine-yamal-win-the-young-player-award-at-the-2026-fifa-world-cup-...` | NO | 2026-07-15 20:36:08 | +34.08 |
| 5 | `will-lamine-yamal-win-the-young-player-award-at-the-2026-fifa-world-cup-...` | NO | 2026-07-15 20:36:09 | +34.08 |

- Sum = **+$898.33** (n=261). Sum **excluding the single top row** = **+$790.45**. So the pelt is not one row — but see the clustering below.

Top markets and days by summed PnL:

```
marketId                                                          legs   ΣPnL
will-spain-win-the-2026-fifa-world-cup-963                         54   +477.90
wta-samsono-keys-2026-07-27                                         8   +230.37
will-lamine-yamal-win-young-player-award-...-wc                    6   +204.48
cs2-fut-ts7-2026-08-23-map-handicap-home-2pt5                       6   -112.56
ethereum-above-2500-on-august-31-2026                               6   -107.28
lol-miss-cont-2026-07-22-game2                                      8   -102.32
val-100t1-kru1-2026-07-24-game2                                    10    +95.31

ET day            legs   ΣPnL
2026-07-15         112  +826.77   <- 92% of the whole slice's +$898.33
2026-07-27           8  +230.37
2026-08-22           8  -104.81
2026-07-22           8  -102.32
2026-07-24          10   +95.31
```

**Concentration is severe: ONE ET day (2026-07-15) carries 112 of 261 legs and +$826.77 = 92% of the slice's net.** Inside that day, the single market `will-spain-win-the-2026-fifa-world-cup-963` contributes 54 legs and +$477.90 — **all 54 on 2026-07-15** (53% of the slice's net on one market, one day). The +$887.61/+$898.33 "STANDARD-positive hour" is essentially one FIFA-World-Cup market on one afternoon.

### (c) Label basis — market-outcome arm on the SAME rows

`realizedPnl` is the **exit-policy** label. The same 261 legs labelled by **market outcome** (`didOutcomeWin()` semantics: normalize label, compare to `OutcomeReview.finalOutcome`; true / false / null):

```
SLICE n=261
  no OutcomeReview row        : 150
  didOutcomeWin = TRUE (won)  : 63   sum realizedPnl = +399.36
  didOutcomeWin = FALSE (lost): 48   sum realizedPnl = -571.06
  didOutcomeWin = NULL (undet): 150
  -- on the 111 rows with a definite outcome label --
  realizedPnl>0 sign AGREES  with market win : 103
  realizedPnl>0 sign DISAGREES               :   8
```

- `realizedPnl > 0` arm: 261 legs, Σ **+$898.33** (positive).
- **market-outcome arm on the same legs:** 63 won (+$399.36) vs 48 lost (−$571.06) → net **−$171.70** on the 111 labelable rows. **The two arms disagree in sign.** Classic negative skew (winners avg +$6.34, losers avg −$11.90).
- 8 of 111 labelable rows have an exit-contaminated sign (profitable exit on a losing token or vice-versa) — consistent with the standing 7.4% disagreement rate.
- Caveat: **150 of 261 legs carry no `OutcomeReview` row**, so the outcome arm is only readable on 111 legs. The +$898.33 headline is carried mostly by the *unlabelled* 150 legs (+$1,070.03 of net), i.e. the money is on rows whose market outcome this DB cannot even name.

**The published +$887.61/+$898.33 is a `realizedPnl` figure; on the market-outcome basis the same legs are net negative.** Any move to act on this finding must be judged on the label basis the *gate* names (`realizedPnl`), but the divergence must be stated.

### (d) Legs vs decisions

```
distinct markets            = 110
distinct ET days            =  25
distinct decisionJournalId  = 261
legs                        = 261
```
261 legs = 261 distinct decisions (1 leg per decision; **no fan-out** in this slice). But the 25 days / 110 markets, dominated by one day/one market, mean the effective sample is far smaller than n=261 — the 08:00 control and the market-clustered view both point the same way.

## 7. Answer to the gate

The gate: *"gate if STANDARD 20:00 stays positive on a post-v52 slice with n >= 40."*

- Post-v52 STANDARD 20:00 ET: **n = 0**, ΣrealizedPnl = n/a (no rows).
- Cause: `C200_BLACKOUT_HOURS_ET = {20}` is a SHARED set applied to BOTH books (`isHourBlackedOut` has no `botId` guard at hour 20) — live since v44 (2026-09-02). No STANDARD leg can open at 20:00 ET, so there is no post-v44 (hence no post-v52) population to read.
- Therefore **n >= 40 is not met → GATE FAILS.** The +$887.61 / 252 rows is 100% pre-v44 legacy (2026-07-15 → 2026-09-01), dominated by one day and one market, and is **not** re-confirmed by any post-v52 mechanics.

**Do not touch the gate**: the gate's own condition cannot be satisfied, so the finding remains un-actionable as written. If a future session wants to price the counterfactual it must do so on the pre-v44 rows with the concentration and label-basis caveats above, or reopen the card with a new pre-registered bar.

---

## Appendix — full command log (raw outputs)

```bash
# status / venue / bot vocab + range
sqlite3 'file:.../prisma/dev.db?mode=ro&immutable=1' "SELECT status,COUNT(*) FROM PaperTrade GROUP BY status"
  closed|8267  open|1288  resolved|3040
sqlite3 ... "SELECT venue,COUNT(*) FROM PaperTrade GROUP BY venue"
  Kalshi|92  Polymarket|12503
sqlite3 ... "SELECT botId,COUNT(*) FROM PaperTrade GROUP BY botId"
  BANKROLL_200|2404  STANDARD|10191
sqlite3 ... "SELECT datetime(MIN(openedAt)/1000,'unixepoch'), datetime(MAX(openedAt)/1000,'unixepoch') FROM PaperTrade"
  2026-06-18 13:00:04 | 2026-10-11 15:04:41

# card SQL verbatim -> EMPTY
sqlite3 ... "SELECT botId, COUNT(*), ROUND(SUM(realizedPnl),2) FROM PaperTrade WHERE status IN ('resolved','closed') AND realizedPnl IS NOT NULL AND isDemo=0 AND venue!='Kalshi' AND CAST(strftime('%H',openedAt/1000,'unixepoch','-4 hours') AS INT)=20 AND openedAt >= strftime('%s','2026-09-06')*1000 GROUP BY botId;"
  (no rows)

# all-time hour-20 ET -> BANKROLL_200|31|-80.43 ; STANDARD|261|898.33
# all-time hour-08 ET -> BANKROLL_200|34|-71.12 ; STANDARD|271|906.77
# post-v52 hour-20 ET -> EMPTY
# post-v52 hour-08 ET -> BANKROLL_200|7|0.48 ; STANDARD|16|-93.69

# predicate soundness
sqlite3 ... "SELECT strftime('%s','2026-09-06')*1000"   -> 1788652800000 (integer)
sqlite3 ... "SELECT COUNT(*) FROM PaperTrade WHERE openedAt >= 1788652800000"  -> 1665

# hour histogram, STANDARD post-v52 (hour 20 absent):
# 0:18 1:14 2:8 3:12 4:19 5:12 6:22 7:21 8:18 9:20 10:15 11:25 12:25 13:18 14:35
# 15:21 16:15 17:31 18:20 19:10 [20:-] 21:18 22:9 23:11
```
