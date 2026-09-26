# Can the historical archive help build the ML model? — measured bridge between the two

**Date:** 2026-09-26 · **Status:** measurement + recommendation only. Nothing implemented, no rule, size,
gate or booked figure moves, no live path touched. Trigger: *"Can we use this backtesting data to help
build our ML model after the Kelly window"*.

Scope of "this backtesting data": `/Volumes/Storage/pm-data` — **Polymarket-v1** (1,201,580,990 OrderFilled
rows + 838.7M CTF + 601.9M daily_aligned, all with resolution labels) and **quant-bench** (12.7M hourly +
1.46M daily bars, 36,831 resolved markets), acquired and independently verified 2026-09-25
(`drafts/historical-archive-inventory-20260925.md`). Companion artifacts: `drafts/fee-maker-calibration-20260925.md`
(fee law + maker hazard), `drafts/backtest-engine-design-20260925.md` (the engine/ML spec).

> **CORRECTION (2026-09-26, same day):** the first pass of §1–§3 ran against a **partial wallet list**
> (1,162 of 3,273 wallets — a shell capture the tool output had truncated), which overstated wallet-skill
> persistence roughly 2×. Every number below is from the **complete list**, rebuilt from the live DB by
> `scripts/archive_lists.py` and re-run end-to-end (4 probes, 11:09→11:12 CDT). The correction makes the
> veto conclusion *stronger*, not weaker — see §6.

## Key insight

The archive's value to the model is **not** more training rows — it is (a) the execution/fill term that the
model's *target* depends on and we currently assume, and (b) the ability to **price a feature before we
spend our own 3,966 labels on it**. Both are cheap and both are already partly measured. What it cannot do
is train the admission policy, because it contains none of our decision context.

Measured today, this is not speculation: **52.3% of the wallets we track and 39.3% of the wallets we
actually copied have 3.4 years of pre-era history in the archive**, with resolution labels usable at fill
level (51.8M labelled buys). The first thing that history says is that **wallet skill barely persists at
all (r ≈ 0.14–0.26 by variant), and what does persist is one-sided: the worst wallets stay worst, the best
wallets do not stay best.**

## 1. The overlap is real (wallets, not markets)

One pass over the 42 `OrderFilled` parquet files (52 GB), semi-joining our **complete** wallet list
(3,273 wallets) against `maker`/`taker` (~46 s):

| quantity | value |
|---|---|
| our distinct wallets (tracked ∪ observed ∪ copied) | **3,273** |
| … found in the archive (2022-12-12 → 2026-04-28) | **1,712 (52.3%)** |
| wallets we actually copied (206) found in the archive | **81 (39.3%)** |
| archive fills touching our wallets | **112,174,053** |
| … of which join to a resolution label (`daily_aligned`) | 110,609,396 |
| our CLOB token ids (9,756) seen in the archive | **593 (6.1%)** — market overlap is thin |
| fills per wallet | median **5,578** · mean 170,239 · max 8,754,974 |
| wallets with ≥1,000 archive fills | **1,270 of 1,712** |

Fill-count distribution: 664 wallets ≥10k fills · 606 1k–10k · 324 100–1k · 98 10–100 · 20 <10.
Top of the book is protocol-scale (0xb27bc9… 8.75M fills / $65.1M; 0x204f72… 5.74M fills / $631M notional).

The useful overlap is **wallet behaviour**, not markets: our tokens are recent, but the actors are not.

## 2. The archive can label our wallets' history (fill level)

`daily_aligned` carries `asset_id → outcome_label, winning_outcome_label, resolution_status, category_refined,
taker_base_fee, maker_base_fee, p_event` (win label populated on 99.0% of rows in the three sampled files,
8 categories, Sports/Politics/Crypto/Finance leading). Joining it to our wallets' fills:

- **868,106 labelled assets** reachable from our wallets' fills;
- **51,782,356 labelled buys** by our wallets (all sides), **3,245,417** on the aggressive (taker) side —
  the side a copy lane actually sees. The `/activity` feed our scanner reads is side-only (no maker/taker
  flag), so the taker cut is a proxy for "the side we copy", stated as such.

## 3. What that already answers: does wallet skill persist?

Per wallet: split its own fill span in half, `skill = mean(win) − mean(price)` per half (band-neutral
variant: `win − that price band's own realised win rate`), keep wallets with ≥200 labelled fills in BOTH
halves, then correlate the halves. All variants restricted to our own wallets, complete list:

| population | wallets | Pearson r | Spearman ρ | worst decile A → B | best decile A → B |
|---|---|---|---|---|---|
| all buys, `win − price` | **920** | **0.144** | 0.123 | −16.3% → −5.1% | +14.1% → **−1.3%** |
| … excluding MM/protocol wallets | 803 | 0.140 | 0.109 | −17.3% → −5.8% | +15.0% → **−1.6%** |
| taker buys, `win − price` | **438** | **0.206** | 0.122 | −10.7% → −5.2% | +8.2% → **−2.7%** |
| taker buys, price 0.05–0.95 | 376 | 0.257 | 0.108 | −12.2% → −7.6% | +9.7% → **−2.7%** |
| taker buys, **band-neutral** | **376** | **0.240** | 0.097 | −12.1% → −7.2% | +9.9% → **−2.9%** |

Quartiles (A → B, %):
- all buys: Q1 −9.5 → **−3.4** · Q2 −1.1 → −1.0 · Q3 +1.8 → −0.5 · Q4 +8.9 → **−0.7**
- taker buys: Q1 −6.3 → **−3.9** · Q2 −0.5 → −1.7 · Q3 +1.9 → −0.2 · Q4 +5.9 → **−1.5**
- taker band-neutral: Q1 −7.1 → **−4.3** · Q2 −0.4 → −1.7 · Q3 +2.3 → +0.2 · Q4 +6.9 → **−2.2**

- **Skill persists weakly-to-barely (r 0.14–0.26) and asymmetrically in the same direction in every
  variant: the worst wallets stay worst, and the best wallets do not stay best** — the top decile collapses
  to ≈0 or flips negative in all five cuts, and quartile 4's half-B mean is negative in all three.
- **The average tracked wallet is fair-priced**: all buys 49.15% win vs 48.90% mean price = **+0.24%**; on
  the aggressive side 51.82% win vs 51.81% mean price = **+0.02%**. Per-band realised win rates track price
  within ±1.6 pt (the two extremes are the only bands with a real gap: 0.8–0.9 −1.5 pt, 0.9–1.0 −1.6 pt).
- This is the same shape our own data showed (wallet scores AUC 0.43–0.50; the ML-1a skip set fair-priced),
  now measured on a sample three orders of magnitude larger — and, after the correction, weaker than the
  first pass suggested. The honest summary is **"the archive finds no wallet-side edge to select on"**.

**Implication for ML-1/ML-2: a wallet-skill feature is a veto, not a selector.** Build it as
"exclude bottom-tercile wallets", do not ship it as "pick top-tercile wallets", and do not spend our label
budget re-deriving that — the archive already answered it, and the corrected numbers answer it harder.

## 4. Where the archive genuinely plugs into the model

| # | use | what it gives the model | effort | when |
|---|---|---|---|---|
| **U1** | **Execution/fill model** (conditional) | the target is net-of-fee PnL (card `ml1-target-net-pnl-and-price-baseline`), and net PnL depends on whether the maker entry filled. Archive gives the hazard skeleton (δ=0.02: 71.1% @5m / 77.6% @1h; 74.3% weighted to C-200's own prices), the fee law (taker-only, `0.10·shares·min(p,1−p)` in its era), and the **adverse selection** it must price (−3.23 pts @1h on 200.3M fills at C-200's band). Missing piece: a **conditional** `p(fill \| spread, size, ttr, category, band, hour)` fitted on ground-truth direction, plus the matching markout — the per-leg expected entry the ML target needs | 2–3 days | now (offline) |
| **U2** | **Feature pricing / priors** | the measurement in §3: set the prior, the sign and the ceiling for every wallet-side feature before fitting; kill candidates the archive already rejects (category concentration was NULL in our own data too) | ~1 day | now (offline) |
| **U3** | **Sharpen the price-only baseline** | the promotion bar is "beat price-only" (AUC 0.747 / Brier 0.199 vs base rate 0.236). Fit the price→outcome surface per category × horizon on 1.2B fills + 36.8k resolved markets so we cannot ship a model that only re-learns price | 2–3 days | after P1/P2 (needs the engine's conventions) |
| **U4** | **Era/drift machinery** | 3.4 years, two fee eras, 8 categories, venue v1→v2 = the natural experiment for the doctrine card's time-ordered, `ruleSetVersion`-era-aware, purged/embargoed splits and deflated-Sharpe/PBO diagnostics | 1–2 days | after P2 |

**Ranking rationale:** U1 is the only item that changes what the model can *learn* (its label depends on it)
and it addresses the largest open assumption in the book (the 2¢ = **75.7%** of C-200 settled PnL). U2 is
one day and stops us from spending labels on a settled question. U3/U4 are eval-quality work and only make
sense once the engine exists.

## 5. What the archive cannot do (hard boundaries)

1. **No decision context.** It has no `copyScore`, no gate outcomes, no hour policy, no lane state — so it
   cannot train the admission policy. Our own label set (3,966 rows, 2026-07-14 → 2026-09-25, 42 rulesets,
   base rate 0.545 `was_good`) remains the only substrate for that, and it is the scarce resource.
2. **It ends 2026-04-28, before our era** (first paper trade 2026-06-18) and covers **CTF Exchange v1,
   which terminated**. Structure transfers; levels do not (booking the archive-era fee rate would put C-200
   at −$206 instead of +$2,180).
3. **No order-book depth** (no quotes, no cancellations; the archive says so itself) — depth exists only in
   our own `data/l2/` since 2026-08-31, so the fill model is tape-proxy + our L2.
4. **quant-bench is daily+hourly, high-liquidity, resolved-only** — no 1–5 min bars; it cannot be the
   short-horizon layer.
5. **No Kalshi wallet identity, ever** → no copy-trade ML on that venue (market-level only).
6. **Licence**: CC-BY-4.0 on the Hub card vs CC BY-SA 4.0 in the paper text — reconcile before any derived
   artifact is redistributed; attribution travels.
7. **Single unencrypted external NVMe, no redundancy** — `scripts/verify-archive-pmdata.py` (exit 0 =
   intact) is the gate before and after any move.

## 6. Reality checks on the numbers in this brief

- **The §1–§3 numbers were wrong once and are fixed here.** The first pass used a 1,162-wallet list (a shell
  capture truncated by tool output) instead of all 3,273; on the complete list the persistence coefficients
  fall from r 0.40/0.24/0.23 to **0.14/0.21/0.24** and the sample grows from 316/170/152 to 920/438/376
  wallets. Direction is unchanged, magnitude is roughly halved, and the selector conclusion is unaffected
  (the winner side still fails to persist). The list build is now a script (`scripts/archive_lists.py`),
  not a hand-piped query — that is the actual fix, because the failure mode was invisible prose.
- **Our wallets are a selected pool** (our scanner already picked them), so §3 is *not* "skill persists
  venue-wide" — it is "skill persists this weakly among wallets we already consider copyable". That is the
  right population for the decision and the wrong population for a venue-general claim.
- **`win − price` is a markout-to-resolution proxy**, not PnL: no fees, no exits, no size, no queue. The
  band-neutral variant exists because a wallet's price style could otherwise manufacture persistence; the
  conclusion survived it (r 0.206 → 0.240, top decile flips in both).
  A first attempt at that control was **algebraically void** (subtracting the same per-band constant from
  both `win` and `price` cancels in the difference) — recorded here because it is the kind of check that
  looks like confirmation and is not.
- **Halves are split at each wallet's own midpoint**, so the two halves are different calendar eras
  (fee-era change, venue change). That makes this a *conservative* persistence read, but it also means part
  of the "top decile flips" could be era, not mean reversion. A calendar-fixed split is the follow-up.
- **MM/protocol wallets** are in the population (2 wallets with >100k taker-buys = 537,352 taker buys; 54
  wallets in the 10k–100k bucket). Results are reported with and without them for the all-buys variant
  (r 0.144 vs 0.140); they are not copy targets and the full study should filter them by a
  notional/fill-rate rule, not by eye.
- Every number in §1–§3 is reproducible in ~40–60 s per script (commands in §9); the whole set re-runs
  end-to-end in ~3 min.

## 7. Sequencing against the Kelly window (frozen through 2026-10-08)

- **Allowed now:** U1 and U2 — offline, read-only, no live path, no published number. Consistent with the
  freeze doctrine and with `bt-data-capture`'s "observability is allowed inside the freeze".
- **Post-Oct-8:** U3/U4 (they need the engine), then the carded path: simulator labels → net-of-fee target →
  era-aware walk-forward → shadow feed → OOS clock (≥30 settled, positive net EV, CI clearing zero) →
  advisory → shadow-sized lane. Each step is user-approved; none during the window.
- **Explicitly not decided here:** whether the 2¢ maker assumption stays. U1 tells us what it is worth; the
  decision is `c200-maker-fill-assumption` and is a PnL-affecting change (approval + post-window).

## 8. Recommendation (option set, recommendation first)

1. **RECOMMENDED — run U1 + U2 now, card U3/U4 behind the engine.**
   U1 pre-registered gate: on ≥50 measured C-200 legs, the conditional model must beat the flat band-hazard
   baseline (74.3% @5m) on Brier/log-loss, reproduce the measured adverse-selection sign, and its expected
   markout must be produced *side by side* with the naive `intent − 0.02`. It replaces the 2¢ in the
   **simulator only**; the live booking changes only by separate approval.
   U2 pre-registered gate: wallet skill enters ML-1 as a **veto** (exclude bottom tercile). Promotion to a
   *selector* requires ≥200 of our own forward legs where top-tercile selection beats price-only with a
   market-clustered 95% CI excluding zero — otherwise the archive's answer stands.
2. **Alternative (a) — U1 only** (smallest useful step; answers the biggest open assumption, ~3 days).
3. **Alternative (b) — all four now** (rejected: U3/U4 without the engine's conventions produces a second,
   divergent evaluation stack — exactly what `bt-ml-lane` exists to prevent).
4. **Alternative (c) — wait for Oct 8 and do it inside the engine phase** (rejected: these studies are cheap,
   offline and shape what P1/P2 must build; waiting buys nothing).

**Say `run U1`, `run U1+U2`, or name a different subset.** Nothing runs until then.

## 9. Reproduction

```bash
cd ~/polymarket-copybot
DUCKDB=/Volumes/Storage/pm-data/.venv/bin/python     # duckdb 1.5.5, no numpy needed

# 1. rebuild the wallet/token lists from the live DB (must print 3273 / 206 / 9756)
$DUCKDB scripts/archive_lists.py

# 2. the four probes (~40-60 s each; overlap 46 s, persistence 59 s, taker 27 s, band-neutral 37 s)
$DUCKDB scripts/archive-wallet-overlap.py                    # -> /tmp/arch_overlap.json
$DUCKDB scripts/archive-wallet-persistence.py                # all buys            -> /tmp/arch_persistence.json
$DUCKDB scripts/archive-wallet-persistence-taker.py          # taker buys          -> /tmp/arch_persistence2.json
$DUCKDB scripts/archive-wallet-persistence-bandneutral.py    # band-neutral skill  -> /tmp/arch_persistence_resid.json

# 3. archive integrity gate (must exit 0 before trusting any figure above)
$DUCKDB scripts/verify-archive-pmdata.py
```

The probes self-build their inputs if `/tmp/our_wallets.txt`, `/tmp/copied_wallets.txt` or
`/tmp/our_assets.txt` are missing, so step 1 is only needed to force a refresh. Wallet list =
`WalletProfile.address ∪ ObservedTrade.walletAddress ∪ PaperTrade.walletAddress` (`isDemo=0` for the
"copied" subset); token list = `data/l2-asset-map.jsonl`.
