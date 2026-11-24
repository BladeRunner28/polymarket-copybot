# ccxt/ccxt — RE-AUDIT (2026-11-23)

**Revision note:** this is a re-surface pass over the standing audit `drafts/ccxt-audit.md` (2026-09-08), not a new audit. The standing verdict ("✅ adopt as the Phase C multi-venue quote backbone") is **unchanged**; what this pass adds is (a) the new `ts/src/prediction/` namespace, which is now real code, and (b) two verified traps and two verified "already ours" that a fresh auditor would otherwise praise.

**Verdict: ⚪ WATCH (standing) — no change in timing. Phase C is still `Backlog`; nothing to build.**

## Freshness (API, 2026-11-23)

- Commits since the standing audit (2026-09-08): **≥100** (API page cap hit at 100), last push 2026-11-23.
- Releases: v4.5.93 (2026-11-17), v4.5.94 (2026-11-23).
- Stars 43.9k → **44,971** (+~2.4%, +~1,070). Forks 8,995 · open issues 769 · MIT · not archived.
- Alive and releasing twice a week. This was never the question — the question is fit.

## What changed on their side since 2026-09-08

A dedicated prediction-market namespace, not the exchange base with PM mapped onto it:

- `ts/src/prediction/` (added ~2026-10-22) + a `js/` mirror, 9 venues.
- Sizes read off the repo: `polymarket.ts` **3,415 lines / 183 KB**, `predictfun` 217 KB, `myriad` 201 KB, `limitless` 168 KB, `sxbet` 149 KB, `kalshi` 138 KB, `opinion` 111 KB, `hyperliquid` 108 KB.
- 39 public methods on Polymarket incl. `fetchEvent`, `fetchOutcome`, `fetchOrderBook`, `fetchTrades`, `fetchTick*`, `fetchOHLCV`, `fetchOpenInterest`, `fetchTradingFee`, plus `watchOrderBook` / `watchTrades` / `watchTicker`.
- `requiredCredentials` on Polymarket: `apiKey: false`, `privateKey: false` — **reads are keyless**, exactly as the queue note claimed. Confirmed in source, not from the README.

## What changed on our side (this is what moves a verdict)

- **`scripts/record-l2.ts` (433 lines, v40)** already subscribes `wss://ws-subscriptions-clob.polymarket.com/ws/market`, keeps a top-25 book, stores `book` / `price_change` / `ltp`. Card `l2-subscribe-at-dispatch` is In Review. → ccxt's `watchOrderBook` is **not a gap**.
- **`src/lib/fee-capture.ts`** (2026-09-28 findings) → ccxt's fee surface is a trap (below).
- **Kalshi cross-venue is already bespoke and live**: `kalshi-pm-btc-pair-prereg` APPROVED+IMPLEMENTED, `kalshi-tape-capture-live` at 93% duty, 12 `scripts/kalshi-*.py` readers. → ccxt's Kalshi venue is **not a gap** either.
- **Slug addressing is already ours**: `src/lib/fee-capture.ts:18` states `GET /markets/slug/<slug>` returns the row for open AND closed markets; the slug path is used in `src/lib/adapters/polymarket.ts`, `gamma-market-payload.ts`, `monitor-trades.ts`, and carded at `polyterm-p4-gamma-slug-endpoint`. ccxt's gamma slug endpoints (`markets/slug/{slug}`, `events/slug/{slug}`, `series-summary/slug/{slug}`, `tags/slug/{slug}`) reproduce a primitive we already run.

## Verified negatives — do not wire these in a future Phase C pass

1. ❌ **`fetchTradingFee` is a wrong number presented as authoritative.** Source: it calls `clobPublicGetFeeRate`, reads `base_fee` (e.g. `{"base_fee": 30}`), and returns `base_fee/10000` as **both `maker` and `taker`** with `tierBased: false` — no flag, no fallback label. Our `fee-capture.ts:32-34` measured the same endpoint: `takerBaseFee` / `makerBaseFee` / CLOB `/fee-rate.base_fee` are a **static 1000 on ~85% of markets regardless of schedule**, so we report it as `source: "clob"` and let the caller flag it. Adopting ccxt's fee call would swap a flagged proxy for an unflagged one — and our live model is the `rate × p(1−p)` curve (politics 0.04 / crypto 0.07), not `base_fee/10000`.
2. ❌ **ccxt's Kalshi venue requires keys.** Its describe block sets `'apiKey': true` (KALSHI-ACCESS-KEY) and `'privateKey': true` (RSA PEM for signing). Our Kalshi lane is keyless at `api.elections.kalshi.com` and already in production. A key-declaring dependency has no place near a keyless read lane.
3. ❌ **Vendoring the library.** 9.0 GB, 9,911 files, 5 languages. If a data-breadth need appears, install `ccxt` as a **pinned dependency** (Python or TS surface); never vendor.

## Standings that survive

| Component | Verdict | Card that asks for it |
|---|---|---|
| Cross-venue quote breadth across the 5 PM venues we don't touch (opinion, predictfun, limitless, myriad, sxbet) + Hyperliquid funding/OHLCV | ✅ adopt **when** Phase C fires, as a pinned dep, data-only | `phase-c` (Backlog) |
| Symbol/outcome normalization as a reference implementation | ⚪ concept — read `ts/src/prediction/polymarket.ts` + `kalshi.ts`, don't depend | `phase-c` |
| WS orderbook stream | ❌ already ours (`scripts/record-l2.ts`) | `l2-subscribe-at-dispatch` |
| Gamma slug addressing | ❌ already ours (`fee-capture.ts`, adapters) | `polyterm-p4-gamma-slug-endpoint` |
| Fee rate surface | ❌ do not adopt (`base_fee` is static) | none — `src/lib/fee.ts` is the source of record |
| Kalshi venue adapter | ❌ requires RSA key + apiKey | none — keyless scripts own this |

## If Phase C ever fires

Read `ts/src/prediction/polymarket.ts` + `kalshi.ts` for the normalize-to-one-symbol-space shape; install `ccxt` pinned as a **data-only** dependency behind a flag; keep our CLOB execution, our fee model (`src/lib/fee.ts`), and our keyless Kalshi readers. Effort ≈ ½ day read + 1–2 days for a quote-normalization prototype; revert = remove the dependency. Risk: it is an abstraction over data we already read bespoke — it buys breadth, not accuracy, and must never be on the live decision path.

## Honest caveats

- 769 open issues at 45k★ is normal triage, not a warning — but the Monorepo is deep; pin the version.
- README markers `coming soon` / `analytics` are boilerplate over 96 MB of `.js` and 39 MB of `.py`; code mass is real. No return claims anywhere — this is infrastructure, not a strategy.
- `fetchPositions` needs `walletAddress`; irrelevant to us (we read public profiles/leaderboard only).
- I did **not** run their suite (cron approval layer blocks script execution by flag; and it is a 9 GB multi-language matrix). No CI-health claim is made here.
- **The gain is breadth on venues we don't trade yet, not accuracy on the two we do.** That is why the verdict is watch, not adopt-now.

## Card block (ready to paste into `phase-c.note`)

```
AUDIT INPUT (2026-11-23, re-audit; drafts/ccxt-reaudit-20261123.md): standing 2026-09-08 adopt-as-backbone verdict STANDS, timing unchanged (Phase C Backlog). New since then: ts/src/prediction/ namespace is real code (polymarket.ts 3,415 lines/183KB; 9 venues) and Polymarket reads are keyless in source (apiKey:false/privateKey:false). Three verified negatives so a future build does not wire them: (1) ccxt fetchTradingFee returns clob /fee-rate.base_fee /10000 as BOTH maker and taker, tierBased:false, unflagged — fee-capture.ts measures base_fee as a static 1000 on ~85% of markets, so our fee.ts curve stays the source of record; (2) ccxt's Kalshi venue declares apiKey:true + privateKey:true (RSA PEM) — our Kalshi lane is keyless and live, do not import it; (3) watchOrderBook is duplicated by scripts/record-l2.ts and gamma slug addressing is already ours (fee-capture.ts:18, polyterm-p4-gamma-slug-endpoint). Net: ccxt buys breadth across opinion/predictfun/limitless/myriad/sxbet only; install pinned as data-only dep, never vendor (9.0GB).
```
