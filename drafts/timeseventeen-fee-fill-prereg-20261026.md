# SUPERSEDED — the fee-incidence question was already answered 2026-09-25

**Written:** 2026-10-26. **Superseded the same day, before any pull.** Nothing was downloaded, nothing
was run, no rule touched. Kept as a **correction trail**, not a plan. Read `bt-fee-maker-calibration`
and `bt-hist-archive-pull` instead.

---

## 1. What I got wrong

I pre-registered a study to measure "the maker/taker split of our flow" from `TimeSeventeen/Polymarket-v1`,
on two premises: that the **aggressor field had never been measured**, and that the archive still had to
be **pulled in a ≤2 GB slice**. Both are false, and both were checkable with one grep of
`data/roadmap.json` — exactly the rule the skill states:

> *"Grep `data/roadmap.json` for the class BEFORE designing anything here. A design written without
> reading them re-proposes settled questions and misses numbers the board already paid for."*

I wrote that rule down and then broke it. Recording the failure rather than deleting the file.

**Premise 1 — "never measured". FALSE.** `bt-fee-maker-calibration` (Done, measured 2026-09-25):

> **MAKER/TAKER SPLIT** — the aggressor is a **SELLER in 83.6 % of 2026-era fills** (74.6–89.4 % by band;
> buyers cross only 16.4 %), so the resting BID is the side that gets filled in this venue.

That is a decisive answer to the question my proposal was going to open — it just answers it "83.6 %
taker-side", which my `≥10 % maker share` decision rule would have read as **REFUTED**. The same card
also carries the maker-fill hazard over 783,342,642 fills: P(print at ≤ p − 0.02 within horizon) =
**71.1 % / 76.1 % / 77.6 %** at 5 m / 30 m / 1 h, and **74.3 % / 81.1 %** weighted by C-200's entry mix.

**Premise 2 — "needs pulling". FALSE.** `bt-hist-archive-pull` (Done) already landed it:
**`/Volumes/Storage/pm-data/polymarket-v1` — 49 GB, 2,152 parquet** (plus `quant-bench`, 0.60 GB /
1,417 parquet), manifests versioned into `data/archive-manifests/`. Re-verified on disk 2026-10-26.
Note the path: **`pm-data/`**, which is a *different* archive from the 50 GB / 49,484-parquet
Jon-Becker set at `prediction-market-data/` on the same volume. Both are present; do not conflate them.

**What that card already settles, which my prereg re-proposed:**

- **Fee law (archive era):** taker BUY `fee = (base/1e4) × shares × min(p,1−p)`, base 1000 → 0.10,
  matching to 1e−6 on 95–99 % of rows in every band of both months tested. Makers pay $0.
- **Schedule change:** the *current* published schedule is `shares × 0.05 × p(1−p)` — ~4× cheaper at mid
  than the archive era. So the archive calibrates **structure and attribution, never today's rate**; our
  2026-09-09 model already matches the current schedule, and the real defect was the ledger booking
  **zero** fees, not a wrong coefficient.
- **Unexplained and correctly left alone:** taker SELL fits `0.10 × shares × min(p,1−p)/p`. The card
  flags this asymmetry as unexplained and explicitly declines to build on it. **Do not resurrect it as a
  finding.**

## 2. The one part that still stands — a correction of my own advice

Unrelated to the duplicate, and worth keeping. I told you the next step was *"fix the L2 trade-print
branch — code, hours not dollars."* **That was wrong, and I verified it before building anything.**

- `scripts/record-l2.ts` **already carries the fix**; its header documents that an earlier version waited
  for an `{event:"trade"}` message that never arrives, which is why the corpus held zero print lines
  across 36,042 files. It now writes `book`, `price_change` (as `pc`) and `last_trade_price` (as `ltp`),
  the latter explicitly labelled **not a fill tape**.
- `data/l2/` — 44,432 files, **books only**. By design: the market channel sends no prints at any event name.
- `data/l2-events/` — **954 files** of `price_change` events carrying `price`/`side`/`size`/`bestBid`/
  `bestAsk` on every quote change (76,221 lines in the newest file alone). Better than I had implied.
- `scripts/c200-printthrough.py` and `scripts/fill-vs-intent.ts` **already join** the public tape to
  dispatch windows, and that join produced the 5 % / 19 % reach rates which killed the 74 % / 81 % prior.

**There is no repair to take.** The remaining gap is not a missing branch: our **booking** assumes
p(fill) = 1, which is `c200-maker-fill-assumption` — a Lane A question, already carded and already
shipped in its measured per-band-credit form.

## 3. What is actually open on this axis

| card | state | what it still needs |
|---|---|---|
| `c200-maker-fill-assumption` | Scheduled, shipped 2026-10-10 | measured per-band credit live; the **booking** question (book only what a resting bid owns) is the open Lane A call |
| `ml-u1-conditional-fill-model` | In Progress | forward arm read done: reachable ~1 leg in 5 (tape 18/339 = 5 % within 5 min), not 3 in 4 |
| `paper-ledger-fee-fidelity` | Backlog | the live gate's fee rate is a slug-keyword proxy; the venue publishes `feeType` + `feeSchedule.rate` and **18/40 markets (45 %) disagree** |
| `kalshi-maker-read-prereg` | Scheduled, approved 2026-10-12 | Kalshi maker multiplier is 0 on standard series; the read itself is what is outstanding |
| `vike-l2-prerecorder-window` | Backlog, **blocked on the user** | vendor key — never handled here; the user pulls and hands over the parquet |

**Verdict: nothing to approve in this file.** The question closed 2026-09-25 with a better answer than
my proposal could have produced, because it came from **1.2 B fills on disk** rather than a 2 GB slice.
