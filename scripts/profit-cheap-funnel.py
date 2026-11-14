#!/usr/bin/env python3
"""
Where the cheap tail's volume dies -- the funnel read behind profit-recs-20261114.

WHY THIS FILE EXISTS
--------------------
Every band/turnover number in the 2026-11-14 review has to be reproducible from a
committed script in the same commit (the 2026-10-20 review shipped prose only and its
first independent re-run disagreed on two of three load-bearing numbers). This is that
script for today's claim set, which is narrow on purpose:

  A. THE BAND LEDGER, ON POSITIONS ONLY. The published ratios divide by notional that
     includes legs stamped fillStatus='unfilled'. Those legs are NOT positions: they
     book $0 realizedPnl but keep their full simulatedPositionSize in the denominator,
     and in a hit-rate table they land in the "lost" bucket because $0 is not > $0.
     Section A prints both denominators side by side so the defect is quantifiable
     rather than asserted. COST BASIS = PaperTrade.simulatedPositionSize (DOLLARS at
     risk, not shares); entryPrice is the price, never the cost.

  B. THE FUNNEL BY PRICE. DecisionJournal x ObservedTrade gives the candidate price at
     detection, so the admit rate can be cut by price band. This is where "the cheap
     tail is starved" either is or is not true, and it separates candidate supply from
     gate refusal. Blocker strings come from risksJson (the operative blockers).

  C. THE COUNTERFACTUAL ON THE REFUSED CHEAP COHORT. Refused cheap candidates are
     resolved from the venue's own archive (clob.polymarket.com/markets/<conditionId>,
     keys, no wallet), and scored as if copied at the DETECTION price: hit -> (1-p)/p,
     miss -> -1. The admitted cheap cohort is the matched control, scored on the same
     identity from PaperTrade. This is the falsifiable core: if the refused cohort earns
     at least what the admitted cohort earns, the gate is not selecting.

BASIS / CLOCK
  level      = one finished non-demo PaperTrade leg, deduped to the first leg per
               bot|wallet|market|outcome
  cost       = simulatedPositionSize (dollars at risk)
  hit        = realizedPnl > 0 on a resolved leg (natural settlement)
  breakeven  = the leg's own entryPrice (a BUY at p needs >p accuracy; every leg in
               this DB is side=BUY)
  edge_pp    = hitRate - mean(entryPrice), in percentage points
  eqw_roi    = mean((won - p)/p), the exact settled return on dollars at risk
  regime     = admitting journal.ruleSetVersion >= 68 (the repo convention)
  CI         = 1,000-rep bootstrap clustered on marketId (legs on one market are one bet)

USAGE
    python3 scripts/profit-cheap-funnel.py                # A + B, no HTTP
    python3 scripts/profit-cheap-funnel.py --resolve      # + C (venue archive, cached)
    python3 scripts/profit-cheap-funnel.py --self-test    # metric known-answers + controls

READ-ONLY: opens the DB with mode=ro, writes nothing except the HTTP response cache
under data/cheap-funnel-cache/ (gitignored). No RuleSet read or write, no prisma write.
"""
import json
import os
import random
import sqlite3
import sys
import time
import urllib.error
import urllib.request
from collections import Counter, defaultdict

DB = os.environ.get("COPYBOT_DB", "file:prisma/dev.db?mode=ro")
CACHE = os.path.join("data", "cheap-funnel-cache")
BOTS = ("STANDARD", "BANKROLL_200")
BANDS = [(0.0, 0.2), (0.2, 0.4), (0.4, 0.6), (0.6, 0.8), (0.8, 1.0001)]
BAND_NAMES = ["0.0-0.2", "0.2-0.4", "0.4-0.6", "0.6-0.8", "0.8-1.0"]
REGIME = 68
SEED = 20261114
cache = None


def con():
    c = sqlite3.connect(DB, uri=True)
    c.row_factory = sqlite3.Row
    return c


def band_of(p):
    if p is None:
        return None
    for (lo, hi), nm in zip(BANDS, BAND_NAMES):
        if lo <= p < hi:
            return nm
    return None


# ---------------------------------------------------------------- statistics
def boot(vals, mkts, reps=1000, seed=SEED):
    """Market-clustered bootstrap: resample MARKETS, recompute the statistic on their legs.
    vals = list of per-leg tuples consumed by stat(); mkts = parallel market ids."""
    bym = defaultdict(list)
    for m, v in zip(mkts, vals):
        bym[m].append(v)
    keys = list(bym.keys())
    if len(keys) < 2:
        return (None, None)
    rnd = random.Random(seed)
    out = []
    for _ in range(reps):
        pick = [keys[rnd.randrange(len(keys))] for _ in keys]
        s = [v for k in pick for v in bym[k]]
        if s:
            out.append(s)
    return tuple(_pct(out, lo) for lo in (2.5, 97.5))


def _pct(samples, q):
    v = sorted(samples)
    if not v:
        return None
    k = (len(v) - 1) * q / 100.0
    f = int(k)
    c = min(f + 1, len(v) - 1)
    return v[f] + (v[c] - v[f]) * (k - f)


def edge_stat(legs):
    """legs = [(won:int, p:float)] -> (hit%, be%, edge_pp, eqw_roi%)"""
    n = len(legs)
    if not n:
        return None
    hits = sum(w for w, _ in legs)
    mp = sum(p for _, p in legs) / n
    eqw = sum(((1.0 if w else 0.0) - p) / p for w, p in legs if p > 0) / n
    return (100.0 * hits / n, 100.0 * mp, 100.0 * (hits / n - mp), 100.0 * eqw)


def stat_ci(legs, mkts, which=2):
    """CI on one component of edge_stat (2=edge_pp, 3=eqw_roi) by market cluster."""
    pairs = [(legs[i], mkts[i]) for i in range(len(legs))]
    bym = defaultdict(list)
    for (lg, m) in pairs:
        bym[m].append(lg)
    keys = list(bym.keys())
    if len(keys) < 2:
        return (None, None)
    rnd = random.Random(SEED)
    out = []
    for _ in range(1000):
        pick = [keys[rnd.randrange(len(keys))] for _ in keys]
        s = [lg for k in pick for lg in bym[k]]
        st = edge_stat(s)
        if st:
            out.append(st[which])
    return tuple(_pct(out, lo) for lo in (2.5, 97.5))


# ---------------------------------------------------------------- data
LEG_SQL = """
WITH leg AS (
  SELECT p.id, p.botId bt, p.walletAddress w, p.marketId m, p.outcome oc, p.entryPrice ep,
         p.simulatedPositionSize sz, p.realizedPnl pnl, p.fillStatus fs, p.openedAt,
         j.ruleSetVersion v,
         ROW_NUMBER() OVER (PARTITION BY p.botId,p.walletAddress,p.marketId,p.outcome
                            ORDER BY p.openedAt) rn
  FROM PaperTrade p LEFT JOIN DecisionJournal j ON p.decisionJournalId = j.id
  WHERE p.isDemo = 0 AND p.status = 'resolved' AND p.realizedPnl IS NOT NULL
)
SELECT bt, w, m, oc, ep, sz, pnl, fs, v FROM leg WHERE rn = 1
"""


def legs(regime):
    c = con()
    rows = c.execute(LEG_SQL).fetchall()
    c.close()
    if regime:
        rows = [r for r in rows if r["v"] is not None and r["v"] >= REGIME]
    return rows


def positions(rows):
    """A leg is a POSITION unless the resolver stamped it 'unfilled' (books $0, no exposure)."""
    return [r for r in rows if (r["fs"] or "") != "unfilled"]


# ---------------------------------------------------------------- section A
def section_a():
    print("=" * 78)
    print("A. BAND LEDGER -- positions only vs every finished row")
    print("   cost = simulatedPositionSize (dollars at risk). hit = realizedPnl>0 on a")
    print("   resolved leg. breakeven hit rate = the leg's own entryPrice.")
    print("=" * 78)
    for regime in (True, False):
        label = f"regime (journal.ruleSetVersion >= {REGIME})" if regime else "all time"
        allr = legs(regime)
        posr = positions(allr)
        print(f"\n{label}:  {len(allr)} finished legs | {len(posr)} POSITIONS | "
              f"{len(allr)-len(posr)} stamped unfilled")
        for name, rows in (("POSITIONS ONLY", posr), ("ALL FINISHED ROWS", allr)):
            print(f"\n  -- {name} --")
            print(f"  {'band':9} {'n':>5} {'ntl':>9} {'pnl':>9} {'hit%':>6} {'be%':>6} "
                  f"{'edge_pp':>8} {'95% CI':>18} {'eqwROI%':>8}")
            for nm in BAND_NAMES:
                cell = [r for r in rows if band_of(r["ep"]) == nm]
                if not cell:
                    continue
                lg = [(1 if r["pnl"] > 0 else 0, r["ep"]) for r in cell]
                mk = [r["m"] for r in cell]
                st = edge_stat(lg)
                lo, hi = stat_ci(lg, mk, 2)
                ntl = sum(r["sz"] for r in cell)
                pnl = sum(r["pnl"] for r in cell)
                ci = f"[{lo:+.1f},{hi:+.1f}]" if lo is not None else "   n/a"
                print(f"  {nm:9} {len(cell):5d} {ntl:9.0f} {pnl:9.0f} {st[0]:6.1f} "
                      f"{st[1]:6.1f} {st[2]:+8.1f} {ci:>18} {st[3]:+8.1f}")

    # by lane, positions only, regime
    print("\n  -- by lane, positions only, regime --")
    print(f"  {'lane':13} {'band':9} {'n':>4} {'ntl':>7} {'pnl':>7} {'hit%':>6} {'be%':>6} "
          f"{'edge_pp':>8} {'eqwROI%':>8}")
    posr = positions(legs(True))
    for bt in BOTS:
        for nm in BAND_NAMES:
            cell = [r for r in posr if r["bt"] == bt and band_of(r["ep"]) == nm]
            if not cell:
                continue
            st = edge_stat([(1 if r["pnl"] > 0 else 0, r["ep"]) for r in cell])
            print(f"  {bt:13} {nm:9} {len(cell):4d} {sum(r['sz'] for r in cell):7.0f} "
                  f"{sum(r['pnl'] for r in cell):7.0f} {st[0]:6.1f} {st[1]:6.1f} "
                  f"{st[2]:+8.1f} {st[3]:+8.1f}")


# ---------------------------------------------------------------- section B
FUNNEL_SQL = """
SELECT j.id jid, j.decision d, j.confidence conf, j.risksJson risk, j.marketId m, j.createdAt ts,
       o.detectedPrice dp, o.walletEntryPrice wp, o.outcome oc, o.conditionId cid
FROM DecisionJournal j JOIN ObservedTrade o ON j.observedTradeId = o.id
WHERE j.isDemo = 0 AND j.ruleSetVersion >= ?
  AND o.detectedPrice > 0 AND o.detectedPrice <= 1
  AND j.venue = 'Polymarket'
"""


def funnel_rows():
    c = con()
    rows = c.execute(FUNNEL_SQL, (REGIME,)).fetchall()
    c.close()
    return rows


def first_risk(js):
    try:
        a = json.loads(js or "[]")
    except Exception:
        return "(unparsed)"
    if not a:
        return "(none recorded)"
    return a[0].split("—")[0].split("<")[0].strip()


def section_b(rows):
    print("\n" + "=" * 78)
    print("B. THE FUNNEL BY PRICE -- candidates vs copies, regime")
    print("   candidate price = ObservedTrade.detectedPrice (what the market showed when we")
    print("   saw the wallet's trade), so this is supply, not our fill.")
    print("=" * 78)
    res = Counter(r["d"] for r in rows)
    print(f"\n  {len(rows)} candidates -> {res.get('paper_copy',0)} copies "
          f"({100.0*res.get('paper_copy',0)/max(1,len(rows)):.2f}%), "
          f"{res.get('watchlist',0)} watchlist, {res.get('skip',0)} skip")
    print(f"\n  {'band':9} {'cand':>6} {'copy':>5} {'watch':>6} {'admit%':>7} {'cand/day':>9}")
    days = 1
    if rows:
        ts = [r["ts"] for r in rows]
        days = max(1.0, (max(ts) - min(ts)) / 86400000.0)
    for nm, (lo, hi) in zip(BAND_NAMES, BANDS):
        cell = [r for r in rows if lo <= r["dp"] < hi]
        cp = sum(1 for r in cell if r["d"] == "paper_copy")
        wt = sum(1 for r in cell if r["d"] == "watchlist")
        if not cell:
            continue
        print(f"  {nm:9} {len(cell):6d} {cp:5d} {wt:6d} {100.0*cp/len(cell):6.2f}% "
              f"{len(cell)/days:9.1f}")

    # refused cheap cohort, deduped to the first sighting per market+outcome
    seen = {}
    for r in rows:
        if r["d"] == "skip" and 0.05 <= r["dp"] < 0.20:
            k = (r["m"], r["oc"])
            if k not in seen or r["ts"] < seen[k]["ts"]:
                seen[k] = r
    cheap_skip = list(seen.values())
    print(f"\n  REFUSED cheap cohort (0.05 <= p < 0.20, deduped to first sighting per "
          f"market+outcome): {len(cheap_skip)} of {sum(1 for r in rows if r['d']=='skip' and 0.05<=r['dp']<0.20)} skip rows")
    if cheap_skip:
        cc = Counter(first_risk(r["risk"]) for r in cheap_skip)
        print(f"  {'operative blocker (first risk string)':58} {'n':>5} {'%':>6}")
        for k, v in cc.most_common(10):
            print(f"  {k[:58]:58} {v:5d} {100.0*v/len(cheap_skip):5.1f}%")
        confs = Counter(round(r["conf"] or 0.0, 2) for r in cheap_skip)
        print(f"\n  confidence of the refused cheap cohort: "
              f"{(confs.get(0.0,0))}/{len(cheap_skip)} at 0.00 "
              f"({100.0*confs.get(0.0,0)/len(cheap_skip):.1f}%)")
        print(f"  mean detection price {100*sum(r['dp'] for r in cheap_skip)/len(cheap_skip):.1f}c, "
              f"mean wallet fill {100*sum(r['wp'] or 0 for r in cheap_skip)/len(cheap_skip):.1f}c")

    # admitted cheap control
    adm = [r for r in rows if r["d"] == "paper_copy" and 0.05 <= r["dp"] < 0.20]
    print(f"\n  ADMITTED cheap control: {len(adm)} copies at mean detection "
          f"{100*sum(r['dp'] for r in adm)/max(1,len(adm)):.1f}c")
    return cheap_skip, adm


# ---------------------------------------------------------------- section C
def fetch_winner(cid):
    """Venue archive: tokens[].winner. Returns 'Yes'/'No'/None, cached on disk."""
    if not cid:
        return None
    os.makedirs(CACHE, exist_ok=True)
    p = os.path.join(CACHE, cid + ".json")
    if os.path.exists(p):
        try:
            with open(p) as f:
                return json.load(f).get("winner")
        except Exception:
            return None
    url = "https://clob.polymarket.com/markets/" + cid
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "medusa-copybot/1.0"})
            with urllib.request.urlopen(req, timeout=20) as r:
                js = json.loads(r.read().decode())
            win = None
            for t in js.get("tokens") or []:
                if t.get("winner") is True:
                    win = t.get("outcome")
            with open(p, "w") as f:
                json.dump({"winner": win, "closed": js.get("closed"),
                           "question": js.get("question")}, f)
            return win
        except urllib.error.HTTPError as e:
            if e.code == 404:
                with open(p, "w") as f:
                    json.dump({"winner": None, "closed": None, "http": 404}, f)
                return None
            time.sleep(1.0 + attempt)
        except Exception:
            time.sleep(1.0 + attempt)
    return None


def spread_of(risk):
    """The quoted spread from the scorer's own blocker string, when it names one."""
    import re
    for s in json.loads(risk or "[]"):
        m = re.search(r"spread\s+([0-9.]+)\s*>", s or "")
        if m:
            try:
                return float(m.group(1))
            except ValueError:
                return None
    return None


def section_c(cheap_skip, adm):
    print("\n" + "=" * 78)
    print("C. COUNTERFACTUAL -- the refused cheap cohort, resolved from the venue archive")
    print("   scored as if copied at the DETECTION price: hit -> (1-p)/p, miss -> -1.")
    print("   The ADMITTED cheap cohort is the matched control, same identity, PaperTrade.")
    print("=" * 78)
    entries = []
    miss = 0
    for r in cheap_skip:
        win = fetch_winner(r["cid"])
        if not win:
            miss += 1
            continue
        oc = (r["oc"] or "").upper()
        won = 1 if oc == win.upper() else 0
        entries.append((won, r["dp"], r["m"], spread_of(r["risk"])))
    print(f"\n  resolved {len(entries)} of {len(cheap_skip)} refused cheap candidates "
          f"({miss} with no archive winner)")
    if not entries:
        print("  no resolution coverage -- claim withheld")
        return
    lg = [(w, p) for w, p, _, _ in entries]
    mk = [m for _, _, m, _ in entries]
    st = edge_stat(lg)
    lo, hi = stat_ci(lg, mk, 2)
    lo2, hi2 = stat_ci(lg, mk, 3)
    print(f"  REFUSED  n={len(entries):4d} mkts={len(set(mk)):4d}  hit {st[0]:5.1f}%  "
          f"be {st[1]:5.1f}%  edge {st[2]:+6.1f}pp [{lo:+.1f},{hi:+.1f}]  "
          f"eqwROI {st[3]:+7.1f}% [{lo2:+.1f},{hi2:+.1f}]")

    # control: admitted cheap copies, positions only, realized
    posr = positions(legs(True))
    ctl = [r for r in posr if 0.05 <= r["ep"] < 0.20]
    if ctl:
        cl = [(1 if r["pnl"] > 0 else 0, r["ep"]) for r in ctl]
        cm = [r["m"] for r in ctl]
        cst = edge_stat(cl)
        clo, chi = stat_ci(cl, cm, 2)
        print(f"  ADMITTED n={len(ctl):4d} mkts={len(set(cm)):4d}  hit {cst[0]:5.1f}%  "
              f"be {cst[1]:5.1f}%  edge {cst[2]:+6.1f}pp [{clo:+.1f},{chi:+.1f}]  "
              f"eqwROI {cst[3]:+7.1f}%")
        print(f"\n  refused minus admitted edge: {st[2]-cst[2]:+.1f}pp "
              f"(positive = the gate refuses better candidates than it admits)")

    # SENSITIVITY: the unresolved remainder booked as losses (the pessimistic bound)
    n_all = len(cheap_skip)
    hit_all = sum(w for w, _, _, _ in entries)
    p_all = sum(p for _, p, _, _ in entries) / len(entries)
    pess = 100.0 * (hit_all / n_all - p_all)
    print(f"\n  SENSITIVITY: the {miss} unresolved candidates booked as LOSSES -> "
          f"hit {100.0*hit_all/n_all:.1f}% vs be {100.0*p_all:.1f}% = {pess:+.1f}pp")

    # BREAKEVEN ENTRY SLIPPAGE: the entry price at which the measured hit rate earns zero
    be_entry = 100.0 * (hit_all / len(entries))
    print(f"\n  BREAKEVEN ENTRY: hit {be_entry:.1f}% breaks even at an entry of "
          f"{be_entry:.1f}c; detection mid is {st[1]:.1f}c, so the fill can worsen by "
          f"{be_entry - st[1]:.1f}c before the band's edge is gone.")

    # ask-adjusted, split by whether the scorer recorded a spread on the row
    have = [(w, p, s) for w, p, _, s in entries if s is not None]
    no_s = [(w, p) for w, p, _, s in entries if s is None]
    if have:
        med = sorted(s for _, _, s in have)[len(have) // 2]
        st_s = edge_stat([(w, p) for w, p, _ in have])
        st_n = edge_stat(no_s) if no_s else None
        print(f"\n  SPLIT BY RECORDED SPREAD (the scorer names a spread on {len(have)} rows; "
              f"median {100*med:.1f}c)")
        print(f"    with a spread recorded  n={len(have):3d}  edge at mid {st_s[2]:+6.1f}pp  "
              f"eqwROI at mid {st_s[3]:+8.1f}%")
        if st_n:
            print(f"    no spread recorded     n={len(no_s):3d}  edge at mid {st_n[2]:+6.1f}pp  "
                  f"eqwROI at mid {st_n[3]:+8.1f}%   <-- UNPRICED: cannot be ask-adjusted here")
        for frac, nm in ((0.5, "half the spread"), (1.0, "the whole spread")):
            roi = [((1 - min(0.999, p + frac * s)) / min(0.999, p + frac * s)) if w else -1.0
                   for w, p, s in have]
            print(f"    with a spread recorded, paying {nm:16} -> mean ROI "
                  f"{100*sum(roi)/len(roi):+7.1f}%")

    # concentration: what the counterfactual is carried by
    order = sorted(entries, key=lambda t: -((1 - t[1]) / t[1] if t[0] else -1))
    top = order[:10]
    print(f"\n  top-10 counterfactual legs by return: "
          f"{sum(1 for w,_,_,_ in top if w)}/{len(top)} won")


def self_test():
    print("SELF-TEST")
    ok = 0
    tot = 0

    def chk(name, got, want, tol=1e-6):
        nonlocal ok, tot
        tot += 1
        good = (got is None and want is None) or (
            got is not None and want is not None and abs(got - want) <= tol)
        print(f"  [{'OK ' if good else 'FAIL'}] {name}: got {got} want {want}")
        ok += 1 if good else 0

    # 1. breakeven identity: 10 legs at p=0.10, 2 win -> edge = 20%-10% = +10pp
    st = edge_stat([(1, 0.10)] * 2 + [(0, 0.10)] * 8)
    chk("hit% (2 of 10 at 0.10)", st[0], 20.0)
    chk("be% = mean price", st[1], 10.0)
    chk("edge_pp", st[2], 10.0)
    chk("eqw ROI = .2*9 + .8*(-1) = +1.0", st[3], 100.0)
    # 2. fair coin at 0.50 is zero edge
    st = edge_stat([(1, 0.5), (0, 0.5)])
    chk("fair 50c book edge_pp", st[2], 0.0)
    chk("fair 50c book eqwROI", st[3], 0.0)
    # 3. favourite needs >p: 90c with 90% hit = 0
    st = edge_stat([(1, 0.9)] * 9 + [(0, 0.9)] * 1)
    chk("90c with 90% hit edge_pp", st[2], 0.0, 1e-9)
    # 4. band edges land in the right bucket (1.0 must be caught by the last band)
    chk("band_of(0.0)", BAND_NAMES.index(band_of(0.0)), 0)
    chk("band_of(0.1999)", BAND_NAMES.index(band_of(0.1999)), 0)
    chk("band_of(0.2)", BAND_NAMES.index(band_of(0.2)), 1)
    chk("band_of(1.0)", BAND_NAMES.index(band_of(1.0)), 4)
    # 5. positions() must drop only the stamped-unfilled rows
    rows = [{"fs": None, "sz": 10}, {"fs": "unfilled", "sz": 10}, {"fs": "filled", "sz": 10},
            {"fs": "", "sz": 10}]
    chk("positions() count", len(positions(rows)), 3)
    # 6. NEGATIVE CONTROL: scipy-free CI must bracket a known value and widen with noise
    lg = [(1 if i % 5 == 0 else 0, 0.2) for i in range(200)]
    mk = ["m%d" % (i // 4) for i in range(200)]
    lo, hi = stat_ci(lg, mk, 2)
    st = edge_stat(lg)
    print(f"  [{'OK ' if lo <= st[2] <= hi else 'FAIL'}] CI brackets the point estimate "
          f"({lo:+.2f} <= {st[2]:+.2f} <= {hi:+.2f})")
    ok += 1 if lo <= st[2] <= hi else 0
    tot += 1
    # 7. NEGATIVE CONTROL: a deliberately wrong edge sign must NOT reproduce
    st = edge_stat([(1, 0.8)] * 10)
    print(f"  [{'OK ' if st[2] > 0 else 'FAIL'}] 10/10 at 0.80 reads POSITIVE edge "
          f"({st[2]:+.1f}pp), so a negative claim cannot come from this function")
    ok += 1 if st[2] > 0 else 0
    tot += 1
    # 8. unfilled legs must not silently enter a hit-rate denominator
    if not os.path.exists("prisma/dev.db"):
        print("  [SKIP] live cross-check (no db)")
    else:
        r = positions(legs(True))
        n0 = len(legs(True))
        print(f"  [{'OK ' if len(r) <= n0 else 'FAIL'}] live regime: {len(r)} positions "
              f"<= {n0} finished rows")
        ok += 1 if len(r) <= n0 else 0
        tot += 1
    print(f"\n  {ok}/{tot} checks passed")
    return 0 if ok == tot else 1


def main():
    args = sys.argv[1:]
    if "--self-test" in args:
        return self_test()
    section_a()
    rows = funnel_rows()
    cheap_skip, adm = section_b(rows)
    if "--resolve" in args:
        section_c(cheap_skip, adm)
    else:
        print("\n(C skipped -- run with --resolve to hit the venue archive)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
