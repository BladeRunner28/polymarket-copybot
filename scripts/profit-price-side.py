#!/usr/bin/env python3
"""
profit-price-side -- the ledger books the COMPLEMENT of the price paid on a small
class of legs, and that class carries the book.

WHY THIS FILE EXISTS
--------------------
Every sizing, band and ladder read in this book divides realised PnL by
`simulatedPositionSize` and trusts `entryPrice`, because the payoff identity
`pnl = ntl*(1-p)/p` on a win and `-ntl` on a loss holds exactly on settled legs.
That identity is only as good as `p`. This instrument asks the one question no
prior review asked: **is the price in the ledger the price of the token that was
actually bought?**

The test needs no external data. `ObservedTrade.walletEntryPrice` is what the
copied wallet paid for the SAME labelled outcome, and `PaperTrade.entryPrice` is
what we booked. For 2,102 finished regime legs the two agree to a median of
0.011. But on a subset the booked price is the wallet's price mirrored around
0.5 -- median |booked - (1-wallet)| = 0.007, p90 = 0.020. A mirror that tight is
arithmetic, not price movement.

That subset is 4.1% of legs and 56% of the book's PnL, because a favourite
booked at its complement is a fake longshot: a 0.88 shot booked at 0.12 pays
+633% instead of +14% when it wins, while a loss still costs the same -ntl.
So the mispricing is one-sided -- it inflates exactly the legs that win.

WHAT THIS FILE PRINTS
---------------------
  §1 classification ledger      (INVERTED / consistent / neither)
  §2 arithmetic proof           (how tight the mirror is, vs the control)
  §3 independent side check     (MarketSnapshot yes/no at trade time: does the
                                 booked price track the YES side?)
  §4 hit-rate test              (model-free: a bet booked at 0.25 that wins 60%
                                 of the time is not a 0.25 bet)
  §5 reprice                    (resolved inverted legs repriced at the wallet's
                                 own price; book totals both ways)
  §6 band table                 (booked vs repriced, deduped like the base
                                 instrument, so it is comparable to prior reads)
  §7 the C-200 ladder gate      (7 local calendar days, the dashboard's basis,
                                 booked vs repriced, phase verdicts)
  §8 concentration              (what the book looks like without the class)
  §9 the two open tests         (the drift fix's verify clause; yesterday's clip finding)
  §10 self-tests

COST BASIS: `simulatedPositionSize` is DOLLARS at risk, never shares. ROI =
PnL / simulatedPositionSize. `entryPrice` is used ONLY as the price in the
payoff identity -- and this file is about the cases where it is the wrong one.

REPRICE IS AN ESTIMATE, AND SAYS WHICH DIRECTION IT MOVES
The counterfactual entry is the copied wallet's own fill (`walletEntryPrice`),
which is the best available estimate of what the token cost; it is not our fill
and it carries no slippage. On an inverted leg the wallet's price is HIGHER than
the booked one (that is the definition -- booked is the complement), so the
reprice always LOWERS a winner's payoff and leaves a loser unchanged. The
repriced book total is therefore a lower bound on the correction, not a
symmetric adjustment.

READ-ONLY. `file:prisma/dev.db?mode=ro`. Writes no row, no RuleSet, no report.

Usage:
    python3 scripts/profit-price-side.py [--self-test] [--no-snapshot]
"""
import sqlite3
import statistics
import sys
import time
import datetime

DB = "prisma/dev.db"
MIN_RULE = 49                     # regime, as in every review since v49
TOL = 0.06                        # wallet-vs-booked agreement tolerance
MIRROR = 0.06                     # tolerance for "booked is the complement"
SEP = 0.10                        # minimum |b-w| for the complement test to mean anything
BANDS = [("0.0-0.2", 0.0, 0.2), ("0.2-0.4", 0.2, 0.4), ("0.4-0.6", 0.4, 0.6),
         ("0.6-0.8", 0.6, 0.8), ("0.8-1.0", 0.8, 1.0001)]
PHASES = [250, 500, 1000, 2000, 5000]


def band_of(p):
    for name, lo, hi in BANDS:
        if lo <= p < hi:
            return name
    return None


def con_ro():
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def load(con):
    """Every finished regime leg, with the wallet's own fill price."""
    q = """
        SELECT p.id, p.botId, p.marketId, p.outcome, p.entryPrice,
               p.simulatedPositionSize AS ntl, p.realizedPnl AS pnl, p.status,
               p.fillStatus AS fillStatus,
               p.openedAt, p.closedAt, p.resolvedAt,
               d.ruleSetVersion AS rv,
               o.walletAddress AS wallet, o.walletEntryPrice AS w,
               o.detectedPrice AS det, o.timestamp AS ots
        FROM PaperTrade p
        JOIN DecisionJournal d ON d.id = p.decisionJournalId
        JOIN ObservedTrade o  ON o.id = d.observedTradeId
        WHERE d.ruleSetVersion >= ? AND p.realizedPnl IS NOT NULL
              AND p.simulatedPositionSize > 0
    """
    rows = [dict(r) for r in con.execute(q, (MIN_RULE,))]
    for r in rows:
        r["cls"] = classify(r)
    return rows


def classify(r):
    """booked price vs the wallet's own fill price on the same labelled outcome."""
    b, w = r["entryPrice"], r["w"]
    if w is None:
        return "neither"
    d_same = abs(b - w)
    d_mirror = abs(b - (1.0 - w))
    if d_mirror + 0.01 < d_same and d_mirror < MIRROR and d_same > SEP:
        return "INVERTED"
    if d_same <= TOL:
        return "consistent"
    return "neither"


def repriced_pnl(r):
    """Booked PnL, except a resolved inverted leg pays at the wallet's price."""
    if r["cls"] != "INVERTED" or r["status"] != "resolved":
        return r["pnl"]
    # A leg the fill resolver booked at zero was never a position: repricing it to -ntl
    # would invent a stop-out that did not happen.
    if r.get("fillStatus") == "unfilled" or r["pnl"] == 0:
        return r["pnl"]
    w = r["w"]
    if not (0.0 < w < 1.0):
        return r["pnl"]
    return r["ntl"] * (((1.0 - w) / w) if r["pnl"] > 0 else -1.0)


def dedupe(rows):
    """First leg per (bot, wallet, market, outcome) -- the base instrument's rule."""
    seen, out = set(), []
    for r in sorted(rows, key=lambda r: r["openedAt"]):
        k = (r["botId"], r["wallet"], r["marketId"], r["outcome"])
        if k in seen:
            continue
        seen.add(k)
        out.append(r)
    return out


def summary(sel):
    n = len(sel)
    if n == 0:
        return dict(n=0, ntl=0.0, pnl=0.0, roi=0.0, hit=0.0, bpx=0.0, wpx=0.0,
                    rep=0.0, rep_roi=0.0)
    ntl = sum(r["ntl"] for r in sel)
    pnl = sum(r["pnl"] for r in sel)
    rep = sum(repriced_pnl(r) for r in sel)
    hit = sum(1 for r in sel if r["pnl"] > 0) / n
    bpx = sum(r["entryPrice"] for r in sel) / n
    ws = [r["w"] for r in sel if r["w"] is not None]
    return dict(n=n, ntl=ntl, pnl=pnl, roi=100 * pnl / ntl if ntl else 0.0,
                hit=100 * hit, bpx=bpx, wpx=sum(ws) / len(ws) if ws else 0.0,
                rep=rep, rep_roi=100 * rep / ntl if ntl else 0.0)


def hdr(t):
    print("\n" + "=" * 78)
    print(t)
    print("=" * 78)


# ------------------------------------------------------------------ main
def main():
    args = sys.argv[1:]
    self_test = "--self-test" in args
    do_snap = "--no-snapshot" not in args
    con = con_ro()
    rows = load(con)
    tot = summary(rows)
    inv = [r for r in rows if r["cls"] == "INVERTED"]

    hdr("§1 CLASSIFICATION LEDGER -- booked price vs the wallet's own fill")
    print("  INVERTED = booked is the wallet price mirrored about 0.5 (|b-(1-w)|<%.2f, |b-w|>%.2f)"
          % (MIRROR, SEP))
    print("  consistent = |b-w| <= %.2f ; neither = everything else\n" % TOL)
    print(f"  {'class':12} {'n':>5} {'ntl':>9} {'booked PnL':>11} {'ROI':>9} {'%ofPnL':>7} {'hit%':>6} {'bpx':>6} {'wpx':>6}")
    for k in ("INVERTED", "consistent", "neither"):
        s = summary([r for r in rows if r["cls"] == k])
        if s["n"] == 0:
            continue
        share = 100 * s["pnl"] / tot["pnl"] if tot["pnl"] else 0.0
        print(f"  {k:12} {s['n']:5} {s['ntl']:9.0f} {s['pnl']:+11.2f} {s['roi']:+8.1f}% "
              f"{share:6.1f}% {s['hit']:5.1f}% {s['bpx']:6.3f} {s['wpx']:6.3f}")
    print(f"  {'TOTAL':12} {tot['n']:5} {tot['ntl']:9.0f} {tot['pnl']:+11.2f} {tot['roi']:+8.1f}%")
    if inv:
        first = datetime.datetime.utcfromtimestamp(min(r["openedAt"] for r in inv) / 1000).date()
        last = datetime.datetime.utcfromtimestamp(max(r["openedAt"] for r in inv) / 1000).date()
        months = {}
        for r in inv:
            m = datetime.datetime.utcfromtimestamp(r["openedAt"] / 1000).strftime("%Y-%m")
            months[m] = months.get(m, 0) + 1
        wc = {}
        for r in inv:
            wc[r["wallet"]] = wc.get(r["wallet"], 0) + 1
        top = sorted(wc.items(), key=lambda kv: -kv[1])
        print(f"\n  class window: first opened {first}, last opened {last}")
        print("  by month: " + " · ".join(f"{k} {v}" for k, v in sorted(months.items())))
        print(f"  {len(wc)} wallets carry it; top 2 hold {top[0][1]+top[1][1] if len(top)>1 else top[0][1]}"
              f" of {len(inv)} legs ({top[0][0][:10]} {top[0][1]}, "
              f"{top[1][0][:10] if len(top)>1 else '-'} {top[1][1] if len(top)>1 else 0})")
        print("  a defect that starts on a date is a regression, not a property of the book.")

    hdr("§2 ARITHMETIC PROOF -- how tight is the mirror, and what does the control look like")
    cons = [r for r in rows if r["cls"] == "consistent"]
    for lab, s in (("INVERTED", inv), ("consistent", cons)):
        if not s:
            continue
        m = [abs(r["entryPrice"] - (1 - r["w"])) for r in s]
        same = [abs(r["entryPrice"] - r["w"]) for r in s]
        det = [abs(r["det"] - (1 - r["w"])) for r in s if r["det"] is not None]
        print(f"  {lab:11} n={len(s):4}  |b-(1-w)| med={statistics.median(m):.3f} "
              f"p90={sorted(m)[int(0.9 * (len(m) - 1))]:.3f}   "
              f"|b-w| med={statistics.median(same):.3f}"
              + (f"   |det-(1-w)| med={statistics.median(det):.3f}" if det else ""))
    print("  A mirror this tight on two independent fields (booked entry AND detected price)")
    print("  is arithmetic. Price movement does not produce complements to 2c.")

    hdr("§3 INDEPENDENT SIDE CHECK -- MarketSnapshot yes/no at the trade time")
    if not do_snap:
        print("  skipped (--no-snapshot)")
    else:
        yes = no = neither = miss = 0
        dy, dn = [], []
        for r in sorted(inv, key=lambda r: -abs(r["pnl"]))[:40]:
            sn = con.execute("""SELECT yesPrice, noPrice FROM MarketSnapshot
                                WHERE marketId=? AND collectedAt BETWEEN ? AND ?
                                ORDER BY abs(collectedAt-?) LIMIT 1""",
                             (r["marketId"], r["ots"] - 900000, r["ots"] + 900000, r["ots"])).fetchone()
            if not sn or sn[0] is None or sn[1] is None:
                miss += 1
                continue
            b = r["entryPrice"]
            dy.append(abs(b - sn[0]))
            dn.append(abs(r["w"] - sn[1]))
            if abs(b - sn[0]) < 0.04 and abs(b - sn[1]) >= 0.04:
                yes += 1
            elif abs(b - sn[1]) < 0.04 and abs(b - sn[0]) >= 0.04:
                no += 1
            else:
                neither += 1
        print(f"  top-40 inverted legs by |PnL|: booked tracks the YES side {yes}, the NO side {no},"
              f" neither {neither}, no snapshot {miss}")
        if dy:
            print(f"  median |booked - snapshot yes| = {statistics.median(dy):.3f};"
                  f" median |wallet - snapshot no| = {statistics.median(dn):.3f}")
            print("  i.e. the market's quote for the outcome's own token agrees with the WALLET's fill")
            print("  price, and the ledger's price sits on the sibling quote. (Not independent of §2:")
            print("  yes+no=1 makes 'booked = 1-wallet' imply 'booked = yes' up to the spread. What")
            print("  this section adds is that the MARKET, not just the wallet, is on the other side.)")
        print("  read: where the booked price is the YES side on a NO-side leg, the ledger price is")
        print("  the sibling token's -- i.e. the complement. 'neither' rows are stale mid-moves.")

    hdr("§4 HIT-RATE TEST -- model-free, no external data")
    print("  For a BUY at p the break-even hit rate IS p. A class that hits far above its")
    print("  booked price is either a miracle or booked at the wrong price.\n")
    print(f"  {'class':12} {'n':>5} {'hit%':>6} {'bookedPx':>9} {'walletPx':>9} {'vs booked':>10} {'vs wallet':>10}")
    for k in ("INVERTED", "consistent", "neither"):
        s = summary([r for r in rows if r["cls"] == k])
        if not s["n"]:
            continue
        print(f"  {k:12} {s['n']:5} {s['hit']:5.1f}% {s['bpx']:9.3f} {s['wpx']:9.3f} "
              f"{s['hit']-100*s['bpx']:+9.1f}pp {s['hit']-100*s['wpx']:+9.1f}pp")
    q = sorted(inv, key=lambda r: r["w"])
    if len(q) >= 10:
        print("\n  quintiles of wallet price inside INVERTED (booked price falls as wallet price rises):")
        for i in range(5):
            part = q[i * len(q) // 5:(i + 1) * len(q) // 5]
            if not part:
                continue
            hit = 100 * sum(1 for r in part if r["pnl"] > 0) / len(part)
            bpx = sum(r["entryPrice"] for r in part) / len(part)
            print(f"    w {part[0]['w']:.2f}-{part[-1]['w']:.2f} n={len(part):3} "
                  f"hit={hit:5.1f}%  bookedPx={bpx:.3f}  -> edge vs booked {hit-100*bpx:+6.1f}pp")

    hdr("§5 REPRICE -- inverted resolved legs pay at the wallet's price")
    print("  (winners only: a loss costs -ntl on either basis)\n")
    print(f"  {'class':12} {'n':>5} {'ntl':>8} {'booked':>10} {'repriced':>10} {'bookedROI':>10} {'repROI':>8}")
    for k in ("INVERTED", "consistent", "neither"):
        s = summary([r for r in rows if r["cls"] == k])
        if not s["n"]:
            continue
        print(f"  {k:12} {s['n']:5} {s['ntl']:8.0f} {s['pnl']:+10.2f} {s['rep']:+10.2f} "
              f"{s['roi']:+9.1f}% {s['rep_roi']:+7.1f}%")
    print(f"\n  BOOK: booked {tot['pnl']:+.2f} ({tot['roi']:+.1f}%) -> repriced {tot['rep']:+.2f} "
          f"({tot['rep_roi']:+.1f}%)  on ${tot['ntl']:,.0f} of notional")
    print(f"  correction {tot['rep']-tot['pnl']:+.2f} = {100*(tot['rep']-tot['pnl'])/tot['pnl']:+.0f}% of the booked figure")
    for b in ("BANKROLL_200", "STANDARD"):
        s = summary([r for r in rows if r["botId"] == b])
        if not s["n"]:
            continue
        print(f"    {b:13} booked {s['pnl']:+9.2f} ({s['roi']:+6.1f}%) -> repriced {s['rep']:+9.2f} ({s['rep_roi']:+6.1f}%)")

    hdr("§6 BAND TABLE -- booked vs repriced, deduped (comparable to profit-band-report)")
    dd = dedupe(rows)
    print(f"  deduped legs: {len(dd)} of {len(rows)} (first leg per bot|wallet|market|outcome)\n")
    print(f"  {'band':8} {'n':>4} {'ntl':>7} {'booked':>9} {'ROI':>8} {'n_inv':>5} {'pnl_inv':>8} {'repriced':>9} {'ROI':>8}")
    for name, lo, hi in BANDS:
        s = [r for r in dd if lo <= r["entryPrice"] < hi]
        if not s:
            continue
        ntl = sum(r["ntl"] for r in s)
        p = sum(r["pnl"] for r in s)
        rep = sum(repriced_pnl(r) for r in s)
        i = [r for r in s if r["cls"] == "INVERTED"]
        print(f"  {name:8} {len(s):4} {ntl:7.0f} {p:+9.2f} {100*p/ntl:+7.1f}% {len(i):5} "
              f"{sum(r['pnl'] for r in i):+8.2f} {rep:+9.2f} {100*rep/ntl:+7.1f}%")
    print("  NOTE: repriced rows stay in their BOOKED band -- the bucket is where the ledger")
    print("  put them. Moving an inverted leg to its true-price band is part of the fix, not")
    print("  of this read, so the band ROIs above are conservative for the cheap band.")

    hdr("§7 THE C-200 LADDER GATE -- 7 local calendar days, the dashboard's basis")
    today = datetime.datetime.fromtimestamp(time.time()).replace(hour=0, minute=0, second=0, microsecond=0)
    start = today - datetime.timedelta(days=6)
    cut = start.timestamp() * 1000
    raw = [r for r in rows if r["botId"] == "BANKROLL_200"
           and (r["closedAt"] or r["resolvedAt"]) is not None
           and (r["closedAt"] or r["resolvedAt"]) >= cut]
    s = summary(raw)
    print(f"  window {start.date()} .. {today.date()} (T+0 included, as the dashboard does)")
    print(f"  legs {s['n']}  booked {s['pnl']:+.2f}  repriced {s['rep']:+.2f}")
    i = [r for r in raw if r["cls"] == "INVERTED"]
    si = summary(i)
    print(f"  of which INVERTED: n={si['n']} booked {si['pnl']:+.2f} ({100*si['pnl']/s['pnl'] if s['pnl'] else 0:.0f}% of the gate sum)"
          f" -> repriced {si['rep']:+.2f}")
    print("\n  phase verdicts (advance needs SUM >= target x 7):")
    for t in PHASES:
        need = t * 7
        print(f"    ${t:5}/day need ${need:6} : booked {'PASS' if s['pnl'] >= need else 'fail'}"
              f"   repriced {'PASS' if s['rep'] >= need else 'fail'}")

    hdr("§8 CONCENTRATION -- what carries the book, and what is left without it")
    for k in (1, 3, 5, 10):
        ex = sorted(rows, key=lambda r: -r["pnl"])[k:]
        s2 = summary(ex)
        print(f"  ex-top{k:<2} booked n={s2['n']:4} pnl={s2['pnl']:+9.2f} roi={s2['roi']:+6.1f}%"
              f"   repriced pnl={s2['rep']:+9.2f} roi={s2['rep_roi']:+6.1f}%")
    print("\n  largest INVERTED legs:")
    print(f"  {'lane':13} {'market':44} {'booked':>6} {'wallet':>6} {'sz':>6} {'pnl':>8} {'status':>8}")
    for r in sorted(inv, key=lambda r: -abs(r["pnl"]))[:12]:
        print(f"  {r['botId']:13} {r['marketId'][:44]:44} {r['entryPrice']:6.3f} {r['w']:6.3f} "
              f"{r['ntl']:6.1f} {r['pnl']:+8.2f} {r['status']:>8}")

    hdr("§9 WHAT THIS DOES TO THE TWO OPEN TESTS")
    # (a) The drift fix (Lane A, approved 2026-10-26) pre-registered: "the favourable-admitted
    #     cohort settles above +20%; refuted if it settles below +5% on >=150 legs". The cohort
    #     it admits is the one this file is about, so it must be re-read net of the class.
    cut = datetime.datetime(2026, 10, 26).timestamp() * 1000
    post = [r for r in rows if r["openedAt"] >= cut and r["det"] is not None]
    fav = [r for r in post if (r["w"] - r["det"]) > 0.05]
    small = [r for r in post if 0.004 < (r["w"] - r["det"]) <= 0.05]
    adv = [r for r in post if (r["det"] - r["w"]) > 0.004]
    print("  post-2026-10-26 settled regime legs: %d" % len(post))
    for lab, s in (("favourable >5c", fav), ("favourable 0.4-5c", small), ("adverse >0.4c", adv)):
        if not s:
            continue
        d = summary(s)
        i = [r for r in s if r["cls"] == "INVERTED"]
        ex = summary([r for r in s if r["cls"] != "INVERTED"])
        print(f"    {lab:16} n={d['n']:4} ntl={d['ntl']:7.0f} booked={d['pnl']:+8.2f} ({d['roi']:+6.1f}%)"
              f" inv={len(i):3} repriced={d['rep']:+8.2f} ({d['rep_roi']:+6.1f}%)"
              f" | ex-inv n={ex['n']:3} {ex['pnl']:+8.2f} ({ex['roi']:+6.1f}%)")
    if fav:
        fs = summary(fav)
        fe = summary([r for r in fav if r["cls"] != "INVERTED"])
        print(f"  read: {100*sum(1 for r in fav if r['cls']=='INVERTED')/len(fav):.0f}% of the favourable-drift"
              f" cohort is this class; ex-inverted it books {fe['roi']:+.1f}% instead of {fs['roi']:+.1f}%.")
    if adv:
        print(f"  the adverse branch the fix keeps blocking books {summary(adv)['roi']:+.1f}% -- the fix")
        print("  is still right in principle; its scoreboard is not yet evidence of edge.")

    # (b) Yesterday's within-wallet clip finding: the biggest clips are where the class lives.
    print("\n  clip tiers, deduped (yesterday's marginal-dollar population):")
    big = [r for r in dd if r["ntl"] >= 18]
    for lo, hi, lab in ((18, 1e9, "clip >= $18"), (5, 18, "clip $5-18"), (0, 5, "clip < $5")):
        s = [r for r in dd if lo <= r["ntl"] < hi]
        if not s:
            continue
        d = summary(s)
        i = [r for r in s if r["cls"] == "INVERTED"]
        ex = summary([r for r in s if r["cls"] != "INVERTED"])
        print(f"    {lab:12} n={d['n']:4} ntl={d['ntl']:7.0f} booked={d['roi']:+6.1f}% "
              f"INV={len(i):3} ({100*len(i)/d['n']:4.1f}% of legs) ex-INV={ex['roi']:+6.1f}%")
    if big:
        bi = [r for r in big if r["cls"] == "INVERTED"]
        bp = sum(r["pnl"] for r in big)
        print(f"    inverted legs hold {100*sum(r['pnl'] for r in bi)/bp if bp else 0:.0f}% of the big-clip PnL;")
        print("    a clip effect measured on this population is partly a price-side effect, and its")
        print("    sign is not safe until the class is excluded.")

    hdr("§10 SELF-TESTS")
    fails = 0
    # (a) payoff identity holds on the BOOKED basis for resolved legs -- this file is about
    #     the price being wrong, not about the identity being broken. A leg the fill resolver
    #     booked at ZERO (fillStatus='unfilled') is not a position: the identity cannot apply,
    #     and counting it as a failure is how a working resolver gets read as a broken ledger.
    res = [r for r in rows if r["status"] == "resolved"]
    zeroed = [r for r in res if r.get("fillStatus") == "unfilled"]
    bad = 0
    checked = 0
    for r in res:
        if r.get("fillStatus") == "unfilled":
            continue
        p = r["entryPrice"]
        if not (0 < p < 1):
            continue
        checked += 1
        expect = r["ntl"] * ((1 - p) / p if r["pnl"] > 0 else -1)
        if abs(expect - r["pnl"]) > 0.02 + 1e-3 * r["ntl"]:
            bad += 1
    print(f"  payoff identity on resolved legs: {checked - bad}/{checked} exact"
          f"  ({len(zeroed)} booked at zero by the fill resolver, excluded)")
    fails += 1 if bad else 0
    # (b) partition
    parts = sum(1 for r in rows if r["cls"] in ("INVERTED", "consistent", "neither"))
    print(f"  classification partitions the population: {parts}/{len(rows)}")
    fails += 1 if parts != len(rows) else 0
    # (c) reprice identity on a synthetic inverted winner: buy at booked 0.20, true 0.80
    synthetic_booked = (1 - 0.20) / 0.20 * 100.0
    fake = {"cls": "INVERTED", "status": "resolved", "ntl": 100.0,
            "pnl": synthetic_booked, "w": 0.80}
    got = float(repriced_pnl(fake))
    print(f"  reprice synthetic: booked {synthetic_booked:+.2f} (p=0.20) -> wallet p=0.80 gives "
          f"{got:+.2f} (expect +25.00)")
    fails += 1 if abs(got - 25.0) > 1e-6 else 0
    # (d) no zero-stake leg can enter an ROI denominator
    zero = [r for r in rows if r["ntl"] <= 0]
    print(f"  zero-stake legs in population: {len(zero)}")
    fails += 1 if zero else 0
    print(f"\n  {'SELF-TEST PASS' if not fails else 'SELF-TEST FAIL (%d)' % fails}")
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
