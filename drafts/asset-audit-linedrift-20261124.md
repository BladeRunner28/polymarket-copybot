# Asset audit — `jman563412/linedrift`

**Verdict: ⚪ WATCH** — nothing to vendor (live path needs Kalshi keys, no CI, one commit), but the
**settlement-scorecard method** is a real gap in our odds lane and the **negative result** is a usable
prior. One read-only replay recommended.
*Audited 2026-11-24 08:20 CST · MIT · ★0 · created today, single commit · report only, nothing adopted.*

---

## What it is

A Python CLI + MCP server that compares sports lines across **Kalshi, Pinnacle (via the PinnAPI
reseller), SX Bet and Polymarket**, de-vigs the sportsbook/exchange references, and scores Kalshi's
fee-adjusted price against each one. Ships an evaluation harness that records every comparison and
judges it against settled results.

The README is unusually honest for this beat: it opens by saying the harness "is what showed there's no
reliable edge", states the account ceiling is "cents per week", and says the deliverable is evidence to
decide whether funding further is justified — "not a profit engine". No return promises anywhere.

## Anatomy that drove the verdict

| Fact | Value | Why it matters |
|---|---|---|
| Licence | MIT (`LICENSE`, 1,067 B) | borrowable with attribution — **not** the blocker |
| Stars / forks / issues | 0 / 0 / 0 | no community signal at all |
| Created / last push | 2026-11-24T05:13Z / same minute | **dumped-once**: one commit, "Initial public release" |
| Substance | 558 KB Python / 77 files; `cli.py` 50 KB, `execute.py` 40 KB, `store.py` 20 KB | real code, not a stub — ~2 months of private work published at once |
| Tests | 39 `test_*.py`, ~400 KB of captured live-API fixtures | substantial, and *unverified* |
| CI | **`total_count: 0` workflows** | nothing ever runs those 39 files — I did not clone or execute by mandate, so test presence is a claim |
| Recorded data | **no `data/`/`*.jsonl` shipped** — store is runtime SQLite | the headline Results table is **not reproducible from the repo** |
| Key requirement | `kalshi/auth.py` = RSA private key for the live order path only | read-only comparison paths are keyless (Polymarket Gamma/CLOB, SX, Pinnacle reseller) |

## What I verified in source (not from the README)

**Fee math — matches ours, with one refinement.** `src/linedrift/fees.py` implements
`ceil(M · rate · C · P · (1−P))` at quantum `$0.0001`, taker 0.07 / maker 0.0175, Decimal-only (comment
notes the float product `0.07*100*0.50*0.50` is `1.7500000000000002`, whose ceiling is a step too high).
It justifies the sub-cent quantum against **four production fills** (0.015232→0.0153, 0.003325→0.0034,
0.00380625→0.0039, 0.00124→0.0013), explicitly contradicting the whole-cent ceiling the docs once
described. Our `scripts/kalshi-crossvenue-read.py:215` and `scripts/kalshi-maker-read.py:114` carry the
same two rates with **no ceiling at all**, so the delta is at most $0.0001/contract — a reconciliation
detail, not a wrong number.

**De-vig — we already have it.** `pinnacle/devig.py` is multiplicative (proportional) de-vig with a
justified choice of method and a guard-digit trick so equal inputs de-vig to exactly 0.5. Our
`scripts/bookmaker-odds-record.py:72` already de-vigs 1/price and takes the **median** across 60+ books
with measured per-sport margins (soccer 8.7%, basketball 8.1%, …). Theirs normalizes a single book's
two-way line. Ours is the stronger construction for the same job.

**Reference-book trust gate — this one is genuinely new to us.** `detect/divergence.py`:

```
MIN_REFERENCE_DEPTH = 50   # contracts at touch, both sides
MAX_REFERENCE_SPREAD = 0.10
sx_implied_prob(book): reject the reference mid unless spread <= 0.10 AND min(bids[0].size, asks[0].size) >= 50
```

A venue's mid is only allowed to act as *fair value* if that venue's book is tight and deep; otherwise
the comparison is not made. We gate our **own** candidates on spread (`MAX_SPREAD = 0.06`, RuleSet v73 in
`scripts/profit-cheap-ask.py:90`) but I found no equivalent gate on the **reference** side of
`kalshi-crossvenue-read.py` — it records `yes_bid_size_fp`/`spread` and prints them, then compares anyway.

**Net-edge split — mostly a discipline we should name.** `detect/base.py` scores both directions from one
reference and keeps the better side, with the side flip done correctly (NO takes at `1−bid`, rests at
`1−ask`), fees charged at the price actually paid, and the maker edge measured **at the resting price**,
not the taker price ("pricing it at the taker price understates it by the spread"). It also skips a
longshot outright — a NO on a 90% favourite is a 10% bet, gated by `win_prob < MIN_WIN_PROB`. And
`keep_no_edge=True` records the *skip* side too, with the reason stated: "recording only the cheap side
would bias the sample."

**Their result (self-reported, data not shipped).** From recording every scan 2026-09-13 → 2026-11-23
(NFL, NCAAF, NBA, UFC):

| reference | games | Brier (0.25 = coin flip) | taker avg/position (95% range) |
|---|---|---|---|
| SX Bet | 445 | 0.227 | −2.65c (−5.08c to −0.22c) |
| Pinnacle | 333 | 0.236 | −2.03c (−4.77c to +0.72c) |
| Polymarket | 119 | 0.196 | −3.07c (−6.25c to +0.10c) |

References are well calibrated (a 50% call happens 49–50% of the time); **the trade is negative on every
row**, and only the maker rows and two taker rows have ranges touching zero. They also flag the maker
numbers as optimistic: "fills are assumed on any print through the bid, and adverse selection isn't
modelled."

## Fit table vs roadmap

| Component | Card | Verdict |
|---|---|---|
| Reference-book trust gate (depth ≥50, spread ≤0.10) before quoting a gap | `kalshi-crossvenue-read-tool` (Done), `phase-data1` (In Progress) | ⚪ **concept, cheap** — ~40 lines in the existing read; would kill phantom gaps outright |
| Settlement scorecard: judge every comparison against settlement, report Brier + fee-adjusted net cents + CI | **`phase-data1`** — no card asks for it and we do not have it: `scripts/gaps-digest.py` **counts** gaps and names the biggest divergence; nothing scores one | ✅ **adopt the method** (not the code) — this is the recommendation |
| Maker row as a cautionary prior for our own maker study | `kalshi-maker-read-prereg` (Scheduled) | ⚪ **prior to record**: a 333–445 game record where touch-through fills produced ≈ −0.2c to −2.8c |
| Sub-cent fee ceiling (`ROUND_CEILING` to $0.0001) | none needed | ⚪ **note** — ≤$0.0001/contract; matters only for 4-dp reconciliation |
| Sports-series IDs from Gamma `/sports` (NFL 12185, NBA 10345, NCAAF 12756, UFC 38, verified 2026-10-27) + the UA-403 note (2026-10-11) | none | ⚪ **constant**, only if sports enters scope |
| Pinnacle via PinnAPI | `phase-data1` | ❌ **redundant** — we already record de-vigged bookmaker consensus (`bookmaker-odds-record.py`) and live gaps (`odds-gaps.py`, 145 KB through 2026-10-28); adding a second reseller key buys nothing |
| Live execution (`execute.py` 40 KB, `kalshi/auth.py`) | — | ❌ **never** — RSA private key, and we never handle keys |
| MCP server (17 KB) | — | ❌ duplicate of our own tooling surface |
| Team/school name aliasing (matcher.py 6.8 KB) | — | ❌ not portable: only needed if we carry a sports book-generation lane |

## Recommendation (read-only, pre-registered shape)

```
REC — Score the odds-gap lane against settlement instead of only counting it
  Hypothesis:   the sportsbook-vs-Polymarket gaps we log in data/odds-gaps.jsonl do not survive
                both venues' fees, so the lane is recording-only and should stay that way.
  Measurement:  new scripts/odds-gaps-scorecard.py, read-only replay over the existing 145 KB
                data/odds-gaps.jsonl joined to settled Polymarket resolutions in prisma/dev.db;
                emits per-sport Brier for the reference + median net c/position after both fees,
                with a bootstrap 95% range. Expected n ≈ 30–80 settled rows (must state n).
  Decision rule: if median net after fees <= 0 on >= 30 settled rows, close the sports leg of
                phase-data1 as recording-only and stop widening it; if > 0 with the 95% range
                excluding 0, open a promotion measurement (REC in the weekly).
  Cost:         ~2 h, read-only over data we already hold; zero live risk.
  Reversibility: new script only — delete the file; nothing touches a rule, size or lane.
```

Cost to adopt anything else: zero (no code accepted). The `⚪` rows are notes, not work.

## Risks / not-portable

- **Keys**: any live path needs a Kalshi RSA private key. Out of scope permanently.
- **Unverifiable quality**: 0 CI workflows, one commit, no shipped recording data. The Results table is
  self-reported; the *method* is visible and sound, the *numbers* are not independently checkable.
- **Single-author, 1 day old**: could be abandoned tomorrow. Do not depend on it; take ideas, not code.
- **Reseller dependency**: PinnAPI (Pinnacle) is a paid third party, not an official venue API.

## Honest caveats

- I did not clone or execute anything (read-only mandate), so "39 test files pass" is unverified — and
  with no CI, nobody has ever verified it either.
- The negative result is their own record, not a replication. It is still the largest-sample evidence I
  have found on the "reference says X, venue says Y → trade Y" idea we would be testing in `phase-data1`.
- The trust-gate thresholds (50 contracts, 0.10 spread) are *their* choices for Pinnacle/SX liquidity on
  Kalshi sports markets; they are not calibrated for our temperature/WTI or macro pairs.
