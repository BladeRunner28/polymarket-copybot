# Weekly research deep-dive — 2026-11-16

Fact sheet: `scripts/research-collect.py`, generated **2026-11-16T14:30:46Z (09:30 CDT)** — fresh, **18/18 blocks ok, no `SOURCE FAILED` line**. Book numbers below come from that sheet or from repo files I opened this run (`logs/cron/tuning-review.md` cycle #87, `drafts/lip-ledger-20261109.md`, `data/lip-ledger.json`, `data/prereg-registry.jsonl`), each labelled. Nothing was written except this file and one roadmap card (§7). No rule, size, threshold, config or lane was touched.

**Two things up front, because they set the tone of this week.**
1. **Last week's weekly does not exist.** The 2026-11-09 08:30 run died on `HTTP 402: Insufficient Balance` (the provider outage that killed 25 Hermes jobs on 11-08/11-09; the five copybot jobs are LLM-free and never noticed). So this report's retro covers **three** published weeklies plus a void, and the void is named rather than skipped.
2. **The queue has never recorded a single decision.** `data/research-asset-queue.json`: 22 items, 22 audited, **0 with any decision field set**, 6 awaiting approval (oldest 2026-10-23, 24 days). This is not new — the 11-02 weekly found the same — but it has now survived a whole missed week, so the ask channel is the thing to fix, not the asks.

---

## 1. Landscape — what changed

**Polymarket: two retirements and one deprecation window; I checked each against our code rather than assuming.**

- **Data API v1 is retired, and the retirement is now enforced.** `docs.polymarket.com/changelog.md` (entry **2026-11-02**, read 2026-11-16) says v1 retired with route mappings to v2. Probed today: `GET https://data-api.polymarket.com/v1/leaderboard?limit=2&window=monthly` → **HTTP 410 `{"error":"Data API v1 has been retired"}`**; `GET /v2/leaderboard?limit=2` → **200** with `{rank, user_id, pnl, volume, pagination.next_cursor}`. **Our stack is already on v2** (`src/lib/adapters/polymarket.ts:237` gates on `apiV2()`, cursor walk at :245) and last night's scan proves it end-to-end: `Leaderboard scan complete: 500 wallets (11 new, 489 updated)`, newest `WalletProfile.createdAt` 2026-11-15 22:00:52. **Residual defect, one line:** the v1 offset walk at `:262` is now dead code that would 410 if `apiV2()` were ever flipped false. Not a proposal — a fact for whoever touches that flag.
- **CLOB order/trade query changes take effect 2026-12-14** (changelog entry **2026-11-11**): `associate_trades` deprecated on order and trade responses; `GET /data/orders` requires `market` when filtering by `asset_id`; `GET /orders` and `GET /v1/trade/open-orders` drop `asset_id`/`token_id` filters. **We do not call any of the three** — `grep -rn "associate_trades\|/data/orders\|open-orders" src/ scripts/` returns only `tests/safety.test.ts` asserting we never touch `clob.polymarket.com/order`. What we do call on CLOB is the archived `GET /markets/{conditionId}` (resolution → `tokens[].winner`) and `GET /prices-history`, neither in the deprecation list. **No action; noted because the changelog is the highest-value read on this beat and this one is a near miss.**
- **PolyBolt price subscriptions require an explicit provider from 2026-11-30, Chainlink-sourced ones a Chainlink API key** (changelog **2026-11-16**). We subscribe to no PolyBolt feed (`grep -rn "polybolt\|price.equity" src/ scripts/` → 0). Not our surface.

**Kalshi: one genuinely useful new keyless surface, and its changelog is running ahead of its own clock.**

- **`GET /incentive_schedules` and `GET /incentive_programs` are live keyless today.** Both are changelogged **2026-11-19** — *after* today — but probing them now returns **200** with real data: `incentive_schedules` gives **850 recurring schedules** (`series_lip_recurring*`) with `reward`, `window_days`, `target_size_fp`, `discount_factor_bps`, `all_markets`; `incentive_programs?status=active` gives **200 per-market programs** with `period_reward`, `start_date`, `end_date`, `paid_out`. Per the OpenAPI schema, `reward`/`period_reward` are **centi-cents** (÷10,000 for dollars — the same trap `scripts/lip-ledger.py` already documents). Today's live distribution: **357 schedules at $100/market/window, 163 at $50, 142 at $200, 87 at $75, 39 at $500**; windows **7d (561), 14d (166), 1d (64), once (59)**; target size **1,000 contracts for 848 of 850**.
  **Why this matters here and not as a new lead:** our own `lip-ledger` instrument already read this leg to a verdict on 2026-11-09 (§3 fact 4), and the schedule endpoint is what makes that verdict *structural* rather than sample-bound — the published pool lets anyone compute the ceiling without a fill model. **The changelog is dated ahead of the live API, so a reader who trusts the changelog would call this "not yet live"; the probe says otherwise.** Marked as: endpoint verified live, changelog date `unverified` as an availability statement.
- **Kalshi removes `expiration_time` from market objects** (changelog **2026-11-19**, future-dated): read `latest_expiration_time` instead; `expected_expiration_time` now capped at it. **Checked our one reader:** `scripts/kalshi-macro-shadow.py:238` reads `m.get("close_time") or m.get("expiration_time")` — `close_time` is first, so the removal degrades the fallback only. **No defect.**
- **Rate-limit headers (`X-RateLimit-*`) on REST responses and lower-latency user WS hosts** (changelog **2026-11-12**): authenticated/user-channel surfaces. We hold no Kalshi key and no Kalshi WS subscription. Not our surface.

**Literature — two q-fin.TR items on 2026-11-16, one transferable idea, nothing adoptable now.**

- **arXiv:2611.18150 — *Who Should Be on the Panel? Task-Conditioned Persona Selection for LLM Trading Agents*** (q-fin.TR, new, announced 2026-11-16, https://arxiv.org/abs/2611.18150, CC-BY-4.0). A recruiter picks a panel of named trader personas **per task** from a direction-blind statistical sketch of the instrument; each persona calls daily, a manager commits after reading the arguments and **hierarchical track records**; on eight US stocks over 2025 the selected panel beats a fixed panel of the same size and three prior LLM agents, and keeps its performance with **no warm-up and no history**. The transferable claim is narrow and testable: **who is in the group is a decision to make per task, before how the group coordinates.**
  **Against our stack, checked:** our LLM surface is the local-sentiment shadow A/B — one model (`LOCAL_SENTIMENT_MODEL` = ollama qwen3.5:9b) writing to `data/sentiment-ab.jsonl`, i.e. a **fixed single-member panel**. The paper's mechanism needs several personas per market, which on a 9B local model means several 9B calls per decision — a cost we have never priced. **Not proposed; recorded as the design question it actually asks** (does persona-per-category beat one fixed sentiment read?), which is already carded as `apr-sentiment-edge-single-polarity` in Lane A. I am not re-proposing it — just noting the literature has moved onto the same question.
- **arXiv:2611.17515 — *A Push Down the Mountain: Framing Effects and Internal State Interventions on Collusive Behavior in a Long-Horizon LLM Agent*** (q-fin.TR cross, announced 2026-11-16, https://arxiv.org/abs/2611.17515). Valence framing moves a 12B agent's willingness to collude (loss 25 %, blame 33 % vs 5 % neutral). **Not relevant to us** — we run no negotiation or counterparty agent. Listed only so the week's q-fin.TR block is accounted for.

**Practitioner signal (Reddit, detection only).** Two threads this week are the same post cross-posted — *"I backtested copy-trading Polymarket wallets for 3 months with no hindsight"* (r/Polymarket 2026-11-14 https://www.reddit.com/r/Polymarket/comments/1xwf02z/, r/PredictionMarkets 2026-11-15 https://www.reddit.com/r/PredictionMarkets/comments/1xwsbxz/). **Marked `unverified`; no number taken from it.** It is the same subject our own `c200-fill-scoreboard-caveat` line has been measuring for three weeks, so the thread is corroboration of *interest*, not evidence. The 25.2-hour-old cache on both feeds means the collector re-read 11-14/11-15 entries (`[cache (25.2h old)]`), which is within its own 26h TTL and correctly labelled.

---

## 2. Reusable assets — the deep version

**Radar yield** (`python3 scripts/radar-yield.py`, 2026-11-16): **62 runs**, **521 usable slots = 8.40/run**, and **9 added over 129 runs = 0.07 new leads/run** (skips: no-licence 1,732, already-in-drafts 800, ★0-only 658, already-in-queue 455). Pre-registered amendment: **RULE DOES NOT FIRE** (`updated`-sorted blocks 10 usable vs 511 for the stars blocks) → `GH_QUERIES` untouched. The honest reading is unchanged from two weeks ago: the "usable" count is flattering, the novelty count is what the radar is worth, and this week's one new lead was **malicious** (below).

| # | Asset | Licence / push | What it is, against what we run | Verdict |
|---|---|---|---|---|
| 1 | `hurside69/Polymarket-Perpetual-Bot` | MIT · ★49 · created 2026-10-14 · pushed 2026-11-16 · 65 files · 9 forks · 0 issues | **A payload repo dressed as a trading bot — the #1 result on the "newest Polymarket tooling" query.** It is a Textual TUI over `mock_data.py` (no live path at all), with `__pycache__` committed and "Auto commit" every ~40 min (7 pushes today alone). Its `support/` package is a dropper: `support/bridge.py` is an HTTPS client with **hex-encoded endpoints** (`_AP1 = "2f6170692f76312f617574682f73657373696f6e"` → `/api/v1/auth/session`, `_AP2` → `/api/v1/data/sync`), a **decimal-array relay IP fallback** (`[[49,48,52,…],[49,55,50,…]]` → 104.21.0.1 / 172.67.0.1) used "when the host cannot resolve", a curl fallback for "stripped-down interpreters", and `support/data/release.pkg` = **13,971,495 bytes** of binary. | **DROP** (do not clone, do not `pip install`, do not run) |
| 2 | `polyrank/PolyRank-MCP` | MIT · ★2 · audited **2026-11-16 08:22** | Cited by audit outcome, not re-judged: **watch** — no portable code (typed client for a commercial SaaS; zero `Math.*` in 221 KB of TS), one keyless read-only cross-check against our wallet-rank shadow arm at its natural 200-bet read. Awaiting your call (§5). | **audit outcome: watch** |
| 3 | `bennyjo/phil` | Apache-2.0 · ★252 · pushed **2026-11-16** · 545 MB | Recurring `watch` since 2026-10-20 and **still showing progress** (pushed today, was pushed 11-02) — the re-listing test is met. A self-improving agent that rewrites its strategy after every settled bet, now with a real-money custody path. **Nothing adoptable** (real-money custody, no key path for us); the interesting delta is the per-bet strategy rewrite our own reviews keep declining to do. | **watch** (progress confirmed) |
| 4 | `mileswangs/pm-hftbacktest` | MIT · ★131 · pushed **2026-11-11** | Last week I said it was 17 days untouched and "next week it is dropped or it moves". **It moved** (11-11, +8 days of work since 10-24): event-driven HFT backtester with queue-position and latency modelling. Still not adoptable as a dependency (C++/Python, our replay is already ours), but it is now the only repo in the radar with a *latency* model we lack, and our L2 tape is 21 GB of the exact input it wants. | **watch** (not dropped — it moved) |
| 5 | `YichengYang-Ethan/oracle3-prediction-market-agent` | Apache-2.0 · ★569 · re-audited **2026-11-13** | Cited by audit outcome: **watch**, recommendation is an isotonic-price arm beside raw price on the frozen ML-1 boundary (artifact only, ~1h). Awaiting your call (§5). | **audit outcome: watch** |

**Dropped without re-listing:** `darup67/market-lab` (**drop** 11-02, licence + half-false premise), `warproxxx/poly-maker` (last push 2026-07-09, 130 days — outside the window), `coreyjoshuamiller/prediction-market-public-metrics` and `trendatrenda/polymarket-scanners` (★0, no licence — the same four shapes the 11-02 weekly already refused). `mbordash/DRADIS` stays measured-dropped (AGPL + private-key requirement; its one idea — horizon-scaled margin — is already a replay).

**What #1 means for the radar, stated plainly.** The queries sort by last push, and an auto-commit script games that. Of 15 "usable" slots today (licence ≠ none, ★≥5, ≤90 d), the single new one was a dropper. I am **not** re-opening `GH_QUERIES` — the pre-registered yield rule governs that and it does not fire — but a post-filter on the collector's formatting (`README`+`support/` heuristics aside: **reject any repo whose only commits are `Auto commit`, or that ships a binary blob > 1 MB, before calling it a usable slot**) is cheap, read-only, and is REC 2 below.

---

## 3. Our book against it

**Fact 1 — the halt is over and the first copy in four days landed six minutes after the rebase.** Cycle #87 (`logs/cron/tuning-review.md`): `data/c200-drawdown.json` rewritten 2026-11-15 07:28:52 (`realizedPeak` 11,068.58 → 7,987.32, commit `f63b55e`), `[DRAWDOWN-SHADOW]` 31.7 % → **5.4 %** on the next cycle, **0 `[PRE-LOOP HALT]` after it**, **21 copies / 21 legs**, 0 childless. Fact sheet: C-200 **open 6 legs / $85.91 = 2.3 %** of the $3,811.96 rail; 24 h opens C-200 14 / $188.69 + STANDARD 7 / $72.00. **Implication:** the constraint was the watermark, not the market — and it is now the admissions funnel again (14 `paper_copy` vs 1,026 skips across **162 distinct skipped markets** in 24 h). **Does NOT imply** the gates are too tight: the top skip tags are drift-at-re-offer (127) and confidence < 0.7 (86 + 75), both settled thresholds.

**Fact 2 — the advance gate is 48.7 % booked on legs the ledger says never filled.** Same file: current window (local 11-07…11-13) reads **$207.01** = `unfilled` 101 legs **+$100.87** | `filled` 57 **+$96.10** | NULL 5 **+$10.04**; through `bookedPnl()` semantics the same window is **$106.14**. C-200 lifetime **+$5,623.92** carries **$2,297.07 (40.8 %) on 526 unfilled legs**, while the `filled` cohort is **−$462.33 lifetime** and **−$269.10 over 14 d** (80 legs). **Implication:** the number that decides a phase advance depends on a fill convention, and the fill-stamped cohort is negative. **Does NOT imply** restating the column: #87's arithmetic puts a restatement-without-re-rebase at NW $5,226.85 vs the 7,987.32 watermark = **DD 34.56 %**, re-halting the book one day after it restarted. This is the pending `apr-ladder-credit-positions-only` decision, not a new proposal.

**Fact 3 — the 30-day flow is negative per leg, and the 7-day number is three legs.** Fact sheet: 30d **n=1,445, −$468.59**, and excluding the two stock-clear days (10-24 n=708, 11-04 n=104) **n=633, −$230.48 = −$0.36/leg** (blended −$0.32). 7d **n=146 +$331.19** but **ex-top-3 −$598.09** — the top three legs are 39 % of the absolute sum and the **sign disagrees** with the window net. Lane split: C-200 7d **+$350.48** vs STANDARD 7d **−$19.29** — the sheet's own `! LANE SIGN DISAGREES` line. **Implication:** "the last week was positive" is a tail statement about C-200, and the 30-day per-leg rate is negative on the trading-only basis. **Does NOT imply** the Kelly regime or the band policy is wrong — a convex longshot book is *supposed* to look like this; what it forbids is quoting the blended $331.19 as flow.

**Fact 4 — the Kalshi reward leg is measured, dead, and closed at 1/137th of its gate.** `drafts/lip-ledger-20261109.md` + `data/lip-ledger.json`: **CLOSE**, **$0.000096/contract-hour net** against the card's **$0.0131** gate over **17,405 counted program-hours** (rule asked ≥ 50); reward-only $0.000195 (1/67). The best program we can measure has a **structural ceiling of $0.001120**, so it cannot clear even at 100 % share. And the reason is selection, not adverse selection: **0 of 473** programs in our macro quote universe and **0 of 533** on our 13 print-tape families clear the gate, while **84,605 of 229,636** usable programs in the venue feed do (median ceiling $0.04, p90 $0.133 for ≤2h windows). **Implication:** this is a *universe* finding, not a reward finding — the families that pay are the ones we never capture, and 7 of our 13 tape families (including KXBTC15M, 13.1 M of ~18.9 M tape prints) have **no LIP at all**. **Does NOT imply** we should go build a 15-minute crypto capture: nothing in that chain has been priced.

**Fact 5 — the daily "pre-registered reads" block is still quoting an instrument the registry has already graded frozen.** `data/prereg-registry.jsonl` now exists (built after the 11-02 weekly) with 3 rows; `entry-floor-a` is graded **FROZEN, n=31, 20 reads, frozen_at 2026-10-17** — i.e. the population stopped moving *before* its own 2026-10-24 gate date, exactly the failure the registry was built to expose. Yet today's fact sheet prints **`INSUFFICIENT_N — gate A n=32/60 ROI −0.5173`** and "gate 2026-10-24 = 23d ago", inviting a reader to wait for a number that cannot arrive. Second row `price-side-inversion` is **UNGRADEABLE** (4.22 % pre-freeze vs a 5 % predicate — the gate asserts what is already true). **Implication:** the registry works and the *print* has not caught up; a dead instrument is still occupying the sheet's scarcest slot. **Does NOT imply** the entry floor is wrong (v67's 0.05 floor is why the population froze) — REC 1 is a print fix.

---

## 4. Recommendations (2)

Both read-only, both cheap, neither touches a rule, size, threshold or lane. **Two, not four:** the week's real decision is already pending (§5, `apr-ladder-credit-positions-only`), and manufacturing two more recs to fill the cap is how the 10-26/10-27 backlog of unstarted recs happened in the first place.

```
REC 1 — Make the fact-sheet gate block read the registry, so a frozen gate cannot be printed as "waiting"
  Hypothesis:   the daily "Pre-registered reads" block reads the bespoke scripts directly, so a gate whose
                population has stopped moving (entry-floor-a: FROZEN at n=31 across 20 reads, frozen
                2026-10-17, before its own gate date) is still printed as INSUFFICIENT_N with a
                "23d ago" gate line — a reader-facing instruction to wait for a number that cannot arrive.
  Measurement:  `data/prereg-registry.jsonl` already grades 3 rows (entry-floor-a FROZEN; price-side-
                inversion UNGRADEABLE). Change only the formatting in `scripts/research-collect.py`'s gate
                block: print the registry row's `state` + `reads` + `frozen_at` beside (not instead of) the
                live number, and mark FROZEN/UNGRADEABLE rows so they cannot be read as pending evidence.
                Read-only; no gate logic, no threshold, no lane.
  Decision rule: after 14 daily runs (by 2026-12-01) read `logs/cron/copybot-research-bot.log`: if >= 1
                FROZEN/UNGRADEABLE state printed with its read count on every run AND no gate line goes
                missing, keep it; if the block loses a live number or any run prints a frozen gate as
                pending, revert the format change.
  Cost:         ~30 min, read-only, zero lane risk. Lane B eligible: this is an unfalsifiable-probe repair
                (the probe cannot move and the sheet does not say so), so the parent session may simply
                execute it without an approval round.
  Reversibility: revert the print block; the registry file is untouched either way.
```
Touches `scripts/research-collect.py` (gate formatting only) and card `fact-sheet-collector-truth`. **Not** `entry-floor-read.jsonl` and **not** the floor.

```
REC 2 — Stop calling a repo "usable" when its only commits are `Auto commit` and it ships a binary blob
  Hypothesis:   the radar's usable-slot count is inflated by push-sorted queries that auto-commit scripts
                game: today's single NEW usable hit (licence != none, stars >= 5, push <= 90d) was a
                payload repo (hex-encoded endpoints, relay-IP fallback, a 13.97 MB release.pkg, seven
                "Auto commit" pushes today), and the yield read is 8.40 usable slots/run for 0.07 new
                leads/run.
  Measurement:  post-filter in `scripts/research-collect.py`'s GitHub block (query unchanged — the
                pre-registered yield rule forbids touching GH_QUERIES): drop a slot from the "usable" list
                when (a) every commit in its last 20 is `Auto commit`-style automation, or (b) it tracks a
                binary blob > 1 MB outside a release, or (c) its file tree is < 100 files with no tests.
                Expected n: ~4 runs/day x 14 = 56 runs, ~5 slots/run.
  Decision rule: if over 14 runs the filter removes >= 14 slots (>= 1/run) AND a monthly hand-sample of
                the removed set finds 0 repos that would have been enqueued, keep it and quote the filtered
                usable/run beside the raw one; if it removes < 1/run, or drops a repo we subsequently
                enqueue, revert the filter.
  Cost:         ~45 min read-only; no query change, no queue change, nothing on the live path.
  Reversibility: delete the predicate; the raw block text is unchanged underneath.
```
Touches `scripts/research-collect.py` (GitHub block formatting) and card `asset-queue-decay-and-atlas-diff` (same family: keep junky repos from consuming slots).

**Deliberately not proposed:** (i) any Lane A rule — `apr-ladder-credit-positions-only` is pending and its number is in §3 fact 2; (ii) the Kalshi LIP universe question — carded instead (§7) because reopening it needs a family-level read, not a recommendation; (iii) persona panels for the sentiment lane — already carded (`apr-sentiment-edge-single-polarity`) and the 9B cost is unmeasured; (iv) nothing on drift, bands, or the entry floor (settled).

---

## 5. Asset audits — awaiting your approval

**6 pending.** Ranked by expected value: #1 and #2 are decisions the evidence has already moved; #3–#6 are cheap reads. Approving any of them buys a measurement, never a dependency.

1. **`mirabilis-agent/lip-ledger`** · verdict **watch** · audited 2026-11-03 · report `drafts/asset-audit-lip-ledger-20261103.md` · **pending 13 days** — **and its premise is now dead.**
   Rec: reimplement the donor's ~60-line LIP `side_score` as `scripts/kalshi-lip-reward-model.py` and price the reward leg net of adverse selection. **That work was done independently, better, on 2026-11-09** — `scripts/lip-ledger.py` (6 defects fixed vs the donor approach, including the centi-cents trap and the `next_cursor` truncation) read **CLOSE at $0.000096/contract-hour over 17,405 counted hours** (§3 fact 4), and the card `lip-ledger-kalshi-reward` is **Done**. **My recommendation: `decline` — not because the donor is bad, but because the measurement it proposes already exists and its verdict is on record.**
   Decision rule (verbatim): if modelled LIP reward ≥ $0.0131/contract-hour **net** of measured adverse selection over ≥ 50 counted program-hours across ≥ 20 distinct programs by 2026-11-24, add the LIP line; else record LIP as immaterial and close the card's reward leg. **Already answered: 17,405 hours, $0.000096, else-branch taken.**
   Effort ~2–3 h (moot) · reversibility n/a · **`decline mirabilis-agent/lip-ledger`**

2. **`polyrank/PolyRank-MCP`** · verdict **watch** · audited **2026-11-16 08:22** · report `drafts/asset-audit-polyrank-mcp-20261116.md` · pending 0 days.
   Rec: one keyless read-only Spearman cross-check of our shrunk-arm wallet ordering against Polyrank's public rank, at the shadow arm's natural 200-bet read. No dependency, no lane input; the free tier ends where copy-trading relevance begins.
   Decision rule (verbatim): if ρ ≥ 0.5 with a bootstrap 95 % CI excluding 0 by the next shadow read (**≤ 2026-12-16**), keep it as a standing corroboration source; else record "no external agreement" and drop the source. Effort ~1–2 h read-only · reversibility: delete the footnote · **`approve polyrank/PolyRank-MCP`** / **`decline polyrank/PolyRank-MCP`**

3. **`YichengYang-Ethan/oracle3-prediction-market-agent`** · verdict **watch** · audited 2026-11-13 · report `drafts/oracle3-reaudit-20261113.md` · pending 3 days.
   Rec: rebuild the ML-1 comparator as price + **train-fitted isotonic** in `scripts/ml1-gate-read.ts`, artifact only, no BAR change.
   Decision rule (verbatim): if isotonic-price beats raw price by ≥ **0.002 Brier** on the frozen ML-1 test legs, propose restating BAR as candidate-vs-price+isotonic and re-read the gate; else record raw price as defended. Effort ~1 h read-only on `data/decision-dataset.csv` · reversibility: delete `data/ml1-isotonic-read.json` · **`approve YichengYang-Ethan/oracle3-prediction-market-agent`** / **`decline …`**

4. **`kmasterfleek/kdreams`** · verdict **watch** · audited 2026-11-07 · report `drafts/asset-audit-kdreams-20261107.md` · pending 9 days.
   Rec: ship `data/prereg-registry.jsonl` + `scripts/prereg-grade.py` so dated gates grade as rows. **This has since shipped** (post-11-02, and it grades entry-floor-a FROZEN — §3 fact 5) **by a different route**, so approving it now buys nothing; the donor's spec grammar was not used. **My recommendation: `decline` as superseded, and note the registry exists.**
   Decision rule (verbatim): grade 3 hand-read gates numerically by 2026-11-22; adopt the registry only if ≥ 2 of 3 match the bespoke printed value, else drop. **Partially met by our own registry; the donor's grader is not needed.** Effort ~2 h (moot) · **`decline kmasterfleek/kdreams`**

5. **`lein3000zzz/polythought-go`** · verdict **watch** · audited 2026-10-29 · report `drafts/asset-audit-polythought-go-20261029.md` · pending 18 days — **executed-unapproved since 10-29.**
   Rec: reimplement the donor's ~55-line book-walk taker fill as a read-only replay. **Run 2026-10-29: n=381, 268/381 = 70 % land ≤ 2¢ with a full fill** (`drafts/fak-marketable-entry-replay-20261029.md`), PASS against a 50 % bar.
   Decision rule (verbatim): if VWAP premium ≤ 2¢ on ≥ 50 % of joined legs (n ≥ 150) → open a maker-vs-taker comparison; else close the taker arm. **Fired PASS.** The live consequence is the 11-02 REC 1 comparison (maker vs taker on one population) — **which was never started** (see §6). Effort moot · **`approve lein3000zzz/polythought-go`** (accept the artifact) / **`decline …`** — either way it can be closed.

6. **`xyonium/reach-mcp`** · verdict **watch** · audited 2026-10-23 · report `drafts/asset-audit-reach-mcp-20261023.md` · **pending 24 days (oldest, and now `stale` per the decay rule).**
   Rec: typed per-block input-health classifier with a JSONL sidecar. **Largely moot too:** the fact sheet already carries a typed `## Input health` header with per-block `ok/no_results/rate_limited/gated_off/void` and a `factsheet-status.jsonl` sidecar — so this shipped by another route as well.
   Decision rule (verbatim): after 14 daily runs (by 2026-11-06) read `data/cache/research-recon/factsheet-status.jsonl`; if ≥ 1 block was `gated_off` or `void`-with-rows while the sheet carried no line, promote the typed states; else drop. **The predicate has not fired: today's run is 18/18 ok.** Effort ~2 h (moot) · **`decline xyonium/reach-mcp`**

**Two ledger defects named, neither fixed by me:** (a) **four of six pending items are already executed or superseded** by work done in this repo (lip-ledger, kdreams, polythought-go, reach-mcp) — the queue has no `executed-unapproved` or `superseded` state, so a completed ask keeps asking; (b) **the queue has no recorded decisions at all** (22 items, 0 decisions).

**Decisions log since 2026-11-02: nothing. Zero.** No `decide` call was recorded in the queue file, and the 11-09 weekly that would have carried the asks failed before delivering (§ intro). So the six items above have been open across a week in which nothing reached you through this channel.

---

## 6. Retro — the last four weeks

| Recommendation | Status | The number that decided it |
|---|---|---|
| **11-02 REC 1** — maker vs taker on one population | **PENDING, NEVER STARTED** | No `drafts/c200-maker-vs-taker-*` exists. The population is ready and larger: 373 priced verdicts at 11-02, and the taker replay already PASSes at 268/381. Two weeks gone. |
| **11-02 REC 2** — print the ladder SUM with its tail removed | **PENDING / partially superseded** | `query_bankroll.js` still has no `ex-top-3` print (grep 0). The fact sheet now carries the concentration line on settled windows (7d ex-top-3 −$598.09 vs +$331.19), so the *information* exists — the gate headline still quotes the raw SUM. |
| **10-26 REC 1** — locate the <0.20 flow loss gate by gate (read due 11-09) | **PENDING, NEVER STARTED** | No `drafts/c200-band-flow-*`. Its read date (11-09) passed inside the failed weekly. |
| **10-26 REC 2** — prereg registry + grader | **ADOPTED** ✅ | `scripts/prereg-grade.py` + `data/prereg-registry.jsonl` exist; 3 rows; entry-floor-a graded **FROZEN at n=31 across 20 reads**. Its first act was to prove a gate dead — the exact purpose. |
| **10-26 REC 3** — depth functional form (n ≥ 100 gate, 11-30) | **PENDING, NOT STARTED** | No artifact. The L2 tape it needs is now 21 GB, so the population exists. |
| **10-27 REC 1** — burst× band with wallet-clustered CIs (decision 11-03) | **PENDING, DECISION DATE PASSED** | No artifact. 11-03 came and went silently — this is now a vanished rec, not a pending one. |
| **10-28 / 11-01 REC 1** — write the entry-floor NULL instead of reading it daily | **SUPERSEDED by the registry** ✅/half | The registry grades it FROZEN (so the NULL is now written down in a machine-readable row), but the sheet still prints `INSUFFICIENT_N` daily — REC 1 this week. |
| **10-29 REC 1** — settled window ex-stock-clear | **ADOPTED (10-30)** ✅ | Live: `last 30d EX-BULK-CLOSE n=633 −$230.48, −$0.36/leg` beside the blended −$0.32 — the 2.3× distortion is now visible on the sheet. |
| **10-30 / 10-31 REC 1** — concentration line beside every window | **ADOPTED (11-01)** ✅ | Live and doing work: 7d **+$331.19 with ex-top-3 −$598.09 = sign DISAGREES** (1 of 14 runs). |
| **10-22 REC 1** — the v65 paired read (2SE ≤ $10, n ≥ 70) | **INSTRUMENT BUILT, READ NOT YET RUN** | `scripts/v65-paired-read.ts` exists (card `v65-paired-read-instrument` shipped); no `drafts/v65-paired-*` artifact, and the window closed 2026-11-15. Fourth week named; now one run away. |
| **11-09 weekly** | **VOID** | `HTTP 402: Insufficient Balance` at 08:31 on 2026-11-09. Not a quiet week — a missing report. |
| **Audits, four weeks** | — | DRADIS **refuted** (n=62, −$0.33/leg) · lip-ledger **measured CLOSE** (1/137 of gate) · kdreams **superseded** (registry shipped) · reach-mcp **superseded** (typed input health shipped) · polythought-go **executed** (268/381 PASS) · PolyRank **watch, pending today** · phil **watch, alive** · pm-hftbacktest **watch, moved** |

**The pattern, stated plainly.** Two of the eleven items on this list decided themselves through instruments someone built; the rest are still paragraphs. The single most active axis — the fill-aware ladder basis — did move (rebased 11-15, gate now open, 21 copies), which is the first week since 10-19 where a *book* decision was executed rather than proposed. What did not move: any measurement with a decision date. Three of them (10-26 REC 1, 10-27 REC 1, 10-22 REC 1) have now passed their own dates without a read.

---

## 7. Cards

- **New — `kalshi-lip-universe-gap`** (Backlog, ~1–2h read-only, reopen gate stated in the card): records that the LIP leg closed on **program selection, not adverse selection** — 0 of 473 quote-universe and 0 of 533 tape-family programs clear $0.0131, while 84,605 of 229,636 venue programs do (median ceiling $0.04 for ≤2h windows), and 7 of our 13 tape families have no LIP at all. Keeps the question alive with a measurable reopen condition instead of a paragraph. Checked against 291 cards: no duplicate (`lip-ledger-kalshi-reward` is Done and measured a different population).
- **No new card for REC 1 or REC 2** — each is a live proposal with its own decision rule; carding a recommendation while it awaits a call is how items get double-counted (same rule as 10-26 and 11-02).
- **Cards touched by this report's facts, not by me:** `apr-ladder-credit-positions-only` (pending, now the only decision that gates the ladder), `c200-maker-fill-assumption` (approved 10-27, still unimplemented — the 40.8 % line), `git-backup-large-artifact-policy` (**.git 2,401.4 MiB vs a 2,048 ceiling, 82.1 MB/day, +140.4 MiB in one night** — the ceiling has been breached four nights running), `fact-sheet-collector-truth` (REC 1), `asset-queue-decay-and-atlas-diff` (REC 2's family; the decay rule did flag `reach-mcp` as stale, so it is working).

---

*Nothing applied. No rule, size, threshold, config or lane was touched. Writes this run: this draft and the one card named above. Read-only probes in `~/.hermes/cache/scratch/` (`card-lip-universe-gap.json`, `ks.json`/`kp.json` Kalshi incentive pulls).*
