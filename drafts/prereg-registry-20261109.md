# Pre-registration registry + deterministic grader — dated gates grade as rows

**Card:** `kdreams-prereg-registry` · **Date:** 2026-11-09 · **Lane:** B (instrument) · approved 2026-11-09 in thread
**Built:** `data/prereg-registry.jsonl`, `scripts/prereg-grade.py`, `data/prereg-reads.jsonl`, `data/prereg-adoption.json`
**Verdict:** **ADOPTED** — 3 of 3 hand-read gates reproduce (rule: ≥ 2 of 3 by 2026-11-22).
**Candidate:** `kmasterfleek/kdreams` (MIT, concept only). Its engine was **not** ported: its maker proxy is
−1.249¢/attempt on Polymarket and −0.984¢ on Kalshi, and 11 of its 14 predictions were refuted in the audit.
What was taken is the spec grammar — a closed metric vocabulary, a freeze date that actually cuts the data,
and guards that make "no information yet" a state rather than a silence.

---

## 1. What this instrument is

A gate is a sentence that can be wrong: *"the sub-$0.05 cell is loss-making at n ≥ 60"*, *"the price-side
inversion still carries the book"*, *"this 7-day window clears $1,750"*. Today each of those lives as a
bespoke script that re-decides its own population, clock, and sample size on every run — so a gate still
accumulating evidence and a gate whose population stopped moving weeks ago produce **the same output**.

The registry makes a gate a record. One JSONL line per gate:

| field | meaning |
|---|---|
| `id` | slug, unique |
| `frozen_at` | ISO date/datetime. Rows at or before it are **never** graded |
| `metric` | one of the closed vocabulary (§2) |
| `venue` | `Polymarket` / `Kalshi` / `all` |
| `slice` | structured population filter (closed key set) |
| `op`, `threshold` | the comparison |
| `min_n` | the sample the author demands |
| `state`, `last_n`, `reads` | written by the grader (everything else is immutable) |

The grader recomputes every metric from `prisma/dev.db`, appends one read row to
`data/prereg-reads.jsonl`, and rewrites only those three mutable fields. **History is append-only**: each
read stores the value, the sample, the verdict and a `spec_sha`; a spec edited after freeze shows
`MODIFIED` on its next read instead of silently re-basing the gate.

## 2. The guards (each one blocks a specific known lie)

| guard | what it prevents | where |
|---|---|---|
| **closed vocabulary** | a typo'd `minN` or `slices` silently changing the population | metric / spec-key / slice-key allowlists; unknown → `REJECTED`, exit 1 |
| **strictly post-freeze** | grading the data that inspired the spec | row clock must be **>** `frozen_at`; date-only freezes are local midnight |
| **`max(min_n, FLOOR)`** | buying a verdict with n=1 | declared floor per metric (e.g. `roi` 30, `inverted_share` 100, `pnl` 20) |
| **`UNGRADEABLE`** | a null or a zero reading as a result | n below the bar, or an undefined metric, is a state |
| **reject spec already true pre-freeze** | an after-the-fact gate that cannot fail | predicate true pre-freeze with n ≥ bar → `REJECTED_PRE_TRUE` |
| **SUPPORTED-but-already-true = no-information** | "PASS" carried by a handful of pre-freeze legs | pre-true with n < bar, then SUPPORTED → `NO_INFORMATION` |
| **`FROZEN`** | waiting forever on a population that never moves | population `n_all` unchanged across ≥ 7 consecutive graded reads |

`FROZEN` overrides `UNGRADEABLE` / `SUPPORTED` / `NO_INFORMATION` (those verdicts depend on the population
growing). It never overrides `REFUTED`: a completed window that failed has already said everything it can.

Metric vocabulary (closed): `legs`, `pnl`, `roi`, `hit_rate`, `mean_entry`, `inverted_legs`, `inverted_share`,
`inverted_pnl_share`, `fill_reach`, `unfilled_pnl_share`. Slice keys (closed): `bot`, `status`, `clock`,
`ruleSetVersionMin`, `entryMin`/`entryMax`, `fillBasis`, `fillStatus`, `since`/`until`, `dayBasis`.

## 3. Adoption rule — 3 of 3 hand-read gates reproduce

`python3 scripts/prereg-grade.py adopt` re-derives each spec's hand read through the generic engine on the
**all-rows** basis (the basis the bespoke scripts used) and compares value and sample:

| gate | metric | hand read | grader | delta | n hand / grader | source of the hand read |
|---|---|---|---|---|---|---|
| `entry-floor-a` | `roi` | −0.5518 | −0.551797 | 0.0000034 | 31 / 31 | `data/entry-floor-read.jsonl` (gateA_roi / gateA_n) |
| `price-side-inversion` | `inverted_share` | 0.0422 | 0.042234 | 0.0000337 | 2131 / 2133 (+2) | `drafts/price-side-inversion-20261109.md` §2 |
| `c200-ladder-window-1025` | `pnl` | $597.46 | $597.46 | 0.00 | 53 / 53 | `drafts/c200-fill-scoreboard-caveat-20261103.md` §3 |

**3 of 3 → ADOPT** (`data/prereg-adoption.json`). The engine is not a rewrite of those three scripts; it
reproduces their numbers from a registry row, which is the property the card asked for.

Sample reproduction is basis-aware, and that is itself a guard against a dead adoption test. A **bounded**
slice (`since`/`until`) is closed, so its n must match the hand read exactly; a **cumulative** slice only
grows, and its hand read carries a date rather than an instant, so legs settling later that same day are
legitimately absent from it — requiring exact n there would make a correct engine fail as the book moves.
The re-run at 11:35 saw 2,133 regime legs against the hand read's 2,131 (+2 settled since 08:59, value
identical at 4 dp); the gate reproduces with `n_drift: +2` recorded in the artifact. A *shrinking*
population still fails.

## 4. The demonstration — entry-floor gate A is FROZEN, and always was

Gate A was pre-registered 2026-10-17: *<0.05 cell ROI ≤ −20% at n ≥ 60 settled C-200 legs*. The bespoke
script read it 17 times. Its own output, verbatim from `data/entry-floor-read.jsonl`:

```
state=INSUFFICIENT_N   n=31   ROI=-0.5518    (2026-10-26 … 2026-11-09, 16 consecutive reads)
```

`n=31` on every one of those reads. The registry, fed that history with `import-legacy` (source-tagged,
append-only) and then graded:

```
entry-floor-a   FROZEN   post=-  n=0  need=60  n_all=31  streak=19
    FROZEN: population n=31 unchanged across 19 consecutive graded reads;
            post-freeze n=0 < required 60 (max(min_n=60, floor=30))
```

(Verbatim from the 11:35 read; the streak is derived from the append-only read log, so it grows by one on
every grade and never resets while `n_all` holds at 31.)

Two facts the bespoke output could not state, now stated:

1. **The population is closed.** All 31 legs in the cell settled **before** the gate's own freeze date, so
   the strictly-post-freeze population is **n=0**. Gate A can never resolve. It was not "waiting for 29 more
   legs"; it was never going to get a 32nd.
2. **The number is frozen at the same time the gate is being counted on.** 19 consecutive graded reads at
   n=31 is a stuck dataset, not slow evidence.

That is the instrument's claim: it turns "INSUFFICIENT_N, try again tomorrow" into a diagnosis.

## 5. What the registry says about today's book (2026-11-09)

| gate | state | post-freeze | all rows | reading |
|---|---|---|---|---|
| `price-side-inversion` | `UNGRADEABLE` | 4 of 36 legs = **11.11%** | 90 of 2,133 = 4.22% | the class is still being **generated**, at ~2.6× the lifetime rate — it is not a pre-freeze artifact. Needs 100 post-freeze legs; 36 today |
| `c200-ladder-window-1025` | `REFUTED` | $597.46 | $597.46 | the pinned 2026-10-25…10-31 window misses the $1,750 Phase-1 bar by 66% |

The price-side number is worth reading next to its PnL form: those 4 post-freeze legs book **+$792.13**
against **+$735.05** for the whole 36-leg post-freeze book — the inverted class is **107.8% of post-freeze
PnL**, i.e. the rest of the book lost money. The all-time PnL share is 59.74% ($5,641.69 of $9,443.76),
which is the figure `drafts/price-side-inversion-20261109.md` §2 carries.

**`REFUTED` on a pinned window is not a statement about the live ladder.** The window is a fixed,
reproducible slice (frozen before it opened) used to prove the engine reproduces the bespoke ladder read.
Reading the live ladder is `query_bankroll.js`'s job until a rolling-window slice key exists (a spec change,
deliberately not smuggled in as config — see §8).

## 6. The guard that rejected a gate written after the fact

The natural way to register the price-side defect is *"the inverted class carries ≥ 20% of booked PnL"*.
Fed to the grader, that spec is **`REJECTED_PRE_TRUE`**: on the pre-freeze population the share is 59.74%
with n=2,097 ≥ 100, so the gate was already true when it was written and passing it later would carry no
information.

That rejection is the card's hypothesis in one line — *a gate asserting what is already true cannot be told
apart from a tautology* — so the registry carries the **forward-detectable** form instead:
`inverted_share ≥ 5%`, which the lifetime 4.22% makes false pre-freeze, and which will either reproduce
(the class is live) or collapse (the pre-freeze legs were the whole story). The after-the-fact form is
recorded here rather than as a dead row, because its rejection is the evidence.

## 7. Verification (what was actually run)

Re-run end-to-end on 2026-11-09 11:35 (independent of the build run), on the live DB:

```
$ python3 scripts/prereg-grade.py self-test        # 0/25 checks failed
$ python3 scripts/prereg-grade.py validate         # 3 spec(s), 0 rejected
$ python3 scripts/prereg-grade.py grade --dry-run  # nothing written
$ python3 scripts/prereg-grade.py grade            # 3 reads appended (read log 23 -> 26)
$ python3 scripts/prereg-grade.py adopt            # 3 of 3 -> ADOPT, artifact rewritten
```

The hand reads were also re-read at their sources rather than trusted from the artifact:
`data/entry-floor-read.jsonl` `verdict.gateA_n=31` / `gateA_roi=-0.5518`;
`drafts/price-side-inversion-20261109.md` (90 inverted of 2,131 legs, §2); and
`drafts/c200-fill-scoreboard-caveat-20261103.md` §3 (15 unstamped + 14 filled + 24 unfilled = 53 legs,
$597.46). The post-freeze price-side PnL was recomputed directly from `prisma/dev.db` (4 inverted legs
+$792.13; 36 leg book +$735.05).

Self-test (synthetic observations, no DB): unknown metric / spec key / slice key / op rejected; non-integer
`min_n` rejected; floor raises the bar (`roi`, min_n 5 → 30) while a higher `min_n` is kept (60); n below
bar → `UNGRADEABLE`; predicate false → `REFUTED`; undefined metric → `UNGRADEABLE`; pre-true with n ≥ bar →
`REJECTED_PRE_TRUE`; pre-true with n < bar then SUPPORTED → `NO_INFORMATION`; 7 unchanged reads → `FROZEN`;
6 → `SUPPORTED`; `REFUTED` never frozen; `now < frozen_at` → `PENDING`; streak counts/resets on the
population; `PENDING` reads do not count; metric arithmetic (`roi`, `inverted_*`, `fill_reach` on stamped
rows only).

Harness behaviour on a scratch copy (`--registry` / `--reads` overrides, real registry untouched), re-run
this session: edit a frozen spec's threshold 1750 → 1700 prints `MODIFIED` on its next read; an appended
spec with an unknown key `minN` is `REJECTED` while the other specs still grade, and the command exits 1;
`--dry-run` writes nothing; repeated grades append and increment the streak.

## 8. Usage, and the limits worth stating

```
python3 scripts/prereg-grade.py grade [--dry-run] [--json]   # append reads, print table
python3 scripts/prereg-grade.py validate                     # schema/vocabulary only
python3 scripts/prereg-grade.py adopt                        # adoption rule + JSON artifact
python3 scripts/prereg-grade.py import-legacy [--id ...]     # seed history from a bespoke read log
python3 scripts/prereg-grade.py self-test
```

Limits, stated so a later read does not over-claim:

- **`FROZEN` reads the slice population (`n_all`), not the graded subset.** Documented in the file header
  because it is the only basis that survives a freeze date; a bounded historical window will therefore
  always look "unchanged" — which is why `FROZEN` never overrides `REFUTED`.
- **A date-only `frozen_at` is local midnight, and the strict cut is real.** Freezing a window spec *on* its
  own first day excluded a leg stamped exactly at 00:00: the first grading read 52 legs / $607.43 against
  the hand read's 53 / $597.46. Moving the freeze to the day before (2026-10-24) restored the exact number.
  Pin the freeze *before* the window opens; that is the prereg discipline anyway.
- **The vocabulary is closed on purpose.** A rolling "trailing 7 settled days" gate (the live ladder shape)
  needs a new slice key; that is a reviewed spec change, not a config value.
- **`adopt` is basis-aware about n, and says so.** A bounded slice must match the hand read's n exactly; a
  cumulative slice may only have GROWN (a shrink fails), with `n_drift` recorded. Without that rule a
  correct engine would fail its own adoption test as soon as one more leg settled — the same class of
  unfalsifiable gate the registry exists to catch.
- **Three specs is a harness, not a population.** It grades the gates that were registered for the adoption
  test; it does not claim to cover every dated gate in the repo.
- **It fixes nothing.** No rule, size, gate or published figure moves. No live path reads any of these files.

**Revert:** delete `data/prereg-registry.jsonl`, `data/prereg-reads.jsonl`, `data/prereg-adoption.json` and
`scripts/prereg-grade.py`; or `git revert` the commit. Nothing else depends on them.

## 9. Repro

```
cd ~/polymarket-copybot
python3 scripts/prereg-grade.py validate
python3 scripts/prereg-grade.py grade --dry-run
python3 scripts/prereg-grade.py adopt --dry-run
python3 scripts/prereg-grade.py self-test
tail -3 data/prereg-reads.jsonl
```
