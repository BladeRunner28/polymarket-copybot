# Audit: arnaudknobloch/awesome-polymarket — adoption fit for Medusa CopyBot

**Date:** 2026-10-24 · **Auditor:** Hermes asset-audit cron · **Method:** GitHub API metadata for the
list and for **every GitHub-hosted entry it carries** (25/25 resolved off the API today, not off the
blurb), README read in full and parsed for a census (115 entries / 75 hosts), the list's own CI run
history and job logs read off the Actions API, its fee convention re-derived from the notebook that
actually uses it and reconciled against the venue fee page, then each entry cross-checked against
`drafts/`, `data/roadmap.json`, `data/research-asset-queue.json` and `data/radar-yield.jsonl`.
No clone, no install, no execution of candidate code. Scratch: `/tmp`-equivalent scratch dir, nothing
referenced after this write.

## Verdict

**DROP as an asset; WATCH one harvested lead.** It is a docs-only curated index (2 `.md`, 26 KB, no
code, no tests, CC0-1.0) whose entire value proposition is "**every link was checked**". That
proposition is falsified by the list's **own CI**: 37 of 49 Actions runs since creation are red, the
last scheduled run (2026-10-19) failed on a repo that is still listed and still 404s today, and 7 PRs
were admin-merged in a ~20-second batch on 2026-10-24 while their link check was red or unapproved.
The deliverable is therefore a **triage**, exactly as with `awesome-trading-agents` (2026-10-15):
18 of its 25 repos are new to our record, 3 are alive+licensed+★≥5, **1 is worth the pipeline**
(`mileswangs/pm-hftbacktest`, queued `watch`), and the rest fail on licence, dormancy, or being a
sales page.

## 1. What it is

A "link-verified" curated list of Polymarket tooling — copy-trading engines, market-making bots,
whale trackers, wallet scoring, SDKs, datasets, MCP servers. Created 2026-08-11, ★5 / 25 forks,
111 KB, **Markdown 100%**, CC0-1.0, not archived, last push 2026-10-24.

| Metadata (GitHub API, 2026-10-24) | |
|---|---|
| Licence | **CC0-1.0** → content reusable without restriction (there is no code to reuse) |
| Stars / forks / issues | 5 / 25 / 1 open |
| Created / last push | 2026-08-11 / **2026-10-24** (alive, unlike the trading-agents list) |
| Tree | 6 files: `README.md` 24.5 KB, `CONTRIBUTING.md`, `LICENSE`, `check-links.sh`, `.github/workflows/check-links.yml`, `.gitattributes`; `tests=NO` |
| Entry census (computed from the README, TOC lines excluded) | **115 entries**, 18 content sections, 75 distinct hosts |
| Entry mix | **25 GitHub repos** · 66 commercial product/service sites · 7 npm/PyPI packages · 3 Chrome Web Store + 2 HF datasets + 3 docs/news/official |

Nothing here is code we would run. The auditable question is not "does it work" but "**is its
curation signal worth anything, and did it surface anything we don't already have**".

## 2. The claim, and where it breaks

README line 7: *"Every link here was checked on 2026-08-11. Entries that 404 … have been removed
rather than carried forward."* Line 216: *"Every entry is checked before merging, and re-checked
periodically."*

| Check | Result |
|---|---|
| Is the date literal? | **No** — 2026-08-11 is the repo's **creation** date. Entries were added as late as today, so the banner is 74 days stale by construction, not a rolling verification date. |
| Does the periodic check run? | Yes: `check-links.yml` on `cron: 0 6 * * 1`. **8/10 scheduled runs succeeded** (2026-08-17 → 2026-10-12); failures 2026-09-21 and **2026-10-19**. |
| What did the last scheduled run find? | Job log, `Checking 107 links in README.md`: 15 WARN (403 bot-protection: npmjs, reddit, twitter, substack, dune — expected from a datacenter IP) and **one DEAD: `404 https://github.com/softdevfz/polymarket-kalshi-price-gaps`**. |
| Is it still listed? | **Yes.** It is entry #1 of *Data APIs & Datasets* today, and `GET /repos/softdevfz/polymarket-kalshi-price-gaps` returns **404** (the repo is gone, not renamed-visible). Red CI has been ignored for 5 days. |
| Is the merge gate real? | **34 of 37 PR runs failed**, 1 `action_required`, 2 success. On 2026-10-24T08:36 the maintainer merged PRs #26, #28, #31, #32 and three others **within ~20 seconds** — including #32, whose own link-check run (02:40, `failure`) is the one that could not run a job at all (`total_count: 0`). |
| Does the list stay current? | 117 unique URLs today vs **107** when CI last ran six days ago — ten links have never been checked by the gate. |

**So the mechanism is real but the gate is bypassed.** A working link check is a good idea; this one
runs weekly, flags dead hosts honestly, and is then merged over. This is the "claim-only README"
pattern the skill warns about, one tier milder than usual: the CI exists, it is just not binding.

**Second gap: link-works ≠ project-alive.** The checker only tests HTTP status. Two entries are
official Polymarket repos that have not been touched since **2024** (`Polymarket/agents` ★3,803,
pushed 2024-11-05; `Polymarket/poly-market-maker` ★326, pushed 2024-07-05) and are presented with no
dates beside live tools. A reader would reasonably assume they are current.

**Third gap: the blurbs are not the sources'.** Entry text for `LuciferForge/polymarket-historical-data`
reads *"19M+ snapshots across 19,300+ markets"*; the repo's own README says **18.6M+, 22,410 markets**
and its coverage table says 18,611,636 price rows. The listing's numbers match neither.

## 3. Concentration: who is stuffing this list

Six of the 25 GitHub entries (**24%**) come from a single account, `LuciferForge` — and five of the
six are new to our record:

| Repo | ★ | Licence | Last push | Size | What it actually is |
|---|---|---|---|---|---|
| polymarket-settlement-bot | 5 | MIT | 2026-03-14 | 7 KB | auto-redeem loop |
| polymarket-odds-scanner | 3 | MIT | 2026-06-21 | 18 KB | sportsbook-vs-PM scan |
| polymarket-pnl | 8 | MIT | 2026-06-21 | 11 KB | CLI P&L print |
| polymarket-api | 0 | MIT | 2026-04-28 | 15 KB | REST wrapper |
| polymarket-historical-data | 0 | MIT | 2026-07-05 | 44 KB | **a sales page** (below) |
| polymarket-mcp | 0 | MIT | 2026-05-26 | 182 KB | MCP wrapper (already known to us) |

24% of the code entries being one author's 7–44 KB scripts is the direct consequence of a gate that
only asks "does this URL resolve". No referral/affiliate parameters appear in any of the 115 entry
URLs (checked: 0 hits for `ref=|aff|utm_|invite|partner`) — the stuffing is by submission, not by
tracking links. That distinction is worth stating: this list is **not** an affiliate honeypot, it is an
unguarded one.

## 4. The one entry with a substantive claim: `pm-hftbacktest`

`mileswangs/pm-hftbacktest` — MIT, ★126, 25 forks, created 2026-05-06, pushed **2026-10-22**, 155 MB,
202 blobs: 900 KB Rust, 310 KB Python, 5.8 MB of notebooks, 793 KB PNG, and 12 KB of committed
`.DS_Store`.

**What it is:** a **fork of `nkaz001/hftbacktest`** (★4,971, MIT, pushed 2025-12-23) — same workspace
shape (`hftbacktest/`, `hftbacktest-derive/`, `py-hftbacktest/`, `collector/`, `connector/`,
`readthedocs`), same `README.rst` voice, same generic fee/latency/queue model modules — with two
Polymarket additions:

- `py-hftbacktest/hftbacktest/data/utils/polymarket.py` (9.4 KB): book/trade frames → `hbt` event
  arrays, `POLY_MIN_PRICE 0.0 / POLY_MAX_PRICE 1.0`, 20 ms default latency;
- `BacktestAssetPoly`: tick 0.001, lot 0.001, `risk_adverse_queue_model()`, ROI bounds 0–1, and the
  docstring is explicit that **"Data, latency, and fee model remain configurable"** — i.e. it sets
  nothing fee-related.

**Claim re-derivation — "Built-in Polymarket fee model": false as a library feature.** The only fee
code in the tree is upstream's generic `TradingValueFeeModel` / `TradingQtyFeeModel` /
`BinaryFeeModel` / `FlatPerTradeFeeModel` in `hftbacktest/src/backtest/models/fee.rs` (7,187 B; upstream's
equivalent is 4,393 B, so the fork added models but no Polymarket curve — grep for `p*(1-p)`, fee-rate
tables or category coefficients across `.rs` and `.py` returns nothing). The Polymarket curve appears
only as **user code in `example/endline.ipynb`**:

```python
taker_fee  = 0.07 * enter_price * (1 - enter_price)
marker_fee = -taker_fee * 0.2
BacktestAssetPoly().data(data).trading_value_fee_model(marker_fee, taker_fee)
```

**And those numbers are right — verified against the venue, not against the README.**
`docs.polymarket.com/trading/fees` (fetched today): `fee = C × feeRate × p × (1 − p)`, makers never
charged, and the published table gives **Crypto taker 0.07 / maker rebate 20%**, Sports 0.05/15%,
Politics-Finance-Tech-Mentions 0.04/25%, **Geopolitics 0** (fee-free), Combos 0.05/0%.

That is a **three-way agreement** on our own fee law: venue page ↔ donor notebook ↔ our
`takerFeePerShare(price, rate) = rate · p · (1 − p)` (`src/lib/scoring/price-edge.ts:56`) with
crypto 0.07 / politics-finance 0.04 / default 0.05 (`categoryFeeRate`, :65–74), and our captured
`rebateRate 0.2` (`scripts/capture-fee-schedules.ts`, from the gamma `feeSchedule`). Independent
corroboration of a measured law is the cheapest honest quality signal there is — but note what it is
*not*: new information. We already encode all of it.

The one nuance worth naming: modelling the rebate as a **negative fee at match time** is an
approximation. The venue pays the maker rebate as a *daily redistribution* to liquidity providers,
not as a discount on each fill — so a small maker's realized rebate can be less than 20% of the fees
on their own fills. Their form and ours (`rebateRate` captured, deliberately "not modelled" per
`scripts/kalshi-pm-btc-pair-sampler.py`) bracket the same fact; neither is a defect.

**Attribution defect:** `LICENSE` in the fork reads `Copyright (c) 2026 mileswangs` — upstream's MIT
copyright line is gone while upstream code ships unchanged in `hftbacktest/`, `hftbacktest-derive/`
and most of `py-hftbacktest/`. MIT requires retaining it. Not a blocker for reading ideas; a blocker
for treating the repo as a maintained upstream.

**Data is key-gated:** the README's "**Free** Polymarket tick data from `pmdata.dev`" requires
`Get an API key from pmdata.dev before running the example`. The vendor page **could not be fetched
from this host** (security scan blocked the request; the extractor backend cannot fetch URLs), so its
coverage, latency and licence are **`unverified`** — do not repeat the "free tick data" claim as fact.

## 5. Fit table against the roadmap

Cards read from `data/roadmap.json` (236 cards) today.

| Component | Card that asks for it | Verdict |
|---|---|---|
| Tick-level queue-position + latency fill simulation (`risk_adverse_queue_model`, `BacktestAssetPoly`) | **`phase-d2-fill-model`** ("P(fill within Δt) from book context … borrow methodology over data/l2/ books") | ⚪ **concept only** — the card already owns this and already names two donors (homerun AGPL, FlashAlpha MIT). A third methodology input adds little; the queue model's real value is the explicit *latency + queue* pair, worth quoting into the D2 note, not a dependency. |
| `polymarket.py` book/trade → event converter (9.4 KB) | none | ⚪ reimplement if D2 ever needs a Polymarket-shaped L2 event stream; our `data/l2/` recorder already emits our own schema. |
| Polymarket fee curve + category table | `bt-fee-maker-calibration` (Done) | ❌ **not portable** — we have the exact curve and the category map; the donor's version is notebook code, and its rebate sign convention is an approximation of a daily redistribution. Value = corroboration, recorded above. |
| `pmdata.dev` tick feed | none (Data-1 is venue-gap feeds, not PM tick history) | ⚪ **watch** — only if the feed is real and keyless-ish; see REC 1. |
| The rest of the repo (crypto collectors for Binance/Bybit/Hyperliquid, Numba stats, notebooks) | none | ❌ out of lane (CEX HFT), 155 MB of it, and a divergent fork. |

The audit's own negative finding: **no gap in our fee handling was found** that this repo closes.
`price-edge.ts` matches the venue page formula-for-formula, and `categoryFeeRate` matches the 0.07 /
0.04 / 0.05 rows. The map is **not** complete on one row — see §7 — but that gap was invisible from
this repo's code and only became checkable by reading the venue table it pointed at.

## 6. Triage of the other 24 GitHub entries (claim → API → verdict)

Known to us (7) — no action: `Polymarket/agents` (★3,803, dormant since 2024-11-05),
`warproxxx/poly-maker` (audited `drafts/poly-maker-audit.md`), `pmxt-dev/pmxt` (weekly + `kazelad-pm-sdk-audit`),
`0xinsider/research` (`drafts/autoresearch-audit.md`), `LuciferForge/polymarket-mcp`
(`polymarket-mcp-server-audit-2026-09-07`), `predgeAI/whale-data-mcp` (in radar-yield),
`YichengYang-Ethan/oracle3` (we **vendor** its WangMLE).

| Entry | API facts (2026-10-24) | Verdict |
|---|---|---|
| `Polymarket/poly-market-maker` | MIT, ★326, **pushed 2024-07-05** | ❌ dormant 2+ yrs, live-execution surface (paper-only here) |
| `AndreySchurko/garnet-polymarket` | **NOASSERTION** (licence "Other"), ★4, 2026-10-02, Rust 1.5 MB | ❌ licence not assertable → read-only; and same primitive as our sidecar |
| `kachence/polymm` | MIT, ★113, 2026-08-16, 489 KB, 124 `.py` — "the retired code behind a public $5k wallet" | ⚪ out of lane (sportsbook de-vig + MM, needs sportsbook odds); honest self-documentation of a *retired* strategy is a good sign, not a fit |
| `floor-licker/polyfill-rs` | Apache-2.0, ★232, 2026-09-12, Rust 3 MB | ⚪ not portable now: paper lane, no execution, and our sidecar's CLOB path is not latency-bound |
| `oraclemangle/polymarket-bot-lab` | Apache-2.0, ★1, 2026-07-29, 2.2 MB | ⚪ ★1 lab of 11 strategies — idea-level only |
| `mileswangs/pm-hftbacktest` | MIT, ★126, 2026-10-22 | **✅ lead — queued `watch`** (§4) |
| `testedmedia/polymarket-weather-command-center` | Apache-2.0, ★4, 2026-07-13, TS 4.6 MB | ⚪ weather lane exists and is carded; a 4★ dashboard is not the missing piece |
| `PredictionMarketTrader/openthomas` | MIT, ★25, 2026-09-12, 7 MB, `pip install openthomas` | ⚪ weather/temperature agent; overlaps the carded weather lane — measurement first, not adoption |
| `elielieli909/polymarket-marketmaking` | **no licence**, ★59, **2021-08-19** | ❌ unlicensed + dead |
| `JDSource/clearmarket` | MIT, ★3, 2026-10-24, 19.7 MB Python | ⚪ too new/unproven (★3), resolution-logic parsing is interesting, not auditable yet |
| `yntymacho/polymarket-honest-tools` | MIT, **★0**, 2026-06-28, 102 KB TS | ⚪ the *idea* (validate whether a wallet's edge survives realistic fills/fees before copying) is our copyability gate in different clothes; ★0 + 102 KB = read-for-ideas |
| `vahnxu/signalradar` | MIT, ★0, 2026-09-27, 107 KB | ❌ we have `monitor:trades`; a threshold-alert CLI replaces nothing |
| `LuciferForge/*` (5 new) | ★0–8, 7–44 KB, all 2026-03→07 | ❌ see §3; `polymarket-historical-data` is a **Gumroad funnel**: repo = `LICENSE` + `README`, no data, `$19` one-time / `$19/mo` API, `utm_source=github` on its own links, MIT covers the README not the data |
| `softdevfz/polymarket-kalshi-price-gaps` | **404 — repo gone** | ❌ listed dead (§2) |

On `polymarket-historical-data` specifically, the vendor's *own* honest note is the useful part and
it argues against the product for us: **~94% of `orderbooks` rows are nominal placeholders**
(`best_bid 0.001 / best_ask 0.999`) because 15-minute polling cannot see a thin book, and **"no
resolution labels (`resolved = 0` for all rows)"** — so calibration, Brier and favourite-longshot work
are not computable from it at all. That is a clean independent confirmation of why our own L2 capture
exists and why we must not substitute a polled dataset for it.

## 7. What the audit surfaced that is *ours*, not theirs

Reading the venue fee page to check the donor exposed one row our live map lacks:

- `docs.polymarket.com/trading/fees` lists **Geopolitics = 0** ("Geopolitical and world events markets
  are fee-free"), plus Tech/Mentions at 0.04. `scripts/fee-sign-flip-test.py:49,62` and
  `scripts/c200-fee-reprice-archive.py:29–34` **do** encode `geopolitics: 0.0` with a
  `geopolit|invade|ceasefire|war|missile|troops|nato` matcher.
- `src/lib/scoring/price-edge.ts:65–74` (`categoryFeeRate`) has **only** crypto 0.07 and
  politics-finance 0.04, falling through to 0.05 — no geopolitics branch, and the file's own comment
  claims it "Mirrors the keyword map in `scripts/build-decision-dataset.py` so the offline fit and the
  live score agree". **The invariant that comment asserts does not hold** (offline 0.0 vs live 0.05
  for a war/ceasefire market).
- Direction of the error is conservative (over-charging fees rejects trades), and `PRICE_EDGE_SPEC_V1`
  is `status: "shadow"`, so **nothing live is mispriced today**. It matters at the shadow→live
  promotion boundary, which is where it should be fixed — not by me, here.

**Prepared, NOT applied** (this job is recommendations-only; the card blocks below are for the parent
session to paste):

```
AUDIT INPUT (2026-10-24, asset-audit cron; drafts/asset-audit-awesome-polymarket-20261024.md):
list triaged, not adopted (CC0-1.0, docs-only, 115 entries / 25 GitHub repos). Its "every link
checked" claim is falsified by its own CI: 37/49 runs red since 2026-08-11, last scheduled run
(2026-10-19) dead-links softdevfz/polymarket-kalshi-price-gaps, still listed and still 404 today;
7 PRs admin-merged 2026-10-24T08:36 over red/unapproved checks. 24% of GitHub entries are one
★0–8 account (LuciferForge). Yield: 18 new repos, 3 alive+licensed+★≥5, 1 queued (pm-hftbacktest,
MIT/★126/2026-10-22, fork of nkaz001/hftbacktest with Polymarket converter + BacktestAssetPoly).
Its fee convention (0.07·p·(1−p), maker −0.2·taker) independently confirms the venue table and our
takerFeePerShare — no capability gap for us. Side finding queued to phase-d2-fill-model: queue+latency
modelling is the same card's ask (already owns homerun/FlashAlpha), concept only.
```

```
(phase-d2-fill-model note append) AUDIT INPUT (2026-10-24, asset-audit; drafts/asset-audit-awesome-polymarket-20261024.md):
pm-hftbacktest (MIT, fork of nkaz001/hftbacktest) pairs an explicit risk-adverse queue model with a
20 ms latency default and a tick/lot 0.001 Polymarket preset (BacktestAssetPoly); its tick data is
key-gated (pmdata.dev, unverified from this host). Concept only — no code to port; quote the
queue+latency pairing into D2's method note.
```

## 8. Honest caveats

- **A curated list is not evidence about any listed project.** 66 of 115 entries are commercial
  sites that need an account or key; their descriptions are marketing copy and were not audited.
  Everything with a verdict row above was re-resolved off the API or read in source.
- **One vendor claim is unverified, deliberately:** `pmdata.dev`'s coverage/latency/licence. The
  request was blocked by the local security scan (lookalike `.dev` TLD) and the extractor backend
  cannot fetch arbitrary URLs, so I did not see the page. Treat "free Polymarket tick data" as unproven.
- **I did not run any candidate code** (unattended job: no installs, no execution). The fee-curve
  re-derivation is source reading + venue-doc comparison, which is the strongest tier available
  without execution — but it is not a test run.
- The list's star count (★5) is not a quality signal in either direction; its fork count (25) is
  mostly PR traffic. Judge it on the triage yield, which is what this document is.
- Staleness bound: API facts read 2026-10-24. The list pushes daily, so entry metadata will drift;
  the §2 findings are tied to run IDs and dates and stay checkable.

## 9. Recommendation

1. **Do not adopt, do not add to any rotation** — it is a dedupe target, and the triage above is the
   whole of its value. A future re-surface is one grep of this file.
2. **Queue one lead:** `mileswangs/pm-hftbacktest` as `watch` (REC 1 below). Nothing else from this
   list clears licence + activity + substance.
3. **Do not** treat its link check as a source of truth in either direction: it flags 403s from npm
   and reddit as "could not verify" (correct) but ships a dead GitHub repo for 5 days (incorrect).

**REC 1 — pm-hftbacktest tick feed vs our L2 capture**
```
Hypothesis:   pmdata.dev serves Polymarket L2/ticks that add depth beyond our own data/l2/
              capture (i.e. it is a real tick feed, not 15-min polling like the $19 dataset).
Measurement:  read-only. Pull one calendar day (a date we already captured) from pmdata.dev after
              the user supplies a key, and diff it against data/l2/ on the same slugs:
              (a) minutes covered per market, (b) distinct book update times, (c) fraction of
              updates with both sides non-placeholder. Also read the vendor's licence + terms.
Decision rule: if a SINGLE day shows median book updates per market >= 5x ours AND licence permits
              internal use, propose wiring it as a shadow input to phase-d2-fill-model by 2026-11-15;
              else drop and keep D2 on our own capture.
Cost:         read-only; one key from the user + ~2 h.
Reversibility: nothing installed; delete the downloaded day.
```

Dashboard: http://localhost:3013/drafts/asset-audit-awesome-polymarket-20261024
