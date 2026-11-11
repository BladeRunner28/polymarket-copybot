# Ledger price-side repair — 233 rows, and the exit column with them

**Card:** `ledger-price-side-repair` · **Lane:** A (proposal, NOT applied) · **Date:** 2026-11-10
**Instrument:** `scripts/profit-ledger-repair-preflight.py` (new, read-only) + `scripts/profit-postfix-integrity.py`
**Manifest:** `data/repair-manifests/ledger-price-side.jsonl` (233 pre/post images, generated but **not written to the DB**)
**Reproduce:** `COPYBOT_DB=$PWD/prisma/dev.db python3 scripts/profit-ledger-repair-preflight.py`

---

## 1. The ask, in one line

Repair every finished `PaperTrade` row whose booked `entryPrice` is the **sibling**
token's price — **233 rows, not 137** — repairing the **early-close exit mark in the
same pass**, then post the *delta* to `BotBankroll` and append one corrected
`PnlSnapshot` per row.

| | booked now | after repair |
|---|---|---|
| Book PnL (5,762 finished legs) | +$12,516.84 (+18.9%) | **+$7,076.06 (+10.7%)** |
| Repaired class (137 measured legs of 233 rows) | +$5,598.58 | **+$157.80** |
| C-200 trailing 7 days, rung 1 = $1,750 | +$2,456.49 → **PASS** | **−$348.18 → fail** |

The gate verdict does not depend on which estimator you pick: all six variants land
between −$345 and −$402 (section 5).

---

## 2. What the proposal's evidence got right

Re-measured 2026-11-10 08:23–08:26 CST, and it holds:

- **The mechanism is positional, not arithmetic.** For 233/233 rows in the class the
  booked price sits on token position 0 (`yesPrice`) and **0** on position 1; a
  snapshot is within reach of `openedAt` for 233/233. That is the pre-fix
  `outcome === "NO" ? noPrice : yesPrice` read, at scale.
- **The write fix is holding.** 0 legs opened after 2026-11-09 09:15:16 carry the
  complement.
- **No open leg is affected.** 0 of 130 deduped open legs (415 open rows) are
  inverted, so there is no mark-vs-entry mismatch to unwind.
- **The gate figure reproduces** (+$2,456 booked vs rung 1's $1,750).
- **The class is older than the original card said** — 74 rows open in July, 66 in
  August, 26 in October, 67 in the first nine days of November.

---

## 3. Three corrections that change the write

### 3a. It is 233 rows, not 137

The instrument dedupes to the first leg per `bot|wallet|market|outcome` **because
it is measuring**. Every reader sums **rows**: the Dashboard, `DailyReport`,
`capital-data`, and `BotBankroll` itself (which incremented once per row at close).

| Level | Count |
|---|---|
| rows in the class | **233** |
| distinct `bot|wallet|market\|outcome` positions | 140 |
| rows beyond the first per position | 93 |
| positions the instrument measures (not shadowed by an earlier consistent leg) | 137 |

One market alone (`mlb-bos-lad-2026-08-01`) carries 23 rows. A 137-row repair would
leave 96 rows printing the false price, and the bankroll — incremented per row —
would be wrong by exactly those rows.

### 3b. The card's prescribed read does not exist in-house

The card says: *"set entryPrice to the token price at the trade minute (the same
read outcome-price.ts now performs)"*. That read needs **token labels**, and:

```
MarketSnapshot rows 15,915,363, of which rawMarketJson='{}': 15,915,363
```

The only in-house price store is `yesPrice`/`noPrice` — **positional**, i.e. the
exact read that produced the defect. Repricing "by label" from snapshots is not
lossy, it is impossible. The venue has to be asked:

```
CLOB /markets/<conditionId> -> tokens[] {token_id, outcome, winner}
     /prices-history?market=<token_id>&startTs=<open-15m>&endTs=<open+15m>&fidelity=1
```

96 distinct conditionIds, 233 rows. Venue reads obtained: **204/233 (88%)**; on 189 of
those the venue corroborates the wallet's fill within 6c. Where a read exists, the
venue's own price for our token is a **median 0.0000** away from the arithmetic
complement `1 − booked` (p90 0.02, ≤0.06 on 189/204). So the identity is exact on this
class and the venue is used as corroboration, not as the source of truth.

### 3c. The exit column carries the same defect

144 of 233 rows are **early closes** (51 deduped legs), and:

- **144/144 closed before the write fix.**
- At close, `currentPrice` was written by the *same* positional read, so it holds the
  **sibling's** price, not ours.
- 4 legs have a venue read at the close minute to decide it: **4 say sibling, 0 say
  ours.** The other 47 have no print in that minute — the fallback is the identity.

So the card's entry-only change would pair **our entry with the sibling's exit**:
the same defect, one column over. It is not cosmetic — the exit column is worth
**$207** on a class whose true PnL is ~$158:

| Repair scope | class PnL | book PnL |
|---|---|---|
| booked as printed | +$5,598.58 | +$12,516.84 |
| entry only (card's literal CHANGE) | −$45.81 | +$6,872.45 |
| entry + exit | **+$157.80** | **+$7,076.06** |

---

## 4. Estimators, and what each costs

| Estimator | Coverage | median \|est − (1−b)\| | Needs network |
|---|---|---|---|
| V venue @ trade minute | 204/233 rows (88%) | 0.0000 (p90 0.020) | yes |
| W copied wallet's fill | 233/233 rows | 0.0050 | no |
| C arithmetic `1 − b` | 233/233 rows | — (the anchor) | no |

- 28 token picks were **rejected by a fill cross-check** (the "own" token must track
  the wallet's fill, the sibling must track the booked price). Those fall back to C,
  as do 29 rows with no venue print within ±15 min of the trade (Δ notional $285).
- **15 rows** (5 distinct markets, **$160** of notional — 4% of the class) have venue
  and complement disagreeing by >6c: all July/August thin esports/MLB lines, largest
  0.405 on `mlb-mia-nym-2026-07-30`. They are flagged `needs_review` in the manifest
  and **stay on the complement**, because we cannot tell from here which print is
  stale — and a 40c guess is worse than a flagged identity. On those 15 rows the
  repair moves −$46.19 to +$146.02; excluding them changes the book by ~$192.

**Rule used for the post image:** `entry = venue if |venue − (1−b)| ≤ 0.06 else 1−b`;
`exit = 0/1` for resolved, `venue at close` where available, else `1 − currentPrice`
for pre-fix early closes.

---

## 5. The C-200 ladder gate — the decision that actually matters

Trailing 7 local days, dashboard basis (day key = local day of `closedAt ?? resolvedAt`),
165 legs of which 27 inverted:

| Basis | 7-day total | rung 1 ($1,750) |
|---|---|---|
| booked (as printed) | +$2,456.49 | **PASS** |
| entry-only, C / W / V | −$401.58 / −$395.26 / −$398.47 | fail |
| entry+exit, C / W / V | −$351.39 / −$344.68 / −$348.18 | fail |

The gate conclusion is **robust to every estimator choice and to the exit question**.
Whatever you believe about the exit column, this week's advance is not earned.

---

## 6. What the write actually is

1. **Pre-image dump** — already produced: 233 records in
   `data/repair-manifests/ledger-price-side.jsonl`, each with `pre` (entryPrice,
   currentPrice, realizedPnl, size, fillStatus), `evidence` (wallet fill, venue
   price, token pick, complement, needs_review) and `post`. Re-generate it with the
   command at the top **on the day of the write**; the live lane is writing new rows
   (5,759 → 5,762 finished legs during this session).
2. **233 row updates**, each guarded on the pre-image value:
   `UPDATE PaperTrade SET entryPrice=?, currentPrice=?, realizedPnl=?
    WHERE id=? AND entryPrice=? AND realizedPnl IS ?`
   A second pass matches 0 rows — the repaired rows classify as *consistent*, so the
   instrument's own class definition becomes empty (verified: **233/233 post images
   classify consistent, 0 inverted**). Non-zero rows changed on a second run is a bug,
   not a rounding artefact.
3. **BotBankroll: post a DELTA, do not rebuild.** The bankroll does not equal its rows
   for reasons that predate this defect:

   | bot | rows | Σ realizedPnl | BotBankroll.realizedPnl |
   |---|---|---|---|
   | STANDARD | 3,699 | +$3,047.09 | +$9,487.34 |
   | BANKROLL_200 | 2,063 | +$9,469.75 | +$8,899.63 |

   A rebuild would silently move STANDARD by −$6,440 for a reason that has nothing to
   do with price side. Post instead: **BANKROLL_200 −$3,843.89, cashBalance −same**
   (STANDARD never posts to the bankroll — `resolvePaperTrade`/`closePaperTrade` skip
   `botId === "STANDARD"`; its 183 rows move −$1,499.04, its bankroll does not).
4. **PnlSnapshot: append one corrected row per repaired row.** The dashboard reads
   the **last** snapshot per trade (`src/app/paper-trades/page.tsx`: `orderBy
   collectedAt desc, take 1`), so an append is what it picks up; no history is
   destroyed and each appended row is reversible by id.
5. **Do not rewrite `DailyReport`.** 119 published daily statements exist. The repair
   makes some of them stale; state the break in the EOD report rather than editing
   published history.
6. **Verify after the write:** class size 0; class PnL +$346.74 on rows (see below);
   bankroll delta applied exactly once; Dashboard book = $7,076.06 ± the rows that
   settled between the dump and the write.

**Rollback:** re-INSERT the `pre` block by `paperTradeId` (233 rows, values are exact
literals, nothing recomputed); reverse the bankroll delta; delete the appended
`PnlSnapshot` ids from the manifest. All three are single statements against the
manifest file.

**Row-level effect (what the write does):** pre +$5,689.67 → post **+$346.74**
(Δ −$5,342.93): BANKROLL_200 50 rows −$3,843.89, STANDARD 183 rows −$1,499.04.
Largest single correction −$769.47. 37 rows do not move at all (unfilled legs booked
at 0.00, and rows whose complement equals their booked price).

---

## 7. Decision rule — apply when all four hold

1. **Identity corroboration:** ≥95% of venue-decidable rows agree with `1 − b` within
   0.06 — **measured 92.6% (189/204)**, and 88.7% within 0.02. *Just under the bar as
   written;* the 15 disagreements are flagged and priced on the identity, which is why
   the bar is the operator's call, not mine.
2. **The operator accepts the restatement:** book +$12,516.84 → +$7,076.06 and this
   week's gate PASS → fail.
3. **The 15 `needs_review` rows are either accepted on the complement** (5 markets,
   $160 of notional, 4% of the class) **or excluded** from the write and repaired after
   manual review — excluding them moves the book by ~$192.
4. **Manifest re-generated within the hour of the write** (the live lane adds rows).

---

## 8. What would REFUTE this proposal

- **The tape check.** ≥20 legs where the **booked** entry price is what that token
  actually traded at (not its sibling) → the rows are right, the fix was wrong, and
  no write should happen. *This is the primary refutation and it is directly
  executable against the same CLOB history used here.*
- **A gate that survives.** If the trailing-7-day C-200 total under **any** of the six
  bases is ≥ $1,750, the "one rung from a false advance" claim fails. Measured: all
  six are negative, so this is currently not refuted.
- **Venue-vs-complement disagreement above 5% of rows.** Measured 7.4% (15/204) — it
  is not refuted today, but if a fresh run pushes it past 5%, the class definition
  (not just individual rows) is wrong and the repair must stop.
- **A non-idempotent repair.** A second run that changes any row means the class
  definition or the guards are wrong.
- **A bankroll that does not reconcile.** If after posting the delta the bankroll minus
  its rows is not the same constant it was before (−$570.12 for BANKROLL_200 today),
  the posting is wrong.

---

## 9. What this is NOT

- **Not a rule change.** No `RuleSet` row, no threshold, no sizing field, no gate moved.
  The ladder's rung stays $250/day; only the ledger it is summed from changes.
- **Not a live-position change.** 0 open legs in the class.
- **Not a resolution change.** Win/loss is decided by label (`didOutcomeWin`), which was
  always correct; only prices were wrong.
- **Not a `DailyReport` rewrite** and not a bankroll rebuild.
- **Not applied.** Nothing was written to `prisma/dev.db`; the instrument opens it
  `mode=ro` and every figure here comes from that read-only connection.

---

## 10. Reproduce

```bash
cd ~/polymarket-copybot
COPYBOT_DB=$PWD/prisma/dev.db python3 scripts/profit-ledger-repair-preflight.py
COPYBOT_DB=$PWD/prisma/dev.db python3 scripts/profit-postfix-integrity.py --only=A,B
```

Both are read-only. `profit-postfix-integrity.py` was patched on this branch to take
`COPYBOT_DB` and open `file:…?mode=ro` — run from a `git worktree` it otherwise reads
that worktree's **0-byte** `prisma/dev.db` placeholder and reports an empty book with
no error (worth knowing: **55** worktrees are checked out against this repo — the
placeholder is not a local quirk). From the repo root the unpatched script reads the
real DB and is unaffected.

The preflight's venue cache (`data/repair-manifests/venue-cache.json`) makes a re-run
take seconds and `--offline` reproduces every figure here without touching the network.
A run writes **only** the manifest and the cache; the DB connection is `mode=ro`, so a
write attempt raises instead of landing.
