# t_81d0a4cb — drift-shadow marker: head-of-line blocking starves the decay bar's 7d cohort

Instrument fix, branch `wt/drift-walk-rotation` (worktree `.worktrees/t_81d0a4cb`), not merged.

## 1. Defect, reproduced

Unmodified code (`git show HEAD:scripts/mark-shadow-longshot.ts`), live log:

```
$ grep -o "shadow-drift: +[0-9]* marked this run (cap [0-9]*/run, backlog [0-9]*)" logs/cron/copybot-shadow-longshot.log | tail -5
shadow-drift: +0 marked this run (cap 300/run, backlog 6147)
shadow-drift: +0 marked this run (cap 300/run, backlog 6154)
shadow-drift: +0 marked this run (cap 300/run, backlog 6156)
shadow-drift: +0 marked this run (cap 300/run, backlog 6161)
shadow-drift: +0 marked this run (cap 300/run, backlog 6164)
```

Trailing consecutive `+0` runs: **14** (earlier streaks in the same log: 22 and 30). `4945 settled` is frozen across 15 consecutive lines.

The old walk selected the first `MARK_LIMIT` keys of the pending map (pre-fix `capPending(dPending)`): the first 25 / first 300 **pending keys** in candidate order, skipping keys that already carry a `resolve` row. Reconstructed read-only from the snapshot this branch ships (`git show HEAD:data/drift-shadow.jsonl`, md5 `5c65da226a4bb67fb98ec3b681cf3faa`, 6,147 distinct pending keys) and from the live copy (`data/drift-shadow.jsonl`, md5 `c75e79691d42236554e59290a31c5514`, mtime 2026-10-10 03:05 = 08:05Z, 6,165 distinct pending keys):

```
                                                   committed 5c65da22   live c75e7969
first 300 CANDIDATE ROWS (NOT what the walk took)  2026-09-17..09-17    2026-09-17..09-17
first  25 PENDING keys (the pre-fix walk)          2026-09-17..09-26    2026-09-17..09-26
first 300 PENDING keys (the pre-fix walk)          2026-09-17..09-26    2026-09-17..09-26
  those 300 fall on 7 distinct decision days: 239 on 2026-09-17, then 17/10/15/16/1/2 on 09-18..09-26
pending keys decided on/before 2026-09-26          4526 of 6147         4526 of 6165
pending keys decided on/after  2026-10-01          1127 of 6147         1145 of 6165
```

So the old walk's 300 slots spanned ten calendar days (2026-09-17..2026-09-26), 239 of them decided 09-17 — the card's "the walk window is one day" is the window of the first 300 *candidate rows*, which is not what the walk walked. Starvation is unaffected: nothing decided after 2026-09-26 was reachable at all, and 1,127 pending keys (live 1,145) were decided on/after 2026-10-01.

**The head is not archived — it is a cohort of long-dated markets that have not settled yet.** The first 30 of the pre-fix walk, re-read through the walk's OWN resolution path (`getAdapter().fetchMarket` + `fetchEventResolution`, `DATA_MODE=live`): `resolved=0, still open=30, threw=0`, every row carrying a live quote — NFL season series (Titans/Jaguars), the November BoE rate decision, the October Bank of Russia decision, the Berlin Abgeordnetenhaus, the Richmond mayoral election, NH-02, CA-07:

```
2026-09-17 will-the-titans-win-the-season-series-against-the-jaguars-...20260717194031567 [NO] fetchMarket{resolved=false, winner=undefined, yesPrice=0.066, endpoint=slug} fetchEventResolution=null
2026-09-17 no-change-in-bank-of-englands-interest-rates-after-november-2026-meeting-... [NO] fetchMarket{resolved=false, winner=undefined, yesPrice=0.09, endpoint=slug} fetchEventResolution=null
2026-09-17 will-the-abgeordnetenhaus-of-berlin-have-163-or-more-seats-after-the-2026-election [YES] fetchMarket{resolved=false, winner=undefined, yesPrice=0.1755, endpoint=slug} fetchEventResolution=null
2026-09-17 will-the-bank-of-russia-make-no-change-to-the-key-rate-after-the-october-meeting-... [NO] fetchMarket{resolved=false, winner=undefined, yesPrice=0.88, endpoint=slug} fetchEventResolution=null
2026-09-17 will-rob-howard-win-the-2026-richmond-mayoral-election-1786127591042 [NO] fetchMarket{resolved=false, winner=undefined, yesPrice=0.485, endpoint=slug} fetchEventResolution=null
```

`resolved === false` on every one of them means both resolution paths return nothing (`value === undefined` → `continue`), so each row is re-attempted every hour and never leaves the head. None of them 404s; none is archived.

**The `?slug=` empty body in the card is an artifact of the deprecated endpoint, not evidence of archival.** Measured today (2026-10-10, plain `curl`, no auth, twice), the legacy `GET /markets?slug=<slug>` still returns OPEN markets — HTTP 200, a ~6–9 kB body, `"closed":false,"active":true` on 5/5 live markets sampled, including these pre-fix head rows — and answers `[]` only for CLOSED ones:

```
# LIVE pre-fix head rows: the legacy form DOES return them
$ curl -s "https://gamma-api.polymarket.com/markets?slug=will-the-titans-win-the-season-series-against-the-jaguars-during-the-2026-27-nfl-regular-season-20260717194031567" | wc -c
    6262        # body: [{"id":"3026140","question":"Will the Titans win the season series against the Jaguars ...","outcomePrices":"[\"0.066\", \"0.934\"]","active":true,"closed":false,"archived":false, ...}]
$ curl -s "https://gamma-api.polymarket.com/markets?slug=no-change-in-bank-of-englands-interest-rates-after-november-2026-meeting-20260730150602309"
[... "outcomePrices":"[\"0.09\", \"0.91\"]","active":true,"closed":false, ...]                                                       # 9130 bytes
$ curl -s "https://gamma-api.polymarket.com/markets?slug=will-the-bank-of-russia-make-no-change-to-the-key-rate-after-the-october-meeting-20260724021538832" | wc -c
    6619        # same shape (Moonshot 9176, Berlin Abgeordnetenhaus 7163): 5/5 live sampled, all closed=false active=true
# CLOSED markets: the legacy form answers []
$ curl -s "https://gamma-api.polymarket.com/markets?slug=nfl-tb-dal-2026-10-09-rec-jake-ferguson-3pt5"
[]                     # a market the walk DOES mark (settled: outcomePrices ["0","1"], closed)
$ curl -s "https://gamma-api.polymarket.com/markets?slug=highest-temperature-in-hong-kong-on-september-18-2026-34c"
[]                     # the slug the card cites is CLOSED and already carries a resolve row here — never pending
$ curl -s "https://gamma-api.polymarket.com/markets/slug/highest-temperature-in-hong-kong-on-september-18-2026-34c" | head -c 110
{"$schema":"https://gamma-api.polymarket.com/schemas/Market.json","id":"4606295","question":"Will the highest temperature in Hong Kong be 34°C ...
```

Both cited temperature slugs (`highest-temperature-in-hong-kong-on-september-18-2026-34c`, `lowest-temperature-in-paris-on-september-17-2026-12c`) are CLOSED at the venue (`/markets/slug/` → `"closed":true`) and both already carry a `resolve` row in `data/drift-shadow.jsonl` (2026-09-21T03:26:18.257Z and 2026-09-17T23:25:45.901Z) — so neither was ever pending and neither was ever in the walk's head. The `[]` was taken on a settled slug.

The adapter prefers `/markets/slug/<slug>`, and the cited slug resolves through it — so it was never unresolvable and never sat in the head:

```
adapter.fetchMarket("highest-temperature-in-hong-kong-on-september-18-2026-34c")
  -> {resolved: true, winningLabel: "No", gammaEndpoint: "slug"}
fetchEventResolution("highest-temperature-in-hong-kong-on-september-18-2026-34c") -> "No"
data/drift-shadow.jsonl already carries its resolve row:
  {"ts":"2026-09-21T03:26:18.257Z","type":"resolve","marketId":"highest-temperature-in-hong-kong-on-september-18-2026-34c","outcome":"NO","value":1}
```

**True mechanism, same symptom.** Head-of-line blocking: the oldest-first walk burned all 300 slots on a cohort of September-decided long-dated markets that cannot settle yet, so decidable recent candidates sat behind them and 14 consecutive runs logged `+0`. Rotation is the right fix, and it fits this cause better than the archival story: the head's rows are still-open October/November-2026 rate decisions and elections, so they will settle on their own dates and the 24 h slow-cadence re-attempt is what will *mark* them, not just a safety net.

## 2. Change

| file | what |
| --- | --- |
| `src/lib/shadow-attempts.ts` (new) | per-candidate attempt ledger + `selectPendingForRun` rotation |
| `scripts/mark-shadow-longshot.ts` | drift walk uses the rotation; stamps attempts; prints the attempted window + cohort reason |
| `tests/shadow-attempt-rotation.test.ts` (new) | 8 tests pinning the ordering, the retry window, coverage and persistence |
| `.gitignore` | `data/shadow-attempt-state.json` (churning runtime state, precedent `data/c200-intent-watch-state.json`) |

Ordering: never-attempted first (most recently **decided** first among themselves) → then least-recently-attempted → a row at/over 3 consecutive failures waits 24 h before re-entering. Ledger is `data/shadow-attempt-state.json`, written atomically, checkpointed every 50 attempts, pruned to pending keys. The other three feeds (lowconf / longshot / wallet-cap) keep their oldest-first `capPending` walk untouched.

New knob: `DRIFT_TEST_LIMIT` caps the drift walk alone (for bounded proof runs); `SHADOW_ATTEMPT_FAIL_LIMIT` / `SHADOW_ATTEMPT_RETRY_HOURS` default to 3 / 24.

## 3. Before / after marker lines (verbatim)

BEFORE (HEAD code, `MARK_LIMIT=25`, same starting data as the after run):

```
shadow-drift: +0 marked this run (cap 25/run, backlog 6147). Gate counterfactual: 26367 would-have entries, 4945 settled (3179 wins, 64.3%), $37159.54 @ $10/trade ($7.51/trade, $0.38/trade ex-dust [695 rows below $0.1]). Summary: .../data/drift-shadow-summary.json
```

AFTER (same cap, same starting data):

```
shadow-drift: +11 marked this run (cap 25/run via DRIFT_TEST_LIMIT, backlog 6147; walk 25/6147 eligible, decided 2026-10-09..2026-10-10, 25 never attempted before, 0 held by the 3-fail/24h retry; trailing-7d attempted 25, resolved 11). Gate counterfactual: 26367 would-have entries, 5028 settled (3206 wins, 63.8%), $36927.64 @ $10/trade ($7.34/trade, $0.32/trade ex-dust [695 rows below $0.1]). Summary: .../data/drift-shadow-summary.json
```

AFTER, production shape (`cap 300/run`, no test limit), two consecutive runs chained:

```
shadow-drift: +276 marked this run (cap 300/run, backlog 6083; walk 300/6083 eligible, decided 2026-10-06..2026-10-08, 300 never attempted before, 0 held by the 3-fail/24h retry; trailing-7d attempted 300, resolved 276).
shadow-drift: +295 marked this run (cap 300/run, backlog 5807; walk 300/5807 eligible, decided 2026-10-03..2026-10-06, 300 never attempted before, 0 held by the 3-fail/24h retry; trailing-7d attempted 300, resolved 295).
```

## 4. Evidence against the exit criteria

**1 — the walk touches candidates decided after 2026-10-01.** Every run prints the window of what it walked: `decided 2026-10-09..2026-10-10` (cap 25), `2026-10-06..2026-10-08`, `2026-10-03..2026-10-06` (cap 300). Reconstructed per run from the ledger stamp joined to the candidates' decision dates: every attempted key in the two bounded runs was decided after 2026-10-01 (25/25 and 25/25), and all 50 were inside the trailing-7d cut.

**2 — backlog/marked move and the attempted set rotates.** Backlog 6147 → 6124 → 6101 → 6083 → 5807 (each run removes the keys it resolved), `marked` 4945 → 5028 → 5073 → 5291 → 5409 → 7296 → 8796. Rotation, two independent ways:

* complete attempted sets of two consecutive runs (new `resolve` rows in the run's wall-clock window ∪ the run's own ledger stamp):

```
run 4 (stamp 2026-10-10T07:51:36.010Z): attempted 25 = 23 resolved + 2 still failing; window 2026-10-09..2026-10-09
run 5 (stamp 2026-10-10T07:52:33.858Z): attempted 25 = 18 resolved + 7 still failing; window 2026-10-08..2026-10-09
overlap between the two consecutive runs' attempted sets: 0 (disjoint — the sets rotate)
attempted keys decided after 2026-10-01: run4 25/25, run5 25/25
```

* the two consecutive cap-300 runs' still-failing sets: `2026-10-10T07:53:42.414Z: 24 rows` vs `2026-10-10T08:01:04.214Z: 5 rows`, overlap **0**. Run 4's rows also keep their original stamp through runs 5 and 6 (they are not re-attempted while never-attempted rows exist).

**3 — cohort7dMarked.** After the cap-300 run: `cohort7dMarked: 3582`, `avgPnlPerTradeExDustLast7dCohort: -0.15` (was 0 / null). The "explicit reason" branch also exists and was exercised on the first smoke run, when the two newest candidates had not settled yet:

```
shadow-drift: +0 marked this run (cap 2/run via DRIFT_TEST_LIMIT, backlog 6147; walk 2/6147 eligible, decided 2026-10-10..2026-10-10, 2 never attempted before, 0 held by the 3-fail/24h retry; trailing-7d attempted 2, resolved 0 — trailing-7d cohort still empty: 0/2 of the attempted candidates decided inside the window resolved at the venue (the rest are still open or archived)).
```

**3b — hold-back and the slow cadence, end to end.** Exercised with a synthetic ledger fixture (every one of the 6,147 pending keys stamped `consecutiveFailures: 3`; the fixture only touches instrument state, no candidate row is edited):

* all stamps fresh (< 24 h) → nothing is walked and the run says so:

```
shadow-drift: +0 marked this run (cap 5/run via DRIFT_TEST_LIMIT, backlog 6147; walk 0/0 eligible, decided —, 0 never attempted before, 6147 held by the 3-fail/24h retry; trailing-7d attempted 0, resolved 0 — trailing-7d cohort still empty: no candidate decided inside the window was attempted this run).
```

* the same fixture with the stamps 25 h old → the held rows re-enter the walk, oldest stamp first (the most recently decided keys, since the fixture ages them in that order), and their streak advances to 4:

```
shadow-drift: +0 marked this run (cap 5/run via DRIFT_TEST_LIMIT, backlog 6147; walk 5/6147 eligible, decided 2026-10-10..2026-10-10, 0 never attempted before, 0 held by the 3-fail/24h retry; trailing-7d attempted 5, resolved 0 — trailing-7d cohort still empty: 0/5 of the attempted candidates decided inside the window resolved at the venue (the rest are still open or archived)).
```

**4 — tsc / vitest / other markers.** `npx tsc --noEmit` clean; `npx vitest run` → 35 files, 391 tests passed (was 34/383). lowconf + wallet-cap lines are byte-identical between the before and after runs at the same cap and same starting data:

```
$ diff <(grep -E "^shadow-(lowconf|wallet-cap)" before-run.log) <(grep -E "^shadow-(lowconf|wallet-cap)" after-run1.log)
(no output)
```

## 5. Marks are real (spot check, read-only)

Five of the 276 rows the cap-300 run marked, re-read from the venue:

```
nfl-tb-dal-2026-10-09-rec-jake-ferguson-3pt5 | UNDER -> marked 1 (entry $0.46) | venue 200: Under @ 1 (closed=true)
nfl-tb-dal-2026-10-09-ryd-bucky-irving-49pt5 | UNDER -> marked 0 (entry $0.30) | venue 200: Over @ 1 (closed=true)
bra-pal-bah-2026-10-08-team-total-home-0pt5 | UNDER -> marked 0 (entry $0.895) | venue 200: Over @ 1 (closed=true)
nfl-tb-dal-2026-10-09-recyd-cade-otton-49pt5 | UNDER -> marked 1 (entry $0.135) | venue 200: Under @ 1 (closed=true)
nfl-tb-dal-2026-10-09-rec-ceedee-lamb-7pt5 | UNDER -> marked 1 (entry $0.19) | venue 200: Under @ 1 (closed=true)
```

## 6. Consequences the operator must know (nothing here re-tuned anything)

* **The drift counterfactual's published numbers move, and the series has a regime break.** Because marking was frozen for weeks and the fix marks the recent cohort first, the drift read now includes rows it never marked before: `marked` 4945 → 8796, win rate 64.3% → 56.2%, `avgPnlPerTradeExDust` $0.38 → $0.14. Any before/after comparison of the *cumulative* drift number across this fix is invalid; the day-level `drift-decay-series.jsonl` row for 2026-10-10 moved from `0.38` (pre-fix code) to `0.14` (post-fix), and 2026-10-10's last row is what the consecutive-days counter reads.
* **The pre-registered 2026-09-20 decay bar now has its cohort input.** `cohort7d: -0.15` (<= $0.50) → `cohortAtOrBelow: true`, while `consecutiveDaysAtOrBelow: 5` of the required 7. The bar is NOT tripped; if the next two days stay at/below the bar it will trip by its own pre-registered rule (which brings forward a maxPriceDrift/longshotDriftPct relaxation, attributed by ruleSetVersion). That decision is the operator's — this card did not touch thresholds or rules.
* The walk consumes the never-attempted front newest-first, so a full pass over the 6,147-key backlog takes ~24-30 h of hourly runs; after that the LRU cycle re-walks the whole set about once per cycle, which keeps the trailing-7d cohort refreshed. New candidates (~2k/day) always sort first, so fresh decisions are marked immediately.

## 7. How to reproduce

```bash
cd /Users/xsnyde2/polymarket-copybot/.worktrees/t_81d0a4cb      # node_modules is a symlink to the main checkout
DATA_MODE=live MARK_LIMIT=25 DRIFT_TEST_LIMIT=25 npx tsx scripts/mark-shadow-longshot.ts
DATA_MODE=live npx tsx scripts/mark-shadow-longshot.ts          # production cap 300
```

Runs write only this worktree's `data/*` copies (live cron artifacts in the main repo were never touched; the worktree's `data/` was snapshotted and restored afterwards, so the branch diff is code-only).
