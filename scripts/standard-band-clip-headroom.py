#!/usr/bin/env python3
"""§AM.7b — the STANDARD band factor's CLIP HEADROOM, and whether lifting the cap rescues it.

Read-only. Opens prisma/dev.db with mode=ro. Writes nothing.

AM.7 (profit-velocity.py) prices a five-band STANDARD size map but reports medians, so it
cannot say WHY the map underperforms: `clampPaperSize` (src/lib/safety.ts, BOT_LIMITS.STANDARD
{0.25, 20.00}) runs AFTER every factor (src/lib/paper.ts:180-198), so a leg booked at $18 takes
any factor >= 1.112 to the same $20. This section measures that headroom directly, then runs
the counterfactual the card names as its own refutation: raise the cap and see whether the map
becomes measurable.

Sections
  B.1  booked-size distribution per band and the effective multiplier each factor really gets
  B.2  as-is (bookable) arms: five-band strong map and the single <0.20 factor
  B.3  cap-lift counterfactual: the same arms at clamp $20 / $30 / $40 / $60
  B.4  power: live-era cadence and the leg count a market-clustered CI would need

Usage:  python3 scripts/standard-band-clip-headroom.py
"""
import os
import sqlite3
import time

import numpy as np

DB = os.environ.get("COPYBOT_DB", "prisma/dev.db")
RO = f"file:{os.path.abspath(DB)}?mode=ro"
BANDS = [(0.0, 0.2), (0.2, 0.4), (0.4, 0.6), (0.6, 0.8), (0.8, 1.0001)]
NAMES = ["<0.20", "0.2-0.4", "0.4-0.6", "0.6-0.8", "0.8-1.0"]
CAP = 20.00  # BOT_LIMITS.STANDARD.max
FLOOR = 0.25
STRONG = (2.0, 1.5, 0.5, 0.4, 0.2)
CHEAP = (2.0, 1.0, 1.0, 1.0, 1.0)
LIVE_ERA = int(time.mktime(time.strptime("2026-09-15", "%Y-%m-%d")) * 1000)


def band_of(p):
    for (lo, hi), nm in zip(BANDS, NAMES):
        if lo <= p < hi:
            return nm
    return None


def con():
    c = sqlite3.connect(RO)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA query_only=1")
    return c


def in_range(p, rng):
    if not rng:
        return False
    try:
        lo, hi = [float(x) for x in str(rng).split("-")]
    except Exception:
        return False
    return lo <= p < hi


def active_rules(c):
    row = c.execute("SELECT version, rulesJson FROM RuleSet ORDER BY version DESC LIMIT 1").fetchone()
    import json
    return row["version"], json.loads(row["rulesJson"] or "{}")


def load_legs(c, since_ms=0, skip_rng=""):
    rows = c.execute(
        """SELECT id, walletAddress, marketId, entryPrice AS px, simulatedPositionSize AS ntl,
                  realizedPnl AS pnl, openedAt
           FROM PaperTrade
           WHERE isDemo=0 AND botId='STANDARD' AND status IN ('closed','resolved')
             AND realizedPnl IS NOT NULL AND entryPrice > 0 AND simulatedPositionSize > 0
             AND openedAt >= ?""", (since_ms,)).fetchall()
    out = []
    for r in rows:
        if in_range(r["px"], skip_rng):
            continue
        nm = band_of(r["px"])
        if not nm:
            continue
        out.append({"id": r["id"], "wallet": r["walletAddress"], "market": r["marketId"],
                    "px": r["px"], "ntl": r["ntl"], "pnl": r["pnl"], "band": nm,
                    "ms": r["openedAt"]})
    return out


def pnl(legs):
    return sum(l["pnl"] for l in legs)


def roi(legs):
    n = sum(l["ntl"] for l in legs)
    return 100.0 * pnl(legs) / n if n else 0.0


def ex_top(legs, k=10):
    return sorted(legs, key=lambda l: -l["pnl"])[k:]


def apply_map(legs, sch, cap=CAP, neutral=False):
    tot0 = sum(l["ntl"] for l in legs)
    out = []
    for l in legs:
        w = sch[NAMES.index(l["band"])]
        new = min(cap, max(FLOOR, l["ntl"] * w))
        f = new / l["ntl"] if l["ntl"] else 1.0
        k = dict(l)
        k["ntl"] = new
        k["pnl"] = l["pnl"] * f
        out.append(k)
    if neutral:
        tot1 = sum(k["ntl"] for k in out)
        f = tot0 / tot1 if tot1 else 1.0
        for k in out:
            k["ntl"] *= f
            k["pnl"] *= f
    return out


def market_deltas(base, arm):
    """Per-market (arm PnL - base PnL), the vector the clustered bootstrap resamples."""
    mb, ma = {}, {}
    for l in base:
        mb[l["market"]] = mb.get(l["market"], 0.0) + l["pnl"]
    for l in arm:
        ma[l["market"]] = ma.get(l["market"], 0.0) + l["pnl"]
    keys = [k for k in mb if k in ma]
    return keys, np.array([ma[k] - mb[k] for k in keys], dtype=float)


def boot_delta(base, arm, reps=2000, seed=11):
    """Market-clustered paired bootstrap of (arm PnL - base PnL) on the same market resample."""
    keys, d = market_deltas(base, arm)
    if len(keys) < 8:
        return float("nan"), float("nan")
    rng = np.random.default_rng(seed)
    n = len(d)
    vals = np.array([d[rng.integers(0, n, n)].sum() for _ in range(reps)])
    return float(np.percentile(vals, 2.5)), float(np.percentile(vals, 97.5))


def window(c, label, since, skip, idx=None):
    legs = load_legs(c, since, skip)
    if not legs:
        print(f"\n   [{label}] no legs")
        return
    if idx is not None:
        legs = [l for l in legs if l["px"] < idx]
    print(f"\n   {label}: {len(legs)} legs, ${sum(l['ntl'] for l in legs):,.0f} at risk, "
          f"flat PnL {pnl(legs):+,.2f} (ROI {roi(legs):+.1f}%)")

    # ---- B.1 clip headroom
    print(f"   B.1 booked size and the multiplier each factor ACTUALLY gets (clamp ${CAP:.2f})")
    print(f"   {'band':8} {'legs':>5} {'med$':>7} {'p90$':>7} {'max$':>7} {'at cap%':>7} "
          f"{'med x2.0':>9} {'med x1.5':>9} {'med x0.5':>9}")
    for nm in NAMES:
        b = [l for l in legs if l["band"] == nm]
        if not b:
            continue
        sz = np.array([l["ntl"] for l in b])
        at_cap = 100.0 * float((sz >= CAP - 0.005).mean())

        def eff(w):
            got = np.minimum(CAP, np.maximum(FLOOR, sz * w)) / sz
            return float(np.median(got))

        print(f"   {nm:8} {len(b):>5} {np.median(sz):>7.2f} {np.percentile(sz,90):>7.2f} "
              f"{sz.max():>7.2f} {at_cap:>6.1f}% {eff(2.0):>9.3f} {eff(1.5):>9.3f} {eff(0.5):>9.3f}")
    vals, counts = np.unique(np.round([l["ntl"] for l in legs], 2), return_counts=True)
    order = np.argsort(-counts)[:4]
    print("   modal booked sizes: " + ", ".join(
        f"${vals[i]:.2f} {100.0*counts[i]/len(legs):.1f}%" for i in order))

    # ---- B.2 as-is arms at the live cap
    print(f"   B.2 as-is (bookable, no renormalisation) arms at the live ${CAP:.2f} cap")
    base = apply_map(legs, (1, 1, 1, 1, 1))
    bp = pnl(base)
    print(f"   baseline (flat/live) ex-top-10 ROI {roi(ex_top(base)):+.1f}%  |  "
          f"flat ROI {roi(base):+.1f}%")
    print(f"   {'arm':24} {'notional':>9} {'pnl':>9} {'dPnL':>8} {'CI low':>8} {'CI hi':>8} "
          f"{'ex10 ROI':>9} {'trim dPnL':>10} {'trim CI':>18}")
    for label_, sch in (("strong 2/1.5/.5/.4/.2", STRONG), ("cheap-only <0.20 x2.0", CHEAP)):
        g = apply_map(legs, sch)
        lo, hi = boot_delta(base, g)
        base_by_id = {b["id"]: b["pnl"] for b in base}
        drop = {x["id"] for x in sorted(g, key=lambda z: -(z["pnl"] - base_by_id[z["id"]]))[:3]}
        trim = [x for x in g if x["id"] not in drop]
        btrim = [x for x in base if x["id"] not in drop]
        tlo, thi = boot_delta(btrim, trim)
        print(f"   {label_:24} {sum(x['ntl'] for x in g):>9,.0f} {pnl(g):>+9,.0f} "
              f"{pnl(g)-bp:>+8,.0f} {lo:>+8,.0f} {hi:>+8,.0f} {roi(ex_top(g)):>+8.1f}% "
              f"{pnl(trim)-pnl(btrim):>+10,.0f} {f'[{tlo:+,.0f},{thi:+,.0f}]':>18}")

    # ---- B.3 cap-lift counterfactual
    print(f"   B.3 CAP-LIFT counterfactual — the card's own refutation clause, priced")
    print(f"   {'cap':>5} {'arm':22} {'notional':>9} {'pnl':>9} {'dPnL':>8} {'CI low':>8} {'CI hi':>8}")
    for cap in (20.0, 30.0, 40.0, 60.0):
        b_cap = apply_map(legs, (1, 1, 1, 1, 1), cap=cap)
        for label_, sch in (("strong", STRONG), ("cheap-only", CHEAP)):
            g = apply_map(legs, sch, cap=cap)
            lo, hi = boot_delta(b_cap, g)
            print(f"   {cap:>5.0f} {label_:22} {sum(x['ntl'] for x in g):>9,.0f} "
                  f"{pnl(g):>+9,.0f} {pnl(g)-pnl(b_cap):>+8,.0f} {lo:>+8,.0f} {hi:>+8,.0f}")

    # ---- B.5 the reopen trigger: the cheap band's own clustered ROI interval
    def boot_roi(sub, reps=2000, seed=7):
        mb, mn = {}, {}
        for l in sub:
            mb[l["market"]] = mb.get(l["market"], 0.0) + l["pnl"]
            mn[l["market"]] = mn.get(l["market"], 0.0) + l["ntl"]
        ks = [k for k in mb if mn.get(k)]
        if len(ks) < 8:
            return float("nan"), float("nan")
        p = np.array([mb[k] for k in ks])
        n = np.array([mn[k] for k in ks])
        rng = np.random.default_rng(seed)
        k = len(ks)
        out = np.empty(reps)
        for j in range(reps):
            idx = rng.integers(0, k, k)
            out[j] = 100.0 * p[idx].sum() / n[idx].sum()
        return float(np.percentile(out, 2.5)), float(np.percentile(out, 97.5))

    for nm in NAMES:
        b = [l for l in legs if l["band"] == nm]
        if len(b) < 8:
            continue
        rlo, rhi = boot_roi(b)
        print(f"   B.5 {nm:8} ROI {roi(b):+6.1f}% CI [{rlo:+6.1f},{rhi:+6.1f}] "
              f"on {len(b)} legs / {len({l['market'] for l in b})} markets "
              f"({'EXCLUDES zero' if rlo > 0 or rhi < 0 else 'spans zero'})")
    days = max((int(time.time() * 1000) - min(l["ms"] for l in legs)) / 86_400_000.0, 1.0)
    keys, d = market_deltas(apply_map(legs, (1, 1, 1, 1, 1)), apply_map(legs, CHEAP))
    mkts = len(keys)
    per_day = mkts / days
    sd = float(np.std(list(d), ddof=1))
    mean_d = float(np.mean(list(d)))
    hi_w = 1.96 * sd * np.sqrt(mkts)
    print(f"   B.4 power: {len(legs)/days:.2f} legs/day, {mkts} markets ({per_day:.2f}/day), "
          f"{len([l for l in legs if l['band'] == '<0.20'])/days:.2f} cheap legs/day")
    print(f"       cheap-only arm: total delta ${float(np.sum(d)):+,.0f} over {mkts} markets, "
          f"market SD ${sd:,.1f} -> CI half-width ${hi_w:,.0f} (observed bootstrap CI above)")
    for label_, sch in (("strong", STRONG), ("cheap-only", CHEAP)):
        k2, d2 = market_deltas(apply_map(legs, (1, 1, 1, 1, 1)), apply_map(legs, sch))
        m2 = float(np.mean(list(d2)))
        s2 = float(np.std(list(d2), ddof=1))
        if m2 == 0:
            continue
        need = (1.96 * s2 / abs(m2)) ** 2
        print(f"       {label_:10}: delta ${m2:+,.2f}/market -> {need:,.0f} markets "
              f"= {need/max(per_day, 1e-9):,.0f} days at this cadence")


def main():
    c = con()
    ver, rules = active_rules(c)
    skip = rules.get("standardSkipBandRange") or ""
    idx = float(rules.get("standardMaxEntryPrice") or 1.0)
    print("=" * 100)
    print("AM.7b STANDARD BAND FACTOR — clip headroom, and whether lifting the cap rescues the map")
    print("=" * 100)
    print(f"   RuleSet v{ver} | standardSkipBandRange={skip!r} | standardMaxEntryPrice={idx} | "
          f"BOT_LIMITS.STANDARD.max=${CAP:.2f}")
    print(f"   deadZoneSizeFactor={rules.get('deadZoneSizeFactor')} "
          f"longshotSizeFactor={rules.get('longshotSizeFactor')} "
          f"sweetSpotSizeUsd={rules.get('sweetSpotSizeUsd')} "
          f"kellyEnabled={rules.get('kellyEnabled')} bot={rules.get('botId') or '-'}")
    print("   cost basis: simulatedPositionSize = dollars at risk. PnL scaled linearly by the")
    print("   booked-size ratio (fixed entry/exit => PnL ∝ dollars at risk). No dedupe, matching")
    print("   AM.7's population. Below the live entry ceiling only (the reachable book).")
    for label, since in (("all-time", 0), ("90d", int((time.time() - 90 * 86400) * 1000)),
                         ("live-era >=2026-09-15", LIVE_ERA)):
        window(c, label, since, skip, idx)


if __name__ == "__main__":
    main()
