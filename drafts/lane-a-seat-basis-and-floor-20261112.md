# Lane A — the ROI basis, and whether a settled-record floor can separate this wallet

Card: `t_b98c4591` (Lane A — **proposals only; nothing here is applied**). Parent measurement:
`t_6d17488d` → `drafts/wallet-17dd-cohort-20261112.md`. Measured 2026-11-12 ~20:25Z.
Instrument: `scripts/lane-a-seat-basis-read.py` → `data/lane-a-seat-basis-read.json`
(25 seats + 15 challenger wallets, 40 full venue CLOSED-position walks, 1,139 pages, 3,000-resample
market-clustered bootstrap). Read-only on `prisma/dev.db`; venue reads keyless (data-api v2
positions); writes only under `data/`.

---

## 0. Verdict, in the order the card asks

**(A) ROI basis — SHIP IT (as A1: full record + `michaelis` curve).** The tail sample is not biased,
it is *noise*: across the 25 seats the stored `roi30d` understates the full venue record for **19 of
25** wallets and overstates it for 5, median ratio **1.51×**. Its single catastrophic error is this
wallet — stored **+163.3% vs a full record of +17.5% (ratio 0.11×)**. Because the sample understates
most seats, repairing the basis *raises* the cut (83.4 → 83.9), so the wallet falls out on score
**even though its own score also falls** (83.9 → 68.0). The card's "still inside the cap" is an
artifact of ranking the 25 seats against *themselves*: against the challenger pool the wallet ranks
**40th of 40**. A1 turns over 8 seats, and 4 of the 8 it drops journaled nothing in the last 7 days;
`A2` (basis + `atan`, the variant that de-saturates the whole range instead of only above +100%) is
priced in §2.2–2.3 with its extra cost — it is the second option, not the default.

**(B) Settled-record floor — REFUTED AS WRITTEN; do not ship.** The rule as stated ("on ≥30
venue-settled legs, ROI's 95% CI excludes zero on the positive side") **passes this wallet**:
its venue-settled record is **+19.0% [+12.6%, +27.0%]** on 24,675 settled legs. The card's −1.47%
is the *legs we observed*, not the wallet's settled record — two different populations. Every variant
that does catch it costs most of the seat set: the best one keeps **17 of 25** seats; the rich-band
and observed-flood variants keep **1–4 of 25**. Measured reason below.

**(C) Per-wallet decision ceiling — not priced.** With (A) shipped the wallet loses its seat, so the
concentration it was going to fix disappears; and the copy-side PnL at stake is −$208/6d. No case.

**Refusal test — does not fire.** Re-cut of the same 6 days with far more than 30 extra settled legs
(4,152 vs 1,899) still reads negative: **−18.2% [−20.8%, −15.8%]** on the wallet's flood-window
positions at today's settlement. The premise survives *on that window* — but see §4: over its full
observed history at our detected mid the copy legs read **+0.7% [+0.2%, +1.3%]**, so "not profitable"
is window-specific, not a property of the wallet.

---

## 1. What "settled" means here, and why the basis choice is the whole argument

Every position below is a venue CLOSED position whose market has ended and whose token carries a
**terminal venue mark** (0 or 1 ±0.005). Two ways to price it, and they disagree in sign for this
wallet:

| Basis | What it prices | Subject result (settled legs) |
|---|---|---|
| **`realized`** — venue `realized_pnl / (size × avg_price)` | what the wallet actually booked, early exits included | **+19.0%** [+12.6, +27.0] on 24,675 legs |
| **`hold`** — `size × (settle − avg_price)` | what a copier who buys and never sells would earn | **−9.3%** [−11.7, −7.0] on the same legs |

Early exits are not a rounding error here: **14.9% of its settled cost** left the position more than a
day before the market ended. This is a dust market-maker (median position $2.18, 31,993 positions):
it earns by trading in and out, and *loses* if you hold its book. Any "is this wallet profitable"
claim must therefore name the basis, because the answer flips sign on it.

Same fork inside the band that generates our cohort (entry ≥0.95, 6,757 settled legs, $276k cost):

| Rich band (0.95–1.01), settled only | ROI | 95% CI |
|---|---|---|
| realized (wallet's own accounting) | **−5.0%** | [−6.7%, −3.1%] |
| hold-to-settlement (copier outcome) | **+0.3%** | [+0.1%, +0.5%] |

The parent card's −5.8% is the realized read and it reproduces (−5.0% on the settled subset; the
parent priced all positions in the band, settled or not). The hold read says a copier who bought that
band and held would have earned **+0.3% before fees** — i.e. zero, not −5.8%. That gap is the whole
difference between "this wallet is bad" and "this wallet is flat".

---

## 2. (A) The ROI basis

### 2.1 What the sample does to the 25 seats

`scan-wallets` scores from the adapter's profiling read: 50 best + 50 worst closed positions by
realised PnL (of 31,991) + 100 open. On this wallet that sample reproduces the stored `roi30d`
1.6333 as 1.6479. On the full record:

| Wallet | stored `roi30d` | full-record ROI | ratio | g now | g @michaelis | seat now → @michaelis |
|---|---|---|---|---|---|---|
| 0x06081d47a698 | +62.6% | +43.9% | 0.70× | 97.2 | 88.9 | 1 → 12 |
| RJW1 | +62.5% | +105.8% | 1.69× | 95.1 | 96.4 | 2 → 2 |
| 0xE156c859FC8A | +59.1% | +104.4% | 1.77× | 94.5 | 96.9 | 3 → 1 |
| Kyn008 | +74.9% | +84.7% | 1.13× | 94.2 | 91.9 | 4 → 9 |
| 0xC576775EF916 | +79.6% | +175.0% | 2.20× | 93.6 | 93.6 | 5 → 5 |
| KongX | +94.9% | +113.3% | 1.19× | 92.1 | 92.1 | 6 → 7 |
| legioncre | +50.8% | +97.0% | 1.91× | 91.6 | 96.1 | 7 → 3 |
| 0x3d5a9e66f15e | +55.2% | +162.9% | 2.95× | 91.1 | 94.7 | 8 → 4 |
| randypunt | +70.1% | +132.5% | 1.89× | 90.7 | 90.8 | 9 → 10 |
| GAMBLINGISCANC… | +49.7% | +69.2% | 1.39× | 90.2 | 90.8 | 10 → 11 |
| TheOmniussiah | +76.8% | +66.4% | 0.87× | 86.8 | 81.5 | 11 → 22 |
| GamblingAddict12345 | +136.5% | +86.0% | 0.63× | 86.5 | 84.5 | 12 → 15 |
| ThisAgain | +34.2% | +73.4% | 2.14× | 85.8 | 91.9 | 13 → 8 |
| 0x167D74FC517d | +56.5% | +56.5% | 1.00× | 85.7 | 81.8 | 14 → 21 |
| SimpleTony | +131.2% | +85.2% | 0.65× | 85.6 | 83.5 | 15 → 18 |
| M4ken168 | +33.1% | +75.1% | 2.27× | 85.4 | 92.2 | 16 → 6 |
| illenial | +63.4% | +77.3% | 1.22× | 85.4 | 82.9 | 17 → 20 |
| kjhgkltivtvriu | +35.5% | +53.6% | 1.51× | 85.4 | 87.5 | 18 → 13 |
| bitcoin9 | +66.7% | +76.7% | 1.15× | 84.9 | 81.3 | 19 → 23 |
| forecastication4 | +65.1% | +66.7% | 1.02× | 84.6 | 79.9 | 20 → 24 |
| lstpetr | +346.1% | +857.9% | 2.48× | 84.3 | 84.3 | 21 → 16 |
| DelidelaDele | +63.4% | +120.0% | 1.89× | 84.0 | 85.0 | 22 → 14 |
| JoeyAroyyOO | +65.6% | +101.9% | 1.55× | 84.0 | 84.3 | 23 → 17 |
| **luciebot (subject)** | **+163.3%** | **+17.5%** | **0.11×** | **83.9** | **68.0** | **24 → 25** |
| 0xe1C08abF3f7D | +66.3% | +145.5% | 2.19× | 83.4 | 83.5 | 25 → 19 |

Read the ratio column: the sample is **not** systematically flattering (19 understated, 5 overstated,
median 1.51×). It is a 100-row draw from a 32,000-row record whose winners were half-selected by
construction — so it carries enormous variance and no bias, and its worst draw in the current seat set
is the wallet that now defines the near-certainty cohort.

### 2.2 The saturation half

`roiScore = clamp(40 + 90·roi)` pins at 100 for any roi ≥ 0.667. Measured consequences on the 25
seats after the basis fix:

| Curve | roiScore(0.67) | roiScore(1.6) | roiScore(16) | seats pinned at 100 | median \|Δ g\| | seats moving |
|---|---|---|---|---|---|---|
| `linear_clamp` (shipped) | 100.0 | 100.0 | 100.0 | **20 / 25** | 0.5 | 24 / 25 |
| `michaelis` (40+90r/(1+r/2)) | 85.2 | 100.0 | 100.0 | 10 / 25 | 2.3 | 23 / 25 |
| `atan` (40+60·(2/π)atan(πr/2)) | 71.0 | 85.5 | 98.5 | 0 / 25 | 5.9 | 25 / 25 |

Basis-fix-only (`linear_clamp`) is **not** a repair: 20 of 25 seats land on the ceiling, so the ranking
is decided entirely by consistency and copyability — the ROI term becomes decorative. That is why the
basis fix and the de-saturation must ship together; they are one change, not two.

### 2.3 What (A) moves — seat set, ranking over the 25 seats **plus** the 15 challengers above the cut

| Variant | seats filled | cut | subject | vacated → entrants |
|---|---|---|---|---|
| today | 25 | 83.4 | **in (seat 24)** | — |
| A0 basis only (`linear_clamp`) | 25 | 84.8 | **out (rank 40/40)** | OUT lstpetr, JoeyAroyyOO, luciebot, 0xe1C08abF3f7D → IN BadTattoo, mo-y, Ksi172, delacsynzy1 |
| **A1 basis + `michaelis`** | 25 | 83.9 | **out (rank 40/40)** | OUT TheOmniussiah, 0x167D74FC517d, SimpleTony, illenial, bitcoin9, forecastication4, luciebot, 0xe1C08abF3f7D → IN Ksi172, 0x658E4EcA37, 1l2ihj34li12, JohnnyWins, gysh.qs, BadTattoo, alvahunter, madmartigan5 |
| A2 basis + `atan` | 25 | 77.9 | **out (rank 40/40)** | OUT TheOmniussiah, 0x167D74FC517d, SimpleTony, illenial, bitcoin9, forecastication4, JoeyAroyyOO, luciebot → IN 0x62D56a9351, Israel26, BadTattoo, mo-y, madmartigan5, alvahunter, JohnnyWins, 0x658E4EcA37 |

Three findings the card does not have:

1. **(A) alone does remove this wallet** — in every variant, and not narrowly: 68.0 vs a cut of 83.9
   (A1). The card's "seat 25 of 25, still inside" compares the wallet to the other 24 seats only.
2. **The turnover is 4–8 seats, and half of it is dead seats.** Under A1, four of the eight dropped
   seats (`0x167D74FC517d`, `illenial`, `bitcoin9`, `0xe1C08abF3f7D`) journaled **zero decisions** in
   the last 7 days — they are occupying seats that produce no flow. The four that do flow are
   `luciebot` (6,644 decisions/7d), `forecastication4` (1,036), `SimpleTony` (448),
   `TheOmniussiah` (11).
3. **The curve choice is a real decision, not a detail.** `atan` is the only variant that keeps
   de-saturating across the whole range (it never flattens: roi +1,600% reads 98.5 against +16,000% at
   99.8), but it shifts the whole scale down (median −2.2 points) because it compresses the ROI term's
   range — which hands effective weight to consistency/copyability and evicts two high-ROI,
   low-consistency seats (SimpleTony, JoeyAroyyOO). `michaelis` tracks the shipped curve closely at the
   low end (within 0.4 points to roi +10%, 3.5 points to +30%) and only compresses the top, so the seat
   order moves least — but it still pins roi ≥ +100% at 100 (10 of 25 seats).

### 2.4 Operational truth: a basis fix lands only when a wallet is re-scanned

The hourly scan profiles **25 wallets** from a **3,841-wallet** rotation ordered by
`lastScannedAt ASC` — one full pass takes ~6.4 days. Measured: 125 profiles scanned in the last 6h;
**3,841/3,841 have been scanned inside 7 days**. So flipping the rule does not re-score the seats
immediately; each wallet keeps its stored (sample-based) score until its turn comes round, i.e. the
wallet can hold its seat for up to ~6 more days after the change. Any ship step needs a one-off
re-score sweep of the seated + near-cut wallets (25 + ~40), which is ~1,100 venue pages at the
measured rate — about 15–20 minutes of one cycle, not a permanent cost increase if the scan walks the
venue record only for wallets near the cut.

---

## 3. (B) The floor, measured on every population the card could mean

Threshold: ≥30 settled legs and the ROI's 95% CI excluding zero on the positive side. All ten
populations, same 25 seats and same 15 challengers:

| Population the floor is measured on | seats pass | challengers pass | subject | subject ROI [CI] |
|---|---|---|---|---|
| venue realized, **all** settled legs | 18/25 | 12/15 | **PASS** | +19.0% [+12.6, +27.0] |
| venue **hold**, all settled legs | 17/25 | 11/15 | FAIL | −9.3% [−11.7, −7.0] |
| venue realized, rich band ≥0.95 | 1/25 | 0/15 | FAIL | −5.0% [−6.7, −3.1] |
| venue hold, rich band ≥0.95 | 2/25 | 0/15 | PASS | +0.3% [+0.1, +0.5] |
| venue realized, copyable band ≥0.80 | 3/25 | 2/15 | FAIL | −4.2% [−5.8, −2.3] |
| venue hold, copyable band ≥0.80 | 4/25 | 2/15 | PASS | +0.8% [+0.5, +1.2] |
| our observed legs, its entry, all history | 12/25 | 9/15 | FAIL | +0.3% [−0.2, +0.8] |
| our observed legs, detected mid, all history | 13/25 | 9/15 | PASS | +0.7% [+0.2, +1.3] |
| our observed legs, its entry, flood window | 4/25 | 3/15 | FAIL | −1.5% [−3.4, +0.1] |
| our observed legs, detected mid, flood window | 4/25 | 3/15 | FAIL | +0.8% [−1.2, +2.6] |

**Why the literal rule cannot work.** "The wallet's settled record" is a *positive* number (+19.0%,
CI excludes zero) because a market maker's settled record is its trading P&L, not the payoff of the
book it handed us. The card's −1.47% is the legs we watched it print — a different population, and one
that no scan-time rule can compute for an unseated wallet until it has been observed (2 of the 25
current seats and 2 of the 15 challengers have **zero** observed settled legs; 12 of 25 have <30).

**Why the variants that do catch it are not shippable.** The two that fail the wallet on a *copyable*
population are the rich/copyable-band reads (1–4 of 25 seats survive) and the flood-window observed
read (4 of 25). They are not filters, they are near-total exclusions of the current universe. And the
sharpest one is also the least stable: the same wallet reads −1.5% at its own entry and **+0.8%** at
our detected mid in the same window, i.e. the gate would be decided by which entry price the
implementation uses, on a ±1% signal.

**The refutation test the card specifies** ("≥3 wallets outside the current top 25 pass and every
current seat also passes") does not fire in the literal form either: 7 of the 25 seats *fail* the
literal rule, all for insufficient evidence (7–25 settled legs) — so the floor is not a no-op, it is a
turnover engine with a null on its intended target. A floor built on evidence alone would drop those
7 seats and change nothing about this wallet.

### 3.1 Seat turnover over the last 30 days (what a floor's cost lands on)

| Measure | Value |
|---|---|
| wallets whose first copy-eligible observation falls inside 30d | 70 |
| … of those, seated today | 22 (so 48 seats were won and lost again inside the window) |
| current seat tenure: median / min / max | 38.9 d / 1.1 d / 121 d |
| seats held under 30 days | 12 of 25 |
| current seats that have never produced a copy-eligible observation | 1 (`0x167D74FC517d`) |
| challengers with <30 observed settled legs | 6 of 15 |

So the seat set already churns roughly half its membership per month — a floor that drops 7–8 seats is
*within* normal churn, which is why the volume argument is not what disqualifies it. What disqualifies
it is that the entrants carry the same thin evidence the incumbents do (6 of 15 challengers have <30
observed settled legs; 2 have none), so the floor moves seats around without raising the evidence base
of the universe.

---

## 4. What this wallet actually is (and the limit of the card's premise)

| Read | Result | Population |
|---|---|---|
| venue realized, all settled legs | **+19.0%** [+12.6, +27.0] | 24,675 legs, $357,809 |
| venue hold, all settled legs | **−9.3%** [−11.7, −7.0] | same legs |
| our observed legs @ detected mid, all history | **+0.7%** [+0.2, +1.3] | 7,798 settled keys, $63,389 |
| our observed legs @ detected mid, flood window | **+0.8%** [−1.2, +2.6] | 1,899-class subset, $34k-class |
| our observed legs @ its entry, flood window | **−1.5%** [−3.4, +0.1] | same subset |
| venue positions, flood vintage, hold | **−18.2%** [−20.8, −15.8] | 4,152 legs |

So: **flat to +0.7% on the legs we can actually copy, negative if you hold its book, positive on its
own trading.** It is not a fraud and not a hidden winner; it is a high-frequency dust market-maker
whose tape is worth roughly nothing per copied leg, ranked at 163% ROI by a 100-row sample, and
therefore selected into a seat where it supplies 48.9% of the journal's decisions (6,644 of 13,575 in
the last 7 days) and **95.5% of the near-certainty cohort** (4,075 of 4,267 rows, re-measured on the
same window).

The honest correction to the card: the case against it is **concentration + mis-scoring**, not
"unprofitable". A rule that says "not profitable" is measuring the wrong population (its own trading)
or an unstable one (our observed legs, ±1%).

---

## 5. Delta a ship would move, on a 7-day replay

Admissions delta is exact for the removal side (journal rows attributable to a dropped seat) and a
**lower bound** for the entry side (untracked wallets are swept 40-per-cycle, so their observed flow
understates what a seat would produce).

| Ship | journal decisions /7d | copies /7d | paper trades /7d | paper PnL /7d | of which dead seats |
|---|---|---|---|---|---|
| today | 13,575 | 192 | 230 | +$247.74 | — |
| A1 (`michaelis`) | −8,139 (−60%) | −143 | −160 | **−$256.16** | 4 of 8 dropped seats journaled 0 |
| A2 (`atan`) | −8,377 (−62%) | −147 | −166 | −$277.53 | 3 of 8 |
| A0 (basis only) | −6,882 (−51%) | −62 | −74 | −$229.40 | 2 of 4 |

Per-seat, the flowing rows that leave under A1: `luciebot` 6,644 decisions / 58 copies / −$208.03;
`forecastication4` 1,036 / 71 / +$82.39; `SimpleTony` 448 / 14 / −$130.52; `TheOmniussiah` 11 / 0 / $0.

So (A) removes ~60% of the journal's volume and **−$256 of 7-day paper PnL** (i.e. it removes a
*negative* book), and the near-certainty cohort it empties is the one the parent card showed is a
single-wallet cohort.

---

## 6. If (A1) is approved — the change, the dry run, the revert

Nothing below is applied. Three pieces, one ship unit; the rule fields are **inert without the code**
(a rule-only flip would be a silent no-op, so an `apply-vNN` must not ship alone).

1. **Adapter** — `src/lib/adapters/polymarket.ts`: add `fetchWalletRecord(address)` reusing the
   existing cursor walk (`/v2/positions?status=CLOSED&limit=50&sort_by=REALIZED_PNL&sort_direction=DESC`,
   cap 700 pages), returning `{n, cost, pnl, winRate, settled:{n, cost, pnl, costEarlyExit}}`.
   Cost basis `total_size × avg_price` (validated against the venue's own `percent_realized_pnl`);
   `total_cost_usdc` is unusable (zero on 87.8% of this wallet's rows). Measured cost: 1,139 pages for
   40 wallets (median wallet 3.5 pages; the tail is one 31,993-position wallet at 640).
2. **Scorer** — `src/lib/scoring/wallet.ts`: `roiScore` reads a curve keyed by
   `rules.walletRoiCurve` (`linear` = today, `michaelis`, `atan`); `scoreWallet` accepts an optional
   full-record ROI and uses it when `rules.walletRoiBasis === "venue_full"`. Persist the sample ROI
   beside the used one (`roiSample30d`) so the before/after stays auditable.
3. **Scan** — `scripts/scan-wallets.ts`: fetch the record for wallets being profiled; walk the venue
   record for near-cut wallets only, so the hourly cost stays bounded.

**Rule fields (the revert is one field each):**

| field | today | proposed (A1) | revert |
|---|---|---|---|
| `walletRoiBasis` | `"sample"` | `"venue_full"` | `"sample"` |
| `walletRoiCurve` | `"linear"` | `"michaelis"` | `"linear"` |

**Dry run** (writes nothing): `python3 scripts/lane-a-seat-basis-read.py --boot 3000` →
`data/lane-a-seat-basis-read.json`; every table in this draft is read back from that file, and
`--fetch-venue` only refreshes the read-only venue cache.

**Ship step after approval:** `npx tsx scripts/apply-v73-wallet-roi-basis.ts --dry-run` (prints the
seat-by-seat consequence and writes nothing), then without `--dry-run`, then the one-off re-score
sweep, then `npx tsx scripts/apply-v73-wallet-roi-basis.ts --revert` to undo (single RuleSet bump,
both fields back to defaults, `RuleChange` before/after JSON records it). `apply-v73` does not exist
yet — it is part of the same ship unit as the adapter/scorer change, because an apply script that
flipped the fields without the code would write a no-op rule and report success.

**Pre-registered expectation to check after the sweep** (so the change is falsifiable, not vibes):
`luciebot` leaves the seat set; the near-certainty cohort falls back to the parent card's measured
ex-wallet baseline (4–28/day, median 13, against ~650/day with it); journal volume falls ~60%/7d; no
wallet in the measured pool falls below the `track` threshold (min score after A1 across the 40
measured wallets is 68.0, well above the 50 implied by `minWalletGlobalScore = 40`). If `luciebot`
keeps a seat after the sweep, (A1) is not doing what this measurement says and should be reverted.

---

## 7. Limits and what this read does not establish

* **Partial counterfactual.** Only the ROI term is re-scored. `consistencyScore` and
  `copyabilityScore` are held at their stored values, and they too come from the 100-row sample
  (copyability is explicitly computed on the sample's price mix, and the sample is 50% winners *by
  construction*). The real after-state will move further than the tables above, in an unmeasured
  direction.
* **Challenger pool is bounded** (15 non-demo `watch` wallets scoring above the cut, of 3,663 watch
  profiles). "Seats filled 22/25" for the observed-legs floors is a *pool* limit, not a rule property.
  The turnover tables are a top-25-of-40 ranking, i.e. the seat set after one full scan rotation.
* **Two wallets' venue walks are censored**: `0x62D56a9351` (candidate) hit the 80-page cap at 4,000
  positions — its record is a lower bound, so its full-record ROI (+2,290%) is biased high and its
  hold-to-settlement (−30.6%) is computed on the largest-PnL slice only. It enters the seat set under
  A2; that entry should not be trusted until its walk completes.
* **Settlement oracle is the venue's terminal mark on the wallet's own closed positions.** It cannot
  price an observed leg the wallet never held a closed position in; those legs are dropped rather than
  defaulted (7,798 of 11,371 observed keys price in for the subject).
* **Early exits** make the hold basis a synthetic for any wallet that round-trips (14.9% of this
  wallet's settled cost). It is the right basis for "what a copier who holds earns", not for "what the
  wallet earned"; both are reported wherever the conclusion depends on it.
* **Scan-rotation lag** means the post-ship seat table is only reachable after a full pass (~6.4 days)
  or a targeted re-score sweep; the 7-day replay columns above price the *journal*, not the lag.

---

## 8. Re-run

```
python3 scripts/lane-a-seat-basis-read.py --fetch-venue --boot 3000 --candidates 20
```

Refreshes 40 venue CLOSED-position walks (1,139 pages), rewrites `data/wallet-seat-positions.json`
(raw cache, gitignored) and `data/lane-a-seat-basis-read.json`. Read-only against `prisma/dev.db`
(SELECT only). No rule, size, gate, exit or tracking change was made by this card.
