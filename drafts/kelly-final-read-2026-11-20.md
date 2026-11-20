# Kelly Window — FINAL READ (2026-11-20, regime day 75)

Window Sep 8 → Oct 8; this read is 42 days past the scheduled close (late final).
Rules v73: kellyEnabled=1, fraction 0.5, maxBankrollPct 10%, maxSizeUsd $100,
minBet $2, minEdge 2%.

## State
cash $6,926 · open $98 · net worth $7,028 · realized $5,124 · exposure
$98/$3,564 headroom · drawdown 12.1% (realized basis, peak $7,987 vs NW $7,024).

Last 24h: 5 copies opened (1 main-lane, 4 short-TTR lane) · $68 booked ·
realized $0.00 on those (0 settled); $6.05 realized from 3 trades settled in
the last 24h. [KELLY] log: 3,675 decisions, 303 sized / 3,372 skipped — top
skips are pure zero-edge (q ≤ p by 2–3¢).

## Window, main-lane Kelly (since v49)
| band | n | avg size | realized | open |
|---|---|---|---|---|
| <0.20 | 97 | $87 | $2,685 | $0 |
| 0.20–0.40 | 131 | $22 | $5 | $18 |
| 0.40–0.60 | 0 | — | $0 | $0 |
| 0.60–0.80 | 23 | $19 | $13 | $0 |
| ≥0.80 | 16 | $94 | $116 | $0 |

Totals: 267 copies, realized $2,819 (+one rounding $2,820 in collector).
Short-TTR lane (Kelly-exempt): 1,324 copies, realized $2,170.
Pre-Kelly baseline (journal v<49, all resolved): $134 on 1,290 copies
(<0.20 +$465 · 0.20–0.40 +$69 · 0.40–0.60 −$355 · 0.60–0.80 −$47 · ≥0.80 +$2).

## Verdict vs §6 pre-registration
| check | pre-registered | actual | verdict |
|---|---|---|---|
| mid-band 0.40–0.60 (λ̂ +0.03) | skip, ≈0 trades | 0 copies, $0 | ✓ aligned-by-skip (pre-Kelly −$355 avoided) |
| 0.60–0.80 (λ̂ +0.21) | skip, ≈0 | 23 copies, +$13 | ✗ small leakage, immaterial |
| ≥0.80 (λ̂ +0.37) | skip, ≈0 | 16 copies, +$116 | ✗ mild misalignment, positive, small n |
| <0.20 (λ̂ −0.91) | size, cap-bound | 97 copies, avg $87/max $100, +$2,685 | ✓ sign-aligned; **absolute target ✗** |
| 0.20–0.40 (λ̂ −0.21) | size | 131 copies, +$5 | **UNRESOLVED** — flipped sign vs λ̂ at n=77 is noise-level; not a loss, not evidence |
| book concentration <0.40 | concentrate | 228/267 (85.4%) | ✓ (collector printed ✗ — polarity bug in the verdict field) |
| mid/high count ≈0 | 39 in 0.60+ | +$129 combined | ✗ above expected, immaterial in $ |
| long-shot **absolute** ≥ $2,500/30d | re-baselined 2026-10-21 | trailing 30d by settle: **−$1,042 on n=39**, short $3,542 | **✗ FAIL** |
| drawdown | ≤ pre-Kelly baseline / 20% gate | 12.1% | ✓ |

Notes: the retired 3–6× ratio target is not used (inflated by a $140 pre-Kelly
denominator; false FAIL at 8.0×). The 30d-by-open-date cohort (39/39 settled)
is −$1,042 — a different cohort, not the 30-day PnL rate. All-time in regime
<0.20 stands at +$2,685 on n=97, so the band is positive over the window and
negative over the trailing month: the edge is not gone on window data, but the
most recent month contradicts the absolute target.
CAVEAT (design §6): λ̂ is a premium measure, not PnL; mid-band skip is by the
zero-edge rule, not calibration sight — band λ̂ vs realized must be rechecked at
the Sep 15 refit.

## Recommendation (recommendations only — no rule change made)
**Continue Kelly enabled at fraction 0.5, hold caps ($100/$10%).** Structural
predictions held: zero-edge starvation of the mid-band (0 copies), 85%
concentration in <0.40, drawdown 12.1% well inside the 20% gate, and +$2,819
window realized vs a +$134 pre-Kelly baseline. The single failing test is the
absolute long-shot target (trailing 30d −$1,042 vs $2,500). Do **not** scale
caps on this read. Proposed follow-ups (needs Xman approval): (a) attribute the
<0.20 30d loss by market cohort (sports vs politics, hour bucket) to test whether
it is regime drift or λ̂ staleness; (b) re-run the long-shot absolute target on
the next 30d with the same pre-registered threshold before any kellyFraction
change; (c) optional RuleSet proposal to trim kellyMaxSizeUsd $100→$60 if (a)
shows loss concentrated in the cap-bound $87–100 cohort. Fallback remains
kellyEnabled→0 (legacy sizing intact).
