# Market-Data Vendor Trials + Research-Feed Remediation
**Plan: post-Kelly-window (after Oct 8 2026 read). Author: hermes. Date: 2026-09-05.**

Scope: two free-tier vendor trials (Bitquery, OddsPipe) and research-feed fixes
(Quiver/govinfo hygiene). NOT before the Kelly read — sentiment/scoring-path
changes would confound the pre-registered Phase-B window. Research-only,
fail-soft, no execution-path integration (Dome's EOL 2026-04-28 is the
object lesson: aggregators churn — wrap everything fail-soft).

---

## 1. Bitquery free tier — wallet vetting (copy-signal quality)

**Use case:** our wallet scoring uses Polymarket's own leaderboard metrics
(roi30d/consistency/copyability — windowed, self-reported platform view).
Bitquery adds **on-chain truth**: realized PnL & win rate computed from
Polygon CTF-Exchange trade history, wash-trade detection (USDC roundtrip
symmetry), all-time vs windowed stats, non-leaderboard wallets.

**Free tier (verified 2026-09-05):** Developer plan — ~10 req/min, small
monthly points bucket, capped rows/request, no streaming concurrency; paid
plans from $49/mo. Points-based billing — queries MUST carry `limit` +
narrow `time` filters or one call drains the month.

**Spec (harness `scripts/research/wallet-vet.ts`, ~6-hourly cron batch + on-demand):**
- Input: candidate wallet addresses from scan-wallets/leaderboard queue
  (top-N new candidates per cycle — a handful, not thousands).
- Per wallet: realized PnL, win rate, trade count, active window (first/last
  trade), USDC roundtrip symmetry (wash flag), markets traded.
- Recipe: Bitquery's documented Polymarket wallet pattern
  (docs.bitquery.io/docs/examples/polymarket-api) — copy the exact GraphQL
  at implementation time; their schema evolves. Add explicit `limit`/time bounds.
- Output: `data/wallet-vet.jsonl` + verdict fields (VET_OK / WASH_SUSPECT /
  STALE / LOW_ACTIVITY). Research display only — no scoring impact in v1.
- Fail-soft: API down / quota exhausted → log + skip wallet (never blocks
  the copy cycle); results cached 24h.

**Decision gate (after ~4 weeks of vet data):** do vetted wallets (VET_OK)
outperform unvetted on realized copy PnL? If yes → propose integrating the
verdict as a scoring input (that's a rules-level change — separate approval,
post-window anyway). If no signal → drop.

## 2. OddsPipe free tier — Kalshi venue-offset measurement

**Use case:** `premium-calibration.json`'s `venueOffsetKalshi` is estimated
from our own fills (small n, execution-biased). 1-minute OHLCV on markets
present on BOTH venues lets us measure the structural Kalshi-vs-Polymarket
premium properly — feeds the λ̂ + venue-offset term used by Phase-B Kelly for
Kalshi-routed copies.

**Free tier (verified 2026-09-05):** free key via email, no card; REST only
(no WS); per-minute + daily hard caps per FAQ ("requests pause until window
resets"); exact caps not published (JS-loaded pricing) → **verify at
signup** via /v1/me. Assume conservative pacing (≤1 req/10s) + backoff.

**Endpoint surface (spec v0.1.0):** /v1/markets, /search, /{id} + /history
(price snapshots, `since`) + /candlesticks (1m/5m/1h/1d, start/end/limit),
/{id}/spread, /v1/spreads (cross-platform divergences), /v1/sources.

**Pre-trial checks (kill criteria):**
1. Kalshi coverage of OUR categories (C-200 trades esports/crypto/congress/
   econ — wrappers typically cover only sports/elections overlap). If absent
   → trial dies before code.
2. History depth: candles `start` range actually served (young service —
   weeks of history is useless for calibration; need ≥ the biweekly refit
   span, ideally 90d).
3. Data sanity: spot-check a known market's 1m candles vs our own record-l2
   snapshots.

**Harness `scripts/research/venue-offset.ts`:** matched-market pairs (same
event both venues) → pull 1m candles → compute per-market premium series →
new `venueOffsetKalshi` estimate with n + CI. Output lands in a draft
calibration review, NOT auto-written into premium-calibration.json (the
existing value stays until user approves the swap).

## 3. Research-feed remediation (Quiver + govinfo) — findings 2026-09-05

**STATUS: quiver collection PAUSED at the collector 2026-09-05 (user-approved).**
Existing rows age out of the 7d aggregation window within ~a week; no scoring
path changed (window integrity intact). Re-review after the Oct 8 Kelly read.

DB audit of RegulatorySignal (all sources, ~3 weeks of the 6-hourly bot):

| source | rows | dups | opinionated | avg|score| | notes |
|---|---|---|---|---|---|
| quiver_congress_trade | 190 | 108 (57%) | 190 | 0.836 | strongest intensity — but see below |
| congress_gov_api | 190 | 158 (83%) | 190 | 0.603 | includes stale 118th-congress bills |
| govinfo_fr_notice | 156 | 139 (89%) | 0 | 0.0 | neutral by construction — never passes the ≥0.3 aggregation gate |

**Quiver-specific problems (why "useful?" = currently marginal-to-harmful):**
1. **Single-person concentration:** top tickers are STE/GWW/GOOGL/AMAT at 19
   each — largely ONE representative's (Moskowitz) portfolio churn. The feed
   is not "Congress is buying defense" — it's one member's IRA rebalance.
2. **84% sells (119 sale + 40 partial)** mapped bearish — selling ≠ a
   directional thesis; it's diversification/tax behavior.
3. **45-day disclosure lag** (STOCK Act) — TransactionDate 7/13 reported
   8/27. Structurally stale for short-horizon markets.
4. **Category-mapping noise:** GWW (industrial distributor) sale → −0.8
   Macro/Politics. 166/190 rows land Macro/Politics at 0.836 intensity —
   fires sentimentDelta into C-200 political copies on idiosyncratic noise.
5. **Tier-A evidence cap (1.0)** in sentiment.ts — same weight as official
   congress.gov data. Mis-rated for disclosed-but-idiosyncratic trades.
6. AB shadow (n=14 window) includes quiver 5/14 but cannot yet attribute
   per-source OUTCOME — the AB tracks source, not realized PnL by source.

**govinfo:** zero opinionated rows → contributes nothing to aggregation;
either reclassify FR notices that actually touch crypto/energy/defense, or
drop from the sentiment path (keep for Atlas if used there).

**Remediation (parked post-Kelly-window to keep the Phase-B read clean — any
of these changes live scoring):**
- [ ] Dedupe ingestion by report fingerprint (item_id/rep/report-date) —
  57–89% dup rates inflate signal counts in aggregation.
- [ ] Re-tier quiver_congress_trade 1.0 → 0.3–0.6 (evidence tier B/C).
- [ ] Multi-member gate: stock-trade sentiment requires ≥2 distinct reps
  same direction; single-member signals → context only, no score.
- [ ] Ticker→category whitelist (semis/tech → Tech/AI; defense → Defense/
  Geopolitics; else no sentiment emitted — kills GWW→Macro noise).
- [ ] Filter congress_gov_api to current congress (119th) + recent actions.
- [ ] Extend the weekly AB summary to realized-PnL correlation per source;
  kill any source with sign-agreement-vs-outcome ≤ 50% at n ≥ 30.

## 4. Sequencing (post-Kelly, ~Oct 9+)

1. **Week 1:** vendor signups (user email), pre-trial kill-checks (OddsPipe
   coverage/depth; Bitquery recipe on 3 known wallets), harness skeletons
   fail-soft in cron. No scoring impact.
2. **Weeks 2–6:** data collection — wallet-vet.jsonl + venue-offset drafts +
   per-source AB outcome attribution (fix lands here too: dedupe + tiers
   roll out as ONE rules/engine change after the window read, with the Oct 8
   baseline preserved).
3. **Week 6+:** decision gates above. Anything touching scoring = separate
   in-thread proposal + approval (standard workflow).

**Guardrails:** research scripts only; never execution path; every external
call fail-soft (missing/quota → off, like premium-calibration null path);
no mid-window changes; verify all pricing/limits at signup (AI-shock market
moves vendor pricing too).
