# Asset audit — `mirabilis-agent/lip-ledger`

**Date:** 2026-11-03 · **Source:** radar-seed (newest fact-sheet radar block) · **Queue id:** `mirabilis-agent/lip-ledger`

## Verdict

**WATCH — adopt ~120 lines of verified formula, never the repo.** MIT, alive (pushed today), genuinely small (26 KB of Python over 12 files), and it contains two things we do not have: an exact model of Kalshi's Liquidity Incentive Program (LIP) reward, and a keyless client for Kalshi's public minute-level Weather Index — the settlement source of the *hourly* temperature family. Both map onto cards that already exist. Its own honest case study says the LIP is a **predictable reward and a losing strategy at small size**, so the value is a formula for a measurement lane, not an edge.

Why not `adopt-now`: the LIP pays for *resting* orders, and we hold no Kalshi key (card `kalshi-maker-read-prereg` already states this) — it can only ever be shadow/paper here, and the code is thin enough that vendoring would be more dependency surface than it saves. Why not `drop`: the two formulas are verified against venue primary sources (below) and neither exists in our tree.

## What it is

A read-only toolkit built by an autonomous agent on a real $20 Kalshi account, published with its losses. Three separable parts:

1. **`lip_ledger/model.py`** (~60 lines) — exact LIP side-scoring and payout model.
2. **`lip_ledger/windex.py`** (~60 lines) — client for `GET /live_data/weather/{city}` + `/calibrations`, lattice arithmetic, and a settlement-verdict helper for hourly temperature markets.
3. **A case study** (`docs/CASE_STUDY.md`, `docs/POSTMORTEM.md`, `docs/METHODS.md`) of nine days of live trading: rewards **+$20.30** against trading losses **−$36.06**, account $20 → $3.84 → ~$0.1 net after a second attempt. It documents its own failures in numbers, which is the highest-signal thing in the repo.

## Anatomy facts that drove the verdict

- MIT, no carve-outs (read the full `LICENSE`: plain MIT, no NonCommercial, no directory-scoped asset clause). Attribution required if we copy the formula text.
- ★7, 1 fork, 0 open issues, created 2026-10-11, pushed 2026-11-03 — alive, but three weeks old and one author.
- 35 files: `.py` 26 KB/12 files, `.md` 19 KB/6, `.csv` 268 KB/1 (`data/train_market_features.csv`), 9 committed `.pyc` cache files (hygiene smell, not a blocker).
- `tests/` present, `.github/workflows/tests.yml` present. **CI green on main (2026-10-15)**, and every one of the 100 commits since is a `Update live snapshot` data refresh — **0 code-touching commits since that run**, verified via `commits/main` (latest touches only `docs/live.json` + `docs/windex.json`). So the green run covers exactly the code that is still there. I did not execute their suite (audit rule: never run candidate code), so this is graded off the reported CI state, not a suite I ran.
- No key, no `.env`, no order-placement code, no telemetry in the README or tree.

## Verified machinery

### LIP reward model — `model.py`

Rule as implemented: per one-second snapshot each side is scored separately; reference price = first level walking down from the best bid where cumulative size ≥ `target/5`; qualifying levels stop at the first level where cumulative ≥ `target`; `score = size · d^(ticks below ref)` with `d = discount_factor_bps/10000`; a snapshot counts only if **both** sides reach the target; `payout = pool · 0.5 · share · counted_fraction`, per side, with a $1.00 minimum per program.

**Checked by hand from its own worked example** (`tests/test_model.py`): others `(0.28,120) (0.27,300) (0.26,450) (0.25,600)`, target 1000, mine `(0.28,5)` → cumulative crosses `target/5=200` at 0.27 → ref 0.27; weights 1, 1, 0.5, 0.25 → total `125+300+225+150 = 800.0`; `share = 5/800`. The test asserts exactly those numbers and they reproduce. The recursion is internally consistent.

**Units verified against the venue, not the README** — this is where this class of code usually breaks, and it is the strongest evidence tier available here:

| Claim | Verified against | Result |
|---|---|---|
| `period_reward` is `pool · 10000` (their `/10000.0`) | `docs.kalshi.com` OpenAPI field description: *"Total reward for the period in **centi-cents**"* | ✅ confirmed — a live program at `1000000` is a **$100** pool |
| `discount_factor_bps: 5000` means `d = 0.5` | live `GET /incentive_programs?type=liquidity` → `discount_factor_bps: 5000` | ✅ their `/10000` is right; the `_bps` suffix is a **misleading label** (5000 "bps" is 50%, not 500000%) — same trap as the archived fee-label case, and their arithmetic survived it |
| Endpoint + input fields exist | live API | ✅ `target_size_fp: "1000.00"`, `discount_factor_bps`, `period_reward`, `market_ticker` (note: `market` is null — `market_ticker` is the real key, which their code uses) |

**Not verified:** the *shape* of the rule itself (the `target/5` reference level, the 50/50 pool split per side). `docs.kalshi.com` has no LIP rule page (`llms-full.txt` returns nothing for "liquidity incentive"); the donor cites a CFTC filing we did not read. The only evidence for the shape is the donor's own reproduction on **n=4** real payouts (ratios 1.03 and 1.01). That is a good number on a small sample, not a proof — treat the rule as "matches four observed payouts" until our own replay confirms it. One further unstated assumption: `side_score` includes *my own* size when locating the reference price, which the rule text does not settle.

### Weather Index — `windex.py`

Claims re-derived against the venue's own endpoints:

- **Lattice `1.8/n_stations` °F** — verified from live `/calibrations`: NYC = **8 stations × 0.125** → 0.225 °F; Chicago = **5 stations × 0.2** → 0.36 °F. Equal weights confirmed, so the "equal-weight mean" docstring holds (per-station Celsius *offsets* exist and are re-estimated weekly, but they are constant per station and shift the level, not the step).
- **Payload fields** — live `/live_data/weather/nyc`: points carry `t`, `v`, `status`, `contributors`, exactly as their parser expects.
- **Correction to their (and the venue's) prose:** the doc says quorum-failed minutes *"are never returned as points"*, but live responses do carry points with `status: "incomplete"` and **no `v` key**. Their filter (`v is not None` AND `status in (normal, degraded)`) handles this correctly — the code is right where the documentation is loose. Good sign for the author.
- **Settlement verdict reproduced end-to-end.** I reimplemented `settlement_value()` + `outcome()` from its definition and ran it against real settled markets: **80/80 contract verdicts matched the venue's own `result`, 0 gaps** (NYC + Chicago hourly, brackets straddling the index value on both sides). Honest denominator: those 80 contracts are only **8 distinct (city, hour) readings** — the bracket ladder inflates n — so this is a smoke test of the logic, not a calibration.
- **Strike convention verified from the rule text**: hourly markets settle `...-T59.99` with *"If the temperature ... is above 59.99°, then the market resolves to Yes"* → strict `>`, which is what `outcome()` does.

**Material finding for our roadmap:** Kalshi runs **two different temperature oracles**. The daily-high family (`KXHIGHNY`) settles on **CLINYC via The Weather Company**; the hourly family (`KXTEMPNYCHS`) settles on **"as reported by Synoptic Data"**. Our `scripts/weather-oracle-reconcile.py` covers the *daily* family only (KXHIGHNY/KXHIGHTDAL vs GHCN TMAX), so it does not touch this oracle at all — and the hourly family's named publisher is a commercial vendor, which is why the keyless index endpoint matters.

## Fit table vs roadmap

Gap proven in our tree before asserting it: `incentive_program|discount_factor_bps|target_size_fp` → **0 hits** in `src/`, `scripts/`, `drafts/`; `live_data/weather|KXTEMP` → **0 hits**. Our weather stack is `weather-oracle-reconcile.py` (daily high, GHCN/IEM/NWS) and `weather-nowcast-sampler.py`.

| Component | Verdict | Card that asks for it |
|---|---|---|
| `model.py` `side_score` / `expected_payout` (~60 lines) | ✅ reimplement behind our own gates (MIT; attribution) | **`kalshi-maker-read-prereg`** (Scheduled) — "resting-order fill simulation net of adverse selection". The card currently says resting orders pay **$0**; LIP is the one cash stream that contradicts "pays $0", so the reward leg is literally the missing half of that sentence |
| `period_reward` centi-cents + `d` unit handling | ✅ take as-is (verified) | same card — the 100× unit bug is pre-solved |
| Measured adverse selection (rewards $20.30 vs fills −$36.06; sweeps 200–600 clips, p90 ~1,400, p99 ~6,000 per 10 s; $1 floor voids ~half of stints) | ⚪ **measured prior**, not code — a number to beat, not to copy | same card, as the null hypothesis for its cost side |
| `windex.py` index/calibrations client + `tick_f`/`cushion_ticks` | ✅ adopt (~60 lines) | **`wx3-weather-breadth-expansion`** (Scheduled) — *extends* its scope: wx3's text names the daily families; the hourly `KXTEMP*HS` family is not named, so adopting this widens the card rather than serving its current text. Flagged for the user, not assumed |
| `settlement_value` / `outcome` (strict `>`, `status` filter, gap handling) | ✅ verified 80/80 | `wx3` / `wx4-weather-live-lane` — oracle identification for the hourly family |
| `data/train_market_features.csv` + the late-day "buy NO" rain hypothesis | ❌ not adoptable | none. The donor measured its own hypothesis away: +11¢ → **−0.001/contract on 139 fills**, and thin-market candidates fell from 5–9/day to ~1/day. Re-testing it would be re-litigating a refuted claim |
| `cli.py` / `dashboard.py` / `recorder.py` | ❌ not portable | none — thin wrappers over our existing samplers and dashboard |
| Autonomous-agent scaffolding / "About: built by Mirabilis" | ❌ | none |

## Integration proposal

Two independent leads; one recommendation, per the one-REC discipline.

**REC — price the LIP reward leg inside the existing maker read.**

```
REC — LIP reward leg for the Kalshi maker read
  Hypothesis:   on markets we actually capture, the LIP reward a resting order earns is at
                least one taker fee per contract, net of the adverse selection that order pays.
  Measurement:  reimplement side_score() as scripts/kalshi-lip-reward-model.py (~60 lines, MIT,
                attribution); replay our captured Kalshi tape (data/kalshi-1c-queue/, the
                kalshi-tape-capture store) over >= 50 counted program-hours across >= 20 distinct
                programs, computing pool*0.5*share*counted_fraction against the live
                /incentive_programs fields, and subtracting the card's measured fill cost.
  Decision rule: if modelled reward >= $0.0131 per contract-hour (one taker fee at P=0.25, the
                card's own bar) NET of adverse selection, over >= 50 counted hours, by 2026-11-24,
                then add the LIP line to kalshi-maker-read-prereg's PnL; else record LIP as
                immaterial and close the card's reward leg.
  Cost:         ~2-3 h, read-only, zero risk to the live lane.
  Reversibility: delete the one script; no rule, size or lane is touched.
```

The donor's own result is the reason to keep the bar high: it earned $20.30 of rewards and lost $36.06 to fills in eight days, and its post-mortem says outright that *"a verified reward model is not an edge until the adverse-selection cost is measured on your own orders"*. Our replay is exactly that measurement — so the expected outcome is a **negative**, cheaply bought.

**Second lead (no REC, documented for the user to pick up):** the Weather Index client closes `wx3`'s stated blocker ("every city needs its own oracle identification — which publisher, which product granularity"). Given the daily/hourly split the station map needs a row per **family**, not per city. Worth 2 h when wx2's residual lands; not now, since wx3 is Scheduled behind wx2 and wx4's prior is negative.

## NOT portable

- The rain-market hypothesis and its dataset — refuted by the donor's own fills; do not re-open.
- Their CLI, dashboard, recorder, and the "autonomous agent" framing — we have equivalents, and the framing adds nothing.
- "Run it, don't vendor it" does **not** rescue the execution side: reading LIP pools is keyless, but *earning* requires placing resting orders, which needs a Kalshi order key we will never hold. Shadow-only, permanently — consistent with `kalshi-maker-read-prereg` and `wx4`.

## Honest caveats

- **The repo's headline is a loss.** Rewards +$20.30, fills −$36.06, NLV $20 → $3.84 in eight days; a second attempt (weather) reached ~$0.1 net. Anyone reading the README's "the model is exact" as an edge is reading it wrong, and the author says so.
- LIP rule *shape* rests on the donor's n=4 reproduction. My verification covers the API, the units and the arithmetic — not the rule text.
- $1 payout floor voids roughly half of small stints; 167 of 184 active liquidity programs carry a **$100** pool (centi-cent-verified), i.e. these are small pools, not a revenue base.
- The Weather Index is *Kalshi-computed* while the hourly market rule names *Synoptic Data* as the reporter; the index point's `source` field reads `hf_asos`, consistent with the same ASOS feed, but index-vs-settlement agreement should be re-confirmed per city on ≥30 closed markets before any wx3 read depends on it. My 80/80 is 8 hours in 2 cities.
- CI green is real but dated (2026-10-15); it is not stale in substance — 0 code-touching commits since — but a suite that has not run in 19 days is a maintenance signal, not a moat. Only 4+ tests in `test_model.py`, and one of them asserts merely `share > 0`, which is close to a tautology.
- One author, three weeks old, ★7. Activity is real (daily), community signal is nil.
- 9 committed `.pyc` files; `data/` carries a 268 KB CSV unrelated to the two components we want.

## §7 — Registry block (prepared, NOT applied)

`data/roadmap.json` was not written: this run's rule is read-only outside `drafts/`, and a sibling session may hold the file. Paste to append to card **`kalshi-maker-read-prereg`** `note`:

```
AUDIT INPUT (2026-11-03, watch; drafts/asset-audit-lip-ledger-20261103.md): mirabilis-agent/lip-ledger
(MIT, ★7, pushed 2026-11-03) carries an exact LIP reward model that this card's economics currently
omit — the card says resting orders pay $0 in fees, and LIP is the one cash stream against that.
Units verified against the Kalshi API field doc ("period_reward ... in centi-cents" -> /10000;
discount_factor_bps 5000 -> d=0.5) and the worked example reproduces by hand (ref 0.27, total 800,
share 5/800). Rule SHAPE rests on the donor's n=4 payout reproduction, not on venue text — no LIP
rule page exists on docs.kalshi.com. REC (read-only, ~2-3h): reimplement side_score as
scripts/kalshi-lip-reward-model.py and price the reward leg over captured tape; decision rule = reward
>= $0.0131/contract-hour (one taker fee at P=0.25) NET of adverse selection over >=50 counted hours by
2026-11-24, else close the reward leg. Donor's own result is the null to beat: +$20.30 rewards vs
-$36.06 fills in 8 days, and "a verified reward model is not an edge until adverse-selection cost is
measured on your own orders". Second lead: same repo's keyless /live_data/weather client settles the
hourly KXTEMP*HS family (Synoptic Data; daily KXHIGHNY uses CLINYC/The Weather Company), which
weather-oracle-reconcile.py does not cover — a wx3 scope extension, no card asks for it today.
```
