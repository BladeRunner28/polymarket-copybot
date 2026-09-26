# Fee model + maker/taker calibration from the Polymarket-v1 archive (2026-09-25)

**Trigger:** the archive landed on `/Volumes/Storage/pm-data` and was verified earlier today
(`drafts/historical-archive-inventory-20260925.md`). Its stated next step was the fee-model calibration on
real `fee_usdc` plus the maker/taker split that the `c200-maker-fill-assumption` card is blocked on. This is
that measurement. **Measurement only — no rule, sizing, gate or booked figure changed.** The C-200 fill
assumption is a PnL/sizing input and stays recommendation-only.

**Instruments (re-runnable, read-only):**
`scripts/archive-fee-maker-analysis.py` (modes `split` / `fee` / `fill` / `drift`; results in
`data/archive-analysis/`) and `scripts/c200-fee-reprice-archive.py` (our own legs). Archive venv:
`/Volumes/Storage/pm-data/.venv/bin/python`.

---

## Key insight

Three separate questions were being answered by one assumption:

1. **Is a fee charged at all, and to whom?** Yes — and only to the **taker**. Measured, not read off a doc.
2. **What does the fee cost?** The archive measures the 2026 rate as **~4–5× harsher at mid prices than the
   schedule published in July 2026** — so the archive calibrates *structure*, and must not be used to re-price
   today's fee. Our September model is consistent with the current schedule; the ledger still books **zero**.
3. **Does a resting bid 2¢ inside actually fill?** On fill *probability*, yes — **74–81%** at C-200's own price
   mix. On fill *quality*, no — the fills are **adversely selected**: filled cases drift **−0.032 points** in the
   next hour, while the ~20% of cases we *don't* get filled are the ones where price ran **+0.22 points** away.

---

## 1. The fee era is visible in the data (1.2B fills)

`fee_usdc` is **zero on 100% of fills through 2025-12**, then fees roll out market-by-market:

| month | fills | fee-bearing | total fee |
|---|---|---|---|
| 2022-11 → 2025-12 | 316.5M | **0.00%** | **$0** |
| 2026-01 | 136,678,547 | 42.3% | $84.6M |
| 2026-02 | 218,101,912 | 67.1% | $185.1M |
| 2026-03 | 320,404,950 | 75.8% | $374.3M |
| 2026-04 | 227,285,666 | 88.0% | $569.0M |

2026 era (Jan–Apr): **902,471,075 fills, $31.11B notional, $1,213.0M of fees = 3.90% of notional.**
Split by aggressor side: taker **BUY** $46.5M on $6.66B (0.70%), taker **SELL** $1,166.6M on $24.45B (4.77%).

## 2. The fee law, fitted exactly

For every taker **BUY** fill, `fee == rate × shares × min(p, 1-p)` — **95–99% of rows match to 1e-6** within
every price band in every month tested, with `rate = 0.10` (= `taker_base_fee` 1000 / 1e4):

| band | rows | median implied rate | rows matching 0.10 exactly |
|---|---|---|---|
| 0.0–0.1 | 3,801,210 | 0.100000 | 3,724,379 |
| 0.2–0.3 | 1,877,942 | 0.100000 | 1,850,014 |
| 0.4–0.5 | 2,407,621 | 0.100000 | 2,382,259 |
| 0.8–0.9 | 1,798,104 | 0.100000 | 1,671,038 |
| 0.9–1.0 | 5,957,785 | 0.100000 | 5,534,309 |

taker **SELL** fills instead follow `rate × shares × min(p,1-p) / p` (median implied rate = 0.10/p in every
band). **I cannot explain that asymmetry** and I am not going to paper over it: it implies a taker SELL at
p<0.5 pays ~0.10 USDC *per share*, i.e. 10%/p of proceeds, which is not economically credible as a fee on the
seller. The BUY form is the one that governs our lane (we buy), so this does not block anything — but the SELL
form is reported as unexplained rather than as a result, and the `taker_direction` semantics (README: "taker is
the aggressor") are the thing to re-check before anyone builds on the SELL side.

**Makers pay zero.** `maker_base_fee` is 0 or equal to the taker rate in the metadata, and no maker-side row
carries a fee; the published schedule agrees ("Makers pay $0"). This supports the fee half of the C-200 maker
premise: *if* our entry is genuinely a resting maker order, its entry fee is 0.

## 3. Reality check — the schedule changed, so do not transplant the archive's rate

Current published schedule (July 2026, re-verified this session): `fee = shares × 0.05 × p(1-p)`, ceiling
**$1.25 per 100 shares at p=0.5**, makers $0. The archive's 2026 era is `0.10 × min(p,1-p)`:

| model | fee per 100 shares at p=0.5 | shape |
|---|---|---|
| archive 2026 era | **$5.00** | `0.10 × min(p,1-p)` |
| current published | **$1.25** | `0.05 × p(1-p)` |
| our 2026-09-09 model | $1.00–1.75 | `0.04–0.07 × p(1-p)` by category |

At mid prices the old regime was **~4× more expensive**. So the honest calibration is: the archive proves fees
are real, taker-only and shape-`min(p,1-p)` for its era; the **current** rate must come from the published
schedule — which is what the September model already used. **The archive cannot be used to claim today's fees
are 5× our estimate**, and the first draft of this analysis nearly did. It does prove the ledger's **zero-fee
booking** is the error, and it quantifies the drag (below).

## 4. The maker/taker split — a buyer's market for resting bids

2026 era, aggressor side by price band (783M fills with usable prices):

| price band | n | taker BUY | taker SELL |
|---|---|---|---|
| 0.0–0.1 | 119,469,279 | 21.6% | 78.4% |
| 0.3–0.4 | 86,927,966 | 14.6% | 85.4% |
| 0.4–0.5 | 116,379,484 | 11.6% | 88.4% |
| 0.5–0.6 | 117,564,902 | 10.6% | 89.4% |
| 0.7–0.8 | 67,163,190 | 14.6% | 85.4% |
| 0.9–1.0 | 128,698,912 | 25.4% | 74.6% |
| **all** | **902,471,075** | **16.4%** | **83.6%** |

**The aggressor is a seller in 83.6% of all fills.** The common side to be *filled* in this venue is the resting
**bid**, which is the structural premise behind a maker-entry lane: someone is usually selling into bids. It is
also why a copied BUY can rest 2¢ inside and still expect to be touched.

## 5. Maker-fill hazard — the first external estimate of the 2¢ assumption

For a fill at price `p` at time `t`: does the tape print at ≤ `p − δ` on the same token within horizon `h`? That
is exactly the event the sidecar's `entry = intent − $0.02` assumes. Measured over **783,342,642 fills**
(2026-01…2026-04), all prices in probability points:

| δ | 5 min | 30 min | 1 h |
|---|---|---|---|
| 0.01 | 77.6% | 82.4% | 83.9% |
| **0.02** | **71.1%** | **76.1%** | **77.6%** |
| 0.05 | 60.4% | 66.3% | 67.8% |
| 0.10 | 48.8% | 55.8% | 57.3% |

By price band at δ=0.02 / 1 h: 0.0–0.1 **45.9%** · 0.1–0.2 83.5% · 0.2–0.3 86.9% · 0.3–0.4 87.7% ·
0.4–0.5 86.7% · 0.5–0.6 84.5% · 0.6–0.7 83.2% · 0.7–0.8 79.2% · 0.8–0.9 71.3% · 0.9–1.0 **48.8%**.

Weighted by **our own legs' entry prices**: C-200 **74.3% (5 min) / 81.1% (1 h)**; STANDARD 69.2% / 75.6%.

**Cross-check (independent code path):** the same January–April table computed unsharded in a single pass for
2026-04 reproduces the sharded run **exactly** — 46.47% / 81.96% / 85.66% / 86.23% / 85.55% / 83.60% / 81.41% /
77.09% / 68.35% / 49.03% by band, Δ = 0.00 pp, n = 191,907,756 in both. The sharding is a memory workaround,
not a methodological choice.

**So the assumption is not implausible on fill probability.** That is a genuinely useful answer: a bid parked
2¢ below a fresh print is touched in roughly three of four cases within five minutes at our price mix.

## 6. …but the fills are adversely selected (the part that matters)

Same population, conditioned on whether the 2¢ bid filled, measuring the price **1 h later** (`px_end − p`):

| band | population | n | mean(px_end − p) | P(px_end < p) |
|---|---|---|---|---|
| 0.4–0.5 | filled | 100,878,463 | **−0.0296** | 58.7% |
| 0.4–0.5 | not filled | 14,744,465 | **+0.2354** | 17.2% |
| 0.5–0.6 | filled | 99,372,864 | **−0.0350** | 51.3% |
| 0.5–0.6 | not filled | 17,354,397 | **+0.2088** | 14.8% |
| 0.7–0.8 | filled | 53,215,736 | −0.0466 | 34.0% |
| 0.7–0.8 | not filled | 13,261,794 | +0.1433 | 10.5% |

Over C-200's own entry band (0.4–0.6, n=200,251,327 filled): mean **−0.0323** points one hour after the entry
print; the unfilled ~20% are cases where price ran **+0.22** points and we hold nothing.

**Reading:** the 2¢ improvement is not a free 2¢. You are filled precisely when the market is coming *down*
through you, and you forgo the moves that go *up*. The maker entry buys a better print at the cost of adverse
selection — which is the classic maker trade-off, now measured on 200M fills at our own price band. A fill
model that books the 2¢ without modelling this selection is booking the upside of the assumption only.

**Caveats (they limit, not erase, the result):** prints are not queue position — a touch does not guarantee
*our* order fills, and size is ignored (a resting bid can be swept only up to the printed size); the archive has
no order-book depth, no cancellations, no quotes (its own README); `OrderFilled` includes relayer/router flows
(kept deliberately — they are real matches against resting orders); the horizon is 1 h and our exits are not;
CTF Exchange v1 terminated 2026-04-28, so this is the venue's structure, not today's tape.

## 7. What the fee drag costs our own legs

`scripts/c200-fee-reprice-archive.py`, on the live book as of this run (read-only, `immutable=1`):

| lane | legs | notional | booked realized | fee: docs/current | fee: archive-era |
|---|---|---|---|---|---|
| BANKROLL_200 | 2,017 | $15,887 | **+$2,180.25** | $853–878 (5.4–5.5%) | $2,386 (15.0%) |
| STANDARD | 10,120 | $115,223 | +$8,845.85 | $3,866–3,874 (3.4%) | $12,207 (10.6%) |

- C-200 net of the **current** schedule as a taker: **+$1,302 to +$1,327**.
- C-200 with a **maker entry** (exit fee only): **+$1,818** — i.e. the maker half of the premise is worth about
  $490–500 on the current book, on top of the price improvement.
- The **archive-era** rate would put C-200 at **−$206** and STANDARD at −$3,361. This is the one number that must
  NOT be quoted as today's fee: it is the pre-July-2026 schedule (§3).

**The 2¢ credit, re-measured on the current maker era** (`openedAt ≥ 2026-08-28`, settled legs): C-200 has 1,190
legs with **$2,288.52** settled realized PnL, and the 2¢ price improvement is worth **$1,732.88 = 75.7%** of it
(the card's original figure was $1,525.76 of $2,534.58 = 60%; the book has grown and the concentration
deepened). Every C-200 edge number still carries it undeclared outside the report legend.

## 8. Verdict and what it changes

**Verdict:** the archive settles the fee half of the C-200 maker premise and reframes the fill half.

- ✅ **Confirmed:** fees are real, taker-only (makers pay 0), and the ledger booking zero is a fidelity error.
- ✅ **Confirmed:** resting bids are the side that gets hit in this venue (83.6% of fills have a selling
  aggressor) — a maker-entry lane is structurally sensible, not wishful.
- ✅ **New evidence:** at our own price mix a bid 2¢ inside is touched **74–81%** of the time within 5 min–1 h.
- ⚠️ **New counterweight:** those fills are adversely selected (≈ −0.03 points at 1 h), and the ~20–26% of cases
  we miss are the up-moves (+0.22 points). The 2¢ is a *fill model*, and it is not free.
- ⚠️ **Not settled by the archive:** whether *our* orders actually filled 2¢ inside, in size, at our queue
  position. Only in-house recording of the intent price can answer that — which is exactly the
  `c200-maker-fill-assumption` card's option (b).

**Recommendation (unchanged, now with evidence): keep the card's option (b) — measure it in-house by storing the
intent price at booking — and pair it with a make-vs-take sensitivity in every backtest/report that quotes a
C-200 edge, so the 2¢ credit and the adverse selection are both visible.** Nothing in the fill model, sizing,
caps or thresholds moves without a separate approval; no shipped number changes on the strength of this doc.

**Reported-by:** this measurement only. The follow-ups it creates are carded, not implemented.
