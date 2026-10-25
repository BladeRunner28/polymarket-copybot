# Asset audit — `mileswangs/pm-hftbacktest` (2026-10-24)

**Verdict: WATCH — reference only, no port.** MIT, alive, real code, and one genuinely verified formula
its binary fee model), but every component worth taking is either **already implemented here** (the fee
law) or **blocked on data we do not hold** (trade-at-level flow for a queue model) — and the question the
engineering would answer was already answered empirically by `c200-intent-printthrough-check`.

- Repo: https://github.com/mileswangs/pm-hftbacktest · ★126 · 25 forks · 0 open issues · MIT
- Created 2026-05-06 · last push 2026-10-22 · releases v1.0.10 (2026-10-14), v1.0.11 in pyproject
- Audit method: GitHub API reads only — no clone, no install, no execution of donor code (cron constraint)
- Report served at http://localhost:3013/drafts/asset-audit-pm-hftbacktest-20261024

---

## 1. What it is

A republished derivative of `nkaz001/hftbacktest` (MIT, ★4,971) with **Polymarket-specific plumbing** on
top. The GitHub API reports `fork: false` — this is not a fork in GitHub's sense, it is a fresh repo
created 2026-05-06 with the upstream tree imported in one commit, and **4 commits since** (the delta):

| Date | Commit |
| - | - |
| 2026-08-01 | Add Polymarket binary fee model |
| 2026-08-01 | Disable unused S3 support in Python build |
| 2026-10-14 | Improve project description and bump version to 1.0 |
| 2026-10-22 | Use PMData V1 Market API in README and examples, bump |

The transferred asset is therefore **not** the simulator (that is upstream's, four years of it) but:

1. `BinaryFeeModel` — `fee = qty × rate × p × (1−p)`, maker rate may be negative for rebates
   (`hftbacktest/src/backtest/models/fee.rs`, ~40 LOC + 4 in-crate tests). **Not present upstream** —
   upstream `fee.rs` is 153 lines with only value/qty/flat models; this one is 243 with the binary model.
2. `BacktestAssetPoly` preset + `polymarket_to_hbt` loader + `PolyAssetRecord` stats adapter
   (`py-hftbacktest/`), i.e. Polymarket parquet → the engine's normalised event stream, with the
   **winning outcome injected as the terminal book** (settlement modelled as a final print).
3. Two strategy notebooks on Polymarket's slug-based **5-minute up/down** markets (endgame, reverse) —
   the market family our own BTC lanes read.

Everything else in the repo — L2/L3 depth engines (`depth/`, 130 KB), queue and latency models,
partial-fill exchange processors (`proc/`, 75 KB), the live bot + iceoryx IPC — is upstream code.

The advertised data source is **pmdata.dev, API key required** (README: "Get an API key from pmdata.dev
before running the example"). No Polymarket connector or collector exists in the repo
(`connector/src/` = binancefutures, binancespot, bybit, hyperliquid; `collector/src/` = binance*, bybit,
hyperliquid): nothing here can place an order or pull venue data on its own.

## 2. Anatomy that drove the verdict

| Signal | Reading |
| - | - |
| Licence | MIT (root LICENSE, 1,093 B) — borrowable with attribution |
| Activity | push 2026-10-22, release 2026-10-14, stale-bot running nightly — alive, not dumped-once |
| Substance | 91 Rust files / 879 KB, 35 Python / 303 KB, 7 notebooks / 5.7 MB (66 % of tree bytes is notebooks + PNGs) |
| Tests | 9 pytest tests (`py-hftbacktest/tests/`), **≥6 Polymarket-specific**: asset preset, binary fee through the builder, `PolyAssetRecord`, and 4× `polymarket_to_hbt` (incl. "uses winning outcome as final book", "rejects null trade price") |
| CI | `codeql.yml`, `release-python.yml` (workflow_dispatch only), `stale.yml`. **No test workflow** — the suite is nowhere gated. Release runs: 3/3 success, and they only build wheels |
| Their own roadmap | unchecked: "Increase documentation and test coverage"; "Github workflow: readthedocs, build, formatting, coverage" |

So: *quality* signals are decent (tests exist, licence clean, alive, 0 open issues), and **fit** is the
thing that fails. A green-ish repo is a reason to read it, not to adopt it.

## 3. Verified machinery

**Only what I could verify from source plus the venue's own documentation. Nothing here is a run of their
code** (no Rust build, no pytest in this run — see §6 caveat 2).

### 3a. Binary fee model — verified numerically against the published venue table

Source (`fee.rs`, `impl FeeModel for BinaryFeeModel<CommonFees>`):

```rust
let price = order.exec_price();
self.fees.select(order.maker) * order.exec_qty * price * (1.0 - price)
```

Venue law (`docs.polymarket.com/trading/fees.md`, fetched 2026-10-24): `fee = C × feeRate × p × (1−p)`,
makers never charged; Crypto 0.07, Sports 0.05, Politics/Finance 0.04, **Geopolitics 0**.

I parsed the doc's published 100-share Crypto fee table (21 rows, p = 0.01…0.99) and evaluated the donor's
formula on each row (`verify_fee.py`, scratch): **max deviation $0.0025 per 100 shares** — the table is
rounded to cents, so this is exact agreement. The negative-maker-rate encoding also checks out: maker rate
`−0.07 × 0.2` at p = 0.50 gives −$0.35, exactly the 20 % crypto maker rebate at that point.

**Era note (this is the trap in the number):** this is the **current** published law. Our archive
calibration (`bt-fee-maker-calibration`, $1.21 B of fees) measured the **2026-era** law as
`0.10 × shares × min(p, 1−p)` on 95–99 % of rows to 1e-6 — the two shapes differ ~4× at mid price.
The donor is on the current side of the change. Our live `takerFeePerShare(price, rate)` in
`src/lib/scoring/price-edge.ts:56` is the same shape with the rate passed in, so **this is corroboration,
not a capability gap**; and `rate`/`rebateRate` are already captured by
`scripts/capture-fee-schedules.ts` from the venue's structured fields.

### 3b. Queue position — formula read from source; invariants re-derived, not executed

Three models in `hftbacktest/src/backtest/models/queue.rs` (46 KB):

- `RiskAdverseQueueModel` — conservative FIFO: queue position advances **only** when trades occur at the
  same price level.
- `ProbQueueModel<P>` + `PowerProbQueueFunc(n)` — advancement probability
  `prob = f(back) / (f(back) + f(front))`, `f(x) = xⁿ`; on a depth change,
  `est_front = front − (1 − prob)·chg + min(back − prob·chg, 0)`, with trade-implied quantity subtracted
  from `chg` to avoid double-counting (their comment says so explicitly).
- `L3FIFOQueueModel` — market-by-order FIFO.

Invariants defensible from the code: `back = 0 ⇒ prob = 0 ⇒` cancels advance us fully; `front → 0 ⇒
prob → 1 ⇒` only trades advance us; `front` is clamped to `new_qty`; fills fire when `front_q_qty` goes
negative (`is_filled` = `round(−front/lot_size)`). Direction is conservative, which is the right bias for a
fill assumption.

**But the exponent is a free parameter with no calibration anywhere in the repo** — the shipped example
hardcodes `PowerProbQueueFunc3::new(3.0)` (`hftbacktest/examples/gridtrading_backtest_args.rs:79`). So this
is *portable arithmetic with a guessed constant*, not a measured fill model.

### 3c. Settlement

`polymarket_to_hbt` injects the winning outcome as the final book (one of the four tested behaviours) —
the one piece of engine logic a binary-market simulator genuinely needs and non-PM backtesters lack.

## 4. Fit table vs `data/roadmap.json` (grep-verified)

| Donor component | Our state (verified) | Card that asks for it | Verdict |
| - | - | - | - |
| `BinaryFeeModel` (rate-parameterised `p(1−p)`) | `takerFeePerShare` price-edge.ts:56 = `rate·p·(1−p)`; per-market `feeType`/`feeSchedule` captured in `scripts/capture-fee-schedules.ts` | none (fee-fidelity cards are Done/Backlog and ahead of it) | ⚪ concept only — corroboration; nothing to build |
| Negative maker rate as rebate encoding | `rebateRate` already captured; paper ledger charges taker fee only | `paper-ledger-fee-fidelity` (Backlog) owns fee fidelity | ⚪ concept only |
| Queue-position `P(fill)` models | Empirical, not simulated: `scripts/c200-printthrough.py` over `data/l2/` + the venue tape | **`phase-d2-fill-model`** (Backlog; gate "~2 weeks of data/l2/ — met: 43,980 asset files / 19 GB) | ⚪ concept only — take the power-probability recurrence, not the crate |
| Latency models | No latency model in the paper path; lane is a copy-**taker**, not a maker HFT | none | ❌ not portable now |
| `polymarket_to_hbt` + poly asset preset + settlement-as-final-book | We hold a full-ladder 5 s corpus (`data/l2/`, top-25 with sizes) that would convert cleanly; no strategy simulator exists or is asked for | `btc-noncopy-lanes-read` (Done) is a measurement lane, **no card asks for a 5m/15m strategy simulator** | ❌ reference |
| Endgame / reverse notebooks (5m up/down strategies) | — | none | ❌ not evidence — no PnL, no measurement, donor's own claim |
| pmdata.dev tick data (API key) | — | — | ❌ not adopted; coverage/licence still **unverified** from this host (carried from the 2026-10-24 awesome-polymarket audit) |

**The decisive check is the middle row.** The question a queue model exists to answer — *does a resting
order at `intent − $0.02` actually fill?* — was already measured here on 339–354 legs against a
pre-registered bar: **5 % within 5 min / 19 % within 1 h** reachable, versus the archive prior of
74.3 % / 81.1 % (`c200-intent-printthrough-check`, read 2026-10-10). Two independent instruments agreed
within 1 pp. A queue simulator would refine *how* a fill happens on a level we have already shown is
mostly never reached; it would not change that number, and it is not what D2 is blocked on.

## 5. What it would cost

- **Reimplement the one formula (recommended if D2 starts):** ~1–2 h in TS/Python beside
  `scripts/c200-printthrough.py`. Zero dependency, zero risk, nothing new to trust.
- **Use the crate as a dependency:** a Rust dep (`maturin` build) plus a converter from
  `data/l2/<asset>.jsonl` (5 s, full ladder) + `data/l2-events/` into their NPZ event stream — ~half a
  day, and our lines are already shaped like the loader's `bid_prices`/`bid_sizes` arrays, so the
  conversion itself is not the hard part.
- **The hard part is the input:** `ProbQueueModel.trade()` advances queue position from **trade flow at
  the level**. Our market channel carries no trade stream at all (`scripts/record-l2.ts` header: only
  `book` and `price_change`; an earlier version waited for a `trade` message that never arrives), and the
  public print tape is thin on our markets (2–50 rows/market). So a converted backtest would run almost
  entirely on the *cancel* path and output a conservative FIFO-ish bound — not a measured fill
  probability, which is what D2 wants.

## 6. Honest caveats

1. **Attribution defect — read this before borrowing anything.** The repo's LICENSE says only
   `Copyright (c) 2026 mileswangs`, while the crate, the engine and most of the Python package are
   upstream nkaz001's MIT code (upstream LICENSE: `Copyright (c) 2022 nkaz001@protonmail.com`). Neither
   the workspace `Cargo.toml` nor `pyproject.toml` names the upstream author, and the package is
   republished to PyPI as `pm-hftbacktest`. MIT requires the notice be preserved in copies, so if we ever
   borrow from this tree, **attribute `nkaz001/hftbacktest` directly** and treat that repo — not this one
   — as the provenance for engine code.
2. **The suite was not run here, and nothing gates it.** No clone/execute is permitted in this cron, and
   the repo has **no test workflow**: `codeql`, `release-python` (manual dispatch, 3/3 green, wheels
   only), `stale`. I am not calling this a verified-green suite — I read the tests, not their result, and
   their own ROADMAP still lists "build, formatting, coverage" CI as unchecked.
3. **Claim size vs code size.** 66 % of the tree's bytes are notebooks and PNGs; the Polymarket-specific
   delta is ~40 LOC of fee model + one loader module + two notebooks. The headline "Polymarket HFT
   backtesting, written in Rust" describes upstream's engine wearing a Polymarket loader.
4. **Vendor claim left unverified.** "Free Polymarket tick data from pmdata.dev" — the README itself
   requires an API key; coverage, licence and cost were unverified in this pass and in the previous one.
   Do not repeat "free tick data" as fact.
5. **No key path, no execution path.** No Polymarket connector, no wallet, no signing code — so the
   safety surface of this candidate is genuinely small. That is a reason it is *safe* to keep as a
   reference, not a reason to adopt it.

## 7. Recommendation

**No build. WATCH — reference only.**

The one idea worth keeping is the **power-probability queue recurrence** (3b) as a candidate mechanism
inside `phase-d2-fill-model` *if and when* that card starts, alongside the FlashAlpha (MIT) and homerun
(AGPL) references it already names — with its exponent treated as a parameter to calibrate against our own
L2 corpus, never as their hardcoded 3.0. The fee model is corroboration of a law we already implement.

Nothing here should be adopted now: our maker-fill question is measured and answered adverse, our fee law
already matches the current venue schedule, and the engine's decisive input (trade-at-level flow) is the
one thing we do not capture.

### Card block — prepared, NOT applied (this job writes only `drafts/`)

Append to `phase-d2-fill-model`'s `note` in `data/roadmap.json` when a session with write scope is next
there:

```
AUDIT INPUT (2026-10-24, watch; drafts/asset-audit-pm-hftbacktest-20261024.md): mileswangs/pm-hftbacktest
(MIT, ★126, alive) = upstream nkaz001/hftbacktest + a Polymarket binary fee model + a pmdata.dev loader.
Third reference for this card, ranked below FlashAlpha: keep the power-probability queue recurrence
(prob = f(back)/(f(back)+f(front)), f(x)=x^n; est_front = front - (1-prob)*chg + min(back - prob*chg, 0),
trade-implied qty subtracted from chg) as a candidate mechanism, but their exponent is a hardcoded,
uncalibrated 3.0 — calibrate n against data/l2/ or do not use it. Input gap that matters: ProbQueueModel
advances on trade-at-level flow, and our market channel has no trade stream (record-l2.ts) with a thin
data-api print tape (2-50 rows/market), so a converted run would be a cancel-path FIFO bound, not a
measured P(fill). If borrowed, attribute nkaz001 upstream — this repo's LICENSE drops that notice.
```
