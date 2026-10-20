# ML bot — independent paper lane, Polymarket + Kalshi

**Design v1 · 2026-10-20 · status: DESIGN ONLY, nothing implemented, nothing live.**
Owner: Hermes · Requires approval before build (Lane A: a new lane that decides entries and consumes sizing).

---

## 1. The question this exists to answer

> Does an independent ML entry model beat pure copy-trading — on the same books, the same
> fill model, and the same accounting — on Polymarket **and** Kalshi?

Today that comparison is not merely unmeasured, it is **not measurable**: the ML work has no
`bot_id`, no ledger, no sizing and no exposure of its own. It trains on copybot's own copy
decisions, so it cannot help but inherit copybot's selection bias. This design gives it its own
lane so the comparison is a real side-by-side rather than an in-sample story.

**One rule governs the whole document:** if the two arms are not scored by the same code on the
same cost basis, the comparison is worthless. We already have a live example of why — the
standing "−3.92 % take-all ROI" figure does **not** reproduce from the files it names (an
independent re-cut reads +2.69 % on STANDARD, +16.13 % all-lane over 90 d). Two accounting paths
in one project is how a number drifts for a week without anyone noticing.

---

## 2. What is already measured, and therefore not up for debate

These are facts from prior cards. The design is built to survive them, not to assume them away.

| Finding | Number | Consequence for this design |
|---|---|---|
| Maker entry reachability (`ml-u1`) | **~19 % within 1 h** (65/353), 5 % within 5 min — not the archive's 74–81 % | **Decides the architecture.** See §3. |
| Adverse selection on reached legs | **−0.0818** (n=56) vs archive −0.0323 | A maker lane must pay this on every fill |
| Anchor mismatch | archive priced a **print**-anchored event; we book a **mid**-anchored one | Archive fill rates do not transfer. Ever. |
| Walk-forward OOS (`bt-ml-lane`) | **−29.84 % ROI**, n=70 (56 settled) vs **+18.0 % in-sample** | The model currently loses money forward. Start at zero size. |
| `copyScore` as a selector (`bt-ml-lane`) | top-30 % kept **−18.0 %**, rejected rows made **+$966.41** | The incumbent score is worse than guessing |
| Price-only ranking decays by era | 0.7582 → 0.6727 → 0.6542 | A single promotion bar cannot be era-blind |
| AUC is not money | top-tercile by `entry_price` **loses −$2.39/leg**, CI excludes 0 | Never promote on AUC/Brier alone |
| Cheap-tail edge | blind <0.20 **+36.8 %** [+8.9,+62.9]; model top half **+106.8 %** [+66.5,+148.6] | This is where the model pays — if it can fill |
| Cheap-band entry tolerance | breakeven slippage **+112 %** of price | **This is the key that unlocks §3** |
| Concentration | all-lane ex-top-10 collapses +16.13 % → +2.13 % on 10 of 4,166 legs | Any scale-up is a bet on a tail that already happened |

---

## 3. The decisive architectural call: the ML bot trades as a TAKER

This is the single most consequential decision in the document, so the reasoning is stated in
full.

**The trap.** A paper lane that books fills at the detection mid, or at any optimistic maker
assumption, will report a fiction. `ml-u1` measured that ~81 % of our maker entries are **never
reached within an hour**, and the 19 % that are reached carry **−8.2 %** adverse selection. On a
cheap longshot with a modelled +79 % ROI, an 80 % non-fill rate does not shave the return — it
deletes the sample and leaves only the adversely-selected remainder. That is precisely how a
shadow arm can print +100 % and be worth less than nothing.

**The unlock, measured rather than assumed.** In the band where the model actually earns, *fill
certainty is worth more than price* — but the cost is far larger than the first draft of this
document claimed, so it is quantified here from 8,997,897 cheap-band quotes (90 d,
`MarketSnapshot`, live `bestAsk` only):

Taker premium `(ask − mid)/mid` by band — the cheap band is the **most expensive place on the
book to cross the spread**, because 0.35 ¢ of premium on a 1 ¢ token is a third of its price:

| band | median premium | p90 | share above 25 % |
|---|---|---|---|
| **<0.20** | **33.3 %** | 71.4 % | **53.6 %** |
| 0.20–0.40 | 2.4 % | 12.9 % | 5.7 % |
| 0.40–0.60 | 1.1 % | 4.3 % | 2.3 % |
| 0.60–0.80 | 0.8 % | 5.0 % | 1.6 % |
| 0.80–1.00 | 0.6 % | 2.7 % | 0.0 % |

ROI at the ask is **multiplicative**, not additive — `ROI_ask = (1/(1+premium))·(1+ROI_mid) − 1`.
Against the measured +47.75 % mid-ROI that means a 33.3 % premium turns +47.75 % into **+10.84 %**,
and the **break-even premium is 47.8 %**. Above it the trade is unprofitable by construction
whatever the model says. That is **44.0 % of all cheap-band quotes** (3.95 M of 9.00 M).

So the lane needs an explicit premium gate, and the modelled trade-off is:

| taker premium cap | quotes kept | median premium kept | modelled ROI |
|---|---|---|---|
| 35 % | 51.9 % | 14.3 % | **+29.28 %** |
| 45 % | 55.3 % | 16.7 % | +26.64 % |
| 50 % | 59.5 % | 20.0 % | +23.13 % |

**Decision.** The ML paper lane books **taker fills at the ask, plus the venue's taker fee**, and
admits a candidate only when the **quoted taker premium ≤ 35 % of mid** (the cap that maximises
modelled total profit, ≈ kept-share × ROI). This rejects about half of cheap-band flow and turns
the dominant unmodellable risk into a knowable, measured cost. A maker arm is retained as a
*measured shadow* (same signals, no ledger weight) so the fill-model card keeps accumulating
evidence — but the lane's reported P&L is the taker arm.

The earlier draft of this section claimed the taker cost was "an order of magnitude inside the
band's tolerance". That was wrong: at the median premium it **consumes 70 % of the band's gross
edge**. Taker survives on measurement, not on comfort — and only behind the cap.

**What this does not fix.** At prices above ~0.40 the band has **zero** slippage tolerance, so a
taker entry there is already negative before any model skill. The ML lane must therefore be
admission-gated to the region where the edge exceeds the spread — see §4.

---

## 4. Architecture

Five layers, each a separate module so the accounting and the model can be swapped independently.

### 4.1 Signal — `ml-signal`
- Candidates come from the **market**, not from a whale: `MarketSnapshot` (price, drift, TTR,
  liquidity, category), band structure, sentiment deltas (`src/lib/forecasting/sentiment.ts`,
  with its `asOf` door so a historical decision re-scores without look-ahead).
- **Point-in-time only.** `WalletProfile` is live-valued (its depth columns are clamped at
  100/200) and must never be read as a feature; wallet depth must be derived as-of-entry.
- Population includes the **declined arm** (open card `ml1-declined-arm-coverage`); a model fit
  only on acted legs cannot learn what we should have taken.

### 4.2 Model — `ml-model`
- **Primary: regularised logistic.** LightGBM as a cross-check that must keep agreeing (they tied
  to four decimals in every arm, so the interpretable model earns its place).
- **Nightly batch refit** on the labelled book. **Online recalibration** of the batch score
  (monotone only), which is the only live-learning form that did not lose: Brier 0.1928 vs 0.1938.
- Standalone online learners are **rejected as primaries** — HAT 0.630 AUC / Brier 0.283, online
  logistic 0.652 / 0.271, both worse than predicting the base rate.

### 4.3 Decision — `ml-policy`
- Admission: `p̂ − cost − fee > θ`, where `cost` includes the **taker** premium.
- Band prior, not band law: the model may discover regions, but the measured structure (cheap
  pays, 0.4–0.6 is dead) is the prior it must beat, not re-learn from scratch.
- Reuses the existing rails from `src/lib/rules.ts` — per-market leg cap, per-wallet cap, gross
  exposure, open-position count. **These stay external to the model (§6).**

### 4.4 Fill + book — `ml-book`
- Taker fill at ask + taker fee (§3).
- **New botId namespace:** `ML_LANE` (Polymarket), `ML_KALSHI` (Kalshi). Never mixed into
  `STANDARD` or `BANKROLL_200`. Own bankroll, own RuleSet namespace.
- Schema: `DecisionJournal.observedTradeId` becomes **nullable**, or a new `MLEntry` table — the
  ML lane generates candidates with no ObservedTrade parent.
- Rows carry a **fill-model version stamp** so a later fill-model change cannot silently restate
  history.

### 4.5 Report — `ml-report`
See §7.

---

## 5. Venue arms

**Polymarket** — existing stack: `MarketSnapshot`, CLOB, the 5 s L2 recorder, `FillIntent` stamps.
No new venue work; the taker fill is `best_ask` + fee.

**Kalshi** — genuinely better suited to the ML bot than to copy-trading, because **the ML lane
does not need wallet data at all**, and Kalshi has no keyless wallet attribution (which is what
made copy parity infeasible). What it does have, keyless: market data at
`external-api.kalshi.com`, plus our own `data/kalshi-tape/` bars and prints already recording.
Differences the arm must model rather than assume:
- **Fee schedule differs** (maker multiplier 0); the fee model cannot be Polymarket's
  `rate · p · (1−p)`.
- **Resolution semantics differ** — scalar/threshold markets need an explicit mapping to the
  binary label the model predicts. Unmapped markets are **excluded**, not guessed.
- The adapter is **fail-loud by design (TR-16)**; a venue error must stop the arm, never book a
  stale price.

---

## 5.5 Cohort scoping — which markets the ML lane trades first

Asked 2026-10-20: *should the ML bot focus on Bitcoin, arbitrage and weather rather than every
category?* Two of the three, yes — but for reasons that are not "those categories pay", and one of
the three is not a category at all.

**Measured on the deduped STANDARD book (3,192 legs, $38,896 notional) with the live classifier
(`src/lib/market-category.ts`, parity-checked against the vendor map — NOT the `marketCategory`
column, which is a slug/event token and carries a question word on 33.1 % of rows):**

| category | legs | notional | ROI | median hold | share |
|---|---|---|---|---|---|
| **weather** | **806** | **$10,665** | **−0.5 %** | 1.6 d | **27.4 %** |
| sports | 735 | $8,759 | +5.4 % | 1.0 d | 22.5 % |
| other (unclassified) | 623 | $7,615 | +9.3 % | 2.1 d | 19.6 % |
| **esports** | **615** | **$7,007** | **−6.2 %** | 1.0 d | **18.0 %** |
| **politics** | 243 | $2,920 | **+19.8 %** | **12.2 d** | 7.5 % |
| tech | 72 | $748 | +22.3 % | 15.5 d | 1.9 % |
| culture | 39 | $475 | −24.7 % | 5.0 d | 1.2 % |
| econ | 33 | $398 | −8.4 % | 13.8 d | 1.0 % |
| **crypto** | **26** | **$309** | −28.6 % | 3.8 d | **0.8 %** |

**An earlier draft of this table grouped by the raw `marketCategory` slug and reported "weather 28 %
at +0.7 %". The slug tokens happen to map to the same buckets here (the classifier's question rules
send `highest` to weather), so the shape survived — but the numbers did not, and the slug version was
unfounded method. Corrected values are above.**

**Crypto is 0.8 % of the book** — 26 legs, $309. BTC is therefore genuinely NEW exposure rather than
a reshuffle, which is the point. Those 26 legs return −28.6 %, but they are *copy* legs following
wallets into crypto, not ML entries reading a price feed, so they are not evidence against the
thesis. They are evidence that copying does not work there.

**Era-check (added same day, because the table above is ALL-TIME and all-time ranks categories by
ancient performance as if it were current).** Re-cut on the last 90 days, the COARSE structure holds:
weather −0.5 % → **−0.9 %** (512 legs, $8,231, CI [−11.3, +10.3]); sports +5.4 % → +0.9 %;
other +9.3 % → +10.5 %; esports −6.2 % → **−5.6 %** (CI [−16.2, +5.3], still spans zero);
politics +19.8 % → +23.9 % (CI [−8.0, +58.1], spans zero); crypto −28.6 % → **−46.4 %**
(CI [−74.8, −7.2] — excludes zero, but on 14 legs).

The era check also **destroyed the one fine-grained positive** this analysis produced: `football-intl`
read +31.2 % all-time (CI [+2.7, +64.5], 131 legs — the only CI-positive category in the book) but
**−41.0 % on its last 16 legs, with zero legs in 30 days**. It is dormant and recently negative, so
no up-weight was applied. That is the reusable rule: **a category claim must be carried by the recent
era, and a class with <5 legs in 90 d is not a live signal however good its all-time ROI looks.**

**A confound this table exposes them.** Politics returns +19.8 % holding **12.2 days** and tech +22.3 %
holding 15.5 days, while weather holds 1.6 days and returns −0.5 %. The band analysis found hold time
*inversely* ordered to edge; at category level the relation **reverses**. So "short holds are better"
is a proxy for category, not a law — the honest statement is that hold time is confounded with what
you are trading, and neither variable should be optimised alone.

Four conclusions that invert the naive read:

1. **Weather is already the book's largest allocation (27.4 % of notional) and returns nothing
   (−0.5 %).** "Focus on weather" would deepen the biggest zero in the book. The case for weather
   is *not* that the book profits there — it is that **the ML lane has information the copy lane
   structurally cannot have: exogenous ground truth (forecast feeds).** The copy lane copies humans;
   a weather model can read the forecast. That makes weather the cleanest available test of
   "can this model see something a copied wallet can't" — and it is testable against a 28 %
   allocation that is currently earning zero.
2. **BTC is genuinely NEW exposure, not a reallocation.** Nothing in the copy book touches it, so an
   ML BTC arm is a real second lane rather than a reshuffle of the same money. It is also the
   fastest-resolving, highest-frequency class available — the best training substrate a
   self-learning loop can get, because label turnaround is the binding constraint on how fast any
   self-learning system can learn.
3. **Esports is where the book actually bleeds**: −6.2 % across **$7,007 = 18.0 % of notional**
   (615 legs), the second-largest loss pool after nothing else in the book is negative at that size.
   This is a finding independent of the ML work and is carded separately as a Lane A item.
4. **Arbitrage is not a category — it is a strategy with zero prediction content.** It needs both
   venues and execution speed, not a forecast. It belongs on the existing `kalshi-pm-pair` shadow
   lane. Putting arb legs inside the ML lane would make the model's AUC/Brier **uninterpretable**,
   because those legs carry no forecast to be right or wrong about.

**Decision.** No category whitelist. `category` becomes a **feature**, and cohorts are **sequenced**
rather than filtered: **BTC / short-TTR crypto first** (new exposure + fastest labels), **weather
second** (tests the exogenous-feature thesis against the book's largest zero). A whitelist would be
priced on a book that returns +0.7 % in its biggest category — i.e. on nothing.

**Lane B defect found while answering this.** `ObservedTrade.marketCategoryClass` /
`marketCategoryFine` were introduced around 2026-W39 and **never backfilled**: ISO week 2026-W37 is
44,671/44,671 null on the new column while the older `marketCategory` column is populated for
44,431 of those same rows. Any query joining on the new taxonomy silently drops ~90 % of history —
which is exactly what happened in the first pass at this question (it read 96.4 % "uncategorised"
when true coverage is 99.4 %). Fix: COALESCE the two columns through one mapping view, behind a
test that asserts coverage ≥99 % on the closed book.

---

## 6. Self-learning and self-reinforcing — with the guardrail that makes it safe

"Self-reinforcing" is the most dangerous phrase in this document. A system that reinforces its
own confidence is how trading bots die. So the loop is specified as **learning from outcomes**,
never as **reinforcing its own conviction**:

1. **Learn from resolved outcomes.** Every closed paper leg (and every declined candidate with a
   simulated label) feeds the next refit. Labels come from the simulator at a declared tier —
   `net_return` primary, `edge_vs_price` secondary — **never** `PaperTrade.realizedPnl`.
2. **Two clocks.** Nightly batch refit; continuous monotone recalibration.
3. **Drift detection (ADWIN) fires a *downside-only* reflex.** On drift: shrink size, pause the
   lane, and raise a report flag. ADWIN has already fired twice for real (08-31, 09-08).
4. **The model can never raise its own risk.** Size ceilings, per-market caps, exposure and
   position count live in `rules.ts`, external to the model and changeable only through the
   versioned RuleSet path. The model's only output is a probability.
5. **Automatic demotion.** If rolling Brier degrades beyond a pre-registered bound, or ROI CI's
   upper bound falls below 0 over a pre-registered leg count, the lane auto-pauses and reports
   it. No human in the loop needed to stop it.
6. **Promotion is pre-registered and human-gated.** The lane may not size up until it clears the
   §8 bar. Nothing sizes itself up.

---

## 7. Reports

**Daily — training progress** (is it learning, and is the learning real?): label counts and
freshness, refit date, discriminating power vs the era-matched price-only bar (headline AUC/Brier
is era-blind — see `ml1-price-baseline-drift`), calibration curve, drift events with their action,
feature-importance movement, and the **OOS-vs-in-sample gap** printed side by side so the −29.84 %
vs +18.0 % failure mode can never hide again.

**Daily — trading effectiveness** (is it making money, on honest fills?): legs, fill rate, ROI
with a market-clustered CI, **edge per capital-day** (the metric that just proved decisive for
STANDARD vs C-200: $0.011 vs $0.382), hit rate and ROI by band/venue/category, and the
**head-to-head against the copy arm on identical accounting**.

**Weekly — scorecard:** ML vs copy vs price-only, on ROI, edge per capital-day, and
concentration (ex-top-10), with the promotion verdict and the number that would change it.

---

## 8. Promotion bar (pre-registered — written before any result is seen)

The paper lane earns size only when **all** of the following hold on the measured taker fill model:

- `n ≥ 400` resolved paper legs, market-clustered.
- Head-to-head **ROI CI lower bound > 0** vs the copy arm over the same window.
- **Edge per capital-day** exceeds the copy arm's on the same window (not just ROI).
- Beats the **era-matched** price-only comparator on money, not only on AUC.
- **Ex-top-10** ROI remains > 0 (the concentration check).

Unless all five hold, the lane stays at zero size and reports why. **The expected outcome is that
it does not clear** — the OOS read is −29.84 %.

---

## 9. Reality checks — what would make this fail

1. **The model may simply have no edge.** −29.84 % OOS is the current honest read. This lane's
   first job is to *prove or kill* the thesis, not to trade.
2. **The taker premium does eat most of the cheap tail — now measured, no longer a risk.** Median
   premium 33.3 % of mid consumes **70 %** of the band's gross edge, and **44.0 %** of cheap-band
   quotes sit above the 47.8 % break-even and are unusable at any model skill. The lane survives
   only behind the 35 % cap, on roughly half the flow.
3. **Selection bias in the gross-ROI transfer.** The +47.75 % mid-ROI was measured on legs copybot
   actually booked — a mid-anchored, maker-shaped population. The taker lane trades only the
   tight-spread half of the cheap band, and nothing yet proves that half returns the same gross
   edge. This is the most likely way the modelled +29 % evaporates, and it is why Phase 2 must
   report the taker arm's own realised ROI per premium bucket rather than leaning on this table.
3. **Sample size.** The decisive cheap-tail cell was n=235 with a CI spanning a factor of two.
4. **Two months, one holdout, one wallet set.** The whole measurement base is thin.
5. **Kalshi resolution mapping** may exclude most of the interesting markets.
6. **Self-learning over a short window** can fit the last regime and call it skill — hence the
   era-matched bar and the downside-only drift reflex.

---

## 10. Build order

| Phase | Work | Lane | Cost |
|---|---|---|---|
| **0** | **Unify accounting** + **fix category attribution** (COALESCE the never-backfilled `marketCategoryClass` against `marketCategory` through one mapping view, with a ≥99 %-coverage test); re-derive the copy baseline on it; stamp the fill-model version | B (repair) | ~1.5 d |
| **1** | Taker fill model; candidate generator; **shadow book only** (signals recorded, zero positions). Per-band spread distribution **already measured** (see §3) — remaining work is the fee model and the premium-bucket reporting | B | ~1.5 d |
| **2** | Paper lane on Polymarket (`ML_LANE`), taker fills, external rails, own bankroll | A (approval) | ~1 d |
| **3** | Kalshi arm (`ML_KALSHI`), fee + resolution mapping, fail-loud | A (approval) | ~2 d |
| **4** | Self-learning loop: nightly refit, online recalibration, ADWIN downside reflex, auto-demotion | A (approval) | ~1 d |
| **5** | Reports + dashboard comparison card | B | ~1 d |

Phases 0–1 are read-only/measurement and Lane B. Phases 2–4 create a lane that decides entries and
consumes sizing, so each needs its own approval.

---

## 11. Decisions made in this design (overridable, one line each)

1. **Taker fills, not maker, behind a 35 %-of-mid premium cap** — converts the dominant
   unmodellable risk into a measured cost. The cost turned out to consume 70 % of the gross edge,
   so the cap is load-bearing, not decoration. Maker retained as a measured shadow (it fills only
   ~19 % of the time and the fills are adversely selected at −8.2 %).
2. **New botId namespace `ML_LANE` / `ML_KALSHI`** — the copy lanes stay untouched and comparable.
3. **Logistic primary, LightGBM cross-check** — they tied to four decimals; interpretability wins.
4. **Batch refit + online recalibration; no free-running online learner** — measured worse than
   the base rate.
5. **Labels from the simulator, never `PaperTrade.realizedPnl`** — per `bt-ml-lane`.
6. **Model cannot raise its own size**; ceilings stay external and versioned.
7. **Drift reflex is downside-only** — shrink or pause, never add.
8. **Kalshi included from the start as a second arm**, because the ML lane needs no wallet data,
   which is exactly what made copy parity impossible there.
9. **Shadow book before paper book** — signals and fills recorded for 2 weeks before any position
   is booked, so the taker assumption is measured against real books first.
10. **Promotion bar written before results** (§8), and the expected outcome is failure.
