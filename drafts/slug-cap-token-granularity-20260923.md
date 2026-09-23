# The v45 15-per-slug cap counts TOKENS — measured three ways

**Card** `slug-cap-token-granularity` (approved 2026-09-23, **measurement half**) · **status** measured;
no rule changed · **date** 2026-09-23 · instrument `scripts/replay-slug-cap-basis.ts`

## What was asked

The card claims the cap is consumed by a single mega-bucket. The measurement half is: replay the C-200 legs we
actually booked and ask *which legs each candidate basis would have blocked, and what those legs cost or earned*.
A basis that blocks net losers is protecting the lane; a basis that blocks net winners is starving it.

## The replay (30 days, cap 15, 1,160 C-200 legs, $2,823 realized + unrealized)

Replayed legs in open order, maintaining the running OPEN count per bucket under each basis; a bucket frees when
a leg finishes. Entries are unchanged — this is a counterfactual about the CAP, not a strategy backtest.

| basis (what the cap counts) | blocked legs | blocked PnL | blocked W/L | reading |
|---|---|---|---|---|
| **token** (production today) | 83 (7.2%) | **+$152.24** | 51 W / 32 L | **starving** — blocks net winners |
| fine class | 261 (22.5%) | −$87.04 | 138 W / 123 L | protective — blocks net losers |
| coarse class | 325 (28.0%) | −$170.11 | 163 W / 162 L | protective, strongest |

Buckets doing the blocking:

- **token**: `highest` 71 legs (+$62.84), `epl` 12 legs (+$89.40).
- **fine**: `weather-temp` 173 legs (+$76.83), `other` 69 legs (−$270.44), `football-epl` 12 (+$89.40).
- **coarse**: `weather` 173 (+$76.83), `other` 69 (−$270.44), `sports` 37 (+$52.89), `politics` 27 (+$62.93),
  `esports` 17 (−$82.76).

The favourable reading of the class bases is not "they block more" — it is that the leg-level loss they prevent
lives in the lopsided buckets (`other` −$270) that the token basis cannot even see, while the token basis spends
its whole budget blocking 71 legs of one weather mega-bucket worth +$62.84.

**The sign is fragile, so I swept the cap before reading it.** Same replay, same window, three cap levels:

| cap | token (production) | fine class | coarse class |
|---|---|---|---|
| 15 | 83 legs · **+$152.24** (51/32) | 261 · −$87.04 (138/123) | 325 · −$170.11 (163/162) |
| 20 | 69 · +$89.31 (40/29) | 157 · +$120.07 (85/72) | 196 · +$44.27 (100/96) |
| 30 | 50 · +$15.62 (25/25) | 54 · +$17.84 (27/27) | 69 · +$39.36 (37/32) |

Every cell is a near-coin-flip winner/loser split and every blocked-PnL is small ($16–$170 on a $2,823 window).
**At equal severity (~50–70 legs) all three bases block roughly break-even legs** — the basis change by itself is
not a money-maker. What the sweep does show is that the *number* and the *basis* are one decision: class bases
bind 3–4x harder at the same number, so re-basing without re-scaling would take the cap from 7% of legs to 22–28%.

## Live state (re-verified today, not carried over)

- **1,711 lifetime** cap blocks; the last one was **2026-09-21 15:14:09 CDT**.
- Last 7 days: **1,008** blocks — 1,002 on `highest`, 4 on `russia`, 2 on `lowest`, all at "would be 16/15".
- Blocks per day: 363 · 340 · 266 · 434 · 219 · **89** · then **0** on 09-22 and 09-23.
- The structure that caused it is unchanged: token `highest` still wraps a mega-bucket — **8,905 observed rows /
  905 distinct marketIds today alone** (the single biggest token in the observed stream).

**Why it stopped firing — chain verified, not guessed:** the 09-21 blocks came from exactly **two wallets**
(`0xcfff…673d` 453 decisions, `0xc518…2594` 40). Both are now `status='watch'`, and since 2026-09-22 they have
produced **zero** decisions on any token. The **observation/copy split (v61, commit `b4e6268`, approved 09-22)**
made `status='track'` — top-25 by score — the only wallets that can book a copy
(`src/lib/wallet-universe.ts`), so the mega-bucket's feed fell out of the copy universe. Timing, mechanism and the
wallets all line up; the one thing not recoverable is their pre-09-22 status (status history is not stored).

Consequence: the cap is **latent, not harmless**. It still counts a bucket spanning 14,879 marketIds, so a single
copy-eligible wallet trading that family re-consumes the whole rail — which is what happened for six straight days
at 219–434 blocks/day.

## Verdict

- Measured: on the token basis the cap spent **71 of its 83 blocked legs (86%) on one bucket** and blocked net
  winners there. That is the defect the card asserted, now with a number on it.
- The class bases block net losers at cap 15, but they are stricter, not looser (3–4x the legs), and the
  favourable sign does not survive to cap 20–30. **This is not a "swap the basis and profit" finding** — it is
  "the rail is aimed at an accidental bucket and its budget is unmeasured".
- Currently **not binding** (0 open `highest` legs; last block 2 days ago), because v61 demoted the wallets that
  feed it. Nothing needs to fire today.
- Changing the counted basis is an **admission-rule change** → parked with the other two under the Oct 8 freeze.
  Decision ask when the window opens: (a) re-basis to **coarse class** *with* a re-scaled cap, (b) re-basis to a
  **market family** key (neither replay basis tests that — it needs a family key first), or (c) leave the cap on
  tokens and treat it as a league-level rail only, with the mega-bucket excluded by token name. Option (c) is the
  smallest change and is the only one the current evidence fully supports; (a) and (b) each need their own replay.

## Reproduce

```
npx tsx scripts/replay-slug-cap-basis.ts --days 30 --cap 15   # -> data/slug-cap-basis-replay.json
```
