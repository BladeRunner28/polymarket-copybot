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
    print("  SELF-TEST PASS" if ok == tot and abs(true_pnl(fake, 0.80) - 2.5) < 0.01
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
    if not only or "E" in only:
        self_test(legs)


if __name__ == "__main__":
    main()
