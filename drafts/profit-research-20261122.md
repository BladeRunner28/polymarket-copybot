# Profit research 2026-11-22 — every rebate schedule in the universe tops out below the execution gap, and the ladder pays most for the band the cap removes

http://localhost:3013/drafts/profit-research-20261122

**Instruments (both committed with this doc, both read-only):**
`scripts/profit-wv-tier.py` (new — the taker-rebate ladder priced on our own volume) and
`scripts/profit-path-research.py` (extended today: suppressed table cells are now declared).
`scripts/probe-zero-cost-filled.py` (new, throwaway probe, kept because it produced the defect
below). Every figure re-runs from those files; DB opened `mode=ro`.

**Basis, unchanged:** cost = `simulatedPositionSize` (**dollars at risk**); PnL = `realizedPnl` on
`status IN ('closed','resolved')` (TR-15 OR); `isDemo=0`; dedupe = first leg per
(bot|wallet|market|outcome); clock = **entry vintage**; CI = market-clustered bootstrap (2,000 draws).

---

## Verdict (ranked, one item)

1. **Run item 1's shadow or admit it is not running.** There is **no maker shadow for the Polymarket
   dispatch population anywhere in the repo** — not zero legs recorded, no writer: the only maker
   shadow on disk is `kalshi-maker-shadow-sim` (different venue, different population), and the
   reachability booth that exists for Polymarket is STANDARD-scoped. Day 5 of a 30-day refutation
   clock with nothing recording.
2. **Nothing on fees or rebates is worth building.** Measured today, both venues, both directions:
   the best possible rebate on this book is **3.70pp of at-risk** and it expires 2026-12-31; the
   global ladder's top rung is **2.28pp**. The gap it would have to close is **≥5pp**.
3. **No change is justified today** beyond (1). The measurement that would unlock a rule is a
   reachability stamp on the C-200 dispatch population (below).

---

## 1. Fresh measurement (same basis; what moved)

| cell | legs | $ at risk | PnL | ROI | clustered 95% CI |
|---|---|---|---|---|---|
| fill-confirmed ALL | 302 | $4,656 | −$865 | **−18.6%** | [−52.3, +22.6] |
| ex-$100 clip | 280 | $2,456 | −$155 | −6.3% | [−29.5, +21.2] |
| $100 clip | 22 | $2,200 | −$710 | −32.3% | win 9.1% vs be 14.3% |

Yesterday: 288 legs / $4,427 / −$775 / −17.5%. **Delta: +14 legs, +$229 at risk, −$90 PnL** — one
new $100 leg at a full −$100 loss. Not a trend.

Vertical split (fill-confirmed):

- **question** 55 legs / $1,539 / −$776 / **−50.4%, CI [−73.3, −17.3]** — provably negative, 4th day
- **esports** 67 / $1,293 / −$736 / **−56.9%, CI [−79.5, −21.9]** — provably negative
- **sports** 114 / $1,096 / +$998 / +91.1%, CI [−25.0, +213.2]; **ex-top-3 −27.0%, CI [−54.0, +6.7]**
- **other** 66 / $728 / −$351 / −48.2%

Adjudication coverage: **BANKROLL_200 908/2,955 (30.7%)**, **STANDARD 0/10,044 (0.0%, sixth day)**.

## 2. Instrument defect found and fixed (Lane B)

The FILL-CONFIRMED clip table summed to **299 of 302 legs and $4,506 of $4,676 at risk** while
printing as if complete: the 3-leg `$40-99` cell was dropped by the table's `minn=8` display floor,
so its rows could not reconcile with the headline ROI (−16.7% from the printed rows vs −18.6%
actual). The same defect hid **296 legs / $3,451 / −$310** in the all-settled category table.

Fixed in `scripts/profit-path-research.py`: every table now prints a `[suppressed]` footer row with
the dropped legs/cost/PnL and writes them to `art["suppressed_cells"]`. Verified by re-running.

The suppressed cell is not noise: `$40-99` is **3 legs, $150, −$111 (−74.0%), 0% win** — a third
independent read that the mid clip tier is the losing tier.

Revert: `git revert <sha>` (single commit, no schema, no RuleSet, no prisma write).

## 3. The rebate ladder, priced (new external fact)

Polymarket's fees page now publishes the full table (`docs.polymarket.com/trading/fees`, effective
2026-11-20 23:59 UTC): **sports 0.05, elections/finance/tech 0.05, Other/General 0.05, crypto 0.01
(BTC 5m/15m 0.05), politics-excluding-elections 0.01, mentions/economics/culture/weather 0.01,
geopolitics 0**. Maker fee 0 everywhere.

The taker rebate ladder (`docs.polymarket.com/programs/taker-rebates`) is **wV = trade size × (1 −
entry price)**, first rung Gold at **$200,000 of 30-day wV**.

- our 30-day wV: **$7,523 = 3.76% of Gold** (591 legs, $12,052 at risk, $402/day run-rate)
- value of each rung on our filled book: Gold **0.36pp**, Platinum 0.89, Diamond 1.42,
  Obsidian 1.78, **Onyx (60%, $75M floor) 2.28pp**
- to clear the 5pp execution gap at rate 0.05 you would need a **132% rebate share**
- reaching Gold needs **$8,770/day** of dispatch — 21.8× the current run-rate, and 57% of Gold is
  the ceiling even at the ladder's own $5,000/day target

**And the gradient points into the loss.** wV per dollar at risk, with the ROI of that same cell:

- px 0.00-0.10 → **0.932** wV, ROI **−97.8%**
- px 0.10-0.20 → 0.836 wV, ROI −4.6%
- px 0.20-0.40 → 0.697 wV, ROI −2.6%
- px 0.40-0.60 → 0.506 wV, ROI +19.1%
- px 0.60-0.80 → **0.324** wV, ROI **+11.9%**

The ladder pays **2.9× more credit per dollar** in the band that loses 97.8% than in the band that
earns +11.9% — i.e. the rebate tier is maximised by the exact $100-on-cheap-longshot cell the
approved cap removes. Optimising for the tier and fixing the defect are opposite trades.

## 4. The US venue has the cheapest taker fee anywhere, and it expires before go-live

`docs.polymarket.us/fees.md` (updated 2026-11-20, read 2026-11-22): **all taker trades placed
through the Polymarket US API** are charged a flat coefficient **0.0695** and receive a **70%
rebate**, from **12:01 AM ET 2026-11-21 through 2026-12-31**. Net coefficient **0.02085**.

On our filled book that is **1.58pp of at-risk vs 3.56pp on global** — saves **$92 on $4,656**, and
per day forward it is the largest single fee improvement available anywhere in the universe.

Why it is not a lever: (a) it is a **different exchange** (QCX, CFTC-regulated) with its own
listing set and auth — we have no market universe, no tape and no data on it; (b) the program ends
**2026-12-31, two days before the 2027-01-02 go-live anchor**, so it is worth exactly nothing to
the plan unless renewed. Recorded as a change-detection fact with a decision rule, not a build.

## 5. External sweeps (change detection only)

- **Polymarket changelog**: no entry after 2026-11-20. The Nov 20 repricing is live; `price-edge.ts:65`
  still hardcodes crypto 0.07 / politics 0.04 — now decidable in the other direction too: the
  politics/finance bucket at 0.05 is *right* for elections+finance and **wrong for non-election
  politics (0.01)**, and crypto is overcharged 7× (or 1.4× if a BTC 5m/15m market). Unwired, so
  still no decision risk; the Lane A proposal stands unchanged.
- **Kalshi changelog**: top batch 2026-11-26 (RFQ concert resolution, on-request rate limits,
  partial-close FIX ordering) — **no fee, no incentive, no liquidity-program change**.
- **Kalshi LIP**: live menu **7,196 programs, 0 above the $0.0131 gate**, max live ceiling
  **$0.002976** (4.4× below), forward schedules 0 above gate; measured net
  **+$0.0000940/contract-hour**. The 33.06% above-gate rate in the 232k feed lives entirely in
  ≤2h families (**75,790 of 92,900 in ≤2h; 0 of 58,592 in >48h**). Verdict stays **CLOSE**.
- **arXiv**: newest prediction-market paper **2026-11-17** (ForecastGym — an LLM forecasting
  benchmark, no microstructure content); newest q-fin.TR **2026-11-19** (equity rebalancing). No
  importable claim.
- **GitHub**: no new tooling; the week's Polymarket/Kalshi repos are zero-star paper-bot ledgers,
  all `NO-LIC` → read-only at best, nothing to read.
- **Reddit**: **4th consecutive day unsampled** — r/Polymarket `.rss` 404, r/Kalshi and
  r/algotrading 429, and the `r.jina.ai` mirror returns Reddit's "whoa there, pardner" block. No
  forum claim is used anywhere in this doc.

## 6. Progress on the approved path (deltas only)

- **item 1 maker-vs-taker shadow** — **no Polymarket-dispatch writer exists** (day 5); the only
  maker shadow on disk is Kalshi's, and the Polymarket reachability booth is STANDARD-scoped.
  Extending it to the C-200 dispatch population is the concrete next step. The item's own
  refutation ("<200 legs in 30 days") cannot fire if nothing records legs.
- **item 2 STANDARD fill adjudication** — today's scheduled run: 157 in scope, **154 book-stamped
  (98%), tape 0**, refutation **NOT EVALUABLE at 154/300**; the union backfill artifact is the
  wider population (1,028 legs / 396 book). Still **0% merged into `fillStatus`**.
- **item 3 $100 clip cap** — forward cohort unchanged (4 legs / −$400 / 0 wins); the 22 filled
  $100 legs now sit $710 negative, and 100% of them are inside the approved band.
- **item 4 ML re-point** — no shipped change.
- **item 5 LIP** — CLOSED again on both the live menu and the forward schedule.

## What would unlock a rule

A reachability stamp on the **C-200 dispatch population** (not STANDARD): for each dispatch, was
there a seller at the booked price, and at the mid? The STANDARD booth already emits that field
per leg; the same join on C-200 legs gives item 1 its population and item 2 its scope in one pass.
Unlock condition: **≥200 stamped C-200 legs**, then the maker-vs-taker ROI delta with a
market-clustered CI — the item 1 decision rule as approved.
