# Capital report — daily deposits into Total Capital (2026-11-07)

**Definitions.** *Total Capital (live)* = principal $1900.00 + realized $8635.38 + open mark-to-market $142.24 = **$10677.62** — the Overview's own stat, so it moves with marks and can fall without a trade closing. *Daily deposit* = the capital added on a local calendar day = that day's **booked** PnL (finished trades, booked at `closedAt ?? resolvedAt`) + any **ledger injection**. This report and the chart on `/capital` are the same `src/lib/capital.ts` series.

## Window

- Window: **2026-10-09 → 2026-11-07** (30 local days)
- Opening booked capital: **$7456.17** (`opening` ledger entry $1900.00 dated 2026-07-22)
- Deposits in window: **+$3079.21** = booked +$3079.21 + injected +$0.00
- Closing booked capital: **$10535.38** · peak close $10535.38 on 2026-11-07
- Up days 14 · down days 15 · flat 1 · longest up-run 4 (current 1)
- Open positions excluded from every row: notional $522.62, unrealized +$142.24

## Daily deposits (same numbers as the /capital chart)

| day | deposit | booked | closing |
|---|---|---|---|
| 2026-11-07 | +$466.24 | +$466.24 | $10535.38 |
| 2026-11-06 | -$81.25 | -$81.25 | $10069.14 |
| 2026-11-05 | +$126.91 | +$126.91 | $10150.39 |
| 2026-11-04 | +$326.33 | +$326.33 | $10023.48 |
| 2026-11-03 | +$1354.67 | +$1354.67 | $9697.15 |
| 2026-11-02 | +$38.19 | +$38.19 | $8342.48 |
| 2026-11-01 | -$121.32 | -$121.32 | $8304.29 |
| 2026-10-31 | +$21.07 | +$21.07 | $8425.61 |
| 2026-10-30 | +$67.71 | +$67.71 | $8404.54 |
| 2026-10-29 | +$968.67 | +$968.67 | $8336.83 |
| 2026-10-28 | -$66.89 | -$66.89 | $7368.16 |
| 2026-10-27 | -$67.78 | -$67.78 | $7435.05 |
| 2026-10-26 | -$249.83 | -$249.83 | $7502.83 |
| 2026-10-25 | -$75.49 | -$75.49 | $7752.66 |
| 2026-10-24 | -$110.00 | -$110.00 | $7828.15 |
| 2026-10-23 | +$16.42 | +$16.42 | $7938.15 |
| 2026-10-22 | +$101.24 | +$101.24 | $7921.73 |
| 2026-10-21 | -$22.03 | -$22.03 | $7820.49 |
| 2026-10-20 | -$127.65 | -$127.65 | $7842.52 |
| 2026-10-19 | — | — | $7970.17 |
| 2026-10-18 | +$485.48 | +$485.48 | $7970.17 |
| 2026-10-17 | -$119.51 | -$119.51 | $7484.69 |
| 2026-10-16 | -$11.96 | -$11.96 | $7604.20 |
| 2026-10-15 | -$65.15 | -$65.15 | $7616.16 |
| 2026-10-14 | +$83.62 | +$83.62 | $7681.31 |
| 2026-10-13 | +$19.33 | +$19.33 | $7597.69 |
| 2026-10-12 | -$86.46 | -$86.46 | $7578.36 |
| 2026-10-11 | -$42.75 | -$42.75 | $7664.82 |
| 2026-10-10 | -$18.49 | -$18.49 | $7707.57 |
| 2026-10-09 | +$269.89 | +$269.89 | $7726.06 |
| **total** | **+$3079.21** | **+$3079.21** | **$10535.38** |

## Best / worst days

- Best: 2026-11-03 +$1354.67 · 2026-10-29 +$968.67 · 2026-10-18 +$485.48 · 2026-11-07 +$466.24 · 2026-11-04 +$326.33
- Worst: 2026-10-26 -$249.83 · 2026-10-20 -$127.65 · 2026-11-01 -$121.32 · 2026-10-17 -$119.51 · 2026-10-24 -$110.00

## Capital ledger (injections)

- `opening` 2026-07-22 **$1900.00** — Standing principal as of the ledger opening (bot's first C-200 trade 2026-07-22). Date is the bot's start, not a documented funding date — the real funding dates predate any recording and are unrecoverable.

- Ledger reconciliation: principal $1900.00 − (seed $1900.00 + net flows $0.00) = **$0.00** ✓

## Caveats

- **Pre-ledger funding is unrecoverable.** `BotBankroll.principal` has no history (`prisma/dev.db` is gitignored, nothing logs a principal change). The ledger seeds the standing principal once as an `opening` entry dated to the bot's first trade — that date is the bot's start, NOT a documented funding date. Real injections are recorded from 2026-09-20 forward; an unlogged principal move surfaces as the ledger gap above.
- **Booked, not marked.** The rows use booked PnL only (paper trades pay out at 1/0 on resolution; early exits book at `closedAt`). The live Total Capital figure includes open mark-to-market, so it will differ from the closing column — by design, and both are labelled on `/capital`.
- **Local-day boundary.** Days are local (America/Chicago) calendar days, the same boundary the Overview's startOfDay and the EOD report use. A finished trade is immutable once booked, so past rows never change.
- Fees/slippage are not modelled in the paper ledger (see the paper-ledger fee-fidelity card), so a deposit is gross of execution costs.

## Reproduce

```bash
npx tsx scripts/capital-deposits-report.ts --days=30          # print, writes nothing
npx tsx scripts/capital-deposits-report.ts --days=30 --write  # + drafts/capital-deposits-2026-11-07.md
npx vitest run tests/capital.test.ts
```
