# Asset audit — `kmasterfleek/kdreams` (2026-11-07)

**Verdict: WATCH — concept, not code.** MIT, real deterministic code, no keys, CI green. What is
worth taking is a *spec grammar plus a grader* (~200 lines of shape, not their 52 KB), and the three
guards that make a nightly hypothesis honest. We should reimplement it behind our own gates in ~2 h;
we should not vendor anything. One recommendation below is the 2026-10-26 weekly's REC 2, still
unstarted — this audit supplies the concrete grammar it lacked, not a new idea.

Audited by the asset-audit worker, read-only. No clone, no install, no execution of candidate code
(cron constraint), so their suite is graded off the reported CI state, not my own run.

---

## 1. What it is

An **observe-only nightly research loop** over Polymarket and Kalshi: every 15 min it snapshots
top-of-book (with touch sizes) for the 100 highest-volume markets per venue plus 4 pinned pairs, and
records settlements; once a night an LLM (OpenRouter, `GPT-6 Sol`) writes **one falsifiable
hypothesis** with a machine-readable spec, and the *evaluator — not the model — grades it in code*
on data recorded **after** the freeze.

The question it chases is deliberately small: *is there an action that nets ≥1c per $10 (0.1%) after
fees, repeatably?* It never trades and holds no credentials. MIT (`LICENSE`, plain, 1,074 B, no
data carve-out). Created 2026-10-14, ★0, 1 author, 24 days old.

**Anatomy (from the injected block + `gh api`, 2026-11-07):** 224 files; 425 KB `.ts` + 691 KB `.js`
of code, tests present, CI present, lockfile present, **66.8 MB of `.ndjson`** — the code is ~1.6 % of
the repo, the recorded data is the rest. `tests=yes ci=yes`, no `.env.example`, no Docker, no
telemetry, README mentions no key/secret.

**Alive, but only as a data faucet.** Last *code* commit: `2026-11-04T17:43Z` (a watchlist change: the
December Fed pairs, with a per-market Polymarket fee rate read off Gamma). Every commit since is
`data: snapshot <ts>` — one every 15 min. So: no abandonment, no development either. CI on `main`:
`completed/success` at 2026-11-04T17:43Z (last run for the last code change). 6 open issues, all
`github-actions[bot]`-filed hypotheses, 0 comments — the issue tracker is the ledger's mirror, not a
community.

## 2. Verified machinery

Read in full: `scripts/lib/kdreams-metrics.mjs` (17 KB), `scripts/kdreams-backtest.mjs` (18.6 KB, the
evaluator + grader), `scripts/kdreams-nightly.mjs` (28.6 KB, grep + the grading path),
`config/kdreams.watchlist.json`, `docs/dream-cycle/hypotheses.json`, the 2026-11-06 report,
`ADR-0004-statistical-validity-budget.md`. **Re-derived by definition, not by import**, in
`verify_fees.py` (scratch): fee = C × rate × p × (1−p) cents; Kalshi rounds up to the cent per order.

**The spec grammar** (`validateSpec`) — a closed vocabulary, and this is the part worth copying:

- 10 metrics, each typed by what it needs: `spread.{fracOneCent,medianCents}`, `maker.{fillRate,
  roundTripRate,netCentsPerAttempt}`, `pair.{meanAbsCents,fracAbsGt2c,bothSidesFracNetPositive}`,
  `resolution.{netCentsPer10,winRate}`.
- slices: `hoursUtc:[from,to]` (wraps past midnight), `midMin/midMax` (spread and maker only),
  `priceMin/priceMax` + `hoursToClose` (**resolution only** — rejected on other metrics), `op` ∈
  `>`,`<`, numeric `threshold`, optional `minN`.
- **Unknown keys are rejected**, not ignored — no metric, slice or op outside the catalog can enter.
  That is the whole point: a hypothesis that cannot be computed is refused *before* the freeze, and a
  spec that fails validation is frozen as `UNGRADEABLE` rather than silently ungraded.

**The grader** (`measureSpecRows` → `gradeSpec`):

```
need  = max(spec.minN ?? 0, floor)         floor = backtest.retestMinN = 100
value = metric(slice(rows after frozenAt))
n < need            → INCONCLUSIVE
value op threshold  → SUPPORTED : REFUTED
```

`since = h.frozenAt` is threaded into `loadRows`, so **the deciding rows are strictly post-freeze** —
the one property that makes a nightly loop an experiment rather than a story.

**Three guards, and the first is the one we do not have in any form:**

1. **`specRejection`** — a *non-profit* prediction that the pre-freeze baseline **already satisfies**
   is rejected as teaching nothing ("already true before the freeze (X = v on n); a non-profit
   prediction must claim a change from the recorded value"). A *profit* prediction is exempt (it is
   allowed to be already true; that is what it is testing). This is the anti-tautology gate.
2. **`planRetests`** — `minTicks=48` fresh ticks must have accumulated since the freeze before a grade
   is issued; `retestMaxOpen=5` caps open hypotheses; anything frozen before the 14-day backtest
   window is **expired, never graded**.
3. **`scorecard`** — the model sees its own record, including the count of *SUPPORTED grades that were
   already true at freeze and carry no information*. Naming free grades is a rarer virtue than
   counting wins.

**Fee arithmetic — verified against the venue, then reconciled with their own printed numbers.**
Their `takerFeeCents(rate,p) = rate·p·(1−p)·100` is the same curve as our
`takerFeePerShare(price, feeRate)` in `src/lib/scoring/price-edge.ts`, and Polymarket's own docs
(`docs.polymarket.com/trading/fees.md`, read today) state `fee = C × feeRate × p × (1−p)`, makers
never charged. Their report line "Fees at 50c per contract: PM taker 1c / maker 0c; Kalshi taker
1.75c / maker 0.44c; one-cent maker round trip nets 1c PM / 0.13c Kalshi" reproduces exactly:
0.04·0.25·100 = 1.00c, 0.07·0.25·100 = 1.75c, 0.0175·0.25·100 = 0.4375 → 0.44c, 1 − 2(0.4375) =
0.125 → 0.13c. Their Kalshi `Math.ceil(rawFee − EPS)` is right *in cents* per Kalshi's per-order
round-up: $10 at 0.97 = 10 shares, gross 30c, fee 3c, win-net 27c, loss −970c → breakeven win rate
**97.29 %** against a quoted 98 % — so that band's edge is real but thin, and the 0.99 end of the same
band is *negative* (breakeven 99.10 % vs ~98 %). The band's +1.0c/$10 is the 0.97 edge carrying the
0.99 tail.

Their watchlist is more careful than the defaults suggest: `pairs[]` carries `polymarketTakerRate`
per pair, sourced from Gamma's `feeSchedule.rate` — which I confirmed keyless today
(`?condition_ids=0x8a419661…` → `{"rate":0.05,"takerOnly":true,"rebateRate":0.25}`; a politics market
returns 0.04, an esports market 0.05). Their defaults (0.04 PM / 0.07 Kalshi) are **below** the
published table for crypto (0.07) and sports (0.05), so an unpinned market's fee is under-priced —
they flag this themselves in the config comment ("must be re-verified before any edge claim").

**Their own answer to their own question is negative, and they print it** (2026-11-06 report, 14-day
window, 7,713 settled markets recorded):

- Polymarket maker proxy: 92,517 attempts, fill 22 %, round-trip 18 %, **−1.249c/attempt** (gross
  +3,617c, fees 0, **mark −119,161c**).
- Kalshi maker proxy: 81,731 attempts, fill 17 %, round-trip 16 %, **−0.984c/attempt** (mark
  −78,488c).
- Hold-to-resolution, 10 bands: **one net-positive band**, `ks 0.97–0.99` at **+1.0c/$10** (n=289);
  everything else −1c to −42.1c/$10.

That mark is adverse selection, and modelling it is the repo's best instinct: an unexited fill is
marked at the last mid, so a fill that happens *because* the market walked down through your bid is
booked as a loss. (Queue position is excluded — optimistic — and disclosed as a "proxy" in the output
line itself.)

## 3. Fit table vs our stack

Baseline: the Rust sidecar + TS pipeline, `scripts/research-collect.py`, the Prisma book, the
sentiment/ML lanes. Absence claims below were grepped, not assumed.

| Component | In the donor | In ours (verified) | Verdict |
|---|---|---|---|
| Spec grammar + deterministic grader | `validateSpec` / `measureSpecRows` / `gradeSpec` / `describeSpec` | **Absent.** No `data/prereg-registry.jsonl`, no `scripts/prereg-grade.py`. Each dated gate is a bespoke reader (`entry-floor-replay.py`, `gate-winrate-basis-read.ts`, `ml1-gate-read.ts`, `analyze-change2-gates.py` — the last carries one `DECISION_RULE` dict for one gate). No card names it. | ✅ **adopt (reimplement)** — the pending `research-weekly-20261026.md` REC 2 |
| Anti-tautology guard (`specRejection`) | rejects a non-profit spec already true pre-freeze | Absent; and our failure mode is the *inverse* — a frozen threshold guarantees the read cannot move (see §4) | ✅ adopt, part of the same ~40 lines |
| Expiry / max-open / fresh-ticks (`planRetests`) | 48 fresh ticks, ≤5 open, expire before window | Absent as a mechanism; the symptom is live: `data/entry-floor-read.jsonl` is read daily on a population v67 (2026-10-24) made unreachable | ✅ adopt; **no card** — weekly 11-02 §3 fact 5 names the symptom |
| Free-grade scorecard | counts SUPPORTED-but-already-true | Absent — our retros score adopted/refuted, never "was it already true" | ✅ concept, same build |
| Validity budget (ADR-0004) | declared, **`Status: Proposed`**, no implementation found | Absent | ⚪ concept only — we would be taking their unimplemented TODO, and §5 shows the failure it did not prevent |
| Maker spread-capture proxy + adverse-selection mark | `makerSpreadProxy`, 60-min horizon, mtm on unexited fills | We have the real thing on our side: `data/l2` (45,618 token files, 21 GB), `data/c200-printthrough.jsonl` (85 MB), 15.9 M `MarketSnapshot` rows over 48,689 markets. Card `phase-d2-fill-model` (Cox-PH) owns fill modelling. | ❌ not portable for the lane; ⚪ the mark-on-unexited-fill sanity check is worth one line in d2 |
| Collector + `resolutions.ndjson` | 15-min, 100 markets/venue, 4 pinned pairs, 7,713 settled | Our capture is deeper where it counts (5 s top-25 + raw `price_change` stream, pinned on dispatch). We do **not** persist a settled-outcome table (resolutions are fetched at read time), so theirs is the one asset we cannot match from the book — but it is 14 days deep, top-100 only, and overlaps our own window. | ❌ (nothing to gain); flag, do not ingest |
| LLM nightly loop (OpenRouter + Dream Machine, files witnessed issues) | ~$0.02/night, GPT-6 Sol | Duplicates `research-collect.py` + the DeepSeek research bot + local sentiment; adds a hosted-model key and a second prose generator | ❌ not portable (explicitly) |

## 4. Integration proposal

**~2 h, read-only, flag-revertible, no rule touched.** Ship `data/prereg-registry.jsonl` +
`scripts/prereg-grade.py` with the donor's grammar, bound to **our** metric vocabulary (ladder SUM
ex-top-3, lane ROI, fill rate at a parked level, calibration slope, per-gate n) rather than theirs.
Three guards ship with it: reject a spec already true on pre-freeze data (unless it is a profit
claim), refuse to grade below `max(minN, floor)`, and **expire** a registration whose population
cannot move. The dashboard reads it at `/prereg`; the fact sheet prints `open / due / unreadable`
instead of one bespoke line per gate.

The cost is real but small and it is *the* thing 12 days of pending REC has not produced.

**Second lead, no recommendation (nothing in our roadmap asks for it):** the `ks 0.97–0.99`
hold-to-resolution band at +1.0c/$10 is exactly the shape of trade our book never takes (we size out
of 0.40–0.60 and into <0.20). It is measurable on our own 4,238 traded markets in under an hour, but
it is one band out of ten in a 14-day sweep — before any card, it needs a price-only baseline and its
own pre-registration. Flagged, not proposed.

## 5. NOT portable, and the caveats that shape the verdict

- **Nothing here is a deployable component for the live lane.** Not one thing places, prices or sizes
  an order; and the repo's headline finding is that the thing it set out to find does not exist at
  these depths (0.1 %/trade is not there: maker proxy negative on both venues, 9 of 10 resolution
  bands negative). Quote that negative number rather than the star count's absence.
- **Its own 24-night ledger shows threshold drift with no validity budget.** 11 profit predictions
  refuted, 3 supported — and all 3 supported are `pair.bothSidesFracNetPositive`, re-specified five
  times in six days (`>0.03` refuted 10-26, `>0.03` supported 10-28, `>0.1` supported 10-31 and
  11-01, `>0.12` open 11-03). ADR-0004's invariant 2 — "repeated nightly comparisons spend from a
  persistent validity budget rather than resetting alpha every run" — is the exact rule this violates,
  and it is `Status: Proposed`. **Taking their grader without a family budget would import the drift.**
- **`n` is not independent, and the config proves it.** `house-2026-republican` and
  `house-2026-democratic` are mirror sides of one event (their own note: "Mirror of
  house-2026-republican"), so `n=1060` and `n=1071` aligned snapshots are the same ticks counted
  twice, and the `n≥100/300` floor is satisfied by ~50 real observations on two events. Any port must
  cluster by event/market, not count snapshot pairs.
- **A working fee default that is quietly wrong for crypto and sports** (0.04 PM default vs the
  published 0.07/0.05), self-flagged in the config comment but not enforced in code.
- **Git as a time-series database.** 66.8 MB of ndjson re-committed every 15 min into a 43 MB repo;
  cloning it is the slowest part of reading it. On their own runner that is free CI minutes; for us it
  is a reason never to mirror it.
- **★0 and 24 days old**, one author, no external consumers. MIT means the code is borrowable with
  attribution — the *design* is worth more than the code, and the design is 200 lines.

## 6. Recommendation (pre-registration shape)

```
REC — The pre-registration grader the 10-26 weekly asked for, with the donor's grammar
  Hypothesis:   the bespoke gate-read problem is structural, not per-gate: gates keep arriving on dated
                schedules (10-27, 11-06 ×2, 11-15 — research-weekly-20261102 §3) and each needs its own
                script, while data/entry-floor-read.jsonl is still written daily (last row 2026-11-07
                07:15) on a population v67 froze on 2026-10-24. A registry + grader that reproduces an
                existing read numerically would make every future gate a row, not a task.
  Measurement:  implement data/prereg-registry.jsonl + scripts/prereg-grade.py (donor grammar:
                metric/slice/op/threshold/minN, closed vocabulary, reject-unknown-keys) and grade the
                three most recent hand-read gates (entry-floor gate B, kelly-final-read, drift-decay)
                as registrations; compare each graded value to the number the bespoke script printed.
                3 gates, expected n = 1 row each, exact match or documented delta.
  Decision rule: if ≥2 of 3 grades match the bespoke reads to their printed precision (or the delta is
                explainable by rounding/floor) by 2026-11-22, adopt the registry as the only way gates
                are read and delete the daily entry-floor line; else drop the registry and keep
                per-gate scripts.
  Cost:         ~2 h engineering, read-only against existing tables, zero risk to the lane.
  Reversibility: delete scripts/prereg-grade.py + data/prereg-registry.jsonl and restore the fact-sheet
                line; no rule, size or threshold is touched either way.
```

**Card block (NEW card — deliberately new, and unapplied here because this run is read-only and a
sibling session may hold `data/roadmap.json`).** A card is warranted because the 10-26 REC has sat
unstarted and *uncarded* for 12 days: an unregistered ask is exactly what this repo's own
`ADR-0004` demonstrates happens to good intentions (proposed 2026-08-29, unimplemented since).

```json
{
  "id": "prereg-registry-and-grader",
  "title": "Pre-registration as data — spec registry + deterministic grader + expiry",
  "column": "Backlog",
  "effort": "2h",
  "gate": "grade 3 hand-read gates numerically by 2026-11-22; adopt only if ≥2 match",
  "tags": ["measurement", "evaluation-hygiene", "asset-audit"],
  "note": "AUDIT INPUT (2026-11-07, concept from kmasterfleek/kdreams, MIT; drafts/asset-audit-kdreams-20261107.md): closed metric vocabulary (metric/slice/op/threshold/minN, unknown keys rejected); grader computes max(minN,floor) and returns SUPPORTED/REFUTED/INCONCLUSIVE on strictly post-freeze rows; three guards worth taking — reject a non-profit spec already true pre-freeze, require fresh ticks since freeze + cap open hypotheses + expire registrations whose population cannot move, and count SUPPORTED-but-already-true as no-information in the scorecard. Do NOT take their metric list (top-of-book spreads/maker proxy) or their thresholds; bind to our ladder/ROI/fill/calibration metrics. Known donor defect to avoid: 24 nightly tests with no validity budget → threshold drift on pair.bothSidesFracNetPositive (>0.03 refuted 10-26, supported 10-28, >0.1 supported 10-31/11-01); add a family budget or fix thresholds per registration. Originates from research-weekly-20261026 REC 2 (PENDING, NOT STARTED as of 11-02)."
}
```

**Side finding for the fee cards (not a recommendation):** our `data/fee-schedules.jsonl` captures the
venue's real per-market `feeSchedule.rate` for 48 markets — last captured **2026-09-28**, tagged by
the writer itself `"capture_only","not_read_by_live_path"`. So the gap is not "we cannot get the rate"
(it is keyless, per market, live today) but that the capture is 40 days stale and unwired; the live
path still prices the keyword proxy, which has **no geopolitics entry** (venue rate 0, our default
0.05). Maps to `fee-booking-net-ledger` (Backlog). The donor adds only a confirmation that the field
is keyless and per-condition_id.
