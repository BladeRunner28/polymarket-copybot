# L2 coverage: make the C-200 5-minute horizon measurable

**Option brief · 2026-09-26 · recommendation only, nothing applied.**

Card: `l2-subscribe-at-dispatch` · Measurement it unblocks: `c200-intent-printthrough-check` →
decision `c200-maker-fill-assumption`.

## Key insight

The rig cannot measure the 5-minute window not because the data is hard, but because the recorder's
universe is defined by **signal freshness**, not by **positions we hold or have just opened**:
`activeMarketIds()` takes the top-25 markets by copy-candidate observed-trade recency (2h window,
`observationOnly=false`) and refreshes every 10 minutes. Measured today:

- every one of the 6 measured legs' book files begins **2.7–8.6 min AFTER its dispatch** — the 5-minute
  horizon has never been covered, on any leg;
- **29 of the 31 markets where we currently hold an open C-200 position are not in the universe at all**,
  and only **1 of 7** measured-leg markets is still in it (coverage ends when the signal goes stale, not
  when the position does);
- and the corpus contains **zero trade prints, ever** — 0 of 36,042 files hold a trade line, because the
  handler waits for an `{event:"trade"}` message the market channel never sends (it sends `book`,
  `price_change`, `last_trade_price`). The "did it print" half therefore rests entirely on the thin
  public tape (2–50 rows per market).

Two independent defects: coverage membership/latency, and a dead print-capture branch.

## Capacity — measured, not assumed

- **One socket per market is a server constraint** (a second subscribe on the same socket is rejected), so
  N markets = N sockets. Current production: 18 markets / 36 assets.
- **Probe (2026-09-26 03:09, 20 markets outside the universe, staged batches of 5):** 20/20 sockets
  received book data while the production 18 stayed healthy → **38 concurrent sockets verified**, first
  message 0.4 s (min 402 / median 433 / max 462 ms), production heartbeat `lastMsg=1s` after. The venue's
  ceiling is at least 38; the design needs ≤37.
- **Concurrency budget:** worst case over the last 7 days is **19** distinct C-200 copy markets inside any
  rolling 2 h (average 5.4). A bounded "hold a dispatched market for 2 h" design therefore adds ≤ +19.
- **Disk:** ~1.3 MB per market-hour (both tokens). At the recent copy rate (13–50 legs/day, average ~27) a
  2 h TTL adds **~70 MB/day** (worst case ~130 MB). Corpus today: 9.6 GB / 36,042 files.

## Options

| | what | trade path | cost | latency to coverage |
|---|---|---|---|---|
| **A2** | recorder polls the DB for new dispatches/legs (20–30 s) and adds those markets immediately, holding each ≤2 h | untouched | +1 socket & 1.3 MB/h per copy; one extra read per poll | ≤30 s (was 2.7–8.6 min) |
| **A1** | dispatch path appends a line to `data/l2-subscribe.jsonl`; recorder tails it | one never-throw write, same shape as the FillIntent shadow | as A2, lower latency | ~1–3 s |
| **B** | fix the print capture (`last_trade_price` → append a print line) | untouched | none (one branch) | n/a — gives an in-house print tape |
| **C** | universe = open positions ∪ candidates (unbounded) | untouched | +29 sockets now, ~0.6 GB/day, re-admits dead-token markets (why v61 excluded it) | immediate |
| **D** | 1 h after each dispatch, ingest the public tape for that market into the artifact | untouched | one bounded HTTP fetch per leg | n/a — archive-comparable prints, free |
| **E** | leave it | — | — | the gate stays unanswerable |

## Reality checks

- **No backfill.** The 6 existing legs' windows are gone; this makes the rig capable from the next
  dispatch onward. The historical read stays 0/6 with its stated caveats.
- **5 s cadence can miss an intrabar touch.** The print capture (B) is the tighter instrument for "a print
  at or below the level" because it is event-driven. A 1 s cadence for the first 10 min after a dispatch
  is a further knob (~0.5 MB per market for that window) — worth it only if B's coverage proves thin.
- **A restart is required either way.** The running process started Sep 24 01:30; the watchdog only
  restarts on death, so the change needs a deliberate `launchctl kickstart -k`. Append-only files, a few
  seconds of gap, nothing lost.
- **Nothing here is a trading change.** A2/B/D are recorder-only; A1 adds one write to the dispatch path.
  No rule, size, gate, sidecar or booked figure is touched. Any eventual change to the 2¢ remains a
  separate approval with a before/after on every affected figure.
- **Even with perfect coverage the gate's *rate* needs ≥50 measured legs.** This buys capability, not the
  number.

## Verdict

**A2 + B + D** — one small change to `record-l2.ts` (~40 lines), one restart: poll for dispatches and hold
those markets for a bounded 2 h (fixes membership *and* latency), capture `last_trade_price` prints (gives
the archive-comparable half from our own data), and fold the public tape into the artifact for every leg
(free cross-check). ≤ +19 sockets against a measured ≥38 ceiling, ~70–130 MB/day, **no trade-path change**.
C rejected: redundant once A2 holds the copied markets, and it re-admits the dead-token markets that were
deliberately dropped. E rejected: it leaves the decision card unanswerable.

**Recommended default: A2 + B + D.** A1 only if the 30 s poll latency proves too coarse (it will not, for a
5-minute test).

Reproduce the measurements:

```
python3 -c "…"            # universe reconstruction vs open positions (see SKILL notes)
node ws-headroom-probe.js # 20-socket staged probe; kept out of the repo
du -sh data/l2 && ls data/l2 | wc -l
grep -c '"t":' data/l2/*.jsonl   # 0 files: no print lines in the corpus
```
