# STANDARD fill-aware booking — the gate is met on the evidence and short on the population, and any re-run after 2026-11-11 inverts the sign

Roadmap card `standard-fill-aware-booking` (Lane A, approved 2026-11-12T16:28 via `apr-standard-fill-aware-booking`).
Supersedes `drafts/standard-fill-aware-booking-20261029.md` (same card, 14 days earlier). Where the two disagree,
this one is measured against today's DB, and the disagreement is explained in §2.

**NOTHING APPLIED.** No `scripts/apply-vNN.ts`, no write to `prisma/dev.db`, nothing merged to main, no rule, size,
gate or published figure changed. Every DB read below is `file:…?mode=ro` + `PRAGMA query_only=1`.

Instruments (read-only, in the working tree, NOT committed — the apply step commits them with the change):

```
scripts/standard-fill-aware-rerebook.py      # the 10-29 instrument, recovered from .worktrees/t_b791ae89
scripts/standard-fill-aware-basis-split.py   # NEW: splits the population by booking basis (d974287)
data/standard-fill-stamp-20261112.jsonl      # NEW: today's forward stamp, 124 legs, from retained L2
data/standard-fill-basis-split-20261112.json # the machine-readable output of the run quoted here
```

---

## 1. Verdict

**Both clauses of the card's own decision rule are MET — on the booked-price basis, on the population the
repair never touched — and the population clause is the only thing left.** It reads 291 clean settled stamped legs
against the required 300, and the literal "forward" reading (legs opened after 2026-10-29) is 62 of 300. The 9 legs
the cumulative reading needs arrive with the next booth run (~1 day of flow); the forward reading needs ~54 days.

**Recommendation: ship the missing writer first (Lane B, no booking change), then adopt the PRICE half as a
bookkeeping truth behind the existing `FILL_AWARE_BOOKING` flag.** The writer is not optional: with no cadence, every
leg opened after the last stamp books with no evidence and the change decays to a no-op within days — the exact
failure `c6222f7` was written to prevent. The change is a downward re-book: STANDARD's 90d completed PnL goes from
**−$1,724.19 (−4.88%)** to a projected **−$3,286.41 (−9.30%)**. It cannot produce a dollar. That is the whole point
of it.

Three judgment calls, each one line and each overridable (the number that changes is on the line):

| # | call I made | instead of | what changes if you override |
|---|---|---|---|
| 1 | basis = **the booked price** (the decision mid) | the mid at the attaining snapshot | the refutation FIRES: vs contemporaneous mid, median +0.00c and 74% of legs sit inside ±0.3c at n=122 |
| 2 | population = **cumulative clean legs (291/300)** | forward-only legs (62/300) | −4.42pp vs −6.84pp; timing ~1 day vs ~54 days at the current settled-clean rate |
| 3 | scope = **price half only** | price + volume (p(fill)) | both halves together move the clean book −3.69pp, not −4.42pp; the volume half is a separate mechanism with its own card |

## 2. The one thing that changes the answer today

**Any re-run of the 10-29 instrument after 2026-11-11 reports the OPPOSITE sign, and the cause is not the market.**

Two price-side changes landed between the stamp and now, both of which REWRITE `PaperTrade.entryPrice` on finished rows:

- `fbf9073` (2026-11-09) — price the token the leg holds, by the venue's own label
- `d974287` (2026-11-11) — the 233-row repair APPLIED, 183 of them STANDARD (`data/repair-manifests/ledger-price-side-applied-20261111T123934.jsonl`)

The 10-29 booth measured `firstAsk` against the entry as booked. A naive re-run subtracts that ask from an entry
that now carries a *different* price for a *different* token. Same script, same artifact, two answers:

| population | booked entry basis | n | mean Δ | median Δ | re-booked ROI Δ |
|---|---|---|---|---|---|
| 291 clean legs | as booked (correct) | 291 | **+1.159c** | **+0.50c** | **−4.42pp** |
| 339 all stamped legs | as of today (naive re-run) | 339 | **−0.382c** | +0.50c | **+2.68pp** |
| 48 repaired legs, as of today | as of today | 48 | **−9.729c** | +0.50c | **+59.87pp** |

The contamination is confined to 48 of 339 legs (14.2%) and it is the whole sign: on those 48 the booked entry
moved by a mean **+50.2c** (median +45.0c, min +22c, max +88c) — one to three orders of magnitude wider than the
1–2c ladder the question is about. On the 291 legs the repair never touched, the naive re-run and the
correct basis give **identical** numbers by construction (there is nothing to correct) — which is what makes it a
control rather than an assertion. Residual exposure (opened before the fix, finished after the repair, so
unrepaired and unknowable): **0 legs**.

Consequence for the board: **the 10-29 draft's −4.13pp and this run's −4.42pp agree, and any reviewer who re-runs
the rebook script without the basis split will report +2.7pp and "adopt, it makes money".** The split is now part
of the instrument (`scripts/standard-fill-aware-basis-split.py`), not a note in a draft.

## 3. Gate status, clause by clause

Decision rule, verbatim from the card: *adopt when, over >=300 forward legs, the resolver-stamped entry is worse
than the booked mid by a median >=0.5c AND the re-booked 90d ROI falls >=1.0pp.*

| clause | required | measured | met? |
|---|---|---|---|
| 1 · median Δ ≥ +0.5c | ≥ 0.5c | **+0.50c** on every cut (291 clean, 191 ≤60s, 62 forward, both 10-29 and 11-12 runs) | **met, on the threshold exactly** |
| 2 · re-booked ROI falls ≥ 1.0pp | ≤ −1.0pp | **−4.42pp** (clean, n=291) · −5.84pp (≤60s, n=191) · **−6.84pp** (forward-clean, n=62) | **met with 4–7x margin** |
| population | ≥ 300 legs | 291 clean cumulative · **62** forward-clean | **NOT met** |

Full table (`scripts/standard-fill-aware-basis-split.py --artifact <union>`):

```
cell                          n  notional    booked  rebooked     Δpp  pfillΔ   bothΔ  mean c  med c  ±0.3c
clean/as-booked             291   4852.78    774.93    560.33   -4.42   -1.66   -3.69   1.159   0.50   5.8%
taker60-clean/as-booked     191   3134.78   1048.98    866.00   -5.84  -11.02  -14.00   1.045   0.50   4.7%
forward-clean/as-booked      62    766.00    200.99    148.59   -6.84  -20.80  -22.36   1.678   0.50   1.6%
all/as-of-today             339   5455.18    816.52    962.59    2.68   -2.77    2.11  -0.382   0.50   5.0%
```

Read the last row only as the trap it is. `Δpp` = re-book at the attainable first ask; `pfillΔ` = the C-200 volume
policy (unreachable ⇒ not a position); `bothΔ` = both together. Booked → re-booked on the clean population is
**+15.97% → +11.55%**.

Three things about clause 1 that matter more than the pass:

1. **The median sits exactly on the threshold because the ladder is on a cent grid.** The distribution is +0.5c /
   +1.0c / +1.5c steps; the mean is +1.159c and only **5.8%** of legs land within ±0.3c of the booked price. A
   half-tick market would read a median of 0.00c and FAIL the clause while the cost was unchanged. The robust
   statement is the mean and the share, not the median.
2. **The refutation clause is decidable in two directions and the card's wording picks one.** "Within ±0.3c of the
   mid" — vs the mid *at the attaining snapshot* it reads median +0.00c / 74% inside the band at n=122, i.e. the
   refutation fires; vs the **booked price**, which is the decision mid the P&L was computed from, it reads mean
   +1.16c / 5.8% inside the band. Same legs, opposite verdict. A mid that moved after the decision is a market
   move, not an entry cost, so the decision-relevant basis is the booked price. **This is judgment call 1.**
3. **The forward population agrees with the pool and has a bigger margin** (−6.84pp vs −4.42pp, mean +1.68c vs
   +1.16c), so the sample is not thin — but it is 62 legs, not 300.

## 4. The writer is missing, and that is why the population clause cannot move

The booth (`scripts/standard-fill-stamp.ts`) has **no scheduled writer**. Its artifact carried one snapshot, from
2026-10-29T17:14Z, until this run. Measured today:

```
STANDARD PaperTrade rows opened since 2026-10-29 00:00   130
  …of which settled                                       107
  …of which carry a fill stamp in the DB                     0
```

This is the `c6222f7` lesson one layer down: *an artifact with no writer is a card that lies.* The C-200 chain got
a cron (`copybot-c200-fill-chain.sh`, every 2h) precisely because its resolver could only ever stamp legs that
existed as of the artifact's last refresh. STANDARD has neither the chain nor a stamp table.

**The evidence itself is not the problem — the run is.** One manual book-only pass, 26 seconds, no network:

```
npx tsx scripts/standard-fill-stamp.ts --book-only --since-ms 1793287841000 \
    --out data/standard-fill-stamp-20261112.jsonl
  population:    124 STANDARD legs opened on/after 2026-10-29 of 10,396 ever · L2 corpus present
  book arm:      122/124 stamped (98%) · median cover lag 14.4s
  first*:        122  mean +1.26c  median +0.50c  ≤booked 7%  ≥+1c 32%  |Δ|≤0.3c 3%
  resolver:      reachable 38/122 = 31%
  gate:          122 stamped over 14.0 days = 8.69/day → 178 more, ~21 days at this coverage
```

So the forward population is **99 settled legs of which 62 are repair-clean**, accruing at ~4.4 clean settled
legs/day. (The booth's own "178 more, ~21 days" line counts every stamped leg, including the 37 whose booking basis
the 11-11 repair moved; clean-settled is the slower, honest rate.) Forward-300 is **~54 days** away; cumulative-300
is 9 legs away. **This is judgment call 2**, and the reason it matters is that the card's clause says "forward" while
its stated purpose (a sample big enough to trust) is served by either.

## 5. What the card claimed, re-derived on today's book

| claim (2026-10-29) | today (2026-11-12) | verdict |
|---|---|---|
| 1c better entry on every settled leg = **+$1,439.33** = 5.0% of 90d notional | **+$1,615.89** = 4.585% of 90d resolved notional ($35,242.46) | reproduces |
| …= **62%** of the 90d profit (+$2,329.01, +8.1%) | **56.7%** of +$2,848.68 (+8.08%) | reproduces (61.8% on the card's own inputs) |
| STANDARD = 72% of the book's notional | **59.3%** of the two lanes' 90d completed notional ($35,344 of $59,564) · **91.0%** of open notional ($4,317.52 of $4,745.16) | 72% not reproduced on either basis today |
| the lever is the lane's | the 90d profit is **C-200's**: BANKROLL_200 +$5,849.23 (+24.15%), STANDARD **−$1,724.19 (−4.88%)** | the size is right, the owner is wrong |
| "a fast lane buys nothing" | not re-measured here; 10-29 marks read flat at every horizon | carried as the previous run's finding |

On STANDARD's own 90d *resolved* book the same formula gives **$680.20 = 3.0% of notional**, because it counts only
winning legs and the lane's 90d resolved book is −$1,125.31. The lever is real at $0.7–1.6k per 90d; **its sign is
negative**, which is what the 10-29 run discovered and this run confirms.

## 6. What is actually missing in code

C-200's fill-aware booking (c6222f7) shipped the **volume** half only: `bookedPnl()` zeroes a leg stamped
`fillStatus = "unfilled"`. There is no price-half mechanism anywhere, for either lane:

- `prisma/schema.prisma:215-217` — `fillStatus` / `fillBasis` / `fillResolvedAt` exist; **no `fillEntryPrice`**
- `src/lib/paper.ts:47-51` — `bookedPnl(leg, pnl)` returns 0 or `pnl`; it cannot re-price
- `src/lib/paper.ts:360, 381, 493` — the three writers (`updatePaperTradePrice`, `resolvePaperTrade`,
  `closePaperTrade`), all already calling `bookedPnl`
- `scripts/c200-fill-resolve.ts` — C-200 only (`botId: "BANKROLL_200"`), stamps `fillStatus`, never a price
- STANDARD legs: 962 settled since the L2 epoch, **0** carrying any fill stamp → `bookedPnl` is a no-op on the lane

## 7. Apply-ready design (operator's step, ~2h)

1. **Schema** — two additive nullable columns. The precedent set by the fill* columns themselves (commit 780ccb4)
   is a metadata-only `ALTER TABLE ADD COLUMN` in SQLite, **not** `prisma db push` (the last migration row is
   2026-08-03, and a 12 GB live DB should not be handed to a schema differ):
   ```
   ALTER TABLE PaperTrade ADD COLUMN fillEntryPrice REAL;
   ALTER TABLE PaperTrade ADD COLUMN fillEntryBasis TEXT;
   ```
   then `fillEntryPrice Float?` / `fillEntryBasis String?` in `prisma/schema.prisma` and `npx prisma generate`.
2. **Resolver** — `scripts/standard-fill-resolve.ts`, modelled on `c200-fill-resolve.ts`: read `data/l2/<assetId>.jsonl`
   (the booth's S1 arm already does this), take the first best-ask at/after `openedAt` inside the cover lag,
   stamp `fillEntryPrice` + `fillEntryBasis`, write **only** those columns, idempotent on `fillEntryPrice IS NULL`,
   dry-run by default, `--apply` to write. Identical asymmetry rule as C-200: no book window ⇒ `NULL`, never a guess.
3. **Reprice** — inside `bookedPnl`, when `fillEntryPrice` is present and differs from `entryPrice`:
   `pnl' = size × (exit/fillEntryPrice − 1)` with `exit = entryPrice + pnl/(size/entryPrice)` (the exit the stored
   PnL already implies, so a resolved total loss stays a total loss), clamped to `[−size, size×(1/fillEntryPrice − 1)]`.
   Signature grows to `bookedPnl(leg, pnl)` → `bookedPnl(leg, pnl, {entryPrice, size})`; the three call sites already
   hold both.
4. **Writer, before or with it (Lane B, no approval needed)** — `scripts/cron-scripts/copybot-standard-fill-chain.sh`,
   every 2h, watchdog-silent: run the booth `--book-only` for legs opened since the last run, then the resolver
   `--apply`. Model the reporting on `copybot-c200-fill-chain.sh` (silent on a healthy no-op, speaks when it stamps
   or when the interface drifts). **Without this the change is a one-off stamp that decays to a no-op for every
   new leg — the exact failure c6222f7 was written to prevent.**
5. **Verify** — `tests/fill-aware-booking.test.ts` (8 existing cases) plus: NULL price ⇒ byte-identical; price ==
   entry ⇒ byte-identical; price above entry ⇒ smaller pnl, never below −size; a resolved loss stays −size.
   Then a dry run that prints the before/after of the 291 stamped legs and must reproduce §3 to the cent.

Operator sequence:

```bash
cd ~/polymarket-copybot
git checkout -b standard-fill-aware-booking
# 1. ALTER TABLE x2 (metadata-only) + schema.prisma + resolver + bookedPnl + chain, then:
npx prisma generate
npx vitest run tests/fill-aware-booking.test.ts
DATABASE_URL="file:./dev.db" npx tsx scripts/standard-fill-resolve.ts            # dry run: counts only
DATABASE_URL="file:./dev.db" npx tsx scripts/standard-fill-resolve.ts --apply
npm run build && launchctl kickstart -k gui/$(id -u)/com.xsnyde2.copybot-dashboard
python3 scripts/standard-fill-aware-basis-split.py   # must still print -4.42pp on the clean arm
```

## 8. Every figure that moves

Write-time only (legs settling after the change); no historical row is restated.

| figure | today | after adoption (projected from −4.42pp) |
|---|---|---|
| STANDARD 90d completed PnL | −$1,724.19 (−4.88% on $35,344.38) | **−$3,286.41 (−9.30%)** |
| STANDARD since L2 epoch (settled) | −$1,158.66 (−6.96% on $16,651.18) | **−$1,894.64 (−11.38%)** |
| all-lane 90d completed PnL | +$4,125.04 (+6.93% on $59,563.67) | **+$2,562.82 (+4.30%)** |
| C-200 ladder / BotBankroll | — | **unchanged** (STANDARD never posts to `BotBankroll`) |
| per settled leg | — | **−$0.74** on a $16.68 mean clip (the measured −$214.60 / 291) |

Projections, labelled as such: the measured rate is carried onto the lane's whole notional, while the evidence
covers 291 of 962 settled legs since the epoch (30.2%). The volume half, if it ships too, is −1.66pp on top and
**not additive** with the price half.

## 9. Revert

`FILL_AWARE_BOOKING=0` (or `false` / `off`) restores today's booking exactly — the same switch C-200 uses, already
read per call by `fillAwareBookingEnabled()`. Legs settled while the flag was on keep their re-booked
`realizedPnl`; a full unwind of those rows is a separate approved restatement, not a flag flip.

## 10. Refutation — of THIS proposal

Wrong, and to be dropped or reversed, if any of these holds:

1. **The forward population reverses within 30 days**: median Δ ≤ 0 or the re-booked ROI fall < 1.0pp once ≥300
   clean forward legs exist. Then 291 clean legs were an early sample and the card closes for the quarter.
2. **The stamped asks are wrong on >5% of legs** (stale ladder, token-identification error, asset-map miss). Five of
   251 stamped legs in the 10-29 booth already carried an ambiguous outcome token; a systematic identification error
   voids the instrument, not just this card.
3. **The re-book cannot be reproduced from the resolver's own stamps** — if `fillEntryPrice` on the labeled legs does
   not reproduce −4.42pp ± 0.3pp, the instrument disagrees with itself and neither number ships.
4. **STANDARD's since-epoch ROI turns ≥ +2% before adoption.** Then the entry-price question is dominated by whatever
   moved the lane and this card should be re-ranked, not executed.

## 11. Reproduction

```bash
cd ~/polymarket-copybot
python3 -m py_compile scripts/standard-fill-aware-rerebook.py scripts/standard-fill-aware-basis-split.py

# today's forward stamp (26s, no network, reads the 12GB DB through sqlite3 -readonly)
npx tsx scripts/standard-fill-stamp.ts --book-only --since-ms 1793287841000 \
    --out data/standard-fill-stamp-20261112.jsonl

# union of the two snapshots (newer wins per leg), then the basis split
python3 scripts/standard-fill-stamp-merge.py data/standard-fill-stamp.jsonl \
    data/standard-fill-stamp-20261112.jsonl /tmp/union.jsonl
python3 scripts/standard-fill-aware-basis-split.py --artifact /tmp/union.jsonl
python3 scripts/standard-fill-aware-basis-split.py --artifact /tmp/union.jsonl --json \
    > data/standard-fill-basis-split-20261112.json
```

Appendix — the numbers quoted above, as measured at 2026-11-12T16:31Z:

```
all_resolved_90d      2585   $35,242.46   +$2,848.68   +8.08%
std_resolved_90d      1436   $22,704.58   −$1,125.31   −4.96%
std_completed_90d     2375   $35,344.38   −$1,724.19   −4.88%
std_completed_epoch    962   $16,651.18   −$1,158.66   −6.96%
c200_completed_90d    2098   $24,219.29   +$5,849.23  +24.15%
all_completed_90d     4473   $59,563.67   +$4,125.04   +6.93%
1c better entry, all-lane 90d resolved : $1,615.89 (4.585% of notional, 56.7% of the profit)
1c better entry, STANDARD-only resolved:   $680.20 (2.996% of notional)
C-200 fill stamps in DB: 582 (193 filled / 389 unfilled) · STANDARD: 0
```
