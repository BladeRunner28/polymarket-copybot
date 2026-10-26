# Pre-registration — fee/fill calibration against the chain-derived aggressor archive

**Status:** proposed, nothing adopted, no code run. Read-only instrument.
**Written:** 2026-10-26. **Decision read:** 2026-11-09 (two weeks, allows the slice pull + one re-read).
**Owner approval:** required before any pull exceeds a 2 GB slice.

---

## 0. Correction to my own recommendation, first

I told you item (1) was "fix the L2 trade-print branch — code, hours not dollars." **That was wrong,
and I verified it before building anything.** `scripts/record-l2.ts` already carries the fix: its header
(line 17-19) documents that an earlier version waited for an `{event:"trade"}` message that never
arrives, which is why the corpus held zero print lines in 36,042 files, and it now writes `book`,
`price_change` (as `pc`) and `last_trade_price` (as `ltp`) lines explicitly labelled as **not a fill
tape**. Measured now:

- `data/l2/` — 44,432 files, **books only**, zero trade prints. That is by design: the market channel
  does not send prints at any event name.
- `data/l2-events/` — **954 files**, `price_change` events carrying `price`/`side`/`size`/`bestBid`/
  `bestAsk` on every quote change (76,221 lines in the newest file alone). This is better than I implied.
- `scripts/c200-printthrough.py` and `scripts/fill-vs-intent.ts` **already join** the public trade tape
  to dispatch windows, and that join already produced the 5 % / 19 % reach rates that killed the
  74 % / 81 % archive prior.

So there is no repair to take. What follows is the question that is genuinely open.

---

## 1. Hypothesis

Our fee model charges **taker fees on all flow**. The venue's law is settled from its own docs —
`fee = C × rate × p × (1 − p)`, **takers only, makers never charged** — and our `takerFeePerShare`
implements it exactly (verified to −$27.05 on 12,710 legs). What has never been measured is the
**share of our flow that is actually taker**, because the CLOB exposes only `maker_base_fee` /
`taker_base_fee` (both `1000`) and every archive-era read has had to assume all-taker.

`TimeSeventeen/Polymarket-v1` carries **1,201,580,990 `orderfilled` rows (27.4 GB) with 100 %
ground-truth aggressor direction derived from the chain** — the maker/taker field we upper-bounded.
If the true maker share of flow at our price/size band is material, our archive-era fee drag is
overstated by that share, and every archive-based ROI (including the fee-sign-flip residual and the
C-200 maker-fill assumption) carries the error.

**Boundary, load-bearing:** the archive's coverage **ends 2026-04-28**, and our first paper trade is
**2026-06-18**. It therefore cannot speak to our present fills. It calibrates the **law's incidence**
(maker share, by band) and the **category assignment**, never our current execution.

## 2. Measurement

1. Pull a **bounded slice** of `orderfilled` (≤2 GB; filter to the price bands and market types we
   trade, then expand only if the slice's per-band row counts clear n≥50,000 each). Do not pull 27.4 GB
   speculatively.
2. Compute, per price band (`<0.20`, `0.20-0.40`, `0.40-0.60`, `0.60-0.80`, `0.80-1.00`) and per size
   bucket matched to our clips ($8–50, $50–100, $100+):
   - **maker share of volume and of trade count**, with a day-clustered bootstrap CI;
   - implied fee under (a) all-taker — today's assumption — and (b) the observed mix.
3. Re-price the archive-era C-200 book under (b) with the existing
   `scripts/c200-fee-reprice-archive.py` (do not write a new re-pricer).
4. Independently verify the **category rate assignment** against the archive's own market metadata: we
   already know `categoryFeeRate` in `src/lib/scoring/price-edge.ts:65-74` has **no geopolitics-0
   branch** and falls through to 0.05. The archive can say how much flow that touches.

## 3. Decision rule

Adopt a maker-branch fee change **iff all three** hold:

- observed maker share of our-sized flow is **≥ 10 %** in at least one band (day-clustered CI lower
  bound > 5 %), **and**
- re-pricing the archive-era book under the observed mix moves it by **≥ $100** (materiality), **and**
- the geopolitics-0 correction is confirmed to touch **≥ 0.5 %** of archive notional or is explicitly
  waived as immaterial.

Otherwise: record **NO-CHANGE** and close the card as verified, quoting the measured maker share.

## 4. Refutation (outcome that proves the hypothesis wrong)

- Maker share **< 5 %** in every band → our all-taker assumption was correct, the fee model needs no
  branch, and this closes permanently. This is the most likely outcome and it is a **useful** result.
- Re-pricing moves the book **< $100** → the incidence question is immaterial regardless of share.
- The slice's band composition cannot be matched to ours (different market types / era) → the archive
  cannot answer the question for this stack; record **UNTRANSFERABLE** and stop. Do not substitute our
  own era as a proxy — that is what the all-taker assumption already is.

## 5. Cost, reversibility, and what this does NOT do

- **Cost:** one slice pull (~1-2 h) + ~2 h analysis. Storage goes to `/Volumes/Storage` (427 GB free),
  never beside the live DB.
- **Reversibility:** read-only. Nothing in the live path reads it; the deliverable is a `drafts/` write-up
  plus a card. A fee change would be a separate Lane A proposal with its own before/after.
- **Does NOT:** shorten the ML gate (that needs n≥400 forward settled legs), improve AUC (the market-only
  lane is closed at −29.84 % expected OOS), or speak to current-era fills. **It is a fee-incidence and
  category-assignment study, not an edge study.** Quoting it as evidence for an ML feature would be a
  category error.

---

## 6. Why this and not the alternatives

| candidate | scale | why not / why now |
|---|---|---|
| `SII-WANGZJ/Polymarket_data` | 232.5 GB | does not fit beside the live DB + L2 growth; take `markets.parquet` only if ever needed |
| `Karmane/...enriched` | ~28k rows | gated, and regenerable from `gamma /markets/keyset` in minutes |
| `jdkatz21/Prediction_Markets_Public` | — | licence `null`, ships no `data/` tree |
| `lycheedata` | paid | never subscribe on a third party's recommendation |
| `Jon-Becker/prediction-market-analysis` | **already on disk**, 50 GB / 49,484 parquet | ✅ free substrate for price history — but it has **no aggressor field**, so it cannot answer this question |

The decisive column is the aggressor field: only the TimeSeventeen archive has it, and it is the only
unknown standing between us and an exact rather than upper-bounded fee model.
