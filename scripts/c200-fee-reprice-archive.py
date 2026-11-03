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

EXIT BASIS — REPAIRED 2026-11-02 (card `fee-exit-basis-instruments`). Until this pass the
exit leg was charged at the leg's ENTRY price (`ex_docs = entry_docs`), i.e. the fee was
doubled. An exit is a trade at the EXIT price, and the fee law p*(1-p) goes to zero at the
payoff extremes, so the old basis inflated the exit leg by ~4x on exactly the legs that
matter: 83.4% of closed legs leave below 0.05 or above 0.80. Both bases print side by
side — the withdrawn one for the record, the corrected one as the headline.

Run: python3 scripts/c200-fee-reprice-archive.py
"""
import argparse
import datetime
import os
import re
import sqlite3
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib.fee_exit import ExitBasisTally, leg_fees, resolve_exit_price  # noqa: E402

DB = "prisma/dev.db"

# category -> taker fee coefficient, from docs.polymarket.com/trading/fees (as of 2026-09)
CAT_RATE = {"politics": 0.04, "crypto": 0.07, "geopolitics": 0.0}
DEFAULT_RATE = 0.05

KEYWORDS = [
    ("crypto", r"bitcoin|btc|eth|ethereum|solana|sol\b|xrp|crypto|dogecoin|token price"),
    ("geopolitics", r"geopolit|invade|invasion|ceasefire|war\b|missile|troops|nato"),
    ("politics", r"election|president|senate|congress|nominee|governor|parliament|vote|poll|primary|trump|biden|harris|mayor|referendum|shutdown"),
]


def category(market_id):
    s = (market_id or "").lower()
    for name, pat in KEYWORDS:
        if re.search(pat, s):
            return name
    return "other"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=DB)
    args = ap.parse_args()
    con = sqlite3.connect("file:%s?immutable=1" % args.db, uri=True)
    rows = con.execute(
        "SELECT botId, marketId, entryPrice, simulatedPositionSize, status, realizedPnl, "
        "currentPrice, closedAt "
        "FROM PaperTrade WHERE isDemo=0"
    ).fetchall()
    con.close()

    closed_at = [r[7] for r in rows if r[7] is not None]
    clock = ("closed-leg clock: closedAt up to %s"
             % datetime.datetime.utcfromtimestamp(max(closed_at) / 1000).strftime("%Y-%m-%dT%H:%M:%SZ")
             if closed_at else "closed-leg clock: no closedAt on any row")
    tally = ExitBasisTally(population="closed legs (status='closed', isDemo=0)",
                           clock=clock, level="leg")

    agg = defaultdict(lambda: defaultdict(float))
    n = defaultdict(int)
    for bot, mk, p, size, status, pnl, cur_px, _closed in rows:
        if not p or p <= 0:
            continue
        rate = CAT_RATE.get(category(mk), DEFAULT_RATE)
        shares = size / p
        early = status == "closed"
        exit_px = None
        if early:
            resolved = resolve_exit_price(cur_px, p, size, pnl)
            tally.add(resolved)
            exit_px = resolved["price"]

        e_docs, x_docs = leg_fees(shares, rate, p, exit_px, early)
        e_pub, x_pub = leg_fees(shares, 0.05, p, exit_px, early)
        e_arch, x_arch = leg_fees(shares, 0.10, p, exit_px, early, law="min")
        # the withdrawn basis, for the record: the exit leg charged at the ENTRY price
        _, x_docs_old = leg_fees(shares, rate, p, p, early)
        _, x_pub_old = leg_fees(shares, 0.05, p, p, early)
        _, x_arch_old = leg_fees(shares, 0.10, p, p, early, law="min")

        n[bot] += 1
        A = agg[bot]
        A["notional"] += size
        A["docs_taker"] += e_docs + x_docs
        A["pub_taker"] += e_pub + x_pub
        A["arch_taker"] += e_arch + x_arch
        A["docs_maker_entry"] += x_docs
        A["docs_taker_old"] += e_docs + x_docs_old
        A["pub_taker_old"] += e_pub + x_pub_old
        A["arch_taker_old"] += e_arch + x_arch_old
        A["docs_maker_entry_old"] += x_docs_old
        A["pnl"] += pnl or 0.0


    print("{:<14} {:>6} {:>12} {:>11} {:>14} {:>13} {:>15} {:>13}".format(
        "lane", "legs", "notional", "ledger fee", "docs t+e@exit",
        "pub t+e@exit", "archive t+e@exit", "docs maker-entry"))
    for bot in sorted(agg):
        A = agg[bot]
        print("{:<14} {:>6d} {:>12,.2f} {:>11,.2f} {:>14,.2f} {:>13,.2f} {:>15,.2f} {:>13,.2f}".format(
            bot, n[bot], A["notional"], 0.0, A["docs_taker"], A["pub_taker"],
            A["arch_taker"], A["docs_maker_entry"]))
    print()
    for bot in sorted(agg):
        A = agg[bot]
        notional = A["notional"] or 0.0
        print("== {}: booked realized PnL ${:,.2f} on {} legs, notional ${:,.2f}".format(
            bot, A["pnl"], n[bot], notional))
        for k in ("docs_taker", "pub_taker", "arch_taker", "docs_maker_entry"):
            pct = 100 * A[k] / notional if notional else 0.0
            print("     net after {:<22} ${:>12,.2f}   (fee ${:,.2f} = {:.2f}% of notional)".format(
                k, A["pnl"] - A[k], A[k], pct))
        old, new = A["docs_taker_old"], A["docs_taker"]
        print("     exit leg: ${:,.2f} on the WITHDRAWN basis (exit charged at entry) vs "
              "${:,.2f} at the leg's own exit ({:+.1f}%)".format(
                  old, new, 100 * (new - old) / old if old else 0.0))

    print()
    print(tally.line())
    tot = defaultdict(float)
    for A in agg.values():
        for k, v in A.items():
            tot[k] += v
    notional = tot["notional"] or 0.0
    print()
    print("=== BOOK TOTAL, same legs, exit priced at the leg's own exit ===")
    print("  docs      ${:,.2f}  ({:.2f}% of ${:,.2f} notional)".format(
        tot["docs_taker"], 100 * tot["docs_taker"] / notional if notional else 0.0, notional))
    print("  published ${:,.2f} | archive ${:,.2f} | docs maker-entry ${:,.2f}".format(
        tot["pub_taker"], tot["arch_taker"], tot["docs_maker_entry"]))
    print("=== BOOK TOTAL on the WITHDRAWN basis (exit charged at the entry price) ===")
    for k in ("docs_taker_old", "pub_taker_old", "arch_taker_old"):
        old = tot[k]
        new = tot[k.replace("_old", "")]
        print("  {:<16} ${:,.2f} -> ${:,.2f}  ({:+.1f}%)".format(
            k, old, new, 100 * (new - old) / old if old else 0.0))
    print("  The delta is the BASIS ERROR, not a fee decision: the law p*(1-p) is identical")
    print("  in every line above. Charging an exit at its entry price was never a reading.")


if __name__ == "__main__":
    main()
