# Reddit ingest — r/TrumpsTrades post into the sentiment feed

**Ingested 2026-10-18. Verified inert with respect to `copyScore`.**

## The item

- **Post:** `1x8gj91` · r/TrumpsTrades · u/hakansan · published 2026-10-17 17:50 UTC
- **Title:** *"Claude can scan news every hour and find potential beneficiaries held by Trump & Congress. Here's how (+ prompt)"*
- **Classification: tooling / how-to — not a political or regulatory event.** It documents a workflow: a paid Claude plan plus the **InsiderCat** connector (political + corporate insider trading data), then Claude scheduled tasks running an hourly news sweep joined against politician holdings, surfacing committee overlaps. The author's prompt is in the comments.

## How it entered the feed

The feed is not a text file — it is `RegulatorySignal` rows that the evidence adapter aggregates into a calibrated edge on `copyScore`. So the item went through the **same two artefacts the political-research-bot writes**, not a side channel:

1. **A/B log** — `local_sentiment.score_and_log()` → `data/sentiment-ab.jsonl`
   `{source: reddit_trumpstrades, item_id: reddit:1x8gj91, model: qwen3.5:9b, host: odin, rule_sentiment: null, local_sentiment: 0.0, local_confidence: 0.95}`
   `rule_sentiment` is `null` by design: no rule-based scorer exists for a Reddit source.
2. **Signal row** — `POST /api/webhooks/research-signal` → **HTTP 201**, `signalId cmvebde1300bm5clozb9dnr5z`
   `source=reddit_trumpstrades · marketCategory=Macro/Politics · sentimentScore=0.0 · confidence=0.95`, with the permalink/author/published/`item_class`/model reason in `rawPayload` for audit.

Model read: **sentiment 0.0, confidence 0.95** — *"describes a workflow/guide … does not constitute a market-moving political event."* (deterministic: identical on two separate runs, temp 0).

## Why this cannot move live copy scores

`aggregateSentimentForCategory()` selects only rows with **|sentimentScore| ≥ 0.3** (`opinionatedThreshold`). A 0.0 row cannot enter the evidence set, so its weight is exactly zero — regardless of `sentimentScale=100` and `sentimentMinSignals=1` in the active v62 ruleset.

**Measured, before → after** (`scripts/sentiment-edge-read.ts`, production call signature):

| Category | n opinionated | delta @ p=0.50 | delta @ p=0.15 |
|---|---|---|---|
| Macro/Politics | 134 → 134 | +0.12399 → **+0.12399** | +0.04757 → **+0.04757** |
| Crypto | 5 → 5 | −0.19083 → −0.19083 | — |
| Healthcare | 1 → 1 | +0.10537 → +0.105**36** | — |

`rows7d` for Macro/Politics went 226 → 227, confirming the write landed. Total rows 1968 → 1969. The global opinionated count stayed **140 → 140**.

**One honest caveat:** Healthcare (a category the insert cannot reach — the aggregation query is category-scoped) moved by **1e-5**, i.e. 0.001 copyScore points. I ruled out row turnover — it has exactly one in-window row (age 3.09 d; the next is 13.4 d, far outside the window) and no Macro/Politics row expired in the interval. The only remaining input is the wall-clock `now` inside `recencyFactor`, but my arithmetic for that term gives ~1e-9, not 1e-5, so **the 1e-5 is unexplained and I am not claiming otherwise.** Magnitude is a thousandth of a point; recorded here rather than smoothed over.

## The reusable part of the post

Its **prompt template**, not its sentiment: a 24 h news sweep (Reuters/AP/Bloomberg/CNBC/WSJ) joined to US government / Trump / Congress holdings, rendered as tables with committee-overlap flags. That is a candidate shape for our own news→holdings join, and it is why the card below exists.

**Card `insidercat-source-audit` (Backlog)** — the connector as a candidate source, with a gate: adopt only if it supplies ≥10 distinct opinionated Macro/Politics signals per 7d that `congress_gov_api` / `govinfo_fr_notice` / `quiver` do not already supply, and only if it needs no key we must hold ourselves. Otherwise it gets a measured NO-GO with the overlap numbers.

## Reproduce

- Scorer/ingest runner: `~/.hermes/cache/scratch/ingest_reddit_signal.py` (refuses to post a `|s| ≥ 0.3` score for a non-event unless `ALLOW_OPINIONATED=1`)
- Edge reader: `scripts/sentiment-edge-read.ts` (read-only; `npx tsx scripts/sentiment-edge-read.ts 0.5 0.15`)
- Post source: Reddit Atom feed (`/comments/1x8gj91/.rss`) — HTML and `.json` are walled for curl on this host; only Atom works.
