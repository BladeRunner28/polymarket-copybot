# Polycopy.app — research review & account evaluation (2026-09-23)

Source scraped: `https://polycopy.app/research` (+ `/copy-score`, `/trader-data`, `/pricing`, `/polymarket-smart-money-index`, `/export-polymarket-trades`).
Method: server-rendered HTML pulled with curl and text-extracted; no account, no login wall hit. Vendor content treated as **untrusted marketing until reproduced on our own data**.

---

## 1. What the site is

A third-party Polymarket copy-trading product (verified member of the Polymarket Builders Program, not affiliated with Polymarket). Two revenue surfaces:

- **Free** ($0): full real-time trade feed, Copy Score on every trader, portfolio tracking, manual copy trading, up to 10 paper-trading bots (7–14 day runs), trader search/filters, wallet trade-history CSV export.
- **Premium** ($30/mo): live execution only — live Auto Copy bots, one-click trade execution, Fire Feed, wallet connection, position-sizing/risk controls, priority support. Plus a flat **0.5% builder fee** on every order executed through them (both tiers, real trades only).

Data claims: 1,637,015,470 trades rebuilt · 2,598,463 markets classified · 3,052,840 wallets seen on-chain · 4,373 wallets measured · 3,687 published · 126 indicators per trader · 2,179 days with no gaps.

## 2. The research library — two reports, two credibility tiers

### A. "Polymarket's Best Traders Are Profitable. Copying Them Isn't." (Sep 8 2026) — **rigorous, worth reading in full**

Screens the top 100 of **both** Polymarket profit leaderboards (all-time and 30-day) through "Copy Score": a trader's trailing-90-day **resolved** positions, shrunk toward a prior, minus an assumed cost of copying (worse entry + fees; slippage term averaged from their own bot fills). Classifier `clf_v14`, frozen snapshot, every figure re-derivable.

- Median **edge** (shrunk, per position): **1.39%** (30-day board) / **2.07%** (all-time).
- Median modeled **cost of copying**: **4.12%** / **3.51%**. Cost is the bigger number on both boards.
- **77% come out negative** after copy costs: 63 of 82 measurable (30-day), 46 of 60 (all-time) — two boards that share only **6 wallets out of 100**.
- **Rank is uninformative:** first clean passer sits at **#9** (30-day) / **#30** (all-time). **4 of the 14** passers had dropped out of both top 100s a day later.
- **Only 18 of 100** wallets carry any exclusion flag (MM / arbitrage / HFT) — so most of what fails is *ordinary traders with thin margins*, not machines.
- **21 of 200** slots cleared their costs; **all 14** on the 30-day board are "Ahead" (barely), **none** "Proven". One clears by 0.1%.
- Dormancy: **66 of 97** all-time wallets placed no trades in the 30 days before measurement.
- Record depth: 12 of 88 (30-day) vs **34 of 65** (all-time) flagged *thin*. Shrinking matters: all-time median raw per-position return 10.52% → shrunk 2.07%.

### B. "The State of Copy Trading on Polymarket: Q1 2026" (Apr 15 2026) — **marketing-grade, treat as hypotheses only**

No dataset, no method, no reproducibility — read the claims as prompts for tests, not as facts.

- Most-copied 50 wallets: 52.3% win / 3.1% ROI vs "rarely copied" tier 56.1% / 11.4% (+8.3pp ROI).
- **Category concentration** was the strongest predictor: 80%+ of volume in one category → 58.2% win vs 51.1% for 4+ categories (**+7.1pp**).
- NBA Over/Under specialists: 71% win, **+18pp above the category average**; weather markets show almost no specialization edge.
- Copy Score ≥85 in NBA O/U: 73% win — ~29pp above low-scored trades in the same category; weather gap only 8pp.
- Speed: "auto" (<30s) 57.8% vs manual 53.2% (**+4.6pp**), manual median delay **4.2 min**.
- Sizing: <2% of capital → Sharpe **1.42**, max DD **−8.3%**; >10% → Sharpe 0.64, DD **−38.5%** (win rates nearly identical — the difference is what you lose when wrong).

## 3. What is mapped onto our stack, and what to test

| Their finding | Our machinery | Falsifiable test on our data |
|---|---|---|
| Copy cost 3.5–4.1% vs edge 1.4–2.1% | `price-edge.ts` taker-fee model (`rate·p·(1−p)`, cat. rates) + spread/drift gates; draft `c200-taker-fee-measurement-2026-09-09` | We already hold both prices per leg: `ObservedTrade.walletEntryPrice` vs `PaperTrade.entryPrice` — our measured copy cost is **−3.03% (C-200)** / **+0.84% (STANDARD)**; detected-vs-wallet gap **+1.27% / +1.06%** |
| Rank carries no information (first passer #9/#30; 4/14 gone in a day) | our universe comes from leaderboard scans, then top-25 by our own `globalScore` | Already consistent — but quantify: PnL by source rank decile vs by `globalScore` decile |
| Concentration beats breadth (+7.1pp; NBA +18pp) | `bestCategory` + `categoryFitScore` exist; C-200 category blacklist (`lol`, `cs2`) | Add a concentration metric (share of wallet volume in its top category) and relate it to our realized PnL per wallet — the axis we currently do not measure |
| Thin records are unreliable (34/65 flagged) | no explicit minimum-resolved-positions gate on wallet selection | PnL of legs from wallets with <N resolved positions vs ≥N |
| Dormancy: 66/97 stopped trading | hourly `scan:wallets` re-derives status; v61 `lastTrackedAt` window | Already covered — verify demoted wallets stop contributing copies (0 today) |
| Speed beats deliberation (+4.6pp; 4.2-min median manual delay) | 11.0 min median cycle; short-TTR lane; cadence axis currently QUIET | Counterfactual: our fill price vs the wallet's price **by detection lag** — do late-detected copies pay more? Directly testable |
| Sizing <2% of capital → Sharpe 1.42 vs 0.64 | exposure cap ($2,188 base +50% above principal), Kelly rails, v60 band half-size | We already size this way; our realized DD 0.2% — cite as corroboration, not as new evidence |

**Our own numbers for comparison** (as of 2026-09-23, paper lane, joined legs):

- C-200: 1,982 legs · mean (our entry − wallet fill)/wallet fill **−3.03%** · settled 1,958 → realized **+$2,417.00** on **$14,812.90** cost = **+16.3% of cost per position**.
- STANDARD: 9,863 legs · mean **+0.84%** · settled 8,566 → **+$8,949.69** on **$98,608.60** = **+9.08%**.

Our booked entry is `currentPrice` at scoring time (`scripts/score-trades.ts:1035`), which is *not* the detected price — so on C-200 the fill model lands ~3% below the wallet's own fill (the sign a real copier would never see), while STANDARD lands ~0.8% above (the expected adverse direction). Our +16%/+9% per position against their 1.4–2.1% median edge is therefore mostly **fill model + short sample**, not demonstrated alpha. This is the strongest reason to adopt their framing: **quote edge and copy cost as two separate numbers, and make the cost term the one we can defend.**

## 4. Account evaluation

**Free account — yes, for three bounded uses.**
1. **Benchmark our wallet selection.** Copy Score is free on every trader and is built for the same question our `globalScore` answers ("is this record worth following after costs?"). Comparing the two rankings on our own 3,243-wallet universe is an independent oracle for our selection quality — the thing we have never had.
2. **Wallet CSV export** (`/export-polymarket-trades`): paste any public wallet → per-fill CSV (`timestamp_utc, type, market_title, market_slug, condition_id, outcome, side, shares, price, usd_size, cash_flow_usd, transaction_hash`), free preview, download needs a free account. Useful for **spot backfill and validation of individual wallets** and for reconstructing a wallet's history without our data-api path (where 429s are the recurring cost).
3. **The 126-indicator checklist** is a free feature spec for our own wallet profile — we already compute many of them; the gaps (concentration, hold time, exit route, sizing consistency, maker/taker mix) are cheap additions.

**Premium ($30/mo + 0.5% fee) — no.** It buys live execution through their platform. Our system is paper-only by construction (SAFETY.md: no keys, no real orders, no wallet connection), the Oct 8 Kelly read is the live-lane gate, and the Go-live anchor is 2027-01-02. Buying an execution path now would add a third-party order flow we cannot reconcile against our own ledger, and the 0.5% builder fee is a direct drag on exactly the copy-cost term this research says is already too high. Revisit only after go-live, and only as a venue question.

**Integration limits (the important one).** There is **no public developer API** for trader-level data or Copy Score — the only published, free, keyless endpoint is the Smart Money Index:
- `GET /api/indexes/smi/public` → today's score/zone (2026-09-22: **65 ACTIVE**, methodology 2.0.0)
- `GET /api/indexes/smi/history[?format=csv]` → 57 daily rows (from 2026-07-28) with components momentum/breadth/participation/conviction, `maxFreeDepthMonths: 24`, attribution required

Their `robots.txt` disallows `/api/` generally, so those two advertised endpoints are the sanctioned ones — do not scrape the rest. Everything else (Copy Score, trader profiles, feed) is UI-only, so an account gives you a *manual/spot* research surface, not an automated feed. Any attempt to drive the export at scanner scale is a scraping operation against a product we do not own — out of bounds.

## 5. Verdict

- **Research value: real, and directly on our problem.** Their Sep-8 report is the first external analysis I've found that formalises the thing our gates approximate — that copying fails on cost, not on trader quality — and it publishes its method, its limits, and the names that passed. The Q1 report is marketing but carries four testable hypotheses (concentration, thin records, speed, sizing).
- **Sign up: free tier only.** No wallet connection, no Premium. Use it as a selection oracle + spot-export source.
- **Wire the PSMI free API in as a measurement first** (keyless, attribution): backfill the 57-day history, join it to our daily C-200 P&L, and see whether the index reads regime at all before it ever gates anything.
- **The highest-value follow-up is not their data — it's their framing applied to ours:** publish our own edge-vs-copy-cost pair (edge and cost, reported separately) so our daily report stops implicitly assuming a zero-cost fill.

*Nothing implemented. Recommendations only, per the standing rule; approval in-thread before any change.*
