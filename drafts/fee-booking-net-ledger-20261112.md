# Fee booking in the ledger and in the ladder advance — APPLY-READY PROPOSAL

http://localhost:3013/drafts/fee-booking-net-ledger-20261112

**Card:** `fee-booking-net-ledger` (Backlog, Lane A) · **Approval:** `apr-fee-booking-net-ledger`, approved
by the operator in the approvals inbox at 2026-11-12T16:10:40Z · **Kanban:** `t_2a23291d`
**This run:** PROPOSAL ONLY. No `apply-vNN` run, **no write to `prisma/dev.db`**, no RuleSet row read or
written, no rule/size/gate/booking/threshold changed, nothing merged to main. The apply is the operator's step
and it is at §7, in five commands.

**In this run:** `drafts/` this file · `src/lib/fee.ts` (new, imported by nothing live) ·
`scripts/backfill-fee-usd.ts` (dry-run by default, exercised on a probe DB) · `tests/fee.test.ts` (12 tests,
green) · `scripts/profit-fee-booking-preflight.py` (new read-only dry run). `scripts/fee-ladder-reread.py`
already on main since 2026-11-02 and re-run today.

---

## 1. The recommendation, and the one consequence to read first

**Book it.** The fee is a real, large, currently invisible cost and the scoreboard is the thing it corrupts. But
one consequence is not optional and the operator should see it before the first command in §7:

> **Booking the fee in the advance basis moves the ladder's first cleared window.** The window that first
> cleared the $1,750 rung — **2026-09-21** — got there by **$48.78 gross**, and on net it **fails by $73.25**
> (fee $122.03 on that window). The first clearing window becomes **2026-09-22**, and the day-level rung
> verdict is Phase 1 on **7 of 100 days** instead of 8. No window has cleared a rung at all since
> **2026-10-04** — under either basis.

That is the honest reading of the book, and it is the reason the pre-registered acceptance rule exists — see §3,
where it **fails again today** on the 30-day window. The approval was given anyway; this document is the
apply-ready form of it, with that conflict left visible rather than argued away.

Five switches, each with the number that changes and its revert, are at **§8**. The only one I would split out
is §8-D3 (the ladder basis) — everything else is pure accounting repair.

---

## 2. What moved since the card was written (the delta, not a restatement)

The card's headline was "27% of measured edge is unbooked", measured 2026-11-02. Ten days later the same
instrument reads **34.4%**, and the direction is not noise: the fee is a function of **notional and price**
(`rate × (1 − p)`), not of edge, so when the edge shrinks the unbooked share of it **grows**.

| figure (bet-level, first leg per wallet/market/outcome) | 2026-11-02 (card) | 2026-11-12 (today) |
| --- | --- | --- |
| finished bets / notional | 4,890 / $52,494 | **5,175 / $56,558** |
| gross ROI | +8.31% | **+6.73%** |
| modelled fee, % of notional | 2.25% | **2.32%** |
| net ROI (entry fee) | +6.05% | **+4.41%** |
| **unbooked share of measured edge** | **27.1%** | **34.4%** |
| $/1k-capital-day gross → net | 8.52 → 6.21 | **7.08 → 4.64** |
| STANDARD $/1k-capital-day | 3.63 → 1.86 | **2.90 → 1.16 (−60.0%)** |

And the last 30 complete settled days are the argument in one line — the fee alone now exceeds the PnL:

| window (BANKROLL_200, 30 complete settled days 2026-10-13…2026-11-11) | value |
| --- | --- |
| gross booked PnL | **−$148.30** |
| modelled entry fee | **$278.62** |
| net after fee | **−$426.92** |
| fee as % of gross | **187.9%** (sign-undefined; the denominator is negative) |

A book whose month is `−$148` gross and `−$427` net is not a scale problem — it is a scoreboard that reports
the venue never took a fee.

---

## 3. The pre-registered clause, re-measured today (this is the honest part)

The card's own decision rule (2026-11-02, unchanged):

> **ADOPT** when the modelled fee is ≥10% of booked PnL **AND** a 30-day net re-read flips the rung verdict on
> ≥1 day. **REFUTATION:** if venue-truth pricing puts the finished book's fee below $600, or a 30-day net
> re-read never flips a rung day, withdraw and keep the fee as a one-line EOD print.

Re-run today, on today's book, on the gate's own population (trailing 7 SETTLED days of `BANKROLL_200`,
bucketed by local day of `closedAt ?? resolvedAt`, advance test `sum ≥ rung × 7`):

| clause | pre-registered test | measured 2026-11-12 | result |
| --- | --- | --- | --- |
| 1 | fee ≥ 10% of booked PnL | **34.4%** bet-level (entry fee $1,311 on $3,807 booked); venue-truth bases $3,245 / $3,790 / $5,261 ≫ $600 | **MET** |
| 2 | 30-day net re-read flips ≥1 rung day | **0 of 30** (leg basis, bet basis and the per-day variant) | **FAILED** |

90-day robustness: **1 flip in 90** — 2026-09-21, the Phase-1 advance itself:

| window end | basis | gross 7d | fee 7d | net 7d | rung G → N | flip |
| --- | --- | --- | --- | --- | --- | --- |
| 2026-09-21 | leg | 1,798.78 | 122.03 | 1,676.75 | 1 → 0 | **YES** |
| 2026-09-21 | bet | 1,751.27 | 107.93 | 1,643.34 | 1 → 0 | **YES** |

**So the rule still says no, and the operator said yes.** Both facts are recorded here because the apply step
should not look like the clause passed. What changed in the operator's favour is §2: over the last 30 days the
fee is **more than 100% of a negative gross PnL**, which is a scoreboard-integrity reason rather than the
rung-verdict reason the rule was written around. If the operator wants the withdrawal instead, the standing
state is one line: *leave `realizedPnl` gross, close the card on its own refutation* — and the column, the
helper, the backfill and the tests in this run all become dead files to delete.

---

## 4. The design that ships

Four nullable columns, one pure helper, two write sites, five read sites, two independent flags. The fee never
touches `realizedPnl` — that is what keeps every historical number, the PnL rollup and the cumulative series
byte-identical, and it is what makes the revert a flag rather than a data migration.

### 4.1 Schema (`prisma/schema.prisma`, `model PaperTrade`, after `fillResolvedAt`)

```prisma
  // FEE BOOKING (fee-booking-net-ledger, approved 2026-11-12). Additive and nullable:
  // NULL = "not booked" and must never be read as "no fee". Nothing reads these unless
  // FEE_NET_LEDGER=1, so with the flag unset the published book is unchanged byte for byte.
  // feeUsd     entry taker fee, dollars = size * rate * (1 - entryPrice)
  // feeExitUsd exit taker fee, dollars, set only on an early exit (a settlement is not a sale)
  // feeRate    the rate used;  feeBasis 'venue' (the market's own published schedule) | 'proxy'
  feeUsd                Float?
  feeExitUsd            Float?
  feeRate               Float?
  feeBasis              String?
```

Apply path is the additive DDL the repo already uses for `fillStatus`/`fillBasis`/`fillResolvedAt`
(2026-10-28): `npm run db:push` after the schema edit — O(1) in SQLite, no table rewrite. The four
`ALTER TABLE` statements are printed by the backfill if the columns are absent, so a forgotten `db:push` fails
loudly instead of writing nothing.

### 4.2 The law — one helper, imported (`src/lib/fee.ts`, shipped in this run)

`feeUsdAtEntry` / `feeUsdAtExit` / `impliedExitPrice` / `bookedFee` / `netPnl`, importing
`takerFeePerShare` + `categoryFeeRate` from `src/lib/scoring/price-edge.ts` — the law is **not** re-implemented.
Rate resolution is venue-truth-first (`data/fee-schedules.jsonl`, 40 slugs) with the slug-keyword proxy
(0.05 / 0.04 politics+finance / 0.07 crypto) as the fallback, and the chosen basis is stamped per row in
`feeBasis` so a later capture can be adopted without re-deriving anything.

Two traps this module is written to avoid, both already in the tree:

- `src/lib/shadow-jev.ts::takerFeePerShare(price)` is the **retired archive-era law** `0.10 × min(p, 1−p)`.
  It is not the current schedule and must not be used for booking. Three implementations of one law is how the
  numbers stop agreeing; that is why this one imports rather than copies.
- The **dollar** fee is `size × rate × (1 − p)` — it *falls* as the price rises. The **per-share** fee peaks at
  p=0.50. Conflating them produces the wrong sign on the cheap band, which is where C-200 makes its money
  (`fee%) 4.34` there vs `0.64` at 0.8–1.0). Both forms are asserted in `tests/fee.test.ts`.

### 4.3 Two write sites (`src/lib/paper.ts`)

```ts
// 4.3a openPaperTrade — the STANDARD/legacy writer (~line 254, inside the tx create)
const fee = bookedFee({ entryPrice: params.entryPrice, simulatedPositionSize: size, marketId: params.marketId,
                        status: "open" }, { basis: FEE_BASIS, venueRates: VENUE_RATES });
data: { ..., feeUsd: fee.entry, feeExitUsd: 0, feeRate: fee.rate, feeBasis: fee.rateSource }

// 4.3b recordExecutionResult — the C-200 writer (~line 306, the sidecar callback). `entryPrice` here is the
// sidecar's BOOKED (credited) price, which is the fill we actually hold — fee it there, not at the intent price.
// 4.3c closePaperTrade (~line 493) — stamp the exit fee on an early exit only:
//      feeExitUsd = feeUsdAtExit(entry, size, exitPrice, rate)
// 4.3d resolvePaperTrade (~line 390) — NO exit fee: a settled leg is redeemed, not sold.
```

### 4.4 Five read sites — the ladder is DUPLICATED and the two cron prompts carry the basis

| # | file | what changes |
| --- | --- | --- |
| 1 | `src/app/page.tsx:297-336` (`C200_PHASES`, `c200Daily`) | bucket `realizedPnl − (feeUsd+feeExitUsd)` when the flag is on |
| 2 | `src/app/analytics/page.tsx:48-74` (`PHASES`, `activePhase`) | same series, same subtraction |
| 3 | `query_bankroll.js:127` (`e.pnl += …`) | same, for the report's phase-gate line |
| 4 | `src/lib/day-pnl.ts` (`FinishedRow`) | carry the fee fields; expose `netRealized` so pages 1–2 do not each invent it |
| 5 | `~/.hermes/cron/jobs.json` — `copybot-c200-daily-report` **and** `copybot-tuning-review-daily` | the standing advance-basis line gains "net of the modelled taker fee (fee-booking-net-ledger, applied <date>)" — **both prompts, or tomorrow's reviewer re-litigates the gross basis** |

`PnlSnapshot` and `scripts/rollup-pnl-hourly.ts` stay **gross** on purpose: they are the chart series, the fee
is a leg-level fact, and rewriting 5,190 rollup cells is a separate change with its own approval.

### 4.5 What the flags do

```bash
FEE_NET_LEDGER=1      # read-side: published PnL + ladder advance subtract the booked fee. DEFAULT OFF.
FEE_BASIS=two         # 'two' (entry + exit-on-closed) | 'entry' (entry only). DEFAULT two.
FEE_LANES=both        # 'both' | 'standard' (C-200 exempt). DEFAULT both.
```

---

## 5. Every figure that moves (dry run, today's book)

`python3 scripts/profit-fee-booking-preflight.py` — read-only, `immutable=1`, nothing written (§10).

### 5.1 The book — leg-level (all finished rows, the gate's own population)

n=12,824 · notional $143,336 · cost basis = `simulatedPositionSize` (dollars at risk)

| population | gross $ | gross % | fee1 $ | fee1 % | net1 % | net2 % | $/1k-cd gross → net1 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| ALL finished | 14,920 | +10.41 | 3,245 | 2.26 | **+8.15** | +7.77 | 11.06 → **8.65** (−21.8%) |
| BANKROLL_200 | 5,632 | +19.99 | 900 | 3.20 | **+16.79** | +15.82 | 114.84 → **96.49** |
| STANDARD | 9,288 | +8.07 | 2,345 | 2.04 | **+6.03** | +5.80 | 7.14 → **5.34** (−25.2%) |

### 5.2 The book — bet-level (the card's headline basis, first leg per wallet/market/outcome)

| population | n | notional | gross % | fee % | net1 % | net2 % | $/1k-cd |
| --- | --- | --- | --- | --- | --- | --- | --- |
| ALL finished | 5,175 | $56,558 | +6.73 | 2.32 | **+4.41** | +4.06 | 7.08 → **4.64** (−34.4%) |
| STANDARD | 3,693 | $44,629 | +3.39 | 2.03 | **+1.36** | +1.15 | 2.90 → **1.16** (−60.0%) |
| BANKROLL_200 | 1,482 | $11,930 | +19.23 | 3.40 | **+15.84** | +14.96 | 150.10 → **123.59** |

### 5.3 Bands that change sign or change a decision (leg-level)

| lane / band | n | gross % | fee % | net1 % | what it means |
| --- | --- | --- | --- | --- | --- |
| STANDARD 0.2–0.4 | 1,281 | +2.61 | 3.40 | **−0.79** | a positive band turns negative |
| C-200 0.4–0.6 | 1,055 | −7.09 | 2.51 | **−9.60** | the dead zone gets 35% worse, not better |
| C-200 0.2–0.4 | 652 | +5.23 | 3.45 | +1.78 | edge collapses to a third of the gross figure |
| STANDARD 0.8–1.0 | 2,704 | −3.28 | 0.32 | **−3.61** | favourites stay negative, and the fee barely matters there |
| C-200 <0.20 | 340 | +48.30 | 4.34 | **+43.96** | still the only band that pays — at 4.34% of notional in fee |

### 5.4 The settlement/early-exit split (bet-level)

| status | n | notional | gross % | net1 % | note |
| --- | --- | --- | --- | --- | --- |
| resolved (held to settlement) | 1,925 | $22,691 | +15.24 | +12.63 | pays the entry fee only |
| **closed (early exit)** | 3,250 | $33,867 | **+1.03** | **−1.09** | **flips sign** — and it is 62.8% of finished bets (70.4% of finished legs) |

### 5.5 Capital the ladder needs (bet-level, fee → capital)

| rung | gross-rate capital | net-rate capital | change |
| --- | --- | --- | --- |
| $500/day | $70,580 | **$107,653** | +52.5% |
| $5,000/day | $705,802 | **$1,076,531** | +52.5% |

Open notional today: $4,745 — i.e. **22.7× short** of the net capital the first rung needs, against the 16.6×
the card quoted on the gross basis.

### 5.6 The ladder read itself

| window | gross 7d | fee 7d | net1 7d | rung (gross → net) | displayed shortfall |
| --- | --- | --- | --- | --- | --- |
| complete settled days ending **2026-11-11** | **+60.31** | 125.88 | **−65.57** | 0 → 0 | $1,689.69 → **$1,815.57** |
| T+0, includes today (2026-11-12) | +55.06 | — | −83.17 (net2 −117.41) | 0 → 0 | $1,694.94 → **$1,833.17** |

Over 100 days of data the gross gate clears rung 1 on **8 windows**, the net gate on **7** — the difference is
2026-09-21 (gross $1,798.78 / rung 1 → net $1,676.75 / rung 0, short by $73.25). The 7 that survive on net are
2026-09-22, 09-23, 09-24, 09-28, 10-02, 10-03 and 10-04; **nothing has cleared a rung since 2026-10-04**, on
either basis.

### 5.7 The backfill, exactly

| status | rows | notional | entry fee $ |
| --- | --- | --- | --- |
| open | 402 | 4,745 | 174.41 |
| closed | 9,033 | 94,034 | 2,014.02 |
| resolved | 3,791 | 49,302 | 1,231.03 |
| **total** | **13,226** | **$148,081** | **$3,419.46** |

33 of 12,824 finished legs (0.3%, $258 notional, $3.67 gross) flip from +PnL to −PnL on the entry fee alone —
so this is not a change that rewrites winners into losers at the row level; it rewrites the aggregate.

### 5.8 Two sensitivities, both printed not booked

| sensitivity | value | reading |
| --- | --- | --- |
| C-200 pays **no** fee (its fill model is a maker limit order) | net1 8.15% → **8.77%** (+0.63pp) | the truth lies between; the booked arm is the conservative one |
| venue-truth rate vs the keyword proxy | 187 of 12,824 rows matched (1.46%): proxy $48.48 vs venue **$46.06** (−$2.42) | the law is right; **coverage** is the gap, not direction |

---

## 6. What does NOT move, and the two reverts

Untouched, byte for byte: `realizedPnl`, `unrealizedPnl`, `PnlSnapshot`, the 5,190-cell PnL rollup, the
cumulative PnL series, win rate, every historical day figure, the RuleSet, every gate and every size.

| revert | scope | effect |
| --- | --- | --- |
| `FEE_NET_LEDGER` unset (or `0`) | read path | every published number returns to its pre-change value **exactly**; rows still carry their fee |
| `npx tsx scripts/backfill-fee-usd.ts --revert --apply` | data | NULLs the four columns; `SUM(realizedPnl)` unchanged (verified on the probe: 0 rows carry a fee, PnL identical) |
| the columns themselves | schema | nullable and read by nothing when the flag is off; dropping them is optional |

Note the `--basis` and `--lanes` switches only change what a *future* backfill stamps; re-running the backfill
with a different basis is the supported way to re-price, and it is idempotent.

---

## 7. The apply sequence (operator's step — I did not run any of it)

```bash
cd ~/polymarket-copybot

# 1. schema: add the four nullable fields, then push (additive, O(1))
#    (the exact block is §4.1)
npm run db:push

# 2. price the book first — dry run, writes nothing
npx tsx scripts/backfill-fee-usd.ts --basis=two
python3 scripts/profit-fee-booking-preflight.py        # independent cross-check, must agree

# 3. stamp it, with a row-level dump for a diff or a reversal
npx tsx scripts/backfill-fee-usd.ts --apply --basis=two --dump=data/backfill-fee-20261112.json

# 4. the live write path (§4.3) and the five read sites (§4.4), then the read flag
#    FEE_NET_LEDGER=1 in .env  +  launchctl kickstart -k gui/501/com.xsnyde2.copybot-dashboard
#    (and the two cron prompts in ~/.hermes/cron/jobs.json, both of them)

# 5. verify: the dashboard's ladder tick, the report's phase-gate line, and today's PnL card
npx tsx scripts/report-daily.ts --dry-run 2>/dev/null | grep -A2 "Phase gate"
```

**Gate on step 4:** `npx vitest run tests/fee.test.ts` must stay green (12 tests), and the phase-gate line must
**fall by the window's fee** — the day it is applied, from roughly `+$60` to roughly `−$66` on the 7-settled-day
window, i.e. the net number `python3 scripts/profit-fee-booking-preflight.py` prints for the same minute. If the
line is unchanged, a read site is still summing gross and `FEE_NET_LEDGER` should go back to unset before
anything else is touched. (Do not test this by "does it still say Phase 0" — the rung has not been cleared
under either basis since 2026-10-04, so that reads the same both ways.)

---

## 8. The five switches (each one line, each with its number)

- **D1 — basis: `two` (entry + exit-on-closed) vs `entry` only.** Recommend **two**: 70% of finished legs are
  early exits where a real sell happened, and entry-only understates the book's cost by **≈$540** ($3,245
  entry-only vs $3,790 with the exit fee on closed legs, 2.26% → 2.64% of notional). Override to `entry` if you
  want the smallest defensible number; the ladder's rung verdict does not change either way (0 of 30 both bases).
- **D2 — lanes: `both` vs `standard` (C-200 exempt).** Recommend **both**: C-200's entry is a *modelled* maker
  fill with an unvalidated 2¢ credit, and exempting it from fees pairs one optimistic assumption with another.
  Exempting C-200 moves the book from 8.15% to **8.77%** net — that is what the conservative choice costs
  (+0.63pp), and it is the honest direction to be wrong in.
- **D3 — ladder advance on net vs gross.** Recommend **net**, which is what was approved and what makes the
  ladder mean something. **The price of it: the first clearing window moves from 2026-09-21 to 2026-09-22**
  ($1,798.78 gross / rung 1 → $1,676.75 net / rung 0, short by $73.25). If you want the advance kept on gross
  while the book reports net, that is `FEE_NET_LADDER=0` separate from `FEE_NET_LEDGER=1` — say so and I will
  wire the second flag instead of the single one.
- **D4 — rate source: venue-first vs proxy-only.** Recommend **venue-first** with the existing capture expanded
  (`scripts/capture-fee-schedules.ts`). Today it touches 1.46% of rows and moves the fee by **−$2.42**; the
  direction is right and the money is negligible, so this is a correctness flag, not a PnL decision.
- **D5 — display: net only vs both.** Recommend **both**, with net labelled *"net of modelled fee"*: the gross
  figure is what reconciles to the existing history, and hiding it would break every prior comparison.

---

## 9. What this does and does not fix

**Fixes:** the scoreboard, the ladder advance, and the daily/annual figures — the book stops reporting PnL the
venue never paid out at. The measured size of that: **+10.41% → +8.15%** leg-level, **+6.73% → +4.41%**
bet-level, **34.4% of the measured edge** at today's numbers.

**Does not fix:** the **decision loop**. `src/lib/scoring/price-edge.ts` is still `status: "shadow"` and wired
to nothing, so no gate and no size sees this fee. Booking the ledger is an accounting change; wiring a
fee-aware admission gate is a separate Lane A proposal and it is exactly what §5.3 is now evidence for —
`STANDARD 0.2–0.4` is positive gross and negative net, and it holds 1,281 legs / $15,447.

**Does not fix:** the C-200 fill model. If those fills are genuinely maker, its fee is overstated (the upper
bound of that error is +0.63pp of book ROI, §5.8). That belongs to `paper-ledger-fee-fidelity` (Backlog,
already carded, still open).

**Review points after apply (pre-registered, so this cannot drift):**

1. **Rate coverage:** if captured venue rates reach ≥25% of monthly notional and the re-priced fee differs from
   the stamped fee by **>5% of the booked fee**, the proxy is refuted and the backfill re-runs on venue truth.
2. **Ladder usability:** if 90 days pass with the net gate clearing no rung while the gross gate would have,
   the advance basis re-opens — a gate that can never fire is not honest, it is decorative.
3. **C-200 fill model:** if the maker assumption is validated (fill share measured live), re-run with
   `FEE_LANES=standard` and restate C-200's net; if it is refuted, C-200's whole book needs a fill-model card,
   not just a fee.

---

## 10. Reproduce (every number above)

```bash
python3 scripts/profit-fee-booking-preflight.py            # §5 tables, §5.7 backfill, §5.8 sensitivities
python3 scripts/fee-ladder-reread.py --db prisma/dev.db --days 30   # §3 clause 2: 0 of 30
python3 scripts/fee-ladder-reread.py --db prisma/dev.db --days 90   # §3 robustness: 1 of 90 (2026-09-21)
python3 scripts/profit-fee-net.py                          # §5.2/§5.4/§5.5 headline tables
npx tsx scripts/backfill-fee-usd.ts                        # dry run; refuses until the columns exist
npx vitest run tests/fee.test.ts                           # 12 tests: the law, the basis, the flag default
```

All three Python instruments open the DB with `immutable=1` and print their own population, basis and window.
`profit-fee-booking-preflight.py` imports the fee law from `profit-fee-net.py`, and `fee-ladder-reread.py` does
the same, so the three cannot drift apart.

### Provenance

| figure | source |
| --- | --- |
| book/lane/band before-after, backfill scope, sign flips, ladder windows, sensitivities | `scripts/profit-fee-booking-preflight.py` (this run) |
| 0 of 30 rung flips; 1 of 90 = 2026-09-21 | `scripts/fee-ladder-reread.py` (this run) |
| gross/net ROI, $/1k-capital-day, capital requirement, settlement split | `scripts/profit-fee-net.py` §FN.1/4/5/6 (this run) |
| 30-day net ladder month (−$148.30 / $278.62 / −$426.92) | `scripts/fee-ladder-reread.py --days 30` |
| fee law `rate·p·(1−p)`, category rates 0.05/0.04/0.07 | `src/lib/scoring/price-edge.ts` `takerFeePerShare` / `categoryFeeRate` |
| venue schedule vs proxy ($4,996.97 vs $5,024.02, 99.68% coverage) | `data/fee-sign-flip-report.json` (2026-10-22) |
| no fee column; ladder gate definition and its three code copies | `prisma/schema.prisma` (22 columns); `src/app/page.tsx:297`; `src/app/analytics/page.tsx:48`; `query_bankroll.js:27,127` |
| the advance basis present in both reviewer prompts | `~/.hermes/cron/jobs.json` (`copybot-c200-daily-report`, `copybot-tuning-review-daily`) |
| apply/revert of the backfill actually works | probe DB `fee_probe.db`, 4 rows: dry run, `--apply` (values 0.45/0.25/0.02, demo untouched, `realizedPnl` unchanged), `--revert --apply` (0 rows carry a fee) |

*Nothing applied: no `apply-vNN`, no `prisma/dev.db` write, no RuleSet row, no rule/size/gate/booking/threshold
changed, nothing merged. Lane A — this file is a proposal, not a change.*
