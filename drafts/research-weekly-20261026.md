# Weekly research deep-dive — 2026-10-26

Fact sheet: `scripts/research-collect.py`, generated **2026-10-26T13:30:34Z (08:30 CDT)** — fresh, **no `SOURCE FAILED` line**. Recon blocks: r/Kalshi **fresh**, r/Polymarket cache 1.2 h, r/predictionmarkets cache 25.3 h (a re-read of the same entries, not a dead feed). Radar-yield read at **22 runs** (first run past the pre-registered n=12).

Numbers about our book below come from the fact sheet, from `logs/cron/tuning-review.md` (cycle #67, 2026-10-26), or from read-only SQL against `prisma/dev.db` taken at 08:34 CDT this run — each labelled. Nothing was written in the repo except this file, the queue decision records named in §5, and card `asset-queue-decay-and-atlas-diff`.

---

## 1. Landscape — what changed this week

**Venues: quiet. Say it plainly — no fee, no rate-limit, no resolution, no new market type on either venue this week.**

- **Polymarket changelog** ([docs.polymarket.com/changelog.md](https://docs.polymarket.com/changelog.md), read 2026-10-26): the newest entry is still **2026-10-21** — PolyBolt's seven forex pairs on `price.equity` and the additive `market_status` field. Both were reported on 10-22 and both are on a surface we do not subscribe to. Nothing dated 10-22 → 10-26.
- **Kalshi changelog** ([docs.kalshi.com/changelog.md](https://docs.kalshi.com/changelog.md), read 2026-10-26): the newest *published* headings are dated **2026-10-29** (subaccount-restricted balance keys on `POST /portfolio/intra_exchange_instance_transfer`; `halt_sources` on margin market responses) — a date **three days ahead of today**, so `unverified` as live, and authenticated/margin surfaces we do not touch. Below them: Oct 22, Oct 19, Oct 15 — all previously read and off-path. **No entry dated 10-23 → 10-26.** Zero impact on the keyless lanes.
- **The one venue event is a non-event: Data API v1's stated retirement date passed and v1 still answers.** The migration page says *"Data API v1 is retired on October 24, 2026"* ([docs.polymarket.com/migrate/data-api-v1-to-v2](https://docs.polymarket.com/migrate/data-api-v1-to-v2), read 2026-10-26). Probed at 08:35 CDT today: `GET /v1/leaderboard` → **200**, `GET /trades` → **200**, `GET /v2/leaderboard` → **200**. So enforcement is either late or was never a hard cutoff — `unverified` which. We are on v2 by default, so nothing degrades; the consequence is narrower and worth stating: the rollback branch at `src/lib/adapters/polymarket.ts:262` still builds a `/v1/leaderboard` URL for an endpoint the docs call retired. It works today and may stop without notice — do not reach for it as an incident lever.

**Literature**

- **arXiv:2610.31903** — *Optimal Size in Market Making under State-Dependent Hawkes Process* (Chávez Casillas & Gan, q-fin.TR, announced **2026-10-26**, https://arxiv.org/abs/2610.31903). Closed-form executed volume = average order size × an **exponential demand function of quote depth** × a Prony-series multiplier over a state-dependent Hawkes order count; retrospective evaluations show higher terminal utility than a baseline under a prescribed inventory bound. It is a market-making paper, not a copy-trading one, but it is the first thing I have read that gives our fill model a *functional form* rather than another linear feature: depth enters multiplicatively and exponentially, and fill probability is a function of placement, not of our scored features. Bears on card `ml-u1-conditional-fill-model` (see REC 3). It does not touch admission.
- **arXiv:2603.01820v2** — *How do standard time series forecasting benchmarks translate to finance?* (Saly-Kaufmann et al., replace, announced **2026-10-26**, DOI 10.1002/for.70233, https://arxiv.org/abs/2603.01820). Sixteen deep architectures on 15 years of daily futures: generic Transformers and SSMs **underperformed a plain AR(1)**; the strongest was a Variable-Selection-Network + LSTM hybrid, and xLSTM was the most transaction-cost robust. This is support for the parsimony doctrine already written into `ml-doctrine-time-and-era-splits` and the ML-1 price-only baseline — support, not licence: 15-year daily futures is not 30-day outcome labels.
- **arXiv:2610.31141** (q-fin.TR, **2026-10-23**, reported in that morning's brief): matched positions earn **+1.28–1.31 units with one passive execution vs none**, and **+3.79–3.82 more with two vs one** — the edge concentrates in liquidity *provision*, not flow-following. Equities, so the transfer is `unverified`; it is the mechanism question behind the pending L2 fill verdict (card `vike-l2-prerecorder-window`): did the source fill passively while we paid the spread?

**Practitioner signal (Reddit — signal detection only, `unverified` as claims)**

- r/predictionmarkets **2026-10-21**, *Ranking prediction-market wallets by capital in place instead of P&L* — an alternative wallet ranker (capital deployed, not realized P&L). It lands on the same question as the already-approved crowdintel BH-FDR read, so it changes nothing; recorded so the next read does not re-derive it from a thread.
- r/predictionmarkets **2026-10-19**, *How often does a 5-exchange spot composite move before Polymarket's BTC settlement feed?* — a settlement-feed identity question. Only relevant to the BTC pair lane, and the thread is not the primary source (Polymarket's published resolution rules are); nothing carded off it.

---

## 2. Reusable assets — tooling radar, deep version

**Radar yield, first verdict past n=12** (`python3 scripts/radar-yield.py`, 2026-10-26): **22 runs**, **9.73 usable slots/run**, but **0.11 new leads/run** — 5 added over 45 runs / 1,575 slots, with skips of no-licence 643, already-in-drafts 317, already-in-queue 201. The pre-registered amendment reads **RULE DOES NOT FIRE** (`updated`-sorted queries 7 usable vs 207 for the stars blocks) → `GH_QUERIES` untouched. Read honestly: the radar is cheap and keeps arrival coverage, it is **not** a lead engine; ~1 usable new asset per 9 runs is the true yield, and this week's five candidates below are what that yield looks like.

| # | Asset | Licence / push | What it is, against what we run | Verdict |
|---|---|---|---|---|
| 1 | `kmasterfleek/kdreams` | MIT · ★0 · created 2026-10-14 · pushed 2026-10-26 · TS, 19 MB, vitest+eslint | Observe-only nightly research loop. Snapshots top-of-book for the 100 highest-volume markets per venue plus resolutions (no keys), forms **one falsifiable hypothesis a night with a machine-readable spec** (metric, venue, slice, op, threshold, `minN`), and grades it **in code on data recorded after the freeze** — SUPPORTED / REFUTED / INCONCLUSIVE / UNGRADEABLE. Two guards: a spec the pre-freeze data already satisfies is rejected, and the model sees its past grades so it cannot re-propose a refuted idea. We have the pre-registration habit in prose; we do **not** have the grader, and this week's entry-floor gate sat unread for two days. | **audit** (concept, not code) |
| 2 | `inputoutput9/prediction-market-agent-atlas` | MIT · ★1 · as-of **2026-10-26** · weekly CI rescan | `data/repos.yaml` = **44 curated entries** (22 polymarket / 10 kalshi / 12 cross) with dated evidence strings, four curated axes (provenance, capability, safety, agent_fit) and a **computed maintenance axis** from `data/live.json` that decays stale repos. Not a scanner and not code we need — it is the *decay rule our asset queue lacks* (16 items, none expires) plus an independent discovery channel. | **watch** (card `asset-queue-decay-and-atlas-diff`) |
| 3 | `pmxt-dev/pmxt` | MIT · ★2,186 · pushed 2026-09-30 (26 d) · 1,451 open issues | "CCXT for prediction markets". The product is a **hosted API with custody and signing**; self-hosting wants venue-native credentials. Our lanes are keyless and the v2 adapter cutover just landed — a custody layer is a non-starter for paper-only, keyless reads. | **drop** |
| 4 | `shreesomnath/EarlyCast` | MIT · ★2 · pushed 2026-10-26 | The whole repo is one 297 KB `index.html` plus icons and a manifest. Description promises "Prediction Market Intelligence"; there is no code to read. | **drop** (claim-only) |
| 5 | `cejor6/kalshi-mcp-server` | MIT · ★3 · pushed 2026-10-25 · Python | The strongest safety model on the Kalshi side (demo-default, tighten-only caps, gitleaks, per-order/day USD caps) — and gated on **RSA-PSS private-key auth**. We hold no keys and route nothing to Kalshi. Nothing transferable except the tighten-only cap idea, which our caps already apply. | **drop for us** |

Recurring items: nothing on `watch` has gone untouched for three weeks — `bennyjo/phil` (10-20), `xyonium/reach-mcp` (10-23), `mileswangs/pm-hftbacktest` (10-24) are all inside the window, so none is dropped for staleness this week. `arnaudknobloch/awesome-polymarket` and `parkyucheol-del/alphapipeline` were dropped by the audit worker and are not re-listed.

---

## 3. Our book against it

1. **C-200's per-leg has fallen by an order of magnitude in a fortnight — and it is a flow story, not an edge story.** Read-only SQL, settled C-200 `PaperTrade`, `isDemo=0`, **opened-cohort** (so this is not realized-in-window): legs opened **2026-09-26 → 10-11** = **256 legs / +$1,930.94 = $7.54/leg**; legs opened **2026-10-12 → 10-25** = **120 legs / +$103.53 = $0.86/leg**. Implies: no ladder advance is reachable (phase gate **$333.95 of $1,750 = 19.1 %**, next read **−$151.99 on 10-27**, tuning #67). Does **not** imply the Kelly regime or the band policy is wrong: one $485.48 day sits in the earlier window and n=120 is thin.
2. **Decomposed, 88 % of that swing is the sized band losing legs, not the dead zone diluting.** Same query, by band: **<0.20** went **53 legs / +$1,838.66 ($34.7/leg) → 21 legs / +$134.03 ($6.4/leg)** — that is **−$1,704.63 of the −$1,930.94 total difference (88 %)**. The **0.20–0.40 dead zone** went 92 → 74 legs and **+$1.97 → −$0.38/leg** (−$210 drag). The **0.40–0.60** block vanished as designed (189 → 2 legs, v62's hard skip). Implies: the binding constraint is admission *into the sized band*. Does **not** imply relaxing a gate — drift is pre-recorded no-change on the poll basis (per-signal basis false, cohort7d +$1.60).
3. **The "one wallet" worry is a day artifact.** Lifetime C-200 = **2,525 legs / +$5,852.66**; excluding the top wallet by leg count (358 legs): **2,167 legs / +$4,759.37 = $2.20/leg**. 30 d = **376 legs / 25 wallets / +$2,034.47**, where the top wallet is **41.8 % of legs but 13.8 % of PnL**. Implies tuning #67's "7 of the 8 C-200 legs on 10-25 came from one wallet" is a *day* observation on a thin flow (3 legs / $49.97 in 24 h). Does **not** license a copy-set change — `wallet-cap-shadow-lane` already prices the per-wallet ceiling.
4. **Admission, not capital, still sets the book** (tuning #67). 805 copy-eligible detections → **3 legs / $49.97**; 818 journal skips of which **626 (76.5 %) are the drift re-offer loop across 106 markets** (5.9 rows per market). Implies the funnel is a gate-mix problem. Does **not** imply a threshold move.
5. **The fact sheet's exposure headline is still a lane + demo blend — card part (c) is open.** It prints *"open positions: 512, at risk $5,562.00"*. Read-only SQL today: **493 STANDARD / $5,376.40** + **1 C-200 / $20.00** + **18 demo STANDARD / $165.60** = 512 / $5,562.00 exactly. So **96.7 %** of the "at risk" number is the legacy lane and **3.0 %** is demo, while the lane the ladder runs on is **$20**. Parts (a) and (b) of `fact-sheet-collector-truth` landed (10-21, 10-22); this one did not.
6. **v67's read is due and its blocked population is a tail.** 78 `near certainty` blocked decisions against a 60 bar, **0 sub-0.05 C-200 legs since 10-24**; the shadow feed's `byPriceBand["0-0.05"]` reads n=1,796 / 1,124 marked / **+$540,379** ≈ $480/row. Read as a distribution, never a mean. Does **not** imply the floor is wrong.

---

## 4. Recommendations (3, ranked by expected value per engineering hour)

```
REC 1 — Locate the <0.20 flow loss gate by gate (sequencing read for the ladder)
  Hypothesis:   the sized band's leg count halving (53 → 21 in a fortnight) is concentrated on ONE
                admission gate on re-offers, so the already-registered drift-sign read (due 2026-11-02)
                is the binding constraint and correctly sequences the next advance.
  Measurement:  read-only SQL over DecisionJournal joined to ObservedTrade on observedTradeId
                (the join research-collect.py already uses), source print price < 0.20, last 30 d:
                decision-level skip counts by gate class (drift / TTR / confidence / blacklist /
                coalesced), deduped by market+outcome, with rows-per-distinct-market beside each class.
                Expected n ≈ 2,000 decision rows (24 h sample is 686 skips / 114 distinct pairs);
                refuse the read below 300 deduped decisions.
  Decision rule: if >= 60% of deduped <0.20 skip decisions carry the drift gate as their ONLY binding
                block by 2026-11-09, record the drift-sign read as the ladder's binding constraint and
                let its 11-02 result set the order of the next advance work; if confidence or TTR
                dominate instead, restate `drift-gate-sign-defect`'s EV as not-binding on this subset
                and drop the drift-first sequencing.
  Cost:         ~1h read-only SQL, zero live-lane risk.
  Reversibility: one table in a draft; delete it and the sentence it feeds.
```
Touches: `drafts/c200-band-flow-20261026.md` (new, read-only), read-only against card `c200-goal-policy-v2-rolling7d-gate`.

```
REC 2 — Pre-registration as data: a spec registry plus a grader (kdreams' design, not its code)
  Hypothesis:   unread gates are a recurring class, not a one-off: the entry-floor gate (2026-10-24) was
                read two days late after nine days with a one-line series, and today's fix only DISPLAYS
                gate status on the fact sheet — each read's metric still needs its own bespoke script,
                so the four dated gates now open (10-27, 11-06 ×2, 11-15) carry the same risk.
  Measurement:  add data/prereg-registry.jsonl (metric, slice, op, threshold, minN, gateDate, freezeAt,
                instrument) and scripts/prereg-grade.py, which computes each registered metric from its
                existing instrument on POST-freeze data only and marks UNGRADEABLE when the spec names
                something no instrument measures; read the count of gates that passed their date with
                no read appended, over 30 days (to 2026-11-25).
  Decision rule: if >= 1 of the four dated gates passes its date unread in that window, make new
                pre-registrations FAIL-CLOSED (a card carrying a gateDate must have a registry row, and
                the weekly job reports any missing one); if zero pass unread, record that the
                display-only fix sufficed and drop the registry.
  Cost:         ~3h (grader + registry + one wrapper hook); read-only, zero risk.
  Reversibility: delete the script and the JSONL; nothing in a decision path reads them.
```
Touches: `scripts/prereg-grade.py`, `data/prereg-registry.jsonl`, extends card `fact-sheet-collector-truth` (stage 2).

```
REC 3 — Test the depth functional form on the fill model (arXiv:2610.31903)
  Hypothesis:   p(fill at intent-$0.02) is better described by executed volume = f(order size) x
                exponential decay in quote depth (the paper's closed form) than by our current logistic
                on (band, hour, size, ttr, activity, vol) — i.e. depth belongs in the model multiplicatively,
                not as one more linear feature.
  Measurement:  out-of-sample log-loss and AUC on C-200 legs whose token has L2 book coverage at
                dispatch time (data/l2 = 44,408 token files / 20 GB, data/l2-events 1.9 GB); fit on
                pre-2026-10-12 legs, test on 10-12+; CHECK n FIRST — defer unless >= 100 out-of-sample
                legs carry depth-at-intent.
  Decision rule: if the depth-form model beats the current feature set by >= 0.02 AUC or >= 2% log-loss
                at n >= 100 out-of-sample legs by 2026-11-30, card ml-u1-conditional-fill-model adopts
                the depth multiplier term (shadow-first, Lane A approval); else the current spec stands
                and the paper is recorded as not transferable at our depth.
  Cost:         ~2-3h read-only replay; no live change.
  Reversibility: one analysis script; the live fill convention is untouched either way.
```
Touches: card `ml-u1-conditional-fill-model` (spec input only — the sidecar's intent−$0.02 maker convention is **not** in scope and is not being re-argued).

Not proposed, deliberately: nothing on Kalshi routing (retired), nothing on the Kelly regime / band policy / ladder gate (settled), no size or threshold change, no new lane. Lanes already in flight (weather, BTC pair, GDELT, ML-1, local sentiment, Kalshi macro shadow) are extended only by measurement above.

---

## 5. Asset audits — awaiting your approval
### 5.1 Pending (1)

- **`xyonium/reach-mcp`** · verdict **watch** · audited 2026-10-23 · report `drafts/asset-audit-reach-mcp-20261023.md`
  - Recommendation: add a **typed per-block input-health classifier** (`ok | no_results | rate_limited | gated_off | void` + notice) with a JSONL sidecar to `scripts/research-collect.py`, extending card `fact-sheet-collector-truth`. Fact-sheet text unchanged in stage 0 — this is instrumentation only, no dependency, no code adopted from the repo.
  - Decision rule: read-only; after **14 daily runs (by 2026-11-06)** read `data/cache/research-recon/factsheet-status.jsonl`; if **≥1 block was `gated_off` or `void`-with-rows** in those runs while the same run's fact sheet carried no line about it, promote the typed states into the fact-sheet header; else drop.
  - Effort ~2h · reversibility: delete the sidecar write and the JSONL.
  - Why it is still on the list: this week produced exactly this class twice — the `DecisionJournal` query voided the distinct-skip line for days under a "no SOURCE FAILED" banner, and the Kalshi block read 200/200 zeros for four days because the page it sampled was the *newest listings*. Both were silent; both are now fixed.
  - Answer: **`approve xyonium/reach-mcp`** / **`decline xyonium/reach-mcp`**

### 5.2 Decisions log — everything decided since the last weekly, and what happened

| Repo | Call | When | What followed |
|---|---|---|---|
| `crowdintel-xyz/polymarket-agent-kit` [audit] | **approved** | 2026-10-21 ("I approve of all 4"), re-confirmed 10-23 ("All approved") | Card `crowdintel-wallet-fdr-audit` (Scheduled) — **not executed yet**. Queue still showed `pending`; **recorded today** from the card notes. |
| `mnemox-ai/tradememory-protocol` [watch] | **approved** | 2026-10-21, re-confirmed 10-23 | Card `tradememory-deflated-sharpe` (Scheduled) — **not executed yet**. Queue still showed `pending`; **recorded today**. |
| `vike-io/vike-data-cli` [watch] | **approved, blocked on you** | 2026-10-21 | Card `vike-l2-prerecorder-window`: needs the 37-day pre-recorder L2 window (205 GB) which *you* pull and hand over — no key is installed or stored here. **Recorded today** as approved-blocked. |
| `agent-next/polymarket-paper-trader` [watch] | approved | 2026-10-21 | Applied same day (`dcb53a5`) — archived-market fee pricing landed; closed. |
| `mbordash/DRADIS` | approved → **refuted** | 2026-10-15 | Read-only horizon-margin replay: n=62, **−$0.33/leg**, CI straddles 0 → dropped with the null recorded (`drafts/horizon-margin-replay-20261015.md`); the one idea that survived is carded separately. |
| `bennyjo/phil` [watch] | audited 10-20 (reaudit) | — | Watch; no adoption proposed. |
| `mileswangs/pm-hftbacktest` [watch] | audited 10-24 | — | Watch; no adoption proposed. |
| `arnaudknobloch/awesome-polymarket` | **drop** | audited 10-24 | Re-listed nowhere. |
| `parkyucheol-del/alphapipeline` | **drop** | audited 10-19 | Re-listed nowhere. |

**Defect named (and now fixed):** three of the four asks from the 10-21 batch sat as `pending` in the queue for five days while the roadmap cards recorded them as approved — so every daily brief since 10-21 re-asked questions you had already answered. That is ledger-vs-cards drift, and it is the reason the same three items appeared in the last weekly. Their calls are now recorded, with the card notes as the source.

---

## 6. Retro — the last four weeks, with the number that decided each

| Recommendation | Status | The number |
|---|---|---|
| 10-16 REC 1 — v1→v2 parity read, then flag-gated cutover | **adopted** | Cutover landed 2026-10-19 (`drafts/data-api-v2-cutover-20261019.md`); 0 v1 literals in the live path. The documented retirement (10-24) then passed with **v1 still answering 200** — the deadline cost nothing, which is only visible because we moved first. |
| 10-17 REC 1 — pre-register the sub-$0.05 entry floor | **read → null-by-n** | Read #2 on 2026-10-26 (2 days after the gate): **INSUFFICIENT_N**, gate A n=**31/60** at ROI **−55.18 %**, gate B passes (+$5,250.66 / 55 resolved). The n cannot move by waiting: **31 settled sub-0.05 legs on 10-17 and 31 on 10-26**, zero sub-0.05 openings since registration. Recording the NULL is a Lane A call — not mine. v67 (10-24) floors the long-shot *multiplier* at 0.05, a different variable from `c200MinEntryPrice`. |
| 10-19 weekly REC 1 — fact-sheet truth (3 defects) | **partly landed** | (a) `DecisionJournal` distinct-count prints **114** (fixed 10-21); (b) Kalshi close-window block reads **617,405 on 76/200** (fixed 10-22, `4ff729c`); (c) the **lane + demo blend on the exposure line is still there** (§3 fact 5: 512 = 493 + 1 + 18, $5,562 = $5,376.40 + $20 + $165.60). Card stays open on (c). |
| 10-19 weekly REC 2 — hull-gap replay on held events | **pending** | Card `c200-exclusive-pair-hull-check` (Backlog), never run. No number. Named, not dropped. |
| 10-19 weekly REC 3 — `ev_ci_low` on the U2b selector | **pending** | Card `ml-u2b-selector-search` (Backlog). No number. |
| 10-19 weekly — radar-yield instrument | **adopted → verdict this week** | 22 runs: **0.11 new leads/run**; the pre-registered amendment **does not fire**, `GH_QUERIES` untouched. |
| 10-20 REC 1 — re-key the `/trades` parity probe | **adopted** | Hash-key overlap was **260/443** (and 0/250 on one condition) → the FAIL was the probe's identity key, not venue divergence; v1 and v2 serve the same fills under different hashes. |
| 10-21 REC 1 — clear the last v1 route string | **partly** | `audit-print-types.ts` moved off v1; the rollback branch at `polymarket.ts:262` survives and, as of today, points at a documented-dead-but-live endpoint. |
| 10-22 REC 1 — v65 paired read (2SE ≤ $10 at n ≥ 70) | **pending, no read recorded** | The v65 question is still unanswered and its window is open until 2026-11-15. This is the one open item with no instrument running; named here so it does not vanish. |
| 10-23 REC 1 — source-print notional as an admission feature | **approved → carded** | `research-source-print-notional`, decision **2026-11-06**. Baseline: <$250 **$5.22/leg (n=1,161)** vs ≥$250 **$0.33/leg (n=159)** since 09-04. |
| 10-24 / 10-25 REC 1 — label the fact sheet's window and skip bases | **adopted** | This run's sheet prints the **SETTLED clock** (`COALESCE(closedAt, resolvedAt)`, `isDemo=0`) as the headline with the **OPENED clock (LEGACY)** line beneath it, and decision-level counts beside entry-level. |
| 10-26 REC 1 — price the drift-sign fix on *admissible* flow | **registered today, read due 2026-11-02** | No number yet; REC 1 above is its sequencing companion. |
| Audit outcomes (4 weeks) | — | DRADIS **refuted** (n=62, −$0.33/leg); phil **watch**; pm-hftbacktest **watch**; awesome-polymarket **drop**; alphapipeline **drop**; reach-mcp **watch → pending your call**. |

No recommendation from the last four weeks has quietly disappeared. Two are stale-but-named (hull-gap, U2b — both Backlog) and one (v65 paired read) has no instrument running at all: that is the closest thing to a vanished rec and it is called out above.

---

## 7. Cards

- **New:** `asset-queue-decay-and-atlas-diff` (Backlog, ~1h, read-only) — the queue's 16 items never expire, so a `watch` verdict is permanent; the atlas ships the decay rule (computed maintenance axis, auto-decay) plus a second discovery channel at 0.11 new leads/run. Checked against all 238 cards before adding: no duplicate.
- **No new card** for REC 1–3: each is a live proposal with its own decision rule, and carding a recommendation while it awaits approval is how recs get double-counted.
- Existing cards touched or extended: `fact-sheet-collector-truth` (part (c) still open; REC 2 would add stage 2), `ml-u1-conditional-fill-model` (REC 3 input), `c200-goal-policy-v2-rolling7d-gate` (read-only), `c200-entry-floor-005-prereg` (null pending Lane A).

---

*Nothing applied. No rule, size, threshold, config or lane was touched. The only writes this run: this draft, one roadmap card, and three `asset-queue.py decide` records reconciling calls you had already made.*
