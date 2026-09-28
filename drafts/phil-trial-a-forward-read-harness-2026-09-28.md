# phil Trial A — pre-registered shadow-read harness (built 2026-09-28)

Pulled forward from `drafts/phil-audit-2026-09-28.md` (§"Shadow-trial proposal",
Trial A). phil's repo is the clearest available demonstration of *why* our
doctrine exists — its sealed forward test returned −0.0730 with 145% of the P&L
in one bet — and the three mechanisms worth taking were the ones that would have
caught it. This is mechanism (a)+(b): one read convention and one pre-registered
pass/fail rule, applied to the shadow feeds we already mark to settlement.

**Nothing live changed.** No RuleSet version, no threshold, no gate, no size, no
published number. The harness is a pure function plus a report script; no live
path imports it for a decision.

Artifacts: `src/lib/shadow-read.ts` (harness), `tests/shadow-read.test.ts`
(14 tests), `scripts/shadow-forward-read.ts` + `npm run shadow:forward-read`,
results appended to `data/shadow-forward-read.jsonl`.

---

## The convention (and why it is fixed before reading)

| criterion | rule | caught failure mode |
|---|---|---|
| (a) | `cw_return = roi − stake-weighted SE > 0` | a positive average that is smaller than its own error |
| (b) | no single bet ≥ 50% of **positive** P&L | phil's actual failure: 1 bet = 145% of the P&L |
| (c) | market-**clustered** bootstrap 95% CI on roi excludes 0 | many rows sharing one resolution read as independent evidence |
| (d) | same sign inside **each** `ruleSetVersion` era | era-averaging hiding a regime flip |

Plus the sampling rules: `< 15` bets is **"too few decisions to price the gate"**
— never a verdict (phil's `MIN_BETS`); `< 150` settled per arm is
**underpowered** — criteria reported, but a low-n pass is not promotion evidence
and a low-n fail is not a rejection. phil's own read was 60 bets and one bet
dominated it; that is the sample these rules refuse to judge.

Entry convention is deliberately borrowed from the lane summaries so the numbers
are comparable: `entry = candidate.currentPrice`, `stake = stakeUsd`,
`return = (settledValue − entry)/entry`, with the approved dust floor (0.10,
tuning #29 rec 1) applied and the excluded count reported.

---

## What it returned on today's data — SMOKE, not the Oct 8 read

The pre-registered window closes **2026-10-08**. These rows are tagged
`mode: "smoke"` so a smoke number can never be quoted later as the pre-registered
result. They are still informative, and one of them is material.

**late_drift_gate — FAIL** (settled 3,297; 2,662 bets after dust; 492 markets)

- roi **−4.05%**, se 1.63% → cw_return **−5.68%** · (a) FAIL
- top bet 1.36% of positive P&L → (b) PASS
- clustered CI **[−18.6%, +9.2%]** → (c) FAIL
- era signs: v55 **+2.03%** (n=2,200) · v56 −46.0% (220) · v57 −19.1% (40) · v58 −33.5% (76) · v59 −14.7% (91) · v60 −13.8% (35) → (d) FAIL

**min_confidence_gate — FAIL** (settled 521; 504 bets after dust; 125 markets)

- roi **+39.3%**, se 6.15% → cw_return +33.2% · (a) PASS
- top bet 1.49% of positive P&L → (b) PASS
- clustered CI **[−17.3%, +95.3%]** → (c) FAIL
- era: single era (v60) → (d) PASS

---

## The material finding: the minConfidence shadow headline is 91% one dust row

Cross-check first, because it is what makes the rest trustworthy: the harness
reproduces the lanes' own incumbent summaries exactly — drift `marked=3297` /
`dustExcluded=635` and lowconf `marked=521` / total `$22,034.85`, to the cent.

Then the split:

- lowconf headline (dust-inclusive): **$22,034.85** over 521 marked rows
- of which **17 dust rows (entry < 0.10) carry $20,052.22 — 91% of the total**
- and **one row carries $19,990 of that** — entry **0.0005** on
  `cs2-fokus-sng2-2026-09-21-game2`, i.e. a 20,000× return on a $10 stake
- honest read: **504 non-dust bets, $1,982.63, roi +39.34%**

**The late-drift lane got a dust floor in tuning #29 rec 1 (2026-09-19, approved)
and the minConfidence lane never did.** Its headline is therefore dust-dominated,
and a 0.0005 fill is not executable at any size on this venue — the same reasoning
that rec used. This is exactly the failure phil's criterion (b) exists to catch,
found here on our own data before the Oct 8 read rather than after it.

Note the harness's (b) passes for lowconf once the dust floor is applied (top bet
1.49%) — the dominance problem IS the dust row. Both guards were needed to see it.

## Reality checks

- **The era split is DERIVED, not recorded.** No shadow row carries its
  `ruleSetVersion`; the harness reconstructs it from `RuleSet.createdAt`
  intervals and labels nothing below v49 (the regime convention). So criterion
  (d) is currently "verifiable by reconstruction", which is weaker than phil's
  per-decision `strategy_rev`. Writing the version into shadow rows is the
  prerequisite for the Oct 8 read (carded).
- **Small-era caution:** the drift lane's negative eras have n=35–220, while v55
  holds 2,200 of 2,662 bets. (d) failing is real — the sign genuinely is not
  consistent — but the negative eras are individually too thin to carry a claim
  of their own. The pooled result is what it is: cw_return negative, CI spanning 0.
- **The clustered CI is wide by construction**, because per-bet returns on
  longshots are heavy-tailed (a 0.15 entry settling at 1.0 is +567%). That is the
  point of clustering on markets, not a defect: it is why the lowconf lane's
  +39% ROI does not yet clear its own interval.
- **Rows are not deduped across wallets**: four rows on
  `cs2-lavked-navij1-2026-09-21-game2` share an identical outcome. They are
  distinct would-have decisions (different wallets), so they stay — clustering on
  the market is what keeps them from counting as four independent draws.
- The drift lane's incumbents disagree with the raw pooled number for the same
  reason the lowconf one does; the ex-dust drift read (−0.41/trade ≈ −4.1% on $10
  stakes) matches the harness's −4.05% roi, so the two are consistent.

---

## Status and next

- **Harness: built, tested (14 tests, each pinning one criterion plus the kill
  rule), and run against live shadow data.**
- **The Oct 8 pre-registered read: not taken.** It runs at the window close with
  `--preregistered`, after shadow rows record their own `ruleSetVersion`.
- **Not done, deliberately:** no lane behaviour changed, no summary was edited,
  and the lowconf dust finding is reported, not applied — editing a published
  lane summary is a decision for the operator, not a side effect of building a
  harness.
