# warproxxx/poly-maker — adoption audit (2026-09-09)

**Clone:** /tmp/audit_triage/clones/warproxxx_poly-maker (HEAD 2026-07-09) · **License:** MIT (verified in-file, "Copyright (c) 2026 warproxxx"; GitHub spdx `mit`) — borrowable with attribution.
**Verdict: ⚪ QUEUE (post-Oct-8). Do not adopt the bot. ✅ Borrow two concrete primitives — the CTF pair-merge path (Phase C / zero-impact exits) and the live-execution safety patterns (go-live hardening). ⚪ Concept card for a maker/reward-farming lane, and one measurement to run now.**

## What it is

Maker-only market-making bot for **Polymarket CLOB V2**, political markets, single async process, local-file config (`config/*.toml`), SQLite state. v2.0.0 · Python ≥3.12 · uv · MIT · **1,492★ / 489 forks** · created 2025-03-31 · last push **2026-07-09 (~2 months stale)** · small (307 KB) · deps pinned exact: `py-clob-client-v2==1.0.2`, web3, httpx, websockets, pydantic, structlog, typer, **py-builder-relayer-client** (gasless tx), socksio/python-socks (proxy), uvloop.

Worth reading for genre context: the repo says outright it is "a reference implementation and a research harness, not a guaranteed-profitable product" and TIPS.md documents a real supervised session that **lost $15.51** (Newsom −$5.27, Romania −$10.24). That honesty is why this audit is favorable even though the bot itself is a don't-adopt.

**Quality (ran locally):** **111 passed, 2 skipped in 0.38s** (`pytest tests/`; the 2 skips are live-gated behind `POLYMAKER_LIVE=1`). `py.typed`, ruff (`E,F,I,UP,B,SIM,ASYNC`) + mypy in dev deps, two dedicated hardening suites (`test_hardening.py`, `test_hardening2.py`) that encode real failure modes. The strategy core (`strategy/quoting.py`, `strategy/regime.py`) is deliberately **I/O-free and deterministic** — the author built it for backtest replay, which is also the thing our Phase D2 needs.

## Verified machinery (read in source, cross-checked against Polymarket's own docs)

Quoting core (`strategy/quoting.py`) — textbook inventory skew, correctly implemented:
- `reservation r = FV − skew`, `skew = γ·σ_short·u`, `u = clamp(net_shares/q_max, −1, 1)`, `net_shares = pos_YES − pos_NO` (holding NO = short YES) — the Avellaneda–Stoikov linear form, with `γ` sized so a full cap leans 1–2 ticks.
- `half_spread δ = base + c_vol·σ_short + c_tox·toxicity`, `base = delta_min_ticks·tick`, and in QUIET **δ is clamped into `[base, rewards_max_spread]`** so quotes keep scoring.
- **YES bid = r − δ; NO bid = (1−r) − δ — both are BIDS.** This is the repo's central insight and it is correct: official rewards §2–3 score `S(v,·)·BidSize` for market m plus `S(v,·)·AskSize` for the complement m′, so a BUY-NO *is* the ask side of the YES book. Both legs score; a filled pair **merges back to collateral at locked edge `1 − p − q`**.
- `FV = microprice + 0.5·flow_z·tick`, bounded; `_place_bid` never crosses (clamps to `best_ask − tick`), never pays through `FV − min_edge`, joins rather than jumps the touch; exits are SELL-makers walked from `fv+δ` toward the touch by urgency, with `size = floor(pos·100)/100` so an exit can never be rejected for overselling.

Estimators (`strategy/estimators.py`) — real microstructure, not technical-indicator cosplay:
- time-decayed EWMA (`weight *= 0.5^(dt/half_life)`) so bursty vs quiet tapes are wall-clock weighted; realized vol from squared FV changes at 10 s / 900 s horizons + ratio; signed-flow z-score (`signed/abs`).
- **MarkoutTracker**: for each fill, remembers FV-at-fill and measures FV 300 s later, signed so negative = picked off; `toxicity = max(0, −markout)` fed back into δ and size. This is the professional adverse-selection measure, and it's the piece the stack's paper fills lack entirely.

Risk (`risk/manager.py`) and regimes (`strategy/regime.py`):
- `equity = net_cash + Σ position·mark`; daily-loss kill switch; rolling **order-error-rate breaker** (≥20 attempts); per-market / event-group / total-exposure caps with a soft size taper from 70 % of cap.
- Documented design note worth stealing: `_market_notional` **deliberately excludes our own resting BUY notional** (counting it self-reinforces cancel/replace churn) — a real bug they hit and reasoned through.
- Regime priority HALTED > EVENT > REDUCE_ONLY > TRENDING > QUIET: halt on kill/stale/resolved/past `halt_before_hours`; pull all quotes on a sweep or a ≥N-tick FV jump with a cool-off; reduce-only at cap or inside `reduce_only_hours` of the end date.

Execution gateway (`execution/gateway.py`) — safety patterns, not just plumbing:
- `post_only = true` for every quote (GTC); FAK/FOK used **only** on the taker exit path; batch cap 15; `rate_budget_fraction = 0.25` of documented limits; drift reconciliation every 20 s; WS/order journaling for backtest.
- **Chained heartbeat dead-man switch** (`post_heartbeat` carrying the previous heartbeat_id; 3 consecutive misses → halt + resync → cancel-all within ~10 s if the engine dies).
- `ws_stale_halt_s = 10` and `user_ws_blind_halt_s = 15` — the second is the sharp one: if the *user* stream is down you can't see your own fills, so pull everything.

**Pair-merge (`merge.py`) — the single most transferable asset.** Real CTF `mergePositions` (ConditionalTokens `0x4D97…6045`, NegRiskAdapter `0xd91E…5296`, USDC `0x2791…4174`), three wallet paths: EOA direct, Gnosis Safe `execTransaction`, and V2 DepositWallet via the **gasless builder relayer**; nonce-serialized concurrent merges; on-chain balances as source of truth. **Live-verified** (LeBron neg-risk merge, tx `0x4d2a2064`, 2026-07-09). Caveat: TIPS says the merge path is **currently gated off for deposit wallets** — i.e. the path matching today's default wallet architecture is *not* the proven one.

**Economics claims — I checked them against Polymarket's docs, and the repo is right:**
- Official: `fee = C × feeRate × p × (1−p)`, category table **Politics 0.04 / maker 0 / maker rebate 25 %**, geopolitics & world-events fee-free. The repo implements exactly that (`taker_fee_bps = fee_rate·10000`, `rebate_rate` from `feeSchedule.rebateRate`, geo handled via `feesEnabled`).
- **Independent confirmation from the repo's own live data:** TIPS reports a ~$127-gross Newsom (Politics, p≈0.19) close that netted 122.86 (~$4.1 fee). `668 shares × 0.04 × 0.19 × 0.81 ≈ $4.11`. ✓ The formula, the 0.04 coefficient and the Politics category all reconcile.
- The author's self-flagged panic ("rate 0.04 — is it 4 % or 0.4 %? if 0.4 % every rebate estimate is 10× too high") is **a labeling bug, not a math bug**: 0.04 is a dimensionless coefficient, not a percentage. Their rebate arithmetic is correct; only the `_bps` name and the "≈2–3 % of notional" comment mislead.
- Liquidity Rewards verified too: `S(v,s) = ((v−s)/v)²·b`, `c = 3.0` single-sided divisor, 10,080 samples/epoch, **$1 minimum payout**, and — the detail that explains the repo's whole shape — **outside mid ∈ [0.10, 0.90] liquidity must be double-sided to score** (hence `extremity()` penalty and the mandatory two-sided BUY-YES + BUY-NO quote).

## Fit table vs roadmap

Context: the stack is copy-trading (C-200) + planned arb (Phase C), TS/Prisma core + Rust sidecar, **paper-only until the 2027-01-02 go-live anchor**. Verified absent from the stack today: any order placement, any CTF/merge/relayer code, and **any fee model at all** (the only `fee` hits in `src/` are the word "feed").

| Component | Fit | Card / timing |
|---|---|---|
| **CTF pair-merge primitive** (`mergePositions` + Safe/relayer paths) | ✅ borrow — the stack has none, and it's the *zero-market-impact exit*: lock `1−p−q` on a held YES+NO pair, no taker fee, no book impact | Phase C (design Sep 15–30 / build early Oct), and as an exit tool for thinning inventory |
| **Single-venue YES+NO ≠ 1 invariant** (their pair economics = a continuous arb) | ✅ concept — this is the *intra-venue* half of Phase C's invariant, and it **sidesteps the Phase Kalshi-1 keyless data wall** entirely (no Kalshi leg) | Phase C input; cheap to measure with books we already record in `data/l2/` |
| **Live-execution safety patterns** (heartbeat dead-man, ws-stale + user-ws-blind halts, error-rate breaker, kill switch, 20 s reconcile, rate budget) | ✅ borrow at go-live | go-live hardening (2027-01-02); nothing to ship before then |
| **Taker-fee model for paper PnL** — `fee = C·0.04·p(1−p)` on Politics, maker rebate 25 % | ✅ **measurement now** (does not touch a lane) | This-week-sized analysis; feeds the execution-leak thread |
| **MarkoutTracker + fill-probability framing** | ⚪ concept — adverse selection + "where is the price 30–60 s after the fill" is precisely the Phase D2 realistic-fill question | Phase D2 |
| **Maker / reward-farming lane** (new strategy class: earn rewards + 25 % rebates, not copy edge) | ⚪ concept, new card — economics are real and documented, but edge is thin and contested (their own session lost money; ~$10 of it was *oversizing a thin book*) | Backlog, post-Oct-8, paper-proving first |
| **The bot itself** (single-process Python, own wallet/config model, tuned Newsom/Romania profiles) | ❌ not portable — wrong runtime, market-specific params fit on live money | — |
| `py-clob-client-v2` dependency (owns V2 EIP-712 signing) | ❌ can't port — TS/Rust would need its own V2 signer; this SDK is the repo's key dependency, and it's the hard part | note as the main porting cost |

## Integration proposal

1. **Now (freeze-compliant, measurement only):** add the documented taker fee to the paper-fill accounting and re-run the attribution on realized C-200 PnL. Formula is citation-backed and independently confirmed above; Politics is our market mix. This tests a real fidelity gap for free and pairs with the C-200 execution-leak thread. *(No lane/rule/size change → measurement, not an override.)*
2. **Phase C design window (Sep 15–30):** take the merge module + the pair-arb insight as design input. Concretely: read `merge.py` and the docs' Market Making / Maker Rebates / Liquidity Rewards pages, then decide whether the first Phase C slice is (a) intra-venue pair arb/merge — cheaper, keyless, no Kalshi dependency — or (b) the cross-venue Kalshi leg as currently carded. Effort to port merge to our stack: **read = half-day; a working dry-run port ≈ 2–3 days** (the cost is wallet-type signing + relayer creds, not the logic). Risk: low-medium, it's an atomic batch primitive, not a lane; ship it as a manual CLI action first, flag-revertible by construction.
3. **Go-live (2027-01-02):** lift the safety patterns (heartbeat dead-man, ws-blind halt, error-rate breaker, reconcile cadence, rate budget) into the live-execution layer. Adopt as design, re-derive constants for our stack.
4. **Optional backlog card:** "Reward-farming / maker lane (concept from poly-maker audit)" — paper-proving only, post-Oct-8, with the repo's own negative result as the prior.

## NOT-portable list

- The bot as a system (Python single process; our stack is TS + Rust with a different orchestration and paper-first posture).
- `py-clob-client-v2` and its EIP-712 signing (the repo delegates the hard part; we'd own it).
- The two tuned profiles (Newsom/Romania values are archetype-specific and the author says they were fit by intuition on live money).
- Their scanner ranking as-is: it scores on Gamma's 24 h volume, which TIPS itself notes **overstates CLOB flow**, and the rebate term inherits the fee-rate labeling confusion.
- Their `moneydoctor`/`livetest` self-tests (they spend real money by design).

## Honest caveats

- **Negative live evidence, honestly reported.** Two markets, one supervised session, −$15.51. There is no statistical case that this strategy is profitable as tuned; the author says so first. Treat the maker lane as an unproven hypothesis with a documented prior *against* it.
- **Stale against a moving venue.** Repo last pushed 2026-07-09; Polymarket's fee/reward programs and CLOB V2 are actively changing (the fees doc is dated 2026-07-23). Verify every parameter live before building on it.
- **The proven merge path may not be ours.** Live verification was on a neg-risk merge, and TIPS says the **deposit-wallet path is gated off** — that's the architecture `config.toml` labels as current (`signature_type = 3`). Budget real effort to prove the merge on our wallet type.
- **Fee-rate labeling is confusing even though the math is right** — do not copy their `_bps` naming or the "2–3 % of notional" comment; use the official formula and the category table.
- **No taker-side sophistication we don't already have** — their taker path is a panic exit (FAK/FOK walk-the-book), explicitly the thing that cost them slippage on a thin book.

## Bottom line

MIT, 111/111 tests, deterministic core, and a live-verified on-chain merge primitive — plus the most honest TIPS file I've read in this audit series (it documents its own losses and names the fix). Nothing here justifies adopting a second trading bot, and the strategy evidence is negative. But two things are worth real money to us and are not currently in the stack: **the CTF merge path** (zero-impact exits, and the intra-venue half of Phase C that avoids the Kalshi data wall) and **the live-execution safety patterns** for go-live. Plus one free measurement: our paper PnL has no fee model, and the fee formula — `C × 0.04 × p × (1−p)` on Politics, 25 % maker rebate — is now verified against Polymarket's own docs and this repo's live fill data.
