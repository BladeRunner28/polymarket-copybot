# The v45 slug cap: the mega-bucket stopped binding, and the counter counts the wrong thing

**Card** `slug-cap-token-granularity` · **status** measured; NO rule changed · **date** 2026-10-30
**Instruments** `scripts/slug-cap-blocked-legs.ts` (new), `scripts/replay-slug-cap-basis.ts` (caveat repaired),
`src/lib/slug-cap-blocks.ts` · **evidence** `data/slug-cap-blocked-legs.json`, `data/slug-cap-basis-replay.json`

## 1. The mega-bucket is no longer the binding bucket

The 2026-09-23 read was right about what it measured: 1,002 of 1,008 blocks in the week to 09-21 were on token
`highest`. That is not the live state any more.

- **Blocks on `highest`, last 30d: 0.** The last `highest` refusal in the journal is **2026-09-21 20:14:09Z**
  (lifetime 1,700, all between 09-15 and 09-21).
- Blocks in the last 30d (2026-09-30 → 2026-10-30, level = one decision): **105**, on **seven league tokens**
  — dota2 33, mex 28, cfb 21, fl1 9, ufc 7, epl 6, nhl 1. Every one of them a bucket the cap was designed to hold.
- The mega-buckets are still huge, in fact bigger than the card said: distinct marketIds in the last 30d —
  `highest` 15,662, `btc` 11,651, `eth` 11,340, `xrp` 11,046, `sol` 10,844, `bnb` 5,293, `doge` 4,382,
  `hype` 4,182, `will` 3,226. So the latent risk is **wider** than one token, but it is not being exercised: the
  rail's live pressure comes from leagues.

**Verdict on the card's three options:** (c) "exclude the mega-bucket by token name" would change **nothing**
today — 0 blocks on those tokens in 30 days. Re-basing to fine/coarse class would tighten the rail 3–4× on league
tokens, where the blocked legs are net ~zero (below). **No basis change is justified. Do not do (a), (b) or (c).**

## 2. What the rail actually refused, last 30 days

The 09-23 instrument replayed legs *as booked*, so it could never see a leg the cap refused. This run prices the
refusals themselves.

**Basis** — population: C-200, non-demo decisions whose journal row carries a v45 slug-cap block, 2026-09-30 →
2026-10-30; level: one decision (each refusal = one copy not taken); price: the decision's `detectedPrice`
(fee 0, slippage 0); settlement: the market's own winning label — **105 of 105 priced**, 0 undetermined, none
counted as a loss.

- per-$1 mean **+$0.05**, median **+$0.10**, trimmed mean **+$0.05**, sum **+$5.66**, win rate **69.5%**
- **ex-top-10: −$5.50** → the positive sum is ~10 legs, and one bucket carries it (fl1, 9 legs, +$9.18 on 10-26)
- with +1c entry slippage: mean +$0.04, sum +$3.90

So the rail is **neither starving nor protecting the lane** at the aggregate level. It is close to a coin flip on
value and it is blocking a lot of nothing.

## 3. The real finding: the counter counts refusals, not positions

`c200SlugCounts` (scripts/score-trades.ts ~L778) is incremented when a decision **passes** the cap check, and it is
**never decremented** when a later gate refuses the copy. Inside one scoring run the bucket therefore fills with
attempts that opened nothing.

Worked example, 2026-10-21 21:17:42Z, token `mex`, one run:

```
21:17:42.410  skip  mex  ... kelly no-edge (q=0.846 ≤ price=0.905)     <- attempt 1 passes cap, opens nothing
   ... 15 attempts, all refused by kelly, mex counter = 15 ...
21:17:42.674  skip  mex  v45 market-slug cap (mex would be 16/15)      <- refused by a bucket holding ZERO legs
21:17:42.691  ... 28 such refusals in 470ms ...                       <- true open mex legs: 0, all day
```

Measured across the 30d population, using the booked legs' own open/close intervals as the ground truth for
concurrent open positions at each decision timestamp:

- **phantom (true concurrent open < cap): 77 of 105 = 73.3%** — mex 28/28 at 0 open, dota2 33/33 at 0–3 open,
  epl 6/6 at 0 open, fl1 9/9 at 2 open, nhl 1/1 at 9 open
- **genuine (true open ≥ cap): 28** — cfb 21 at exactly 15 open, ufc 7 at exactly 15
- the refused legs split by class: **genuine −$5.78 per $1 (protective, ex-top-10 −$11.81)**,
  **phantom +$11.44 (ex-top-10 +$0.46)** — so the wrong-basis blocks are the mildly costly ones

**But the phantom cost is probably ~0 in practice.** The cap is checked BEFORE kelly, band and wallet gates, so a
phantom refusal never learns what the rest of the funnel would have done. Same-run, same-token peers are killed
downstream in bulk: mex 420 kelly refusals, dota2 471 kelly + 212 confidence, fl1 65 kelly, cfb 30 confidence.
The +$11.44 is an upper bound, and close to the whole of it is likely to be refused downstream anyway.

**Why this is Lane A, not a free repair.** Making the counter track opened positions (or decrementing it when a leg
fails) admits copies the bot currently refuses. It is queued as `slug-cap-counter-basis` with `awaiting-approval`;
nothing was changed in `score-trades.ts`.

## 4. Instrument repair shipped (Lane B)

- `scripts/replay-slug-cap-basis.ts` now prints the journal refusal count beside its own replay result and states
  that a replay over booked legs is a **lower bound**, not a statement about the rail. On the 30d window it prints
  `0/441 blocked` while the journal recorded 105 refusals — the silence that made the 09-23 number look complete.
- `scripts/slug-cap-blocked-legs.ts` + `src/lib/slug-cap-blocks.ts` (11 tests) price the refusals and classify
  genuine vs phantom.
- The 09-23 token-arm figure (**83 legs, +$152.24, "starving"**) is not reproducible on the current window: at
  today's concurrency the same replay blocks **0/441**, and the fine/coarse bases block 21/41 legs at −$53.27/−$17.67.
  Both readings are correct for their windows — the rail's pressure moved from the mega-bucket to the leagues.

## 5. Refutation

The card closes as **measured, no change**. It reopens if any wallet admitted under the current top-25 copy set
starts producing ≥15 concurrent `highest`/`crypto` legs — the same signature that produced 1,700 `highest` blocks
in the week to 09-21. Watch: `decisionJournal` refusal count by token, weekly.
