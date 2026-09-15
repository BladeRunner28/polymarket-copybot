# Tuning review #26 — five recommendations applied and verified

**Date:** 2026-09-15 · **Approver:** user ("i approve of these recommendations") in the tuning-review thread
**Source:** `logs/cron/tuning-review.md` Cycle #26, recs 1–5 (each carries a `Verify:` line)
**RuleSet:** unchanged (v53) — none of these are threshold changes.

---

## 1. Label a copy decision by outcome (copy-score axis, 3rd delivery)

The journal row was written with `decision: result.decision` **before any gate ran**, so a fully
blocked copy stayed `paper_copy` (in-window 539 stored copy rows / 466 childless; EOD printed
"copy 422" against 79 real opens).

`scripts/score-trades.ts` now collects the blocking gate per leg (`legBlocks`) and counts
successful legs (`legsOpened`). After the per-bot loop:

- **no leg opened** → the row is rewritten `decision: "skip"`, `simulatedPositionSize: null`, with
  the blocking gates appended to `risksJson`, and `skips++` (the copy branch previously incremented
  neither copies nor skips, so a fully-blocked decision vanished from the summary);
- **≥1 leg opened** → the copy label stands, the blocks are recorded as context.

**Verify (7 d):** `SELECT COUNT(*) c, SUM(CASE WHEN t.id IS NULL THEN 1 ELSE 0 END) nc FROM DecisionJournal d LEFT JOIN PaperTrade t ON t.decisionJournalId=d.id WHERE d.isDemo=0 AND d.decision='paper_copy' AND d.createdAt > <apply_ms>` → `nc = 0`; and the EOD "copy" figure tracks real opens within ±5.

## 2. Declare AND implement the drawdown/exposure basis (exposure-cap axis, 3rd delivery)

`data/c200-drawdown.json` now carries **`basis`** (`mtm` | `realized` | `min`), **`peakRule`**,
`basisDeclaredAt` and (previously missing for three reviews) a place for `note`. `score-trades.ts`
derives **everything** from the declared basis: the peak ratchet, the equity-linked exposure cap
(`effectiveExposureCap(..., basisNetWorth, principal)`) and the drawdown gate; the
`[DRAWDOWN-SHADOW]` line now leads with `basis=<x>` and still prints both definitions; the
`[RISK-GATE]` veto text names the basis it used. Legacy files with no `basis` keep MTM.

**Declared value: `mtm`** — today's behaviour, now explicit instead of implied. Switching to
`realized` or `min` is a one-field edit with a large, stated consequence: the same $1,300 book is
**88.0% of cap ($1,477.97) on MTM vs 130.0% ($1,000) on realized-only**, i.e. `realized`/`min`
would force ~$300 of deleveraging mid-window. That sizing consequence is why it is left visible
rather than taken unilaterally.

**Verify (done):** state file contains `basis` + `peakRule`; the newest `[DRAWDOWN-SHADOW]` line
starts `basis=mtm`; `Y` in the `[RISK-GATE] … gross exposure cap` line = `1000 + 0.5 × (NW_mtm − 1900)`.

## 3. Break the ML-1 head-of-line block (measurement, 2nd delivery)

`scripts/review-outcomes.ts` selected `orderBy: { decision: "asc" }, take: 200` — the same 200
oldest pending copy decisions every night (all created 2026-07-15, only 34/200 with a resolved leg),
so the judge reported 0 while 8,475 decisions with a settled leg sat unreviewed and labels froze.

Now: **settled-leg candidates first** (`paperTrades: { some: { status: { in: ["resolved","closed"] } } }`,
`orderBy: createdAt desc`, `take: REVIEW_TAKE` — env-overridable, default 300), with a recency-ordered
fallback over the broad pending set if that yields nothing, so watchlist/skip rows still accrue
hypothetical labels. The run logs how many candidates exist.

## 4. Journal the v45 market-slug-cap blocks (category/slug axis, new)

The slug cap was one of the largest visible block classes (338 in-window) and wrote **zero** journal
rows, so neither the skip histogram nor the refit sample could see it. It is now one of the
`legBlocks` reasons (`BANKROLL_200: v45 market-slug cap (… would be N/15)`), so it lands on the row
whenever any leg of that decision was capped.

## 5. Report STANDARD net of legacy duplicate stacks (measurement, 2nd delivery)

The EOD report now prints the day **net of legacy duplicate stacks** plus, when it dominates, the
largest single stack. A day row counts as stacked when its `(wallet, market, outcome)` key holds
more than one row in the STANDARD book (open or finished) — the group is what makes it a stack.

**Verify (done, exact):** printed `Net of legacy duplicate stacks: $-36.49 (day $-52.49 − $-16.00
from 2 stacked rows)` vs independent SQL on 2026-09-15 → `day -52.49 | stacked -16.00 | net -36.49`.
Difference **$0.00**.

---

## Files

`scripts/score-trades.ts` (recs 1, 2, 4) · `scripts/review-outcomes.ts` (rec 3) ·
`src/lib/report.ts` (rec 5) · `data/c200-drawdown.json` (rec 2 declaration).

TypeScript clean; full suite green.
