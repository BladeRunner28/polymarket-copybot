# Clip rebalance — cap 0.0-0.2 at $25, and the lift that cannot execute

**LANE A — PROPOSAL ONLY. Nothing applied: no RuleSet row, no `apply-v*.ts`, no write to
`prisma/dev.db`, no merge to main.**
Draft slug: `profit-band-clip-rebalance-20261111` · card: `profit-band-clip-rebalance` ·
proposed 2026-11-11 · re-read with the two commands at the bottom.

---

## 1. The verdict first

**Approve the CAP ($25 on 0.0-0.2). Decline the LIFT as written — not because the lift is
wrong, but because two thirds of it cannot execute and what can execute is worth $57 in the
live window.**

Three measurements decide it, none of which were on the card:

1. **The cap binds on one lane only.** All 65 cheap-band legs above $25 are `BANKROLL_200`
   (Kelly path, `kellyMaxSizeUsd` = 100 in the active RuleSet v71). `STANDARD` has **zero**
   legs above $25 in the band — its clamp is `BOT_LIMITS.STANDARD = $20.00`. So the cap is a
   C-200-scoped sizing change, not a book-wide one.
2. **The lift is an upper bound the rails will not honour.** 892 of the 904 all-time 0.2-0.4
   legs sit *below* $25 and would need to be raised to reach it, but a leg clamped at $20
   (`BOT_LIMITS` for STANDARD *and* the legacy C-200 path) cannot be lifted to $25 by any
   rule — the clamp takes it straight back. Implementable, the lift is **+$1,414 all-time
   (CI +$451..+$2,424)** instead of the card's +$2,186, and **+$57 in the live regime
   (CI −$193..+$323)** instead of +$145. That is noise, on 246 legs over 17 days.
3. **The cap is not an edge trade, it is insurance — and it is the only half that pays where
   the book is now.** It costs $2,108 all-time (30.6% of the book's $6,895) to remove 6.3% of
   its notional, and in exchange it takes all-time **max drawdown from −$1,052 to −$599** and
   the worst day from −$439 to −$289; in the regime −$938 → −$272. Its regime delta is the
   one arm in this card whose market-clustered CI excludes zero **and survives ex-top-5
   wallets and ex-top-5 markets**.

Read plainly: the card's own split note says *"if only one half is approved, apply the lift."*
On the live window the evidence points the **other way** — the cap's regime delta is
+$790 (CI +$290..+$1,324, robust to ex-top-5 wallets: +$729) while the lift's is +$145
(CI −$246..+$564, and it goes **negative**, −$26, once the top five wallets are removed).
The lift's support is all-time history; the cap's support is the regime plus a drawdown cut.
On a book whose ladder gate is currently failing, drawdown is the binding constraint.

---

## 2. Measured basis (reproduced, not re-quoted)

Two instruments, both read-only, both run against `file:…dev.db?mode=ro`:

```
COPYBOT_DB="file:$PWD/prisma/dev.db?mode=ro" python3 scripts/profit-postfix-integrity.py --only=G,J
COPYBOT_DB="file:$PWD/prisma/dev.db?mode=ro" python3 scripts/profit-band-clip-preflight.py
```

Basis (identical by contract in both): cost = `simulatedPositionSize` = **dollars at risk**;
dedupe = first leg per `bot|wallet|market|outcome` within status class; `trueP` = the wallet's
own fill price *only* for the INVERTED price-side class; PnL rescales linearly at a fixed
price; CI = market-clustered bootstrap, 2,000 draws. Population: **5,680 finished legs,
$64,168 at risk** all-time; **246 legs** in the regime (opened ≥ 2026-10-26, 17 days,
14.5 legs/day, 91% resolved); **35 legs** in the post-fix cohort.

### 2.1 Edge — hit rate vs the price paid (§G; every card figure reproduces)

| band | n | hit% | avgP paid | edge pp | Wilson 95% on edge | verdict | ROI@identity |
|---|---|---|---|---|---|---|---|
| 0.0-0.2 | 509 | 20.4 | 0.113 | **+9.1** | +5.9 … +12.9 | edge | +80.9% |
| 0.2-0.4 | 904 | 37.6 | 0.312 | **+6.4** | +3.3 … +9.6 | edge | +20.6% |
| 0.4-0.6 | 1,928 | 46.9 | 0.497 | −2.8 | −5.0 … −0.6 | no edge | −5.6% |
| 0.6-0.8 | 1,167 | 66.5 | 0.688 | −2.4 | −5.1 … +0.3 | open | −3.4% |
| 0.8-1.0 | 1,172 | 84.9 | 0.925 | −7.6 | −9.8 … −5.7 | no edge | −8.2% |

**Correction C6 — the −7.6pp that motivates "clip is inverse to edge" is a mark-priced
number, not a resolution number.** The finished basis includes early closes (a leg that exits
at the mark pays neither 1.0 nor 0.0), so `hit − p` is exact only on the resolved subset. On
the **exact** basis (1,942 resolved legs) the favourite band reads **+2.1pp, CI −3.1…+5.6,
verdict "open"** — not negative — and 0.4-0.6 flips from "no edge" to "open" (+2.8, CI
−0.9…+6.6). The inverse-to-edge claim survives, but it must rest on the two paying bands and
on what the book *does* with the three that don't, **not** on a favourite-band sign.

### 2.2 Shadow — the same legs, re-clipped (§J; every card figure reproduces)

Delta vs the book as actually sized; pp = delta per dollar at risk; CI is market-clustered.

| arm | all-time (5,680 legs) | regime ≥ 2026-10-26 (246) | pre-fix (35) |
|---|---|---|---|
| cap cheap $25 | −$2,108 (−3.3pp) CI −9.0…+1.4 | **+$790 (+15.7pp) CI +6.3…+24.3** | +$224 (+32.9pp) CI +0.0…+48.5 |
| lift 0.2-0.4 $25 | +$2,186 (+3.4pp) CI +1.2…+5.8 | +$145 (+2.9pp) CI −4.8…+11.5 | +$63 (+9.3pp) CI −21.4…+47.4 |
| package (both) | +$78 (+0.1pp) CI −5.8…+5.3 | +$935 (+18.6pp) CI +5.5…+29.9 | +$287 (+42.2pp) CI +0.5…+74.6 |

Notional: all-time 64,168 → **72,358** (+12.8%), regime 5,037 → **5,038**. The card's "same
gross" is a regime-window fact, not a property of the rule — the package adds 13% gross on
history.

### 2.3 What the preflight adds (the three deciders)

**Who the cap binds on** (`0.0-0.2`, legs with clip > $25):

| pop | lane | n | n > $25 | notional > $25 | PnL of those legs | ROI | share of band PnL |
|---|---|---|---|---|---|---|---|
| all-time | BANKROLL_200 | 253 | 65 | $5,656 | +$2,757 | +48.7% | 44% |
| all-time | STANDARD | 256 | **0** | $0 | $0 | — | 0% |
| regime | BANKROLL_200 | 30 | 16 | $1,500 | −$982 | −65.5% | 93% |
| pre-fix | BANKROLL_200 | 6 | 3 | $300 | −$299 | −99.7% | 85% |

Largest cheap-band clip in the book: **$100.00** (= `kellyMaxSizeUsd` v71). The all-time
profit the cap gives up lives in 65 legs; in the regime those same legs are the loss.

**What the lift can reach** (`0.2-0.4`): 892 of 904 all-time legs (and 90 of 90 regime legs)
are below $25; raising them to $25 needs **$12,221** of new notional all-time. Only **12**
legs in the band already exceed $25, all C-200. `BOT_LIMITS` caps STANDARD and the legacy
C-200 path at $20.00 — so most of that $12,221 cannot be booked at $25 without raising a
book-wide clamp, which is a different (and much larger) risk decision.

| arm | all-time | regime | pre-fix |
|---|---|---|---|
| lift to $25 (card's arm, upper bound) | +$2,186 | +$145 | +$63 |
| **lift to $20 (no clamp change)** | **+$1,414** CI +451…+2,424 | **+$57** CI −193…+323 | +$25 |
| **package: cap $25 + lift to $20** | **−$694** CI −4,512…+2,435 | **+$847** CI +269…+1,456 | +$249 |

**Is the delta a tail?**

- cap, all-time: −$2,108 → ex-top-1 **wallet** −$1,340, ex-top-2 −$189, **ex-top-5 +$864
  (sign flips)**. The history the cap "pays for" is two wallets' winning draws — which is
  exactly the tail the cap is built to truncate.
- cap, regime: +$790 → ex-top-5 wallets **+$729**, ex-top-5 markets **+$855**. Robust.
- lift, all-time: +$2,186 → ex-top-5 wallets **+$1,208** (55% survives), ex-top-5 markets
  +$2,034. Robust.
- lift, regime: +$145 → ex-top-5 wallets **−$26**. The live-window lift is carried by the
  top five wallets and nothing else.

**What the cap buys** (closed-leg daily series, same legs):

| pop | arm | cumulative | worst day | max drawdown |
|---|---|---|---|---|
| all-time | book as sized | +$6,895 | −$439 (2026-10-26) | −$1,052 |
| all-time | cap $25 | +$4,787 | −$289 | **−$599 (−43%)** |
| all-time | package | +$6,973 | −$289 | −$580 |
| regime | book as sized | −$852 | −$340 (2026-10-26) | −$938 |
| regime | cap $25 | −$62 | −$201 | **−$272 (−71%)** |
| regime | package | +$83 | −$320 | −$409 |

**Kelly check — what the bands' own records justify** (f* = h − (1−h)·p/(1−p); f* < 0 =
bet nothing; the book bets ~0.2% of bankroll, so nothing here is binding — this RANKS):

| band | avg clip | f* (finished, n=5,680) | f* (resolved, exact, n=1,942) |
|---|---|---|---|
| 0.0-0.2 | $23.0 | **+10.3%** | +11.3% |
| 0.2-0.4 | $11.8 | **+9.3%** | +12.0% |
| 0.4-0.6 | $9.4 | −5.6% | +5.7% |
| 0.6-0.8 | $10.0 | −7.6% | +20.7% |
| 0.8-1.0 | $10.2 | −101.3% | +17.6% |

**Correction C7 — between the two paying bands the clip is not inverse to edge at all:**
f* is +10.3% vs +9.3%, a 1pp difference on a band the book sizes at half the clip. What *is*
misallocated is the other 65% of notional, sitting at $9.4–$10.2 clips in the three bands
whose finished-basis f* is negative. (The resolved column is printed because its identity is
EXACT, and it flips four of five bands positive — that is the winner-skew of a resolved-only
population, not a discovery; judge the book on the finished basis.)
**That 65% is a bigger lever than either half of this card and is not in it.**

**Fillability.** The lift's tolerance is ROI@identity × avgP = 20.6% × 0.312 = **6.4c** of
entry slippage before the added notional stops paying — the card's own bar. In-house we can
only observe booked price vs dispatch intent (222 legs in 0.2-0.4 carry `intentPrice`; mean
booked − intent = **−0.89c**, i.e. the maker credit, not a size effect). **That does not test
a bigger clip**, so every lift number above is an upper bound on thin books.

---

## 3. Decision rule (what to approve, exactly)

**APPROVE — cap `0.0-0.2` at $25.**

- Where: the C-200 sizing path, after `clampPaperSize` so it also bites Kelly-sized legs
  (`mapBankroll200Size` → `applyKellyBandRails` → `clampPaperSize` → **band cap**). Only
  `BANKROLL_200` is affected; STANDARD needs no change (it never reaches $25 in the band).
- How it ships: a new **RuleSet field defaulted to empty** (`bandClipCaps: ""` → no cap →
  byte-identical to today), consumed through the loader's spread-merge. A ruleset that lacks
  the field keeps today's behaviour, so **the revert is deleting one field / writing the
  previous version back** — one field, no code revert, no data migration. No row is
  rewritten: `PaperTrade` sizing is not retro-edited.
- Expected effect, measured: regime **+$790 (+15.7pp)**, CI +$290…+$1,324; pre-fix cohort
  +$224; all-time **−$2,108** = the premium paid for max drawdown −$1,052 → −$599 (−43%) and
  worst day −$439 → −$289. Notional down $1,100 in the regime, $5,656 all-time (6.3% of
  book, 31% of booked profit) — which also frees gross-exposure headroom against the $1,000
  `maxGrossExposureUsd`.

**DECLINE (defer) — lift `0.2-0.4` to $25.** Reasons, in order: (i) it is +$57 in the live
window once clamped to what can execute, (ii) it needs a clamp raise above $20 to be more
than that, (iii) its live-window delta is carried entirely by the top five wallets, and
(iv) the only fill evidence in-house cannot see size impact. If the operator prefers to take
one lever only, this is the half to wait on — the opposite of the card's note.

**If you want the pair anyway**, take the implementable form — cap $25 + **lift to $20**:
all-time −$694 (CI −$4,512…+$2,435), regime **+$847** (CI +$269…+$1,456), pre-fix +$249,
max drawdown −$580 all-time. It needs no `BOT_LIMITS` change.

---

## 4. What would REFUTE this

For the **cap**:
- **The cap costs more than it insures.** On the first **150 settled 0.0-0.2 legs opened
  after the cap**, the shadow on those same legs (actual vs $25-capped) shows a cost above
  **$1,000** with a market-clustered CI excluding zero, **or** the capped band's own realised
  ROI falls below **+20%** while a matched uncapped control stays above it. (Pre-registered
  re-read at 150 legs — ~7–8 weeks of cheap-band flow at the current 47 legs / 17 days =
  2.8 legs/day.)
- **The drawdown purchase does not appear.** Over the next 90 days the closed-leg max
  drawdown of the capped book is **not** at least 25% below the uncapped counterfactual on
  the same legs. Then the premium was paid for nothing and the cap should be reverted (delete
  the field).
- **The binding lane is wrong.** If a forward read shows STANDARD or the legacy C-200 path
  booking cheap-band legs above $25 (it cannot today, clamp $20), the scoping in this
  proposal is stale and the implementation must be re-aimed before it is trusted.

For the **lift**, i.e. what would make me withdraw the deferral:
- 150 forward 0.2-0.4 legs with the **lift-to-$20** shadow's CI excluding zero **and** the
  ex-top-5-wallet delta still positive **and** median realised entry slippage on the cell
  **≤ 3.2c** (half the 6.4c tolerance). All three, not one.

For **my reading of the history**:
- The card's package is a wash all-time (+$78, CI −$5.8…+5.3) only *because* cap and lift
  offset; if a re-run shows the cap's all-time cost is **not** concentrated in two wallets
  (ex-top-5 wallets no longer flips the sign), then the cap is not truncating a lucky tail
  and the insurance argument weakens materially.

**Enforcement proof required before this is called live** (the rule is only real if it
binds): loader spread-merges defaults → field → predicate, evaluated on the boundaries
(0.1999 / 0.20 / 0.2001 and clip 24.99 / 25.00 / 25.01), plus a test that the **DEFAULT**
value of the new field is empty so a ruleset lacking it cannot silently start capping.

---

## 5. Where the numbers come from

| script | role | this run |
|---|---|---|
| `scripts/profit-postfix-integrity.py --only=G,J` | edge vs price, sizing shadow (the card's instrument) | reproduced every card figure |
| `scripts/profit-band-clip-preflight.py` | cap/lift binding, per-lane split, ex-top tails, drawdown, Kelly ranking, per-window shape | new, read-only, imports the instrument above |

Verified this run: `python3 -m py_compile` on both scripts; `--only=E` self-test passes
(identity, band partition, resize identity and lift arithmetic). No TS changed. DB opened
`mode=ro`; zero writes; `data/approvals.json` untouched by me (the intake cron owns it).
