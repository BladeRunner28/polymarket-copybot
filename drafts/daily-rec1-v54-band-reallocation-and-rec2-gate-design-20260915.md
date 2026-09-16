# Daily report recs applied (2026-09-15): v54 band reallocation · mid-price gate redesigned

**Approver:** user ("I approve") in the C-200 daily-report thread
**Source:** C-200 daily report 2026-09-15, Rec 1 + Rec 2.

---

## Rec 1 — band reallocation — **APPLIED** (RuleSet v53 → **v54**)

| | |
|---|---|
| Long-shot band (`<0.20`) | `c200LongshotBandFactor` **2.0 → 2.5** (+25%) |
| Dead zone (`0.40–0.60`) | `c200DeadZoneBandFactor` **0.25 → 0.125** (−50%) |
| Mid (`0.20–0.40`) and premium (`≥0.60`) | unchanged (×1.0 / ×0.5) |
| Revert | one field each; `DEFAULT_RULES` reproduces pre-v54 sizing exactly |

**Why these are new fields and not the existing `deadZoneSizeFactor` / `longshotSizeFactor`:**
those two are read by the **shared** scorer (`src/lib/scoring/trade.ts`) for every bot, so
flipping them would (a) resize STANDARD, which the recommendation never argued for, and (b)
double-apply on the C-200 legacy path — the v41 neutralization to 1.0 exists to stop exactly that.
The C-200-only fields feed `paper.ts mapBankroll200Size`, and the Kelly rails compare against the
same factors, so the Kelly and legacy C-200 paths move together.

**Verified with the live ruleset loaded from the DB:**

```
ruleset v54 {"longshot":2.5,"deadZone":0.125}
long-shot <0.20          pre-v54 $15.94 -> v54 $19.92   x1.250
mid 0.20-0.40 (unchanged) pre-v54 $ 7.97 -> v54 $ 7.97   x1.000
dead zone 0.40-0.60       pre-v54 $ 1.99 -> v54 $ 1.00   x0.500
premium >=0.60 (unchanged) pre-v54 $3.98 -> v54 $ 3.98   x1.000
shared v37 factors: 1 1 => STANDARD sizing untouched
```

**Window caveat:** this lands mid-Kelly-window. Every journal row now carries
`ruleSetVersion v54`, so attribute by window (`analyze-calibration.py --since`), not by the
Oct 8 total.

## Rec 2 — mid-price gate redesigned to **price + confidence** — **QUEUED, not executed**

The recommendation was to add the confidence condition *before* executing the queued dead-zone
stop; it did not ask for the gate to go live, and the standing rule is that this class of change
waits for the Oct 8 close unless explicitly overridden. The card is updated, the blunt draft is
retired, and the design is now pre-registered:

> **Block new C-200 entries with entry price in `[0.20, 0.60)` UNLESS confidence ≥ 0.80.**

**Evidence, reproduced independently** (C-200, Polymarket-only, finished, row-level):

| Cell | rows | staked | PnL | ROI |
|---|---|---|---|---|
| 0.20–0.60 × conf 0.70–0.75 | 96 | $605 | −$286.16 | −47.3% |
| 0.20–0.60 × conf 0.75–0.80 | 63 | $425 | −$156.55 | −36.8% |
| **0.20–0.60 × conf 0.70–0.80** | **159** | **$1,030** | **−$442.71** | **−43.0%** |
| **0.40–0.60 × conf ≥0.80** | **28** | **$201** | **+$129.54** | **+64.6%** |
| 0.20–0.40 × conf ≥0.80 | 3 | $60 | −$0.51 | −0.9% |
| 0.20–0.40 × conf <0.80 | 296 | $2,280 | −$215.45 | −9.4% |

The 159-row / −$442.71 cell reproduces the report exactly. Confidence is non-monotonic inside the
band (≥0.85 +83.3%, 0.80–0.85 +46.2%, 0.75–0.80 −36.8%, 0.70–0.75 −47.3%), and the ≥0.80 carve-out
is load-bearing: it preserves the **+64.6%** cell in 0.40–0.60, which a blanket band block would
have deleted. The decision-level (deduped) sample agrees in direction (−17.3% / −19.1% / +19.6%).

**Implementation at apply:** admission-path gate in `score-trades.ts` behind a new rule field,
covering the short-TTR lane and the legacy path. The Kelly main lane already skips 0.40–0.60 via
λ̂=+0.03 but **not** 0.20–0.40, so the gate must sit in the shared admission path, not in Kelly.

**Not touched, deliberately:** the ≤0.20 tier-1 adverse exit (its 7-day counterfactual reads
Sep 20 — pre-commit, don't change it on 19 rows), new hour gates/sizing (17–27 rows — shadow
first), and any phase-target raise.

## Files

`src/lib/rules.ts` (2 fields + defaults) · `src/lib/paper.ts` (`mapBankroll200Size` factors +
`openPaperTrade` param) · `scripts/score-trades.ts` (passes the factors on both the booking and
the Kelly-rail paths) · `scripts/apply-v54.ts` · `tests/paper-sizing.test.ts` (+4 tests).
tsc clean · 171/171 tests green.
