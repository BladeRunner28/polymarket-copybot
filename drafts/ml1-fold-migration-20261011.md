# Fold-owner migration — one implementation, and enforcement that can see what it bans

**Card:** `ml-doctrine-time-and-era-splits` (7-day verify half) · **Date:** 2026-10-11
**Approval:** "Do the migration and then I approve starting on the fit" (the second half of my own
offer to take items 1 → 2 together)

---

## 1. Key insight

The card's remaining work was written as "7 fold owners still to migrate". That list was a
**guess from filenames**, and it was wrong in both directions:

- of its 8 entries only **3** had fold logic at all (`mode_split()` splits a parquet scan,
  `vendor_split()` splits wallets by category share — neither is a fold);
- **2 real owners were not on it** (`pilot-score-separation.py`,
  `pilot-score-separation-papers.py`, both re-deriving the market-blocked fold arithmetic inline).

So the migration could not have been finished by working the list: the list had to be replaced by
detection. `scripts/check-split-doctrine.py` now **discovers** owners from fold *evidence* —
fold-count constant, fold array, per-fold slicing, holdout/purge language, call into a split helper
— and requires each discovered owner to be either wired to `scripts/lib/splits.py` or marked
`split-doctrine: compliant-inline` inside the owning function's docstring, with a justification the
checker **echoes on every run**. An unaccounted owner fails the build; there is no list to forget
to update.

Second insight, found while writing the rule: the first version of the inline-arithmetic ban used a
pattern that cannot see nested parentheses, so it **missed `zlib.crc32(r["market"].encode()) %
K_FOLDS` — precisely the shape the rule exists to ban.** A rule that cannot fail on the thing it
names is prose with a regex. Fixed, and the red/green probe uses the nested form.

## 2. What changed

- **`scripts/lib/splits.py`** — new `keyed_holdout(keys, frac, hasher)`; `hasher="crc32"` (default,
  the shared assignment that matches the TypeScript `crc32()`) and `hasher="sha256"` kept as an
  explicitly documented legacy path for the one caller whose published numbers depend on it.
- **`scripts/fit-fill-model.py`** — its private `hash_split` now delegates to
  `splits.keyed_holdout(..., hasher="sha256")`. The hasher is pinned on purpose: the published U1
  read (18,763 test cells, Brier-vs-flat) was fit with that assignment, and switching it to `crc32`
  would silently rewrite a published number. A time-ordered re-read of that model is a **separate
  decision**, not a migration side effect.
- **`scripts/pilot-score-separation.py`**, **`scripts/pilot-score-separation-papers.py`** — the
  market-blocked 5-fold and the inner 3-fold CV assignment now call `splits.assign_blocked_fold`;
  `import zlib` dropped in both (it existed only for this).
- **`scripts/fit-price-edge.py`** — its last inline inner fold moved onto the helper (the fold
  *designs* already were).
- **`scripts/shadow-expectancy-model.py`** — **not migrated, on purpose**, and now says so in code:
  its walk-forward re-builds the eligible training set *per row* (`closed <= prediction time`),
  which is **stricter** than the shared window-level purge; and its artifact
  (`data/shadow-score-model.json`) is read by the live `kalshi-shadow.py` lane, so an
  equivalent-but-not-identical re-implementation would silently rescore a live lane.
- **`scripts/check-split-doctrine.py`** — owner-list guess removed; detection added; inline
  `crc32(...) % k` banned; `compliant-inline` exemption requires a marker **inside the owning
  function's docstring** plus ≥100 chars of justification, printed in the report.

## 3. Evidence

**Fold arrays are element-identical on the real inputs** — not on a synthetic stand-in. Read
through each script's own SQL and row filters:

- `pilot-score-separation`: 7,910 rows / 3,473 markets, k=5 → folds `{0:1567, 1:1646, 2:1618, 3:1414, 4:1665}`; inner k=3 identical.
- `pilot-score-separation-papers`: 11,219 rows / 3,591 markets, k=5 → `{0:2037, 1:2267, 2:2698, 3:2133, 4:2084}`; inner k=3 identical.
- Fuzz: 75,000 strings (including unicode and 0x-hex keys) × k ∈ {2,3,5,7,10} → identical.
- `fit-fill-model.py`: full re-run of the d.02@300s fit — **logloss byte-identical (0.39333)**,
  every coefficient and z identical (band z 4078.98, band² −4774.53), markout block identical.
  The Brier block differed; since Brier is a function of the same y/p/w on the same 18,763 cells it
  *cannot* move while logloss is fixed — that delta predates the edit. Confirmed: this artifact is
  the one file the Oct-10 regeneration sweep missed (siblings read 0.104/0.156 and 0.135/0.193,
  matching the re-run's 0.121/0.182). Published artifact restored, so no churn landed.
- `fit-price-edge.py`: full re-run reproduces `data/score-spec-v1.json` and `-eval.json` with
  **only `created_at` / `generated_at` moved** (both published copies restored afterwards).

**Checker state (green):** `python3 scripts/check-split-doctrine.py` → exit 0, "scanned 61
script(s) … 5 fold owner(s): 4 on the shared helper, 1 justified inline, 0 unaccounted".

**Checker teeth (red, deliberately induced, then removed):**

- inline `zlib.crc32(r["market"].encode()) % K_FOLDS` → `FAIL … re-derives the fold arithmetic inline` (exit 1)
- `from sklearn.model_selection import KFold` → `FAIL … random/row-level fold API` (exit 1)
- an owner with neither helper nor marker → `FAIL … no compliant-inline marker` (exit 1)

**Suite:** `npx tsc --noEmit` clean; `npx vitest run` → **471/471 in 41 files**.

## 4. Reality checks

- **Nothing published moved, nothing live was touched.** No rule, threshold, size, RuleSet or
  published metric changed; the only edits are *where* the fold arithmetic lives.
- **This is not "time-ordered everywhere".** `fit-fill-model` and both pilot scripts still use
  **keyed** (grouped, non-time-ordered) holdsouts — the helper's docstring now labels that
  explicitly as not a substitute for a temporal split, and the fill model's report says so. Making
  the fill model time-ordered would rewrite a published read and is carded as a separate decision.
- **The scan is `scripts/*.py` at top level.** `scripts/lib/*.py`, nested dirs and the TypeScript
  fit/eval path are not covered by this checker; `scripts/ml1-gate-read.ts` implements its own
  frozen-boundary holdout and self-calibrates against the recorded bar instead.
- **`compliant-inline` is an honest escape hatch, not an enforcement.** Its value is that the
  justification is printed on every run, so a second exemption is visible at review time. Today
  there is exactly one.

## 5. Verdict

Migration half **done**: one shared implementation, 5 owners by detection, 0 unaccounted, proven
behaviour-preserving on real inputs, and enforcement that fails red. 7-day verify clock starts
2026-10-11 (re-check on/after 2026-10-18: checker still exits 0 with 0 unaccounted owners).

**Next (approved):** run a **fitted** candidate through the ML-1 harness — the gate is executable
(`npx tsx scripts/ml1-gate-read.ts`) and now needs a model to judge, not more prose.

*Reproduce:* `python3 scripts/check-split-doctrine.py` ·
`./venv-calib/bin/python scripts/fit-price-edge.py` ·
`./venv-calib/bin/python scripts/fit-fill-model.py --delta 0.02 --horizon 300` · `npx vitest run`
