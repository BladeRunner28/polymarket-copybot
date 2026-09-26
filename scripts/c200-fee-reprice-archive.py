#!/usr/bin/env python3
"""c200-fee-reprice-archive — what the ledger's missing fee costs, re-priced with the
fee models the Polymarket-v1 archive calibrates.

Read-only over prisma/dev.db (immutable=1 so it never fights the crons for a lock) and
prints, per lane, the modelled entry+exit fee under four models on the SAME legs:

  ledger   : no fee at all (what the paper ledger books today)
  docs     : the 2026-09-09 model  fee = shares * rate * p * (1-p)   (per-category rate)
  published: the current published schedule  fee = shares * 0.05 * p * (1-p)
  archive  : the measured 2026-era taker-BUY law from the archive
             fee = shares * (basefee/1e4) * min(p, 1-p),  basefee = 1000 -> 0.10

and the same legs with a MAKER entry (fee 0 on entry; the C-200 sidecar's assumption).
Exit is charged only for status='closed' (a real sell); status='resolved' settles at
0/1 with no trade. Nothing is written; no rule, size or booked figure changes.

Run: python3 scripts/c200-fee-reprice-archive.py
"""
import json
import re
import sqlite3
import sys
from collections import defaultdict

DB = "prisma/dev.db"

# category -> taker fee coefficient, from docs.polymarket.com/trading/fees (as of 2026-09)
CAT_RATE = {"politics": 0.04, "crypto": 0.07, "geopolitics": 0.0}
DEFAULT_RATE = 0.05

KEYWORDS = [
    ("crypto", r"bitcoin|btc|eth|ethereum|solana|sol\b|xrp|crypto|dogecoin|token price"),
    ("geopolitics", r"geopolit|invade|invasion|ceasefire|war\b|missile|troops|nato"),
    ("politics", r"election|president|senate|congress|nominee|governor|parliament|vote|poll|primary|trump|biden|harris|mayor|referendum|shutdown"),
]


def category(market_id: str) -> str:
    s = (market_id or "").lower()
    for name, pat in KEYWORDS:
        if re.search(pat, s):
            return name
    return "other"


def fee_docs(shares, p):
    return shares * CAT_RATE.get(category_of_current, DEFAULT_RATE) * p * (1 - p)


def main():
    global category_of_current
    con = sqlite3.connect(f"file:{DB}?immutable=1", uri=True)
    rows = con.execute(
        "SELECT botId, marketId, entryPrice, simulatedPositionSize, status, realizedPnl "
        "FROM PaperTrade WHERE isDemo=0"
    ).fetchall()

    agg = defaultdict(lambda: defaultdict(float))
    n = defaultdict(int)
    for bot, mk, p, size, status, pnl in rows:
        category_of_current = category(mk)
        if not p or p <= 0:
            continue
        shares = size / p
        entry_docs = shares * CAT_RATE.get(category_of_current, DEFAULT_RATE) * p * (1 - p)
        entry_pub = shares * 0.05 * p * (1 - p)
        entry_arch = shares * 0.10 * min(p, 1 - p)
        # exit leg: only an early exit is a trade
        ex_docs = ex_pub = ex_arch = 0.0
        if status == "closed":
            ex_docs = entry_docs
            ex_pub = entry_pub
            ex_arch = entry_arch
        n[bot] += 1
        A = agg[bot]
        A["notional"] += size
        A["docs_taker"] += entry_docs + ex_docs
        A["pub_taker"] += entry_pub + ex_pub
        A["arch_taker"] += entry_arch + ex_arch
        A["docs_maker_entry"] += ex_docs
        A["pnl"] += pnl or 0.0
        A["entry_below_half"] += 1 if p < 0.5 else 0
        # value of the modelled 2c maker improvement, per share, in $ on the stake
        A["two_cent_pct_of_entry"] += (0.02 / p) if p > 0.02 else 0.0

    print(f"{'lane':<14} {'legs':>6} {'notional':>12} {'ledger fee':>11} "
          f"{'docs taker':>11} {'pub taker':>10} {'archive taker':>14} {'docs maker-entry':>17}")
    for bot in sorted(agg):
        A = agg[bot]
        print(f"{bot:<14} {n[bot]:>6} {A['notional']:>12,.0f} {0:>11,.0f} "
              f"{A['docs_taker']:>11,.0f} {A['pub_taker']:>10,.0f} {A['arch_taker']:>14,.0f} "
              f"{A['docs_maker_entry']:>17,.0f}")
    print()
    for bot in sorted(agg):
        A = agg[bot]
        print(f"== {bot}: booked realized PnL ${A['pnl']:,.2f} on {n[bot]} legs, "
              f"mean entry-below-half {100*A['entry_below_half']/n[bot]:.1f}%, "
              f"mean 2c-as-%-of-entry {100*A['two_cent_pct_of_entry']/n[bot]:.2f}%")
        for k in ("docs_taker", "pub_taker", "arch_taker", "docs_maker_entry"):
            print(f"     net after {k:<17} ${A['pnl'] - A[k]:>12,.2f}   (fee ${A[k]:,.0f} = "
                  f"{100*A[k]/A['notional'] if A['notional'] else 0:.2f}% of notional)")


if __name__ == "__main__":
    category_of_current = "other"
    main()
