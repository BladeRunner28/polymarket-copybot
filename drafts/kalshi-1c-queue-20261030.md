# Kalshi 1¢ tail — measured queue depth and fill probability

Card `t_0cb77acd` (Lane B instrument) · read 2026-10-30 00:30Z · branch `wt/kalshi-1c-queue-depth`, uncommitted
Dashboard: http://localhost:3013/drafts/kalshi-1c-queue-20261030

## Key insight

The pre-registered maker read (`drafts/kalshi-maker-read-20261029`) credits the +0.64¢ gate cell on the
first ≥100-contract print at 1¢ and cannot see the queue. Measured forward over 91.6 minutes, the queue
is **not** what kills the cell, and the fill is **not** uniformly available either — it depends entirely
on which side of the 1¢ level is resting:

- The 1¢ level is **empty of sellers 46.5%** of market-time; when occupied, a median **12,620
  contracts** stand ahead of a new seller, and only 8.5% of occupied observations hold ≤1,000. A
  100-lot that joins late is behind ~100× its own size, and on those strikes a ≥100-contract lift moves
  the queue by 2–23%.
- Conditional on a ≥100-contract 1¢ lift, a 100-lot resting at 1¢ fills **37.0% [29.4, 45.4]** of the
  time. But **every** fill comes from the one channel where the level held a resting 1¢ YES bid — a
  quote a seller crosses on arrival (41 bursts, 95.1%). In the channel the parent card actually named —
  resting asks at 1¢, i.e. *passively queueing behind the level* — the fill is **4.6% [1.8, 11.2]** on
  87 bursts.
- Asked the question a resting order really faces — one 100-lot on one strike, held for that strike's
  life — the fill is **13.3% [9.2, 18.9]** across 188 strikes observed for ≥80% of their life.

The declared decision rule (≥25%) **passes on its own conditional terms (37.0%)** and **fails on the two
formulations an operator would use (13.3% per order, 4.6% as a passive maker)**. The cell is a *take
into momentary 1¢ bids*, not a deep-queue make. Nothing here changes a rule, size, gate or booking.

---

## 1. What was built

Three keyless, read-only (`GET`-only) scripts plus a standing capture:

| file | role |
|---|---|
| `scripts/kalshi-1c-queue-capture.py` | one `GET /markets?series_ticker=KXBTCD` (238 open strikes in one call) + one `GET /markets/trades?limit=1000` per 1.5 s cycle, plus one per-market `GET /markets/{t}/orderbook` immediately after any ≥100-contract 1¢ print |
| `scripts/kalshi-1c-queue-estimate.py` | the read: depth distribution, channel classification, fill test with Wilson bands, EV translation |
| `scripts/kalshi-1c-tape-side.py` | independent retrospective cross-check on 13.5 days of already-captured tape |
| `scripts/cron-scripts/copybot-kalshi-1c-queue.sh` | 14-minute window every 15 minutes, house lock/observability contract — registered and running, because Kalshi publishes no book history |

Why polling, not streaming — the v2 stream refuses keyless clients:

```
$ python3 probe_ws_raw.py
HTTP/1.1 401 Unauthorized
{"code":"token_authentication_failure","message":"token authentication failure"}
```

No Kalshi API key exists, so 1.5 s polling is the floor. Every event row carries `snap_age_ms`
(p50 0.85 s, p90 1.49 s, max 7.29 s) so stale attributions can be excluded.

### The book model this rests on

Kalshi quotes one price per market, so the YES ask at 1¢ *is* a resting NO bid at 99¢, and a YES bid at
1¢ crosses it (1¢ + 99¢ = $1). One prediction follows, and it held: **0 crossed books in 791,112
market-observations**. The two sides of the 1¢ level never coexist, so exactly one of three states is
true at any instant, and that decides the fill channel:

| state | meaning for a sell-YES-at-1¢ order |
|---|---|
| `cross` | a YES bid rests at 1¢ → **crosses it, fills on arrival** |
| `queue` | YES asks rest at 1¢ → **queues behind them**, needs the sweep to reach it |
| `alone` | neither side → the order is the only resting seller at the level |

The tape cannot supply this: `taker_book_side` was `"bid"` on **112 of 112** captured 1¢ prints, so the
label does not identify the maker's side. The prior-snapshot book state does.

---

## 2. What was measured

Coverage, quoted with every number below (`data/kalshi-1c-queue/coverage.jsonl`): **3,324 snapshot
cycles over 91.6 min, 791,112 market-observations, 614 tickers, 862 captured 1¢ lifts on 51 tickers
(313 of them ≥100 contracts), 293 bursts, 135 qualifying bursts, 6,845 requests, 0 errors.**

### 2.1 How deep is the 1¢ level?

| state of the 1¢ level | share of market-observations |
|---|---|
| YES asks resting (a seller queues) | 53.5% |
| level absent (a seller would be alone) | 45.0% |
| YES bid resting (a seller fills on arrival) | 1.5% |

Contracts resting at 1¢ when occupied: p10 **1,286** · p25 **6,010** · median **12,620** · p75
**39,100** · max **39,390**. Share of occupied observations at or below 1,000 contracts: **8.5%**
(≤100: 3.7%, ≤5,000: 22.9%, ≤20,000: 50.8%). When a crossable 1¢ bid is present its size is p25 155 ·
median 846 · p75 2,584.

This is the number the pre-registration could not see: on half of all market-time the 1¢ queue is
thousands of contracts deep, while the median print at 1¢ is 200 contracts (retrospective, §3).

### 2.2 p(fill | depth ahead) — the card's deliverable

135 qualifying bursts (largest print ≥100 contracts); a 100-contract order joins at the prior snapshot
and fills only if cumulative 1¢ lift reaches depth-ahead + 100:

| contracts ahead of us | n | p(fill) LOWER | 95% Wilson |
|---|---|---|---|
| 0 (first in queue, or we cross) | 48 | 95.8% | [86.0, 98.8] |
| 1 – 100 | 1 | 100.0% | [20.7, 100.0] |
| 100 – 1,000 | 19 | 10.5% | [2.9, 31.4] |
| 1,000 – 5,000 | 57 | 1.8% | [0.3, 9.3] |
| > 5,000 | 10 | 0.0% | [0.0, 27.8] |
| **all qualifying** | **135** | **37.0%** | **[29.4, 45.4]** |

Two bounds, not one: LOWER assumes every contract resting at the prior snapshot is still ahead of us
(Kalshi publishes one aggregate size per level, so a cancel ahead of us is indistinguishable from a
fill); UPPER caps pre-burst depth at `min(depth_before, depth_after + lift)`. They coincide on this
sample, so nothing below is an artefact of the bound choice.

Fill probability rises with the size of the lift — 100–500 contracts: 31.2% (n=80), 500–2,000: 40.0%
(n=45), >2,000: 70.0% (n=10) — which is the mechanism working as advertised: bigger sweeps reach deeper
into the queue.

### 2.3 Which channel carries the fills

| channel | n | p(fill) LOWER | 95% Wilson |
|---|---|---|---|
| `cross` — 1¢ YES bid rested (fill on arrival) | 41 | 95.1% | [83.9, 98.7] |
| `queue` — 1¢ YES asks rested (fill needs the sweep) | 87 | 4.6% | [1.8, 11.2] |
| `alone` | 7 | 100.0% | — |

Sensitivity to the card's 100-contract cut: ≥100 → 37.0% (n=135), ≥50 → 32.2% (n=180), ≥30 → 30.4%
(n=204), ≥1 → 25.6% (n=289). Loosening the cut pulls the answer *down* — small lifts rarely clear a
deep level — so the ≥100 cut is not flattering the result.

Strata that matter for the parent card's adverse-fill story: fills are more likely in the last minutes
before a close — ≤5 min to close 45.2% (n=31), 5–30 min 30.4% (n=69), 30–120 min 29.2% (n=24).

### 2.4 What it would be worth

Taking +0.64¢/contract from the pre-registered read as given (not re-derived here, and the 0.36%
adverse-fill share is already inside it):

- one fill of a 100-lot = 0.64¢ × 100 = **64¢**, held against **$99** of collateral (99¢ per contract)
- EV per qualifying burst you are standing in = 64¢ × 0.370 = **23.7¢**
- qualifying bursts per strike-hour (measured) = **0.371** → **8.80¢ per strike-hour of resting**
- at the lane's $1,000 base exposure cap ≈ 10 resting 100-lots → **1.38 fills/hour → $0.88/hour
  gross → 2.1%/day gross on $990**

That last line is an order-of-magnitude translation, not a claim: burst arrival is strongly
non-stationary (it clusters in the last minutes of each hourly close), so a flat per-hour rate
extrapolates an activity-weighted window. Throughput and sizing are Lane A's call.

---

## 3. Reality checks

**Independent retrospective (13.5 days, different dataset).** `scripts/kalshi-1c-tape-side.py` over the
parent's verbatim tape — 384 captured hours, 20,358 ≥100-contract 1¢ prints, 2,973 markets. Print size
at 1¢: median 200, p90 805. Per-market whole-life lift at 1¢: median **1,013**, p75 2,863, p90 6,456;
only 13.8% of markets ever lift ≥5,000 and 4.4% ≥10,000. Against a median occupied depth of 12,620, a
100-lot at the back needs ~12,700 of cumulative lift — reachable in a few percent of markets. This
reproduces the ~5% queue-channel result from a completely different dataset, without the forward
capture at all.

**Does the standing 1¢ bid actually decrement when hit?** Mostly not, and this is the one soft spot in
the headline. Markets-list before vs after (n=38): unchanged 35, shrank by less than the lift 0, shrank
by at least the lift 3. Fresh per-market orderbook 0.3 s after the print (n=31): **the 1¢ bid was gone
entirely 28 times**, unchanged once. So the crossable quote is usually consumed by the very print used
as the trigger — a resting order in the counterfactual would have crossed it first, but the *size* it
would capture is not resolvable at 1.5 s polling. The cross channel's 95.1% is therefore an upper bound
on a real fill, not a capacity measurement.

**`/markets` list vs fresh `/markets/{t}/orderbook`.** 9 of 10 sampled strikes agreed exactly; one had
the list a tick behind the book. Depth attribution is right most of the time and never silently stale
by more than one cycle; `snap_age_ms` is stored per event so it can be excluded.

**Non-stationarity.** Lifts cluster at each hourly close: the retrospective tape averages 62.7
events/hour but 129–154 in its busiest hours, and the first four minutes of this capture (across a
23:00Z close) produced 98 lifts. Every "per hour" figure above is an activity-weighted average.

**Sample size.** 135 qualifying bursts separate "always" from "never" and little more. The
queue-channel CI [1.8, 11.2] is tight enough to call it below 25%; the cross channel's is tight enough
to call it above — but its capacity question is open. The standing 15-minute capture exists to fix that.

**Deliberately not claimed.** The settlement side (does the 1¢ short actually win 96.4% of the time net
of the adverse tail) is the parent card's finding and is not re-measured here. Whole-life fill rate over
*multiple days* still needs the standing capture; the estimator already refuses that row until markets
are observed for ≥80% of their life.

---

## 4. Verdict against the declared decision rule

The rule declared on the card: *promote the 1¢ cell for a Lane A capital/risk decision only if p(fill)
at 1¢ clears 25% for a 100-contract order resting through a ≥100-lot lift.*

Three numbers, three questions:

| question | measured | vs the 25% bar |
|---|---|---|
| p(fill \| a ≥100-lot lift lands) — **the card's rule** | 37.0% [29.4, 45.4] | **passes** |
| p(a resting 100-lot is ever filled, over the strike's life) | 13.3% [9.2, 18.9] | fails |
| p(fill \| lift) as a passive maker behind the level | 4.6% [1.8, 11.2] | fails |

So: **the card's rule passes as written, and I would not read that pass as a green light.** The pass is
carried by a channel where the order is effectively a *take* — crossing a 1¢ bid that is gone 28/31
times within 0.3 s — while the mechanism the pre-registration described (rest behind the level and let
the sweep come to you) measures 4.6%, and the per-order rate an operator would actually experience is
13.3%. The fill is not the cell's weak link, so the lane should not be closed on fill grounds; but the
cell is **not** the passive-queue trade it was described as.

Recommendation for Lane A (their call, not mine): treat the +0.64¢ cell as a **take into momentary 1¢
bids near the hourly close**, and restate the promotion bar on the per-order number (13.3%) rather than
the burst-conditional one (37.0%) before capital moves. The open measurement is now narrow and
answerable: *how much size can actually be sold into standing 1¢ bids per hour, and does that survive
sub-second competition* — which needs either an authenticated websocket (no key exists) or more days of
this capture at finer polling.

Nothing here changed a rule, a size, a gate, a booking or a threshold, and no money is at risk.

---

## 5. Reproduce

```bash
cd /Users/xsnyde2/polymarket-copybot/.worktrees/t_0cb77acd

python3 -m py_compile scripts/kalshi-1c-queue-capture.py scripts/kalshi-1c-queue-estimate.py \
    scripts/kalshi-1c-tape-side.py scripts/kalshi-1c-queue-capture.test.py
python3 scripts/kalshi-1c-queue-capture.test.py                                     # timestamp normaliser
python3 scripts/kalshi-1c-queue-capture.py --minutes 20                             # forward capture
python3 scripts/kalshi-1c-queue-estimate.py                                         # every table above
python3 scripts/kalshi-1c-tape-side.py --out data/kalshi-1c-queue/tape-side.json    # retrospective
```

Standing capture: cron job `copybot-kalshi-1c-queue` (id `d510ffc855f1`, every 15 min, 14-minute
window, silent when healthy, lock-protected) → `~/.hermes/scripts/copybot-kalshi-1c-queue.sh` →
`scripts/cron-scripts/copybot-kalshi-1c-queue.sh`. The shim prefers the main-repo copy and falls back
to this worktree, which is where it currently resolves because **this work is deliberately uncommitted
and unmerged** (card constraint); Kalshi keeps no book history, so the capture started immediately
rather than waiting for a merge. Re-run the estimator any time; it accumulates. Merging
`wt/kalshi-1c-queue-depth` later moves the script and its data under the main repo without any change
to the instrument.

## 6. Artefacts

- `data/kalshi-1c-queue/kalshi-1c-queue-read.json` — machine-readable version of every table, with
  burst-level rows
- `data/kalshi-1c-queue/tape-side.json` — retrospective cross-check
- `data/kalshi-1c-queue/snaps-*.jsonl.gz`, `events-*.jsonl`, `coverage.jsonl`, `state.json` — raw capture
