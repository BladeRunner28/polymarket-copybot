# Asset audit — `parkyucheol-del/alphapipeline` (2026-10-19)

**Verdict: ❌ DROP as a dependency / ⚪ two ideas noted.**
It is a real, working, actively developed paid data API — not a stub — but for our Polymarket work it adds
**zero marginal information**: everything it returns about Polymarket is computed from the public, keyless
CLOB `/book` endpoint we can call ourselves for free, and the two pieces of arithmetic worth keeping are
~40 lines. Its "risk guard" behaviour rests on four hand-set constants with no calibration data anywhere in
the repo, so it must not be imported as a fill or cost model. The scout hypothesis that this is "a possible
second method for the fill model alongside the vike book archive" is **refuted**: it has no history and no
hazard estimate, only a live-book ladder walk with a guessed haircut.

Dashboard: http://localhost:3013/drafts/asset-audit-alphapipeline-20261019

---

## What it is

An x402-metered data API + remote MCP server (`POST /mcp`) run on Render, paid per call in USDC on Base
($0.005–$0.03), no signup and no API key. Twelve `prediction.*` endpoints cover Polymarket and Hyperliquid
HIP-4: neg-risk basket arbitrage, exit-capacity audit, order-split (TWAP/VWAP) guide, bid-ask spread,
orderbook imbalance, liquidity depth after haircut, taker fee estimate, mispricing, plus HL snapshot/ladder.
The rest of the catalogue is on-chain token/honeypot risk, Korean price premium, funding rates, DEX
slippage and SEC/macro calendars — none of it our beat.

## Anatomy facts that drove the verdict

| Fact | Value |
| --- | --- |
| Licence | MIT (`LICENSE`, 1069 B) — borrowable with attribution |
| Stars / forks / issues | ★1 / 0 / 0 |
| Created → last push | 2026-09-02 → 2026-10-19 (alive, and pushing code, not just data) |
| Code | 49 `.py` files, 1.02 MB; `app/logic.py` 184 KB, `app/mcp_server.py` 113 KB |
| Hygiene | **20 MB `mcp-publisher.exe` committed at repo root**; 16 `patch_*.py` scripts at root (self-patches, not centralised); `Claude outputs/`; `payer_endpoint_guess.ps1` |
| Tests | anatomy says `tests=yes`, but **there is no `tests/` directory**. Two root-level `test_*.py`: `test_oracle_gap.py` (a genuine monkeypatched unit test) and `test_clef_signal.py` (a live-API probe with no assertions) |
| CI | `.github/workflows/ci.yml` runs `python -m compileall -q .` — **a syntax check that executes no tests**. Runs are green (3/3 on 2026-10-18), so this is a *green suite that proves nothing*, not a broken one |
| Wire-up | The prediction endpoints are **not** dead code: 12 routes registered and priced in `main.py:282-293`, with handlers in `main.py:1011-1251`. This is the opposite of the zero-call-site trap |

The one-day burst of Polymarket endpoints on 2026-10-18 (`order_split_guide`, `orderbook_imbalance`,
`polymarket_fee_estimate`, `polymarket_mispricing`) is real feature work, not scaffolding.

## Verified machinery (transcribed from source, checked numerically)

Job constraint is read-only / no execution of candidate code, so I transcribed each helper verbatim into a
scratch script and compared it against an independent brute-force oracle (200 000 slices per level).
Synthetic ladders used: asks `0.42×120, 0.44×300, 0.47×900, 0.51×5000`; bids `0.40×80, 0.37×250, 0.33×1500`.

1. **`_leg_vwap_price_for_shares`** (`app/logic.py:2290`) — plain ladder walk, `cost/filled`. **Exact match**
   to the oracle at 50/120/420/1000 shares on both sides. Correct.
2. **`_cumulative_shares_within_avg_price`** (`app/logic.py:2936`) — walks levels accumulating shares and
   notional, and on the level that breaks the average-price constraint solves the linear interpolation
   `x = (cum_notional − T·cum_shares) / (T − p)`, clamped to `[0, size]`. That is exactly the root of
   `(cum_n + x·p)/(cum_s + x) = T`. **Matches brute force to ≤8×10⁻⁶ relative error across 10 side/impact
   combinations** (0.5/1/2/5/10 % impact, buy and sell). Correct.
3. **`polymarket_fee_estimate`** (`app/logic.py:3053`) — `fee = shares · rate · p · (1 − p)`, with `rate`
   read live per token from Polymarket's `GET /fee-rate` (`base_fee` in bp). **Same shape as our own
   `takerFeePerShare` at `src/lib/scoring/price-edge.ts:56`** — so the fee *curve* is not a gap for us.
4. **Definitional inconsistency (not a bug):** the file carries *two* different meanings of "how much can I
   actually take". `_leg_capacity_shares` (`:2278`) — used by the neg-risk basket's liquidity bottleneck —
   sums sizes whose **level price** falls inside a ±slippage band. `_cumulative_shares_within_avg_price`
   enforces slippage on the **average execution price** instead, and is the looser of the two (band 120 vs
   avg 152 shares at 1 % impact on the synthetic ask ladder). Both are defensible; they are not the same
   quantity, and the endpoints' outputs are therefore not comparable to each other.

## What it does NOT contain (the part that kills the fit)

- **No historical data.** Every prediction endpoint reads the live CLOB `/book` at call time.
  `data-public/` holds BTC cycle metrics, a Kalshi BTC-15m log and a stock-discrepancy log — **no L2, no
  Polymarket time series**. Point-in-time history starts when you start recording, so this can never
  backfill the pre-2026-08-31 gap that `drafts/asset-audit-vike-data-cli-20261018.md` measured.
- **No fill or queue model.** The nearest thing is `get_liquidity_depth_after_haircut`, which multiplies the
  top level's size by `(1 − haircut_pct/100)`. The constant is `haircut_pct = 10.0` — a default with no
  measurement behind it anywhere in the repo (no calibration file, no test, no data). Its own docstring
  correctly says a top-of-book capacity number is optimistic; the replacement is a guess, not an estimate.
- **No calibration of any kind:** `assumed_round_trip_cost_pct = 1.5`, `max_price_impact_pct = 5.0`,
  `min_net_edge_pct = 1.0` are all hand-set. The neg-risk "net edge" is gross edge minus that flat 1.5 %,
  which lumps taker fees, conversion cost and slippage into one invented number.

## Fit table vs `data/roadmap.json` (208 cards)

| Component | Card that asks for it | Verdict |
| --- | --- | --- |
| Ladder-walk VWAP / avg-price-constrained depth | `phase-d2-fill-model` (Cox-PH paper fill model) | ⚪ **concept only** — verified absent from our stack (`grep -rn "vwap\|VWAP" scripts/ src/` finds only Kalshi bar VWAP in `kalshi-tape-capture.py`), but it is 40 lines and it models a *taker* walk, while C-200 is a maker lane |
| Top-level haircut as a cancel-risk adjustment | `phase-d2-fill-model` | ❌ **not portable** — the 10 % constant is unmeasured; our own `scripts/c200-printthrough.py` already states that a touch is not queue position. A haircut on *size* cannot substitute for a hazard rate, and our touch test is a *price* test, so the haircut would not even change `askAtLevel` unless a level is fully consumed |
| Live per-token `GET /fee-rate` (`base_fee` bp) | none directly; `phase-d2-fill-model` for forward costing | ⚪ **one-input gap, and only forward.** We hardcode `CAT_RATE`/`DEFAULT_RATE = 0.05` in `scripts/c200-fee-reprice-archive.py`. The donor's "never hardcode, read live" advice is right for *forward* quoting and **wrong for repricing history** — today's `base_fee` is not the trade-time rate, and using it to reprice past fills would inject look-ahead. Do not apply it to the archive script |
| Neg-risk YES-basket arbitrage (sum of best asks < $1, capacity = min leg) | **no card** — `phase-c` is *cross-venue* arb gated on Kalshi recovery; single-venue neg-risk basket arb is not carded | ⚪ concept, not now. Also: it needs simultaneous fills across n legs plus neg-risk conversion, and its cost model is the invented 1.5 % |
| Metered API / MCP server / x402 payments | — | ❌ not portable: a paid USDC-settled external dependency in the live path |
| HL HIP-4, honeypot checks, Korean premium, funding rates, DEX slippage, SEC/macro | — | ❌ outside our beat |

## Why DROP rather than watch

- **The upstream is public and keyless.** Polymarket's CLOB `/book`, gamma market objects and `/fee-rate`
  are free; this service is a paid wrapper over them plus arithmetic we have now verified and can write.
  A dependency here buys latency and ops burden, not information.
- **The measured gap it was scouted for does not exist.** We do not get a fill model out of it; we get a
  ladder walk we already know how to write.
- **The unmeasured constants are the actual product.** Four invented thresholds are exactly what our
  `phase-d2-fill-model` card must not inherit — our own printthrough doc is careful to say a touch proves
  reachability, never a fill, and this repo's answer to that is a 10 % haircut with no data behind it.
- **MIT + real code, so nothing is lost by dropping it:** both helpers are transcribed above and can be
  re-derived from this document in an hour if a card ever needs them.

## Honest caveats on this audit

- I did not run their code (job constraint: read-only, no execution) and there is effectively no test suite
  to run — CI is `compileall` only. My numerics are a transcription check of the published arithmetic
  against a brute-force oracle, not a green-suite signal.
- I did not call the live paid service; correctness of their *live* Polymarket parsing (`_parse_book_levels`,
  string→float, sort direction) is read from source only.
- Star count (★1, six weeks old) is a community signal, not a maintenance one — the commit log shows daily
  data commits plus real feature work, so I am *not* calling it abandoned.

## Registry block (not applied — this job writes no roadmap/card files)

Ready to paste into `phase-d2-fill-model`'s `note`:

```
AUDIT INPUT (2026-10-19, drop; drafts/asset-audit-alphapipeline-20261019.md):
parkyucheol-del/alphapipeline (MIT, ★1, active) - paid x402 CLOB wrapper, live books only, no history.
Verified correct in source: ladder-walk VWAP, avg-price-constrained depth (linear interpolation, matches
brute force <=8e-6), fee = shares*rate*p*(1-p) reading live GET /fee-rate. Refuted as a fill method:
no queue/hazard estimate, haircut_pct=10 is a guess, cost constants (1.5%/5%/1%) unmeasured.
Not adopted. Keep one idea: live base_fee per token for FORWARD cost only - never for historical
repricing (look-ahead). No L2/neg-risk capacity numbers to be taken from this repo.
```

## Recommendation

**Drop** — no queue item, no approval ask. Nothing enters the codebase; the two verified primitives live in
this document if a D2 sub-task ever wants them.
