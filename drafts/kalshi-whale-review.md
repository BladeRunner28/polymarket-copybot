# Kalshi Whale/Wallet Tracking Review — can we duplicate the Polymarket stack?

**Date:** 2026-09-03 · **Author:** Hermes · **Status:** scoping review (no code merged) · **Roadmap:** phase-kalshi1

## Ask

Duplicate the Polymarket copy-lane data stack on Kalshi: leaderboard → wallet
profiles → observed trades → scoring/copy. This review answers one question
first: does Kalshi expose the same public data surface that makes the
Polymarket stack possible?

## What makes the Polymarket stack possible (recap)

- `data-api.polymarket.com/v1/leaderboard` — **keyless** wallet leaderboard
  (rank, volume, PnL) → 2,752 tracked `WalletProfile`s today.
- CLOB trade feed exposes **maker/taker wallet addresses on every fill** →
  195k `ObservedTrade` rows with wallet attribution, entry prices, sides.
- That attribution is the entire copy lane. No addresses → no copy lane.

## Empirical findings (live probes, 2026-09-03)

1. **Host churn.** `trading-api.kalshi.com` (what the Rust sidecar uses)
   returns **401 "API has been moved to https://api.elections.kalshi.com/"** on
   every call. Official docs (May 2026) point keyless market data at
   `https://external-api.kalshi.com/trade-api/v2`. Elections + external hosts
   both serve ALL Kalshi markets (the "elections" name is legacy).

2. **Public REST surface is market-data only.** Keyless endpoints verified:
   `/series`, `/events`, `/markets`, `/markets/{ticker}/orderbook`. That's it.

3. **No public trades route.** `/trades?ticker=…` and
   `/markets/{ticker}/trades` → **404** on both the elections and external
   hosts, even for liquid markets. Fill/trade data is not part of the public
   REST API (portfolio-fills are authenticated; market *history* is a separate
   paid data tier since 2026-02-19).

4. **No leaderboard, no profiles.** `/leaderboard`, `/portfolios/leaderboard`,
   `/users/me`, `/portfolio/balance` → 404 or 401. No keyless wallet identity
   surface exists. No OpenAPI spec exposed at any host (probed 3 hosts × 3
   doc paths).

5. **Third-party Kalshi "whale trackers" exist but aren't a keyless path.**
   predictmarketcap / polysharks / polywhaler / rivo / botforkalshi all claim
   Kalshi coverage, but the honest ones say it plainly: botforkalshi's tracker
   is per-market YES/NO **flow with no wallet identity** ("size is a research
   lead, not proof of an edge"). Wallet-level Kalshi PnL claims imply their own
   authenticated accounts, paid data, or scraping — not a free public feed.

6. **Sidecar bug discovered (pre-existing, live):** `rust-sidecar/src/adapters.rs`
   Kalshi adapter (a) targets the deprecated host → every call 401s, (b) has no
   real Polymarket→Kalshi ticker mapping (guesses `UPPER/dash→underscore`), and
   (c) **on any non-2xx returns a hardcoded `Ok(0.52)` stub price** instead of
   failing. Consequences: Kalshi "depth" used for cross-venue routing is likely
   a phantom 52¢ constant — a manufactured arb signal of exactly the kind the
   calibrated pipeline exists to kill. The 92 Kalshi paper trades and the
   Kalshi −$50 circuit-breaker evaluation are priced against it. Needs a TR card.

## Verdict

**Full Polymarket parity on Kalshi is NOT feasible with public data.** The
wallet-attributed trade feed that powers the copy lane does not exist on
Kalshi's public API — no leaderboard, no fills-with-addresses, no profiles.
This is a data-availability wall, not an engineering-effort wall.

## Options

| Option | Verdict | Notes |
|---|---|---|
| A. Full parity (leaderboard → wallets → observed trades) | ❌ not feasible | No public wallet-attributed trade data, no leaderboard. Would require Kalshi auth'd accounts or paid/third-party data. |
| B. Anonymous Kalshi size-flow feed (large orderbook moves / fills-per-size per market, no identity) | ⚪ low value | Doesn't feed the copy lane (no wallet to follow). Could add venue context to Phase C arb later. Public orderbook deltas are the only real-time source. |
| C. Third-party Kalshi wallet data (polysharks, rivo, …) | ⚪ unproven | API availability/ToS unknown. Shadow-test ONE provider before any build — measure wallet-attribution quality + freshness vs Polymarket's own lane. |
| D. Status quo + fix the sidecar Kalshi adapter | ✅ recommended now | Re-point to `external-api.kalshi.com`, add a real ticker mapper (series/markets search), **fail loud instead of 0.52 stub**, and re-run the Kalshi routing evaluation clean. |

## Recommendation

1. **Do not build Phase Kalshi-1 as a Polymarket clone** — the data wall is
   structural. Park the card with this verdict.
2. **Fix the sidecar Kalshi adapter first (TR-16).** The 0.52 phantom price is
   a correctness bug that may be manufacturing fake arb routes — worth
   checking whether the 92 Kalshi paper trades correlate with the early-exit
   bleed. Flag-revertible, ~1–2h.
3. **If Kalshi wallet visibility stays desired:** shadow-test one third-party
   provider (option C) as a research task — no build commitment until the
   provider proves it can deliver wallet-attributed Kalshi trades with usable
   freshness. Then re-open phase-kalshi1 with real data in hand.

## Honest caveats

- Probes were anonymous GETs on 2026-09-03; Kalshi changes hosts/endpoints
  frequently (three hosts observed, one deprecated). Re-verify before any build.
- The WS surface (wss://external-api-ws.kalshi.com/trade-api/ws/v2) was NOT
  exhaustively channel-audited; public channels observed in docs are
  orderbook/ticker oriented. If a public `trades` channel with attribution
  exists, it would change option B — worth one dedicated probe before
  finalizing "no trades anywhere".
- Third-party tracker claims were not verified (no API keys to test).

---

## Appendix — TR-16 fix (shipped 2026-09-03) + third-party provider probe

### TR-16 shipped (approved "proceed with all three")

`rust-sidecar` Kalshi adapter rewritten:
- Host `trading-api.kalshi.com` (deprecated, 401) → `external-api.kalshi.com/trade-api/v2`.
- Real book parse: `orderbook_fp.{yes_dollars,no_dollars}` = top-level BID per side,
  dollar strings. BUY price = 1 − best NO bid; SELL price = best YES bid
  (semantics verified against a two-sided market: 0.168/0.791 book ↔ 0.168 bid /
  0.209 ask listing ✓).
- **No more `Ok(0.52)`/`Ok(0.58)` stubs anywhere** (Kalshi + PredictIt): failures
  return Err → sidecar logs loud and books at the Polymarket reference price
  with an execution note (`MAKER … — Kalshi depth unavailable (…)`).
- Ticker resolution: `ExecutionIntent` gained `market_question` (passed through
  paper.ts from score-trades); Rust resolves via bounded open-events walk
  (25 pages, token-overlap, in-process cache, 60 ms pacing, 429 backoff).
  Cross-listing is rare → most resolutions fail loudly, which is correct.
- Verified: cargo build ✓, TS typecheck ✓, live smoke test resolves
  KXELONMARS-99 and returns a real book price (0.99 on the illiquid Mars
  market — book top-level can be stale on joke markets; acceptable for paper).
- Sidecar restarted via launchd kickstart (new binary, PID 80253, :3014 up).

**Historical impact to review:** the old code booked EVERY Kalshi venue trade at
~$0.50 (0.52 stub − 2¢ maker tweak). All 92 Kalshi paper trades' realized PnL
and the Kalshi −$50 circuit-breaker evaluation are priced against that
constant. Recommend a one-off re-pricing/review of the 92 trades before
trusting the Kalshi leg numbers in reports.

### Third-party provider probe (2026-09-03)

| Provider | Keyless API | Kalshi wallet attribution |
|---|---|---|
| polywhaler.com/api/leaderboard | ✅ 200, 50 entries (wallet, PnL, winRate, smartMoneyScore) | ❌ **Polymarket-only** — `?platform/exchange/venue=kalshi` silently ignored (same data) |
| botforkalshi.com/api/public/whale-tracker | ✅ 200 | ❌ anonymous per-ticker size-flow (contracts/fills/notional/vwap) — no wallet identity |
| polysharks.ai | ❌ no keyless API found | — |
| predictmarketcap.com | ❌ no keyless API found | — |

**Shadow-test verdict:** no keyless third-party path to Kalshi wallet-level
attribution exists in this sample. Option C stays unproven → do not build.
botforkalshi's anonymous flow feed is the only genuinely useful public
Kalshi signal (per-ticker notional/vwap) if anonymous flow context is ever
wanted for Phase C — zero copy-lane value.
