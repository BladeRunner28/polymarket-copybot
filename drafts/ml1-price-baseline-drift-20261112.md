# ML-1 promotion bar — the absolute AUC/Brier were population-specific, and price-only fails its *own* bar

Card: `ml1-price-baseline-drift` (medusa t_e0f7c159, approval `apr-ml1-price-baseline-drift`).
Measured 2026-11-12 with `scripts/ml1-bar-restatement.ts` → `data/ml1-bar-restatement.json`.
Status: **bar restatement already in force (815ecda, 2026-10-28); the audit-trail instrument was
corrected today and this card is closed.** No threshold, rule, size or published gate state moved
in this session.

---

## 1. The finding, in one sentence

`0.729 / 0.212` were never a standard — they are **price's own read on one population**
(`data/decision-dataset.csv`, 2026-09-13: 0.7285 / 0.2115) rounded to three decimals. Applied as an
absolute threshold to the population the fit actually uses (`training_data.csv`), they stop meaning
"beat price" and start demanding the *distance between two different populations' price reads*.
That is not a strict gate, it is an unfalsifiable one.

## 2. What is enforced today

| | |
|---|---|
| Form | **RELATIVE** (`BAR.form = "relative"`, `src/lib/ml1-read.ts`) |
| Rule | `AUC >= price + 0.0005` AND `Brier <= price + 0.0005` |
| Comparator | price-only, recomputed **on each arm's own scored rows** (`readArms()`, lines ~401-402) |
| Also required | market-clustered 95% CI on ΔAUC excluding 0, plus the money arm (top tercile vs copy-all) |
| Since | 815ecda, 2026-10-28 (operator-approved restatement) |
| Absolute 0.729/0.212 | printed **reference line only**, never enforcement |

## 3. Measured today (both populations, frozen holdout at 2026-08-21, label `pnl_net_entry > 0`)

| Population | test n / markets | price AUC / Brier | the *retired* absolute bar would demand |
|---|---|---|---|
| `data/decision-dataset.csv` (where the constants were cut) | 1,060 / 783 | 0.7292 / 0.2110 | −0.0002 AUC, Brier ceiling 0.0010 above price |
| `training_data.csv` (where the fit happens) | 3,054 / 2,333 | 0.7143 / 0.2182 | **+0.0147 AUC headroom, and a Brier ceiling 0.0062 BELOW price's own** |

The second row is the whole finding: on the file the model is fitted on, the retired form asked for
a Brier no candidate can reach without being *better calibrated than price itself*, plus 1.5pp of
AUC headroom. The slack check still passes (`0.7285 + 0.0005 = 0.7290`, `0.2115 + 0.0005 = 0.2120`
≈ 0.729 / 0.212), so the derivation of the constants is correct — what was wrong was carrying them
across populations. Population drift since 2026-09-13 is reported separately (+0.0007 AUC / −0.0005
Brier on the bar file; the export has grown from n=1,055 to n=1,060).

## 4. The measured half: price's ranking power is era-dependent, so the pooled number hides the work

New in today's output — the per-era price-only AUC is now printed beside the pooled figure:

| Population | pre-kelly-v1-48 | kelly-window-v49-57 | exposure-v58plus | pooled |
|---|---|---|---|---|
| decision-dataset | 0.7592 (n=754) | 0.6265 (n=306) | — | 0.7292 |
| training_data | 0.7406 (n=975) | 0.6749 (n=843) | 0.6849 (n=1,236) | 0.7143 |

Both artifacts agree on the direction: price got **worse at ranking** as sizing changed. So "beats
price by 0.0005" is ~0.06 AUC of skill apart depending on which era a candidate is judged in, and a
single pooled threshold silently re-weights the eras by how many legs each contributes. Any future
comparator read that quotes only the pooled number is quoting a mixture.

## 5. AUC is not money (recorded on the card; not re-derived in this session)

`scripts/ml1-gate-read.ts` money arm on the fit file, as recorded on the card: top tercile selected
by `entry_price` returns **−$1.97/leg** vs copy-all (2026-10-29 read; CI [−4.43, +0.04] — it spanned
zero on that read, where the 2026-10-27 read was −$2.39 with CI [−4.96, −0.20] excluding it).
Selection scores look *mildly positive* (+$1.63 / +$1.79 per leg) on intervals that span zero. The
instrument that ranks best is not the instrument that makes money, which is why the bar keeps the
money arm as a second conjunct rather than promoting on AUC alone. Re-running `ml1-gate-read.ts`
would refresh these; it is deliberately out of scope here because it rewrites
`data/ml1-gate-read.json`.

## 6. Nothing is promoted

Every stored arm is below price on the fit population today (in-force relative verdict):

| arm | AUC | vs price 0.7143 | in-force verdict |
|---|---|---|---|
| entry_price (the comparator) | 0.7143 | — | **fails by construction** (cannot beat itself + slack) |
| detected_price | 0.6999 | −0.0144 | fails |
| entry_timing_score | 0.5448 | −0.1695 | fails |
| copy_score | 0.5250 | −0.1893 | fails |
| wallet_quality_score | 0.5127 | −0.2016 | fails |
| thesis_score | 0.4811 | −0.2332 | fails |

## 7. The instrument defect this session actually fixed

After 815ecda the audit trail kept printing the **retired** absolute form as `IN-FORCE` and the
in-force relative form as `NOT IN FORCE`, and its artifact note said "BAR in `src/lib/ml1-read.ts`
is unchanged. Proposal … (awaiting-approval)" — while the same JSON carried
`inForceBar.form = "relative"`. Two consequences, both real:

- `entry_price` printed as **clearing** the in-force bar on the bar population (it clears the
  *absolute* 0.729/0.212 there), which is precisely the reading the card exists to refute: price-only
  **fails its own bar** on every population, by construction.
- a reader of the gate's own headers (`src/lib/ml1-read.ts`, `scripts/ml1-gate-read.ts`) saw
  "clearing AUC >= 0.729 AND Brier <= 0.212" as the rule in force.

Fixed in the same commit: both entry headers restated to the relative form; the script now prints the
enforcing form, the retired form as a labelled reference, per-arm verdicts under **both**, the
comparator recomputed on each arm's own scored rows, and per-era price AUC; the artifact `note`
matches the `enforcement` block it ships beside. Exit code is still 1 when the slack derivation stops
reproducing the constants.

## 8. Verification

- `npx tsx scripts/ml1-bar-restatement.ts` → exit 0, artifact rewritten, slack reproduces 0.7290 / 0.2120.
- `npx vitest run tests/ml1-bar.test.ts` → 7/7 pass (including "a candidate identical to price fails on the AUC leg" — the property that makes price-only fail its own bar).
- `npx tsc --noEmit -p tsconfig.json` → no new errors (one pre-existing, unrelated: `scripts/apply-v73-c200-cheap-band-clip.ts`).
- `data/roadmap.json` re-parses; card `ml1-price-baseline-drift` → `Done` with the fresh numbers in `dates`/`note`.

## 9. Rollback

- This session's changes: `git revert <commit>` — comment/print corrections + the roadmap card state, no behaviour change.
- The bar itself (if ever needed): one edit in `src/lib/ml1-read.ts` — set `BAR.form` back to
  `"absolute"` and restore the two literals as enforcement. Nothing in this session touches that.
- The restatement step can be dropped from `scripts/ml-daily.sh` without affecting enforcement.

## 10. What would refute the relative bar

A candidate that clears `price + 0.0005` on the same rows **with** a ΔAUC CI excluding 0 but fails
the money arm (top tercile vs copy-all) — i.e. AUC rising while money does not. That would say the
relative bar is still the wrong target and the money arm should become the *primary* conjunct. As of
today no arm clears the AUC leg at all, so that test is not yet live.
