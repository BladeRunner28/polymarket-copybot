# v54 — 2026-09-11 C-200 daily report: long-shot shadow ladder (shipped) + dead-zone admission stop (queued to Oct 8)

User approved both changes. Change 1 is freeze-allowed instrumentation (shipped);
Change 2 carries the report's own window-contamination caveat and is queued to
the Oct 8 Kelly-window close by default (apply-now on explicit override).

## Change 1 — long-shot shadow ladder (SHIPPED, freeze-allowed)

**Thesis (report):** the proven <0.20 bucket is STARVED, not scarce — since v49
2,296 distinct sub-0.20 candidates were scored, 61 copied (2.7%, ≈9/day)
against ~400 in-band candidates/day; blockers: drift 74%, confidence floor 79%,
sub-0.05 near-certainty 53%, liquidity 40%, spread 21%. All live thresholds are
frozen for the Kelly window, so this MEASURES instead of changing.

**Shipped:**
- `src/lib/shadow-longshot.ts` — relaxed ladder (drift ≤ 0.01, spread ≤ 0.08,
  confidence ≥ 0.50, price [0.05, 0.20)), $20 fixed shadow stake; every sub-0.20
  candidate logged with its full feature vector (raw features stored, so the
  ladder can be re-cut retroactively without re-instrumenting).
- `scripts/score-trades.ts` — appends every sub-0.20 candidate to
  `data/longshot-shadow.jsonl` (never fatal; run counter in the completion line).
- `scripts/mark-shadow-longshot.ts` (`npm run shadow:mark`) — resolves
  would-admit rows via the adapter + parent-event fallback and writes
  `data/longshot-shadow-summary.json` (N, resolved, win rate, PnL, $/trade).
- Cron `copybot-shadow-longshot-mark` (job 0c8c6fedea9f, hourly :25, no_agent,
  deliver local) via wrapper `~/.hermes/scripts/copybot-shadow-longshot-mark.sh`.
- **Log plumbing fix (review #22 rec 2, required for visibility):** the
  monitor-score wrapper piped `score:trades` through `tail -6`, hiding
  `[RISK-GATE]`/`[KELLY]`/`[DRAWDOWN-SHADOW]`/`[SHADOW]` lines — `tail -6`
  removed for score:trades in `~/.hermes/scripts/copybot-monitor-score.sh`.

**Verified:** ladder logic unit-checked in-memory (admit/block cases + summary
math), marker runs end-to-end and writes the summary, tsc clean, 128/128 tests.
Book is empty by design — it fills as in-band candidates flow (the current
unscored backlog is dominated by sweep fills, which are coalesced before
scoring — correct: the shadow book holds one row per independent candidate).

**Decision point: Sep 22 (7 shadow days) or Oct 8.** If the edge survives
(all-time +$2.79/trade, last 7d +$5.90/trade), a 3–4× lift to ~30 admits/day is
worth ≈ +$90–180/day.

## Change 2 — dead-zone (0.40–0.60) admission stop (APPROVED, queued)

0.40–0.60 = 46% of all staked capital ($3,713) at −13.7% lifetime, −30.0% ROI
last 7d; v51's ×0.25 cut shrank the absolute loss, not the bleed rate (capital
is not stuck — avg open age 17.6h, recycler frees it hourly — the bot re-enters
~18×/day at 99% cap utilization), so each dead-zone admit displaces long-shot
stake (~$76/day redirected). Fix is admission-only (copyScore ≥ 90 in the band,
or zero admits) and must cover the short-TTR LANE + legacy paths (Kelly
main-lane already skips the band).

**Queued by default** because applying now contaminates the pre-registered
Sep 8–Oct 8 window read (the report's own caveat). Roadmap card
`v54-deadzone-admission` carries the evidence, fix design, and verify line.
Apply on explicit override ("apply dead-zone gate now") with the contamination
documented, or at the Oct 8 close alongside the shadow-ladder evidence.

## Notes
- Wrapper scripts live in `~/.hermes/scripts/` (outside the repo) — this doc is
  their record (monitor-score tail fix + new marker wrapper).
- Review #22's other recs (journal coalesced fills + partial unique index on
  open positions; WAL + busy_timeout; Sep 15 band-bar pre-registration) remain
  PENDING — rec 1 is the material one: 5 duplicate open-pairs slipped past the
  v52 option-A guard because coalesced fills write no journal row (they stay
  "unscored" forever). Flagged for approval.
