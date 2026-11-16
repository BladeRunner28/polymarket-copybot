# Exclude already-decided entries from the ML training population

**Status: LANE A PROPOSAL — NOT APPLIED.** Approval `apr-training-exclude-already-decided-rows`
(card `training-exclude-already-decided-rows`). Nothing in this document has been merged, no
`apply-vNN.ts` was run, `prisma/dev.db` was not written, and the tree is byte-identical to how it
was found (`training_data.csv`, `data/ml1-fit-candidate.json`, `data/ml1-gate-read.json` restored and
sha-verified). The one file added is the read-only instrument
`scripts/ml-already-decided-read.py`, which re-derives every number below.

---

## 1. Verdict

| Question | Answer |
|---|---|
| Is the class real? | Yes — **239 of 5,869 rows (4.07%)** entered at a detection price ≥ 0.995, 87.4% of them labelled wins, at a mean net-entry PnL of **−$0.019/leg** |
| Does the approved change remove them? | **No.** The column it filters on holds **0 rows** in the training population — its first value is 2026-11-15T03:29:59Z and only 24 acted legs exist since |
| What does remove them? | The column **plus** the pre-epoch fallback (scored price, then the detection print): **−239 rows**, y-rate 53.0% → 51.5%, mean net-entry +$1.020 → +$1.064 |
| Does anything published move? | **No candidate's verdict changes.** The bar's own comparator on the fit population is unchanged (AUC 0.7143 / Brier 0.2182); the frozen bar population is untouched (1,060 test rows, 0.7292 / 0.2110) |
| Recommendation | Apply the **ordered** basis, **after** the dedupe, with `ML_EXCLUDE_ALREADY_DECIDED=off` as the no-code revert |

The two things the naive patch would get wrong, both measured in §4: a `WHERE`-level filter
**swaps** decided legs for other decided legs instead of removing positions, and the export's
frozen-baseline reconciliation prints `DRIFT` by construction unless the baseline is scoped too.

---

## 2. What exists, and what does not

- `DecisionJournal.alreadyDecidedAtEntry` (`prisma/schema.prisma:182`,
  `alreadyDecidedAtEntry Boolean @default(false) // priceAtDecision >= 0.995`) is written at the
  scoring site via `decisionProvenanceFields()` (`src/lib/decision-provenance.ts:73`) and shipped
  2026-11-14 as Lane B on card `data2-per-decision-provenance`.
- The **exclusion** does not exist. `scripts/export-training-data.ts` builds the population from one
  `$queryRaw` (line ~226) and never mentions the column: the training book is
  `PaperTrade JOIN DecisionJournal JOIN ObservedTrade`, `status IN ('closed','resolved')`,
  `isDemo = 0`, then `dedupeFirstPerPosition()` (first leg per bot|wallet|market|outcome).
- So a leg entered at 0.998 is still a training row whose label is ~87% predetermined and whose net
  edge is −$0.019. That is the dilution the card names.

---

## 3. Measured basis — population, clock, level

**Population:** `training_data.csv` as re-exported for this measurement at 2026-11-16T17:00Z
— **5,869 rows**, decision_at 2026-07-15T18:27Z .. 2026-11-16T10:29Z. (The 05:35 chain artifact
carried 5,866; the three extra legs settled during the day and change no arm count.) **Level:**
`ALREADY_DECIDED_PRICE = 0.995` (`src/lib/decision-provenance.ts:27`). **Clock:** as of
2026-11-16T17:00Z.

Four arms, because a filter can key on any of them and they are *not* the same population:

| Arm | n | share | y=1 |
|---|---|---|---|
| population | 5,869 | 100.0% | 53.0% |
| `alreadyDecidedAtEntry` | **0** | 0.0% | – |
| `priceAtDecision` ≥ 0.995 | **0** | 0.0% | – |
| `detectedPrice` ≥ 0.995 (legacy) | **239** | 4.07% | 87.4% |
| `entryPrice` ≥ 0.995 (ours) | 241 | 4.11% | 87.1% |

Mean net-entry PnL: population **+$1.020**; the 239-row detection arm **−$0.019** (sum −$4.51,
mean booked entry 0.997).

**Why the column arm is zero, stated as a clock rather than as a dead writer.** 377,107 journal rows
carry 202 flagged rows and 1,620 rows with `priceAtDecision`; the flag's epoch is
**2026-11-15T03:29:59Z**, 24 acted legs exist since it, and none has reached `closed`/`resolved` yet.
The export can only hold terminal legs, so a column-only filter is a no-op until that cohort settles.
This is the same "n = 0 because of the population, not because of the effect" trap: the approved
diff, run against today's book, prints **`dropped 0 of 5869`** and writes a byte-identical CSV.

**The shape of the class is not what the card implies.** All 239 rows were decided on
**2026-07-15T18:27Z .. 2026-07-16T14:30Z**, all under `ruleSetVersion 2`, all in era
`pre-kelly-v1-48`, and **239 of 239 sit inside the frozen train window** (decision_at < 2026-08-21).
So the class is a two-day burst at the very start of the book, not a diffuse live phenomenon — which
is why the fix can only ever touch what the fit *learns*, never which rows it is *judged on* (§5).

**Threshold sensitivity** (detection print): ≥0.990 → 322 rows (5.5%); ≥0.995 → 239 (4.1%);
≥0.999 → 5 (0.1%). The 0.995 line is the already-shipped policy constant, not re-chosen here.

---

## 4. Two constraints the patch has to respect (both measured, both get it wrong if ignored)

### 4a. The filter must run AFTER `dedupeFirstPerPosition`, not in the SQL `WHERE`

The dedupe keeps the FIRST leg per position key in `openedAt` order, and the export filters in SQL —
i.e. **before** the dedupe. Removing a first leg there promotes a later duplicate leg into the
population instead of removing the position:

| Fact | n |
|---|---|
| keys whose excluded first leg has a later closed/resolved leg | 119 |
| …whose later leg is *itself* already decided | 112 |
| …whose later leg is not | 7 |

A `WHERE`-level filter would therefore swap 112 keys for another already-decided leg (mean booked
entry 0.997 — same class, different row) and re-admit 7 under a different leg. Post-dedupe filtering
makes the unit the **position**, which is what "the market was already decided when we entered" means.

### 4b. The frozen-baseline reconciliation must be scoped, or it drifts by construction

The export reconciles itself against `data/decision-dataset.manifest.json` (generated 2026-09-13,
3,516 rows) on positions settled at or before that timestamp. **149 of the 239 excluded rows sit
inside that scope**, so an unscoped subtraction makes three of the four checks fail the moment the
filter drops anything — the same defect class the fee-truth `proxy-only scope` fix repaired in
October. With the scope applied (mode `ordered`):

```
rows: dataset 3363 vs export 3363 OK
proxy-only scope: 3363 positions reconciled | truth-bearing: 4 positions, $2.14 gross
                  | already-decided (excluded from the check): 149 positions, $-5.24 gross
```

The remaining three `DRIFT` lines are **pre-existing** and unchanged in magnitude (§8).

---

## 5. Dry run — every figure that moves, and the ones that must not

Run end to end in this tree, `mode=off` then `mode=ordered`, same clock, artifacts restored after.

**Export (the population):**

| Figure | off | ordered | Δ |
|---|---|---|---|
| rows | 5,869 | 5,630 | −239 |
| y_net_entry = 1 | 53.0% | 51.5% | −1.5pp |
| mean pnl_net_entry | +$1.020 | +$1.064 | +$0.044 |
| sum pnl_net_entry | $5,986.85 | $5,991.36 | +$4.51 |
| pre-kelly-v1-48 rows | 3,762 | 3,523 | −239 |

No other era moves (exposure-v58plus 1,264 / kelly-window-v49-57 843 in both), no column is added,
no label is recomputed.

**Fit + gate (`ml1-fit-candidate.ts`, `ml1-gate-read.ts`, default splits):**

| Figure | off | ordered |
|---|---|---|
| train n / test n (time split) | 2,300 / 3,082 | 2,155 / 3,082 |
| purged train rows | 487 | 393 |
| price-only on fit population | AUC 0.7143 / Brier 0.2182 | **identical** |
| frozen bar population | 1,060 test, 0.7292 / 0.2110 | **identical** |

Candidate arms, time split (test n unchanged at 3,082):

| Candidate | ΔAUC vs price, off | ΔAUC vs price, ordered |
|---|---|---|
| C1 price+stored | −0.0043 | −0.0047 |
| C2 price+exec | −0.0160 | −0.0128 |
| C3 price+combined | −0.0138 | −0.0080 |

Every candidate still **loses** to price on AUC (the bar is `≥ price + 0.0005` with a CI excluding
zero), and C0's Brier barely moves (0.2171 → 0.2165). On the era-stratified holdout the same holds
(C1 −0.0051 → −0.0027, P(>) 0.074 → 0.185; C3 −0.0090 → −0.0075, P(>) 0.028 → 0.051). **No verdict
flips, nothing crosses the bar.** That is the expected shape: the exclusion removes 145 train rows
and 0 holdout rows, so it can only change what is learned, never what the model is scored on.

---

## 6. Exact change

`scripts/export-training-data.ts` only. Three hunks; the whole change is inert at
`ML_EXCLUDE_ALREADY_DECIDED=off`, which is why the default is a one-word revert.

```diff
+import { isAlreadyDecided } from "../src/lib/decision-provenance";
@@ $queryRaw
            d.ruleSetVersion, d.simulatedPositionSize AS decisionSize,
+           d.alreadyDecidedAtEntry, d.priceAtDecision,
@@ after the dedupe
-  const rows = dedupeFirstPerPosition(
+  const dedupedAll = dedupeFirstPerPosition(
     raw.map((r) => ({ botId: ..., walletAddress: ..., marketId: ..., outcome: ..., raw: r }))
   );
+  const excludeMode = String(process.env.ML_EXCLUDE_ALREADY_DECIDED ?? "off").toLowerCase();
+  if (!["off", "column", "ordered"].includes(excludeMode)) {
+    throw new Error(`ML_EXCLUDE_ALREADY_DECIDED must be off|column|ordered (got ${excludeMode})`);
+  }
+  const isDecidedRow = (r: any): boolean => {
+    if (r.alreadyDecidedAtEntry === 1 || r.alreadyDecidedAtEntry === true) return true;
+    if (excludeMode !== "ordered") return false;
+    const scored = num(r.priceAtDecision);
+    if (scored !== null) return isAlreadyDecided(scored);
+    return isAlreadyDecided(num(r.detectedPrice));
+  };
+  const rows = excludeMode === "off" ? dedupedAll : dedupedAll.filter((x) => !isDecidedRow(x.raw));
+  const alreadyDecidedDropped = dedupedAll.length - rows.length;
```

Two supporting edits, both required by §4 and both invisible when nothing is dropped:

- the `Exported …` line reports `deduped` and `excluded N already-decided legs` separately, so the
  duplicate-accumulation count cannot appear to jump by 239;
- the reconciliation block subtracts `decidedSums` from the manifest side and prints
  `already-decided (excluded from the check): N positions`.

The basis is **ordered, never OR'd**: `alreadyDecidedAtEntry` → `priceAtDecision` → `detectedPrice`.
The flag and the scored price cannot disagree (both come from `decisionProvenanceFields()`), so the
order only decides what happens to a pre-epoch row, which has no scored price and only the detection
print to go on.

**Rollback (e):** `ML_EXCLUDE_ALREADY_DECIDED=off npx tsx scripts/export-training-data.ts` and the
CSV returns to the 5,869-row book byte for byte (verified: sha `70e3b0f1…` both ways). `training_data.csv`
is a committed artifact, so the revert is *code + re-export*; reverting only the code leaves a stale
filtered file behind.

---

## 7. Failure modes this change must be able to fail — pre-registered

1. **The exclusion's own effect must stay train-side.** If a future run shows a candidate's ΔAUC vs
   price crossing +0.0005 *because* of this flag, that is a fit-side artifact and not evidence of
   anything — the holdout row set is identical by construction (test n 3,082 both ways today).
   Refutation: any test-n change attributable to the flag.
2. **The exclusion must not silently drop more than it says.** `dropped` on the report line and
   `before − after` row counts must agree; a gap means the dedupe-ordering trap (§4a) has reappeared.
3. **The fallback must not invent decidedness.** A row with a scored price below 0.995 but a detection
   print above it must be KEPT (`ordered`, not OR). Refutation: such a row appearing in the exclusion
   list.
4. **The reconciliation must still reconcile.** Rows check must stay `OK`; if a future change makes it
   drift *differently* than the three pre-existing lines below, the scoping is wrong.

---

## 8. Behaviour that is broken already and is NOT this card's business

Reproduced with the pristine `HEAD` script, in the same minute, byte-identical CSV:

```
rows: dataset 3512 vs export 3512 OK
pnl_gross:     dataset $1065.75 vs export $1075.89 DRIFT
pnl_net_entry: dataset  $295.95 vs export  $306.41 DRIFT
pnl_net_full:  dataset  $167.47 vs export  $178.40 DRIFT
```

The export's reconciliation already reports **3 DRIFTED checks on HEAD** (~$10.46 on
`pnl_net_entry` inside a 3,512-position frozen scope). This proposal neither causes nor fixes it —
folding it in would make an approval of one change carry a decision about another. Suggested separate
card: *"the ML export's frozen-baseline reconciliation has drifted $10.46 on pnl_net_entry for an
unknown number of nights; find the math delta or retire the check."* A check that always says DRIFT
is the same defect class as a probe that cannot fail.

---

## 9. Open items for the operator

- **Scope (the one decision this asks for).** The approval names the column only; that is a measured
  no-op today. Recommendation: apply `ordered` (§6). If you want the literal approved scope instead,
  the same patch ships with `ML_EXCLUDE_ALREADY_DECIDED=column` — it drops 0 rows and the proposal's
  numbers in §5 then describe a future population, not today's.
- **Default.** Recommend the merge sets the default to `ordered` so the next 05:35 chain run applies
  it; the env knob stays as the revert. (The dry-run code as written defaults to `off`.)
- **Nothing to decide about the threshold** — 0.995 is the already-shipped constant; the sweep in §3
  is there so the neighbour values are on the record.

---

## Reproduce

```bash
python3 scripts/ml-already-decided-read.py                       # §3, §4 numbers
# §5 (dry run): patch as in §6, then
ML_EXCLUDE_ALREADY_DECIDED=off     npx tsx scripts/export-training-data.ts
ML_EXCLUDE_ALREADY_DECIDED=ordered npx tsx scripts/export-training-data.ts
npx tsx scripts/ml1-fit-candidate.ts && npx tsx scripts/ml1-gate-read.ts
```

Artifacts of the dry run (both arms, logs + JSON) are kept at
`~/.hermes/cache/scratch/lanea/` for this session.
