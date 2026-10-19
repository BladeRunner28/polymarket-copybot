# Asset audit — `vike-io/vike-data-cli` (2026-10-18)

**Verdict: WATCH — the *data* is the asset and it is worth a bounded one-off pull; the *code* is worth nothing to us.**

Split verdict, stated explicitly because the repo and the dataset have different licences and different value:

- **Full-L2 Polymarket archive (CC BY 4.0, key-gated)** → ✅ the only source that can retro-fill our pre-recorder book history. Recommendation is a scoped 205 GB pull of the 37 days before our own recorder existed, not an integration.
- **`@vike-io/cli` + MCP server + 72 skill playbooks (MIT)** → ❌ nothing to vendor. It is a vendor's own thin client for its own HTTP API; we have no Node CLI layer and no agent-skill layer that this would accelerate.

Audited read-only from the GitHub API and the vendor's keyless endpoints. **Nothing was downloaded, installed, executed, or wired. No key was created or used.**

---

## What it is

A CLI (`vike`) + MCP client + agent skill pack for **Vike Data**, a commercial data vendor. The vendor sells one product we care about: **a daily-partitioned Parquet archive of full Polymarket L2 order-book events**, plus a taker tape and a derived top-of-book table. The repo is 322 KB / 90 files of which 43 are `.md` (127 KB of skill playbooks) and 30 are `.js` (72 KB of HTTP wrappers); the Python is 4 files / 16 KB, all examples.

Vendor-owned repos are a different animal from the community repos this audit normally sees: ★0 / 0 forks / 1 open issue means **no community validation and no community durability** — the only signal is that the vendor still ships (v0.12.0 → v0.12.1 on 2026-10-17, `ci.yml` last three runs `completed/success`).

## Anatomy facts that drove the verdict

| Fact | Value | Why it matters |
|---|---|---|
| Repo licence | MIT (`LICENSE`, API `license.spdx_id=MIT`) | Code is borrowable **if** we wanted it. We do not. |
| Data licence | CC BY 4.0, stated in the manifest itself, with the required attribution string, and an explicit "grants no rights to any Vike source code" | Separates the two questions cleanly — the archive can be used without touching the client. |
| Coverage | **85 daily partitions, 2026-07-25 → 2026-10-17** (`/archive/manifest.json`, generated 2026-10-18T00:45:54Z) | Still growing daily ⇒ alive, not a dumped-once dump. |
| Real scale (off the manifest, not the prose) | book_events **539.9 GB / 35.49 B rows** (latest day alone: 483.4 M rows, 7.77 GB) · trades **1.0 GB** · l1_quotes **46.5 GB** | The README's numbers reconcile with the vendor's own file listing; no inflation found. |
| Gating | `/archive/manifest.json` → HTTP 200 keyless. `/archive/samples/book_events.parquet` → HTTP 200 keyless, 6,496,750 bytes, **byte-exact** vs the sample README's stated size, real `PAR1` Parquet. `/archive/` root, `/archive/venue=.../book_events.parquet` → **HTTP 401** | Data files need an `X-API-Key` header. The free sample and the manifest do not — which is exactly enough to verify everything below without an account. |
| Activity | pushed 2026-10-17, releases v0.12.1 (10-17) and v0.12.0 (10-16), CI green ×3 | Alive. |
| Substance vs claim | 72 skill playbooks, `tests/`, `ci.yml`, `evals/`, lockfile, `examples/polymarket_archive.py` (a real polars reader), range-request warning in the example docstring | Claim matches code *for a client*. The client is simply not the valuable part. |
| Trust flags | README requires a key (`vk_`); no telemetry markers; one open issue: **#22 "Clarify redistribution rights for on-chain OHLCV API exports"** | Key is a vendor account key, not a wallet key — but it still gates the data. |

Rates: README claims 20,000 req/hour, 5 keys/account, archive downloads uncounted. **Unverified** — I did not create a key, so this is a README claim only.

## Verified schema — this is the whole reason the audit exists

`book_events` (event-level, ordered):

```
token_id, condition_id, ts, local_ts, seq,
event_type ∈ {book, price_change, trade, tick_size_change, status},
is_snapshot, side ∈ {none, buy, sell}, price, size,
best_bid, best_ask, bids, asks, tick_size, status
```

`trades` (taker tape): `token_id, condition_id, ts, local_ts, seq, price, size, side`
`l1_quotes` (derived): `token_id, condition_id, ts, local_ts, bid, ask, bid_size, ask_size`

Partitioning: `venue=polymarket/date=YYYY-MM-DD/{book_events,trades,l1_quotes}.parquet`, plus an **additive** family layout for crypto up/down (`asset=btc/tenor=5m/...`) with `asset=other/tenor=other` as the never-dropped catch-all. `range_requests: true`.

## What we already run (the honest baseline, verified in our repo)

| Our asset | Coverage | Granularity | Gap vike fills |
|---|---|---|---|
| `data/l2/` recorder (`scripts/record-l2.ts`) — 42,790 token files, **17 GB**, first files **2026-08-31**, live now (08:21 today) | 2026-08-31 → now | **5-second top-25 snapshot** per token; event tape only for PINNED markets (`data/l2-events/`, 1.8 GB) | Sub-5-second book state; and **everything before 08-31** |
| `MarketSnapshot` (Prisma) — 15,886,692 rows since 2026-07-14 | 07-14 → now | L1 only (`bestBid/bestAsk/spread`) | Depth, queue, deltas |
| `/Volumes/Storage/pm-data` — 50 GB (Polymarket-v1 + quant-bench) | historical | **trade level** (`OrderFilled`, maker/taker, `fee_usdc`) | Book depth; already fed `drafts/fee-maker-calibration-20260925.md` (783 M fills) |
| Venue | — | Polymarket serves **no historical L2** after the fact | This is why we built the recorder; it is also why a third-party archive is the *only* backfill path |

**The measured gap.** `PaperTrade` C-200 (`BANKROLL_200`) starts **2026-07-22**. Trades opened before 2026-08-31 — i.e. with **zero book state at entry** — are **1,130 of 2,484 C-200 trades (45 %)**, and **10,448** across all lanes, over **2,537 distinct markets**. vike covers 07-25 → 08-30 = **37 days, 205.2 GB of `book_events`, 12.68 B rows**, which closes all of it except the first three days.

Two honest qualifiers on that window:

1. Our gap-window flow is **100 % non-crypto** (esports/ATP: `lol-vit-g2-2026-07-25`, `atp-lajal-ruiz-2026-07-22`). Those markets land in vike's `asset=other/tenor=other` catch-all, so **the family layout does not shrink our pull** — we take the date-partitioned `book_events` files. Any plan that quotes the small crypto-family sizes as our cost is wrong.
2. The existing `c200-intent-printthrough-check` already answers "did our price *print*" from the trade tape (bar: materially below 74.3 % reached-levels ⇒ the −2¢ is booked on fills that never happened). `book_events` answers the strictly harder question — **was size there, and would a resting order in that queue have filled** — which is the D2 fill model's input, not a replacement for that check.

## Fit table

| Component | Maps to | Verdict |
|---|---|---|
| 37-day pre-recorder `book_events` backfill (205 GB) | **`phase-d2-fill-model`** (gate "~2 weeks of L2 in data/l2/" is already satisfied — we have 48 days) | ✅ **adopt as data**, bounded, after user approves the key |
| Event-tape fidelity check of our 5 s recorder on 2–3 overlap days | `phase-d2-fill-model`, and the recorder's own trust | ✅ adopt, cheap (~21 GB or the free sample) |
| `trades` taker tape (1.0 GB / 85 days) | cross-check of the `OrderFilled`-based tape we already hold | ⚪ marginal — cross-check only |
| `@vike-io/cli`, MCP server, 72 skill playbooks | — | ❌ not portable (vendor's own client; no capability we lack) |
| Hyperliquid perps, cohort positioning, labelled EVM wallets | — | ❌ out of scope; not our venue, not the copy lane |
| `examples/polymarket_archive.py` (download-whole-file + polars) | pattern for the reader | ⚪ concept only — 60 lines, and the useful line is the warning *not* to point a Parquet reader at the URL (range-request storm), which the manifest's `range_requests: true` makes easy to get wrong |

No card asks for "historical L2 archive" by name; `phase-d2-fill-model` asks for the *use* and `phase-data1` owns external-dataset wiring generally. `phase-data1` is the right host for the pull mechanics; `phase-d2` is the consumer.

## Recommendation (pre-registered)

```
REC — Backfill the pre-recorder L2 window from the Vike archive
  Hypothesis:   The 1,130 C-200 trades opened before 2026-08-31 have book context that changes their
                fill verdict — at least 25% of them would NOT have filled at intent−$0.02 with our size
                available in the book, versus the assumed-fill baseline.
  Measurement:  read-only replay. Pull book_events for 2026-07-25..2026-08-30 (37 files, 205.2 GB),
                build per-token book state at each PaperTrade.openedAt, and compute depth-at-intent-price
                vs simulated size for the 1,130 gap-window C-200 legs (scripts/c200-printthrough.py
                already does the join for our own recordings — extend its reader to Parquet).
  Decision rule: if ≥25% of gap-window legs flip to no-fill (or the implied fill rate differs from the
                08-31→now recorder-window baseline by >10 pp) then adopt the archive as the D2 fill-model
                input and keep the pull; else keep the 37 days as a one-off calibration set and drop the
                vendor relationship.
  Cost:         1 dev-day reader + 0.5 day join; 205 GB on /Volumes/Storage (377 GB free → 172 GB left);
                1 free vendor account key, download-only.
  Reversibility: delete the 37 date partitions; nothing in the live lane references them.
```

**Precondition the user must own:** the data is behind a free `X-API-Key` (`vk_…`) issued to an account at vike.io. I did not create one and will not. If a vendor account is unacceptable on principle, the audit collapses to "drop" — there is no keyless path to the full archive, and the free sample (one 5-minute market, one day) is only enough for a fidelity check, not a backfill.

## NOT portable

- The CLI, MCP wiring, and the 72 `skills/**/SKILL.md` playbooks — a client layer for a vendor we would call with `curl`/`polars` at most 37 times.
- Anything Hyperliquid / perp / cohort / labelled-wallet — different venue, different problem.
- Their `evals/` harness (agent-question evals) — not our test shape.

## Honest caveats

1. **Single-vendor, zero-community.** ★0, one open issue, no forks. If Vike disappears, there is **no second source of historical Polymarket L2** — the venue does not serve it. That asymmetry argues for pulling the bounded fixed window *now* rather than "when we need it": the window cannot grow, and the vendor is the only holder.
2. **Key-gated.** Every data file returns 401 without `X-API-Key`. Only the manifest and one daily 5-minute sample are keyless. Treat any plan that assumes keyless bulk pulls as wrong.
3. **Rate/price claims unverified.** 20,000 req/h and "archive downloads uncounted" are README text; I created no key, so they are untested. Nothing in the recommendation depends on them (37 whole-file downloads).
4. **Licence is fine but redistribution of *derived exports* is unsettled** — vendor issue #22 is open on exactly this. Pull-and-analyse locally: no issue. Re-publishing derived datasets: wait for that answer. CC BY 4.0 attribution string is supplied by the manifest and must ship with any table we publish.
5. **The 45 % figure is our book's, not the archive's.** 1,130/2,484 C-200 legs is measured from `prisma/dev.db`; the archive's usefulness for them is inferred from its coverage window and schema, **not** yet demonstrated on a single row — the decision rule above is what demonstrates it.
6. **205 GB is the whole-window price and it does not shrink** for our flow (catch-all partition), against 377 GB free on `/Volumes/Storage`. Bounded and deletable, but it is 54 % of free space for one measurement.
7. **Their `l1_quotes` duplicates what our `MarketSnapshot` already has** since 07-14 — 46.5 GB of the archive is not worth pulling.

---

### Registry block (NOT applied — this job's constraint is audit-doc-only)

Both candidate hosts exist in `data/roadmap.json`; append to the existing card rather than creating one:

```
AUDIT INPUT (2026-10-18, pending user approval; drafts/asset-audit-vike-data-cli-20261018.md):
vike-io/vike-data-cli (MIT client / CC BY 4.0 archive) — full Polymarket L2 event archive verified off
the vendor API: 85 daily partitions 2026-07-25..2026-10-17, book_events 539.9 GB / 35.5 B rows, schema
(seq, event_type, is_snapshot, price/size, bids/asks ladders), manifest keyless, data files 401 without
X-API-Key, free daily sample byte-exact. Our own recorder (data/l2/, 5 s top-25 snapshots) starts
2026-08-31, so 1,130/2,484 C-200 legs (45 %) and 10,448 all-lane legs have zero book state at entry;
the pre-recorder window is 37 days / 205.2 GB and Polymarket serves no historical L2, so this is the only
backfill path. Proposal: scoped read-only pull + extend c200-printthrough.py to Parquet (1.5 dev-days,
205 GB of 377 GB free). Decision rule: adopt if ≥25 % of gap-window legs flip to no-fill, or the implied
fill rate moves >10 pp vs the 08-31→now baseline; else one-off calibration and drop. Precondition: user
creates the free vendor key (no keyless bulk path). Client code: nothing to vendor.
```
