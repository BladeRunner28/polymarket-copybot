# Capital report — daily deposits into Total Capital (2026-09-25)

**Definitions.** *Total Capital (live)* = principal $1900.00 + realized $2180.25 + open mark-to-market $116.01 = **$4196.26** — the Overview's own stat, so it moves with marks and can fall without a trade closing. *Daily deposit* = the capital added on a local calendar day = that day's **booked** PnL (finished trades, booked at `closedAt ?? resolvedAt`) + any **ledger injection**. This report and the chart on `/capital` are the same `src/lib/capital.ts` series.

## Window

- Window: **2026-08-27 → 2026-09-25** (30 local days)
- Opening booked capital: **$1737.80** (`opening` ledger entry $1900.00 dated 2026-07-22)
- Deposits in window: **+$2342.45** = booked +$2342.45 + injected +$0.00
- Closing booked capital: **$4080.25** · peak close $4300.26 on 2026-09-23
- Up days 14 · down days 15 · flat 1 · longest up-run 3 (current 0)
- Open positions excluded from every row: notional $414.77, unrealized +$116.01

## Daily deposits (same numbers as the /capital chart)

| day | deposit | booked | closing |
|---|---|---|---|
| 2026-09-25 | -$181.36 | -$181.36 | $4080.25 |
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
| 2026-09-12 | +$272.80 | +$272.80 | $2001.47 |
| 2026-09-11 | -$136.59 | -$136.59 | $1728.67 |
| 2026-09-10 | -$37.97 | -$37.97 | $1865.26 |
| 2026-09-09 | +$70.37 | +$70.37 | $1903.23 |
| 2026-09-08 | -$107.48 | -$107.48 | $1832.86 |
| 2026-09-07 | +$276.93 | +$276.93 | $1940.34 |
| 2026-09-06 | -$99.65 | -$99.65 | $1663.41 |
| 2026-09-05 | -$27.77 | -$27.77 | $1763.06 |
| 2026-09-04 | -$29.85 | -$29.85 | $1790.83 |
| 2026-09-03 | +$16.34 | +$16.34 | $1820.68 |
| 2026-09-02 | +$5.83 | +$5.83 | $1804.34 |
| 2026-09-01 | +$25.47 | +$25.47 | $1798.51 |
| 2026-08-31 | -$58.85 | -$58.85 | $1773.04 |
| 2026-08-30 | -$116.41 | -$116.41 | $1831.89 |
| 2026-08-29 | +$206.78 | +$206.78 | $1948.30 |
| 2026-08-28 | +$3.72 | +$3.72 | $1741.52 |
| 2026-08-27 | — | — | $1737.80 |
| **total** | **+$2342.45** | **+$2342.45** | **$4080.25** |

## Best / worst days

- Best: 2026-09-18 +$993.70 · 2026-09-16 +$743.38 · 2026-09-22 +$742.72 · 2026-09-21 +$337.02 · 2026-09-07 +$276.93
- Worst: 2026-09-14 -$229.46 · 2026-09-25 -$181.36 · 2026-09-20 -$150.14 · 2026-09-11 -$136.59 · 2026-09-15 -$119.50

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
npx tsx scripts/capital-deposits-report.ts --days=30 --write  # + drafts/capital-deposits-2026-09-25.md
npx vitest run tests/capital.test.ts
```
