# Kalshi LIP: the pay and the capture were disjoint — and the pay left the menu

**Card:** kalshi-lip-universe-gap · **Run:** 2026-11-17 09:00 · **Lane B, read-only**
**Instrument:** scripts/kalshi-lip-family-gap.py · **Artifact:** data/kalshi-lip-family-gap.json

## Key insight

The card asked: "the venues that pay and the families we capture are disjoint (0 of 1,006
programs clear the gate) — find the families that pay $0.0131/contract-hour." The answer is
that the paying families were real, were never in our capture, and **had already stopped
being posted three weeks before the card was written**. On today's menu nothing clears the
gate at all — not at the margin, by 2.9x on the very best program.

The card's premise came from a *retrospective* population: a paged feed of 231,158 programs
spanning 2026-03-12..2026-12-07. Read on the clock that matters (what a maker can join
today) the same feed's above-gate mass is entirely closed.

## The three surfaces, each on its own clock

Level = one program. Unit = centi-cents (KXRT posts $100.00 in both the programs and the
schedules feed, so the scale is cross-checked, not assumed). Gate = $0.0131/contract-hour.

| surface | clock | population | above gate | max ceiling |
|---|---|---|---|---|
| Live menu (active+upcoming, paged to exhaustion) | 2026-11-17T15:06Z | 7,608 usable programs / 448 families | **0** | $0.004458 |
| Series schedules (/incentive_schedules) | 2026-11-17T15:06Z | 630 scorable rows / 405 series | **0** | $0.002976 |
| Historic paged feed | 2026-11-09T17:47Z | 229,636 usable programs / 1,936 families | 84,605 (36.8%) | $120.00 |

Live menu: pool $687,510 at a posted rate of $13,866/day over a 49.6-day span; ceiling p50
$0.000298, p90 $0.000744. The best program on the venue today is 2.9x below the gate; the
median is 44x below.

## Where the historic money sat

Above-gate programs held $3,281,354 = 20.4% of the venue's $16.07M pool. It is a class, not
one row: top-3 families are 26.9% of those dollars, top-10 are 44.5%.

| family | programs | pool | median ceiling | median window | last program ended |
|---|---|---|---|---|---|
| KXTEMPMIAH (Miami hourly temp) | 10,606 | $1,042,680 | $0.0517 | 0.97h | 2026-10-27 |
| KXCRYPTOLEAD15M (15-min crypto) | 24,148 | $482,960 | $0.0400 | 0.25h | 2026-10-28 |
| KXTTELITEMATCH (table tennis) | 15,342 | $330,700 | $0.0222 | 1.50h | 2026-10-03 |

KXTEMPMIAH alone was 6.5% of the *entire* venue LIP pool, at 240 programs/day of $100.

## Reality checks

- **Still open today?** 0 of the 84,605 above-gate programs. Last one ended
  2026-11-06T21:56Z. The "money is elsewhere" reading is a closed era, not a live gap.
- **Does our tape overlap any of it?** 0 of the 148 above-gate families. Only 3 of our 13
  allowlisted families appear in the LIP feed at all (KXCPI 323, KXFED 150, KXHIGHNY 60);
  their best ceiling is $0.001120 — 11.7x below gate. The parent card's $0.000096 measured
  net stands on the population it was measured on.
- **Is capture reachable if pay returns?** Structurally yes: the capture pages the venue
  firehose and filters locally, so a family is one allowlist line, and these families were 1
  market per program. That is a fact about cost, not a reason to buy.
- **Could a unit error manufacture this?** No: the self-test reads the feed as cents and the
  live above-gate count jumps 0 -> 7,583. A wrong scale is visible, not silent.
- **Reconciliation:** per-family $/day sums back to the whole feed at 0.0005%.

## Verdict

**Do not expand the Kalshi tape capture. The LIP reward leg stays CLOSED.** The card's own
gate ("no capture expansion without a yes on all three") is satisfied in the negative:
condition (a) fails on the live clock.

**Re-open condition:** a family must show a LIVE median ceiling >= $0.0131/contract-hour and
be capturable, both read on one fetch at one clock:

    python3 scripts/kalshi-lip-family-gap.py --fetch-live && python3 scripts/kalshi-lip-family-gap.py

The verdict line is the gate. The historic arm may never be quoted as the live menu.

## Instrument defects fixed while building this

1. The last page's next_cursor is the **empty string**, not null, so a pager testing
   'cur is None' reports not-exhausted after reading every row. This file did exactly that
   on its first run.
2. An empty page can arrive **with a cursor still set**; the loop must break on the empty
   page and record why. Both are printed per status now (active 6 pages / 5,310 rows,
   upcoming 3 / 2,300, exhausted=True).
