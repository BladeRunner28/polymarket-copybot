# v55 per-market seats leak on v58 refusals — real defect, zero admissions, 5 false journal rows

Date: 2026-10-30 · Lane A · roadmap card `permarket-legs-seat-release` · **PROPOSAL — nothing applied**
Tree: worktree `wt/permarket-legs-seat-release` at `6b577b5` (repo `/Users/xsnyde2/polymarket-copybot`)
Instruments (both read-only, `prisma/dev.db?mode=ro`):
`scripts/permarket-cap-blocked-legs.ts` (existing) · `scripts/permarket-seat-release.ts` (added here)

## 0. Verdict in one line

The defect is **real and reproduced** — 5 of the 58 legs-clause refusals (8.6%) printed
`legs 3 > max 2` while the market truly held 0–1 legs, and every one of the 5 traces to a **v58
per-wallet refusal that consumed the seat** — but its cost is **zero admissions**: the seat consumer
and the refused candidate are the *same wallet*, already 2.3–2.4× over its own v58 ceiling, so a released
seat only moves the refusal one gate down. The card's own decision rule (c) therefore **passes**
(<1 admission/day measured at exactly 0.0, nothing released to be net-negative), and the card's
NO-CHANGE recommendation rests on a cost that does not exist. **Recommendation: apply as a
basis-truthfulness fix** — the same shape the operator approved for the v45 slug cap — or close it on
"no churn" grounds with the defect documented. Both are defensible; the money argument is not.

## 1. The defect, verified in this tree

`scripts/score-trades.ts`

- L214-232 — the maps are seeded from truth: `PaperTrade WHERE botId='BANKROLL_200' AND status='open'`.
- L1043-1061 — the v55 gate. The seat is taken **inside the pass branch**:

  ```
  if (verdict.blocked) { …refuse… continue; }
  c200MarketLegs.set(t.marketId, legsHere + 1);        // ← seat consumed here
  c200MarketNotional.set(t.marketId, notionalHere + sizeHere);
  ```

- **Correction to the card's gate list.** The card names four later gates (per-wallet ceiling, gross
  exposure, `maxOpenPositions`, `maxCopiesPerCycle`). Measured against the code, three of those fire
  *before* the seat: `maxCopiesPerCycle` / wallet-daily cap at L590-616, the gross-exposure / drawdown /
  circuit-breaker block at L621-694, `maxOpenPositions` at L728-732 — all of them ahead of L1043.
  **The only `continue` between L1059 and the booking call is v58, L1087-1115.** The other carrier is a
  thrown exception out of `openPaperTrade` swallowed at L1216. Both leak the seat; only v58 has victims.

- Measured size of the exception carrier: **0 rows, all-time** (decisions that are `paper_copy`, carry a
  size, and have neither a `PaperTrade` nor a `FillIntent`). It is unobservable in the journal when it
  happens, so this is a bound, not a proof of impossibility — but it has no historical instance.

## 2. Measured basis, as carded

Population: `DecisionJournal`, `isDemo=0`, `risksJson` carrying `v55 per-market cap (…)`; level = one
decision; clock = `createdAt` UTC; ground truth = the booked C-200 legs' own `[openedAt, COALESCE(closedAt,
resolvedAt))` intervals per `marketId`. Rail live since RuleSet **v55 (2026-09-17T05:03Z)**,
`maxMarketLegsPerMarketId=2` (still 2 in active v70).

| window | refusals | legs clause | notional clause | GENUINE | PHANTOM |
|---|---|---|---|---|---|
| lifetime (43.9d) | 79 | 58 | 21 | 53 | **5** (8.6% of legs clause) |
| last 30d | 46 | 46 | 0 | 46 | **0** |

The card's figures reproduce exactly: 5/58 all-time, 0/46 in the last 30d. All 21 `unknown` rows are
notional-clause refusals from 2026-09-18 under the pre-growth $125.12 ceiling — untouched by this card
(the same leak exists on the notional map, and the proposed hunk covers it).

Rate: 79 refusals / 43.9d = **1.80/day**; phantoms = **0.114/day lifetime, 0.00/day in the last 30d**.

## 3. The 5 phantoms, one by one (mechanism, not inference)

Same-run context is reconstructed from the journal ±15 min around each refusal, plus `FillIntent` rows.
Every seat consumer below is the **same wallet as the refused candidate** (`0xb0c85813…`), and every one
of them was refused by v58 with no dispatch: `intents=0`, `booked=[]`.

| # | decision (UTC) | market | printed basis | true open | seat consumer |
|---|---|---|---|---|---|
| 1 | 09-19 20:58:11.233Z | will-voter-turnout ≥62 RU | `legs 3 > max 2` | 1 | v58 @20:58:10.828 — $1,033.59 > cap $431.38 |
| 2 | 09-19 20:58:11.281Z | *same market* | `legs 3 > max 2` | 1 | (seat held by #1's leak) |
| 3 | 09-19 20:58:11.457Z | *same market* | `legs 3 > max 2` | 1 | (seat held by #1's leak) |
| 4 | 09-20 03:59:54.958Z | highest-temp Helsinki 17c | `legs 3 > max 2` | **0** | v58 @03:59:54.739 + .893 — $1,008.65 > $433.29 |
| 5 | 09-20 05:31:20.629Z | highest-temp Hong Kong 32c | `legs 3 > max 2` | **0** | v58 @05:31:20.277 + .534 — $1,008.65 > $431.58 |

Three leak **events** produced five phantom **refusals**: the 20:58:10.828 refusal took the market's
second seat and the next three same-token candidates (224 ms apart) each re-printed `3 > 2` against a
count that had reached 2 with one real leg open. Row 5 is the card's headline case literally — a market
reading 2/2 with **zero** positions open.

Note the direction of the error: the rail refused a copy **conservatively**. Nothing was admitted that
should not have been; the journal's stated reason was false.

## 4. What the repair would actually admit: zero

This is the number the card did not have, and it decides the card.

For each phantom decision, the wallet's open C-200 notional was reconstructed from the booked legs'
intervals at the decision instant:

| # | wallet open notional at decision | v58 ceiling in force | headroom |
|---|---|---|---|
| 1-3 | $1,023.59 (53 legs) | $431.38 | **−$592 (2.37×)** |
| 4 | $998.65 (50 legs) | $433.29 | **−$565 (2.30×)** |
| 5 | $998.65 (50 legs) | $431.58 | **−$567 (2.31×)** |

Releasing the v55 seat moves each of these five candidates to the **very next line of code**, where the
same wallet is 2.3–2.4× over its ceiling. **Admission delta = 0 legs, ever** — not "fewer than 1/day",
exactly zero. The repair changes what the journal says, not what the bot admits.

That also retires the card's implicit worry ("this changes what the bot admits, so park it"). Under the
proposal the bot admits precisely what it admits today; only five false lines in `risksJson` become
truthful.

## 5. Value arm — only if the five had been admitted (they would not be)

Per $1 staked, entry = the decision's `detectedPrice`, settlement = the market's own winning label
(adapter, 79/79 resolved, none guessed), fee 0, slippage 0:

| # | market+outcome | entry | settled | per $1 |
|---|---|---|---|---|
| 1-3 | will-voter-turnout ≥62 (NO) | 0.4095 | won | +1.442 each |
| 4 | highest-temp Helsinki 17c (NO) | 0.2800 | **lost** | −1.000 |
| 5 | highest-temp Hong Kong 32c (NO) | 0.4650 | won | +1.151 |

Sum **+$4.48 per $1** over 5 rows — net positive, i.e. the defect is not accidentally protective, which
is the condition (c) asks about. Read it for what it is: rows 1-3 are **one** outcome (one bet counted
three times), the whole arm is 5 rows, and no dollar total is claimed because the journal persists
`simulatedPositionSize` on 2 of 79 refused decisions.

## 6. The change, its semantics and its residual error

Chosen over "decrement on every downstream refusal path": there is exactly one such path today, but that
shape must be maintained in lockstep with gate order and re-creates the defect silently the day a gate is
inserted below v55 — the same argument that rejected it for the v45 cap.

```diff
@@ -1056,8 +1056,6 @@
               legBlocks.push(`BANKROLL_200: v55 per-market cap (${verdict.why})`);
               continue;
             }
-            c200MarketLegs.set(t.marketId, legsHere + 1);
-            c200MarketNotional.set(t.marketId, notionalHere + sizeHere);
           }
@@ -1162,6 +1162,18 @@
           openCopyKeys.add(`${t.walletAddress}|${t.marketId}|${t.outcome}`);
           legsOpened++;
 
+          // v55 seat-basis fix (2026-10-30, Lane A proposal on card
+          // permarket-legs-seat-release): the seat is consumed by the leg that
+          // actually books, not by a candidate that merely passed the check and
+          // then died at a later gate (only v58 sits below it). Measured before
+          // the fix: 5 of 58 legs-clause refusals printed `legs 3 > max 2` with
+          // 0-1 legs truly open. Same shape as the approved v45 basis fix.
+          if (botId === "BANKROLL_200" && (c200MarketNotionalCap > 0 || rules.maxMarketLegsPerMarketId > 0)) {
+            c200MarketLegs.set(t.marketId, (c200MarketLegs.get(t.marketId) ?? 0) + 1);
+            c200MarketNotional.set(
+              t.marketId,
+              (c200MarketNotional.get(t.marketId) ?? 0) + (positionSize || 0.25)
+            );
+          }
```

Unchanged: `maxMarketLegsPerMarketId` stays **2**, `maxMarketNotionalPctOfCap` stays **0.20** (active
RuleSet v70), no RuleSet version, no schema, no `rules.ts`, no sizing field, no threshold.

Two honest limits of the fixed counter:

1. **Booking point = dispatch for C-200.** The row is written by the Rust sidecar's webhook, so the
   counter counts dispatches that passed every gate. Measured `FillIntent.dispatchedAt → PaperTrade.openedAt`
   lag: median **0.0s**, p90 **0.0s**, max **3.2s** over 292 linked intents — the basis is truthful to
   within a second. A dispatch the sidecar later rejects still consumes the seat: **fail-closed**, never
   phantom-admitting. (Related, out of scope: 108 of the last 400 C-200 `FillIntent` rows have no
   `PaperTrade` at all — a dispatch→row drop worth its own card. It makes this residual error non-trivial
   in the conservative direction only.)
2. **The seed stays once-per-run**, so a leg that closed earlier in the same run is still counted. That
   error exists today, is unchanged by this hunk, and errs the same way.

## 7. Decision rule (card §c), applied

| condition | measured | verdict |
|---|---|---|
| repair changes fewer than 1 admission/day | **0.0 admissions/day, all-time** (§4) | pass |
| released legs not net-negative per $1 | +$4.48/$1 on 5 rows; none released in practice (§5) | pass |
| rail's purpose (≤2 legs/market) survives the change | baseline: 0 of **727** post-v55 markets ever exceeded 2 concurrent legs | must hold post-fix — see §8 |

Both stated conditions hold, so the card's own rule returns **apply**. What is actually bought: the skip
histogram and the refit sample stop carrying five relabelled `skip` rows whose printed reason claims two
open legs where none were open — the same class of fix the operator approved for `slug-cap-counter-basis`
(77/105 phantom there, 73.3%; 5/58 here, 8.6%). What is not bought: copies, or money.

If the operator's preference is "no code churn on a rail that has not misfired in 30 days", the honest
alternative is to close the card as measured and leave the instrument in place — the cost of closing is
five misleading journal rows in a 43-day window, all on 2026-09-19/20.

## 8. Refutation (pre-registered — do not read the result without this)

Re-run with:

```
export DATABASE_URL="file:$PWD/prisma/dev.db?mode=ro"
npx tsx scripts/permarket-cap-blocked-legs.ts --days 30      # class split
npx tsx scripts/permarket-seat-release.ts                    # per-refusal mechanism + peers
```

REFUTED IF, on the first ≥30d window after the fix lands:

1. **Phantom refusals persist** — any v55 row printing `legs N > max 2` with `N−1 >` the true concurrent
   open count at decision time. That would say the seat was not the cause and the fix is cosmetic.
   (Power warning, stated plainly: the baseline is **0 phantoms in the last 30d**, so this test cannot
   "confirm" the fix on history — it can only catch a reintroduction. The economic arm of this card is
   closed by §4 and cannot move.)
2. **The rail stops binding** — any C-200 `marketId` reaching **3+ concurrent open legs** post-fix.
   Pre-fix baseline: 0 of 727 markets, max 2. This is the failure mode that matters if the increment is
   misplaced: an undercounting seat breaches the cap the rail exists to hold. Revert on first instance.
3. **The journal stops recording the rail at all** — zero v55 refusals over 30d where the live clause
   fires ~1.8/day today (46 in the last 30d). A silent loss of the gate is not a "fix".

## 9. Verification actually run (not inferred)

```
$ npx tsx scripts/permarket-cap-blocked-legs.ts --days 0
  refused 79 legs across 11 markets | clause: legs 58 / notional 21 |
  class: genuine 53 / phantom 5 / unknown 21
  settlement known for 79/79 (market 79, event 0; 0 undetermined, NOT guessed)
  priced 79: per $1 staked mean $2.47 median $2.28 sum $194.85 | ex-top-10 $140.85 | +1c slip sum $184.08
  genuine-seat refusals only: n=53 mean $1.98 sum $105.12

$ npx tsx scripts/permarket-cap-blocked-legs.ts --days 30
  refused 46 legs across 3 markets | clause: legs 46 / notional 0 |
  class: genuine 46 / phantom 0 / unknown 0

$ npx tsx scripts/permarket-seat-release.ts      # 79 rows, per-refusal peers + intents
  phantom 2026-09-19T20:58:11.233Z wallet 0xb0c85813a7… open notional $1023.59 across 53 legs
    v58 peer: notional $1033.59 > cap $431.38, intents 0, booked []
  … (all 5 rows, §3)

$ npx tsc --noEmit                     # run WITH the §6 hunk applied
tsc exit=0
$ npx vitest run
Test Files  69 passed (69)
     Tests  690 passed (690)
  Duration  11.11s
$ git checkout -- scripts/score-trades.ts && git status --short
 M data/permarket-cap-blocked-legs.json      # instrument artifact from the read-only run
?? scripts/permarket-seat-release.ts         # new read-only probe; no code change to the bot
```

No test exercises this counter: it is inline inside `main()` with no exported seam, so the mechanical
proof available is the type-check plus the post-landing journal read in §8. If a seam is wanted, extract
`marketSeatAfterBooking(legs, notional, size)` and unit-test the boundary (1→2 admit, 2→3 refuse) in the
same commit — optional, +15 min.

Nothing in this run wrote to `prisma/dev.db` (every read opened it `?mode=ro`), ran any `apply-v*.ts`,
changed a rule, size, gate, booking or threshold, or touched `main`.

## 10. Rollback

`git revert` of the single commit. No RuleSet version, no threshold, no sizing field, no schema, no data
migration. The journal keeps whatever it recorded either way.

## 11. Flags — what an approval means

- **FLAG 1 — seat basis.** Move the increment to the booking point (§6). *Recommended.* Revert = move
  four lines back. Number that moves: phantom share of legs-clause refusals (8.6% → ~0), **not**
  admissions (0.0/day) and not PnL.
- **FLAG 2 — closing instead.** Say "close it": card → Done with this measurement attached and the
  instrument kept, no code change. Cost of closing: five false journal rows in 43 days.
- **FLAG 3 — the gate list in the card is wrong.** Gross exposure, `maxOpenPositions` and
  `maxCopiesPerCycle` fire *before* the seat; only v58 does after. Any future "release on every refusal
  path" variant would be guarding a gate order that does not exist — the booking-point form avoids that
  entirely.
- **FLAG 4 — not bundled.** The same leak on `c200CategoryCounts` (L670-680 increments on pass, before
  the per-market gate) is the same defect class and is *not* touched here. Say "bundle category seats"
  to add that third site; it needs its own measurement first (no instrument prices it yet).
