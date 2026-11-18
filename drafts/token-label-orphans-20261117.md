# Token-label orphans: the rename class, audited across the whole book (2026-11-17)

**Card:** `token-label-alias-phantom-loss` · **Lane B, read-only** · nothing applied to any rule, size,
threshold or settlement path.

## The question the card pre-registered

A venue token can be RENAMED between our ingest and its settlement. `didOutcomeWin`
(`src/lib/resolution.ts`) compares **labels**, deliberately refusing to guess across label spaces, so a leg
opened under the retired label can only read "lost" against the new one. The card held one leg
(`ufc-jon5-jos27-2026-11-07`, `JOSE HENRIQUE`, −$9.00, the same token as the `JOSE SOUZA` leg that won
+$4.14) and fixed two gates in advance:

- **ACT** when the class reaches **≥ $100** of booked PnL **or ≥ 5 legs**;
- **REFUTE** if a further audit of **≥ 500 more markets** finds no further instances.

## Basis of every number below

- **population** — settled `PaperTrade` legs (`isDemo=0`, `status='resolved'`, `resolvedAt NOT NULL`):
  the only legs whose PnL can depend on a label compare. Early exits are excluded.
- **level** — one leg / one market. **clock** — `resolvedAt` (UTC); venue label sets read at
  `2026-11-18T02:09Z`.
- **truth** — CLOB `GET /markets/<conditionId>` → `tokens[].outcome` / `[].winner`.
- **instance** — deliberately narrow: stored label non-binary, the venue market has exactly two tokens,
  both venue labels non-binary, and the stored label is absent from the current set. A leg is only
  **priced** when the token it held can be established (see *Identity* below); everything else is counted
  unresolved, never assumed.

## Result

| read | value |
|---|---|
| settled legs / markets | 3,848 / 1,710 |
| with venue truth | 3,808 legs (98.96%), 1,709 markets |
| **rename orphans** | **1 leg, 1 market** (the card's own instance) |
| booked on instances | −$9.00 → **error $13.14** (identity says +$4.14) |
| binary-vs-named, multi-token absent | 0 and 0 |
| no venue truth | 40 legs — **all** the known no-identity cohort |

**The gate that fires is the refutation, not the act.** 1,172 markets were audited beyond the 537 the
2026-11-16 audit covered (target: 500), and the count did not move off the one known instance. Both act
clauses fail by a wide margin: $13.14 vs $100, 1 leg vs 5. Per its own pre-registered rule the card closes
as a documented curiosity with a re-open condition, **not** as a restatement.

## Identity: how the one instance is priced without a stored token id

The instrument does not assume the leg held the winner. It asks the record first:

- **twin_flip** (fired here) — the venue published the *same print* under both labels: same condition,
  same price within $0.01, same instant within 1h. That is the rename on our own tape, not an inference.
- **sibling_leg** — another leg on the same market carries a current label at the same entry (±$0.005)
  within 2h. Weaker, same shape.
- otherwise **unresolved**, uncounted as error: the leg may have held the losing token, in which case the
  booked loss is correct.

Concentration check before believing anything: the whole error is one leg (`ex_top_instance_error_usd`
= $0.00), which is the same thing as saying the class *is* the instance.

## The real finding: the identity key exists at ingest and is thrown away

`src/lib/adapters/polymarket.ts` already maps the data API's `token_id` → **`asset`** and
`outcome_index` → `outcomeIndex`. `scripts/monitor-trades.ts` persists `rawTradeJson: "{}"` and no token
column, so the one key that settles this class by identity never reaches the DB. Any future rename
diagnosis has to reconstruct identity from price coincidence, exactly as above. Carded as
`token-identity-not-persisted` (Backlog, needs its own schema pass) — **not** built here.

## Not re-derived

The 40 legs with no venue truth are the blank-`marketId` / event-id-`conditionId` cohort already measured
on `parlay-rows-in-decision-path` (2026-11-06): −$412.97, 40/40 booked as full losses in one batch resolve
with no venue label, deliberately left booked because inventing an identity would be fabricating data.
This instrument joins them and excludes nothing by hand.

## Re-run / rollback

```
python3 scripts/token-label-orphan-read.py --self-test     # 13/13
python3 scripts/token-label-orphan-read.py                  # report off the cache
python3 scripts/token-label-orphan-read.py --fetch-truth    # fill missing venue truth first
```

Artifact `data/token-label-orphan-read.json`. Read-only: SQLite opened `mode=ro`, SELECT only; the only
write is the gitignored CLOB fetch cache. Rollback = delete the script + artifact + this draft; no DB
write, no schema change, no booking path, no published number moved.
