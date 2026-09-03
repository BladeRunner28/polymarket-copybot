# v42 Change-set — 2026-09-01 Daily Report Recommendations (user-approved 2026-09-02)

Source: copybot-c200-daily-report (job 84e37616f39a, 2026-09-01 18:02 CDT, N=1,124 calibration) →
user: "Make all recommendations, including the capacity recommendation. Also, extend the deadline
from October 1st to December 1st."

## 1. Dead-zone sizing deepened ×0.75 → ×0.50 (Rec 1)
- `src/lib/paper.ts` `mapBankroll200Size`: 0.40–0.60 band now ×0.50 (was ×0.75, v41).
- Rationale: 0.40–0.60 = 48% of volume (538/1,124), **−$271.70 = 99.9% of total drag** (z=−1.56 n.s.
  but dollar-concentrated). Effective: $18 parent @ 0.50 entry → $9.00 (was $13.50).
- Code change (not a ruleset field); labeled v42. Tests updated (`tests/paper-sizing.test.ts`).

## 2. maxSpread tightened → 0.06 (Rec 2)
- Protects the 0.20–0.40 band: significant positive price edge (z=+2.62, p=0.009) yet dollar-negative
  (−$105.69) — sign-flip consistent with spread costs eroding the edge.
- **RuleSet v43** (`scripts/apply-v43.ts`, changedBy `hermes-v42-daily-report`): maxSpread 0.064 → 0.06.
  (Note: active value was 0.064, not 0.08 — the auto rule-updater had tightened it at EOD 09-01 22:02.)

## 3. Capacity rec — drift loosened → 0.004
- Signal flow (drift) is the binding constraint on C-200 throughput (0 cap-skips, ~$1.4k idle cash).
- **RuleSet v43**: maxPriceDrift 0.0025 → 0.004 — **supersedes the RuleSet v42 auto-updater tighten**
  (EOD 2026-09-01 22:02: drift 0.0034→0.0025, maxSpread→0.064, minLiquidity→750; minLiquidity 750 kept).
  ⚠ The auto rule-updater (EOD update:rules) may tighten drift again if late-entry trades keep losing —
  that's by design (paper-only); manual approvals override per-run.
- RuleSet v43 active: maxSpread 0.06 · maxPriceDrift 0.004 · minLiquidity 750 · maxCategoryPositions 40 ·
  maxDrawdownPct 0.20. RuleChange audit row written.

## 4. Deadline extended Oct 1 → **Dec 1, 2026**
- `src/app/page.tsx` + `src/app/analytics/page.tsx`: "Oct 1st/Oct 1" → "Dec 1st/Dec 1" (projection horizon
  2026-10-01 → 2026-12-01). Dashboard rebuilt + relaunched (launchctl kickstart -k), verified serving.
- copybot-c200-daily-report cron prompt: "Path to $5k/day by Oct 1st" / "October 1st goal" → Dec 1st /
  December 1st (cronjob update, job 84e37616f39a).
- Memory/profile goal updated to Dec 1, 2026. query_bankroll.js phase logic date-free (unchanged).
- No roadmap.json deadline references existed (kanban carries features, not the milestone).

## Verification
- 93/93 tests · `tsc --noEmit` clean · RuleSet v43 active + audit row · dashboard :3013 serves "Dec 1st"
  (HTTP 200 on / and /analytics).

## Rollback
- Rules: reactivate v42 (or v41). Sizing: revert 0.40–0.60 to ×0.75 in paper.ts. Deadline: revert the
  three UI/prompt spots to Oct 1.
