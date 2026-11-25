# Profit research — 2026-11-25

http://localhost:3013/drafts/profit-research-20261125

**Instruments (both committed with this doc):** `scripts/profit-path-research.py` (unchanged, daily read)
and **`scripts/profit-clarification-read.py` (new today)**. Every figure below re-runs from one of them.
**Basis:** cost = `simulatedPositionSize` (dollars at risk, not notional); PnL = `realizedPnl`,
`status IN ('closed','resolved')` (TR-15 OR); `isDemo=0`; dedupe = first leg per
(bot, wallet, market, outcome); clock = entry vintage; CI = market-clustered bootstrap, 2,000 draws.

---

## Headline

**Polymarket's new settlement-clarification surface does not price a rule.** Markets whose rules were
clarified *after* we entered are the one population negative on both the booked and the stamped basis
(−9.6% on 141 legs, ex-top-3 −13.4%, win 53.9% vs break-even 61.4%) — but they are **2.3% of settled
dollars at risk**, their CI spans zero, and a perfect gate on them is worth at most **$160**. The corpus
is also not what its name suggests: 48.9% of the clarifications we pulled are "rules updated for clarity"
copyedits and 84.4% set `clearBook`, so the flag selects a *market family* (110 of 141 post-entry legs are
weather `highest`), not a settlement dispute.

The book itself is unchanged: **fill-confirmed −17.2% on n=315** ($4,826 at risk, −$828.71, CI
[−49.2, +23.8]), **86% of the loss is still the 22 $100 clips**.

---

## 1. Measure (today's numbers, not a re-derivation)

**Fill-confirmed, all settled, both lanes:**

- n=315 · $4,826 · **−$828.71 · −17.2%** · CI **[−49.2, +23.8]** · win 40.3% vs BE 47.1%
- ex-$100 clip: n=293 · $2,626 · **−$118.86 · −4.5%** · CI [−28.0, +23.1]
- Δ vs yesterday: **+7 legs, +$79.74 at risk, −$79.53 PnL** — and all seven new filled legs lost
  ≥99.5% of stake (C-200, $10–20 clips, entries 0.11–0.73). Nothing structural; the point estimate
  moved −15.8% → −17.2% because of them.

**The $100 tier (22 clips, 46% of filled at-risk):** $2,200 · **−$709.85 · −32.3%** · win 9.1% vs
BE 14.3% · ex-top-3 −$1,757 (−79.9%) · **85.7% of the filled loss**. Forward sample since the 11-11
approval (entry vintage, not settlement): **5 clips opened, $500, −$500, 0 wins** — 5 of the 40 the
refutation needs, most recent opened 11-21.

**Verticals, fill-confirmed:**

- question n=55 · $1,539 · **−$776 · −50.4%** · CI [−73.3, −17.3]
- esports n=67 · $1,293 · **−$736 · −56.9%** · CI [−79.5, −21.9]
- sports n=121 · $1,196 · +$1,091 · +91.2% · ex-top-3 **−14.8%** (three legs, not a vertical)
- other n=72 · $798 · −$407 · −51.0%

**Adjudication coverage (the constraint):**

- BANKROLL_200: **992 / 3,039 = 32.6%** all-time; 100% on every entry vintage since 11-17
- STANDARD: **0 / 10,056 = 0.0%**, eighth consecutive day
- standard stamp 13:26Z today: **171 legs booked-mid arm** (162 yesterday) of the 300 required;
  **tape arm 0** → item 2's refutation still **NOT EVALUABLE**

---

## 2. Approved path — deltas only

1. **Maker-vs-taker shadow: 0 legs, no writer.** Day 8 of the 30-day clock. No shadow-rest artefact
   exists; what has been measured (yesterday) is a retrospective reachability read, not a shadow arm.
2. **STANDARD fill adjudication:** stamp in-scope 171, book-stamped 171, **not merged** into
   `PaperTrade.fillStatus`. Gate (≥60% filled at non-negative ROI) still not decidable.
3. **$100 clip cap: day 14, zero at both ends.** `c200BandClipCaps` is **absent from the active
   RuleSet v73** (v73's only delta vs v72 was `maxConcurrentLongshotPctOfNetWorth`) *and* has **no
   reader in `src/`** (`grep -rn c200BandClipCaps src/` → nothing). The apply script exists and has
   never run. Forward sample 5/40 (entry vintage).
4. **ML objective re-point: not started.** The daily gate is still the outcome objective
   (price-only AUC 0.7292; no arm clears +0.0005); `ml-ledger.jsonl` (39 entries) has no
   fill/adverse-selection arm.
5. **Kalshi LIP: closed, and the ceiling fell again.** `lip-ledger.py --fetch` today: live menu
   **7,846 programs, 0 above $0.0131/contract-hour, max ceiling 0.002976** (0.00446 yesterday, so
   −33% in a day); our measured ceiling $0.001120 → **11.7× below the gate**. No action.

---

## 3. New today — the clarification probe

**What changed externally.** Polymarket published a keyless endpoint on 2026-11-25:
`GET gamma-api.polymarket.com/market-clarifications` — "the notes that resolve ambiguity in how a
market settles" (filterable by market/event/question/tx; no auth). That is a rules change that happens
*after* trading begins, i.e. exactly the class of information a copy trader cannot read at entry.

**Hypothesis.** Legs whose market received a clarification after our entry are adversely selected,
by enough to price a "no entry on clarified markets" gate.

**Measurement** (`scripts/profit-clarification-read.py`; join = PaperTrade.marketId → conditionId →
gamma id → clarifications; 4,563 markets mapped, 311 legs = 5.1% unmapped):

- The clarification corpus runs **2025-11-13 → 2026-11-25**, so it covers the whole book.
- **176 of 4,562 markets (3.9%)** carry ≥1 clarification; those markets hold **272 legs, $3,254
  (4.5% of risk) and $2,368 of the $7,366 booked PnL (32.1%)** — but ex-top-3 that edge is **+9.1%**,
  i.e. four legs, the largest a **+$1,513 unfilled** `will-alibaba…` NO at 0.06.
- **Split by timing is the real result:**
  - **after entry: n=141, $1,662, −$160, −9.6%, ex-top-3 −13.4%, win 53.9% vs BE 61.4%, CI [−26.2, +6.3]**
  - before entry: n=131, $1,592, +$2,528, +158.8%, ex-top-3 +28.6%, CI [−8.5, +367.9]
- Question only, post-entry: **n=132, −$179, −11.5%, ex-top-3 −15.6%, CI [−28.6, +5.2]**.
- **Fill-confirmed clarified legs: 3, −$6.15.** The flag cannot be read on the provable class at all.

**Transfer review (before any rule).** Population = markets with a published rules note, not markets
with a disputed settlement. Of the 180 clarifications pulled: **84.4% set `clearBook`, 48.9% are the
"rules have been updated for clarity" boilerplate**; 110 of the 141 post-entry legs are weather
`highest` (a STANDARD family where the note is boilerplate). Exclusion filters: none — this is the
whole settled book. Fill model: unresolved (3 filled legs). A population whose flag is a copyedit in
a high-frequency weather family does not describe anything the copy lane decides on.

**Decision rule (proposed, not shipped).** Build a clarification gate only if, together: ≥60
post-entry-clarified legs, market-clustered CI excluding zero, **and** a measured saving ≥ $500/30d.
**Refutation:** the cohort's whole loss is $160 — a perfect gate is worth ≤$160, 0.2% of at-risk and
2.2% of booked PnL. **Refuted today**; re-open only if the count triples and the CI excludes zero.

---

## 4. External sweep (everything cited, nothing imported)

- **Polymarket changelog, Nov 25 2026** — market-clarifications endpoint (above). Nov 20 fee/rebate
  changes were already booked on 11-20; **no new fee change today**.
  <https://docs.polymarket.com/changelog.md>
- **Kalshi changelog, Nov 26 (UTC-dated) entries** — all RFQ/margin/weather-authoring changes;
  **no fee, incentive or liquidity-program change**. One instrument-only fact: `GET /historical/fills`
  now takes **100 comma-separated tickers** per call (a tape-refresh speedup, not a decision change).
  <https://docs.kalshi.com/changelog>
- **Kalshi incentive_programs** — re-read, not assumed: 233,077 usable programs, 74,032 (31.8%)
  historically above gate — all in ≤2h windows (81.0% of ≤2h clear, 0.0% of >48h); live menu
  **0 of 7,846**. See §2.5.
- **Forums** — Reddit `.rss` and `old.reddit.com/.rss` both returned block pages today (HTTP 200 with
  a "Welcome to Reddit" shell / "Blocked"). **No forum evidence was available; none used.** This is a
  hole in today's coverage, not a null result.
- **arXiv q-fin.TR, newest 25 (2026-11-18 → 11-23)** — nothing on prediction-market microstructure or
  fills. One prediction-market paper (*Political Orientation and Participation in Prediction Markets*,
  2026-11-22) is about participation, not price; no transfer. No import.
  <http://export.arxiv.org/api/query?search_query=cat:q-fin.TR>
- **GitHub** — the recently-updated repos matching polymarket+kalshi are generic arb scanners; nothing
  on fill adjudication or queue position worth reading. No licence reviewed because nothing qualified.

---

## 5. Ranking — what to do (and what not to)

1. **Ship nothing new today. The clarification gate is refuted** (impact ceiling $160, flag is a
   copyedit). No predictor work is licensed while STANDARD is 0% adjudicated.
2. **The approved path has not moved and its largest item is at zero at both ends.** Item 3 is missing
   its field from the live RuleSet *and* its reader in `src/`; its approved $25 constant is also
   dominated by the $10 variant measured in this morning's review — that one decision is outstanding
   with the operator, and this run does not re-derive it.
3. **The measurements that would unlock something:**
   - STANDARD stamp **300 legs** (171 today, +9/day → ~14 days) → item 2 becomes decidable.
   - C-200 $100 forward sample **40 settled** (5 today, all losses) → item 3's refutation fires
     or closes.
   Neither is a build; both are clocks.

**If I am wrong:** the place to look is the +158.8% "clarification existed before entry" cohort. It is
one leg deep (ex-top-3 +28.6%) and unfilled, so it is the same phantom-profit story as the whole book —
but if a filled version of that cohort ever reaches 60 legs at a positive ex-top-3, the clarification
endpoint becomes an *entry filter in reverse* (prefer markets whose rules were already clarified).

---

## Reproduce

```bash
python3 scripts/profit-path-research.py          # §1 numbers, §2 coverage
python3 scripts/profit-clarification-read.py     # §3, caches under data/cache/gamma-*.json
python3 scripts/lip-ledger.py --fetch            # §2.5
```
