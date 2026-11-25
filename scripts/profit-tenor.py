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
                        endms=end,
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
          f"risk ${sum(l['ntl'] for l in legs):.0f} / "
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
    # S20/S22 helpers: the family rule is a PORT of src/lib/event-family.ts and must match it
    assert event_family("unl-nor-prt-2026-09-27-nor") == "unl-nor-prt-2026-09-27"
    assert event_family("unl-nor-prt-2026-09-27-prt") == "unl-nor-prt-2026-09-27"
    assert event_family("will-elon-musk-tweet-by-friday") == "will-elon-musk"
    # a losing leg must gain when its risk is cut; a small leg must be untouched
    assert abs(cap_delta(dict(ntl=100, pnl=-30), 25) - 22.5) < 1e-9
    assert cap_delta(dict(ntl=20, pnl=-6), 25) == 0.0
    # S25 resize: PnL scales exactly with dollars at risk, and a leg under the cap is unchanged
    big = resize(dict(ntl=100, pnl=-20, days=1.0), 10)
    assert big["ntl"] == 10 and abs(big["pnl"] + 2.0) < 1e-9
    small = dict(ntl=8, pnl=3, days=1.0)
    assert resize(small, 10) is small
    print("selftest 15/15 OK")


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


def event_family(market_id):
    """EXACT port of src/lib/event-family.ts (pre-registered family rule). Do not re-derive:
    the EOD line and this read must agree, so the rule is copied, not approximated.

      1. a slug carrying an ISO date -> family is everything up to and including the date
         (unl-nor-prt-2026-09-27-nor + -prt are ONE family);
      2. otherwise the first 3 dash tokens (will-<entity>-…, elon-musk-of-…).
    """
    import re as _re
    m = _re.match(r"^(.*?-\d{4}-\d{2}-\d{2})(?:-|$)", market_id or "")
    if m:
        return m.group(1)
    toks = (market_id or "").split("-")
    return "-".join(toks[:3]) if len(toks) >= 3 else (market_id or "")


def cap_delta(l, cap):
    """Exact dollar PnL change from rescaling one leg's risk to min(ntl, cap).

    PnL scales linearly in dollars at risk (entry and the realised exit are unchanged),
    so this is exact on outcomes rather than a re-simulation. Fees scale the same way;
    they are deliberately NOT netted here (profit-fee-net.py owns the fee law and a fee
    is ~2-4% of notional against a 5-20% effect -- it changes levels, not the ranking).
    """
    if l["ntl"] <= cap:
        return 0.0
    return (cap - l["ntl"]) * (l["pnl"] / l["ntl"])


def sec_clip_joint(legs, days, opens=None):
    """S20-S22 -- is the defect the BAND, the CLIP or the TENOR, and does a joint rule flip
    the ownable book?

    WHY: two approved/backlogged cards price the same $25 field on different scopes --
    profit-band-clip-rebalance (band-scoped, approved 2026-11-11) and profit-c200-clip-cap-25
    (lane-wide, +$102.9 over 17.8d). Both cannot be right, and neither was priced on the
    tape-reachable population. S20 puts every scope x cap x basis in one matrix.
    """
    import importlib.util as _iu
    _s = _iu.spec_from_file_location("_pft2", os.path.join(HERE, "profit-fill-tape.py"))
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
    BASES = (("booked", lambda l: True),
             ("touched 1h", lambda l: touch(l, W60) is True),
             ("touched 5m", lambda l: touch(l, W5) is True))
    SCOPES = (
        ("lane-wide (all Kelly-path legs)", lambda l: not l["stair"]),
        ("C-200 Kelly path (implementable)",
         lambda l: l["bot"] == "BANKROLL_200" and not l["stair"]),
        ("approved: px<0.20", lambda l: not l["stair"] and l["px"] < 0.20),
        ("tenor: 2-24h Kelly path",
         lambda l: (not l["stair"]) and l["ttr"] is not None and 2 <= l["ttr"] < 24),
        ("2-24h C-200 Kelly path (impl.)",
         lambda l: l["bot"] == "BANKROLL_200" and (not l["stair"])
         and l["ttr"] is not None and 2 <= l["ttr"] < 24),
        ("px<0.20 AND 2-24h",
         lambda l: (not l["stair"]) and l["px"] < 0.20
         and l["ttr"] is not None and 2 <= l["ttr"] < 24),
        ("every leg, incl. the $10 lane", lambda l: True),
    )

    print("\n== S20. CAP SCOPE x CAP LEVEL x BASIS -- the two contradictory clip cards, one table ==")
    print("   $/day in the cell's PnL over the %.1f-day window; (binds) = legs the cap resizes." % days)
    for bname, bfn in BASES:
        v = [l for l in legs if bfn(l)]
        base = sum(l["pnl"] for l in v)
        print(f"\n  basis {bname}: n={len(v)} notional ${sum(l['ntl'] for l in v):.0f} "
              f"PnL ${base:+.1f} ROI {roi(v):+.1f}%")
        print(f"    {'scope':<34}" + "".join(f"{('$'+str(c)):>16}" for c in (10, 20, 25, 40)))
        for label, sel in SCOPES:
            cells = []
            for c in (10, 20, 25, 40):
                d = [cap_delta(l, c) for l in v if sel(l)]
                nb = sum(1 for l in v if sel(l) and l["ntl"] > c)
                cells.append(f"{(sum(d)/days):>+9.2f}({nb:>2})")
            print(f"    {label:<34}" + "".join(f"{x:>16}" for x in cells))

    # ---- concentration of the CAP DELTA itself: is the recommendation one leg wide? ----
    print("\n   DELTA CONCENTRATION -- a $-of-day figure one leg wide is not a rule, it is a leg:")
    for lab, sel, c in (("$10 on px<0.20", lambda l: not l["stair"] and l["px"] < 0.20, 10.0),
                        ("$25 on px<0.20 (approved)", lambda l: not l["stair"] and l["px"] < 0.20, 25.0),
                        ("$10 on 2-24h Kelly path",
                         lambda l: (not l["stair"]) and l["ttr"] is not None and 2 <= l["ttr"] < 24, 10.0)):
        for bname, bfn in BASES:
            v = [l for l in legs if bfn(l)]
            pairs = sorted(((cap_delta(l, c), l) for l in v if sel(l)), key=lambda x: -x[0])
            d = [p[0] for p in pairs]
            if not d:
                continue
            k = len(pairs)
            print(f"    {lab:<26}{bname:<12}total ${sum(d):>+8.2f}  top-1 ${d[0]:>+7.2f} "
                  f"({d[0]/max(sum(d),1e-9):>5.0%})  ex-top-1 ${sum(d[1:]):>+8.2f}  "
                  f"ex-top-3 ${sum(d[min(3, k):]):>+8.2f}  ex-top-5 ${sum(d[min(5, k):]):>+8.2f}")

    print("\n  the same three rules with a market-clustered CI on the delta (dollars):")
    print(f"    {'rule':<42}{'basis':<12}{'binds':>6}{'delta $':>10}{'$/day':>8}   CI")
    HEAD = (
        ("approved $25, px<0.20", lambda l: not l["stair"] and l["px"] < 0.20, 25),
        ("$10, px<0.20 (same field, level fix)", lambda l: not l["stair"] and l["px"] < 0.20, 10),
        ("C-200 Kelly path, $10 (impl.)",
         lambda l: l["bot"] == "BANKROLL_200" and not l["stair"], 10),
        ("C-200 Kelly path, $25 (impl.)",
         lambda l: l["bot"] == "BANKROLL_200" and not l["stair"], 25),
        ("$10, 2-24h Kelly path", lambda l: (not l["stair"]) and l["ttr"] is not None and 2 <= l["ttr"] < 24, 10),
        ("$10, 2-24h C-200 Kelly (impl.)",
         lambda l: l["bot"] == "BANKROLL_200" and (not l["stair"])
         and l["ttr"] is not None and 2 <= l["ttr"] < 24, 10),
        ("$25, 2-24h C-200 Kelly (impl.)",
         lambda l: l["bot"] == "BANKROLL_200" and (not l["stair"])
         and l["ttr"] is not None and 2 <= l["ttr"] < 24, 25),
        ("$10, px<0.20 AND 2-24h", lambda l: (not l["stair"]) and l["px"] < 0.20 and l["ttr"] is not None and 2 <= l["ttr"] < 24, 10),
        ("$10, lane-wide Kelly-path", lambda l: not l["stair"], 10),
    )
    for label, sel, c in HEAD:
        for bname, bfn in BASES:
            v = [l for l in legs if bfn(l)]
            d = [cap_delta(l, c) if sel(l) else 0.0 for l in v]
            lo, hi = boot_delta(v, d)
            nb = sum(1 for l in v if sel(l) and l["ntl"] > c)
            print(f"    {label:<42}{bname:<12}{nb:>6}{sum(d):>+10.2f}"
                  f"{(sum(d)/days):>+8.2f}   [{lo:+.0f},{hi:+.0f}]")

    # ---- S21: the joint rule, and does either loss belong to the current regime? ----
    print("\n== S21. THE JOINT RULE -- the two caps are substitutes, so the LEVEL and the ORDER matter ==")

    def mp24(l):
        return (not l["stair"]) and l["ttr"] is not None and 2 <= l["ttr"] < 24

    def apply_pair(l, cheap_cap, mp_cap):
        s = l["ntl"]
        if cheap_cap and (not l["stair"]) and l["px"] < 0.20:
            s = min(s, cheap_cap)
        if mp_cap and mp24(l):
            s = min(s, mp_cap)
        m = dict(l)
        m["pnl"] = l["pnl"] * (s / l["ntl"])
        m["ntl"] = s
        m["cd"] = l["cd"] * (s / l["ntl"])
        return m

    CONFIGS = ((0, 0, "baseline (nothing shipped)"),
               (25, 0, "approved $25 cheap only"),
               (10, 0, "cheap only, but at $10"),
               (0, 10, "tenor $10 only"),
               (25, 10, "approved $25 cheap + tenor $10"),
               (10, 10, "$10 cheap + $10 tenor"))
    print(f"    {'rule':<32}{'basis':<12}{'n':>5}{'notional $':>12}{'PnL $':>10}{'ROI':>8}{'$/day':>8}   CI(PnL)")
    store = {}
    for cc, mc, lab in CONFIGS:
        for bname, bfn in BASES:
            v = [apply_pair(l, cc, mc) for l in legs if bfn(l)]
            ci = boot_pnl(v)
            store[(cc, mc, bname)] = (sum(l["pnl"] for l in v), roi(v), ci)
            print(f"    {lab:<32}{bname:<12}{len(v):>5}{sum(l['ntl'] for l in v):>12.0f}"
                  f"{sum(l['pnl'] for l in v):>+10.1f}{roi(v):>+7.1f}%"
                  f"{(sum(l['pnl'] for l in v)/days):>+8.2f}   {fmt_ci(ci)}")

    print("\n    MARGINAL: what each cap adds GIVEN the other is already shipped ($/day, and CI):")
    print(f"    {'marginal':<40}{'booked':>22}{'touched 1h':>22}{'touched 5m':>22}")
    for lab, a, b in (("approved $25 given tenor $10", (25, 10), (0, 10)),
                      ("tenor $10 given approved $25", (25, 10), (25, 0)),
                      ("tenor $10 given cheap $10", (10, 10), (10, 0)),
                      ("cheap $10 given tenor $10", (10, 10), (0, 10))):
        cells = []
        for bname, _ in BASES:
            d = (store[(a[0], a[1], bname)][0] - store[(b[0], b[1], bname)][0]) / days
            cells.append(f"{d:>+21.2f}")
        print(f"    {lab:<40}" + "".join(cells))
    print("    (a pair is worth shipping only if BOTH marginals are positive on the basis you trust)")

    ms_sorted = sorted(l["ms"] for l in legs)
    mid = ms_sorted[len(ms_sorted) // 2]
    last7 = max(ms_sorted) - 7 * 86_400_000
    print("\n   RECENCY -- is either loss a live property or a history artefact?")
    print(f"    {'cell':<40}{'half 1':>16}{'half 2':>16}{'last 7d':>16}")
    for lab, sel in (
        ("cheap $100 clips (px<0.20, >$25)", lambda l: (not l["stair"]) and l["px"] < 0.20 and l["ntl"] > 25),
        ("main-path 2-24h (all)", mp24),
        ("main-path 2-24h clips >=$60", lambda l: mp24(l) and l["ntl"] >= 60),
        ("main-path clips $15-30", lambda l: (not l["stair"]) and 15 <= l["ntl"] < 30),
    ):
        cells = []
        for sel2 in (lambda l: l["ms"] <= mid, lambda l: l["ms"] > mid, lambda l: l["ms"] >= last7):
            v = [l for l in legs if sel(l) and sel2(l)]
            cells.append(f"{len(v):>3} {roi(v):>+7.1f}%" if v else f"{'-':>12}")
        print(f"    {lab:<40}" + "".join(f"{x:>16}" for x in cells))
    print("    (cell = legs / ROI; half 1 + half 2 split at the median openedAt)")

    # ---- S22: does the loss concentrate in EVENT FAMILIES, i.e. is a per-event cap better? ----
    R = [l for l in legs if touch(l, W60) is True]
    print("\n== S22. EVENT-FAMILY CONCENTRATION (touched 1h) -- is a per-event cap a better shape? ==")
    fam = {}
    for l in R:
        fam.setdefault(event_family(l["market"]), []).append(l)
    tot_nt = sum(l["ntl"] for l in R)
    ranked = sorted(fam.items(), key=lambda kv: -sum(l["ntl"] for l in kv[1]))[:8]
    print(f"    {'family':<34}{'legs':>6}{'notional $':>12}{'% ntl':>7}{'PnL $':>9}{'ROI':>8}")
    for k, v in ranked:
        nt = sum(l["ntl"] for l in v)
        print(f"    {k[:34]:<34}{len(v):>6}{nt:>12.0f}{100*nt/tot_nt:>6.1f}%"
              f"{sum(l['pnl'] for l in v):>+9.1f}{roi(v):>+7.1f}%")
    print(f"    families in the reachable book: {len(fam)}; "
          f"max legs in one family {max(len(v) for v in fam.values())}")

    for cap in (25.0, 50.0):
        d = []
        nb = 0
        for k, v in fam.items():
            nt = sum(l["ntl"] for l in v)
            if nt <= cap:
                d.append(0.0)
                continue
            scale = cap / nt
            nb += len(v)
            d.append(sum(l["pnl"] * (scale - 1.0) for l in v))
        # boot_delta needs one delta per leg; build leg-aligned deltas instead
        dal = []
        for l in R:
            k = event_family(l["market"])
            v = fam[k]
            nt = sum(x["ntl"] for x in v)
            s = min(1.0, cap / nt) if nt > 0 else 1.0
            dal.append(l["pnl"] * (s - 1.0))
        lo, hi = boot_delta(R, dal)
        print(f"    per-EVENT cap ${cap:.0f} -> delta ${sum(dal):>+8.2f} "
              f"({sum(dal)/days:+.2f}/day) CI [{lo:+.0f},{hi:+.0f}], "
              f"resizes {sum(1 for l in R if sum(x['ntl'] for x in fam[event_family(l['market'])]) > cap)} legs")

    cheap60 = [l for l in R if (not l["stair"]) and l["px"] < 0.20 and l["ntl"] > 25]
    if cheap60:
        f = {}
        for l in cheap60:
            f.setdefault(event_family(l["market"]), []).append(l)
        print(f"    the approved cap's target class: {len(cheap60)} legs "
              f"in {len(f)} families (max {max(len(v) for v in f.values())} legs/family), "
              f"${sum(l['ntl'] for l in cheap60):.0f} notional, ${sum(l['pnl'] for l in cheap60):+.1f}")

    # ---- S23: ladder arithmetic -- what flow/clip a rung actually requires ----
    print("\n== S23. LADDER ARITHMETIC -- what rung 1 ($250/day) needs at the book's measured ROI ==")
    print("   profit/day = notional/day x ROI; notional/day = legs/day x avg clip.")
    v = [apply_pair(l, 0, 10) for l in legs]          # the recommended rule, booked
    r = roi(v)
    r1 = roi([apply_pair(l, 25, 0) for l in legs])     # approved $25, booked
    nd = sum(l["ntl"] for l in v) / days
    lpd = len(v) / days
    print(f"    today (tenor $10 rule): {lpd:.1f} settled legs/day x ${nd/lpd:.2f} avg clip = "
          f"${nd:.0f}/day of risk at {r:+.1f}% = ${nd*r/100:.2f}/day")
    for target in (250.0, 500.0):
        need_nt = target / (r / 100)
        need_lpd10 = need_nt / 10.0
        need_lpd25 = need_nt / 25.0
        need_lpd100 = need_nt / 100.0
        print(f"    ${target:.0f}/day at {r:+.1f}%: ${need_nt:,.0f}/day of risk -> "
              f"{need_lpd10:,.0f} legs/day at $10, {need_lpd25:,.0f} at $25, "
              f"{need_lpd100:,.0f} at $100  (today {lpd:.1f})")
    print(f"    the approved $25 rule alone reads {r1:+.1f}%; the $100 tier it exempts is the "
          f"tier that pays for the ladder and is measured at "
          f"{roi([l for l in legs if (not l['stair']) and l['ntl'] >= 60]) + 0.0:+.1f}%")
    # capacity: is the book actually short of cash to size into? (read-only, from BotBankroll)
    print("\n    capacity check (BotBankroll vs open notional) -- is capital the binding constraint?")
    for row in con().execute("select botId, cashBalance, principal from BotBankroll").fetchall():
        ow = [l for l in (opens or []) if l["bot"] == row["botId"]]
        print(f"      {row['botId']:<13} cash ${row['cashBalance']:>9.2f}  principal ${row['principal']:>9.2f}"
              f"  open ${sum(l['ntl'] for l in ow):>8.2f}  ({len(ow)} legs)")


def _tape_touch():
    """Load the venue minute tape once and return touch(leg, W) -> True/False/None.

    Same reader as sec_fill_basis (scripts/profit-fill-tape.py, cached). Touch is
    NECESSARY, not sufficient: queue position is unmodelled, so touched is an upper
    bound on what we own -- which is the direction that matters for S24 (it can only
    understate the adverse-selection gap, never overstate it).
    """
    import importlib.util as _iu
    _s = _iu.spec_from_file_location("_pft", os.path.join(HERE, "profit-fill-tape.py"))
    if _s is None or _s.loader is None:
        return None, {}
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

    return touch, tape


def resize(leg, cap):
    """Dollars at risk capped; PnL scales linearly (exact on a settled outcome)."""
    if leg["ntl"] <= cap:
        return leg
    m = dict(leg)
    m["pnl"] = leg["pnl"] * (cap / leg["ntl"])
    m["ntl"] = cap
    m["cd"] = cap * leg["days"]
    return m


def _worst_cells(legs, basis_label, k=3, min_n=5):
    """The loss cells a rule LEAVES BEHIND: what the kept book looks like under a microscope."""
    cells = {}
    for l in legs:
        tier = "<$15" if l["ntl"] < 15 else "$15-30" if l["ntl"] < 30 else "$30-60" if l["ntl"] < 60 else "$60+"
        cells.setdefault((l["tb"], band_of(l["px"]), tier), []).append(l)
    rows = [(v, key) for key, v in cells.items() if len(v) >= min_n]
    rows.sort(key=lambda r: sum(l["pnl"] for l in r[0]))
    for v, key in rows[:k]:
        print(f"      {basis_label} left behind: {key[0]:<7}{key[1]}  clip {key[2]:<6} "
              f"n={len(v):>3} ${sum(l['ntl'] for l in v):>6.0f} risk  "
              f"PnL ${sum(l['pnl'] for l in v):>+8.1f}  ROI {roi(v):>+6.1f}%")


def sec_owned(legs, days, opens):
    """S24-S26 -- the book we actually OWN, and what each candidate rule leaves standing.

    WHY THIS EXISTS
    ---------------
    Every $/day figure in S12-S23 prices a rule on the BOOKED ledger, where p(fill)=1.
    The book carries two independent stamps of whether that assumption held: the
    resolver's fillStatus and the venue's own minute tape. S24 prints them against each
    other. If the two agree, the booked book is the owned book. If they disagree, the
    difference is not a rounding error -- it is the sign of the strategy.
    """
    touch, tape = _tape_touch()
    W5, W60 = 300, 3600
    for l in legs:
        l["t5"] = touch(l, W5) if touch else None
        l["t60"] = touch(l, W60) if touch else None
    # OWNED = the resolver says filled, or the venue traded at our price inside 5 min.
    # CONFIRMED = resolver filled (the stricter, book-internal stamp).
    for l in legs:
        l["owned"] = (l["fs"] == "filled") or (l["t5"] is True)

    print("\n== S24. FILL-CLASS INVERSION -- the legs we OWN are the losers ==")
    print("   cost = dollars at risk; PnL = the ledger's own realisedPnL; CIs market-clustered")
    print(f"{'fillStatus':<12}{'legs':>6}{'mkts':>6}{'notional $':>12}{'PnL $':>10}{'ROI':>9}"
          f"{'$/1k cd':>9}   CI(PnL)")
    for st, nm in (("filled", "filled"), ("unfilled", "unfilled"), ("", "null")):
        v = [l for l in legs if l["fs"] == st]
        if not v:
            continue
        print(f"{nm:<12}{len(v):>6}{len({l['market'] for l in v}):>6}"
              f"{sum(l['ntl'] for l in v):>12.0f}{sum(l['pnl'] for l in v):>10.1f}"
              f"{roi(v):>8.1f}%{per1k(v):>9.2f}   {fmt_ci(boot_pnl(v))}")
    own = [l for l in legs if l["owned"]]
    not_own = [l for l in legs if not l["owned"]]
    print(f"\n   OWNED (resolver filled OR tape-touched <=5min): {len(own)} legs / "
          f"${sum(l['ntl'] for l in own):.0f} / PnL ${sum(l['pnl'] for l in own):.1f} "
          f"({roi(own):+.1f}%) {fmt_ci(boot_pnl(own))}")
    print(f"   NOT owned (neither stamp):                      {len(not_own)} legs / "
          f"${sum(l['ntl'] for l in not_own):.0f} / PnL ${sum(l['pnl'] for l in not_own):.1f} "
          f"({roi(not_own):+.1f}%) {fmt_ci(boot_pnl(not_own))}")
    gap = roi(own) - roi(not_own)
    print(f"   the sign gap is {gap:+.1f}pp of ROI; the booked book is the average of the two.")

    print("\n   do the two stamps agree? (rows = resolver, cols = venue tape within 5 min)")
    print(f"     {'':<12}{'touched':>10}{'never':>10}{'no tape':>10}")
    for st, nm in (("filled", "filled"), ("unfilled", "unfilled"), ("", "null")):
        v = [l for l in legs if l["fs"] == st]
        a = sum(1 for l in v if l["t5"] is True)
        b = sum(1 for l in v if l["t5"] is False)
        c = sum(1 for l in v if l["t5"] is None)
        print(f"     {nm:<12}{a:>10}{b:>10}{c:>10}")
    print("   the `unfilled` row is the defect: those legs are booked with PnL the venue says")
    print("   never traded at our price inside 5 minutes.")

    print("\n   the same book split by year-half, so a stale stamp cannot explain it")
    for st, nm in (("filled", "owned (filled)"), ("unfilled", "booked only (unfilled)")):
        v = [l for l in legs if l["fs"] == st]
        ms = sorted(l["ms"] for l in v)
        if len(ms) < 6:
            continue
        mid = ms[len(ms) // 2]
        h1 = [l for l in v if l["ms"] <= mid]
        h2 = [l for l in v if l["ms"] > mid]
        print(f"     {nm:<26} half1 n={len(h1):>3} ROI {roi(h1):>+7.1f}%   "
              f"half2 n={len(h2):>3} ROI {roi(h2):>+7.1f}%")

    # ---------------------------------------------------------------- S25
    print("\n== S25. THE KEPT BOOK -- a rule is judged by what it LEAVES, not what it cuts ==")
    print("   delta ($/day) = improvement; LEVEL = what the book earns per day afterwards.")
    print("   post-rule ROI is the number the ladder is actually paid on.")
    rules = [
        ("nothing (today)", lambda l: l),
        ("cheap $10 (C-200 only)", lambda l: resize(l, 10)
            if (l["bot"] == "BANKROLL_200" and not l["stair"] and l["px"] < 0.20 and l["ntl"] > 10) else l),
        ("cheap $10 (both lanes)", lambda l: resize(l, 10)
            if (not l["stair"] and l["px"] < 0.20 and l["ntl"] > 10) else l),
        ("tenor $10 (C-200, 2-24h)", lambda l: resize(l, 10)
            if (l["bot"] == "BANKROLL_200" and not l["stair"] and l["ttr"] is not None
                and 2 <= l["ttr"] < 24 and l["ntl"] > 10) else l),
        ("cheap $10 + tenor $10", lambda l: resize(l, 10)
            if ((not l["stair"] and l["px"] < 0.20 and l["ntl"] > 10)
                or (l["bot"] == "BANKROLL_200" and not l["stair"] and l["ttr"] is not None
                    and 2 <= l["ttr"] < 24 and l["ntl"] > 10)) else l),
        ("lane-wide $10 (all Kelly)", lambda l: resize(l, 10)
            if (l["bot"] == "BANKROLL_200" and not l["stair"] and l["ntl"] > 10) else l),
    ]
    print(f"   {'rule':<26}{'basis':<10}{'legs':>6}{'notional $':>12}{'PnL $':>10}{'ROI':>9}"
          f"{'ex-top-1':>10}{'ex-top-3':>10}{'$/day':>9}{'delta/d':>9}")
    base = {}
    for nm, f in rules:
        for basis, sel in (("booked", lambda l: True),
                           ("touched 1h", lambda l: l["t60"] is True),
                           ("touched 5m", lambda l: l["t5"] is True)):
            v = [f(l) for l in legs if sel(l)]
            if not v:
                continue
            pnl = sum(l["pnl"] for l in v)
            if nm.startswith("nothing"):
                base[basis] = pnl
            s = sorted(v, key=lambda l: -l["pnl"])
            e1 = roi(s[1:]) if len(s) > 1 else 0.0
            e3 = roi(s[3:]) if len(s) > 3 else 0.0
            print(f"   {nm:<26}{basis:<10}{len(v):>6}{sum(l['ntl'] for l in v):>12.0f}"
                  f"{pnl:>10.1f}{roi(v):>8.1f}%{e1:>9.1f}%{e3:>9.1f}%"
                  f"{pnl/days:>+9.2f}{(pnl - base.get(basis, 0.0))/days:>+9.2f}")
    print("\n   what the two surviving books still carry (touched 5m basis, cells with n>=5):")
    cheap_kept = [resize(l, 10) if (l["px"] < 0.20 and l["ntl"] > 10) else l
                  for l in legs if l["t5"] is True]
    tenor_kept = [resize(l, 10) if (l["bot"] == "BANKROLL_200" and not l["stair"]
                                    and l["ttr"] is not None and 2 <= l["ttr"] < 24
                                    and l["ntl"] > 10) else l
                  for l in legs if l["t5"] is True]
    _worst_cells(cheap_kept, "cheap $10")
    _worst_cells(tenor_kept, "tenor $10")

    # ---------------------------------------------------------------- S26
    print("\n== S26. THE LADDER ON THE OWNED BASIS -- the advance test is computed on which book? ==")
    import datetime as dt
    def day_key(ms):
        return dt.datetime.utcfromtimestamp(ms / 1000).date()
    daily_b, daily_o = {}, {}
    for l in legs:
        end = l.get("endms")
        k = day_key(end) if end else day_key(l["ms"])
        daily_b[k] = daily_b.get(k, 0.0) + l["pnl"]
        if l["owned"]:
            daily_o[k] = daily_o.get(k, 0.0) + l["pnl"]
    keys = sorted(set(daily_b) | set(daily_o))
    if keys:
        print(f"   settlement days: {keys[0]} .. {keys[-1]} ({len(keys)} days)")
        print(f"   {'window end':<12}{'booked 7d':>12}{'owned 7d':>12}{'ratio':>8}")
        for i in range(max(1, len(keys) - 6), len(keys)):
            end = keys[i]
            lo = end - dt.timedelta(days=6)
            b = sum(v for k, v in daily_b.items() if lo <= k <= end)
            o = sum(v for k, v in daily_o.items() if lo <= k <= end)
            print(f"   {str(end):<12}{b:>+12.2f}{o:>+12.2f}{(o / b if b else float('nan')):>8.2f}")
        print("   rung 1 = $250/day = $1,750 per rolling 7d window (advance basis, v2 policy)")
    b_tot = sum(l["pnl"] for l in legs) / days
    o_tot = sum(l["pnl"] for l in legs if l["owned"]) / days
    print(f"   book PnL/day: booked {b_tot:+.2f} | owned {o_tot:+.2f}")
    o_roi = roi([l for l in legs if l["owned"]])
    if o_roi > 0:
        print(f"   at the OWNED ROI ({o_roi:+.1f}%) rung 1 needs "
              f"${250 / (o_roi / 100):,.0f}/day of risk; "
              f"today's owned flow is ${sum(l['ntl'] for l in legs if l['owned']) / days:,.0f}/day")
    else:
        print(f"   at the OWNED ROI ({o_roi:+.1f}%) rung 1 is UNREACHABLE by sizing at any flow: "
              f"the owned book has no positive edge to scale. Owned flow is "
              f"${sum(l['ntl'] for l in legs if l['owned']) / days:,.0f}/day of risk.")
    print("\n   NOTE: `owned` here is a LOWER bound on the adverse-selection problem, not an")
    print("   estimate of live PnL -- the tape cannot see queue position, and the resolver's")
    print("   own stamp is the thing under test. It bounds the sign, not the magnitude.")


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
    sec_clip_joint(legs, days, opens)
    sec_owned(legs, days, opens)

    print("\n== S8. the same tenor cap applied to today's open book ==")
    for cap_h, label in ((720, "30d"), (2160, "90d"), (4320, "180d"), (8760, "365d")):
        blocked = [l for l in opens if l["ttr"] is not None and l["ttr"] >= cap_h]
        print(f"  cap {label:<4} blocks {len(blocked):>3} open legs / "
              f"${sum(l['ntl'] for l in blocked):>6.0f} risk / "
              f"{sum(l['cd'] for l in blocked):>7.0f} capital-days already carried "
              f"/ booked upnl ${sum(l['upnl'] for l in blocked):>8.2f}")


if __name__ == "__main__":
    main()
