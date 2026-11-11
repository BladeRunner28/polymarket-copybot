#!/usr/bin/env python3
"""
profit-postfix-integrity -- the price-side fix repaired the WRITE path. Did it
repair the LEDGER, and does any scoreboard still print the number the fix
disproved?

WHY THIS FILE EXISTS
--------------------
2026-11-09 shipped src/lib/outcome-price.ts (fbf9073): score-trades, update-pnl,
monitor-trades and exit-recovery now price a leg by the venue's own token label.
That is a WRITE-path repair. The 93 legs already in the book still carry the
complement of the price paid, and every downstream reader -- Dashboard, DailyReport,
PnlSnapshot, capital-data, the C-200 ladder gate -- reads those ROWS, not the parser.

Two consequences that no prior instrument measures:

  (1) THE OPEN BOOK IS NOW INTERNALLY INCONSISTENT. update-pnl marks a leg at the
      correct token price while its entryPrice is still the sibling's. unrealizedPnl
      = ntl*(mark/entry - 1) therefore divides a right price by a wrong one and pays
      a fake gain on every open inverted leg, hourly, until those legs resolve.
      This is NEW: before the fix both sides were wrong together, so the ratio was
      roughly right. A partial fix can be worse than no fix.

  (2) THE BAND MAP IS STILL BUCKETED BY A PRICE THAT NEVER EXISTED. profit-price-side
      §6 says so explicitly ("repriced rows stay in their BOOKED band"). The 36
      inverted legs sitting in 0.0-0.2 are 0.8-0.9 favourites at their true price.
      Any allocation read -- "the cheap band pays +39.8%, fund it" -- is reading the
      booked bucket. This file re-bands by the price actually paid.

BASIS (identical to profit-band-report.py by contract)
  cost basis = simulatedPositionSize = DOLLARS at risk, NOT shares.
  dedupe     = first leg per bot|wallet|market|outcome.
  CI         = market-clustered bootstrap (resample markets, 2,000 draws).
  true price = ObservedTrade.walletEntryPrice when the booked price is its
               complement (the INVERTED class); booked entryPrice otherwise.
               Where no ObservedTrade matches, the leg is TRUE_UNKNOWN and is
               reported separately rather than assumed correct.

USAGE
  python3 scripts/profit-postfix-integrity.py          # all sections
  python3 scripts/profit-postfix-integrity.py --only=A,B
"""
import random
import sqlite3
import sys
import time

DB = "prisma/dev.db"
FIX_EPOCH = "2026-11-09 09:15:16"      # fbf9073 commit time, local (CST)
REGIME = "2026-10-26 00:00:00"         # drift gate went directional
BANDS = [(0.0, 0.2), (0.2, 0.4), (0.4, 0.6), (0.6, 0.8), (0.8, 1.0001)]
MIRROR_TOL = 0.06
SEP_TOL = 0.10


def band_name(lo, hi):
    return "0.8-1.0" if hi > 1 else f"{lo:.1f}-{hi:.1f}"


def band_of(p):
    for lo, hi in BANDS:
        if lo <= p < hi:
            return band_name(lo, hi)
    return None


def con():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    return c


def load_legs(days=None, min_rule=None):
    """Finished + open non-demo legs with the wallet's own fill price.

    The fill is taken by PROVENANCE (`DecisionJournal.observedTradeId` -> the exact
    ObservedTrade that triggered the copy), not by nearest timestamp. A nearest-
    timestamp match pairs a leg with whatever else the wallet did in that market
    and invents mirror pairs; the first draft of this file did exactly that and
    classified 54 July/August legs as INVERTED that the committed provenance join
    (scripts/profit-price-side.py) does not. Same join as that instrument.
    """
    c = con()
    since = int((time.time() - days * 86400) * 1000) if days else 0
    q = """SELECT p.id, p.botId, p.walletAddress, p.marketId, p.outcome,
                  p.entryPrice, p.currentPrice, p.simulatedPositionSize,
                  p.realizedPnl, p.unrealizedPnl, p.status, p.openedAt,
                  p.closedAt, p.resolvedAt, p.isDemo, p.fillStatus,
                  d.ruleSetVersion AS rv,
                  o.walletEntryPrice AS w, o.timestamp AS ots
             FROM PaperTrade p
             JOIN DecisionJournal d ON d.id = p.decisionJournalId
             LEFT JOIN ObservedTrade o ON o.id = d.observedTradeId
            WHERE p.isDemo = 0 AND p.openedAt >= ?"""
    rows = c.execute(q, (since,)).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        if min_rule is not None and (d["rv"] is None or d["rv"] < min_rule):
            continue
        ts = _ms(d["openedAt"])
        b, w = d["entryPrice"], d["w"]
        inverted = (
            w is not None
            and abs(b - (1.0 - w)) + 0.01 < abs(b - w)
            and abs(b - (1.0 - w)) <= MIRROR_TOL
            and abs(b - w) > SEP_TOL
            and 0.0 < w < 1.0
        )
        d["inverted"] = inverted
        d["class"] = "INVERTED" if inverted else ("consistent" if w is not None else "no_fill")
        # THE PRICE WE ACTUALLY PAID.
        # Only an inverted leg is repriced (its booked price is the sibling token's).
        # A "consistent" leg is NOT re-priced at the wallet's fill even when that fill is
        # 1-6c better: |b-w| <= 0.06 is spread and one block of latency, and claiming the
        # wallet's price would credit us with their queue position. Repricing those legs
        # at w inflated the cheap band's ROI by 40x on the /p arithmetic (a 0.14 fill
        # against a 0.20 book is +43% on the same exit) -- caught on the first run and
        # fixed here rather than quoted.
        d["trueP"] = w if inverted else b
        d["trueP_known"] = inverted or (w is not None and abs(b - w) <= MIRROR_TOL)
        d["openedTs"] = ts
        out.append(d)
    return out


def dedupe(legs):
    seen, out = set(), []
    for l in sorted(legs, key=lambda x: x["openedAt"]):
        k = (l["botId"], l["walletAddress"], l["marketId"], l["outcome"])
        if k in seen:
            continue
        seen.add(k)
        out.append(l)
    return out


def true_pnl(l, p):
    """PnL if the SAME exit had been entered at price p, with the same DOLLARS AT RISK.

    cost basis = dollars at risk, so a fixed $ntl at price p buys ntl/p shares:
        pnl = ntl * (exit/p - 1)
    The exit price is basis-independent and is implied by the booked PnL
    (exit = entry*(1 + booked/ntl)). On a resolution exit of 1.0 or 0.0 this
    reduces to the (1-p)/p / -1 payoff identity the whole book rests on.
    """
    if l["status"] == "open":
        return None
    ntl = l["simulatedPositionSize"]
    b = l["entryPrice"]
    booked = l["realizedPnl"]
    if ntl is None or ntl <= 0 or b is None or b <= 0 or booked is None:
        return booked or 0.0
    if booked == 0 and l.get("fillStatus") == "unfilled":
        return 0.0
    exit_price = b * (1.0 + booked / ntl)
    if p is None or p <= 0:
        return booked
    return ntl * (exit_price / p - 1.0)


def cluster_ci(legs, pnl_of, n=2000, seed=7):
    """Market-clustered bootstrap CI on ROI (pnl / notional)."""
    by = {}
    for l in legs:
        v = pnl_of(l)
        if v is None:
            continue
        g = by.setdefault(l["marketId"], [0.0, 0.0])
        g[0] += v
        g[1] += l["simulatedPositionSize"]
    ks = list(by)
    if len(ks) < 2:
        return (None, None)
    rnd = random.Random(seed)
    out = []
    for _ in range(n):
        sp = sn = 0.0
        for _ in range(len(ks)):
            p_, n_ = by[ks[rnd.randrange(len(ks))]]
            sp += p_
            sn += n_
        if sn > 0:
            out.append(sp / sn * 100.0)
    out.sort()
    return (out[int(0.025 * len(out))], out[int(0.975 * len(out)) - 1])


def market_day(ms):
    return time.strftime("%Y-%m-%d", time.localtime(ms / 1000.0))


def money(v):
    return f"{v:+,.2f}"


def pct(v):
    return f"{v:+.1f}%"


def sec_integrity(legs, ded):
    print("=" * 78)
    print("A. THE LEDGER AFTER THE WRITE-PATH FIX -- what is still unrepaired")
    print("=" * 78)
    fin = [l for l in ded if l["status"] != "open"]
    opn = [l for l in ded if l["status"] == "open"]
    inv_fin = [l for l in fin if l["inverted"]]
    inv_opn = [l for l in opn if l["inverted"]]
    print(f"  finished legs {len(fin):,}   open legs {len(opn):,}   (deduped)")
    print(f"  INVERTED among finished: {len(inv_fin):>4}  notional ${sum(l['simulatedPositionSize'] for l in inv_fin):,.0f}")
    if inv_fin:
        bi = sum(l["realizedPnl"] or 0 for l in inv_fin)
        ti = sum(true_pnl(l, l["trueP"]) or 0 for l in inv_fin)
        print(f"    booked {money(bi)}  ->  true {money(ti)}   (delta {money(ti - bi)})")
        fin_all = [l for l in ded if l["status"] != "open"]
        ba = sum(l["realizedPnl"] or 0 for l in fin_all)
        print(f"    that class holds {bi / ba * 100:.0f}% of the book's booked profit "
              f"(${bi:,.0f} of ${ba:,.0f})")
    print(f"  INVERTED among open    : {len(inv_opn):>4}  notional ${sum(l['simulatedPositionSize'] for l in inv_opn):,.0f}")
    if inv_opn:
        fake = 0.0
        for l in inv_opn:
            m = l["currentPrice"]
            if m and l["entryPrice"] > 0:
                real = l["simulatedPositionSize"] * (m / l["entryPrice"] - 1.0)
                right = l["simulatedPositionSize"] * (
                    (m / l["trueP"] - 1.0) if l["trueP"] > 0 else 0.0
                )
                fake += real - right
        print(f"  open inverted legs: unrealized booked against a WRONG entry vs the")
        print(f"  same marks against the true price -> overstated by ${fake:,.2f} TODAY,")
        print(f"  and it grows with the mark until each leg resolves.")
        for l in sorted(inv_opn, key=lambda x: -x["simulatedPositionSize"])[:6]:
            print(f"    {l['botId']:<12} {l['marketId'][:44]:<44} b={l['entryPrice']:.3f} "
                  f"true={l['trueP']:.3f} mark={l['currentPrice']:.3f} "
                  f"ntl={l['simulatedPositionSize']:.1f}")
    # post-fix regression: any inverted leg opened AFTER the fix?
    fix_ts = _ms(FIX_EPOCH)
    post = [l for l in ded if l["openedTs"] > fix_ts]
    post_inv = [l for l in post if l["inverted"]]
    print(f"\n  ACCEPTANCE (fix landed {FIX_EPOCH}): legs opened after the fix {len(post)},"
          f" of which INVERTED {len(post_inv)}, settled {sum(1 for l in post if l['status'] != 'open')}")
    if post_inv:
        for l in post_inv[:10]:
            print(f"    REGRESSION {l['botId']:<12} {l['marketId'][:40]:<40} "
                  f"{time.strftime('%Y-%m-%d %H:%M', time.localtime(l['openedTs']/1000))} "
                  f"b={l['entryPrice']:.3f} w={(l['w'] or 0):.3f}")
    else:
        print("    -> INVERTED n=0 on the post-fix cohort. The write path is holding.")
    # when did the class actually open?
    hist = {}
    for l in inv_fin:
        hist[time.strftime("%Y-%m", time.localtime(l["openedTs"] / 1000))] = \
            hist.get(time.strftime("%Y-%m", time.localtime(l["openedTs"] / 1000)), 0) + 1
    print("  inverted-by-open-month: " + "  ".join(f"{k} {v}" for k, v in sorted(hist.items())))
    return inv_fin, inv_opn


def sec_scoreboard(legs, ded):
    print()
    print("=" * 78)
    print("B. SCOREBOARD vs TRUE BASIS -- what the dashboard still reports")
    print("=" * 78)
    fin = [l for l in ded if l["status"] != "open"]

    def booked(l):
        return l["realizedPnl"] or 0.0

    def true(l):
        return true_pnl(l, l["trueP"])

    for lane in ("STANDARD", "BANKROLL_200"):
        f = [l for l in fin if l["botId"] == lane]
        if not f:
            continue
        ntl = sum(l["simulatedPositionSize"] for l in f)
        b = sum(booked(l) for l in f)
        t = sum(true(l) or 0.0 for l in f)
        print(f"  {lane:<13} n={len(f):>4} ntl=${ntl:>9,.0f}  booked {money(b):>10} "
              f"({pct(b / ntl * 100):>7})  true {money(t):>10} ({pct(t / ntl * 100):>7})")
    ntl = sum(l["simulatedPositionSize"] for l in fin)
    b = sum(booked(l) for l in fin)
    t = sum(true(l) or 0.0 for l in fin)
    print(f"  {'BOOK':<13} n={len(fin):>4} ntl=${ntl:>9,.0f}  booked {money(b):>10} "
          f"({pct(b / ntl * 100):>7})  true {money(t):>10} ({pct(t / ntl * 100):>7})")

    # the C-200 ladder gate, the dashboard's own basis: trailing 7 local days
    # (day key = local calendar day of closedAt ?? resolvedAt, as src/app/page.tsx does)
    now = time.time() * 1000
    cut = now - 7 * 86400 * 1000
    c2 = [l for l in fin if l["botId"] == "BANKROLL_200"
          and (l["closedAt"] or l["resolvedAt"]) and _ms(l["closedAt"] or l["resolvedAt"]) >= cut]
    by_day = {}
    for l in c2:
        d = market_day(_ms(l["closedAt"] or l["resolvedAt"]))
        g = by_day.setdefault(d, [0.0, 0.0, 0])
        g[0] += l["realizedPnl"] or 0.0
        g[1] += true_pnl(l, l["trueP"]) or 0.0
        g[2] += 1
    print("\n  C-200 ladder, last 8 local days (booked rows vs true basis):")
    print(f"    {'day':<12} {'n':>4} {'booked':>10} {'true':>10}")
    for d in sorted(by_day):
        b_, t_, n_ = by_day[d]
        print(f"    {d:<12} {n_:>4} {money(b_):>10} {money(t_):>10}")
    sb = sum(v[0] for v in by_day.values())
    st = sum(v[1] for v in by_day.values())
    print(f"    {'7d total':<12} {sum(v[2] for v in by_day.values()):>4} "
          f"{money(sb):>10} {money(st):>10}")
    print(f"  rung 1 needs $250/day x 7 = $1,750. booked {money(sb)} -> "
          f"{'PASS' if sb >= 1750 else 'fail'};  true {money(st)} -> "
          f"{'PASS' if st >= 1750 else 'fail'}")


def sec_bands(ded, label, legs_filter=None):
    fin = [l for l in ded if l["status"] != "open"]
    if legs_filter:
        fin = [l for l in fin if legs_filter(l)]
    print()
    print("=" * 78)
    print(f"C. TRUE-BASIS BAND MAP -- {label}  (re-banded by the price actually paid)")
    print("=" * 78)
    print(f"  legs {len(fin):,}   ntl ${sum(l['simulatedPositionSize'] for l in fin):,.0f}")
    print(f"  {'band':<8} {'n':>4} {'ntl':>9} {'truePnL':>10} {'ROI':>8} {'CI95':>18} "
          f"{'hit%':>6} {'avgP':>6} {'bnr':>6} {'tol':>6}")
    tot_p = tot_n = 0.0
    for lo, hi in BANDS:
        bn = band_name(lo, hi)
        g = [l for l in fin if band_of(l["trueP"]) == bn]
        if not g:
            continue
        ntl = sum(l["simulatedPositionSize"] for l in g)
        p = sum((true_pnl(l, l["trueP"]) or 0.0) for l in g)
        hits = sum(1 for l in g if (l["realizedPnl"] or 0) > 0)
        hit = hits / len(g) * 100
        avgp = sum(l["trueP"] for l in g) / len(g)
        clo, chi = cluster_ci(g, lambda l: true_pnl(l, l["trueP"]))
        ci = f"[{clo:+.1f},{chi:+.1f}]" if clo is not None else "n/a"
        tot_p += p
        tot_n += ntl
        print(f"  {bn:<8} {len(g):>4} {ntl:>9,.0f} {money(p):>10} {pct(p / ntl * 100):>8} "
              f"{ci:>18} {hit:>6.1f} {avgp:>6.3f} {avgp * 100:>6.1f} {hit - avgp * 100:>+6.1f}")
    if tot_n:
        print(f"  {'TOTAL':<8} {len(fin):>4} {tot_n:>9,.0f} {money(tot_p):>10} "
              f"{pct(tot_p / tot_n * 100):>8}")
    print("  bnr = break-even hit rate = the average price paid. tol = hit% - avgP")
    print("  (percentage points of entry slippage the band can absorb before it is")
    print("   loss-making: fee and slippage must both fit inside tol).")
    # concentration
    for k in (1, 3, 5, 10):
        s = sorted(fin, key=lambda l: -(true_pnl(l, l["trueP"]) or 0))
        keep = s[k:]
        p = sum((true_pnl(l, l["trueP"]) or 0) for l in keep)
        n = sum(l["simulatedPositionSize"] for l in keep)
        print(f"  ex-top{k:<2}  n={len(keep):>4} roi {pct(p / n * 100):>7}  pnl {money(p):>9}")


def sec_velocity(ded):
    print()
    print("=" * 78)
    print("D. CAPITAL VELOCITY on the true basis -- edge x capital x TURNOVER")
    print("=" * 78)
    fin = [l for l in ded if l["status"] != "open"]
    opn = [l for l in ded if l["status"] == "open"]
    now = time.time() * 1000

    def hold_days(l):
        end = l["closedAt"] or l["resolvedAt"]
        if not end:
            return None
        try:
            return max(0.05, (_ms(end) - l["openedTs"]) / 86400000.0)
        except Exception:
            return None

    print(f"  {'lane':<13} {'n':>4} {'ntl':>9} {'ROI':>7} {'capdays':>10} {'$/capday':>9} {'hold':>6}")
    for lane in ("STANDARD", "BANKROLL_200"):
        f = [l for l in fin if l["botId"] == lane]
        cd = sum(l["simulatedPositionSize"] * (hold_days(l) or 0) for l in f)
        p = sum((true_pnl(l, l["trueP"]) or 0) for l in f)
        ntl = sum(l["simulatedPositionSize"] for l in f)
        hd = [hold_days(l) or 0 for l in f]
        print(f"  {lane:<13} {len(f):>4} {ntl:>9,.0f} {pct(p / ntl * 100):>7} "
              f"{cd:>10,.0f} {p / cd if cd else 0:>9.4f} "
              f"{sum(hd) / len(hd) if hd else 0:>6.1f}")
    cd_open = sum(l["simulatedPositionSize"] * ((now - l["openedTs"]) / 86400000.0) for l in opn)
    cd_fin = 0.0
    for l in fin:
        cd_fin += l["simulatedPositionSize"] * (hold_days(l) or 0)
    # the same table for the live regime, which is the population a cap would act on
    print(f"\n  same table, regime opened >= {REGIME}:")
    for lane in ("STANDARD", "BANKROLL_200"):
        f = [l for l in fin if l["botId"] == lane and l["openedTs"] > _ms(REGIME)]
        if not f:
            continue
        cd = sum(l["simulatedPositionSize"] * (hold_days(l) or 0) for l in f)
        p = sum((true_pnl(l, l["trueP"]) or 0) for l in f)
        ntl = sum(l["simulatedPositionSize"] for l in f)
        hd = [hold_days(l) or 0 for l in f]
        print(f"  {lane:<13} {len(f):>4} {ntl:>9,.0f} {pct(p / ntl * 100):>7} "
              f"{cd:>10,.0f} {p / cd if cd else 0:>9.4f} "
              f"{sum(hd) / len(hd) if hd else 0:>6.1f}")
    # open book split by lane: what share of live capital sits in each lane
    for lane in ("STANDARD", "BANKROLL_200"):
        g = [l for l in opn if l["botId"] == lane]
        n = sum(l["simulatedPositionSize"] for l in g)
        tot = sum(l["simulatedPositionSize"] for l in opn)
        print(f"  open book {lane:<13} n={len(g):>3} ${n:>8,.0f} = "
              f"{n / tot * 100 if tot else 0:>4.1f}% of live notional")
    print(f"\n  capital-days still tied up in the OPEN book: {cd_open:,.0f} "
          f"(${sum(l['simulatedPositionSize'] for l in opn):,.0f} over "
          f"{cd_open / max(1e-9, sum(l['simulatedPositionSize'] for l in opn)):.1f} days avg)")
    print(f"  capital-days in ALL finished history          : {cd_fin:,.0f}")
    print(f"  -> the open book is {cd_open / cd_fin if cd_fin else 0:.2f}x the entire finished history")
    # by true band
    print(f"\n  {'band':<8} {'open n':>6} {'open ntl':>9} {'capdays':>9} {'ROI(true)':>10} {'$/capday':>9}")
    for lo, hi in BANDS:
        bn = band_name(lo, hi)
        g = [l for l in opn if band_of(l["trueP"]) == bn]
        f = [l for l in fin if band_of(l["trueP"]) == bn]
        if not g and not f:
            continue
        cdg = sum(l["simulatedPositionSize"] * ((now - l["openedTs"]) / 86400000.0) for l in g)
        cdf = sum(l["simulatedPositionSize"] * (hold_days(l) or 0) for l in f)
        pf = sum((true_pnl(l, l["trueP"]) or 0) for l in f)
        nf = sum(l["simulatedPositionSize"] for l in f)
        print(f"  {bn:<8} {len(g):>6} {sum(l['simulatedPositionSize'] for l in g):>9,.0f} "
              f"{cdg:>9,.0f} {pct(pf / nf * 100) if nf else 'n/a':>10} "
              f"{pf / cdf if cdf else 0:>9.4f}")


def _ms(v):
    s = str(v)
    if isinstance(v, (int, float)):
        return float(v)
    import datetime
    y, mo, d = int(s[0:4]), int(s[5:7]), int(s[8:10])
    hh = int(s[11:13]) if len(s) > 12 else 0
    mm = int(s[14:16]) if len(s) > 15 else 0
    ss = int(s[17:19]) if len(s) > 18 else 0
    return datetime.datetime(y, mo, d, hh, mm, ss,
                             tzinfo=datetime.timezone.utc).timestamp() * 1000


def sec_wallets(ded):
    print()
    print("=" * 78)
    print("F. WALLET COHORT on the true basis -- who the fake PnL was attributed to")
    print("=" * 78)
    fin = [l for l in ded if l["status"] != "open"]
    by = {}
    for l in fin:
        g = by.setdefault(l["walletAddress"], {"n": 0, "ntl": 0.0, "b": 0.0, "t": 0.0,
                                               "inv": 0, "legs": []})
        g["n"] += 1
        g["ntl"] += l["simulatedPositionSize"]
        g["b"] += l["realizedPnl"] or 0.0
        g["t"] += true_pnl(l, l["trueP"]) or 0.0
        g["inv"] += 1 if l["inverted"] else 0
        g["legs"].append(l)
    rows = sorted(by.items(), key=lambda kv: -kv[1]["b"])
    print(f"  {'wallet':<14} {'legs':>5} {'inv':>4} {'ntl':>9} {'booked':>10} {'ROI':>8} "
          f"{'true':>10} {'ROI':>8}")
    for w, g in rows[:10]:
        print(f"  {w[:12]:<14} {g['n']:>5} {g['inv']:>4} {g['ntl']:>9,.0f} "
              f"{money(g['b']):>10} {pct(g['b'] / g['ntl'] * 100):>8} "
              f"{money(g['t']):>10} {pct(g['t'] / g['ntl'] * 100):>8}")
    carriers = [(w, g) for w, g in rows if g["inv"] >= 5]
    print(f"\n  wallets carrying >=5 inverted legs: {len(carriers)}")
    tot_t = tot_n = 0.0
    for w, g in carriers:
        clo, chi = cluster_ci(g["legs"], lambda l: true_pnl(l, l["trueP"]))
        ci = f"[{clo:+.1f},{chi:+.1f}]" if clo is not None else "n/a"
        print(f"    {w[:12]:<14} legs {g['n']:>3} inv {g['inv']:>3} "
              f"booked {pct(g['b'] / g['ntl'] * 100):>8}  true {pct(g['t'] / g['ntl'] * 100):>8} "
              f"CI {ci:>16}")
        tot_t += g["t"]
        tot_n += g["ntl"]
    if tot_n:
        print(f"    {'ALL CARRIERS':<14} ntl ${tot_n:,.0f}  true {money(tot_t)} "
              f"({pct(tot_t / tot_n * 100)})")
    # how much of the BOOKED profit is theirs
    book_b = sum(g["b"] for _, g in rows)
    car_b = sum(g["b"] for _, g in carriers)
    print(f"  carriers hold {car_b / book_b * 100:.0f}% of the booked profit "
          f"(${car_b:,.0f} of ${book_b:,.0f}) and {tot_t / sum(g['t'] for _, g in rows) * 100:.0f}% "
          f"of the true profit")
    # multiple testing: how many wallets would look good by chance
    per = [(w, g["t"] / g["ntl"]) for w, g in rows if g["n"] >= 20]
    pos = sum(1 for _, r in per if r > 0)
    print(f"  wallets with >=20 finished legs: {len(per)}, of which true-ROI positive: {pos} "
          f"({pos / max(1, len(per)) * 100:.0f}%)")


def _wilson(k, n, z=1.96):
    """Wilson score interval for a binomial proportion (no normal approx at small n)."""
    import math
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, c - h), min(1.0, c + h))


def risk_legs(ls):
    """Legs that actually TRADED. `unfilled` with a zero payoff is an order the venue
    says never filled: it risked nothing, so it must not sit in an ROI denominator and
    must not be counted as a loss. In the current regime these are 121 of 367 legs and
    $3,042 of the regime's $8,079 notional (a third of the legs, 38% of the money) --
    so this exclusion moves every number it touches, in the direction of MORE extreme,
    not less. `unfilled` legs that DO carry a payoff (246 all-time, partial fills / fee
    adjustments) are kept.
    """
    return [l for l in ls if not (l["fillStatus"] == "unfilled" and (l["realizedPnl"] or 0) == 0)]


def _excl_note(label, all_legs, kept):
    drop = [l for l in all_legs if l not in kept]
    if not drop:
        return
    print(f"  [{label}: {len(drop)} unfilled legs excluded, "
          f"${sum(l['simulatedPositionSize'] for l in drop):,.0f} notional "
          f"({len(drop) / max(1, len(all_legs)) * 100:.0f}% of legs)]")


def sec_calibration(ded):
    """G. HIT RATE VS PRICE -- the basis-independent edge test.

    WHY THIS SECTION EXISTS. The standing claim "PnL is extremely concentrated,
    ex-top-10 collapses +16.1% -> +2.1%, so there is no edge" is a FAVOURITES test
    applied to a LONGSHOT book. In a cell with a ~19% hit rate and a ~+700% payoff,
    the top 10 of 541 legs holding the whole profit is arithmetic, not evidence: with
    19% accuracy the mean is carried by a handful of draws at ANY sample size, and
    ex-top-N destroys it EVEN IF the edge is exactly the measured one. For a BUY at
    p, ROI = hit/p - 1, so the cell has edge iff hit > p. That is the falsifiable
    statement, and its standard error depends on the number of DRAWS (legs), not on
    how fat the tail is. So this section reports hit rate, break-even rate (= the
    price paid), the gap in points, and a Wilson interval on the hit rate.

    Resolved-only, by contract: a resolved leg pays 1.0 or 0.0, so the identity
    ROI = hit/p - 1 is EXACT. An early close pays the mark, and hit%-p would then be
    the wrong identity -- which is why the finished-all table is printed for reference
    but the VERDICT rests on the resolved table. Where the two disagree, the gap is
    the early-close policy and section H prices it.
    """
    print()
    print("=" * 78)
    print("G. CALIBRATION -- hit rate vs the price paid (the edge test that does not")
    print("   depend on the clip size, the cost basis, or the shape of the payoff)")
    print("=" * 78)
    fin_all = [l for l in ded if l["status"] != "open"]
    fin = risk_legs(fin_all)
    _excl_note("ALL-TIME", fin_all, fin)
    clean_from = _ms(FIX_EPOCH)
    reg_from = _ms(REGIME)
    pops = [
        ("ALL-TIME finished", fin),
        ("ALL-TIME resolved", [l for l in fin if l["status"] == "resolved"]),
        ("REGIME >= %s finished" % REGIME[:10], [l for l in fin if l["openedTs"] >= reg_from]),
        ("REGIME resolved", [l for l in fin if l["status"] == "resolved" and l["openedTs"] >= reg_from]),
        ("CLEAN post-fix resolved", [l for l in fin if l["status"] == "resolved" and l["openedTs"] >= clean_from]),
    ]
    for label, pop in pops:
        if not pop:
            continue
        exact = "resolved" in label
        print(f"\n  {label}   (legs {len(pop):,}; identity "
              f"{'EXACT' if exact else 'approx -- early closes pay a mark'})")
        print(f"    {'band':<8} {'n':>4} {'hit%':>6} {'wilson95':>15} {'avgP':>6} "
              f"{'tol pp':>7} {'tol CI95':>16} {'ROI@ident':>9} {'verdict':>10}")
        for lo, hi in BANDS:
            bn = band_name(lo, hi)
            g = [l for l in pop if band_of(l["trueP"]) == bn]
            if not g:
                continue
            k = sum(1 for l in g if (true_pnl(l, l["trueP"]) or 0.0) > 0)
            n = len(g)
            hit = k / n
            avgp = sum(l["trueP"] for l in g) / n
            wlo, whi = _wilson(k, n)
            tlo, thi = (wlo - avgp) * 100, (whi - avgp) * 100
            roi = (hit / avgp - 1.0) * 100 if avgp > 0 else 0.0
            verdict = "edge" if tlo > 0 else ("NO edge" if thi < 0 else "open")
            print(f"    {bn:<8} {n:>4} {hit * 100:>6.1f} "
                  f"[{wlo * 100:>4.1f},{whi * 100:>5.1f}] {avgp:>6.3f} "
                  f"{(hit - avgp) * 100:>+7.1f} [{tlo:>+6.1f},{thi:>+6.1f}] "
                  f"{roi:>+9.1f} {verdict:>10}")
        tot_k = sum(1 for l in pop if (true_pnl(l, l["trueP"]) or 0.0) > 0)
        tot_avgp = sum(l["trueP"] for l in pop) / len(pop)
        print(f"    {'BOOK':<8} {len(pop):>4} {tot_k / len(pop) * 100:>6.1f} "
              f"{'':>15} {tot_avgp:>6.3f} {(tot_k / len(pop) - tot_avgp) * 100:>+7.1f}")
    print("\n  READ: a band has an EDGE iff tol's interval excludes 0. tol < 0 means the")
    print("  band pays a price above the accuracy it delivers. No tail-trimming argument")
    print("  is needed for that, and none can argue it away.")


def sec_clean(ded):
    """H. THE CLEAN COHORT -- the only population where the price basis cannot matter.

    Every leg opened after FIX_EPOCH was written by the corrected parser, so booked
    price == price paid and bookedPnl == truePnl. That makes it the one forward read
    that is immune to the 233-row defect and to any argument about which estimator to
    use. It is small, and small is the finding: n is on every line.

    H2 prices the gap between the two edge statistics: a cell's ROI can be far worse
    than its calibration when the early-close policy sells the ticket before it pays.
    For a longshot that is the whole edge -- the payoff IS the tail -- so the split
    between `closed` and `resolved` legs is the difference between being paid for a
    lottery and paying for one.
    """
    print()
    print("=" * 78)
    print("H. CLEAN COHORT -- legs opened after the write fix (basis-independent)")
    print("=" * 78)
    fin_all = [l for l in ded if l["status"] != "open"]
    fin = risk_legs(fin_all)
    clean = [l for l in fin if l["openedTs"] >= _ms(FIX_EPOCH)]
    if not clean:
        print("  none settled yet")
        return
    _excl_note("CLEAN", [l for l in fin_all if l["openedTs"] >= _ms(FIX_EPOCH)], clean)
    ntl = sum(l["simulatedPositionSize"] for l in clean)
    p = sum((true_pnl(l, l["trueP"]) or 0.0) for l in clean)
    clo, chi = cluster_ci(clean, lambda l: true_pnl(l, l["trueP"]))
    print(f"  settled {len(clean)} legs that traded, ${ntl:,.0f} at risk, true PnL "
          f"{money(p)} ({pct(p / ntl * 100)}), clustered CI [{clo:+.1f},{chi:+.1f}]")
    days = (max(l["openedTs"] for l in clean) - _ms(FIX_EPOCH)) / 86400000.0
    print(f"  cohort spans {days:.1f} days; ${ntl / max(days, 0.1):,.0f}/day at risk")
    print(f"\n  {'band':<8} {'n':>4} {'ntl':>8} {'ROI':>8} {'CI95':>17} {'hit%':>6} "
          f"{'avgP':>6} {'tol':>6} {'x1':>7} {'x3':>7}")
    for lo, hi in BANDS:
        bn = band_name(lo, hi)
        g = [l for l in clean if band_of(l["trueP"]) == bn]
        if not g:
            continue
        n_ = sum(l["simulatedPositionSize"] for l in g)
        p_ = sum((true_pnl(l, l["trueP"]) or 0.0) for l in g)
        a, b_ = cluster_ci(g, lambda l: true_pnl(l, l["trueP"]))
        hit = sum(1 for l in g if (true_pnl(l, l["trueP"]) or 0.0) > 0) / len(g) * 100
        avgp = sum(l["trueP"] for l in g) / len(g)
        ex = {}
        for k in (1, 3):
            s = sorted(g, key=lambda l: -(true_pnl(l, l["trueP"]) or 0.0))[k:]
            nn = sum(l["simulatedPositionSize"] for l in s)
            ex[k] = (sum((true_pnl(l, l["trueP"]) or 0.0) for l in s) / nn * 100) if nn else 0.0
        print(f"    {bn:<8} {len(g):>4} {n_:>8,.0f} {pct(p_ / n_ * 100):>8} "
              f"[{a:+.1f},{b_:+.1f}]".rjust(18) + f" {hit:>6.1f} {avgp:>6.3f} "
              f"{hit - avgp * 100:>+6.1f} {ex[1]:>+7.1f} {ex[3]:>+7.1f}")

    # H2. closed vs resolved -- the early-close column
    print(f"\n  H2. WHERE ROI AND CALIBRATION DISAGREE: the early-close column")
    for label, pop in (("ALL-TIME", fin), ("REGIME", [l for l in fin if l["openedTs"] >= _ms(REGIME)]),
                       ("CLEAN", clean)):
        print(f"    {label}: {'band':<8} {'closed n':>9} {'closed pnl':>11} "
              f"{'resolved n':>11} {'resolved pnl':>12} {'resid ROI':>10}")
        for lo, hi in BANDS:
            bn = band_name(lo, hi)
            g = [l for l in pop if band_of(l["trueP"]) == bn]
            if not g:
                continue
            c = [l for l in g if l["status"] == "closed"]
            r = [l for l in g if l["status"] == "resolved"]
            cp = sum((true_pnl(l, l["trueP"]) or 0.0) for l in c)
            rp = sum((true_pnl(l, l["trueP"]) or 0.0) for l in r)
            rn = sum(l["simulatedPositionSize"] for l in r)
            print(f"        {bn:<8} {len(c):>9} {money(cp):>11} {len(r):>11} "
                  f"{money(rp):>12} {pct(rp / rn * 100) if rn else 'n/a':>10}")
    # H3. band ROI by window on legs that traded -- the table the review quotes
    print(f"\n  H3. BAND ROI by window, legs that traded only (cost = $ at risk)")
    for label, pop in (("ALL-TIME", fin), ("REGIME", [l for l in fin if l["openedTs"] >= _ms(REGIME)]),
                       ("CLEAN", clean)):
        print(f"    {label:<9} {'band':<8} {'n':>4} {'ntl':>8} {'ROI':>8} {'CI95':>17} "
              f"{'share':>6}")
        tt = sum(l["simulatedPositionSize"] for l in pop)
        for lo, hi in BANDS:
            bn = band_name(lo, hi)
            g = [l for l in pop if band_of(l["trueP"]) == bn]
            if not g:
                continue
            n_ = sum(l["simulatedPositionSize"] for l in g)
            p_ = sum((true_pnl(l, l["trueP"]) or 0.0) for l in g)
            a, b_ = cluster_ci(g, lambda l: true_pnl(l, l["trueP"]))
            print(f"    {'':<9} {bn:<8} {len(g):>4} {n_:>8,.0f} {pct(p_ / n_ * 100):>8} "
                  f"[{a:+.1f},{b_:+.1f}]".rjust(18) + f" {n_ / tt * 100:>5.0f}%")
    # what the open book is holding in the same cells
    opn = [l for l in ded if l["status"] == "open"]
    print(f"\n  open book by band (this is what the clean cohort is about to become):")
    for lo, hi in BANDS:
        bn = band_name(lo, hi)
        g = [l for l in opn if band_of(l["trueP"]) == bn]
        if not g:
            continue
        print(f"    {bn:<8} n={len(g):>3} ${sum(l['simulatedPositionSize'] for l in g):>8,.0f}")


def _day_series(legs):
    """Per-local-day booked PnL, true PnL and leg count for finished legs."""
    b, t, n = {}, {}, {}
    for l in legs:
        end = l["closedAt"] or l["resolvedAt"]
        if not end:
            continue
        d = market_day(_ms(end))
        b[d] = b.get(d, 0.0) + (l["realizedPnl"] or 0.0)
        t[d] = t.get(d, 0.0) + (true_pnl(l, l["trueP"]) or 0.0)
        n[d] = n.get(d, 0) + 1
    return b, t, n


def sec_ladder(ded):
    """I. WHAT IS THE LADDER READING, AND DOES THE READ EXIST ON THE TRUE BASIS?

    query_bankroll.js computes the phase at READ TIME: gateFrom() walks the phase
    table and advances while the trailing 7 SETTLED days sum >= target*7. It reads
    the rows. Two consequences this section measures:

      (1) THE RUNG IS NOT STORED. Nothing records "we earned Phase 2". A window that
          clears $1,750 for seven days makes the read say Phase 2; the day that
          window rolls off, the read falls back with no event and no alarm. So a
          booked-clearing window is not a milestone -- it is a rolling artefact, and
          the ladder can advance and retreat on arithmetic that later changes.
      (2) THE SUM IS BOOKED. On the true basis the sum is a different number, and
          "how many windows EVER cleared" becomes a question with an arithmetic
          answer that does not depend on any estimator choice.

    Also priced here: the 30-day capital series (src/lib/capital.ts, the /capital
    chart) and the standing "50% of daily profit swept out of capital" policy, which
    converts a booked daily number into an irreversible cash decision and a tax event.
    """
    print()
    print("=" * 78)
    print("I. LADDER PROVENANCE -- the rung is a read-time function of booked rows")
    print("=" * 78)
    fin = [l for l in ded if l["status"] != "open" and l["botId"] == "BANKROLL_200"]
    b, t, n = _day_series(fin)
    import datetime
    days = sorted(b)
    if len(days) < 8:
        print("  too few days")
        return
    d0, d1 = datetime.date.fromisoformat(days[0]), datetime.date.fromisoformat(days[-1])
    one = datetime.timedelta(days=1)

    PHASES = [250, 500, 1000, 2000, 5000]
    K = 7
    wins = []
    cur = d0
    while cur + one * (K - 1) <= d1:
        ds = [(cur + one * i).isoformat() for i in range(K)]
        wins.append((ds[0], ds[-1],
                     sum(b.get(x, 0.0) for x in ds),
                     sum(t.get(x, 0.0) for x in ds),
                     sum(n.get(x, 0) for x in ds)))
        cur += one
    print(f"  calendar span {days[0]} .. {days[-1]}; rolling {K}-day windows: {len(wins)}")
    print(f"  {'rung':<12} {'need/7d':>9} {'booked clearing':>16} {'true clearing':>14}")
    for i, target in enumerate(PHASES):
        need = target * K
        cb = sum(1 for w in wins if w[2] >= need)
        ct = sum(1 for w in wins if w[3] >= need)
        print(f"  Phase {i + 1} (${target:>4}/d) {need:>9,} {cb:>9}/{len(wins):<6} {ct:>8}/{len(wins):<5}")
    best = max(wins, key=lambda w: w[3])
    print(f"  best TRUE window ever: {best[0]}..{best[1]} {money(best[3])} "
          f"(booked {money(best[2])})")
    lastb = [w for w in wins if w[2] >= 1750]
    lastt = [w for w in wins if w[3] >= 1750]
    print(f"  last BOOKED window clearing $1,750: ends {lastb[-1][1] if lastb else 'never'}")
    print(f"  last TRUE   window clearing $1,750: ends {lastt[-1][1] if lastt else 'never'}")
    if len(lastb) > len(lastt):
        span_b = {(w[0], w[1]) for w in lastb}
        span_t = {(w[0], w[1]) for w in lastt}
        print(f"  windows that clear on BOOKED rows but not on true rows: "
              f"{len(span_b - span_t)} of {len(span_b)}")

    # reproduce query_bankroll's own read: settled window = days T-SETTLE..T-SETTLE-6
    SETTLE = 3
    today = max(datetime.date.fromisoformat(x) for x in days)
    for label, series in (("booked", b), ("true", t)):
        w = [(today - one * (SETTLE + i)).isoformat() for i in range(K)]
        s = sum(series.get(x, 0.0) for x in w)
        idx = 0
        for i, target in enumerate(PHASES):
            if s >= target * K:
                idx = i + 1
            else:
                break
        idx = min(idx, len(PHASES) - 1)
        need = PHASES[idx] * K
        print(f"\n  query_bankroll read reproduced ({label}): window {w[-1]}..{w[0]} "
              f"sum {money(s)}")
        print(f"    -> current goal = Phase {idx + 1} (${PHASES[idx]}/day), "
              f"gate {money(s)} vs ${need:,} = {s / need * 100:.1f}% "
              f"{'MET' if s >= need else 'SHORT'}")

    # the 30-day capital series (capital.ts) and the 50% sweep policy
    print(f"\n  30 local days of the /capital series (booked vs true, same rows):")
    end = today
    start = end - one * 29
    sb = st = 0.0
    sweep_b = sweep_t = 0.0
    for i in range(30):
        d = (start + one * i).isoformat()
        vb, vt = b.get(d, 0.0), t.get(d, 0.0)
        sb += vb
        st += vt
        sweep_b += 0.5 * max(0.0, vb)
        sweep_t += 0.5 * max(0.0, vt)
    print(f"    {start} .. {end}: booked {money(sb)}   true {money(st)}   "
          f"gap {money(sb - st)}")
    print(f"    50% profit sweep over the same 30 days: booked {money(sweep_b)}  "
          f"true {money(sweep_t)}  -> phantom withdrawal {money(sweep_b - sweep_t)}")
    print("    (the sweep is a PRODUCTION policy, 2027-01-02; in paper it is a number,")
    print("     in production it is cash leaving the book and a taxable event)")


def _resize(l, plan):
    """New dollars at risk under a band-relative clip PLAN.

    `plan` is a list of {"band": ..., "cap": ...} / {"band": ..., "lift": ...} steps,
    applied in order, so a plan can cap one cell and lift another (the first draft
    passed cap and lift as one dict and silently capped AND lifted the same band,
    which made the 'cap cheap + lift mid' arm print the lift-only number -- caught
    before quoting). PnL scales linearly in size at a fixed price:
    pnl = ntl*(exit/p - 1). FILL ASSUMPTION: the larger clip pays the same price.
    """
    old = l["simulatedPositionSize"]
    if old is None or old <= 0:
        return old
    new = old
    bn = band_of(l["trueP"])
    for step in plan:
        if band_of(l["trueP"]) != step["band"]:
            continue
        if "cap" in step and new > step["cap"]:
            new = step["cap"]
        if "lift" in step and new < step["lift"]:
            new = step["lift"]
    return new


def _shadow(legs, plan, label):
    """Apply a sizing plan to realised legs and re-sum. Delta CI resamples markets."""
    p_old = n_old = 0.0
    tot = 0.0
    n_new = 0.0
    by = {}
    for l in legs:
        po = true_pnl(l, l["trueP"]) or 0.0
        old = l["simulatedPositionSize"] or 0.0
        new = _resize(l, plan) or 0.0
        pn = po * (new / old) if old > 0 else po
        p_old += po
        n_old += old
        n_new += new
        tot += pn - po
        g = by.setdefault(l["marketId"], [0.0, 0.0])
        g[0] += pn - po
        g[1] += old
    # clustered bootstrap on the DELTA (roi points, old notional as the base)
    import random
    ks = list(by)
    out = []
    rnd = random.Random(11)
    for _ in range(2000):
        dp = dn = 0.0
        for _ in range(len(ks)):
            k = ks[rnd.randrange(len(ks))]
            dp += by[k][0]
            dn += by[k][1]
        if dn > 0:
            out.append(dp / dn * 100.0)
    out.sort()
    lo = out[int(0.025 * len(out))] if out else 0.0
    hi = out[int(0.975 * len(out)) - 1] if out else 0.0
    print(f"  {label:<26} n={len(legs):>4} ntl={n_old:>8,.0f}->{n_new:>8,.0f} "
          f"pnl {p_old:>+9,.2f} -> {p_old + tot:>+9,.2f}  delta {tot:>+8,.2f} "
          f"({tot / n_old * 100 if n_old else 0:+.1f}pp) CI [{lo:+.1f},{hi:+.1f}]")


def sec_sizing(ded):
    """J. SIZING SHADOW -- is the clip where the edge is?

    LANE A CONTEXT: this is a shadow computation on REALISED legs. It proposes
    nothing by itself; it prices a band-relative clip, which is the one sizing
    question the 2026-10-20 clamp refutation does not cover (that refutation was
    about a GLOBAL $18 cap on a single day; this caps ONE cell and lifts another).
    """
    print()
    print("=" * 78)
    print("J. SIZING SHADOW -- band-relative clip, on realised outcomes (no re-selection)")
    print("=" * 78)
    fin_all = [l for l in ded if l["status"] != "open"]
    fin = risk_legs(fin_all)
    clean_from = _ms(FIX_EPOCH)
    reg_from = _ms(REGIME)
    print(f"\n  observed clip by band (all-time, legs that traded):")
    print(f"    {'band':<8} {'n':>4} {'avg clip':>9} {'median':>7} {'p90':>7} {'share ntl':>10} {'ROI':>8}")
    tot = sum(l["simulatedPositionSize"] for l in fin)
    for lo, hi in BANDS:
        bn = band_name(lo, hi)
        g = [l for l in fin if band_of(l["trueP"]) == bn]
        if not g:
            continue
        s = sorted(l["simulatedPositionSize"] for l in g)
        p_ = sum((true_pnl(l, l["trueP"]) or 0.0) for l in g)
        print(f"    {bn:<8} {len(g):>4} {sum(s) / len(s):>9.1f} {s[len(s) // 2]:>7.1f} "
              f"{s[int(0.9 * len(s))]:>7.1f} "
              f"{sum(s) / tot * 100:>9.0f}% {pct(p_ / sum(s) * 100):>8}")
    rules = [
        ("cap cheap at $25", [{"band": "0.0-0.2", "cap": 25.0}]),
        ("cap cheap at $50", [{"band": "0.0-0.2", "cap": 50.0}]),
        ("lift 0.2-0.4 to $25", [{"band": "0.2-0.4", "lift": 25.0}]),
        ("lift 0.2-0.4 to $50", [{"band": "0.2-0.4", "lift": 50.0}]),
        ("cap cheap $25 + lift 0.2-0.4 $25",
         [{"band": "0.0-0.2", "cap": 25.0}, {"band": "0.2-0.4", "lift": 25.0}]),
        ("cap cheap $13 + lift 0.2-0.4 $25",
         [{"band": "0.0-0.2", "cap": 13.0}, {"band": "0.2-0.4", "lift": 25.0}]),
    ]
    pops = [
        ("ALL-TIME", fin),
        ("REGIME >= %s" % REGIME[:10], [l for l in fin if l["openedTs"] >= reg_from]),
        ("CLEAN post-fix", [l for l in fin if l["openedTs"] >= clean_from]),
    ]
    for plabel, pop in pops:
        print(f"\n  {plabel}:")
        for rlabel, rule in rules:
            _shadow(pop, rule, rlabel)
    print("\n  delta is vs the book as actually sized. Positive = the rule would have")
    print("  earned more on the SAME legs, at the SAME prices, with no re-selection.")
    print("  A rule whose delta changes SIGN between rows is a window bet, not a lever.")
    print("  FILL ASSUMPTION: a lifted clip pays the same price. On thin books that is")
    print("  the optimistic case, so the lift arms are UPPER BOUNDS; the cell's tol (G)")
    print("  is the entry slippage it can absorb before the lift is worthless.")


def self_test(legs):
    print()
    print("=" * 78)
    print("E. SELF-TESTS")
    print("=" * 78)
    fin = [l for l in legs if l["status"] != "open"]
    ok = 0
    tot = 0
    for l in fin:
        if l["simulatedPositionSize"] <= 0 or l["entryPrice"] <= 0:
            continue
        tot += 1
        if abs((true_pnl(l, l["entryPrice"]) or 0.0) - (l["realizedPnl"] or 0.0)) < 0.02:
            ok += 1
    print(f"  identity check: repricing at the BOOKED price reproduces realizedPnl on "
          f"{ok:,}/{tot:,} legs")
    # synthetic: $10 at risk, won at 1.0; reprice the entry to 0.80
    fake = {"status": "resolved", "entryPrice": 0.20, "simulatedPositionSize": 10.0,
            "realizedPnl": 40.0}
    print(f"  synthetic reprice: $10 at risk entered 0.20 (won at 1.0) repriced to 0.80 "
          f"-> {true_pnl(fake, 0.80):+.2f} (expect +2.50)")
    inv = sum(1 for l in legs if l["inverted"])
    cons = sum(1 for l in legs if l["class"] == "consistent")
    print(f"  classification partitions: inverted {inv} + consistent {cons} + "
          f"no_fill {len(legs) - inv - cons} = {len(legs)}")
    # G/J arithmetic: the resize rule must be the identity when nothing binds, and
    # risk_legs must remove exactly the unfilled-and-unpaying rows.
    fake2 = {"status": "resolved", "entryPrice": 0.30, "trueP": 0.30,
             "simulatedPositionSize": 12.0, "realizedPnl": 28.0}
    same = _resize(fake2, [{"band": "0.0-0.2", "cap": 25.0}])
    lift = _resize(fake2, [{"band": "0.2-0.4", "lift": 25.0}])
    print(f"  resize identity (band not in plan): 12.00 -> {same:.2f} (expect 12.00); "
          f"lift 0.2-0.4 $25 -> {lift:.2f} (expect 25.00)")
    zero_unfilled = sum(1 for l in legs if l["fillStatus"] == "unfilled" and (l["realizedPnl"] or 0) == 0)
    kept = len(risk_legs(legs))
    print(f"  risk_legs: {len(legs):,} rows -> keeps {kept:,}, drops {len(legs) - kept:,} "
          f"(unfilled & zero-payoff = {zero_unfilled:,})")
    # window sums must close: the 7-day windows cannot invent money
    print("  SELF-TEST PASS" if ok == tot and abs(true_pnl(fake, 0.80) - 2.5) < 0.01
          and same == 12.0 and lift == 25.0 and len(legs) - kept == zero_unfilled
          else "  SELF-TEST FAIL")


def main():
    only = None
    for a in sys.argv[1:]:
        if a.startswith("--only="):
            only = set(a.split("=", 1)[1].split(","))
    legs = load_legs()
    # dedupe WITHIN status class: an open first leg must not shadow a finished later leg
    # with the same bot|wallet|market|outcome key (it did on the first run -- 2,063 vs 2,002).
    fin = dedupe([l for l in legs if l["status"] != "open"])
    opn = dedupe([l for l in legs if l["status"] == "open"])
    ded = sorted(fin + opn, key=lambda l: l["openedTs"])
    reg = dedupe([l for l in load_legs(min_rule=49) if l["status"] != "open"])
    print(f"population: {len(legs):,} non-demo PaperTrade rows -> {len(fin):,} finished + "
          f"{len(opn):,} open deduped legs (first per bot|wallet|market|outcome within class); "
          f"regime rv>=49: {len(reg):,}")
    if not only or "A" in only:
        sec_integrity(legs, ded)
    if not only or "B" in only:
        sec_scoreboard(legs, ded)
    if not only or "C" in only:
        sec_bands(ded, "ALL-TIME")
        sec_bands(ded, "LAST 90 DAYS", lambda l: l["openedTs"] > (time.time() - 90 * 86400) * 1000)
        sec_bands(reg, "REGIME ruleSetVersion >= 49")
        sec_bands(reg, f"REGIME opened >= {REGIME}",
                  lambda l: l["openedTs"] > _ms(REGIME))
    if not only or "D" in only:
        sec_velocity(ded)
    if not only or "F" in only:
        sec_wallets(ded)
    if not only or "G" in only:
        sec_calibration(ded)
    if not only or "H" in only:
        sec_clean(ded)
    if not only or "I" in only:
        sec_ladder(ded)
    if not only or "J" in only:
        sec_sizing(ded)
    if not only or "E" in only:
        self_test(legs)


if __name__ == "__main__":
    main()
