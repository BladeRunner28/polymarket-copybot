# Profit research 2026-11-19 — the profit vintage is the one that can never be checked

http://localhost:3013/drafts/profit-research-20261119

**Instruments:** `scripts/profit-path-research.py` (extended today: band CIs, adjudicability ceiling, booking-vs-verdict order) + `scripts/adjudicability-probe.py` (**new**: book-at-dispatch reachability per vintage) + `scripts/lip-ledger.py --fetch`. DB opened `mode=ro`.
**Basis:** cost = `simulatedPositionSize` (dollars at risk); PnL = `realizedPnl`, `status IN ('closed','resolved')` (TR-15 OR); `isDemo=0`; dedupe = first leg per (botId, wallet, market, outcome); clock = entry vintage; CI = market-clustered bootstrap (resample markets).
**Lane:** measurement + Lane B instrument only. No RuleSet read or write, no prisma write, no apply-v*.ts.

---

## Verdict in one line

**Fill adjudication has hit its ceiling and cannot settle the profit question: the C-200 Sep question vintage carries $5,055 of the $6,076 question profit and has a book at dispatch for only 16.5% of its legs (73.9% sit on markets the recorder never mapped), while the one vintage that is 100% adjudicated reads −$566, with its filled half at −55%.**

---

## 1. Fresh numbers (deltas vs 2026-11-18, same basis)

- Fill-confirmed: **n=282** (was 280), $4,344 at risk, **−$931, −21.4%**, CI **[−55.7, +22.0]** — still spans zero. Two legs settled (+$6.05 sports, −$20 dota2).
- All settled: 5,919 legs, $69,696, **+$7,086 (+10.2%)** — unchanged shape.
- **$100 clip: 21 legs, $2,100, −$610, −29.0%; ex-top-3 −$1,657 (−78.9%).** Carries **65%** of the filled loss.
- Vertical (filled): question −57.9% [−77.3,−31.6] · esports −60.5% [−81.5,−26.5] · other −53.0% · sports +114.1% [−23.9,+233.3], **ex-top-3 −26.2%**.
- Coverage: C-200 827/2,874 (28.8%, 100%/day since 11-09); **STANDARD 0/10,030**.

**New today — the filled class is not uniform.** First CI on every band cell: only one cell is distinguishable from zero, and it is not the $100 tier by itself.

- `0.00–0.10`: **15 legs, $805, −97.7%, 0/15 wins, CI [−100.0, −92.8]**, ex-top-3 −93.1%
- `0.10–0.20`: 29 legs, −5.5% [−84.0,+93.6], ex-top-3 **−73.0%**
- `0.20–0.60`: 189 legs, −6.3% / +19.1% (both CIs span zero)
- Composition of the penny cell: **6 are $100 clips ($600, −100%), 9 are ordinary clips ($205, −91%)** — so the penny band is a losing *price* class, not only a sizing defect.

## 2. The finding — profit and proof never coexist in the same vintage

`adjudicability-probe.py` asks the only question that matters for item 2: does the recorder even HAVE a book at the decision timestamp? (Book at dispatch is necessary, never sufficient.)

**Sep 2026, C-200 question vintage — 605 legs, $6,819 at risk, +$5,055:**

- book at dispatch: **100 legs (16.5%)**, $1,576, +$1,429 — of which the 6 already-filled legs are **−$120**
- no book in window: 58 legs (9.6%), $958, +$1,593
- **market never mapped by the recorder: 447 legs (73.9%), $4,285, +$2,032** — permanently unprovable

**Oct–Nov 2026, C-200 question — the fully-adjudicated control: 99 legs, 100% mapped, 100% adjudicated.**

- total **−$566**; filled **48 legs, $1,383, −$761 (−55.0%)**; unfilled +$194

So the question vertical's +$6,076 splits into a vintage we can never check (Sep, +$5,055, 16.5% reachable) and a vintage that is fully checked and loses (−$566). The book-level ceiling table says the same: post-epoch question legs are 34.6% mapped / 10.5% adjudicated, against sports at 84.4% / 51.0%.

**STANDARD's entire adjudicable book is 249 legs / $3,048** (Oct+; 81.7% book coverage). Merging the daily stamp (145 in scope, 143 stamped, 98.6% book) cannot move the profit question — it covers $3k of a $69.7k book.

## 3. The measured window is still not a book result

Order matters: the fill-aware path zeroes a leg only when the verdict exists **at booking time**.

| vintage | class | legs | PnL | of which verdict-after-booking |
|---|---|---|---|---|
| oct+ | filled | 247 | −$867 | n=166, +$78 |
| oct+ | unfilled | 474 | **+$1,418** | **n=312, +$1,418** |
| pre-oct | unfilled | 64 | +$851 | n=64, +$851 |

**Every dollar booked on an unfilled leg arrived after the booking.** Re-book those 313 legs at 0 and the oct+ window goes **+$551 → −$867** (filled only, −21.3% on $4,079 — the same −21.4% the all-time filled class prints). All-time the restatement is **+$7,086 → +$4,817**.

This is the mechanism behind the central finding, now localised to a column: `fillStatus='unfilled'` and `realizedPnl≠0` coexist on 538 legs, and the ordering proves the ledger never saw the verdict.

## 4. The approved cap is unapplied and still billing

Approved 2026-11-12 (band-scoped, $25 on 0.00–0.20); `apply-v73` never run, and v73 does not carry the field. Since approval, C-200's **filled** book is 22 legs / −$536 — of which the **$100 tier is 4 legs, $400, −100%** (all inside the cap's own band: 0.143/0.163/0.191/0.193). Sub-$18 in the same window: 16 legs, −46%. The card's refutation (a forward 40-leg $100 sample beating the sub-$40 tiers) has 4 of 40 legs and reads −100% vs −51%.

## 5. Approved-path deltas

1. **Maker-vs-taker shadow — CLOSED (measured 11-18).** Maker −6.1% vs taker −6.8% per intent-dollar (+0.7pp); the rule required ≥5pp on ≥200 legs. Do not re-open without a new mechanism.
2. **STANDARD adjudication — instrument runs, book unmoved.** Stamp 145 in scope / 143 stamped (98.6% book) / 0 merged; STANDARD `fillStatus` still 0/10,030. New: its reachable ceiling is 249 legs, $3,048.
3. **$100 clip cap — unapplied; $400 of new provable loss since approval** (§4).
4. **ML re-point — in progress** (`ml-u1-conditional-fill-model`: p(fill | band, hour, size, ttr) + adverse-selection markout). No delta required today.
5. **LIP — re-read, still empty, now answerable forward.** Live menu **0 of 9,503** above the $0.0131 gate (max ceiling 0.003529); measured net **+0.0000902/contract-hour** (145x below). New endpoint (below) shows **0 of 671 recurring schedules** above gate, max 0.002976 — **4.4x below** even at 100% pool share.

## 6. External (citations)

- **Polymarket changelog, 2026-11-16** — taker-fee repricing **effective 2026-11-20 23:59 UTC (tomorrow)**: maker rebates move from market-wide pools to 3/7/10/15% of generated taker fees; geopolitics stays free. `src/lib/scoring/price-edge.ts:65` still hardcodes 0.07 crypto / 0.04 politics; reachable from the live fee path via `src/lib/fee.ts:86` (proxy fallback only — `venue` schedule wins when present). https://docs.polymarket.com/changelog.md
- **Polymarket changelog, 2026-11-02** — Data API v1 retired. Verified live today: `GET /v1/leaderboard` → **410 `Data API v1 has been retired`**, `/v2/leaderboard` → 200. Our adapter defaults to v2 (`apiV2()`), so **no live break**; the v1 branch at `adapters/polymarket.ts:262` is now dead code that throws if `DATA_API_VERSION=v1` is ever set. Lane B note only, not fixed (no decision or risk change).
- **Polymarket changelog, 2026-11-11** — CLOB deprecations effective **2026-12-14** (`associate_trades`, `/data/orders` asset_id needs `market`, `/orders` loses asset_id filter). Grepped: **we call none of them** → no action.
- **Polymarket changelog, 2026-11-16** — PolyBolt price subscriptions require an explicit provider and a Chainlink key from **2026-11-30**. `record-l2.ts` uses the CLOB market socket (`ws-subscriptions-clob`), not PolyBolt → no action.
- **Kalshi changelog, 2026-11-19** — **new keyless `GET /incentive_schedules`**: recurring incentives — reward per window (centi-cents, same unit as `period_reward`), window length, `ends`, `all_markets` promise flag. 671 schedules on the wire today: **all liquidity, 0 promised, 0 above the $0.0131 gate, max ceiling $0.002976**; **no sub-day window except 15 one-day series**, and none of the families that historically paid (KXCRYPTOLEAD15M / KXTTELITEMATCH / KXTEMPMIAH) appear. This converts "nothing is live" into "nothing is scheduled". https://docs.kalshi.com/changelog (response parsed against `openapi.yaml` → `IncentiveSchedule.reward` = centi-cents).
- **arXiv 2611.05218 (2026-11-18), "Beyond Anonymous Order Flow: Wallet Identity as a Feature for Short-Horizon Return Prediction"** — Hyperliquid L4, 17.1bn messages / 147k wallets / $84.3bn taker notional; wallet-identity features add ~1.1pp R² on 1-second returns and **3.11 bps** top-ventile 10-second markout. Transfer review fails on cost: 3.11 bps = 0.031% against our 2.8–3.6% per dollars at risk on Polymarket (fee + spread). Hypothesis only; not an import. https://arxiv.org/abs/2611.05218
- **GitHub (search, 2026-11-19)** — no transferable tooling: the recent Kalshi/Polymarket repos are no-licence hobby ledgers and dashboards (read-only at best). `Szarbon/mogbot-clob-data` is a second public 5-min-crypto CLOB tape; our loss is not in 5-min crypto, so no use.
- **Forums unreachable this run** — Reddit serves 429 / a "Welcome to Reddit" interstitial to `.rss` and to `old.reddit.com` from this host. Recorded as a gap, not as evidence.

## 7. Ranking (what to do, in order)

**1. Execute the approved $25 cap on C-200 0.00–0.20 (Lane A, approved 11-12 — this is the only action that stops a measured bleed).**
- Hypothesis: the $100 clip at ≤0.20 is a full-loss generator, not a lottery ticket worth its variance.
- Measurement: filled $100 tier since approval = 4 legs, $400, −100%; sub-$40 same window −51%.
- Before/after: filled $100 tier −$610 on $2,100 → **−$152 on $525** (linear stake, same prices) = **+$457** on the filled class alone; live rate of loss **$57/day**.
- Decision rule: ship when the forward $100 tier underperforms sub-$40 on ≥20 legs (now 4/20, −100% vs −51%).
- Refuted by: 40 forward $100-tier legs earning ≥ the sub-$40 tiers — then the tier is a variance play and the cap is wrong.
- Remaining work is code, not approval: the field is inert without the four call-site edits in the card's §5.2 (`Rules` interface, `DEFAULT_RULES`, `band-size.ts` min-only helper, `openPaperTrade` call site, `score-trades.ts` pass-through). Do not write the RuleSet field alone.

**2. Re-book verdict-after-booking legs at 0, and only then trust any PnL-derived gate (Lane A).**
- Hypothesis: the oct+ window's positive sign is booking order, not fills.
- Measurement: §3 — 313 legs, +$1,446 (dedupe-free) / +$1,418 (dedupe), all verdict-after-booking.
- Before/after: oct+ window **+$551 → −$867**; all-time **+$7,086 → +$4,817**; netWorth → exposure cap → drawdown gate → the ladder's settled-7d advance all move with it.
- Decision rule: re-book when >300 unfilled legs carry PnL whose verdict stamp postdates the booking.
- Refuted by: a re-book that moves no published figure by >$50 or flips no gate — then the ordering is cosmetic and this closes.

**3. Close approved item 2 as an adjudication programme; keep it as a forward-only instrument.**
- The Sep question vintage — 83% of the question profit — is 16.5% reachable and 73.9% never-mapped; STANDARD's whole adjudicable book is $3,048. The ≥60% decision rule the item was written with cannot be met by construction.
- Refuted by: a mapping backfill that puts books at dispatch behind >50% of the Sep question markets — which the recorder's own map says does not exist (447 of 605 legs unmapped). Structural, not pending.

**4. Keep item 1 closed; do not reopen maker conversion.** It was measured and failed its own rule by 4.3pp.

**5. LIP: closed, and now closed looking forward.** 0 of 9,503 live + 0 of 671 scheduled, best scheduled ceiling 4.4x below gate. The only thing worth building is a watch on `/incentive_schedules` so a returning ⩽2h family is seen the day it posts — 30 lines in `lip-ledger.py`, no capital.

## 8. What this does not mean

- **Not "the fills are proven to lose −21%".** CI [−55.7,+22.0] spans zero. What is now distinguishable from zero is narrower: the sub-0.10 price cell (15 legs, [−100,−92.8]) and, on yesterday's cut, question and esports.
- **Not a licence to stop adjudicating C-200.** Daily coverage is 100% and stays; what closes is the hope that adjudicating *more of the past* settles the profit claim.
- **The unrealised book is unchanged by this read** (384 legs, $4,211, −$227 marked) — nothing here touches exits.
