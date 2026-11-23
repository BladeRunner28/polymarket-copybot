#!/usr/bin/env python3
"""
TENOR — does the book's edge survive the capital-day it costs?

WHY THIS EXISTS
---------------
Every band table in this repo answers "what does a leg return per dollar risked". The ladder
turns on a different product: edge x capital x TURNOVER. The 2026-11-21 open-book read showed
where the capital-time actually sits: 322 of 384 open STANDARD legs are 100+ days old, and the
legs are season-long futures (Champions League winner, MLS Cup, ETH-by-December, 2027 French
presidential) that cannot resolve for another 4-14 months. Meanwhile the approved TTR floor
(STANDARD 2h -> 24h, `profit-floor-ttr-24h-standard`) only addresses the SHORT end.

So the question is symmetric and unasked:

    within the >24h population that the floor treats as one bloc earning +24.7%, is edge per
    capital-day flat in tenor -- or does it collapse as the market's remaining term grows?

If long-tenor legs earn materially less per capital-day, the highest-expectancy change is not
a bigger clip and not another exit rule: it is a tenor CEILING, which frees capital we cannot
currently recycle.

BASIS (stated once)
-------------------
population : PaperTrade isDemo=0, DecisionJournal.ruleSetVersion >= MIN_RULE, settled
             (status != open), deduped to the first leg per bot|wallet|market|outcome.
cost       : simulatedPositionSize = DOLLARS AT RISK, not shares (the trap the band report
             documents: size x entryPrice understates cost on cheap legs).
tenor      : timeToResolution in HOURS from the last MarketSnapshot at or before entry+15min,
             rejected as unclassified if that snapshot is older than 24h. Same axis and same
             source as scripts/profit-velocity.py and scripts/ttr-floor-shadow.py, reused
             deliberately: a shadow that derives its own axis becomes an argument about the
             instrument instead of the rule.
hold       : (closedAt ?? resolvedAt) - openedAt, floored at 0.05d.
cap-day    : size x hold_days.  $/1k cap-day = 1000 * PnL / cap-days.
CIs        : market-clustered bootstrap of the ratio, 2000 draws (PnL and cap-days resampled
             together, so the ratio's dependence is preserved).
READ-ONLY  : DB opened mode=ro, no prisma write, no RuleSet read/write.

RUN
  python3 scripts/profit-tenor.py
  python3 scripts/profit-tenor.py --min-rule 68 --since 2026-09-01
  python3 scripts/profit-tenor.py --selftest
"""
import argparse
import bisect
import json
import os
import sqlite3
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DB = os.path.join(ROOT, "prisma", "dev.db")
HOUR_MS = 3600_000

BUCKETS = [
    ("<2h", 0, 2),
    ("2-24h", 2, 24),
    ("1-7d", 24, 168),
    ("7-30d", 168, 720),
    ("30-90d", 720, 2160),
    ("90d+", 2160, float("inf")),
]
ORDER = [b[0] for b in BUCKETS] + ["unknown"]


def bucket(ttr_h):
    if ttr_h is None:
        return "unknown"
    for name, lo, hi in BUCKETS:
        if lo <= ttr_h < hi:
            return name
    return "unknown"


def con():
    c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    c.row_factory = sqlite3.Row
    return c


def ttr_for(c, market_id, at_ms, max_stale_ms=24 * HOUR_MS):
    row = c.execute(
        "select timeToResolution, collectedAt from MarketSnapshot "
        "where marketId=? and collectedAt<=? and timeToResolution is not null "
        "order by collectedAt desc limit 1",
        (market_id, at_ms + 15 * 60_000),
    ).fetchone()
    if row is None:
        return None
    if row["collectedAt"] is not None and (at_ms - row["collectedAt"]) > max_stale_ms:
        return None
    return float(row["timeToResolution"]) if row["timeToResolution"] is not None else None


def load_settled(c, min_rule, since_ms):
    rows = c.execute(
        """select p.id, p.botId, p.walletAddress, p.marketId, p.outcome, p.entryPrice,
                  p.simulatedPositionSize sz, p.realizedPnl pnl, p.openedAt, p.closedAt,
                  p.resolvedAt, p.status, j.ruleSetVersion v, j.confidence conf,
                  j.reasonsJson reasons, p.fillStatus fs
           from PaperTrade p join DecisionJournal j on j.id = p.decisionJournalId
           where p.isDemo=0 and p.status in ('closed','resolved') and p.realizedPnl is not null
             and j.ruleSetVersion >= ? and p.openedAt >= ?""",
        (min_rule, since_ms),
    ).fetchall()
    seen = set()
    out = []
    for r in rows:
        key = (r["botId"], r["walletAddress"], r["marketId"], r["outcome"])
        if key in seen:
            continue
        seen.add(key)
        end = r["resolvedAt"] or r["closedAt"]
        if not end or not r["openedAt"]:
            continue
        if not r["entryPrice"] or r["entryPrice"] <= 0 or not r["sz"] or r["sz"] <= 0:
            continue
        days = max((end - r["openedAt"]) / 86_400_000.0, 0.05)
        out.append(dict(id=r["id"], bot=r["botId"], wallet=r["walletAddress"],
                        market=r["marketId"], outcome=r["outcome"], px=r["entryPrice"],
                        ntl=float(r["sz"]), pnl=float(r["pnl"]), days=days,
                        cd=float(r["sz"]) * days, ms=r["openedAt"], status=r["status"],
                        v=r["v"], conf=r["conf"], fs=r["fs"] or "",
                        stair=("Short-TTR" in (r["reasons"] or ""))))
    for l in out:
        t = ttr_for(c, l["market"], l["ms"])
        l["ttr"] = t  # timeToResolution is ALREADY in hours (verified: 144.17 = 6d)
        l["tb"] = bucket(l["ttr"])
    return out


def load_open(c):
    rows = c.execute(
        """select botId, walletAddress, marketId, outcome, entryPrice, simulatedPositionSize sz,
                  unrealizedPnl upnl, openedAt
           from PaperTrade where isDemo=0 and status='open'"""
    ).fetchall()
    now = c.execute("select strftime('%s','now')*1000").fetchone()[0]
    out = []
    for r in rows:
        if not r["openedAt"]:
            continue
        age = max((now - r["openedAt"]) / 86_400_000.0, 0.0)
        t = ttr_for(c, r["marketId"], r["openedAt"])
        out.append(dict(bot=r["botId"], market=r["marketId"], outcome=r["outcome"],
                        px=r["entryPrice"], ntl=float(r["sz"]), upnl=float(r["upnl"] or 0),
                        age=age, cd=float(r["sz"]) * age,
                        ttr=t,  # hours, see load_settled
                        tb=bucket(t)))
    return out


def capday(legs):
    cd = sum(l["cd"] for l in legs)
    return (sum(l["pnl"] for l in legs) / cd) if cd else 0.0


def per1k(legs):
    return 1000 * capday(legs)


def roi(legs):
    n = sum(l["ntl"] for l in legs)
    return 100 * sum(l["pnl"] for l in legs) / n if n else 0.0


def boot_per1k(legs, reps=2000, seed=11):
    if not legs:
        return (float("nan"), float("nan"))
    by = {}
    for l in legs:
        by.setdefault(l["market"], []).append(l)
    keys = list(by)
    if len(keys) < 8:
        return (float("nan"), float("nan"))
    rng = np.random.default_rng(seed)
    vals = []
    for _ in range(reps):
        pick = rng.integers(0, len(keys), len(keys))
        s = [l for i in pick for l in by[keys[i]]]
        v = per1k(s)
        if np.isfinite(v):
            vals.append(v)
    if not vals:
        return (float("nan"), float("nan"))
    return (float(np.percentile(vals, 2.5)), float(np.percentile(vals, 97.5)))


def pct(x, d=1):
    return "n/a" if x is None else f"{x:+.{d}f}%"


def band_of(p):
    if p < 0.2:
        return "0.00-0.20"
    if p < 0.4:
        return "0.20-0.40"
    if p < 0.6:
        return "0.40-0.60"
    if p < 0.8:
        return "0.60-0.80"
    return "0.80-1.00"


BANDS = ["0.00-0.20", "0.20-0.40", "0.40-0.60", "0.60-0.80", "0.80-1.00"]


def boot_pnl(legs, reps=2000, seed=13):
    """Market-clustered bootstrap CI of TOTAL PnL (dollars), resampling markets."""
    if not legs:
        return (float("nan"), float("nan"))
    by = {}
    for l in legs:
        by.setdefault(l["market"], []).append(l)
    keys = list(by)
    if len(keys) < 8:
        return (float("nan"), float("nan"))
    rng = np.random.default_rng(seed)
    vals = []
    for _ in range(reps):
        pick = rng.integers(0, len(keys), len(keys))
        vals.append(sum(l["pnl"] for i in pick for l in by[keys[i]]))
    return (float(np.percentile(vals, 2.5)), float(np.percentile(vals, 97.5)))


def knife(legs, label, k_list=(1, 3, 10)):
    ci = boot_pnl(legs)
    print(f"\n  -- {label}: legs {len(legs)} / mkts {len({l['market'] for l in legs})} / "
          f"PnL ${sum(l['pnl'] for l in legs):.2f} {fmt_ci(ci)} / ROI {roi(legs):+.1f}% / "
          f"$/1k cd {per1k(legs):+.2f} / hold {np.mean([l['days'] for l in legs]):.1f}d")
    s = sorted(legs, key=lambda l: -l["pnl"])
    for k in k_list:
        rest = s[k:]
        if rest:
            print(f"     ex-top-{k:<2} PnL ${sum(l['pnl'] for l in rest):>9.2f}  "
                  f"ROI {roi(rest):>7.1f}%  $/1k cd {per1k(rest):>8.2f}")
    for b in ("STANDARD", "BANKROLL_200"):
        v = [l for l in legs if l["bot"] == b]
        if v:
            print(f"     {b:<13} n={len(v):>3} PnL ${sum(l['pnl'] for l in v):>9.2f} "
                  f"ROI {roi(v):>7.1f}%")
    w = {}
    for l in legs:
        w[l["wallet"]] = w.get(l["wallet"], 0) + l["pnl"]
    if w:
        top = max(w.items(), key=lambda kv: kv[1])
        print(f"     wallets {len(w)}, best wallet carries ${top[1]:.2f} "
              f"({top[1]/max(1e-9, sum(w.values())):.0%} of the cell's PnL)")
    ms = sorted(l["ms"] for l in legs)
    if len(ms) >= 4:
        mid = ms[len(ms) // 2]
        h1 = [l for l in legs if l["ms"] <= mid]
        h2 = [l for l in legs if l["ms"] > mid]
        print(f"     halves: {roi(h1):+.1f}% (n={len(h1)}) then {roi(h2):+.1f}% (n={len(h2)})")


def fmt_ci(ci):
    if not np.isfinite(ci[0]):
        return "[n/a]"
    return f"[{ci[0]:+.2f},{ci[1]:+.2f}]"


def selftest():
    assert bucket(None) == "unknown"
    assert bucket(1.9) == "<2h" and bucket(2.0) == "2-24h"
    assert bucket(23.9) == "2-24h" and bucket(24.0) == "1-7d"
    assert bucket(2400) == "90d+" and bucket(2159) == "30-90d"
    legs = [dict(market="a", ntl=100, pnl=10, cd=100), dict(market="b", ntl=100, pnl=-5, cd=50)]
    assert abs(roi(legs) - 2.5) < 1e-9
    assert abs(per1k(legs) - (5 / 150) * 1000) < 1e-9
    # a 90d+ future that returns +20% over 300 days earns far less per capital-day than
    # a 1-7d leg returning +5% over 3 days: the whole point of the axis
    fast = [dict(market="c", ntl=100, pnl=5, cd=100 * 3)]
    slow = [dict(market="d", ntl=100, pnl=20, cd=100 * 300)]
    assert per1k(fast) > 10 * per1k(slow)
    print("selftest 9/9 OK")


def table(title, legs, extra=None):
    print("\n" + "=" * 104)
    print(title)
    print(f"{'tenor':<9}{'legs':>6}{'mkts':>6}{'notional $':>12}{'PnL $':>10}{'ROI':>9}"
          f"{'hold d':>8}{'cap-days':>11}{'$/1k cd':>9}   CI")
    for name in ORDER:
        v = [l for l in legs if l["tb"] == name]
        if not v:
            continue
        ci = boot_per1k(v)
        print(f"{name:<9}{len(v):>6}{len({l['market'] for l in v}):>6}"
              f"{sum(l['ntl'] for l in v):>12.0f}{sum(l['pnl'] for l in v):>10.1f}"
              f"{roi(v):>8.1f}%{np.mean([l['days'] for l in v]):>8.1f}"
              f"{sum(l['cd'] for l in v):>11.0f}{per1k(v):>9.2f}   {fmt_ci(ci)}")
    if extra:
        print(extra)


def boot_delta(legs, dvals, reps=2000, seed=17):
    """Market-clustered bootstrap of a SUM of per-leg deltas (resample markets, sum members)."""
    import collections
    g = collections.defaultdict(list)
    for l, d in zip(legs, dvals):
        g[l["market"]].append(d)
    keys = list(g)
    if not keys:
        return (0.0, 0.0)
    rng = np.random.default_rng(seed)
    out = []
    for _ in range(reps):
        pick = rng.choice(len(keys), len(keys), replace=True)
        out.append(sum(sum(g[keys[i]]) for i in pick))
    a = np.array(out)
    return float(np.percentile(a, 2.5)), float(np.percentile(a, 97.5))


def sec_fill_basis(legs, days, cap=25.0):
    """S16-S19 — the same book, split by whether the venue ever traded at our price.

    WHY: every ROI in S1-S15 is booked at p(fill)=1. A maker bid that the market never
    came down to is not a position, and the resolver stamp covers only the legs its own
    resolver could reach. The venue's minute tape (keyless, retroactive, cached under
    data/fill-tape-cache) adjudicates all of them on one basis: did the MID for the token
    we bid on print at or below our price inside the horizon?

    touch(W) is necessary, not sufficient: queue position is unmodelled, so a touch is an
    UPPER bound on the fill and the phantom class is a LOWER bound on the phantom dollars.
    """
    import importlib.util as _iu
    _s = _iu.spec_from_file_location("_pft", os.path.join(HERE, "profit-fill-tape.py"))
    if _s is None or _s.loader is None:
        return
    pf = _iu.module_from_spec(_s)
    _s.loader.exec_module(pf)

    tlegs = [l for l in pf.load("2026-09-01")
             if l.get("status") != "open" and l.get("realizedPnl") is not None
             and (l.get("rv") or 0) >= 68]
    pf.classify(tlegs, workers=8)
    tape = {l["id"]: l for l in tlegs}

    def touch(leg, W):
        t = tape.get(leg["id"])
        if t is None:
            return None
        s = t.get("tape_series")
        if not s:
            return None
        t0 = t["openedTs"] // 1000
        sub = [p for t2, p in s if t2 <= t0 + W]
        if not sub:
            return None
        return min(sub) <= t["trueP"] + 0.001

    W5, W60 = 300, 3600
    print("\n== S16. FILL BASIS — did the venue ever trade at our price? (minutes tape, keyless) ==")
    print(f"   population {len(legs)} settled legs; tape-classified {sum(1 for l in legs if l['id'] in tape)}")
    print("   reach  W=300s (resolver's own 5-min fidelity) / W=3600s (a resting bid's hour):")
    for st, nm in (("filled", "resolver filled"), ("unfilled", "resolver unfilled"), ("", "resolver null")):
        v = [l for l in legs if l["fs"] == st]
        n5 = [l for l in v if touch(l, W5) is not None]
        t5 = sum(1 for l in n5 if touch(l, W5))
        n60 = [l for l in v if touch(l, W60) is not None]
        t60 = sum(1 for l in n60 if touch(l, W60))
        print(f"     {nm:<18} n={len(v):>3}  touch {t5}/{len(n5)} = {100*t5/max(len(n5),1):5.1f}%"
              f"   touch {t60}/{len(n60)} = {100*t60/max(len(n60),1):5.1f}%")
    for W, lab in ((W5, "5min"), (W60, "1hour")):
        print(f"   basis W={lab}:")
        for nm, f in (("all legs", lambda l: True),
                      ("touched  (reachable)", lambda l: touch(l, W) is True),
                      ("never touched (phantom)", lambda l: touch(l, W) is False),
                      ("no tape", lambda l: touch(l, W) is None)):
            v = [l for l in legs if f(l)]
            if not v:
                continue
            print(f"     {nm:<24} n={len(v):>3} ${sum(l['ntl'] for l in v):>7.0f} risk "
                  f"PnL ${sum(l['pnl'] for l in v):>8.1f} ROI {roi(v):>6.1f}%")

    def capped(l, d=cap):
        m = dict(l)
        if l["px"] < 0.20 and l["ntl"] > d:
            m["pnl"] = l["pnl"] * (d / l["ntl"])
            m["ntl"] = d
            m["cd"] = d * l["days"]
        return m

    B = [capped(l) for l in legs]
    print(f"\n== S17. the APPROVED $25 cheap-band cap (v73 apply script, never run), priced on both bases ==")
    print("   cap binds px<0.20 clips > $25 (C-200 only: STANDARD's BOT_LIMITS max is $20)")
    for nm, sel in (("booked (as filed)", lambda l: True),
                    ("touched W=5min", lambda l: touch(l, W5) is True),
                    ("touched W=1hour", lambda l: touch(l, W60) is True)):
        v = [l for l in legs if sel(l)]
        d = [(cap - l["ntl"]) * (l["pnl"] / l["ntl"])
             if (l["px"] < 0.20 and l["ntl"] > cap) else 0.0 for l in v]
        lo, hi = boot_delta(v, d)
        nb = sum(1 for l in v if l["px"] < 0.20 and l["ntl"] > cap)
        nz = sum(1 for x in d if x != 0.0)
        post = sum(l["pnl"] for l in v) + sum(d)
        nt = sum(l["ntl"] for l in v) - sum(l["ntl"] - cap for l in v
                                            if l["px"] < 0.20 and l["ntl"] > cap)
        print(f"     {nm:<18} clips {nb:>3} ({nz} priced)  delta ${sum(d):>+8.2f} "
              f"({sum(d)/days:+.2f}/day) CI [{lo:+.0f},{hi:+.0f}]  "
              f"post-cap ROI {100*post/nt if nt else 0:+.1f}%  "
              f"helped {sum(1 for x in d if x > 0)}/hurt {sum(1 for x in d if x < 0)}")

    def row(v, label, base=True):
        if not v:
            print(f"     {label:<30} empty")
            return
        s = sorted(v, key=lambda x: -x["pnl"])
        ex1 = roi(s[1:]) if len(s) > 1 else 0.0
        print(f"     {label:<30} n={len(v):>3} ${sum(l['ntl'] for l in v):>6.0f} "
              f"PnL ${sum(l['pnl'] for l in v):>+8.1f} ROI {roi(v):>+6.1f}% ex1 {ex1:>+6.1f}% "
              f"mkts {len({l['market'] for l in v}):>3}")

    R = [l for l in B if touch(l, W60) is True]
    print("\n== S18. POST-CAP, TOUCHED ONLY (W=1hour): where the ownable edge is ==")
    row(R, "post-cap reachable book")
    for b in BANDS:
        row([l for l in R if band_of(l["px"]) == b], f"band {b}")
    for lo_h, hi_h, lab in ((2, 24, "2-24h"), (24, 72, "24-72h"), (72, 168, "72h-7d"),
                            (168, float("inf"), "7d+")):
        for fl, nm in ((True, "short-TTR lane"), (False, "main path")):
            row([l for l in R if l["ttr"] is not None and lo_h <= l["ttr"] < hi_h and l["stair"] == fl],
                f"{lab} {nm}")
    cell = [l for l in R if not l["stair"] and l["ttr"] is not None and 2 <= l["ttr"] < 24]
    if cell:
        lo, hi = boot_pnl(cell)
        s = sorted(cell, key=lambda x: -x["pnl"])
        print(f"   the main-path short-tenor cell, under the knife: PnL CI [{lo:+.1f},{hi:+.1f}], "
              f"ex-top-1 {roi(s[1:]):+.1f}%, ex-top-3 {roi(s[3:]):+.1f}%, "
              f"ex-top-5 {roi(s[5:]):+.1f}%")

    print("\n== S19. what is LEFT to cap after the approved $25 (nothing stacks) ==")
    cand = (
        ("$10 cap, main-path 2-24h", lambda l: not l["stair"] and l["ttr"] is not None and 2 <= l["ttr"] < 24, 10),
        ("$15 cap, main-path 2-24h", lambda l: not l["stair"] and l["ttr"] is not None and 2 <= l["ttr"] < 24, 15),
        ("$20 cap, long-dated cheap (card)", lambda l: l["ttr"] is not None and l["ttr"] >= 168, 20),
        ("$10 cap, px<0.10", lambda l: l["px"] < 0.10, 10),
        ("$20 cap, px<0.20", lambda l: l["px"] < 0.20, 20),
    )
    for lab, pred, d in cand:
        tot = 0.0
        nb = 0
        for l in B:
            if touch(l, W60) is not True or not pred(l):
                continue
            if l["ntl"] > d:
                tot += (d - l["ntl"]) * (l["pnl"] / l["ntl"])
                nb += 1
        print(f"   {lab:<36} binds {nb:>3}  delta ${tot:>+8.2f} ({tot/days:+.2f}/day)  "
              f"[measured AFTER the approved cap]")

    print("\n   the two upsizes the data refuses (measured, not argued):")
    lane = [l for l in R if l["stair"]]
    if lane:
        s = sorted(lane, key=lambda x: -x["pnl"])
        wal = {}
        for l in lane:
            wal[l["wallet"]] = wal.get(l["wallet"], 0.0) + l["pnl"]
        top = max(wal.items(), key=lambda kv: kv[1])
        print(f"     short-TTR lane reached: {len(lane)} legs ROI {roi(lane):+.1f}%, "
              f"ex-top-1 {roi(s[1:]):+.1f}%, ex-top-3 {roi(s[3:]):+.1f}%, "
              f"ex-top-5 {roi(s[5:]):+.1f}%; one wallet carries ${top[1]:.0f} of ${sum(l['pnl'] for l in lane):.0f}")
    fav = [l for l in R if l["px"] >= 0.80]
    if fav:
        s = sorted(fav, key=lambda x: -x["pnl"])
        print(f"     0.80+ reached: {len(fav)} legs ROI {roi(fav):+.1f}% CI "
              f"[{boot_pnl(fav)[0]:+.0f},{boot_pnl(fav)[1]:+.0f}] ex-top-1 {roi(s[1:]):+.1f}%; "
              f"{sum(1 for l in fav if l['pnl'] < 0)} losses in the cell")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-rule", type=int, default=68)
    ap.add_argument("--since", default="2026-09-01")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        selftest()
        return

    import datetime as dt
    since_ms = int(dt.datetime.fromisoformat(a.since).replace(tzinfo=dt.timezone.utc).timestamp() * 1000)
    c = con()
    legs = load_settled(c, a.min_rule, since_ms)
    opens = load_open(c)

    days = (max(l["ms"] for l in legs) - min(l["ms"] for l in legs)) / 86_400_000.0
    print(f"population: {len(legs)} settled legs, {len({l['market'] for l in legs})} markets, "
          f"{days:.1f} days, ${sum(l['ntl'] for l in legs):,.0f} risk, "
          f"ruleSetVersion >= {a.min_rule}, deduped bot|wallet|market|outcome")
    unk = sum(1 for l in legs if l["tb"] == "unknown")
    print(f"tenor classified: {len(legs) - unk}/{len(legs)} ({unk} unclassified -> 'unknown' row)")

    table("S1. SETTLED BOOK BY TENOR AT ENTRY (cost = dollars at risk)", legs)

    print("\n== S2. where the capital-time goes (settled legs) ==")
    tot_cd = sum(l["cd"] for l in legs)
    for name in ORDER:
        v = [l for l in legs if l["tb"] == name]
        if not v:
            continue
        cd = sum(l["cd"] for l in v)
        print(f"  {name:<9} cap-days {cd:>10.0f} ({cd/tot_cd:>6.1%})   "
              f"PnL ${sum(l['pnl'] for l in v):>9.1f}   legs {len(v):>4}")

    print("\n== S3. the live open book by tenor at entry (capital parked) ==")
    print(f"{'tenor':<9}{'legs':>6}{'risk $':>10}{'booked upnl $':>15}{'age d':>8}{'cap-days':>11}")
    for name in ORDER:
        v = [l for l in opens if l["tb"] == name]
        if not v:
            continue
        print(f"{name:<9}{len(v):>6}{sum(l['ntl'] for l in v):>10.0f}"
              f"{sum(l['upnl'] for l in v):>15.2f}{np.mean([l['age'] for l in v]):>8.0f}"
              f"{sum(l['cd'] for l in v):>11.0f}")
    print(f"  open capital-days total {sum(l['cd'] for l in opens):,.0f}; "
          f"settled history {tot_cd:,.0f}")

    print("\n== S4. lane x tenor (is the loss a lane or a tenor?) ==")
    print(f"{'tenor':<9}{'lane':<14}{'legs':>6}{'notional $':>12}{'PnL $':>10}{'ROI':>9}{'$/1k cd':>10}")
    for name in ORDER:
        for b in ("STANDARD", "BANKROLL_200"):
            v = [l for l in legs if l["tb"] == name and l["bot"] == b]
            if len(v) < 3:
                continue
            print(f"{name:<9}{b:<14}{len(v):>6}{sum(l['ntl'] for l in v):>12.0f}"
                  f"{sum(l['pnl'] for l in v):>10.1f}{roi(v):>8.1f}%{per1k(v):>10.2f}")

    print("\n== S5. tenor x price band: is the tenor story just the cheap band again? ==")
    print(f"{'tenor':<9}" + "".join(f"{b:>18}" for b in BANDS))
    for name in ORDER:
        v = [l for l in legs if l["tb"] == name]
        if not v:
            continue
        cells = []
        for b in BANDS:
            w = [l for l in v if band_of(l["px"]) == b]
            cells.append(f"{len(w):>4}/{roi(w):>+7.1f}%" if w else f"{'-':>13}")
        print(f"{name:<9}" + "".join(f"{c:>18}" for c in cells))
    print("  (cell = legs / ROI; cost = dollars at risk)")

    print("\n== S6. the two cells that carry the book, under the knife ==")
    knife([l for l in legs if l["tb"] == "2-24h"], "2-24h (76% of settled legs)")
    knife([l for l in legs if l["tb"] == "1-7d"], "1-7d (the only positive cell)")
    lng = [l for l in legs if l["tb"] in ("7-30d", "30-90d", "90d+")]
    knife(lng, "7d+ settled (what the ceiling would block)")
    knife([l for l in legs if l["tb"] == "90d+"], "90d+ settled (n is the story)")

    print("\n== S7. ceiling shadow: what a tenor cap at entry would have done ==")
    print(f"{'cap':<8}{'blocked':>8}{'blocked $':>11}{'kept PnL $':>12}{'kept ROI':>10}"
          f"{'kept $/1k cd':>13}{'Δ cap-days':>12}")
    base_cd = tot_cd
    base_pnl = sum(l["pnl"] for l in legs)
    for cap_h, label in ((720, "30d"), (2160, "90d"), (4320, "180d"), (8760, "365d")):
        blocked = [l for l in legs if l["ttr"] is not None and l["ttr"] >= cap_h]
        kept = [l for l in legs if l not in blocked]
        print(f"{label:<8}{len(blocked):>8}{sum(l['ntl'] for l in blocked):>11.0f}"
              f"{sum(l['pnl'] for l in kept):>12.1f}{roi(kept):>9.1f}%"
              f"{per1k(kept):>13.2f}{-(base_cd - sum(l['cd'] for l in kept)):>12.0f}")
    print(f"  unblocked book: PnL ${base_pnl:.1f}, cap-days {base_cd:,.0f}, "
          f"$/1k cd {per1k(legs):.2f}")
    print("  NOTE: a cap can only be judged on blocked legs that SETTLED. The 6 settled 90d+")
    print("  legs are a selection (the 358 open ones have not resolved and cannot), so this")
    print("  table prices a tenor cap on evidence that structurally underweights the long end.")

    print("\n== S9. the short-TTR channel vs the main path, inside the same tenor ==")
    print("   the live RuleSet carries shortTtrMaxHours=72 / shortTtrSizeUsd=$10; a leg whose")
    print("   journal reasons name the Short-TTR lane was sized by that channel, the rest by Kelly.")
    print(f"{'window':<12}{'channel':<14}{'legs':>6}{'avg clip':>10}{'notional $':>12}"
          f"{'PnL $':>10}{'ROI':>9}{'$/1k cd':>10}")
    for lo, hi, label in ((2, 24, "2-24h"), (24, 72, "24-72h"), (72, 168, "72h-7d")):
        v0 = [l for l in legs if l["ttr"] is not None and lo <= l["ttr"] < hi]
        for flag, nm in ((True, "short-TTR"), (False, "main path")):
            v = [l for l in v0 if l["stair"] == flag]
            if not v:
                continue
            print(f"{label:<12}{nm:<14}{len(v):>6}{np.mean([l['ntl'] for l in v]):>10.1f}"
                  f"{sum(l['ntl'] for l in v):>12.0f}{sum(l['pnl'] for l in v):>10.1f}"
                  f"{roi(v):>8.1f}%{per1k(v):>10.2f}")

    print("\n== S10. clip tier inside the same-day window (is the loss a size, a price or a clock?) ==")
    tiers = [("<$15", 0, 15), ("$15-30", 15, 30), ("$30-60", 30, 60), ("$60+", 60, 1e9)]
    for lo, hi, label in ((2, 24, "2-24h"), (24, 72, "24-72h")):
        v0 = [l for l in legs if l["ttr"] is not None and lo <= l["ttr"] < hi]
        if not v0:
            continue
        print(f"  {label}:")
        for nm, a, b in tiers:
            v = [l for l in v0 if a <= l["ntl"] < b]
            if not v:
                continue
            print(f"    {nm:<8} n={len(v):>3} notional ${sum(l['ntl'] for l in v):>7.0f} "
                  f"PnL ${sum(l['pnl'] for l in v):>8.1f} ROI {roi(v):>7.1f}% "
                  f"avg px {np.mean([l['px'] for l in v]):.3f}")

    print("\n== S11. the two channels under the knife (no cell above is quoted before this) ==")
    knife([l for l in legs if l["stair"]], "all short-TTR legs (the $10 channel)")
    knife([l for l in legs if (not l["stair"]) and l["ntl"] >= 60], "main path, clip >= $60")
    knife([l for l in legs if (not l["stair"]) and 15 <= l["ntl"] < 30], "main path, clip $15-30")
    knife([l for l in legs if (not l["stair"]) and l["ttr"] is not None and 2 <= l["ttr"] < 24],
          "main path, 2-24h (the loss engine)")

    print("\n== S12. sizing-rule shadows (exact: PnL scales linearly in dollars at risk) ==")
    print("   each leg's dollars at risk is rescaled to min(size, cap) under the rule's scope;")
    print("   entry and the realised exit are unchanged, so PnL scales linearly and the")
    print("   counterfactual is exact on these outcomes. Fees would also scale linearly.")
    base_pnl = sum(l["pnl"] for l in legs)
    base_ntl = sum(l["ntl"] for l in legs)
    print(f"{'rule':<46}{'legs':>6}{'notional $':>12}{'book PnL':>10}{'ROI':>8}{'Δ $/day':>9}")

    def shadow(sel_fn, cap, label):
        tot, ntl = 0.0, 0.0
        n_sel = 0
        for l in legs:
            if sel_fn(l):
                s = min(l["ntl"], cap)
                n_sel += 1
            else:
                s = l["ntl"]
            tot += l["pnl"] * (s / l["ntl"])
            ntl += s
        print(f"{label:<46}{n_sel:>6}{ntl:>12.0f}{tot:>10.1f}{100*tot/ntl:>7.1f}%"
              f"{(tot-base_pnl)/days:>9.2f}")
        return tot

    print(f"{'baseline (no rule)':<46}{len(legs):>6}{base_ntl:>12.0f}{base_pnl:>10.1f}"
          f"{100*base_pnl/base_ntl:>7.1f}%{0:>9.2f}")
    shadow(lambda l: not l["stair"], 25, "A. $25 cap on every Kelly-path leg (global)")
    shadow(lambda l: (not l["stair"]) and l["px"] < 0.2, 25, "B. $25 cap on Kelly path, px < 0.20 (approved)")
    shadow(lambda l: l["ttr"] is not None and 2 <= l["ttr"] < 24, 10,
           "C. $10 cap on every leg resolving in 2-24h")
    shadow(lambda l: (not l["stair"]) and l["ttr"] is not None and 2 <= l["ttr"] < 24, 10,
           "D. $10 cap on Kelly path, 2-24h only")
    shadow(lambda l: (not l["stair"]) and l["ntl"] >= 60, 25,
           "E. $25 cap on Kelly-path clips >= $60 only")
    shadow(lambda l: (not l["stair"]) and l["px"] < 0.2 and l["ntl"] >= 60, 25,
           "F. $25 cap on cheap Kelly-path clips >= $60 (tight)")
    shadow(lambda l: (not l["stair"]) and l["px"] < 0.2 and l["ntl"] >= 60, 10,
           "G. $10 cap on cheap Kelly-path clips >= $60")
    print(f"  (Δ$/day = change in realised PnL over the {days:.1f}-day window)")

    print("\n== S13. the 72h-7d cell (the biggest positive number in the book) ==")
    w = [l for l in legs if l["ttr"] is not None and 72 <= l["ttr"] < 168]
    knife(w, "72h-7d, main path")
    if len(w) >= 8:
        ws = {}
        for l in w:
            ws[l["wallet"]] = ws.get(l["wallet"], 0) + l["pnl"]
        top = sorted(ws.items(), key=lambda kv: -kv[1])[:3]
        print("     top wallets: " + ", ".join(f"{a[:8]}.. ${b:.0f}" for a, b in top))
        bands = {}
        for l in w:
            bands[band_of(l["px"])] = bands.get(band_of(l["px"]), 0) + l["pnl"]
        print("     PnL by band: " + ", ".join(f"{k} ${v:.0f}" for k, v in sorted(bands.items())))

    print("\n== S14. basis check: who does the book itself call unfilled, and does the sign survive? ==")
    for nm, f in (("all booked legs", lambda l: True),
                  ("owned only (fillStatus != 'unfilled')", lambda l: l["fs"] != "unfilled")):
        v = [l for l in legs if f(l)]
        print(f"\n  {nm}: n={len(v)} notional ${sum(l['ntl'] for l in v):.0f} "
              f"PnL ${sum(l['pnl'] for l in v):.1f} ROI {roi(v):+.1f}%")
        for label, sel in (
            ("2-24h main path", lambda l: (not l["stair"]) and l["ttr"] is not None and 2 <= l["ttr"] < 24),
            ("clip >= $60 (cheap)", lambda l: l["ntl"] >= 60 and l["px"] < 0.2),
            ("7d+ settled", lambda l: l["tb"] in ("7-30d", "30-90d", "90d+")),
            ("72h-7d main path", lambda l: (not l["stair"]) and l["ttr"] is not None and 72 <= l["ttr"] < 168),
        ):
            w = [l for l in v if sel(l)]
            if w:
                print(f"    {label:<22} n={len(w):>3} PnL ${sum(l['pnl'] for l in w):>8.1f} "
                      f"ROI {roi(w):>7.1f}%")
    print("  NOTE: the paper model books PnL on legs it also labels `unfilled`; this section shows")
    print("  whether the headline cells depend on that ambiguity. It is a DATA contradiction in the")
    print("  book, not something this script resolves.")

    print("\n== S15. blocking (not capping) the 2-24h window, all lanes vs per lane ==")
    print("   this is the shape of the approved TTR floor (minTimeToResolutionHours 2 -> 24).")
    print("   That field is GLOBAL (src/lib/scoring/trade.ts:124 hard gate), while the")
    print("   approved shadow (data/ttr-floor-shadow.json) measures STANDARD only.")
    for nm, f in (("all lanes", lambda l: True),
                  ("STANDARD only", lambda l: l["bot"] == "STANDARD"),
                  ("BANKROLL_200 only", lambda l: l["bot"] == "BANKROLL_200")):
        v = [l for l in legs if f(l)]
        at = [l for l in v if l["ttr"] is not None and 2 <= l["ttr"] < 24]
        kept = [l for l in v if l not in at]
        if not at:
            continue
        print(f"  {nm:<20} book {len(v):>3} legs ${sum(l['ntl'] for l in v):>6.0f} "
              f"PnL ${sum(l['pnl'] for l in v):>7.1f} | blocked {len(at):>3} legs "
              f"${sum(l['ntl'] for l in at):>6.0f} PnL ${sum(l['pnl'] for l in at):>7.1f} "
              f"({roi(at):+.1f}%) | kept ROI {roi(kept):+.1f}%")

    print("\n  price-conditional variant: block 2-24h only BELOW 0.60, keep same-day favourites")
    for label, sel in (("block 2-24h, px<0.60", lambda l: l["ttr"] is not None and 2 <= l["ttr"] < 24 and l["px"] < 0.6),
                       ("block 2-24h, px<0.20", lambda l: l["ttr"] is not None and 2 <= l["ttr"] < 24 and l["px"] < 0.2)):
        blk = [l for l in legs if sel(l)]
        kept = [l for l in legs if not sel(l)]
        print(f"    {label:<24} blocks {len(blk):>3} legs ${sum(l['ntl'] for l in blk):>6.0f} "
              f"PnL ${sum(l['pnl'] for l in blk):>7.1f} ({roi(blk):+.1f}%) | book after "
              f"${sum(l['pnl'] for l in kept):>7.1f} ROI {roi(kept):+.1f}% "
              f"Δ$/day {(sum(l['pnl'] for l in kept) - sum(l['pnl'] for l in legs))/days:+.2f}")

    print("\n  overlap with the clip cap: legs that are BOTH 2-24h AND cheap (px<0.2) AND clip>=60")
    ov = [l for l in legs if l["ttr"] is not None and 2 <= l["ttr"] < 24
          and l["px"] < 0.2 and l["ntl"] >= 60]
    print(f"    {len(ov)} legs / ${sum(l['ntl'] for l in ov):.0f} notional / "
          f"PnL ${sum(l['pnl'] for l in ov):.1f} ({roi(ov):+.1f}%)")
    tier = [l for l in legs if l["px"] < 0.2 and l["ntl"] >= 60]
    res = [l for l in tier if l not in ov]
    print(f"    the cheap >=$60 tier overall: {len(tier)} legs / "
          f"${sum(l['ntl'] for l in tier):.0f} / PnL ${sum(l['pnl'] for l in tier):.1f} "
          f"({roi(tier):+.1f}%)")
    print(f"    residual the cap would still reach after the floor: {len(res)} legs / "
          f"${sum(l['ntl'] for l in res):.0f} / PnL ${sum(l['pnl'] for l in res):.1f} "
          f"({roi(res):+.1f}%)")
    print("    stacking both approved fixes is NOT additive: the floor already removes these legs,")
    print("    so the cap's measured value applies only to whatever the floor leaves behind.")

    sec_fill_basis(legs, days)

    print("\n== S8. the same tenor cap applied to today's open book ==")
    for cap_h, label in ((720, "30d"), (2160, "90d"), (4320, "180d"), (8760, "365d")):
        blocked = [l for l in opens if l["ttr"] is not None and l["ttr"] >= cap_h]
        print(f"  cap {label:<4} blocks {len(blocked):>3} open legs / "
              f"${sum(l['ntl'] for l in blocked):>6.0f} risk / "
              f"{sum(l['cd'] for l in blocked):>7.0f} capital-days already carried "
              f"/ booked upnl ${sum(l['upnl'] for l in blocked):>8.2f}")


if __name__ == "__main__":
    main()
