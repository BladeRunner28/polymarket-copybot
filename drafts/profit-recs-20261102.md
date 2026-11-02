# Profit review — 2026-11-02

http://localhost:3013/drafts/profit-recs-20261102

**Cost basis on every ROI below: `simulatedPositionSize` = dollars at risk, never shares.** A BUY of
`$n` at `p` is `n/p` shares, so settlement at `s` realises `n*(s/p − 1)`; `edge` is measured against
the break-even hit rate, which is **not** `p` (see the identity below). Bet-level = first leg per
`(wallet, market, outcome)`, the canonical dedupe; leg-level is printed beside it because notional
lives there.

Every figure is computed by **`scripts/profit-fee-net.py`** (§FN, new this commit). Reproduce:

```
python3 scripts/profit-fee-net.py              # full report, all finished legs, rate 0.05
python3 scripts/profit-fee-net.py --days 90    # card's window (only affects FN.7)
python3 scripts/profit-fee-net.py --selftest   # identities: fee law, hurdle algebra, settlement check
python3 scripts/profit-fee-net.py --rate 0.07  # rate sensitivity
```

Read-only over `prisma/dev.db` (`immutable=1`). Nothing written, no RuleSet read or touched.

---

## The venue charges this book a fee that neither the ledger nor any gate books — 27% of its measured edge

`PaperTrade` has no fee column. `src/lib/paper.ts` writes `realizedPnl` from the price path alone,
and `src/lib/copy-cost.ts` states it in its own header: *"the paper fill crosses no spread and pays
no fee."* The one fee-aware gate in the repo (`src/lib/scoring/price-edge.ts`) is
`status: "shadow"` and is wired to nothing. So the decision loop is fee-blind **and** the scoreboard
is fee-blind, while the venue is not.

Priced with the repo's own law — `fee = shares * rate * p * (1-p)`, rate 0.05 default / 0.04
politics-finance / 0.07 crypto — the finished book pays:

| basis | bets | notional | gross ROI | fee | net ROI | $/1k-cd gross→net |
| --- | --- | --- | --- | --- | --- | --- |
| **all finished, bet-level** | 4,890 | $52,494 | +8.31% | 2.25% | **+6.05%** | 8.52 → **6.21** |
| BANKROLL_200 | 1,299 | $9,031 | +28.28% | 3.35% | +24.93% | 186.91 → 164.77 |
| STANDARD | 3,591 | $43,463 | +4.16% | 2.03% | **+2.13%** | 3.63 → **1.86** |
| all finished, leg-level | 12,429 | $135,467 | +11.25% | 2.24% | +9.01% | 11.95 → 9.57 |

**The rate is not the open question; the application is.** Our 0.05 proxy prices the venue's own
per-market schedule within 0.5%: `data/fee-sign-flip-report.json` (2026-10-22, 4,040 markets,
99.68% coverage) reads **$4,996.97 venue vs $5,024.02 proxy** on 12,710 legs, with **2 sign flips**.
My script reproduces that $4,996 exactly when it uses the same exit basis (§FN.1: `$4,996`, 3.69% of
notional). The disagreement in this repo was never about the fee *rate* — it is about whether the
fee exists in the numbers we decide on. It does not.

### The identity that has been missing from every band table

Break-even hit rate with a taker fee is **`p * (1 + rate*(1-p))`**, not `p`. At p=0.50, rate 0.05,
that is **51.25%** — a leg entered at the dead zone's midpoint has to be right 1.25pp more often than
the price to break even, and every "edge = hit − p" in the last twelve briefs has been measuring
against a hurdle that is 1.25–2.5pp too low.

The mirror-image correction matters for allocation. Fee as a fraction of **dollars at risk** is
`rate*(1-p)`:

- `<0.20` pays **4.29%** of stake · `0.2–0.4` 3.36% · `0.4–0.6` 2.49% · `0.6–0.8` 1.54% · `0.8–1.0` **0.37%**

So "fees peak at p=0.50 and vanish at both extremes" is true per unit of **notional traded** and
**false per unit of capital at risk** — and capital at risk is the basis of every ROI in this book.
The cheap tail pays the highest fee per dollar it stakes; it simply has 90pp of gross ROI to absorb
it. The top band pays almost nothing and still loses.

### Where the money actually is (STANDARD, bet-level, one fee, net contribution)

| band | bets | notional | net ROI | net $ | fee % of stake |
| --- | --- | --- | --- | --- | --- |
| <0.20 | 236 | $2,935 | **+58.36%** | **+$1,713** | 4.29 |
| 0.2–0.4 | 453 | $5,767 | +12.23% | +$705 | 3.36 |
| 0.4–0.6 | 1,181 | $15,465 | **−9.07%** | **−$1,403** | 2.49 |
| 0.6–0.8 | 684 | $8,902 | +0.99% | +$88 | 1.54 |
| 0.8–1.0 | 1,037 | $10,395 | −1.71% | −$178 | 0.37 |

**STANDARD's entire net profit — +$2,418 — comes from the 20% of notional below 0.40. The 80% above
it nets −$1,493.** On the gross basis that line reads +$2,737 / −$929, so the fee does not create the
inversion; it almost doubles the hole on the side we fund most.

### The hurdle table, on the population that actually settled

Resolved bets only (1,674 bets, $19,528), one fee, dollar-weighted hit rate:

| band | n | mean px | hurdle | $hit | vs hurdle | net ROI |
| --- | --- | --- | --- | --- | --- | --- |
| <0.20 | 158 | 0.112 | 11.65% | 19.95% | **+8.30pp** | +86.90% |
| 0.2–0.4 | 297 | 0.314 | 32.51% | 39.45% | **+6.94pp** | +20.95% |
| 0.4–0.6 | 655 | 0.501 | 51.33% | 48.06% | **−3.27pp** | −7.88% |
| 0.6–0.8 | 413 | 0.688 | 69.88% | 72.15% | +2.27pp | +3.18% |
| 0.8–1.0 | 151 | 0.885 | 89.00% | 86.71% | **−2.29pp** | −2.37% |

Two bands clear their fee by a margin worth having, two lose to it, and `0.6–0.8` clears by a
margin (2.27pp) that is smaller than its own year-to-year noise. **There is no band whose net edge
is both positive and comfortably larger than the fee.**

### Two-thirds of the book's notional is a fee-paying coin flip

| status | bets | notional | gross | net (one fee) | net (two fees) |
| --- | --- | --- | --- | --- | --- |
| resolved (settled) | 1,674 | $19,528 | +19.18% | +16.63% | +16.63% |
| closed (mark exit) | 3,216 | $32,966 | +1.86% | **−0.21%** | **−0.73%** |

63% of bet-level notional leaves by a mark, not a settlement, earns **+1.86% gross** — and the entry
fee alone turns it negative. Settlement pays for the book; the mark half pays the venue and nothing
else. (Exit prices are bimodal — **83.4%** of closed legs leave below 0.05 or above 0.80, where the
exit fee is near zero — which is why the one-fee reading is the fair one and the two-fee reading is
the worst case.)

### The ladder arithmetics, net

Gross **8.52 $/1k-capital-day**, net **6.21** — a **27.1% haircut**. At that rate:

- **$500/day needs $80,541 of capital continuously deployed** (gross reading: $58,693).
- $5,000/day needs **$805,411** (gross: $586,932).

Against the **$4,865** of open notional actually deployed, the fee moves the ladder from **121× short
of the top rung to 166×** short, and the $500 rung from 12.1× to 16.6×. It does not change the
verdict on the ladder; it changes the number everyone is quoting.

### The pending band card, priced net (this is the only money on the table)

Same notional-neutral shadow the 10-30 brief used — §AM.7 `strong` map 2.0/1.5/0.5/0.4/0.2, each
bet's notional and fee scaled by factor/normaliser:

| window | gross delta | fee delta | **net delta** | eaten by fee |
| --- | --- | --- | --- | --- |
| all finished (n=4,890) | +$7,693 | +$482 | **+$7,211** | 6.3% |
| 90d (n=3,414) | +$5,725 | +$308 | **+$5,417** | 5.4% |
| 90d ex-top-10 | +$1,246 | — | — | — |

**The fee does not kill the band map.** It removes 5–6% of the gross delta, not the 10%+ I expected
when I started this section — see the refutation under #2. Caveat that must travel with these
numbers: no clamps, no live band skip, bet-level — so the magnitudes are **not** comparable to the
card's own §AM.7 print (+$2,586 / ex-top-10 +1.7%); only the *ratio* gross→net travels.

---

## #1 — Book the fee in the ledger and in the ladder advance. Lane A, propose only.

**Hypothesis.** The paper book's PnL is gross, so the ladder's 7-day rung test and every sizing
decision read a number that is 27% too high, and the closed half of the book — 63% of notional — is
being treated as a small profit when it is a small loss.

**Measurement.** `scripts/profit-fee-net.py` §FN.1/§FN.4/§FN.5 on `PaperTrade` (isDemo=0,
closed+resolved, 4,890 bets / 12,429 legs), fee `= shares*rate*p*(1-p)` at the implied exit price,
rate 0.05/0.04/0.07, cross-checked against the venue's captured per-market schedule
(`data/fee-sign-flip-report.json`, 99.68% coverage, 2 sign flips).

**Decision rule.** Adopt when the modelled fee is **≥10% of booked PnL** (it is **27.1%** at
bet-level, 20% at leg-level) **and** it changes the rung verdict on **≥1 of the last 30 days** when
re-read net. Below that it is a printed line, not a ledger change.

**Refutation.** If the venue-truth schedule prices the finished book below **$600 (5% of booked
profit)** — or if a 30-day net re-read never flips a rung day — the fee is cosmetic for this
mechanism, the ledger is honest enough at this size, and I withdraw the card and keep the fee as a
one-line print in the EOD.

**Expected effect.** **$0 of new PnL.** It re-prices the only metric that decides advancement: net
edge 8.52 → 6.21 $/1k-cd, STANDARD 3.63 → 1.86, closed legs +1.86% → −0.21%, rung capital
$58.7k → $80.5k. It is ranked first because it is the largest single accounting item measured in
this book's review history — $3.0–3.5k on the finished record, against the largest *lever* measured
in the last two weeks (the band map) at +$1.7–2.4k per 90d — and because every future card
(including #2) is otherwise judged on the wrong number. **Cost: 2h.** Carded as
`fee-booking-net-ledger` (Backlog, Lane A, not approved).

---

## #2 — Judge the band card on the net number; it survives, and no new threshold is needed. Lane B, done this commit.

**Hypothesis.** The pending 10-27 band map's advantage shrinks under the fee by enough to change its
own decision rule (it needs ex-top-10 improvement ≥3pp, which a 10%+ haircut could erase).

**Measurement.** §FN.7, same §AM.7 `strong` constants, notional-neutral, fee scaled with notional:
90d gross delta **+$5,725**, fee delta **+$308**, net **+$5,417** (5.4% eaten); ex-top-10 gross
delta +$1,246 on the same window.

**Decision rule.** The card keeps its existing gate (net delta CI excluding zero on ≥150 forward
shadow legs **and** ex-top-10 ≥3pp) with "delta" read **net of fee** from here on. No threshold is
being moved today.

**Refutation.** If the fee had eaten **≥10%** of the map's delta — my prior — the card's ex-top-10
edge would have been inside its own noise and I would have argued to close it. Measured **5.4%**, so
that claim is **wrong** and I am recording it wrong rather than quietly dropping it.

**Expected effect.** $0 direct; it protects the only profit-producing proposal in the queue
(+$1.7–2.4k/90d net) from being rejected on a fee argument that measures 5%, and it stops me from
proposing a *new* band variant on top of an unapproved one. **Cost: 1h** (re-read the forward shadow
net when it exists; the arithmetic is committed).

---

## #3 — The two existing fee instruments disagree with each other by $1,459 on the same legs. Lane B, fix.

**Hypothesis.** `scripts/c200-fee-reprice-archive.py` and `scripts/fee-sign-flip-test.py` (which
writes `data/fee-sign-flip-report.json`) both charge the exit fee as equal to the entry fee, which
overstates the bill on the closed legs that leave near an extreme, where the fee curve is near zero
by construction.

**Measurement.** §FN.1 prints three bases on the identical 12,429 legs: entry only **$3,038**
(2.24%), entry + exit at implied price **$3,537** (2.61%), entry + exit at entry price **$4,996**
(3.69%). The third basis reproduces the venue report's $4,996.97 — the two instruments agree with
each other and both are on the third basis.

**Decision rule.** Adopt implied-exit pricing in both instruments when the bases differ by **≥10% of
the fee bill** — the exit basis alone moves the bill by **41.2%** against the entry+implied-exit
figure and **64.5%** against entry-only.

**Refutation.** If closed legs clustered at exits near their entry price, `exit ≈ entry` would be
right and the correction would be <5%. The measured exit distribution is bimodal at the extremes
(2,673 legs <0.05, 4,827 ≥0.80), so the simple model overstates by $1,459 — the refutation does not
fire, but this is an instrument correction, not a finding about the market.

**Expected effect.** $0 PnL. It stops a 1.4pp basis disagreement ($5.0k vs $3.5k) from being quoted
as if it were one number, and it is why my bet-level fee line ($1,183) is not a contradiction of the
repo's $5,024 — different population, same law. **Cost: 0.5h** (one function in each script). Carded
as `fee-exit-basis-instruments` (Backlog, Lane B).

---

## Contradictions I am not resolving silently

- **$1,183 vs $3,038 vs $5,024: three fee numbers, one law.** Bet-level (dedupe to one bet per
  wallet/market/outcome) $1,183; leg-level entry-only $3,038; leg-level with exit=entry $4,996. The
  only difference between the last two is the exit basis. Anyone quoting "the book pays $5k of fees"
  is quoting all legs at the wrong-sided exit fee; anyone quoting $1,183 is quoting one fee per bet.
- **0.4–0.6 looks alive on bet weight and dead on dollar weight.** Bet-weighted hit 52.52% clears
  the 51.33% hurdle by 1.19pp; dollar-weighted hit 48.06% loses by 3.27pp, and net ROI is −7.88%.
  The band is dead **because its large legs lose**, not because its small ones do. This is the second
  time in three weeks the weighting choice has decided a sign (the first was the 2026-10-26 dust
  correction, where row-level counted 17× the bet-level figure). Dollar-weighted is correct here: the
  dollars are what we risk.
- **My 8.52 $/1k-capital-day vs the 11-01 brief's 12.09.** Not a disagreement: mine is bet-level,
  11-01's is leg-level, and my leg-level reading is **11.95** — 1.2% apart on a one-day-later book.
  The $/1k-cd unit scales with how many legs carry the same bet; quote the basis with the number.
- **The fee does not flip any rung arithmetic in direction, and the ladder was already 88× short.**
  #1 is not a profit proposal and I am not dressing it as one.

---

**IF YOU WEREN'T HERE:** I would book the fee today, because it is the only item in this book that is
both large (27% of measured edge, $3.0–3.5k on the finished record) and invisible — and because
until it is booked, the ladder gate and the one pending sizing card are both being judged on a number
that a real account would never show. Then I would stop: no band change, no exit rail, no sizing
change, because the net hurdle table shows no band with an edge comfortably above its fee, and the
one axis that might still carry money (the band map) is already carded and waiting on its own forward
shadow.

---

### Provenance

| figure | source |
| --- | --- |
| gross/net ROI, fee %, $/1k-capital-day, per-lane and per-band | §FN.1/§FN.2, `python3 scripts/profit-fee-net.py` |
| hurdle table, dollar-weighted hit, resolved-only | §FN.3, same |
| ladder capital arithmetic, 27.1% haircut | §FN.4, same |
| band map gross vs net, ex-top-10 | §FN.7, same (`--days 90` for the card's window) |
| resolved vs closed split, exit distribution | §FN.5, `sqlite3` on `PaperTrade` |
| three fee bases, $3,038 / $3,537 / $4,996 | §FN.1 |
| venue skill: $4,996.97 venue vs $5,024.02 proxy, 99.68% coverage, 2 sign flips | `data/fee-sign-flip-report.json` (2026-10-22) |
| fee law and rates (0.05/0.04/0.07) | `src/lib/scoring/price-edge.ts::takerFeePerShare`, `categoryFeeRate` |
| §AM.7 `strong` map 2.0/1.5/0.5/0.4/0.2 | `scripts/profit-velocity.py:2854` |

*Lane B applied directly this commit: `scripts/profit-fee-net.py`, this file, and two roadmap cards
(`fee-booking-net-ledger` — Lane A proposal, not approved; `fee-exit-basis-instruments`). Read-only DB
(`immutable=1`) throughout. **No RuleSet row read or written, no rule edited, no PnL row changed.***
