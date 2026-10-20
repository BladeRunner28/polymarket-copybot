# CopyBot research — weekly deep-dive · 2026-10-19

Fact sheet: `scripts/research-collect.py`, stamp **2026-10-19T13:30:30Z** (fresh). Book numbers below are
from that sheet or from repo files I opened; every external claim carries a URL and the date I read it.
Reference run for radar yield: `python3 scripts/radar-yield.py` (8 runs logged).

---

## 0. On your desk (in deadline order)

1. 🔴 **`go data-api-v2` / `hold`** — Polymarket Data API v1 is **retired 2026-10-24, 5 days out**, card
   `data-api-v2-migration` still `Scheduled`, **no code moved** (today's brief asked this and it is
   unanswered; nothing new from me on it except the count below).
2. Three asset audits awaiting approval — §5. Cheapest first: `agent-next/polymarket-paper-trader`.

---

## 1. Landscape — the week in markets, venues, tooling, literature

**Polymarket: quiet on fees, loud on retirement.** The changelog's newest entry is still **Oct 7, 2026**
(`/v2/tokens` token lookup, `/v2/positions` `first_entry_at`, cached `/v2/resolutions`) —
[docs.polymarket.com/changelog](https://docs.polymarket.com/changelog), read 2026-10-19. No fee-schedule
change, no taker-delay change this week (crypto taker delay still 150 ms, set 2026-09-04, same page).
The material item is not in the changelog: the migration guide states, verbatim,
> **"Data API v1 is retired on October 24, 2026."**
> — [docs.polymarket.com/migrate/data-api-v1-to-v2](https://docs.polymarket.com/migrate/data-api-v1-to-v2), read 2026-10-19.

The Sep 4 release note ("`/v1` keeps serving unchanged but is frozen") read as a freeze, not a sunset;
the migration guide is the operative document and it names a date **5 days out**. Our exposure, grepped
today: **10 `data-api.polymarket.com` occurrences across 8 files**; the live path is
`src/lib/adapters/polymarket.ts` (3 sites — leaderboard, positions, activity), the rest are the
print-through instrument and read-only scripts. Parity is done (`drafts/data-api-v2-migration-20261017.md`:
values identical, four shape blockers — `offset` rejected, sort enums renamed, leaderboard wallet key is
`user_id`, `/closed-positions` folded into `/v2/positions?status=CLOSED`). What is missing is the cutover
and one gate clause: a **print-level `/trades` parity read on ≥20 conditions**, because
`scripts/c200-printthrough.py` feeds a published fill number (today's brief, 2026-10-19).

**Kalshi: an authenticated-lane rate-limit change we do not feel yet.** Changelog entry **October 15,
2026**: `GET /trade-api/v2/portfolio/balance` moved out of the Read budget into its own bucket — 1 req/s
on Basic and Advanced, 5 req/s on higher tiers, one second of budget with **no burst**, `429` above it;
"Balance only changes on fills, settlements and transfers, so react to those … rather than polling this
endpoint" — [docs.kalshi.com/changelog](https://docs.kalshi.com/changelog), read 2026-10-19. Impact on us
today: **none** — every Kalshi lane in the stack is keyless read-only (`markets`, whale-tracker). It
matters only if Phase C ever authenticates, and then it argues for fill-driven balance reads, not polling.
The same page carries three entries labelled **October 22, 2026** (REST schema corrections, FIX
per-market mass cancel, Margin funding averaging) — future-dated relative to today and therefore
`unverified` as live; treat as announcements.

**Literature: the first published magnitude for the Phase C thesis.** *Combinatorial Arbitrage in
Prediction Markets* (Seo et al., arXiv:2610.23517v1, submitted **2026-10-19**, q-fin.TR/CP,
[arxiv.org/abs/2610.23517](https://arxiv.org/abs/2610.23517); via [rss.arxiv.org/rss/q-fin.TR](https://rss.arxiv.org/rss/q-fin.TR)).
Prices outside the convex hull of admissible payoff vectors are arbitrage; the paper recovers **1.9 M
logical relations over 255,000+ contracts** from venue metadata plus *semantic analysis of resolution
criteria*, compiles them into constraint systems, and replays **full-depth Polymarket order books**:
"guaranteed profit after spreads and fees equals **2.2 % of committed capital**, while profit at
resolution reaches **3.2 %**", and opportunities "persist longer and attract less observed participation
where relation discovery and execution are more costly."

What this does and does not say for us: it is a **Polymarket-internal** result (relations between
Polymarket contracts), so it prices the *intra-venue half* of `phase-c`, not the Kalshi cross-venue half;
2.2 % net-of-fee on committed capital is a real magnitude for a market-neutral lane, but it is earned by
(a) relation recovery at 255 k-contract scale and (b) full-depth book execution — the two costs the paper
itself says protect the residual. It does **not** license a build: `phase-c` stays gated on its own card,
and the paper is CC BY-NC-SA 4.0 even if code is released (non-commercial — read it for method).
Correction to any prior framing: our Kalshi arb lane is *not* what this paper measures.

**Practitioner signal (detection only).** r/predictionmarkets, 2026-10-17, "My paper bot wins 92 % of its
trades and is still down"
([thread](https://www.reddit.com/r/PredictionMarkets/comments/1x7x5i0/my_paper_bot_wins_92_of_its_trades_a)) —
same failure mode our own book measures (§3, fact 1). `unverified`, and not a basis for anything.
r/Polymarket 2026-10-18 "any good tools left?" names no tool. r/Kalshi feed **STALE (95.2 h) after HTTP
429** — the documented rotation quirk, not a block.

---

## 2. Reusable assets

Radar yield first, because it frames the section: **8 runs, 103 usable slots (12.88/run), but only 3 new
leads reached the queue in 17 runs = 0.18 new/run**; dedupe skips 246 no-licence, 123 already in
`drafts/`, 102 already in queue. The verdict is pre-registered at n=12 — **INSUFFICIENT n=8/12**, quote
it, don't pre-empt it. This week's `newest Kalshi` block was 5/5 no-licence or zero-star; the Polymarket
block 4/5 the same. One asset is worth a second look.

### 2.1 `crowdintel-xyz/polymarket-agent-kit` — verdict **AUDIT** (enqueued 2026-10-19)

MIT · ★0 (1 fork) · created 2026-08-13 · pushed 2026-10-19 · 86 KB ·
[repo](https://github.com/crowdintel-xyz/polymarket-agent-kit)

Substance, read not skimmed: the *code* is a client — a 182 KB `openapi.json`, four agent-skill markdowns,
two examples, one CI workflow, **no tests**. The *data* is behind a vendor token (`cint_mcp_…`; free tier
**20 MCP calls/day, 50 REST req/hr**). So, like `vike-data-cli`, the repo is not the asset. What is
different here is that the vendor publishes its **methodology** in the repo:

- `docs/metrics.md` — ranks wallets on the **lower bound of a confidence interval on EV per dollar**
  (`ev_ci_low`), with **Kish effective sample size** so that "positions inside one event count as fully
  correlated", a **90-day half-life** decay, and **Benjamini–Hochberg q-values** across 3 M tested wallets;
  a `trader_kind` verdict that separates `maker` (machine flow with rebates ≥5× taker) and `bot` from
  `human`, and labels PnL as resolved-outcome with a `pnlAsOf` stamp.
- `docs/pitfalls.md` — seven named failure modes, two of which we have already been bitten by: raw win
  rate cannot sort a board, and "**every Polymarket proxy wallet starts at `nonce = 1`**" (so nonce is not
  freshness).

What it would replace or accelerate: **an independent selection oracle for the open U2b question**. Every
feature U2 priced is *ours*; a third party scoring the same wallets from the same chain with a published
method is a different measurement, the same role the Polycopy Copy Score plays on
`polycopy-free-account-oracle`. Adoption effort: ~half a day for a snapshot job — but the blocker is
**look-ahead**: the vendor serves a *current* snapshot (`pnlAsOf`), no history, so any read of it is
**forward-only**, and at ~5 copies/day the U2b bar (≥200 forward legs) is ~40 days away. That is exactly
why this goes to the audit worker with that constraint stated, rather than being proposed by me as a
measurement. Verdict **audit** (queued).

### 2.2 `darup67/market-lab` — verdict **DROP**

`NOASSERTION` licence · ★1 · created 2026-09-07 · pushed 2026-10-19 · 375 MB with data committed ·
[repo](https://github.com/darup67/market-lab)

Genuinely well-built for what it is: append-only, idempotent recorders for the four **Kalshi 15-minute
crypto windows** (KXBTC15M/ETH/XRP/SOL) plus CME futures bars, each row carrying `minute_quotes` (clock-
aligned YES bid/ask at open and each minute, from Kalshi 1-minute candles), committed because the venue
serves ~2 days and nothing can be backfilled — and it says so honestly ("~10 min delayed ⇒ research data,
not an intraday signal source"). Drop reasons, in order: the licence is **not a licence** (NOASSERTION
grants nothing), the venue is **Kalshi 15-minute crypto**, and our copy lanes do not route to Kalshi
(retired by decision, not by oversight), and the method duplicates the L2 recorder we already run for the
markets we do trade. The one transferable idea — deriving a book proxy from 1-minute candles for markets
we have no book state on — is already covered by our own skip counterfactual, which marks skipped
candidates to resolution (4,945 settled, `drift-gate-counterfactual`, read 2026-10-10).

### 2.3 Not re-listed (recurring, already read)

`mbordash/DRADIS` (★29, still in the radar) — audited 2026-10-15, idea measured and **dropped** (§6).
`pmxt-dev/pmxt` — upstream audited in `drafts/kazelad-pm-sdk-audit.md`, superseded by the carded ccxt
decision. `Jon-Becker/prediction-market-analysis` — read (`drafts/pma-audit.md`), carded as `phase-data1`.
`parkyucheol-del/alphapipeline` — audited today by the worker, **drop** (§5).

---

## 3. Our book against it — five measured facts

1. **Per leg, C-200 earns 2.3× STANDARD at a *lower* win rate.** C-200: 2,485 settled, **+$6,070.17**,
   win **0.477** → $2.44/leg. STANDARD: 8,975 settled, **+$9,508.08**, win **0.633** → $1.06/leg.
   *Implication:* expectancy and accuracy are decoupled in our own book, so any ranking built on win rate
   (including the copy-score's) is measuring the wrong quantity — the same thing the CrowdIntel methodology
   argues from the other direction. *Does not imply* C-200 should be scaled: the ladder gate and v62's
   band reads own that, and v62 closed NO-CHANGE today (tuning #60).
2. **The headline 30-day number is a lane blend, not a run-rate.** 30 d: n=802, **+$4,193.54** (+$5.23/leg)
   mixes both lanes and both is above either lane's lifetime rate — quote it as a blend or not at all.
3. **Day- and week-grain reads are single-leg artifacts.** last 1 d: **n=2, −$12.45** (no information at
   n=2). 7 d: **n=127, +$284.67**, of which one leg (`swe-org-gais…-org`, $100 @0.16332 → +$512.29) is
   more than the whole window (today's brief). *Implication:* n before sign, every time.
4. **Admission is timing-bound, not score-bound.** 24 h decisions: **776 skip / 5 paper_copy (0.64 %)**;
   of the newest 400 skip rows, **price-drifted-late 178 (44.5 %)**, TTR <2 h 51, confidence 49, coalesced
   47, NFL blacklist 38. *Implication:* the biggest cost on the book is a **one-tick drift bar**
   (0.005 vs `maxPriceDrift` 0.0040), not the score — and no change is proposed: the decay bar reads
   no-action on both bases (#60) and the counterfactual's pre-registered gate is structurally unable to
   trip (`drift-gate-counterfactual`, read 2026-10-10).
5. **"Open positions 1,279 / $13,675.57 at risk" is 98 % not C-200.** The C-200 open book measured at
   #60 is **3 legs / $47.97 = 1.2 %** of a $4,035 cap. *Implication:* the fact sheet's exposure line must
   be read by lane or not at all — it is the STANDARD lane's 8,975-leg paper book.

**Fact-sheet integrity (report, don't paper over).** Three defects, none of them a `SOURCE FAILED` line:

- **`DecisionJournal read FAILED: no such column: outcome`** — second consecutive day. `research-collect.py:199`
  builds `COUNT(DISTINCT marketId || '|' || outcome)`; `PRAGMA table_info(DecisionJournal)` has 24 columns
  and **no `outcome`** (the column lives on `PaperTrade`). Effect: the "distinct skipped market/outcome"
  line is void every run; the funnel and skip-mix lines survive.
- **The Kalshi venue block is a silent zero, not a snapshot.** 200/200 rows carry `volume_24h_fp = "0.00"`;
  `limit=200&status=open` returns the newest listings, and today's top row is a 7-leg MVE combo created
  `2026-10-19T13:31Z`. `order=`/`sort=` are ignored (4 variants, all Σ0); a **close-window** filter returns
  real volume (100 markets, Σ 39,112, max 10,054). So the block reports listing churn as a zero-volume
  market.
- **Lane blends** in the exposure line and the 30 d PnL (facts 2 and 5).

Reddit r/Kalshi cache **95.2 h stale after a 429** — expected rotation behaviour, noted so it is not
mistaken for a block.

---

## 4. Recommendations (3 of a possible 4; ranked by expected value per unit of effort)

### REC 1 — Make the fact sheet say what it means (3 defects, ~30 min)
```
Hypothesis:   the weekly/daily fact sheet is the only book input the research agent has, and two of its
              blocks are currently void (DecisionJournal query error; Kalshi zero-volume page) while two
              lines blend lanes that must never be blended.
Measurement:  (a) drop `outcome` from research-collect.py:199 (use marketId only, or gate on
              "outcome" in cols); (b) filter the Kalshi read by a close window (e.g. max_close_ts = now+7d)
              or order by volume if the API ever honours it — verified today: close-window Σ 39,112 vs 0;
              (c) print the open-exposure line split BANKROLL_200 | STANDARD.
Decision rule: if by 2026-10-26 every run prints a distinct-skipped line, a Kalshi sum > 0, and a
              lane-split exposure line, adopt; if the Kalshi block still reads 0 on a close-window filter,
              delete the block rather than carry a fake zero (a missing line is honest, a zero is not).
Cost:         ~30 min, read-only collector changes, zero live-lane risk; no rule/size/threshold touched.
Reversibility: revert one commit; the collector writes nothing but its own stdout.
Touches:      scripts/research-collect.py (only file). Card: fact-sheet-collector-truth.
```

### REC 2 — Price the convex-hull question on the book we already hold (~2–3 h, read-only)
```
Hypothesis:   the 2.2 %-of-committed-capital result is earned at 255k-contract scale; at our scale the
              relations that matter are the ones inside events we already hold, and if our held
              exhaustive sets price away from 1 by more than fees, a hedge/arb layer would touch the book.
Measurement:  read-only replay over the 1,279 open legacy legs + gamma metadata: group open legs by event,
              take every multi-outcome (neg-risk) event where we hold >=1 leg, compute sum-of-asks (and
              sum-of-bids) vs 1 net of each market's published fee class, and report the distribution of
              gaps plus how many of OUR legs sit on the rich side. n = number of exhaustive events we hold.
Decision rule: if >=10 of our held events show a hull gap > 2x the round-trip fee against us (i.e. we are
              systematically on the expensive side), card a pre-registered hedge read; if <10, record the
              null and keep phase-c parked — the paper's magnitude does not transfer to our book.
Cost:         ~2-3h offline replay, keyless, no live-path change, no writes.
Reversibility: nothing written outside drafts/.
Touches:      new scripts/hull-gap-replay.py + drafts/; card c200-exclusive-pair-hull-check. Phase-c
              (Backlog) is the consumer; this does not build it.
```

### REC 3 — Store the closed-position distribution and price `ev_ci_low` as a U2b candidate (~1–2 days)
```
Hypothesis:   a lower confidence bound on EV per dollar (event-clustered effective n, 90-day decay,
              BH-corrected across tested wallets) separates our forward legs where the snapshot features
              U2 priced do not — the U2 read's inversion is what a CI bound is designed to fix.
Measurement:  WalletProfile stores only aggregates (roi30d, winRate30d, resolvedTradeCount30d,
              consistencyScore — 3,568 rows, no distribution), so first persist the per-wallet closed-position
              rows the profiler already fetches (src/lib/adapters/polymarket.ts closed walker), compute
              ev_ci_low point-in-time per entry, then run the card's own instrument:
              `python3 scripts/wallet-selection-test.py --feature ev_ci_low`.
Decision rule: the card's PRE-REGISTERED bar verbatim, unchanged: promoted only if, on >=200 of our own
              FORWARD legs, its top tercile beats price-only with a market-clustered 95% CI excluding zero
              AND beats both copy-all and the top-tercile-by-entry-price selector. A read that clears one
              CI is reported as a miss. At ~5 copies/day, n=200 is ~40 days: if n<200 at 2026-12-15,
              report INSUFFICIENT, never a partial verdict.
Cost:         ~1-2 days offline (schema column + backfill pass); no live-path change, no rule/size/gate.
Reversibility: drop the column and the offline job; nothing in the live lane reads it.
Touches:      prisma/schema.prisma (WalletProfile), the scan-wallets profiler, ml-u2b-selector-search (home
              card — no new card; this adds a candidate the card does not list).
```

**Not proposed, deliberately:** moving `maxPriceDrift` (#60 watch item, decay bar no-action), any
size/band change (v62 closed NO-CHANGE today, #50's |z|<1.5 binds), the sub-$0.05 floor (carded, gate
2026-10-24, see §6), Kalshi routing (retired), and anything that re-argues the Kelly regime.

---

## 5. Asset audits — awaiting your approval

Ranked by expected value. **All three are `watch` — no adoption follows from approval alone; each buys a
read, not a change.**

1. **`agent-next/polymarket-paper-trader`** [watch] · audited 2026-10-15 20:26 CDT ·
   [report](http://localhost:3013/drafts/asset-audit-polymarket-paper-trader-20261015)
   → price fees from the venue per market for **ARCHIVED** markets too, via the CLOB
   `clob-markets/{conditionId}` `fd` block (touches `scripts/capture-fee-schedules.ts` and the
   `paper-ledger-fee-fidelity` card).
   *Rule:* `fd` must resolve ≥90 % of conditionIds (measured 25/25 where Gamma serves 6/25) **and** the
   re-pricing must move total fee ≥$25 or flip a leg's net sign; else keep the proxy and record the null.
   *Effort:* ~1–2 h, read-only, keyless. **Cheapest item that can move a published number.**
2. **`vike-io/vike-data-cli`** [watch] · audited 2026-10-18 08:24 CDT ·
   [report](http://localhost:3013/drafts/asset-audit-vike-data-cli-20261018)
   → pull the 37-day pre-recorder L2 window (2026-07-25..08-30, 205 GB) so the **1,130 uncovered C-200
   legs** get book-state fill verdicts (extends `scripts/c200-printthrough.py` to Parquet).
   *Rule:* if ≥25 % of the gap-window legs flip to no-fill at intent−0.02, or implied fill rate moves
   >10 pp vs the 08-31→now recorder baseline, adopt as the `phase-d2-fill-model` input; else keep as a
   one-off calibration and drop the vendor.
   *Effort:* 1.5 dev-days + 205 GB + **you must create the free vendor key**.
3. **`mnemox-ai/tradememory-protocol`** [watch] · audited 2026-10-15 20:26 CDT ·
   [report](http://localhost:3013/drafts/asset-audit-tradememory-protocol-20261015)
   → reimplement the **deflated-Sharpe** multiple-testing correction in TS for the rule-selection/ML stats
   (rule-tuner/review read path; no card owns multiple-testing correction).
   *Rule:* read-only — derive n_trials per axis from `RuleChange` rows (v40–v62), compute DSR on the C-200
   daily net PnL, live regime 2026-09-04+; if p≥0.05 or INSUFFICIENT_DATA the ladder/rule claims carry an
   explicit "not distinguishable from selection" caveat, else record the p. **No threshold moves either way.**
   *Effort:* ~2 h, read-only. Lowest ceiling, lowest cost.

Answer with `approve <owner/repo>` or `decline <owner/repo>`. Nothing is deferred silently: these are all
three of the pending items in `data/research-asset-queue.json`.

**Completed since last week (no action needed):** `parkyucheol-del/alphapipeline` — audited 2026-10-19,
verdict **drop** ([report](http://localhost:3013/drafts/asset-audit-alphapipeline-20261019)).

### Decisions log (since the last weekly)

- **2026-10-15 — `mbordash/DRADIS` approved** (read-only horizon-scaled margin replay) → **ran the same
  day, rule did not fire, measured-dropped**: flip set n=62 across 23 wallets, mean **−$0.3307/leg**,
  wallet-clustered CI **[−5.5543, +3.7130]** includes 0 (rule required CI excluding 0 at n≥30), and the
  flip-mean sign moved with the anchor across the sensitivity grid. Nothing written to the shadow spec.
  ([report](http://localhost:3013/drafts/horizon-margin-replay-20261015))
- No other approve/decline recorded since 2026-10-15.
- Queue health: **12 items — 11 `audited`, 1 `pending`** (`crowdintel-xyz/polymarket-agent-kit`, enqueued
  today for the audit worker, §2.1), **0 stuck in `auditing`** (`asset-queue.py status`, 2026-10-19).

---

## 6. Retro — every recommendation of the previous four weeks

The research agent's first run was 2026-10-15, so the window it can report on is five briefs (10-15 → 10-19).
Briefs are recoverable from the session store (`~/.hermes/state.db`, `messages` by session title
`copybot-research-daily`), which is how this retro was built — that is now written into the skill so next
week does not have to rediscover it.

| Date | Recommendation | Status | The number that decided it |
|---|---|---|---|
| 10-15 | Pre-register the radar's yield so the 2026-10-29 card gate is answered by a script | **ADOPTED** (`scripts/radar-yield.py`, `data/radar-yield.jsonl`) | 12.88 usable slots/run vs **0.18 new leads/run** over 17 runs; verdict withheld until n=12 (now 8/12) |
| 10-15 | DRADIS horizon-scaled admission margin (via audit) | **REFUTED → dropped** | flip set n=62, mean −$0.3307/leg, CI [−5.55, +3.71] straddles 0 |
| 10-16 | v1→v2 Data API parity probe, then flag-gated cutover (deadline then 10-20) | **PENDING, behind** | probe ran 10-17 with values identical on 5/5 rows; **0 code moved**, real deadline 10-24, 5 days out |
| 10-17 | Sub-$0.05 C-200 entry floor, pre-registered, gate 2026-10-24 | **PENDING** (`c200-entry-floor-005-prereg`) | read #1: <0.05 ROI **−55.2 %** at **n=31** vs the n≥60 the rule requires; gate (b) passes on both bases → non-discriminating |
| 10-18 / 10-19 | No new recommendation (10-18 corrected its own row count: 206 rows @7.35 ¢, not "404 @3.6 ¢") | — | — |

Two notes on this retro:

- **The 10-17 floor read is on course for a forced NULL.** It needs 29 more settled sub-$0.05 legs in the
  thinnest band in a week, and the band is de-starved by v62 (0 legs in 0.40–0.60, and <0.20 flow is
  clamp-bound). If 10-24 arrives at n<60 the honest outcome is **INSUFFICIENT**, not "drop the hypothesis" —
  the card should record that distinction when it closes.
- **The 10-16 item is the only one where being late is expensive**, and it is the one still unstarted.

---

## 7. Cards added today

- **`fact-sheet-collector-truth`** (Scheduled, effort ~30 min) — the three fact-sheet defects above, with
  the verification as its gate. Home for REC 1.
- **`c200-exclusive-pair-hull-check`** (Backlog, effort ~2–3 h) — the convex-hull gap replay over held
  events. Home for REC 2; consumer is `phase-c`, which stays parked.
- REC 3 needs **no new card**: `ml-u2b-selector-search` is its home and its bar is already pre-registered.
  It is listed there as an added candidate (`ev_ci_low`), not as a new card.

---

## Sources (all read 2026-10-19 unless stated)

- Polymarket migration guide — "Data API v1 is retired on October 24, 2026": https://docs.polymarket.com/migrate/data-api-v1-to-v2
- Polymarket changelog (newest entry Oct 7, 2026; crypto taker delay 150 ms set Sep 4): https://docs.polymarket.com/changelog
- Kalshi API changelog (Oct 15, 2026 balance bucket; three entries labelled Oct 22, 2026): https://docs.kalshi.com/changelog
- Kalshi markets API, probed live: `https://api.elections.kalshi.com/trade-api/v2/markets?limit=200&status=open` → 200/200 `volume_24h_fp = "0.00"`; with `max_close_ts` → Σ 39,112, max 10,054
- arXiv 2610.23517v1, *Combinatorial Arbitrage in Prediction Markets* (2026-10-19): https://arxiv.org/abs/2610.23517
- r/predictionmarkets 2026-10-17 thread (signal detection only, `unverified`): https://www.reddit.com/r/PredictionMarkets/comments/1x7x5i0/my_paper_bot_wins_92_of_its_trades_a
- Repos: https://github.com/crowdintel-xyz/polymarket-agent-kit · https://github.com/darup67/market-lab
- Internal: `logs/cron/tuning-review.md` (cycle #60, 2026-10-19) · `data/roadmap.json` · `drafts/data-api-v2-migration-20261017.md` · `data/research-asset-queue.json` · `scripts/research-collect.py:199`

**Nothing was applied, changed, or written to the live lane. No rule, size, threshold, config or lane was
touched. Recommendations only.**
