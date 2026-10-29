# Data-feed research — what to poll, what to scrape, what to start recording

**Date:** 2026-10-29 · **Author:** Hermes (ML data-feed research agent, first run)
**Instrument:** `scripts/data-feed-scout.py` → `data/data-feed-scout.json` + `drafts/data-feed-scout-2026-10-29.md`
**Scope:** candidate external feeds for the ML lane's *training* data and *decision* signal. Recommendations only — nothing here is applied.

---

## The reframe that governs everything below

The ML-1 era-stratified holdout says the model is not short of **capacity**, it is short of **information**:

- price-only **0.6704** AUC on the held-out era
- every wallet feature **loses** to it: `detected_price` +0.0001, `thesis` 0.5586, `entry_timing` 0.5197, `copy_score` 0.5172, **`wallet_quality` 0.4434** (worse than a coin flip)
- price itself fell **0.7592 → 0.6704** between eras

So the binding problem is **regime**, not coverage. That gives one hard filter for every candidate below:

> **A feed is only interesting if it is orthogonal to a price series we already hold.** More order-book data, more venue prices, or more transforms of the same book cannot help. What can help is what the market is a *bet on*: fixtures, injuries, news flow, bookmaker consensus, weather, schedules.

A second filter, because we are a trading lane and not a paper:

> **No look-ahead.** Any feed that only exists as a *revised* series (what the forecast said *after* the fact) is the single most common way an AUC is inflated and the inflation is invisible in the score.

---

## What the instrument found

**16 source probes: 13 ok, 3 FAILED** (all three Reddit 429 — throttling, not a block; reported rather than skipped).
Note on honesty: all 13 "ok" reads were served from a same-minute cache, so this run represents **one** real network pass, not 13 independent ones.

**48 candidates: 8 eligible · 20 review · 20 ideas-only.**

Licence mix across all 48: **25 permissive · 6 copyleft · 3 other · 14 none.**

**Known instrument limitation, stated rather than buried:** the `LEAK-FLAG` column matched **zero** candidates this run. It is a phrase-level detector (`"post-match"`, `"closing line"`, `"retrospective"`) run against titles and tags only — it does **not** screen dataset bodies. Leakage assessment here is **manual** and the flag list catches only the explicit cases. Do not read "0 leak flags" as "no leakage".

Two candidate-quality bugs were found and fixed *during* this run, because they were producing a list that looked plausible and was wrong:

1. **`injury` matched medical datasets.** The keyword retrieved road-traffic trauma, spinal-cord injury, OSHA and NEISS corpora — a different sense of the word entirely. Now requires sports context within 40 characters, with a wrong-sense blocklist.
2. **The search query was being scored.** Every hit inherited the words of the query that found it, so `sports results` produced twelve unrelated datasets at rel=4. Scoring is now on the dataset's own id + tags only.

Both are the same failure mode: an instrument that grades its own homework. Worth remembering when reading any future run.

---

## Recommendations

Four, ordered by expected value per hour spent. Each carries a decision rule and a refutation condition, because a recommendation without one is an opinion.

### REC 1 — Adopt Open-Meteo's `previous-runs` API as the weather substrate. Highest value, zero cost.

**What it is:** Open-Meteo publishes historical *forecast runs as they were issued*, not just the current revised analysis. That is the look-ahead fix for weather in one API call, free and keyless.

**Why I trust it beyond the pitch:** `openthomas/weather-forecasts` (MIT) is a **complete published weather desk** built on exactly this: 29,022 rows of as-of daily extremes from **seven** NWP models at leads 0–5 via Open-Meteo previous-runs, plus 5,600 rows of its own GraphCast/Pangu inference, GenCast ensemble spread, NBM/GFS-MOS baselines, and official settlements (ACIS / NWS CLI). Their replay rows carry "the settlement station and day, the baseline probability at the snapshot, the Kalshi bid/ask at that snapshot, and the outcome — never anything the agent could not have known at decision time." That is a working proof of the leak-free structure, from a party with no reason to help us.

**Cost:** free, no key, no licence (we pull it ourselves). Licence of *their* dataset is MIT, but the transferable asset is the **method**.

**Decision rule:** add NWP lead-0..2 daily extreme as a feature to the wx2 lane. Ship only if it improves settlement-direction accuracy by **≥5 pp** over the current baseline on **≥20 settled days**, measured out-of-sample on a time-ordered split.
**Refuted if:** Δ < 2 pp, or the sign flips across the two halves of the window.

**Lane:** A (it changes what the lane forecasts). Propose, do not apply.

---

### REC 2 — Start recording bookmaker consensus odds **now**, because no history exists to buy. Highest value later, worthless retroactively.

**What the lead actually said** (r/datasets, posted by `/u/OddsRelay`, i.e. **vendor advertising, not a neutral share**): free sample on HF of 15,820 matched pre-match prices across UK/Irish bookmakers, one snapshot taken 11 Oct, CC BY 4.0, joins on `event_id` + `bookmaker_key`. The feed itself carries **60+ UK and Irish bookmakers**, including Betfair, Smarkets, Matchbook and BETDAQ lays beside back prices.

**The two facts that decide this:**
- The vendor states plainly: **"There's no history or closing prices, in the sample or in the feed. Pre-match only."** So the sample is **useless as training data** — one snapshot, and the highest-value quantity (the *closing* line) is explicitly absent.
- Coverage mismatch: UK/Irish football, tennis, horse racing, darts — while our admitted book is overwhelmingly US sports, politics and crypto. Horse racing and darts have **no** Polymarket equivalent.

**So the only use is forward-looking:** poll the live feed, record as we go, and accept that the corpus is built at the speed of settlement. Start today or never.

**Decision rule:** record 60 days of pre-match consensus implied probability for markets existing on **both** venues. Recommend adoption only if the consensus-vs-Polymarket gap predicts settlement direction at **≥55 %** on **≥200 paired observations**.
**Refuted if:** ≤52 %, or paired markets number under 100 (insufficient overlap — then drop the lane rather than extend it).

**Cost:** paid tier (price unknown); free tier is 50k tokens / 14 days, enough to test the schema and the matching. Requires CC BY 4.0 attribution and a ToS read before any live dependency.

**Lane:** A (new paid dependency). Propose.

---

### REC 3 — Use the CC BY 4.0 half of `SuperAGI/llm-vs-prediction-markets-news` as the news-corpus *structure*, and treat its NC half as radioactive.

**What it is:** the exact news text each model saw at each forecast moment, price-blind, 5,317 texts from Common Crawl News, keyed by SHA-256 with article URL, site and capture time. `dnakhla/us-news-headlines-enriched` (CC BY 4.0, 100K–1M rows, headline + outlet + date + section + sentiment/NER) is the bulk training corpus that complements it.

**Why the structure matters more than the rows:** our `data/ml/decisions.parquet` stores decisions but not *the news text as it stood at decision time*. These datasets demonstrate the right shape — text stored once, referenced by checksum, with a capture timestamp. Adopting that shape is what makes news features leak-free by construction rather than by discipline.

**The landmine:** `window_a/texts.parquet` (1,141 rows, the news PolyBench fetched at each forecast moment) is **CC BY-NC-SA 4.0** — *NonCommercial*. A lane that trades real money is a commercial use. **`window_a` must be excluded from anything that feeds the live lane**, and is usable only as research/eval input. This is not a judgement call; it is the licence.

**Decision rule:** train a headline→event-type classifier on the **CC BY 4.0 split only**; add its outputs as features only if era-split AUC beats price-only **0.6704** by **≥0.01** out-of-sample.
**Refuted if:** Δ ≤ 0, or the improvement vanishes when the classifier is retrained on a later era (i.e. it is regime-fitting, the same decay that hit price itself).

**Lane:** A (feature set). Propose.

---

### REC 4 — Use the prediction-market corpora as a **recorder audit**, never as features.

The registry is full of prediction-market datasets: `manja316/crypto-prediction-market-signals` (CC BY 4.0, 15-min BTC/ETH/SOL OHLCV + funding + OI + 99 Polymarket crypto markets, auto-updating), `iiiitips/prediction-market-pro-stats`, `thomaswmitch/kalshi-prediction-markets-betting` (MIT), `lowskillcoding/pdata-prediction-markets`, `rhinot/prediction-market-analysis`, `SuperAGI/llm-vs-prediction-markets`.

**They cannot be features.** They contain Polymarket/Kalshi probabilities, which is the quantity we predict *from*. Training on them is leakage with extra steps. But they are useful for a different job: **independent replication of our own booked numbers.** We already know the recorder has a drift problem — the localisable export drift of **$0.0496** in `pnl_net_full`, traced to exit-side `currentPrice` recomputation on 7,702 early-closed positions. An external copy of the same markets is a cross-check that does not share our bug.

The genuinely orthogonal columns in `manja316` are **funding rates and open interest** — external capital-flow signal, not our order book.

**Decision rule:** replicate our settled PnL against their rows for overlapping markets. Investigate our recorder if the two differ by **>2 %** on **≥100** overlapping markets.
**Refuted if:** difference ≤0.5 % on ≥100 overlapping markets — then our recorder is fine and this instrument retires.

**Lane:** B (data-integrity instrument, no change to decisions). Can be built and verified.

---

## Rejected, with reasons

- **`howitspread` viral events (1,309 events / 19,732 dated timeline rows, CC BY 4.0, rel=8 — our top-scoring candidate).** Rejected despite the score. The author states the disqualifier themselves: *"everything in it went viral, so it can't tell you the odds of going viral."* That is **selection on the outcome** — no negatives, so no base rate, so no decision boundary can be learned. It also answers a question we don't ask. Timelines are LLM-compiled with a partial verification column. A high relevance score on an unusable dataset is a score of *topic*, not of *fitness*.
- **`electricsheepafrica/...polling-stations...` (CC BY-SA 4.0, rel=5).** Static geography for Mauritius. No market overlap.
- **All 20 `ideas-only` candidates.** Six are copyleft and fourteen have no licence at all. Per standing rule, no-licence means read-for-ideas, GPL/AGPL cannot become a dependency of the live lane. Several are worth reading for design questions; none are adoptable.
- **arXiv q-fin.TR and stat.ML feeds.** Both returned 0 relevant entries this run (small feeds, no dataset-releasing papers in window). Worth keeping in the rotation — a paper that releases its data carries its own licence and its own look-ahead caveats, which is better provenance than any registry.

---

## What is genuinely still missing (and no dataset fixes)

The honest gap: our price-only model *decays between eras* (0.7592 → 0.6704). No amount of new features fixes a decaying regime if the decay is in the market structure rather than the features. Before spending on REC 2 or REC 3, it is worth answering whether the era decline is (a) harder markets, or (b) our features aging. One held-out era (n=852) cannot separate those — that is the open `ml1-fit-population-gaps` card, and it is upstream of every recommendation above.

**Recommended order of work:** REC 1 first (free, fast, leak-free by construction, and it lands on a lane that already has a prereg). REC 4 second (cheap instrument, possible recorder win). REC 3 third. REC 2 last, and only if the coverage question is answered — otherwise we pay for a feed covering horse racing and darts that Polymarket does not list.

---

## Reproduce

```
.venv-ml/bin/python scripts/data-feed-scout.py            # both families
python3 scripts/data-feed-scout.py --sources reddit       # 429s after ~1 feed/min, cache covers repeats
python3 scripts/data-feed-scout.py --dry-run --top 20     # print, write nothing
```
