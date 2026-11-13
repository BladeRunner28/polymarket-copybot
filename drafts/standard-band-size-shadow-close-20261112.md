# STANDARD band size factor — CLOSED: the clip is real, and lifting it does not make the map measurable

**Card:** `standard-band-size-shadow` · approval `apr-standard-band-size-shadow` (lane A, operator
clicked approve 2026-11-12T16:27:44Z) · kanban `t_9ffff566`
**Status: PROPOSED, NOTHING APPLIED.** No `apply-v*.ts` run, no write to `prisma/dev.db`
(every read is `?mode=ro` + `PRAGMA query_only`), no merge to main. RuleSet still **v72**.
**Branch picked from the approved either/or:** the card's own recommendation was *close or amend*;
this takes **CLOSE** (the recommended branch) and prices AMEND in §7 so it is one line to override.
**Instruments:** `scripts/profit-velocity.py` §AM.7 (unchanged, re-run today) +
`scripts/standard-band-clip-headroom.py` §B.1–B.5 (new, read-only, in the working tree beside this
write-up — this run does not commit or merge; the 22:30 nightly backup does).
Draft served at `http://localhost:3013/drafts/standard-band-size-shadow-close-20261112`.

---

## 0. Why this card came back at all

The 10-29 recut wrote its verdict into the card's `note` and left the card in **Backlog** with the
`awaiting-approval` tag and **no closure stamp**. `scripts/approvals-intake.py` drops a pending-tagged
card only when `closure_evidence()` finds a *stamp* — a tag prefix-matching `closed/done/shipped/...`
or a note segment that opens with `APPLIED|DONE 2026|CLOSED 2026|REFUTED|WITHDRAWN`. A recommendation
sitting in prose is therefore still a pending decision, so nine days later the queue handed the
operator "close or amend" as if it were unexamined — the same mechanism that revived
`lane-scoped-band-factors` (dropped only once it carried `shipped-v71`). This run closes the loop
structurally: the card is **Done**, the note carries the verdict block, and it now carries
`closed-2026-11-12`, verified by importing the intake's own `closure_evidence()` **before and after**
(today: `tag:closed-2026-11-12` → DROPPED; before the tag: `closure=-` → QUEUED).

---

## 1. Verdict

The card's title is **true on the live book** and it still does not justify a shadow. Measured today,
`STANDARD`'s cluster of `$18.00` clips means a ×2.0 band factor buys **+11.1%**, not +100% — but the
cap is a *symptom*, not the binding constraint:

1. **The clip is real and now quantified.** Live era (≥2026-09-15, below the live 0.85 ceiling):
   300 legs, median booked size **$18.00 in all four populated bands**, and the median multiplier a
   ×2.0 factor actually gets is **1.111 in every band**. All-time, where the median clip was
   $9.80–$11.40, the same factor really did get 1.75–2.00× — which is exactly why the old CI
   excluded zero.
2. **Lifting the cap does not rescue it — this is the new, decisive measurement.** The 10-29 recut
   named "a STANDARD base-size change that lifts the cheap band above $20" as the clause that would
   refute its own close. Priced today: at a **$40 cap** (6× the headroom actually used; equivalent to
   no cap, since no base size exceeds $40 after any map) the live-era strong map is **+$638
   [−$235, +$1,643]** and cheap-only is **+$499 [−$291, +$1,458]** — both still span zero. The
   refutation does not fire.
3. **The card's own ship rule is 269–369 days away.** Live-era cadence is 5.13 legs/day (cheap band
   0.91/day). A market-clustered CI excluding zero needs **1,239 markets ≈ 269 days** for the cheap
   arm and **1,700 ≈ 369 days** for the five-band map — at an effect of $0.30–$0.39 per market. The
   card's `≥150 forward legs` gate is ~29 days of flow but only ~165 days of *cheap-band* flow, and
   its second condition (ex-top-10 ROI +3pp) **fails in two of three windows** (90d −7.0% → −8.7%,
   live −9.6% → −15.5%).
4. **The one interval that excludes zero is all-time cheap-band, and it dies on trim.**
   +$3,920 [+$334, +$8,416] becomes **+$3,494 [−$92, +$7,904]** after dropping three legs. Live-era
   cheap-only is **−$42** after dropping three legs.

**Recommendation: close.** Record the reopen trigger as the *live-era cheap band's market-clustered
ROI CI excluding zero at ≥150 cheap-band legs* (today: 53 legs, +58.9%, CI **[−36.7, +174.9]**), and
**not** "the cap rises" — that condition is now measured insufficient.

---

## 2. Basis, so the numbers mean something

| item | value |
| --- | --- |
| population | `STANDARD`, `status IN (closed,resolved)`, `isDemo=0`, `realizedPnl IS NOT NULL`, `entryPrice>0` |
| filters | entry below the live `standardMaxEntryPrice=0.85`; net of the live `standardSkipBandRange="0.4-0.6"` |
| cost basis | `simulatedPositionSize` = **dollars at risk** (never shares, never × price) |
| PnL | stored `realizedPnl`, scaled linearly by the booked-size ratio (fixed entry/exit ⇒ PnL ∝ $ at risk) |
| CI | market-clustered paired bootstrap, 2,000 reps, seed 11 |
| dedupe | **none** — matches §AM.7's population, so the figures are comparable to the card's own instrument |
| live ruleset | v72 · `deadZoneSizeFactor=1` · `longshotSizeFactor=1` · `sweetSpotSizeUsd=18` · `kellyEnabled=1` (C-200 only) |

Reachable book today:

| window | legs | $ at risk | flat PnL | ROI | ex-top-10 ROI |
| --- | --- | --- | --- | --- | --- |
| all-time | 3,864 | $45,930 | **+$5,949.53** | +13.0% | +9.0% |
| 90d | 1,311 | $19,706 | **+$381.47** | +1.9% | −7.0% |
| live era ≥ 2026-09-15 | 300 | $4,841 | **+$754.03** | +15.6% | −9.6% |

§AM.7 prints 6,273 all-time legs / $68,208 / +$5,034 for the unceiling'd book, and 310 live-era legs
net of the skip; the 10 extra live-era legs sit above the 0.85 gate and are excluded here, as are the
2,399 all-time legs above it (the card's own instruction: do not quote that arm).

---

## 3. Finding 1 — the clip, quantified (B.1)

Median multiplier the factor **actually** gets through `clampPaperSize` (`src/lib/safety.ts:45`,
`BOT_LIMITS.STANDARD = {0.25, 20.00}`, applied at `src/lib/paper.ts:198`, i.e. **after** every factor):

| window | band | legs | med $ | p90 $ | ×2.0 effective | ×1.5 effective | ×0.5 effective |
| --- | --- | --- | --- | --- | --- | --- | --- |
| live era | <0.20 | 53 | 18.00 | 18.00 | **1.111** | 1.111 | 0.500 |
| live era | 0.2–0.4 | 98 | 18.00 | 20.00 | **1.111** | 1.111 | 0.500 |
| live era | 0.6–0.8 | 127 | 18.00 | 18.00 | **1.111** | 1.111 | 0.500 |
| live era | 0.80–0.85 | 22 | 18.00 | 20.00 | **1.111** | 1.111 | 0.500 |
| 90d | <0.20 / 0.2–0.4 / 0.6–0.8 | 222 / 400 / 555 | 18.00 | 18.00 | 1.111 | 1.111 | 0.500 |
| all-time | <0.20 | 548 | 10.00 | 18.00 | **2.000** | 1.500 | 0.500 |
| all-time | 0.2–0.4 | 1,281 | 11.40 | 18.00 | **1.754** | 1.500 | 0.500 |
| all-time | 0.6–0.8 | 1,740 | 11.00 | 18.00 | **1.818** | 1.500 | 0.500 |

Modal booked sizes say the same thing in one line: **live era $18.00 (69.3%) / $9.00 (21.3%) /
$20.00 (8.3%)**; 90d $18.00 (51.8%); all-time $18.00 (17.6%) / $8.00 (14.7%).

Two consequences the card states and one it does not:

- Any up-factor ≥ 1.112 books $20 from $18. The map's 2.0 and 1.5 are the **same trade** live — the
  down-weights are the only part that expresses, and they are a de-risking, not a reallocation.
- The 0.4–0.6 band is hard-skipped live (`standardSkipBandRange`), so the map's middle factor (0.5)
  is dead code on this lane. Four populated bands, not five.
- **Not stated by the card:** the $9.00 mode (21.3% of live legs) is the v68 maturity bucket
  (`0.5 × $18` for <24h TTR), and there a ×2.0 **does** express fully. So the factor is not 100%
  inexpressible — it is inexpressible precisely where the band evidence lives, and expressible only
  in the bucket v68 already halves because <24h returns −8.6%/−6.5%. Up-weighting the cheap band
  inside a bucket de-weighted for negative edge is a contradiction, not an amendment.

---

## 4. Finding 2 — lifting the cap does not rescue it (B.3)

The 10-29 recut's own refutation clause: *"a STANDARD base-size change that lifts the cheap band
above $20 (removing the clamp) would make the five-band map testable again."* Tested directly by
re-running the same arms with `BOT_LIMITS.STANDARD.max` raised in the shadow only:

**live era (300 legs, $4,841):**

| cap | strong map ΔPnL | CI | cheap-only ΔPnL | CI |
| --- | --- | --- | --- | --- |
| $20 (live) | +$104 | [−$157, +$367] | +$82 | [−$78, +$270] |
| $30 | +$481 | [−$153, +$1,210] | +$341 | [−$204, +$992] |
| $40 | +$638 | **[−$235, +$1,643]** | +$499 | **[−$291, +$1,458]** |
| $60 | same as $40 (no base size exceeds $40) | | same | |

The delta grows 6× and **the interval still spans zero**. Halving the cap's bite does not convert a
per-market effect of $0.30–$0.39 into a measurable one; it only means each leg risks more to chase it.
Same shape in the 90d window ($1,439 [−$1,127, +$4,518] strong at cap $40). All-time is the exception
— cheap-only at cap $40 is +$4,832 [+$330, +$10,082] — but that arm lives on 2026-08/09 legs booked at
$8–$10 and already excludes zero at the live cap. It is the same $10-clip-era evidence, re-weighted.

**So the card's premise is correct and its remedy is void:** the $20 clip is why *this* MAP cannot
express itself, and removing the clip does not make the map work. The band edge is not established at
live sizes at all; the clip merely hides that.

---

## 5. Finding 3 — the bookable arms, with dominance (B.2)

As-is = what would actually book (no post-clamp renormalisation; the 10-29 draft already showed the
"notional-neutral" arm pushes 886 of 3,731 legs back through the cap and is unbookable):

| window | arm | notional | ΔPnL | CI | ex-top-10 ROI (base → arm) | after dropping top-3 Δ legs | its CI |
| --- | --- | --- | --- | --- | --- | --- | --- |
| all-time | strong 2/1.5/.5/.4/.2 | $40,490 | **+$3,570** | [−598, +8,482] | +9.0% → +16.8% | +$3,144 | [−954, +7,929] |
| all-time | cheap-only ×2.0 | $49,706 | **+$3,920** | **[+334, +8,416]** | +9.0% → +14.4% | +$3,494 | **[−92, +7,904]** |
| 90d | strong | $15,301 | +$643 | [−451, +1,917] | −7.0% → **−8.7%** | +$225 | [−722, +1,410] |
| 90d | cheap-only | $20,692 | +$599 | [−210, +1,560] | −7.0% → **−6.7%** | +$180 | [−469, +1,083] |
| live | strong | $3,724 | +$104 | [−157, +367] | −9.6% → **−15.5%** | **−$19** | [−229, +209] |
| live | cheap-only | $5,022 | +$82 | [−78, +270] | −9.6% → **−11.8%** | **−$42** | [−135, +72] |

Read it as three lines: (i) the only interval that excludes zero at all is all-time cheap-only, and it
is three legs deep; (ii) the card's second ship condition — "ex-top-10 ROI +3pp" — holds in the
all-time window and **fails in the 90d and live windows**, which is the pre-registered refutation the
card attached to itself; (iii) live-era, the trimmed delta is *negative* on both arms. Adding capital
to the cheap band is right in sign and still unmeasured in size; it is a bet on May–September 2026
transferring forward, and the 90d window already says it does not.

---

## 6. Finding 4 — the ship rule cannot fire (B.4)

| window | legs/day | markets/day | cheap legs/day | cheap arm: markets for a CI excl. zero | at this cadence |
| --- | --- | --- | --- | --- | --- |
| all-time | 32.2 | 11.6 | 4.57 | 1,550 | 134 days |
| 90d | 14.6 | 7.8 | 2.47 | 1,640 | 210 days |
| live era | 5.13 | 4.60 | 0.91 | **1,239** | **269 days** |
| live era | — | — | — | strong map: 1,700 | 369 days |

At the live-era effect ($0.30/market cheap, $0.39 strong), the card's `≥150 forward shadowed legs`
gate is reached in ~29 days of any-band flow but only ~165 days of cheap-band flow — and at 150 legs
the CI half-width is ±$177 against a $82 delta, i.e. the window closes with "not met" by
construction. A shadow whose own decision rule cannot fire inside its horizon is a delay, not a test.

---

## 7. The amend branch — priced, refused, and one line to override

If the operator would rather keep the question alive, this is the whole of it, and it is **cheaper
than the 10-29 draft thought**: `src/lib/band-size.ts::applyBandSizeFactor(size, price, factor, range)`
already exists (shipped 2026-09-20 for C-200, boundary semantics `lo ≤ px < hi`, no clamp) and is
already imported by `scripts/score-trades.ts:19`. The pair of rules fields it reads
(`c200BandSizeFactor` / `c200BandSizeFactorRange`, `src/lib/rules.ts`) is the template. **No new
module is needed** — the 10-29 §Implementation proposed one because it did not check that the
primitive had shipped.

- `src/lib/rules.ts`: `standardBandSizeFactor: number` (default **1** = inert),
  `standardBandSizeFactorRange: string` (default **""** = inert). Both defaults inert ⇒ byte-identical
  legacy behaviour; revert is one field.
- `src/lib/paper.ts`: inside the existing `botId !== "BANKROLL_200"` branch, after
  `applyMaturitySizeFactor` and **before** `clampPaperSize` (the clamp stays downstream, as v68's
  comment requires). Reuse `applyBandSizeFactor` — do not re-arm `deadZoneSizeFactor` /
  `longshotSizeFactor`, which are shared with C-200 and were neutralised at v41 on purpose.
- Tests: inert on empty range and factor 1; 0.199/0.200 boundary; clamp still applied after the
  factor; `BANKROLL_200` unchanged.

**But it should not ship on this evidence.** Arm = `<0.20` only, factor 2.0, clamp untouched. The one
interval that excludes zero (all-time +$3,920) loses it at trim (−$92/+$7,904) and the live window
needs 269 days. A default-off factor that has never been measured live is a permanent piece of
sizing surface for an effect we cannot estimate.

**Pre-registered rule if the operator overrides to AMEND** (take this text, do not re-derive it):

- **Sample:** ≥150 forward **cheap-band** legs (`<0.20`, below the 0.85 ceiling), ~165 days at 0.91/day.
- **Statistic:** as-is (bookable) delta, market-clustered bootstrap, **after dropping the top 3
  delta-contributing legs**; reported beside the trimmed CI, never alone.
- **Ship only if** the trimmed CI excludes zero **and** the cheap band's clustered ROI stays above
  +10% (the fillability break-even is 6.1¢/share) **and** the inverse control (×2.0 on 0.80–0.85)
  does not match it.
- **Refutation (revert at once if any):** trimmed CI includes zero at ≥150 cheap-band legs; the
  inverse control matches or beats the arm; cheap-band clustered ROI < +10%; cheap-band cadence falls
  below 0.5 legs/day (sample unreachable — currently 0.91).

---

## 8. What closes, and what reopens it

**Close `standard-band-size-shadow`.** Grounds, in one line each: the map's up-factors are the same
trade live (median 1.111× at a $18 clip); the cap-lift the card named as its own refutation is now
measured insufficient (live era still spans zero at a $40 cap); the ship rule needs 269–369 days at
the measured effect; the ex-top-10 condition fails in 2 of 3 windows; and the only excluding-zero
interval is all-time cheap-band at three legs of depth.

**Reopen trigger (recorded on the card):** the live-era cheap band's market-clustered ROI CI excludes
zero at **≥150 cheap-band legs**. Today: 53 legs, +58.9%, CI **[−36.7%, +174.9%]** on 49 markets, 0.91
legs/day. **Not** the cap: §4 prices that condition and it is insufficient.

**Band ROI context (B.5, clustered, reachable book):**

| window | <0.20 | 0.2–0.4 | 0.6–0.8 | 0.80–0.85 |
| --- | --- | --- | --- | --- |
| all-time | +75.8% **[+8.2,+153.9]** | +2.6% [−18.3,+24.9] | +3.1% [−6.1,+11.5] | +2.2% [−7.0,+10.4] |
| 90d | +39.5% [−26.8,+119.8] | −6.5% [−38.7,+36.4] | −6.6% [−20.2,+7.0] | +1.2% [−9.5,+10.4] |
| live era | +58.9% **[−36.7,+174.9]** | +17.4% [−15.7,+49.9] | −2.4% [−16.3,+10.4] | +8.9% [−14.6,+21.7] |

The cheap band is the only cell whose all-time interval excludes zero, and its live interval is 212pp
wide. That is the honest state of the question — and it is a **fillability/admission** question this
card does not own: `profit-band-clip-rebalance` (C-200 $25 cheap cap) and the 11-11 profit review
already carry the cheap-band allocation thread. Nothing here is lost by closing.

---

## 9. Reproduce

```
cd ~/polymarket-copybot
python3 scripts/profit-velocity.py --only-am              # §AM.7, 13.9s, read-only
python3 scripts/standard-band-clip-headroom.py            # §B.1-B.5, 0.6s, read-only
```

Both open `prisma/dev.db` read-only; §B executes `PRAGMA query_only=1` as well.

---

## 10. Verified

- `python3 scripts/standard-band-clip-headroom.py` → **exit 0**, 101 lines, 0.59s (output captured at
  `~/.hermes/cache/scratch/am7b_full_20261112.txt`).
- `python3 scripts/profit-velocity.py --only-am` → **exit 0**, 13.9s; §AM.7 reproduced this run's
  flat/live and ex-top-10 baselines to the tenth of a point (+13.0/+9.0, +1.9/−7.0, +15.6/−9.6).
- `python3 -m py_compile scripts/standard-band-clip-headroom.py` → **exit 0**.
- No `apply-v*.ts` executed. No write to `prisma/dev.db`. RuleSet still **v72**
  (`deadZoneSizeFactor=1`, `longshotSizeFactor=1`, `sweetSpotSizeUsd=18`).
- No TypeScript changed, so `tsc`/`vitest` were not re-run; §7's implementation is unshipped design.
- Roadmap card `standard-band-size-shadow`: **column Backlog → Done**, verdict block appended to
  `note`, `dates` records the closure, tag `closed-2026-11-12` added. Verified by re-loading the JSON
  (278 cards, every other card byte-equal) and by importing `scripts/approvals-intake.py`'s own
  `closure_evidence()`: before the tag it returned `''` → QUEUED; after, `tag:closed-2026-11-12` →
  DROPPED. Edit is text-level (a `json.dump` round-trip is **not** byte-identical to the file on disk,
  so re-serialising would churn a 1 MB file other sessions write).
- Dashboard: `http://localhost:3013/drafts/standard-band-size-shadow-close-20261112` → **200**, body
  contains the verdict heading.
- Nothing merged. Branch picked: **CLOSE** (recommended branch of the approved either/or);
  AMEND priced in §7 and overridable on one line.
