# Asset audit — `akilatrades/sports-market-maker`

**Verdict: ⛔ DROP** — real research, wrong venue, and every portable measurement is already
further along in our own stack. No recommendation, no new ask.
*Audited 2026-11-23 08:23 CST · MIT · ★0 · pushed same day · report only, nothing adopted.*

---

## What it is

A one-person, real-money Kalshi **market-making** operation: three bots (NBA player-prop NO
resting orders, NFL receiving-yards, a two-sided "spread maker" that quotes both sides of wide
spreads and pairs them for <$1), one shared account-risk engine (daily $20 / total $100 loss
stops, kill switches, exchange reconciliation), a Poisson minutes→stat prop model, and a
5,181-line pre-registered `RESEARCH_LOG.md` where every test is written down before it runs.

It is not a shell. 317 Python files (122 under `tests/`, 81 under `research/`, 47 under `live/`),
47 GitHub workflows, a 2,921-line `live/prod_spread_auto.py`, and a research log that publishes
its own failures — the README opens with "My first idea failed" and "profit is not yet proven".

## Anatomy that drove the verdict

| Fact | Value | Why it matters |
|---|---|---|
| Licence | MIT (`LICENSE` read in full, no data carve-out) | borrowable — licence is *not* the blocker here |
| Stars / forks / issues | 0 / 1 / 6 open | community signal is absent; it is one person's operation |
| Created / last push | 2026-10-15 / 2026-11-23T14:18Z | alive, ~100 commits in the last 7 days |
| Repo weight | 282,754 KB — 108.9 MB of `.gz` in 3,167 files under `data/` | data committed in-repo; clone-and-read is 283 MB of mostly backfill |
| Releases / tags | 0 / 0 | no versioned surface to depend on |
| CI (`tests.yml`) | 100 successes, newest **2026-11-19T20:00Z**; then **30/30 failures** 2026-11-21T16:55Z → 2026-11-22T17:28Z | see caveat 1 — the suite is red *right now* |
| CI failure cause | 3 ruff errors (`F401` unused `numpy` ×2, `E731` lambda at `kalshi/sportsbook_primary.py:72`) | the gate fails **before** `pytest` runs; issue #121 ("Fix player pool imports so CI tests pass") tracks it |
| Tests | 122 test files; README claims "about 800 offline tests" | not executed here (read-only mandate) and **not executed by CI since 11-19** — claim unverified |

**No keys, no telemetry, no wallet addresses required to read it**; the live path needs RSA
signed Kalshi credentials (`live/check_credentials.py`, `cryptography>=42`), which is a hard
blocker for anything beyond reading — we never handle keys.

## What is genuinely measured in there

The reason this deserved a full read rather than a 5-minute drop: the numbers are pre-registered,
clustered, and negative where they are negative.

**One month live, 18 Oct – 19 Nov 2026, after fees** (`RESEARCH_LOG.md`, 2026-11-19):

| Bot | Contracts | Cost | Profit | Per contract |
|---|---:|---:|---:|---:|
| NBA props | 826 | $337 | −$2.27 | −0.3¢ |
| Spread maker | 910 | $300 | +$7.87 | +0.9¢ |
| NFL | 20 | $11 | −$2.57 | −12.9¢ |
| All | 1,756 | $648 | **+$3.04** | +0.2¢ |

Its own verdict: "No bot's result is distinguishable from zero."

**The one strong replay (pre-registered, 2025-26 regular season):** resting NO orders on player
props, 14,516 orders, 31% filled, **+3.1¢/contract, game-clustered t 4.1** (4,541 fills, 854
games), and the adverse-selection counterfactual stated openly: had *every* order filled the
book would have made **+11.3¢**; the orders that did **not** fill would have made **+15.0¢**.
Fills are selected against you, and it still nets positive in-sample.

**Its own best negative result:** `v7` lost **$11.00 on 174 contracts**; ~85% of those fills came
at spreads under 10¢ versus 10% for the version the rule was based on, because fill probability is
strongly spread-dependent — **4.4% of orders filled at <10¢ spread against 0.1% at ≥20¢**. The
log records v7 as "a failure of that rule at tight spreads, not a test of esports". That is the
most transferable sentence in the repo, and it is a *mechanism*, not code.

**Structure checks, all negative:** ladder arbitrage 6 of 116,307 hourly snapshots (0.2¢ avg —
Kalshi keeps its ladders consistent); correlated double-doubles −1.7¢/contract (t −0.7) because
Kalshi already prices the correlation (Brier 0.1331 mid vs 0.1327 fair).

## Fit table vs our roadmap

Proven capability first, then the row. Every ⚪/❌ names the card, or says none does.

| Component | Where it lives | Fit | Card / evidence on our side |
|---|---|---|---|
| Live **fill share / capture** (`Σ min(fills, min(through,size)) / Σ min(through,size)`, plus a cautious `E[min(Binomial(through,0.25), size)]` benchmark) | `live/prod_spread_auto.py:1149` `fill_share()` | ⚪ **already ours, further along** | `src/lib/copy-cost.ts:189 measuredFillShare()` (band-static weights from the 2026-10-10 freeze-thaw read) + `src/lib/fill-intent.ts` (`FillIntent` / `PaperTrade.intentPrice`, card `c200-maker-fill-assumption` option (b)); reader `scripts/fill-vs-intent.ts` |
| **Queue position at placement** (`GET /portfolio/orders/{id}/queue_position`) | `live/prod_spread_auto.py`, `queue.csv` | ❌ **not portable** | Requires an authenticated order in a real book. We place none — paper-only. Nearest in-flight equivalent is the polythought-go book-walk taker fill, **awaiting approval 24d** (`drafts/asset-audit-polythought-go-20261029.md`) |
| **Adverse-selection markouts** at 10/30/60 min, written to `measurements.jsonl`, explicitly "never used for trading" | `live/prod_spread_auto.py` (`MARKOUT_HORIZONS`, line ~1221) | ⚪ **already carded and measured** | Card `ml-u1-conditional-fill-model` (In Progress) is literally "p(fill \| band, hour, size, ttr, activity, vol) **+ adverse-selection markout**", and its forward read already reproduced the sign: 18/339 (5%) reachable within 5 min, 65/339 (19%) within 1 h, against an archive 74.3%/81.1% |
| **Pre-registration protocol** (write the test, then the result, never edit the plan) | `RESEARCH_LOG.md` (5,181 lines) | ⚪ **concept, already our practice** | The `copybot-research-agent` pre-registration shape; two worked self-corrections worth citing as prose models (line ~1650 "capture, not fill share" — four measurement defects found and fixed; and the v7 stop above) |
| **Kalshi fee model** + per-series maker-fee list (`KXNCAAFSPREAD` charges 0.0175·P·(1−P)) | `live/spread_policy.py`, log 2026-10-22 | ❌ **venue retired** | Card `retire-kalshi-copy-routing` — user decision, structurally unsatisfiable |
| **Sports prop model** (Poisson expected-minutes → stat marginals, sportsbook-consensus veto) | `markets/nba/`, `markets/nfl/` | ❌ **no lane, no card** | No sports lane exists and none is carded; the veto needs a paid/whitelisted sportsbook feed (its own Idea 2 was "not testable for free") |
| **Polymarket US quote replay** | `research/polymarket_us_replay.py`, `docs/POLYMARKET_US_QUOTE_REPLAY.md` | ❌ **not our venue** | US exchange ≠ international Polymarket; the doc self-labels its payoff `not_trading_profit` and refuses to rank venues on all-filled hypotheticals |
| **Two-sided wide-spread quoting** (pair pays $1 for <$1) | `live/spread_policy.py` | ❌ **no card** | A Kalshi maker strategy with 4.4% fill at tight spreads; nothing in our stack quotes, and it cannot without keys |

## The one cross-venue fact worth keeping

`docs/POLYMARKET_US_QUOTE_REPLAY.md` states that on the Oct 19 2026 **Polymarket US** maker
schedule the lowest volume tier earns **zero standard maker rebate until $10M prior-month maker
volume**. Checked against us: it does not apply — our PnL never assumes a rebate. Maker credit is
priced as 2¢ of price improvement per share (`src/lib/copy-cost.ts:107`), and the only `rebate`
fields in `src/` are parse-only (`fee-capture.ts:72` reads `rebateRate` from the venue's published
schedule; `print-types.ts` names the label). Nothing in a decision path reads either.
**Verified absence, recorded so a future fee review does not have to re-ask it.**

## What it would cost

- **Adopt any code: not possible.** Live path is RSA-keyed Kalshi execution on a funded account;
  research scripts are keyless but Kalshi-only.
- **Reimplement the ideas: ~0 cost, because there is nothing left to reimplement.** The capture
  metric, the intent-vs-entry gap, the conditional fill model and the adverse-selection markout
  are all already instrumented, and `ml-u1` reports a *measured* reachability well below the
  donor's in-sample numbers (18–19% vs its 31% fill rate on a different venue and rule).
- **Reading cost: ~1.5 h** (this audit). Reading the research log's method sections is the only
  thing with continuing value.

## Risks

1. **The CI badge is red right now** (30/30 failures since 2026-11-21T16:55Z). Cause is three ruff
   lint errors, so this is a *gate* failure, not a logic failure — but it means `pytest` has not
   run in CI since 2026-11-19T20:00Z, and the README's "about 800 offline tests" is unverified at
   head. Do **not** treat this repo as a green-suite donor on the strength of its badge.
2. **Repo weight:** 283 MB, 3,167 `.gz` files and 65 MB of CSV committed under `data/`. Any
   consumer clones the backfill, not the code.
3. **Single-operator, zero-star, no releases/tags.** Bus factor 1; the "rule" set is private
   intent (`STRATEGY_VERSION` strings), so there is no stable interface to depend on.
4. **Its profitable replay is in-sample on a venue whose economics differ from ours** (maker fee
   schedule, queue mechanics, prop markets). Even if we wanted the strategy, the 31%-fill /
   +3.1¢ result would need a Polymarket replay from scratch — we have no sports coverage to
   replay it against.

## Recommendation

**Drop.** Queue it as read, record no ask. Rationale, in order: the live asset requires keys on a
**retired venue**; the measurement apparatus is **already in our stack and ahead of it** (cards
`ml-u1-conditional-fill-model`, `c200-maker-fill-assumption`, `profit-fill-never-reachable` — the
last of which already found 96% of C-200's booked profit sitting on legs the market never brought
to our price in 24h); and its own one-month live result is "not distinguishable from zero", stated
by the author.

**What would change this:** if a Polymarket maker-quoting lane is ever opened (i.e. `phase-d2-fill-model`
reopened with real orders), the *design* to copy is `fill_share()`'s two-benchmark shape —
through-normalised capture plus a cautious binomial counterpart — because it answers "was the
replay's fill assumption optimistic, and by how much" without needing our own fills in the
numerator. That design is already the shape of `ml-u1`; this repo is a second independent worked
example of it, nothing more.

**Roadmap:** no card written and no `note` appended — nothing here is a new work item, and this
audit's mandate is the report + queue record only. If a future pass wants the precedent recorded,
the block to paste is: `AUDIT INPUT (2026-11-23, drop; drafts/asset-audit-sports-market-maker-20261123.md):
MIT Kalshi sports maker, keys + retired venue; capture/markout design already cards ml-u1 + c200-maker-fill-assumption; no new item.`

## Honest caveats

- **I did not run their suite** (read-only, no candidate execution). The "800 tests" figure is
  theirs, and CI's `pytest` step has not executed since 2026-11-19 — so treat 800 as a claim.
- **I did not verify the Kalshi fee constants against Kalshi's docs today.** `docs.kalshi.com`
  publishes fee *rounding* mechanics (`fee_rounding.md`: six-decimal amounts, `ceil` to the micro-
  dollar, per-order accumulator) but no page stating the 0.07·P·(1−P) schedule at the URLs tried.
  What I can say: the repo's own live `fee_cost` fields printed 0.0175·P·(1−P) on `KXNCAAFSPREAD`,
  i.e. its arithmetic agrees with what the venue actually charged it — the strongest tier
  available — while the 0.07 base rate itself remains `unverified against the venue's page`.
- **Their in-sample replay (+3.1¢, t 4.1) is not a claim about our venue** and I have not
  restated it as an edge anywhere above.
- Numbers quoted from `RESEARCH_LOG.md` are the author's own; I verified the code paths that
  produce the fill-share and markout figures (`live/prod_spread_auto.py:1149`, `~1221`) exist and
  are labelled measurement-only, but I have not recomputed their P&L from raw fills.
