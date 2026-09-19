# TrendRadar audit — sansan0/TrendRadar (adoption fit for the copybot signal stack)

**Audit date:** 2026-09-18 · **Requested by:** user ("audit this repo and see how we can use this news aggregator
to enhance our signals") · **Method:** `github-repo-audit` skill; metadata via GitHub API, shallow clone at
`/tmp/trendradar`, formulas read line-by-line in source, capability gap verified by grep in our own repo.

> Dashboard: this file is served at `/drafts/trendradar-audit`.

---

## 1. What it is

A self-hosted **public-opinion / hot-list aggregator**: it crawls platform "hot lists" (Weibo, Zhihu, Douyin,
Baidu, Toutiao, Bilibili, …) plus arbitrary **RSS/Atom** feeds on a schedule, dedupes items, accumulates a
temporal history per item, filters by keyword groups, optionally enriches with an LLM, and pushes digests to
~8 chat channels. It also ships an **MCP server** so an LLM client can query the accumulated news DB.

| | |
|---|---|
| License | **GPL-3.0** → read-only. Separate service or reimplement concepts; copy NO code into our repo |
| Language / size | Python 3.12+, 34.5k LOC, 24 MB, 162 files |
| Stars / activity | 62,379★ · pushed 2026-09-13 · 58 open issues · not archived |
| Tests | **none** (`[dependency-groups] dev = []`; only a manual `commands/test_notification.py`) |
| Runtime deps | `fastmcp`, `feedparser`, `litellm`, `requests`, `PyYAML`, `websockets`, `boto3`, `json-repair`, `tenacity` |
| Packaging | `pyproject.toml` (hatchling) + Docker + setup scripts for mac/win |

The 62k stars are a **consumer-app** artifact (Chinese social virality + a Cherry Studio companion doc), not a
trading-relevance signal. Treat it as useful scaffolding whose every claim you re-verify.

## 2. Verified machinery

### 2a. The data model is the valuable part — per-item attention *time series*

`trendradar/storage/schema.sql`:

- `news_items(title, platform_id, rank, url, mobile_url, first_crawl_time, last_crawl_time, crawl_count)` with a
  unique index on `(url, platform_id)` → dedupe by story, not by crawl.
- `rank_history(news_item_id, rank, crawl_time)` → **the rank of the same story at every crawl**.
- `title_changes(news_item_id, old_title, new_title, changed_at)` → the story's headline evolving over time.
- `crawl_records` / `crawl_source_status(..., status IN ('success','failed'))` → per-source health.
- Separate `rss_*` and `ai_filter_*` schemas for feeds and LLM tags.

This is the primitive our news lane does not have. Our `RegulatorySignal` is
`(source, marketCategory, sentimentScore, confidence, rawPayload, processedAt)` — a **point estimate per
category**, with no marketId, no series, no rank, no corroboration count. GDELT gives tone/significance/geo per
story; it does not give us *how long a story stayed salient* or *how many sources carried it*.

### 2b. The attention score (`trendradar/core/analyzer.py:17`)

```python
for rank in ranks:                       # ranks = item's rank at each crawl it appeared in
    rank_score_sum  += 11 - min(rank, 10)          # rank 1 -> 10 … rank ≥10 -> 1
    high_rank_count += (rank <= rank_threshold)    # default threshold 5
rank_weight      = (rank_score_sum / len(ranks)) * 10      # 10..100
frequency_weight = min(count, 10) * 10                     # 0..100, saturating
hotness_weight   = (high_rank_count / len(ranks)) * 100    # 0..100
total = 0.6*rank_weight + 0.3*frequency_weight + 0.1*hotness_weight
```

Defaults `RANK_WEIGHT 0.6 / FREQUENCY_WEIGHT 0.3 / HOTNESS_WEIGHT 0.1`, overridable at
`config.yaml → advanced.weight.{rank,frequency,hotness}`. Three 0–100 terms, linear combination.

**Math audit (honest):**
- It is a **ranking heuristic, not a calibrated quantity** — no probabilities, no fitting, weights hand-set.
- **No recency decay.** A story that trended 6 hours ago and returned scores identically to one trending now;
  "frequency" and "hotness" are both all-time fractions of appearances. For a *lead-time* signal this is the
  main deficiency — our own use needs velocity/decay, which we would add.
- **Saturation caps**: `min(rank,10)` flattens everything below rank 10 (rank 12 scores exactly like rank 10);
  `min(count,10)` caps persistence at 10 crawls.
- **The same function exists three times** (`core/analyzer.py:136`, `core/loader.py:170`,
  `mcp_server/tools/analytics.py:36`) → drift risk if we ever took it as a dependency.

### 2c. The rest of the pipeline

- **Keyword rule engine** (`core/frequency.py`, `config/frequency_words.txt`): word groups, required `+word`,
  excluded `!word`, `[GLOBAL_FILTER]` block, regex `/a|b/`, display alias `word => Alias`, per-group max. Richer
  and more testable than the ad-hoc category matching we do today.
- **RSS is first-class** (`rss.enabled: true` by default; `feedparser`; freshness filter) — so it can be pointed
  at *our* feeds, not just Chinese hot lists.
- **MCP server** (`fastmcp`) exposing `get_latest_news`, `get_trending_topics`, `get_latest_rss`, `search_rss`,
  `resolve_date_range`, plus platform/feed/keyword/date resources → an LLM can query accumulated news natively.
- **LLM layer** (litellm): interest-based filter, translation, analysis brief.
- **Notification layer**: WeChat / Feishu / DingTalk / Telegram / email / ntfy / bark / Slack (no Discord).

## 3. Capability-gap check in OUR repo (verified, not asserted)

Greps over `src/`, `scripts/`, `data/roadmap.json`:

| primitive | in our stack today |
|---|---|
| RSS / `feedparser` ingestion | **absent** (only the phrase "RSS" in a roadmap note) |
| hot-list / trending tracking | **absent** |
| per-item rank or persistence history | **absent** (no `rank_history`, no attention series) |
| MCP server of our own | absent (we *consume* GDELT MCP) |
| news → evidence lane | **exists**: `political-research-bot/src/gdelt_shadow.py` → `data/gdelt-shadow.jsonl` (dual keyless-DOC + GDELT Cloud), 6-hourly, 148 rows / 6 categories, shadow only |
| research ingest | Quiver congressional trades, Congress.gov, GovInfo → `RegulatorySignal` webhook |

So the gap is real and specific: **we have sources and sentiment, we have no salience/persistence layer.**

## 4. Fit table vs roadmap

| Component | Adopt? | Where it lands |
|---|---|---|
| `news_items` + `rank_history` + `title_changes` schema, and the persistence/corroboration concept | ✅ **concept only** (reimplement, ~50 LOC; GPL means no copy) | `phase-gdelt` (OSINT feed) + `data2-per-decision-provenance` |
| Attention score as an **evidence-confidence modifier** (`sources_agreeing`, `best_rank`, `persistence_hours`) | ⚪ shadow-measure first | `phase-gdelt` A2 evidence tier |
| Trending topics + keyword groups as a **salience router** (which markets deserve an evidence look) | ⚪ strongest idea — addresses the measured A2 *coverage* problem (sentiment touches 148/191k decisions = 0.08%) | `phase-gdelt`, feeds `phase-ml2` |
| RSS reader + freshness filter | ✅ concept only | `presidential-socials-lane` (Truth Social RSS), `phase-data1` |
| MCP server as a **dependency** | ❌ | — (expose our own later; consuming theirs as a service is fine) |
| litellm AI filter/translate/summarize | ❌ | we run DeepSeek + local Ollama |
| Notification senders (no Discord) | ❌ | we have Hermes cron → Discord |
| Chinese-platform scrapers, HTML report generator, `boto3` remote sync | ❌ | irrelevant to Polymarket |

## 5. Integration proposal (shadow-first, measurement-gated)

Everything below is **analysis and shadow only**; wiring into evidence follows the lane's existing
post-Phase-B gate. Licence-safe by construction: the service runs in its own container and we read its output —
no GPL code enters our repo.

1. **Stand it up as a separate service (~2-3h, no integration).** Docker on the homelab/Mac mini, RSS +
   hot-list enabled, keyword groups written for *our* subject space (election, nominee, fed, cpi, tariff,
   ceasefire, court, shutdown…). Its own SQLite; klipper-style "separate process, own data" boundary.
2. **Read-only shadow reader (~1 dev-day).** Extend `political-research-bot` with a small script that pulls
   TrendRadar's SQLite and writes **our** schema to `data/attention-shadow.jsonl`:
   `{ts, topic_key, url, sources[], best_rank, crawl_count, persistence_hours, first_seen}`. Our file, our
   schema, no GPL code, same shadow pattern as astro/odds/manifold/gdelt.
3. **Measure before believing (~1-2 dev-days, analysis-only).**
   - *Coverage lift*: what fraction of markets gain an evidence row that has none today (the A2 reach fix).
   - *Lead test*: do attention spikes precede price drift **beyond the price-only baseline** — market-clustered
     bootstrap CIs, time-ordered + era-aware splits (per the ML-doctrine card). The null we should expect and
     report honestly: attention is *already* in the price, so the only interesting result is a lead in
     minutes-to-hours, or a *routing* gain (finding markets) rather than a ranking gain.
   - *Corroboration test*: does `sources_agreeing` add anything to win-probability beyond the price?
4. **Only if step 3 lifts:** feed attention as an A2 evidence-tier *confidence* input (never a price delta),
   shadow → paper, flag-revertible.

## 6. NOT portable (explicit)

- The AI analysis/translation layer (litellm) — duplicates our DeepSeek research bot + local-LLM sentiment.
- All notification senders (no Discord; our delivery is Hermes cron → Discord).
- The Chinese-platform scrapers — fragile, GPL, and irrelevant to Polymarket market subjects.
- HTML report generator, remote (boto3) storage sync, the container's own MCP server.
- The attention score **as a score we trust** — uncalibrated, undecayed, hand-weighted. If it ever enters
  `copyScore` unvalidated it repeats the `thesisScore` failure (a component that measures AUC 0.27–0.36 against
  outcomes inside a composite that measures 0.41).

## 7. Honest caveats

- **No test suite upstream.** Nothing here has been validated by its authors beyond use. Everything we take is
  re-derived by us (the ~50 LOC schema + score are small enough to own outright).
- **Source mismatch.** The default platform list is Chinese consumer hot lists; the transferable asset is the
  tracker/reader, not the sources. Point it at RSS, or the signal is noise for our markets.
- **Point-in-time bias.** Its history starts when *we* start crawling; there is no backfill, so any historical
  test has to accumulate forward (2-4 weeks for a first read) before it can be measured.
- **GPL-3.0 boundary.** Running it as a separate service and reading files it writes is fine; linking or copying
  its code into our repo is not. Keep the boundary explicit or don't do it.
- **The repo's own highest-value idea, restated:** it is not an alpha source. It is a **salience router** — a way
  to decide *which* markets deserve an evidence look. Our binding problem is measured reach (0.08%), not
  sentiment quality.

## 8. Verdict

**Audit now, adopt later, concept-first — do not integrate as a dependency.**

- The two things worth taking are the **attention time-series schema** and the **keyword/frequency rule engine
  concept** — both reimplemented in our own code, ~150 LOC, no licence entanglement.
- The one thing worth *running* is the aggregator as a **separate shadow service** pointed at our RSS feeds, to
  attack the A2 coverage problem and to accumulate an attention series for the lead test.
- Sequencing: it belongs **behind the same post-Phase-B gate** as the rest of the news lane, and it is a
  *measurement* item first. Nothing here justifies touching the live scorer during the Kelly window.
- Cost of being wrong is low (a container + a JSONL); cost of integrating it as a dependency is a GPL boundary
  and an uncalibrated score in our composite. Take the first, not the second.
