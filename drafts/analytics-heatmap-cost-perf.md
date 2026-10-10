# /analytics is the slowest page — measurement + fix

Card: `analytics-heatmap-cost` (kanban t_4a8a595b, branch `wt/analytics-heatmap-cost`).
Measured 2026-10-07 on the Mac mini, `DATA_MODE=live`, DB `prisma/dev.db` (8.85 GB,
91 MB WAL). Read-only measurement + one projection change in
`src/app/analytics/page.tsx`.

## Key insight

The page's per-row work is **not** the problem, and the "9.7k-row heatmap fetch"
is only half the story.

1. `allResolved` is 11,170 rows (not 9.7k) and it is the single biggest read
   (~55% of the page's data path) because the `include` deserialises **22.4 MB**
   of JS objects to use seven fields.
2. Total per-row compute for *every* pass on the page — heatmap, category,
   venue, rule-version, wallet maps, benchmark series — is **62 ms**. The
   heatmap's per-row `etParts()` is 13 ms. Per-row work is a rounding error.
3. The "3.4 s" figure is ~5x amplified by the *process*, not the page: the live
   launchd dashboard burns 3.3 s wall / 3.8 s CPU per `/analytics` request, while
   a freshly started process of the **identical build** does 0.56 s / 0.92 s.
   Only DB-backed pages are affected; `/reports` and `/trades` are identical.

## Method

- `/analytics` TTFB before: 2.64–3.44 s (6 samples, `curl` against :3013).
- A read-only harness (`perf-analytics-data-path.ts`) replicated the page's exact
  reads and per-row passes against the same DB and timed each one.
- A/B harness (`perf-analytics-query-shape.ts`) timed the candidate projection.
- Built the worktree (`next build`) and served it on :3113; served the live
  Oct-4 build from the main tree on :3114; ran the pre-fix build under
  `taskpolicy -b` (background QoS) on :3115/:3116 to mirror the live plist.
- `ps -o time=` deltas around N requests gave CPU/req, separating "same work,
  scheduled slower" from "genuinely more work".

## Before — page data path (fresh process, main dev.db)

    read                                        ms
    allResolved  (include decision->observedTrade)   584
    decisionCounts + reviewedDecisions + copies      335
    trackedWallets                                    37
    c200Resolved                                      21
    dailyPnlSeries                                    15
    walletStats groupBy                               10
    insiderScores                                      1
    calibration json + baseline csv                    0
    -------- queries subtotal                        993   (94%)
    per-row compute, ALL passes                       62
      of which heatmap(etParts)                       13
      of which cat/venue/version                      24
    -------- TOTAL data path                       1,055

    rows: allResolved 11,170 | c200 2,294 | reviewed 6,613 | copies 11,366
          rollup 3,592 hourly -> 164 day/bot | tracked 25 | insiders 61
          DecisionJournal 325,582

## The candidate change, A/B (median of 3, same process)

    query shape                                   ms     JSON
    include { decision { observedTrade } }       492    22.4 MB   <- before
    include + observedTrade select               293    13.4 MB
    select only the 7 fields used                133     3.3 MB   <- after
    scalars only (no joins at all)                34     1.8 MB

The join itself costs ~100 ms; ~360 ms was deserialising `reasonsJson`,
`risksJson` and `rawTradeJson` for 11k rows nobody reads.

## After — end to end (prod build, fresh process)

    /analytics      PRE  556 ms/req   920 ms CPU
                    POST 294 ms/req   582 ms CPU      (-47% wall, -37% CPU)
    /performance    PRE  241 ms       POST 238 ms     (unchanged)
    /               PRE   74 ms       POST  77 ms     (unchanged)

Under the background QoS the live plist imposes, the same fix takes
`/analytics` from 3,434 ms to 1,644 ms per request.

## The bigger finding — the live process is degraded

    /analytics, same DB, per request        wall      CPU
    LIVE :3013  (launchd, Background QoS)  3,323 ms  3,783 ms
    fresh process, PRE-fix build             556 ms    920 ms
    fresh process, POST-fix build            294 ms    582 ms
    fresh process, POST-fix, taskpolicy -b 1,644 ms  2,370 ms

    non-DB pages, LIVE vs fresh:  /reports 42 vs 40 ms;  /trades 16 vs 15 ms
    DB pages,     LIVE vs fresh:  /journal 2,088 vs 400 ms; /wallets 361 vs 100 ms

`~/Library/LaunchAgents/com.xsnyde2.copybot-dashboard.plist` sets
`ProcessType = Background`. On Apple Silicon that pins the process to background
QoS (efficiency-core scheduling, reduced memory priority), which inflates
CPU-seconds ~4x on memory-heavy DB work while leaving pure-CPU pages untouched.
The process has also been up for 3 days at 648 MB RSS with the WAL at 91 MB.

Action: remove `ProcessType Background` (or set it to `Interactive`) and
`launchctl kickstart -k gui/$UID/com.xsnyde2.copybot-dashboard`. That is worth
~5x on **every** DB-backed page — more than any remaining code change on
`/analytics`. Not done here: it edits the live ops config, not the repo.

## Correctness

- Pre-fix build vs post-fix build renders: **data-identical** — `<title>`
  tooltips, `<text>` labels, every SVG path/rect/line/circle, the DOM with
  scripts stripped, and the RSC flight payload all match after normalising
  build identity only (`cmp-renders.py`).
- `tsc -p tsconfig.json` clean; `vitest run` 379/379 pass.
- Same rows, same order; only the projected columns changed.

## Verdict

The code fix is real and safe: **556 -> 294 ms** per request on a healthy
process, verified output-identical. It is *not* what makes the dashboard show
3.4 s. Restarting the dashboard out of background QoS is the dominant lever and
needs the operator.

Still on the table (not done — out of "smallest change" scope): the decision
triple (`reviewedDecisions` + `copyDecisions`, 335 ms / 17,979 rows) and
`trackedWallets` (37 ms for 25 rows).

Harnesses: `_perf-analytics.ts`, `_perf-variants.ts` (attached to the card).
