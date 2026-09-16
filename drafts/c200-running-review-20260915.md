# C-200 Running Review — 2026-09-15 (18:05 CDT)

Source: `node query_bankroll.js` + `python3 scripts/analyze-calibration.py` (regenerated 2026-09-15T23:00:17Z) +
Prisma probes on `prisma/dev.db`. Bot: BANKROLL_200. All figures paper.

## 1. Verdict up front

The bot is not behind because the signal is weak — it is behind because **the goal and the
capital don't match**. Phase 1 asks for $500/day on a $1,900 principal (26%/day). The
book's own ceiling today is ≈$258/day even at its best observed lane ROI. Second-order,
the realized hole is exit-side and admission-mix, not entry-quality: the ≤0.20 entry band
is the only statistically significant *positive* band in the book.

## 2. Book state

| Item | Value |
| --- | --- |
| Cash | $365.12 |
| Open book (74 rows) | $1,236 cost / $2,409 mark |
| Open unrealized | +$1,173.15 (18 rows ≥0.95 = $915 of it) |
| Net worth (cash+mark) | $2,774.26 (+46.0% vs $1,900 principal, mtm) |
| Realized today / 7d / 14d / 30d | -$142.12 / -$218.10 / -$200.65 / -$80.89 |
| Staked 7d / 14d / 30d | $2,597 / $4,931 / $7,555 |
| ROI 7d / 14d / 30d | -8.4% / -4.1% / -1.1% |
| Median hold | 24.6h (p25 23.9, p75 29.4) |

Exit split, 14d: **early exits 308 rows, -$487.22 on $3,386 (-14.4%)** vs **natural
resolutions 227 rows, +$286.57 on $1,545 (+18.5%)**. The book pays when it is allowed to
resolve and bleeds when it is cut.

Post-v53 only (2026-09-13 09:34Z → now, 2.5 days): 94 closes, **-$347.75 on $1,090
(-31.9%)**; 41 of 46 early exits fired on ≤-15% moves for -$330.04. Concentration: the
`price <0.20 × confidence <0.70` cell is 19 rows / $643 staked / **-$403.08** — 93% of the
post-v53 hole. All-time that same cell is ≈-1.5% on $1,991, so this is a 19-row drawdown
in a high-variance cell, not a broken rule.

## 3. Phase gate

- `Phase stability: 0/7` at $500/day. No day ≥ $500 in the last 21 days; best days were
  +$276.93 (Sep 7) and +$272.80 (Sep 12).
- Gate arithmetic for the Dec 1 target: 4 phases × 7 consecutive days = 28 days of clean
  ladder, so the **$5k streak must run Nov 25 → Dec 1**, $2k Nov 18–24, $1k Nov 11–17,
  $500 Nov 4–10. The first $500/day day must land **Nov 4 = 50 days from today**, with zero
  slack for a reset.
- Exposure cap: `$1,000 + 50% × max(0, $2,774 − $1,900)` = **$1,437**, with $1,236 open →
  $201 free. At a ~1.03-day median hold that is a **≈$1.4k/day turnover ceiling → ≈$258/day
  at the best observed lane ROI (+18.5%)**, about half of Phase 1.
- Notional needed for $500/day at 1 turnover/day: $10k at +5% ROI, $5k at +10%, $2.7k at
  +18.5% (best lane). For $5k/day: $100k / $50k / $27k respectively. At the 30d blended
  ROI (-1.1%) neither target is reachable at any size.
- Grow-into-it path: at +18.5% on the full cap the equity grows ~$266/day, so the cap
  reaches $10k in ~64 days — inside Dec 1 only in the no-drawdown best case.
- **Watch:** drawdown = 18.63% vs the 20% gate (peak $3,409.47 mtm, ratcheted today
  17:09Z). Trip level $2,727.58, **headroom $46.68**. One bad mark day freezes new entries
  and resets the streak. The query script does not print this line.

## 4. Calibration significance (fresh run, 2026-09-15T23:00:17Z)

Row-level, all-time, N=1,567, `deduped: false` (duplicate accumulation rows included → z
inflated; the decision-level file `data/calibration-analysis-deduped.json` is the
conservative read).

Bands, |z| ≥ 2:

| Band | Excess | z | Realized |
| --- | --- | --- | --- |
| 0.00–0.20 | +0.1861 | +4.56 | +$101.43 |
| 0.20–0.40 | +0.0712 | +2.53 | -$225.02 |
| 0.60–0.80 | -0.0775 | -2.86 | -$35.94 |
| 0.80–1.01 | -0.0664 | -2.14 | +$0.12 |

Decision-level (Sep 13, 1,473 rows → 785 decisions): <0.20 z=+2.99, 0.20–0.40 z=+2.12,
0.40–0.60 z=-2.87, 0.60–0.80 z=-2.16 — the same four bands survive; 0.40–0.60 goes
significant-negative at decision level.

Hours ET, |z| ≥ 2: 06:00 +0.2747 z=+3.43 (+$424.26), 09:00 +0.1531 z=+2.58 (-$28.90),
22:00 +0.1514 z=+2.10 (+$309.35) — all **open and unsized**; 08:00 -0.1812 z=-2.26
(-$71.12) and 20:00 -0.2365 z=-2.82 (-$80.43) — **both already gated** (08:00 = C-200-only
blackout applied Sep 13; 20:00 = shared v44 blackout; 23:00 un-gated in v48, z=-0.49,
not significant). Verified: 0 entries opened in 08:00/20:00 ET since v53.

Prior-gate check on the 0.80–1.01 band: already capped by `c200MaxEntryPrice = 0.80` (v47),
and 14d entries ≥0.80 were +6.7% on $160 — the significant drag is historical, no action.
0.60–0.80 is the queued "premium-band gate (approved in principle, Oct 8)"; this run
re-confirms it (row z=-2.86 / decision z=-2.16).

## 5. Cross-cut the calibration does not print (price × confidence, all-time)

| Cell | n | Staked | PnL | ROI |
| --- | --- | --- | --- | --- |
| 0.20–0.60 × conf 0.70–0.80 | 159 | $1,030 | -$442.71 | **-43.0%** |
| 0.40–0.60 × conf 0.60–0.70 | 192 | $1,078 | +$25.96 | +2.4% |
| 0.20–0.40 × conf ≥0.80 | 19 | $193 | +$190.42 | +98.7% |
| any × conf ≥0.85 | 58 | $535 | +$112.01 | +20.9% |
| any × conf 0.75–0.80 | 81 | $642 | -$121.67 | -19.0% |

Confidence is non-monotonic: ≥0.80 pays (+5.7% at 0.80–0.85, +20.9% at ≥0.85), 0.70–0.80
is the worst population in the book, and <0.60 is roughly flat (-1.5%) on the largest stake.

## 6. Recommendations (recommendations-only until approved in-thread)

**Rec 1 — Reallocate size: mid-price dead zone → long-shot band (capital-neutral).**
`longshotSizeFactor` 1.0 → 1.25 on ≤0.20 entries, funded by `deadZoneSizeFactor` 1.0 → 0.5
(or by executing the already-approved v54 admission stop in 0.40–0.60).
Case: ≤0.20 is the only positive-ROI band all-time (+$100.18 on $2,370 = +4.23%) and the
only band significant-positive in both cuts; 0.40–0.60 is the largest loss bucket
(-$324.80 on $3,884 = -8.36%; decision z=-2.87; 14d -11.5%). Neutral to the binding
exposure cap (size factor, not new notional). Cost: further mid-window contamination of
the Sep 8–Oct 8 Kelly read (already accepted once for v53) — tag it or hold to Oct 8.

**Rec 2 — Add the confidence condition to the mid-price gate before executing v54.**
The -$442.71 / -43% cluster is 0.20–0.60 price × **0.70–0.80 confidence**. Inside
0.40–0.60 alone the damage is that same slice (-$245.58 on $756) while 0.40–0.60 ×
0.60–0.70 is **+2.4%**, so v54 as drafted blocks a positive slice. Ship it as
price+confidence (block 0.20–0.60 unless confidence ≥0.80) or keep v54 and add the
confidence condition for 0.20–0.40 (-$197.13 on $274, the worst ROI cell in the book).
This is the largest structural loss cluster available to cut today.

**Not recommended today (with reasons):**
- Changing the ≤0.20 tier-1 adverse exit. The 7-day "counterfactual exit exemption" clock
  (started Sep 13, reads Sep 20) is measuring precisely this; pre-commit the decision rule
  now, don't ship a live change on a 19-row sample.
- New hour gates/sizing. The two significant *negative* hours are already gated; the two
  significant *positive* hours (06:00, 22:00) rest on 17–27 rows — shadow-measure a size
  bump, don't wire it.
- Raising phase targets. The gate is 0/7 at $500/day; everything above is aimed at making
  that line non-zero for 7 consecutive days.

**Capital question to settle (this is the Dec 1 blocker):** the equity-linked cap cannot
grow fast enough to make $500/day reachable from signal work alone. Either raise the cap
base (`maxGrossExposureUsd` $1,000 → ~$2,500+) / inject principal, or re-date the phase
ladder — state which and the rest of the plan follows.
