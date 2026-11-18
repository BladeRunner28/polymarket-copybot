#!/usr/bin/env python3
"""
TAKER-ENTRY VALUATION — is there ANY entry mechanism at which this signal makes money?

WHY THIS EXISTS
---------------
2026-11-17 adjudicated fills from the venue tape and found the book's realised profit living in
legs that never traded. That closes the FILL question and leaves the ENTRY-MECHANISM question open,
which is the one that decides the ladder: a maker bid that fills 30% of the time is a different
business from a taker order that fills 100% of the time, and the book has only ever been valued at
the maker bid.

Three prices, one exit
----------------------
For every settled leg we know the quoted book at dispatch (MarketSnapshot bestBid/bestAsk, keyless,
collected ~1/min) and the exit (implied exactly by the booked PnL). Re-price the SAME trade at:
    bid  = our resting bid (the booked entry; what the paper ledger assumes we paid)
    mid  = the market's own fair price (no spread paid, no queue position won)
    ask  = what a taker actually pays to be SURE of the fill
The gap bid->mid is the half-spread we are credited for winning; mid->ask is what we would pay to
stop waiting. If ROI(mid) <= 0 the signal has no value before execution. If ROI(ask) > 0 the whole
fill problem is solvable by crossing and the ladder is a volume problem, not an edge problem.

EV PER DISPATCH
---------------
The ranking number is expected PnL per dispatched intent, not per filled leg:
    maker: P(touch) * ROI(touched)      -- P from the venue tape, the 2026-11-17 model
    taker: 1.0      * ROI(ask)          -- a marketable order does not wait
Both are dollars of PnL per dollar of intent, so they are directly comparable.

COST BASIS: PaperTrade.simulatedPositionSize = DOLLARS AT RISK (not shares). Re-pricing to a higher
price buys FEWER shares on the same stake: pnl = ntl * (exit/p - 1), exit implied by the booked PnL
(ppi.true_pnl). Market-clustered bootstrap CIs (2,000 draws). Dedupe: first leg per
bot|wallet|market|outcome. Regime: DecisionJournal.ruleSetVersion >= 68.

SIDE MAPPING (the trap): the snapshot's bestBid/bestAsk belong to the snapshot's reference token,
which is NOT always the token the leg is on. The tape's own mid for the leg's token decides the
side; legs whose two sides are within AMBIG of each other are counted as unmappable and excluded
from the ask-basis ROI rather than guessed.

READ-ONLY: DB mode=ro, no prisma write, no RuleSet read/write. Caches nothing new (reuses
data/fill-tape-cache via scripts/profit-fill-tape.py).

RUN
  python3 scripts/profit-taker-entry.py                 # regime v68+, snapshot window 300s
  python3 scripts/profit-taker-entry.py --snap-window=60
  python3 scripts/profit-taker-entry.py --selftest
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

MIN_RULE = 68
BANDS = ((0.0, 0.20), (0.20, 0.40), (0.40, 0.60), (0.60, 0.80), (0.80, 1.01))
AMBIG = 0.02
FAIL = []


def chk(label, ok, detail=""):
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}" + (f" — {detail}" if detail else ""))
    if not ok:
        FAIL.append(label)
    return ok


# ------------------------------------------------------------------ stats helpers

def agg(ls, pnl=None):
    pnl = pnl or (lambda l: l["realizedPnl"] or 0.0)
    n = sum(l["simulatedPositionSize"] for l in ls)
    p = sum(pnl(l) for l in ls)
    return len(ls), n, p, (p / n * 100.0 if n else None)


def cistr(ls, pnl=None):
    if len(ls) < 2:
        return "n/a"
    lo, hi = ppi.cluster_ci(ls, pnl or (lambda l: l["realizedPnl"] or 0.0))
    return "n/a" if lo is None else f"[{lo:+.1f},{hi:+.1f}]"


def line(tag, ls, pnl=None, width=24):
    n, ntl, p, r = agg(ls, pnl)
    rr = f"{r:+.1f}%" if r is not None else "   n/a"
    print(f"  {tag:<{width}} {n:>4} {ntl:>8.0f} {p:>+9.1f} {rr:>8}  {cistr(ls, pnl):>17}")


def ex_top(ls, k, pnl=None):
    pnl = pnl or (lambda l: l["realizedPnl"] or 0.0)
    return sorted(ls, key=lambda l: -pnl(l))[k:]


def at(p):
    """Re-price every leg at price p (dollars at risk held constant)."""
    return lambda l: pnl_at(l, p(l))


def exit_of(l):
    """The exit price, including on rows the ledger masks.

    The fill-aware booking flip writes realizedPnl = 0 on resolver-`unfilled` rows. That is a
    BOOKING convention, not a price: the leg still had a settlement. currentPrice on those rows is
    the settlement price (0.0 / 1.0 on resolved rows) or the mark at close. Using the PnL identity
    alone would value every masked row at ZERO PnL in every arm -- which is exactly the class the
    taker arm exists to capture, so it would silently bias the taker result toward zero on the
    largest clips. Returns None when no exit can be established.
    """
    ntl, b, booked = l.get("simulatedPositionSize"), l.get("entryPrice"), l.get("realizedPnl")
    masked = (l.get("fillStatus") == "unfilled" and (booked or 0.0) == 0.0)
    if masked or booked is None:
        cp = l.get("currentPrice")
        if cp is None:
            return None
        return float(cp)
    if not ntl or not b:
        return None
    return b * (1.0 + booked / ntl)


def pnl_at(l, p):
    """PnL if the SAME exit had been entered at price p, same DOLLARS AT RISK."""
    ntl, e = l.get("simulatedPositionSize"), l.get("exit_px")
    if not ntl or e is None or p is None or p <= 0:
        return l.get("realizedPnl") or 0.0
    return ntl * (e / p - 1.0)


# ------------------------------------------------------------------ snapshot side mapping

def snap_for(c, market_id, t0, window_s):
    row = c.execute(
        "SELECT bestBid, bestAsk, spread, collectedAt FROM MarketSnapshot WHERE marketId=? "
        "AND bestBid > 0 AND bestAsk > 0 AND collectedAt BETWEEN ? AND ? "
        "ORDER BY ABS(collectedAt-?) LIMIT 1",
        (market_id, t0 - window_s * 1000, t0 + window_s * 1000, t0)).fetchone()
    if not row:
        return None
    b, a, sp, at_ms = row
    if not b or not a or not (0 < b < 1) or not (0 < a < 1):
        return None
    return {"b": float(b), "a": float(a), "spread": float(sp or (a - b)),
            "lag_s": abs(at_ms - t0) / 1000.0}


def map_side(leg, snap):
    """Which side of the quoted book is the leg's token? Returns (bid, ask, how) on the LEG's token.

    The tape's minute series for the leg's OWN token is the arbiter: the snapshot's book is on the
    leg's side if its mid is closer to the tape mid than the complement's mid. No tape -> fall back
    to the booked entry, and if that is ambiguous too, refuse to map.
    """
    mid_snap = (snap["b"] + snap["a"]) / 2.0
    ref = None
    if leg.get("tape_series"):
        t0s = leg["openedTs"] // 1000
        ref = min(leg["tape_series"], key=lambda tp: abs(tp[0] - t0s))[1]
    how = "tape" if ref is not None else "booked"
    if ref is None:
        ref = leg["trueP"]
    d_own = abs(ref - mid_snap)
    d_comp = abs(ref - (1.0 - mid_snap))
    if abs(d_own - d_comp) < AMBIG:
        return None, None, "ambiguous"
    if d_own <= d_comp:
        return snap["b"], snap["a"], how + "/own"
    return 1.0 - snap["a"], 1.0 - snap["b"], how + "/complement"


# ------------------------------------------------------------------ enrich

def enrich(legs, window_s):
    c = ft._con()
    out = []
    stats = {"no_snap": 0, "ambiguous": 0, "bad_book": 0}
    for l in legs:
        sn = snap_for(c, l["marketId"], l["openedTs"], window_s)
        if sn is None:
            stats["no_snap"] += 1
            continue
        b, a, how = map_side(l, sn)
        if how == "ambiguous":
            stats["ambiguous"] += 1
            continue
        if b is None or a is None or a <= b or a >= 1.0 or b <= 0.0:
            stats["bad_book"] += 1
            continue
        l = dict(l)
        l.update({"mkt_bid": b, "mkt_ask": a, "mkt_mid": (a + b) / 2.0,
                  "mkt_spread": sn["spread"], "snap_lag_s": sn["lag_s"], "map_how": how})
        l["exit_px"] = exit_of(l)
        l["is_pos"] = l.get("fillStatus") != "unfilled"
        out.append(l)
    return out, stats


# ------------------------------------------------------------------ main

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--snap-window", type=int, default=300)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--min-rule", type=int, default=MIN_RULE)
    a = ap.parse_args()

    print("=" * 94)
    print("TAKER-ENTRY VALUATION — one exit, three entry prices: our bid / the mid / the quoted ask")
    print("=" * 94)

    legs = [l for l in ft.load("2026-09-01") if (l.get("rv") or 0) >= a.min_rule]
    print(f"\n  regime v{a.min_rule}+, deduped, non-demo: {len(legs)} legs")
    print(f"  adjudicating fill from the venue tape (cached) ...", flush=True)
    ft.classify(legs, workers=a.workers)
    for l in legs:
        l["closedTs"] = ppi._ms(l["closedAt"]) if l.get("closedAt") else None
        l["resolvedTs"] = ppi._ms(l["resolvedAt"]) if l.get("resolvedAt") else None

    settled = [l for l in legs if l["status"] != "open"]
    S, stats = enrich(settled, a.snap_window)
    print(f"  settled {len(settled)}; quoted book mapped on {len(S)} "
          f"({len(S) / max(1, len(settled)) * 100:.1f}%)  "
          f"[no snapshot {stats['no_snap']}, side-ambiguous {stats['ambiguous']}, "
          f"bad book {stats['bad_book']}]")

    # ---------------------------------------------------------------- S1 sanity
    print("\n" + "-" * 94)
    print("S1. SANITY — is the mapped book coherent, and is our bid really under it?")
    print("-" * 94)
    monotone = sum(1 for l in S if l["mkt_bid"] <= l["mkt_mid"] <= l["mkt_ask"])
    chk("mapped book is ordered bid <= mid <= ask", monotone == len(S),
        f"{monotone}/{len(S)}")
    under = [l for l in S if l["trueP"] <= l["mkt_ask"] + 1e-9]
    print(f"  our booked entry at or below the ask: {len(under)}/{len(S)} = "
          f"{len(under) / len(S) * 100:.1f}%  (we rest under the offer)")
    prem = sorted((l["mkt_ask"] - l["trueP"]) * 100 for l in S)
    print(f"  premium a taker would pay over our bid: median {prem[len(prem) // 2]:.2f}c  "
          f"p10 {prem[int(0.1 * len(prem))]:.2f}c  p90 {prem[int(0.9 * len(prem))]:.2f}c")
    spreads = sorted(l["mkt_spread"] * 100 for l in S)
    print(f"  quoted spread: median {spreads[len(spreads) // 2]:.2f}c  "
          f"p90 {spreads[int(0.9 * len(spreads))]:.2f}c")
    # identity: re-pricing at the booked price reproduces the ledger on unmasked rows
    ident = max([abs(pnl_at(l, l["trueP"]) - (l["realizedPnl"] or 0.0))
                 for l in S if l.get("fillStatus") != "unfilled"] or [0.0])
    chk("re-pricing at the booked price reproduces realizedPnl", ident < 0.02, f"max diff ${ident:.4f}")
    masked = [l for l in S if l.get("fillStatus") == "unfilled"]
    if masked:
        print(f"  rows the ledger masks to zero (fillStatus=unfilled): {len(masked)} legs / "
              f"${sum(l['simulatedPositionSize'] for l in masked):.0f} — their exit is taken from")
        print(f"  currentPrice (settlement 0/1 or the close mark), NOT from realizedPnl, so the")
        print(f"  taker arm can value the class it would actually own. book ROI on them: "
              f"{agg(masked, lambda l: pnl_at(l, l['mkt_ask']))[3]:+.1f}% at the ask.")
    own = sum(1 for l in S if l["map_how"].endswith("own"))
    print(f"  side map: own {own} / complement {len(S) - own} — a complement-heavy map is expected")
    print("  on named-outcome markets, where the snapshot's reference token is the other side.")

    # ---------------------------------------------------------------- S1b staleness
    print("\n" + "-" * 94)
    print("S1b. IS THE QUOTED BOOK STALE AT DISPATCH? — snapshot mid vs the tape mid at the same minute")
    print("-" * 94)
    dl = []
    for l in S:
        if not l.get("tape_series"):
            continue
        t0s = l["openedTs"] // 1000
        tv = min(l["tape_series"], key=lambda tp: abs(tp[0] - t0s))[1]
        l["tape_t0"] = tv
        dl.append(abs(tv - l["mkt_mid"]))
    dl.sort()
    if dl:
        print(f"  n={len(dl)}  |snapshot mid - tape mid| : median {dl[len(dl) // 2] * 100:.2f}c  "
              f"p90 {dl[int(0.9 * len(dl))] * 100:.2f}c  share >2c "
              f"{sum(1 for x in dl if x > 0.02) / len(dl) * 100:.1f}%")
        chk("snapshot quote is within 2c of the tape mid on >=70% of legs",
            sum(1 for x in dl if x <= 0.02) >= 0.70 * len(dl),
            "else the ask arm is a stale price, not a taker price")
    snap_lags = sorted(l["snap_lag_s"] for l in S)
    print(f"  snapshot age at dispatch: median {snap_lags[len(snap_lags) // 2]:.0f}s  "
          f"p90 {snap_lags[int(0.9 * len(snap_lags))]:.0f}s")

    # ---------------------------------------------------------------- S2 the three prices
    print("\n" + "-" * 94)
    print("S2. THE ENTRY LADDER — the same exits, three entry prices (cost = dollars at risk)")
    print("-" * 94)
    P = [l for l in S if l["is_pos"]]
    print(f"  positions (resolver did not stamp unfilled): {len(P)} legs / "
          f"${sum(l['simulatedPositionSize'] for l in P):.0f}; all intents: {len(S)} / "
          f"${sum(l['simulatedPositionSize'] for l in S):.0f}")
    print(f"  {'arm':<30} {'legs':>4} {'cost':>8} {'pnl':>9} {'ROI':>8}  {'cluster CI':>17}")
    line("booked (ledger, all rows)", S, lambda l: l["realizedPnl"] or 0.0, width=30)
    for tag, f in (("mid  (no spread paid)", lambda l: l["mkt_mid"]),
                   ("ask  (taker, certain fill)", lambda l: l["mkt_ask"]),
                   ("ask+1c (slippage)", lambda l: min(0.999, l["mkt_ask"] + 0.01))):
        line("positions: bid -> " + tag, P, at(f), width=30)
    print()
    print("  and the UNFILTERED population, which is what a taker actually owns:")
    for tag, f in (("@bid", lambda l: l["mkt_bid"]), ("@mid", lambda l: l["mkt_mid"]),
                   ("@ask", lambda l: l["mkt_ask"]),
                   ("@ask+1c", lambda l: min(0.999, l["mkt_ask"] + 0.01))):
        line("TAKER all intents " + tag, S, at(f), width=30)
    print()
    for lane in ("BANKROLL_200", "STANDARD"):
        sub = [l for l in S if l["botId"] == lane and l["is_pos"]]
        if not sub:
            continue
        print(f"  {lane} (positions, n={len(sub)}):")
        for tag, f in (("bid  (booked, maker)", lambda l: l["trueP"]),
                       ("mid", lambda l: l["mkt_mid"]),
                       ("ask  (taker)", lambda l: l["mkt_ask"])):
            line("  " + tag, sub, at(f), width=26)

    # ---------------------------------------------------------------- S2b lane split
    print("\n" + "-" * 94)
    print("S2b. LANE SPLIT — does the only positive cell survive its own best legs?")
    print("-" * 94)
    b2 = [l for l in S if l["botId"] == "BANKROLL_200" and l["is_pos"]]
    st = [l for l in S if l["botId"] == "STANDARD" and l["is_pos"]]
    if b2 and st:
        for tag, sub in (("BANKROLL_200", b2), ("STANDARD", st)):
            prem_s = sorted((l["mkt_ask"] - l["trueP"]) * 100 for l in sub)
            spr_s = sorted(l["mkt_spread"] * 100 for l in sub)
            print(f"  {tag}: n={len(sub)}  median ask-bid premium {prem_s[len(prem_s) // 2]:.2f}c  "
                  f"median spread {spr_s[len(spr_s) // 2]:.2f}c  "
                  f"median clip ${sorted(l['simulatedPositionSize'] for l in sub)[len(sub) // 2]:.1f}")
            for k in (0, 1, 2, 3):
                s2 = ex_top(sub, k, at(lambda l: l["mkt_ask"])) if k else sub
                n, ntl, p, r = agg(s2, at(lambda l: l["mkt_ask"]))
                print(f"    @ask ex-top-{k:<2} {n:>4} ${ntl:>7.0f} {p:>+9.1f} {r:>+7.1f}%")
        lo, hi = ft.diff_ci(st, b2, pnl=at(lambda l: l["mkt_ask"]))
        print(f"\n  STANDARD minus C-200 at the ask (positions): "
              f"{agg(st, at(lambda l: l['mkt_ask']))[3]:+.1f}pp "
              f"minus {agg(b2, at(lambda l: l['mkt_ask']))[3]:+.1f}pp  "
              f"= {agg(st, at(lambda l: l['mkt_ask']))[3] - agg(b2, at(lambda l: l['mkt_ask']))[3]:+.1f}pp  "
              f"CI95 [{lo:+.1f},{hi:+.1f}] (market-clustered, paired by market)")

    # ---------------------------------------------------------------- S3 is it the spread
    print("\n" + "-" * 94)
    print("S3. IS THE EDGE THE HALF-SPREAD? — booked vs mid vs ask inside each quoted-spread bucket")
    print("-" * 94)
    print(f"  {'quoted spread':<16} {'legs':>4} {'bid ROI':>9} {'mid ROI':>9} {'ask ROI':>9} "
          f"{'half-spread':>12} {'bid-ask gap':>12}")
    buckets = ((0.0, 0.011, "<=1c"), (0.011, 0.021, "1-2c"), (0.021, 0.041, "2-4c"),
               (0.041, 0.081, "4-8c"), (0.081, 9.9, ">=8c"))
    for lo, hi, tag in buckets:
        sub = [l for l in S if lo < l["mkt_spread"] <= hi]
        if len(sub) < 5:
            continue
        rb = agg(sub, at(lambda l: l["trueP"]))[3]
        rm = agg(sub, at(lambda l: l["mkt_mid"]))[3]
        ra = agg(sub, at(lambda l: l["mkt_ask"]))[3]
        hs = sum((l["mkt_mid"] - l["mkt_bid"]) / max(l["mkt_mid"], 1e-9) for l in sub) / len(sub) * 100
        print(f"  {tag:<16} {len(sub):>4} {rb:>+8.1f}% {rm:>+8.1f}% {ra:>+8.1f}% "
              f"{hs:>11.1f}% {rb - ra:>11.1f}pp")

    # ---------------------------------------------------------------- S4 by band
    print("\n" + "-" * 94)
    print("S4. BY PRICE BAND — where paying the offer erases the cell, and where it does not")
    print("-" * 94)
    print("  (a) POSITIONS — the book as owned, re-priced at what the offer would have cost")
    print(f"  {'band':<12} {'legs':>4} {'cost':>8} {'cost%':>6} {'bid ROI':>9} {'mid ROI':>9} "
          f"{'ask ROI':>9} {'ask CI':>17} {'breakeven premium':>18}")
    tot_cost = sum(l["simulatedPositionSize"] for l in P)
    for lo, hi in BANDS:
        sub = [l for l in P if lo <= l["trueP"] < hi or (hi >= 1.01 and l["trueP"] >= lo)]
        if len(sub) < 5:
            print(f"  {lo:.2f}-{hi:.2f}     {len(sub):>4}   — below 5 legs, unmeasured")
            continue
        rb = agg(sub, at(lambda l: l["trueP"]))[3]
        rm = agg(sub, at(lambda l: l["mkt_mid"]))[3]
        ra = agg(sub, at(lambda l: l["mkt_ask"]))[3]
        cst = sum(l["simulatedPositionSize"] for l in sub)
        be = (rm / 100.0) * (sum(l["mkt_mid"] for l in sub) / len(sub)) if rm is not None else None
        print(f"  {lo:.2f}-{hi:.2f}     {len(sub):>4} {cst:>8.0f} {cst / tot_cost * 100:>5.1f}% "
              f"{rb:>+8.1f}% {rm:>+8.1f}% {ra:>+8.1f}% "
              f"{cistr(sub, at(lambda l: l['mkt_ask'])):>17} "
              f"{(f'{be * 100:+.1f}c' if be is not None else 'n/a'):>18}")
    print("\n  (b) EVERY DISPATCHED INTENT at the ASK — the population a taker would own")
    print(f"  {'band':<12} {'legs':>4} {'cost':>8} {'cost%':>6} {'@ask ROI':>9} {'ask CI':>17} "
          f"{'@bid ROI':>9} {'touch%':>7}")
    tot_all = sum(l["simulatedPositionSize"] for l in S)
    for lo, hi in BANDS:
        sub = [l for l in S if lo <= l["trueP"] < hi or (hi >= 1.01 and l["trueP"] >= lo)]
        if len(sub) < 5:
            continue
        cst = sum(l["simulatedPositionSize"] for l in sub)
        tch = sum(1 for l in sub if l.get("tape_verdict") == "filled_tape") / len(sub) * 100
        print(f"  {lo:.2f}-{hi:.2f}     {len(sub):>4} {cst:>8.0f} {cst / tot_all * 100:>5.1f}% "
              f"{agg(sub, at(lambda l: l['mkt_ask']))[3]:>+8.1f}% "
              f"{cistr(sub, at(lambda l: l['mkt_ask'])):>17} "
              f"{agg(sub, at(lambda l: l['trueP']))[3]:>+8.1f}% {tch:>6.1f}%")

    # ---------------------------------------------------------------- S4b inside the favourite tail
    print("\n" + "-" * 94)
    print("S4b. INSIDE THE ONLY CI-POSITIVE CELL — is it a tail, or a band?")
    print("-" * 94)
    fav = [l for l in P if l["trueP"] >= 0.80]
    for k in (0, 1, 2, 3):
        s2 = ex_top(fav, k, at(lambda l: l["mkt_ask"])) if k else fav
        n, ntl, p, r = agg(s2, at(lambda l: l["mkt_ask"]))
        print(f"  @ask ex-top-{k:<2} {n:>4} ${ntl:>7.0f} {p:>+9.1f} {r:>+7.1f}%  "
              f"{cistr(s2, at(lambda l: l['mkt_ask']))}")
    print(f"  {'sub-band':<12} {'legs':>4} {'cost':>8} {'ask ROI':>9} {'ask CI':>17} {'days held':>10}")
    for lo, hi in ((0.80, 0.90), (0.90, 0.95), (0.95, 1.01)):
        sub = [l for l in fav if lo <= l["trueP"] < hi]
        if len(sub) < 3:
            print(f"  {lo:.2f}-{hi:.2f}     {len(sub):>4}   — too thin")
            continue
        hold = [((l["closedTs"] or l["resolvedTs"]) - l["openedTs"]) / 86400000.0
                for l in sub if (l.get("closedTs") or l.get("resolvedTs"))]
        print(f"  {lo:.2f}-{hi:.2f}     {len(sub):>4} "
              f"{sum(l['simulatedPositionSize'] for l in sub):>8.0f} "
              f"{agg(sub, at(lambda l: l['mkt_ask']))[3]:>+8.1f}% "
              f"{cistr(sub, at(lambda l: l['mkt_ask'])):>17} "
              f"{(sum(hold) / len(hold) if hold else 0):>9.1f}d")
    print("  per-leg, so the reader can see the shape rather than the summary:")
    for l in sorted(fav, key=lambda x: -x["trueP"]):
        w = l.get("w")
        dw = f"{l['trueP'] - w:+.3f}" if w is not None else "  none"
        print(f"    p={l['trueP']:.3f} ask={l['mkt_ask']:.3f} ntl={l['simulatedPositionSize']:>6.1f} "
              f"pnl={l['realizedPnl'] or 0:>+8.2f} roi@ask="
              f"{pnl_at(l, l['mkt_ask']) / l['simulatedPositionSize'] * 100:>+7.1f}% "
              f"{l['botId'][:4]:<5} {l['status']:<9} {l['class']:<10} p-w={dw} "
              f"{l['marketId'][:34]}")
    print(f"\n  {'provenance class':<14} {'legs':>4} {'cost':>7} {'ask ROI':>9} {'ask CI':>17}")
    for cls in ("consistent", "no_fill", "INVERTED"):
        sub = [l for l in fav if l["class"] == cls]
        if not sub:
            continue
        print(f"  {cls:<14} {len(sub):>4} {sum(l['simulatedPositionSize'] for l in sub):>7.0f} "
              f"{agg(sub, at(lambda l: l['mkt_ask']))[3]:>+8.1f}% "
              f"{cistr(sub, at(lambda l: l['mkt_ask'])):>17}")
    print("  'consistent' = the booked entry agrees with the wallet's own fill (|p-w| <= 0.06);")
    print("  'no_fill' = no provenance row; 'INVERTED' = the complement-price defect class.")
    # the test that decides whether a 26-leg cell is evidence
    mks = {l["marketId"] for l in fav}
    be = (sum(l["simulatedPositionSize"] * l["trueP"] for l in fav) /
          sum(l["simulatedPositionSize"] for l in fav))
    wins = sum(1 for l in fav if pnl_at(l, l["mkt_ask"]) > 0)
    print(f"\n  distinct markets {len(mks)}, legs {len(fav)}, winning legs {wins}")
    print(f"  cost-weighted breakeven hit rate (h* = p): {be * 100:.2f}%")
    for n_, tag in ((len(mks), "distinct bets"), (len(fav), "legs")):
        lb = 0.05 ** (1.0 / n_) * 100 if wins == len(fav) else None
        print(f"  95% one-sided binomial lower bound, all {n_} {tag} winning: "
              f"{(f'{lb:.2f}%' if lb else 'n/a (not all won)')} -> "
              f"{('CLEARS' if lb and lb > be * 100 else 'FAILS')} the breakeven")
    print("  the difference between those two lines IS the correlation between lanes on the same market.")

    # ---------------------------------------------------------------- S5 EV per dispatch
    print("\n" + "-" * 94)
    print("S5. EV PER DISPATCHED INTENT — the only number that ranks mechanisms")
    print("-" * 94)
    print("  EV per intent-DOLLAR: PnL at that mechanism divided by the cost of EVERY intent in the")
    print("  cell, so a mechanism that fills rarely is not flattered by its small denominator.")
    for l in S:
        l["touched"] = l.get("tape_verdict") == "filled_tape"
    print(f"  {'cell':<22} {'n':>4} {'intent $':>9} {'maker $':>9} {'EV maker':>9} "
          f"{'taker $':>9} {'EV taker':>9} {'better':>7}")
    cells = [("BOOK", S)] + [(lane, [l for l in S if l["botId"] == lane])
                             for lane in ("BANKROLL_200", "STANDARD")]
    cells += [(f"band {lo:.2f}-{hi:.2f}", [l for l in S if lo <= l["trueP"] < hi])
              for lo, hi in BANDS]
    for tag, sub in cells:
        if len(sub) < 5:
            continue
        icost = sum(l["simulatedPositionSize"] for l in sub)
        owned = [l for l in sub if l["is_pos"]]
        pm = sum(pnl_at(l, l["trueP"]) for l in owned)
        pt = sum(pnl_at(l, l["mkt_ask"]) for l in sub)
        print(f"  {tag:<22} {len(sub):>4} {icost:>9.0f} {pm:>+9.1f} {pm / icost * 100:>+8.1f}% "
              f"{pt:>+9.1f} {pt / icost * 100:>+8.1f}% "
              f"{'maker' if pm > pt else 'taker':>7}")
    print("  a negative EV at BOTH columns is the finding: the mechanism is not the problem.")

    # ---------------------------------------------------------------- S6 concentration
    print("\n" + "-" * 94)
    print("S6. CONCENTRATION — does either arm survive removing its best legs")
    print("-" * 94)
    for tag, f in (("bid", lambda l: l["trueP"]), ("mid", lambda l: l["mkt_mid"]),
                   ("ask", lambda l: l["mkt_ask"])):
        for k in (0, 1, 3, 5):
            sub = ex_top(P, k, at(f)) if k else P
            n, ntl, p, r = agg(sub, at(f))
            print(f"  positions {tag} ex-top-{k:<2} {n:>4} ${ntl:>7.0f} {p:>+9.1f} {r:>+7.1f}%")
        print()
    print("  the same cut on the taker population (every intent):")
    for k in (0, 1, 3, 5):
        sub = ex_top(S, k, at(lambda l: l["mkt_ask"])) if k else S
        n, ntl, p, r = agg(sub, at(lambda l: l["mkt_ask"]))
        print(f"  taker ask ex-top-{k:<2} {n:>4} ${ntl:>7.0f} {p:>+9.1f} {r:>+7.1f}%")

    # ---------------------------------------------------------------- S7 dollars per day
    print("-" * 94)
    print("S7. WHAT THE LADDER WOULD SEE — realised rate per day on each arm, and the rung")
    print("-" * 94)
    ts = sorted(l["openedTs"] for l in S)
    d = max((ts[-1] - ts[0]) / 86400000.0, 0.5)
    print(f"  window {d:.1f} days, {len(S) / d:.1f} settled legs/day, "
          f"${sum(l['simulatedPositionSize'] for l in S) / d:,.0f}/day of notional at risk")
    print(f"  {'arm':<28} {'$/day':>8} {'ROI':>7}   notional/day needed for +$250/day")
    for tag, pop, f in (("maker: positions @bid", P, lambda l: l["trueP"]),
                        ("maker: positions @mid", P, lambda l: l["mkt_mid"]),
                        ("taker: all intents @ask", S, lambda l: l["mkt_ask"]),
                        ("taker: all intents @ask+1c", S, lambda l: min(0.999, l["mkt_ask"] + 0.01))):
        n, ntl, p, r = agg(pop, at(f))
        need = f"{250 / (r / 100):>8,.0f}" if r and r > 0 else "        —"
        print(f"  {tag:<28} {p / d:>+8.2f} {r:>+6.1f}%   {need}")
    print(f"  today's notional: ${sum(l['simulatedPositionSize'] for l in S) / d:,.0f}/day. A multiple of")
    print("  that is the only way to the rung, so the ratio above IS the ladder's distance.")

    # ---------------------------------------------------------------- S8 the maker fill class
    print("\n" + "-" * 94)
    print("S8. THE ONE COMPARISON THAT DECIDES ADVERSITY — filled legs at the bid vs the whole cohort")
    print("-" * 94)
    print("  If the taker arm (unconditional, every signal) beats the touched-maker arm, the fill")
    print("  filter is not selecting bad trades; if it is worse, market movement into our bid is bad news.")
    touched = [l for l in S if l["touched"]]
    line("touched maker @bid", touched, at(lambda l: l["trueP"]), width=24)
    line("untouched @bid", [l for l in S if not l["touched"]], at(lambda l: l["trueP"]), width=24)
    line("touched @ask", touched, at(lambda l: l["mkt_ask"]), width=24)
    line("untouched @ask", [l for l in S if not l["touched"]], at(lambda l: l["mkt_ask"]), width=24)

    # ---------------------------------------------------------------- S10 fast-stop pricing
    print("\n" + "-" * 94)
    print("S10. IS THE LOSS EXIT-ABLE? — mark the owned class at +5/+15/+30/+60m and price a fast stop")
    print("-" * 94)
    print("  Exit at the leg-side BID (mid minus half the quoted spread), so the exit pays the spread.")
    print("  Compared with the leg's own realized exit. A stop only helps if the damage is SLOW.")
    def mark(l, lag_s):
        s = l.get("tape_series")
        if not s:
            return None
        t0s = l["openedTs"] // 1000
        sub = [p for t, p in s if t <= t0s + lag_s]
        if len(sub) < 2:
            return None
        return max(0.001, min(0.999, sub[-1] - l["mkt_spread"] / 2.0))

    owned_series = [l for l in P if l.get("tape_series") and l.get("exit_px") is not None]
    print(f"  owned legs with tape: {len(owned_series)}")
    print(f"  {'exit rule':<30} {'legs':>4} {'pnl':>9} {'ROI':>8} {'delta vs hold':>13} {'better on':>10}")
    base_pnl = sum(pnl_at(l, l["trueP"]) for l in owned_series)
    base_ntl = sum(l["simulatedPositionSize"] for l in owned_series)
    for lag in (300, 900, 1800, 3600):
        rows = []
        for l in owned_series:
            m = mark(l, lag)
            if m is None:
                continue
            rows.append((l, l["simulatedPositionSize"] * (m / l["trueP"] - 1.0)))
        if not rows:
            continue
        p = sum(v for _, v in rows)
        ntl = sum(l["simulatedPositionSize"] for l, _ in rows)
        bh = sum(pnl_at(l, l["trueP"]) for l, _ in rows)
        better = sum(1 for l, v in rows if v > pnl_at(l, l["trueP"]) + 1e-9)
        print(f"  exit +{lag // 60:<3}m unconditionally   {len(rows):>4} {p:>+9.1f} {p / ntl * 100:>+7.1f}% "
              f"{p - bh:>+12.1f} {better / len(rows) * 100:>9.1f}%")
    print("\n  threshold grid — a stop that only works at one cell is a coincidence, not a rule:")
    print(f"  {'rule':<20} {'stopped':>8} {'pnl':>9} {'ROI':>8} {'vs hold':>9} {'ex-top-3 delta':>15}")
    hold_p = sum(pnl_at(l, l["trueP"]) for l in owned_series)
    for lag in (300, 900, 1800, 3600):
        for thr in (0.03, 0.05, 0.08, 0.15):
            rows = []
            for l in owned_series:
                m = mark(l, lag)
                if m is None:
                    m = l["trueP"]
                stopped = m <= l["trueP"] * (1.0 - thr)
                v = l["simulatedPositionSize"] * (m / l["trueP"] - 1.0) if stopped else pnl_at(l, l["trueP"])
                rows.append((l, v, stopped))
            p = sum(v for _, v, _ in rows)
            ntl = sum(l["simulatedPositionSize"] for l, _, _ in rows)
            deltas = sorted(((v - pnl_at(l, l["trueP"])) for l, v, _ in rows), reverse=True)
            ex3 = sum(deltas[3:])
            print(f"  +{lag // 60:<3}m down >={thr * 100:>2.0f}%    {sum(1 for _, _, s in rows if s):>8} "
                  f"{p:>+9.1f} {p / ntl * 100:>+7.1f}% {p - hold_p:>+8.1f} {ex3:>+14.1f}")
    print("  (ex-top-3 delta removes the three legs the stop helped most; a rule that only pays on")
    print("  three legs is a tail cut, and it has to be judged as one.)")
    print("\n  the +5m/down>=8% cell by lane (the stop must not be eating the one profitable lane):")
    for lane in ("BANKROLL_200", "STANDARD"):
        sub = [l for l in owned_series if l["botId"] == lane]
        rows = []
        for l in sub:
            m = mark(l, 300)
            if m is None:
                m = l["trueP"]
            stopped = m <= l["trueP"] * (1.0 - 0.08)
            v = l["simulatedPositionSize"] * (m / l["trueP"] - 1.0) if stopped else pnl_at(l, l["trueP"])
            rows.append((l, v, stopped))
        p = sum(v for _, v, _ in rows)
        h = sum(pnl_at(l, l["trueP"]) for l in sub)
        print(f"    {lane:<14} legs {len(rows):>4}  hold {h:>+8.1f}  with stop {p:>+8.1f}  "
              f"delta {p - h:>+7.1f}  ({sum(1 for _, _, s in rows if s)} stopped)")
    print(f"  {'hold to the realized exit':<30} {len(owned_series):>4} {base_pnl:>+9.1f} "
          f"{base_pnl / base_ntl * 100:>+7.1f}%")
    print()
    print("  and split by how fast the fill arrived (a touch <=60s means the market crossed to us):")
    print(f"  {'touch lag':<16} {'legs':>4} {'@bid ROI':>9} {'@ask ROI':>9} {'median exit':>11}")
    for a_, b_, tag in ((0, 61, "<=60s"), (61, 301, "1-5m"), (301, 1801, "5-30m"),
                        (1801, 10 ** 9, ">30m")):
        sub = [l for l in P if l.get("tape_touch_lag_s") is not None
               and a_ <= l["tape_touch_lag_s"] < b_]
        if len(sub) < 5:
            continue
        ex = sorted(l["exit_px"] for l in sub if l["exit_px"] is not None)
        print(f"  {tag:<16} {len(sub):>4} {agg(sub, at(lambda l: l['trueP']))[3]:>+8.1f}% "
              f"{agg(sub, at(lambda l: l['mkt_ask']))[3]:>+8.1f}% "
              f"{(ex[len(ex) // 2] if ex else 0):>10.3f}")
    notouch = [l for l in P if l.get("tape_touch_lag_s") is None]
    if notouch:
        print(f"  {'no touch stamp':<16} {len(notouch):>4} "
              f"{agg(notouch, at(lambda l: l['trueP']))[3]:>+8.1f}% "
              f"{agg(notouch, at(lambda l: l['mkt_ask']))[3]:>+8.1f}%")

    # ---------------------------------------------------------------- S11 depth ladder
    print("\n" + "-" * 94)
    print("S11. THE MAKER DEPTH LADDER — how much discount buys how much fill, and at what edge")
    print("-" * 94)
    print("  entry(k) = market mid at dispatch - k. Filled(k) = the venue tape printed at or below that")
    print("  level inside 60m. PnL is the SAME exit at entry(k). EV per intent = fill rate x ROI, so the")
    print("  best row is the depth a maker should actually post. A deep bid fills late; the tape cannot")
    print("  tell us whether it would still be resting at hour 7, so 60m is the horizon for every row.")
    print(f"  {'depth k':<9} {'filled':>7} {'of':>4} {'fill%':>7} {'cost':>8} {'pnl':>9} {'ROI':>8} "
          f"{'EV/intent':>10} {'CI on ROI':>17}")

    def filled_at(l, k):
        s = l.get("tape_series")
        if not s:
            return None
        t0s = l["openedTs"] // 1000
        lvl = max(0.001, l["mkt_mid"] - k)
        mn = min((p for t, p in s if t >= t0s), default=None)
        return (mn <= lvl + 0.001, lvl)

    for k in (0.0, 0.005, 0.01, 0.02, 0.03, 0.05, 0.08):
        rows = []
        for l in S:
            r = filled_at(l, k)
            if r is None or not r[0]:
                continue
            l = dict(l)
            l["_lvl"] = r[1]
            rows.append(l)
        if not rows:
            continue
        pf = lambda l: l["simulatedPositionSize"] * (l["exit_px"] / l["_lvl"] - 1.0)
        p = sum(pf(l) for l in rows)
        ntl = sum(l["simulatedPositionSize"] for l in rows)
        r = p / ntl * 100
        ev = r * len(rows) / len(S)
        print(f"  {k * 100:>5.1f}c    {len(rows):>7} {len(S):>4} {len(rows) / len(S) * 100:>6.1f}% "
              f"{ntl:>8.0f} {p:>+9.1f} {r:>+7.1f}% {ev:>+9.1f}% {cistr(rows, pf):>17}")
    print("  read: EV/intent is the column to maximise. If it is negative at every depth, no maker")
    print("  posting strategy on this signal pays, and the only remaining lever is what we CHOOSE to")
    print("  copy, not how we post it.")
    print("\n  where the fills actually came from (same legs, touch lag inside the window):")
    for a_, b_, tag in ((0, 1, "immediate (<=1m)"), (1, 301, "1s-5m"), (301, 1801, "5-30m"),
                        (1801, 3601, "30-60m")):
        sub = [l for l in P if l.get("tape_touch_lag_s") is not None
               and a_ <= l["tape_touch_lag_s"] < b_]
        if len(sub) < 5:
            continue
        print(f"    {tag:<18} {len(sub):>4} legs  ${sum(l['simulatedPositionSize'] for l in sub):>7.0f}  "
              f"{agg(sub, at(lambda l: l['trueP']))[3]:>+7.1f}% at our bid  "
              f"{agg(sub, at(lambda l: l['mkt_ask']))[3]:>+7.1f}% at the offer")

    # ---------------------------------------------------------------- S9 the standing premise
    print("\n" + "-" * 94)
    print("S9. THE STANDING PREMISE, RE-TESTED — 'the 0.8-1.0 band is destroyed' (baseline f* -101.3%)")
    print("-" * 94)
    print("  The baseline figure was measured before the 2026-11-11 ledger repair, which moved 233 rows")
    print("  off the COMPLEMENT price. Re-read on the repaired rows, reachable basis (resolver-filled OR")
    print("  tape touch -- unfilled rows are phantom and are excluded), whole v49+ regime.")
    allL = [l for l in ft.load("2026-09-01") if (l.get("rv") or 0) >= 49]
    allL = [l for l in allL if l["status"] != "open"]
    print(f"  re-adjudicating {len(allL)} settled regime legs against the tape (cached) ...", flush=True)
    ft.classify(allL, workers=a.workers)
    REPAIR = ppi._ms("2026-11-11 12:39:00")
    reach_all = []
    for l in allL:
        if l.get("fillStatus") == "filled":
            reach_all.append(l)
        elif l.get("fillStatus") == "unfilled":
            continue
        elif l.get("tape_verdict") == "filled_tape":
            reach_all.append(l)
    print(f"  settled {len(allL)}, reachable {len(reach_all)}")
    print(f"  {'band':<12} {'basis':<10} {'era':<10} {'legs':>4} {'cost':>8} {'pnl':>9} "
          f"{'ROI':>8} {'cluster CI':>17} {'inv%':>5}")
    for lo, hi in BANDS:
        for tag, pop in (("booked", allL), ("reachable", reach_all)):
            for era, f in (("pre-repair", lambda l: l["openedTs"] < REPAIR),
                           ("post-repair", lambda l: l["openedTs"] >= REPAIR)):
                sub = [l for l in pop if f(l) and (lo <= l["entryPrice"] < hi or
                                                   (hi >= 1.01 and l["entryPrice"] >= lo))]
                if len(sub) < 5:
                    continue
                n, ntl, p, r = agg(sub)
                inv = sum(1 for l in sub if l.get("inverted"))
                print(f"  {lo:.2f}-{hi:.2f}     {tag:<10} {era:<10} {n:>4} {ntl:>8.0f} {p:>+9.1f} "
                      f"{r:>+7.1f}% {cistr(sub):>17} {inv / n * 100:>4.0f}%")
    print("  read: if the pre-repair reachable rows carry the destruction and the post-repair rows do")
    print("  not, the baseline figure is the complement defect, not a property of favourites.")

    print("\n" + "=" * 94)
    print(f"self-checks: {len(FAIL)} FAIL" if FAIL else "self-checks: all PASS")
    print("=" * 94)
    return 1 if FAIL else 0


def selftest():
    print("self-test: true_pnl reprice identity, side mapping, arm monotonicity")
    leg = {"status": "resolved", "simulatedPositionSize": 10.0, "entryPrice": 0.25,
           "realizedPnl": 30.0, "fillStatus": None, "openedTs": 1_700_000_000_000,
           "tape_series": [(1_700_000_000, 0.30)]}
    assert abs(ppi.true_pnl(leg, 0.30) - (10 * (1.0 / 0.30 - 1))) < 1e-6
    snap = {"b": 0.28, "a": 0.30, "spread": 0.02}
    bid, ask, how = map_side(leg, snap)
    assert (round(bid, 4), round(ask, 4), how.endswith("own")) == (0.28, 0.30, True), (bid, ask, how)
    leg2 = dict(leg, tape_series=[(1_700_000_000, 0.70)])
    bid2, ask2, how2 = map_side(leg2, snap)
    assert abs(bid2 - 0.70) < 1e-9 and abs(ask2 - 0.72) < 1e-9 and how2.endswith("complement")
    leg3 = dict(leg, tape_series=[(1_700_000_000, 0.50)])
    assert map_side(leg3, snap)[2] == "ambiguous"
    print("  selftest OK")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
    else:
        sys.exit(main())
