# Re-audit — `darup67/market-lab`

**Re-audited:** 2026-11-26 · **Verdict: ❌ DROP (unchanged, on a now-harder basis)**
**Standing audit:** `drafts/research-weekly-20261102.md` §2, row 2 — verdict **drop** (licence +
half-false premise), with the premise probe carried into `drafts/kalshi-settled-history-surface-20261118.md`.
**Dashboard:** http://localhost:3013/drafts/market-lab-reaudit-20261126

This is a re-surface check, not a fresh audit. The candidate was claimed by the queue this morning;
the prior verdict stands, and two things are now *worse* than they were at the audit.

## What changed on their side

| | 2026-11-02 (audited) | 2026-11-26 (now) |
|---|---|---|
| Licence | API `NOASSERTION` | **`LICENSE` read in full: proprietary, all-rights-reserved** — *"This software and its documentation are proprietary. No permission is granted to use, copy, modify, merge, publish, distribute, sublicense or sell any part of it"* |
| Kalshi recorder | described as running every 10 min | **PAUSED since 2026-10-08**, still paused — `PAUSED-KALSHI-RECORDER.md` is present at root (its own resume instruction says to delete it after restarting), and it states the gap *"CANNOT be backfilled"* |
| Commits | pushed 2026-11-02 | ≥100 commits since, but the messages are repeated **data/edition churn** (`paper-lab: bars and headlines`, `event-desk: headlines and judgments`) — the repo has pivoted to different products, not fixed the recorder |
| Captured Kalshi data | ~2 days of live capture | `data/KXBTC15M/ETH/SOL/XRP.jsonl` = 4 files, 6.5 MB total, **frozen at the Oct-8 pause**. The bulk of the 81 MB of jsonl and the 403 MB repo size is elsewhere (futures/perps/results) |
| Stars / forks | ★1 · 0 | ★1 · 0 (no drift) |
| Tests | none | `ml_test.py` / `ml_test_minute.py` are research scripts, not a suite; still no CI |

## What did *not* change — and is now disproved on our side

The repo's founding premise is that Kalshi serves only ~2 days of settled markets, so *"nothing here
can be backfilled."* We probed that keyless on 2026-11-02 and it is **false for market records**:
`GET /trade-api/v2/markets?status=settled&min_close_ts&max_close_ts` returns settled markets back
**≥700 days** (`kalshi-settled-history-surface`, Done). The premise holds only for **fills**, which
exist only for markets closed ≤ 2026-09-18. So the one asset market-lab was built to accumulate —
a settled-market record — is retrievable from the venue whenever we want it, and the asset it
*actually* accumulated (trades) is (a) unreachable under its licence and (b) already superseded by
our own live capture.

## Re-mapped against the current roadmap (328 cards)

| Their component | Current card | Verdict |
|---|---|---|
| Committed Kalshi 15m jsonl capture | `kalshi-tape-capture-live` (In Progress) — our venue tape at 93–94% duty, 215k prints/window | ❌ superseded; ours is live and ours |
| "Kalshi serves 2 days" premise | `kalshi-settled-history-surface` (Done) — settled records ≥700 days, fills ≤2026-09-18 | ❌ premise refuted by our own probe |
| CME futures bars via Yahoo, 15-min, ~10-min delayed | no card; their own README is honest that it is research data, not an intraday signal (`btx3` is parked for the real thing) | ❌ no gap to fill |
| Null-padding hygiene — *"Bars Yahoo pads with nulls for periods that never traded are dropped rather than storing them… keeping them would put fake flat bars into a volatility study"* | same defect class our `label-integrity-*` batch spent five cards on | ⚪ concept only — the rule ("never store a synthetic flat bar as an observation") is already our standard; nothing to import |

## Amendment to the verdict

**Drop, and drop it harder than 11-02.** At the audit it was `NOASSERTION` — unusable as a dependency
pending a licence read. The licence is now read: it is explicit all-rights-reserved, which is stricter
than "no licence" (no permission granted at all, with an added non-compete clause). Combined with a
recorder that has been dead for seven weeks, ★1, no CI, and a premise refuted by our own keyless probe,
there is nothing here to adopt, nothing to measure, and nothing to watch.

Do not re-surface it again on a "pushed ≤90d" filter: the pushes are headline/bars churn on unrelated
products, which is exactly the shape the fake-activity pattern describes.

## Caveats

- The Kalshi capture's *contents* were not read (licence forbids copying, and there is nothing to
  adopt) — the pause is established from the repo's own notice, the plist filenames, and the frozen
  file sizes, not from parsing the jsonl.
- I did not clone, install or execute anything (job constraint), so I cannot report their scripts'
  correctness — only that they are unlicensed, untested and dead.
