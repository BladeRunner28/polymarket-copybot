# Repo Audit: pselamy/polymarket-insider-tracker — 2026-09-09

**Verdict: QUEUE → adopt the trade-tap + wallet-profiler slice post-Oct-8 freeze; concept-donor for Phase D "insider-score" definition; skip the alerting/ops stack wholesale.**

Scope note: first audit of this repo (not in the 2026-09-07/09 scout batches; pushed same day as this audit). Clone: `/tmp/audit_triage/clones/pselamy_polymarket-insider-tracker` (shallow, depth 1, commit `7712364`, 2026-09-09 05:32 UTC, author Patrick Selamy).

---

## 1. What it is

Real-time **behavioral suspicion-scoring system** for Polymarket, marketed as an "insider tracker": it watches the live Polymarket trade stream, profiles each trading wallet on-chain (Polygon), scores trades with deterministic heuristics + one DBSCAN cluster detector, and dispatches "SUSPICIOUS ACTIVITY" alerts to Discord/Telegram.

**Critical framing finding:** there is no identity layer. No KYC link, no username mapping, no proof-of-insider-status anywhere — the codebase contains **zero** references to leaderboards, Twitter/X, wallet PnL, or profit history (verified by grep: `leaderboard`=0, `twitter`=0, `profit`=0, `pnl`=1 in a comment). "Insider" is a **marketing label on an informed-flow anomaly detector** — the README's own sample alert says "SUSPICIOUS ACTIVITY DETECTED," which is the honest reading. The underlying heuristics (fresh CEX-funded wallet + concentrated size on a low-liquidity market) are legitimate informed-money priors, but they cannot establish actual possession of non-public information — no on-chain signal can.

Metadata: 181★, 45 forks, Python 3.11–3.13, MIT (verified below), created 2026-01-04, pushed 2026-09-09, 1 open issue, heavy agent-style spec culture (8KB AGENTS.md, `specs/audit/` with constitution + review-gate, 832 tests across 36 files, strict mypy/pyright/vulture/complexipy gates). Engineering discipline reads unusually high; production battle-test is unproven (single-owner, no evidence of a running public deployment).

## 2. License verdict (FIRST)

**MIT** — GitHub API `license.spdx_id = "MIT"` + `LICENSE` file present (1,071 bytes). **Borrowable with attribution** (keep notice + credit). No copyleft, no patent grant issues for this use.

## 3. Verified machinery (heuristics, file paths)

All verified by reading source in the shallow clone. Numbers below are as-coded, not as-README'd.

| # | Component | Verified behavior | File |
|---|-----------|-------------------|------|
| I1 | **Global live trade tap** | WebSocket to `wss://ws-live-data.polymarket.com`, subscription `{action: subscribe, topic: "activity", type: "trades"}` — **no filters by default = global all-market stream**; optional `event_slug`/`market_slug` filters. Parses payloads carrying `transactionHash` + `proxyWallet` → per-wallet, per-trade events. Public + keyless. | `ingestor/websocket.py` (sub build ~L155–180, parse ~L200–210) |
| I2 | **CLOB REST** | Market list (active-only, cursor-paginated), per-market, orderbook via py-clob-client; rate limiter + retry/backoff wrapper | `ingestor/clob_client.py` |
| I3 | **Gamma metadata (cache-first)** | `gamma-api.polymarket.com` /markets for volume/liquidity; Redis cache TTL 600s; background scan every 300s; retry with backoff; category fallback when volume unknown (niche heuristic degrades gracefully). Mitigates the CF-429 fragility, doesn't remove it. | `ingestor/gamma_client.py`, `ingestor/metadata_sync.py` |
| P1 | **Wallet profiler** | Per wallet: tx-count (nonce) + age from first tx via Polygon RPC; Redis-cached profiles. Freshness = nonce ≤ 5 AND age < 48h. | `profiler/analyzer.py` (fresh_threshold=5) |
| P2 | **Entity registry** | 33 hard-coded Polygon addresses (CEX hot wallets: Binance/Coinbase/Kraken/OKX/Kucoin/Bybit/Crypto.com; bridges: Polygon/Multichain/Stargate/Hop; DEXs: Uniswap/Sushiswap/Quickswap/1inch). Sources cited in code: Etherscan labels, Arkham, public disclosures. | `profiler/entity_data.py` |
| P3 | **Funding-chain tracer** | Walks inward USDC transfer history hop-by-hop (max 3 hops) from the trading wallet, terminating at a known entity (CEX/bridge) or RPC prune horizon. Public-RPC-aware: 9,000-block eth_getLogs chunks, 80k-block max lookback (~44h at ~2s blocks) — enough for fresh wallets by design, useless for old wallets. Pruned-history error markers stop the walk early. | `profiler/funding.py` |
| D1 | **Fresh-wallet detector** | Flags trades ≥ $1,000 notional from fresh wallets (nonce ≤ 5, age < 48h). Confidence 0.5 base +0.2 brand-new (nonce 0) +0.1 very-young (<2h) +0.1 size >$10k, clamp [0,1]. | `detector/fresh_wallet.py` |
| D2 | **Size-anomaly detector** | Trade > 2% of 24h volume OR > 5% of book depth; niche market = <$50k daily volume (or category science/tech/finance/other when volume unknown) gets 1.5× multiplier; niche-only path suppressed below $500 notional (anti-flood guard, added post-tuning). Confidence from capped impact ratios. | `detector/size_anomaly.py` |
| D3 | **Sniper clusters** | DBSCAN (sklearn, eps=0.5, min_samples=2) over wallet market-entry vectors (entry-delta-seconds from market creation, position size, timestamp) → coordinated-entry clusters. Docstring hypothesis: entry within minutes of market creation "suggesting advance knowledge of market creation times" — the one genuinely insider-flavored signal, still circumstantial. | `detector/sniper.py` |
| D4 | **Composite scorer** | weighted = Σ confidence×weight {fresh 0.40, size 0.35, niche 0.25}; ×1.2 for 2 signals, ×1.3 for 3+; cap 1.0; alert if ≥ **0.80** (env-overridable `DETECTOR_ALERT_THRESHOLD`); Redis dedup 1h per wallet×market. | `detector/scorer.py` |
| S1 | **Persistence** | `risk_assessments` (trade, score, per-signal confidences, delivered flag), `wallet_profiles`, `funding_transfers`, `wallet_relationships` — schema docstring: "captures everything a **future** backtest needs without going back to the public API" (i.e., no backtest exists yet in-repo). | `storage/models.py`, `storage/repos.py` |

**Methodology soundness verdict:** real, deterministic, well-guarded heuristics — NOT hype keyword-matching. But the alert threshold comment claims "0.6→0.80 after the first cost-adjusted backtest showed everything below 0.85 was follower-PnL negative under realistic taker fees + half-cent slippage" — **that backtest is not in the repo** (grep confirms zero backtest code); the shipped schema is designed for a backtest that doesn't exist yet. So the 0.80 threshold is an unverifiable in-repo claim, and the repo cannot demonstrate alert-to-PnL validity. Treat all thresholds as author-tuned priors to re-derive, not evidence.

## 4. Fit table vs roadmap gaps

Roadmap anchors (data/roadmap.json): **C-200 copybot whale lane** (copy proven winners on Polymarket CLOB), **Phase D — Insider-score copy gating** + v40 "insider scoring" (gate copy by an insider score), **Phase Kalshi-1 whale/wallet parity (parked: data wall)**, existing polymarket-wallet-analysis methodology (leaderboard data-api PnL/win-rate). Kelly measurement window Sep 8–Oct 8: nothing ships, recommendations only; shadow feeds (astro-shadow, gdelt-shadow) are the established paper/posture precedent.

| Component | What it offers the stack | Verdict | Rationale |
|---|---|---|---|
| I1 Global WS trade tap (`websocket.py` ~200 lines) | **Live per-wallet trade visibility keyed by `proxyWallet`** — genuinely new vs leaderboard snapshots / archived CLOB; catches whale entries in near-real-time for the copy lane | ✅ **ADOPT** (slice, post-freeze) | Public keyless; self-contained module; MIT. Effort LOW; read-only → flag-revertible. THE transfer. |
| P1 Wallet profiler (age/first-tx, nonce) | Freshness feature **not derivable from leaderboard data-api** — new column for wallet-profiling methodology | ✅ **ADOPT** (concept + code) | Small module + Redis cache; complements leaderboard PnL/win-rate, doesn't duplicate. |
| P2+P3 CEX-origin provenance (entity registry + 1-hop funding) | "Fresh + Binance/Coinbase-funded" label on candidate wallets; registry alone is trivially portable | ⚪ **CONCEPT-ONLY** (full 3-hop tracer) / ✅ adopt the registry + first-hop tag | Full crawl is heavy for public RPC and near-useless beyond ~44h lookback; the *label* is the value. |
| D1–D4 Detector trio + scorer | **Candidate-discovery pre-filter**: fresh+size+niche+sniper defines an operational "informed-flow score" | ⚪ **CONCEPT-ONLY** | Code is portable and clean, but thresholds (0.80, weights 0.40/0.35/0.25) rest on an unverifiable out-of-repo backtest → must be re-derived for C-200 goals before any gate use. Feed as *input to* Phase D insider-score definition, not a finished gate. |
| D3 Sniper/DBSCAN | Coordinated-entry clustering | ⚪ **CONCEPT-ONLY, later** | Needs market-creation-time vectors + multi-market entry history; niche, heavier, no near-term roadmap slot. |
| S1 risk_assessments schema | Backtest-ready capture pattern for a paper/shadow feed | ⚪ **CONCEPT** (pattern only) | Xman stack already has its own DB + shadow-feed conventions; steal the field design idea, not the tables. |
| Alerter (Telegram/Discord, dedup, formatter) | Alert ops | ❌ **NOT-PORTABLE** | C-200 is an execution bot, not an alert bot; duplicates existing lane infra. |
| Runtime stack (Postgres+Redis+docker-compose+alembic+health+shutdown) | Ops scaffolding | ❌ **NOT-PORTABLE** | Xman stack has its own; adds two services for zero roadmap value. |
| Whole-repo "insider tracker" claim | Copy-gating on proven-insider status | ❌ **NOT-PORTABLE** (as claimed) | No identity/ground-truth layer exists; would be overclaiming. Use as suspicion score only. |
| Anything Kalshi | Phase Kalshi-1 parity | ❌ **NOT-PORTABLE** | Polymarket-only end-to-end; Kalshi lane stays parked on its own data wall. |
| Leaderboard/PnL analytics | Replace/augment wallet-analysis lane | ❌ **NOT-PORTABLE** | Absent from repo (grep-verified); existing methodology already covers it. |

## 5. Integration proposal

**Target: C-200 whale-lane "live behavior tap" + Phase D insider-score input.** Three slices, sequenced:

- **T1 — Live trade tap (ADOPT, post-Oct-8 or as paper shadow now).** Vendor the WS subscription semantics (MIT; module is self-contained; keep LICENSE notice) into the existing research/shadow feed: subscribe global `activity/trades`, filter notional ≥ $1,000 (repo's own threshold), persist wallet-keyed entries. Effort: **LOW — ~1–2 days** incl. code review + adapter tests (832-test repo gives high confidence in the module's own correctness; review still mandatory before vendoring). Risk: **LOW** — read-only public feed, no capital, no CLOB auth; flag-revertible by killing the watcher. Rate/volume: global Polymarket trade stream is high-frequency → the $1k filter + Redis-style dedup matter.
- **T2 — Wallet freshness/CEX-origin label (ADOPT, same change).** Add nonce/age + first-hop funding entity as new features on watched wallets; reuse P1 + entity registry + 1-hop trace only. Effort: **LOW–MED**. Risk: **LOW** (public Polygon RPC rate limits are the binding constraint — repo itself warns to use a dedicated RPC for production).
- **T3 — Insider-score concept draft (CONCEPT, deliverable pre-Oct-8).** Write the recommendation: fold D1/D2/D4's signal definitions into the Phase D "insider-score" spec as *candidate* inputs **alongside** existing leaderboard PnL/win-rate methodology; explicitly re-derive weights/thresholds from C-200's own backtest data before any gate use. No code ships in the Kelly window.

**Pre-Oct-8 posture:** paper-only — T3 doc + optional throwaway read-only WS-tap viability check (no capital, no production DB writes) matches the shadow-feed precedent. Nothing ships before the freeze lifts.

## 6. NOT-portable list

- Full runtime stack: Postgres 15 + Redis 7 + docker-compose + alembic + health server + graceful-shutdown — duplicates Xman stack; two extra services for zero roadmap value.
- Alert dispatch layer: Discord/Telegram channels, formatter, dedup-as-alert-guard — C-200 executes, it doesn't alert humans.
- Complete funding-chain tracer (3-hop eth_getLogs crawl, 44h lookback ceiling): only the registry + first-hop CEX tag carry value; the crawl is RPC-expensive and blind beyond fresh wallets.
- Sniper/DBSCAN module in current form: needs entry-delta-to-market-creation features and cluster bookkeeping that don't exist in the Xman data layer; no near-term roadmap slot.
- "Insider-tracker" framing as a copy gate: no identity layer, no ground truth, unverifiable threshold backtest → suspicion score only.
- Kalshi coverage: none (Phase Kalshi-1 unaffected, remains parked at its data wall).
- Alert-threshold/weights as-is: tuned to an out-of-repo follower-PnL backtest; re-derive or ignore.

## 7. Honest caveats + verdict

- **Overclaim risk:** "insider" ≠ proven. Behavioral suspicion only; cannot be validated on-chain; no ground-truth backtest in-repo (0.80 threshold cites an out-of-repo backtest; schema is explicitly designed for a *future* one).
- **Young, unproven in battle:** created 2026-01-04, single main author, agent-heavy spec culture (constitution, review gates, 832 tests, strict static gates) — quality signals excellent, but no evidence of sustained public deployment; review before vendoring anything.
- **Gamma dependency remains:** mitigated (cache-first, retry, category fallback) but the CF-429-prone endpoint is still in the path for volume stats; the fallback path is what keeps it alive.
- **Freshness of repo:** pushed 2026-09-09 (same day as this audit); README/CHANGELOG keep pace with code — not a stale star-farm. Not in prior scout batches; 1 open issue.
- **RPC economics:** public Polygon RPCs bound the profiler; production use wants a dedicated RPC (repo docs agree).

**Verdict: QUEUE.** The genuinely new, roadmap-shaped capability is T1 (global live per-wallet trade tap — beyond leaderboard snapshots and archived CLOB data) plus T2 (wallet freshness + CEX-origin label — beyond leaderboard PnL/win-rate). Both are low-effort, low-risk, MIT-borrowable, flag-revertible, and feed both the C-200 whale lane and the Phase D insider-score definition. But nothing ships before the Oct-8 Kelly-window gate: deliver the T3 concept draft (paper) inside the window, land T1/T2 as the first post-freeze whale-lane change, and treat the detector scoring as concept-only until thresholds are re-derived from C-200's own data. Do not adopt the alerting/ops stack; do not adopt the "insider" framing as a gate.

**Next owner action (recommendation only, pre-Oct-8):** approve T3 concept draft into the Phase D spec queue; stage T1/T2 for the first post-freeze sprint.
