# Kelly-window staging — kellyFraction + λ̂ refit (approved 2026-09-19, staged)

**Status: STAGED — nothing in the trading path changed by this document.**
Answering the 2026-09-18 Kelly-window report offer: *"I can stage a RuleSet proposal
(kellyFraction or band cap) or a λ̂ refit card."* User replied **"I approve"**.

The 2026-09-18 report's offer named two levers and one card. What shipped here, and what
the one-word triggers are:

| # | Item | State |
|---|---|---|
| 1 | Band cap on the losing mid band | **ALREADY LIVE** (v57 change B, applied 2026-09-19 06:38) — recon correction, see §1 |
| 2 | kellyFraction proposal | **STAGED as `scripts/apply-v58-kelly-fraction.ts`** (no default action) — recommendation: **HOLD at 0.5** |
| 3 | λ̂ refit card (Oct 1) | **CARDED** — `kelly-oct1-lambda-refit-capture`, pre-registration in §4 |
| 4 | `[KELLY-RAIL]` log label | **FIXED** (observability only, `scripts/score-trades.ts`) |

---

## 1. Recon correction — the band cap is already live

The offered "band cap" is not a new proposal: **v57 change B** (2026-09-18 C-200 daily
report, user-approved same day) widened `applyKellyBandRails` in `src/lib/paper.ts` from
`[0.40,0.60)` to **`[0.20,0.60)`** — Kelly admits in the 0.20–0.40 band are capped at the
legacy-equivalent size, exactly the instrument the report was offering to stage.

* Live in the working tree (uncommitted at time of writing), `tsc` clean, 22/22 tests pass.
* RuleSet **v57 active** (`longshotDriftPct=0.08`); `data/premium-calibration.json` unchanged.
* Applied 06:38 local today; newest main-lane Kelly row opened 04:17 local, so **the rail has
  not fired in production yet** — its first `[KELLY-RAIL]` line is still pending. Provisional
  verification: `grep '\[KELLY-RAIL\]' logs/cron/copybot-monitor-score.log` on the next run that
  admits a 0.20–0.60 copy.

**Counterfactual replay of the rail over the whole window** (`scripts/kelly-window-counterfactual.ts`,
read-only; PnL is linear in position size at a fixed entry price, so the replay re-scales each
row by `railedSize/bookedSize`):

* 0.20–0.40: 31 rows, **28 changed**; stake $1,125 → **$547**; realized −$427 → **−$164**
* <0.20: 34 rows, **0 changed**; $2,488 staked, realized **+$988** (rail inert — Kelly > legacy-equivalent)
* 0.40–0.60 / 0.60–0.80 / ≥0.80: 0 rows

So the rail as written cuts the losing band's stake 51% and its booked loss 62%, and does not
touch the profitable band. That is the correct scope — which is the whole argument in §3.

**Label fix:** the `[KELLY-RAIL]` line still printed a two-way label
(`currentPrice >= 0.4 … ? "dead-zone cap" : "long-shot floor"`), so a 0.20–0.40 **cap** logged
as a "long-shot floor". Corrected to a three-way label (`dead-zone cap` / `mid-band cap (v57-B)` /
`long-shot floor`). Log-only; no behavior change. This is the line the Oct 8 attribution reads.

## 2. What the window actually says (measured today, 09:0x CDT)

Main-lane Kelly = `DecisionJournal.ruleSetVersion >= 49`, short-TTR lane excluded.

| band | rows | avg size | settled | realized | open |
|---|---|---|---|---|---|
| <0.20 | 34 | $73.2 | 29 | **+$988.16** | $487 |
| 0.20–0.40 | 31 | $36.3 | 24 | **−$427.36** | $326 |
| 0.40+ | 0 | — | — | $0 | $0 |

**Decision-level (deduped one row per wallet|market|outcome) — the sample that decides anything:**

| slice | decisions | staked | realized | mean ROI | t | bootstrap 95% | MDE |
|---|---|---|---|---|---|---|---|
| all main-lane | 37 | $2,799 | +$560.80 | +11.5% | +0.30 | [−0.51, +0.92] | 1.06 |
| <0.20 | 23 | $2,000 | +$988.16 | +50.1% | +0.86 | [−0.45, +1.76] | 1.63 |
| 0.20–0.40 | 14 | $799 | −$427.36 | −51.8% | **−2.21** | **[−0.89, −0.02]** | 0.66 |

This inverts the report's framing in one important way: the dollar loss sits in the mid band,
and the mid band is the **only** slice whose interval excludes zero. The long-shot profit is
not yet significant on 23 decisions (sd 2.79 — long-shot ROI is fat-tailed). Both are small-n;
neither is a verdict. The Oct 8 read carries both.

**Regime split (the band was not a black hole before Kelly):** main-lane 0.20–0.40 under
journal v<49 = 214 rows / 78 decisions, $1,242 staked, **+$17.46** (flat, ~$5.8/trade).
Same band in the window: −$427 on 31 rows (~$36/trade). The band's entry edge did not change
(all-time excess +6.4pp, z=+2.37 — a pooled stat that has failed regime splits before); the
**stake did**.

**Where the loss concentrates:** 0.20–0.25 → 19 rows, avg $24.9, avg conf 0.47, −$150.63
(ROI −35%); 0.30–0.40 → 12 rows, avg $54.3, avg conf 0.60, −$276.73 (ROI −43.2%). Both
halves negative → the band, not just its expensive half. Kelly sizes rising with price inside
the band, so the biggest stakes sit in the worse half.

**Overlap with the already-approved Oct 8 gate:** all 31 window rows have `confidence < 0.80`
(max 0.75). The approved mid-price gate (block C-200 entries in [0.20,0.60) unless conf≥0.80)
would have blocked **31/31** of them; its carve-out (conf≥0.80) is 3 rows all-time at −$0.51.
So the two instruments act on the same population with different mechanisms — the rail *shrinks*
it now, the gate *stops* it on Oct 8. If the gate ships, the rail becomes moot for this slice;
the rail is the mid-window interim.

## 3. kellyFraction — staged, recommendation HOLD

`scripts/apply-v58-kelly-fraction.ts` (no flag → prints state + consequences, exits 2, writes
nothing; `--fraction=x` alone = dry run):

| entry price | λ̂ | f* (full Kelly) | size @0.5 | size @0.35 | size @0.25 |
|---|---|---|---|---|---|
| 0.05 | −0.789 | 0.154 | $68 | $47 | $34 |
| 0.10 | −0.789 | 0.235 | $88 | $72 | $52 |
| 0.15 | −0.789 | 0.297 | $88 | $88 | $65 |
| 0.25 | −0.204 | 0.092 | $40 | $28 | $20 |
| 0.30 | −0.204 | 0.106 | $47 | $33 | $23 |
| 0.35 | −0.204 | 0.120 | $53 | $37 | $26 |

Computed through the real `kellySizeForCopy` at the live bankroll ($879 = cash $2,122 − open
$1,243; `maxBankrollPct` 10% ⇒ **$88 binds before `maxSizeUsd` $100**).

**Why hold:**
1. `kellyFraction` is a **global** multiplier — it scales the <0.20 band (the only positive one,
   +$988) and the 0.20–0.40 band together. The defect is band-specific.
2. It is also **dominated in its own target band**: fraction 0.25 would still book $20–26 in the
   0.20–0.40 band, while the v57-B rail already holds it at **$17.99**.
3. The one slice that would justify a global cut — a negative long-shot band — has not happened
   (+50.1% mean ROI, est. +$988).
4. Freeze classification: a sizing change **needs an explicit override** (Kelly window Sep 8–Oct 8
   pre-registers "no rule/sizing/live-lane changes"; only the λ̂ refits Sep 15/Oct 1 are pre-authorized).

Use it only if the <0.20 band itself turns negative before the close.

## 4. λ̂ refit — pre-registration for the Oct 1 refit

Next scheduled `copybot-calibrate-premium` run: **Oct 1, 06:00** (biweekly 1st/15th) — 7 days
before the window close, pre-authorized as a system-under-test refresh, not a change.

Current table (Sep 15 refit): `[0,0.2) −0.789` · `[0.2,0.4) −0.2042` · `[0.4,0.6) +0.0341` ·
`[0.6,0.8) +0.2142` · `[0.8,1.01) +0.2906`.

What to capture at that refit (card `kelly-oct1-lambda-refit-capture`):
1. **Sign flips**, which move behavior with no human in the loop: if λ̂(0.2,0.4) turns ≥ 0, Kelly
   skips the band outright (`f* ≤ 0`) 7 days before the close; if λ̂(<0.20) rises toward 0,
   long-shot sizes shrink proportionally. Record the per-band Δ before/after.
2. **Attribute by `ruleSetVersion`, not by the Oct 8 total** — the refit writes no RuleSet, but
   it changes admits/sizes, and v57 change A (drift tolerance) landed mid-window too.
   `python3 scripts/analyze-calibration.py --since 2026-09-15` (writes its own
   `calibration-analysis-since-*.json`, never clobbers the daily report's canonical file).
3. **Rails-only-bind-at-refit rule** (v51): the band rails are inert while λ̂ keeps the dead zone
   at f*≤0 and long-shots funded — the refit is when they can start biting.

## 5. One word per item

* Nothing further needed for the band cap — it is live; its first production `[KELLY-RAIL]` line
  is the open verification item.
* **"apply the fraction cut"** (+ the value, e.g. `--fraction=0.25 --confirm`) → applies v58.
  Not recommended (§3).
* Everything else stays queued to the **Oct 8 close** (mid-price confidence gate,
  0.60–0.80 band gate, drift-counterfactual decision).

## 6. Caveats

* n = 14 settled decisions in the band; the bootstrap CI (−0.89, −0.02) only just excludes zero
  and 6 bands were inspected — treat as a strong prior, not proof.
* The rail replay assumes a size-invariant exit path; true for this paper ledger (no slippage,
  `pnl` linear in `S`), false for any live venue.
* $487 open in <0.20 and $326 open in 0.20–0.40 settle before the close and can move both rows.
* The report's own state line (cash $2,506) predates today's opens; live bankroll is $879 available.

## 7. Reproduce

```bash
DATABASE_URL="file:./dev.db" npx tsx scripts/kelly-window-counterfactual.ts   # §1 replay + §3 sizing table
DATABASE_URL="file:./dev.db" npx tsx scripts/apply-v58-kelly-fraction.ts      # no-flag probe (exit 2, writes nothing)
DATABASE_URL="file:./dev.db" npx tsx scripts/kelly-window-report.ts daily     # the cron report's own data
sqlite3 -readonly prisma/dev.db "SELECT version, json_extract(rulesJson,'$.kellyFraction') FROM RuleSet WHERE active=1;"
```
