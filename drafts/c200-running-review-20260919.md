# C-200 Running Review — 2026-09-19 (18:00 CDT)

Sources: `node query_bankroll.js`, `python3 scripts/analyze-calibration.py` (both fresh, 23:00:34Z), Prisma
probes on `prisma/dev.db`, `logs/cron/copybot-monitor-score.log`, `data/c200-drawdown.json`. Bot
BANKROLL_200, paper only. Supersedes `drafts/c200-running-review-20260915.md`.

## 1. Verdict

The 09-15 review's headline problem — "the goal and the capital don't match" — is **no longer the binding
constraint**. Realized equity is $3,362 (principal $1,900 + $1,462.32 realized), the realized-basis cap is
now **$1,734.50**, and the open book uses $1,286 of it (74%). The 7d lane returns **+58.2% on $2,894
staked** — enough that $500/day needs ~$859/day of stake against ~$1,009/day of cap capacity. The
constraint has flipped to **deal flow**, and the newly-applied v58 per-wallet rail is now vetoing the
book's highest-volume wallet.

## 2. Book state (fresh probes)

- Cash $2,076.33 · open book 85 legs / **$1,285.99 staked** / +$446.61 mtm · net worth (realized basis) **$3,362**.
- Ledger invariant holds: cash = principal + realized − open notional, gap **−$0.0004** (report.ts flags >$5).
- Windows: 7d 255 legs $2,893.77 **+$1,684.40 / +58.2%**; 14d 582 legs $6,013.49 +$1,619.39 / +26.9%;
  all-time 1,800 legs $12,941.66 +$1,462.32 / +11.3%.
- Exit split all-time: early closes 1,381 rows **−$344.52**; natural resolutions 419 rows **+$1,806.84**.
- Drawdown: realized 3.2% (peak $3,482, NW $3,369) · MTM 5.2% (peak $4,005). Gate = 20% realized. No alert.
- Health: last observed trade 6.6 min ago, last journal row 5.2 min ago. Blackout hours 08:00 / 20:00 ET
  verified clean — 0 entries in those hours over the last 7 days.

### Band view (stake = Σ simulatedPositionSize, PM+Kalshi)

| Band | All-time ROI | 7d staked | 7d PnL | 7d ROI |
| --- | --- | --- | --- | --- |
| 0.00–0.20 | +60.9% | $1,769.70 | +$1,845.84 | +104.3% |
| 0.20–0.40 | −7.9% | $520.06 | −$221.87 | −42.7% |
| 0.40–0.60 | −7.9% | $222.52 | +$18.49 | +8.3% |
| 0.60–0.80 | −1.2% | $381.49 | +$41.94 | +11.0% |

The long-shot band is 61% of 7d stake and produced more than the whole book's 7d PnL; every other band
combined was −$161.44.

## 3. Phase gate (user policy 2026-08-31)

- `Phase stability (T+0): 0/7`; `settled (T+3): 1/7` from 2026-09-16 — the settled read is the basis.
  Sep 17 (+$12.36) breaks the streak behind Sep 16 (+$743.38).
- The two ≥$500 days in the settled window are Sep 16 (+$743.38) and Sep 18 (+$993.70, still settling).
- Ladder: 4 phases × 7 consecutive days = 28 clean days, so the $500 streak must start **Nov 4**, $1k
  Nov 11–17, $2k Nov 18–24, $5k Nov 25–Dec 1. Today is 73 days out; the first $500 day is 46 days out,
  with zero slack for a reset. **Do not raise any phase target** — the streak is the goal.

### Trajectory arithmetic

- 7d stake rate $413/day → $1,684/day-of-PnL $240.6/day. $500/day at the 7d ROI needs **$859/day staked
  (2.1×)**, which is ~50% of the cap's one-day-turnover capacity at the observed ~1.03-day median hold.
- Capital self-feeds: every $500 realized adds $250 to the cap, so the cap grows faster than the
  requirement — no principal injection needed anymore (this reverses the 09-15 blocker).
- So the gate is flow: qualifying long-shot copies per day, and whatever the rails veto.

## 4. NEW: the v58 per-wallet rail is live and binding (evidence)

v58 was applied 2026-09-19T18:25:21Z (`RuleSet v58`, `maxWalletNotionalPctOfCap 0.25`; call site
`scripts/score-trades.ts:880`, ceiling = 25% × effective cap).

- Ceiling today = 0.25 × $1,734.50 = **$433.64**.
- Wallet `0xb0c85813a7` holds **$1,003.64 open (78% of the open book, 51 of 85 legs)** = **2.36× the ceiling**.
- `logs/cron/copybot-monitor-score.log`: **22 `v58 per-wallet cap (notional $1,02x–1,05x > cap $433.6x)`
  vetoes in the ~4.5h since activation**, in every 15-min cycle, 1–4 per cycle. Blocked slugs
  (temperature ladders, Elon tweet-count, RU/Berlin election lines) resolve to that wallet.
- Effect: entries after 13:25 CDT today = **7 legs**, vs 43 legs in the 00:00–11:00 window. Cycles since
  then close with 0–3 copies.
- Caveat, stated honestly: some of those vetoed copies would have been rejected anyway by
  `c200MaxEntryPrice 0.80` (the log shows `high-entry cap (0.830/0.895 > 0.80)` on the same slugs), so the
  raw veto count overstates the marginal cost. That is why Rec 1 is a shadow measurement, not a rule change.
- This is not a "bug" claim: v58's comment acknowledged the wallet carried 84.6% of the book. What the
  comment did not anticipate is that a rail measured against *existing* open notional behaves as a **freeze**
  for any wallet already above the ceiling — it cannot bind gradually, and `0xb0c85813a7` stays frozen until
  ~$570 of its book closes.
- Wallet quality for context: `0xb0c85813a7` all-time 288 legs $2,320.83 staked **+$217.84 (9.4%)**, 7d
  +$161.78 on $1,061.91 (15.2%). The 7d PnL leader is `0xc5187cb669` (+$1,128.68 on $562.98, 200%) and it
  holds only $45.10 open — **unaffected** by the rail. So the freeze is not cutting the best lane; it cuts
  the largest-volume lane.

## 5. Calibration significance (fresh 2026-09-19T23:00:34Z, N=1,707, `deduped: false`)

Row-level, PM-only (script excludes Kalshi per v48 — 92 Kalshi rows, +$27.82 net, are outside this file;
that is why band PnL differs slightly from the raw-SQL table in §2). Overall book: excess +0.0018, z=+0.15
— **the edge is not in the aggregate, it is in the bands**.

Bands |z| ≥ 2:

| Band | Excess | z | Realized |
| --- | --- | --- | --- |
| 0.00–0.20 | +0.2232 | +5.77 | +$2,022.61 |
| 0.20–0.40 | +0.0633 | +2.35 | −$406.89 |
| 0.60–0.80 | −0.0801 | −3.16 | −$18.24 |
| 0.80–1.01 | −0.0664 | −2.14 | +$0.12 |

- **0.00–0.20** is the strongest result in the dataset (p=0.0000): 33.1% win rate vs 10.8% mean entry.
  Reinforce, do not trim.
- **0.20–0.40 is the contradiction to resolve**: significant *positive* resolution excess (+6.3pp) but
  −$406.89 realized. The gap is exit-side — early closes 275 rows −$271.15 (−$0.99/leg) vs resolutions
  62 rows +$48.38 (+$0.78/leg) — and it is concentrated in the last 7 days (−$221.87, −42.7%).
- **0.60–0.80** confirms the queued premium-band gate (row z=−3.16, decision-level z≈−2.16). Stays queued
  for Oct 8; don't ship inside the Kelly window.
- **0.80–1.01** already handled by `c200MaxEntryPrice 0.80` (v47). No action.

Hours |z| ≥ 2 (ET):

- Significant **drains: 20:00 ET** (−0.2365, z=−2.82, −$80.43) and **08:00 ET** (−0.1812, z=−2.26, −$71.12)
  — **both already gated** (v44 shared / v53 C-200-only); verified 0 entries in those hours over 7 days.
- **23:00 ET is NOT significant** (−0.0532, z=−0.79) and was already un-gated in v48 after the
  Kalshi-phantom audit. Do not re-gate it on this run.
- Significant **winners, unsized**: 09:00 ET (+0.1341, z=+2.50), 22:00 ET (+0.1514, z=+2.10, +$309.35),
  21:00 ET (+0.1223, z=+2.00, +$720.06); 06:00 ET is sub-threshold (z=+1.95) but the biggest dollar hour
  (+$1,512.07). Today's entries are already concentrated in 09:00 ET (17 legs) — the one positive hour the
  book naturally trades.

## 6. Recommendations (recommendations-only until approved in-thread)

**Rec 1 — TODAY, free (measurement, no override needed): price the v58 freeze and extend the exit
counterfactual to 0.20–0.40.**
Two shadow lanes, no config/trade behavior touched:
(a) log the counterfactual copies the frozen wallet `0xb0c85813a7` would have produced (would-be size, band
by entry price, then realized PnL when the underlying resolves) so the rail's cost/benefit is a number, not
an argument — the freeze removes 78% of open notional;
(b) the Sep-13 exit-exemption counterfactual reads **tomorrow (Sep 20)** for the <0.20 band; add the
0.20–0.40 band to the same read, since §5 shows its loss is exit-side, not selection-side. Pre-commit the
decision rule today so tomorrow's number is decidable on the day.

**Rec 2 — needs your explicit override (rule change, Kelly window Sep 8–Oct 8): fix the v58 rail basis.**
The ceiling compares *existing* open notional to 25% × cap, so a wallet already above it is frozen outright
(`0xb0c85813a7`: $1,003.64 vs $433.64). Either (i) grandfather pre-activation notional and gate only
new-cycle accumulation, or (ii) raise `maxWalletNotionalPctOfCap` 0.25 → 0.40 ($433 → $694) so the rail
binds gradually. This is a rule change inside the freeze; it stays a recommendation until you say go.

**Not recommended today, with reasons:**
- Any phase/target change. The settled streak is 1/7; a target move now resets the ladder's meaning.
- Wiring the significant positive hours (06:00/09:00/21:00/22:00) to size uplifts — sizing change inside the
  free window, and 06:00 is sub-threshold. Shadow-measure first (free), wire after Oct 8.
- Re-gating 23:00 ET — not significant (z=−0.79); it was un-gated for a documented phantom-pricing reason.
- Trimming the 0.00–0.20 band anywhere: it is z=+5.77 and +104.3% on the last 7 days' stake.
- Pre-empting the Sep-20 exit-exemption read with a live exit change.

**The one sizing lever with real leverage, if you want throughput before Oct 8:** `c200LongshotBandFactor`
2.5 → ~4.0 (band clip $38–55/leg today, band ROI +60.9% all-time / +104.3% 7d). It is an override and it
widens exactly the concentration Rec 2 is trying to cap — so Rec 2's shadow read should land before it.
