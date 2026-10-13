# btx2 — PRE-REGISTRATION: deterministic convergence on Binance-settled Polymarket families

**Frozen 2026-10-13, before the first sample row exists.** Approved in-thread 2026-10-13 16:26 CDT
(*"B, and then proceed with asset universe, venue scope, futures, and history cap"*) after the btx1
feasibility read. Card: `btx2-deterministic-convergence-study`.

**What this is:** a measurement instrument. Read-only, keyless, no orders, no sizing, no venue
decision, nothing added to the live path. Kalshi is out of scope by decision (§2.3) and we hold no
key for it in any case.

**How to read it:** §1 is why this lane is different from every other BTC lane we run. §2 pins the
universe, §3–4 the instrument and the fee law, §5–6 the two questions and their gates, §7 the sample
floors, §8 what voids the series, §9 what a PASS would and would not license, §10 the reality checks
stated up front so the numbers cannot be over-read later.

---

## 1. Why the premise is exact here and nowhere else

Polymarket's crypto **price/threshold** families name **Binance itself** as the resolution source in
their own rule text. Our keyless pull reproduced the venue's recorded verdict for **1,617 / 1,617**
settled markets = **100.00%** (btx1). Therefore, in this family only:

- **oracle risk ≡ 0** — we can compute the outcome to the cent, before or after the venue does;
- **"determined" is a well-defined, computable object** — not an opinion about probability;
- and a position bought on a determined leg cannot lose to settlement basis, only to **price and fees**.

That last sentence is the entire hypothesis. It does **not** transfer to Kalshi (settles on CF
Benchmarks BRTI, whose own constituent list does not include Binance) or to PM's 5 m/15 m/1 h/4 h
up-or-down families (Chainlink). There, Binance is a **proxy** with a *measured* error rate
(97.795% against BRTI's recorded verdicts; 93.06% at best against Chainlink, with **every** miss
inside $19.60 of the knife edge) — and for a proxy, that error rate *is* the risk. Mixing a proxy
into an instrument whose premise is "oracle risk is zero" would destroy the instrument's only claim,
which is why §2.3 excludes them.

## 2. Universe and scope (PINNED — changing this voids the series)

### 2.1 Assets
`bitcoin, ethereum, solana, xrp, dogecoin, bnb, hyperliquid` → Binance spot `BTCUSDT, ETHUSDT,
SOLUSDT, XRPUSDT, DOGEUSDT, BNBUSDT, HYPEUSDT` (all verified reachable keyless on
`data-api.binance.vision`; `api.binance.com` and `fapi.binance.com` are HTTP 451 from this host).

**Inclusion rule (frozen):** an asset is in the universe **only if** the reconcile harness
(`scripts/btc-oracle-reconcile.py --assets all --days 2`) reproduces that asset's recorded
Polymarket verdicts **exactly** over the validation window. Any asset below 100% is **excluded** and
named. Anything less than exact reproduction is a trap, not a data source.

**Validation (completed before the first sample; `--assets all --days 2 --futures`, 2026-10-13):**

| asset | families reproduced (ok/n) | rate |
|---|---|---|
| bitcoin | hit_day 32/32 · hourly_above 960/960 · noon_close 22/22 · updown_1h 48/48 | **100%** |
| ethereum | hit_day 28/28 · hourly_above 768/768 · noon_close 22/22 · updown_1h 48/48 | **100%** |
| solana | hit_day 20/20 · noon_close 22/22 · updown_1h 48/48 | **100%** |
| xrp | hit_day 20/20 · noon_close 22/22 · updown_1h 48/48 | **100%** |
| bnb | updown_1h 48/48 | **100%** |
| dogecoin | updown_1h 48/48 | **100%** |
| hyperliquid | **no listed families matched in the window** | *unvalidated* |
| **TOTAL** | **2,204 / 2,204** | **100.00%** |

Two honest readings of that table, both frozen here:
- A family with **zero** rows (solana `hourly_above`, bnb/dogecoin ladders) means the venue **did not
  list** that family in the window — not that it failed. Those assets are validated by the families
  they did list, and a family that is not listed simply produces no rows.
- **hyperliquid is UNVALIDATED** (nothing listed to check against), so it fails the inclusion rule on
  the evidence available: its rows, if any appear, are recorded but are **excluded from every
  statistic** until a later validation reproduces at least one of its families exactly. It is left in
  the sampler's asset list deliberately — dropping it would mean editing the universe (which §8 voids
  a series for), and its observations cost nothing while they cannot be used.

No asset that was validated came in below 100%, so no asset was dropped by the exclusion rule.

### 2.2 Families (PINNED — four, each with a frozen determination rule)
1. `hit_day` — `what-price-will-<asset>-hit-on-<month>-<d>-<year>`: outcome determined the moment a
   **1 m High** touches the strike (↑ ladders) or a **1 m Low** touches it (↓ ladders).
2. `hourly_above` — `<asset>-above-on-<date>-<h><am|pm>-et`: determined by the **1 m candle closing
   at that hour** (both sides decided at that instant).
3. `updown_1h` — `<asset>-up-or-down-<date>-<h><am|pm>-et`: determined by the **1 h candle that
   BEGINS at that hour**. *(Trap, measured in btx1: anchoring on the candle that ENDS there scored
   43% — worse than a coin flip.)*
4. `noon_close` — `<asset>-price-on-<date>` / `<asset>-above-on-<date>`: determined by the **1 m candle
   closing at 12:00 ET** (both sides decided).

Determination is computed from **Binance tape only — never from the venue's own price**. A row whose
`determination_basis` cites a venue price is invalid by construction and is excluded.

### 2.3 Excluded by decision (one line each to override)
- **Kalshi KXBTC15M** — settles on CF BRTI, so nothing here is deterministic; a Binance-based signal
  there carries the measured proxy error. That measurement already runs in its own lane
  (`kalshi-pm-btc-pair-prereg`, 288-window gate) and card `btx3` is where a Binance nowcast would
  belong — **parked**, and it must be pre-registered against that running gate, not bolted on.
- **PM Chainlink 5 m/15 m/1 h/4 h up-or-down** — same reason; best proxy agreement 93.06%, and the
  error is knife-edge concentrated (exactly where a single-venue feed cannot speak for a composite).
- **Futures features (funding, open interest, perp basis)** — `fapi.binance.com` is **451** here, so
  there is no live funding/OI feed. The **archive** is reachable (measured: UM klines 1,441 rows/day,
  UM aggTrades 452,085 rows/day, CM klines 1,441 rows/day, metrics/OI 289 rows/day, and fundingRate
  published **monthly, one month behind**) and is available at T+1 for *research*, but nothing in
  this instrument's gate may rest on a funding or open-interest feature, and no live decision may.

## 3. Instrument (PINNED)

- **Sampler:** `scripts/btc-convergence-sampler.py`, **code hash `sha256[:12] = b06650b8c215`**.
  Every row and every coverage line carries this hash (`code`), so an analysis can restrict itself to
  the frozen revision and a later change can never silently ride on earlier rows.
- **Reader (the gate's only voice):** `scripts/btc-convergence-read.py` — pinned to the same hash,
  implements §5–§7, and prints the structural census and the sanity identities **before** any verdict.
  Below the floor it prints the shortfall, never a percentage.

### 3.1 Cadence — set by a measured constraint, not by convenience

**Measured on the venue's own `closedTime` (2026-10-13):** an hourly above-ladder closes ~**11–12
minutes after its anchor** (3 pm ET ladder `closedTime 19:11:33Z` for a 19:00Z anchor; 4 pm ladder
`20:11:33Z`). The noon ladder closed at `16:12:42Z` for a 16:00Z anchor. **A 15-minute sampling grid
therefore cannot observe that window at all — it would systematically miss it.** So the instrument
runs two cadences, both frozen here:

| job | schedule | families | purpose |
|---|---|---|---|
| **coverage** | every 15 min | all four | the day's ladders, `hit_day` states, decided legs seen late |
| **window** | minutes **1, 4, 7, 10** every hour | `hourly_above, updown_1h, noon_close`, `--hours-back 1`, `--max-minutes-since-determined 12` | the only place a Q1 edge could live: the first minutes after determination |

*Observation kept, not explained away:* the 5 pm ET ladder was still `acceptingOrders: true` **45
minutes** after its anchor, so the close is *not* always at +11 min. Every row therefore carries
`accepting_orders` and `minutes_since_determined`, and no row is ever scored as buyable without an
ask actually present in the book.
- **Books:** both tokens' **real executable CLOB book** per market. Gamma's `bestBid`/`bestAsk` is
  never used (measured stale by up to ~0.6 in the pair lane).
- **Row payload:** label, strike/strike_kind, `determined`, `determination_basis`,
  `determined_at_ms`, `sampled_at_ms`, `minutes_since_determined`, both tokens' best bid/ask **with
  sizes**, `feeType`, `feeSchedule`, `accepting_orders`, `distance_to_strike`, and for decided legs a
  `q1` block (determined side, ask, size, fee, fee law, edge, `executable_at_floor`).
- **Tape:** 1 m for all determination and anchors. The 1 s archive is pulled only where the history
  cap allows it (§8) and is never used to determine an outcome (the archive CSV is **microseconds**
  while the klines API is **milliseconds** — this mismatch silently produced a false 50.95%
  "finding" in btx1; prices are looked up **by timestamp, never by list position**).

## 4. Fee law (PINNED — a change voids the sample)

- **Canonical:** the market's **own** `feeType`/`feeSchedule`; taker fee
  `= rate × shares × min(p, 1−p)`, exponent ∈ {1}, makers 0. Recorded per row as
  `fee_law ∈ {schedule, no_schedule_zero, unpinned_exponent, no_price}`:
  - `schedule` → fee charged from the published rate;
  - `no_schedule_zero` → **no** schedule is published on that market ⇒ taker fee 0;
  - `unpinned_exponent` / `no_price` → row is **dropped** and counted, never imputed.
- **Sensitivity arm (frozen):** every `no_schedule_zero` row is **re-priced at 0.07 × min(p, 1−p)** —
  the rate pinned in the pair lane from the venue's own fields (`feeType=crypto_fees_v2`,
  `feeSchedule.rate=0.07`). A PASS that exists in the canonical arm but not in the sensitivity arm is
  reported as **NO CLAIM**.
- **Trap, never used:** `takerBaseFee`/`makerBaseFee` and CLOB `/fee-rate` are a legacy constant
  `1000` on ~85% of markets regardless of schedule; pricing `base/1e4` charges 0.10/share — enough to
  erase the entire apparent edge.

## 5. Q1 — determined legs (PRIMARY question)

**Observation.** At sample time *t*, a bracket/pair whose outcome is **already determined** from the
tape, with the determined side's executable ask *a* and size *s* at that instant.

**Three categories, counted separately (frozen taxonomy).** `q1.reason ∈ …`

| reason | meaning | in the canonical statistic? |
|---|---|---|
| `no_ask` | **no ask exists on the determined side at all** — structurally unbuyable at *any* price | no — but the *fraction* is itself reportable |
| `thin` | an ask exists but `s < 50` shares | no (reported separately) |
| `priced` | an ask exists with `s ≥ 50` → `edge = 1 − a − fee` | **yes** |
| `unpinned_exponent` / `no_price` | the row cannot be priced | no (dropped, counted) |

**Statistic.** `edge = 1 − a − fee`; executable ⇔ `s ≥ S = 50` shares.

**First live observation (2026-10-13, 20/20 decided rows, replayed before this file was committed).**
**Every** decided leg had `reason = no_ask`: the venue's book on a decided market is **bid-only on the
winner** (20 bid levels at ≤ 0.999, **zero asks**) with the **loser** offered at ~0.001 — and that was
verified against the CLOB per token, including the token↔outcome mapping (the winner's token carries
the 0.999 bid and no ask; the loser's token carries the 0.001 ask and no bid; `outcomes` order and
`clobTokenIds` order agree). If this 100% `no_ask` fraction survives the window cadence (§3.1), then
Q1 is answered **negatively and structurally**: a determined leg is unbuyable at any price rather than
mispriced, and the gate reports that finding, not a statistic. This is recorded **before** the sample
series starts, so it cannot be presented later as an after-the-fact discovery.

**Pre-registered reporting (per family and pooled):**
1. median edge over executable determined observations;
2. mean edge with a **clustered bootstrap, cluster = UTC day**, 10,000 resamples, 95% CI — the day is
   the cluster because one day's High/Low decides many strikes simultaneously, so rows within a day
   are strongly dependent and an i.i.d. bootstrap would overstate precision;
3. the same two statistics on the **0.07 sensitivity arm** (§4);
4. the **decision curve** `edge` vs `minutes_since_determined` — because an edge that collapses inside
   the window is a **latency artefact**, not a dislocation (the pair lane's window-open "6¢ edge"
   died in 6–8 minutes; the same trap applies here and is pre-empted).

**PASS ⇔** pooled executable **median edge > 0** **and** the day-clustered bootstrap **CI lower bound
> 0**, in **both** the canonical **and** the sensitivity arm, at **n ≥ floor** (§7).

**A measured reprice latency with no edge is a valid, publishable result** and ends the study in
`NO CLAIM`. The instrument failing to find an edge is a success of the instrument.

## 6. Q2 — undetermined ladders (SECONDARY, separate series)

**Question.** For a strike not yet touched, is the distance-to-strike priced consistently with the
physical remaining-horizon distribution?

**Estimator (spec frozen NOW so it cannot be fitted after seeing outcomes).** At time *t*, anchor
*A*, remaining horizon `T = A − t`, boundary `B` (strike/edge):

```
z  = (B − spot_t) / (σ̂ · √T)
p̂  = empirical P(Z ≥ z)   [↑ / above ladders; mirrored for ↓ / below]
```

where `σ̂` = realised 1 m volatility over the trailing 24 h (per asset, from 1 m bars) and the
distribution of `Z` is the empirical one over the **trailing 90 days** of 1 m bars for that asset
(vol-normalised remaining-horizon extremes: max High for ↑ ladders, min Low for ↓ ladders, close for
hour ladders).

**Eligibility (frozen).** Undetermined rows are recorded from the start, but rows are
**Q2-analysis-eligible only if written under the estimator revision whose hash is recorded here** —
the sampler stamps `code` on every row, so pre-estimator rows are excluded transparently rather than
post-hoc annotated. Until the estimator is implemented and its hash recorded in this section, Q2
carries **no claim and no verdict**.

**Asset eligibility (from §2.1):** `hyperliquid` is unvalidated (no listed families to check against),
so any hyperliquid rows are recorded but excluded from Q1 and Q2 statistics until a later validation
reproduces at least one of its families exactly.

**Gate (frozen).**
1. **Calibration:** Brier skill of `p̂` against the **venue's own** implied probability, both scored
   against the **exact** verdict computed from Binance once the anchor closes.
2. **Trade arm:** buy the side where `p̂ > venue p + fee` at `s ≥ 50`; net PnL per $1 with a
   day-clustered bootstrap CI.

**PASS ⇔** Brier skill > 0 **and** the trade arm's CI lower bound > 0, at n ≥ floor. Q2 is the arm
most likely to be **refuted by the market** — which is exactly why it is separate and cannot
contaminate Q1's verdict.

## 7. Sample floors (frozen — below floor the reader prints the shortfall, never a number)

- **Q1:** ≥ **1,500** executable determined observations (`s ≥ 50`) spanning ≥ **14** distinct UTC
  days, including ≥ **200** observations whose determined-side ask is **< 0.99** (the only bucket an
  edge can physically live in — a 0.998 ask is a rounding error, not opportunity).
- **Q2:** ≥ **2,000** decided bucket-observations spanning ≥ **14** distinct UTC days, under the
  estimator revision.
- Expected collection: **2–4 weeks**. Rationale for the floor: these families are new and rotate
  daily; per asset per day a hit ladder yields ~20–40 buckets and the hourly/noon families a handful,
  so 7 assets × 14 days is the practical minimum, not an arbitrary round number.

## 8. What voids or trims the series (frozen)

- **Any change to** the determination rules (§2.2), anchor conventions, fee law (§4), size floor,
  asset universe (§2.1) or the sampler hash (§3) → **the series restarts** at the change; the old
  rows stay on disk under their old `code` and are not pooled with the new ones.
- Rows with `fee_law ∈ {unpinned_exponent, no_price}` → dropped, counted in coverage.
- Rows where the **book read and the tape read are separated by more than 5 s** → flagged and excluded
  from the canonical statistic (the canonical read must be near-simultaneous; this is the pair lane's
  `venue_skew_ms` lesson carried over).
- A market whose `feeSchedule` changes mid-sample → dropped for the day, counted.
- **History cap:** the 1 s archive is pulled at most **90 days** per run (≈2.3 MB/day); 1 m is ~2.1 MB
  **per month**. Keeps a run bounded and the nightly backup's 95 MB guard untouched.
- A tick capturing 0 rows writes a **coverage row**, never a silent gap; errors are recorded in
  `errors[]`, never swallowed.

## 9. What a PASS would license — and what it would not

**Would license exactly one sentence:** *a determined Polymarket bracket on a Binance-settled family
is buyable below `1.00 − fee` at ≥ 50 executable shares, with the edge surviving both the fee-law
sensitivity arm and a day-clustered confidence interval.*

**Would not license:** any sizing or capital decision; any change to the C-200 ladder, its rules, or
its gates; any inference about Kalshi or Chainlink families; any live lane. The live-lane decision is
card **btx4** and requires this instrument to produce a signed edge *and* a separate exposure/risk
review.

## 10. Reality checks, stated up front

- **The instrument can fail by finding nothing**, and that is the more likely outcome: if the venue
  reprices a determined leg within our sampling interval, the honest result is *no lag, no edge*
  plus a measured reprice latency.
- The venue's own **fees are usually zero on these markets** (`no_schedule_zero`), which is why §4
  carries a sensitivity arm that charges the crypto fee schedule anyway — otherwise any PASS would
  rest on "no schedule means free".
- **Listing risk:** these families rotate daily and are new; the 14-day span is bounded by what the
  venue actually lists, not by what we want to sample.
- **Clustering is not optional:** one day's High/Low decides many strikes at once; treating bracket
  rows as independent observations would manufacture significance.
- **Skew is real:** the book and the tape are read back-to-back but not simultaneously; every row
  carries both timestamps and the >5 s rows are excluded rather than trusted.
- **The window cadence starts at minute 1, not minute 0.** An edge that exists only inside the first
  60 seconds after determination is **invisible to this instrument** — a stated limitation and not a
  finding. If the window cadence returns a 100% `no_ask` fraction (§5), the honest conclusion is
  "unbuyable from minute 1 onward", not "unbuyable at every instant".
- **The venue's close is not on a fixed schedule** (observed: +11–12 min for two ladders, >45 min for
  another), so the window job's 12-minute filter is a sampling choice, not a claim about when trading
  stops.

## 11. Reproduce / operate

```bash
# sampler (writes data/btc-convergence-samples-<date>.jsonl + data/btc-convergence-coverage.jsonl)
python3 scripts/btc-convergence-sampler.py --assets all --verbose

# the pre-registered WINDOW job (minutes 1,4,7,10 of every hour)
python3 scripts/btc-convergence-sampler.py --families hourly_above,updown_1h,noon_close \
        --hours-back 1 --max-minutes-since-determined 12

# one asset / one family, anywhere (never writes into data/)
python3 scripts/btc-convergence-sampler.py --assets bitcoin --families updown_1h --out-dir /tmp/btx-scope/x

# the gate read
python3 scripts/btc-convergence-read.py

# the universe validation behind §2.1 (read-only)
python3 scripts/btc-oracle-reconcile.py --assets all --days 2 --futures --json /tmp/btx-scope/harness-all.json
```

**Instruments referenced (all keyless, read-only):** `data-api.binance.vision` (klines), Polymarket
`clob.polymarket.com/book` (books) and `gamma-api.polymarket.com/events` (market metadata only).
