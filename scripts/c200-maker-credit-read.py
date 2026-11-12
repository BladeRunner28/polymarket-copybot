#!/usr/bin/env python3
"""Read-only: value the C-200 maker credit on the live book, pre- and post-cutover.

Answers "does the fixed 2c maker fill stay in the C-200 model?" from the book.
Writes NOTHING (sqlite opened immutable=1).

Three PnL bases are printed because the lane has changed booking model twice:
  raw        - PaperTrade.realizedPnl as stored (p(fill)=1 on every leg)
  fill-aware - src/lib/paper.ts bookedPnl(): fillStatus='unfilled' -> 0 (live
               DEFAULT since 2026-10-28, FILL_AWARE_BOOKING=0 restores raw)

Counterfactual convention is the repo's (src/lib/copy-cost.ts): hold the EXIT
price and the stake fixed, re-price the ENTRY. exit = e*(1+p/S); entry e2 gives
p2 = S*(exit-e2)/e2. Exact at the total-loss boundary (exit=0 -> p2=-S).

Entry model per era:
  pre  2026-10-10 03:07  entry = max(0.01, intent - 0.02)   (flat, modelled)
  post                   entry = max(0.01, intent - 0.02*band_weight(intent))
So intent is reconstructed era-aware, and cross-checked on BUY legs against the
stamped PaperTrade.intentPrice (fill-intent shadow).
"""
import os
import sqlite3
import sys

DB = os.environ.get("COPYBOT_DB", os.path.expanduser("~/polymarket-copybot/prisma/dev.db"))

BANDS = [(0.00, 0.10, 0.028), (0.10, 0.20, 0.084), (0.20, 0.40, 0.229),
         (0.40, 0.60, 0.188), (0.60, 0.80, 0.185), (0.80, 999.0, 0.185)]
MODELLED = 0.02
CUTOVER_MS = 1791606424000   # 2026-10-10T03:07:04-05:00 (binary rebuilt / kickstarted)
MAKER_START_MS = 1787875200000  # 2026-08-28T00:00Z (Phase 6 maker path live)
FLOOR = 0.01


def band_weight(p):
    for lo, hi, w in BANDS:
        if lo <= p < hi:
            return w
    return BANDS[-1][2]


def solve_intent(entry, measured):
    """Invert the booking rule; measured=False -> flat 2c (era before cutover)."""
    p = entry + (MODELLED * band_weight(entry) if measured else MODELLED)
    for _ in range(10):
        c = MODELLED * band_weight(p) if measured else MODELLED
        nxt = max(FLOOR + c, entry + c)  # entry was clamped at the floor at booking
        if abs(nxt - p) < 1e-12:
            return p
        p = nxt
    return p


def pnl_at(entry, size, pnl, entry2):
    if entry <= 0 or entry2 <= 0:
        return None
    exit_price = entry * (1.0 + pnl / size)
    return size * (exit_price - entry2) / entry2


def booked_pnl(fill_status, pnl):
    return 0.0 if fill_status == "unfilled" else pnl


def main():
    con = sqlite3.connect("file:%s?immutable=1" % DB, uri=True)
    con.row_factory = sqlite3.Row
    rows = con.execute(
        """
        SELECT entryPrice AS entry, simulatedPositionSize AS size,
               realizedPnl AS pnl, openedAt AS openedMs, intentPrice AS stamp,
               fillStatus AS fill,
               CAST(COALESCE(closedAt, resolvedAt) AS INTEGER) AS settledMs
        FROM PaperTrade
        WHERE botId='BANKROLL_200' AND isDemo=0
          AND status IN ('closed','resolved')
          AND COALESCE(closedAt, resolvedAt) IS NOT NULL
          AND realizedPnl IS NOT NULL AND openedAt >= ?
        """,
        (MAKER_START_MS,),
    ).fetchall()

    out = {"pre": [], "post": []}
    for r in rows:
        e, S, p = r["entry"], r["size"], r["pnl"]
        if not e or not S or e <= 0 or S <= 0:
            continue
        post = r["openedMs"] >= CUTOVER_MS
        intent = solve_intent(e, measured=post)
        mod_entry = max(FLOOR, intent - MODELLED)
        out["post" if post else "pre"].append({
            "entry": e, "intent": intent, "size": S, "pnl": p,
            "bpnl": booked_pnl(r["fill"], p), "fill": r["fill"], "stamp": r["stamp"],
            "settledMs": r["settledMs"],
            "band": [lo for lo, hi, _ in BANDS if lo <= intent < hi][0],
            "credit": p - pnl_at(e, S, p, e + (intent - e)),
            "p_mod": pnl_at(e, S, p, mod_entry),
            "p_none": pnl_at(e, S, p, intent),
        })

    def summarize(name, legs):
        n = len(legs)
        if not n:
            print(f"\n{name}: no legs")
            return
        raw = sum(x["pnl"] for x in legs)
        b = sum(x["bpnl"] for x in legs)
        size = sum(x["size"] for x in legs)
        mod_raw = sum(x["p_mod"] for x in legs)
        mod_b = sum(booked_pnl(x["fill"], x["p_mod"]) for x in legs)
        none_b = sum(booked_pnl(x["fill"], x["p_none"]) for x in legs)
        cred = sum(x["credit"] for x in legs)
        fills = {}
        for x in legs:
            fills[x["fill"] or "unresolved"] = fills.get(x["fill"] or "unresolved", 0) + 1
        stamp = [x for x in legs if x["stamp"] is not None and 0 < x["entry"] < x["stamp"] < x["entry"] + 0.031]
        err = max((abs(x["stamp"] - x["intent"]) for x in stamp), default=None)
        print(f"\n=== {name}: n={n}  staked=${size:,.2f}  fills={fills} ===")
        print(f"  realizedPnl raw       ${raw:9,.2f}   $/trade {raw/n:7,.3f}")
        print(f"  realizedPnl fill-aware${b:9,.2f}   $/trade {b/n:7,.3f}   (unfilled -> 0, live default)")
        print(f"  booked credit (raw)   ${cred:9,.2f}   = {100*cred/raw if raw else float('nan'):6.1f}% of raw PnL")
        print(f"  flat-2c counterfactual, fill-aware: ${mod_b:9,.2f}  ({mod_b-b:+,.2f} = {100*(mod_b-b)/b if b else float('nan'):+.1f}%)")
        print(f"  no-credit counterfactual, fill-aware: ${none_b:9,.2f}  ({none_b-b:+,.2f})")
        if err is not None:
            print(f"  intent reconstruction vs stamped intentPrice: n={len(stamp)} BUY legs, max |err|={err:.4f}")
        print("    band      legs  staked$   rawPnL$  fillPnL$  credit$  2c-on-fill$")
        for lo, hi, _ in BANDS:
            g = [x for x in legs if x["band"] == lo]
            if not g:
                continue
            gb = sum(x["bpnl"] for x in g)
            gm = sum(booked_pnl(x["fill"], x["p_mod"]) for x in g)
            print(f"    {lo:.2f}-{hi if hi < 999 else 1.0:.2f}  {len(g):5d} "
                  f"{sum(x['size'] for x in g):9,.2f} {sum(x['pnl'] for x in g):9,.2f} "
                  f"{gb:9,.2f} {sum(x['credit'] for x in g):8,.2f} {gm-gb:+9,.2f}")

    summarize("PRE-cutover  (flat 2c live)", out["pre"])
    summarize("POST-cutover (measured bands live)", out["post"])

    # the conditional-fill question: on legs the resolver says FILLED, what would
    # the full 2c book? (reachability observed -> credit no longer a probability)
    filled = [x for x in out["post"] if x["fill"] == "filled"]
    if filled:
        b = sum(x["bpnl"] for x in filled)
        m = sum(booked_pnl(x["fill"], x["p_mod"]) for x in filled)
        print(f"\nPOST cutover, fillStatus='filled' only: n={len(filled)}  "
              f"as booked ${b:,.2f}  full-2c ${m:,.2f}  delta ${m-b:+,.2f}")

    # --- the EOD's copy-cost counterfactual: what src/lib/copy-cost.ts prices ---
    # It re-prices every maker-era leg at entry+0.02, which is only the model that
    # was live BEFORE the cutover. Post-cutover entry = intent - c_m, so the
    # modelled entry is entry + (0.02 - c_m), not entry + 0.02.
    post = out["post"]
    repo_credit = sum(MODELLED * (x["pnl"] + x["size"]) / (x["entry"] + MODELLED) for x in post)
    true_credit = sum(x["p_mod"] - x["pnl"] for x in post)
    print(f"\ncopy-cost.ts counterfactual on the POST-cutover book (settled, raw basis):")
    print(f"  as coded (entry+2c on every leg)   ${repo_credit:,.2f}")
    print(f"  era-correct (entry + (2c - c_m))   ${true_credit:,.2f}"
          f"   overstatement ${repo_credit-true_credit:+,.2f}")

    # --- ladder impact: v2 rolling-7d-SUM advance basis ---
    import datetime as _dt
    if post:
        last = max(x["settledMs"] for x in post)
        start = last - 7 * 86400000
        w = [x for x in post if x["settledMs"] > start]
        wb = sum(x["bpnl"] for x in w)
        wf = sum(booked_pnl(x["fill"], x["p_mod"]) for x in w)
        ws = sum(x["size"] for x in w)
        print(f"\nv2 ladder basis, last 7 settled days "
              f"({_dt.datetime.utcfromtimestamp(start/1000):%Y-%m-%d}.."
              f"{_dt.datetime.utcfromtimestamp(last/1000):%Y-%m-%d}), "
              f"n={len(w)} legs staked ${ws:,.2f}:")
        print(f"  booked fill-aware  ${wb:9,.2f}  -> {wb/7:8,.2f}/day")
        print(f"  with the flat 2c   ${wf:9,.2f}  -> {wf/7:8,.2f}/day   (delta {wf-wb:+,.2f})")
        print("  rung 1,000/day clears at >= $7,000 over 7 settled days")


if __name__ == "__main__":
    sys.exit(main())
