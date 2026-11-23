# Profit research — 2026-11-23

http://localhost:3013/drafts/profit-research-20261123

**Instruments (committed with this doc):** `scripts/profit-path-research.py` (re-run, no edit),
`scripts/profit-pm-liq-rewards.py` (**new today** — first measurement of Polymarket's own liquidity-reward
pool on our universe), `scripts/lip-ledger.py --fetch`. Every number below prints from one of those runs.

**Basis, once for the whole doc.** cost = `PaperTrade.simulatedPositionSize` (**dollars at risk**, not
notional); PnL = `realizedPnl` where `status IN ('closed','resolved')` (**TR-15 OR**, `closed` = early
exit, `resolved` = natural); `isDemo=0`; dedupe = first leg per (botId, wallet, marketId, outcome);
clock = **entry vintage** (`openedAt`), never settlement date; CI = **market-clustered** bootstrap,
2,000 draws (resamples markets, not legs). Label = `realizedPnl > 0` — a PnL label, not the market outcome.

---

## The finding

**The fill-confirmed book with the $100 tier removed is now exactly flat.** Four newly-settled legs
turned the ex-$100 class from −6.3% to **+$0.77 on $2,506 at risk (0.0%, CI [−23.8, +27.9])** — and all
**−$709.08** of the filled loss sits in **22 clips of $100**, every one of them inside the **0.00–0.20**
band that has had an approved $25 cap since 2026-11-11.

That is not a new edge. It is the same statement made sharper by one day of settlement: the only
provable loss left in the book is a sizing decision the user already approved, and the code that would
enforce it **still has no reader** (`grep -rn c200BandClipCaps src/` → nothing; RuleSet v73 is active and
its JSON does not contain the field, confirmed `grep -c` = 0). Twelve days, one field, one clamp call.

| cell | legs | $ risk | PnL | ROI (CI) |
|---|---:|---:|---:|---|
| filled, all | 306 | $4,706 | −$709 | −15.1% [−47.3, +26.3] |
| filled ex-$100 | 284 | $2,506 | **+$0.77** | 0.0% [−23.8, +27.9] |
| $100 clip | 22 | $2,200 | −$709.85 | −32.3% |
| → of which entry < 0.20 | 22 | $2,200 | −$709.85 | 100% of the tier |

Win rate on the clip tier: **9.1% against its own 14.3% break-even**. Ex-top-3 it is −$1,757.03
(−79.9%) — the two winners do not carry the tier, they mask it.

Delta vs yesterday: n 302→306, +$49.83 at risk, **+$156.04 PnL** on four legs. That is one leg's worth of
variance, not a trend; the tier and the vertical split are materially unchanged.

**By vertical (fill-confirmed, unchanged from prior runs):** question 55 legs −50.4% CI [−73.3, −17.3];
esports 67 legs −56.9% CI [−79.5, −21.9]; sports 117 legs +101.3% CI [−16.1, +210.6], **ex-top-3 −9.2%** —
the sports cell is a tail, not a class. Two cells have CIs excluding zero and both are negative.

**Coverage, the reason the aggregate is still fragile:** C-200 936/2,983 settled (31.4% adjudicated);
STANDARD **0/10,047 (0.0%, seventh day)**. Today's STANDARD stamp ran at 13:02Z with **162 legs in
scope** (157 yesterday) — advancing ~5 legs/day, still not merged into `fillStatus`.

---

## Progress on the five approved items

- **Item 1 (maker conversion): no writer, day 6 of a 30-day refutation clock.** The only maker shadow on
  disk is `kalshi-maker-shadow-sim.py` — different venue, different population. The card's refutation is
  *"failing to reach 200 shadow legs in 30 days"*, which **fires by inaction on 2026-12-17** if nothing
  ships. A time-based refutation against an unbuilt instrument is not a measurement; it is a deadline.
  *(The 07:40 review's tape-touch arm — 100% of resolver-`filled` legs touched ≤1h, 93.7% of `null` —
  is a reachability read, not a resting-order shadow; it does not discharge this item.)*
- **Item 2 (STANDARD / question adjudication): NOT DECIDABLE.** On the tick-aligned arm the gate reads
  51.7% (46/89) against a 60% bar at **73.0% coverage** of the adjudicable universe (89/122); the ≥90%
  coverage bar is the blocker, not the point estimate (`drafts/profit-item2-question-gate-basis-20261123.md`,
  instrument `scripts/profit-question-fill-read.py`).
- **Item 3 ($100 clip cap): approved 2026-11-11, never applied, no reader.** Forward cohort since
  approval: **9 legs opened at $100, 7 settled, $900 at risk, −$500, 0 wins**. The pre-registered
  refutation (a forward 40-leg $100 sample earning ≥ the sub-$40 tiers) has not fired — it is at 7 of 40,
  losing. The tier is now the entire filled loss, so the cap's value is no longer marginal.
- **Item 4 (ML re-point): no shipped change.** The Kalshi arb lane remains CLOSED (pre-registered
  refutation, 2026-10-22); the observe lane is unchanged. Nothing new to say until a fill-probability
  arm exists.
- **Item 5 (LIP): CLOSE.** Re-read to exhaustion: feed 231,937 usable programs, 75,909 above gate (32.7%,
  all ≤2h families — 74,972 of 92,082 in that bucket, 0 of 59,380 in >48h); **0 of 526 programs on the
  351 tickers we quote** clear the gate; measured net **+$0.0000892/contract-hour against $0.0131**
  (147x below).

---

## New external fact: Polymarket's liquidity-reward pool is live, and it is not where our flow is

We had only ever measured Kalshi's LIP and Polymarket's maker/taker rebate tiers. Polymarket also runs a
**separate per-market liquidity-reward program**, and it is paying: `GET clob.polymarket.com/sampling-markets`
(keyless) lists **8,030 markets, 7,873 with a USDC daily rate, $131,739/day published** (median $3/day,
p90 $24, max $1,556) — 2026-11-23. Third-party count for 2026-11-22: $66,933/day across 7,913 markets
([predictionscout.com](https://predictionscout.com/research/prediction-market-maker-incentives/), updated
2026-11-22); my sum is 2x theirs, consistent with counting *all* published rates including holding
rewards, so treat the level as an upper bound and the join below as the usable result.

Measured on our own book (`scripts/profit-pm-liq-rewards.py`):

- **53 of 4,503** settled markets are reward-eligible (1.2%), carrying **$1,538 of $71,415 = 2.15%** of
  all-time at-risk.
- Last 30 days: **8 of 506 markets** (1.6%), **$628 of $12,315 = 5.1%** of risk.
- On those 53 cells the published ceiling is **$0.0125/share-hour median**, p90 $0.10, **26 of 53 above
  the $0.0131 gate**, and the median one-side capital to qualify is **$18**.

**Verdict: a real program, not a lane.** The ceiling is at the gate on half the eligible subset, but the
subset is 5% of our 30-day risk, competition share is unmeasurable from the endpoint, and the reward
requires resting orders — which is item 1's work, not a new workstream. The useful consequence is one
line in the maker shadow when it is built: record `rewards_daily_rate` and `min_size` at dispatch, so the
subsidy is priced on the legs that would earn it instead of discovered later. No rule change today.

Also noted, no action: **QCX / Polymarket US** amended its Market Liquidity Incentive Program effective
2026-11-18 (adds optional Max Spread, Minimum Volume Requirement and Reward Cap; raises max period,
target size and daily reward) — a different exchange, no listing set or tape on disk
([CFTC filing PMX-2026-70](https://www.cftc.gov/filings/orgrules/rules11032642175.pdf), 2026-11-03).

---

## Changelogs and community (negative result)

- **Polymarket changelog: no entry since 2026-11-20** (the fee/rebate repricing, already costed at
  +1.02pp of at-risk). `price-edge.ts:65` still hardcodes the pre-change 0.07/0.04 coefficients; unwired,
  so no decision risk, Lane A proposal stands.
- **Kalshi changelog: top batch 2026-11-26** (10 entries) is RFQ / on-request-market plumbing — concert
  resolution rules, per-account market-creation limits, `historical/fills` accepting 100 tickers,
  `side` validation, Margin exit-trigger codes, weather-market time zones. **No fee, incentive or
  liquidity change.**
- **arXiv:** newest prediction-market paper remains ForecastGym (2026-11-17); q-fin.TR newest 2026-11-19
  (`Trading Before a Committed Rebalance`). Nothing on fill/adverse-selection microstructures since.
- **GitHub:** the `polymarket OR kalshi` recent-updated set is all no-licence paper-trading ledgers —
  read-only at best, nothing to adopt.
- **Reddit: unsampled fifth consecutive day.** r/Polymarket `.rss` returns a 404 feed, r/Kalshi returns
  a Blocked interstitial. Community change detection is blind; no forum claim was used, and none could be.

---

## Ranking (what I would do, in order)

**1 — Ship the approved $25 cheap-band cap (+$31/day, 1h).** Not a new proposal: the approval exists
(2026-11-11), the field exists (`c200BandClipCaps`), the only missing piece is the reader and one clamp
call in `openPaperTrade`, plus `apply-v73 --yes`. Today's measurement raises the stakes rather than
changing the case: with the tier at 100% of the filled loss, the cap is the difference between −15.1% and
break-even on the only class we can prove. Refutation unchanged (forward 40 clipped cheap-band legs at
tape-touch ROI ≥ +10%, or a 30-day capped-vs-uncapped underperformance ≥ $150 with CI excluding zero).

**2 — Build the item-1 shadow writer, or accept its refutation on 2026-12-17.** One of the two. The
clock is running against an instrument that does not exist, so the current default outcome is a
"refuted" verdict that measures nothing. If built, record reward eligibility alongside the touch
(above). Refutation stays as written (200 legs / 30 days).

**3 — Nothing else.** Item 2 is blocked on coverage (73% vs 90%), item 4 has no arm to ship, item 5 is
closed, and the Polymarket reward pool touches 5% of flow. Any fourth lever today would be work
manufactured to fill the report.

---

## Reproduce

```bash
python3 scripts/profit-path-research.py                 # filled n=306, -15.1%, ex-$100 +$0.77
python3 scripts/profit-pm-liq-rewards.py                # reward pool vs our universe (new)
python3 scripts/lip-ledger.py --fetch                   # 0 of 526 quoted programs above gate
grep -rn c200BandClipCaps src/                          # (nothing) — approved cap has no reader
sqlite3 prisma/dev.db "SELECT rulesJson FROM RuleSet WHERE active=1;" | grep -c c200BandClipCaps   # 0
```

**Lane policy:** read-only today — one new instrument, one existing instrument re-run, no RuleSet write,
no prisma write (DB opened `mode=ro`). Items 1 and 3 change what the bot risks; both already carry
approval, so the remaining step is code, not a decision.
