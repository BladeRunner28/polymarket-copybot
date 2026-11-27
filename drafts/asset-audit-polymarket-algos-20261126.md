# Asset audit — `govinterset-dotcom/polymarket-algos`

**Audited:** 2026-11-26 · **Verdict: ⚪ WATCH (read-for-ideas only; one read-only replay proposed)**
**Dashboard:** http://localhost:3013/drafts/asset-audit-polymarket-algos-20261126

> No code from this repo may enter the live lane — the licence taxes production order flow with a
> third-party builder attribution. Research use *is* permitted, which is what makes the replay legal.
> Nothing here is adopted. The single actionable item is a measurement on our own tape.

---

## 1. What it is

A 13-day-old (created 2026-11-13) consolidation of ~35 short-horizon Polymarket bots for **BTC/ETH
up-down 5m and 15m** markets, plus a historical dataset of per-second order-book paths and Binance
second bars. ★2 · 0 forks · 154 files · 1.59 MB of Python across 57 files · 62 MB of committed zips.

The tree is a **dump, not a project**: 30+ single-bot folders at root (`arb_bot`, `autotaker`,
`boxarb`, `merge_split`, `pair_spread_arb`, `reward_farmer`, `martbot`, `pmgrid`, …), a
`best-live-algos/` shortlist (mojo, path_z, sniper), an `algorithms/` folder of ten 26–55 KB
generated .py files, and `datasets/`. The README says as much: *"older one-folder-per-bot layout
still present at repo root."*

Provenance is the load-bearing question, and the repo answers it inadvertently: `reconstruct_algos.py`
(724 B) reconstructs `all_algos_src.zip` **from `archive/part_XX.b64` base64 parts and extracts it
over the repo root**. The algos were assembled by an agent pushing base64 through the contents API,
then unpacked. `algorithms/'ineff yjdsq.env'` is a keyboard-mash filename. Despite this,
`LICENSE` asserts *"Copyright (c) 2026 govinterset-dotcom. All rights reserved"* over the whole
tree — a chain-of-title claim over code whose authorship is not documented anywhere in the repo.
That matters twice: it makes the licence unenforceable-by-them on parts we might want, and it means
we cannot assume any file we copy is theirs to license.

## 2. Licence — checked first, and it is neither MIT nor a blocker for research

`NOASSERTION` on the API is **not** the verdict; the `LICENSE` is a hand-written
**"Polymarket Builder Attribution Source-Available License v1.0"**. Read in full, it splits cleanly:

| Clause | Effect on us |
|---|---|
| §2(a)–(c) | view/download/study, **run for personal, educational and research purposes**, modify, create derivatives — **permitted** |
| §3 | **Production Use** (any system that *submits orders to a live venue*) through Polymarket must preserve the original **Builder address + Builder Code in every order** and may not remove/bypass it |
| §4 | redistributing a derivative (source form) must carry the same terms — **distribution-triggered** share-alike, no network clause |
| §5 | disclaims any entitlement to builder rewards/fees — but confirms builder fees "may be charged to users" |
| §6 | third-party components keep their own licences — which, given the provenance above, is most of the tree |

**Reading:** this is *not* GPL/AGPL (nothing is triggered by linking or by serving over a network),
and it is *not* no-licence. It is **source-available: free to study and to research with, tolled on
production order flow.** For a paper-only stack that is nearly sufficient — but our go-live anchor is
2027-01-02, and every order we send then would have to carry a third party's builder code, which is
both an economic term we did not choose and a PR/attribution obligation on our own lane. Two
committed `.env` files (`algorithms/doppler.env`, `algorithms/ineff yjdsq.env`) exist alongside 32
`.env.example`s — unusual hygiene for a repo that also runs a CI check enforcing builder attribution.

**Verdict on code: read-only. Reimplement anything small; vendor nothing.**

## 3. Verified machinery

### 3.1 Their fee model matches ours exactly

`datasets/README.md` prescribes taker `FEE_RATE * p * (1-p)` with `FEE_RATE=0.07`. That is
character-for-character the law in our `src/lib/fee.ts` / `scoring/price-edge.ts`
(`takerFeePerShare = rate * p * (1-p)`, crypto rate 0.07). **No capability gap** — their fee-aware
backtests are the same arithmetic we already run, and they additionally deduct a 1% builder fee that
our paper ledger does not model (because we pay none).

### 3.2 `path_z`'s residual-z — re-derived from source, and it has a real defect

The README states `z = log(spot_now / window_open) / (σ_1s * sqrt(remaining_s))`. Source confirms the
formula literally (`path_z.py:266-275`), and confirms two things the docstring hides:

- **`sigma` is a sample stdev (n−1) over *per-tick* log returns** (`path_z.py:200,282`), not a
  per-second σ. Its value therefore depends on WebSocket message rate, so `z` is not comparable
  across quiet/busy regimes or across assets. Verified numerically: their expression reproduces
  `statistics.stdev` exactly (0.005100 on a 6-tick sample) — the convention is per-tick, and the
  `σ_1s` label is wrong.
- **`|z|` inflates as `sqrt(300/remaining)`**: at fixed 1% displacement, z = 0.113 at 300 s left,
  0.252 at 60 s, 0.617 at 10 s (5.48×), 1.951 at 1 s (17.3×). `Z_THR=0.55` is therefore a different
  threshold at every point in the window, and near expiry almost any drift clears it.

They name this themselves — the paper section attributes the losing arms to *"regime + inflated |z|"*.
That self-doubt is a claim I could verify, and did: **the arithmetic is right and the design is
wrong.** The *idea* (displacement measured in units of remaining-window σ) is a decent near-resolution
certainty statistic; the implementation needs a horizon-normalised σ and a remaining-time-scaled
threshold before it means anything.

### 3.3 `mojo` economics — the arm that matters, priced from its own definition

Rule: BTC 5m, take the **leader at ≥25% of the window, ask ≥ 0.95**. Their claim: n≈208, WR≈99%,
"all weeks green, ~6 trades/day", *"small edge after fees — high-WR crumbs, not high ROI."*

At ask 0.95 the fee is `0.07 × 0.95 × 0.05 = 0.003325/share`, so **break-even WR = 95.33%**, not
"nearly certain". Their n=208 at 99% gives an approximate 95% CI lower bound of **97.65%** — the arm
survives on the point estimate, but the margin is ~2.3pp, i.e. **one extra loss in every ~43 trades
erases it.** At ask 0.97 the break-even rises to 97.20% and, once their own mandated 1% builder fee is
added, to **98.17% — above the CI lower bound, so the edge dies.** The builder fee exceeds the taker
fee by 4.7× at that price. This is a narrow, fragile band, and the honest summary is theirs, not mine:
high-WR crumbs.

## 4. Dataset claim vs artifact — the ladder, walked

| Claim | Artifact | Verdict |
|---|---|---|
| "~12,600 unique windows (BTC 5m ≈7,000, BTC 15m ≈3,200)" | `paths/path.zip`, 7.8 MB, is the only candidate. `paths/SOURCE.md` tells the reader to publish it as a **GitHub Release `datasets-path-2026-11`** — **there are zero releases on the repo.** The sample file `comeback_path_sample.jsonl` is 189 bytes of placeholder text saying the full dumps "are too large for the agent→GitHub API channel." | ⚠️ **claim not backed by a downloadable artifact** |
| July-2026 archive: "2,567 markets (5m 1,618; 15m 949)" | Four zips present and real. Their own README discloses that `eth_15m.zip` contains a byte-identical nested copy of `eth_5m__.zip` and must not be double-counted; 809 BTC 5m windows and 809 ETH 5m windows are the *same* windows | ✅ exists; **BTC-only countable total = 809 (5m) + 679 (15m) = 1,488 windows** |
| `btc_5m__.zip`: 809 markets, 391 Up / 418 Down, Jul 6 00:00–Jul 8 22:55, era v2, 95% of possible windows | Downloaded (14.5 MB) and parsed the metadata: **809 records, 391 Up / 418 Down, era `{v2: 809}`, 2026-07-06 00:00 → 2026-07-08 22:50, 95.1% of the 851 possible 5m windows, one 3.6-hour gap** | ✅ **matches their table exactly** (they say 22:55, actual last window 22:50 — 5 min) |
| Top-of-book 1.42m rows / trades 1.99m rows | Files present at plausible sizes (3.65 MB / 10.7 MB); `n_src_rows` sums to **208,741,742 raw source rows** for 809 markets (~258k messages → ~1.5k collapsed top rows per market) | ⚪ **parquet contents unverified** — `pyarrow` is not installed on this host and installing it is out of scope for this job. Row counts and timestamp bounds are unchecked |

Two consequences, both decisive for fit:

1. **The archive is one resolution-era stale.** All 2,567 windows are July 2026 and the repo says so
   itself: they *"predate the August 7, 2026 switch to 60-second TWAP resolution."* The settlement
   mechanism is the thing that determines the outcome, so this is **calibration/pretraining
   substrate, never a substitute for our own capture** — and specifically it cannot test a rule whose
   edge depends on how the last minute resolves.
2. **It is not a look-ahead-clean evaluation input as shipped.** The metadata carries `winner` per
   window alongside the window start; a naive join by slug leaks the label into any feature build.
   That is the same trap our own label-integrity batch spent five cards on.

## 5. Fit table vs `data/roadmap.json` (328 cards)

| Component (named file) | Our baseline, verified by grep | Card that asks for it | Verdict |
|---|---|---|---|
| Fee-aware backtest (`datasets/README.md` §3) | `src/lib/fee.ts`, `scoring/price-edge.ts` — **same law, 0.07 crypto** | `fee-booking-net-ledger` (proposal stage) | ❌ already have it |
| Per-second order-book path archive (`datasets/paths/*.zip`) | Kalshi venue tape live at 93–94% duty, 215k prints/window (`kalshi-tape-capture-live`, In Progress); L2 archive 59,316 files / 28.57 GiB / 4,602 markets; `scripts/btc-convergence-sampler.py` (btx2, In Progress) | `btx2-deterministic-convergence-study` | ⚪ concept only — pre-TWAP era, 1,488 BTC windows, unverified parquet; our own capture is deeper in every dimension except *history depth we can't otherwise reach* |
| Binance second bars (`datasets/seconds/*.parquet`) | `btx1-binance-oracle-reconcile-harness` (Done): our keyless pull reproduces the venue's verdicts **1,617/1,617** | `btx1` done, `btx3` parked | ❌ no gap |
| `mojo` — late-window favourite, ask ≥0.95 at ≥25% of window (`best-live-algos/mojo/mojo.py`, 74.9 KB) | **We skip this class by rule**: btc-noncopy read measured all 1,469/1,469 btc-updown decisions as skips across 602 markets, gates incl. *"price near certainty"*; counterfactual −$0.0522/$1, clustered 95% CI [−0.0939, −0.0096] | **none** — `btc-noncopy-lanes-read` is Done; no open card asks for the near-certainty arm | ⚪ **concept only, and the one replay worth running** — see §6 |
| `path_z` residual-z (`best-live-algos/path_z/path_z.py:266`) | `btx2` convergence study + `btc-convergence-sampler.py` already measure displacement-vs-spot | `btx2` (In Progress) | ❌ not portable as written (per-tick σ, remaining-time blow-up); concept belongs inside btx2 |
| `sniper` time×price pockets (`sniper/sniper.py`, 75.9 KB) | — | none | ❌ their own paper: WR ~33%, net negative; not a whitelist-ready rule |
| Arb/merge folders (`boxarb/`, `merge_split/`, `pair_spread_arb/`, `autotaker/`) | Phase C is capital-gated; no merge/relayer primitive in our tree | Phase C (not started) | ❌ not portable — zero tests, collected provenance, and Phase C has not fired |
| Test suite / CI as a quality signal | — | — | ❌ **`tests=NO`; `ci=yes` is `compileall` + `scripts/check_builder_attribution.py` only — and it is RED: 3/3 most recent `Python and Builder checks` runs `failure`.** The CI enforces the *licence*, not correctness |

The honest framing of the one real gap: **nothing in our tree measures the near-certainty arm of
btc-updown**, because a generic gate throws it away. That is an absence we should be able to state
with a number instead of a gate.

## 6. Integration proposal — one read-only replay, on our data, not theirs

Attach to the existing BTC lane as a **third arm of `btx2`** (no new lane, no code from the repo):

> **REC — late-window-favourite arm, read-only replay**
> **Hypothesis:** in PM `btc-updown-5m`, taking the book leader at ≥25% of the window when the ask is
> ≥0.95 resolves up often enough to clear the 95.33% break-even implied by our own fee law.
> **Measurement:** replay our captured btc-updown quotes/tape; bucket by (fraction of window, ask
> band 0.95/0.96/0.97+); report realized WR with a market-clustered 95% CI and net EV per share after
> `rate*p*(1-p)`. Target n ≥ 300 windows before any read is quoted.
> **Decision rule:** if the clustered CI **lower bound** on realized WR exceeds the band's break-even
> (95.33% at 0.95, 97.20% at 0.97) by 2026-12-31, propose it as a size-capped C-200 arm (Lane A,
> separate approval); otherwise drop with the number recorded.
> **Cost:** ~2 h, read-only, zero risk to the live lane.
> **Reversibility:** measurement artifact only; delete `data/btc-late-favourite-replay-*.json`.

Reimplement the rule from the published definition. **Do not copy `mojo.py`** — licence §3 and §4
attach to derivatives, and the file's own provenance is unestablished.

## 7. NOT portable

- **All algorithm source.** §3/§4 of the licence + undocumented chain of title over collected bot
  code. Read, cite the idea, write our own.
- **The agent-assembly pipeline** (`reconstruct_algos.py`, base64 parts → zip → extract over root).
  It is how 1.5 MB of code appeared in 13 days; it is not a build system.
- **`path_z.py`, `sniper.py`** — the σ/blow-up defect above and their own negative paper results.
- **The dataset as an evaluation input** — pre-TWAP era, label in metadata, parquet unverified, bulk
  archive never published.
- **The CI** as a trust signal: it compiles syntax and verifies builder attribution; it does not test
  behaviour, and it currently fails.

## 8. Honest caveats

- ★2, created 2026-11-13, pushed today. The activity is real code, but the **most recent commits are
  LaunchPoly badge/listing commits** (`README: add LaunchPoly badge`, `Add static LaunchPoly badge
  page for crawler verific`) pointing at `launchpoly.com/tools/polymarket-algos?ref=badge` — a
  directory listing with a referral parameter. Treat the star count and README polish as marketing.
- **CI is red on main** (3/3 recent `Python and Builder checks` = `failure`). I did not clone, install
  or execute anything (job constraint), so I cannot say *which* step fails — only that the repo's own
  gate does not pass today.
- **Self-reported numbers are unverified by me**: mojo's n≈208/99%, path_z's backtest table, and the
  21-hour paper run (−$35, max DD −$123, 91% one-sided on Down — that side bias alone is a red flag
  for a rule set that trades two-sided). I verified the *formulas and the metadata*, not their P&L.
- The repo documents its own losses (sniper net negative, path_z −$35 / max DD −$123, "5m_L_vs_35/40
  paper n=4 — too few"). That candour is the single most valuable thing in the repo, and it is worth
  more than the code.
- Parquet contents unverified (no `pyarrow` on this host; installing it was out of scope).

## 9. Card block — NOT applied (job constraint: recommendations only, no repo writes)

Append to `btx2-deterministic-convergence-study`'s `note` (or open a child card if preferred):

```
AUDIT INPUT (2026-11-26, watch; drafts/asset-audit-polymarket-algos-20261126.md):
govinterset-dotcom/polymarket-algos — source-available (research OK, production carries a builder-
attribution tax), code read-only, dataset pre-TWAP and 1,488 BTC windows max. ONE transferable item:
the late-window-favourite arm (leader at >=25% of window, ask >=0.95). Our own gate skips this class
by rule (btc-noncopy-lanes-read: 1,469/1,469 skips, counterfactual -$0.0522/$1, CI excludes 0) and
nothing in the tree measures its near-certainty subset. Proposed third arm: read-only replay against
our captured btc-updown quotes, buckets by window-fraction x ask band, gate = market-clustered CI
lower bound on WR > break-even (95.33% @0.95, 97.20% @0.97, from rate*p*(1-p) @ 0.07) by 2026-12-31.
~2h, read-only. Also verified: their per-tick sigma + remaining-time blow-up kills path_z as designed.
```
