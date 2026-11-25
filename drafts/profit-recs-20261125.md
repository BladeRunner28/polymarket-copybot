# PROFIT REVIEW — 2026-11-25

http://localhost:3013/drafts/profit-recs-20261125

**Instrument (committed with this doc):** `scripts/profit-tenor.py`, extended today with **§S24–S26**
(`--selftest` **15/15**). Re-run: `python3 scripts/profit-tenor.py` (DB `mode=ro`; venue tape cached
under `data/fill-tape-cache`; 640 legs classified in ~15 s warm). Every figure below prints from that run.
**Population:** 640 settled deduped legs / 533 markets, `ruleSetVersion ≥ 68`, 2026-10-27…11-25
(28.3 days), **$12,380 at risk**. **Cost basis = `simulatedPositionSize` = DOLLARS AT RISK**, never
size × price. Dedupe = first leg per `bot|wallet|market|outcome`. CIs = market-clustered bootstrap
(2,000 draws). Fees not netted (2–4% of notional against 5–20% effects; `profit-fee-net.py` owns that law).
**Three bases, stated once.** `booked` = the ledger as filed (p(fill)=1). `touched 1h` / `touched 5m` =
the venue's minute tape printed a MID at or below our price inside that window of dispatch (necessary,
not sufficient — queue position unmodelled). **Owned** = resolver `fillStatus='filled'` OR tape-touched
≤5 min. Everything below is labelled.

---

## The one thing

**The edge is not in the book we own — and the two pending clip rules differ only in what they leave behind.**

The ledger carries two independent stamps of whether we actually got the trade: the resolver's
`fillStatus`, and the venue's own tape. Measured against each other for the first time on the full
settled population (`§S24`):

| fillStatus | legs | $ at risk | PnL | ROI | CI (PnL) |
|---|---:|---:|---:|---:|---|
| filled | 139 | $3,162 | **−$815.1** | **−25.8%** | [−1,950, +703] |
| unfilled | 334 | $6,689 | +$343.3 | +5.1% | [−427, +1,268] |
| null | 167 | $2,529 | +$333.0 | +13.2% | [−82, +796] |

Union of the two stamps — **owned 369 legs / $7,952 / −$642.6 (−8.1%) [−2,169, +1,139]**;
**not owned 271 legs / $4,428 / +$503.7 (+11.4%) [CI +5.1, +1,117]** — the *only* class in the book
whose PnL CI excludes zero, and it is the class we never traded. A **19.5pp** ROI gap between the book
we can own and the book we merely booked.

**The honest limit, stated before anyone quotes it:** the filled/unfilled sign inversion is NOT stable
across halves (filled −51.8% → +7.1%; unfilled +10.7% → −5.5%). What is stable is (a) the stamp
disagreement itself — **142 of 640 legs (22%) have the two instruments arguing**, 58 "filled" legs the
tape never touched and 84 "unfilled" legs the tape touched within 5 minutes — and (b) the not-owned
class being the only CI-positive one. Read it as: **the booked headline is not evidence of edge; it is
evidence of an unadjudicated fill record.** Not as: "the strategy is proven negative."

That reframes the whole clip programme. Every `$/day` in the pending cards is a *delta on a book whose
fill status is 22% contested*. The right way to choose between two near-equal rules is therefore not the
delta — it is **what book survives the cut** (`§S25`).

---

## 1. The kept book decides the ranking, and it reorders yesterday's answer

`§S25` applies each rule, then prices the *surviving* book — level, ROI, ex-top-1, ex-top-3, delta:

| rule | basis | $ at risk | ROI | ex-top-1 | ex-top-3 | Δ/day |
|---|---|---:|---:|---:|---:|---:|
| nothing | booked | $12,380 | −1.1% | −5.6% | −9.7% | — |
| nothing | touched 5m | $6,759 | −10.1% | −14.1% | −18.0% | — |
| **cheap $10 (C-200)** | booked | $9,012 | **+7.5%** | +4.5% | **+1.7%** | **+28.78** |
| **cheap $10 (C-200)** | touched 1h | $6,297 | +7.2% | +2.9% | −1.1% | **+34.56** |
| **cheap $10 (C-200)** | touched 5m | $4,911 | **+9.3%** | +3.8% | −1.4% | **+40.30** |
| tenor $10 (C-200 2–24h) | booked | $9,176 | +7.9% | +1.9% | **−2.5%** | +30.43 |
| tenor $10 | touched 1h | $6,245 | +8.3% | −0.5% | **−7.0%** | +37.04 |
| tenor $10 | touched 5m | $4,809 | **+1.2%** | −4.4% | **−9.8%** | +26.30 |
| lane-wide $10 | touched 5m | $3,545 | +8.6% | +1.0% | −6.3% | +34.91 |
| both | touched 5m | $3,935 | +10.5% | +3.7% | −2.8% | +38.83 |

Three things fall out, none of which the delta tables could show:

- **Only the cheap-band rule leaves a book that is still positive after its three best legs are
  removed** (+1.7% booked) — and it is the only rule positive on ex-top-1 at every basis.
- **The tenor rule leaves the worst book of any candidate**: +1.2% at the strict basis, −9.8% ex-top-3.
  A rule whose post-rule book does not survive concentration has not fixed the book; it has moved the
  same loss to a smaller denominator. At 1h it looks like the best rule in the book (+8.3%); at 5m it is
  the worst. That fragility is the finding.
- The two are **substitutes** (confirming yesterday): shipped together the kept book is +10.5% ROI but
  +$38.83/day of delta on $3,935 — less absolute money than the cheap rule alone. Ship one.

What the cheap cut still carries at the strict basis (n≥5 cells): `1-7d / 0.60-0.80 / $15-30` −16.5%
(18 legs), `1-7d / cheap / <$15` −62.4% (6), `2-24h / 0.20-0.40 / <$15` −5.4% (69 legs, the largest
residual block). The tenor cut instead leaves `2-24h / cheap / <$15` at **−50.4%** on 26 legs — it caps
the big cheap clips and leaves the small ones, which is the opposite of where that cell's loss lives.

## 2. Window-scoping prices a cell, not a book

`§S24` **tail**: the reason yesterday's ranking inverted is structural. A tenor-scoped cap reaches 55
legs inside one clock; a cheap-scoped cap reaches 46 clips across all clocks. Both deltas land in the
same $26–40/day band, so the delta cannot separate them — but the tenor cut leaves the cheap small-clip
block untouched (`2-24h cheap <$15`, −50.4%) while the cheap cut leaves the `1-7d 0.60-0.80 $15-30`
block (−16.5%, 18 legs) and the `2-24h 0.20-0.40 <$15` block (−5.4%, 69 legs). The second set of
residuals is smaller in dollars and already near break-even; the first is not.

## 3. The ladder: on the owned book there is nothing to scale

`§S26`. Rolling-7d settlement sums, booked vs owned (advance policy v2 = $1,750 per 7-day window):

| window end | booked 7d | owned 7d | ratio |
|---|---:|---:|---:|
| 2026-11-21 | −$584.05 | −$546.06 | 0.93 |
| 2026-11-22 | −$425.72 | −$387.73 | 0.91 |
| 2026-11-23 | −$192.30 | −$191.04 | 0.99 |
| 2026-11-24 | +$24.31 | −$8.21 | −0.34 |
| 2026-11-25 | +$138.04 | +$114.52 | 0.83 |

**Important negative result:** the ladder is *not* currently being advanced on fiction — owned tracks
booked at 0.83–0.99 on the recent windows, so re-basing the gate would not have changed any decision.
I checked because R1's reasoning implied it should; it does not. The distortion is in the cumulative
ROI sign, not in the weekly sum.

What does hold: **book PnL/day booked −$4.90, owned −$22.69**, and at the owned ROI (−8.1%) rung 1 is
**unreachable by sizing at any flow** — 250/(−0.081) has no positive solution. Owned flow is $281/day
of risk. Every sizing card on the board, including the two ranked here, is worth $25–40/day against a
$250/day rung. That is not a criticism of the cards; it is the arithmetic of scaling a book whose
ownable ROI is negative.

---

# Recommendations, ranked by expected value

### R1 — Ship the approved cheap-band field at **$10** now, alone. **+$28.78/day booked, +$40.30/day at the strict basis. 0.5h. Lane A.**

- **Hypothesis.** Capping C-200 Kelly clips at $10 in 0.0–0.20 leaves a book that is still profitable
  after its best three legs are removed, whereas the tenor-scoped alternative does not — so on the
  criterion the ladder is actually paid on (post-rule ROI, concentration-removed), the cheap rule is the
  one to ship first.
- **Measurement.** `scripts/profit-tenor.py` §S25 (committed today), scope
  `bot=BANKROLL_200 AND not stair AND px<0.20 AND ntl>10` — i.e. exactly the `c200BandClipCaps` field.
  Kept book: **booked +7.5% ROI ($9,012) / +1.7% ex-top-3; touched-1h +7.2% / −1.1% ex-top-3;
  touched-5m +9.3% / −1.4% ex-top-3.** Delta **+$814 booked (+$28.78/day)**, **+$978 (+$34.56/day)** at
  1h, **+$1,140 (+$40.30/day)** at 5m. Against the tenor rule on all six measures it wins four (5m delta,
  5m ROI by 8.1pp, ex-top-3 at every basis) and loses two by ~$2/day (booked and 1h delta).
- **Decision rule.** Set the constant in the already-written `scripts/apply-v73-c200-cheap-band-clip.ts`
  from `"0.0-0.2:25"` to **`"0.0-0.2:10"`** and run `apply-v73 --yes` (the field, reader and apply script
  exist and have never run; 13 days approved). Boundary probe at px 0.1999/0.2000/0.2001 × clip
  9.99/10.00/10.01, plus one live cycle proving a $100 0.18 leg books $10 and a $100 0.22 leg books $100.
  **Do not ship the tenor field in the same window** (measured substitutes).
- **Refutation.** Forward 40 settled cheap-band legs clipped at $10 whose tape-touch ROI is **< 0**, or
  whose kept book is **< −5% ex-top-3**, or the $10-capped book trailing a $25-capped shadow by **≥ $100
  with a CI excluding zero** over 30 days → set the field back to `""` (byte-identical to pre-v73).

### R2 — Keep the tenor card but demote it to second, and re-specify its refutation. **+$30.43/day booked / +$26.30 at 5m if it later ships. 0h today. Lane A (no build yet).**

- **Hypothesis.** The tenor cap's value is real on the ledger but not on the kept book: it removes the
  big main-path same-day clips and leaves the small cheap same-day clips untouched, so it should not be
  built until the cheap rule has run and the residual cell is re-measured.
- **Measurement.** `§S25` tenor row: post-rule **+1.2% at touched-5m, −9.8% ex-top-3** (vs the cheap
  rule's +9.3% / −1.4%); `§S24` tail: the block it leaves behind is `2-24h cheap <$15`, **−50.4% on 26
  legs**. Card `profit-mainpath-short-tenor-clip` continues to assert it is first; on this instrument it
  is second.
- **Decision rule.** Build `mainPathShortTtrClipUsd=10` only after the cheap rule has **7 days** of
  forward data **and** the residual `2-24h main-path clip ≥ $60` cell is still negative on the
  tape-touch basis (≥ 20 forward legs). Re-read: `python3 scripts/profit-tenor.py | sed -n '/S24/,/S26/p'`.
- **Refutation.** If, after the cheap rule, the main-path 2–24h cell's forward tape-touch ROI is **≥ 0**
  on 20+ legs, the tenor cell was a proxy for the cheap cell all along — withdraw the card instead of
  building it.

### R3 — Adjudicate the 22% fill-stamp disagreement before any further sizing card is priced. **$0 direct; protects every future measurement. 1–2h. Lane B.**

- **Hypothesis.** The resolver's `fillStatus` and the venue tape disagree on 142 of 640 legs (58 filled
  legs never touched; 84 unfilled legs touched within 5 minutes), so booked PnL — the basis of every
  card — carries a 22% mislabelled population.
- **Measurement.** `§S24` 2×3 stamp matrix (filled 80 touched / 58 never / 1 no tape; unfilled
  84 / 250 / 0; null 146 / 20 / 1) and the class ROIs above.
- **Decision rule.** Re-derive `fillStatus` from the tape where the tape has a series (touch ≤ 5 min at
  our price ⇒ filled, no touch ≤ 1 h ⇒ unfilled), keep the resolver stamp as a second column, and gate
  the repair on **≥ 95% agreement on a 200-leg replay** with zero changes to any `realizedPnl`.
- **Refutation.** If, on a 200-leg replay, resolver and tape agree on **≥ 95%** (i.e. today's 78% is a
  stale-stamp artefact confined to older legs), no repair is needed — report the stamp as reliable and
  move on.

---

**IF YOU WERE NOT HERE:** I would run `apply-v73 --yes` with the constant set to `0.0-0.2:10` today.
Zero new code, the field defaults to empty so the revert is byte-identical, and it is the only pending
rule whose kept book survives removing its own best legs (+1.7% ex-top-3 booked, +7.5% overall).

**Lane policy:** Lane B only today — one instrument extended (§S24–S26), nothing applied, no RuleSet
read/write, DB `mode=ro`, no prisma write. R1 and R2 change what the bot risks: **Lane A proposals,
the operator's call.** R3 is an instrument repair I may perform directly.

---

## Corrections and contradictions carried forward

1. **Yesterday's ranking was on delta; today's is on the kept book.** I ranked the tenor card first
   because its delta CI excludes zero on all three bases, which remains true (+$30.43 / +$37.04 /
   +$26.30 per day). But the book it leaves behind is +1.2% at the strict basis and −9.8% ex-top-3,
   against the cheap rule's +9.3% / −1.4%. A delta CI prices the legs you cut; the ladder pays on the
   legs you keep. Ranking corrected; the numbers behind both are in one table now.
2. **The measured baseline's "0.4–0.6 is the only CI-negative band … carded as a Lane A proposal" is
   stale in a way that matters**: 0.4–0.6 is not a pending card, it is **v63, live since 2026-10-20**
   (`standardSkipBandRange = "0.4-0.6"`). In the v68+ window the band holds **2 legs** (both C-200) and
   **zero STANDARD legs**, which is the rule working, not the band disappearing. Deduped all-time
   STANDARD 0.4–0.6 reproduces the premise at **−5.78% on 1,203 legs / $15,780** (−$912.7); the
   non-deduped cut reads **+9.1% on 3,741 legs / $47,063** — the 3× duplicate inflation is entirely in
   the duplicated tail. Do not re-card this; do not quote the +9.1%.
3. **The adverse-selection story is not stable enough to build on.** `§S24` halves: filled −51.8% →
   +7.1%, unfilled +10.7% → −5.5%. I am reporting the sign gap because the *union* split (owned −8.1%
   vs not-owned +11.4%, CI excluding zero on the not-owned side) is robust across the halves even when
   the resolver classes are not. Anyone who quotes "our fills are adversely selected, therefore the
   strategy is negative" is quoting the unstable half.
4. **The ladder is not being advanced on fiction** — checked and refuted (owned/booked ratio 0.83–0.99
   on recent windows). I expected otherwise and said so before checking; the finding is the negative.
5. Unchanged and still true: the two caps are substitutes; the lane-wide $25 card stays falsified; the
   `$15–30` clip tier upsize stays refused (ex-top-10 −11.7%); per-event capping stays a null.
6. Open, unchanged: the `null` resolver class is 92.2% tape-touched at 1h, so it is probably a fill
   class with no stamp rather than a phantom class — R3's gate is what resolves it.

## Reproduce

```bash
python3 scripts/profit-tenor.py --selftest          # 15/15
python3 scripts/profit-tenor.py | sed -n '/S24/,/S26/p'
grep -rn c200BandClipCaps src/                      # (nothing) — field still has no reader
grep -c '"0.0-0.2:25"' scripts/apply-v73-c200-cheap-band-clip.ts   # the constant R1 changes
```
