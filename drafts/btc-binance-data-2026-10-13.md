# Binance data for Polymarket + Kalshi BTC — feasibility, measured (2026-10-13)

**Question (in-thread, 2026-10-12 23:4x CDT):** *"Does Binance have an API that we can query to get
bitcoin data to enhance our bitcoin trading on both Polymarket and Kalshi?"*

**Status:** read-only reconnaissance + one read-only harness (`scripts/btc-oracle-reconcile.py`).
**Nothing changes in the live path** — no rule, no size, no gate, no venue decision. Keyless
throughout. Kalshi stays paper regardless: we hold no key.

---

## Verdict — the endpoint list is not the interesting part

**Yes, and from this host the usable keyless surface is `data-api.binance.vision` (REST + WebSocket).
But the thing that actually decides how we may use it is a distinction a feature list hides: on these
two venues Binance is sometimes the *oracle* and sometimes only a *proxy*.**

| | role of Binance | measured reproduction of the venue's OWN recorded verdict |
|---|---|---|
| **Polymarket** crypto price book | **pinned settlement oracle** ("the resolution source for this market is Binance, specifically the BTC/USDT …") | **1,617 / 1,617 markets = 100.00%** |
| **Kalshi** BTC (KXBTC15M / KXBTCD) | **not the oracle** — settles on **CF Benchmarks' BRTI**, a composite index whose own constituent list **does not include Binance** | **6,382 / 6,526 windows = 97.793%** |
| **Polymarket** short-dated up/down (5m/15m/1h/4h) | **not the oracle** — settles on **Chainlink** BTC/USD TWAP | best proxy convention **268 / 288 = 93.06%** |

**Key insight: the same feed is exact settlement certainty on one family and a proxy with a measured
error rate on the other — and for a proxy, that error rate *is* the risk of any position built on it.**
The Kalshi misses were not random: **every one of the 144 disagreements sat within $19.60 of the
knife edge** (median $2.40), i.e. the error lives entirely in the "who is within a few dollars of the
boundary" bucket, which is exactly where a single-venue feed cannot speak for a composite.

And the volume at stake is not marginal: across the 1,000 largest open crypto events on Polymarket,
**Binance-settled markets carry $2,177,175 of $2,358,540 24 h volume = 92.3%**, versus $39,653 for
Chainlink (677 events). Binance is the *single largest settlement source in the crypto book*, measured.

---

## 1. What the API actually gives, from this host

**Hosts** (all keyless; this is the first thing that constrains everything else):

| host | result | consequence |
|---|---|---|
| `api.binance.com` | **HTTP 451** (restricted location) | the "normal" API is **geo-blocked** here |
| `fapi.binance.com` (futures) | **HTTP 451** | **no funding rate, no open interest, no mark/index, no perp basis** |
| `data-api.binance.vision` | **200**, ~0.45–0.65 s/call | ✅ the working spot market-data host |
| `api.binance.us` | 200 | ✅ fallback / cross-check (BTCUSDT price agreed to cents) |
| `stream.binance.com:9443` (WS) | **HTTP 451** | blocked |
| `data-stream.binance.vision:9443` (WS) | **101 Switching Protocols**, live trade frames verified | ✅ real-time is available |
| `stream.binance.us:9443` (WS) | **101**, verified | ✅ fallback |

**Endpoints verified working** (spot, keyless): `ping`, `ticker/price`, `ticker/24hr`,
`ticker/bookTicker`, `depth`, `aggTrades`, `klines`, `uiKlines`, `exchangeInfo`.

**Depth** — the reason this is worth wiring at all: `1m` klines go back to **2017-08-17** (first bar
verified: 4261.48), `1s` klines to **2022-06-01** (verified), and the keyless **bulk archive**
(`data.binance.vision`) serves monthly/daily ZIPs — measured sizes: `1m` **2.1 MB/month**,
`1s` **70.3 MB/month**, `aggTrades` **395.7 MB/month**. So both a 9-year 1-minute history and a
second-resolution tape are available with no key and no vendor.

**Liquidity:** BTCUSDT 24 h = **$1.315 B** quote volume / **3.34 M** trades.

**Rate limits** (published by `exchangeInfo`): `REQUEST_WEIGHT` 6,000/min, `RAW_REQUESTS` 300,000/5min;
per-call usage is returned in `X-MBX-USED-WEIGHT-1M`. At `klines` weight 2 (≤1,000 bars) the whole
5-year 1-second history is a throughput question, not a quota question.

*What we cannot get here:* futures/perp anything (see the 451 above). Any feature resting on funding
rates, open interest or the perp basis is **off the table from this host** without a different egress.

---

## 2. The oracle map — read from the markets' own rule text, not assumed

Polymarket's crypto book is not one thing. Three regimes, verbatim:

| family | rule (quote) | source |
|---|---|---|
| `what-price-will-bitcoin-hit-on-<date>` (↑/↓ ladders) | *"any Binance 1-minute candle … has a final 'High' price equal to or greater than the price specified"* | **Binance** |
| `bitcoin-above-on-<date>-<hour>pm-et` (20-strike ladder) | *"the BTC/USDT 1 hour candle that ends on the time and date specified"* | **Binance** |
| `bitcoin-price-on-<date>` (11 ranges) | *"the final 'Close' price of the Binance 1 minute candle for BTC/USDT closing at 12:00 in the ET timezone"* | **Binance** |
| `bitcoin-up-or-down-<date>-<hour>pm-et` | *"the BTC/USDT 1 hour candle that **begins** on the time and date specified"* | **Binance** |
| `btc-updown-15m-<epoch>` / `-1h-` / `-4h-` | *"time-weighted average price (TWAP) … generated by Chainlink"* | **Chainlink** |
| Kalshi `KXBTC15M`, `KXBTCD` | *"the simple average of the sixty seconds of CF Benchmarks' BRTI before …"* | **CF BRTI** |

**Kalshi's oracle is a composite, and Binance is not in it.** From CF Benchmarks' own *Constituent
Exchanges List* (v13.7, 24 Aug 2026 — the primary document, fetched this session), the BRTI basket is:
Bitstamp, Coinbase, Kraken, Gemini, Bullish Exchange, Crypto.com, LMAX Digital — plus Bitfinex and
OKCoin.com (HK), both suspended Apr-17, and **itBit suspended 27-Jul-26**. **The document contains no
occurrence of "Binance" at all** (Bitstamp 49×, Crypto.com 79×, Coinbase 41×, Kraken 34×,
Gemini 20× … Binance 0×).

*That basket is not static:* Bitstamp was suspended from certain CF benchmarks on 2026-08-10 and itBit
removed 2026-08-27. Any strategy that treats "Kalshi BTC" as a fixed quantity inherits that churn.

---

## 3. The reconciliation numbers

### 3a. Polymarket — Binance-settled families reproduce **exactly**

Pull the tape ourselves from the keyless archive, apply the rule as written, compare with the venue's
own recorded outcome:

| family | markets reproduced | note |
|---|---|---|
| hourly "above" ladders | **1,440 / 1,440** | 72 hour-events × 20 strikes |
| hourly up-or-down (1 h candle) | **96 / 96** | open vs close of the candle *beginning* at the stated hour |
| daily "hit" ladders (↑ High / ↓ Low) | **48 / 48** | ↑ reads the *High*, ↓ reads the *Low* |
| noon-close ranges | **33 / 33** | included [lo, hi) semantics confirmed |
| **total** | **1,617 / 1,617 = 100.00%** | zero misses (shipped `--days 2` run: 1,062 / 1,062, same 100%) |

### 3b. Kalshi — a Binance proxy vs 6,525 recorded BRTI verdicts (69 days, 2026-08-06 → 10-13)

| | |
|---|---|
| agreement | **6,382 / 6,526 = 97.793%** |
| disagreements | 144, **all within $19.60** of the knife edge (median $2.40) |
| \|proxy delta\| p05 / median / p95 | **$4.67 / $57.47 / $279.00** |
| windows within ±$1 / ±$5 / ±$10 / ±$50 | 1.27% / 5.41% / 10.39% / 45.39% |

*Triangulation with the existing pair card:* Kalshi's BRTI and Polymarket's Chainlink **disagree with
each other** on 1.74% of windows (282/287, card `kalshi-pm-btc-pair-prereg`); a Binance proxy misses
Kalshi's BRTI **2.21%** of the time (different window set, so not a like-for-like contrast — but the
same order: this is basis noise, not a bug).

### 3c. Polymarket short-dated up/down — Chainlink is not reachable via Binance

Seven candidate proxy conventions, same 288 windows (3 days):

| convention | agreement |
|---|---|
| end_open ≥ start_open | **93.06%** ← best |
| end_close ≥ start_open | 92.36% |
| end_mid ≥ start_mid | 92.01% |
| end_close ≥ start_mid | 90.62% |
| end_close ≥ start_close | 87.15% |
| window mean ≥ start_open | 81.94% |
| end_close ≥ window mean | 77.08% |

**No convention is exact, and none is close to exact.** Binance cannot stand in for Chainlink's TWAP.

### 3d. When is a 15-minute window physically decided? (measured from the tape, n=6,526)

Calling the window off Binance alone at minute *m* (call = px(m) ≥ the 60 s pre-window average):

| min in | accuracy | accuracy at \|margin\| ≥ $50 | ≥ $100 | ≥ $200 |
|---|---|---|---|---|
| 0 | 53.9% | 62.0% | 73.3% | -- |
| 4 | 68.8% | 79.6% | 85.5% | 88.8% |
| 8 | 77.8% | 88.5% | 93.7% | 96.3% |
| 12 | 85.8% | 96.2% | 98.7% | 99.8% |
| 14 | 93.9% | **99.9%** | **99.9%** | **100.0%** |

Read: one minute before the boundary, a $50-clear call is right 99.9% of the time — but a $50-clear
call at minute 8 is only 88.5%, and at minute 4 only 79.6%. **Margins are not certainty; the curve is
the risk table.** This is the sizing input any 15-minute strategy needs, and it is measured, not assumed.

---

## 4. Traps (each one cost a measurement in this session)

1. **The bulk archive's timestamps are MICROSECONDS; the klines API's are MILLISECONDS.** The
   `open_time` in `data.binance.vision` daily ZIPs is `1.79e15` (µs) while `/api/v3/klines` returns
   `1.79e12` (ms). Comparing them matches *nothing* and silently falls through to a fallback: the first
   Kalshi run reported **50.95% agreement** purely from this, and looked like a real finding. Normalise
   before any join.
2. **Look prices up by timestamp, not by list position.** Even after fixing (1), an index-based slice
   (`w[i0:i1]`) mis-paired windows and produced deltas that disagreed with the venue ~50% of the time
   while *looking* plausible (all-positive, right magnitude). Timestamp lookups fixed it to 100% on a
   25-window hand-check, and the hand-check is what exposed the corruption.
3. **`↑` reads the candle's High, `↓` reads its Low.** Treating a `↓` ladder as an up-strike scored
   **54%** on 48 markets; the fix scores 100%. Labels are semantics, not decoration.
4. **A 1-hour up-or-down candle *begins* at the stated hour.** Anchoring on the candle *ending* there
   scored **43%** (worse than a coin flip) on 72 markets; the fix scores 100%. Off-by-one-hour on a
   price path produces believable-looking noise, not an obvious error.
5. **Binance is not in BRTI** (see §2) and PM's 15-minute family is Chainlink, so *neither* short-dated
   family can be settled from Binance. Only the price/threshold families can.
6. **The venue's `endDate` is not the settlement instant for every family** (from the weather study,
   same family of trap): key every join on the venue's own recorded result and its stated rule times,
   never on a slug or an assumed close.
7. **Geo-block shapes the product.** Futures are 451: funding-rate / open-interest / basis features are
   simply unavailable here, and they are the most obvious "binance data" ideas. Say no to them now
   rather than after building them.

---

## 5. What "enhance our bitcoin trading" can actually mean

Ranked by what the measurement supports, not by what sounds useful:

**A · Read-only harness — SHIPPED (no approval needed).**
`scripts/btc-oracle-reconcile.py`, keyless, writes only to `/tmp`. Reproduces §1 (hosts),
§3a (Polymarket Binance-oracle verdicts), §3b–d (Kalshi proxy agreement, knife-edge census,
decision curve). ~2–3 min from warm cache.

**B · RECOMMENDED — pre-registered "deterministic convergence" study on the Binance-settled families.**
This is the only place where **oracle risk is exactly zero**, because Binance *is* the settlement source
and we can compute the verdict ourselves to the cent: e.g. for an hourly 20-strike above-ladder, the
1-minute candle closing at the stated hour determines all 20 markets at that instant ("immediately
resolve", per the rule), and for a daily "↑ X" ladder the YES verdict is locked the moment a 1-minute
High touches X. The falsifiable questions: (i) at the instant the determining candle closes, is the
venue's price already 0/1 — or is there a measurable window where a **determined** leg still trades
away from 1.00 by more than the round-trip fee? (ii) for a not-yet-determined ladder, is the distance-
to-strike priced consistently with the realized distribution of BTC's remaining-horizon range (measured
from 1s tape)? Blocked-by-nothing, ~1 day to instrument, 2–4 weeks of forward samples, no orders.
Gate frozen before the first sample, floor stated up front, verdict `NO CLAIM` below the floor.

**C · Binance as a nowcast inside the live 15-min pair lane (card `kalshi-pm-btc-pair-prereg`).**
The pair lane already prices a *basis*: our two legs settle on BRTI vs Chainlink, and we know those two
disagree on 1.74% of windows. Binance's 1s tape gives a real-time estimate of the physical state
(§3d) that neither venue publishes before its own settlement instant. Worth a study, **not** a bolt-on:
any use must be pre-registered against the 288-window gate that is already running, or it becomes an
after-the-fact story.

**D · Live lane — explicitly not now.** No sizing, no orders, no venue decision on the strength of a
data-availability answer.

**Overridable flags** (one line each — say the word and I change it):

- **Asset universe** = *BTC only*. → change: the same oracle map covers ETH/SOL/XRP/HYPE/DOGE/BNB
  (`what-price-will-<asset>-hit-*`, `<asset>-above-on-*`) — the harness is BTC-hardcoded today.
- **Venue scope** = *Polymarket ladder families + Kalshi 15-min*. → change: drop Kalshi (it is a
  proxy, not an oracle, so it only ever yields an error rate) or add PM's Chainlink families as a
  §3c-style proxy study.
- **Futures** = *excluded* (451 from this host). → change: needs a different egress; say so if you want
  funding/OI features, because that is an infrastructure decision, not a data one.
- **History window** = *full available* (1m from 2017-08-17, 1s from 2022-06-01). → change: cap the
  backfill at N days if the bulk-ZIP volume matters to the backup guard.

---

## 6. Reproduce

```bash
python3 scripts/btc-oracle-reconcile.py --days 3 --json /tmp/btc-recon/btc-recon.json   # keyless, read-only
```

Keyless endpoints used (no auth anywhere): `data-api.binance.vision/api/v3/{ping,klines,aggTrades,
depth,ticker}` + `data.binance.vision/data/spot/daily/klines/BTCUSDT/1s/…zip`,
`api.elections.kalshi.com/trade-api/v2/markets?series_ticker=KXBTC15M&status=settled`,
`gamma-api.polymarket.com/events?slug=…`, and — for the oracle *definition* rather than prices —
`docs.cfbenchmarks.com/CME%20CF%20Constituent%20Exchanges.pdf` (v13.7, 24 Aug 2026) and the rule text
on each market.

*Caveats, stated so the numbers are not over-read:* the Polymarket reproduction is 1,617 markets over
3 days of settled cycles (the family is new and rotates daily, so the sample cannot be extended
retroactively for the *hourly* ladders); the Kalshi proxy result is 6,526 windows over 69 days, all of
it in Aug–Oct 2026 — the earliest period for which Kalshi listed this series; the Chainlink proxy table
is 288 windows over 3 days; the decision curve is measured against Kalshi's BRTI verdicts using a
Binance proxy, so it contains proxy error as well as physical determination. Wider claims need the
forward samples option B collects.
