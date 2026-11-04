# C-200 fill scoreboard — the verdicts read as a population (Lane B measurement)

**Card:** `c200-fill-scoreboard-caveat` · **Date:** 2026-11-03 · **Lane:** B (measurement / instrument only)
**Instrument:** `scripts/c200-fill-scoreboard.py` (read-only; `mode=ro&immutable=1`). Nothing booked, no rule or size touched.

---

## 1. What the card claimed, and what reproduces

The card's headline, from `scripts/profit-robustness-alloc.py` §7, **reproduces exactly**:

| verdict | legs | notional | settled | booked PnL | ROI | hit |
|---|---|---|---|---|---|---|
| filled | 138 | $1,333.27 | 137 | +$324.37 | +24.3% | 47.4% |
| unfilled | 275 | $2,750.13 | 266 | +$707.80 | +25.7% | 31.2% |
| **reach** | **33.4% of legs / 32.7% of notional** | | | **phantom $707.80 of $1,032.17 = 68.6%** | | |

All 413 legs are `botId=BANKROLL_200`, `fillBasis='book-window'` (no tape verdicts, no unresolved-stamped-as-unfilled), and the near-identical ROI confirms the card's point: the filled legs are not the losers, so this is a **volume** fact, not adverse selection.

## 2. Four corrections the card needs

### (a) The read is 16% of the lane, not the lane
| | count |
|---|---|
| C-200 legs (`isDemo=0`) | 2,600 |
| stamped `filled`/`unfilled` | 413 (15.9%) |
| never stamped | 2,187 (84.1%) |
| legs carrying a `FillIntent` row (the resolver's own join key) | 415 (16.0%) |

The binding limit is `FillIntent` coverage, not evidence quality: **a leg with no `FillIntent` can never be stamped**, so 84% of the lane books at `p(fill)=1` permanently with no verdict possible. The 68.6% is a rate measured on the resolvable 16%, not a figure that applies to the lane's ledger by construction — it is an extrapolation to the rest.

### (b) The window is ONE HOUR, not five minutes
`scripts/c200-printthrough.py` stores `book.minAsk` over `H60 = 3600s`, and that is the field `src/lib/c200-fill-resolution.ts::resolveFill()` tests. Re-scanned from `data/l2` at the **booked** level (`PaperTrade.entryPrice`), 409 stamped legs:

```
reach@5min   11.5%  (47/409)
reach@1hour  22.5%  (92/409)   <- the window the resolver actually tested
```

So the card's "5-MINUTE window" is wrong in the **helpful** direction: a negative verdict already spans an hour, so "a resting bid could still fill later" is a much smaller escape hatch than stated, and 33.4% is an **upper** bound on the 5-minute reach, not a lower bound on fill.

### (c) The verdicts test a price the leg was not booked at (257 of 413 legs)
The resolver prices the level with the **live** credit (`intent − 0.02 × measuredFillShare`), while 257 of the 413 legs were booked by the sidecar at the **flat** `intent − 0.02` (avg credit −0.0139 vs the live model's −0.006 to −0.008). Testing the shallower level biases toward "filled": reproducing the verdicts from the artifact's stored `minAsk` vs the booked entry agrees on 366 and **disagrees on 47**. If anything the true reach rate at the booked levels is *lower* than 33.4%.

### (d) The phantom is RESIDUE, not forward flow
`src/lib/paper.ts::bookedPnl()` is fill-aware by default (2026-10-28+): an `unfilled` leg books **$0** at every later mark and settlement. Splitting the stamped population on stamp-vs-settlement order:

| verdict | settled BEFORE the verdict landed | settled AFTER |
|---|---|---|
| filled | 131 legs / +$438.87 | 6 legs / −$114.50 |
| unfilled | **247 legs / +$707.80** | **19 legs / $0.00** |

The entire $707.80 sits on legs that settled before the resolver stamped them (it stamps after the fact and never restates PnL). The 19 legs stamped while still open book exactly zero. So the flip works; what leaks is the **latency**, not the model.

## 3. What the ladder actually sums today

`query_bankroll.js` sums raw `realizedPnl` over the trailing 7 SETTLED days (`SETTLE_DAYS=3` → today−9…today−3). For **2026-10-25 … 2026-10-31**, total **$597.46**:

| verdict | legs | PnL | share of |PnL| |
|---|---|---|---|
| **unstamped** | 15 | **+$975.57** | 72.1% |
| filled | 14 | −$218.82 | 16.2% |
| unfilled | 24 | −$159.29 | 11.8% |

**163% of the advance window's number is carried by legs that carry no verdict at all.** And the two biggest legs in it fail the reachability test outright:

| leg | market | booked PnL | booked entry | minAsk 5m | minAsk 1h | reachable |
|---|---|---|---|---|---|---|
| cmvton3q7003 | atp-altmaie-lehecka-2026-10-29 | +$552.23 | 0.1533 | 0.16 | 0.16 | **no** |
| cmvte173a003 | atp-norrie-medvede-2026-10-29 | +$476.97 | 0.1733 | 0.18 | 0.18 | **no** |

Both were $100 clips booked 0.7¢ and 0.7¢ **inside** the spread (bid 0.15/ask 0.16 and bid 0.17/ask 0.18), and the ask never came down to the booked level in the hour that followed — they would only have filled if the price had moved **against** us, and both instead won. They are marked `fillStatus NULL` because they have no `FillIntent` row: **the instrument cannot reach the legs the ladder depends on.**

The card's "$128/day claimed vs $46/day reached" is a units error: the 413 legs were dispatched over **38.3 days** (2026-09-26 → 2026-11-03), not 7; the stamping window was 7 days. Booked $1,032.17 / 38.3 = $26.9/day, reached $324.37 / 38.3 = $8.5/day.

## 4. Verdict on the card

- **The direction is confirmed and stronger than the card states**: the lane's advance number in its own window is carried by legs with no verdict, two of which provably never had a position.
- **The 3x framing is right for the wrong reason.** It is not "the stamped legs' PnL is 3x phantom" (that residue has aged out of the window); it is "84% of the lane is unverifiable and still booked at p(fill)=1, and where it has been verified ~2/3 of legs were never positions".
- **The proposed EOD print is a Lane A change** (a published figure) and, as specified, would print **33.4% — a rate measured 1 hour after dispatch, over 16% of the lane**. I am not applying it. The open decision is on the card.

## 5. Options for the print (operator decision, not applied)

1. **No print; fix the coverage first** (recommended). The honest gap is that `FillIntent` covers 16% of the lane. Until the join key exists on most legs, any printed reach rate is a slice rate wearing a lane label. Cost: the instrument work, not a report edit.
2. **Print the coverage caveat, not the rate**: one EOD line — `C-200 fill verdict: 413/2,600 legs stamped (15.9%); 15 of the 7-day advance's legs carry no verdict ($975.57 of $597.46)`.
3. **Print the whole scoreboard line as carded** (reach rate + reach-weighted PnL), labelled `1-hour reach, stamped slice`. Refutation unchanged: a 30-day forward reach ≥ 70% voids it.

## 6. Re-run

```
cd ~/polymarket-copybot
python3 scripts/c200-fill-scoreboard.py                # §A–§D, instant
python3 scripts/c200-fill-scoreboard.py --window5      # + 5-min vs 1-hour reach (re-scans data/l2, ~16 s)
python3 scripts/c200-fill-scoreboard.py --probe-top 5  # + L2 reachability of the advance window's biggest legs
```

Verification: `python3 -m py_compile scripts/c200-fill-scoreboard.py` → clean. No TS touched (`npx tsc --noEmit` not applicable).
