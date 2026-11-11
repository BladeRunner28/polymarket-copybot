#!/usr/bin/env python3
"""
temp-ladder-hull-read — does the published combinatorial-arb magnitude (2.2% of
committed capital, arXiv:2610.23517v1, Seo et al. 2026-10-19) exist at OUR scale,
on the relation sets our own book already sits inside?

WHY THIS EXISTS (roadmap card c200-exclusive-pair-hull-check, Lane B, read-only)
    The paper earns 2.2% net of spreads and fees on 255,000+ contracts replayed at
    FULL DEPTH. We replay nothing at full depth and hold at most a few legs per
    event, so reproducing the number is not the question. The question the card
    actually asks is: on the families our tape already covers, does an executable
    combination price outside the convex hull of admissible payoffs — i.e. is a
    mispricing sitting on top of positions we already hold?

WHAT A "RELATION SET" IS HERE (definition, not a guess)
    A temperature ladder: every market in one city+date whose slug ends in a
    bucket token (`32c`, `35c`, `30corbelow`, `99corhigher`). Exactly one bucket
    can win, so the set is MUTUALLY EXCLUSIVE BY CONSTRUCTION — and that alone is
    enough for the NO-side test below, which needs no assumption that the set is
    EXHAUSTIVE (a missing bucket simply makes every NO pay, which is the best
    case, not the worst).

    NO side (risk-free from exclusivity alone): buy 1 NO on every bucket.
      cost = K - SUM(bid_yes)      payout >= K-1  (at most one bucket wins)
      edge = SUM(bid) - 1 - fees
    YES side (needs EXHAUSTIVENESS, which our tape cannot prove):
      cost = SUM(ask_yes)          payout = 1 if the winner is in our set, else 0
      edge = 1 - SUM(ask) - fees
    The YES arm is therefore printed but NOT claimed: our observed member set is
    whatever the sampler walked, so an incomplete set makes SUM(ask) small and
    `1 - SUM(ask)` large with no arbitrage behind it. The first version of this
    probe fell into exactly that trap (it read +0.97 "edge" on 3-of-20
    exact-score sets) — the share of windows with SUM(ask) < 0.5 is printed every
    run as the honesty check on that arm.

BOOK ARM (the part the card is really about)
    For every ladder where the book holds >= 2 distinct buckets, the held legs are
    replayed as a STATIC hold-to-settlement vector: payoff is computed for every
    possible winner (each held bucket, plus "<unheld bucket>"). min/max over those
    cases says whether the family locks a profit or a loss as a position set. It is
    a hold-to-settlement read — legs closed early break the lock, and that is
    stated in the output, not hidden.

BASIS (stated, never implied)
    population  non-demo MarketSnapshot rows (isDemo=0) with a yesPrice, and
                non-demo PaperTrade legs (isDemo=0, all statuses)
    level       one ladder-group x one time window (venue arm); one ladder family
                (book arm)
    clock       snapshot collectedAt, UTC, bucketed into --window-min windows; a
                window is used only when EVERY observed member of the set is
                quoted with both bid and ask inside it
    price       venue best bid / best ask as recorded on our own tape (top of book
                ONLY — depth is not in the tape, so every edge here is an UPPER
                bound on what is fillable)
    fees        takerFeePerShare(price, rate) = rate * price * (1 - price), rate
                0.05 (PRICE_EDGE_SPEC_V1.defaultFeeRate; temperature markets are
                not in the crypto/politics keyword map)

READ-ONLY: opens the DB, reads MarketSnapshot + PaperTrade, writes
data/temp-ladder-hull-read.json and prints. No database write, no live-path input.

Run:
    python3 scripts/temp-ladder-hull-read.py
    python3 scripts/temp-ladder-hull-read.py --window-min 2      # staleness check
    python3 scripts/temp-ladder-hull-read.py --self-test         # proves it can go RED
"""
import argparse
import json
import os
import re
import sqlite3
import statistics as st
import sys
from collections import defaultdict

DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "prisma", "dev.db")
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "temp-ladder-hull-read.json")
FEE_RATE = 0.05
BUCKET = re.compile(r"^\d+c(orhigher|orbelow)?$")


def ladder_key(slug):
    """City+date ladder prefix, or None when the slug carries no bucket tail."""
    toks = (slug or "").split("-")
    if len(toks) >= 3 and toks[-1] and BUCKET.match(toks[-1]):
        return "-".join(toks[:-1])
    return None


def fee_per_share(price, rate=FEE_RATE):
    """Polymarket taker fee law: rate * p * (1 - p), per share."""
    return rate * price * (1.0 - price)


def window_vector(quotes, k_expected):
    """quotes: {marketId: (bid, ask)}. Returns the vector stats or None if partial."""
    if len(quotes) < k_expected or k_expected < 3:
        return None
    vals = list(quotes.values())
    if any(b is None or a is None for b, a in vals):
        return None
    sb = sum(b for b, _ in vals)
    sa = sum(a for _, a in vals)
    k = len(vals)
    no_fee = sum(fee_per_share(1.0 - b) for b, _ in vals)
    yes_fee = sum(fee_per_share(a) for _, a in vals)
    no_cap = k - sb          # capital committed buying every NO at 1-bid
    yes_cap = sa             # capital committed buying every YES at ask
    return {
        "k": k,
        "sum_bid": sb,
        "sum_ask": sa,
        "no_gross": sb - 1.0,
        "no_net": sb - 1.0 - no_fee,
        "no_cap": no_cap,
        "no_pct": (sb - 1.0 - no_fee) / no_cap if no_cap > 0 else None,
        "yes_gross": 1.0 - sa,
        "yes_net": 1.0 - sa - yes_fee,
        "yes_cap": yes_cap,
        "yes_pct": (1.0 - sa - yes_fee) / yes_cap if yes_cap > 0 else None,
    }


def payoff_cases(legs):
    """Static hold-to-settlement payoff of one family's held legs, per possible winner.

    legs: [{marketId, outcome ('YES'|'NO'), entryPrice, cost}]
    Returns {case -> payout} with one case per held bucket plus '<unheld bucket>'.
    """
    held = {l["marketId"] for l in legs}
    shares = [(l["marketId"], (l["outcome"] or "").upper(), (l["cost"] or 0.0) / l["entryPrice"])
              for l in legs if l["entryPrice"] and l["entryPrice"] > 0]
    cases = {}
    for w in sorted(held) + ["<unheld bucket>"]:
        cases[w] = sum(s for m, o, s in shares if (o == "YES") == (m == w))
    return cases


def summarize_book(by_family):
    out = []
    for fam, legs in by_family.items():
        if len({l["marketId"] for l in legs}) < 2:
            continue
        cost = sum(l["cost"] or 0.0 for l in legs)
        cases = payoff_cases(legs)
        out.append({
            "family": fam,
            "buckets_held": len({l["marketId"] for l in legs}),
            "legs": len(legs),
            "cost": cost,
            "min_payoff": min(cases.values()),
            "max_payoff": max(cases.values()),
            "worst_case_pnl": min(cases.values()) - cost,
            "best_case_pnl": max(cases.values()) - cost,
            "locked_profit": min(cases.values()) > cost + 1e-9,
            "locked_loss": max(cases.values()) < cost - 1e-9,
        })
    return out


def distribution(vals):
    s = sorted(vals)
    n = len(s)
    return {
        "n": n,
        "median": st.median(s) if n else None,
        "p10": s[int(n * 0.10)] if n else None,
        "p90": s[int(n * 0.90)] if n else None,
        "max": s[-1] if n else None,
        "share_pos": (sum(1 for x in s if x > 0) / n) if n else None,
    }


def collect(conn, window_ms):
    cur = conn.cursor()
    groups = defaultdict(lambda: defaultdict(dict))
    n_rows = 0
    for market_id, collected, bid, ask in cur.execute(
        "SELECT marketId, collectedAt, bestBid, bestAsk FROM MarketSnapshot "
        "WHERE isDemo = 0 AND yesPrice IS NOT NULL"
    ):
        key = ladder_key(market_id)
        if not key or "temperature" not in key:
            continue
        groups[key][(collected // window_ms) * window_ms][market_id] = (bid, ask)
        n_rows += 1
    windows = []
    for key, wins in groups.items():
        members = {m for d in wins.values() for m in d}
        k = len(members)
        if k < 3:
            continue
        tailed = any(re.search(r"or(higher|below)$", m) for m in members)
        for w, quotes in wins.items():
            v = window_vector(quotes, k)
            if v:
                v.update({"family": key, "window": w, "tailed": tailed})
                windows.append(v)
    return n_rows, groups, windows


def book_legs(conn):
    by_family = defaultdict(list)
    for market_id, outcome, entry, size in conn.execute(
        "SELECT marketId, outcome, entryPrice, simulatedPositionSize FROM PaperTrade WHERE isDemo = 0"
    ):
        key = ladder_key(market_id)
        if not key or "temperature" not in key:
            continue
        by_family[key].append({"marketId": market_id, "outcome": outcome,
                               "entryPrice": entry, "cost": size or 0.0})
    return by_family


def report(conn, window_min):
    window_ms = window_min * 60 * 1000
    n_rows, groups, windows = collect(conn, window_ms)
    if not windows:
        print("no fully-quoted ladder windows — nothing measurable")
        return None
    no_net = distribution([w["no_net"] for w in windows])
    no_gross = distribution([w["no_gross"] for w in windows])
    yes_gross = distribution([w["yes_gross"] for w in windows])
    pct = distribution([w["no_pct"] for w in windows if w["no_pct"] is not None])
    pos = [w for w in windows if w["no_net"] > 0]
    pos_sorted = sorted((w["no_net"] for w in pos), reverse=True)
    by_group = defaultdict(float)
    for w in pos:
        by_group[w["family"]] += w["no_net"]
    top10 = sum(sorted(by_group.values(), reverse=True)[:10])
    tailed_windows = [w for w in windows if w["tailed"]]

    print(f"=== VENUE ARM — temperature ladders from our own tape ({window_min}-min windows) ===")
    print(f"basis: population = non-demo MarketSnapshot rows with a yesPrice and a temperature "
          f"bucket tail ({n_rows} rows); level = ladder x window; clock = collectedAt UTC; "
          f"price = top of book only (depth NOT in tape, so every edge below is an upper bound); "
          f"fees = {FEE_RATE:.2f} taker on every leg")
    print(f"ladder groups with >=3 observed buckets: {len({w['family'] for w in windows})}; "
          f"fully-quoted windows: {len(windows)}")
    print(f"NO side (risk-free from mutual exclusivity ALONE): gross median {no_gross['median']:+.4f}, "
          f"NET-of-fee median {no_net['median']:+.4f} per unit set; net > 0 in "
          f"{len(pos)}/{len(windows)} windows ({100 * no_net['share_pos']:.2f}%)")
    print(f"  net edge as % of committed capital (K - sum bid): median {100 * pct['median']:+.2f}%, "
          f"p90 {100 * pct['p90']:+.2f}%, max {100 * pct['max']:+.2f}%")
    if pos:
        print(f"  positive-window mass: sum ${sum(pos_sorted):.4f} per unit set; ex-top-1 "
              f"${sum(pos_sorted[1:]):.4f}; ex-top-5 ${sum(pos_sorted[5:]):.4f}; "
              f"top-10 groups = {100 * top10 / sum(pos_sorted):.1f}% of it")
    print(f"YES side (needs EXHAUSTIVENESS, which our member set cannot prove): gross median "
          f"{yes_gross['median']:+.4f}, >0 in {100 * yes_gross['share_pos']:.2f}% of windows — "
          f"NOT CLAIMED. Honesty check: {100 * sum(1 for w in windows if w['sum_ask'] < 0.5) / len(windows):.1f}% "
          f"of windows have sum-ask < 0.5, i.e. an incomplete member set, and on those `1 - sum-ask` "
          f"is an artifact of the coverage, not an arbitrage")
    if tailed_windows:
        t = distribution([w["yes_gross"] for w in tailed_windows])
        print(f"  tailed-set subset (both orhigher/orbelow tails present): {len(tailed_windows)} windows, "
              f"YES gross median {t['median']:+.4f}, >0 in {100 * t['share_pos']:.2f}%")

    by_family = book_legs(conn)
    rows = summarize_book(by_family)
    if rows:
        cost = sum(r["cost"] for r in rows)
        locked_p = [r for r in rows if r["locked_profit"]]
        locked_l = [r for r in rows if r["locked_loss"]]
        worst = distribution([(r["min_payoff"] - r["cost"]) / r["cost"] for r in rows if r["cost"] > 0])
        print()
        print("=== BOOK ARM — ladders where we hold >=2 buckets, as static hold-to-settlement vectors ===")
        print(f"basis: population = non-demo PaperTrade legs in temperature ladders; level = ladder family; "
              f"cost = simulatedPositionSize; payoff per possible winner (held buckets + one unheld case)")
        print(f"families: {len(rows)}; legs: {sum(r['legs'] for r in rows)}; notional ${cost:.2f}")
        print(f"  guaranteed LOSS as a set (cost > best-case payoff): {len(locked_l)} families, "
              f"${sum(r['cost'] - r['max_payoff'] for r in locked_l):.2f} locked")
        print(f"  guaranteed PROFIT as a set (cost < worst-case payoff): {len(locked_p)} families, "
              f"${sum(r['min_payoff'] - r['cost'] for r in locked_p):.2f} locked on ${sum(r['cost'] for r in locked_p):.2f}")
        print(f"  worst-case return on cost (one held bucket wins): median {100 * worst['median']:+.1f}%, "
              f"p10 {100 * worst['p10']:+.1f}%")
        print(f"  CAVEAT: this is a hold-to-settlement vector. Legs closed early break the lock, so it "
              f"describes the position set, not the booked PnL.")
    else:
        print("\nbook arm: no temperature ladder holds >=2 buckets")

    return {
        "window_min": window_min,
        "venue": {"windows": len(windows), "groups": len({w["family"] for w in windows}),
                  "no_gross": no_gross, "no_net": no_net, "no_pct_of_capital": pct,
                  "yes_gross": yes_gross,
                  "positive_windows": len(pos), "positive_sum_per_unit": sum(pos_sorted),
                  "positive_ex_top1": sum(pos_sorted[1:]), "positive_ex_top5": sum(pos_sorted[5:]),
                  "top10_group_share": (top10 / sum(pos_sorted)) if pos else None},
        "book": rows,
    }


def self_test():
    """Every assertion here is a NEGATIVE control: it fails if the detector regresses."""
    ok = True
    def check(name, cond):
        nonlocal ok
        print(f"  {'PASS' if cond else 'FAIL'}  {name}")
        ok = ok and cond

    # 1. ladder key: bucket tails only, and a non-bucket slug is not a ladder
    check("ladder_key strips a bucket tail",
          ladder_key("highest-temperature-in-madrid-on-july-16-2026-34c")
          == "highest-temperature-in-madrid-on-july-16-2026")
    check("ladder_key keeps orbelow/orhigher tails grouped",
          ladder_key("x-on-july-16-2026-30corbelow") == "x-on-july-16-2026")
    check("ladder_key refuses a non-bucket slug",
          ladder_key("acl-foo-bar-2026-09-14-total-2pt5") is None)

    # 2. the NO-side detector fires on a real arb and stays silent otherwise
    arb = {"a": (0.40, 0.42), "b": (0.38, 0.40), "c": (0.32, 0.34)}   # sum bid 1.10
    v = window_vector(arb, 3)
    check("detects sum-bid > 1 as a NO-side edge", v["no_gross"] > 0.09)
    quiet = {"a": (0.40, 0.42), "b": (0.30, 0.32), "c": (0.20, 0.22)}  # sum bid 0.90
    check("does NOT report an edge on a normal vector", window_vector(quiet, 3)["no_gross"] < 0)

    # 3. fees must be able to flip a thin edge, or fee accounting is fake
    thin = {"a": (0.40, 0.42), "b": (0.38, 0.40), "c": (0.23, 0.25)}   # sum bid 1.01 gross
    v = window_vector(thin, 3)
    check("a +0.01 gross edge is net NEGATIVE after fees", v["no_gross"] > 0 and v["no_net"] < 0)

    # 4. a partial set must be refused, not silently summed
    check("refuses a window missing a member", window_vector({"a": (0.4, 0.42)}, 3) is None)
    check("refuses a window with a null quote",
          window_vector({"a": (0.4, 0.42), "b": (None, 0.3), "c": (0.3, 0.32)}, 3) is None)

    # 5. the payoff vector must include the unheld case, or every all-NO family looks locked
    legs = [{"marketId": "m1", "outcome": "NO", "entryPrice": 0.8, "cost": 8.0},
            {"marketId": "m2", "outcome": "NO", "entryPrice": 0.5, "cost": 8.0}]
    cases = payoff_cases(legs)
    check("payoff vector carries the <unheld bucket> case", "<unheld bucket>" in cases)
    check("all-NO vector is not a locked loss when an unheld bucket can win",
          max(cases.values()) > 16.0)          # 8/0.8 + 8/0.5 = 26
    check("held-bucket win case pays only the other leg", cases["m1"] == 16.0)

    # 6. a genuinely locked loss is still caught
    # two YES legs on exclusive buckets, 10 shares each at 0.60 -> cost 12, best case pays 10
    locked = [{"marketId": "m1", "outcome": "YES", "entryPrice": 0.6, "cost": 6.0},
              {"marketId": "m2", "outcome": "YES", "entryPrice": 0.6, "cost": 6.0}]
    rows = summarize_book({"f": locked})
    check("catches a constructed locked loss", rows[0]["locked_loss"])

    print("SELF-TEST", "GREEN" if ok else "RED")
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--window-min", type=int, default=10)
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--no-write", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    try:
        result = report(conn, args.window_min)
    finally:
        conn.close()
    if result and not args.no_write:
        with open(OUT, "w") as fh:
            json.dump(result, fh, indent=1)
        print(f"\nwrote {os.path.relpath(OUT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
