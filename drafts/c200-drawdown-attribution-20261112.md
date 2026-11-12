# C-200 drawdown halt — attribution and the three options

**Card:** `t_02fb099d` (LANE A, from `t_1b33d26a`) · **Written:** 2026-11-12T16:51Z (10:51 CST)
**Nothing was applied.** No RuleSet row, no write to `data/c200-drawdown.json`, no
`prisma/dev.db` write, no booking column touched. The C-200 lane is still halted as of this read.

---

## The answer (option C, the measurement this card said to take first)

**The 32% drawdown is not a drawdown. It is a ledger restatement with the watermark never re-based.**

Commit **`d974287`** ("ledger-price-side: the 233-row repair is applied", 2026-11-11 12:43:23 CST)
re-priced 233 legs to their sibling-complement price and posted
**`BANKROLL_200 realizedPnl 8,913.40 → 5,069.51`** (delta **−$3,843.89**) and cash
`9,603.64 → 5,759.75`. The realized drawdown watermark `realizedPeak = $11,068.58` was set on
2026-11-09/10 from the *pre-repair* ledger and nothing re-based it.

So the gate is now comparing a repaired net worth to an unrepaired peak. Every dollar of the
"drawdown" is the repair; **zero is trading loss.**

The card's own clue was the tell: settled PnL 11-10 → 11-12 was **+$425 net**, so the gap could
not have opened through settlements — and it did not. It opened in **one monitoring cycle**, and
that cycle is the repair.

---

## 1. The discontinuity, measured

The monitor prints `[DRAWDOWN-SHADOW]` every cycle; 7,464 runs carry a realized-NW reading.
Across that whole series, the single largest one-cycle change is this one:

| boundary (local) | realized NW from | to | step |
|---|---|---|---|
| **2026-11-11T12:32:43 → 12:43:43** | **$10,813** | **$6,970** | **−$3,843** |
| 2026-09-25T12:29:15 → 12:40:15 | $4,299 | $4,099 | −$200 |
| 2026-09-25T13:35:15 → 13:46:15 | $4,099 | $3,899 | −$200 |
| 2026-09-21T14:33:14 → 14:46:15 | $3,657 | $3,527 | −$130 |

The largest step is **19.2× the next largest** — the signature of a single-event re-basing, not a
settlement batch. (For scale: the worst genuine settlement *minute* in the lane's whole history is
−$365.81, and a leg's maximum possible loss is its ~$10–100 clip.)

The two runs either side of the repair, verbatim:

```
=== run 2026-11-11T12:32:43 ===
[DRAWDOWN-SHADOW] basis=realized 2.3% (peak $11069, NW $10813) ...
Scoring complete: 0 paper copies ... 7 skips ...

=== run 2026-11-11T12:43:43 ===
[DRAWDOWN-SHADOW] basis=realized 37.0% (peak $11069, NW $6970) ...
[RISK-GATE] nba-was-ind-... drawdown gate [realized] (net worth $6970 vs peak $11069 = 37.0% > 20%)
[PRE-LOOP HALT] 0 copies this cycle — 1 candidate(s) vetoed by a PORTFOLIO gate ...
```

Same book, no trades settled between those two runs (settled PnL for the day is +$451.52 net, all
before the repair) — and the drawdown read **2.3% then 37.0%**. The first `[PRE-LOOP HALT]` in the
log is at **2026-11-11T18:43Z = 12:43 CST — the same cycle**. 81 halt runs since; last leg on
either lane is `BANKROLL_200 2026-11-11T18:10:56Z`.

Cross-check against the ledger, not the log: reconstructing NW from `PaperTrade` settlements at the
12:32:43 instant gives **$6,969.51** while the monitor observed **$10,813** — a **+$3,843.49**
divergence that is the posted delta to the cent, and it closes to **+$0.49** one cycle later.

## 2. What the book actually looks like on the repaired ledger

| | value |
|---|---|
| principal (unchanged since the era began) | $1,900.00 |
| `BotBankroll.realizedPnl` | $5,631.94 |
| `PaperTrade` ledger sum (2,819 settled legs) | $5,631.94 (drift $0.00) |
| **corrected high-water mark NW** (2026-10-18T19:10:41Z) | **$7,987.32** |
| realized NW now | $7,531.94 |
| **corrected drawdown today** | **5.70%** |
| corrected max drawdown since the realized basis began (1,057 settle events) | 13.53% (2026-11-11T08:40:53Z) |
| whole-life corrected max drawdown (Aug, when the gate read MTM) | 28.62% |

Two facts follow, and both matter for the decision:

1. **The watermark $11,068.58 is above anything the repaired ledger has ever produced.** It implies
   cumulative realized PnL of $9,168.58; the ledger's own peak cumulative PnL is $6,087.32. The
   watermark sits **$3,081.26 above the book's best-ever running total**.
2. **On a clean ledger this gate would never have fired in its own era.** Its corrected max drawdown
   since 2026-09-18 is 13.53%, under the 20% cap. The gate is not protecting the book from anything
   right now; it is freezing it on an accounting event.

Reproduce both arms with the instrument shipped alongside this note:

```
python3 scripts/c200-drawdown-attribution.py      # S1 state · S2 watermark provenance · S3 step scan
```

## 3. Why the lane cannot restart itself (this is the part to read before choosing A)

The gate does not wait for a bad book to recover; it waits for a watermark that only ratchets up:

- `scripts/score-trades.ts:158-160` — `realizedPeak` is floored at principal and **raised** to
  `realizedOnlyNW`; there is no path that lowers it.
- `scripts/apply-v56-drawdown-basis.ts:102` — `--reseed-peak` sets
  `realizedPeak = Math.max(realizedNW, st.realizedPeak)`. **The documented reseed lever is inert for a
  downward re-base**: running it today would rewrite `peak` and leave `realizedPeak` at $11,068.58,
  and the lane would stay halted with a fresh `updatedAt` to make it look fixed.

So "A — let the gate stand" is not a wait, it is a lottery with a closing date:

| what would have to happen | value |
|---|---|
| gap to clear ($8,854.86 − $7,531.94) | **+$1,322.92** |
| C-200 open legs / notional | 11 / $427.64 |
| mark-implied expected gain from all 11 | +$50.56 |
| legs whose maximum payoff alone could clear the gap | 3 |

| leg | entry | max payoff | implied P(hit) | venue time-to-resolution |
|---|---|---|---|---|
| Broncos win 2027 NFL championship | 0.050 | $1,902.40 | 5.0% | ~221d (≈ Jun 2027) |
| Maduro leader of Venezuela, end-2026 | 0.067 | $1,393.88 | 6.7% | ~131d (≈ Mar 2027) |
| Chang San Cheng, Taoyuan mayor | 0.069 | $1,340.09 | 6.9% | ~20d (≈ 29 Nov 2026) |

The other eight legs together max out at **$394.08** — they cannot clear the gap at all.

**P(self-clear) ≈ 17.5%**, earliest possible **≈ 2026-11-29**, most likely **Q1 2027**. If none of
the three hits, the lane is halted permanently under A, because net worth can only rise through
entries and the gate forbids entries.

## 4. Blast radius — the halt is not C-200-local

The drawdown gate is classified as a **portfolio gate** (`isPortfolioGate()` matches
`/drawdown gate|gross exposure cap/`) and it fires before the per-bot leg loop, so a C-200
accounting artifact stops **both** lanes. Measured:

```
SELECT COUNT(*) FROM PaperTrade WHERE openedAt > <2026-11-11T18:43:00Z in ms> GROUP BY botId;
-- no rows: zero legs on BANKROLL_200 *or* STANDARD since the halt
```

STANDARD holds **409 open legs / $4,483.12 notional** (unrealized −$18.57) and has no defect in
this story. It is idle because C-200's *peak file* says so. Worth stating plainly: whichever option
is chosen, the lane that actually carries the book is currently governed by the other lane's
measurement error.

## 5. The options, priced

### A — let the gate stand
Entries stay halted until realized NW ≥ $8,854.86. Nothing to implement.
- Cost: both lanes idle ≥17 days at best, ~17.5% chance of ever clearing, and no compounding path
  in the meantime (the book has not opened since 11-11T18:43Z).
- Applies to reality: the "drawdown" being respected does not exist. This option pays an artifact
  the deference of a real loss.
- **Verdict: not recommended.**

### B1 — re-base the watermark to the corrected high-water mark ($7,987.32) ← **recommended**
- Drawdown 32.0% → **5.70%**; gate clears immediately on the next cycle.
- Keeps the gate honest: the book is still shown **5.7% below its real best**, and the halt line
  moves from $8,854.86 down to a $6,389.86 floor, so a genuine 20% drawdown from here still halts.
- Blast radius: the exposure cap does **not** move (it is NW-linked): $3,815.97 unchanged.
- Needs a lever that does not exist yet (see §3): a small script that recomputes the peak from the
  ledger and refuses a hand-typed value.

### B2 — re-base the watermark to *today's* net worth ($7,531.94)
This is what the 07:00 tuning review proposed (as `c200-realized-peak-rebase`, using a stale
$7,548.21).
- Drawdown → **0.00%**; gate clears.
- Cost: it silently forgives a **real 5.7% retracement**, and it makes the watermark a function of
  *when someone happened to look* — the same defect that froze both lanes twice under the MTM basis
  in September. A 20% drawdown from a Monday reading and a 20% drawdown from a Friday reading are
  different rules.
- **Verdict: works, but B1 gets the same unblock without discarding a real loss from the record.**
  B1 differs from B2 by only the 5.7pp of headroom; that headroom is the only part of this that was
  ever real.

### B3 — raise `maxDrawdownPct` (20% → ~40%)
Clears the halt (32% < 40%) without touching the peak. Rejected: it leaves the phantom in place,
buys the unblock with a rule change that also applies to **future real** drawdowns, and would need
another bump the next time a restatement lands.

### The figure diff for B1 (what moves if approved)

| figure | before | after |
|---|---|---|
| gate drawdown (realized basis) | 32.0% | **5.70%** |
| clearing line (`realizedPeak × 0.8`) | $8,854.86 | **$6,389.86** |
| C-200 exposure cap | $3,815.97 | $3,815.97 (unchanged) |
| dashboard `peak` on :3013 (MTM) | $11,458.63 | $11,458.63 (**unchanged**) |

That last row is a deliberate disclosure: the dashboard's peak axis is the **MTM** peak, not
`realizedPeak`, so :3013 will still show a ~33.8% drawdown after B1 while the gate reads 5.7%. The
MTM peak is *also* contaminated — 2,484 pre-fix `PnlSnapshot` marks still carry the sibling pnl
(residual 11.3 of the repair). Re-basing MTM is a separate, larger job and is **not** part of this
card.

## 6. Refutation

This recommendation is wrong if any of these hold:

- **The repair itself was wrong.** If the 233 legs were re-priced to a level that is not the correct
  outcome side, the post-repair ledger is the artifact and the peak was right. The repair shipped
  with `scripts/verify-ledger-price-side.py` (233/233 post image, class 0 inverted of 12,785
  fill-bearing rows) and a pre-image manifest; re-running the verify is the check, and it has not
  been re-run here.
- **A real drawdown hides behind the artifact.** If realized NW on the repaired ledger fell >20%
  from its corrected peak, B1 would not clear and the halt would be correct. Measured: 5.70% today,
  13.53% max since the basis began — so B1 does clear. If those two numbers are ever both above 20%,
  this note is stale.
- **The gate is not what is holding entries.** After any re-base the next `[DRAWDOWN-SHADOW]` must
  report a drawdown under 20% and a `paper_copy` must appear within ~24h. If the halt line persists
  with a low DD, a second gate is binding and this analysis addressed the wrong organ.

## 7. State, at write time

```
realizedPeak = 11068.58   basis = realized   basisDeclaredAt 2026-09-18T10:05:42Z
principal 1900.00   realizedPnl 5631.94   cash 7104.30   NW 7531.94   DD 32.0%
halts in log: 81   first 2026-11-11T18:43Z   last leg on either lane 2026-11-11T18:10:56Z
```

**Revert:** nothing to revert — this card applied nothing. The only commits it adds are the
report-only instrument (§2 command) and this note.

## 8. What to say if you want it applied

Say **B1** (or B2) and the following ships as one Lane A change, with the before/after printed and a
single reverting command:

1. `scripts/reseed-realized-peak.py --to <value>` — recomputes the corrected peak **from the ledger**
   and refuses if the argument disagrees with its own calculation, writes `realizedPeak` + a `note`
   + a fresh `basisDeclaredAt`, and refuses a second run (exit 2) unless `--force`.
2. Nothing else: the gate reads the file each cycle, so no RuleSet version is needed for the peak
   (the *threshold* would need one; this does not touch it).
3. Verification: the next `[DRAWDOWN-SHADOW]` line shows the new drawdown, `[PRE-LOOP HALT]` stops,
   and the first post-halt leg appears in `PaperTrade` — which also unblocks `t_1b33d26a`'s
   outstanding "leg opened after 2026-11-12" clause and lets the STANDARD fill chain stamp it.
