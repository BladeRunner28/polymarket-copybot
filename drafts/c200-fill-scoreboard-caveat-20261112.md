# C-200 fill scoreboard, re-measured 9 days later — the coverage gap has a cause, and it is a race

http://localhost:3013/drafts/c200-fill-scoreboard-caveat-20261112

**Card:** `c200-fill-scoreboard-caveat` (approvals `apr-c200-fill-scoreboard-caveat`, approved 2026-11-12T19:32Z) · **Lane B** · **Date:** 2026-11-12
**Instruments:** `scripts/c200-intent-link-coverage.py` (read-only, `mode=ro&immutable=1`) · `scripts/c200-link-missing.ts` (dry-run by default) · `src/lib/fill-intent.ts` (`stampIntentLink`, repaired)
**Nothing booked. No RuleSet write, no `apply-v*`, no `prisma/dev.db` write, no merge, no EOD print.**

---

## 0. The short version

The card's numbers still reproduce in direction, but the reason it gave for them was wrong, and the
wrong reason hides a repairable defect:

- The card read the **84% never-stamped** share as "the join key does not exist". It does exist — the
  instrument era is `FillIntent`-complete **by `decisionJournalId` for 100% of legs**. What fails is
  the **`paperTradeId` link**, on 27.3% of them, and the cause is a **cross-process race** with no
  retry: the intent row is written by the scorer that dispatched, the leg row by the dashboard's
  execution-result webhook, and when the webhook wins by a few milliseconds the link lookup finds
  nothing and gives up silently, forever.
- **That is now fixed for future legs** (§3, tested, with a one-line revert) and it is a Lane B
  repair: no decision, size, gate or published figure reads the link.
- The historical half — **201 pairs** (of 219; 18 are refused, see §5) — is a **priced Lane A
  decision**, not a repair: linking them lets the resolver restate **$3,728 of notional and
  +$1,115.18 of booked PnL**, which flows into netWorth, the equity-linked exposure cap and the
  drawdown gate. It is dry-run only in this change (§6).
- The card's "phantom 68.6%" framing is **stale as a forward statement**: since the fill-aware flip
  (2026-10-28) a proven-unfilled leg books exactly **$0.00** — measured, the trailing-7-day window's
  unfilled legs book `$0.00` across 83 rows. The live leak is the **unresolved** class, which is the
  sibling card's question (`profit-fill-class-basis`), not this one's.

## 1. The card's figures, re-measured

| figure | card 2026-11-03 | today 2026-11-12 |
|---|---|---|
| stamped legs | 413 | **582** |
| reach, % of legs | 33.4% | **33.2%** (193/582) |
| reach, % of notional | 32.7% | **28.5%** |
| filled booked PnL | +$324.37 | **−$94.64** on $2,313.81 |
| unfilled booked PnL | +$707.80 | **+$828.66** on $5,808.89 |
| unfilled share of stamped PnL | 68.6% | 112.9% (residue, see (d)) |

The rate is stable at ~33% — the card's central quantity is not an artefact of its window. What
changed is the dollars: the filled class has gone negative, which is the same finding the fill-class
card reached independently.

The 2026-11-03 read's four corrections all still hold, with one sharpening:

- **(a) coverage** — sharpened in §2: the binding limit is the *link*, not the join key.
- **(b) window is 1 hour** — not re-derived here; `scripts/c200-printthrough.py` still writes
  `book.minAsk` over `H60`, and that is the field `resolveFill()` tests.
- **(c) the verdict tests a price the leg was not booked at** — still true, and §5 shows it is worse
  than "flat vs measured credit" on a small set of legs.
- **(d) the phantom is residue** — confirmed: unfilled legs book **$0.00** in the current window.

## 2. The coverage gap is two different facts

```
C-200 legs (isDemo=0)                                          2,830   opened 2026-07-22 .. 11-11
  pre-instrument  (decision has NO FillIntent row, by design)  2,028   71.7%   never stampable
  instrument era  (decision HAS a FillIntent row)                802
    linked   -> the resolver can reach it                        583   72.7%
    UNLINKED -> no verdict is possible, books p(fill)=1           219   27.3%   <- the defect
  stamped 582 · filled 193 (33.2%) · unfilled 389
  verifiable share of the whole lane: 20.6% of legs
last 7 days of opens (2026-11-04..11-11): 189 legs, 140 linked (74.1%), 49 orphaned
```

**The 2,028 are not a defect.** `FillIntent` ships with no backfill (documented in
`src/lib/fill-intent.ts`): every leg booked before 2026-09-26 has no intent price and cannot be
stamped. That share only shrinks as the book turns over.

**The 219 are a defect, and the mechanism is measurable.** For every one of them:

- a `FillIntent` row exists on the same `decisionJournalId` — **100%**, not 16%;
- a leg exists on the exact `(decisionJournalId, marketId, outcome, side)` tuple the linker matches
  — **1:1, 219 legs for 219 intents, zero ambiguous keys, zero duplicate tuples**;
- `logs/dashboard.log` carries **zero** `[fill-intent] link skipped` lines, so the lookup did not
  throw — it returned nothing;
- the two timestamps differ by **milliseconds** (median −2 ms, range −8…+17 ms).

So the lookup ran before the intent insert was visible. It cannot be otherwise: the intent is
inserted by the **scoring process** (`scripts/score-trades.ts` → `recordFillIntent`, awaited *after*
the dispatch POST returns) while the leg is inserted by the **dashboard process** (execution-result
webhook), both on the same SQLite file. The sidecar posts the webhook as it responds, so on ~1 leg in
4 the webhook's link wins the race against the intent's commit — and nothing retried, so the leg was
permanently unreachable.

## 3. What was shipped (Lane B)

`src/lib/fill-intent.ts::stampIntentLink` now retries the lookup with bounded backoff
(`FILL_INTENT_LINK_ATTEMPTS` 5 × `FILL_INTENT_LINK_BACKOFF_MS` 20 ms ≈ 200 ms worst case) and, on a
final miss, **logs the miss with its keys** instead of returning `null` silently. It still never
throws, still only touches `PaperTrade.intentPrice` + `FillIntent.paperTradeId/linkedAt`, and it runs
after the booking commits, so a slow miss can never delay or fail a copy.

**Verification (real SQL path, isolated DB — `tests/fill-intent.test.ts`):**

```
FILL_INTENT_LINK_ATTEMPTS=1 npx vitest run tests/fill-intent.test.ts -t race     -> 1 failed
    [fill-intent] link MISSED after 1 attempt(s): leg … — no unlinked intent
    AssertionError: expected null to be 0.58          (the old behaviour, reproduced)
npx vitest run tests/fill-intent.test.ts                                        -> 21 passed
```

The new tests pin the two properties that matter: an intent landing **after** the webhook still links
(the race), and a genuinely absent intent gives up in **bounded time** (never an open-ended wait on
the booking path). `npx tsc --noEmit` is clean for `src/` and `tests/` (the one remaining error is a
pre-existing one in `scripts/apply-v73-c200-cheap-band-clip.ts`, another session's uncommitted file).

**Revert:** `FILL_INTENT_LINK_ATTEMPTS=1` in the environment restores the single-shot lookup exactly
(no rebuild needed — the constants are read at module load, so a `launchctl kickstart` picks it up).

**Deployment state:** committed (`f93274d`), **not yet serving**. `npm run build` fails — not on this
change, on `scripts/apply-v73-c200-cheap-band-clip.ts` (another session's untracked file), which
Next's type-check compiles and which references `c200BandClipCaps`, a field that does not exist in
`src/lib/rules.ts`. `tsc --noEmit` is clean for `src/` and `tests/`; the dashboard is still serving
(`/` and `/approvals` both 200) on the 10:54 build. The fix goes live on the next successful build —
unblock by fixing or removing that file (its own card's problem), after which
`npm run build && launchctl kickstart -k gui/$(id -u)/com.xsnyde2.copybot-dashboard` ships it.

**What it changes going forward, stated plainly:** future legs that would have been orphaned now link,
so the resolver will stamp them, and a proven-unfilled leg books $0 at every later mark and at
settlement. That is the approved fill-aware behaviour working as designed, not a new rule — but it
does mean the stamp rate rises from ~73% to ~100% of new legs, which moves booked PnL and therefore
netWorth, the exposure cap and the drawdown gate over time. Revert line above if that is unwanted.

## 4. What the ladder sums today (local days, `query_bankroll.js` basis)

```
window 2026-11-03 .. 2026-11-09   160 rows  (filled 27 / unfilled 83 / unresolved 50)
  A. as the report reads it (unresolved at p(fill)=1)   $  -203.47   rung 1 needs $1,750   fail
  B. unresolved credited at ZERO                        $  -286.42                          fail
  C. proven fills only                                  $  -286.42                          fail
  the whole A->C gap is the UNRESOLVED class: $+82.95 on 50 legs
  unfilled books exactly $0.00 in the window
all-time unresolved class: 2,248 rows, +$4,904.36 booked
```

Cross-check: an independent instrument in this repo (`scripts/c200-ladder-fill-basis.py`, another
session's, uncommitted) reads the same window as −$203.5 booked / −$286.4 fills-only on 160 legs —
identical. **A UTC `date()` basis instead of local reads −$90.75 for arm A on the same rows**, so
quote the basis with the number.

The honest statement of the ladder is therefore *not* "the sums are 3x phantom". It is: **the advance
is judged on a sum whose only positive contributor is the class nobody can adjudicate, and the class
that can be adjudicated is negative on every basis.** Whether the gate should stop crediting the
unresolved class is `profit-fill-class-basis` (Lane A, proposed today, moves no advance).

## 5. What I did not expect: 42 legs are priced on the complement

Of the 802 intent↔leg pairs, **42 (5.2%) have `entry = 1 − intent`** — exactly a complement, on
named-outcome markets (team names, player names, `UNDER`). The intent is write-only so no PnL flows
from the price itself, but **the intent price is the level the resolver tests**: `resolveFill` compares
`book.minAsk` against `intent − credit`, so on these legs the verdict is decided a dollar away from the
booked level.

Re-testing the **same** evidence (`book.minAsk` from `data/c200-printthrough.jsonl`) at the **booked**
level, on the 24 of the 42 that already carry a stamp:

| | count |
|---|---|
| verdicts that survive | 20 |
| **verdicts that do not** (stamped `unfilled`, reachable at the booked level) | **4** |

All four are `unfilled → filled`: `wta-joint-cirstea` (entry 0.695, minAsk 0.340), `nba-phx-gsw`
(0.635 / 0.620), `ucl-aek1-rma` (0.940 / 0.940), `lal-mad-bar` (0.625 / 0.620) — $137.94 of notional
and −$17.99 of stored PnL that currently books $0. Small, and stated as small: the contamination is
4 of 582 stamps (0.7%), not a rewrite of the scoreboard. It is still a wrong verdict, and it is
**Lane A to restamp, Lane B to refuse linking** — which is what the link tool now does (§6).

## 6. The historical half — a priced Lane A decision, not applied

`scripts/c200-link-missing.ts` (dry run today, `--apply` required to write):

```
C-200 intent links — 802 intents, 2,830 legs
  already linked          : 583
  unlinked intents        : 219
  REPAIRABLE 1:1 pairs    : 201   notional $3,728.02   booked PnL $+1,115.18   settled 198
  ambiguous (refused)     : 0 keys
  unlinked intent, no leg : 0
  REFUSED, complement frame: 18  notional $776.89   booked PnL $+101.13
```

Applying it would let the resolver's next run stamp 201 legs, moving booked PnL (their current
contribution is +$1,115.18, which would be replaced by their proven verdicts), and through it
netWorth → the exposure cap → the drawdown gate. That is why it is not applied here. **One command,
reversible at the row level only by re-null: treat it as a restatement decision, and decide it
together with `profit-fill-class-basis` (both move the same gate inputs; running one without reading
the other's apply is how a gate gets moved twice).**

## 7. Verdict on the card's decision rule

The card's three options were about **printing** a reach rate in the EOD. Option 1 — "no print; fix
the coverage first" — was the recommended branch and is the branch this read executed: the coverage
defect now has a fix (shipped), an instrument (committed) and a priced repair path (dry-run).

**No print was shipped.** That is deliberate, not an omission: the print is Lane A (a published
figure), the approval came through the inbox as one bit with no branch attached, and options 2 and 3
would both print a number measured on a population that §2 shows is still 27% incomplete for the
historical book. If a print is wanted, the honest one today is option 2's coverage line, and it needs
its own yes:

```
C-200 fill verdict: 582/2,830 legs stamped (20.6%); 50 of the 7-day advance window's legs carry no verdict ($82.95 of $203.47)
```

**Refutation of this read:** a fresh 30-day forward sample in which reach ≥ 70% would make 33% an
artefact of the 1-hour window rather than a property of the lane — the card's original kill clause,
unchanged. And if linking the 201 pairs produced verdicts that reproduce the current booked PnL to
within the CI, the "phantom" framing is void for the historical book too.

## 8. Re-run

```
cd ~/polymarket-copybot
python3 scripts/c200-intent-link-coverage.py --orphans 6      # §2, §4, §5, S5-baseline
DATABASE_URL="file:./dev.db" npx tsx scripts/c200-link-missing.ts    # §6 (dry run)
npx vitest run tests/fill-intent.test.ts                      # the race + bound tests
```

Verified for this write-up: `python3 -m py_compile` clean; the python instrument's local-day window
reproduces the report's own SQL (`160 rows`, `−$203.47`); the TS script's dry run writes nothing;
`tsc --noEmit` clean for `src/` and `tests/`.
