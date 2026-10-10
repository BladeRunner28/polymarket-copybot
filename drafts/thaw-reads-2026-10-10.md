# Freeze-thaw reads — 2026-10-10 (Kelly window closed 2026-10-08 23:59 UTC; freeze expired 10-09 05:00 UTC)

Every card below was held to the window close by the pre-registered freeze. All reads are
read-only; nothing here changes a rule, a size or a lane. Verdicts are stated per card, with the
pre-registered bar quoted, and each one is attributed to the window it was read on.

## 1. `change2-oct8-gates` — NO TRIGGER FIRES → no gate ships (card closes)

Pre-registered trigger (in-window only, decision-level/deduped): `|z| >= 2.0 AND realized PnL < 0 AND N >= 20`.
Command: `python3 scripts/analyze-change2-gates.py` (writes `data/change2-gates-since-2026-09-06.json`).

| candidate | deduped N | excess (z) | PnL | fires? |
|---|---|---|---|---|
| band 0.60–0.80 | 217 | −0.0866 (**z=−2.61**) | **+$31.55** | **no — PnL ≥ 0** |
| hour 08:00 ET | 8 | −0.1838 (z=−1.07) | −$2.01 | no — N and z |
| hour 00:00 ET | 47 | −0.0573 (z=−0.80) | −$89.35 | no — z |
| hour 01:00 ET | 37 | +0.0608 (z=+0.74) | −$32.20 | no — sign |

The 0.60–0.80 band passes the significance and the N tests and fails the cash test: the band's
excess is *negative* (−8.7pp, z=−2.61) while its realized PnL is **positive**. That is the same
shape v60 was applied for, and it is the second independent confirmation today that this band is a
zero-cash, negative-excess slice — not a bleed to gate on. Nothing ships.

## 2. `drift-gate-counterfactual` — read done, but the pre-registered bar is STRUCTURALLY DEAD

Gate text: *"Read `data/drift-shadow-summary.json` at the close; act only if the settled
would-have PnL is materially positive on a >=100-settled sample."*

Read (2026-10-10 07:35 UTC): **4,945 settled** of 26,420 candidates, 3,179 wins (64.3%),
raw `$7.51/trade`, **`$0.38/trade ex-dust`** (695 rows below $0.10 excluded). So: positive on a
huge sample, but thin ex-dust — the raw headline is still dust-driven, exactly the artifact
documented in tuning #29.

**The blocker is the bar's own second clause.** The 2026-09-20 pre-registration requires the
CONJUNCTION: `avgPnlPerTradeExDust <= $0.50` for 7 consecutive days **AND** the trailing-7d cohort
mean also ≤ the bar. `decayBar` now reads `consecutiveDaysAtOrBelow: 5` (the daily series works:
0.01 / 0.52 / 0.39 / 0.39 / 0.38 / 0.38 / 0.38) but **`cohort7d: null`, `cohort7dMarked: 0`** →
`cohortAtOrBelow: false` → `tripped: false`, permanently.

Cause (measured, not inferred): the drift shadow's marking walk has **stalled head-of-line**.
`shadow-drift: +0 marked this run (cap 300/run, backlog 6,096 → 6,161)` over 20 consecutive hourly
runs while settled sat frozen at 4,945 — the same oldest-first 300-slot window is retried every run
against candidates whose markets never resolve, so nothing behind them can ever be marked. The
other three markers in the SAME job are healthy in the same runs (lowconf marks +1…+11/run,
12,062 settled of 13,186 candidates), so this is not a transport failure — it is queue ordering.
Consequence: `cohort7dMarked = 0` for any candidate decided in the last 7 days, so a drift
relaxation can never be justified no matter how long the ex-dust series sits at $0.38.

Verdict: **no threshold moves** (the drift gate keeps `maxPriceDrift 0.004`), and the instrument
needs the fix carded below before this card can close. Ratio note: 4,945/26,420 = 19% of drift
candidates have ever settled, vs 91% for lowconf — the drift population is long-dated by nature,
so "0 in the trailing-7d cohort" is plausible *only* in combination with the stalled walk.

## 3. `wallet-cap-shadow-lane` — the rail is INERT; the card's question is unmeasurable

Gate: *"reports candidates > 0, marked > 0 …"*. Actual: **candidates 0, marked 0, no
`data/wallet-cap-shadow.jsonl` at all** — 0 would-be entries in 21 days, and the marker prints
`shadow-wallet-cap: +0 marked (backlog 0)`. The v58/v59 per-wallet ceiling
(`maxWalletNotionalPctOfCap 0.25`) is now **$993 on the $3,971 cap** while the largest wallet holds
~$300, so the rail is structurally unreachable and cannot be priced from its own counterfactual.
Do NOT judge the rail on the historical veto count (the whole point of the card).

Decision needed (user pick): (a) leave the lane running and re-read if the book concentrates again;
(b) re-scope the rail to a level the book can actually reach (that is a rule change, its own
option set); (c) retire the lane as unmeasurable. Recommendation: **(a)** — it costs one line per
hour and is the only way to answer the card if concentration returns.

## 4. `lowconf-shadow-lane` — the confidence bar is CORRECTLY SET (no-change)

Gate: candidates > 0, would-have PnL by confidence bucket and by band, plus the `confidenceOnly`
slice — *"the population a lower bar would actually admit."*

Read: 13,186 candidates, 12,062 settled. The only slice that matters is `confidenceOnly`
(rejects where confidence was the ONLY blocker): **n=86 candidates, 31 settled, −$106.74,
−$3.44/trade — negative.** The headline buckets are dust-dominated (`<0.40` bucket = $470,962 of
the $502,192 total) and are *not* what a lower bar would admit. The 1,124 still-awaiting rows and
the 0.60–0.70 bucket (−$126.17 on 110 settled) point the same way.

Verdict: **`minConfidence` stays at 0.7** — the bar is rejecting a loss-making population, so
lowering it would admit losses. Card closes as read-and-validated.

## 5. `kalshi-shadow-score-and-ledger` — spread is now FAVOURABLE, sample still short

Judged on the pre-registered EX-TOP-1 basis (not the raw line): selected arm **+27.4% ROI**
(n=81 settled, +$197.93 / $720.96) vs rejected arm **−2.6%** (n=39 settled, −$1.35 / $52.29) =
**+30.0pp in favour of the selected arm**. The raw line for the same clock reads selected +95.9% vs
rejected +0.6% (spread −95.3pp on the *rejected − selected* convention, i.e. an even larger
separation) — but that whole gap is **one row**: `cmux2h02u007hyp6swmgk5vgh`, $589.66, sitting in the
**selected** arm, which is why the pre-registration judges the ex-top-1 line and not the raw one.

The sample gate at the Oct 8 call is **≥150 SETTLED in BOTH arms**, and it is not close:
**81 settled selected / 39 settled rejected** → +69 and +111 settled rows still needed. Note the OOS
clock is not the Sep-13 one: the model was **refit 2026-10-04 09:28 CDT**, which resets `oosSinceFit`
(18 selected + 6 rejected rows are still open and will add as they resolve). The 2026-09-20 reading
(104 / 85 settled, ex-top-1 spread −1.0pp) was on the *pre-refit* clock and is **not comparable** to
this one — it is not evidence the separation has emerged; it is a different sample.

Verdict: **keep observing, do not act.** Nothing is actionable at 81/39 settled, and the direction of
the (thin) forward read is not a switchover signal.

## 6. `midprice-confidence-gate-oct8` — design measured, and its PREMISE DOES NOT HOLD

The card was approved 2026-09-15 and explicitly queued to the Oct 8 close: block new C-200 entries
with entry in [0.20, 0.60) unless confidence ≥ 0.80. Measured now, C-200 only, deduped
(one row per market+outcome), in-window since 2026-09-06:

| slice of [0.20, 0.60) | n | avg entry | PnL | win% | excess |
|---|---|---|---|---|---|
| conf ≥ 0.80 (would PASS) | 11 | 0.469 | +$20.25 | 63.6% | +16.7pp |
| conf 0.70–0.80 (would be BLOCKED) | 72 | 0.446 | +$113.17 | 40.3% | −4.3pp |
| conf < 0.70 (would be BLOCKED) | 845 | 0.438 | +$223.28 | 43.3% | −0.5pp |

The blocked population is **+$336.45 over 917 legs — positive cash**, and the excess on both
blocked slices is only mildly negative (−0.5pp / −4.3pp), not the dead zone the design assumed.
Band split for the same window: `0.20–0.40` n=275 **+$416.73**, `0.40–0.60` n=644 **−$8.37**
(win 46.4%). So the *dead* half is 0.40–0.60, which is ~zero as pre-registered, while 0.20–0.40
carries real cash — and the approved design blocks BOTH. Recommendation: **do not apply the gate as
designed**; either narrow it to [0.40, 0.60) or drop it. User pick, no change made.


## 7. `ml-u1-conditional-fill-model` — its pre-registered forward gate is now CLEARED and it is bad news for the 2¢

Two cards were waiting on the same ≥50-measured-leg bar; both read now, at **354 dispatched intents /
258 stamped legs** (`python3 scripts/c200-printthrough.py`, `npx tsx scripts/fill-vs-intent.ts`):

**7a. `fill-vs-intent` — the arithmetic ran, exactly as modelled, on every leg.** 258 measured legs:
gap (entry − intent) mean **−$0.0200**, median −$0.0200, **exactly −$0.02 on 100.0%**, better by >2.5¢
0.0%, no-improvement 0.0%, worse (bug signature) 0.0%. So the credit is applied uniformly — nothing to
fix in the plumbing. **96 of 354 intents (27%) never linked to a booked leg** (dispatched, never booked).

**7b. `c200-intent-printthrough-check` — the level is reachable about one leg in five, not three in four.**
354 legs, 339 tape-analysable, 353 book-analysable:

| instrument | horizon | reachable | archive bar |
|---|---|---|---|
| public trade tape (prints ≤ level) | 5 min | **18/339 = 5%** | 74.3% |
| public trade tape (prints ≤ level) | 1 h | **65/339 = 19%** | 81.1% |
| our own 5 s L2 book (best ask ≤ level) | 1 h | **65/353 = 18%** | 81.1% |

Two independent instruments agree to within 1pp, so this is not a tape-thinness artifact. The anchor
measurement explains the gap: **intent == the detection MID on 336/354 legs (94.9%)** and == the copied
wallet's own print on only 5/354, and the level (`mid − 2¢`) sits **below the first covered best bid on
278/353 (79%)**. The archive's 74.3% was measured on a *print* at `p`; ours is a mid-anchored level one
tick deeper, which the archive could never price. Adverse selection also reproduces and is *larger*:
reached legs drift **−0.0818** (n=56) vs the archive's −0.0323, while unreached legs are flat
**+0.0038** (n=212) — the archive's strongly positive missed arm (+0.13) does **not** reproduce here.

Coverage note (instrument nit, not a data problem): the recorder's post-v62 fix works — median L2 start
lag is **0.2 min** after dispatch, so the 5-minute book horizon *is* covered on post-2026-09-26 legs —
but `c200-printthrough.py` still prints the pre-v62 sentence "the 5-min horizon has NO in-house book
coverage on any leg". That line is a static string; it under-reports and should be computed from
`l2StartLagMin` (or dropped).

**Verdict: the 2¢ does not survive being measured.** It is booked unconditionally on every C-200 BUY,
and the venue's own evidence supports the level on ~18–19% of legs within an hour. Nothing in the trade
path moves on this read (measurement only). The decision belongs to `c200-maker-fill-assumption`
(approval-needed), whose gate asked for exactly three things and now has all three: (a) share of legs at
exactly −$0.02 → **100.0%**, (b) unlinked-intent count → **96**, (c) does the improvement survive
measurement → **no**. The honest re-pricing is **p(fill)-weighted, not a flat 2¢ subtraction**: an
unfilled leg is not a −2¢ leg, it is a leg that never existed, so the choice is between (i) keeping the
credit and labelling it, (ii) cutting it to the measured rate and re-running every affected C-200 figure
with a before/after, (iii) removing it entirely (entry = intent), or (iv) keeping the booking but
publishing a `measured-credit` counterfactual beside every C-200 headline. Recommendation: **(ii)**, with
(iv) available immediately at zero risk to live behaviour — but it is a sizing-model change and needs the
go word.

## 8. `ml-u2-wallet-feature-priors` — FORWARD READ (approval: forward gate counted, read re-run)

The card's promotion gate is ">=200 of our own forward legs where top-tercile selection beats
price-only with a market-clustered CI excluding zero"; the forward population is now **365 C-200 legs
since 2026-09-26**, so the dataset was rebuilt (`data/decision-dataset-forward-20261010.csv`, 4,793
deduped legs / 3,546 markets / 214 wallets, 2026-07-15 -> 2026-10-09) rather than re-quoting the
2026-09-13 file. Ranking read re-run on the forward population (`scripts/wallet-feature-priors.py`,
same 1,000-rep market-clustered bootstrap, seed 20260926):

| feature | AUC (win) | 95% CI | verdict |
|---|---|---|---|
| **entry price (BASELINE)** | **0.7299** | 0.7122–0.7474 | the bar |
| entry timing | 0.5740 | 0.5550–0.5921 | beats chance, 5/5 quintiles |
| spread score | 0.5510 | 0.5322–0.5707 | beats chance, 4/5 quintiles |
| wallet's own size | 0.5199 | 0.5008–0.5413 | marginal, CI just clears 0.5 |
| confidence | 0.4968 | 0.4769–0.5159 | KILL |
| composite copyScore | 0.4629 | 0.4426–0.4812 | VETO (was 0.418) |
| wallet quality | 0.4298 | 0.4106–0.4482 | VETO (was 0.420) |
| thesis | 0.3980 | 0.3773–0.4182 | VETO (was 0.370) |

**Verdict unchanged: a veto, never a selector.** Nothing on the wallet side approaches price (0.73),
and the composite score is still *anti*-predictive at 0.463. What HAS moved is the reporting: entry
timing, spread score and wallet size now clear the script's AUC-chance test on the forward population,
where the launch-day read called entry timing and spread a price-proxy (3/5 quintiles) and wallet size
a KILL. That is the script's verdict rule, **not** the card's promotion gate — the gate is a
top-tercile-selection-vs-price test that has not been run, so nothing is promoted on this.

Live-era strata (same read) keep the earlier finding: in `BANKROLL_200|exposure-v58plus` (n=478) price
is 0.650 and copyScore 0.505 — at chance — and in the Kelly window (n=527) copyScore 0.495, price 0.646.
The headline inversion is a property of the company's **pre-Kelly STANDARD era** (n=2,716, copyScore
0.385) and should not be quoted as a live claim.

Artifacts: `data/decision-dataset-forward-20261010.csv`, `data/wallet-feature-priors-forward-20261010.json`.

## 9. `c200-maker-fill-assumption` — BEFORE/AFTER of the 2¢ credit (approved, priced, corrected)

**Correction first, because the first version of this table was wrong.** It valued the credit as
`0.02 × shares`, which assumes a leg's PnL scales with its entry price. It does not at the total-loss
boundary: buying fewer shares at a worse price changes nothing when the token goes to zero, so the
credit on a full loser is $0. The repo's own convention — the number the EOD report already publishes —
is `credit = 0.02 × (realizedPnl + size) / (entry + 0.02)`, i.e. hold the exit price and the stake fixed
and re-price the entry. Every figure below uses that, and the naive form ($2,272.21 vs $2,730.07) is
noted only so the older number can be recognised as the artifact it was.

Maker era (`openedAt >= 2026-08-28`, settled legs, gross of fees): **1,531 legs, $13,983.54 staked,
booked realized PnL $5,934.33, of which the credit is $2,730.07 = 46.0%.**

| scenario | credit $ | C-200 PnL $ | $/trade | vs booked |
|---|---|---|---|---|
| as booked today (credit = 2¢ on every leg) | 2,730.07 | 5,934.33 | 3.876 | — |
| **cut to the measured per-band fill share** | **175.74** | **3,380.00** | **2.208** | **−43.0%** |
| credit removed entirely | 0.00 | 3,204.26 | 2.093 | −46.0% |

Same read as the report renders it (`npx tsx scripts/edge-copy-cost.ts`, lifetime / trailing 30d):
C-200 edge **+31.6% / +63.0%** of committed cost as booked, **+17.7% / +39.1%** at the measured credit,
**+16.8% / +37.7%** with the credit removed. Only 6.4% of the modelled credit survives the measured
rates — the assumption is not slightly optimistic, it is almost entirely unsupported.

**And the credit is concentrated exactly where it is least realizable.** Per-band reachability measured
on the same 353 legs, against the credit's size in that band (repo convention):

| intent band | legs | credit $ | credit as % of entry | reachable 1h (own book / tape) | weight booked |
|---|---|---|---|---|---|
| 0.00–0.10 | 111 | **1,821.78** | 34.9% | 0.0% / 5.6% | 0.028 |
| 0.10–0.20 | 92 | 533.46 | 14.0% | 6.7% / 10.0% | 0.084 |
| 0.20–0.40 | 280 | 245.19 | 6.9% | 27.2% / 18.5% | 0.229 |
| 0.40–0.60 | 613 | 69.90 | 4.1% | 17.6% / 19.9% | 0.188 |
| 0.60–0.80 | 340 | 47.60 | 2.9% | 19.6% / 17.4% | 0.185 |
| 0.80–1.01 | 95 | 12.15 | 2.3% | n=2, unmeasured | 0.185 |

**86% of the whole credit sits in the two cheapest bands**, where reachability is 2.8–8.4%. The
0.00–0.10 band books $3,454.20 and $1,821.78 of it is credit. That is the same <0.20 band that carried
100% of the Kelly window's profit — the two findings are one finding: **on this book the long-shot
edge and the 2¢ credit are not separable.**

Framing that must travel with the change: this is not "we paid 2¢ too much", it is "we are booking
fills we may not have got". An unfilled leg is not a −2¢ leg, it is a leg that never existed, so the
measured-rate column is the conservative *price-effect* view — the touched legs are also the adversely
selected ones (−0.0818 drift vs the archive's −0.0323), and ~$490–500 of the lane's net rides on the
entry also being a *maker* fee (2026-09-25 audit), which this change does not address.

## 10. Applied after approval (2026-10-10) — what shipped, and what proves it

| change | card | evidence |
|---|---|---|
| **Sidecar books the measured per-band credit** instead of a flat 2¢ | `c200-maker-fill-assumption` | `rust-sidecar/src/main.rs`: `maker_credit()` + band table + `MAKER_CREDIT_MODE` (default `measured`, `modelled` = the old behaviour, read per request so reverting is an .env edit plus `launchctl kickstart`, never a rebuild). `cargo test`: 4 new tests pass (band shares, never >2¢, modelled = old behaviour, the 1¢ floor). Binary rebuilt 03:07, job kickstarted 03:07:04, `/quote` probe answered 422 on :3014 |
| **EOD publishes the measured-credit counterfactual** beside the existing modelled-credit line | `c200-maker-fill-assumption` | `src/lib/copy-cost.ts` (+4 tests, `tests/copy-cost.test.ts`); `scripts/edge-copy-cost.ts` now prints `2c maker credit $2,730 of $5,826 realized (ex-maker edge +16.8%) / measured-rate credit $176 (edge at measured rate +17.7%)`. `tsc --noEmit` clean |
| **Mid-price gate DROPPED** — no gate ships | `midprice-confidence-gate-oct8` | card → Done with the measurement that killed it; no admission code changed |
| **Per-wallet cap lane kept running** (option a) | `wallet-cap-shadow-lane` | card records the decision and the re-read trigger (~$993 wallet); no code changed |

Still open on this thread: the drift-marker fix (medusa card `t_81d0a4cb`, worker still running at the
time of writing — reviewed in its own worktree, main untouched), and `ml-u1`'s archive half.

## Remaining freeze-paused items

`ml-u2-wallet-feature-priors` — forward-leg count is now **365 C-200 legs since 2026-09-26** against its
≥200-leg promotion gate, but the launch-day read (2026-09-26) was built from `data/decision-dataset.csv`,
which was last rebuilt **2026-09-13**. A forward read therefore needs the dataset rebuilt before any AUC
can be quoted; not quoted here rather than re-quoting a 4-week-old slice. The card's verdict (wallet
features are a **veto**, never a selector: composite copyScore AUC 0.418, thesis 0.370, wallet quality
0.420) stands unchanged.

`ml-u1` archive half — the 20-shard conditional fill-hazard scan + `fit-fill-model.py` results section
were never filled in (the draft's §Results is still empty); it needs `/Volumes/Storage/pm-data/polymarket-v1`,
and the row-level event it would price is the *print*-anchored one (74.3%), which 7b shows is not our
anchor. Worth finishing for the p(fill) curve, not for the rate.
