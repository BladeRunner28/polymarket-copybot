# Wallet score: the win-rate arms now read the market's outcome, not our exit sign

**Card** `label-integrity-wallet-win-filter` (Lane A value change, operator-approved 2026-11-11T18:36Z,
approvals id `apr-label-integrity-wallet-win-filter`) · **Shipped** 2026-11-11 · **Revert** one hunk
(see §8)

---

## 1. What was wrong

`src/lib/scoring/wallet.ts` derived **every** win-rate term from `(t.pnl ?? 0) > 0` — our own exit
sign:

| arm | line (pre-change) | what it claimed | what it measured |
|---|---|---|---|
| `consistencyScore` win term | 146 | "how often this wallet picks winners" | how often our exit booked a profit |
| `winRate30d` | 245 | same | same |
| `categoryStrengths[*].winRate` | 59 | category fit for `scoreTrade()` | same |

A leg we sold at +40 on a token that then settled to zero counted as a **win**. The row already carried
the venue's answer — `won`, set by `src/lib/adapters/polymarket.ts:337` from a **terminal** mark
(`settledWinFromMark`, band 0.99/0.01) since the label half shipped 2026-10-29 — and the scorer never
read it.

That label half shipped alone because the card's original premise was wrong: it claimed `won` flows
into `winRate30d → globalScore → the copy decision`. It did not; nothing read `won` except the v1/v2
parity diff. Correcting the label was therefore a Lane B repair. **Substituting the basis is not**: it
changes `globalScore`, hence wallet status, hence what the bot copies. That is what this change is.

## 2. The change

`src/lib/scoring/wallet.ts`:

- new `settledWinRate(trades)` — wins = `won === true`, denominator = **resolved legs with
  `won !== undefined`**; a mid-mark leg is excluded, never defaulted, and an all-unknown sample
  returns `null` rather than `0`.
- `consistencyScore()`'s win term and `WalletScore.winRate30d` read it.
- `strengthMap()` (category buckets) uses `t.resolved && t.won === true`.

Unchanged on purpose, same approval: **ROI, copyability, the one-hit-wonder penalty, and the
`resolved` population** that gates them. Those price what the wallet *earned*; only the win-rate arms
claim to price what it *predicted*.

## 3. An instrument defect found while re-running the card's own check

`scripts/wallet-win-basis-audit.ts` sampled its population with
`orderBy: [{status:"asc"}, {globalScore:"desc"}], take: 25`. `status` is a **string**, so `asc` sorts
alphabetically — `ignore < track < watch` — and the take never reached a track row. The report still
printed `population: … (status rank: track first)`.

Consequence: the read that priced this card on 2026-10-29 (and the one I reproduced at 12:40 today —
*"1 of 16 wallets ignore→watch"*, `0x7cca0a0c` g 24.6→25.4, n=100) was taken on the **ignore tier**,
where selection never happens.
Fixed: each tier is queried explicitly (track → watch → ignore), `isDemo:false`, and the report prints
the tier mix it actually sampled.

Two more instrument repairs in the same file: the re-implementation now compares against the basis the
scorer **ships** (it compared `pnl>0` against a scorer that read `pnl>0` — a tautology that would pass
a wrong change), and it uses **unrounded** copyability/penalty internals (multiplying the stored 1-dp
fields into a 0-100 score crossed the 0.1 rounding step and reported 4 phantom "replication
mismatches" on high-score wallets).

## 4. Measured delta — track tier (the population selection acts on)

25 tracked wallets × their closed positions, 30d lookback, fetched 2026-11-11T18:45Z (pre-change) and
18:50Z (post-change), level = leg.

| | settlement flag (`won`) | exit sign (`pnl>0`) |
|---|---|---|
| closed legs | 1,580 | 1,580 |
| legs with a knowable outcome | 1,549 (**98.0%**) | — |
| booked wins | 1,188 (75.2%) | 1,254 (79.4%) |
| wins booked on legs that settled **LOST** | **0** | **60** |
| settled wins called losses | 0 | 0 |
| true settlement win rate (mark + CLOB truth) | 76.7% | — |

Both pre-registered conditions in the card's decision rule hold:

- **(c)(i) coverage ≥ 50%** — 98.0% of closed legs carry a terminal outcome.
- **(c)(ii) no wallet crosses the TRACK floor** — 0 status flips under the substitution, on the track
  tier and against the CLOB-augmented truth arm.
- **Replication** — the audit's independent re-implementation of the scorer reproduces `scoreWallet`
  exactly on the shipped basis: **0 mismatches of 25** (post-change).
- **Stored rows** — all 25 currently match the exit basis (25/25) and only 13/25 match the new one, so
  12 rows will move on the next rotation of the hourly scan. That is the change, visible as a ledger.

Wallet-level size: mean |ΔglobalScore| **0.84**, max **11.1**.

## 5. The one number that matters

| wallet | legs (known) | winRate exit → settlement | globalScore |
|---|---|---|---|
| `0x17dd123a` | 73 (71) | **0.685 → 0.197** (−48.8pp) | **83.9 → 72.8** |

36 of its 73 legs were profitable **exits** on tokens that settled **against** it: the wallet's edge is
timing its exit, not picking the outcome. It stays `track` (floor is 50), but it drops from
5th-from-bottom of the tracked set to **2nd-from-bottom**, against a cap that keeps only the top 25 and
re-draws hourly (`MAX_TRACKED_WALLETS`). The binding admission constraint here is the **cap at ~72**,
not the floor at 50 — 1,769 `watch` rows already score ≥ 50 and 433 score ≥ 72 — so this wallet's
demotion risk is real, though it does not change status at this clock.

Three smaller movers exceed the card's 5pp comparability guard (`0x167d74fc` +15.0pp on 10 legs,
`0xe36756aa` +9.1pp on 11, `0xeaac36f7` +8.8pp on 100); one lands inside it (`0xede186f3` −4.6pp).
The per-wallet table for all 25, on all three bases, is in `data/wallet-win-basis-audit.json`
(`walletRows[]`: `winRate_exitBasis` / `winRate_shipped` / `winRate_truth`, `global_*`, `status_*`).

**Why that is the intended semantics, not a regression:** we copy a wallet's **entries**. Its exit skill
is not inherited — the exit policy is ours. Scoring consistency on the venue's outcome measures the
thing we actually import. The money it made is still credited: `roi30d` and the PnL terms are untouched,
so this wallet keeps its ROI score and loses only the "it picks winners" claim it never earned.

## 6. Verification

- `npx tsc --noEmit` clean.
- `npx vitest run` — **956/956 pass in 90 files**; `tests/label-win-basis.test.ts` rewritten to pin the
  new basis (a profitable exit on a lost token is a loss; unknown legs leave the denominator; ROI and the
  one-hit-wonder penalty do **not** move when `won` moves; category buckets follow the same predicate).
  The file previously pinned the *opposite* ("the scorer never reads `won`") — that pin is what forced
  this change to be priced as Lane A, so it is inverted deliberately, not deleted.
- `npx tsx scripts/wallet-win-basis-audit.ts` (post-change, track tier) — 0 replication mismatches,
  0 status flips, 0 booked label errors on 1,549 settlement-known legs.

## 7. Not in this change

- The `resolved` **population** — narrowing it (e.g. to naturally-settled rows only) would change what
  the bot admits and needs its own sizing review.
- Other `pnl > 0` win rates elsewhere (`src/lib/rule-updater.ts:131`, `src/lib/gate-winrate-basis.ts:54`,
  `src/lib/benchmarks.ts:61`) — different instruments, different cards.
- **Exit-skill credit**: if you want a wallet's early-exit skill to remain part of its score, that is now
  a *separate* arm (a `realizedPnl`-based term), not the win-rate term. Not proposed here.

## 8. Overridable flags

- **(a) KEEP OR REVERT THE BASIS SWAP** — revert = `git revert <commit>` (restores
  `settledWinRate` call sites to `(t.pnl ?? 0) > 0`, 3 predicates), then `npm run scan:wallets`; the next
  scan rewrites each row. No migration, no stored field changes shape.
- **(b) THE CAP BOUNDARY** — `0x17dd123a` falls to 72.8 and is the most likely next demotion. If that
  wallet is one you want kept, raise `MAX_TRACKED_WALLETS` or pin its status before the next cap run; I
  did **not** touch the cap (that is a sizing decision).
- **(c) PUBLISHING** — `winRate30d` now means "settled win rate". The dashboard label still reads
  "Win Rate (resolved)"; renaming it is a display change I left alone.
