# v45 slug cap counts ATTEMPTS, not open positions — 73% of its refusals are phantom

Date: 2026-10-30 · Lane A · roadmap card `slug-cap-counter-basis` · **PROPOSAL — nothing applied**
Instrument: `scripts/slug-cap-counter-basis.py` (read-only, opens `prisma/dev.db` with `immutable=1`)
Evidence dump: `~/.hermes/cache/scratch/slugcap-30d.json` (105 rows, one per refusal)

## 0. Verdict in one line

The counter behind the v45 15-per-slug cap consumes its budget on candidates that **never opened a
position**, so 77 of 105 cap refusals in the last 30 days printed a basis (`would be 16/15`) that
claimed 15 open legs when as few as **zero** existed. Approve it as a **basis-truthfulness fix**.
The money attached to the phantoms does not clear zero (mean +$0.149/$1, market-clustered CI
[−0.423, +0.589]), and at most 33 extra legs in 30 days could pass the gates that come after the
cap — so this is not an admission or profit lever.

## 1. The defect (code, verified in this tree at 1f5f77a)

`scripts/score-trades.ts`

- L263 `const c200SlugCounts = new Map<string, number>()` — seeded **once per scoring run** from
  `PaperTrade WHERE botId='BANKROLL_200' AND status='open'` (L216-268), i.e. from truth.
- L777-789 the check. The bucket is incremented **inside the pass branch** of the check:

  ```
  const slugOpen = (c200SlugCounts.get(t.marketCategory) ?? 0) + 1;
  if (slugOpen > rules.maxMarketSlugPositions) { …refuse… }
  c200SlugCounts.set(t.marketCategory, slugOpen);      // ← slot consumed here
  ```

  Everything that can refuse the copy afterwards — `kelly no-edge` (L849-855), `STANDARD` entry cap,
  `c200MaxEntryPrice` (L1016-1020), `band skip` (L1032-1038), `v55 per-market` (L1043-1061),
  `v58 per-wallet` (L1069-1118) — is a `continue` **after** the slot was taken. Nothing decrements.
- The `openPaperTrade` dispatch is at L1120 and `legsOpened++` at L1165; `c200SlugCounts` is written
  in exactly four places (L263, L268, L778 read, L788 write) — there is no release path at all.

Consequence inside one run: once 15 same-token candidates have *passed the check*, every later
same-token candidate of that run is refused at `16/15` for the rest of the batch, whatever the first
15 actually did. Because `SCORE_BATCH_LIMIT` defaults to 400 observations, a league token with many
observations in one batch fills its bucket from a handful of seconds of scoring.

## 2. Measured basis — the card's numbers reproduce

Population: `DecisionJournal` rows, `isDemo=0`, window **2026-10-01T00:38Z .. 2026-10-31T00:38Z**,
`risksJson` carrying `BANKROLL_200: v45 market-slug cap (<token> would be N/15)`; level = decision.
True concurrent open count reconstructed from C-200 legs on the same raw `marketCategory` token over
`[openedAt, COALESCE(closedAt, resolvedAt))`.

| token | refusals | GENUINE (true open ≥ 15) | PHANTOM (true open < 15) | true open at refusal |
|---|---|---|---|---|
| dota2 | 33 | 0 | 33 | 0..3 |
| mex | 28 | 0 | 28 | 0 |
| cfb | 21 | 21 | 0 | 15 |
| fl1 | 9 | 0 | 9 | 2 |
| ufc | 7 | 7 | 0 | 15 |
| epl | 6 | 0 | 6 | 0 |
| nhl | 1 | 0 | 1 | 9 |
| **total** | **105** | **28** | **77** | phantom share **73.3%** |

77 of the 105 printed `would be N/15` with `N-1 > true open`, i.e. the bucket held at least one
position that did not exist. Worked example (measured, single second):

```
2026-10-21 21:17:42Z  token 'mex'  15 decisions refused by 'kelly no-edge'
                                   19 decisions refused by 'v45 market-slug cap (mex would be 16/15)'
                    C-200 mex legs opened that calendar day: 0
```

The 15 `kelly no-edge` rows are the ones that filled the bucket; they opened nothing, so the 19 rows
behind them refused a cap that had never been reached. `mex` never had a single open leg at any of its
28 refusals in the window.

## 3. What the refused legs would have earned (unit notional, hold to settlement)

Basis: `$1` per refused decision, entry = `ObservedTrade.detectedPrice` (no maker credit, no fee),
win/lose from the market's own settled winner (keyless CLOB archive `/markets/<conditionId>`,
`tokens[].winner`, 105/105 resolved, 0 undetermined), mean CI = percentile bootstrap resampling
**markets** (2,000 draws, seed 20261030).

| class | n | sum | mean/$1 | median | win rate | mean CI |
|---|---|---|---|---|---|---|
| GENUINE | 28 | −$7.93 | −$0.283 | −$0.398 | 50.0% | [−0.556, −0.045] |
| PHANTOM | 77 | +$11.44 | +$0.149 | +$0.105 | 75.3% | [−0.423, +0.589] |

ex-top-k (drop the k largest absolute contributions inside the class), sum:

| class | k=1 | k=3 | k=5 | k=10 |
|---|---|---|---|---|
| GENUINE | −$8.99 | −$6.99 | −$4.99 | +$0.01 |
| PHANTOM | +$10.29 | +$7.99 | +$5.69 | +$0.46 |

**Reproduction note, stated rather than smoothed over.** The card's phantom arm reproduces to the
cent (+$11.44 sum, +$0.46 ex-top-10). Its genuine arm does **not**: the card says −$5.78 with
ex-top-10 **−$11.81**; on this construction the genuine class is −$7.93 and ex-top-10 **+$0.01**. The
card does not define its cut, and no cut I tried makes the genuine class *more* negative when its 10
largest contributors are removed (they sum to −$7.94, so removing them must raise the residual). What
this changes for the decision: the card's "the rail is RIGHT about those (ex-top-10 −$11.81)" does not
survive as a robust claim. What survives is weaker and still sufficient — the genuine class has a
CI that excludes zero (mean −$0.283) and is loss-making in every cut up to k=5, but it is carried by
at most 10 legs: on both arms, everything past the top 10 is ≈ zero.

## 4. Reachability ceiling — what the fix could actually admit

The cap fires before kelly / band / entry-price / v55 / v58, so a cap-refused row records nothing
about what those gates would have said. Three of them are reconstructable from the row itself
(price and ruleSet version are stored per decision; `v55` from that market's open-leg intervals),
which gives an **upper bound** on the legs this fix could admit (kelly and confidence are not
reconstructable here — that is what makes it an upper bound):

| class | refusals | blocked by high-entry (>0.80) | blocked by band skip (0.4-0.6) | blocked by v55 | survive → could be admitted |
|---|---|---|---|---|---|
| PHANTOM | 77 | 28 | 16 | 0 | **33** (value +$6.32 unit-notional) |
| GENUINE | 28 | 2 | 0 | 0 | 26 — but still cap-refused (true open is 15, so 16/15 stands) |

And the cap is a small slice of these tokens' refusal flow in the same window (decision-level skips
fire before the per-bot loop, so the C-200 leg was never evaluated on them):

| token | cap refusals | decision-level skips | of which confidence | leg-level kelly | leg-level band skip |
|---|---|---|---|---|---|
| epl | 6 | 3,658 | 1,371 | 160 | 74 |
| dota2 | 33 | 2,237 | 1,915 | 214 | 5 |
| nhl | 1 | 603 | 323 | 4 | 29 |
| cfb | 21 | 481 | 420 | 51 | 91 |
| mex | 28 | 261 | 257 | 28 | 4 |
| fl1 | 9 | 246 | 86 | 40 | 15 |
| ufc | 7 | 229 | 116 | 73 | 27 |

7,715 decision-level skips against 105 cap refusals for the same seven tokens: the rail is not what
is holding these tokens back, which is exactly why the card's option (c) — "approve as a
basis-truthfulness fix, not a profit fix" — is the right frame.

## 5. The change (exact, one site moved)

Chosen over the two alternatives named in the card:

- **Decrement at every downstream `continue`** — six call sites plus the `catch` path at L1216; a gate
  added later without the release re-creates the defect silently. Rejected: it must be maintained in
  lockstep with gate order.
- **Re-seed the map from the DB per candidate** — correct but one `paperTrade.findMany` per candidate
  inside the hot loop; measured seed query already handles ~2,560 rows at run start.
- **Move the write to the booking point** (chosen): the slot is consumed where the position is
  actually created, which is the semantic the cap claims.

```diff
@@ -785,7 +785,6 @@ async function main() {
             continue;
           }
-          c200SlugCounts.set(t.marketCategory, slugOpen);
         }
 
         try {
@@ -1164,6 +1163,15 @@ async function main() {
           openCopyKeys.add(`${t.walletAddress}|${t.marketId}|${t.outcome}`);
           legsOpened++;
 
+          // v45 basis fix (2026-10-30, Lane A proposal on card slug-cap-counter-basis):
+          // the slug slot is consumed by an OPENED leg, not by a candidate that merely
+          // passed the cap check and then died at kelly / band skip / high-entry / v55 /
+          // v58. Measured before the fix: 77 of 105 cap refusals in 30d printed a basis
+          // with fewer than 15 legs actually open (73.3% phantom).
+          if (botId === "BANKROLL_200" && rules.maxMarketSlugPositions > 0 && t.marketCategory) {
+            c200SlugCounts.set(t.marketCategory, (c200SlugCounts.get(t.marketCategory) ?? 0) + 1);
+          }
+
           // Counters and the copy alert belong to a SUCCESSFUL open, so they live
```

Unchanged: `rules.maxMarketSlugPositions` stays **15** (active RuleSet v70), no basis change, no
RuleSet version, no schema, no `rules.ts` edit.

Two honest limits of the fixed counter:

1. For C-200 the row is written asynchronously by the sidecar's webhook (`openPaperTrade` returns
   `rust-pending`), so the counter counts **dispatches that passed every gate**, not confirmed rows.
   A dispatch the sidecar later rejects consumes a slot with no position — i.e. the residual error
   is fail-closed (it can refuse a copy that would have been allowed), never phantom-admitting.
   Counting confirmed rows would need the webhook and is out of scope here.
2. The seed is still once per run, so a leg that closed earlier in the same run is still counted.
   That error exists today and is unchanged by this hunk.

Same-class leak, deliberately **not** bundled: `v55` (L1059-1060) and `v58` (L1117) also increment on
the pass branch. `v58` fired **0 times** in the window (measured: 0 decisions carry a v58 block; 44
carry a v55 block), so the v55-slot leak had no observable victim in 30d. It is a separate 3-line
change if you want it; folding it in makes the diff explain two rails at once.

## 6. Decision rule — what an approval means

Approve **as a basis-truthfulness fix**: a printed reason that says 15 open legs should not be printed
when 0 are open. Expected effect, pre-registered from the numbers above:

- refusals fall from ~105/30d to ~28/30d (the GENUINE class survives: true open 15 → `16/15` still
  refuses);
- at most **33 extra legs / 30d**, worth **+$6.32** unit-notional before kelly, i.e. ≈ +$60/month at a
  $10 clip with a CI that spans zero — no reason to expect a PnL move, and no reason to refuse the
  change on PnL grounds either;
- the journal's cap rows become a truthful measurement of a real constraint.

If the goal is more copies admitted, this is not the lever (§4: 7,715 decision-level skips vs 105 cap
refusals on the same tokens). The lever for that is the liquidity-side of the cards now in the queue.

## 7. Refutation (pre-registered — do not read the result without this)

Baseline to compare against (weekly cap refusals, by class, same instrument):

| week | total | genuine | phantom |
|---|---|---|---|
| 2026-W40 | 25 | 25 | 0 |
| 2026-W41 | 36 | 3 | 33 |
| 2026-W42 | 7 | 0 | 7 |
| 2026-W43 | 28 | 0 | 28 |
| 2026-W44 | 9 | 0 | 9 |

**REFUTED IF, on the first full week after the fix lands:**

1. weekly cap refusals do **not** fall by roughly the phantom share — i.e. `phantom/total` on the
   post-fix rows is not below ~20% (a truthful counter can only print ≥15 true open); or
2. the admitted-extra legs (decisions that post-fix reach `openPaperTrade` where they were
   cap-refused before) carry a per-$1 mean ≤ 0 over **≥30 extra legs**, measured on the same
   settlement basis; or
3. total `/30d` refusals do not move at all — that would say the counter was never what bound, and
   the change is only cosmetic.

Read it with:

```
python3 scripts/slug-cap-counter-basis.py --days 7
```

which prints the class split, the weekly table and the value arm. Clause 1 is self-checking: a
correct fix makes `would be N/15` rows extremely rare at N<16, because the printed N is now `open+1`.

## 8. Rollback

Single-site revert: move `c200SlugCounts.set(...)` back into the pass branch (or `git revert` the one
commit). No schema, no RuleSet version, no `rules.ts`, no data migration, no backfill — the journal
keeps whatever it recorded either way.

## 9. Verification actually run (not inferred)

```
$ python3 scripts/slug-cap-counter-basis.py --days 30 --end 2026-10-30T19:38:16Z
population: 105 slug-cap refusals on 105 decisions written in [2026-10-01T00:38:16Z, 2026-10-31T00:38:16Z)
legs: 2560 C-200 non-demo legs across 188 tokens (5 still open)
… TOTAL 105 genuine 28 phantom 77  phantom share 73.3%
OUTCOME COVERAGE: 105/105 refusals resolved (settled winner published on the market's conditionId)
exit=0
```

```
$ npx tsc --noEmit          # run WITH the §5 hunk applied to scripts/score-trades.ts
tsc exit=0
$ git checkout -- scripts/score-trades.ts && git status --short
?? scripts/slug-cap-counter-basis.py          # hunk reverted; worktree carries no code change
```

```
$ npx vitest run            # clean tree, regression baseline
Test Files  68 passed (68)
     Tests  678 passed (678)
  Duration  11.48s
```

No test exercises this counter: it is inline inside `main()` with no exported seam, so the only
mechanical proof available is the type-check plus the post-landing journal read in §7. If a seam is
wanted, extract `slugSlotDecision(count, cap)` and unit-test the boundary (14→15 admit, 15→16 refuse)
in the same commit — optional, +15 min.

Nothing in this run wrote to `prisma/dev.db` (all reads `immutable=1`), ran any `apply-v*.ts`, changed
a rule, size, gate or threshold, or touched `main`.

## 10. Overridable flags

- **FLAG 1 — counter basis.** Move the increment to the booking point (§5). *Recommended.* Revert =
  move one line back; the number that moves is weekly cap refusals (105/30d → ~28/30d). Say "keep
  attempts" to drop this card.
- **FLAG 2 — booking point = dispatch for C-200.** The counter counts dispatches, not confirmed rows,
  so a sidecar-rejected dispatch still consumes a slot (fail-closed). Number that moves if changed:
  none today — 0 measured cases in the window.
- **FLAG 3 — v55/v58 slot leak.** Same class, not bundled (v58 fired 0 times in 30d, 44 v55 blocks).
  Say "bundle v55" to add the second hunk; it raises the diff to two rails.
- **FLAG 4 — cap value / basis.** No change: `maxMarketSlugPositions` stays 15 and the token basis is
  settled by `slug-cap-token-granularity` (mega-bucket no longer binds). Not re-opened here.
