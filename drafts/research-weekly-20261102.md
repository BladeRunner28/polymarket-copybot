# Weekly research deep-dive — 2026-11-02

Fact sheet: `scripts/research-collect.py`, generated **2026-11-02T14:30:38Z (09:30 CDT)** — fresh, **no `SOURCE FAILED` line**.
Book numbers below come from that sheet, from `logs/cron/tuning-review.md` (cycle #74, 2026-11-02), or from read-only SQL against `prisma/dev.db` (`immutable=1`) taken 08:40–09:10 CDT this run — each labelled. Nothing was written in the repo except this file and the two cards named in §7. No rule, size, threshold, config or lane was touched.

**One correction up front, against yesterday's brief.** The 2026-11-02 daily brief claimed "the r/algotrading block has vanished from the fact sheet entirely … a void block passing as a quiet day is exactly the case `reach-mcp` exists to catch." That is **wrong**, and I am retracting it here. `scripts/research-collect.py` ships two fixed Reddit feeds plus **one rotating feed chosen by weekday** (`REDDIT_ROTATION[weekday % 4]`, `research-collect.py:594`); Monday is `r/Kalshi top/week`. The block was never due today, and today's sheet carries exactly the three feeds the code asks for. The genuine input-health fact this week is narrower and it is **labelled**: `search: kalshi bot` was served from a **333.8 h-old cache** on 10-29 and `r/algotrading` from **168.9 h** on 11-01 — both printed their own staleness, so `reach-mcp`'s decision rule ("a block was gated_off or void-with-rows while the same run's fact sheet carried no line about it") has, on its own terms, **not fired**. That changes how the pending ask should be read (§5.1).

---

## 1. Landscape — what changed this week

**Venues: quiet, and now measurably so for twelve days.**

- **Polymarket changelog** ([docs.polymarket.com/changelog.md](https://docs.polymarket.com/changelog.md), read 2026-11-02): newest entry is still **2026-10-21** (PolyBolt forex symbols + the additive `market_status` field — a live-data surface we do not subscribe to). **Twelve days with no entry.** No fee, rate-limit, resolution or market-type change.
- **Kalshi changelog** ([docs.kalshi.com/changelog.md](https://docs.kalshi.com/changelog.md), read 2026-11-02): the **Oct 29** batch reported last week as future-dated is now live and readable — `GET /portfolio/credit_history`, Margin `market_lifecycle_v2`, subaccount-restricted keys on `intra_exchange_instance_transfer` and `get-all-subaccount-balances`, `halt_sources` on margin responses, `orderbook_delta` **`clock`** (stable across connections, unlike `seq`), FIX `NoMDEntryTypes`/`MDEntryType`, and `GET /portfolio/orders` accepting 100 tickers. **Every one is authenticated, Margin or FIX; none touches a keyless read.** The **Nov 5** entries stay dated *ahead* of today → `unverified`. **Nothing dated 2026-10-30 → 2026-11-02 on either venue.** The only item with any adjacent relevance is `clock` on `orderbook_delta`: a cross-connection-stable update counter is exactly what a book recorder needs to de-duplicate redundant feeds — we hold no Kalshi book and will not build one this phase.
- **Polymarket's 10-29 halt** was reported in the 10-30 brief (Reuters, [10-29](https://www.reuters.com/business/polymarket-reports-major-outage-suspends-trading-actions-2026-10-29/)) and is not re-litigated here.

**Literature — two items, one of them actually useful.**

- **arXiv:2610.41689 — *QBX: A Compiler for Well-Formed, Auditable Alpha Programs*** (cross-listed q-fin.CP, announced **2026-11-02**, https://arxiv.org/abs/2610.41689). A typed block-registry IR for formulaic alphas whose **availability-effect system rejects contract-visible look-ahead at compile time**, with Merkle-style node identities for trial provenance. On Chinese A-share panels, evaluation-valid proposals rise 36.4 % → 97.7 % going from grammar-only to typed programs, and the availability checker admits **zero** registered-contract violations across 23,342 candidates. The authors are careful that this is validity/reuse, not extra information.
  **Transfer, checked rather than assumed:** I read our own feature path before citing it. `scripts/ml_features.py:18` already carries an explicit `LEAK_COLS` guard (`payout`, `cost_ps`, `roi_net`, `roi_mid`, `y_yes`, `label_status`, `resolved_at`) and `NUM_FEATURES` is market-only (`yesPrice`, `ask`, `mid`, `spread`, `premium`, `fee_ps`, `liquidity`, `volume`, time-to-resolution, question geometry). **So the gap QBX would close on our side is already closed for the market model** — no rec, no card. Worth stating because it is the first time I have checked it, and it means ML-1's frozen holdout is not exposed to this class.
- **arXiv:2610.33400v2 — *Tracking High-Frequency Trading Activity in China*** (q-fin.TR, replace, announced **2026-11-02**, https://arxiv.org/abs/2610.33400). Order-level HFT proxy = the share of **active exact-match orders** (limits priced exactly at the best opposite quote), validated on Shenzhen data; latency-induced HFT raises short-horizon price variation, spread incidence and adverse selection while realised spreads fall. **Not transferable at our data depth**: the proxy needs order-level submissions, and `data/l2` is books-only by design (`record-l2.ts` receives no trade stream). Recorded, not actionable.

**Practitioner signal (Reddit — detection only, `unverified` as claims).** r/predictionmarkets **2026-10-30**, *The Math Behind Kalshi Taker Fees: Why Most "1.5¢ Mispricings" Are Actually Negative Expectancy*. Independent arrival at the number our own replay measured this week (§3 fact 4): the taker fee, not the spread, eats the tolerance. Corroboration, not evidence — the primary source is Kalshi's published schedule and our own L2 walk. Also 10-29, *There is no such thing as a profitable trader bot* — sentiment, no data, no action.

**One venue-mechanics probe I ran myself, because a candidate repo asserted the opposite.** `darup67/market-lab`'s README claims "Kalshi serves roughly the last **two days** of settled markets, and trades vanish with them … nothing here can be backfilled." Probed keyless today: `GET /trade-api/v2/markets?status=settled&min_close_ts=…&max_close_ts=…` returns **200 rows closing 2026-09-16**, **200 closing 2026-10-16**, and a row for **2026-08-01** — i.e. three months back on the same endpoint the repo says serves two days. **The premise is false for markets.** It is *not* refuted for fills: `GET /historical/trades` returned an empty set on my window and `GET /markets/{ticker}/trades` 404s, so trade history is `unverified`, not available. Split finding, stated that way, and carded (§7).

---

## 2. Reusable assets — the deep version

**Radar yield** (`python3 scripts/radar-yield.py`, 2026-11-02): **34 runs**, **313 usable slots = 9.21/run**, and **6 added over 73 runs = 0.08 new leads/run** (skips: no-licence 1,007, already-in-drafts 465, ★0-only 318, already-in-queue 277, ★1-only 143, ★2-only 65). The pre-registered amendment reads **RULE DOES NOT FIRE** (`updated`-sorted blocks 7 usable vs 306 for the stars blocks) → `GH_QUERIES` untouched. Read honestly: **this week produced no new lead.** The newest-updated blocks are ★0/no-licence paper-trading-dashboard clones (`user-kv/polymarket-desk`, `agustinooo/polymarket-desk`, `agustinooo/kalshi-desk`, `barsinai/polymarket-lab`, `mezianialaee-star/polymarket-arb-scanner`) — the same shape four times, none with a licence, none with code worth reading. Not listed as candidates.

| # | Asset | Licence / push | What it is, against what we run | Verdict |
|---|---|---|---|---|
| 1 | `bennyjo/phil` | Apache-2.0 · ★244 · created 2026-07-30 · pushed **2026-11-02** · 399 MB · 3 open issues | **Recurring (`watch` since 2026-10-20) and showing real progress**, which is the test for re-listing: 8 commits on 2026-11-02 alone — `operator: real-money Polymarket V2: bet, sweep, and claim binary V2 markets`, `read-only Polymarket V2: list, tag, forecast`, `cycle: 20261102-1221 placed 1 settled 0`, on an hourly lease/cadence cycle. It is a self-improving agent that rewrites its own strategy after every settled bet, now with a custody-path execution layer via Pearl Connect. **Against our stack:** we already have the loop it is famous for (score → book → review → tune); what it has that we do not is a *per-bet strategy rewrite*, which is exactly the thing our own reviews keep declining to do (two consecutive `No rule changes warranted`). Nothing adoptable — real-money custody, no key path for us, and its "cycle" cadence is hourly on one book. | **watch** (progress confirmed; no adoption path) |
| 2 | `darup67/market-lab` | **NOASSERTION** · ★1 · created 2026-09-07 · pushed **2026-11-02** · 390 MB | Two node recorders: Kalshi 15-minute crypto contracts (`record.js`, 10-min cadence) and CME futures bars via Yahoo (`record-futures.js`), with `data/*.jsonl` committed. **Read for its premise, not its code.** The premise ("nothing can be backfilled") is **half false**: settled *market records* reach back months (§1 probe). Its futures half is honest about being 10-minute-delayed research data, not a signal. `NOASSERTION` = unusable as a dependency regardless. | **drop** (licence; premise half-false; 1 star, no tests) |
| 3 | `inputoutput9/prediction-market-agent-atlas` | MIT · ★1 · weekly CI rescan · as-of 2026-11-02 | Re-listed only for its **decay rule**, already carded (`asset-queue-decay-and-atlas-diff`, Backlog): 44 curated entries with dated evidence strings and a computed maintenance axis that *auto-decays* stale repos. Our queue has 17 items and **none expires** — that is still the gap, and it is still not being worked. No new verdict. | **watch** (unchanged, already carded) |
| 4 | `xyonium/reach-mcp` | MIT · audited **2026-10-23** | Cited by audit outcome, not re-judged: **watch**, typed per-block input-health classifier. Pending your call (§5.1) — with the evidence corrected above. | **audit outcome: watch** |
| 5 | `lein3000zzz/polythought-go` | MIT · audited **2026-10-29** | Cited by audit outcome: **watch**, ~55-line book-walk taker fill. **Its read-only replay has already been run and passed** — see §5.2, it is the week's most consequential artifact and it arrived without a recorded decision. | **audit outcome: watch (executed)** |

Recurring `watch` items not re-listed: `mileswangs/pm-hftbacktest` (10-24, untouched since — **17 days**, inside the three-week drop window, but next week it is dropped or it moves), `arnaudknobloch/awesome-polymarket` (**drop**, 10-24), `crowdintel-xyz/polymarket-agent-kit` (**audit**, approved 10-21, execution pending), `vike-io/vike-data-cli` (approved 10-21, **blocked on you** — the 37-day / 205 GB pre-recorder parcel; no key is held here).

---

## 3. Our book against it

**Fact 1 — the lane's edge is ten legs deep, and the capacity maths follow from that.** Read-only SQL, settled `PaperTrade`, `isDemo=0`, `COALESCE(closedAt,resolvedAt)`:

- **C-200: 2,574 legs / $22,028.72 staked / +$6,356.47 = +28.9 %.** Remove its ten largest legs (0.39 % of legs, +$6,914.03 between them): **−$557.56 = −2.5 %.** Ex-top-5 +$1,863.77 (8.5 %); ex-top-20 −$2,809.54.
- **STANDARD, same query: 9,855 legs / $113,438.18 / +$8,881.13 = +7.8 %; ex-top-10 +$7,041.33 = +6.2 %.**

The contrast is the point: the instrument *can* tell a broad book from a concentrated one, so this is not an artefact of removing tails. **Implication:** the C-200 lane's positive record is a longshot-payoff record — 10 resolutions carry it — not a flow record. **Capacity:** $22,028.72 over 89 days = **$247.51/day staked**, realising **$71.42/day**. The **$250/day rung therefore needs 3.5× today's staked flow at the lifetime ROI — or 6.4× at the fill-aware ROI (+15.8 %, §3 fact 4)** — and the lane is **not capital-bound** (open book $81.95 = 2.0 % of a $4,178.23 ceiling), so that multiple has to come from admissions, not size.
**Does NOT imply** the Kelly regime, the band policy or the sizing ladder is wrong. A convex book is *supposed* to look like this; what it forbids is quoting "+28.9 %" as if it were an earned rate, and assuming the next 3.5× of flow arrives at the same payoff shape.

**Fact 2 — the ladder's own advance test has never been met by flow.** Read-only, same population, day-bucketed on local CST, trailing 7-day windows over the lane's 89-day life: **83 windows; the ≥ $1,750 advance test (rung × 7) fires in 8 — all of them between 2026-09-21 and 2026-10-04 — and in every one of the 8 the SUM-minus-top-3 is below the bar (max $342.04 = 19.5 % of it).** No non-firing window gains by removing legs. Recent windows: 10-30 **$466.39** (which reproduces `query_bankroll.js`'s printed `$466.39` for 10-24…10-30 **exactly**, so the instrument is calibrated against the live one), 10-31 $607.43, 11-01 **$551.63** — ex-top-3 every one of them negative (−$491, −$431, −$288).
**Implication:** the ladder advances when a handful of longshot legs resolve, and the printed SUM alone cannot distinguish that from flow progress. **This is not a new discovery — the card that applied the gate already recorded it** (`c200-goal-policy-v2-rolling7d-gate`, 2026-10-12: "top 3 days = $3,513.44 = 60 % of the $5,826.06 book"; "rolling 7d windows clearing $1,750 = 8 of 61"). What today's read adds is that **the same 8 windows are the only ones that ever cleared, and none of them clears without its 3 largest legs** — i.e. the property is in the *window* the gate reads, not only in the day distribution. The gate was chosen because the old basis was structurally unsatisfiable; this says the new basis is satisfiable only by the tail. **Does NOT imply** the v2 rolling-7d gate should change: the gate is the user's settled policy and this reads its *tail-sensitivity*, not its validity. The honest consequence is a display one (§4 REC 2).

**Fact 3 — the book is tiny on the lane that matters, and the funnel has a 100× surplus.** Fact sheet: **C-200 open 5 legs / $81.95 = 2.0 %** of the $4,178.23 cap; **STANDARD 444 / $4,873.40 = 34.2 %** of 1,300 legs; 24 h **11 `paper_copy` vs 1,136 skips across 112 distinct skipped markets**. **Implication:** the programme's constraint is admission into the sized band, not capital — consistent with Fact 1's 3.5–6.4× requirement. **Does NOT imply** relaxing a gate: the largest skip classes are drift-at-re-offer (165), confidence < 0.7 (138), and the static v45 `sea` blacklist (85), and the first of those is a threshold settled by the 2026-10-10 option-A decision.

**Fact 4 — the two entry conventions are now both measured, and nobody has compared them on one population.** Three shipped instruments, one population of C-200 dispatches:

- **Maker, parked at `intent − credit`:** reachable on **130/373 = 34.9 %** of legs at the live credit (`c200-fill-aware-pnl.ts`, 2026-10-26 snapshot; 17.1 % at the flat 2¢). Print-through at `intent − $0.02` is worse: **6 %** on the 5-minute tape, **17 %** on the 1-hour tape, 90/529 on our own book (`drafts/c200-printthrough-20261030.md`), against the archive prior of 74.3 %/81.1 %.
- **Taker, FAK at decision + 2¢** (`drafts/fak-marketable-entry-replay-20261029.md`, 381 joined legs of 390): **full fill 341/381 = 89.5 %**, full fill *and* ≤ 2¢ on **268/381 = 70 %**, median effective entry **+1.69¢** including fee, p90 +2.59¢.
- **Cost decomposition:** on the 250 legs whose book had not drifted, median half-spread **+0.50¢** + median taker fee **+1.17¢ = +1.69¢** — **the fee alone is 58 % of the 2¢ tolerance**, which is precisely the mechanism the 10-30 Reddit thread argues and our own walk confirms.
- **What this does to the headline:** booked +$1,313.66 (+40.6 %) → fill-aware +$510.93 (**+15.8 %** per intended copy) — the maker booking overstates C-200 PnL by **61 %**, the single largest distortion of the number the ladder is judged on.

**Implication:** the entry convention is a *fill-probability* trade (≈35 % at a parked maker level vs ≈90 % crossing) priced at ≈3.7¢ of entry on a book whose median clip is $2.48 — i.e. the choice is decidable from data we already hold, and it has not been decided. **Does NOT imply** the sidecar's maker convention is wrong (that question is closed and is not re-opened here); it implies the *booking* is a policy input that has been left at p(fill)=1.

**Fact 5 — the one prereg the sheet still reads every day cannot resolve.** `data/entry-floor-read.jsonl` (read 0.1 d ago): **INSUFFICIENT_N, gate A n=31/60, ROI −55.18 %**; gate B $40,084.61 across 45 resolved. Gate A is frozen by construction — v67 (2026-10-24) set `c200LongshotBandFloor=0.05`, so no sub-5¢ C-200 leg can be booked again, and all 31 predate the floor. **Implication:** a daily read that cannot move is a dead instrument occupying the sheet's scarcest slot. **Does NOT imply** the floor is wrong — it implies the gate needs a reachable population (already asked, §6).

---

## 4. Recommendations (2, ranked by expected value per engineering hour)

Both are read-only. I am proposing **two**, not four: this week's honest output is one measurement that settles a live choice and one display line that stops a metric being misread. Nothing on Kalshi routing (retired), nothing on the Kelly regime / band policy / ladder thresholds (settled), no size, threshold or lane change.

```
REC 1 — Maker vs taker on ONE population: price the entry convention the lane actually pays
  Hypothesis:   at equal intended copy the taker convention earns more per intended copy than the
                maker convention at the live credit — because the parked level reaches only 34.9% of
                legs while a decision+2c FAK fills 89.5% of them, and the extra cost (+1.69c median,
                of which 1.17c is fee) is cheaper than losing 55% of the legs.
  Measurement:  read-only join of the two shipped instruments on the SAME legs: the 507 dispatched
                C-200 intents already resolved by `scripts/c200-fill-aware-pnl.ts` (373 verdicts) and
                the per-leg capped effective entry from `scripts/fak-marketable-replay.py` over
                `data/l2`. Compute PnL per intended copy under three conventions — (a) booked maker
                (intent - credit, p=1), (b) fill-aware maker (p = reach at live credit), (c) taker FAK
                (p = 89.5% full fill, entry = decision + measured delta) — each with ex-top-10 and by
                band. Expected n = 373 resolved legs, ~370 joined to a book; refuse the read below 300
                joined.
  Decision rule: if (c) beats (b) by >= 5pp of ROI per intended copy at n >= 300 AND the sign holds
                ex-top-10, card a SHADOW taker lane (book C-200 at the taker convention in shadow only,
                no live booking) by 2026-12-14; if (c) does not beat (b) by 5pp, close the taker arm
                permanently and record the maker convention as defended on total fill-value — not on
                cost — so it is not re-opened on the fee argument alone.
  Cost:         ~2h read-only. Both instruments already shipped; no new data, no live path.
  Reversibility: one artifact (`drafts/c200-maker-vs-taker-<date>.md`); delete it and nothing changes.
```
Touches: `drafts/c200-maker-vs-taker-2026110X.md` (new), read-only against cards `c200-maker-fill-assumption` and `c200-intent-printthrough-check`.

```
REC 2 — Print the ladder's SUM with its tail removed, beside the lane ROI with its tail removed
  Hypothesis:   the v2 rolling-7d SUM cannot distinguish flow progress from a longshot tail — all 8
                advance-eligible windows in the lane's history fall below the $1,750 bar once their 3
                largest legs are dropped (max $342.04), and the printed value is what the phase gate
                and the daily report both quote as "progress".
  Measurement:  already run read-only today (83 trailing-7d windows, 2,574 settled C-200 legs,
                local-CST day buckets; instrument reproduces query_bankroll.js's $466.39 for
                10-24..10-30 exactly). Extend it: print `ex-top-3 SUM` beside the 7d SUM and
                `ex-top-10 lifetime` beside the lane ROI, in query_bankroll.js and the EOD block; keep
                a 30-day series in the existing phase-streak log.
  Decision rule: if by 2026-12-02 no window has cleared $1,750 ex-top-3 (today: 0 of 83, max $342.04)
                then the two companions become permanent on every ladder headline and "progress" may
                only be quoted as the ex-top-3 figure; if any window clears $1,750 ex-top-3 first,
                record the concern as REFUTED and drop the line. Thresholds and gate logic never
                change — this is a print.
  Cost:         ~45 min (two print statements + one series line), read-only, zero live-lane risk.
  Reversibility: delete the two printed lines; the series file is append-only and harmless.
```
Touches: `query_bankroll.js`, `scripts/phase-streak-log` writer, card `c200-goal-policy-v2-rolling7d-gate` (In Progress), and the EOD headline block. **Not** the rung thresholds.

**Deliberately not proposed:** (i) the `c200-maker-fill-assumption` booking change — **you approved it on 2026-10-27** ("I approve your recommendations", floor waived) and it is still unimplemented six days later; it needs a Prisma migration (`PaperTrade.fillResolved`) + the ~60-min resolver + `FILL_AWARE_BOOKING=0`, and re-proposing an approved change as a "recommendation" would be laundering an owed item into a decision (§6). (ii) nothing on drift thresholds (option-A settled, per-signal cohort 0/7). (iii) nothing on `sea`/`cs2` (static v45 constants, no lever exists).

---

## 5. Asset audits — awaiting your approval

### 5.1 Pending (2 items; nothing adopted by approving — each buys a read)

- **`xyonium/reach-mcp`** · verdict **watch** · audited 2026-10-23 · report `drafts/asset-audit-reach-mcp-20261023.md` · **pending 10 days**
  - **Recommendation:** a typed per-block input-health classifier (`ok | no_results | rate_limited | gated_off | void`) with a JSONL sidecar on `scripts/research-collect.py`, extending card `fact-sheet-collector-truth`; fact-sheet text unchanged in stage 0.
  - **Decision rule (verbatim):** read-only; after **14 daily runs (by 2026-11-06)** read `data/cache/research-recon/factsheet-status.jsonl`; if **≥ 1 block was `gated_off` or `void`-with-rows** in those runs while the same run's fact sheet carried no line about it, promote the typed states into the fact-sheet header; else drop.
  - **Effort** ~2 h · **reversibility:** delete the sidecar write and the JSONL · no dependency, no code adopted from the repo.
  - **Honest state of the evidence:** the three briefs that sold this as "the failure mode is live this week" were **over-reading** — Monday's missing block is the weekday rotation, and the two genuinely stale feeds (333.8 h and 168.9 h) each printed their own label. On its written rule the predicate has **not** fired. The ask still stands on design merit (a missing *line* is still distinguishable from a missing *block* only by a human reading the rotation table, which is exactly what failed me yesterday), but it is a 2 h instrumentation buy, not an emergency.
  - **Answer:** **`approve xyonium/reach-mcp`** / **`decline xyonium/reach-mcp`**

- **`lein3000zzz/polythought-go`** · verdict **watch** · audited 2026-10-29 · report `drafts/asset-audit-polythought-go-20261029.md` · **pending 4 days — and already executed**
  - **Recommendation:** reimplement the donor's ~55-line book-walk taker fill as a read-only replay over `data/l2/` to price a marketable FAK entry at dispatch on booked C-200 legs; touches no live lane.
  - **Decision rule (verbatim):** if VWAP premium over `intentPrice` is ≤ 2¢ on ≥ 50 % of joined C-200 BUY legs with an L2 snapshot < 60 s after dispatch (**n ≥ 150**), open a maker-vs-taker entry before/after comparison as a v-next lane-A proposal; else close the taker arm permanently and record the maker convention as defended on cost.
  - **Effort** ~2 h read-only · **reversibility:** delete the artifact and the proposed card.
  - **It has been run.** `drafts/fak-marketable-entry-replay-20261029.md`, generated **2026-10-29 12:09 CDT** from `.worktrees/t_29cb928b/`, **n = 381 joined legs, PASS: 268/381 = 70 % land ≤ 2¢ with a full fill** against a 50 % bar (81 % on the 250 undrifted legs). So the audit's rule has fired and the queue item is stale as written: approving it now buys nothing, because the measurement exists. **What is actually yours to decide is the rule's consequence**, and it overlaps REC 1 above — REC 1 is the same comparison done on the fill-aware population with actual PnL instead of a cost bar. My reading: **let REC 1 be the decision** and close this queue item as executed.
  - **Answer:** **`approve lein3000zzz/polythought-go`** (accept the artifact, let REC 1 carry the comparison) / **`decline lein3000zzz/polythought-go`** (reject the replay as non-evidence — it is a book-walk, not an observed fill) — either way the queue entry can then be closed; I have not recorded a decision I did not receive.

- **Not a queue item, still on you:** `vike-l2-prerecorder-window` — approved 2026-10-21, **blocked** on the 37-day / 205 GB pre-recorder L2 parcel you pull by hand. Nothing downstream of it can run, and it is the input that would turn the maker p(fill) from a 34.9 % book-walk into an observed fill rate.

### 5.2 Decisions log — what was decided since the last weekly, and what followed

| Repo / item | Call | When | What followed |
|---|---|---|---|
| *(nothing)* | — | 2026-10-26 → 11-02 | **No decision was recorded this week.** `asset-queue.py status`: 17 audited, 2 awaiting approval, 0 stuck in `auditing`. |
| `crowdintel-xyz/polymarket-agent-kit` [audit] | approved (recorded 10-26 from cards) | 10-21 | Card `crowdintel-wallet-fdr-audit` — **still not executed**, 12 days. |
| `mnemox-ai/tradememory-protocol` [watch] | approved (recorded 10-26 from cards) | 10-21 | Card `tradememory-deflated-sharpe` — **still not executed**, 12 days. |
| `vike-io/vike-data-cli` [watch] | approved, **blocked on you** | 10-21 | The 205 GB parcel; no key held here. |
| `mbordash/DRADIS` | approved → **refuted** | 10-15 | Horizon-margin replay n=62, −$0.33/leg, CI straddles 0 — dropped with the null recorded. |

**Two ledger defects named, not fixed by me:**
1. **`polythought-go` was executed while its ask was pending** (audit 08:24 → replay 12:09, same day, no `decide` ever recorded). A queue item whose work already exists cannot be honestly re-asked as "shall I measure this"; hence §5.1's reframing. The queue needs a state for *executed-unapproved*, or this repeats.
2. **Three approved items (`crowdintel`, `tradememory`, `vike`) have sat unexecuted for 12 days.** They are approved, so they are not a decision for you — they are owed work. Named here because the weekly is where owed work is visible.

---

## 6. Retro — the last four weeks, each with the number that decided it

| Recommendation | Status | The number |
|---|---|---|
| **10-26 REC 1** — locate the <0.20 flow loss gate by gate (read due 11-09) | **PENDING, NEVER STARTED** | No `drafts/c200-band-flow-20261026.md`, no SQL artifact. **7 days to its own read date**, and Fact 1 above now says this is the *capacity* question (3.5–6.4× flow needed, admission-bound). This is the week's clearest defect. |
| **10-26 REC 2** — prereg registry + grader (measure to 11-25) | **PENDING, NOT STARTED** | No `scripts/prereg-grade.py`, no `data/prereg-registry.jsonl`. Meanwhile the entry-floor gate has been read daily for 9 days on a population that cannot move (§3 fact 5) — the exact failure the registry was for. |
| **10-26 REC 3** — depth functional form from 2610.31903 (n ≥ 100 gate, 11-30) | **PENDING, NOT STARTED** | No artifact. n-gate unchanged; `data/l2` now **21 GB / 45,618 token files**, so the population exists. |
| **10-27 REC 1** — burst× band with wallet-clustered CIs (decision 11-03) | **PENDING — decision date is TOMORROW** | No artifact found. If 11-03 passes with no read this joins the unstarted list. |
| **10-28 REC 1** — write the entry-floor NULL instead of reading it daily (decision 11-04) | **SUPERSEDED, and doubled** | Two open recs now sit on the same object (10-28's drop-the-read, 11-01's retire-gate-A on 11-08). That is my own duplication; the 11-01 version governs, the 10-28 one should be closed when it is read. |
| **10-29 REC 1** — publish the settled window ex-stock-clear | **ADOPTED (shipped 10-30)** | Live in today's sheet: `last 7d EX-STOCK-CLEAR n=149 $787.23, $5.28/leg` beside the blended figure, and 30d **$1.55 blended vs $3.58 ex-bulk** — a 2.3× difference in the number a human reads. Its 14-run verify (sign disagreement) has produced 0 in-run disagreements so far because 10-24 has rolled out of both windows. |
| **10-30 / 10-31 REC 1** — concentration line beside every settled window | **ADOPTED 11-01 (commit `4cf86c9`)** | Live and it is doing work: today **7d net +$787.23 with ex-top-3 −$373.97 — sign DISAGREES** (1 of 14), 30d agrees (+$2,789.51 vs +$585.58), 1d agrees. |
| **11-01 REC 1** — entry-floor gate A is structurally unfalsifiable; retire it at the 11-08 read | **PENDING** | No read yet; gate A still **n=31/60** and 0 sub-5¢ openings since 2026-10-09. |
| **11-02 REC 1** — the drift fix's verify clause cannot fire inside its window; re-spec to n ≥ 40 by 11-16 | **ISSUED TODAY, UNACTIONED** | No read yet. |
| **10-22 REC 1 — the v65 paired read (2SE ≤ $10, n ≥ 70)** | **PENDING WITH NO INSTRUMENT — third week named** | Still nothing: no card, no script, no reader, window open to **2026-11-15** (13 days). This is the rec closest to having vanished, so it is carded this week (§7) rather than named again. |
| **10-19 weekly** — hull-gap replay; U2b `ev_ci_low` | **PENDING on cards** | `c200-exclusive-pair-hull-check`, `ml-u2b-selector-search` — both Backlog, neither run. No number. |
| **Audits, four weeks** | — | DRADIS **refuted** (n=62, −$0.33/leg); phil **watch** (progress); pm-hftbacktest **watch**; awesome-polymarket **drop**; alphapipeline **drop** (paid x402 API); **polythought-go executed-unapproved** (PASS, 268/381); reach-mcp **pending 10 days**. |

**The pattern, stated plainly:** in the last four weeks I have shipped two collector prints that now do real work, and I have **five measurements with decision rules and dates that have never been started** (10-26 REC 1–3, 10-27 REC 1, 10-22 REC 1). Their decision dates are 11-03, 11-09, 11-15, 11-25 and 11-30. The registry in 10-26 REC 2 was proposed precisely to stop this, and it is itself one of the five.

---

## 7. Cards

- **New — `kalshi-settled-history-surface`** (Backlog, ~30 min read-only, gate: Phase C kickoff): records today's verified probe — `GET /trade-api/v2/markets?status=settled&min_close_ts&max_close_ts` returns settled market records **three months back** keyless (200 rows closing 2026-09-16 and 2026-10-16; a row for 2026-08-01), while **trade history is `unverified`** (`/historical/trades` empty on my window, `/markets/{ticker}/trades` 404). Retires the "Kalshi serves two days, nothing can be backfilled" premise **for markets only**, which is the premise `market-lab` is built on. Checked against 261 cards before adding: no duplicate.
- **New — `v65-paired-read-instrument`** (Backlog, ~1 h, gate: **2026-11-15**, the window's own close): the three-week-named rec gets an instrument instead of a paragraph — a reader over `PaperTrade` + `DecisionJournal` for the v65 paired population (2SE ≤ $10, n ≥ 70), so the window can be read before it closes rather than after. No duplicate.
- **No new card for REC 1 or REC 2** — each is a live proposal with its own decision rule; carding a recommendation while it awaits your call is how recs get double-counted (same rule as 10-26).
- Cards touched by this report's facts, not by me: `c200-maker-fill-assumption` (approved 10-27, unimplemented — the 61 % distortion), `c200-goal-policy-v2-rolling7d-gate` (REC 2's print), `fact-sheet-collector-truth` (part (c) still open — the exposure line now prints 449 / $4,955.35 for `isDemo=0` only, so the DEMO half landed; the **lane** split on that line is still missing), `asset-queue-decay-and-atlas-diff` (untouched, 7 days).

---

*Nothing applied. No rule, size, threshold, config or lane was touched. The only writes this run: this draft and the two roadmap cards named above. Read-only probes live in `~/.hermes/cache/scratch/` (`win_weekly1102.py`, `win_conc1102.py`).*
