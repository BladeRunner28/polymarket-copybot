# Asset audit — `agent-next/polymarket-paper-trader` (2026-10-15)

**Verdict: WATCH — do not adopt the repo; one narrow, verified-new extract (the archived-market fee
source). The headline capability the lead was enqueued for (venue fee-schedule truth) is already
carded and instrumented in this repo since 2026-09-28.**

Lead source: `drafts/asset-audit-awesome-trading-agents-20261015.md` §3 (enqueued 2026-10-15 12:25 CDT,
note: "PM paper-trading simulator + live order books + claimed official fee model + fill-fidelity
benchmark harness + PROVENANCE.md"). Read-only: no clone, no install, no execution of candidate code.

## 1. What it is

A Python paper-trading simulator + benchmark harness for Polymarket ("a zero-risk gym for AI agents"):
`pm_trader` CLI/MCP server (paper book, live order books, fee model, Kalshi support), `benchmark/`
(a Brier/calibration/alpha scoring harness + the public "Forecast Arena" leaderboard), and
`leaderboard-server/`. MIT, published on PyPI, ~1.8 MB of Python across 229 files.

## 2. Anatomy facts that drove the verdict (deterministic, 2026-10-15)

| Fact | Value |
| --- | --- |
| Licence / archive | MIT · not archived · **fork: false** (org-owned) |
| Stars / forks / open issues / watchers | ★499 · 65 · 1 · 11 |
| Created / last push | 2026-03-01 / **2026-10-16T00:31Z** (alive; v0.4.13 released today) |
| Commits since 2026-10-01 / contributors | 100 (page-capped) / 3 |
| Code | 229 files · .py 1,810 KB/140 files · .md 170 KB/24 · tests=yes ci=yes docker=yes **lock=NO** |
| Test corpus | `tests/test_engine.py` 116 test fns (76.8 KB), `tests/test_orderbook.py` 85 (45.8 KB), `test_backtest.py` 17, `test_e2e_live.py` 36.5 KB (live-gated), `benchmark/tests/test_arena*.py` 165 KB |
| CI health (read off the API, not assumed) | Tests / Toolkit CI / Publish all `completed/success` on `55bb35b` 2026-10-15T23:04Z |
| Hygiene | `PROVENANCE.md` documents 3 imported subtrees with a gitleaks scan; no telemetry markers; no hype markers |

Claim-vs-substance: the README is long but the tree backs it — 1.8 MB of Python, real CI, real releases.
This is a **substantive** repo, not spam.

## 3. Verified machinery (read from source, reconciled against the venue)

- **Fee curve — verified correct against the venue docs, not just self-consistent.**
  `pm_trader/orderbook.py:calculate_fee_schedule` = `round(shares * rate * (p*(1-p))**exponent, 5)`.
  `docs.polymarket.com/trading/fees` (fetched 2026-10-15) states verbatim `fee = C × feeRate × p × (1-p)`,
  "Makers are never charged fees. Only takers pay fees.", "Fees are rounded to 5 decimal places …
  smallest fee charged is 0.00001 USDC". Its own docstring cites that page. Numeric reconciliation
  against the docs' 100-share fee table: 100×0.07×0.25 = **1.75** (crypto), ×0.05 = **1.25** (sports),
  ×0.04 = **1.00** (finance/politics) — the published table's peak fees exactly. **Their arithmetic,
  the 5-dp rounding and the maker semantics are all right.**
- **Maker semantics:** `_maker_fee` returns `0.0` when `feeSchedule.takerOnly` (true on every market I
  sampled) — matches the docs. The `else` branch ("makers pay the taker fee") is Kalshi's `makerRate`
  series, not Polymarket.
- **Fee schedule is read from the venue per market**, two shapes: Gamma `feeSchedule{rate,exponent,
  takerOnly,rebateRate}` and the CLOB abbreviated block `fd{r,e,to,rr}` on
  `/clob-markets/{condition_id}` (`api.py:_clob_fee_schedule`).
- **Per-level fee summation:** the fee is charged per matched level at that level's own price
  (`engine.py:_fill_fee`, `orderbook.py:simulate_*_fill` walking the book), not once at the average price.
- **Fill simulation:** `fok`/`fak` semantics, `max_price` limits, per-level `Fill` records.
- **Benchmark harness:** `compute_brier_score`, `compute_calibration_error`, `compute_alpha_score`,
  `compute_composite_score` (`benchmark/pm_benchmark/scoring.py`) — model-forecast evaluation, not trading.

## 4. Fit table vs our stack (baseline = Rust sidecar + TS pipeline + Prisma book)

| Component | Our state (verified) | Verdict |
| --- | --- | --- |
| Fee **curve** `rate·p(1−p)` | `src/lib/scoring/price-edge.ts:takerFeePerShare` — same curve | ⚪ already have (identical) |
| Fee **rate input** (venue truth per market) | `data/fee-schedules.jsonl` (48 rows, 2026-09-28) + `scripts/capture-fee-schedules.ts` (npm `capture:fees`) — captured, **not read by the live path**; card `paper-ledger-fee-fidelity` (Backlog) owns it | ⚪ carded/in flight — not a new finding |
| **Archived-market fee source** `clob-markets/{cid}.fd` | `clob-markets` appears **0 times** in `src/`, `scripts/`, `drafts/` — verified absence | ✅ **adopt-slice** (this draft, §5) |
| Per-level fee summation in fills | not modelled (single charge at entry/exit price) | ⚪ concept — matters only if we model depth fills (`phase-d2-fill-model`) |
| Maker/taker split + `rebateRate` | `takerOnly`/rebate noted in samplers; rebate **unmodelled**; open question R2 on the fee card | ⚪ already carded (R2) |
| The simulator itself | our Prisma book + Rust sidecar | ❌ not portable |
| Forecast Arena / benchmark harness / leaderboard | we score wallets (`insider.ts` Brier) and probabilities, not LLM forecasts | ❌ not portable |
| MCP server, remote auth, Kalshi client | we have our own; Kalshi copy-routing retired | ❌ not portable |
| Their fee/fill **test corpus** (85 + 116 test fns) | reference spec for fee/fill edge cases (dust trades, 5-dp rounding, level-walk partials) | ⚪ reference only |

## 5. The one extract, and why it matters (measured on our own book)

`clob-markets/{conditionId}` returns `fd` = `{"r": <rate>, "e": 1, "to": true}`. Measured 2026-10-15 on
the 25 newest `BANKROLL_200` legs (read-only, keyless):

- Gamma still serves **6/25** of those markets (it purges resolved/daily markets — cf.
  `src/lib/dead-slug-cache.ts`); the CLOB `fd` block resolves **25/25 = 100%**.
- `fd` key set was `{e,r,to}` on all 25 — **no `rr`**, so this source gives the *rate* but cannot close
  the fee card's rebate question R2.
- Venue rate was **0.05 on all 25** → proxy Δ = **$0.0000** on the recent book. The coverage win is
  verified; the re-pricing win on *this* window is not (state it, don't imply it).

Our carded capture only ever samples *active* markets (Gamma top-volume), so the fee-fidelity work as
specified can never be applied to the settled ledger. This source can.

Independently re-measured fee-proxy error (keyless Gamma, 2026-10-15, top-500 by volume, n=400 with a
schedule): live rates are only 0.03 / 0.04 / 0.05 / 0.07; **170/400 (42.5%) disagree with our keyword map
and 38.8% of 24h volume sits on a wrong proxy**; in the default bucket **133 over-charged vs 10
under-charged**; 59/500 markets carry `feesEnabled:false` + no schedule (geopolitics, fee-free) where we
charge the 0.05 default (+0.0125/share at p=0.50). Both directions confirmed against our own 2026-09-28
capture (27 exact / 21 differ / 14 venue-zero of 48). Only `crypto` (88/99) and `pol/fin` (80/90) hold up.

Scope honesty: **the paper ledger charges no fee at all** (no `fee` reference in `pnl-rollup.ts` /
`paper.ts` / `update-pnl.ts`), so this error is confined to shadow measurement — the price-edge gate's
fee term and the ML-1 net-of-fee labels — never to booked PnL.

## 6. Risks / NOT portable

- **Keys:** the repo's live/remote paths expect a wallet/account (`remote_auth.py`, `pm_trader/mcp_server.py`);
  never touch them. Paper use needs none, but the surface exists.
- **Dependency weight:** Python/PyPI/MCP into a TS + Rust stack — reimplement, never vendor.
- **Untrusted code:** not executed here (no clone/install by job constraint); CI greenness read off the API.
- **`takerBaseFee`/`makerBaseFee` = 1000 on every sampled market** — a static field, not market truth;
  a `base/10000` fallback prices 0.10/share. Our capture already recorded this trap; do not reintroduce it.
- The repo's `_maker_fee` "otherwise makers pay the taker fee" branch would contradict Polymarket docs if
  ever hit on Polymarket — do not copy that branch.

## 7. Recommendation (recorded in the asset queue)

```
REC — Fee source that survives the purge: price archived markets' fees from the CLOB `fd` block
  Hypothesis:   Venue fee rates are retrievable for markets Gamma has purged (`clob-markets/{cid}.fd.r`),
                so the settled ledger can be fee-priced on venue truth instead of a slug-keyword proxy.
  Measurement:  read-only replay over every settled C-200 leg's conditionId: resolve the venue rate from
                `clob-markets/{cid}.fd.r` (+ Gamma `feeSchedule` where it still serves), re-price the entry
                fee at each leg's entryPrice, report coverage %, venue-vs-proxy Δ$ and any sign flip.
                (Coverage half already measured: Gamma 6/25 vs CLOB fd 25/25 on the newest 25 legs.)
  Decision rule: if fd resolves >= 90% of settled legs AND |Δ total fee| >= $25 or any leg's net sign
                flips, then price fees from the venue rate inside the `paper-ledger-fee-fidelity` card;
                else keep the proxy and record the null.
  Cost:         ~1-2 h, read-only (keyless), zero live-lane risk
  Reversibility: drop the source from the fee-source list; touches no rule, size, gate or published number
```

**AUDIT INPUT (2026-10-15, watch; drafts/asset-audit-polymarket-paper-trader-20261015.md)** — card owner is
`paper-ledger-fee-fidelity` (Backlog): its capture samples *active* markets only (Gamma top-volume), so the
fee assumption can never be applied to the settled ledger. The CLOB `clob-markets/{conditionId}` `fd`
block resolves the venue rate for **25/25** of the newest C-200 legs where Gamma serves 6/25 (verified
2026-10-15; `fd` carries `r,e,to` — no rebate field, so R2 stays open). Ready to paste — no roadmap/registry
write was made by this job (recommendations-only constraint); apply deliberately.

## 8. Honest caveats

- No test was run and no code was executed here (job constraint). CI state is read off the Actions API.
- The Donor's "official fee model" claim is **verified true** — say so; the audit's finding is that we
  already have the curve and the capture, not that the repo is wrong.
- The `$0` proxy delta on the newest 25 legs is a real result and cuts against the extract's value on that
  window; the extract's case rests on coverage (archived markets) and on the older population where the
  proxy is wrong in both directions (42.5% of markets, 38.8% of volume).
- Drafts on sibling files: `drafts/print-type-and-fee-measurement-2026-09-28.md` (fee capture + open
  question R2), `drafts/polyterm-audit-2026-09-28.md` (capture script's origin, missing-vig backtest
  +$5,397.60 → +$2,933.77 with 238 winner→loser flips).

Dashboard: http://localhost:3013/drafts/asset-audit-polymarket-paper-trader-20261015
