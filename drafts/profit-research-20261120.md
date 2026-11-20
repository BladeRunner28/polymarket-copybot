# Profit research 2026-11-20 — the venue's biggest fee change in this book's life is worth 1.0pp

http://localhost:3013/drafts/profit-research-20261120

**Instruments:** `scripts/profit-path-research.py` (unchanged, re-run) + `scripts/profit-fee-reprice-filled.py` (**new today**, `--selftest` 8/8, committed with this doc) + `scripts/lip-ledger.py --fetch`.
**Basis:** cost = `simulatedPositionSize` (dollars at risk); PnL = `realizedPnl`, `status IN ('closed','resolved')` (TR-15 OR); `isDemo=0`; dedupe = first leg per (bot|wallet|market|outcome); clock = entry vintage; CI = market-clustered bootstrap (resample markets). DB opened `mode=ro`. No RuleSet write, no prisma write, no `apply-v*.ts`.
**Lane:** measurement + external research only. Nothing applied.

---

## Verdict in one line

**The taker fee is 3.89% of every dollar-at-risk in the fill-confirmed book — a cost no published ROI in this repo includes — and tonight's repricing (the largest venue change since go-live) removes 1.02pp of it, moving the provable class from −25.68% to −24.66% net and flipping no cell; measured in dollars it is +$2.07/day against a book burning $31.70/day, so the ranking of levers does not change today.**

---

## 1. Fresh numbers (deltas vs 2026-11-19, same basis)

- Fill-confirmed: **n=283** (was 282), $4,364 at risk, **−$951, −21.8%**, CI **[−56.6, +21.8]** — still spans zero. One leg settled (−$20 dota2).
- ex-$100-clip: **−15.1%**, CI [−38.2, +11.5].
- **$100 clip: 21 legs, $2,100, −$610, −29.0%; ex-top-3 −$1,657 (−78.9%).** All **21 of 21** sit at entry < 0.20, so the approved cap's band contains 100% of the tier — no new information, but it removes the last "the cap misses half the tier" doubt.
- Vertical (filled): question **−57.9%** [−77.3,−31.6] · esports **−60.5%** [−81.5,−26.5] · other −54.4% · sports +114.1%, ex-top-3 **−26.2%**.
- Coverage: C-200 **832/2,880 (28.9%)**, 100%/day since 11-09; **STANDARD 0/10,035 (0.0%)**.

**One basis caveat, stated because it is material:** the sports cell is bucketing-sensitive. `profit-path-research.py`'s prefix set gives 105 filled sports legs at +114.1%; today's fee script uses a wider prefix set and gets **143 legs at +60.6%, ex-top-3 −36.1%**. Ex-top-3 is negative under both, so the class carries no claim either way — but any future "+114%" quote needs its prefix list beside it.

## 2. The finding — the fee is a 3.9% tax on the class we can prove, and today's repricing is a level shift

`profit-fee-reprice-filled.py` prices the fill-confirmed book on the venue's own law, `fee/shares = rate·p·(1−p)`, so **fee per dollar at risk = rate·(1−p)** — largest at cheap prices, ~0 near p=1. Exit fee is charged only where we actually sell (`status='closed'`), never on a resolution.

| book (n=283, $4,364) | ROI | fee $ | fee % of at-risk |
|---|---|---|---|
| gross (what every ROI published here reports) | −21.79% | — | — |
| net, schedule in force until tonight | **−25.68%** | $170 | 3.89% |
| net, schedule effective 23:59 UTC today | **−24.66%** | $125 | 2.87% |

The repricing is worth **+$44 on the whole book (+1.02pp)** and **+$2.07/day** at the measured 30-day intent rate of $390/day. The band and vertical sign table is empty: **no cell changes sign.** Worst-case mapping (treating every question market as an election, coefficient 0.05) costs a further 1.35pp and still changes no verdict.

Where the fee actually bites, by entry band — and why the only positive cells are the ones we barely fund:

- **0.00–0.10: −97.8% gross, −99.7% net**, fee $16 → 0/16 wins. Fee is 4.5% of at-risk at p=0.10.
- **0.20–0.40: −6.3% gross, −9.5% net** on **$1,304** — the largest filled cell by both legs (112) and dollars.
- **0.40–0.60: +19.1% gross, +16.5% net** — on **$98 of at-risk across 77 legs** ($1.27/leg).
- **0.60–0.80: +5.9% gross, +4.7% net** — on **$310**.

That is the central finding in fee terms: **90% of the provable dollars sit in cells that lose 6–98%, and the two cells that survive the fee carry $408 of $4,364.** The fee is not why the book loses; it is 3.9pp of a 21.8pp problem. But it also means the one lever the venue handed us today is small by construction: the rate only moves on the question/culture/econ/crypto classes, which are 34% of filled cost and already −58%.

## 3. Approved path — deltas only

1. **Maker-vs-taker shadow — CLOSED (11-18).** Maker −6.1% vs taker −6.8% per intent-dollar; the rule wanted ≥5pp on ≥200 legs. Nothing reopens it today; the repricing does not touch maker fees (makers still pay zero), so it does not create a new maker case.
2. **STANDARD adjudication — instrument ran, book unmoved.** Stamp at 06:26 today: 147 in scope, **144 book-stamped (98%)**, tape arm **0**, refutation **NOT EVALUABLE at 144 of the required 300 legs with a mid**. `fillStatus` still **0/10,035** (+5 legs since yesterday, none adjudicated). The reachable ceiling is unchanged: ~249 legs / $3,048 of a $69.7k book.
3. **$100 clip cap — unapplied, day 8.** The active RuleSet (v73) carries `c200BandSizeFactor 0.5` on 0.6–0.8 and `c200SkipBandRange 0.4-0.6` — verified from the live `rulesJson` — and **no clip field in the 0.00–0.20 band**. Forward refutation sample since approval: **4 of 40 legs, $400, −$400, 0 wins** (card `profit-band-clip-rebalance`, Scheduled).
4. **ML re-point — In Progress** (`ml-u1-conditional-fill-model`). No delta required.
5. **LIP — re-read, still zero.** Live menu (active+upcoming) **10,035 programs, 0 above the $0.0131 gate**, max ceiling **0.003529** (3.7x below). Measured net **+0.0000902/contract-hour** (145x below). Quote-universe overlap 351 tickers → 519 programs, **0 above gate**, max 0.001120. **CLOSE.**

## 4. External (URL + date on every claim)

- **Polymarket changelog — no new entry since 2026-11-16.** The fee page is now the authoritative table (retrieved 2026-11-20): `fee = shares × feeRate × price × (1−price)`, makers pay no platform fee, and the coefficients from 23:59 UTC tonight are **crypto BTC 5m/15m 0.05 · crypto other 0.01 · all sports 0.05 · finance 0.05 · tech 0.05 · politics-election 0.05 · politics-non-election 0.01 · economics/culture/weather/mentions 0.01 · geopolitics 0 · combos 0.05 · other 0.05**. https://docs.polymarket.com/programs/fee-and-rebate-changes-november-2026.md (page states effective Friday 2026-11-20 23:59 UTC).
- **Taker/maker rebate tiers same effective time:** sub-$200k 30-day weighted volume earns **0%**; maker rebates become 3/7/10/15% of the taker fees your fills generate. Our 30-day maker weighted volume is ~$7.4k — **27x below the first tier**, so rebates are $0 for us under either regime. Same URL.
- **`src/lib/scoring/price-edge.ts:65` still hardcodes the pre-change table** (crypto 0.07, politics/finance 0.04, default 0.05; last touched 2026-09-13). From tonight it **overcharges non-election politics by 4x** and **undercharges elections/finance/tech by 1pp**. It is `status:"shadow"` and reachable from the live path only through `fee.ts`'s proxy fallback, and `fee.ts` is explicitly NOT WIRED — so this is a **wrong published figure, not a wrong decision**. Lane A proposal stands (needs approval, before/after below).
- **Kalshi changelog — the 2026-11-19 batch adds `GET /incentive_schedules` (recurring windows, centi-cents) and `series_ticker`/`event_ticker` filters on `GET /incentive_programs`, plus `X-RateLimit-Reset`/`X-RateLimit-Cost` headers.** Nothing changes the liquidity economics; the schedule surface is already priced in §3.5 (0 of 671 forward schedules above gate, yesterday's read). Note the changelog's newest entries are dated 2026-11-26, i.e. ahead of today; treat undated reads as forward notices. https://docs.kalshi.com/changelog.md
- **Reddit — unreachable again today** (`r/algotrading` and `r/PredictionMarkets` `.rss` → **429**; `old.reddit.com/r/Polymarket/new/.rss` → "Welcome to Reddit" interstitial at HTTP 200). Recorded as a gap; community signal is not sampled. No forum claim is used anywhere in this doc.
- **arXiv q-fin.TR (retrieved 2026-11-20):** newest relevant submissions are 2026-11-19 "Trading Before a Committed Rebalance" and 2026-11-18 "Algorithmic Market Making Can Lead to Rough Volatility Through the Order Book" — neither is prediction-market, neither is an import. A separate `abs:"prediction market"` sweep returns nothing newer than 2026-11-17 (ForecastGym benchmark). No paper considered today meets the transfer test.
- **GitHub** (`q=polymarket OR kalshi`, sorted by updated): the 2026-11-20 results are three unlicensed `KalshiDash*` shells and one "new" repo; nothing with a licence, nothing with a fill model worth reading. Read-only at best.

## 5. Ranking — where money can be made, in $/day

1. **Band clip cap on C-200 0.00–0.20 (approved 11-12, unapplied).** Measured 11-20 07:48: **+$17.7/day** at the cell's low-clip rate, **+$34.2/day** at the tier's, **−$22.3/day** floor once ex-top-3. It is the only lever already approved and still billing.
2. **STANDARD's fill rate (92% vs C-200's 63%)** — **+$8.4/day** on 13% of intent. Unchanged; its EV is tape-owned, and its `fillStatus` adjudication is still 0%.
3. **The dear band 0.80–1.01** — **+$8.6/day**, the only positive CI in the cell table ([+10.6,+17.4], 16 legs). Underfunded at 14% of intent; fee there is ~0.5% of at-risk, the cheapest in the book.
4. **Tonight's fee repricing** — **+$2.07/day**, no sign flips, no new rule implied.
5. **Kalshi LIP** — **$0.00/day**. 0 of 10,035 live; the families that pay are ≤2h and absent.
6. **Maker conversion** — closed on measurement; rebate floor 27x away, so it was never a subsidy story.

## 6. What I would do, and what would refute it

**Nothing new ships today.** The one action is to **execute the cap that was approved eight days ago** (card `profit-band-clip-rebalance`) — it is the top of this ranking and the only item in it that needs no further measurement.

- **Decision rule:** apply `c200CapUsd 25` on entry band 0.00–0.20 (and lift 0.20–0.40 to $25, as the card specifies); hold the lift if the first 40 forward legs of the 0.20–0.40 band come in below the 0.00–0.20 band's rate.
- **Refuted by:** the forward $100-tier sample reaching 40 legs and earning **≥** the sub-$40 tiers (currently 4/40, −100% vs −51%), or the cap's band producing no measurable change in EV/intent over 60 legs.
- **Not recommended, and why:** any new predictor (the filled class has no positive cell with power), any Kalshi LIP build (0 of 10,035), any maker push (rebate floor 27x away, and maker only beat taker by 0.7pp).

**Negative result, stated plainly:** *no change is justified today beyond executing the approved cap.* The measurements that would unlock a new one: (a) the $100 tier's forward sample reaching 40 legs (36 to go); (b) STANDARD reaching 300 stamped legs with a mid, which is the only path to knowing whether its +12.9% is real; (c) the live LIP menu returning a ≤2h family with a ceiling ≥ $0.0131, which `lip-ledger.py --fetch` re-reads automatically.

## Reproduce

```
python3 scripts/profit-path-research.py            # §1 numbers, CIs, coverage
python3 scripts/profit-fee-reprice-filled.py       # §2 fee layer, selftest 8/8
python3 scripts/lip-ledger.py --fetch              # §3.5 LIP
```
