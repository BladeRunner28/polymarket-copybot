# Horizon-scaled admission margin — measurement result (2026-10-15)

**VERDICT: `DROP`** — flip mean -0.3307/leg, clustered CI [-5.5543, +3.7130] includes 0.

Approved from the DRADIS audit (`drafts/asset-audit-dradis-20261015.md` §5) via the asset queue;
approved by the user in Discord 2026-10-15. **Nothing was adopted: the shadow spec was NOT written.**
Read-only replay over the frozen decision dataset — no rule, size, live path or stored value touched.

## What was tested

The hypothesis (audit's words): legs admitted on a **flat 0.05** margin but inside a
**horizon-scaled** bar — larger discount demanded the further out settlement is — carry realized
net PnL per leg at or below zero.

- **Ours (the gate):** `src/lib/scoring/price-edge.ts` (status `shadow`): `edge = pWin − price − fee`, admit iff `edge > 0.05`; `pWin = σ(a + b·z)`, `fee = fee_rate·p·(1−p)`.
- **Borrowed (the shape only):** DRADIS `required_edge` = `base·√(secs_left/taper)`, floored at `min_edge`, capped — from `src/vipers/bookline_impl.rs`.
- **Not borrowed (declared choice):** its absolute scale. Their base/min are per-share numbers for a resting-bid strategy on a 1-hour window; ours is a probability-space margin on legs with hours-to-days TTR. Primary parameterization fixed before looking: `taper=24h`, `min=0.02`, `cap=0.1`, `base=0.05`.
- **Metric:** realized net PnL per leg (`pnl_net_full`, falling back to entry-net then gross); 95% CI by **wallet-clustered** bootstrap, resampling wallets not legs, 10,000 reps.

## Result

Universe: **662** settled C-200 legs (drops: {'other-bot': 2617, 'unsettled': 228, 'no-ttr': 9}). **132** of them are admitted by the flat-0.05 gate. TTR hours — min 2.07, p25 11.1, median 35.06, p75 167.66, max 12039.44.

| set | n | wallets | mean $/leg | median | win rate | 95% CI (clustered) |
|---|---|---|---|---|---|---|
| flip (flat-admit, scaled-reject) | 62 | 23 | **-0.3307** | -0.8947 | 35.5% | [-5.5543, +3.7130] |
| kept (admitted by both) | 70 | 26 | +2.7552 | -4.2202 | 25.7% | [-3.2956, +8.4363] |

Decision rule, applied literally: flip mean < 0 **and** clustered CI excluding 0 **at n ≥ 30**. n = 62 clears the sample gate; the mean is negative (-0.3307); the CI **includes 0** ([-5.5543, +3.7130]) → **rule does not fire**. The honest reading is not "the scaled margin is wrong" but "this frozen set cannot tell".

## Sensitivity to the anchor (why a negative here is still informative)

| taper | cap | flip n | flip mean $/leg | flip CI | kept mean |
|---|---|---|---|---|---|
| 6h | 0.10 | 103 | +1.6001 | [-4.455, +7.832] | +0.2602 |
| 6h | 0.20 | 103 | +1.6001 | [-4.455, +7.832] | +0.2602 |
| 24h | 0.10 | 62 | -0.3307 | [-5.554, +3.713] | +2.7552 |
| 24h | 0.20 | 62 | -0.3307 | [-5.554, +3.713] | +2.7552 |
| 72h | 0.10 | 40 | +0.4679 | [-8.069, +7.282] | +1.6700 |
| 72h | 0.20 | 40 | +0.4679 | [-8.069, +7.282] | +1.6700 |
| 168h | 0.10 | 28 | +0.3153 | [-0.901, +2.988] | +1.5724 |
| 168h | 0.20 | 28 | +0.3153 | [-0.901, +2.988] | +1.5724 |

The **sign of the flip mean is not stable across the anchor** (+1.60 at 6 h, −0.33 at 24 h, +0.47 at 72 h, +0.32 at 168 h) and the cap never binds (it needs `secs_left > taper·(cap/base)²`). Since the anchor is our arbitrary choice rather than the donor's (their scale is not transferable), a result that flips sign with it is not evidence for a rule change.

## Caveats worth carrying forward

- **Heavy tails, few wallets.** The means and medians disagree in both sets (flip: mean -0.33 vs median -0.89; kept: +2.76 vs -4.22) and only 23/26 wallets stand behind each mean. A handful of settlements drives both numbers.
- **The basis is the frozen 2026-09-13 set** (662 settled C-200 legs), not the 1,962-leg / 102-wallet basis the audit cited from the 2026-09-23 wallet-selection read. A re-run on that basis is a *different* pre-registration, and it should be preceded by a power calculation rather than by curiosity.
- **The flat gate is highly selective**: it admits 132 of 662 legs (20%), so a horizon rule has little room to act on this book.
- **The rate source is still a slug-keyword proxy** (crypto 0.07 / politics-finance 0.04 / default 0.05), the defect independently flagged by the audit and by the daily brief. Fee error enters both arms equally here, so it does not change this verdict — but it does bound how precisely any edge bar can be priced.

## Artifacts

- Artifact: `data/horizon-margin-replay.json` · Script: `scripts/horizon-margin-replay.py`
- Audit that proposed it: `drafts/asset-audit-dradis-20261015.md` §5
- Ledger: `python3 scripts/asset-queue.py status` (result recorded against `mbordash/DRADIS`)

*(Read-only. Nothing adopted, no shadow spec written, no rule or live path touched. A future pass at the same frozen data would be the thin-window error our own rules forbid; re-open only with a larger basis and a power calculation, or with an anchor derived from our own realized-vol-per-horizon data rather than borrowed.)*
