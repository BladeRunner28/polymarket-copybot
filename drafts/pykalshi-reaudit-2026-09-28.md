# pykalshi — re-surface check (arshka/pykalshi), 2026-09-28

**Why this file exists:** the weekly repo scout re-surfaced `arshka/pykalshi` in its top-5 on 2026-09-28.
It was **already audited twice** on 2026-09-09 — `drafts/pykalshi-audit.md` (the full adoption audit) and
`drafts/pykalshi-audit-2026-09-09.md` (the batch-workflow copy). This is the mandatory prior-work lookup,
not a third audit; the standing verdict below is unchanged except where our own roadmap moved.

## Freshness (GitHub API, re-fetched 2026-09-28)

| field | 2026-09-09 audit | now | delta |
|---|---|---|---|
| commits since 2026-09-01 | — | **0** | nothing merged in 19 days |
| pushed_at | 2026-07-29 | 2026-07-29 | unchanged |
| stars / forks | 123 / 23 | 126 / 27 | +3★ (organic drift) |
| open issues | 1 | 1 | — |
| license (API + LICENSE file) | MIT | MIT | — |
| tags / releases | none | none | still no pinned release |

**Conclusion:** the scout's digest carries **no new information**. The repository has not changed since the
audit; re-running the clone/tests would reproduce the same 527-test result recorded on 09-09.

## Standing verdict (from `drafts/pykalshi-audit.md`, unchanged)

- **✅ Borrow / ⚪ Queue** — MIT, borrowable with attribution. Unusually high quality for a single-maintainer
  library: RSA-PSS signing, retry/backoff honoring `Retry-After`, typed error taxonomy keyed on Kalshi order
  codes, `book_side` direction semantics that encode the same lesson as our TR-16 phantom-fill bug, sync+async
  REST parity via codegen, private WS channels, order groups, queue positions. 527 mocked unit tests, verified
  locally on 09-09.
- **The one friction point is unchanged and is decisive for the lane our roadmap just opened:** the client is
  **auth-first** — its constructor raises without a key id + PEM key file, so there is no keyless mode. Our
  Kalshi market-data path is deliberately keyless.

## What changed on OUR side since 09-09 (the only reason to re-read the verdict)

The roadmap has grown a backtest/data-capture track that would have been pykalshi's natural home:

- **`bt-data-capture`** (Backlog, carded 2026-09-25, explicitly STARTABLE NOW — “data capture is observability,
  allowed inside the Kelly freeze”) requires an **hourly keyless Kalshi `/markets/trades` capture over rolling
  6h windows (dedup on `trade_id`)** plus a settled-universe pull.
- **`bt-engine-design`** (Done 2026-09-25) measured that that endpoint is alive with
  `ticker|min_ts|max_ts|cursor` but only reaches back to ~2026-07-18 — a forward tape recorder is the critical
  path.
- **`phase-c`** (cross-venue arb) and **`live-execution-reference`** remain Backlog, both post-Oct-8.

**Re-mapping the 09-09 fit table against the current board:**

| pykalshi component | new target card | verdict now |
|---|---|---|
| `GET /markets/trades`, `/markets/candlesticks` batch, `/historical/markets|trades`, `/series`, `/events` | `bt-data-capture` (Kalshi forward tape) | ⚪ **reference only** — the recorder is one keyless REST call with `cursor` pagination; pykalshi's auth-first constructor cannot be dropped in, and adding a Python client + key to a capture job for one endpoint is more machinery than the job needs. Mine its param/cursor semantics, do not import it. |
| Auth'd orders/fills/positions/settlements + private WS | `live-execution-reference`, `phase-c` execution leg (both post-Oct-8) | ✅ **queue** — still the only verified full Kalshi trading surface in the candidate pool; adopt (or port its V2 create-order body + `book_side` mapping to the Rust sidecar) the day a Kalshi key exists. |
| RSA-PSS signing / retry / error taxonomy | TR-16 (Done) | ⚪ cross-check reference only — already implemented in Rust. |

## Verdict

**Skip as an audit; keep as a queued, MIT-licensed reference.** Nothing to adopt today: the lane that could
have used it (`bt-data-capture`) needs keyless capture, and the lane that needs its surface
(`live-execution-reference` / `phase-c` execution) is gated behind the Oct 8 window close and a Kalshi
account key that does not exist. No roadmap change proposed — `phase-c`'s note already carries the
read-only-audit-before-build instruction.

**Scout hygiene note (corrected after reading the generator):** `scripts/scan-github-repos.py` does filter
seen repos (`if full.lower() in seen: continue`, L131), so this is not a broken filter — it is a **stale
source of truth**. `data/github-scout-seen.json` is only ever written by the scout itself: it saves the five
repos it printed that week (L198-199) plus five hardcoded defaults. A repo audited by any *other* path — a
batch audit, a user ask — never enters it. `pykalshi` was audited on 2026-09-09 through the batch flow, was
never added to the seen list, and therefore re-surfaced today with zero new information; `homerun`,
`Polyseer`, `oracle3`, `octagon` sit in the list only because the scout happened to print them first.

The five candidates in this digest are now in the seen list (this run added them), so these five will not
re-surface — but the class of noise remains for anything audited off-scout. Proposed (not shipped, awaiting
your word): one line in the digest generator that greps `drafts/` for each candidate's name and prints
`already audited → drafts/<file>` instead of a bare listing — ~10 lines, no change to the candidate filter or
the seen list.
