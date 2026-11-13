# v55 per-market seats leak on v58 refusals — re-measured 2026-11-12: defect real, admission delta zero, 5 false journal rows

Date: 2026-11-12 · Lane A · roadmap card `permarket-legs-seat-release` · **PROPOSAL — nothing applied**
Repo `/Users/xsnyde2/polymarket-copybot` @ `947ceb5`, `scripts/score-trades.ts` unmodified (verified before and after the trial hunk)
Prior read: `drafts/permarket-legs-seat-release-20261030.md` (this document supersedes its numbers)
Instruments (all read-only, `file:prisma/dev.db?mode=ro`):
`scripts/permarket-cap-blocked-legs.ts` (committed 2026-10-30) · `scripts/permarket-seat-release.py`
(added with this document — class split, per-phantom mechanism, binding baseline, carriers)

## 0. Verdict

The defect is **real and reproduces**: 5 of the 60 legs-clause refusals (8.3 %) printed `legs 3 > max 2`
while the market truly held **0–1** open legs, and every one traces to a **v58 per-wallet refusal that
consumed the v55 seat**. Its cost is **zero admissions**: the seat consumer and the refused candidate are
the same wallet, 2.3–2.4× over its own v58 ceiling at that instant, so a released seat only moves the
refusal one gate down.

What changed since the 10-30 read: the population grew from 79 to **81** refusals (both additions
genuine), the phantom set is **unchanged at 5**, the last phantom is now **53.5 days old**, and the
"0 of 727 markets ever exceeded 2 legs" baseline is re-measured as **0 of 991** markets. Also new: the
**v45 per-slug seat leaks the same way** (it sits above the v55 gate too) — flagged, not bundled.

**Recommendation: APPLY the 4-line basis fix** (card decision rule §c returns it: 0.0 admissions/day,
nothing released to be net-negative). The alternative — close as measured and keep the five false journal
rows — is defensible if zero churn on a rail clean for 53 days is preferred; it is FLAG 2.

## 1. The defect, verified in this tree

`scripts/score-trades.ts` @ `947ceb5`:

| where | what |
|---|---|
| L217-235 | the maps are seeded from truth: `PaperTrade WHERE botId='BANKROLL_200' AND status='open'` |
| L1082-1100 | the v55 gate; the seat is taken **inside the pass branch** at L1098-1099 |
| L1108-1157 | v58 per-wallet ceiling — the only `continue` below the seat (L1154) |
| L1159-1209 | `openPaperTrade(...)` — the point the leg actually books |
| L1279-1281 | `catch` around the booking: a throw skips the booking and never releases a seat |

```ts
if (verdict.blocked) { …refuse…; continue; }
c200MarketLegs.set(t.marketId, legsHere + 1);        // ← seat consumed here
c200MarketNotional.set(t.marketId, notionalHere + sizeHere);
```

**Correction to the card's gate list (re-verified today).** The card names four later gates. Measured
against the code, they fire **before** the seat: `maxCopiesPerCycle` L625, wallet-daily cap L632, gross
exposure / drawdown / circuit breaker L654-732, `maxOpenPositions` L767. **v58 is the only gate below the
seat.** Any "decrement on every downstream refusal" variant would be guarding a gate order that does not
exist; the booking-point form avoids the question entirely.

The second carrier is a thrown exception out of `openPaperTrade` swallowed at L1279. Measured size:
**0 rows all-time** (non-demo `paper_copy` decisions with no `PaperTrade` child, 0 with no `FillIntent`
either). Bounded, not proven impossible — but it has no historical instance.

## 2. Measured basis, re-derived today

Population = C-200 non-demo decisions carrying a `v55 per-market cap` refusal · level = one decision ·
clock = `createdAt` UTC · ground truth = the booked C-200 legs' own `[openedAt, COALESCE(closedAt,
resolvedAt))` intervals per `marketId`. Rail live since RuleSet **v55 (2026-09-17T05:03:12Z)**; active
RuleSet **v72**, `maxMarketLegsPerMarketId=2`, `maxMarketNotionalPctOfCap=0.20` — unchanged by this card.

| window | refusals | legs clause | notional | genuine | phantom |
|---|---|---|---|---|---|
| lifetime (56.7 d) | 81 | 60 | 21 | legs 55 · notional 21 | **5** (8.3 % of legs clause) |
| last 30 d | 4 | 4 | 0 | 4 | **0** |

Basis note on the `genuine` column: the tsx instrument labels the 21 notional-clause rows `unknown`
(it only classifies the legs clause); the probe here labels them `genuine` when the market truly held
notional at the decision instant (all 21 did — they are the pre-growth $125.12-ceiling refusals of
2026-09-18). The two instruments agree exactly on the legs clause: **55 genuine / 5 phantom of 60**.

Rates: 1.43 refusals/day lifetime; **0.088 phantoms/day lifetime, 0.00/day for the last 53.5 days**
(last phantom 2026-09-20T05:31:20Z).

```
$ python3 scripts/permarket-seat-release.py
active RuleSet v72 | maxMarketLegsPerMarketId=2 maxMarketNotionalPctOfCap=0.2 | v55 live since 2026-09-17 05:03:12Z
[1] v55 refusals all-time: 81 | clause {'notional': 21, 'legs': 60} | class {'genuine': 76, 'phantom': 5}
    first->last refusal span 45.9 d | rail age 56.7 d | refusal rate 1.43/day | phantom rate 0.088/day
    last 30d: 4 refusals, 0 phantom
```

## 3. The five phantoms — mechanism, not inference

Seats are per `marketId`, so the reconstruction is **same-market**, not same-wallet. Three leak events
produced five phantom refusals; every leaked candidate is the same wallet (`0xb0c85813…`) that v58 had
already refused microseconds earlier.

| # | decision (UTC) | market | printed | true open | v58 peer (µs before) |
|---|---|---|---|---|---|
| 1 | 09-19 20:58:11.233 | will-voter-turnout ≥62 RU | legs 3 > max 2 | 1 | −0.405 s: $1,033.59 > cap $431.38 |
| 2 | 09-19 20:58:11.281 | *same market* | legs 3 > max 2 | 1 | (seat held by #1's leak) |
| 3 | 09-19 20:58:11.457 | *same market* | legs 3 > max 2 | 1 | (seat held by #1's leak) |
| 4 | 09-20 03:59:54.958 | highest-temp Helsinki 17c | legs 3 > max 2 | **0** | −0.219 s and −0.065 s: $1,008.65 > $433.29 |
| 5 | 09-20 05:31:20.629 | highest-temp Hong Kong 32c | legs 3 > max 2 | **0** | −0.352 s and −0.095 s: $1,008.65 > $431.58 |

Row-by-row walk for #1 (seed 0 → one leg booked at −0.887 s → one seat leaked by the v58 refusal at
−0.405 s → count 2 → printed 3). Rows 4 and 5 are the card's headline case literally: **two seats
consumed, zero positions open.** Each refused decision has **0 `FillIntent` rows** — nothing was dispatched.

## 4. What the repair would admit: zero

| # | candidate wallet open at decision | v58 ceiling in force | projected | verdict |
|---|---|---|---|---|
| 1-3 | $1,023.59 (53 legs) | $431.38 | $1,033.59 | refused, 2.37× over |
| 4 | $998.65 (50 legs) | $433.29 | $1,008.65 | refused, 2.30× over |
| 5 | $998.65 (50 legs) | $431.58 | $1,008.65 | refused, 2.31× over |

Releasing the seat moves each candidate to the **next line of code**, where the same wallet is already
2.3–2.4× over its own ceiling. **Admission delta = 0 legs, all-time** — not "<1/day", exactly zero. The
repair changes what the journal says, not what the bot admits.

Value arm if they *had* been admitted (moot, for completeness): +$4.48 per $1 over 5 rows, 3 of them the
same market+outcome — read it as one bet counted three times, not a P&L claim. The journal persists
`simulatedPositionSize` on 4 of 81 refused decisions, so no dollar total is quoted.

## 5. The rail's binding baseline (this decides the refutation test)

Re-measured today over every C-200 market touched after v55 activation:

```
markets touched post-v55: 991
max concurrent C-200 legs per market, distribution: {1: 936, 2: 55}
markets ever holding 3+ concurrent legs post-v55: 0
post-v55 legs opened on a market already holding >=2 live legs: 0 of 1,054
```

The rail binds exactly as designed. (The 10-30 draft's "0 of 727, max 2" reproduces in shape, not in
count — the population grew. Two markets *carry* ≥3 concurrent legs at instants before v55 activation;
that is grandfathered pre-activation stock holding back new admissions, not a breach.)

## 6. The change

Chosen form: **move the increment to the booking point**, not "decrement on every downstream refusal".
There is exactly one such path today, but that shape must be maintained in lockstep with gate order and
silently re-creates the defect the day a gate is inserted below v55.

```diff
@@ -1095,8 +1095,6 @@
               legBlocks.push(`BANKROLL_200: v55 per-market cap (${verdict.why})`);
               continue;
             }
-            c200MarketLegs.set(t.marketId, legsHere + 1);
-            c200MarketNotional.set(t.marketId, notionalHere + sizeHere);
           }
@@ -1217,6 +1215,19 @@
           // since 2026-10-30, one duplicating a -$35.98 loss.
+          // v55 seat-basis fix (2026-10-30 proposal on card permarket-legs-seat-release,
+          // re-measured 2026-11-12): the seat is consumed by the leg that actually
+          // books, not by a candidate that merely passed the check and then died at a
+          // later gate (only v58 sits below it). Before the fix: 5 of 60 legs-clause
+          // refusals printed `legs 3 > max 2` with 0-1 legs truly open.
+          if (botId === "BANKROLL_200" && (c200MarketNotionalCap > 0 || rules.maxMarketLegsPerMarketId > 0)) {
+            c200MarketLegs.set(t.marketId, (c200MarketLegs.get(t.marketId) ?? 0) + 1);
+            c200MarketNotional.set(
+              t.marketId,
+              (c200MarketNotional.get(t.marketId) ?? 0) + (positionSize || 0.25)
+            );
+          }
+
           openCopyKeys.add(positionIdentityKey(t.walletAddress, t.marketId, t.outcome));
```

Unchanged: `maxMarketLegsPerMarketId=2`, `maxMarketNotionalPctOfCap=0.20`, no RuleSet version, no schema,
no `rules.ts`, no sizing field, no threshold. The increment sits immediately after `openPaperTrade`
returns and **before** the `copies++`/Discord/`premiumRisk` block, so a Discord or journal-write throw
cannot skip it.

Two honest limits of the fixed counter:

1. **For C-200 the booking point is the dispatch.** The row is written by the Rust sidecar's webhook, so
   the seat counts dispatches that passed every gate. Measured `FillIntent.dispatchedAt →
   PaperTrade.openedAt`: n=581, median **0.01 s**, p90 **0.05 s**, max **3.19 s**. A dispatch the sidecar
   later drops still consumes the seat — **fail-closed**, never phantom-admitting. (Related, out of
   scope: 219 of 802 C-200 `FillIntent` rows have no linked `PaperTrade` — a dispatch→row drop worth its
   own card. It makes this residual one-directional.)
2. **The seed stays once-per-run**, so a leg that closed earlier in the same run is still counted. That
   error exists today, is unchanged by this hunk, and errs the same way.

## 7. Decision rule (card §c), applied

| condition | measured | verdict |
|---|---|---|
| repair changes fewer than 1 admission/day | **0.0 admissions/day** (§4) | pass |
| released legs not net-negative per $1 | nothing released in practice; value arm +$4.48/$1 on 5 rows (§4) | pass |
| the rail's purpose (≤2 legs/market) survives | 0 of 991 markets ever at 3+ post-v55 (§5) | must hold post-fix — see §8 |

Both stated conditions hold, so the card's own rule returns **apply**. What is bought: the skip histogram
and the refit sample stop carrying five `skip` rows whose printed reason claims two open legs where none
were open (same class of fix the operator approved for `slug-cap-counter-basis`, 77/105 phantom there).
What is not bought: copies, or money.

## 8. Refutation (pre-registered — read the result with this)

Re-run after any landing:

```
export DATABASE_URL="file:$PWD/prisma/dev.db?mode=ro"
npx tsx scripts/permarket-cap-blocked-legs.ts --days 30    # class split
```

REFUTED / REVERT IF, on the first ≥30 d window after the fix:

1. **Phantom refusals persist** — any v55 row printing `legs N > max 2` with `N−1 >` the true concurrent
   open count at decision time. The seat was then not the cause. (Power: baseline is 0 phantoms in the
   last 53 d, so this test can only catch a reintroduction, never confirm the fix.)
2. **The rail stops binding** — any C-200 `marketId` reaching **3+ concurrent open legs**. Pre-fix
   baseline 0 of 991 markets, max 2. An undercounting seat breaches the cap the rail exists to hold:
   revert on first instance.
3. **The rail goes silent** — zero v55 refusals over 30 d where the live rate is 1.43/day (4 in the last
   30 d). A silent loss of the gate is not a fix.

## 9. Verification actually run today

```
$ npx tsx scripts/permarket-cap-blocked-legs.ts --days 0
  refused 81 legs across 13 markets | clause: legs 60 / notional 21
  class: genuine 55 / phantom 5 / unknown 21          (81 = 55 + 5 + 21; unknown = notional clause)
  settlement known for 81/81 (market 81, event 0; 0 undetermined, NOT guessed)
  priced 81: per $1 mean $2.45 median $2.28 sum $198.83 | ex-top-10 $144.82
  genuine-seat refusals only: n=55 mean $1.98 sum $109.09
$ npx tsx scripts/permarket-cap-blocked-legs.ts --days 30
  refused 4 legs across 3 markets | clause: legs 4 / notional 0 | class: genuine 4 / phantom 0
$ python3 scripts/permarket-seat-release.py  # §1 class split, §3 mechanism, §5 baseline, carriers
  [3] markets touched post-v55: 991 | max concurrent C-200 legs distribution: {1: 936, 2: 55}
      post-v55 legs: 1054 | 3+ concurrent-leg instants or admit-on->=2 events: 0
  [4] openPaperTrade-throw carrier: childless paper_copy 0 (of which no FillIntent: 0)
      FillIntent->PaperTrade lag: n=581 median 0.01s p90 0.05s max 3.19s
      C-200 FillIntent rows with no linked PaperTrade: 219 of 802 (fail-closed direction)
$ npx tsc --noEmit            # run WITH the §6 hunk applied
tsc exit=0
$ npx vitest run
Test Files  93 passed (93)
     Tests  989 passed (989)
$ git checkout -- scripts/score-trades.ts && git diff --stat scripts/score-trades.ts
(empty)   # hunk removed; tree clean for scripts/
```

Every DB read opened `prisma/dev.db` read-only (`?mode=ro`). No `apply-v*.ts` was run, no RuleSet row or
`prisma/dev.db` write was made, and nothing was committed or merged.

## 10. Rollback

`git revert` of the single commit. No RuleSet version, no threshold, no sizing field, no schema, no data
migration. The journal keeps whatever it recorded either way.

## 11. Flags — what an approval means

- **FLAG 1 — apply the seat basis fix (§6).** *Recommended.* Revert = `git revert` of the one commit, or
  move four lines back. Number that moves: the phantom share of legs-clause refusals (8.3 % → ~0), **not**
  admissions (0.0/day) and not PnL.
- **FLAG 2 — close it instead.** Say "close it": card → Done with this measurement attached and the
  instrument kept, no code change. Cost of closing: five false journal rows, all on 2026-09-19/20.
- **FLAG 3 — the card's gate list is wrong** (v58 is the only later gate; the other three fire before the
  seat). Recorded here so no future "release on every refusal path" variant is built against it.
- **FLAG 4 — two sibling seats are NOT touched.** The **v45 per-slug seat** (`c200SlugCounts`, L816-828,
  incremented on pass at L827 — above the v55 gate, so it leaks on v55 refusals too) and the **v41
  category seat** (`c200CategoryCounts`, L703-718, incremented on pass at L717; since 2026-11-06 it
  *prints* its true basis via `c200CategorySeat`/`categoryTrueOpen`, but the gate still counts attempts).
  Same shape, same fix form. Say "bundle the slug/category seats" to add them — each needs its own
  measurement first (the slug cap's phantom share was 77/105 = 73.3 % on its own card).
