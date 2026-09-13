# Kalshi venue-shadow book — forward-only, with match verification

**Status:** shipped 2026-09-13 (user-approved). Observability only: no rule, size, routing or
position change. **Predecessor:** `drafts/kalshi-venue-dormancy-review-20260913.md` (Kalshi
copy-routing retired → Option A, carded `retire-kalshi-copy-routing`).
**Target read:** the post-Oct-8 Kelly-window decision. **Cron:** `copybot-kalshi-venue-shadow`
(job `3866d783e3d3`, every 15m, deliver=local).

---

## 1. Why a second ledger, when `kalshi-shadow.py` already exists

They answer different questions and must not be confused:

| | `data/kalshi-shadow.jsonl` (attribution) | `data/kalshi-venue-shadow.jsonl` (this) |
|---|---|---|
| question | which candidate venue rule would have **routed** what? | what would the same trade have **paid on Kalshi**? |
| prices | Polymarket reference for every row | Polymarket entry **and** Kalshi top-of-book (two bookings) |
| history | full book, backfillable | **forward-only** — cannot be backfilled |
| kind | counterfactual attribution, in-sample | venue-price comparison, real quotes |

The attribution ledger's PnL is a *subset* of the Polymarket book (selected + remainder = live, by
construction), so it can never be added to the live number. This book's two arms differ **only** by
the venue's price, which is the one thing the attribution ledger cannot represent.

## 2. Forward-only, and why that is not a limitation we can engineer around

Kalshi order books are not archived. A quote fetched after a trade opened is not the entry that
trade would have got, and the sidecar's matcher only searches **open** events — so historical
Polymarket questions mostly resolve to nothing at all (three probes on July questions scored 0.00
against 25 pages of open events; a current-market probe matched). Consequences baked into the code:

- Rows whose first sighting is more than `--max-quote-age-hours` (default 6) after `openedAt` are
  recorded `stale: true`, get **no** Kalshi entry, and are excluded from both books.
- The collector **never re-quotes** an existing row: re-quoting would silently rewrite an entry.
- Collection starts the first time the collector runs (window start, recorded in the summary).

## 3. The finding that changed the design: the matcher fabricates cross-listings

The sidecar resolves a Polymarket question to a Kalshi **event** by token overlap,
`token_score = |intersection| / min(|question|, |title|)`, bar `MATCH_THRESHOLD = 0.55`
(`rust-sidecar/src/adapters.rs`). Short questions built from generic tokens clear it on noise.
Observed live on the first probe (2026-09-13):

```
🎯 [Kalshi Matcher] 'Will Bursaspor win on 2026-09-13?' -> event KXANYDEMWINTEXAS-26NOV03
     "Will Democrats win any statewide election in Texas in 2026? (Blexas)"  (score 0.67)
⚖️ [Kalshi Adapter] event KXANYDEMWINTEXAS-26NOV03 ask price 99.9¢ (top level)
```

The question reduces to three usable tokens (`bursaspor`, `win`, `2026`); sharing the generic pair
{win, 2026} gives 2/3 = 0.67. Booked naively, that single row would have manufactured a **~28¢
venue edge** on a football match. Two responses:

1. **Sidecar exposes provenance.** New read-only `POST /quote` (the existing `/execute` cannot be
   reused — it books a paper trade via the execution-result webhook) runs the *same* adapter path
   and returns `price` **plus** `ticker`, `matched_title` and `match_score`. `fetch_kalshi_depth`
   is unchanged for `/execute`; both now share `orderbook_price`, and the ticker cache stores
   `ticker\ttitle\tscore` so an audited match stays audited.
2. **The ledger verifies before it prices.** A quote is priced only if it passes
   `verifyMatch()`: `match_score >= 0.75` **and** at least one shared token of length ≥ 5 that is
   not in a generic-word list. This deliberately prefers false negatives (Kalshi tickers abbreviate
   — `bitcoin` → `KXBTCD` — so a real match can be dropped) over fabricating a price. Rejections
   are counted by reason and shown on the card; **unverified matches never enter a book**.

## 4. What the book contains

Per copy: both entries, both fee legs, the outcome, and the audit trail.

- **PM leg:** the actual booked `realizedPnl` minus the entry-leg taker fee
  (`size × rate × (1−p)`, rate by keyword; the ledger charges no fees at all — see
  `drafts/c200-taker-fee-measurement-2026-09-09.md`).
- **Kalshi leg:** same size, entry at Kalshi top-of-book, same fee form at the Kalshi rate (0.07,
  flagged as needing live confirmation), no settlement fee on `resolved`.
- **Buckets always sum**: `verified + unverified + no-match === inWindow` (asserted in the run
  output, and the pre-guard migration is counted as `pre_guard_quote`).

Known limits (repeated on the card): top-of-book only — no depth, no market impact, no fill
probability; coverage is a selection, not a random sample; `won` is derived from the `realizedPnl`
sign, so partial exits and early closes make both legs approximate; paper only.

## 5. State at ship time (2026-09-13 11:01 CDT)

```
collecting 401 copies, 6 in window | verified=0 | no-match=4 | unverified=2 | stale-skips=395
buckets: {"low_match_score_0.67": 2, "pre_guard_quote": 1}
books: PM +$0.00 (n=0) | Kalshi +$0.00 (n=0) | delta +$0.00
days to Kelly window close (Oct 8): 25
```

**The binding constraint is coverage, not the delta.** Zero verified cross-listings so far (the two
quotes that resolved were the same false positive, rejected on score). Two probes on a *current*
market also scored 0.00 against 25 pages of open events.

## 6. What Oct 8 can and cannot conclude

- **If coverage stays ≈0:** the honest read is *"not measurable via this matcher"* — not "no venue
  edge". The fix is matcher quality (series-level mapping from Polymarket market → Kalshi series,
  rather than fuzzy question text), and that is a separate, larger piece of work.
- **If coverage reaches double digits:** read the delta as **$/trade**, cluster-bootstrapped by
  wallet, alongside the count of settled pairs; a delta from <20 settled pairs is not evidence.
- **Either way:** this book cannot resurrect copy-routing on its own. Reviving the leg is dormancy
  Option B, which needs its own shadow measurement of the *rule*, not just the venue price.

## 7. Operating notes

- Activation: rebuilt sidecar + `launchctl kickstart -k gui/$(id -u)/com.xsnyde2.copybot-rust-sidecar`
  (PID 1633 → 94212, 2026-09-13 10:57 CDT); `/quote` verified HTTP 200 on :3014 afterwards.
- `SIDECAR_PORT` (default 3014) makes it possible to smoke-test a rebuilt binary on a spare port
  without disturbing the live daemon — that is how the route was validated before the restart.
- Wrapper: `~/.hermes/scripts/copybot-kalshi-venue-shadow.sh` (lockfile, sidecar reachability check,
  compact status). Log: `logs/cron/copybot-kalshi-venue-shadow.log`.
- Run by hand: `npx tsx scripts/kalshi-venue-shadow.ts` (`--dry-run` to preview; against a test
  sidecar: `SIDECAR_QUOTE_URL=http://127.0.0.1:3015/quote`).
