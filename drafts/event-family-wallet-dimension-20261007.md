# The EOD event-family read gets a WALLET dimension (tuning #48 rec 1, applied 2026-10-07)

**Status: APPLIED 2026-10-07, measurement-only — no cap, size, threshold, schedule or rule was
touched.** Approved in-thread on review #48's rec 1. Card:
`tr48-rec1-event-family-wallet-split` (In Progress, 7-day verify gate).

---

## 1. The problem the rec named

The shipped event-family line (`scripts/event-family-concentration.ts`, #36 R1 / #38 rec 2) prices
correlated exposure **across markets** — eight weather cities are eight markets but one regime, and
the line is the only read that sees that, because v55 (per-market) and v59 (per-wallet) both report 0
on correlated cross-market exposure. That was the shape behind the −$300 realisation #37 documented
(three adjacent elon tweet-count bands, one wallet).

What the line **cannot** see is whether the family is *also* one counterparty's book. Review #48's
finding is exactly that shape, and it is now the dominant feature of the C-200 book:

| read (review #48, 10-07 07:00) | value |
|---|---|
| EOD top-3 open cost | **95.2%** (was 73.2%) |
| `highest-temperature-in` | 8 legs / $209.92 = 62.5% |
| live book, same morning | 12 legs / $279.90 = **64.6%** of 26 legs / $433.55, ONE wallet `0x7c63520c…` |
| caps | **no breach** — wallet $280 vs $864 ceiling; book 12.5% of the exposure cap; realized DD 0.2% |

So this is a **measurement gap, not a breach**: nothing we ship could distinguish "eight cities" from
"one wallet's weather book" at a glance.

## 2. What shipped

- **`src/lib/event-family.ts`** (new, pure — no logger, no DB):
  - `eventFamily()` moved out of the script **unchanged** (the pre-registered rule: cut at the ISO
    date when the slug carries one, else the first 3 dash tokens);
  - `walletSplit()` / `describeSplit()` / `shortWallet()` — the wallet dimension, ordered **cost DESC
    then wallet ASC** so a re-run at a fixed instant cannot flip ties;
  - `NO_WALLET` sentinel: a leg with no stored address is its own bucket, never folded into a real
    wallet.
- **`scripts/event-family-concentration.ts`**: two added lines (top family's wallet split; whole-book
  wallet concentration) and it now imports the helpers. The original line is byte-unchanged,
  including the `by event family` substring the logs are grepped for.
- **`tests/event-family.test.ts`** (10 tests): the family rule (including the live non-ISO case
  `highest-temperature-in-denver-on-october-8-2026-86-87f`, which must NOT be read as a date cut),
  order-determinism under shuffled input, the no-wallet sentinel, null-cost handling.
- **`~/.hermes/scripts/copybot-eod.sh`**: this script's budget `tail -6` → `tail -8` (six lines now);
  written via temp+rename so a run in flight keeps its inode; `bash -n` clean.
- **Reviewer standing input** appended to the `copybot-tuning-review-daily` prompt so #49 does not
  re-propose the dimension, with the Kelly-window instruction that nothing may be sized or capped off
  this line.

## 3. First read (2026-10-07 07:1x)

```
top family wallet split (highest-temperature-in, 12 legs +$279.90): 0x7c63520c… 12 legs +$279.90
  (100.0%) — wallets in family: 1 (SINGLE-WALLET family)
open-book wallet concentration: 0x7c63520c… 12 legs +$279.90 (64.6%) | 0xcfad110b… 1 legs +$100.00
  (23.1%) | 0x885ffdf3… 8 legs +$46.18 (10.7%) — top-3 wallets = +$426.08 = 98.3% of open cost |
  wallets in book: 6 | largest single wallet 0x7c63520c… 12 legs
```

It reproduces the reviewer's hand-derived numbers (12 legs / $279.90 / 64.6% / one wallet) — the
line's purpose is to stop that being hand-derived each cycle.

## 4. Verification evidence

- Two consecutive runs, byte-identical (`cmp -s`) — at a fixed instant, which is the satisfiable
  form: the read covers the OPEN book, so a re-run after legs resolve legitimately differs.
- Hand-run in the wrapper's own environment (`unset DATABASE_URL; set -a; source .env; set +a`):
  6 lines survive `tail -8`.
- `grep -c "by event family" logs/cron/copybot-eod.log` = **9** at baseline (pre-change), and the
  added lines carry no new grep target, so the existing clause is unaffected.
- `npx vitest run tests/event-family.test.ts` → **10/10**; full suite and `tsc --noEmit` clean.
- Nothing in the read path gates a decision: `grep` shows no RuleSet/paper/scorer import of
  `src/lib/event-family.ts`.

## 5. Boundaries (what this is NOT)

- It **prices** a shape; it gates nothing. No cap, size, threshold or schedule change is proposed off
  it, and doing so **inside the Kelly window** would be an override-class change that pollutes the
  Oct 8 attribution and creates another `ruleSetVersion` sub-window.
- The exposure axis **resets** after this rec: the dimension shipped, so a future review carrying the
  same ask is a duplicate.
- Re-read at the 7-day gate (review #55): both lines print, byte-identical at a fixed instant,
  `grep` ≥ 1, 0 FAILED.

## 6. Reproduce

```bash
npx tsx scripts/event-family-concentration.ts          # the six-line read
npx vitest run tests/event-family.test.ts              # 10 tests
grep -c "by event family" logs/cron/copybot-eod.log    # wrapper still emitting
```
