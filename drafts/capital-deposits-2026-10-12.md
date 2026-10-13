# Capital report — daily deposits into Total Capital (2026-10-12)

**Definitions.** *Total Capital (live)* = principal $1900.00 + realized $5698.30 + open mark-to-market $3.38 = **$7601.68** — the Overview's own stat, so it moves with marks and can fall without a trade closing. *Daily deposit* = the capital added on a local calendar day = that day's **booked** PnL (finished trades, booked at `closedAt ?? resolvedAt`) + any **ledger injection**. This report and the chart on `/capital` are the same `src/lib/capital.ts` series.

## Window

- Window: **2026-09-13 → 2026-10-12** (30 local days)
- Opening booked capital: **$2001.47** (`opening` ledger entry $1900.00 dated 2026-07-22)
- Deposits in window: **+$5596.83** = booked +$5596.83 + injected +$0.00
- Closing booked capital: **$7598.30** · peak close $7726.06 on 2026-10-09
- Up days 16 · down days 14 · flat 0 · longest up-run 4 (current 0)
- Open positions excluded from every row: notional $40.44, unrealized +$3.38

## Daily deposits (same numbers as the /capital chart)

| day | deposit | booked | closing |
|---|---|---|---|
| 2026-10-12 | -$66.52 | -$66.52 | $7598.30 |
| 2026-10-11 | -$42.75 | -$42.75 | $7664.82 |
| 2026-10-10 | -$18.49 | -$18.49 | $7707.57 |
| 2026-10-09 | +$269.89 | +$269.89 | $7726.06 |
| 2026-10-08 | +$98.95 | +$98.95 | $7456.17 |
| 2026-10-07 | -$62.65 | -$62.65 | $7357.22 |
| 2026-10-06 | +$604.87 | +$604.87 | $7419.87 |
| 2026-10-05 | +$594.55 | +$594.55 | $6815.00 |
| 2026-10-04 | -$33.42 | -$33.42 | $6220.45 |
| 2026-10-03 | +$236.59 | +$236.59 | $6253.87 |
| 2026-10-02 | +$68.47 | +$68.47 | $6017.28 |
| 2026-10-01 | +$132.11 | +$132.11 | $5948.81 |
| 2026-09-30 | +$59.93 | +$59.93 | $5816.70 |
| 2026-09-29 | -$72.71 | -$72.71 | $5756.77 |
| 2026-09-28 | +$1776.36 | +$1776.36 | $5829.48 |
| 2026-09-27 | +$22.45 | +$22.45 | $4053.12 |
| 2026-09-26 | -$45.40 | -$45.40 | $4030.67 |
| 2026-09-25 | -$185.54 | -$185.54 | $4076.07 |
| 2026-09-24 | -$38.65 | -$38.65 | $4261.61 |
| 2026-09-23 | +$15.53 | +$15.53 | $4300.26 |
| 2026-09-22 | +$742.72 | +$742.72 | $4284.73 |
| 2026-09-21 | +$337.02 | +$337.02 | $3542.01 |
| 2026-09-20 | -$150.14 | -$150.14 | $3204.99 |
| 2026-09-19 | -$18.04 | -$18.04 | $3355.13 |
| 2026-09-18 | +$993.70 | +$993.70 | $3373.17 |
| 2026-09-17 | +$12.36 | +$12.36 | $2379.47 |
| 2026-09-16 | +$743.38 | +$743.38 | $2367.11 |
| 2026-09-15 | -$119.50 | -$119.50 | $1623.73 |
| 2026-09-14 | -$229.46 | -$229.46 | $1743.23 |
| 2026-09-13 | -$28.78 | -$28.78 | $1972.69 |
| **total** | **+$5596.83** | **+$5596.83** | **$7598.30** |

## Best / worst days

- Best: 2026-09-28 +$1776.36 · 2026-09-18 +$993.70 · 2026-09-16 +$743.38 · 2026-09-22 +$742.72 · 2026-10-06 +$604.87
- Worst: 2026-09-14 -$229.46 · 2026-09-25 -$185.54 · 2026-09-20 -$150.14 · 2026-09-15 -$119.50 · 2026-09-29 -$72.71

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
npx tsx scripts/capital-deposits-report.ts --days=30 --write  # + drafts/capital-deposits-2026-10-12.md
npx vitest run tests/capital.test.ts
```
