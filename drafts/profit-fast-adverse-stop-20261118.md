# The fast adverse stop: the money is real, but 45% of it is the spread and 68% of it is the $100 clip

**Date:** 2026-11-18 · **Lane A — PROPOSAL. Nothing applied.** No RuleSet write, no `prisma/dev.db`
write, no apply-vNN, DB opened `mode=ro`. The apply step is the operator's, after this read.
**Card:** `profit-fast-adverse-stop` (approval `apr-profit-fast-adverse-stop`) ·
**Source measurement:** `scripts/profit-taker-entry.py` §S10 (`drafts/profit-recs-20261118.md` R1)
**This read:** `scripts/profit-fast-stop-replay.py` (committed with this doc; every figure below re-runs)

Basis, once: regime = `DecisionJournal.ruleSetVersion >= 68`, deduped to the first leg per
`bot|wallet|market|outcome`, non-demo, settled. Re-run at 2026-11-18 17:0x: **450 settled intents,
21.6 days, 250 owned positions / $4,958 of dollars at risk, 200 rows the resolver stamped
`unfilled`**. Cost = `PaperTrade.simulatedPositionSize` (dollars at risk). Exit price = the leg-side
bid at the mark = venue-tape midpoint − half the quoted spread at dispatch. CIs are
market-clustered paired bootstraps on the **delta** (2,000 draws, 210 markets).

---

## Verdict

1. **The lever exists and it is not a tail cut.** Stop at +5m / −8%: **+$630.1 / 21.6 days**, 29 of
   250 legs fired (11.6%), market-clustered CI **[+$269, +$1,048]**, ex-top-3 **+$376**, ex-top-10
   **+$145**, **_0_ of 29 fires cut a winner**, both lanes positive, both halves of the window
   positive. This survives every concentration and stability cut I ran.
2. **But the carded trigger is not the hypothesis.** It is read at the **bid**, and on a cheap leg
   the bid sits 10–30% under the mid before anything moves: **13 of 29 fires never moved 8% on the
   mid at all**, and one fired at −18.4% while the mid was **up 10.2%**. Re-cut on a real move (trigger
   on the mid, exit still at the bid) the delta falls to **+$348.8** (16 fires, CI [+102,+676]).
   That is what the hypothesis is worth.
3. **And 68% of that is the $100 C-200 clip.** Twenty legs at $60–100 carry **+$430.4** of the
   headline (+21.5% per $1 risked); the 227 legs at ≤$25 carry +$195.4 (+7.0%). Normalised to the
   book's natural $13 clip the carded rule is worth **+$239.5 / 21 days (+7.4% of risk)** and the
   honest mid-trigger rule **+$114.6 (+3.5%)** — about **$5/day**, not $30.

**Recommendation: do not apply the carded form.** Ship the write-only mark log (the pre-registered
forward test), scope the rule to entries **0.10–0.40**, read the trigger on the **mid**, book the
exit at the **bid**, and apply only when the forward read clears the bar in §9. The stop is the
third-best lever on these legs: fixing the $100 clip is first, the entry-floor question is second,
and both are substitutes for this rule rather than additive with it.

---

## 1. What reproduces, and what moved

| arm (owned class) | legs | cost | PnL | ROI |
|---|---|---|---|---|
| hold to the leg's own exit | 250 | $4,958 | **−$620.2** | −12.5% |
| with the carded stop (+5m, bid ≤ −8%) | 250 | $4,958 | **+$10.0** | +0.2% |
| **delta** | 29 fired | — | **+$630.1** | +12.7% of risk |

The doc quoted −$600.2 → +$30.0 = +$630.1 on 249 legs. One more leg has settled since
(21.1 → 21.6 days); it moved **both** arms by −$20 and left the delta **identical to the cent**.
So: the headline reproduces exactly; only the two absolute levels moved.

Self-checks from the instrument, all PASS: the stoptable population is **100.0% of owned cost**
(no coverage gap — every position has tape and an exit); **0 of 250** legs are valued at a
convention-zero exit; the “+5m” mark really is a +5m mark (248 legs, age p10 252s / median 264s /
p90 275s, 97% at ≥240s, 0% under 60s); **0** legs' own exit landed inside the 5-minute window, so
no leg is being “stopped” after it had already closed.

## 2. The same rule, four ways — this is the number to argue with

| form | fires | PnL | delta / 21.6d | per day |
|---|---|---|---|---|
| **A** carded: bid trigger, book as sized | 29 | +$10.0 | **+$630.1** | +$29.2 |
| **B** carded form, uniform $13 clip | 29 | — | **+$239.5** | +$11.1 |
| **C** honest: mid trigger, bid exit, book as sized | 16 | −$271.4 | **+$348.8** | +$16.2 |
| **D** honest trigger, uniform $13 clip | 16 | — | **+$114.6** | +$5.3 |

Row A is the card the operator approved. Row D is what the rule is worth on a book that is not
buying $100 of a 0.05 longshot. Rows B and D are the same counterfactual applied to each trigger:
rescale every leg's contribution by `13 / simulatedPositionSize`. Everything in §3–§5 is the
distance between A and D.

## 3. Finding 1 — the carded trigger reads a bid, and a bid is a quote, not a loss

The trigger is `mid(t+5m) − spread/2 ≤ entry × 0.92`. On a 1c-spread token trading at 0.06 the
half-spread alone is **16% of the entry**, so the rule fires with no move at all. Per-leg anatomy
of the 29 carded fires (`C5b`, the full table is in the instrument output):

| entry | +5m mid | mid move | half-spread | trigger reads | final exit | clip |
|---|---|---|---|---|---|---|
| 0.060 | 0.065 | **+8.3%** | 16.7% | −8.3% | 0.000 | $18 |
| 0.059 | 0.066 | **+10.2%** | 28.6% | −18.4% | 0.000 | $100 |
| 0.059 | 0.060 | **+0.9%** | 33.6% | −32.7% | 0.000 | $20 |
| 0.173 | 0.175 | **+1.0%** | 14.4% | −13.5% | 0.135 | $50 |
| 0.240 | 0.105 | −56.3% | 2.1% | −58.4% | 0.000 | $18 |

**13 of 29 fires are spread-only** (the mid did not move 8% against us). They were still *right* in
this window — those legs went to 0.000 anyway — but they were right for the wrong reason, and the
rule that would fire them is not “cut a mover at five minutes”, it is “sell a cheap leg at its
bid”. The band split shows exactly where the two readings diverge:

| entry band | legs | carded delta (bid trigger) | CI | honest delta (mid trigger) | CI | median spread |
|---|---|---|---|---|---|---|
| 0.00–0.10 | 15 | **+$247.4** | [+37,+532] | **+$18.8** | [+0,+48] | 18.4% of price |
| 0.10–0.20 | 29 | +$309.2 | [+80,+580] | +$292.0 | [+63,+564] | 6.5% |
| 0.20–0.40 | 94 | +$76.0 | [+28,+129] | +$40.4 | [+7,+81] | 3.6% |
| 0.60–0.80 | 86 | −$2.4 (1 fire) | [−7,+0] | −$2.4 | [−7,+0] | 1.6% |
| 0.80–1.01 | 26 | $0.0 (0 fires) | — | $0.0 | — | 1.2% |

**$229 of the carded delta — 36% — exists only because the sub-0.10 band has an 18% spread.** That
band is 15 legs of the 250. If this rule ships as written it will *also* fire on the **248 of the
402 currently-open legs that sit under 0.20**, i.e. it will liquidate most of the cheap book
at its bid inside five minutes of every fill. That is not a stop; that is a band exit with a
20–30% haircut, and it needs to be approved as one.

## 4. Finding 2 — 68% of the delta is 20 legs at $100

| clip band | legs | cost | hold | with stop | delta | delta per $1 risked |
|---|---|---|---|---|---|---|
| $0–25 | 227 | $2,808 | −$82.2 | +$113.2 | +$195.4 | **+7.0%** |
| $25–60 | 3 | $150 | −$2.4 | +$2.0 | +$4.3 | +2.9% |
| $60–100 | **20** | **$2,000** | **−$535.6** | −$105.2 | **+$430.4** | **+21.5%** |

The five legs the stop helped most are all $100 `BANKROLL_200` clips at entries 0.053–0.183:
`will-kai-cenat-fin` (+$86.9), `will-bitcoin-dip-t…` (+$85.7), `will-susie-wiles-b…` (+$81.6),
`dota2-frogli-pr1-2…` (+$75.0), `nba-chi-nyk-2026-1…` (+$62.7). Their loss is large *because the
clip is 8× the other lane's*, and the stop converts a −100% into a −8…−20%. **The cheap fix for the
same dollars is not an exit rule, it is not buying $100 of a 0.05 contract** — the
`profit-c200-price-frame-sizing` card's subject. Their deltas are the same dollars twice: run this
stop on a book that clips $13 and it earns **+$114.6, not +$630**.

To be explicit about the ordering: **fixing the clip changes what this rule is worth (it removes
68% of its in-sample delta) without changing whether the rule is right.** The rule is right either
way. That is the case for measuring it, and the case against quoting +$630 as the ladder's lever.

## 5. Finding 3 — 60% of the carded delta is the clock, not the trigger

| arm | PnL | delta |
|---|---|---|
| exit **everything** at +5m, no trigger | −$242.1 | **+$378.1** (248 legs) |
| stop at +5m, −8% trigger (carded) | +$10.0 | **+$630.1** (29 legs) |

Exiting every leg unconditionally five minutes after the fill is worth $378 of the $630. The
**trigger adds $252** over the blanket exit — real triage value, but it means most of the mechanism
is “the marks are better than the entry at five minutes”, not “an 8% move is a signal”. Cross-check
that agrees: **r(+5m mark, final exit price) = +0.557** on 248 legs; the 29 fired legs' mean mark is
0.144 against a mean final exit of **0.030**, while the other legs sit at 0.503 → 0.514. The mark
carries information. It does not carry *this trigger's* semantics.

## 6. What survives, stated fairly

- **Not a tail cut.** ex-top-1 +$543, ex-top-3 +$376, ex-top-5 +$238, ex-top-10 +$145 — all
  positive; contributions are +$632.6 on 28 legs against −$2.4 on **one**.
- **It does not cut winners.** 0 of 29 carded fires, 0 of 16 honest fires, settled at ≥0.995.
  (0 of 29 against a uniform 20% recovery rate would be a 0.16% coincidence, so this is the mark
  being informative, not luck.)
- **Both lanes.** C-200: 125 legs, −$842.3 → −$285.7, **+$556.6** CI [+253,+918]. STANDARD: 125 legs,
  **+$222.1 → +$295.6**, +$73.5 CI [+19,+140]. The stop does not eat the profitable lane.
- **Stable.** First half +$210.8 (8 fires) / second half +$419.3 (21 fires); 13 of 16 grid cells
  positive; the whole 60m row is not (1 of 4).
- **Slippage-tolerant.** −1c on every exit: +$535.9 [+226,+894]; −2c: +$444.1 [+183,+757]. A taker
  fee is not in any row (~0.5c of price at p=0.45, rate 0.02) — the −1c row is the conservative
  proxy for fee + slippage together.
- **The grid was searched.** The quoted cell is the **max of 16 correlated cells** (4 horizons × 4
  thresholds). Its in-sample delta is optimistically biased by construction. That is why §9 is a
  forward bar and not a conclusion.

## 7. The rule I would actually ship

**Trigger** (read every 5 minutes on each open leg in scope):
`mid(t) ≤ entry × (1 − 0.08)` — **the mid, not the bid**.
**Exit:** sell at the bid, book at the bid (`min(bestBid)` from the live book, not the mark).
**Scope:** entry **0.10 ≤ p < 0.40**, both lanes. (0.00–0.10: honest delta +$18.8, and 248 open
STANDARD legs sit there — a separate decision about that band, not this one. 0.40–0.60: the regime
has **zero** settled entries in it (v63 skips it on STANDARD), so no leg can reach the exit there.
0.60–0.80: 1 fire, −$2.4. 0.80–1.01: never reached in-sample, so untested rather than safe.)
**Mark source:** the venue's own book, keyless — verified live from this host today:
`GET clob.polymarket.com/book?token_id=…` → `best_bid 0.402 / best_ask 0.415` on an open leg's
market, and `POST clob.polymarket.com/midpoints` returns a whole batch in one call. **`MarketSnapshot`
is not a candidate:** 655 rows across 90 markets in the last 24h (~7/market/day, 2–10 markets/hour)
— it is a wallet-following universe, not a 5-minute mark.
**Cadence:** a new `*/5` job (`copybot-fast-stop`, lock + `deliver: local`, `failure_deliver:
origin`). One batched `/midpoints` call per tick over the open legs in scope; a `/book` call only
for a token whose mid is within ~3% of its trigger level, to get the true bid for the exit.
**RuleSet fields, all defaulting to OFF** so any ruleset lacking them is byte-identical:
`fastStopMinutes: 0` (0 = disabled), `fastStopAdverseMove: 0`, `fastStopBandMin: 0`,
`fastStopBandMax: 1`, `fastStopLanes: ""`. The live value is applied by `apply-vNN` after the bar
in §9 clears — **not now**.
**Revert:** `fastStopMinutes: 0` (one field) plus disable the cron job. No schema change, no
migration, nothing to unwind.
**Cost:** ~3–4h (the */5 job + the pure predicate + its boundary test + the write-only mark log).

## 8. Why not simply widen it

- **It is not additive with the sizing fix** (§4). Quoting +$630 as a ladder lever while a $100 clip
  is outstanding double-counts the same dollars.
- **It is not additive with an entry-floor either.** The 44 sub-0.20 owned legs hold −$704.1
  between them; the honest stop recovers +$310.8 of that. Not buying them would have avoided more
  than the stop recovers — but that band's calibration edge at the mid is *positive* (the
  `profit-cheap-refusal-ask-price` +13.9pp read, the long-shot shadow's +81.7% on 113 would-admits),
  so it stays an open measurement, not a recommendation here. Flagged because the two levers are
  competing for the same loss, and the doc that proposed this one priced neither.
- **Do not confuse it with the 168h stale exit.** The v66 comment in `src/lib/rules.ts` (“the same
  stop at 0.20–0.40 DESTROYS $1,064”) is about a **168-hour age** cut. This rule is a **5-minute
  adverse** cut and my 0.20–0.40 row (+$40.4 honest, CI [+7,+81]) is a different measurement on a
  different horizon. Neither number adjudicates the other; don't let either comment acquire the
  other's scope.

## 9. The pre-registered forward test (what would make me withdraw this)

Ship the **write-only** half now: on every open leg in scope, append
`{tradeId, openedAt, t, mid, bestBid, bestAsk, age_s}` to `data/fast-stop-marks.jsonl` every 5
minutes, and compute the counterfactual offline. Nothing closes, nothing books, no field is read by
the decision path.

**Apply when** all of:
- **150 forward owned legs** in scope, of which **≥ 15 fired**;
- forward **delta ≥ +$150** with **market-clustered CI excluding zero**;
- **ex-top-3 delta > 0**;
- **trigger rate ≤ 25%** of in-scope legs;
- and the delta computed at the **true bid** (not mid − dispatch spread) is within 40% of the
  delta computed at the modelled bid — if it isn't, the replay's exit price is the story.

**Withdraw if** any of:
- forward delta ≤ 0 at 150 legs;
- trigger rate **> 40%** (firing on noise) or **< 2%** (the rule never reaches);
- ex-top-3 delta ≤ 0;
- the stopped legs' final exits stop being worse than their +5m marks (today: mean 0.030 vs 0.144).
  If that flips, the damage is not accruing *after* five minutes and there is nothing left to save.

## 10. Overridable calls, one line each

- **Scope: entries 0.10–0.40, not all bands** — the sub-0.10 band's carded delta (+$247.4) collapses
  to +$18.8 on a mid trigger; revert to all-bands by setting `fastStopBandMin: 0`.
- **Trigger on the mid, not the bid** — bid-trigger +$630.1 vs mid-trigger +$348.8; revert by
  reading the bid, and re-read §3 first because it will liquidate the cheap book.
- **Book the exit at the bid, not the mark** — every other exit in the book books at the adapter
  mark; this one is an aggressive sell, and booking at the mark flatters it by the half-spread
  (+$743.9 vs +$630.1 on this window). Revert: book `priceForOutcome(m)` as the other rails do.
- **Do not count the stop alongside the clip fix** — at a uniform $13 clip the same rule is +$114.6.
  If the operator prefers to keep the $100 clip, the +$630 stands and this flag is moot.
- **Which lane** — both (C-200 +$556.6, STANDARD +$73.5, both CIs exclude zero). `fastStopLanes`
  scopes it if one should be exempt.

## 11. Reproduce

```
python3 scripts/profit-taker-entry.py                  # the source §S10 cell (7s warm)
python3 scripts/profit-fast-stop-replay.py             # this read: C1–C13, exit 1 on a self-check
python3 scripts/profit-fast-stop-replay.py --selftest  # mark arithmetic, trigger boundary, slippage
python3 scripts/profit-fast-stop-replay.py --lag=900 --thr=0.05
```

Read-only throughout: `mode=ro` connection, no RuleSet read/write, no `prisma` write, no new
network calls (the tape comes from `data/fill-tape-cache`, which the source instrument already
maintains).

**IF YOU WERE NOT HERE:** the +5m stop is real, cluster-significant and cuts no winners — but the
carded version reads its trigger on the bid, so a third of it is the spread and 68% of it is the
$100 clip. Ship the 5-minute mark log, scope it to 0.10–0.40, read the mid, book the bid, and judge
it on 150 forward legs. Expected size of the prize once the clip is fixed: **~$5/day**, not $30.
