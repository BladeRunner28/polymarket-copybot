# Asset audit — `mbordash/DRADIS` (2026-10-15)

**VERDICT: `watch` — AGPL-3.0 + live-execution keys ⇒ read-only concept source. One measurement worth
running (horizon-scaled admission margin); one row where they independently arrived at a gate we
already ship (the taker-fee curve), and one where their fix for a bug is a stronger version of a bug we
still have (one rate source for the gate and the accounting).**

Queue id: `mbordash/DRADIS` · audit worker run 2026-10-15 09:26 CDT · read-only: no clone, no install,
no execution of candidate code.

---

## 1. What it is

A single-author, AGPL-3.0 **live** prediction-market trading engine in Rust (86% of the tree; 106 `.rs`
files ≈ 5.4 MB) for three venues — Polymarket International (self-custody CLOB), Polymarket US retail,
and Kalshi — with 10 strategies ("Vipers": fairvalue, maker, arbitrage, basis, bookline, convergence,
momentum, time-decay, trend-reversal, GBoost ML), scout layers ("Raptors": price, funding, derivatives,
tide, horizon, sports book-consensus, tennis), a Next.js operator UI ("Control Tower"), and an LLM
advisor (Ollama/OpenAI/Anthropic) that can propose — or, under a tiered policy, apply — config changes.
It is also the free half of a commercial product: the README sells a prebuilt AWS Marketplace AMI under
a **commercial license**, with the source route licensed AGPL-3.0.

## 2. Anatomy facts that drove the verdict

| Fact | Value |
| --- | --- |
| Licence | **AGPL-3.0** (`LICENSE`) + commercial dual-license via AWS Marketplace ⇒ read-only, reimplement concepts |
| Stars / forks / issues | ★27 · 14 forks · 1 open issue (community signal is thin) |
| Created / last push | 2026-03-22 / **2026-10-15** (alive, committing today) |
| Size | 218 files, 5,922 KB; `.rs` 5,431 KB/106f, `.tsx` 589 KB/30f |
| Structure | tests=yes · CI=yes · docker=yes · lockfile=yes · `.env.example`=yes |
| Keys required | **yes** — `POLYMARKET_PRIVATE_KEY`, `POLYGON_RPC_URL`, `KALSHI_API_KEY_ID` + RSA-PSS PEM, `ODDS_API_KEY`, `LIVETENNIS_API_KEY`, Telegram tokens |
| Telemetry markers | none detected in README; no analytics claims |

**Substance matches the claim.** Unlike the usual hype-readme candidates, the code is the product:
`#[test]` appears in ~78 of the 106 Rust files (`gh search code`), the CI builds a **3-venue feature
matrix** (`intl_clob` default / `us_retail` / `kalshi`) with the reason documented in the workflow:
checking only the default features is *"what let a pull request touching 40 lines of
`src/venues/us/trader.rs` pass every check without that file ever being compiled — green CI that had not
read the change."* The best single artifact is a regression test pinned to **real production entries**:
`floor_priced_longshots_lose_their_edge_and_every_live_favorite_is_unchanged` freezes 10 live entries
(2026-09-09→09-12, σ solved from each logged observation) and asserts that a change to the σ floor must
not reprice a single favorite while the two longshots must lose their edge. That is the same
"frozen set a change must not move" discipline our own card gates use.

**But** it is a keys-required live bot with a self-custody wallet path, and our lane is paper-only and
never handles keys. Nothing here can be vendored into the live lane; the value is arithmetic,
thresholds and engineering doctrine — which is what the rows below grade.

## 3. Verified machinery (read in source, or greped against our own)

1. **Taker-fee curve — identical to ours, no gap.** `fairvalue_impl.rs::fee_frac(price)` delegates to
   `venues::taker_fee_per_share(price)` = `rate · p · (1−p)`. Ours,
   `src/lib/scoring/price-edge.ts::takerFeePerShare(price, feeRate) { return feeRate * price * (1 - price); }`
   — the same function. **The gap is not the curve, it is the rate source** (row 2).
2. **One rate source for gate AND accounting — their bug, our bug in a different place.** Their comment:
   the fee used to read a separate `CRYPTO_FEE_RATE = 0.072`, *"so the entry gate and the accounting
   disagreed on every venue, by 20% on Polymarket US, and editing the rate in the Control Tower moved
   only the accounting."* Ours is the mirror image: the gate prices the fee from a **slug-keyword
   proxy** (0.05 default / 0.07 crypto / 0.04 politics) while the venue publishes structured
   `feeType` + `feeSchedule.rate` — measured on 40 top-volume markets, **18/40 (45%) disagree**
   (`paper-ledger-fee-fidelity`, re-measured 2026-09-28). Their fix (single source, read by both sides)
   is the shape of the fix that card already pre-registers.
3. **Settlement dominance — corroborates a measurement we already own.** Their exit rule leans on
   *"settlement pays $1.00 with zero exit fee (strictly dominates a taker TP)"*, and they record having
   paid a taker fee twice when an exit crossed the bid. We already have this: our decision dataset
   treats `status='resolved'` as settling at 0/1 **with no trade ⇒ no exit fee**
   (`scripts/build-decision-dataset.py:190`, `drafts/c200-taker-fee-measurement-2026-09-09.md`), and the
   maker-entry/exit-fee-only counterfactual is priced in `drafts/fee-maker-calibration-20260925.md`
   (C-200 maker entry: **+$1,818**). **No new information** — recorded as corroboration, not as input.
4. **Horizon-scaled edge requirement — no analogue in our stack.** `required_edge(dc, secs_left)`
   linearly tapers MIN_EDGE→BASE_EDGE inside a taper horizon, then grows as `√(secs_left / taper)`
   (capped, floored at BASE), with the stated reason: *"the further out settlement is, the less the
   1-hour realized-vol window can be trusted, so mid-session entries on daily markets need a much
   larger discount than endgame entries."* Verified absence here: `timeToResolution` exists in our
   book only as (a) a lane flag (`timeToResolutionHours` in `scoring/trade.ts`, the short-TTR band note
   in `band-size.ts`) and (b) a close-time estimate (`open-mtm-horizon.ts`); our admission margin is a
   **flat** number (`PRICE_EDGE_SPEC_V1.margin = 0.05`, status `shadow`). Grep for any taper/horizon-
   scaled margin in `src/lib`: **zero hits**. No roadmap card asks for one (see §5).
5. **Their own loss numbers (their words, not independently verified).** The fairvalue doc-comments
   report a net loss concentrated in **14 stop exits (−$14.54)** and a window where *"fees were the
   entire loss"* (label: *"−$0.07, fees −$1.05"*); they also state the fee curve collapses at extreme
   prices, so longshots that clear a naive edge test still lose. A repo that publishes its own losses
   and its own removed silent no-ops is the highest-signal kind of donor — and the shape of the loss
   (fees and stops, not signal) is what our own C-200 fee work keeps finding.
6. **Same-market complement arb (`arbitrage_impl.rs`, 644 lines) — a genuine capability we do not
   have, but out of our current paper lane.** Rests a maker bid on **each leg of one market** (YES+NO),
   exits FAK at a combined-bid threshold (0.995), and guards the real failure mode (one leg fills and
   the other runs): *both* legs must have a seller to rehedge against, the dominant leg's bid must clear
   a conviction floor (decided markets only), each leg is capped, plus an ask-gap ceiling and a
   complement-leg ask ceiling as an orphan guard. Their recorded incident is a venue-level move that
   filled the wrong leg. Our repo has **no arb/complement detector at all** (grep `arbitrage` in
   `src/lib`: 0 hits; `complement` appears once, in `rules.ts`); the nearest card is `phase-c`
   ("Constraint-based cross-venue arb", Backlog) — which is cross-venue, a different mechanism.

## 4. Fit table vs our roadmap

| Component (donor file) | What it is | Fit here | Card that asks for it |
| --- | --- | --- | --- |
| `venue::taker_fee_per_share` / `fee_frac` | `rate·p·(1−p)` fee at the ask | ✅ **already ours, byte-equivalent** — no work | `paper-ledger-fee-fidelity` (Backlog) |
| Single rate source for gate + accounting | their fix for gate-vs-accounting divergence | ⚪ **concept**, feeds the fee card's pre-registered fix shape | `paper-ledger-fee-fidelity` (Backlog) |
| `settlement pays $1.00 with zero exit fee` | hold-to-settlement dominates a taker exit | ❌ **not portable / already measured by us** | `paper-ledger-fee-fidelity`, `fee-maker-calibration` draft |
| `required_edge(secs_left)` | margin scaled by time-to-resolution | ⚪ **concept, no card asks for it** — measurement proposed in §5 | none (new card text in §7) |
| `arbitrage_impl` complement arb + orphan guards | same-market YES+NO maker arb | ⚪ **concept only** (we are paper-only; no detector exists) | nearest is `phase-c` (cross-venue, different mechanism) — say so, do not claim it |
| CI 3-venue feature matrix + the pinned production-entry regression test | engineering doctrine, not code | ⚪ **concept** — the frozen-set-a-change-must-not-move discipline we already use in card gates | none needed |
| LLM advisor / OpenClaw / Telegram layer, Control Tower UI, GBoost ML tail, sports+tennis Raptors | agent + UI + third-party-keyed feeds | ❌ **not portable** — duplicates our research bot, alerting and dashboard; the Raptors need `ODDS_API_KEY` / `LIVETENNIS_API_KEY` | — |
| Venue execution clients (`src/venues/*/trader.rs`, `auth.rs`) | signed order placement | ❌ **not adoptable** — keys required + paper-only invariant | — |
| `docs/QUANTUM.md`, AWS Marketplace AMI packaging | vendor funnel | ❌ not relevant | — |

## 5. Recommendation (measurement only — nothing is changed by it)

```
REC — Horizon-scaled admission margin: does a time-to-resolution-scaled edge bar beat the flat 0.05?
  Hypothesis:   legs admitted on a FLAT 0.05 margin but inside a scaled bar (larger discount required
                the further out settlement is) carry realized net PnL per leg at or below zero.
  Measurement:  read-only replay over the frozen settled C-200 leg set (n stated by the run; the
                2026-09-23 wallet-selection read used 1,962 settled legs / 102 wallets). Join
                MarketSnapshot.timeToResolution to each leg, recompute admission under (a) the current
                flat margin and (b) a taper-then-√ horizon scale, and report the FLIP SET's count,
                realized net PnL per leg and win rate, with a wallet-clustered CI.
  Decision rule: if the flip set (admitted flat, rejected scaled) has mean realized net PnL per leg < 0
                with a wallet-clustered CI excluding 0 at n ≥ 30, adopt the scaled margin as a SHADOW
                spec for a further 30-day window; else drop.
  Cost:         ~half a day (one replay script + one artifact; no live path, no rule touched).
  Reversibility: delete the shadow spec / its flag — no stored value changes.
```

Deliberately **not** proposed: the complement-arb detector. It is a different mechanism from `phase-c`,
it needs intraday two-leg book capture to be measurable at all, and our book is paper-only; pricing a
new mechanism during an open measurement window is exactly the move the standing rules forbid. It is
recorded as a concept so a future `phase-c` kickoff can pick it up.

## 6. Honest caveats

- **AGPL-3.0**: read-only. Any code taken from this repo would copyleft the adopting stack — the
  precedents for this verdict are the Homerun (AGPL) and Octagon audits. Concept reimplementation is
  the only path, and it needs its own tests.
- **Keys everywhere**: the live paths need a Polymarket private key and Kalshi PEM. We never handle or
  adopt keyed code — this repo's execution layer is permanently out of scope, not merely deferred.
- **It is a sales funnel**: free AGPL source + paid Marketplace AMI + "make sure to regularly pull
  updates as our own LLM advises on config". Treat the README's performance framing as marketing.
- **Thin community signal**: ★27 with one author. The star count is not a maintenance signal; the CI
  matrix and the production-pinned tests are the real quality evidence.
- **Their numbers are their logs**, not an audited track record; we did not run their engine. Nothing
  in this audit is a return claim — the only numbers quoted from *them* are marked as theirs.
- **No clone, no install, no execution** was performed (candidate-code hygiene); every claim above is
  from source read over the API or from a grep of our own tree.

## 7. Registry blocks (NOT applied — see the note below)

This run is constrained to the audit draft plus the queue record, so nothing was written to
`data/roadmap.json`. Ready to paste if you want it:

```
AUDIT INPUT (2026-10-15, audit worker; drafts/asset-audit-dradis-20261015.md): mbordash/DRADIS
(AGPL-3.0, ★27, keys-required live engine) — read-only concept source. Its taker-fee curve is
byte-equivalent to ours (`rate·p·(1−p)`), so the fee CURVE is not a gap; their gate-vs-accounting
single-rate-source fix matches the shape `paper-ledger-fee-fidelity` already pre-registers. Its
hold-to-settlement dominance claim corroborates our own measured no-exit-fee-on-settlement model —
no new information. NEW: `required_edge(secs_left)` scales the entry margin by time-to-resolution
(taper then √, capped); our margin is flat and no card asks for a scaled one. Proposed read-only
measurement (replay the frozen settled C-200 legs; flip-set realized net PnL per leg, wallet-clustered
CI, n ≥ 30) awaits the user's approval via the queue.
```

Proposed new card (only if the measurement is approved — not created by this run):

```json
{
  "id": "ttr-scaled-margin-measurement",
  "title": "Measure a time-to-resolution-scaled admission margin against the flat 0.05 (concept from the DRADIS audit)",
  "column": "Backlog",
  "effort": "~half day (read-only replay + artifact)",
  "dates": "Carded 2026-10-15 (DRADIS audit input)",
  "gate": "VERIFY: on the frozen settled C-200 leg set, the flip set (admitted at the flat margin, rejected by the scaled margin) has mean realized net PnL per leg < 0 with a wallet-clustered CI excluding 0 at n ≥ 30. FAILS IF: the flip set is n < 30 or its CI includes 0 — then drop, do not re-propose without new legs.",
  "note": "WHY: DRADIS's required_edge widens the entry bar as settlement gets further away because a short realized-vol window cannot be trusted mid-session; our admission margin is a constant and TTR is used only as a lane flag / close estimate. Read-only; nothing is adopted without a separate approval.",
  "tags": ["gate", "measurement", "ttr", "audit-input"]
}
```

Dashboard: http://localhost:3013/drafts/asset-audit-dradis-20261015
