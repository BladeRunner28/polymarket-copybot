# Audit: Lumiwealth/lumibot — adoption fit for Medusa CopyBot

**Date:** 2026-10-15 · **Auditor:** Hermes asset-audit cron · **Method:** GitHub API metadata + tree
aggregation + CI/releases read + read-only inspection of the raw Polymarket module
(`brokers/polymarket.py`, `data_sources/polymarket_data.py`, `backtesting/polymarket_backtesting.py`,
`backtesting/backtesting_broker.py` greps, `entities/trading_fee.py`, `entities/trading_slippage.py`,
`backtesting/data_provenance.py`, `example_strategies/polymarket_prediction_contract.py`,
`docs/investigations/2026-07-01_POLYMARKET_*`). **No clone, no install, no execution** — this job
forbids running candidate code, so the standing "run their test suite" step is replaced by a CI-history
read (see Caveats).

## Verdict

**DROP** — read-for-ideas only. **GPL-3.0** (strong copyleft ⇒ blocker for anything linked into our
stack) *and* the Polymarket path requires a wallet private key. Per-component, nothing here beats
what we already run or already have in plan; the two ideas worth a sentence are conventions, not code.

## 1. What it is

An AI-agent trading framework ("AI agents that actually place the trade"), Python, 12 broker
integrations incl. **Polymarket**, backtesting, a BotSpot MCP surface and an LLM agent runtime.

| Metadata (GitHub API, 2026-10-15) | |
|---|---|
| Licence | **GPL-3.0** → read-only, reimplement concepts only |
| Stars / forks / open issues | 2,124 / 414 / 101 |
| Created / last push | 2020-09-10 / **2026-10-15** (alive, pushed same day) |
| Releases | v4.6.18 + v4.6.17 (both 2026-10-10) — weekly cadence |
| Default branch / language | `dev` / Python 100% |
| Size | 479,651 KB repo, 1,980 files, 732 `.py` = 11.4 MB |
| Tests / CI | `tests/` present (87 `.py` under `tests/backtest`); `.github/workflows/cicd.yaml` |

**Size is not code:** 257 MB of `.png` (268 files), 38 MB `.jar`, 20 MB `.html`, 5.4 MB `.map`,
3.2 MB `.csv` — the engine is a minority of the 479 MB. The repo also carries an internal research
corpus (`docs/research` 315 files, `docs/investigations` 103 files).

**CI health (read off the API, per the recipe):** last 15 `cicd.yaml` runs — 11 `success`,
4 `cancelled`, **0 `failure`**; the newest four are `queued`/`in_progress`/`cancelled` on a
`version/4.6.19` release branch. So this is a maintained project with a green suite — the star count
is backed by maintenance here. That does **not** make it adoptable under GPL-3.0.

**Polymarket surface (new, ~2026-07, 11 files):** `brokers/polymarket.py` (60 KB),
`data_sources/polymarket_data.py` (31 KB), `backtesting/polymarket_backtesting.py` (13 KB),
`example_strategies/polymarket_prediction_contract.py`, 5 PM tests, 3 investigation docs
(dated 2026-07-01: integration gameplan, deep-integration research, "international CLOB live proof").
It is **wired** (example strategy + tests + docsrc), not dead code.

**Keys (disqualifying):** `POLYMARKET_SECRET_KEYS = {PRIVATE_KEY, CLOB_API_KEY, CLOB_API_SECRET,
CLOB_API_PASSPHRASE, RELAYER_API_KEY, RELAYER_API_KEY_ADDRESS, BUILDER_API_KEY, BUILDER_SECRET,
BUILDER_PASSPHRASE}` (`brokers/polymarket.py:22-31`); the broker raises without
`POLYMARKET_PRIVATE_KEY` for authenticated CLOB reads/trades (`:355-357`) and derives API creds from
it (`create_or_derive_api_key`, `:389`). Our never-handle-keys rule: **do not run its live path, do
not `pip install` `lumibot` into any venv here (including `venv-calib`).**

## 2. Verified machinery (read in source, file:line)

1. **Keyless read path** (`data_sources/polymarket_data.py`): order book → best bid/ask + sizes
   (`:162-187`); CLOB `/spread` and `/midpoint` (`:303-323`); market rules → `tick_size`
   (`orderPriceMinTickSize` et al.), `min_order_size`, `enable_order_book` (`:252-282`);
   resolution status + settlement price (`:284-302`, `:377`); `prices-history` → OHLC bars (`:73-146`).
2. **Bar-feed validation + synthetic settlement bar** (`backtesting/polymarket_backtesting.py`):
   prices **validated to [0,1] and numeric — it raises rather than imputing** (`:337-348`); limit
   prices checked for **tick-size alignment** (`:177-185`); min order size enforced (`:160-167`);
   and at market close it **injects a synthetic settlement bar** with `open=high=low=close=bid=ask
   = settlement price, volume=0` (`:278-322`) so hold-to-resolution needs no special case.
3. **Quote-first fill engine** (`backtesting/backtesting_broker.py`, 239 KB): buys fill at the
   **ask**, sells at the **bid** (`:2314`, `:2402`, `:2426-2441`); OHLC fallback when no quote;
   **admissibility rule** — marketable limits (buy limit ≥ ask / sell limit ≤ bid) fill regardless of
   spread width, while *inside-spread* limits fill only if the quoted spread ≤ `max_spread_pct`
   ("otherwise strategies can get stuck with uncloseable legs", `:2445-2452`); partial-fill handling
   when bid/ask/trades are missing (`:1833`).
4. **Cost model** (`:2059-2085` + `entities/trading_fee.py`, `entities/trading_slippage.py`):
   per order, `flat + percent×notional + per_contract×qty`, selected by maker|taker flags, plus a
   single absolute `TradingSlippage.amount`. **Somewhere between linear and 2-parameter — the exact
   shape our own design doc already rejected in another donor.**
5. **Provenance artifact** (`backtesting/data_provenance.py`): a completed backtest writes a JSON
   record naming route/vendor/exchange/feedType/resolution/window/fallbackDecision per asset.
6. **Fee stance, from their own doc** (`docs/investigations/2026-07-01_POLYMARKET_DEEP_INTEGRATION_RESEARCH.md:534-538`):
   *"Makers are not charged; takers can be charged depending on category. Fees need to be represented
   in raw order/trade payloads first, then normalized into LumiBot trade/fill accounting only after
   real fills show the fields consistently."* → **the PM lane ships with no fee model at all.**

## 3. Fit table vs the CURRENT roadmap

| Component | Card that asks for it | Verdict |
|---|---|---|
| Keyless book/quote read (`/book`, `/spread`, `/midpoint`) | `l2-subscribe-at-dispatch` (In Review), `bt-engine-design` §3 | ⚪ **we are deeper**: the L2 recorder snapshots the full book every 5 s around dispatch; `MarketSnapshot` is wallet-following, not a quote source |
| `prices-history` → bars + [0,1]/numeric/tick validation | `bt-engine-design` (Done) §3 ("validate timestamps against the requested window and drop outliers"), `bt-data-capture` (Backlog) | ⚪ **already in plan** — our design names timestamp validation + manifest discipline; range/tick checks are a few lines in a pager we have not built yet |
| Synthetic settlement bar at close (O=H=L=C=1\|0) | `bt-engine-design` (Done) — settlement semantics ("settlement, not a sell, closes the trade") | ⚪ convention already implied; no open card needs it |
| Quote-first fill (buy@ask / sell@bid) as a **model** | `ml-u1-conditional-fill-model` (In Progress), `c200-maker-fill-assumption` (Scheduled) | ❌ our C-200 entry is a *resting maker* fill at mid − measured credit; our measured hazard (74.3%@5m / 81.1%@1h, band- + category-conditioned, from 1.2 B archive fills) is strictly better evidence than a constant-quote engine |
| Inside-spread vs marketable-limits admissibility + spread cap | `src/lib/rules.ts` `maxSpread` (0.06) enforced as a hard skip in `src/lib/scoring/trade.ts:94` | ❌ we already gate quoted spread at admission; the inside-spread/marketable split is a **concept sentence** for `ml-u1`, nothing more |
| `TradingFee(flat, percent, per_contract)` + `TradingSlippage(amount)` | `bt-fee-maker-calibration` (Done), `paper-ledger-fee-fidelity` (Backlog) | ❌ **strictly behind us**: absent for PM (no fee code), and the linear (commission+slippage) shape is the model `bt-engine-design:165` explicitly rejected; ours is measured — taker `0.10 × shares × min(p,1−p)` on 95-99% of 1.2 B archive rows |
| Per-backtest provenance JSON | `bt-engine-design` (Done) §80 | ❌ ours is stronger (sha256 + min/max ts + coverage gaps + schema version; reproducible by hash) |
| LLM agent runtime (`components/agents`, 220 KB `builtins.py`, skill packs) | — duplicates our research bot + local-LLM lane | ❌ not portable |

**NOT portable:** `components/agents*` (LLM runtime, browser tools, managed gateway), the 12 broker
adapters, options/derivatives helpers, the nine TA strategies, `BotSpot`/notification surfaces.

## 4. Integration proposal

**None — drop.** Nothing is taken as code (licence + keys). If anything, two sentences from this
audit belong in `ml-u1-conditional-fill-model`'s admissibility section: (a) the inside-spread vs
marketable-limit distinction as a *microstructure convention to test*, (b) the settlement-bar
convention for the future price layer. Both are already in plan or in stack; neither is a gap.

## 5. Honest caveats

- **Method deviation, stated:** the standing recipe clones and runs a donor's suite; this job's hard
  constraint forbids clone/install/execution, so test health is asserted from **CI history**
  (11/15 success, 0 failure) and the test tree (87 files under `tests/backtest`), not from a run I did.
- **Venue claims in their doc are dated 2026-07-01** ("makers not charged, takers per category") and
  are weaker than our measured facts from `bt-fee-maker-calibration` (Done). Do not cite them over ours.
- **Their PM lane is young and self-declared incomplete on PnL realism** (fees deferred). Treat any
  "verified fill fidelity"-style claim with the same scepticism we apply to our own model.
- Read-for-ideas only: no file, symbol or threshold from this repo may be copied into ours.
- Repo is GPL-3.0 on PyPI as `lumibot` — never install it in our venvs.

## 6. Registry block (prepared, NOT applied — this job is recommendations-only)

```
AUDIT INPUT (2026-10-15, asset-audit cron; drafts/asset-audit-lumibot-20261015.md): audited, no action.
GPL-3.0 + POLYMARKET_PRIVATE_KEY required ⇒ read-only. Its Polymarket lane ships NO fee model and a
per-order linear TradingFee/TradingSlippage shape bt-engine-design:165 already rejected; its fill
engine (buy@ask / sell@bid; inside-spread limits only under max_spread_pct; marketable limits exempt)
and its prices-history bar feed ([0,1]+tick validation, synthetic settlement bar at close) are
already in-plan (bt-engine-design §3/§80, bt-data-capture) or already in-stack (maxSpread 0.06 hard
skip, src/lib/scoring/trade.ts:94; L2 book recorder). No gap, no card. Optionally two convention
sentences into ml-u1-conditional-fill-model's admissibility section.
```

Dashboard: http://localhost:3013/drafts/asset-audit-lumibot-20261015
