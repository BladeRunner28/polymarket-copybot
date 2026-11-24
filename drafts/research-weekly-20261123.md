# Weekly research deep-dive — 2026-11-23

Fact sheet: `scripts/research-collect.py`, generated **2026-11-23T14:30:07Z (08:30 CST)** — **15/18 blocks ok, 0 `no_results`, 0 `rate_limited`, 3 `void`** (all three Reddit Atom feeds; caches 145.2 / 145.2 / 169.2 h old behind HTTP 404). Book numbers below come from that sheet or from repo files I opened this run — `logs/cron/tuning-review.md` cycle #94, `data/lowconf-shadow-summary.json` (generated 14:33Z), `data/prereg-registry.jsonl`, `drafts/ttr-floor-all-lane-basis-20261123.md`, `data/research-asset-queue.json` — each labelled where quoted. Nothing was written except this file and the two cards named in §7.

**Two things up front, because both are defects in the channel rather than in the market.**

1. **The approval command silently truncates — and it is hiding the one item I recommended approving last week.** `python3 scripts/asset-queue.py approvals` prints `awaiting approval: 6` and then lists **five**; its `--limit` default is **5** (`scripts/asset-queue.py:741`), and the sixth — `polyrank/PolyRank-MCP`, the only live recommendation — is the one dropped. I caught it only because `status` disagrees with `approvals`; a run that trusted the command would have dropped an ask silently, which is the exact failure the 2026-11-16 weekly called "the thing to fix, not the asks". All six are listed in §5 below.
2. **The practitioner lane is not quiet, it is host-blocked — 7th consecutive day.** Probed again today from this host: `www.reddit.com/r/X/top/.rss` → **404** (266 bytes), `old.reddit.com/…/.rss` → **302**, `www.reddit.com/r/X/top/.json` → **403**, `api.pullpush.io` → **429** ("does not provide free scraping resources for agents"), `rsshub.app` → **403** ("restrict access for some feed readers"). A mirror swap would be another silent void; only an app credential survives this.

---

## 1. Landscape — what changed

**Polymarket: nothing new since 2026-11-20, but the final fee/rebate text is worth reading once — because it is the first schedule where maker side is paid at all.** Newest changelog entry is **Nov 20, 2026** (docs.polymarket.com/changelog.md, read 2026-11-23): taker coefficients settle at **0.01 or 0.05** by category with **geopolitics fee-free**; **maker rebates move from daily market-wide pools to volume tiers paying 0/3/7/10/15 % of the taker fee eligible maker fills generate**; taker rebates become Gold 10 / Platinum 25 / Diamond 40 / Obsidian 50 / Onyx 60 % with Bronze, Silver, category multipliers and one-time level-up bonuses removed (docs.polymarket.com/programs/maker-rebates.md). **Against our stack:** our booking law (`src/lib/fee.ts`) charges a taker fee only on early exits and books **no rebate of either kind**, and the rebate ladder is already priced on our book by `scripts/profit-wv-tier.py` (the 11-23 sibling read) — so this is context, not a new lead. What is *still* wrong is the input: `data/fee-schedules.jsonl` mtime remains **2026-11-20 09:18**, 14 h before the 23:59 UTC reprice, i.e. ~3 days stale; that is the approved-unapplied pair in tuning #94 Rec 2, not a proposal.

**Kalshi: genuinely quiet.** The changelog has no entry between **2026-11-19** and a block of **nine entries dated 2026-11-26**, all ahead of today → `unverified`. They are on-request *market-creation* limits (`POST /weather_point_markets`, `/concert_cancellation_markets`, `/flight_disruption_markets` return 429 past a per-account rolling-24h cap) and a restatement of how on-request concert markets resolve (JamBase listing first-shown-within-period; `close_time` one minute before scheduled start). Neither is a copyable surface for us and neither touches a reader we run. The **keyless `/incentive_schedules` + `/incentive_programs`** surface reported last week is unchanged, and the LIP leg remains closed on program selection (card `kalshi-lip-universe-gap`, no progress this week).

**Literature: q-fin.TR is empty today, and the feed answered rather than failing.** `https://rss.arxiv.org/rss/q-fin.TR` returns the channel and **zero items**; `rss.arxiv.org/rss/q-fin.PM` returns three, none on prediction markets or microstructure: *Nonlinear Shrinkage for Higher Moments Estimation in Large Portfolios* (arXiv:2611.27274), *Are Calibrated Decision Models Calibrated on Markets?* (arXiv:2611.26716 — Nasdaq-100 allocation), *Trust and Lottery-Related Anomalies* (arXiv:2611.27020). A quiet week on this beat, stated plainly.

**Practitioner signal: unavailable.** See the top of this file. Detection-only by rule, so nothing was lost that could have been *sourced* — but the lane has now been dark long enough that a "fee changed" thread would not reach us until the second week.

---

## 2. Reusable assets — the deep version

**Radar yield, quoted as it stands** (`python3 scripts/radar-yield.py`, 08:32): **70 runs logged**, **588 usable slots over 70 runs = 8.40/run**, and — the number that matters — **10 leads added over 157 runs = 0.06 new leads/run** (skips: no-licence 2,171 · already-in-drafts 978 · ★0-only 799 · already-in-queue 521). Pre-registered rule: **RULE DOES NOT FIRE** — `updated`-sorted blocks 10 usable vs 578 for the stars blocks — so `GH_QUERIES` stays untouched. Today's own evidence for why: all five "newest Polymarket tooling" hits are **★0** and four carry no licence at all.

| # | Asset | Licence · push | What it is, against what we run | Verdict |
|---|---|---|---|---|
| 1 | **`ccxt/ccxt`** — prediction namespace | MIT · ★44,967 · pushed 2026-11-23 | `js/src/prediction/` (also php/cs/py/ts) ships a **2,853-line Polymarket adapter over `clob.polymarket.com` + `data-api.polymarket.com`** covering markets (one outcome token = one market), order book, trades, OHLCV, events, **positions, holders and wallet `activity`**, plus a Kalshi adapter over `api.elections.kalshi.com`. This is the same keyless surface our hand-rolled `src/lib/polymarket.ts` reads. **What it does not do:** our funnel — wallet tracking/demotion, observation-only containment, decision journaling, the snapshot containment identity. **Effort:** 2–4 h audit before any adoption; it would become a dependency of the read path, so licence + maintenance matter more than the code it saves. | **audit** (enqueued today) |
| 2 | **`pmxt-dev/pmxt`** | MIT · ★2,218 · pushed 2026-09-30 (54 d) | "CCXT for prediction markets" — but it is a **hosted SaaS** with open-source SDKs; writes supported on Polymarket/Opinion/Limitless. Replaces nothing locally: it inserts a third party in the read path we already own, keyless-based, and adds a service dependency for a paper bot. | **drop** |
| 3 | **`mbordash/DRADIS`** | AGPL-3.0 · ★38 · pushed 2026-11-22 | Recurring. Audited 2026-10-15 → **measured-dropped** (n=62, −$0.33/leg); its one transferable idea (TTR-scaled admission margin) is already a pre-registered replay, and the blocker (AGPL + requires a private key in the process) has not moved in five weeks. No progress → not re-listed as a lead. | **drop** |
| 4 | **`clearfills/clearfills`** | NOASSERTION · ★0 · pushed 2026-11-23 | "Deterministic Ed25519 pre-trade risk firewall & MCP server for AI trading agents". The idea — refuse before dispatch on a signed risk state — is what `[RISK-GATE]` + the drawdown/gross/rail stack already do, natively, in-process. NOASSERTION is not a usable licence for anything that would sit in front of an order path. | **drop** |
| 5 | **`qizwiz/juice-board`** | no-licence · ★0 · pushed 2026-11-23 | Cross-venue prediction-market pricing "measured honestly, with the denominator" — the methodology we already apply (every window carries its ex-top-3 / ex-bulk-close / nonzero-row count). No licence = unusable. | **drop** |

**Continuity, not re-listing:** `akilatrades/sports-market-maker` was audited today → **drop** (`drafts/asset-audit-sports-market-maker-20261123.md`); `parkyucheol-del/alphapipeline` (x402 proxy, needs a signing wallet) → **drop** (11-23 brief); `polyrank/PolyRank-MCP` is **pending your call** and is in §5, not here.

---

## 3. Our book against it

**Fact 1 — the 7-day loss is broad, and the 1-day gain is one leg. Those are different shapes and only one of them is a signal.** Fact sheet: 7 d settled **n=183, −$322.68**; the top-3 legs by |PnL| are **$140.47 of a $1,635.54 leg-magnitude sum (9 %)**, and **ex-top-3 the window is −$463.15 — the sign agrees**. The same sheet's 1 d is **n=33, +$221.36 with top-3 = $187.63 of $239.36 (78 %)**, i.e. the green day *is* one leg (tuning #94: `epl-hul-bri` @0.1333, `filled`, +$130.02 = 83 % of the day). **Implies:** the negative week is not a bad market to excise, it is the lane's current distribution. **Does not imply** the lane has no edge — C-200 lifetime is **+17.2 % ROI on n=2,984 / $31,072 cost** (fact sheet), so the 30 d number is a regime read, not a verdict on the design.

**Fact 2 — the ladder gate has stopped being inflated by unfilled legs; the lifetime headline has not.** Tuning #94: trailing-7 d settled **145 legs = `filled` 44 / −$278.03 + `unfilled` 101 / $0.00 + `NULL` 0** — "second consecutive 7-day window with zero unstamped legs", so **one hundred per cent of the current 7-day loss sits on venue-confirmed fills**. Lifetime is the opposite: **`unfilled` 627 legs carry +$2,297.07 of the +$5,345.89**, `filled` 309 legs are **−$896.40**. **Implies:** `apr-ladder-credit-positions-only` no longer changes any *current* gate number — its remaining scope is the lifetime ROI quote (43 % of the headline on legs the market never brought to our price). **Does not imply** the gate is trustworthy in the other direction: the same window says the filled class loses.

**Fact 3 — the gate turns positive this week on window arithmetic, not on trading.** Tuning #94: settled rolling-7d gate **−$393.31 vs $1,750 (−22.5 %)**, window 11-14…11-20; **forward: 11-24 +$98.03, 11-25 +$118.03, 11-26 +$237.95**. The first positive print is 11-17's **−$217.86** rolling out of the window. $237.95 is **13.6 % of the bar**. **Implies:** a green gate line on 11-24 is a mechanical read and must not be consumed as recovery; the advance rule (v2: settled 7d SUM ≥ target × 7) cannot fire on any forward path visible today. **Does not imply** the loss is over — 11-21…11-23 contributes to the *next* window.

**Fact 4 — the minConfidence bar is defended, and I can now say so dust-free.** `data/lowconf-shadow-summary.json` (generated 14:33Z today): 42,077 candidates, 28,735 marked, win 47.3 %, headline `wouldHavePnl` **+$546,210** — of which **1,527 dust rows carry $549,804**; dust-free the whole shadow is **−$3,593.93 = −$0.13/trade**. The subset refused *only* on confidence: **n=433, 127 marked, −$399.02 = −$3.14/trade**. **Implies:** the ~70 confidence skips in the last 24 h are doing work; there is no case to touch `minConfidence` 0.7, and the "we are skipping half the funnel" reading is a dust artifact. **Does not imply** confidence is well-calibrated above 0.7 — the 0.60–0.70 bucket reads n=1,605 / −$2,401 *before* the dust floor, so that cell is not usable as printed.

**Fact 5 — capacity is not the constraint; two unfilled $100 clips are.** Fact sheet: open **14 C-200 legs / $339.44 = 9.2 %** of the **$3,672.94** rail (STANDARD 381 legs / $4,171.52 against a 1,300-leg cap). Tuning #94: `will-bitcoin-reach-65k` @0.17332 and `ucl-sf-fcb` @0.09444 are **$100 each and both `unfilled` = 56.0 % of open cost**. **Implies:** the book has room and no power to use it; the binding variable is the clip tier (card `profit-c200-clip-cap-25`), not the cap. **Does not imply** the cap formula is wrong — the sheet's own note says the printed $3,672.94 omits the open-MTM term the scorer adds.

---

## 4. Recommendations (3)

Three instrument repairs, all read-only in effect, none touching a rule, size, threshold, lane or config. **Not four:** the week's live money decisions are already on the table — the approved-unapplied fee pair (tuning #94 Rec 2 + Rec 3, same window by their own note) and the pending basis call — and manufacturing a fourth would add noise, not evidence.

```
REC 1 — Make the fact-sheet gate block print the registry's FROZEN state (carried; 2nd week)
  Hypothesis:   the "Pre-registered reads" block reads the bespoke script and nothing else, so a gate whose
                population has all but stopped is printed as INSUFFICIENT_N with a "30d ago" gate date — a
                reader-facing instruction to wait for a number that arrives in ~13 months.
                Evidence today: sheet prints "gate A n=32/60 ROI=-0.5173"; data/prereg-registry.jsonl grades
                entry-floor-a FROZEN (reads 20, hand_read n=31 ROI -55.18%, frozen_at 2026-10-17, gate
                2026-10-24). The ROI criterion (<= -20%) has been met on every read since #1; only n>=60 is
                unmet, and n moved 31 -> 32 in the 14 days since the last graded read (~0.07 legs/day).
  Measurement:  formatting only, in scripts/research-collect.py's gate block — print the registry row's
                state + reads + frozen_at BESIDE the live number, plus the projected n-arrival from the
                observed legs/day. No gate logic, no threshold, no lane, no read file touched.
  Decision rule: after 14 daily runs (by 2026-12-07) read logs/cron/copybot-research-bot.log: if >= 1
                FROZEN state is printed with its read count on every run AND no live number goes missing,
                keep it; if a run prints a frozen gate as pending or loses a live number, revert the block.
  Cost:         ~30 min, read-only. Lane B eligible (unfalsifiable probe: the probe cannot move and the
                sheet does not say so) — the parent session may execute it without an approval round.
  Reversibility: revert the print block; the registry file is untouched either way.
```
Touches `scripts/research-collect.py` only · card **`fact-sheet-gate-block-registry-state`** (added today, Backlog).

```
REC 2 — Stop paying for a dead practitioner lane: gate it off honestly, or move it to an app credential
  Hypothesis:   Reddit is hard-blocked from this host, so the three recon feeds can only ever return a stale
                cache; every run therefore reports 3 void blocks on a pipeline that is otherwise 15/15, and
                the reader cannot tell a real source failure from this permanent one.
                Evidence today (probes logged in the card): .rss 404 · old.reddit 302 · .json 403 ·
                api.pullpush.io 429 · rsshub.app 403. Caches 145-169 h. 7th consecutive day.
  Measurement:  (a) mark the three feeds `gated_off` in the collector with ONE notice line ("practitioner
                lane hard-blocked since 2026-11-19") and stop the 5-feed daily re-fetch; or (b) move the read
                to a Reddit app credential (OAuth) — the same credential card `reddit-intel-digest` already
                specifies. Both are Lane B; (b) is the only route that survives an anonymous-API block.
  Decision rule: after 14 runs: if `## Input health` reads >= 17/18 with the notice line present and no run
                prints a Reddit cache age, keep it; if any block that is NOT Reddit goes void/gated_off
                without its own line, revert. Reopen the block itself when a probe returns 200 with entries
                dated inside the 26 h TTL.
  Cost:         ~30 min (a) / ~2-3 h (b); zero lane risk, no key stored by an agent either way.
  Reversibility: delete the gate flag / the OAuth fetch; the block text is unchanged underneath.
```
Touches `scripts/research-collect.py` (recon block) · card **`research-recon-reddit-host-block`** (added today, Backlog).

```
REC 3 — Make the approval command incapable of dropping an ask
  Hypothesis:   `asset-queue.py approvals` defaults to `--limit 5` while the header prints the true count,
                so with 6 pending today it silently omits `polyrank/PolyRank-MCP` — the one item the previous
                weekly recommended approving. Any report generated by trusting the command loses that ask.
  Measurement:  print every pending item by default (or print "showing 5 of 6 — pass --limit 0 for all" when
                a limit is applied). Test: seed a 7-item fixture in a scratch copy and assert the item count
                printed equals the header count.
  Decision rule: at the next 4 weekly/daily reports: every pending item named in `status` appears in the
                report's ask section (count equality, not eyeball) AND the header's total is stated; if any
                item is missing while the header says it is pending, revert to the explicit `--limit` call.
  Cost:         ~10 min, read-only, no lane risk.
  Reversibility: restore the clamp; no queue record is written by listing.
```
Touches `scripts/asset-queue.py` (argparse default + one print) · no new card (it is a 10-minute repair with a 4-report decision rule, and carding it would duplicate `asset-queue-decay-and-atlas-diff`).

**Deliberately not proposed, with the number that closed each:** the maker/taker rebate ladder (`scripts/profit-wv-tier.py` priced it on this book today) · `minConfidence` (§3 fact 4: dust-free −$0.13/trade overall, −$3.14/trade on confidence-only rejects) · the short-TTR lane vs the main funnel (`drafts/ttr-floor-all-lane-basis-20261123.md`: **+7.65 %** lane vs **−26.92 %** main-funnel on the same 2–24 h markets — a size signal, Lane A, already carried by tuning Rec 1) · the fill-class basis (two `Scheduled` cards) · the $100 clip tier (card) · fee booking and the git ceiling (tuning Recs 2–4) · anything on drift, the bands, or the entry floor (settled).

---

## 5. Asset audits — awaiting your approval

**6 pending.** Ranked by expected value. Four have already been executed by other work; two are cheap live reads. **My read in brackets.**

1. **`polyrank/PolyRank-MCP`** · **watch** · audited 2026-11-16 · report `drafts/asset-audit-polyrank-mcp-20261116.md` · MIT · ★2 · **pending 7 days — and it is the item `approvals` truncates away today.**
   Rec: one keyless, read-only Spearman cross-check of our shrunk-arm wallet ordering against Polyrank's free-tier public rank, as a footnote in `drafts/wallet-rank-shadow-<date>.md`. No dependency, no lane input.
   Decision rule (verbatim): *Spearman rho ≥ 0.5 with market-clustered bootstrap 95 % CI excluding 0 ⇒ keep as a standing corroboration source and cite it in the shadow verdict; rho < 0.5 or CI straddles 0 ⇒ record "no external agreement" and drop the source.* Effort ~1–2 h read-only · reversibility: delete the footnote. **[approve]** → `approve polyrank/PolyRank-MCP`
2. **`YichengYang-Ethan/oracle3-prediction-market-agent`** · **watch** · audited 2026-11-13 · report `drafts/oracle3-reaudit-20261113.md` · pending 10 days.
   Rec: rebuild the ML-1 comparator as price + train-fitted isotonic in `scripts/ml1-gate-read.ts`, artifact only, **no BAR change**.
   Decision rule (verbatim): *if isotonic-price beats raw price by ≥ 0.002 Brier on the frozen ML-1 test legs, propose restating BAR as candidate-vs-price+isotonic and re-read the gate; else record raw price as defended.* Effort ~1 h read-only on `data/decision-dataset.csv`. **[approve]** → `approve YichengYang-Ethan/oracle3-prediction-market-agent`
3. **`lein3000zzz/polythought-go`** · **watch** · audited 2026-10-29 · report `drafts/asset-audit-polythought-go-20261029.md` · **pending 25 days, executed-unapproved since 10-29.**
   Rec: reimplement the donor's ~55-line book-walk taker fill as a read-only replay. **Run 2026-10-29: 268/381 = 70 % land ≤ 2 ¢ with a full fill → the rule fired PASS.** Nothing left to buy; the live consequence (maker-vs-taker on one population) is the 11-02 REC 1 that was never started. **[either]** — `approve` accepts the artifact, `decline` closes it; both are honest.
4. **`mirabilis-agent/lip-ledger`** · **watch** · audited 2026-11-03 · report `drafts/asset-audit-lip-ledger-20261103.md` · **pending 20 days — premise dead.**
   Its ask was answered better on 2026-11-09 by `scripts/lip-ledger.py`: **CLOSE, $0.000096/contract-hour vs the $0.0131 gate over 17,405 counted hours** (1/137th), and the card `lip-ledger-kalshi-reward` is Done. **[decline]** → `decline mirabilis-agent/lip-ledger`
5. **`kmasterfleek/kdreams`** · **watch** · audited 2026-11-07 · report `drafts/asset-audit-kdreams-20261107.md` · pending 16 days.
   Its registry + grader **shipped by another route** (`data/prereg-registry.jsonl`, 3 rows, grading entry-floor-a FROZEN); the donor's spec grammar was not used. Nothing to adopt. **[decline]** → `decline kmasterfleek/kdreams`
6. **`xyonium/reach-mcp`** · **watch** · audited 2026-10-23 · report `drafts/asset-audit-reach-mcp-20261023.md` · **pending 31 days (oldest, `stale` per the decay rule).**
   Its typed per-block input health **shipped**: today's `## Input health` header is that output (`ok/no_results/rate_limited/gated_off/void` + `factsheet-status.jsonl`). **[decline]** → `decline xyonium/reach-mcp`

**Shortest path if you want one line:** `approve polyrank/PolyRank-MCP` and `approve YichengYang-Ethan/oracle3-prediction-market-agent`, then `decline` the four superseded ones (3–6 above) — I will pass the exact calls to the parent session for `asset-queue.py decide`.

**Decisions log.** `data/research-asset-queue.json`: **25 items, 5 with a decision — all `approved`, newest 2026-10-26**; nothing decided since, so nothing to report for this week. Note how those five arrived: one was recorded same-day (DRADIS 10-15), and **four were backfilled by the research job on 10-22/10-26 because the queue was never updated** when you approved them in-thread. Their authorised work is still open — `mnemox-ai/tradememory-protocol` (deflated-Sharpe p on rule-selection trials v40–v64, report-line only), `vike-io/vike-data-cli` (**blocked on you** for the 37-day pre-recorder L2 window — no agent installs a client or stores a key), `crowdintel-xyz/polymarket-agent-kit` (q-gated wallet ranking with event-clustered n + BH-FDR). Two of the three are not waiting on evidence; they are waiting on execution.

---

## 6. Retro — the last four weeks

- **11-16 REC 1 — gate block reads the registry → STILL PENDING, 2nd week.** Today's sheet prints `INSUFFICIENT_N` while the registry has the row **FROZEN (20 reads, n=31, ROI −55.18 %)**. Carried as REC 1 and now carded; a recommendation that has survived two weeklies unexecuted is a queue defect, not a research one.
- **11-16 REC 2 — radar auto-commit/blob filter → STILL PENDING, 2nd week.** The yield line is unchanged (588 usable slots / 8.40 per run vs **10 leads added in 157 runs**), and today's newest-tooling page is five ★0 repos, four unlicensed.
- **10-26 REC 2 — prereg registry + grader → ADOPTED.** Its first act proved a gate dead: `entry-floor-a FROZEN`, and §3/REC 1 is the follow-through.
- **10-29 REC 1 — settled window ex-stock-clear → ADOPTED (10-30).** Live on the sheet: 30 d **n=728 −$1,116.95 = −$1.53/leg** ex-bulk vs **−$1.04 blended** — the 2026-11-04 stock-clear day is still distorting the blended line by ~50 %.
- **10-30 / 10-31 REC 1 — concentration line → ADOPTED (11-01).** Still earning its keep: this week the line reads 7 d **−$322.68** net but **−$463.15 ex-top-3** (sign agrees); last week the same line disagreed outright (**+$331.19** → **−$598.09**).
- **10-26 REC 1** (locate the <0.20 flow loss gate by gate, read due 11-09), **10-27 REC 1** (burst× band with wallet-clustered CIs, decision 11-03) and **10-22 REC 1** (v65 paired read on the closed 11-15 window; instrument exists, read not run) → **all three still unrun, 3rd–4th week past their own dates.** Three decision dates have now elapsed inside reports that said "pending".
- **11-02 REC 1 — maker vs taker on one population → PENDING, never started.** Unchanged from last week; its taker half is already PASSing (268/381 ≤ 2 ¢).
- **11-09 weekly → VOID** (`HTTP 402`), not quiet. Named so the record stays honest.
- **Audits, four weeks:** DRADIS **refuted** (n=62, −$0.33/leg) · lip-ledger **measured CLOSE** (1/137 of gate) · kdreams **superseded** · reach-mcp **superseded** · polythought-go **executed** (268/381) · PolyRank **pending** · oracle3 **pending** · sports-market-maker **dropped today**.
- **New this week — a question that closed itself, via an instrument rather than a report:** the minConfidence bar is now **defended dust-free** (§3 fact 4: −$0.13/trade overall, **−$3.14/trade** on the confidence-only rejects, n=127 marked). Same for the short-TTR lane question — `drafts/ttr-floor-all-lane-basis-20261123.md` read the two populations inside 2–24 h: **+7.65 %** (lane) vs **−26.92 %** (main funnel), which turns the TTR floor into a *size* question and is why I proposed nothing on it here.

**The pattern, stated plainly.** Every research item that has moved in four weeks was moved by a measurement someone *ran*; every item that has not is a paragraph with a date. Four of the six pending asks were already executed by another route, which means the queue's real function is now bookkeeping of decisions, not discovery.

---

## 7. Cards

- **`fact-sheet-gate-block-registry-state`** (Backlog, ~30 min, Lane B) — REC 1's tracking card; gate: 14 runs by 2026-12-07, state printed with read count on every run, no live number lost.
- **`research-recon-reddit-host-block`** (Backlog, ~30 min gate-off / ~2–3 h OAuth) — records the five probed surfaces, the two dispositions, and ties the OAuth route to the existing `reddit-intel-digest` card rather than opening a parallel one.
- **Not carded:** REC 3 (10-minute repair, 4-report decision rule) and the `ccxt/ccxt` audit (the queue item **is** its tracker — `status: pending`, enqueued today).
- **Cards this report's facts touch, not by me:** `apr-ladder-credit-positions-only` (§3 fact 2: current windows are already all-filled — its remaining scope is the lifetime quote), `profit-c200-clip-cap-25` and `profit-fill-class-basis` (§3 fact 5 / fact 2), `fee-booking-net-ledger` (approved, blocked on a 3-day-stale capture), `git-backup-large-artifact-policy` (`.git` 3,533.7 MiB vs 2,048, +177.3 MB in one night).

---

*Nothing applied. No rule, size, threshold, config or lane was touched. Writes this run: this draft and the two cards named above; one queue addition (`ccxt/ccxt`, pending for the audit worker). Read-only probes in `/tmp` and `~/.hermes/cache/scratch/`.*
