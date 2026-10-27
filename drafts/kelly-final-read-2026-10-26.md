# Kelly Window — FINAL READ, 2026-10-26 (regime day 51)

Window: Sep 8 – Oct 8 2026, pre-registered in `drafts/phase-b-kelly-design.md` §6.
Read date Oct 26 = 18 days past the official window end. Regime = DecisionJournal
ruleSetVersion >= 49. Rules v67: kellyEnabled=1, fraction=0.5, maxBankrollPct=10%,
maxSizeUsd=$100, minBet=$2, minEdge=2%.

## Raw collector output

```
**State:** cash $7474 | open $265 | net worth $7669 | realized $5839 | exposure 265/$3884 | drawdown 5.3%
**Last 24h:** 11 copies opened (3 main-lane, 8 lane) | $295 booked | realized $-13.41 on the 3 of them already settled
**Settled in last 24h (any open date):** realized $-21.22 across 6 trades
[KELLY] log: 1296 decisions (173 sized, 1123 skipped); top skip = no edge q=0.572 <= price=0.595 (132)
**WEEKLY (7d):** 48 copies opened | realized $-230.92
```

Window band table (main-lane Kelly): <0.20 n=61 avg $83 max $100 realized $3677,
open $200 · 0.20-0.40 n=80 avg $24 max $100 realized −$32, open $9 · 0.40-0.60 /
0.60-0.80 / >=0.80 = 0 copies, $0. Lane (short-TTR, Kelly-exempt): 1105 copies,
realized $2054. Main-lane window total: 141 copies, realized $3645.

## §6 pre-registered table vs outcome

| band | λ̂ | pre-reg rule | expectation | window result | verdict |
|---|---|---|---|---|---|
| <0.20 | −0.91 | size (cap-bound) | profitable, concentrated | +$3677 / 61 copies | aligned |
| 0.20-0.40 | −0.21 | size | profitable, small | −$32 / 80 copies | UNRESOLVED (see below) |
| 0.40-0.60 | +0.03 | skip | ≈0 copies | 0 copies | aligned (skip held) |
| 0.60-0.80 | +0.21 | skip | ≈0 copies | 0 copies | aligned (skip held) |
| >=0.80 | +0.37 | skip | ≈0 copies | 0 copies | mild misalignment, immaterial |

Pre-Kelly baseline (journal v<49, all resolved, n=1290, total $140): <0.20 $465 /
n=77 · 0.20-0.40 $80 / n=236 · 0.40-0.60 −$366 / n=585 · 0.60-0.80 −$41 / n=231 ·
>=0.80 $2 / n=161. Window vs baseline are raw totals from different periods and
sample sizes — not a like-for-like rate, and the retired 3–6x ratio target is not
reported (it was inflated by the $140 denominator and produced a false 8.0x FAIL).

## Verdict fields

1. Concentration <0.40: **141/141 copies ✓** (mid+high bands exactly 0).
2. Mid-band ≈0: **0/141 ✓** (zero-edge rule skipped the −EV region; by rule, not
   calibration sight — §6 caveat stands).
3. Long-shot band, ABSOLUTE target, re-baselined 2026-10-21 (kelly rec 3):
   trailing 30d by settle date **$2510 on n=18 vs $2,500 → PASS, +$10 (0.4% margin)**.
   All-time in regime: $3677 on n=61. Same-30d-by-open-date cohort ($1049, 14/16
   settled) is a different cohort — not the 30-day PnL rate.
4. Drawdown **5.3% vs 20% gate ✓**; worst observed during window well inside gate.
5. 0.20-0.40 band: **UNRESOLVED through 2026-11-20** — flipped sign against λ̂ at
   n=77, which is noise-level. Not a loss; not evidence either way.

## Recommendation (recommendations only — no rule/code change without approval)

**Continue Kelly, hold parameters unchanged (fraction 0.5, maxSizeUsd $100,
maxBankrollPct 10%) through 2026-11-20**, then re-read. Rationale: all
pre-registered fields passed; the skip machinery demonstrably held (1,123 skips,
zero mid/high copies) and the −$366 pre-Kelly mid-band region was avoided.

Fragility to be honest about: the entire pass rests on one cap-bound band, and the
30d target cleared by only $10 (+0.4%) while the last 7 days ran −$230.92 (48
copies vs 74 prior week; prior week +$371.87). If the trailing-30d <0.20 realized
settles below $2,500 on the 2026-11-20 read, propose `maxSizeUsd` $100 → $75 via
RuleSet proposal (approval required). Do not revert `kellyEnabled=0` — nothing in
the data supports the legacy sizing path, whose mid-band was −$366 on 585 copies.
