# v52 — TR-20: auto-tune revert + Kelly-window suppression + rule-updater resolved+closed (approved 2026-09-09)

User approved the tuning-review #20 package; via clarify chose (rec 2)
**"Revert to v50 + suppress auto-tuner until Oct 8"**. Rec 1 (sweep coalesce
A/B/C) timed out at clarify — status quo held, decision still open.

## What shipped

### 1. RuleSet v52 — revert of the v51 AUTO-TUNE (`scripts/apply-v52.ts`, changedBy `hermes-v52-tr20-approved`)
The EOD auto-tuner fired 22:02 CDT Sep 8 (day 1 of the Kelly window) once the
48h manual lockout after v50 expired: maxPriceDrift 0.004→0.003, minLiquidity
750→1125, changedBy `hermes` (no approval marker), on RESOLVED-ONLY evidence.
That violated the standing approved holds (#16–#20: thresholds unchanged
through Oct 8). **v52 restores the pre-registered v50 baseline** (drift 0.004,
minLiq 750). Verified: active v52, audit row present.

### 2. Auto-tune suppression through the window (`src/lib/rule-updater.ts`)
`KELLY_WINDOW_SUPPRESS_UNTIL = 2026-10-09T05:00Z` (end of Oct 8 CDT) — absolute
gate at the top of `runRuleUpdate()`: logs "auto rule update SKIPPED: Kelly
window freeze" and returns null. The 48h manual lockout alone couldn't hold the
freeze (v51 proved it); this makes the freeze real on the auto axis too.
Scheduled λ̂ refits (Sep 15/Oct 1) are separate and unaffected. Smoke-tested
live: runRuleUpdate returns null, no changes.

### 3. rule-updater.ts resolved-only → resolved+closed (defect fix, rec 2 second half)
Both analysis queries (`collectSamples` + the wallet-downgrade groupBy) read
`status: "resolved"` only — same bug class as report.ts (fixed earlier in v52):
realized PnL books at closedAt for early exits, so the auto-tuner's evidence
(and wallet downgrades) understated closed trades. Now `[resolved, closed]`.
This also means any post-Oct-8 auto-tune runs on the honest sample.

### Rec 1 (residual sweep leak) — STATUS QUO, decision open
The 24-min-cadence sweep (0x85f0 on ucl-liv NO, 70 STANDARD opens = $1,260 of
one economic intent) beats the 15m v52 coalesce. Clarify timed out → per
workflow, kept the strong state (v52 15m coalesce live, no further change).
Options still on the table: A) coalesce into the OPEN copy (one position per
wallet/market/outcome while open — cadence-agnostic), B) widen 15m→2h, C) no
change. Verify for A/B: 0 same-key opens >1 (baseline 70).

### Rec 3 (watch) — armed
Kelly main-lane <30 admits by Oct 1 → flow review before the Oct 8 read. No
threshold change. (Current: 0 [KELLY] lines, all C-200 opens short-TTR lane.)

## Verification
tsc clean · vitest green · v52 active with drift 0.004/minLiq 750 · suppression
guard smoke-tested (returns null, SKIPPED log) · commit `…` (git log).
