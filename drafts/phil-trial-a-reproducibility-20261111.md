# phil Trial A — the pre-registered read was not reproducible (and now is)

**Status:** instrument repair, executed and verified (Lane B). No rule, gate, size, threshold or
live path changed. No published verdict changed.
**Date:** 2026-11-11 · **Card:** `phil-trial-a-oct8-forward-read` (roadmap, done) ·
**Approval:** `apr-phil-trial-a-oct8-forward-read` (Lane B, clicked 2026-11-11T18:36Z)

The card's job was the pre-registered shadow read at the Oct 8 window close. That read was taken on
2026-10-10 and is stored in `data/shadow-forward-read.jsonl` rows 2–3 (`mode: "preregistered"`).
This pass was the read-back — and it found that the read could not be re-derived, because the
population it scored was defined by *when you ran it*, not by the window it was registered against.

---

## 1. The defect: `--preregistered` was a label, not a population

`scripts/shadow-forward-read.ts` built its rows from every `resolve` row present in the shadow feed
at run time. There was no cutoff on settle time and no cutoff on decision time. `readAt` was written
into each row, but nothing enforced it: re-running the identical command returned a *different
population*.

Same command, two dates:

| run | late_drift_gate bets | min_confidence_gate bets |
|---|---|---|
| 2026-10-10 14:47 CDT (stored pre-registered read) | 4,250 | 11,437 |
| 2026-11-11 12:34 (identical command, `mode=smoke`) | 38,662 | 26,325 |

9.1× / 2.3× the population, and the answer moves with it: `min_confidence_gate` criterion (a)
(cw_return > 0) **PASSes at the read instant (+1.06%) and FAILs today (−0.92%)**. A pre-registered
read whose verdict depends on the calendar is not pre-registered — the whole authority of the bar
is that the same population is scored against it, forever.

## 2. The repair (Lane B — default behaviour is bit-identical)

Two cutoffs, both optional, both recorded in the written row:

| flag | freezes | why |
|---|---|---|
| `--as-of <ISO>` | the settle population (`resolve.ts` ≤ instant) | what a read run at that moment could actually have seen |
| `--decided-by <ISO>` | the decision window (`candidate.ts` ≤ instant) | a window-close read must not score decisions taken after the window shut |

Neither flag ⇒ the historical uncut read, unchanged. Implementation: the row builder moved out of
the script into a pure, exported `buildShadowRows()` in `src/lib/shadow-read.ts` (so the cutoffs are
testable), and the script calls it. The written row now carries `asOf`, `decidedBy`,
`candidatesInWindow`, and `awaitingSettle` (rows resolved only *after* the as-of — the ones an as-of
read must not count, reported instead of silently dropped).

- `tests/shadow-read.test.ts`: **20 tests pass** (14 pre-existing + 6 new pinning the cutoffs,
  including "no cutoffs = historical read" and "era is the one live at the DECISION").
- `npx tsc --noEmit -p tsconfig.json`: no diagnostics in either touched file (the two remaining
  errors in the tree are pre-existing, in `scripts/shadow-market-hygiene.ts`, and untouched here).
- No-cutoff output re-run and compared field-by-field against the pre-patch run: identical.

## 3. Reproduction proof — the stored read comes back to the cent

Re-running the read pinned to its own `readAt` (`2026-10-10T19:47:04Z`) reproduces both stored rows
**exactly**, on every field the criteria read:

| | stored row 2 (drift) | re-derived (`--as-of`) | stored row 3 (lowconf) | re-derived (`--as-of`) |
|---|---|---|---|---|
| settled / dust / era-unlabelled | 4,945 / 695 / 0 | 4,945 / 695 / 0 | 12,343 / 906 / 0 | 12,343 / 906 / 0 |
| bets / market clusters | 4,250 / 862 | 4,250 / 862 | 11,437 / 2,513 | 11,437 / 2,513 |
| roi / stake-weighted SE | 3.787% / 1.494% | 3.787% / 1.494% | 2.272% / 1.213% | 2.272% / 1.213% |
| cw_return | +2.293% | +2.293% | +1.059% | +1.059% |
| clustered 95% CI | [−8.876%, +16.821%] | [−8.876%, +16.821%] | [−9.701%, +14.307%] | [−9.701%, +14.307%] |
| largest winner share | 0.724% | 0.724% | 0.149% | 0.149% |

So the published numbers were honest — they simply named no population. That is now fixable by one
flag, and the fixed seed (`20261008`) makes the interval itself reproduce.

## 4. The four cuts, side by side

| cut | lane | bets | clusters | roi | cw_return | clustered CI | (a) | (b) | (c) | (d) | decision |
|---|---|---|---|---|---|---|---|---|---|---|---|
| **uncut, today** | drift | 38,662 | 7,965 | +0.98% | +0.41% | [−5.61%, +7.81%] | P | P | **F** | **F** | **fail** |
| | lowconf | 26,325 | 4,619 | −0.17% | −0.92% | [−8.51%, +9.10%] | **F** | P | **F** | **F** | **fail** |
| **as-of read instant** (published) | drift | 4,250 | 862 | +3.79% | +2.29% | [−8.88%, +16.82%] | P | P | **F** | **F** | **fail** |
| | lowconf | 11,437 | 2,513 | +2.27% | +1.06% | [−9.70%, +14.31%] | P | P | **F** | P | **fail** |
| **window close** (`--as-of 2026-10-08T23:59:59Z`) | drift | 4,243 | 858 | +3.83% | +2.33% | [−8.80%, +16.97%] | P | P | **F** | **F** | **fail** |
| | lowconf | 10,346 | 2,353 | +5.81% | +4.53% | [−6.60%, +18.91%] | P | P | **F** | P | **fail** |
| **window decisions, matured** (`--decided-by 2026-10-08T23:59:59Z`) | drift | 21,475 | 5,247 | +4.85% | +4.08% | [−2.61%, +12.66%] | P | P | **F** | **F** | **fail** |
| | lowconf | 11,160 | 2,515 | +4.20% | +2.97% | [−8.29%, +16.87%] | P | P | **F** | P | **fail** |

**The verdict is the same under every cut**: both lanes fail, both on criterion (c) — the
market-clustered CI includes 0 — and the drift lane also fails (d) on era signs. Both clear the
≥150-settled power bar in every arm, so these are powered fails, not "underpowered, criteria only".

## 5. What the cutoffs exposed (two measurement findings, neither changes the verdict)

**(i) 630 of the published lowconf bets were decided AFTER the window closed — and they lost.**
The published read (as-of Oct 10, no decision cutoff) scored 11,437 bets; the strict window scores
10,807. The difference — 630 decisions taken on Oct 9–10 — returns **≈ −35%** (derived by subtraction:
$114,370 × 2.272% vs $108,070 × 4.42% over the extra $6,300 staked). That single leak halved the
headline: the window's own lowconf ROI is **+4.42%**, not +2.27%. The leak runs *against* the
conclusion, so it never flattered the read — but a pre-registered read that includes post-window
decisions is not the read that was registered. The drift lane had no such leak: every drift decision
that had settled by Oct 10 was decided on or before Oct 8.

**(ii) A window-close read is a read of the fast-settling subset.** At the read instant only
**4,945 of the 23,462** in-window drift decisions that have since marked to settlement had actually
settled (21%); the other 79% resolved afterwards, and when they did the window's ROI moved from
**+3.79% to +4.85%** — i.e. the rows that mature slowly were the *better* ones here, and the early
read was pessimistic by ~1.1pp. (The lowconf lane settles fast: 11,689 of 12,045 resolved, 97%, so its
close read was nearly complete — its gap to the matured window (+4.20% on 11,160 bets) is much
smaller, and the 2.27% headline's distance from it is the leak in (i), not maturity.) The lesson is
mechanical, not rhetorical: **"read at the window close" ≠ "read the window"**, and the size of the
gap is lane-specific. Report the maturity split beside any close-dated read, or quote a cohort that
is 21% complete as if it were the window.

## 6. What did NOT change, and the one judgement call

- No rule, gate, threshold, size or live path. No row in `data/shadow-forward-read.jsonl` was
  rewritten or appended: the stored read stands as recorded, and §3 shows it reproduces.
- The roadmap card's published result is **unchanged and still correct** for the population it
  scored. §5(i) is recorded as an addendum with both figures labelled, not as a silent re-basing.
- **One overridable flag:** whether the canonical lowconf figure for this window should read
  **+2.27% (as-run, 11,437 bets, includes 630 post-window decisions)** or **+4.42% (strict window,
  10,807 bets)**. I have left the card's original figure in place and put the strict re-cut beside it;
  reverting = delete the addendum line. If you want the strict figure canonical, the card note
  becomes the strict table and this paragraph moves to a footnote.
- Adjacent defect noticed, not touched (outside this card): `scripts/shadow-market-hygiene.ts` does
  not compile — `holderConcentration` is undefined at lines 194 and 204. That is the "query that
  throws" class; it wants its own Lane B pass.

## 7. Reproduce

```bash
cd ~/polymarket-copybot
# the published read, re-derived exactly (§3)
npx tsx scripts/shadow-forward-read.ts --as-of 2026-10-10T19:47:04Z
# the window close (§4 row 3)
npx tsx scripts/shadow-forward-read.ts --as-of 2026-10-08T23:59:59Z
# window decisions, matured (§4 row 4)
npx tsx scripts/shadow-forward-read.ts --decided-by 2026-10-08T23:59:59Z
npx vitest run tests/shadow-read.test.ts        # 20 tests
```

**Revert:** `git revert <this commit>` — the defaults are unchanged, so no stored read and no
published figure depends on the new flags.

**Files:** `src/lib/shadow-read.ts` (+`buildShadowRows`) · `scripts/shadow-forward-read.ts`
(`--as-of`, `--decided-by`, stamped rows) · `tests/shadow-read.test.ts` (+6 tests) ·
`data/roadmap.json` (addendum + as-of provenance) · this file.
