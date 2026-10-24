# Asset audit — `xyonium/reach-mcp`

**Verdict: WATCH** · audited 2026-10-23 · MIT · ★8 · alive (pushed today, CI green)
**Run it, don't vendor it** — and the only thing worth taking is one *taxonomy*, not code.

Dashboard: http://localhost:3013/drafts/asset-audit-reach-mcp-20261023

---

## What it is

A Python MCP server that fans a query out across 33 sources (Reddit, X, HN, GitHub,
arXiv, Polymarket, 微博/知乎/豆瓣/头条/雪球/V2EX/B站, YouTube, TikTok…) concurrently,
normalises the rows, dedups, scores them, and optionally runs an LLM rerank + cited
brief. It is a *search service for agents*, not a trading component — the boundary
is: running it in its own container and reading what it returns keeps our repo clean;
vendoring any of it in does not, and neither is warranted here.

Real substance by the anatomy: 434 KB of Python across 81 files (97% Python), 24 test
files, ruff+pytest CI, Dockerfile + published image, PyPI package, no lockfile.
README is 4,898 words against a 434 KB tree — claim size and code size are in the
same order of magnitude, which is rare on this beat.

## Anatomy facts that drove the verdict

- **Licence:** MIT — borrowable with attribution. Not the blocker here.
- **Activity:** created 2026-07-29, last push 2026-10-23 (today), ★8 / forks 0 /
  open issues 0. Single-author project with steady commits (2026-09-12, 10-01, 10-23),
  not dumped-once.
- **CI health (read off the API, not inferred):** `ci.yml` has 5 runs, **all
  `success`**, most recent 2026-10-23T09:14:28Z; `publish` and `Build and Push Docker
  Image` both green on 2026-10-01. No `action_required` runs. This is a maintained
  repo — the ★8 is a community signal, but maintenance here is real.
- **No GitHub releases/tags** (releases API empty) despite the PyPI badge and a
  publishing workflow — versioned distribution, no release notes.
- **Key surface is heavy:** `OPENAI_API_KEY` (LLM rerank/brief, and `synthesize`
  **defaults to true**, so the default path calls an LLM), `WHISPER_API_KEY`,
  `JINA_API_KEY`, `BRAVE_API_KEY`, `APIFY_API_TOKEN`, `REACH_MCP_API_KEY` (its own
  server auth), optional `GH_TOKEN`/`BSKY_*`. The *free core* — polymarket, hackernews,
  arxiv, reddit RSS, github-without-token — is keyless. Per our never-handle-keys rule
  this rules out adoption as a live-lane dependency; it does not rule out reading it.

## Verified machinery (re-derived in code, not off the README)

`src/reach_mcp/pipeline.py` is the whole deterministic core. `run_search` is 4 lines of
real logic (365-368): `dedup → score → cluster → sort`.

**Score** — `z = (v − mean) / pop_std` per source (population σ, divisor `n`), then
`factor = max(0.1, 0.5 + 0.5·z)`, `decay = max(0, 1 − age_days/max(1,days))`,
`score = factor · decay`. The engagement value is an unweighted **sum of every numeric
field** in `engagement`, so a source's upvotes and comments are added together as if
interchangeable.

Two of its own claims do not survive checking:

1. **The factor ceiling is wrong.** The code comment asserts *"z in [-1,1] -> factor in
   [0.1, 1.0]"*. Population z is unbounded: with one large value and n−1 small ones,
   `z_max = (n−1)/√n`. Recomputed from their own formula:

   | n | z_max | factor |
   |---|-------|--------|
   | 5 | 2.000 | 1.500 |
   | 10 | 3.000 | 2.000 |
   | 20 | 4.359 | 2.679 |
   | 50 | 7.000 | 4.000 |
   | 100 | 9.950 | 5.475 |

   On a realistic heavy-tailed volume-like distribution (Pareto 1.2, n=20) the factor
   spans **0.26–2.57**. The *floor* (0.1) is correct; the ceiling is not. Consequence:
   the stated design intent — "recency is the dominant signal within the window" — does
   **not** hold where engagement is heavy-tailed, which is exactly the Polymarket
   volume case. A viral item can carry 2.5–5× the multiplicative weight of an ordinary
   one and outrank recency by a wide margin.
2. **`dedup` never selects on score.** Its docstring says it keeps "the highest-scored
   representative", but `run_search` calls `dedup` at line 365, one line **before**
   `score` at 366 — so every `item.score` is `0.0` at dedup time and `it.score > cur.score`
   is never true. It keeps the **first-seen** row. Their own test does not catch this:
   `test_dedup_by_url` creates both same-URL items with the **default `score_=0.0`** and
   only asserts the resulting URL *set*, while its comment claims "keep the higher-scored
   one at that URL". The test asserts neither the score nor the ordering.

Also verified: `cluster()` groups on `md5` of a title stripped to `[a-z0-9 ]` — that is
**exact-match after normalisation**, not the "near-duplicate" the docstring claims
(`OpenAI ships thing` vs `OpenAI ships thing!!` match; `… ships thing tomorrow` does not).
Single-item sources get `std=0 → 1.0`, so `z=0 → factor 0.5` (confirmed against their
own test comment at `test_score_naive_date_gets_recency_decay_not_zero`).

**Polymarket adapter** — `sources/polymarket.py`. Search hits
`gamma-api.polymarket.com/public-search?q=`, strict-then-relaxed tail-drop of query
words. Its docstring records a live-verified venue fact: the naive `/markets?query=`
endpoint **ignores the query param**. I re-verified that against the venue today, not
off the comment:

- `GET /markets?query=zzzznonsense&limit=5` → HTTP 200, 28,669 bytes, sha256 `92e02e7d…`
- `GET /markets?limit=5` (no query at all) → HTTP 200, 28,669 bytes, **byte-identical sha256**
- `GET /public-search?q=fed&limit_per_type=3` → HTTP 200, 62,741 bytes of genuinely
  scored, query-matching events

So the donor's finding is **true on 2026-10-23**: text search on gamma must go through
`/public-search`; `?query=` silently returns the volume-sorted hot list. **This does not
apply to us** — grep of `scripts/ src/` for `markets?query` / `/markets?.*query=` returns
**0 hits**, and the one place we do gamma text search already uses the right endpoint
(`scripts/kalshi-crossvenue-read.py:388`, `/public-search?q=WTI%20Crude%20Oil`). Recorded
as an exoneration plus a tripwire, not as a gap.

**Data-loss note for a prediction-market consumer:** `_search()` passes the *event* to
`_market_row`, so every market inside a multi-outcome event gets `url =
polymarket.com/event/<event-slug>` — identical URLs — and `dedup` then collapses them to
**one row per event** (the surviving one is the highest-volume market only because the
list is sorted by `-volume` first). `fetch_trending` calls `_market_row(m)` with no
event and therefore keeps per-market URLs. As a market-discovery source this adapter
cannot return sibling outcomes of an event through the search path.

## Fit table vs our roadmap

| Donor component | Our state (verified) | Verdict | Owner |
|---|---|---|---|
| Typed per-source status `ok / no_results / rate_limited / gated_off / errored` + `notice` for degraded-but-working (`pipeline.py` `SourceReport`) | We have a **binary** `SOURCE FAILED — <label>` line per block, one ad-hoc Reddit state dict, and a single "not attempted — backing off after a 429" prose path. No typed enum, no `notice` field. | ✅ **adopt as concept** (reimplement ~60 LOC) | `fact-sheet-collector-truth` (open, Scheduled) — its gate literally reads *"FAILS IF: a block is left silent — a missing line is honest, a zero is not"* |
| `gated_off` as a state distinct from failure | 0 hits for gated/inert/plan/credential as a block state in `research-collect.py`. A GDELT plan-403 or an inert-by-env lane currently prints as **SOURCE FAILED**, i.e. "broken", when the truth is "blocked on the user". | ✅ **concept** — separates *fix me* from *you must act* | `fact-sheet-collector-truth` + `phase-gdelt` (the 403 lane's own note) |
| `PoliteClient` — per-host pacing, `Retry-After`, bounded exponential retries | We already have the behaviour, ad hoc: `REDDIT_PAUSE_S=3.0`, a 3-request budget/run, one 30 s backoff, stop-after-first-429, and 1/2/4 s retry in `update-pnl.ts`. | ❌ **not portable** — Python `httpx` vs our stack, and the capability is already present | `research-agent-recon-github-reddit` (Done) |
| Engagement z-score × recency-decay salience | Our radar ranks by **hard gates** (licence ≠ none, ★≥5, pushed ≤90 d), not a score. Any composite score we tried has a measured failure behind it. | ⚪ **concept only** — and the ceiling invariant is false as written; never into a composite | salience is owned by `market-to-news-lead-test` / `phase-gdelt`, where the 2026-09-18 TrendRadar audit already **measured and rejected** a hand-weighted salience score (component AUC 0.27–0.36 inside a 0.41 composite). Adds nothing there. |
| Canonical-URL dedup (`strip fragment, trailing slash, lowercase host, drop utm_*`) | Our dedupe is *semantic* — `(bot, wallet, market, outcome)` in `score-trades.ts` v52 — not content-URL based. No multi-source item stream to apply it to. | ❌ **no consumer** | none — no card asks for content dedupe |
| Near-dup title clustering | No use case; and it is exact-normalised matching, not near-dup | ❌ **not portable** | none |
| `adapt_query` — collapse a verbose question to a literal-AND source's core subject, pass through to semantic sources | Our queries are fixed `gh` search strings and RSS feeds; no literal-AND keyword source in the stack | ❌ **not portable** | none |
| `/public-search` vs `/markets?query=` venue fact | Already correct in our single gamma text-search call; 0 hits for the broken form | ⚪ **concept only** (tripwire + documentation) | none — nothing to fix |

## Integration proposal (the one thing worth doing)

**REC — typed block-level input-health sidecar for the fact sheet.**
Reimplement the donor's `SourceReport` taxonomy in `scripts/research-collect.py` as a
classifier over the blocks that already exist (dev.db, gamma, Kalshi, GitHub, Reddit,
arxiv, radar-yield, persistence): `ok | no_results | rate_limited | gated_off | void`,
plus a `notice` for "worked but degraded", written as **one JSONL row per block** to
`data/cache/research-recon/factsheet-status.jsonl`. The injected fact-sheet text does not
change in this stage.

- **Cost:** ~2 h. No dependency, no vendor code (MIT anyway), no new service.
- **Risk:** zero to the live lane — the collector is read-only by design and this only
  adds a sidecar write. Revert = delete the sidecar write and the JSONL.
- **Reversibility:** one function + one file; nothing in a decision path reads them.
- **Why now-ish rather than never:** the owning card's gate is currently judged by prose
  ("a block is left silent") and there is **no fact-sheet history** — only
  `factsheet-latest.md`, overwritten every run. A sidecar JSONL is the cheapest way to
  make that gate machine-checkable *and* to accumulate the evidence to read it.

## NOT portable

- **The LLM layer.** `synthesize=true` by default → OpenAI-compatible rerank + cited
  brief (`gemini-flash-lite` default model). We already run DeepSeek (research agent) and
  a local `qwen3.5:9b` sentiment lane on Odin; this duplicates both and would add a paid
  API call to a job that currently costs $0.
- **The MCP server itself** as a dependency: Python service, own auth key, 33 adapters,
  heavy credential surface — nothing here we cannot get from the endpoints we already call.
- **The CN-platform scrapers / Playwright adapters** (`zhihu`, `xiaohongshu`, `douban`,
  `bilibili`, Apify actors): irrelevant to Polymarket/Kalshi and a maintenance tax.
- **`score()`, `cluster()`, `Polymarket` adapter rows, `adapt_query`** — see the table.

## Honest caveats

- **I did not run their suite.** This job's constraint is read-only — no clone, no
  install, no execution — so the suite is judged by the *reported* CI state (5/5 green,
  latest today), not by my own run. That is the weaker of the two evidence tiers and I am
  naming it as such.
- **★8 / forks 0 / one author / no releases.** The code is real and the CI is real, but
  this is a personal-scale project with a bus-factor of one; nothing here should become a
  dependency of anything we run.
- **Their own quality signals are mixed.** Green CI and 24 test files on one hand; a test
  whose comment claims a property it does not assert, and a documented invariant its code
  violates, on the other. Take arithmetic and vocabulary from this repo; take no
  thresholds and no "verified" claims without re-deriving them (I found two that fail).
- **The interesting finding was already ours, inverted.** The donor's `/markets?query=`
  discovery is correct and we are already immune to it; the transferable value is the
  *status vocabulary*, which is a repair to an existing instrument, not a new capability.
  There is no alpha here — this is a coverage/observability donor.

## Registry block (paste-ready — not applied)

This job is recommendations-only and must not edit repo files, so the roadmap note is
left here for deliberate application:

```
AUDIT INPUT (2026-10-23, audit worker, recommendation-only; drafts/asset-audit-reach-mcp-20261023.md):
xyonium/reach-mcp (MIT, ★8, CI 5/5 green) is a multi-source search MCP server — no alpha,
no adoption. Its only transferable asset is a typed per-source status taxonomy
(ok|no_results|rate_limited|gated_off|errored + notice for degraded-but-working) which maps
1:1 onto THIS card's gate ("a block is left silent — a missing line is honest, a zero is not").
Proposed stage 0 (read-only, ~2h): classify each existing block in research-collect.py and log
one JSONL row per block to data/cache/research-recon/factsheet-status.jsonl; fact-sheet text
unchanged. Rationale: the gate is currently prose-judged and there is NO fact-sheet history
(only factsheet-latest.md, overwritten each run), so the sidecar is the cheapest way to make it
machine-checkable and to accumulate the read. `gated_off` matters specifically to phase-gdelt:
a plan-403 currently prints as SOURCE FAILED ("broken") when it is "blocked on the user".
Decision rule: after 14 runs (by 2026-11-06) read the JSONL — if >=1 block was gated_off or
void-with-rows in those runs and the same run's fact sheet carried no line about it, promote the
typed states into the fact sheet header; else drop. Revert: delete the sidecar write. NOT
portable: its LLM rerank/brief layer (duplicates DeepSeek + local qwen), the MCP server, the
CN-platform scrapers, score()/cluster()/adapt_query. Their score() comment claims
"z in [-1,1] -> factor <= 1.0" — false: z_max=(n-1)/sqrt(n) (n=20 -> 4.36, factor 2.68), so
engagement can outrank recency; their dedup() docstring claims "highest-scored" but runs one
line BEFORE score(), so it keeps first-seen (their test sets both scores to the default 0.0 and
asserts only the URL set).
```
