# v47 — 2026-09-03 Daily Report Recommendations (user-approved)

Source: copybot-c200-daily-report (job 84e37616f39a, 2026-09-03 18:02 CDT, N=1,131 calibration) →
user: "I approve of the recommendations".

## Rec 1 — Gate 20:00/23:00 ET drain hours: **ALREADY LIVE** (v41, both books v44)
Hard blackout since Aug 31; C-200 entries in those hours: 30/week pre-gate → 0 since.
Skips are shadow-logged (`[BOT] hour blackout …`). Re-run analyze-calibration.py after 7 days
per the report — the post-gate refits will show the drain rows shrinking.

## Rec 2 — Reshape band eligibility toward the edges
- **(a) dead zone 0.40–0.60**: already at **×0.5** cap cut (v42 — deeper than the proposed
  ~25%/confidence+0.10). No change.
- **(b) hard-cap new entries ≤0.80** → **IMPLEMENTED** — `c200MaxEntryPrice: 0.8`
  (**RuleSet v47**, changedBy `hermes-v47-daily-report`, audit row written). Per-leg
  BANKROLL_200 gate in score-trades.ts (main + short-TTR lane), mirroring the v44 STANDARD
  pattern. NOT via the shared `maxEntryPrice` (symmetric [1−max, max] — 0.80 would block
  <0.20 long-shots, the z=+4.05 +$143.82 band). Active: C-200 ≤0.80, STANDARD ≤0.85.
- **(c) <0.20 long-shots at full cap**: already at **×1.5 → $20 clamp** (v41). No change.

## Watch item — Aug 25–27 zero finished trades
Confirmed as the **known Aug 17–28 sidecar-outage tail**: zero C-200 rows Aug 24–27, with the
exact silent-skip footprint in logs/cron/copybot-monitor-score.log under rules v25
(`[BANKROLL_200] Skipped execution: Rust Execution Engine offline or failed: TypeError: fetch
failed`). No sidecar archive logs exist for that window (launcher added Aug 29). Fixed since by
the watchdog + launchd supervision; the separate Aug 31–Sep 3 silent-401 void was fixed today
(sidecar launcher env, see drafts/tuning-review-14-execution-fix.md).

## Verification
93/93 tests · tsc clean · RuleSet v47 active (c200MaxEntryPrice 0.8) + RuleChange audit row.
Sibling v45/v46 rules (blacklists, exposure base) untouched.

## Rollback
Deactivate v47 → reactivate v46 (cap falls back to DEFAULT 0.8 — set 0 to disable per-leg).
