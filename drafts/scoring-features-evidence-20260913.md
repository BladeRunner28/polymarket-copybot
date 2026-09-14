# What Empirically Predicts a Copied Prediction-Market Trade

**Evidence review for the Medusa CopyBot scorer**
Date: 2026-09-13 · Author: research subagent · Status: draft for review
Scope: public research (working papers, academic preprints, dataset releases, credible practitioner write-ups)

---

## 0. How to read this document

The scorer we run today (`src/lib/scoring/trade.ts`) is:

```
copyScore = walletQuality×0.30 + catFit×0.15 + entryTiming×0.20
          + spread×0.10 + liquidity×0.15 + thesis(≈price 0.50)×0.10
          (+ swarmCount≥3 → +25, + sentimentDelta×scale, − meanReversion for ttr<48 & p>0.80)
```

The parent's own SQL over `prisma/dev.db` (2026-09-13) established the headline fact that motivated this
review: **the wallet-quality / category-fit / entry-timing / spread / liquidity / price-near-0.50 components
are statistically indistinguishable between winners and losers** (wallet quality 87.4 vs 86.9; thesis 72.7 vs
76.5; timing 61.7 vs 59.6; spread 90.3 vs 91.4), while **entry-price band and exit policy carry all of the
measured signal** (entries <$0.20 the only positive band, z=+4.94; 0.60–0.80 significantly negative; early
exit −$152.82 vs held-to-resolution +$180.64).

The literature below independently reproduces that shape. The two things it says are most predictive — *which
side of the trade you are on* (maker vs taker) and *whether a wallet's record reflects skill or luck* — are the
two things the current score either omits entirely or implements using the proxy the research most directly
discredits.

Evidence-strength tags used throughout:

| Tag | Meaning |
|---|---|
| **A — strong** | Large disclosed sample, clear methodology, two or more independent confirmations |
| **B — moderate** | Credible study, single source, plausible method, some caveats |
| **C — thin** | Small sample, vendor-published, unreviewed, or no direct study found |
| **⚠V** | Vendor / marketing-adjacent — treat the *direction* as a hypothesis, not a fact |

---

## 1. Ranked feature table

Ranked by strength of published evidence for predicting trade outcome on a prediction market — **not** by
whether the current bot uses it.

| # | Feature | Claim | Evidence (source · sample) | Direction / magnitude | Contradicts current bot? | Strength |
|---|---|---|---|---|---|---|
| **1** | **Liquidity-provision side (maker vs taker share)** | Profitable users are net *makers*; losing users *take* liquidity | Akey, Grégoire, Harvie, Martineau (2026) · 2.4M users, $67B, Nov-2022→Mar-2026; Whelan, Deng (2026) · 313,972 Kalshi contracts; Yang (2026) · 150M Polymarket trades; Roosevelt Institute (2026) · 400M Kalshi trades, $32B | Akey: 1 SD ↑ maker-volume share ⇒ **+9.0 pp** probability of positive PnL — *the largest behavioral effect estimated*. Top 0.1% earners: 47.3% maker volume vs 17.1% bottom-95%. Whelan: maker −9.64% vs taker **−31.46%** average ROI. Yang: skilled earn $121/market as maker, $63 as taker. Roosevelt: retail takers −$583.5M | **YES — severe.** The bot is a pure taker by construction and has *no maker-share feature*. Its own `whaleSizeUsd` guard already notes "wallets trading large size in their home category are often the liquidity, not the edge" — it detects the symptom in one dimension and never scores it | **A** |
| **2** | **Statistical skill classification (sign-randomization) ≠ raw PnL/ROI** | Raw PnL on a leaderboard is a *poor* proxy for persistent skill | Gomez-Cram, Guo, Jensen, Kung (2026), *Prediction Market Accuracy: Crowd Wisdom or Informed Minority?*, SSRN 6617059 · 1.72M accounts, 98,906 events, 210,322 markets, $13.76B, 2023–2025; corroborated by Akey et al. (2026) | Only **3.14%** of accounts are "skilled winners"; skilled + market makers (<3.5% of accounts) capture **>30%** of all gains. **Only 12% of top-PnL earners overlap the skilled group**; ~**60% of "lucky winners" revert to losses** out-of-sample. Akey: finite-mixture classifies only ~29% as skilled | **YES — severe.** `walletQuality` carries the single largest weight (0.30) and is derived from PnL/ROI leaderboard data — precisely the 88%-overlap-failure proxy | **A** |
| **3** | **Entry price / favourite–longshot direction** | Price level is a real, systematically mispriced axis — but the *sign is contested near the extremes* | Whelan & Deng (2026) · 313,972 contracts; Polymarket-v1 Database (2026, arXiv 2606.04217) · 1.20B trades, 1.30M markets, $61B; polymarket-edge (2026, practitioner) · 249,840 tokens at T-7; PolySyncer (2026⚠V) · 28,407 resolved markets; arXiv 2602.19520; arXiv 2607.14430 · 23M moneyline trades | Whelan: contracts ≤10¢ lose **>60%**; >50¢ small positive; makers >50¢ **+2.6%**; avg contract **−20%**. Polymarket-v1: price ≤0.30 ⇒ negative realized return, ≥0.40 ⇒ positive. **Counter-evidence:** polymarket-edge finds a **reverse** FLB at T-7 (0–10% bucket implied 2.55% vs realized 3.88%); PolySyncer finds sports *favourites slightly overpriced* ⇒ selective underdog edge; arXiv 2602.19520 finds FLB *widens with time to expiration* | **PARTLY — and against our own tape.** `thesisScore = 100 − abs(p−0.5)×160` actively *penalises* extreme prices (p=0.15 ⇒ 44/100), yet the parent's own data says <$0.20 is the only positive band. Note the literature measures *unconditional* longshot buying; ours is conditioned on a top-wallet copy — a different estimand. v48's "long-shot floor" hack is the design fighting its own component | **A** (direction contested) |
| **4** | **Time-to-resolution (TTR) as a conditioning variable** | Calibration and skill are TTR-dependent; price alone is an invalid probability | arXiv 2607.14430 · 23M Kalshi moneyline trades (NBA 13.0M, MLB 7.1M, NHL 2.8M), Mar–May 2026; Yang (2026); arXiv 2602.19520; Whelan & Deng (2026) | Calibration is **U-shaped in TTR**: near-perfect mid-life, sharply departing as expiry approaches — in the **final 10 minutes** the curve turns step-like (Prelec curvature >1, *opposite* the lottery-choice sign ⇒ insurance demand by holders of losing positions). Authors' conclusion: "any use [of prices as probabilities] should condition on both time-to-expiry and product type." Yang: skilled traders provide liquidity more in **higher-volume and shorter-duration** markets | **PARTLY.** Supports the <72h short-TTR lane (our one profitable channel, +$538.16). But note the *final minutes* are the **worst** regime — so "short TTR" is only good up to a point, and TTR should modulate the price/Favourite term, not sit beside it | **A** |
| **5** | **Hold to resolution vs early exit** | Winners hold to natural resolution; early exit is the loss channel | Wang (2026), *Smart Money on Polymarket*, SSRN 6624899⚠V · 273 top wallets; Akey et al. (2026); Whelan & Deng (2026) | Wang: median **event-level win rate 93% vs median trade-level win rate 58%** — i.e. profits come from *holding* to resolution through staggered DCA (median 15 entries/market); "resolution-edge holding" is the dominant strategy; "Heavy-DCA Holders" highest median PnL, "HFT-like Bots" lowest. Akey: persistence concentrated among limit-order (maker) users. Whelan: prices get *more* accurate toward the close, but cheap-contract losses persist to the final day | **YES.** Exit policy dominates our realized PnL ('closed' −$152.82 vs 'resolved' +$180.64) exactly as Wang predicts. The bot also *penalises* ttr<48 with p>0.80 (−10, "mean-reversion risk") — the favourite/hold configuration the research calls profitable | **B+** |
| **6** | **Wallet-skill persistence horizon** | Skill persists meaningfully but *far below* what leaderboard continuity implies; most PnL-reversion is luck unwinding | Gomez-Cram et al. (2026); Akey et al. (2026) | Gomez-Cram: **44%** of accounts classified skilled in a training split remain skilled on a held-out set (vs ~**10%** for active mutual funds) — unusually high for this literature, but still >half decay; skilled average **79 markets** each. Akey: month-to-month persistence only *modest*, concentrated in limit-order users, and plausibly **selection** (who keeps trading) rather than skill | **YES.** Directly undercuts treating a leaderboard score as a durable wallet attribute. Our own measurement (wallet quality 87.4 vs 86.9) is the empirical echo | **A** |
| **7** | **Category specialisation / within-domain skill** | Specialists beat generalists *once you condition on which categories they trade* | Akey et al. (2026); Yang (2026); Stand/Polymarket *COPYCAT* (2026)⚠V; Wang (2026)⚠V; Nechepurenko (2026, arXiv 2605.02287) | Akey: Category HHI ⇒ **−8.6 pp** alone but **+5.5 pp** once category indicators enter ⇒ *within-category* concentration predicts positive performance. Exposure to Crypto/Politics/Tech/Weather/Finance = **+3.3 to +7.9 pp** vs Sports-only in the full sample (flips negative for the >1,000-trade cohort). Yang: **within-**category accuracy (not cross-domain) validates the skill classification. Stand: top copied wallets are domain-narrow — Domer's worst categories are crypto; "domain specificity equals edge" | **SUPPORTS the concept, not the implementation.** The bot *has* `categoryFit` (0.15) — directionally right. But it is built from `walletCategoryWinRate`, and the parent's own data shows it is identical for winners/losers (72.7 vs 76.5). Win-rate is the same luck-contaminated proxy as #2 | **B+** |
| **8** | **Informed-flow microstructure (size anomaly, pre-event timing, directional concentration, order imbalance)** | Composite flow signatures identify informed traders with high hit rates | Mitts & Ofir (2026), *From Iran to Taylor Swift*, Columbia/Haifa · 210,000+ wallet–market pairs, Feb-2024→Feb-2026; Gomez-Cram et al. (2026); Polymarket-v1 (2026) | Mitts & Ofir: flagged traders achieve **69.9% win rate**, ≈**$143M** aggregate anomalous profit; composite = *bet-size anomalies + profitability + pre-event timing + directional concentration*. Gomez-Cram: **1 pp ↑ in skilled net buying ⇒ 8 bp ↑** probability of the correct final outcome. Polymarket-v1: order-flow imbalance estimators carry real predictive content | **PARTLY.** We gate on `orderbookImbalance` (hard skip) — good, and directionally supported. But no size-anomaly / timing / concentration term *feeds the score*; `tradeSize` only triggers a whale-wake label and a category-fit cap | **B** |
| **9** | **Trade size relative to activity / book depth** | Larger per-trade size is mildly *positive* conditional on activity, but size does not make prices more accurate | Akey et al. (2026); Roosevelt Institute (2026); **countervailing:** Whelan & Deng (2026) | Akey: `log(total volume)` −2.3 pp full sample but **+2.0 to +4.4 pp** among >100-trade users ⇒ conditional on trade count, bigger size ⇒ slightly better. Roosevelt: **63.2%** of all taker revenue flowed to just **6.3%** of matched orders (≥$200). Whelan: quintiles by average transaction size **do not** improve price accuracy — the largest-size quintile has the *largest* bias | **MIXED.** We treat size only as a cap/penalty (v45 whale guard). The research says size is informational *conditional on an active wallet* and non-informational as a market-level accuracy proxy. Two different questions are being conflated | **B / mixed** |
| **10** | **Spread & liquidity as execution cost (not alpha)** | Spread is what separates marginal winners from losers; thin depth kills otherwise-real edges | Akey et al. (2026); polymarket-edge (2026); Whelan & Deng (2026) | Akey: removing even the **minimum-tick spread cost** would move **18.5%** of losers (≈1 in 5) to non-negative PnL — but cannot explain the worst performers, whose losses are forecast errors, not costs. polymarket-edge: gross longshot edge survives fees + spread proxy but is **not exploitable at scale** (only ~$11 depth at the relevant price). Whelan: even top-decile Kalshi markets average $526k total volume | **NO — consistent.** `spreadScore` (0.10) and `liquidityScore` (0.15) are directionally right. Reframe them as cost control rather than as evidence of edge — they do not discriminate winner from loser trades | **A** |
| **11** | **Swarm / consensus of top wallets on the same side** | N top wallets same-side within an hour ⇒ stronger signal | **No direct published study found.** Nearest analogue: skilled order-flow imbalance predicts price (Gomez-Cram 8 bp/1 pp; Polymarket-v1 OIB) | Direction unknown; magnitude unaudited | **UNSUPPORTED & OVER-WEIGHTED.** A flat **+25** — larger than any single component's maximum contribution except `walletQuality`. Inherits the #2 PnL-proxy contamination: swarming *leaderboard* wallets ≠ swarming *statistically skilled* wallets | **C** |
| **12** | **Sentiment / regulatory-evidence delta** | External evidence shifts the fair probability ⇒ edge | **No direct support found** in the prediction-market prediction literature reviewed | n/a | **UNSUPPORTED as a return predictor** in any source reviewed. Not disproven — simply not evidenced | **C** |
| **13** | **Entry drift vs the wallet's fill (copy-timing penalty)** | Delayed copying mechanically destroys the copy's risk/reward | dev.to / CtrlPoly (2026)⚠V · "200+ whale wallets, 2 months"; Stand *COPYCAT* (2026)⚠V | Worked example: wallet enters 0.34, copier 0.41 ⇒ on a YES win, 194% → 144% return, **identical −100% downside**, i.e. **26% less upside for the same risk**. "67% of copy traders underperformed the whale they were copying." Stand: iceberg orders, position *merging*, secondary/tertiary wallets mean the public book is not the full book; bots ⇒ guaranteed worse fills | **NO — consistent in direction.** But the parent measured drift as having *no* edge (timing 61.7 vs 59.6), so its current 0.20 weight overstates what the tape shows. Keep the gate; stop treating it as alpha | **C / ⚠V** |

### Sources (URLs)

| Ref | URL |
|---|---|
| Akey, Grégoire, Harvie, Martineau (2026), *Who Wins and Who Loses in Prediction Markets? Evidence from Polymarket* | https://www.carf.e.u-tokyo.ac.jp/wp/wp-content/uploads/2026/06/260714_polymarket.pdf |
| Gomez-Cram, Guo, Jensen, Kung (2026), *Prediction Market Accuracy: Crowd Wisdom or Informed Minority?* (SSRN 6617059) | https://papers.ssrn.com/sol3/papers.cfm?abstract_id=6617059 |
| Whelan & Deng (Bürgi, Deng, Whelan), *Makers and Takers: The Economics of the Kalshi Prediction Market* | https://www.karlwhelan.com/Papers/Kalshi.pdf |
| Yang (2026), *Skilled Liquidity Provision in Prediction Markets: Evidence from 150 Million Trades* (SSRN 6396698) | https://papers.ssrn.com/sol3/papers.cfm?abstract_id=6396698 |
| Nechepurenko (2026), *Per-Market Information Leakage and Order-Flow Skill* (arXiv 2605.02287) | https://arxiv.org/html/2605.02287 |
| *Polymarket-v1 Database* (arXiv 2606.04217) | https://arxiv.org/abs/2606.04217 · https://arxiv.org/html/2606.04217v1 |
| *Decomposing Crowd Wisdom: Domain-Specific Calibration Dynamics* (arXiv 2602.19520) | https://arxiv.org/html/2602.19520 |
| *Prices, Probabilities, and Parlays: Systematic Bias in Sports Prediction Markets* (arXiv 2607.14430) | https://arxiv.org/html/2607.14430v1 |
| Mitts & Ofir (2026), *From Iran to Taylor Swift: Informed Trading in Prediction Markets* | https://www.capitalspectator.com/research-review-24-april-2026-prediction-markets/ (abstract roundup) |
| Wang (2026), *Smart Money on Polymarket* (SSRN 6624899) ⚠V | https://papers.ssrn.com/sol3/papers.cfm?abstract_id=6624899 |
| Roosevelt Institute (2026), Kalshi retail losses | https://rooseveltinstitute.org/blog/since-kalshis-launch-ordinary-users-have-lost-half-a-billion-dollars/ |
| Stand / Polymarket *COPYCAT* interview | https://news.polymarket.com/p/copycat |
| *Why Most Copy Traders Lose Money* (0xIcaruss) ⚠V | https://medium.com/@0xicaruss/why-most-copy-traders-lose-money-and-how-configuration-actually-fixes-it-6988875e65f8 |
| CtrlPoly copy-trading trap ⚠V | https://dev.to/jacobyf/the-polymarket-copy-trading-trap-what-nobody-tells-you-about-following-prediction-market-whales-27b5 |
| Polymarket-v1 / SII dataset releases | https://github.com/SII-WANGZJ/Polymarket_data · https://github.com/jon-becker/prediction-market-analysis |
| polymarket-edge (practitioner calibration study) | https://github.com/sachacoemelck/polymarket-edge |
| PolySyncer calibration study ⚠V | https://www.polysyncer.com/blog/polymarket-prediction-accuracy |

---

## 2. Direct answers to the six commissioned questions

**(1) Does wallet skill persist, and over what horizon?**

Yes, but modestly — and **raw PnL is a demonstrably bad proxy for it.** The strongest evidence is
Gomez-Cram et al. (2026): a sign-randomization classifier re-runs each account's history 10,000 times with
event-level buy/sell directions randomized, then locates realized PnL in that null. Only **3.14%** of
accounts are "skilled winners," and **44%** of training-split skilled accounts retain the label on a
held-out set — high versus the ~10% they measure for active mutual funds, but still a majority decay.
The killer number for a copybot: **only 12% of top-PnL earners overlap the skilled group**, and ~**60% of
"lucky winners" revert to losses out-of-sample. Akey et al. (2026) independently find month-to-month
persistence is only *modest* and plausibly **selection** (who keeps trading) rather than durable skill.
Horizon evidence: there is no published "edge half-life in days" figure; the persistence unit in the
literature is *events/markets*, not calendar time (skilled traders average 79 markets each).

**(2) Informed vs liquidity-providing flow.**

This is where the literature is most decisive and most inconvenient for us. Two independently
identified facts:

- **Being the maker is the single strongest cross-sectional predictor of positive PnL** (Akey et al.:
  +9.0 pp per 1 SD of maker-volume share; top 0.1% earners 47.3% maker volume vs 17.1% for the bottom 95%).
  Whelan: makers −9.64% vs takers **−31.46%**. Yang: skilled earn $121/market as maker, $63 as taker. Roosevelt:
  Kalshi retail *takers* lost $583.5M.
- **But skill, not the maker/taker label, is what actually pays** — Yang's headline is "trader skill, not the
  maker–taker distinction, determines who profits." Skilled traders *choose* to make more often in
  higher-volume, shorter-duration markets; ordinary traders lose on **both** sides.

The practical reading for a taker-by-construction copybot: taker-side copying is a structurally negative-sum
seat, and the only thing that can rescue it is copying a wallet whose edge is *forecasting*, not *spread
capture* — because spread-capture edges do not transfer to a taker. We currently have no feature that
distinguishes the two. `tradeSize` is the closest thing and it is used only as a cap.

Aggression/size-relative-to-depth: Mitts & Ofir's composite screen — **bet-size anomalies + profitability +
pre-event timing + directional concentration** — flags traders at a **69.9%** win rate (≈$143M anomalous
profit over 210k+ wallet–market pairs). Notably they need *all four* jointly, not size alone. Counterpoint:
Whelan finds market-level average transaction size does **not** improve price accuracy — the largest-size
quintile is the *most* biased. Size is informative about an individual's conviction, not about market-wide
mispricing.

**(3) Entry price / favourite–longshot bias magnitudes in event contracts.**

Well documented, and the **sign flips depending on venue, horizon, and conditioning**:

- Whelan (Kalshi, 313,972 contracts): ≤10¢ contracts lose **>60%** of money; >50¢ slightly positive;
  makers buying >50¢ earn **+2.6%**; average contract **−20%**. Prices become more accurate toward the close.
- Polymarket-v1 (1.20B trades): tokens at price ≤0.30 show **negative** realized returns, ≥0.40 **positive** —
  classic FLB sign on Polymarket.
- PolySyncer (28,407 resolved markets, Jan-2024→May-2026): mean absolute calibration error **2.1 pp**, bias
  **small (1–2 pp)** — sportsbooks 4–8 pp, polls 5–10 pp; sports shows *favourites slightly overpriced*.
- polymarket-edge (249,840 tokens at T-7): a **reverse** FLB — 0–10% bucket priced 2.55% vs realized 3.88%;
  sports 10–20% bucket −5.3 pp. Gross edge survives fees but is **not exploitable at scale** (~$11 depth).
- arXiv 2602.19520: FLB **widens with time to expiration**; domains follow different calibration paths.
- arXiv 2607.14430 (23M trades): calibration is **U-shaped in TTR**; the final 10 minutes are the *most*
  miscalibrated; parlays are systematically overpriced, growing with leg count.

So: the *level* effect (extreme prices are mispriced) is robust across venues with |bias| ~2–6 pp on
Polymarket and 20%+ average ROI drag on Kalshi. The *sign* at the longshot end is genuinely contested
between Polymarket-v1 and polymarket-edge — likely a TTR/period interaction. Our own +0.23 excess on
<$0.20 copies is a **fourth** estimate, conditioned on premium-wallet flow, and rests on 102 trades.

**(4) Holding to resolution vs early exit.**

Holding wins. Wang (2026) measures the mechanism crisply: median **event-level win rate 93%** vs median
**trade-level win rate 58%** across 273 top wallets — the gap *is* the holding premium, achieved via
staggered DCA (median 15 entries/market) into mispriced binaries held to resolution. "Heavy-DCA Holders"
produce the highest median profit; "HFT-like Bots" the lowest. Akey adds that what persistence exists is
concentrated among limit-order (maker) users. Whelan supplies the tension: prices get *more* accurate as
contracts approach closing, so a favourable entry can be structurally whittled away — but cheap-contract
losers stay losers right to the final day.

Caveat from arXiv 2607.14430: the **final ten minutes before settlement** are the *most* miscalibrated
regime (Prelec curvature >1; insurance demand from traders sitting on losing positions). "Hold to
resolution" should mean *hold through*, not *enter into*, that window.

**(5) Category / sport specialisation.**

Supported, with an important conditional. Akey et al.: Category HHI is **−8.6 pp** on its own but **+5.5 pp**
once category indicators enter — i.e. herding into one category without an edge is bad, whereas
*within-category* concentration (given a real choice of categories) is good. Exposure to Crypto/Politics/
Tech/Weather/Finance runs **+3.3 to +7.9 pp** vs Sports-only in the full sample, but *flips negative*
(Crypto −5.7 pp, Politics −4.1 pp) among the >1,000-trade cohort, where Sports-only fares relatively better —
a selection effect they call out explicitly ("pooled regressions mask substantial subgroup heterogeneity").
Yang finds within-category accuracy (not cross-domain luck) validates skill. Practitioner corroboration:
Stand's most-copied wallets are domain-narrow (weather in five cities; a soccer-only quant; Domer's worst
categories are crypto/Ethereum), and Wang reports **98% of politics specialists profitable, median $172K**,
while sports draws 45% of the population with a flatter payout.

**This is the one current component whose *concept* the literature endorses.** Its implementation is the
problem.

**(6) Public prediction-market tapes.**

The "~680M-trade Polymarket dataset" figure in the brief **could not be verified**; I found larger, citable
releases instead:

- **Polymarket-v1 Database** (arXiv 2606.04217): **1.20 billion** trade records, **1.30 million** markets,
  **$61B** nominal volume, 41 months (2022-11-21 → 2026-04-28), built from Polygon CTF Exchange `OrderFilled`
  events, with maker/taker addresses and ground-truth taker direction, 99.8% metadata-join coverage.
- **SII-WANGZJ/Polymarket_data**: 107 GB, **~1.1 billion** records, 268K+ markets, with tooling.
- **Jon-Becker/prediction-market-analysis**: framework + "largest publicly available" Polymarket *and* Kalshi
  dataset.
- Kalshi-native tapes: Roosevelt Institute (400M+ trades, $32B, Jul-2021→May-2026); arXiv 2607.14430
  (23M sports moneyline trades, Mar–May 2026); Whelan (313,972 contracts).

One structural caveat worth carrying into any feature work: **Nechepurenko (2026) documents that Polymarket's
off-chain CLOB makes address-level quote-lifecycle attribution permanently unavailable** — `OrderPlaced` /
`OrderCancelled` are off-chain and absent from public archives, so quote-intensity, two-sided-ratio and
posted-spread features **cannot** be built at the wallet level from public data. That is a hard validity gate
on the maker-share feature in #1: you can observe *fills* side (maker/taker, which is what Akey and Yang use),
but not resting quotes.

---

## 3. What this implies for our score

### 3.1 The two contradictions that matter most

**Contradiction A — the bot is on the losing side of the trade by construction, and scores nothing
about it.**
`copyScore` is entirely a *selection* function over which wallet to follow. It contains no term for whether
the edge being copied is a *liquidity-provision* edge or a *forecasting* edge. Akey et al.'s largest
behavioral effect (+9.0 pp/1 SD, maker-volume share), Whelan's maker/taker ROI split (−9.64% vs −31.46%),
Yang's maker/taker profit split ($121 vs $63) and Roosevelt's −$583.5M taker loss all say the same thing:
takings liquidity is a structurally negative-sum seat. Our own `whaleSizeUsd` guard already encodes the
intuition ("wallets trading large size in their home category are often the liquidity, not the edge") — but
it is a narrow cap, not a scored dimension, and it is fighting the 0.30-weight leaderboard term that
*positively* selects for large, category-dominant wallets.

**Contradiction B — the score's dominant term is the proxy the literature most directly discredits.**
`walletQuality` (0.30) is PnL/ROI-leaderboard-derived. Gomez-Cram et al.: only **12%** of top-PnL earners are
in the statistically-skilled group and ~**60%** of lucky winners revert out-of-sample. Akey et al.: persistence
is modest and possibly selection. So the heaviest-weighted feature is the one with the *documented worst*
signal-to-noise as a skill proxy — and it is exactly the component our own SQL found to be identical between
winners and losers (87.4 vs 86.9). The research did not merely fail to support `walletQuality`; it explains
*why* it measured flat.

A **third**, softer contradiction: `thesisScore` (price near 0.50) *penalises* the <$0.20 band that is our
only positive band. But here the literature is itself split (Polymarket-v1 vs polymarket-edge disagree on the
longshot sign), so this is a case for *conditioning* rather than flipping.

### 3.2 Concrete changes, in priority order

1. **Add a maker-share feature and re-rank wallets on it.** For each candidate wallet compute the fraction
   of its volume executed as maker (observable from the trade tape's maker/taker fields — the same fields
   Akey and Yang rely on). This is the highest-expected-value change available: it is the largest effect in
   the literature, it is computable from data we already store, and it is currently absent.
   *Validity gate:* quote-lifecycle features (posted spreads, two-sided ratio) are **not** buildable
   (Nechepurenko 2026) — fill-side maker share only.
2. **Replace the PnL/ROI leaderboard score with a luck-adjusted skill score.** Concretely: a
   sign-randomization / permutation test on each wallet's event-level directions (the Gomez-Cram method), or
   at minimum an excess-hit-rate measure (realized outcome − entry price, averaged per trade) instead of raw
   ROI. Akey's excess hit rate runs from **−15/−18 pp** in the loss tail to **+20 pp** for the most profitable
   users, and it is *not* contaminated by position sizing the way ROI is. Our 195k observed wallet trades are
   enough to compute this. Demote `walletQuality` from 0.30 to a small tie-break weight until the replacement
   out-performs it on our own tape.
3. **Rebuild `categoryFit` on within-category accuracy, not win rate.** Keep the concept (it is the one
   component with real literature support: +5.5 pp for within-category concentration, +3.3 to +7.9 pp for
   category exposure), but compute it as *accuracy within the category relative to price*, so it stops being
   the same luck-contaminated statistic as the global leaderboard score (which is why it measured 72.7 vs
   76.5).
4. **Re-specify the price term as band × TTR, and stop penalising the longshot band on priors alone.**
   The evidence supports *conditioning*: arXiv 2607.14430 requires conditioning price-on-TTR (calibration is
   U-shaped, and the last 10 minutes are the worst regime); arXiv 2602.19520 says FLB widens with time to
   expiration. Replace `thesisScore = 100 − |p−0.5|×160` with an explicit `(band, TTR)` lookup learned from
   our own 9,600 finished trades — the only tape where the <$0.20 effect is measured *conditional on a
   premium-wallet copy*. Keep the v48 long-shot floor, but drive it from data rather than from a hand-set
   rule, and add a TTR floor so we never enter the final-minutes regime.
5. **Make hold-to-resolution the default and price the early-exit path explicitly.** Our tape (−$152.82
   closed vs +$180.64 resolved) and Wang's holding premium (93% event vs 58% trade win rate) agree. Either
   remove the `ttr<48 & p>0.80 ⇒ −10` penalty, or invert it — that configuration is the bond/hold setup
   Sharky6999 runs profitably (95% of trades above 80¢, held to completion). If an early-exit policy is kept,
   it should have to beat the hold baseline on our own data, and it should exclude the final-minutes window
   (arXiv 2607.14430).
6. **Demote or gate the two post-hoc boost terms.** `swarmCount ≥ 3 ⇒ +25` has **no direct published
   support** and is a larger single contribution than any component except `walletQuality`; it also inherits
   the leaderboard-proxy problem (swarming *leaderboard* wallets ≠ swarming *skilled* wallets). The nearest
   supportable analogue is order-flow imbalance (Gomez-Cram: 8 bp per 1 pp of skilled net buying) — so if
   swarm is kept, it should be restricted to wallets that pass the skill classifier and scaled, not flat
   +25. `sentimentDelta × scale` similarly has **no support found** in the prediction-market prediction
   literature; keep it as an experimental lane, not a score term.
7. **Reclassify spread and liquidity as cost control, not signal.** Both are well-evidenced, but as *costs*:
   removing even the minimum-tick spread moves 18.5% of losers to non-negative PnL (Akey), and gross
   calibration edges are wiped out by thin depth (polymarket-edge; Whelan's $526k top-decile volumes). They
   are currently measured as identical between winners and losers (90.3 vs 91.4) — consistent with the
   literature's framing that they set the *break-even bar*, not the *edge*. Keep them as hard gates; drop
   them from the weighted sum so they stop diluting the discriminating features.
8. **Treat size as conditional on wallet skill, and stop conflating two questions.** Akey: size is mildly
   *positive* among active users (+2.0 to +4.4 pp per log volume) — individual conviction. Whelan: size is
   *not* informative about market-level accuracy (largest-size quintile = most biased). Roosevelt: 63.2% of
   taker revenue flows to 6.3% of ≥$200 matched orders. So `tradeSize` should feed the score as a
   *conviction* signal for wallets that already pass the skill test, while the whale-size *cap* stays as an
   execution-quality guard.

### 3.3 Where we do NOT have evidence — do not over-fit to it

- **Swarm count.** No direct study. Currently carries a flat +25. Treat as an unvalidated hypothesis and
  A/B it against our own tape before trusting it.
- **Sentiment / regulatory-evidence delta.** No supporting study found. Absence of evidence, not evidence of
  absence — but it has not earned a score term.
- **Longshot sign.** Polymarket-v1 (≤0.30 overpriced) and polymarket-edge (longshots underpriced at T-7)
  directly disagree. Our +$176.77 on 102 sub-$0.20 trades is a *third*, much smaller estimate. Do not
  hard-code a direction from any one of them.
- **A wallet's edge half-life in days/hours.** No published figure exists. The literature's persistence unit
  is events/markets, not calendar time. Our own decision rows are the only way to estimate this.
- **The ~680M-trade dataset.** Unverified; superseded by the 1.2B-record Polymarket-v1 release.

### 3.4 Vendor-flagged sources (direction ≠ fact)

Wang (2026) *Smart Money on Polymarket* (uses polydata.pro aggregates; affiliation "not provided to SSRN"),
PolySyncer (a copy-trading product; its own conclusion recommends mirroring its leaderboard), CtrlPoly
dev.to piece (written to promote the author's copy-trading tool), and the Medium "configuration" posts. The
Stand/Polymarket *COPYCAT* interview is vendor-adjacent too, but it is published by Polymarket's own
newsletter and is unusually candid about the *failure* modes of copy trading (iceberging, merging, decoy
secondary wallets, bot slippage), which is why it is cited above for the negative evidence rather than for
any performance claim.

---

## 4. One-paragraph summary

The published record says a copied trade's outcome is predicted, in descending order of evidence strength,
by: **(1)** which side of the book the copied flow sits on — maker-side flow is the strongest single
cross-sectional predictor of profit (+9.0 pp/SD; makers −9.64% vs takers −31.46%), and a taker-by-construction
copybot is structurally on the wrong side; **(2)** whether the wallet's record reflects *statistical* skill —
only 12% of top-PnL wallets are in the skilled group and ~60% of lucky winners revert, so leaderboard PnL is
a poor proxy; **(3)** entry price and its TTR-conditioned calibration (FLB is real but sign-contested at the
longshot end; calibration is U-shaped in TTR and worst in the final minutes); **(4)** holding to resolution
rather than exiting early (93% event vs 58% trade win rate among top wallets; our own −$152.82 vs +$180.64);
**(5)** within-category specialisation (+5.5 pp, but only once category choice is conditioned out); and
**(6)** spread/liquidity as break-even costs rather than as edge (+18.5% of losers become non-negative if the
minimum spread is removed). The current score weights the *least* predictive axis most heavily and omits the
most predictive one entirely.
