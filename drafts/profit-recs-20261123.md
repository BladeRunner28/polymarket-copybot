# PROFIT REVIEW — 2026-11-23

http://localhost:3013/drafts/profit-recs-20261123

**Instrument (committed with this doc):** `scripts/profit-tenor.py`, extended today with **§S16–S19**
(`--selftest` 9/9 PASS). Re-run: `python3 scripts/profit-tenor.py` (DB `mode=ro`; tape cached under
`data/fill-tape-cache`, no writes). Every figure below prints from that run.
**Population:** 578 settled deduped legs / 476 markets / 32 wallets, `ruleSetVersion ≥ 68`,
2026-09-01…2026-11-23 (26.3 days), **cost = `simulatedPositionSize` = dollars at risk**, dedupe = first
leg per `bot|wallet|market|outcome`, tenor = `timeToResolution` at entry, CIs = market-clustered
bootstrap (2,000 draws).
**Fill basis, stated once, used everywhere below.** `touch(W)` = the venue minute tape
(`clob.polymarket.com/prices-history`, keyless, retroactive) printed a MID at or below the price we bid
inside W of dispatch. A touch is **necessary, not sufficient** (queue position unmodelled), so the
reachable class is an upper bound on what we own and the phantom class a lower bound on the phantom
dollars. Two horizons are printed; **W=1h is the headline**, W=5min the strict variant.

---

## The one thing

**For twelve days the highest-expectancy change in this book has been an approved card that no code
reads.** `profit-band-clip-rebalance` was approved 2026-11-11 as "cap C-200 at $25 in 0.0–0.2, ship the
field defaulted EMPTY". The field is `c200BandClipCaps`; `grep -rn c200BandClipCaps src/` returns
**nothing** — it exists only inside `scripts/apply-v73-c200-cheap-band-clip.ts`, which refuses to run
without a reader. RuleSet **v73 is active with no clip field**, so the cap has never bound once.

Priced today on the legs we can actually own, that card is **+$805.77 over 26.3 days (+$30.67/day)** and
it takes the book from **−5.3% to +5.7%**. On the 5-minute basis it is +$943.21 (+$35.90/day) with a CI
that **excludes zero** [+485, +1460]. On the booked basis it is +$706.60 (+$26.89/day) — the *smaller*
number, because the cap also cuts phantom winners.

That is the review. Everything else today is either a rounding error, a subset of this card, or a bet
the data refuses. **Yesterday's #1 — the 2 → 24h TTR floor at +$30.96/day — is dead**: the short-TTR lane
rescue clears the skip the floor would add, and the committed reach probe runs `scoreTrade` under the live
RuleSet at floor 2 vs 24 over 22,464 cases and moves **0 decisions** (controls armed at 75 / 15 / 1,115;
`drafts/ttr-floor-all-lane-basis-20261123.md`, `scripts/ttr-floor-reach-probe.ts`). It is a rule that
cannot fire. Withdraw it.

---

## 1. The measurement that reorganises the book: the profit we report was never tradeable

`§S16`. The resolver's stamp and the venue tape, on the same 578 legs:

| resolver stamp | legs | touched ≤5min | touched ≤1h |
|---|---:|---:|---:|
| `filled` | 132 | 58.0% | **100.0%** |
| `unfilled` | 288 | 26.4% | **38.5%** |
| `null` (never adjudicated) | 158 | 89.2% | **93.7%** |

Two things follow. The stamp is **directionally right but conservative** (its 5-minute window misses
42% of the legs it calls "filled"); and the **`null` class is not phantom** — 93.7% of it traded at our
price, so reading `fillStatus != 'unfilled'` as "owned" (the 2026-11-03 caveat card's framing) **understates
the book by roughly the null class**. The tape, not the stamp, is the basis to use.

| basis | legs | $ at risk | PnL | ROI |
|---|---:|---:|---:|---:|
| booked (as filed) | 578 | $11,557 | −$91.1 | −0.8% |
| **touched ≤1h (reachable)** | **391** | **$8,305** | **−$443.8** | **−5.3%** |
| never touched ≤1h (phantom) | 187 | $3,251 | **+$352.7** | +10.8% |
| touched ≤5min (strict) | 292 | $6,549 | −$651.2 | −9.9% |
| never touched ≤5min | 284 | $4,895 | +$546.4 | +11.2% |

The book as filed is a coin flip; **the book we own loses 5.3%** and every dollar of reported profit sits
on legs the market never brought to our bid. This is the same defect the fill cards have been circling
(2026-11-03 caveat: 68.6% phantom; 2026-11-13 tape read: 96% of C-200's booked profit unreached) —
today's addition is that it survives on the post-v68 population **and** that the two classes price
differently, which is what makes the cap an edge trade rather than a rail (§2).

## 2. The approved cap is worth more than its own approval memo says

`§S17`. `c200BandClipCaps = "0.0-0.2:25"`, linear rescale of the 38 clipped legs (24 of them priced;
14 booked exactly $0.00), no re-selection:

| basis | clips | delta | $/day | delta CI | post-cap ROI |
|---|---:|---:|---:|---|---:|
| booked (as filed) | 38 | **+$706.60** | +$26.89 | [−476, +1623] | +7.0% |
| touched ≤5min | 21 | **+$943.21** | +$35.90 | **[+485, +1460]** | +5.8% |
| touched ≤1h | 27 | **+$805.77** | +$30.67 | [−287, +1651] | +5.7% |

**Contradiction reported, not resolved by preference.** The apply script's own header measures the same
field as a PnL **cost** — all-time −$2,421.93, CI [−6,321, +877], "a DRAWDOWN RAIL, not an edge trade".
Both readings are true on their own windows: the all-time cheap band is **positive** (69 legs / $6,056 /
+52.4%, in that script's evidence) and the v68+ band is not. What changed between them is the clip
(kellyMaxSizeUsd = $100 lifting cheap legs from ~$12 to $100), not the band. So the honest statement is:
**on the population the current ruleset creates, the cap is an edge trade on the reachable class and a
rail on the rest; the all-time memo prices a cheap band that no longer exists.** The rail argument alone
would have justified it; today's read says it also pays.

**What keeps this from being a tail truncation** (the 2026-11-13 evidence note on the card said the band's
profit is 97.8% ten legs, so the cap could be read as giving up the only tail it has): on the reachable
class the cap **helps on 21 of its 22 priced clips and hurts on 1**. On the booked basis it is 22 helped /
2 hurt, and the two give-ups are +$552 and +$223 — the cap is not picking a side on those two legs, it is
cutting 19 losers at 75% of their clip to collect their clip on two winners it also cuts. That is
variance reduction *and* +EV at the same time, which is why it ranks first.

## 3. Where the ownable book stands after the cap — and the one allocation defect left

`§S18`, post-cap, touched ≤1h. Whole book: **391 legs / $6,380 / +$362.0 / +5.7% / 327 markets,
ex-top-1 +1.5%**. That ex-top-1 is the number to keep in view: after the cap the book is a rounding
error per market, which is why nothing else in it earns a recommendation on its own.

| cell (post-cap, reachable) | legs | $ risk | PnL | ROI | ex-top-1 | mkts |
|---|---:|---:|---:|---:|---:|---:|
| 2–24h **short-TTR lane** | 146 | $1,733 | +$400.5 | **+23.1%** | +7.7% | 146 |
| 2–24h **main path** | 147 | $2,688 | −$351.4 | **−13.1%** | −14.9% | 111 |
| 72h–7d main path | 36 | $852 | +$401.6 | +47.1% | +31.9% | 20 |
| 7d+ main path | 26 | $604 | −$77.7 | −12.9% | −18.4% | 20 |
| band 0.00–0.20 | 82 | $1,596 | +$229.9 | +14.4% | −2.4% | 69 |
| band 0.60–0.80 | 143 | $1,660 | +$24.0 | +1.4% | +0.7% | 121 |
| band 0.80–1.00 | 32 | $1,510 | +$129.8 | +8.6% | +7.7% | 18 |

**The defect: the bot puts more dollars on the copy that loses and fewer on the copy that earns.** Same
window, same lane rescue available: the $11.87 lane copy earns +23.1% on 146 distinct markets; the $18.29
Kelly copy loses −13.1% on 111 — 1.54x the clip and 1.55x the notional on the loser. The main-path
short-tenor cell is **broad, not a tail**: ex-top-1 −14.9%, ex-top-3 −18.0%, ex-top-5 −21.0% (the loss
deepens as winners are removed), PnL CI [−695.2, **+14.0**].
That upper bound is the whole argument: **the most the cell could be worth is $14 over 26 days, and the
point estimate is $351 against it.** Capping it is a positive-EV bet at the CI boundary.

---

# Recommendations, ranked by expected value

### R1 — Implement and apply the approved $25 cheap-band cap. **+$31/day. 1h. Lane A (approved; needs the code).**

- **Hypothesis.** The v68+ cheap band loses money on the legs we can fill, and a $25 clip removes most of
  that loss without touching any other band.
- **Measurement.** `scripts/profit-tenor.py` §S17 (committed today): 38 clipped legs, delta **+$805.77
  (+$30.67/day)** on the touched-≤1h basis and **+$943.21 (+$35.90/day), CI [+485,+1460]** on the
  ≤5-min basis; the book's ownable ROI moves **−5.3% → +5.7%**. Contrast basis: booked +$706.60.
- **Decision rule.** Ship as designed in `drafts/profit-band-clip-rebalance-20261112.md` §5.2 — the four
  edits (Rules field, DEFAULT `""`, parser + min-only helper in `band-size.ts`, clamp call in
  `openPaperTrade` after `clampPaperSize`, pass-through in `score-trades.ts`), then
  `npx tsx scripts/apply-v73-c200-cheap-band-clip.ts --yes`, then the boundary probe at px
  0.1999/0.2000/0.2001 × clip 24.99/25.00/25.01 and one live cycle proving `simulatedPositionSize ≤ 25`
  in-band with neighbouring bands untouched. Apply **alone** — nothing else in the same window.
- **Refutation.** A forward 40 settled cheap-band legs clipped at $25 whose tape-touch ROI is **≥ +10%**
  (the cap is then destroying real wins, not truncating a losing tail), **or** a forward 30-day window in
  which the capped book underperforms its uncapped shadow by **≥ $150 with a CI excluding zero** → revert
  (`apply-v73 --revert`, the default is `""`, byte-identical).

### R2 — Size main-path legs resolving inside 24h at the lane clip ($10). **+$5.9/day. 1h. Lane A (propose only).**

- **Hypothesis.** The main path is misrouted inside 24h: a leg with hours left should be sized by the
  short-TTR channel, not by Kelly, because the price has no time to converge on our thesis.
- **Measurement.** `§S18`/`§S19`: post-cap reachable main-path 2–24h = 147 legs / $2,688 / −$351.4
  (−13.1%), CI [−695.2, +14.0], 111 markets, ex-top-5 −21.0%. A $10 cap on that cell **after** the
  approved cap binds 55 clips and is worth **+$155.41 (+$5.91/day)**; $15 → +$79.33; a full block → the
  whole +$351.4 (+$13.4/day) but on a −13.1% point estimate that is one half-point short of a CI that
  excludes zero.
- **Decision rule.** One RuleSet field `mainPathShortTtrClipUsd` (default `0` = off), applied in the same
  clamp as `kellyMaxSizeUsd` when `timeToResolution < 24h` and the leg was **not** admitted by the short-TTR
  lane (read the lane flag, not the price). Ship at $10. Escalate to a block (+$196 more) only if the
  forward read in the refutation clause lands adverse.
- **Refutation.** A forward 150 main-path 2–24h legs (tape-touch basis) at **≥ 0 ROI**, or ex-top-5 ≥ 0 →
  withdraw. The cell's own CI upper bound (+$14) means the worst case is ~−$0.5/day, which is why this is
  worth an hour even at this n.

### R3 — Nothing else. Three measured refusals, one unlocking measurement.

Do **not** stack a third lever on these cells. Each of the tempting ones is dead on a number measured
today, with its own refutation:

- **Upsize the short-TTR lane** (the +23.1% cell). Refused: **one wallet, 0x885ffdf3, carries $392 of the
  cell's $390**; ex-top-1 +6.3%, **ex-top-3 −7.0%**, CI [−11.8, +68.7]. And the wallet axis is closed
  independently: `drafts/wallet-fdr-audit-20261029.md` — 0 of 25 tracked wallets survives the correction
  for 1,136 screened (best q = 0.101). Unlocks on: the lane cell clearing +5% **ex-top-3** at n ≥ 300.
- **Upsize 0.80–0.85 favourites** (+8.6%, CI [+69,+202], 0 losses in 32 legs, 18 markets, avg px 0.865).
  Refused: at a 0.865 break-even, "no loss yet" is not 100% accuracy, it is n=32 and 23 legs from one
  wallet; `profit-entry-ceiling-censored-pool` (2026-11-20) already measured the next bucket up at −7.6%.
  Unlocks on: ≥100 forward acted bets at 0.80–0.85 clearing price+5pp with one loss priced in.
- **The 2 → 24h TTR floor** (+$30.96/day yesterday). Refused: reaches **0 of 22,464** scoreTrade cases
  (three armed controls). Unlocks on: moving `shortTtrMaxHours` 72 → 24, which is a *different* field and
  must be priced with the reach probe first.
- **The residual long-dated $20 cap** (yesterday's R2). Refused as non-additive: measured **after** the
  approved $25 cap it is worth **+$11.21 (+$0.43/day)** on 10 clips, not the +$6.60/day the card quotes —
  96% of that card is the approved cap wearing a tenor filter.

**IF YOU WEREN'T HERE:** implement `c200BandClipCaps` and run `apply-v73 --yes` — twelve days of an
approved, measured, unimplemented +$31/day, and the only change that flips the ownable book positive.

---

## Corrections and contradictions carried forward

1. **Yesterday's #1 (floor flip) is withdrawn** — it cannot fire (§3 above; reach probe 0/22,464).
2. **Yesterday's R2 (long-dated $20 cap)** is 96% subsumed by the approved $25 cap: +$0.43/day, not +$6.60.
3. **The cap's own approval memo calls it a rail at zero cost** — on the v68+ reachable population it is
   +$31/day. The all-time window it quotes is a cheap band that the $100 Kelly clip no longer produces.
4. **The 2026-11-03 caveat's "owned = not unfilled" basis understates the book**: the resolver `null` class
   is 93.7% touched and is a real position class.
5. **Capacity is not the constraint.** 396 open legs / $4,537 / **433,860 capital-days already carried**
   (S3/S8) is a capital-days number, not a refusal: no gate moves a leg on exposure, so freeing stranded
   STANDARD notional buys nothing until flow does. The stranded-`closed` problem stays a mark problem.

## Reproduce

```bash
python3 scripts/profit-tenor.py --selftest          # 9/9
python3 scripts/profit-tenor.py | sed -n '/S16/,/S19/p'
npx tsx scripts/ttr-floor-reach-probe.ts             # 0/22,464, controls 75/15/1115
grep -rn c200BandClipCaps src/                       # (nothing) — the approved cap has no reader
```

**Lane policy:** Lane B only today — one instrument extended, no RuleSet read/write, no prisma write, DB
opened `mode=ro`, nothing applied. R1 and R2 change what the bot risks: **Lane A proposals, operator's call.**
