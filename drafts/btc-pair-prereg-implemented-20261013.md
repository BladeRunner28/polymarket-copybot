# Kalshi × Polymarket BTC up/down paired read — pre-registered, now LIVE

**Card:** `kalshi-pm-btc-pair-prereg` (approved in-thread 2026-10-13: *"I approve the btc pair prereg"*) · **Built 2026-10-13 ~01:2x–01:4x UTC** · read-only, keyless, no live-path change.

## What this is and why the gate had to be frozen first

`KXBTC15M` (Kalshi) and `btc-updown-15m-*` (Polymarket) are the **only** cross-venue pair in
either venue family that aligns exactly — same 15-minute wall-clock window, same binary
proposition. Temperature and oil die on ontology (a one-degree bucket-grid offset; "above 84.99"
vs integer strikes → zero exact-alignment rows).

The two venues settle on **different oracles**: Kalshi on the simple average of sixty seconds of
**CF Benchmarks' BRTI**, Polymarket on the **Chainlink BTC/USD 60s TWAP**. So this is a *basis*
trade, and the basis is the risk — which is exactly the kind of thing that gets "confirmed" after
the fact if you don't write the gate down first.

**The gate, frozen before the first sample row existed:**

- Per direction — **A = PM Up + Kalshi No**, **B = PM Down + Kalshi Yes** — take the per-window
  **best** net at an executable size of **≥50 pairs**.
- Charge the direction's **own** measured fatal-oracle rate as a **Wilson 95% upper bound**.
- Clustered bootstrap over windows (samples inside a window are autocorrelated).
- **PASS ⇔ CI lower bound > 0 on at least one direction.**
- **Sample floor 288 windows (72h).** Below it the verdict is `INSUFFICIENT SAMPLE` and no claim
  is made. If it fails, the honest close is *"both venues price the same 15 minutes correctly"*.

## Fee schedule — pinned from the venue's structured truth, not from a constant

This was the card's precondition, and it was **not** the 0.07-vs-0.10 coin flip it looked like:

- Polymarket publishes, for this market: `feeType = crypto_fees_v2`, `feeSchedule = {rate: 0.07, exponent: 1, takerOnly: true, rebateRate: 0.2}`, `feesEnabled: true`.
- The archive-measured fee law (`bt-fee-maker-calibration`, $1.21B of fees, 95–99% of rows to 1e-6) is **taker fee = rate × shares × min(p, 1−p)**, makers $0 — so **0.07·min(p,1−p) per PM share is exactly right**.
- **Trap avoided:** `takerBaseFee`/`makerBaseFee`/CLOB `/fee-rate` are a legacy constant `1000` on ~85% of markets *regardless of schedule*. Pricing `base/1e4` would have charged 0.10/share here — 43% more than the real fee, i.e. enough to erase the entire apparent edge.
- Kalshi: taker `0.07·P·(1−P)`, maker 0. Both legs are crossed (taker/taker) — the conservative read; PM's `rebateRate` 0.2 is maker-only and unmodelled.

## Oracle basis — split per direction, because the aggregate can't price either leg

287 windows / 72h, measured 2026-10-13 (`scripts/kalshi-pm-btc-updown-read.py --outcomes 288 --json data/kalshi-pm-btc-oracle.json`):

- agreement **282 / 287**, disagreement **1.74%** (95% CI 0.75–4.01%)
- **kalshi up × PM up 136** · **kalshi down × PM down 145**
- **fatal to A** (Kalshi up, PM down) = **4/287 = 1.39%**, CI upper **3.53%**
- **fatal to B** (Kalshi down, PM up) = **2/287 = 0.70%**, CI upper **2.50%**

Why this matters: a paired position pays 1.00 when the venues agree and **0.00** in exactly one
disagreement cell — so the *per-direction* cell, not the 1.74% aggregate, is what a pair has to
clear. The two cells are near-symmetric here, which is itself a finding: the A/B price asymmetry
observed live is **not** explained by oracle basis.

## What got built

- **`scripts/kalshi-pm-btc-pair-sampler.py`** + wrapper `~/.hermes/scripts/copybot-kalshi-pm-pair.sh`, **cron `faa5df74ddf3`, every 15 min** (~11.7-minute span at 20s resolution → ~78% window duty, ~35 samples/window).
  - both venue books read back-to-back with the **measured skew** recorded (spec: <1000 ms; observed median ~0.6 s);
  - **real depth** on both legs — Kalshi `/markets/{ticker}/orderbook?depth=10` (`orderbook_fp`), PM `clob.polymarket.com/book` for **both** tokens. **Never** Gamma's `bestBid`/`bestAsk`: stale by up to ~0.6 on these markets (measured 2026-10-12: gamma 0.72/0.73 vs live CLOB 0.86/0.90);
  - per-leg fees at the pinned schedules, both directions' cost/fee/net and **executable size**;
  - **Kalshi's touch exists twice** (market summary vs the resting ladder) and they disagree by ~1¢ live — so every row carries both, `net` is priced at the **worse** ask and `net_optimistic` at the better one. A pass cannot be a snapshot-choice artefact;
  - one **coverage row per invocation** (`data/kalshi-pm-btc-pair-coverage.jsonl`) — coverage is measured, never assumed.
- **`scripts/kalshi-pm-btc-pair-read.py`** — the analyzer/gate, which prints the **identity checks before any verdict**:
  - the **mirror sum** (best A_cost + best B_cost ≈ 2.00 + both spreads — so one direction being cheap *means* the other is expensive; neither is free),
  - the **cross-venue side spread** (PM Up bid − Kalshi Yes ask) at the **first vs last sample** of each window, because a gap that collapses inside the window is a **latency artefact**, not an opportunity.

## First look — n = 1 window, explicitly NOT a claim

Three samples in one window (2026-10-13 01:26Z), recorded here as observation only, because the
pre-registered floor is 288 windows and 3 samples cannot support anything:

- direction **A** net **−0.139 → −0.176** ; direction **B** net **+0.020 → +0.063**
- mirror sum **2.06** (≈2.00 + spreads — consistent, so the asymmetry is the venue spread, not free money)
- side spread **+0.07 → +0.11** *inside* the window — it widened rather than collapsing, which is the one pattern that would justify continuing to 288 windows

## Overridable flags (one line each, if you want them changed)

1. **Cadence** 700s span / 20s resolution (~78% window duty) → raise to 880s for ~98% duty at the same resolution.
2. **Min executable size** 50 pairs counts as a qualifying opportunity; a real position would need a size cap the venues' thin PM book (5–150 shares at the touch is normal) may not support.
3. **Sample floor** 288 windows ≈ 3 days; the same study reads at 576 (~6 days) for a tighter CI.

**Next action, unattended:** nothing to do but let it run — the gate read happens at ≥288 windows, and this card proposes no trade on its own. Any actual position would be a separate approval with its own before/after.

Artifacts: `data/kalshi-pm-btc-pair.jsonl`, `data/kalshi-pm-btc-pair-coverage.jsonl`, `data/kalshi-pm-btc-oracle.json`, the two scripts above.
