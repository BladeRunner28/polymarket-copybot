# Batch audit lite pass — farm rejects + out-of-core notes (36-repo dump, 2026-09-09)

Triage companion to the deep-audit batch. Deep audits dispatched for 16 repos
(`*-audit-2026-09-09.md`, same dir). Two prior-audited repos excluded with
standing verdicts: **oracle3** (Apache, ADOPT at Phase C kickoff —
drafts/oracle3-audit-2026-09-07.md) and **homerun** (AGPL read-only —
drafts/homerun-audit.md).

Method: GitHub API metadata + shallow clone + marker scan (code presence,
domain-topic grep over ALL code files, license file read, referral links).
Marker data per repo is from the clones in /tmp/audit_triage/clones/.

## A. Farm / empty / honeypot rejects (verdict: SKIP, with receipts)

- **brishowkanem4/Polymarket** — 173★, NO-LICENSE. ONE file: README.md claiming
  "HyperTrader scans thousands of markets… executes trades automatically".
  Zero code files. Stars correspond to nothing (radioman criteria: topic grep =
  README only). Honeypot.
- **lllllilllll/Kalshi-Trade-Bot** — 79★, MIT. Zero code (README +
  requirements.txt + .env.example only). Mislabeled repo name: README describes
  a **Polymarket multi-account streak/rewards volume farmer** ("farms volume,
  completes streaks, maximizes rewards across unlimited accounts") — ToS-risk
  tooling, not software worth touching. SKIP on both grounds.
- **AsArchitects/Kalshi-trade-bot** — 82★, MIT. Zero code. README-only describes
  a PM↔Kalshi 15-min BTC arb ("sum of UP and DOWN prices across both venues
  < 0.90 → arb"). Note: same pushed date + near-identical star counts as the
  llllllilllll repo = star-farm pair. The described rule is unverified README
  text and ignores fees/spread — not evidence for Phase C.
- **Key-wxh/market-fish** — 47★, MIT ("Keystart AI"), Product Hunt-marketed
  generic AI trading dashboard (streamlit). 0/45 files mention polymarket /
  kalshi / prediction markets. Name-bait for PM search traffic. SKIP.
- **arn-c0de/ANPS-TradeMeUp** — 46★, "PROPRIETARY SOURCE-AVAILABLE LICENSE"
  (fake-open license trap: view/clone/modify granted, real use restricted).
  Multi-agent news→market LLM system, 1/218 domain hits (a design doc).
  Duplicates the research-bot + LLM layer is not-portable anyway. SKIP.
- **aitradingbotspro/crypto-liquidity-ai-trading-bot** — 67★, NO-LICENSE (MIT
  badge in README, no LICENSE file = license dishonesty tell). Generic crypto
  order-book liquidity bot; 1/99 domain hits (README only). Out of PM domain.
  SKIP.
- **bigmacman1129/crypto-ai-trading-bot** — 201★, NO-LICENSE (badge w/o file).
  Generic crypto market-making/arb Node bot w/ messenger control (repackaged
  legacy project). 9/118 domain hits, none PM-specific. Out of domain. SKIP.
- **duemig/Stanford LSTM** — 290★, NO-LICENSE. Genuine 2016-era Stanford course
  project (notebook + report PDF), stock-price LSTM. LSTM-on-prices is a
  near-random-walk result class; nothing transferable beyond walk-forward
  validation discipline (already standard practice). SKIP.

## B. Real but out-of-core (verdict: no audit; one-line notes)

- **KoNananachan/Neuberg** — 203★, **BSL-1.1** (Business Source License:
  source-available + usage-restricted → read-only concept donor). Real 1.6k-file
  "open Bloomberg terminal" product (vol-arb / merger-arb panels, polymarket.ts
  route). It's a monitoring product, not strategy; BSL blocks borrowing. SKIP.
- **YicunAI/Pnlclaw-community** — 198★, **AGPL-3.0** (read-only). Real local-first
  AI quant research desktop app; exchange-sdk has Polymarket WS/redemption
  tests. Redundant with research-bot + dashboard; AGPL; LLM-first. SKIP.
- **x1xhlol/market-ai-resolution** — 37★, MIT. PoC to replace Polymarket's UMA
  optimistic oracle with evidence-based AI resolution. Not an edge source —
  but its critique ("resolution by inertia", capital-weighted voting) is a
  settlement-risk reminder for late-window positions. SKIP (concept note only).
- **BizShibe/openclaw-ai-polymarket-trading-bot** — 47★, NO-LICENSE. Small TS:
  5-min BTC Up/Down prediction via Openclaw LLM agent + real CLOB orders.
  Concept note: another repo chasing the 5-min/15-min BTC short-TTR lane —
  supports the standing recommendation (BTC late-window tape test BEFORE any
  short-TTR build; audits 2026-09-07). LLM-signal layer not-portable, no
  license, real-orders pattern violates paper posture. SKIP.
- **pathikrit/zeitgeist** — 33★, NO-LICENSE. Real but trivial: one-file daily
  macro report (markets → LLM → hosted HTML). Parallels existing cron daily
  reports; nothing new. SKIP.
- **moondevonyt/Limitless-Prediction-Market-Bots** — 67★, NO-LICENSE. Legit
  small onboarding examples for Limitless (Base) — fetch_history /
  whale_scanner / live_eth_15min, keyless. Concept-only: a Limitless whale
  scan could extend the C-200 watchlist net; venue already covered by ccxt
  anyway. Examples, no strategy, no license. SKIP.
- **mjunaidca/polymarket-skills** — 90★, NO-LICENSE. Real content: agentskills-
  spec Polymarket skill family w/ small analyzer scripts (orderbook analysis,
  momentum scanner, find_edges, correlation tracker). Read-only content;
  analyzer ideas mirror the existing Hermes polymarket skill set. SKIP (note).

## C. Promoted to content-digest (separate leaf, `audit-content-digest-2026-09-09.md`)

- **AKCodez/prediction-market-alpha-playbook** — MIT, docs repo (2.6k lines:
  EDGES / METHODOLOGY / NEG_RISK_NO_CARRY / ANTIPATTERNS / APIS /
  ARCHITECTURE / PLAYBOOK). Real production lessons content — highest
  hypothesis-donor value in the reject pile.
- **0xrsydn/polymarket-crypto-toolkit** — NO-LICENSE, real Python monorepo
  (copybot.py + copybot_v2.py, backtest engine, copytrade/streak-reversal/
  candle-direction strategies, indicators pkg). C-200-adjacent; read-only
  concept donor.
- **tradinglabpremium/sports-prediction-market-scanner (SEMS)** — MIT, TS,
  ~1.2k lines core+feeds w/ MarketEdgePricer, soccer feeds, CLI vocab — needs
  the scaffold-vs-real check before any verdict.

Verdict tally for the lite pass: **15 SKIP (8 farm/empty + 7 out-of-core), 3
content-digest.** None ship pre-Oct-8; all of it recommendations-only.
