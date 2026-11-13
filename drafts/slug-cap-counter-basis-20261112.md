# v45 slug cap counts ATTEMPTS, not open positions — re-measured 2026-11-12

Date: 2026-11-12 · Lane A · roadmap card `slug-cap-counter-basis` · **PROPOSAL — nothing applied**
Supersedes the basis read in `drafts/slug-cap-counter-basis-20261030.md` (same defect, older window).
Instrument: `scripts/slug-cap-counter-basis.py` (read-only, opens `prisma/dev.db` with `immutable=1`)
Evidence dump: `data/slug-cap-basis-30d-20261112.json` (268 rows, one per refusal; committed copy of the
scratch dump `~/.hermes/cache/scratch/slugcap-30d-1112.json`, which the scratch dir prunes).
Tree read at: `947ceb5`, clean working tree for `scripts/score-trades.ts` (see §6 — the file is edited
concurrently by sibling sessions; re-read before applying).

## 0. Verdict in one line

The counter behind the v45 15-per-slug cap consumes its budget on candidates that **never opened a
position**: in the last 30 days **all 268** cap refusals printed `would be 16/15` while the true
concurrent open count was ≤14 — 249 of 268 (92.9%) still phantom after allowing for unbooked
dispatches — and only **11 legs (0.37/day)** would survive the gates that follow the cap. Approve as a
**basis-truthfulness fix**. Both clauses of the family decision rule pass; the money does not.

## 1. The defect (verified in this tree)

`scripts/score-trades.ts`

- **L265-271** the map is seeded **once per scoring run** from truth:
  `PaperTrade WHERE botId='BANKROLL_200' AND status='open'` → `c200SlugCounts`.
- **L816-827** the check. The bucket is incremented **inside the pass branch**:

  ```
  const slugOpen = (c200SlugCounts.get(t.marketCategory) ?? 0) + 1;
  if (slugOpen > rules.maxMarketSlugPositions) { …refuse, continue… }
  c200SlugCounts.set(t.marketCategory, slugOpen);      // ← slot consumed here  (L827)
  ```

  Everything that can refuse the copy afterwards is a `continue` **after** the slot was taken:
  kelly no-edge (L892), high-entry >0.80 (L1056), C-200 band skip 0.4-0.6 (L1073), v55 per-market
  (L1095), v58 per-wallet (L1129). The booking point is `openPaperTrade` at **L1159**, `legsOpened++`
  at **L1228**. `c200SlugCounts` is written in exactly two places (seed L271, pass-branch L827) —
  **there is no release path anywhere in the file.**
- The bucket **pins at exactly the cap**, by construction: once it reads 15, every later candidate
  computes `16/15` and refuses, and the refuse branch does not write. So the printed string can never
  reveal how many attempts filled it — 268 of 268 refusals read `would be 16/15`, not one of them
  printed 17 or 18.

**Monotonicity (why this is a safe change to price):** the current bucket is ≥ the truthful bucket at
every point in a run (a booking always implies a passing check, and the truthful bucket only increments
on bookings). So moving the increment to the booking point can only **admit a superset** — it cannot
refuse a leg the current code admits. The risk is one-directional: slightly less conservative at the
async-booking edge (§7, clause 2).

**This is the third card in one family, and the other two have already reported:** v41 category seats
(`category-seats-never-released` — Lane B basis label shipped 2026-11-06, seat move still awaiting
approval), v55 per-market seats (`permarket-legs-seat-release` — 8.6% phantom, 0/46 in the last 30d,
hunk written for it, not in the tree at the final read). The slug rail is the family's worst case by an
order of magnitude: 100% phantom, on the highest-volume token.

## 2. Measured basis — 2026-10-13 → 2026-11-12

Population: C-200 non-demo decisions carrying a slug-cap block (`risksJson LIKE '%v45 market-slug cap%'`),
level = decision, clock = decision `createdAt` UTC. True concurrent open count reconstructed from booked
C-200 legs' `[openedAt, COALESCE(closedAt, resolvedAt))` intervals on the same raw `marketCategory` token.

```
$ python3 scripts/slug-cap-counter-basis.py --days 30 --end 2026-11-12T16:45:00Z
population: 268 slug-cap refusals on 268 decisions in [2026-10-13T22:45Z, 2026-11-12T22:45Z)
legs: 2830 C-200 non-demo legs across 204 tokens (11 still open)
TOTAL 268   genuine 0   phantom 268   phantom share 100.0%
OUTCOME COVERAGE: 268/268 refusals resolved (settled winner on the market's conditionId)
```

| token | refusals | GENUINE (true open ≥15) | PHANTOM | true open at refusal (n by value) |
|---|---|---|---|---|
| nba | 169 | 0 | 169 | 0:78, 9:21, 12:15, 13:25, 14:20, other 1-11:10 |
| lal | 41 | 0 | 41 | 3:41 |
| mex | 28 | 0 | 28 | 0:28 |
| fl1 | 19 | 0 | 19 | 0:10, 2:9 |
| epl | 11 | 0 | 11 | 0:11 |
| **total** | **268** | **0** | **268** | phantom share **100%** (92.9% robust, below) |

Prior read for the trend (2026-09-30 → 2026-10-30, `drafts/slug-cap-counter-basis-20261030.md`): 105
refusals, 28 genuine / 77 phantom = 73.3%. The class composition flipped to **0 genuine** and the
volume 2.6×'d on a rotated token mix (dota2 33 and cfb 21 / ufc 7 — the old genuine cases — have no
refusals at all now; nba and lal are new).

Three honesty checks on this population, because each one can manufacture a phantom:

1. **Duplicate accumulation.** 268 decisions are only **50 distinct `market|side|wallet`** events
   (47 markets, 8 wallets); 198 of 268 rows sit within 60 s of an identical `market|side|wallet` row.
   The decision-level N is inflated roughly 5×, so the value arm is also reported deduped (§4) and its
   CI is market-clustered.
2. **Async booking lag.** A C-200 row is written by the sidecar's webhook, so a leg dispatched seconds
   ago may not be in `PaperTrade` when a later decision is evaluated — which would make a genuine
   refusal read phantom. Allowance: one slot per same-token leg opened within ±300 s of the refusal.
   **249/268 (92.9%) stay phantom even then**; the 19 unresolved rows are all `gap = 1` with exactly
   one lagging leg, i.e. unproven rather than disproven. Near the boundary (true open ≥13) it is
   29 of 45 robust — that is where the caveat bites and where the fix matters most.
3. **The rail is reachable — and just barely binding.** Max true concurrency in the 30d window:
   **nba 15** (the cap), ucl 13, highest 13, nhl 11, everything else ≤5. So this is not a dead rail
   being measured against a token that never fills; nba touches the cap, and 45 of its 169 refusals
   happened at 13-14 open with a bucket claiming 15. A truthful counter admits every one of the 268
   (true open ≤14 < 15); 11 of them survive the later gates (§3, §5).

## 3. Second basis lie found this read: 85% of the cap's refusals belong to another gate

The C-200 band skip (`c200SkipBandRange = 0.4-0.6`, active v72) fires **after** the slug cap, so a leg
in that band is journalled as a *cap* refusal although the cap is not what would have refused it:

| gate that decides the refused leg | legs | share |
|---|---|---|
| C-200 band skip 0.4-0.6 (fires after the cap) | 229 | 85.4% |
| high-entry >0.80 (fires after the cap) | 28 | 10.4% |
| would have been admitted → **the cap is the constraint** | **11** | 4.1% |

So the journal names the slug cap on 268 legs, of which 257 were already owned by a later gate. That
is worth fixing for the same reason as the seat itself: the skip histogram and the refit sample read
these rows as "the cap did this".

## 4. What the refused legs would have earned (unit notional, hold to settlement)

Basis: $1 per refused decision at `ObservedTrade.detectedPrice`, no maker credit, no fee, win/lose from
the market's own settled winner (keyless CLOB archive `/markets/<conditionId>`, 268/268 resolved, 0
undetermined). CI = percentile bootstrap resampling **markets** (the script's own arm).

| arm | n | sum | mean/$1 | median | win rate | 95% CI |
|---|---|---|---|---|---|---|
| PHANTOM (all rows) | 268 | +$24.34 | +$0.091 | +$0.105 | 55.6% | [−0.477, +0.739] |
| PHANTOM, deduped `market\|side` | 47 | +$13.95 | +$0.297 | — | 64% | — |
| **survivors of the price/market gates** | **11** | **+$2.84** | **+$0.258** | — | 55% | — |
| survivors, deduped `market\|side` | 9 | +$2.31 | +$0.256 | — | 56% | — |

ex-top-k on the full phantom arm: k=1 +$22.35, k=3 +$19.26, k=5 +$16.37, k=10 +$9.71 — no single leg
carries it, but the CI spans zero and the entire survivor set is **11 legs of one token (nba), six of
them one game** (`nba-den-hou-2026-11-09`, 19:25:54Z). This is not a profit claim and is not offered
as one.

## 5. Reachability ceiling — what the fix could actually admit

11 legs / 30 d = **0.37 admissions/day**, against **395 C-200 legs opened** in the same window
(+2.8% throughput). Kelly and confidence are not reconstructable on a cap-refused row, so 11 is an
**upper bound**, not a forecast.

## 6. The change (exact, one site moved)

`scripts/score-trades.ts`: delete the pass-branch increment (L827) and increment at the booking point,
beside the v55 and v41 booked counters:

```diff
@@ -824,7 +824,6 @@
             continue;
           }
-          c200SlugCounts.set(t.marketCategory, slugOpen);
         }
@@ -1225,6 +1224,15 @@
          if (botId === "BANKROLL_200" && tradeCat) {
            c200CategoryBooked.set(tradeCat, (c200CategoryBooked.get(tradeCat) ?? 0) + 1);
          }
+          // v45 slug seat-basis fix (2026-10-30 proposal on card slug-cap-counter-basis,
+          // re-measured 2026-11-12): the slug slot is consumed by the leg that actually
+          // books, not by a candidate that merely passed the cap check and then died at
+          // kelly / high-entry / band skip / v55 / v58. Before the fix: 268 of 268
+          // slug-cap refusals in 30d printed `would be 16/15` with fewer than 15 legs
+          // truly open (249/268 = 92.9% even after allowing for unbooked dispatches).
+          if (botId === "BANKROLL_200" && rules.maxMarketSlugPositions > 0 && t.marketCategory) {
+            c200SlugCounts.set(t.marketCategory, (c200SlugCounts.get(t.marketCategory) ?? 0) + 1);
+          }
           legsOpened++;
```

Patch file: attached to kanban card `t_6c0efb3d` as `slug-cap-seat.patch` (also at
`~/.hermes/cache/scratch/slug-cap-seat.patch`, which prunes) — `git apply --check` OK against `947ceb5`.
The sibling card `permarket-legs-seat-release` has an identical-shaped hunk for the v55 seat that was
present in the working tree while this was being measured and had been reverted again before the final
check; **this hunk's context is the category-booked block and does not touch the v55 lines**, so it
applies whether or not that one is in the tree. If both land, order inside the block is irrelevant —
they touch different maps. Re-read the file before applying (sibling sessions clobber it).

Unchanged: `maxMarketSlugPositions` stays **15** (active RuleSet **v72**), no RuleSet version, no
`rules.ts` edit, no schema, no basis change (the token-granularity question was settled by
`slug-cap-token-granularity` and is not reopened).

Two honest limits of the fixed counter:

1. For C-200 the row is written asynchronously by the sidecar (`openPaperTrade` returns `rust-pending`),
   so this counts **dispatches that passed every gate**, not confirmed rows. A dispatch the sidecar
   later rejects consumes a slot with no position — the residual error is **fail-closed** (it can
   refuse a copy that would have been allowed), the same direction as today.
2. The seed is still once per run, so a leg that closed earlier in the same run still counts. That
   error exists today and is unchanged.

## 7. Decision rule — the rule the other two repairs in this family used

**Apply iff (i) the repair changes fewer than 1 admission/day AND (ii) the released legs are not
net-negative at their own market settlement.**

| clause | measured | verdict |
|---|---|---|
| (i) admissions/day | 0.37/day (11 legs / 30d, upper bound) | **PASS** |
| (ii) released legs, per $1 | +$0.258 mean over 11 legs (deduped +$0.256 over 9) | **PASS** |

→ **RECOMMEND APPLY AS A BASIS FIX.** It makes the printed number true, it cannot add more than ~11
legs a month, and the legs it does add are not losses. If the goal is more copies admitted this is
still not the lever: the same five tokens carry 6,968 decision-level skips against 268 cap refusals.

## 8. Refutation (pre-registered — read the result against these, not against a feeling)

Baseline, weekly refusals by class (same instrument, this window):

| week | total | genuine | phantom |
|---|---|---|---|
| 2026-W42 | 6 | 0 | 6 |
| 2026-W43 | 28 | 0 | 28 |
| 2026-W44 | 97 | 0 | 97 |
| 2026-W45 | 47 | 0 | 47 |
| 2026-W46 | 90 | 0 | 90 |

**REVERT IF, on the first full week after the fix lands:**

1. any cap refusal still prints a bucket whose true concurrent open is **below 15** (a truthful counter
   can only refuse at ≥15) — the seat move did not take;
2. **any token holds >15 concurrent open C-200 legs** post-fix (the rail stopped binding). Baseline:
   0 tokens exceeded 15 in this 30d, peak = nba 15. This is the cheap safety read, and it is the one
   that would catch a seed/async interaction the monotonicity argument does not cover;
3. the admitted-extra legs reach **n≥30** and carry a per-$1 mean ≤0 at their own settlement. At the
   measured rate (0.37/day) this needs ~3 months — do not read it early and do not call the change
   a win before it is readable.

Read it with:

```
python3 scripts/slug-cap-counter-basis.py --days 7
```

Clause 1 is self-checking: post-fix, `would be 16/15` at 14 true open is arithmetically impossible.

## 9. Rollback

`git apply -R slug-cap-seat.patch` (the card attachment), or `git revert` the single commit. No
schema, no RuleSet version, no `rules.ts`, no data migration, no backfill — the journal keeps whatever
it recorded either way.

## 10. Verification actually run (not inferred)

```
$ python3 scripts/slug-cap-counter-basis.py --days 30 --end 2026-11-12T16:45:00Z
268 refusals / 0 genuine / 268 phantom (100.0%) · 249/268 = 92.9% robust to a ±300s dispatch lag
outcome coverage 268/268 · exit 0
$ git apply --check slug-cap-seat.patch   → OK
$ git apply slug-cap-seat.patch && npx tsc --noEmit   → tsc exit=0
$ git apply -R slug-cap-seat.patch        → reversed; tree back to the pre-existing 13/2 v55 diff
```

No test exercises this counter (it is inline in `main()` with no exported seam), so the only mechanical
proof available pre-landing is the type-check plus the post-landing journal read in §8. If a seam is
wanted, extract `slugSlotDecision(count, cap)` and unit-test 14→15 admit / 15→16 refuse in the same
commit — optional, +15 min.

Nothing in this run wrote to `prisma/dev.db` (all reads `immutable=1`), ran any `apply-v*.ts`, changed
a rule, size, gate or threshold, or touched `main`.

## 11. Overridable flags

- **FLAG 1 — seat move.** Increment at the booking point (§6). *Recommended.* Revert = reverse one hunk;
  the number that moves is slug-cap refusals (268/30d → ~0/30d at this window's concurrency) and
  admissions (+0.37/day). Say "keep attempts" to drop this card.
- **FLAG 2 — if you keep attempts, label the basis instead.** The v41 category rail solved this the
  other way on 2026-11-06: the gate still counts attempts, and the refusal line names the basis
  (`… would be N/40 on an attempts basis; true open K`). Same 2-line read-only repair here
  (`would be N/15 on an attempts basis; true open K`), Lane B, no gate change. Say "label only" and I
  ship that instead — but note it leaves 268 refusals a month that a truthful counter would not make.
- **FLAG 3 — nba is the token that binds.** 169 of 268 refusals, peak concurrency exactly at the cap,
  45 refusals at 13-14 open. The cap value stays 15; do NOT re-basis (the token-granularity question is
  settled). Flagged so the post-fix read is not mistaken for a cap malfunction if nba refusals persist.
- **FLAG 4 — v58 seat leak, not bundled.** `v58` also increments on its pass branch (L1156) and
  releases nothing; it fired **0** times in this 30d window (v55 fired 4, and a seat-move hunk is
  written for it under `permarket-legs-seat-release`). Left alone so this diff explains one rail.
