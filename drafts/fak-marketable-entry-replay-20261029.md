# FAK marketable-entry replay over `data/l2` — read-only

Generated 2026-10-29 12:09 CDT by `.worktrees/t_29cb928b/scripts/fak-marketable-replay.py`. Measurement only: nothing in the trade path reads this output, and the live taker path was not touched.

## Verdict against the pre-registered rule

**PASS — >=50% of joined legs land <=2c with a full fill.** A marketable FAK at the dispatch quote lands inside 2c *with a full fill* on **268/381 = 70%** of the legs that have a book at dispatch (bar: 50%). On the **250** legs whose recorded book had not drifted from the decision price at all it is **203/250 = 81%** — the verdict holds on both readings. The median capped effective-entry delta is **+0.0169** including the taker fee, and the median book carries **$2,261** of notional within +2c of the decision price — **434x** the median $2.48 clip.

Rule (from the asset audit, unchanged): *the slice is worth a booking change only if the effective-entry delta lands <= 2c on >= 50% of joined legs.* Joined = a leg whose market has an ask ladder recorded within 120 s of its dispatch in our own L2 corpus.

## The numbers

```
[fak] FAK marketable-entry replay over data/l2 — BOOK-WALK, not an observed fill (the L2 corpus holds books only, zero trade prints by design)
[fak] legs 390 | joined to a book at dispatch 381 | unjoined 9 | no recorded book within +-5 min of dispatch for either token x5, book exists but only at 279s from dispatch (>120s) x1, book exists but only at 162s from dispatch (>120s) x2
[fak] bookBasis post-dispatch 381 / pre-dispatch 0 | lag median 12s (p10 4s, p90 21s) | tokenAmbiguous 14
[fak] at the dispatch quote: best ask - decision price median +0.0050, book mid - decision price median +0.0000
[fak] DECISION RULE (1x clip, FAK limit = decision + 2c): landed on 268/381 = 70% vs the 50% bar -> PASS — >=50% of joined legs land <=2c with a full fill | on the 250 legs whose book had not drifted: 203/250 = 81%
[fak]   1x: capped delta (incl fee) median +0.0169 p90 +0.0259 | full fill 341/381, partial 40 (of which unfillable at the cap 26) | uncapped delta median +0.0172 p90 +0.0318, needs >2c on 112/381
[fak]   vs the booked entry (decision - 2c, what the sidecar writes): capped effective entry sits +0.0369 above it at the median
[fak]   2x: capped median +0.0169 | full fill 335/381 | uncapped median +0.0172 >2c on 119/381
[fak]   4x: capped median +0.0170 | full fill 327/381 | uncapped median +0.0172 >2c on 124/381
[fak] DEPTH within +2c of the decision price: median $2,261 (p10 $7, p90 $32,051)
[fak] fee rates on the joined legs: 0.04 x3, 0.05 x372, 0.07 x6
[fak] fill shape at 1x: median 1 price level(s) walked, 339/381 legs fill at the touch alone
[fak] RECONCILIATION (book mid vs decision price at the dispatch quote): at-dispatch n=250 gap +0.0000 delta +0.0170 landed 203 | drifted-up n=58 gap +0.0100 delta +0.0264 landed 3 | drifted-down n=73 gap -0.0100 delta +0.0071 landed 62
[fak] COST DECOMPOSITION on the 250 at-dispatch legs: half-spread +0.0050 + fee/share +0.0117 = +0.0169 (vs median walk delta +0.0169) | half-spread alone > 2c on 3 legs
[fak] DEPTH vs CLIP: median clip $2.48 (p90 $20.00) vs +2c depth ratio median 434x | clip > +2c depth on 39 legs | +1c depth median $510
[fak] STABILITY over the first 60s of covered quotes (361 legs): median spread of the capped delta 0.0000 | full fill throughout 343/361
[fak] CAVEAT: a book-walk prices what the ladder OFFERS, never whether a counterparty would have traded with us; ladders are top-25 levels per side and the first covered quote is a sample that starts ~20s after the pin. No rule, size, gate or booked figure moves — measurement only.
```

## What this does and does not establish

- **ESTABLISHED — the cost of crossing at dispatch, on 381 legs.** Capped at a decision+2c limit, the median effective entry (VWAP + shipped taker fee) sits **+0.0169** from the decision price, p90 **+0.0259**. 341/381 legs take the whole clip. With no price cap the walk needs more than 2c on **112/381** legs (median **+0.0172**), so the cap is not manufacturing the answer: on a fifth of the book the ladder beyond the touch really does cost more than the bar.
- **ESTABLISHED — the cost is the fee, not the ladder.** On the 250 legs whose recorded book mid still equals the decision price exactly, median half-spread is **+0.0050**, median taker fee **+0.0117/share**, and half-spread + fee **+0.0169** — the same number as the median walk delta. Median price levels walked: **1**, and 339/381 legs never leave the touch. At the median the 2c bar is ~58% fee and ~25% spread: **the taker fee alone consumes more than half the rule's tolerance.**
- **ESTABLISHED — partial fill is a thin-book problem, and it is measurable.** 40/381 legs cannot take the whole clip inside +2c. 26 never fill at all: 22 because the book had already repriced above decision+2c, 1 because it had already fallen below it, and 3 on a book that had NOT drifted — i.e. the half-spread alone already exceeded 2c (true of 3 at-dispatch legs). The other 14 fill part of the clip because it outran the +2c depth; those are the case the card asked for, and the table below shows they are small books carrying large clips, not a price problem.
- **ESTABLISHED — depth.** Median notional within +2c of the decision price is **$2,261** (p10 $7, p90 $32,051), against a median $2.48 clip — 434x the clip at the median, but clip > +2c depth on 39 legs. The same shape v68's ship note reported on live books (12/12 absorbed the doubled clip within +2c, median +2c depth $4,317); this sample is wider and its median is lower, and the ordering still holds.
- **NOT ESTABLISHED — that we would have been filled.** `data/l2` is **books only, with zero trade prints by design** (`record-l2.ts`: the venue's market channel sends no trade stream, and an earlier version of that recorder waited forever for a `trade` message that never arrives). Every number here is a book-walk: it prices what the ladder *offered*, never whether a counterparty would have taken the other side. There is **no execution evidence** in this artifact and none should be read into it.
- **NOT ESTABLISHED — the pre-trade book.** v62 pins a market only *after* its C-200 dispatch, so all 381 joined legs read their ladder **12s after** the dispatch (median; p90 21s); 0 legs have a pre-dispatch quote. 9 legs are not joined at all: no recorded book within +-5 min of dispatch for either token x5; book exists but only at 279s from dispatch (>120s) x1; book exists but only at 162s from dispatch (>120s) x2; book exists but only at 234s from dispatch (>120s) x1. Book state sampled after the decision is not the book the decision faced — that is the one substitution this replay cannot remove.

## Where the cost sits

Worst legs (largest 1x delta including fee):

| market | outcome | decision | clip $ | best ask | 1x delta incl fee | filled | uncapped delta |
| --- | --- | --- | --- | --- | --- | --- | --- |
| wnba-atl-nyl-2026-10-09-spread-home-3pt5 | ATLANTA DREAM | 0.490 | 1.25 | 0.510 | +0.0325 | 100% | +0.0325 |
| fif-chn-tjk-2026-10-06-chn | NO | 0.440 | 1.25 | 0.460 | +0.0324 | 100% | +0.0324 |
| cfb-lou-ncst-2026-10-03-1h-spread-away-3 | LOUISVILLE | 0.430 | 1.25 | 0.450 | +0.0324 | 100% | +0.0324 |
| ufc-lucbor-ianesc-2026-09-29 | LUCA BORANDO | 0.540 | 1.25 | 0.560 | +0.0323 | 100% | +0.0323 |
| wnba-atl-wsh-2026-09-30-assists-jordin-c | NO | 0.550 | 1.25 | 0.570 | +0.0323 | 100% | +0.0323 |
| nba-was-cle-2026-10-28-rebounds-jarrett- | YES | 0.600 | 1.23 | 0.620 | +0.0318 | 100% | +0.0318 |
| ufc-ilibul-erivis-2026-09-29-bulaid-win- | NO | 0.640 | 2.48 | 0.660 | +0.0312 | 100% | +0.0312 |
| arg-riv-aae-2026-10-10-btts | NO | 0.690 | 2.48 | 0.710 | +0.0303 | 100% | +0.0303 |

Cheapest-fill legs for contrast — 5 of these 5 sit in the drifted-down bucket, i.e. the ladder had already fallen below the decision price. A negative delta there is a STALE DECISION PRICE, not a cheap fill:

| market | outcome | decision | clip $ | best ask | 1x delta incl fee | filled | uncapped delta |
| --- | --- | --- | --- | --- | --- | --- | --- |
| dota2-salami-huliga-2026-10-21-game1 | SALAMIT | 0.350 | 17.99 | 0.200 | -0.1420 | 100% | -0.1420 |
| dota2-ts8-pari-2026-10-11-game1 | TEAM SPIRIT | 0.305 | 9.97 | 0.240 | -0.0559 | 100% | -0.0559 |
| dota2-amaru-playti-2026-10-14 | AMARU GAMING | 0.360 | 9.97 | 0.300 | -0.0495 | 100% | -0.0495 |
| dota2-mouz-og-2026-10-01-game2 | MOUZ | 0.285 | 4.96 | 0.230 | -0.0461 | 100% | -0.0461 |
| fif-lie-gib-2026-10-05-lie | NO | 0.725 | 1.23 | 0.670 | -0.0439 | 100% | -0.0439 |

### Where the fill runs out (14 legs partial at 1x)

| market | clip $ | +2c depth $ | fill % | walked delta | gap mid-vs-decision |
| --- | --- | --- | --- | --- | --- |
| ufc-nor1-ail1-2026-09-26-perez-win-by-ko | 20.00 | 0.57 | 2% | +0.0237 | -0.005 |
| will-aurora-win-the-esl-pro-league-seaso | 100.00 | 3.97 | 3% | +0.0125 | +0.000 |
| highest-temperature-in-shanghai-on-octob | 20.00 | 0.80 | 4% | +0.0267 | +0.000 |
| mlb-phi-atl-2026-09-29-first-five-winner | 9.97 | 1.45 | 14% | +0.0253 | +0.005 |
| cfb-syra-vir-2026-10-10-spread-away-5pt5 | 100.00 | 21.98 | 20% | +0.0210 | +0.000 |
| ukr1-kud-buk-2026-10-17-draw | 9.97 | 2.40 | 23% | +0.0241 | +0.000 |
| highest-temperature-in-san-francisco-on- | 20.00 | 8.44 | 38% | +0.0200 | +0.000 |
| nba-mil-ind-2026-10-16 | 9.97 | 4.06 | 38% | +0.0251 | +0.010 |
| ufc-nic24-ias-2026-10-24 | 50.00 | 22.61 | 41% | +0.0221 | -0.010 |
| elon-musk-of-tweets-september-26-septemb | 20.00 | 9.45 | 44% | +0.0233 | +0.010 |
| acl2-svr-shs-2026-10-15-total-3pt5 | 9.97 | 4.92 | 48% | +0.0271 | +0.000 |
| highest-temperature-in-manila-on-septemb | 20.00 | 15.55 | 69% | +0.0116 | +0.000 |
| ufc-geosta-loaabu-2026-09-29-go-the-dist | 9.97 | 8.00 | 76% | +0.0259 | +0.000 |
| highest-temperature-in-toronto-on-octobe | 20.00 | 21.51 | 95% | +0.0224 | +0.000 |

Every row is a book whose +2c depth is smaller than the clip it was asked to carry. The rule's "full fill" is therefore the honest gate: a partial fill at a good price is not a good execution, and 11 of these 14 legs took less than half the clip.

## Consequence if this were booked (NOT a recommendation — Lane A)

The sidecar books `entry = intent - $0.02` on every BANKROLL_200 BUY (`rust-sidecar/src/main.rs`), while crossing the book at dispatch costs **+0.0369** more per share at the median. That gap is not a slippage estimate for the maker model — it is the price of certainty of fill, which the maker model does not have. Whether that trade is worth taking is a booking decision this replay does not make.

## Honest limits

- Ladders are **top-25 levels per side**; "uncapped" means uncapped within what was recorded, and a clip larger than the recorded depth reports `fillFrac < 1` by construction.
- The DB carries no token ids (`ObservedTrade.rawTradeJson` is empty), so our outcome's token is resolved by best-ask proximity to the decision price (the same rule as `c200-printthrough.py::pick_l2_asset`). 14 legs are ambiguous (the sibling token's book is within 1c of the chosen one); 5 of those pass the rule. The PASS margin is 78 legs above the bar, so a token flip on all of them could not overturn it.
- The fee law is the shipped one, not a re-derivation: fee = C x rate x p x (1-p), takers only, charged per level on the walked price; rates by category from the shipped keyword map.
- Fee rates are the shipped category keyword map (crypto .07, politics/finance .04, else .05) applied to the market question: 0.04 x3, 0.05 x372, 0.07 x6 — 98% of this book lands on the default rate, so a category error can only move a minority of legs.
- The fee is charged on every walked level, not just the first, which is the conservative reading.
- Reconciliation, not selection: 250 legs are at-dispatch (book mid equals the decision price to the tick), 58 had drifted up, 73 had drifted down — all of them are counted in the rule. The cost decomposition uses only the at-dispatch set, because a delta measured against a ladder that has moved is measuring the move, not the fill.
- No rule, size, gate or booked PnL moves. A booking change is Lane A and needs approval.

## Reproduce

```
python3 scripts/fak-marketable-replay.py                   # all booked C-200 legs
python3 scripts/fak-marketable-replay.py --limit 40         # fast sample
python3 scripts/fak-marketable-replay.py --all-intents      # include never-booked intents
```

Script: `/Users/xsnyde2/polymarket-copybot/.worktrees/t_29cb928b/scripts/fak-marketable-replay.py` (branch `wt/fak-marketable-replay`, not committed).
Artifact: `/Users/xsnyde2/polymarket-copybot/data/fak-marketable-replay.jsonl` (append-only: one row per leg plus one summary row per run).
