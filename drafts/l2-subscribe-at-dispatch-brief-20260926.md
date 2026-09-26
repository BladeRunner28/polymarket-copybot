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


---

# IMPLEMENTED — v62, 2026-09-26 03:29:46 CDT

Approved option set **A2 + B′ + D**, applied to `scripts/record-l2.ts` (+`scripts/c200-intent-watch.py`).
What the brief asked for vs what shipped, where they differ:

- **A2 — shipped as scoped.** The recorder polls `FillIntent` every 20 s over a 10-min lookback, pins the
  market of any fresh dispatch (2 h TTL, `L2_PIN_TTL_MS`/`L2_PIN_POLL_MS`/`L2_PIN_LOOKBACK_MS` overridable),
  and rebuilds `universe = candidates ∪ pinned` so a 10-min candidate refresh can never drop a market we are
  mid-measurement on. Startup seeds pins before the first universe build. Heartbeat now carries
  `pinned=N pins=N lastPoll=Ns ago` so a dead poll loop and a fresh one are distinguishable.
- **B — corrected at implementation time, not as written.** The brief's "fix the print capture
  (`last_trade_price`)" rested on a wrong premise: a 90 s capture of the market channel showed it sends
  **only `book` and `price_change`** — there is no trade event, and `last_trade_price` is a field on `book`
  that did not change once in 90 s (context, not a print tape). Measured event rate: **~7.5 KB/min per
  market, ~9 price changes/min**, book re-sent every ~45 s. So B became an **event-level quote tape**
  (`data/l2-events/<assetId>.jsonl`, pinned markets only): every `price_change` level touch between the 5 s
  snapshots, which is exactly the granularity the "did it fill" question needs. Cost ~0.21 GB/day at 19
  pinned markets. Prints still come from the public tape (S1) — no in-house print stream exists to capture.
- **D — shipped, but it had never run.** The watcher's ingest call used `--ingest-closed`, a flag that does
  not exist in `c200-printthrough.py`; the call exited 2 with a usage error and the failure was swallowed
  (captured output, no return-code check), so D had ingested nothing since it was written. Fixed to the real
  entry point (`--json`) with a return-code check that raises an alert, and proven to append:
  artifact 5 → 6 lines, 30,799 → 41,023 bytes on the first live run.

## Two silent failures found while closing this out

1. **The recorder had no supervision and was dead.** It was started by hand on 2026-09-24 from a shell
   (`logs/record-l2.log` first line 2026-08-31T12:22:39Z for the previous incarnation); nothing — no
   launchd job, no cron, no alert — restarted it when it stopped at ~03:19 today. L2 coverage had simply
   stopped. It is now running **detached** (own session, reparented to launchd: `scripts/start-l2-recorder.py`)
   so a Hermes session boundary cannot reap it — which is exactly how the pre-flight instance died at
   03:28:38 — and a LaunchAgent with `KeepAlive` is written and waiting to be bootstrapped by hand:
   `~/Library/LaunchAgents/com.xsnyde2.copybot-l2-recorder.plist`.
2. **The watcher's own new coverage gate was unsafe in three ways**, all fixed before commit: (a) its
   `L2_FIX_MS` floor was `1790413140000` = **03:59 CDT, 30 min in the future** behind a comment claiming
   03:19 — it would have exempted every dispatch for the next half hour; (b) it judged coverage from the
   book file's **first line**, which passes for a market last covered days ago and would have declared
   coverage healthy for a market the recorder dropped hours before the dispatch; (c) it filtered offenders
   through `alertedIntents` but never appended to it, so a failed window would have re-alerted on every tick.
   The gate now tests for a book line **inside `[t0 − 30 s, t0 + 90 s]`** (the recorder snapshots every
   subscribed asset every 5 s, so a pin shows up within seconds), caches each verdict once, and reports
   distinct truthful reasons: `book gap A→B spans the dispatch` / `first data N s AFTER the dispatch` /
   `no asset-map entry (gamma never resolved the tokens)`.

## Verification performed

- 4 gate verdicts + both `recorder_alive` branches asserted from fixtures; real-corpus probe: fresh market
  (12.8 MB file) → hit in 0.09 s, stale market → answered from the tail with 0.00 MB read (fast path).
- `tsc --noEmit` clean; recorder live with `universe: 19 markets, 38 assets (19 candidates + 0 pinned)` and
  `lastPoll` ticking; watcher tick silent, exit 0.
- **Still unproven on live flow:** the pin path in the production process on a real dispatch (proven in a
  pre-flight instance: 8 markets pinned from real historical dispatches, sockets open, event files writing).
  The next C-200 dispatch closes it — watcher check 7 reports the verdict automatically, check 8 alarms if
  the recorder dies or its heartbeat stalls >180 s.
- Coverage-relevant note: the recorder was down 03:19:39 → 03:29:46 and again for 13 s at 03:34:00
  (handover to the detached process). **No C-200 intent was dispatched in either gap** (newest intent
  03:09:44, next dispatch after go-live), so nothing measurable was lost and the floor exempts nothing real.
