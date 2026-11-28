# Capital report — daily deposits into Total Capital (2026-11-27)

**Definitions.** *Total Capital (live)* = principal $1900.00 + realized $5298.59 + open mark-to-market -$65.44 = **$7133.15** — the Overview's own stat, so it moves with marks and can fall without a trade closing. *Daily deposit* = the capital added on a local calendar day = that day's **booked** PnL (finished trades, booked at `closedAt ?? resolvedAt`) + any **ledger injection**. This report and the chart on `/capital` are the same `src/lib/capital.ts` series.

## Window

- Window: **2026-10-29 → 2026-11-27** (30 local days)
- Opening booked capital: **$7437.74** (`opening` ledger entry $1900.00 dated 2026-07-22)
- Deposits in window: **-$239.15** = booked -$239.15 + injected +$0.00
- Closing booked capital: **$7198.59** · peak close $7618.47 on 2026-11-03
- Up days 9 · down days 21 · flat 0 · longest up-run 2 (current 0)
- Open positions excluded from every row: notional $687.21, unrealized -$65.44

## Daily deposits (same numbers as the /capital chart)

| day | deposit | booked | closing |
|---|---|---|---|
| 2026-11-27 | -$2.09 | -$2.09 | $7198.59 |
| 2026-11-26 | +$104.28 | +$104.28 | $7200.68 |
| 2026-11-25 | -$49.80 | -$49.80 | $7096.40 |
| 2026-11-24 | -$59.69 | -$59.69 | $7146.20 |
| 2026-11-23 | -$40.00 | -$40.00 | $7205.89 |
| 2026-11-22 | +$156.04 | +$156.04 | $7245.89 |
| 2026-11-21 | -$87.79 | -$87.79 | $7089.85 |
| 2026-11-20 | +$173.70 | +$173.70 | $7177.64 |
| 2026-11-19 | -$20.00 | -$20.00 | $7003.94 |
| 2026-11-18 | -$123.92 | -$123.92 | $7023.94 |
| 2026-11-17 | -$217.86 | -$217.86 | $7147.86 |
| 2026-11-16 | -$176.19 | -$176.19 | $7365.72 |
| 2026-11-15 | -$17.99 | -$17.99 | $7541.91 |
| 2026-11-14 | -$11.05 | -$11.05 | $7559.90 |
| 2026-11-13 | -$2.71 | -$2.71 | $7570.95 |
| 2026-11-12 | +$150.66 | +$150.66 | $7573.66 |
| 2026-11-11 | +$513.43 | +$513.43 | $7423.00 |
| 2026-11-10 | -$190.22 | -$190.22 | $6909.57 |
| 2026-11-09 | -$47.95 | -$47.95 | $7099.79 |
| 2026-11-08 | -$121.11 | -$121.11 | $7147.74 |
| 2026-11-07 | -$95.09 | -$95.09 | $7268.85 |
| 2026-11-06 | -$112.94 | -$112.94 | $7363.94 |
| 2026-11-05 | +$114.19 | +$114.19 | $7476.88 |
| 2026-11-04 | -$255.78 | -$255.78 | $7362.69 |
| 2026-11-03 | +$315.21 | +$315.21 | $7618.47 |
| 2026-11-02 | -$24.40 | -$24.40 | $7303.26 |
| 2026-11-01 | -$121.32 | -$121.32 | $7327.66 |
| 2026-10-31 | +$21.07 | +$21.07 | $7448.98 |
| 2026-10-30 | +$25.99 | +$25.99 | $7427.91 |
| 2026-10-29 | -$35.82 | -$35.82 | $7401.92 |
| **total** | **-$239.15** | **-$239.15** | **$7198.59** |

## Best / worst days

- Best: 2026-11-11 +$513.43 · 2026-11-03 +$315.21 · 2026-11-20 +$173.70 · 2026-11-22 +$156.04 · 2026-11-12 +$150.66
- Worst: 2026-11-04 -$255.78 · 2026-11-17 -$217.86 · 2026-11-10 -$190.22 · 2026-11-16 -$176.19 · 2026-11-18 -$123.92

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
npx tsx scripts/capital-deposits-report.ts --days=30 --write  # + drafts/capital-deposits-2026-11-27.md
npx vitest run tests/capital.test.ts
```
