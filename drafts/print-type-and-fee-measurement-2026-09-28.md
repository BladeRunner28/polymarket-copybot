# Print-type + fee-schedule measurement (2026-09-28)

Two measurements ported from `drafts/polyterm-audit-2026-09-28.md` (§P6 print-type
exclusion, §P2 fee assumption) were run for real against keyless venue reads today.
This is the write-up of what they returned.

**Nothing in a live path changed.** No RuleSet version, no threshold, no size, no gate,
no published number. Both scripts are capture/measure-only, both are explicitly
`not_read_by_live_path`, and the code changes made today are (a) a bug fix in the audit
script's own reporting, (b) three tape types named in a classification helper whose
behaviour for them was already "not a fill", and (c) three extra fields captured into an
append-only JSONL. The two decisions this evidence would justify are §Recommendations
and are recommendation-only.

Artifacts: `data/print-type-audit.jsonl` (64 rows), `data/fee-schedules.jsonl` (48 rows),
`scripts/audit-print-types.ts`, `scripts/capture-fee-schedules.ts`,
`src/lib/print-types.ts`, `tests/print-types.test.ts`.

---

## 1. Print-type measurement (§P6) — the control held, and it held by a wide margin

### Method

The question was whether non-fill rows can reach our book. `data-api.polymarket.com/activity`
mixes real fills with position-management rows (`split`, `merge`, `redeem`, `conversion`,
liquidity ops, deposits/withdrawals), and our adapter never inspected `row.type`. So the
same 30 wallets, same 7-day window, same 500-row page were read twice — once the way the
live adapter reads them (`&type=TRADE`, the server-side filter), once with that filter
removed, which is what a client-side classifier would actually have to catch.

### Result — identical wallets, identical window

| read | rows | fills | non-fills |
|---|---|---|---|
| `&type=TRADE` (live path) | 14,500 | 14,500 (100%) | 0 |
| no server filter (counterfactual) | 14,500 | 11,981 (82.6%) | 2,519 |

Dropped types in the counterfactual, by count:

- `redeem` — 1,359 (53.9% of drops)
- `conversion` — 571 (22.7%)
- `merge` — 542 (21.5%)
- `maker_rebate` 16 · `reward` 16 · `taker_rebate` 12 · `yield` 2 · `split` 1

### Key insight

**17.4% of activity rows on our own tracked wallets are not prints** — and the server-side
filter we already send is what keeps them out. That is the number that matters: it is the
blast radius if the filter is ever dropped, changed, or bypassed by a new path. Booking
those 2,519 rows as copies would have invented that many phantom trades, at prices nobody
crossed, on wallets we actually follow.

### Reality checks

- **The live exposure today is zero, and that is a verified result, not an assumption.**
  `src/lib/adapters/polymarket.ts:297` is the only `/activity` read and it sends
  `type=TRADE`. The `/trades` tape used by `scripts/c200-printthrough.py:150` carries no
  filter parameter at all — so it was sampled directly: 3,000 rows across 6 high-volume
  markets, **0 rows carry a `type` field**, and every row has price/size/outcome. It is a
  fills-only surface. No live path today is exposed.
- **Both reads returned exactly 14,500 rows — that is the page cap, not a coincidence.**
  29 of 30 wallets returned a full 500-row page, so all counts above are lower bounds, and
  it also means an unfiltered read does not surface *more* trades: non-fill rows consume
  page slots. The server filter strictly dominates a client-side one for trade coverage; a
  client-side classifier could not recover those slots.
- 4 of 30 wallets had zero non-fill rows, 1 of 30 returned an empty page in the window.
- **The ported list was incomplete.** `maker_rebate`, `taker_rebate` and `yield` appear on
  the real tape and were not in the source repo's eight. `isTradeRow` already returned
  false for them via the unknown-type default, so behaviour did not change — but had we
  wired the filter in without this run, three real tape types would have been dropped as
  "unknown" rather than recognised, and an *unrecognised* type is exactly the case the
  conservative default hides.
- **A bug in the audit tool itself, found by running it.** Its "unclassified types" check
  compared a raw-case string (`REDEEM`) against lowercased keys, so it flagged every
  skipped row and the signal was worthless. Fixed, and the signal is now a set-membership
  test (`isKnownRowType`) that fires only on a type we have never catalogued — the thing
  that would silently shrink ingest if the venue adds a row type.

## 2. Fee-schedule capture (§P2) — the proxy rate is wrong on 45% of markets, in both directions

### Method

Our admission gate prices the taker fee with the right curve
(`takerFeePerShare(price, feeRate)`) but a **proxied rate**: `defaultFeeRate = 0.05` plus a
keyword table (crypto .07, politics/finance .04), inferred from the slug because
`MarketSnapshot.category` is NULL. The venue publishes structured truth per market. 40 of
the top-volume active markets were captured (Gamma `feeType` + `feeSchedule`, plus CLOB
`/fee-rate` per token), and both fee-per-share figures computed at the observed mid.

### Result — 18 of 40 markets (45%) disagree with the live gate

| venue `feeType` | venue rate | n | proxy rate | per-share delta |
|---|---|---|---|---|
| `sports_fees_v3` | 0.05 | 15 | 0.05 | 0 |
| `zero_fees` | 0 | 7 | 0.05 | **+1.25¢** |
| `sports_fees_v2` | 0.03 | 4 | 0.05 | **+0.50¢** |
| `crypto_fees_v2` | 0.07 | 4 | 0.07 | 0 |
| `economics_fees` | 0.05 | 3 | 0.04 | **−0.25¢** |
| `politics_fees` | 0.04 | 1 | 0.04 | 0 |
| none published | 0 / 0.05 | 6 | 0.05 | +1.25¢ (4) · 0 (2) |

`rebateRate` is also published and unmodelled by us: 0.15 (17 markets), 0.25 (8), 0.20 (4),
0 (7), absent (4).

### Key insight

The fee assumption is not noise around a right answer — it is wrong in **both**
directions, and the two directions cost different things:

- **Over-charging (15 markets, +0.50¢ to +1.25¢/share):** on a 50¢ contract that is 1–2.5%
  of notional charged to our own gate, so the gate rejects copies that are genuinely
  profitable. Zero-fee markets are currently taxed at the default rate.
- **Under-charging (3 markets, `economics_fees`, −0.25¢/share):** the macro/Fed markets our
  keyword table guesses at 0.04 are actually charged 0.05, so the gate **admits** trades
  whose real net edge is a quarter-cent per share lower than we think. Same failure shape
  as the archive finding (gross +$5,397.60 → net +$2,933.77, 238 winner→loser flips): the
  errors that matter are the ones that admit.
- **`feeType` is the discriminator, not text.** Rate is a pure function of `feeType` in
  every market measured. That is a structured field the venue hands us and our gate
  substitutes a slug-keyword guess for.

### Reality checks — including a trap

- **`takerBaseFee` / `makerBaseFee` / CLOB `/fee-rate.base_fee` are NOT market truth.**
  `takerBaseFee` is a constant 1000 on 34/40 markets and CLOB `base_fee` is 1000 on 36/40 —
  identical on markets whose schedule says rate 0 and on markets charged 0.07. It looks
  like a legacy static field. The capture script's fallback path reads it as `base/10000`
  = 0.10/share, i.e. ~2× the highest real rate and ~8× a `zero_fees` market: if Gamma's
  schedule were ever missing, that fallback would double-charge every market. The fallback
  is now tagged `clob_fallback_unit_unverified` in the output rather than silently trusted.
  (Nothing in the live path reads it today.)
- **6 of 40 markets publish no `feeType`** — a consumer must handle absence explicitly,
  which is why the capture now emits `fee_type_missing`.
- **Sample shape:** top-40 by trailing 24h volume, not a random draw — the mix skews to
  sports and crypto, which is where the zero/sports-v2 rates concentrate. The 45% figure is
  a property of the volume-weighted universe our lane actually trades, not of all markets.
- **One snapshot.** Nothing here says a market's `feeType` is permanent; `zero_fees` on an
  NFL game could be event-specific. A single capture cannot answer that, which is why the
  recommendation below is a cadence rather than a one-off.
- The CLOB `/fee-rate` read was included precisely to be a second source and did **not**
  corroborate Gamma — it returned the same constant on everything. Recorded as a negative
  result: we do not have two independent fee sources.

---

## Recommendations (recommendation-only — nothing applied)

**R1 — Wire the print-type classifier into the `/activity` ingest path as a defence in
depth (~30 min).** Expected effect measured: **zero rows today** (the server filter
already holds), so this is insurance, not a fix: it costs nothing, counts skipped rows with
a quality flag, and converts "we rely on a query parameter we do not control" into "we
cannot book a redemption as a buy". Measurably distinct from the fee work — it is a
classification guard, and the gate is unaffected.

**R2 — Replace the keyword rate proxy with venue truth in `price-edge.ts`.** Key on
`feeType` + `feeSchedule.rate` (captured per market), fall back to the keyword table only
when the venue publishes neither, and tag those fallbacks. This is a **rule-input change**,
so it needs your approval and a before/after re-measurement of the gate's admission set on
a frozen window — this write-up is the before.

**R3 — Put `capture:fees` on a light cadence (daily or weekly, keyless, ~40 requests).**
One snapshot cannot tell whether a rate is per-market-permanent or per-event; a short
history makes the fee model's inputs auditable instead of assumed.

Open question R2 would have to answer before it ships: whether the gate's *rebate*
asymmetry matters — we model the taker fee but not the published `rebateRate`, and if our
lane is sometimes the maker, that is an unmodelled credit.

---

## Verification for this document

- `npx tsc --noEmit` — clean.
- `npx vitest run` — **310 passed / 28 files** (was 308; +2 covering `isKnownRowType`).
- Both scripts re-run for real after the patches: `audit:print-types --unfiltered` no
  longer emits a spurious unclassified list, and `capture:fees --dry` prints `feeType`
  alongside rate/rebate (e.g. `nfl-phi-chi-2026-09-29 type=zero_fees venue_rate=0`).
- Venue calls are keyless read-only; capture scripts only append to `data/*.jsonl`.
