**Kelly Window Report — 2026-10-13** (regime day 38 — FINAL READ)
Rules v62: kellyEnabled=1 fraction=0.5 maxBankrollPct=10% maxSizeUsd=$100 minBet=$2 minEdge=2%

**State:** cash $7450 | open $148 | net worth $7595 | realized $5698 | exposure 148/$3847 | drawdown 6.2%

**Last 24h:** 21 Kelly-regime copies opened (3 main-lane, 18 lane) | realized $-0.61 | $181 booked
[KELLY] decisions in log: 562 (152 sized, 410 skipped). Top skip reasons: no edge: q=0.556 ≤ price=0.585 (20); no edge: q=0.381 ≤ price=0.410 (19); no edge: q=0.436 ≤ price=0.465 (16)

**Window (since v49, main-lane Kelly):**
| band | n | avg size | max | realized | open |
|---|---|---|---|---|---|
| <0.20 | 53 | $81 | $100 | $3615 (53 res) | $0 open |
| 0.20-0.40 | 67 | $26 | $100 | $-36 (65 res) | $27 open |
| 0.40-0.60 | 0 | $0 | $0 | $0 (0 res) | $0 open |
| 0.60-0.80 | 0 | $0 | $0 | $0 (0 res) | $0 open |
| >=0.80 | 0 | $0 | $0 | $0 (0 res) | $0 open |

**Lane (short-TTR, Kelly-exempt):** 1025 copies, realized $1978
**Target check:** mid/high-band main-lane copies 0/120 → ≈0 ✓ (zero-edge skips holding)


**FINAL — pre-Kelly baseline (all resolved, journal v<49):**
| band | n | realized |
|---|---|---|
| <0.20 | 77 | $465 |
| 0.20-0.40 | 236 | $80 |
| 0.40-0.60 | 585 | $-366 |
| 0.60-0.80 | 231 | $-41 |
| >=0.80 | 161 | $2 |
Baseline total realized $140 | Kelly-window main-lane realized $3580
Long-shot (<0.20) realized: baseline $465 → window $3615 (7.8x)
**Verdict fields (pre-registered §6):** concentration ✓/✗ above | mid-band ≈0 ✓/✗ above | drawdown 6.2% vs 20% gate ✓
CAVEAT (design §6): λ̂ is a premium measure, not PnL — check band λ̂ vs realized alignment at the Sep 15 refit; mid-band skip is by zero-edge rule, not calibration sight.

**Band λ̂ alignment check (§6, live λ̂ from monitor-score log, 562 [KELLY] lines):**
- <0.20: λ̂ −0.815 (49 dec) → size ✓ | realized +$3615
- 0.20–0.40: λ̂ −0.198 (104) → size ✓ | realized −$36 (n=67)
- 0.40–0.60: λ̂ +0.063 (242) → skip all ✓ — no negative flip at Sep-15 refit
- 0.60–0.80: λ̂ +0.219 (82) → skip ✓
- ≥0.80: λ̂ +0.327 (85) → skip ✓

**Verdict:** concentration <0.40 ✓ (120/120) | mid-band ≈0 ✓ (0/120) | long-shot share 7.8×
baseline — pre-registered 3–6× → ABOVE target band | drawdown 6.2% vs 20% gate ✓
Per-copy long-shot: baseline $6.04 → window $68.21 (11.3×), inflated by cap $20→$100 + variance.
No ⚠ flags; exposure cap not binding (3.8%).

**Recommendation (recommendations only, no change without approval):** continue Kelly. Mid-band
starvation is rule-driven and holding; sole deviation is long-shot concentration overshoot —
option to trim kellyMaxSizeUsd $100→$60, or accept and watch <0.20 per-copy edge at larger size.
Re-run the λ̂ alignment at the next scheduled refit.

---

**DECISION — 2026-10-13, user-approved in-thread.** Kelly CONTINUES; the cap trim `kellyMaxSizeUsd`
$100→$60 is **DECLINED**. No RuleSet version created — active set stays **v62** (verified:
active RuleSet v62 · kellyEnabled=1 · fraction 0.5 · maxSizeUsd $100 · maxBankrollPct 10%; exactly
1 active set).

Measured cost of the declined trim (read-only first-order-exact replay — paper has no
size-dependent slippage and PnL is linear in size, so each resolved main-lane copy is rescaled by
min(60,s)/s; population = 118 resolved main-lane copies under journal v≥49):

| cap | main-lane realized | <0.20 | 0.20–0.40 |
|---|---|---|---|
| $100 (actual) | $3,580 | $3,615 | −$36 |
| $60 (declined) | $2,095 | $2,112 | −$17 |

→ the trim would have removed **$1,485 (−41%)** of the window's profit to improve the
loss-making band by **$19**. 45 of 118 positions sat above $60 and were repriced (39 long-shot,
6 in 0.20–0.40).

Watch item carried to the Oct 15 λ̂ refit (fires 06:00, biweekly 1st/15th): does the <0.20
per-copy edge survive at cap $100 (window $68.21/copy vs pre-Kelly $6.04, n=53)? A decay there is
the one live falsifier of this decision, and its lever is the sizer (λ̂ / kellyFraction), not a cap
trim.

Recorded on roadmap cards `kelly-cap-trim-oct13-decision` (Done) and
`kelly-oct15-lambda-refit-capture` (Scheduled).

