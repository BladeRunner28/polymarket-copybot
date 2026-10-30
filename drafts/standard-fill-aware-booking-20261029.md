# STANDARD fill-aware booking — the cent is a COST, not a gain (Lane A proposal, 2026-10-29)

Roadmap card `standard-fill-aware-booking`. **Nothing applied** — no rule, size, gate, booking or booked
figure changed; no write to `prisma/dev.db` (every read below is `mode=ro`), no `apply-v*.ts`, nothing merged.

Measurement scripts (read-only, this worktree, uncommitted):

```
scripts/standard-fill-aware-rerebook.py     # clause 2 + the lane baseline + the rec reproduction
data/standard-fill-stamp.jsonl              # the fill booth's per-leg evidence (snapshot 2026-10-29T17:14Z)
scripts/standard-fill-stamp.ts              # the booth that produced it (card t_7560e0d0)
```

```
python3 scripts/standard-fill-aware-rerebook.py                 # all stamped legs — the run quoted below
python3 scripts/standard-fill-aware-rerebook.py --since 2026-09-21   # W39+ era cut
python3 scripts/standard-fill-aware-rerebook.py --since 2026-10-05   # W41+ era cut
python3 scripts/standard-fill-aware-rerebook.py --json          # machine-readable
```

The DB is 12 GB and shared with the live lane: every read is `file:…?mode=ro` + `PRAGMA query_only=1`.
`prisma/dev.db` inside a worktree is a 0-byte stub, so the script resolves the populated primary-tree file
and prints which one it used.

## The one-paragraph version

STANDARD books `entryPrice = currentPrice` with p(fill) = 1. The card priced "1c better entry" at
**+$1,439.33 = 5.0% of the 90d notional = 62% of the 90d profit**. Measured on the lane's own stamped legs,
the attainable entry is **+0.50c WORSE** than the booked price at the median (**+1.04c at the mean**), on
235 settled legs with book evidence. Re-booking every one of those legs at the entry a taker could actually
have lifted sends the 90d ROI from **+17.8% to +13.6% = −4.13pp**. The rec's arithmetic is right and its
sign is wrong: the same 1c, applied better, is worth +5.1% of notional on this population — but the entry we
book is not better than the market, it is **half a cent optimistic**. And the profit the cent was supposed
to be 62% of is not STANDARD's: the lane's own 90d completed book is **−$1,049.91 (−1.8%)**, and since the
L2 epoch it is **−$1,238 (−8.1%)**.

## What was measured, in the card's own terms

Clause 1 of the decision rule — *"the resolver-stamped entry is worse than the booked mid by a median >=0.5c"*
— on `delta = attainable ask − booked price`, in cents, **positive = we would have paid more**:

| arm (settled legs with book evidence) | n | mean | median | p10 | p90 | at-or-better | ≥ +1c worse |
|---|---|---|---|---|---|---|---|
| taker: first snapshot after the decision | 235 | +1.04c | **+0.50c** | 0.00c | +2.00c | 11% | 36% |
| taker, first snapshot within 60s | 149 | +0.84c | **+0.50c** | +0.05c | +1.50c | 9% | 36% |
| hour-min 30–60m (hindsight) | 235 | −0.45c | +0.50c | −1.50c | +1.50c | 30% | 25% |

The booth's own 251-leg read agrees (first-snapshot median +0.50c, mean +1.03c, ≥+1c share 38% with the
open legs included) — two independent passes, same answer. Only **6%** of settled legs land within ±0.3c of
the booked price: the distribution sits on the tick grid (+0.5c / +1.0c), which is exactly why the median
lands on the 0.5c threshold rather than near zero. The mean is heavier than the median because of a thin
tail (−23.5c to +25c on markets that repriced); the median is what the card asks for and it sits **on the
threshold in every cut**.

*One arithmetic note that changes a share by 4 points*: `(0.11 − 0.10) × 100` evaluates to
`0.9999999999999996` in binary float, so a tick-exact 1.00c delta is excluded from "≥ +1c worse" unless the
cents are rounded before comparing — 8 of these 235 legs flip on that noise (32% vs 36%). The script rounds
to 4dp first; the 36% is the correct count.

Clause 2 — *"the re-booked 90d ROI falls >= 1.0pp"* — re-booking each leg at `entry' = max(0.01, ask)` and
keeping its own exit price (`exit = entry × (1 + pnl/size)`, so a total loss stays a total loss and only
winners shrink):

| arm / era | n | notional | booked | re-booked | Δpp |
|---|---|---|---|---|---|
| taker, all stamped | 235 | $4,185 | +$743.06 (17.8%) | +$570.36 (13.6%) | **−4.13** |
| taker, first snapshot ≤60s | 149 | $2,644 | +$949 (35.9%) | +$807 (30.5%) | **−5.39** |
| taker, W39+ (coverage complete) | 162 | $2,871 | +$471 (16.4%) | +$412 (14.3%) | **−2.07** |
| taker, W41+ (last 4 weeks) | 116 | $2,043 | +$394 (19.3%) | +$348 (17.0%) | **−2.25** |
| hour-min 30–60m (hindsight) | 235 | $4,185 | +$743.06 (17.8%) | +$1,281 (30.6%) | +12.86 |

Both clauses clear on every era cut; the magnitude is 2.1–4.1pp. This is not a knife-edge result.

The rec's counterfactual, recomputed on the same population for an apples-to-apples check: 1c better on
every leg → +$957 (22.9%) vs +$743 booked = **+5.1% of notional**, which is the rec's 5.0% (90d book) /
5.3% (today's all-lane 90d resolved book, reproduced in the same run at $1,542.63 on $29,145). The formula
reproduces; only the sign of the realisable move was never checked.

**The hour-min row is a trap, not a target.** Taking the window's best ask looks like an improvement
(+12.86pp) precisely because it buys collapsing markets 30 minutes after the decision — that is hindsight
wearing a price. Any implementation that books "the best price we saw" would manufacture profit. The
booking price must be the first observable ask, and nothing later.

## The volume half, which the card did not price

The C-200 precedent was p(fill) — a leg that never filled is not a small loss, it is not a position. Same
resolver, mode `none` (level = the booked price) on the same 235 settled legs: **71 reachable (30%)**;
booked +$743.06 → fill-aware **+$528.04 = −5.14pp**. So on this lane the *price* half is the larger
misspecification (−4.1pp) and the *volume* half is the smaller one (−5.1pp, i.e. comparable). Unresolved
legs (no book window) book exactly as before in both halves — never as "did not fill".

## Reality checks

1. **The card's profit denominator is the wrong lane.** STANDARD's 90d *completed* book, all statuses:
   4,445 legs / $58,569 / **−$1,049.91 (−1.8%)** — resolved 1,337 / $21,433 / −$872.42; early-closed
   3,108 / $37,136 / −$177.49. Since the L2 epoch (2026-08-31): 855 legs / $15,345 / **−$1,238 (−8.1%)**.
   The card's "$2,329.01 = +8.1% over 90d" is the **all-lane, resolved-only** book (today: $29,145 →
   +$3,549.25, and BANKROLL_200 alone contributes +$4,421 of it). "1c = 62% of the 90d profit" is a true
   statement about C-200's profit and a false one about the lane this card would re-book.
2. **The gate is short by population, not by time — and coverage is no longer the constraint.** 235 settled
   stamped legs vs 300. The booth's 29% coverage is a historical average: week-by-week book coverage is
   5% / 0% / 32% / 69% / 100% / 100% / 100% / 100% / 100% for W36→W44, i.e. **every in-scope leg since
   W40 carries a book stamp**. The constraint is the lane's own (shrunk) volume: ~25–30 settled stamped
   legs/week ≈ 4/day → 65 more legs ≈ **16 days, ~2026-11-14**.
3. **The refutation clause as written is not decidable.** "Stamped fills within ±0.3c of *the mid*" — of
   *which* mid? Against the mid at the attaining snapshot the booth reads mean +0.20c (68% within ±0.3c);
   against the **booked price**, which IS the decision mid and is the number the P&L was computed from,
   it reads mean +1.04c. Same legs, opposite verdict. The decision-relevant basis is the booked price: a
   mid that moved after the decision is a market move, not an entry cost. Pre-register it that way or the
   test can be fired either way at will.
4. **Coverage of the instrument is honest but thin**: evidence on 29% of in-scope legs overall; cover lag
   median 9.9s but p90 428s (max 53min), so "first snapshot" on 37% of legs is not the decision-time book —
   that is what the ≤60s cut is for, and it gives the same median (+0.50c) with a smaller n (149).
5. **A re-book is not restated history.** `bookedPnl()` sits in `updatePaperTradePrice` / `resolvePaperTrade`,
   so any flip applies to legs settling *after* the change; already-settled rows keep their booked entry
   unless a migration restates them. Any before/after figure must say which side of the cut it is on.

## What is being proposed

**Recommendation: HOLD to the gate, then adopt price-honest booking as a bookkeeping truth — not as an edge.**
Two of the rule's three conditions are met and the third is 65 legs away; waiting costs almost nothing
because the misstatement is *downward* (~0.5c on ~4 settled legs/day at $18 clips ≈ $2–4/week of
overstatement on the lane), so no decision is being made on an inflated number that compounds.

If it is adopted, this is what it is worth: carried onto the lane's since-L2-epoch notional ($15,345), the
measured −2.07 to −4.13pp projects to **−$318 to −$634 of P&L** (lane −$1,238 → −$1,556…−$1,872) — a
projection, not a measurement, because the evidence covers 29% of in-scope legs. The volume half projects
to −$788 more. **None of that is recoverable money**: it is a correction of what the lane claims to have
made, and after it the lane's loss is bigger, not smaller.

### Option A — adopt now

Add a nullable `PaperTrade.fillEntryPrice` / `fillEntryBasis` stamped by the existing booth turned resolver
(same shape as `fillStatus`), and reprice in `bookedPnl()` behind the existing `FILL_AWARE_BOOKING` flag:
`pnl' = size × (exit/fillEntryPrice − 1)` with `exit` implied by the stored PnL. NULL = book as before, so
an unstamped leg is never manufactured worse. Blast radius: two call sites (`updatePaperTradePrice`,
`resolvePaperTrade`) — the writers that already call `bookedPnl`. **Rollback:** `FILL_AWARE_BOOKING=0`
restores today's book byte-identically. Cost ~2h. Reported STANDARD ROI drops 2.1–4.1pp the moment it lands.
**This is the operator's decision, and it is a decision to report a smaller number.**

### Option B — hold to the pre-registered gate (recommended)

No code change now. Pre-register, in these words: *evaluate when ≥300 settled STANDARD legs carry a book
stamp opened after 2026-10-29; adopt when median(attainable ask − booked price) ≥ +0.5c AND the re-booked
ROI fall ≥ 1.0pp, measured against the BOOKED price, using the first snapshot and a ≤60s robustness cut.*
Expected fill ~2026-11-14 at current volume.

### Option C — close the card and re-rank

If the aim was profit, the measured effect is a downward re-book: the card cannot produce a dollar. The
lane-level item that can is STANDARD's own −8.1% since the epoch (−$1,238 on $15,345) — a 2–7x larger
quantity in dollars than the entry correction, and it is where the next card's effort belongs. The card's
own refutation anticipated this ("the highest-EV item then becomes capital, not execution"); the data
reaches that conclusion by a different route.

## Refutation — of *this* proposal

It is wrong, and should be dropped or reversed, if any of these holds:

1. **The forward ≥300 settled stamped legs come back with |median delta| < 0.3c** (vs the booked price).
   Then the booked entry is honest, there is nothing to re-book, and the card closes for the quarter.
2. **The re-booked ROI fall is < 1.0pp on the forward population.** Then the correction is immaterial and
   the reporting churn is not worth the risk of a restatement bug.
3. **The stamped asks are shown to be wrong on >5% of legs** (stale ladder, token-identification error,
   asset-map miss). Five of 251 stamped legs already carry an ambiguous outcome token; a systematic
   identification error would void the instrument, not just this card.
4. **The lane's since-epoch ROI turns ≥ +2% before the gate fills.** Then the entry-price question is
   dominated by whatever moved the lane and this card should be re-ranked, not executed.

## Sign-off checks (run before reporting)

```
python3 -m py_compile scripts/standard-fill-aware-rerebook.py     # OK
python3 scripts/standard-fill-aware-rerebook.py                   # numbers quoted above
```

Append-only artifact untouched; DB opened `file:…?mode=ro` + `PRAGMA query_only=1`; nothing written.
