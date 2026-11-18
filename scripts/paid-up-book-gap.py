#!/usr/bin/env python3
"""
PAID-UP ENTRY COHORT — the mapping from the TAPE basis (what the card measured) to the
EXECUTABLE basis (the book we could actually have traded against at dispatch).

WHY THIS EXISTS
---------------
Card `paid-up-entry-cohort` carries a standing caveat that decides its implementation:

    "gap is measured against a print price, not the book the bot saw; the executable form is
     'entry above the best ask at dispatch' and the mapping from print-gap to book-gap is
     unmeasured — measure that join before writing the rule."

This instrument measures that join. The retrospective gap is

    gap_print = trueP - tape_p0        (tape_p0 = prices-history MIDPOINT at dispatch)

and the executable frame is the quoted book at dispatch (MarketSnapshot bestBid/bestAsk,
collected ~1/min, median age 11s at dispatch):

    gap_ask  = trueP - mkt_ask         > 0  <=>  we paid THROUGH the offer  (a taker)
    gap_mid  = trueP - mkt_mid         > 0  <=>  our price was above the market's mid at
                                             dispatch (we crossed the mid, not the spread)

READ-ONLY: DB mode=ro, no prisma write, no RuleSet read/write, no dispatch code touched,
no fillStatus stamp written. Lane A: the RULE it prices is a proposal, never an apply.

RUN
  python3 scripts/paid-up-book-gap.py                  # whole tape-reachable book
  python3 scripts/paid-up-book-gap.py --snap-window 300
  python3 scripts/paid-up-book-gap.py --selftest
"""
import argparse
import importlib.util
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def _mod(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(m)
    return m


ppi = _mod("ppi", os.path.join(HERE, "profit-postfix-integrity.py"))
ft = _mod("ft", os.path.join(HERE, "profit-fill-tape.py"))
pte = _mod("pte", os.path.join(HERE, "profit-taker-entry.py"))

FAIL = []
FIX_TS = "2026-11-09 09:15:16"      # the price-side ledger repair, the bar's post window
READ_TS = "2026-11-17 00:00:00"     # the profit review that produced the card's headline


def chk(label, ok, detail=""):
    print("  [%s] %s%s" % ("PASS" if ok else "FAIL", label, (" — " + detail) if detail else ""))
    if not ok:
        FAIL.append(label)
    return ok


def agg(ls):
    n = len(ls)
    ntl = sum(l["simulatedPositionSize"] for l in ls)
    p = sum(l["realizedPnl"] or 0.0 for l in ls)
    return n, ntl, p, (p / ntl * 100.0 if ntl else None)


def cistr(ls):
    if len(ls) < 2:
        return "n/a"
    lo, hi = ppi.cluster_ci(ls, lambda l: l["realizedPnl"] or 0.0)
    if lo is None:
        return "n/a"
    return "[%+.1f,%+.1f]" % (lo, hi)


def line(tag, ls, width=28):
    n, ntl, p, r = agg(ls)
    rr = ("%+.1f%%" % r) if r is not None else "   n/a"
    print("  %-*s %4d %9.0f %+10.1f %8s  %18s" % (width, tag, n, ntl, p, rr, cistr(ls)))


def row(tag, cells, width=28):
    print("  %-*s %s" % (width, tag, cells))


def pgap(l):
    return l["trueP"] - l["tape_p0"]


PRINT_BUCKETS = ((-9.9, -0.02, "gap_print <= -2c (rested)"),
                 (-0.02, 0.0, "gap_print -2..0c"),
                 (0.0, 0.02, "gap_print 0..+2c (paid up)"),
                 (0.02, 9.9, "gap_print >= +2c (crossed)"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--window", type=int, default=3600, help="tape touch window (s)")
    ap.add_argument("--snap-window", type=int, default=300, help="MarketSnapshot join window (s)")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()

    print("=" * 96)
    print("PAID-UP ENTRY COHORT — tape gap vs the quoted book at dispatch (is the executable rule the same rule?)")
    print("=" * 96)

    legs = [l for l in ft.load("2026-09-01")]
    print("\n  deduped non-demo legs opened >= 2026-09-01 with a conditionId: %d" % len(legs))
    print("  adjudicating against cached venue tape ...")
    ft.classify(legs, workers=a.workers)
    for l in legs:
        l["tv"] = ft.verdict_at(l, a.window)
    settled = [l for l in legs if l["status"] != "open"]

    # same reachable basis as profit-filled-decomp.py S4 / S8
    reach = []
    for l in settled:
        if l.get("fillStatus") == "filled":
            reach.append(l)
        elif l.get("fillStatus") == "unfilled":
            continue
        elif l["tv"] == "filled_tape":
            reach.append(l)
    reach = [l for l in reach if l.get("tape_p0") is not None]
    print("  settled %d; tape-reachable with a dispatch mid: %d" % (len(settled), len(reach)))

    # ---------------------------------------------------------------- S0 book coverage
    print("\n" + "-" * 96)
    print("S0. COVERAGE — can the QUOTED BOOK speak to the same legs the tape does?")
    print("-" * 96)
    S, stats = pte.enrich(reach, a.snap_window)
    cov = len(S) / float(len(reach)) * 100.0 if reach else 0.0
    print("  book mapped: %d/%d = %.1f%%  [no snapshot %d, side-ambiguous %d, bad book %d]"
          % (len(S), len(reach), cov, stats["no_snap"], stats["ambiguous"], stats["bad_book"]))
    if S:
        lag = sorted(l["snap_lag_s"] for l in S)
        print("  snapshot age at dispatch: median %.0fs  p90 %.0fs" %
              (lag[len(lag) // 2], lag[int(0.9 * len(lag))]))
        stal = sorted(abs(l["mkt_mid"] - l["tape_p0"]) * 100 for l in S)
        print("  |book mid - tape mid| at dispatch: median %.2fc  p90 %.2fc  share >2c %.1f%%"
              % (stal[len(stal) // 2], stal[int(0.9 * len(stal))],
                 sum(1 for s in stal if s > 2.0) / len(stal) * 100.0))
        own = sum(1 for l in S if l["map_how"].endswith("/own"))
        print("  side map: own %d / complement %d" % (own, len(S) - own))
        chk("book mapped on >=70%% of tape-reachable legs", cov >= 70.0, "%.1f%%" % cov)
        chk("book mid agrees with the tape mid within 2c on >=70%% of legs",
            sum(1 for s in stal if s <= 2.0) >= 0.7 * len(stal))

    # the card's headline, re-cut today, and what moved since the read
    print("\n  the card's two classes, re-cut on TODAY's reachable book (cost = dollars at risk):")
    print("  %-28s %4s %9s %10s %8s  %18s" % ("class", "legs", "cost", "PnL", "ROI", "cluster CI"))
    pu = [l for l in reach if pgap(l) > 0.0]
    rest = [l for l in reach if pgap(l) <= 0.0]
    line("as traded (reachable)", reach)
    line("paid at/below print", rest)
    line("paid up (print, >0)", pu)
    b_after = ppi._ms(READ_TS)
    for tag, pop in (("legs opened >= 2026-11-17", [l for l in reach if l["openedTs"] >= b_after]),
                     ("legs opened <  2026-11-17", [l for l in reach if l["openedTs"] < b_after])):
        print("  " + tag)
        line("  at/below", [l for l in pop if pgap(l) <= 0.0], width=26)
        line("  paid up", [l for l in pop if pgap(l) > 0.0], width=26)

    if not S:
        print("\n  no book coverage — cannot answer the mapping. STOP.")
        return 1

    # ---------------------------------------------------------------- S1 the mapping
    print("\n" + "-" * 96)
    print("S1. THE MAPPING — where the booked entry sat in the QUOTED BOOK at dispatch")
    print("-" * 96)


    def book_pos(l):
        if l["trueP"] > l["mkt_ask"] + 1e-9:
            return "through ask"
        if l["trueP"] > l["mkt_mid"] + 1e-9:
            return "mid..ask"
        return "<= mid"


    cols = ("<= mid", "mid..ask", "through ask")
    print("  %-30s %s" % ("", "".join("%24s" % ("entry " + c) for c in cols)))
    for lo, hi, label in PRINT_BUCKETS:
        sub = [l for l in S if lo < pgap(l) <= hi]
        if not sub:
            continue
        cells = ""
        for c in cols:
            k = sum(1 for l in sub if book_pos(l) == c)
            cells += "%18d (%4.1f%%)" % (k, k / float(len(sub)) * 100.0)
        print("  %-30s %s" % (label, cells))
    tot = {}
    for c in cols:
        tot[c] = [l for l in S if book_pos(l) == c]
    print("  " + "-" * 92)
    for c in cols:
        line("  ALL: entry " + c, tot[c], width=26)

    puS = [l for l in S if pgap(l) > 0.0]
    through = [l for l in puS if book_pos(l) == "through ask"]
    print("\n  of the %d print-paid-up legs, %d (%.1f%%) were THROUGH THE OFFER at dispatch"
          % (len(puS), len(through), len(through) / float(len(puS)) * 100.0 if puS else 0.0))
    above_mid = [l for l in puS if book_pos(l) != "<= mid"]
    print("  of the %d print-paid-up legs, %d (%.1f%%) were above the BOOK MID at dispatch"
          % (len(puS), len(above_mid), len(above_mid) / float(len(puS)) * 100.0 if puS else 0.0))

    # ---------------------------------------------------------------- S1b p0 timing
    print("\n" + "-" * 96)
    print("S1b. IS tape_p0 THE PRICE AT DISPATCH? (p0 = first print at/after dispatch-120s)")
    print("-" * 96)
    for l in S:
        t0 = l["openedTs"] // 1000
        ser = l.get("tape_series") or []
        p0t = None
        for t, _p in ser:
            if t >= t0 - 120:
                p0t = t
                break
        l["p0_lag_s"] = (p0t - t0) if p0t is not None else None
        near = min(ser, key=lambda tp: abs(tp[0] - t0)) if ser else None
        l["tape_pn"] = near[1] if near else None
        l["pn_lag_s"] = abs(near[0] - t0) if near else None
    pl = sorted(l["p0_lag_s"] for l in S if l["p0_lag_s"] is not None)
    if pl:
        print("  p0 offset from dispatch: median %+ds  p10 %+ds  p90 %+ds  (negative = p0 is PRE-dispatch)"
              % (pl[len(pl) // 2], pl[int(0.1 * len(pl))], pl[int(0.9 * len(pl))]))
        print("  share of legs whose p0 print predates dispatch: %.1f%%"
              % (sum(1 for x in pl if x < 0) / float(len(pl)) * 100.0))
    pn = sorted((l["trueP"] - l["tape_pn"]) * 100 for l in S if l.get("tape_pn") is not None)
    p0v = sorted(pgap(l) * 100 for l in S)
    if pn:
        print("  median gap on p0: %+.2fc ; on the NEAREST print: %+.2fc ; nearest-print age median %ds"
              % (p0v[len(p0v) // 2], pn[len(pn) // 2],
                 sorted(l["pn_lag_s"] for l in S if l.get("pn_lag_s") is not None)[len(S) // 2]))
    print("  re-cut of the card's class on the NEAREST print (p0 timing removed):")
    for lo, hi, label in ((-9.9, 0.0, "paid at/below"), (0.0, 0.02, "paid 0..+2c"), (0.02, 9.9, "paid >= +2c")):
        sub = [l for l in S if l.get("tape_pn") is not None and lo < (l["trueP"] - l["tape_pn"]) <= hi]
        if sub:
            line("  " + label, sub, width=24)

    # ---------------------------------------------------------------- S1c the 2x2
    print("\n" + "-" * 96)
    print("S1c. PRINT SAYS PAID UP vs BOOK SAYS PAID UP — where does the loss actually live?")
    print("-" * 96)
    for l in S:
        l["d_lag"] = max(0.0, (l["openedTs"] - l["ots"]) / 1000.0) if l.get("ots") else None
    cells = (("A print>0 AND above book mid (real)", lambda l: pgap(l) > 0.0 and book_pos(l) != "<= mid"),
             ("B print>0, book says <= mid (print-only)", lambda l: pgap(l) > 0.0 and book_pos(l) == "<= mid"),
             ("C print<=0, book says above mid (book-only)", lambda l: pgap(l) <= 0.0 and book_pos(l) != "<= mid"),
             ("D neither (both say rested)", lambda l: pgap(l) <= 0.0 and book_pos(l) == "<= mid"))
    print("  %-42s %4s %8s %9s %8s  %16s %9s %10s"
          % ("cell", "legs", "cost", "PnL", "ROI", "cluster CI", "med det.lag", "med|b-t|"))
    for tag, f in cells:
        sub = [l for l in S if f(l)]
        if not sub:
            continue
        n, ntl, p, r = agg(sub)
        lags = sorted(l["d_lag"] for l in sub if l["d_lag"] is not None)
        dis = sorted(abs(l["mkt_mid"] - l["tape_p0"]) * 100 for l in sub)
        print("  %-42s %4d %8.0f %+9.1f %+7.1f%%  %16s %8s %9.2fc"
              % (tag, n, ntl, p, r, cistr(sub),
                 ("%.0fs" % lags[len(lags) // 2]) if lags else "n/a", dis[len(dis) // 2]))

    # ---------------------------------------------------------------- S1d agreement-conditioned
    print("\n" + "-" * 96)
    print("S1d. DOES THE CLASS SURVIVE WHERE THE TWO BASES AGREE? (kills the basis-noise explanation)")
    print("-" * 96)
    for tol_c in (0.5, 1.0):
        tol = tol_c / 100.0
        Ag = [l for l in S if abs(l["mkt_mid"] - l["tape_p0"]) <= tol + 1e-9]
        print("  legs whose book mid and tape mid agree within %.1fc: %d/%d = %.1f%%"
              % (tol_c, len(Ag), len(S), len(Ag) / float(len(S)) * 100.0))
        if not Ag:
            continue
        for lo, hi, label in ((-9.9, 0.0, "print: at/below"), (0.0, 0.02, "print: 0..+2c"),
                              (0.02, 9.9, "print: >= +2c")):
            sub = [l for l in Ag if lo < pgap(l) <= hi]
            if sub:
                line("  " + label, sub, width=24)
        for tag, f in cells[:2]:
            sub = [l for l in Ag if f(l)]
            if sub:
                line("  " + tag[:24], sub, width=24)
        print()



    print("\n" + "-" * 96)
    print("S2. THE EXECUTABLE RULE — 'do not dispatch when the entry is above the best ask' (and two variants)")
    print("-" * 96)
    print("  %-28s %4s %9s %10s %8s  %18s" % ("arm", "legs", "cost", "PnL", "ROI", "cluster CI"))
    for tag, fired in (("entry through the ask", [l for l in S if book_pos(l) == "through ask"]),
                       ("entry above the book mid", [l for l in S if book_pos(l) != "<= mid"]),
                       ("entry above the tape mid", [l for l in S if pgap(l) > 0.0])):
        kept = [l for l in S if l not in fired]
        line("  SKIP " + tag + " (n)", fired, width=30)
        line("  -> book kept", kept, width=30)
    print()
    base = agg(S)
    print("  baseline (book-mapped reachable): %d legs $%.0f %+.1f (%.1f%%)"
          % (base[0], base[1], base[2], base[3]))

    # ---------------------------------------------------------------- S3 dose-response on the book basis
    print("\n" + "-" * 96)
    print("S3. DOES THE DOSE-RESPONSE SURVIVE ON THE BOOK BASIS? (PnL by gap_ask and gap_mid)")
    print("-" * 96)
    for name, key, buckets in (
            ("gap_ask = entry - best ask", "a", ((-9.9, -0.05, "<= -5c under the offer"),
                                                 (-0.05, -0.02, "-5..-2c"),
                                                 (-0.02, 0.0, "-2..0c"),
                                                 (0.0, 0.02, "0..+2c"),
                                                 (0.02, 9.9, ">= +2c through the offer"))),
            ("gap_mid = entry - book mid", "m", ((-9.9, -0.05, "<= -5c under the mid"),
                                                 (-0.05, -0.02, "-5..-2c"),
                                                 (-0.02, 0.0, "-2..0c"),
                                                 (0.0, 0.02, "0..+2c above the mid"),
                                                 (0.02, 9.9, ">= +2c above the mid")))):
        print("  " + name)
        for lo, hi, label in buckets:
            sub = [l for l in S
                   if lo < ((l["trueP"] - l["mkt_ask"]) if key == "a" else (l["trueP"] - l["mkt_mid"])) <= hi]
            if sub:
                line("  " + label, sub, width=26)
        print()

    # ---------------------------------------------------------------- S3b live-observable proxies
    print("-" * 96)
    print("S3b. CAN DISPATCH SEE IT? loss by the quantities the scorer actually holds at dispatch")
    print("-" * 96)
    print("  |entry - book mid| at dispatch (distance, both directions):")
    for lo, hi, label in ((-0.01, 0.005, "<= 0.5c"), (0.005, 0.01, "0.5-1c"),
                          (0.01, 0.02, "1-2c"), (0.02, 0.05, "2-5c"), (0.05, 9.9, "> 5c")):
        sub = [l for l in S if lo < abs(l["trueP"] - l["mkt_mid"]) <= hi]
        if sub:
            line("  " + label, sub, width=24)
    print("  quoted spread at dispatch:")
    for lo, hi, label in ((-0.01, 0.015, "<= 1.5c"), (0.015, 0.025, "1.5-2.5c"),
                          (0.025, 0.05, "2.5-5c"), (0.05, 9.9, "> 5c")):
        sub = [l for l in S if lo < l["mkt_spread"] <= hi]
        if sub:
            line("  " + label, sub, width=24)
    print("  snapshot age at dispatch:")
    for lo, hi, label in ((-1, 30, "<= 30s"), (30, 60, "30-60s"), (60, 180, "60-180s"),
                          (180, 10 ** 6, "> 180s")):
        sub = [l for l in S if lo < l["snap_lag_s"] <= hi]
        if sub:
            line("  " + label, sub, width=24)
    print("  |book mid - tape mid| at dispatch (the disagreement axis, both directions):")
    for lo, hi, label in ((-0.01, 0.005, "<= 0.5c"), (0.005, 0.01, "0.5-1c"),
                          (0.01, 0.02, "1-2c"), (0.02, 9.9, "> 2c")):
        sub = [l for l in S if lo < abs(l["mkt_mid"] - l["tape_p0"]) <= hi]
        if sub:
            line("  " + label, sub, width=24)

    # ---------------------------------------------------------------- S4 decomposition
    print("-" * 96)
    print("S4. WHAT IS THE PRINT GAP MADE OF? drift vs paying through the offer")
    print("-" * 96)
    print("  gap_print = (trueP - book_mid)  +  (book_mid - tape_p0)")
    print("              ^ we crossed the mid       ^ the mid moved between our read and dispatch")
    print("  %-30s %6s %14s %14s" % ("print bucket", "legs", "median x-mid", "median drift"))
    for lo, hi, label in PRINT_BUCKETS:
        sub = [l for l in S if lo < pgap(l) <= hi]
        if not sub:
            continue
        xm = sorted((l["trueP"] - l["mkt_mid"]) * 100 for l in sub)
        dr = sorted((l["mkt_mid"] - l["tape_p0"]) * 100 for l in sub)
        print("  %-30s %6d %13.2fc %13.2fc"
              % (label, len(sub), xm[len(xm) // 2], dr[len(dr) // 2]))

    # ---------------------------------------------------------------- S5 the live shadow
    print("\n" + "-" * 96)
    print("S5. WHAT A [PAID-UP] SHADOW WOULD HAVE PRINTED — and how the 150-leg bar accrues")
    print("-" * 96)
    fix = ppi._ms(FIX_TS)
    post = [l for l in S if l["openedTs"] >= fix]
    if post:
        d = max((max(l["openedTs"] for l in post) - min(l["openedTs"] for l in post)) / 86400000.0, 0.5)
        pu_post = [l for l in post if pgap(l) > 0.0]
        thr_post = [l for l in post if book_pos(l) == "through ask"]
        print("  post price-side fix: %d book-mapped legs over %.1fd = %.2f legs/day" %
              (len(post), d, len(post) / d))
        print("  bar class on the PRINT basis : %d legs (%.2f/day) -> 150 at ~%.0f days"
              % (len(pu_post), len(pu_post) / d, (150 - len(pu_post)) / (len(pu_post) / d)) if pu_post else "")
        print("  rule class on the BOOK basis : %d legs (%.2f/day) -> 150 at ~%.0f days"
              % (len(thr_post), len(thr_post) / d,
                 ((150 - len(thr_post)) / (len(thr_post) / d)) if thr_post else 0))
        print()
        line("  post-fix, print paid-up", pu_post)
        line("  post-fix, through the ask", thr_post)
    print("\n  ONE LINE PER SCORING CYCLE, write-only, no decision:")
    print("    [PAID-UP] legs=%d gap_bid/med=%.2fc gap_ask/med=%.2fc through_ask=%d "
          "post_fix_pu=%d/150 roi=%+.1f%%")
    print("  fields: entry vs bestBid/bestMid/bestAsk at dispatch (MarketSnapshot), the tape gap "
          "joined\nafter the fact, the post-fix bar count, and the running ROI of the flagged class.")

    print("\n" + "=" * 96)
    print("self-checks: all PASS" if not FAIL else ("self-checks: %d FAIL" % len(FAIL)))
    print("=" * 96)
    return 1 if FAIL else 0


def selftest():
    print("self-test: bucket edges, book position, aggregation identity")
    mk = lambda p, a, m, t0: {"trueP": p, "mkt_ask": a, "mkt_mid": m, "tape_p0": t0,
                              "simulatedPositionSize": 10.0, "realizedPnl": 0.0}
    l1 = mk(0.50, 0.48, 0.485, 0.49)  # through ask, print paid up
    l2 = mk(0.48, 0.52, 0.51, 0.50)   # under mid, print paid down
    assert l1["trueP"] > l1["mkt_ask"] and l2["trueP"] <= l2["mkt_mid"]
    assert pgap(l1) > 0.0 and pgap(l2) <= 0.0
    n, ntl, p, r = agg([l1, l2])
    assert (n, ntl, p, r) == (2, 20.0, 0.0, 0.0)
    print("  selftest OK")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
    else:
        sys.exit(main())
