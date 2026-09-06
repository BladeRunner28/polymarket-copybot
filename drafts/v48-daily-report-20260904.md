# v48 — 2026-09-04 Daily Report Recommendations (user-approved: "Both approved")

Source: copybot-c200-daily-report (job 84e37616f39a, 2026-09-04 18:00 CDT, N=1,167 → venue-filtered N=1,094).

## Rec 1 — Band-aware admission for the <0.20 long-shot lane (IMPLEMENTED)
- New rule fields (**RuleSet v48**, changedBy `hermes-v48-daily-report`, audit row written):
  `longshotMinCopyScore: 70` · `longshotMinConfidence: 0.55` (0 disables per-field).
- `src/lib/scoring/trade.ts`: when entry price < `longshotMaxPrice` (0.20), the copy/confidence
  floors relax to the band values; every other gate (spread, liquidity, drift, wallet score,
  v47 ≤0.80 cap) stays global. Admits carry an audit reason: "Long-shot band (<$20¢): admitted
  on relaxed floor 70 (score 77 vs global 80)".
- Rationale: <0.20 is the only +PnL band (z=+3.81, +$94.59 on 64 trades, +22.6pp excess) yet its
  historical flow is median score 72 / conf 0.57 — the 80/0.7 bars admitted 3/64. Win-rate-derived
  bars structurally anti-select long-shots (low win rate is why they're priced at ~12¢).
- Verified live: ws=80 @0.12 → score 76.6 / conf 0.57 → **paper_copy** (floors disabled → skip;
  0.30 entry → skip — relaxation doesn't leak). Regression test added.
- Measure 7–10 days → re-run analyze-calibration.py → re-tighten if the edge doesn't survive.

## Rec 2 — Hour gating corrected for the Kalshi artifact (IMPLEMENTED)
- `hour-policy.ts`: **23:00 ET removed from the blackout** (`C200_BLACKOUT_HOURS_ET = {20}`) —
  venue separation showed 85% of 23:00's "drain" was phantom-priced Kalshi rows (−$80.91 on 9
  rows); PM-only 23:00 is noise. **20:00 ET stays blacked out** (real PM drain: −$80.43 on 31
  trades, z=−2.99). 21:00 ET untouched (z=+2.80 best evening hour). Both books affected
  (STANDARD inherited the same set).
- `scripts/analyze-calibration.py`: **venue != 'Kalshi'** filter added — N drops 1,167 → 1,094;
  hour/band stats now Kalshi-clean (ALL PnL −$321 → −$231.91 without the phantom rows).
- Watch item armed: 10:00 ET (PM-only −$229, z=−1.68, p≈0.09) — the hour-policy gate pattern is
  a one-line addition when it crosses significance.

## Verification
95/95 tests (new regression: band admission works, doesn't leak outside <0.20, floors-disabled
skips) · tsc clean · RuleSet v48 active + audit row · analyze-calibration live-verified
venue-filtered.

## Still open (backlog, NOT part of this approval)
- **kalshi-reprice-92**: the one-off re-price of the 92 legacy Kalshi rows (TR-16 resolver
  available). Until it lands: Kalshi excluded from C-200 reporting, Kalshi routing stays paused,
  23:00 ET re-test pending honest data.
