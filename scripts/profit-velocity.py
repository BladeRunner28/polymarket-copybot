#!/usr/bin/env python3
"""
CAPITAL VELOCITY + GROUND-TRUTH STOP -- the instrument behind the 2026-10-23 profit review.

WHY A SEPARATE FILE (the rule is "extend, don't fork"): profit-band-report.py answers
"what is the realised ROI of each entry band". That question is answered and is not the
open one. The open question is TURNOVER: profit = edge x capital x turnover, and three
reviews have optimised `edge` while never measuring the third factor on realised data.
The metrics here (dollars per capital-day, holding-time cohorts, ground-truth stop replay)
do not exist in the band report and would be a fourth competing definition of "band ROI"
if bolted onto it. Cost basis is identical by contract: simulatedPositionSize = dollars at
risk, NOT shares.

USAGE
    python3 scripts/profit-velocity.py           # T, U, V, W, X
    python3 scripts/profit-velocity.py --t30     # add the 30-day window cut (slower)

SECTIONS
  T. EDGE PER CAPITAL-DAY, lane x band, realised. The allocation table: ROI says how much
     each band earns per dollar RISKED; capital-day return says how much it earns per dollar
     HELD PER DAY. They rank bands differently, and only the second one compounds. Market-
     clustered bootstrap CI on the ratio (resample markets, recompute PnL / capital-days).
  U. CAPITAL-DAY AUDIT. Where all capital-time actually goes: finished legs vs the open book,
     and the PnL returned per capital-day in each. The open book cannot exit on STANDARD
     (stale-exit block is scoped to BANKROLL_200), so its capital-days are pure carry.
  V. GROUND-TRUTH STOP REPLAY. The 10-22 stop proposal was measured against stale marks
     (median 836h). This runs the same 168h rule on legs whose market has SETTLED, where the
     hold arm is the realised outcome (1.0 / 0.0) instead of a mark. This is the test of the
     10-22 proposal's own refutation clause (c): does 0.6-0.8 hold-to-settlement turn
     positive on settled legs?
  W. SIZING HEADROOM. Per lane: pre-cap clip vs maxPositionSize vs exposure cap. Who is
     pinned at a cap, and who has headroom -- and what the realised book says about scaling
     the lane that has headroom (ex-top-10, because both lanes' headline ROI is 10 legs).
  X. THE CAPITAL IMPLIED BY $5,000/DAY. Turn the ladder gap into the number that closes it:
     capital needed = target / (measured $ per capital-day), at the best robust bucket.
"""
import json
import os
import sqlite3
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import numpy as np

DB = "prisma/dev.db"
ARGS = sys.argv[1:]
T30 = "--t30" in ARGS
TRUTH_REFRESH = "--refresh-truth" in ARGS
TRUTH_RAW_DIR = os.path.join("data", ".clob-truth-raw")
BANDS = [(0.0, 0.2), (0.2, 0.4), (0.4, 0.6), (0.6, 0.8), (0.8, 1.0001)]
NAMES = ["<0.20", "0.2-0.4", "0.4-0.6", "0.6-0.8", "0.8-1.0"]


def band_of(p):
    for (lo, hi), nm in zip(BANDS, NAMES):
        if lo <= p < hi:
            return nm
    return None


def con():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    return c


def load_finished(c, since_ms=0):
    """Every closed/resolved real leg with a resolution OR close timestamp."""
    rows = c.execute(
        """SELECT id, botId, walletAddress, marketId, outcome, entryPrice,
                  simulatedPositionSize AS ntl, realizedPnl AS pnl, openedAt, closedAt,
                  resolvedAt, status
           FROM PaperTrade
           WHERE isDemo=0 AND status IN ('closed','resolved')
             AND realizedPnl IS NOT NULL AND openedAt >= ?""", (since_ms,)).fetchall()
    out = []
    for r in rows:
        if not r["entryPrice"] or r["entryPrice"] <= 0 or not r["ntl"] or r["ntl"] <= 0:
            continue
        end = r["resolvedAt"] or r["closedAt"]
        if not end:
            continue
        days = max((end - r["openedAt"]) / 86_400_000.0, 0.05)  # floor 72min: never divide by 0
        out.append({"id": r["id"], "bot": r["botId"], "wallet": r["walletAddress"],
                    "market": r["marketId"], "band": band_of(r["entryPrice"]),
                    "px": r["entryPrice"], "ntl": r["ntl"], "pnl": r["pnl"],
                    "days": days, "cd": r["ntl"] * days, "ms": r["openedAt"],
                    "status": r["status"]})
    return out


def capday(legs):
    """$ returned per $1 of capital-day -- the compounding objective."""
    cd = sum(l["cd"] for l in legs)
    return (sum(l["pnl"] for l in legs) / cd) if cd else 0.0


def roi(legs):
    n = sum(l["ntl"] for l in legs)
    return 100 * sum(l["pnl"] for l in legs) / n if n else 0.0


def ex_top(legs, k=10):
    return sorted(legs, key=lambda l: -l["pnl"])[k:]


def boot_capday(legs, reps=1500, seed=5):
    """Market-clustered bootstrap of $/capital-day (PnL and capital-days both resampled)."""
    if not legs:
        return (0.0, 0.0)
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
        sample = [l for i in pick for l in by[keys[i]]]
        v = capday(sample)
        if np.isfinite(v):
            vals.append(v)
    if not vals:
        return (float("nan"), float("nan"))
    return (np.percentile(vals, 2.5), np.percentile(vals, 97.5))


def usd_per_1k_cd(legs):
    """Readable unit: dollars earned per $1,000 of capital held for one day."""
    return 1000 * capday(legs)


# ---------------------------------------------------------------- T
def velocity_table(legs, label):
    print("\n" + "=" * 100)
    print(f"T. EDGE PER CAPITAL-DAY -- {label}")
    print("=" * 100)
    print("   $/1k-cd = dollars earned per $1,000 of capital held one day. ROI% = per dollar risked.")
    print(f"   {'lane':10} {'band':9} {'legs':>5} {'notional':>9} {'pnl':>9} {'ROI%':>7} "
          f"{'medD':>5} {'$/1k-cd':>8} {'CI low':>7} {'CI hi':>7} {'shCD%':>6} {'ex10 ROI%':>9} {'ex10 $/1k':>9}")
    for bot in ("STANDARD", "BANKROLL_200"):
        sub = [l for l in legs if l["bot"] == bot]
        total_cd = sum(l["cd"] for l in sub)
        for nm in NAMES:
            b = [l for l in sub if l["band"] == nm]
            if not b:
                continue
            lo, hi = boot_capday(b)
            print(f"   {bot[:10]:10} {nm:9} {len(b):>5} {sum(l['ntl'] for l in b):>9,.0f} "
                  f"{sum(l['pnl'] for l in b):>+9,.0f} {roi(b):>+7.1f} "
                  f"{np.median([l['days'] for l in b]):>5.1f} {usd_per_1k_cd(b):>+8.2f} "
                  f"{1000*lo:>+7.2f} {1000*hi:>+7.2f} "
                  f"{100*sum(l['cd'] for l in b)/total_cd:>5.1f}% "
                  f"{roi(ex_top(b)):>+9.1f} {usd_per_1k_cd(ex_top(b)):>+9.2f}")
    all_cd = sum(l["cd"] for l in legs)
    print(f"   {'ALL':10} {'':9} {len(legs):>5} {sum(l['ntl'] for l in legs):>9,.0f} "
          f"{sum(l['pnl'] for l in legs):>+9,.0f} {roi(legs):>+7.1f} "
          f"{np.median([l['days'] for l in legs]):>5.1f} {usd_per_1k_cd(legs):>+8.2f} "
          f"{'':>7} {'':>7} {'100.0%':>6} {roi(ex_top(legs)):>+9.1f} "
          f"{usd_per_1k_cd(ex_top(legs)):>+9.2f}")

    # Does the capital-day ranking agree with the ROI ranking? Stated explicitly, because the
    # whole point of the section is that the two orderings differ.
    def rank(fn, adj=""):
        d = {nm: fn([l for l in legs if l["band"] == nm]) for nm in NAMES
             if any(l["band"] == nm for l in legs)}
        return sorted(d.items(), key=lambda kv: -kv[1])
    print("\n   ranking by ROI%:        " + " > ".join(f"{k}({v:+.1f})" for k, v in rank(roi)))
    print("   ranking by $/capital-day: " + " > ".join(f"{k}({v:+.2f})" for k, v in rank(usd_per_1k_cd)))

    # Holding-time cohorts: is the capital-day number driven by ROI or by how long it sits?
    print(f"\n   holding-time cohorts (all lanes) -- same capital, different patience")
    print(f"   {'cohort':10} {'legs':>5} {'notional':>9} {'pnl':>9} {'ROI%':>7} {'$/1k-cd':>8}")
    for lo, hi, nm in ((0, 1, "<1d"), (1, 3, "1-3d"), (3, 7, "3-7d"), (7, 14, "7-14d"),
                       (14, 30, "14-30d"), (30, 10**4, ">30d")):
        b = [l for l in legs if lo <= l["days"] < hi]
        if not b:
            continue
        print(f"   {nm:10} {len(b):>5} {sum(l['ntl'] for l in b):>9,.0f} "
              f"{sum(l['pnl'] for l in b):>+9,.0f} {roi(b):>+7.1f} {usd_per_1k_cd(b):>+8.2f}")


# ---------------------------------------------------------------- U
def capital_audit(c, legs):
    print("\n" + "=" * 100)
    print("U. CAPITAL-DAY AUDIT -- where capital-time is spent, and what it returns")
    print("=" * 100)
    now = time.time() * 1000
    rows = c.execute(
        """SELECT botId, entryPrice, simulatedPositionSize AS ntl, currentPrice, openedAt,
                  outcome, entryPrice AS px
           FROM PaperTrade WHERE isDemo=0 AND status='open'""").fetchall()
    op = [dict(r) for r in rows if r["ntl"] and r["ntl"] > 0 and r["px"] and r["px"] > 0]
    fin_cd = sum(l["cd"] for l in legs)
    fin_pnl = sum(l["pnl"] for l in legs)
    print(f"   finished book : {len(legs):>5} legs  ${sum(l['ntl'] for l in legs):>9,.0f} notional "
          f"{fin_cd:>12,.0f} capdays  ${fin_pnl:>+9,.0f}  -> {1000*fin_pnl/fin_cd:>+6.2f} $/1k-cd")
    for bot in ("STANDARD", "BANKROLL_200"):
        sub = [t for t in op if t["botId"] == bot]
        if not sub:
            continue
        cd = sum(t["ntl"] * (now - t["openedAt"]) / 86_400_000.0 for t in sub)
        pnl_db = sum(t["ntl"] * (t["currentPrice"] / t["px"] - 1.0) for t in sub
                     if t["currentPrice"] is not None)
        age = np.median([(now - t["openedAt"]) / 86_400_000.0 for t in sub])
        print(f"   open {bot[:9]:9}: {len(sub):>5} legs  ${sum(t['ntl'] for t in sub):>9,.0f} notional "
              f"{cd:>12,.0f} capdays  ${pnl_db:>+9,.0f}  -> "
              f"{1000*pnl_db/cd if cd else 0:>+6.2f} $/1k-cd   (median age {age:.0f}d)")
    print("   NOTE: open-book PnL is an unrealised mark, so its $/capday is not a realised return.")

    # The squeeze: capital-days consumed per calendar day of operation, and the share of the
    # whole book's capital-time that sits in positions which cannot be exited on STANDARD.
    print("\n   capital-time split (realised legs vs open book)")
    for bot in ("STANDARD", "BANKROLL_200"):
        f = [l for l in legs if l["bot"] == bot]
        o = [t for t in op if t["botId"] == bot]
        ocd = sum(t["ntl"] * (now - t["openedAt"]) / 86_400_000.0 for t in o)
        fcd = sum(l["cd"] for l in f)
        if fcd + ocd:
            print(f"   {bot[:10]:10} finished {fcd:>12,.0f}  open {ocd:>12,.0f}  "
                  f"open share of capital-time {100*ocd/(fcd+ocd):>5.1f}%")


# ---------------------------------------------------------------- V
def boot_delta(legs, reps=1500, seed=17):
    """Market-clustered bootstrap of (stop - hold) as a fraction of notional."""
    by = {}
    for t in legs:
        by.setdefault(t["marketId"], []).append(t)
    keys = list(by)
    if len(keys) < 8:
        return (float("nan"), float("nan"))
    rng = np.random.default_rng(seed)
    vals = []
    for _ in range(reps):
        pick = rng.integers(0, len(keys), len(keys))
        s = [t for i in pick for t in by[keys[i]]]
        ntl = sum(t["ntl"] for t in s)
        if ntl:
            vals.append((sum(t["stop_pnl"] - t["pnl"] for t in s)) / ntl)
    if not vals:
        return (float("nan"), float("nan"))
    return (np.percentile(vals, 2.5), np.percentile(vals, 97.5))


def ground_truth_stop(c, legs):
    """168h stop on SETTLED legs: hold arm is the realised outcome, not a mark.
    Population = legs whose market resolved more than 168h after entry, i.e. exactly the legs
    the rule would have touched. For each, the stop sells at the first recorded snapshot at or
    after entry+168h; the hold arm is realisedPnl (settlement truth). PnL at mark m for entry p
    is stake*(m/p - 1) -- same convention as the band report.
    """
    print("\n" + "=" * 100)
    print("V. GROUND-TRUTH 168h STOP REPLAY -- settled legs only (hold arm = realised outcome)")
    print("=" * 100)
    rows = c.execute(
        """SELECT id, botId, marketId, outcome, entryPrice AS px, simulatedPositionSize AS ntl,
                  realizedPnl AS pnl, openedAt, resolvedAt
           FROM PaperTrade
           WHERE isDemo=0 AND status='resolved' AND resolvedAt IS NOT NULL
             AND (resolvedAt-openedAt) > 168*3600000 AND realizedPnl IS NOT NULL""").fetchall()
    by_mkt = {}
    for r in rows:
        if not r["px"] or r["px"] <= 0 or not r["ntl"] or r["ntl"] <= 0:
            continue
        by_mkt.setdefault(r["marketId"], []).append(dict(r))
    priced = []
    for mkt, ts in by_mkt.items():
        snaps = c.execute(
            "SELECT collectedAt, yesPrice, noPrice FROM MarketSnapshot WHERE marketId=? "
            "ORDER BY collectedAt", (mkt,)).fetchall()
        if not snaps:
            continue
        times = [s["collectedAt"] for s in snaps]
        import bisect
        for t in ts:
            target = t["openedAt"] + 168 * 3600 * 1000
            i = bisect.bisect_left(times, target)
            if i >= len(snaps):
                continue          # market went dark before the stop could fire: not in test set
            s = snaps[i]
            px = s["yesPrice"] if t["outcome"] == "YES" else s["noPrice"]
            if px is None or not (0 <= px <= 1):
                continue
            t["stop_px"] = px
            t["stop_age"] = (s["collectedAt"] - t["openedAt"]) / 3_600_000.0
            t["stop_pnl"] = t["ntl"] * (px / t["px"] - 1.0)
            t["band"] = band_of(t["px"])
            priced.append(t)
    if not priced:
        print("   no priceable settled legs")
        return
    print(f"   {len(priced)} settled legs ({len({t['marketId'] for t in priced})} markets) resolve >168h "
          f"after entry, median stop age {np.median([t['stop_age'] for t in priced]):.0f}h")
    print(f"   {'lane':10} {'scope':10} {'n':>4} {'notional':>9} {'hold':>9} {'stop':>9} "
          f"{'delta':>8} {'delta%ntl':>9} {'hold ROI':>8} {'stop ROI':>8}")
    for bot in ("STANDARD", "ALL"):
        sub_bot = priced if bot == "ALL" else [t for t in priced if t["botId"] == bot]
        for nm, lo, hi in (("0.2-1.0", 0.2, 1.01), ("0.4-1.0", 0.4, 1.01),
                           ("0.6-1.0", 0.6, 1.01), ("0.8-1.0", 0.8, 1.01), ("<0.4", 0.0, 0.4)):
            sub = [t for t in sub_bot if lo <= t["px"] < hi]
            if not sub:
                continue
            ntl = sum(t["ntl"] for t in sub)
            h = sum(t["pnl"] for t in sub)
            s = sum(t["stop_pnl"] for t in sub)
            print(f"   {bot[:10]:10} {nm:10} {len(sub):>4} {ntl:>9,.0f} {h:>+9,.0f} {s:>+9,.0f} "
                  f"{s-h:>+8,.0f} {100*(s-h)/ntl:>8.1f}% {100*h/ntl:>+7.1f} {100*s/ntl:>+7.1f}")
    # Per-band detail in the two bands yesterday's proposal hinges on. CI is market-clustered
    # (85 markets for 277 legs -- legs on one market are not independent) and ex-top-10 is
    # reported because every load-bearing number in this book so far has been 10 legs.
    print(f"\n   per-band (settled truth; delta CI = market-clustered bootstrap, % of notional)")
    for nm in NAMES:
        sub = [t for t in priced if t["band"] == nm]
        if not sub:
            continue
        ntl = sum(t["ntl"] for t in sub)
        h = sum(t["pnl"] for t in sub)
        s = sum(t["stop_pnl"] for t in sub)
        wins = sum(1 for t in sub if t["pnl"] > 0)
        lo, hi = boot_delta(sub)
        ex = sorted(sub, key=lambda t: -(t["pnl"] - t["stop_pnl"]))[:10]
        exdelta = sum(t["stop_pnl"] - t["pnl"] for t in sub) - sum(t["stop_pnl"] - t["pnl"] for t in ex)
        print(f"   {nm:9} n={len(sub):>3} ${ntl:>7,.0f} hold ${h:>+8,.0f} ({100*h/ntl:+.1f}%) "
              f"stop ${s:>+8,.0f} ({100*s/ntl:+.1f}%) delta ${s-h:>+7,.0f} "
              f"[{100*lo:+.0f}%,{100*hi:+.0f}% of ntl] ex-top10 ${exdelta:>+7,.0f} "
              f"settled hit {wins/len(sub)*100:.0f}%")
    # Exit cost, same as the band report: the stop pays a haircut on proceeds.
    tot = [t for t in priced if t["px"] >= 0.6]
    if tot:
        pr = sum(t["ntl"] * (t["stop_px"] / t["px"]) for t in tot)
        d0 = sum(t["stop_pnl"] - t["pnl"] for t in tot)
        print(f"\n   exit-cost: >=0.60 delta at 0/0.5/1/2% haircut: "
              + " / ".join(f"{d0 - h*pr:+,.0f}" for h in (0, 0.005, 0.01, 0.02))
              + f"   breakeven {100*d0/pr:.1f}% of proceeds")


# ---------------------------------------------------------------- W
def sizing_headroom(c, legs):
    print("\n" + "=" * 100)
    print("W. SIZING HEADROOM -- who is pinned at a cap, and what scaling the open lane implies")
    print("=" * 100)
    import json
    row = c.execute("SELECT rulesJson FROM RuleSet WHERE active=1").fetchone()
    rules = json.loads(row["rulesJson"])
    bank = {r["botId"]: dict(r) for r in c.execute("SELECT * FROM BotBankroll").fetchall()}
    print(f"   active ruleset v{rules.get('version','?')}: standardMaxEntryPrice={rules.get('standardMaxEntryPrice')}, "
          f"maxEntryPrice={rules.get('maxEntryPrice')}, "
          f"c200LongshotBandFactor={rules.get('c200LongshotBandFactor')}")
    for k in ("exposureCapBase", "exposureCapPerNetWorth", "maxOpenPositions", "standardMaxPositionSize",
              "c200MaxPositionSize", "maxPerMarket", "maxLegsPerMarket"):
        if k in rules:
            print(f"     {k} = {rules[k]}")
    for bot, b in bank.items():
        print(f"   {bot:12} principal ${b['principal']:>9,.2f}  cash ${b['cashBalance']:>9,.2f}  "
              f"clip ${b['minPositionSize']:.2f}-${b['maxPositionSize']:.2f}  "
              f"realised ${b['realizedPnl']:>8,.2f}")

    # Realised clip actually used, per lane (dollars at risk per leg).
    print(f"\n   realised clip (dollars at risk per leg) by lane")
    for bot in ("STANDARD", "BANKROLL_200"):
        q = c.execute(
            """SELECT simulatedPositionSize FROM PaperTrade
               WHERE isDemo=0 AND botId=? AND status IN ('closed','resolved') AND simulatedPositionSize>0""",
            (bot,)).fetchall()
        v = [r[0] for r in q]
        if v:
            print(f"   {bot[:10]:10} n={len(v):>5} median ${np.median(v):>7.2f} p90 ${np.percentile(v,90):>7.2f} "
                  f"max ${max(v):>7.2f}")

    # Scale shadow: the marginal dollar in each lane, and how much of it survives the tail test.
    print(f"\n   scale shadow -- what 1x / 3x / 8x the clip would have returned (linear in stake)")
    print(f"   {'lane':10} {'mult':>5} {'pnl':>9} {'ex-top10':>9} {'ex-top10 ROI%':>13} {'$/1k-cd x10':>11}")
    for bot in ("STANDARD", "BANKROLL_200"):
        sub = [l for l in legs if l["bot"] == bot]
        if not sub:
            continue
        e = ex_top(sub)
        for mult in (1, 3, 8):
            print(f"   {bot[:10]:10} {mult:>4}x {mult*sum(l['pnl'] for l in sub):>+9,.0f} "
                  f"{mult*sum(l['pnl'] for l in e):>+9,.0f} {roi(e):>+13.1f} "
                  f"{10*mult*usd_per_1k_cd(e):>+11.2f}")


# ---------------------------------------------------------------- X
def implied_capital(legs):
    print("\n" + "=" * 100)
    print("X. THE CAPITAL IMPLIED BY $5,000/DAY -- the ladder as a turnover equation")
    print("=" * 100)
    print("   PnL/day = capital x ($ per capital-day). Solve for capital at the measured rate.")
    print(f"   {'bucket':28} {'$/1k-cd':>8} {'capdays/leg':>11} {'capital for $5k/day':>20}")
    buckets = [("all lanes, all bands", legs)]
    buckets += [(f"{nm} (all lanes)", [l for l in legs if l["band"] == nm]) for nm in NAMES]
    for nm, b in buckets:
        if not b:
            continue
        r = 1000 * capday(b) / 1000.0       # $ per $ of capital-day
        cd_leg = sum(l["cd"] for l in b) / len(b)
        need = 5000 / r if r > 0 else float("inf")
        print(f"   {nm:28} {1000*capday(b):>+8.2f} {cd_leg:>11.1f} "
              + (f"${need:>19,.0f}" if np.isfinite(need) else f"{'never (rate<=0)':>20}"))
    # Best robust bucket: highest $/capday among buckets whose ex-top-10 ROI is still positive.
    cand = [(nm, 1000 * capday(b), roi(ex_top(b))) for nm, b in
            [(n, [l for l in legs if l["band"] == n]) for n in NAMES] if b]
    robust = [(nm, v, r) for nm, v, r in cand if r > 0]
    if robust:
        nm, v, r = max(robust, key=lambda t: t[1])
        print(f"\n   best robust bucket (ex-top-10 ROI > 0): {nm} at {v:+.2f} $/1k-cd, "
              f"ex-top-10 ROI {r:+.1f}%")
        print(f"   capital needed to earn $5,000/day there: ${5000/(v/1000):,.0f}")
    else:
        print("\n   no bucket survives the ex-top-10 test: no capital level reaches the target "
              "on measured edge.")


# ---------------------------------------------------------------- Y
def dedupe_audit(c):
    """Y. Does the 0.4-0.6 verdict survive the choice of dedupe basis?

    v63 hard-skips STANDARD entries at 0.40-0.60 citing "90d DEDUPED 1,027 legs, -7.67%,
    CI [-14.48,-0.89]". profit-band-report.load() dedupes by keeping the FIRST leg per
    (wallet, market, outcome). That is the right basis for one question (what does the first
    fill of a bet return) and the wrong basis for another (what does the capital deployed in
    this band return). This section prints both, plus the repeat legs separately, because a
    rule that skips the band blocks BOTH the first fill and every add.

    Windows: all-time and 90d (v63's own window). CI clustered by market on the all-legs basis.
    """
    print("\n" + "=" * 100)
    print("Y. DEDUPE-BASIS AUDIT -- 0.40-0.60, the band a live rule (v63) is skipping")
    print("=" * 100)
    now = time.time() * 1000
    for label, since in (("all-time", 0), ("90d", now - 90 * 86_400_000)):
        rows = c.execute(
            """SELECT walletAddress, marketId, outcome, entryPrice AS px,
                      simulatedPositionSize AS ntl, realizedPnl AS pnl, openedAt
               FROM PaperTrade
               WHERE isDemo=0 AND botId='STANDARD' AND status IN ('closed','resolved')
                 AND realizedPnl IS NOT NULL AND openedAt >= ?
                 AND entryPrice >= 0.40 AND entryPrice < 0.60
               ORDER BY openedAt ASC""", (since,)).fetchall()
        groups = {}
        for r in rows:
            if not r["px"] or r["px"] <= 0 or not r["ntl"] or r["ntl"] <= 0:
                continue
            k = (r["walletAddress"], r["marketId"], r["outcome"])
            groups.setdefault(k, []).append(dict(r))
        firsts = [g[0] for g in groups.values()]
        repeats = [r for g in groups.values() for r in g[1:]]
        allg = [r for g in groups.values() for r in g]

        def line(nm, legs):
            if not legs:
                print(f"   {label:9} {nm:26} {'0':>5}")
                return
            ntl = sum(l["ntl"] for l in legs)
            p = sum(l["pnl"] for l in legs)
            lo, hi = boot_roi(legs)
            print(f"   {label:9} {nm:26} {len(legs):>5} ${ntl:>9,.0f} ${p:>+8,.0f} "
                  f"{100*p/ntl:>+7.2f}% [{100*lo:>+6.1f},{100*hi:>+7.1f}]")

        print(f"\n   window {label}: {len(groups)} distinct bets, {len(allg)} legs")
        print(f"   {'':9} {'basis':26} {'n':>5} {'notional':>10} {'pnl':>9} {'ROI':>8}")
        line("first fill only (v63 basis)", firsts)
        line("repeat fills (adds)", repeats)
        line("ALL legs (capital basis)", allg)
        if allg:
            ex = sorted(allg, key=lambda l: -l["pnl"])[10:]
            ntl = sum(l["ntl"] for l in ex)
            print(f"   {label:9} {'ALL legs ex-top-10':26} {len(ex):>5} ${ntl:>9,.0f} "
                  f"${sum(l['pnl'] for l in ex):>+8,.0f} {100*sum(l['pnl'] for l in ex)/ntl:>+7.2f}%")
            mk = {}
            for l in allg:
                mk[l["marketId"]] = mk.get(l["marketId"], 0) + l["pnl"]
            top = sorted(mk.items(), key=lambda kv: -kv[1])[:5]
            print(f"   {label:9} top markets by PnL: "
                  + ", ".join(f"{k[:10]} ${v:+,.0f}" for k, v in top))
        # A rule that skips the band removes the adds too. What share of the band's
        # capital-days does v63 actually block?
        ntl_r = sum(l["ntl"] for l in repeats)
        ntl_a = sum(l["ntl"] for l in allg)
        if ntl_a:
            print(f"   {label:9} adds = {100*ntl_r/ntl_a:.0f}% of the band's notional, "
                  f"{100*sum(l['pnl'] for l in repeats)/ntl_r if ntl_r else 0:+.2f}% on those adds")


def boot_roi(legs, reps=1500, seed=29):
    by = {}
    for l in legs:
        by.setdefault(l["marketId"] if "marketId" in l else l["market"],
                      []).append(l)
    keys = list(by)
    if len(keys) < 8:
        return (float("nan"), float("nan"))
    rng = np.random.default_rng(seed)
    vals = []
    for _ in range(reps):
        pick = rng.integers(0, len(keys), len(keys))
        s = [l for i in pick for l in by[keys[i]]]
        n = sum(x["ntl"] for x in s)
        if n:
            vals.append(sum(x["pnl"] for x in s) / n)
    if not vals:
        return (float("nan"), float("nan"))
    return (np.percentile(vals, 2.5), np.percentile(vals, 97.5))


# ---------------------------------------------------------------- Z
TTL_BUCKETS = [(0, 6, "<6h"), (6, 24, "6-24h"), (24, 72, "1-3d"), (72, 168, "3-7d"),
               (168, 720, "7-30d"), (720, 2160, "30-90d"), (2160, 10**9, ">90d")]


_TTL_CACHE = {}


def ttl_edges(c, since_ms=0, bot=None):
    """Attach time-to-resolution AT ENTRY (decision-time variable, no lookahead) to each leg.

    Source: the last MarketSnapshot at or before entry+15min. timeToResolution is HOURS
    remaining. This is the only maturity variable a rule can act on before the trade, so it is
    the honest selection axis -- realised holding time is post-treatment and cannot be gated.
    """
    ck = (since_ms, bot)
    if ck in _TTL_CACHE:
        return _TTL_CACHE[ck]
    sql = """SELECT botId, marketId, entryPrice AS px, simulatedPositionSize AS ntl,
                    realizedPnl AS pnl, openedAt, closedAt, resolvedAt
             FROM PaperTrade
             WHERE isDemo=0 AND status IN ('closed','resolved') AND realizedPnl IS NOT NULL
               AND openedAt >= ?"""
    params = [since_ms]
    if bot:
        sql += " AND botId=?"
        params.append(bot)
    rows = c.execute(sql, params).fetchall()
    cache = {}
    out = []
    for r in rows:
        if not r["px"] or r["px"] <= 0 or not r["ntl"] or r["ntl"] <= 0:
            continue
        end = r["resolvedAt"] or r["closedAt"]
        if not end:
            continue
        key = (r["marketId"], r["openedAt"] // 3_600_000)
        if key not in cache:
            s = c.execute(
                """SELECT timeToResolution FROM MarketSnapshot
                   WHERE marketId=? AND collectedAt<=? AND timeToResolution IS NOT NULL
                   ORDER BY collectedAt DESC LIMIT 1""",
                (r["marketId"], r["openedAt"] + 900_000)).fetchone()
            cache[key] = s[0] if s else None
        ttl = cache[key]
        if ttl is None or ttl < 0:
            continue
        days = max((end - r["openedAt"]) / 86_400_000.0, 0.05)
        out.append({"bot": r["botId"], "market": r["marketId"], "px": r["px"], "ntl": r["ntl"],
                    "pnl": r["pnl"], "ttl": ttl, "days": days, "cd": r["ntl"] * days,
                    "ms": r["openedAt"]})
    _TTL_CACHE[ck] = out
    return out


def ttl_report(c):
    print("\n" + "=" * 100)
    print("Z. TIME-TO-RESOLUTION AT ENTRY -- the one maturity variable a rule can act on")
    print("=" * 100)
    print("   TTL = hours remaining at entry (last snapshot within 15min of the fill).")
    print("   Realised holding time is post-treatment and cannot be gated; TTL can.")
    for label, since in (("all-time", 0),
                         ("90d", int((time.time() - 90 * 86_400) * 1000))):
        legs = ttl_edges(c, since)
        if not legs:
            continue
        ntl_all = sum(l["ntl"] for l in legs)
        print(f"\n   window {label}: {len(legs)} legs with TTL (${ntl_all:,.0f})")
        print(f"   {'TTL':9} {'legs':>5} {'notional':>9} {'shNtl%':>7} {'pnl':>9} {'ROI%':>7} "
              f"{'CI':>16} {'medHold':>7} {'$/1k-cd':>8} {'ex10 ROI%':>9}")
        for lo, hi, nm in TTL_BUCKETS:
            b = [l for l in legs if lo <= l["ttl"] < hi]
            if not b:
                continue
            ntl = sum(l["ntl"] for l in b)
            p = sum(l["pnl"] for l in b)
            lo_ci, hi_ci = boot_roi(b)
            ex = sorted(b, key=lambda l: -l["pnl"])[10:]
            print(f"   {nm:9} {len(b):>5} {ntl:>9,.0f} {100*ntl/ntl_all:>6.1f}% {p:>+9,.0f} "
                  f"{100*p/ntl:>+7.1f} [{100*lo_ci:>+6.1f},{100*hi_ci:>+6.1f}] "
                  f"{np.median([l['days'] for l in b]):>7.1f} {usd_per_1k_cd(b):>+8.2f} "
                  f"{100*sum(l['pnl'] for l in ex)/sum(l['ntl'] for l in ex):>+9.1f}")
        # The gate this section exists to test.
        for nm, lo, hi in (("<24h", 0, 24), ("<72h", 0, 72), (">=72h", 72, 10**9),
                           (">=7d", 168, 10**9)):
            b = [l for l in legs if lo <= l["ttl"] < hi]
            if not b:
                continue
            ntl = sum(l["ntl"] for l in b)
            p = sum(l["pnl"] for l in b)
            lo_ci, hi_ci = boot_roi(b)
            print(f"   {nm:9} {len(b):>5} {ntl:>9,.0f} {100*ntl/ntl_all:>6.1f}% {p:>+9,.0f} "
                  f"{100*p/ntl:>+7.1f} [{100*lo_ci:>+6.1f},{100*hi_ci:>+6.1f}]")
    # Lane split on the two halves of the cut, so a lane-specific edge is not averaged away.
    print(f"\n   lane split, all-time (each cell = n / $pnl / ROI%)")
    legs = ttl_edges(c, 0)
    cuts = [("<24h", 0, 24), ("1-3d", 24, 72), ("3-7d", 72, 168),
            ("7-30d", 168, 720), (">=30d", 720, 10**9)]
    print(f"   {'lane':11} " + " ".join(f"{nm:>19}" for nm, _, _ in cuts))
    for bot in ("STANDARD", "BANKROLL_200"):
        cells = []
        for nm, lo, hi in cuts:
            b = [l for l in legs if l["bot"] == bot and lo <= l["ttl"] < hi]
            if not b:
                cells.append(f"{'-':>19}")
                continue
            ntl = sum(l["ntl"] for l in b)
            p = sum(l["pnl"] for l in b)
            cells.append(f"{len(b):>6}/{p:>+7,.0f}/{100*p/ntl:>+5.1f}%")
        print(f"   {bot[:11]:11} " + " ".join(cells))

    # IS TTL JUST A PROXY? Two checks before any rule may cite it: (1) does the effect hold
    # INSIDE each price band (0.4-0.6 is already skipped on STANDARD, so a band-driven effect
    # would be double-counting), and (2) does it hold inside each category (same-day sports
    # resolve fast, so TTL could be a category gate wearing a maturity hat).
    print(f"\n   Z1. band x TTL (all-time, all lanes) -- cell = n / ROI% / ex-top10 ROI%")
    print(f"   {'band':9} " + " ".join(f"{nm:>22}" for nm, _, _ in cuts))
    for nm in NAMES:
        cells = []
        for cn, lo, hi in cuts:
            b = [l for l in legs if l["px"] >= 0 and band_of(l["px"]) == nm
                 and lo <= l["ttl"] < hi]
            if len(b) < 25:
                cells.append(f"{'n=%d' % len(b):>22}")
                continue
            ntl = sum(l["ntl"] for l in b)
            p = sum(l["pnl"] for l in b)
            ex = sorted(b, key=lambda l: -l["pnl"])[10:]
            e_ntl = sum(l["ntl"] for l in ex)
            cells.append(f"{len(b):>5}/{100*p/ntl:>+6.1f}/{100*sum(l['pnl'] for l in ex)/e_ntl:>+6.1f}")
        print(f"   {nm:9} " + " ".join(cells))

    print(f"\n   Z2. category x TTL (all-time) -- cell = n / ROI%")
    cat = {}
    for r in c.execute("SELECT marketId, MAX(category) cat FROM MarketSnapshot GROUP BY marketId"):
        cat[r["marketId"]] = r["cat"] or "unknown"
    cov = sum(1 for l in legs if cat.get(l["market"], "unknown") not in ("unknown", None))
    print(f"   COVERAGE: {cov}/{len(legs)} legs have a MarketSnapshot.category "
          f"({100*cov/max(len(legs),1):.1f}%) -- the column is populated on a handful of rows, "
          f"so category attribution is NOT measurable from this table and no cell below is usable")
    if cov < 0.5 * len(legs):
        print("   (skipped: an attribution table computed on <50% coverage is an instrument "
              "defect, not a finding)")
        return
    for want in ("Sports", "Politics", "Crypto", "Economics", "Business", "Science", "Pop Culture"):
        cells = []
        for cn, lo, hi in cuts[:4]:
            b = [l for l in legs if cat.get(l["market"], "?") == want and lo <= l["ttl"] < hi]
            if not b:
                cells.append(f"{'-':>17}")
                continue
            ntl = sum(l["ntl"] for l in b)
            cells.append(f"{len(b):>5}/{100*sum(l['pnl'] for l in b)/ntl:>+7.1f}%")
        print(f"   {want:14} " + " ".join(cells))


def ttl_by_lane(c):
    """Z3. Who actually feeds the short-TTL block: the named short-TTR lane, or the regular funnel?

    The 2026-08 rules added a short-TTR lane (shortTtrMaxHours=72, minCopyScore=35, size $10,
    drift 0.05) whose own journal line calls it a 'daily PnL channel'. Section Z showed 43% of
    notional entering with <24h to resolution at -6.4%. This splits that block by HOW it was
    admitted, because a lane that is explicitly designed to admit short-TTR flow and a lane that
    merely fails to exclude it are different defects with different fixes.
    """
    print("\n" + "=" * 100)
    print("Z3. THE SHORT-TTL BLOCK BY ADMISSION PATH -- named lane vs regular funnel")
    print("=" * 100)
    now = int(time.time() * 1000)
    for label, since in (("all-time", 0), ("90d", now - 90 * 86_400_000)):
        legs = ttl_edges(c, since)
        print(f"\n   window {label}")
        print(f"   {'cohort':30} {'n':>5} {'notional':>9} {'pnl':>9} {'ROI%':>7} "
              f"{'ex10 ROI%':>9} {'$/1k-cd':>8}")
        for bot in ("BANKROLL_200", "STANDARD"):
            sub = [l for l in legs if l["bot"] == bot]
            if not sub:
                continue
            for nm, lo, hi in (("TTL<24h", 0, 24), ("TTL 24-72h", 24, 72),
                               ("TTL 72h-7d", 72, 168), ("TTL>=7d", 168, 10**9)):
                b = [l for l in sub if lo <= l["ttl"] < hi]
                if not b:
                    continue
                ntl = sum(l["ntl"] for l in b)
                p = sum(l["pnl"] for l in b)
                ex = sorted(b, key=lambda l: -l["pnl"])[10:]
                e_ntl = sum(l["ntl"] for l in ex)
                print(f"   {bot[:8] + ' ' + nm:30} {len(b):>5} {ntl:>9,.0f} {p:>+9,.0f} "
                      f"{100*p/ntl:>+7.1f} {100*sum(l['pnl'] for l in ex)/e_ntl:>+9.1f} "
                      f"{usd_per_1k_cd(b):>+8.2f}")
        # Cumulative marginal cost of a floor at each candidate level (what the rule removes).
        print(f"   {'marginal cost of a TTL floor (STANDARD)':30} {'n':>5} {'notional':>9} "
              f"{'pnl':>9} {'ROI%':>7}")
        sub = [l for l in legs if l["bot"] == "STANDARD"]
        for X in (6, 12, 24, 48, 72, 168):
            b = [l for l in sub if l["ttl"] < X]
            if not b:
                continue
            ntl = sum(l["ntl"] for l in b)
            print(f"   {'  block TTL < %dh' % X:30} {len(b):>5} {ntl:>9,.0f} "
                  f"{sum(l['pnl'] for l in b):>+9,.0f} {100*sum(l['pnl'] for l in b)/ntl:>+7.1f}")


def ttl_robustness(c):
    """Z4. Did I get fooled? STANDARD's TTL<24h block, examined four ways before it is a rule.

    (a) market-clustered CI, (b) ROI inside every price band with the 0.4-0.6 skip already in
    force, (c) the largest markets by PnL on BOTH tails -- 64 legs in one market is the failure
    mode this book keeps repeating, so ex-top-10 LEGS is not enough -- (d) month by month, so a
    single bad fortnight cannot carry the verdict.
    """
    print("\n" + "=" * 100)
    print("Z4. ROBUSTNESS OF THE STANDARD TTL<24h FINDING")
    print("=" * 100)
    legs = [l for l in ttl_edges(c, 0) if l["bot"] == "STANDARD"]
    short = [l for l in legs if l["ttl"] < 24]
    long_ = [l for l in legs if l["ttl"] >= 24]
    ntl = sum(l["ntl"] for l in short)
    lo, hi = boot_roi(short)
    print(f"   short block: {len(short)} legs ${ntl:,.0f} ${sum(l['pnl'] for l in short):+,.0f} "
          f"({100*sum(l['pnl'] for l in short)/ntl:+.1f}%) CI [{100*lo:+.1f},{100*hi:+.1f}]")
    ntl2 = sum(l["ntl"] for l in long_)
    print(f"   rest       : {len(long_)} legs ${ntl2:,.0f} ${sum(l['pnl'] for l in long_):+,.0f} "
          f"({100*sum(l['pnl'] for l in long_)/ntl2:+.1f}%)")

    print(f"\n   (b) inside each band (short TTL<24h vs rest), and the MARGINAL value given v63")
    for wlabel, since in (("all-time", 0),
                          ("90d", int((time.time() - 90 * 86_400) * 1000))):
        wl_legs = [l for l in ttl_edges(c, since) if l["bot"] == "STANDARD"]
        s_all = [l for l in wl_legs if l["ttl"] < 24]
        r_all = [l for l in wl_legs if l["ttl"] >= 24]
        print(f"   -- window {wlabel}: {len(s_all)} short legs ${sum(l['ntl'] for l in s_all):,.0f} "
              f"${sum(l['pnl'] for l in s_all):+,.0f} | {len(r_all)} rest "
              f"${sum(l['pnl'] for l in r_all):+,.0f}")
        print(f"   {'band':9} {'short n':>7} {'short $pnl':>10} {'short ROI%':>10} "
              f"{'rest n':>7} {'rest $pnl':>10} {'rest ROI%':>9}")
        for nm in NAMES:
            b = [l for l in s_all if band_of(l["px"]) == nm]
            r = [l for l in r_all if band_of(l["px"]) == nm]
            if not b or not r:
                continue
            print(f"   {nm:9} {len(b):>7} {sum(l['pnl'] for l in b):>+10,.0f} "
                  f"{100*sum(l['pnl'] for l in b)/sum(l['ntl'] for l in b):>+10.1f} "
                  f"{len(r):>7} {sum(l['pnl'] for l in r):>+10,.0f} "
                  f"{100*sum(l['pnl'] for l in r)/sum(l['ntl'] for l in r):>+9.1f}")
        # v63 (live since 2026-10-20) already blocks NEW 0.4-0.6 entries, so most of the gross
        # number is already bought. The marginal value of a TTL floor is what it adds on the
        # bands that are still open -- stated here because it is a quarter of the headline.
        still_open = [l for l in s_all if band_of(l["px"]) != "0.4-0.6"]
        m_lo, m_hi = boot_roi(still_open)
        print(f"   marginal value of the floor ON TOP OF v63 (bands v63 leaves open): "
              f"{len(still_open)} legs ${sum(l['ntl'] for l in still_open):,.0f} -> "
              f"${sum(l['pnl'] for l in still_open):+,.0f} "
              f"({100*sum(l['pnl'] for l in still_open)/sum(l['ntl'] for l in still_open):+.1f}%) "
              f"CI [{100*m_lo:+.1f},{100*m_hi:+.1f}]")

    print(f"\n   (c) largest markets by PnL inside the short block (both signs)")
    mk = {}
    for l in short:
        d = mk.setdefault(l["market"], {"pnl": 0.0, "ntl": 0.0, "n": 0})
        d["pnl"] += l["pnl"]; d["ntl"] += l["ntl"]; d["n"] += 1
    order = sorted(mk.items(), key=lambda kv: kv[1]["pnl"])
    for k, v in order[:6] + order[-4:]:
        print(f"   {k[:34]:34} n={v['n']:>4} ${v['ntl']:>7,.0f} ${v['pnl']:>+8,.0f}")
    top5_loss = sum(v["pnl"] for _, v in order[:5])
    print(f"   short block ex-top-5-loss-markets: ${sum(l['pnl'] for l in short) - top5_loss:+,.0f} "
          f"on ${ntl - sum(v['ntl'] for _, v in order[:5]):,.0f}")

    print(f"\n   (c2) wallet concentration inside the short block")
    # ttl_edges does not carry the wallet, so re-derive the same cohort with a join on
    # (marketId, openedAt) -- the pair is unique per leg in this book.
    wl = {}
    rows = c.execute(
        """SELECT p.walletAddress w, p.marketId m, p.openedAt o, p.simulatedPositionSize n,
                  p.realizedPnl p
           FROM PaperTrade p WHERE p.isDemo=0 AND p.botId='STANDARD'
             AND p.status IN ('closed','resolved') AND p.realizedPnl IS NOT NULL""").fetchall()
    short_keys = {(l["market"], l["ms"]) for l in short}
    for r in rows:
        if (r["m"], r["o"]) not in short_keys:
            continue
        d = wl.setdefault(r["w"], {"pnl": 0.0, "ntl": 0.0, "n": 0})
        d["pnl"] += r["p"]; d["ntl"] += r["n"]; d["n"] += 1
    order_w = sorted(wl.items(), key=lambda kv: -kv[1]["ntl"])
    tot_ntl = sum(v["ntl"] for v in wl.values())
    for w, v in order_w[:5]:
        print(f"   {w[:14]:14} n={v['n']:>4} ${v['ntl']:>7,.0f} "
              f"({100*v['ntl']/tot_ntl:>4.1f}% of short notional) ${v['pnl']:>+8,.0f}")
    ex3 = [r for r in rows if (r["m"], r["o"]) in short_keys
           and r["w"] not in {w for w, _ in order_w[:3]}]
    n3 = sum(r["n"] for r in ex3)
    print(f"   short block ex-top-3-wallets: ${sum(r['p'] for r in ex3):+,.0f} on ${n3:,.0f} "
          f"({100*sum(r['p'] for r in ex3)/n3 if n3 else 0:+.1f}%)")

    print(f"\n   (d) month by month (STANDARD, short vs rest) -- one bad fortnight cannot carry it")
    print(f"   {'month':8} {'short n':>7} {'short $pnl':>10} {'short ROI%':>10} "
          f"{'rest n':>7} {'rest $pnl':>10} {'rest ROI%':>9}")
    bym = {}
    for l in legs:
        bym.setdefault(time.strftime("%Y-%m", time.gmtime(l["ms"] / 1000)), []).append(l)
    for m in sorted(bym):
        s = [l for l in bym[m] if l["ttl"] < 24]
        r = [l for l in bym[m] if l["ttl"] >= 24]
        cs = (f"{100*sum(l['pnl'] for l in s)/sum(l['ntl'] for l in s):>+10.1f}"
              if s else f"{'-':>10}")
        cr = (f"{100*sum(l['pnl'] for l in r)/sum(l['ntl'] for l in r):>+9.1f}"
              if r else f"{'-':>9}")
        print(f"   {m:8} {len(s):>7} {sum(l['pnl'] for l in s):>+10,.0f} {cs} "
              f"{len(r):>7} {sum(l['pnl'] for l in r):>+10,.0f} {cr}")


def ladder_effect(c):
    """X2. What the TTL floor does to book-level capital productivity and the implied capital."""
    print("\n" + "=" * 100)
    print("X2. BOOK-LEVEL EFFECT OF A 24h TTL FLOOR ON STANDARD")
    print("=" * 100)
    legs = load_finished(c)
    # Remove exactly the STANDARD legs with TTL<24h by matching on (market, openedAt).
    short_keys = {(l["market"], l["ms"]) for l in ttl_edges(c, 0)
                  if l["bot"] == "STANDARD" and l["ttl"] < 24}
    # ...and the subset of those on bands v63 already blocks (0.40-0.60), so the marginal
    # scenario does not double-count a change that is already live.
    short_open = {(l["market"], l["ms"]) for l in ttl_edges(c, 0)
                  if l["bot"] == "STANDARD" and l["ttl"] < 24
                  and band_of(l["px"]) != "0.4-0.6"}
    keep, cut = [], []
    keep_m, cut_m = [], []
    for l in legs:
        k = (l["market"], l["ms"])
        is_short = l["bot"] == "STANDARD" and k in short_keys
        (cut if is_short else keep).append(l)
        (cut_m if (l["bot"] == "STANDARD" and k in short_open) else keep_m).append(l)
    def line(nm, xs):
        cd = sum(l["cd"] for l in xs)
        p = sum(l["pnl"] for l in xs)
        rate = (1000 * p / cd) if cd else None
        # A block whose rate is <= 0 does not "need negative capital": it loses money at EVERY
        # capital level and can never reach $5k/day. Printing 5000/rate here produced
        # "-39,788 capital for $5k/day" on the TTL<24h block (live, 2026-10-24) -- a number that
        # reads as a shortcut to the target when it is the opposite. Section X already words this
        # correctly; X2 now uses the same phrasing so the two halves cannot disagree.
        need = (f"{5000/(rate/1000):>12,.0f} capital for $5k/day" if rate and rate > 0
                else f"{'never (rate<=0)':>12}      ")
        print(f"   {nm:34} {len(xs):>5} legs ${sum(l['ntl'] for l in xs):>9,.0f} "
              f"${p:>+9,.0f} {rate if rate is not None else 0:>+7.2f} $/1k-cd "
              f"{need}")
    line("baseline (all finished legs)", legs)
    line("  gross block: TTL<24h, all bands", cut)
    line("gross floor applied", keep)
    line("  marginal block: TTL<24h, bands v63", cut_m)
    line("marginal floor applied (on top of v63)", keep_m)


# ---------------------------------------------------------------- AA..AD
# SETTLEMENT TRUTH AND EXIT ALPHA
#
# Why this exists: 74% of the finished book's notional leaves through the early-exit path
# (status='closed'), and that path has only ever been judged against its own marks. Nothing
# in this repo has compared an exit price to what the market actually SETTLED at, so
# "the exits are fine" has never been a measurement -- it has been an assumption. A closed
# leg and a resolved leg never co-occur on the same (market, outcome) in STANDARD (0 markets
# out of 2,305), so there is no within-market control available and the counterfactual must
# come from an external settlement record.
#
# Truth source: archived CLOB /markets/<conditionId> -> tokens[].winner, keyless, cached in
# data/market-truth-clob.json so the section re-runs offline. The cache is committed; the
# fetched raw responses are not. Coverage and mapping accuracy are PRINTED, not assumed --
# a truth join that silently drops half the book is the same failure as an instrument that
# cannot fail.
#
# Cost basis: simulatedPositionSize = dollars at risk (never shares). For a BUY at p with
# dollars at risk n, a settlement worth s realises n*(s/p - 1); an early exit at c realises
# n*(c/p - 1). Both identities were verified against realizedPnl before this section was
# written (max abs error $0.005, i.e. the rounding of the position size).

TRUTH_CACHE = "data/market-truth-clob.json"


def _norm_outcome(s):
    return (s or "").strip().upper().replace("-", " ").replace("_", " ")


def market_condition_ids(c):
    """marketId -> conditionId, one indexed lookup per market (MarketSnapshot has 15.9M rows)."""
    markets = [r[0] for r in c.execute(
        """SELECT DISTINCT marketId FROM PaperTrade
           WHERE isDemo=0 AND status IN ('closed','resolved')""")]
    out = {}
    for m in markets:
        r = c.execute(
            """SELECT conditionId FROM MarketSnapshot
               WHERE marketId=? AND conditionId IS NOT NULL LIMIT 1""", (m,)).fetchone()
        if r and r[0]:
            out[m] = r[0]
    return out


def _fetch_one(cid):
    """One archived market -> {'tokens': [[name, winner]], 'end': iso} or None."""
    path = os.path.join(TRUTH_RAW_DIR, cid + ".json")
    for attempt in range(3):
        if not os.path.exists(path) or os.path.getsize(path) < 40:
            subprocess.run(["curl", "-s", "--max-time", "25",
                            "https://clob.polymarket.com/markets/" + cid, "-o", path],
                           check=False)
        try:
            d = json.load(open(path))
            toks = [[t.get("outcome"), bool(t.get("winner"))] for t in d.get("tokens", [])]
            if toks and any(t[1] for t in toks):
                return cid, {"tokens": toks, "end": d.get("end_date_iso"),
                             "closed": bool(d.get("closed"))}
            if toks:
                # Market exists but has no winner yet -> not settled, cache as such.
                return cid, {"tokens": toks, "end": d.get("end_date_iso"),
                             "closed": bool(d.get("closed")), "unsettled": True}
        except Exception:
            time.sleep(0.4 * (attempt + 1))
    return cid, None


def build_truth(c, refresh=False):
    """Cached settlement truth for every market the finished book touches."""
    cache = {"markets": {}}
    if os.path.exists(TRUTH_CACHE):
        try:
            cache = json.load(open(TRUTH_CACHE))
        except Exception:
            cache = {"markets": {}}
    old = cache.get("markets", {})
    m2c = market_condition_ids(c)
    want = sorted(set(m2c.values()))
    have = {k for k, v in old.items() if v and not v.get("unsettled")}
    if refresh:
        missing = want
    else:
        missing = [cid for cid in want if cid not in have]
    print(f"\n   truth cache: {len(want)} distinct markets in the finished book, "
          f"{len(want) - len(missing)} settled already cached, fetching {len(missing)}")
    if missing:
        with ThreadPoolExecutor(max_workers=8) as ex:
            for cid, rec in ex.map(_fetch_one, missing):
                if rec:
                    old[cid] = rec
    cache = {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
             "source": "https://clob.polymarket.com/markets/<conditionId> tokens[].winner",
             "markets": old}
    with open(TRUTH_CACHE, "w") as f:
        json.dump(cache, f, indent=0, sort_keys=True)
    return cache, m2c


def truth_of(cache, cid, outcome, stats):
    """Settlement value (1.0 / 0.0) for OUR side, or None. Name match first, index fallback."""
    rec = cache["markets"].get(cid) if cid else None
    if not rec or rec.get("unsettled"):
        stats["no_record"] += 1
        return None
    toks = rec.get("tokens") or []
    n = _norm_outcome(outcome)
    for name, win in toks:
        if _norm_outcome(name) == n:
            stats["name_match"] += 1
            return 1.0 if win else 0.0
    if len(toks) == 2 and n in ("YES", "NO"):
        i = 0 if n == "YES" else 1
        stats["index_fallback"] += 1
        return 1.0 if toks[i][1] else 0.0
    stats["no_match"] += 1
    return None


def load_closed(c, since_ms=0, bot=None):
    sql = """SELECT p.id, p.botId, p.marketId, p.outcome, p.entryPrice px, p.currentPrice cur,
                    p.simulatedPositionSize ntl, p.realizedPnl pnl, p.openedAt, p.closedAt
             FROM PaperTrade p
             WHERE p.isDemo=0 AND p.status='closed' AND p.realizedPnl IS NOT NULL
               AND p.openedAt >= ?"""
    params = [since_ms]
    if bot:
        sql += " AND p.botId=?"
        params.append(bot)
    out = []
    for r in c.execute(sql, params):
        if not r["px"] or r["px"] <= 0 or not r["ntl"] or r["ntl"] <= 0:
            continue
        end = r["closedAt"] or r["openedAt"]
        out.append({"id": r["id"], "bot": r["botId"], "market": r["marketId"],
                    "outcome": r["outcome"], "px": r["px"], "cur": r["cur"],
                    "ntl": r["ntl"], "pnl": r["pnl"], "band": band_of(r["px"]),
                    "days": max((end - r["openedAt"]) / 86_400_000.0, 0.02),
                    "ms": r["openedAt"]})
    return out


def _boot_sum(legs, key, reps=1500, seed=41):
    """Market-clustered bootstrap CI on sum(legs[key]) -- dollars, not a ratio."""
    if not legs:
        return (0.0, 0.0)
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
        vals.append(sum(l[key] for i in pick for l in by[keys[i]]))
    return (float(np.percentile(vals, 2.5)), float(np.percentile(vals, 97.5)))


def calibration_report(c):
    """AA. Realised hit rate vs the price we paid -- the edge in probability points.

    The payoff identity ROI = (hit - p)/p is exact under this book's settlement maths, so
    every dollar of realised edge is (hit - p) amplified by 1/p. That means a band's ROI
    can be large with no probability edge at all (cheap legs) and small with a real one
    (expensive legs). This table separates the two, which no ROI table in this repo does.
    """
    print("\n" + "=" * 100)
    print("AA. CALIBRATION -- realised hit rate vs entry price, i.e. the edge in probability points")
    print("=" * 100)
    print("   ROI% = (hit - p)/p exactly; 'pp' = hit - p. A band can print a big ROI on a")
    print("   negative pp edge (1/p amplification) -- that is the number this table exists to expose.")
    print(f"   {'lane':10} {'band':8} {'legs':>5} {'notional':>9} {'avgP':>6} {'hit%':>6} "
          f"{'pp':>7} {'pp CI':>16} {'ROI%':>7} {'implied':>8} {'$/pp':>9} {'pnl':>9}")
    for bot in ("STANDARD", "BANKROLL_200", "ALL"):
        for nm in NAMES:
            rows = c.execute(
                """SELECT entryPrice px, simulatedPositionSize ntl, realizedPnl pnl, marketId m
                   FROM PaperTrade WHERE isDemo=0 AND status='resolved' AND realizedPnl IS NOT NULL
                     AND entryPrice>=? AND entryPrice<?""" +
                ("" if bot == "ALL" else " AND botId=?"),
                ([BANDS[NAMES.index(nm)][0], BANDS[NAMES.index(nm)][1]] +
                 ([] if bot == "ALL" else [bot]))).fetchall()
            legs = [{"px": r["px"], "ntl": r["ntl"], "pnl": r["pnl"], "m": r["m"],
                     "hit": 1.0 if r["pnl"] > 0 else 0.0, "pp": (1.0 if r["pnl"] > 0 else 0.0) - r["px"]}
                    for r in rows if r["px"] and r["px"] > 0 and r["ntl"] and r["ntl"] > 0]
            if len(legs) < 20:
                continue
            ntl = sum(l["ntl"] for l in legs)
            pnl = sum(l["pnl"] for l in legs)
            avgp = sum(l["px"] * l["ntl"] for l in legs) / ntl
            hit = sum(l["hit"] * l["ntl"] for l in legs) / ntl
            pp = hit - avgp
            # market-clustered bootstrap of the notional-weighted pp edge
            by = {}
            for l in legs:
                by.setdefault(l["m"], []).append(l)
            keys = list(by)
            rng = np.random.default_rng(11)
            vals = []
            for _ in range(1200):
                pick = rng.integers(0, len(keys), len(keys))
                s = [l for i in pick for l in by[keys[i]]]
                n_ = sum(x["ntl"] for x in s)
                if n_:
                    vals.append(sum(x["hit"] * x["ntl"] for x in s) / n_
                                - sum(x["px"] * x["ntl"] for x in s) / n_)
            lo, hi = (np.percentile(vals, 2.5), np.percentile(vals, 97.5)) if vals else (np.nan, np.nan)
            # dollars of notional per 1pp of edge -- the amplification axis
            per_pp = ntl / 100.0 * 100.0 / (avgp * 100)
            print(f"   {bot[:10]:10} {nm:8} {len(legs):>5} {ntl:>9,.0f} {avgp:>6.3f} "
                  f"{100*hit:>6.1f} {100*pp:>+7.2f} [{100*lo:>+6.2f},{100*hi:>+6.2f}] "
                  f"{100*pnl/ntl:>+7.1f} {100*pp/avgp:>+8.1f} {per_pp:>9,.0f} {pnl:>+9,.0f}")


def exit_alpha_report(c, since_label="all-time", since_ms=0):
    """AB. CLOSED legs vs settlement truth: did the exit beat holding to resolution?"""
    print("\n" + "=" * 100)
    print(f"AB. EXIT ALPHA -- every closed leg re-priced at settlement ({since_label})")
    print("=" * 100)
    cache, m2c = build_truth(c, refresh=TRUTH_REFRESH)
    for bot in ("STANDARD", "BANKROLL_200"):
        legs = load_closed(c, since_ms, bot)
        stats = {"name_match": 0, "index_fallback": 0, "no_match": 0, "no_record": 0}
        for l in legs:
            s = truth_of(cache, m2c.get(l["market"]), l["outcome"], stats)
            l["settle"] = s
            if s is None:
                continue
            l["hold_pnl"] = l["ntl"] * (s / l["px"] - 1.0)
            l["dlt"] = l["pnl"] - l["hold_pnl"]          # >0: the exit beat holding
            l["dlt_pp"] = 100 * l["dlt"] / l["ntl"]
        cov = [l for l in legs if l.get("settle") is not None]
        print(f"\n   {bot}: {len(legs)} closed legs, {len(cov)} priced at settlement "
              f"({100*len(cov)/len(legs) if legs else 0:.0f}% coverage; "
              f"name-match {stats['name_match']}, index fallback {stats['index_fallback']}, "
              f"no-match {stats['no_match']}, no record {stats['no_record']})")
        if not cov:
            continue
        ntl = sum(l["ntl"] for l in cov)
        act = sum(l["pnl"] for l in cov)
        hold = sum(l["hold_pnl"] for l in cov)
        print(f"   exit as executed: {len(cov):>5} legs ${ntl:>8,.0f} ${act:>+8,.0f} "
              f"({100*act/ntl:>+6.1f}%)   hold to settlement: ${hold:>+8,.0f} "
              f"({100*hold/ntl:>+6.1f}%)   exit alpha ${act-hold:>+8,.0f} "
              f"({100*(act-hold)/ntl:>+6.2f}% of notional)")
        ex = sorted(cov, key=lambda l: -l["dlt"])[10:]
        lo, hi = _boot_sum(cov, "dlt")
        print(f"   exit alpha CI (market-clustered) [${lo:+,.0f}, ${hi:+,.0f}]   "
              f"ex-top-10 ${sum(l['dlt'] for l in ex):+,.0f} on ${sum(l['ntl'] for l in ex):,.0f}")
        print(f"\n   {'band':8} {'legs':>5} {'notional':>9} {'exitROI%':>9} {'holdROI%':>9} "
              f"{'alpha$':>8} {'alpha%':>7} {'win%exit':>8} {'win%hold':>8} {'medExit':>7} {'medSettle':>9}")
        for nm in NAMES:
            b = [l for l in cov if l["band"] == nm]
            if len(b) < 10:
                continue
            bn = sum(l["ntl"] for l in b)
            a = sum(l["pnl"] for l in b)
            h = sum(l["hold_pnl"] for l in b)
            print(f"   {nm:8} {len(b):>5} {bn:>9,.0f} {100*a/bn:>+9.1f} {100*h/bn:>+9.1f} "
                  f"{a-h:>+8,.0f} {100*(a-h)/bn:>+7.2f} "
                  f"{100*sum(1 for l in b if l['cur']>l['px'])/len(b):>7.0f}% "
                  f"{100*sum(l['settle'] for l in b)/len(b):>7.0f}% "
                  f"{np.median([l['cur'] for l in b]):>7.3f} "
                  f"{np.mean([l['settle'] for l in b]):>9.3f}")
        # The mechanism split: did we sell strength or cut weakness?
        print(f"\n   mechanism split (exit price vs entry price)")
        print(f"   {'side':22} {'legs':>5} {'notional':>9} {'exitROI%':>9} {'holdROI%':>9} "
              f"{'alpha$':>8} {'alpha%':>7} {'medMove':>8}")
        for label, sel in (("sold into strength", lambda l: l["cur"] > l["px"] + 1e-9),
                           ("cut into weakness", lambda l: l["cur"] < l["px"] - 1e-9),
                           ("flat", lambda l: abs(l["cur"] - l["px"]) <= 1e-9)):
            b = [l for l in cov if sel(l)]
            if not b:
                continue
            bn = sum(l["ntl"] for l in b)
            a = sum(l["pnl"] for l in b)
            h = sum(l["hold_pnl"] for l in b)
            print(f"   {label:22} {len(b):>5} {bn:>9,.0f} {100*a/bn:>+9.1f} {100*h/bn:>+9.1f} "
                  f"{a-h:>+8,.0f} {100*(a-h)/bn:>+7.2f} "
                  f"{np.median([l['cur']-l['px'] for l in b]):>+8.3f}")
        # Capital-time released by exiting, so the alpha can be priced against the book's rate.
        ends = {}
        for l in cov:
            rec = cache["markets"].get(m2c.get(l["market"]))
            if rec and rec.get("end"):
                try:
                    ends[l["market"]] = time.mktime(time.strptime(rec["end"][:19], "%Y-%m-%dT%H:%M:%S")) * 1000
                except Exception:
                    pass
        rel = [l for l in cov if l["market"] in ends
               and (ends[l["market"]] - l["ms"]) / 86_400_000.0 > l["days"]]
        if rel:
            rel_days = sum(l["ntl"] * ((ends[l["market"]] - l["ms"]) / 86_400_000.0 - l["days"])
                           for l in rel)
            rel_alpha = sum(l["dlt"] for l in rel)
            print(f"\n   capital-time: {len(rel)} exits released {rel_days:,.0f} capital-days "
                  f"(scheduled end vs exit time) for an exit alpha of ${rel_alpha:+,.0f} "
                  f"-> ${1000*rel_alpha/rel_days if rel_days else 0:+,.0f} per 1k capital-day released")
            print(f"   finished-book benchmark is +27.43 $/1k-cd (section T): releasing a day of capital")
            print(f"   is worth ~$27 per $1,000 of it, so an alpha below that per released capital-day")
            print(f"   means the exit was the better use of the money even if it sold a winner.")


# ---------------------------------------------------------------- AC
def high_price_audit(c):
    """AC. The expensive half of the book: is the edge at 0.60-1.00 real, and where is the volume?

    Standing baseline says '64.4% of acted trades sit above 0.50, where edge is negative'. The
    calibration table (AA) does not support that as a book-level statement: at 0.60-1.00 the
    C-200 lane shows a positive, CI-excluding-zero pp edge while STANDARD shows ~zero. So the
    claim is either lane-specific or dead. This tests it four ways before anything is proposed
    on it: market/wallet concentration, ex-top-N, month stability, and a first-fill dedupe
    (the basis v63 was challenged on and upheld).
    """
    print("\n" + "=" * 100)
    print("AC. HIGH-PRICE BLOCK AUDIT -- 0.60-1.00 by lane, and the volume that sits there")
    print("=" * 100)
    rows = c.execute(
        """SELECT botId, marketId, walletAddress, entryPrice px, simulatedPositionSize ntl,
                  realizedPnl pnl, openedAt
           FROM PaperTrade WHERE isDemo=0 AND status='resolved' AND realizedPnl IS NOT NULL""").fetchall()
    legs = [{"bot": r["botId"], "m": r["marketId"], "w": r["walletAddress"], "px": r["px"],
             "ntl": r["ntl"], "pnl": r["pnl"], "ms": r["openedAt"],
             "hit": 1.0 if r["pnl"] > 0 else 0.0}
            for r in rows if r["px"] and r["px"] > 0 and r["ntl"] and r["ntl"] > 0]
    for bot in ("STANDARD", "BANKROLL_200"):
        for lo, hi, nm in ((0.60, 0.80, "0.6-0.8"), (0.80, 1.0001, "0.8-1.0")):
            s = [l for l in legs if l["bot"] == bot and lo <= l["px"] < hi]
            if len(s) < 10:
                continue
            ntl = sum(l["ntl"] for l in s)
            pnl = sum(l["pnl"] for l in s)
            markets = len({l["m"] for l in s})
            wallets = len({l["w"] for l in s})
            avgp = sum(l["px"] * l["ntl"] for l in s) / ntl
            hit = sum(l["hit"] * l["ntl"] for l in s) / ntl
            ex10 = sorted(s, key=lambda l: -l["pnl"])[10:]
            n10 = sum(l["ntl"] for l in ex10)
            first = {}
            for l in sorted(s, key=lambda l: l["ms"]):
                first.setdefault((l["m"], l["w"]), l)
            f = list(first.values())
            fn = sum(l["ntl"] for l in f)
            print(f"\n   {bot} {nm}: {len(s)} legs / {markets} markets / {wallets} wallets, ${ntl:,.0f}")
            print(f"     pp edge {100*(hit-avgp):+.2f}   ROI {100*pnl/ntl:+.1f}%   "
                  f"ex-top-10 {100*sum(l['pnl'] for l in ex10)/n10:+.1f}% on ${n10:,.0f}   "
                  f"first-fill {len(f)} legs {100*sum(l['pnl'] for l in f)/fn:+.1f}%")
            mon = {}
            for l in s:
                mon.setdefault(time.strftime("%Y-%m", time.gmtime(l["ms"] / 1000)), []).append(l)
            seq = [f"{m}:n{len(v)}/{100*sum(x['pnl'] for x in v)/sum(x['ntl'] for x in v):+.0f}%"
                   for m, v in sorted(mon.items())]
            print("     months " + "  ".join(seq))
    closed = c.execute(
        """SELECT botId b, count(*) n, sum(simulatedPositionSize) ntl, sum(realizedPnl) pnl
           FROM PaperTrade WHERE isDemo=0 AND status='closed' AND realizedPnl IS NOT NULL
             AND entryPrice >= 0.60 GROUP BY botId""").fetchall()
    print(f"\n   volume in the same price region that left via the early-exit path "
          f"(judged in AB, counted here):")
    for r in closed:
        print(f"     {r['b']:12} {r['n']:>5} legs ${r['ntl']:>8,.0f} {100*r['pnl']/r['ntl']:>+6.1f}%")
    print(f"\n   allocation: notional per 1pp of measured pp edge (resolved legs)")
    print(f"   {'lane':12} {'band':8} {'notional':>9} {'pp':>7} {'$/1pp':>10}  verdict")
    for bot in ("STANDARD", "BANKROLL_200"):
        for lo, hi, nm in ((0.0, 0.2, "<0.20"), (0.2, 0.4, "0.2-0.4"), (0.4, 0.6, "0.4-0.6"),
                           (0.6, 0.8, "0.6-0.8"), (0.8, 1.0001, "0.8-1.0")):
            s = [l for l in legs if l["bot"] == bot and lo <= l["px"] < hi]
            if len(s) < 10:
                continue
            ntl = sum(l["ntl"] for l in s)
            avgp = sum(l["px"] * l["ntl"] for l in s) / ntl
            pp = sum(l["hit"] * l["ntl"] for l in s) / ntl - avgp
            per = f"{ntl/(100*pp):,.0f}" if pp > 1e-6 else "n/a"
            verdict = ("edge, under-allocated" if pp > 0.03 and ntl < 3000
                       else "edge" if pp > 0.03
                       else "no edge, over-allocated" if ntl > 8000 else "no edge")
            print(f"   {bot:12} {nm:8} {ntl:>9,.0f} {100*pp:>+7.2f} {per:>10}  {verdict}")


# ---------------------------------------------------------------- AD
def truth_bands(c, since_label="all-time", since_ms=0):
    """AD. Band ROI on SETTLEMENT TRUTH, over every leg -- no exit-path survivorship.

    The reason this table, and not the ROI table, is the load-bearing one: legs split by how
    they ended. 'resolved' legs are the ones whose market reached resolution; 'closed' legs are
    the ones whose market went dead and were expired at the last mark. Conditioning a band's
    edge on either half is a selection on the exit path, and the two halves disagree in sign in
    three of five STANDARD bands. So every leg is re-valued at what its market actually settled
    at, which is the only basis that is independent of both our exit rules and our data gaps.

    Validation is built in: for RESOLVED legs the truth PnL must equal realizedPnl by identity
    (both are n*(s/p-1)), and the max absolute difference is printed. If that number is not
    ~0, the truth join is wrong and the table is not readable.
    """
    print("\n" + "=" * 100)
    print(f"AD. BAND EDGE ON SETTLEMENT TRUTH -- every leg, both exit paths ({since_label})")
    print("=" * 100)
    cache, m2c = build_truth(c)
    rows = c.execute(
        """SELECT botId, marketId, walletAddress, outcome, entryPrice px,
                  simulatedPositionSize ntl, realizedPnl pnl, status, openedAt
           FROM PaperTrade WHERE isDemo=0 AND status IN ('closed','resolved')
             AND realizedPnl IS NOT NULL AND openedAt >= ?""", (since_ms,)).fetchall()
    stats = {"name_match": 0, "index_fallback": 0, "no_match": 0, "no_record": 0}
    legs = []
    for r in rows:
        if not r["px"] or r["px"] <= 0 or not r["ntl"] or r["ntl"] <= 0:
            continue
        s = truth_of(cache, m2c.get(r["marketId"]), r["outcome"], stats)
        if s is None:
            continue
        legs.append({"bot": r["botId"], "m": r["marketId"], "w": r["walletAddress"],
                     "px": r["px"], "ntl": r["ntl"], "band": band_of(r["px"]),
                     "settle": s, "hit": s, "ms": r["openedAt"],
                     "tp": r["ntl"] * (s / r["px"] - 1.0), "pnl": r["pnl"],
                     "status": r["status"]})
    res = [l for l in legs if l["status"] == "resolved"]
    err = max((abs(l["tp"] - l["pnl"]) for l in res), default=0.0)
    print(f"   truth join: {len(legs)} of {len(rows)} legs priced "
          f"({100*len(legs)/len(rows):.1f}%) -- name-match {stats['name_match']}, "
          f"index fallback {stats['index_fallback']}, no-match {stats['no_match']}, "
          f"no record {stats['no_record']}")
    print(f"   VALIDATION: max |truth PnL - realizedPnl| over {len(res)} resolved legs = "
          f"${err:.3f} (must be ~0 for this table to be readable)")
    print(f"\n   {'lane':12} {'band':8} {'legs':>5} {'mkts':>5} {'notional':>9} {'avgP':>6} "
          f"{'hit%':>6} {'pp':>7} {'truthROI%':>9} {'CI':>16} {'ex10%':>7} {'ex3mk%':>7}")
    for bot in ("STANDARD", "BANKROLL_200", "ALL"):
        for nm in NAMES:
            b = [l for l in legs if l["band"] == nm and (bot == "ALL" or l["bot"] == bot)]
            if len(b) < 15:
                continue
            ntl = sum(l["ntl"] for l in b)
            tp = sum(l["tp"] for l in b)
            avgp = sum(l["px"] * l["ntl"] for l in b) / ntl
            hit = sum(l["hit"] * l["ntl"] for l in b) / ntl
            lo, hi = boot_roi([{"marketId": l["m"], "ntl": l["ntl"], "pnl": l["tp"]} for l in b])
            e10 = sorted(b, key=lambda l: -l["tp"])[10:]
            n10 = sum(l["ntl"] for l in e10)
            bym = {}
            for l in b:
                d = bym.setdefault(l["m"], [0.0, 0.0]); d[0] += l["tp"]; d[1] += l["ntl"]
            top3 = {k for k, _ in sorted(bym.items(), key=lambda kv: -kv[1][0])[:3]}
            keep = [l for l in b if l["m"] not in top3]
            kn = sum(l["ntl"] for l in keep)
            print(f"   {bot[:12]:12} {nm:8} {len(b):>5} {len(bym):>5} {ntl:>9,.0f} {avgp:>6.3f} "
                  f"{100*hit:>6.1f} {100*(hit-avgp):>+7.2f} {100*tp/ntl:>+9.1f} "
                  f"[{100*lo:>+6.1f},{100*hi:>+6.1f}] "
                  f"{100*sum(l['tp'] for l in e10)/n10:>+7.1f} "
                  f"{100*sum(l['tp'] for l in keep)/kn if kn else 0:>+7.1f}")
    # The allocation read: what the size factors actually are, next to the measured edge.
    print(f"\n   lane bands, the live size factor, and the measured truth edge "
          f"(all-time, legs>=15)")
    print(f"   {'lane':12} {'band':8} {'live factor':>12} {'clip$':>7} {'pp':>7} {'truthROI%':>9} {'verdict':>26}")
    for bot in ("STANDARD", "BANKROLL_200"):
        for nm in NAMES:
            b = [l for l in legs if l["band"] == nm and l["bot"] == bot]
            if len(b) < 15:
                continue
            ntl = sum(l["ntl"] for l in b)
            avgp = sum(l["px"] * l["ntl"] for l in b) / ntl
            pp = sum(l["hit"] * l["ntl"] for l in b) / ntl - avgp
            tp = sum(l["tp"] for l in b)
            if bot == "BANKROLL_200":
                fac = {"<0.20": "3.5 (longshot)", "0.2-0.4": "1.0", "0.4-0.6": "0.125 (skip)",
                       "0.6-0.8": "0.5 (halved)", "0.8-1.0": "1.0"}[nm]
            else:
                fac = {"<0.20": "1.0", "0.2-0.4": "1.0", "0.4-0.6": "skipped (v63)",
                       "0.6-0.8": "1.0", "0.8-1.0": "1.0"}[nm]
            print(f"   {bot[:12]:12} {nm:8} {fac:>12} {ntl/len(b):>7.2f} {100*pp:>+7.2f} "
                  f"{100*tp/ntl:>+9.1f}")


# ---------------------------------------------------------------- AE
SUB_BANDS = [(0.0, 0.05, "0.00-0.05"), (0.05, 0.10, "0.05-0.10"), (0.10, 0.15, "0.10-0.15"),
             (0.15, 0.20, "0.15-0.20")]


def cheap_tail_decomposition(c):
    """AE. The <0.20 band is not one bet: 0.00-0.05 and 0.05-0.20 behave oppositely.

    Why it matters for sizing rather than for a gate: the live C-200 map applies its LARGEST
    factor (c200LongshotBandFactor, 3.5x, paper.ts mapBankroll200Size) to everything below
    0.20 with no lower bound, and applyKellyBandRails FLOORS Kelly at that size ("must never
    shrink the one proven winner"). So the deepest longshots in the book get the biggest clips
    and the code is written to keep it that way. If the edge is not there, the factor is a
    sizing error the rails actively defend.
    """
    print("\n" + "=" * 100)
    print("AE. CHEAP-TAIL DECOMPOSITION -- 0.00-0.05 vs 0.05-0.20, on settlement truth")
    print("=" * 100)
    cache, m2c = build_truth(c)
    rows = c.execute(
        """SELECT botId, marketId, walletAddress, outcome, entryPrice px,
                  simulatedPositionSize ntl, realizedPnl pnl, status
           FROM PaperTrade WHERE isDemo=0 AND status IN ('closed','resolved')
             AND realizedPnl IS NOT NULL AND entryPrice < 0.20""").fetchall()
    stats = {"name_match": 0, "index_fallback": 0, "no_match": 0, "no_record": 0}
    legs = []
    for r in rows:
        if not r["px"] or r["px"] <= 0 or not r["ntl"] or r["ntl"] <= 0:
            continue
        s = truth_of(cache, m2c.get(r["marketId"]), r["outcome"], stats)
        if s is None:
            continue
        legs.append({"bot": r["botId"], "m": r["marketId"], "w": r["walletAddress"],
                     "px": r["px"], "ntl": r["ntl"], "hit": s, "pnl": r["pnl"],
                     "tp": r["ntl"] * (s / r["px"] - 1.0), "status": r["status"]})
    print(f"   {'sub-band':10} {'legs':>5} {'mkts':>5} {'notional':>9} {'clip':>6} {'avgP':>6} "
          f"{'hit%':>6} {'pp':>7} {'truthROI%':>9} {'ex10%':>7} {'ex3mk%':>7} {'REALIZED$':>9}")
    for lo, hi, nm in SUB_BANDS:
        b = [l for l in legs if lo <= l["px"] < hi]
        if len(b) < 10:
            continue
        ntl = sum(l["ntl"] for l in b)
        tp = sum(l["tp"] for l in b)
        hit = sum(l["hit"] * l["ntl"] for l in b) / ntl
        px = sum(l["px"] * l["ntl"] for l in b) / ntl
        e10 = sorted(b, key=lambda l: -l["tp"])[10:]
        n10 = sum(l["ntl"] for l in e10)
        bym = {}
        for l in b:
            bym.setdefault(l["m"], []).append(l)
        top3 = {k for k, _ in sorted(bym.items(), key=lambda kv: -sum(x["tp"] for x in kv[1]))[:3]}
        keep = [l for l in b if l["m"] not in top3]
        kn = sum(l["ntl"] for l in keep)
        print(f"   {nm:10} {len(b):>5} {len(bym):>5} {ntl:>9,.0f} {ntl/len(b):>6.2f} {px:>6.3f} "
              f"{100*hit:>6.1f} {100*(hit-px):>+7.2f} {100*tp/ntl:>+9.1f} "
              f"{100*sum(l['tp'] for l in e10)/n10:>+7.1f} "
              f"{100*sum(l['tp'] for l in keep)/kn if kn else 0:>+7.1f} "
              f"{sum(l['pnl'] for l in b):>+9,.0f}")
    # Who owns the sub-0.05 region, and at what clip -- this is the size-factor question.
    print(f"\n   sub-0.05 by lane: clip vs the lane's own band factor")
    for bot in ("STANDARD", "BANKROLL_200"):
        b = [l for l in legs if l["bot"] == bot and l["px"] < 0.05]
        if not b:
            continue
        ntl = sum(l["ntl"] for l in b)
        pk = [l for l in legs if l["bot"] == bot and 0.05 <= l["px"] < 0.20]
        pn = sum(l["ntl"] for l in pk)
        print(f"   {bot:12} <0.05: {len(b):>3} legs ${ntl:>6,.0f} clip ${ntl/len(b):>6.2f} "
              f"settle-hit {100*sum(l['hit'] for l in b)/len(b):>5.1f}% "
              f"REALIZED ${sum(l['pnl'] for l in b):>+7,.0f} ({100*sum(l['pnl'] for l in b)/ntl:>+6.1f}%)"
              f"   |   0.05-0.20: {len(pk):>3} legs clip ${pn/len(pk):>6.2f}")
    # Break-even hit rate is the price; print the gap that matters.
    print(f"\n   break-even hit rate = the price paid. Sub-0.05 requires "
          f"{100*sum(l['px']*l['ntl'] for l in legs if l['px']<0.05)/sum(l['ntl'] for l in legs if l['px']<0.05):.2f}% accuracy; "
          f"realised settlement hit is "
          f"{100*sum(l['hit']*l['ntl'] for l in legs if l['px']<0.05)/sum(l['ntl'] for l in legs if l['px']<0.05):.2f}%.")


def cheap_tail_fill_probe(c, limit=40):
    """AF. Fill headroom in the cheap tail, from live order books (Lane B, read-only).

    The standing caveat is that fillability of thin books is unmodelled and is the dominant
    risk in every cheap-tail result. This is the first measurement of it: for open positions
    below 0.20, how much notional can be bought within 1c / 2c / 5c of the best ask? That
    number, divided by the clip, is the clip multiplier the book can actually carry.
    """
    print("\n" + "=" * 100)
    print("AF. CHEAP-TAIL FILL HEADROOM -- live order books for open positions < 0.20")
    print("=" * 100)
    rows = c.execute(
        """SELECT DISTINCT marketId, outcome, entryPrice px, simulatedPositionSize ntl
           FROM PaperTrade WHERE isDemo=0 AND status='open' AND entryPrice < 0.20
           ORDER BY entryPrice LIMIT ?""", (limit,)).fetchall()
    m2c = market_condition_ids(c)
    out = []
    for r in rows:
        cid = m2c.get(r["marketId"])
        if not cid:
            continue
        if not os.path.exists(os.path.join(TRUTH_RAW_DIR, cid + ".json")):
            subprocess.run(["curl", "-s", "--max-time", "20",
                            "https://clob.polymarket.com/markets/" + cid,
                            "-o", os.path.join(TRUTH_RAW_DIR, cid + ".json")], check=False)
        try:
            d = json.load(open(os.path.join(TRUTH_RAW_DIR, cid + ".json")))
        except Exception:
            continue
        toks = [(t.get("outcome"), t.get("token_id")) for t in d.get("tokens", [])]
        match = [t for t in toks if _norm_outcome(t[0]) == _norm_outcome(r["outcome"])]
        if not match or not match[0][1]:
            continue
        bk = subprocess.run(["curl", "-s", "--max-time", "20",
                             "https://clob.polymarket.com/book?token_id=" + match[0][1]],
                            capture_output=True, text=True).stdout
        try:
            b = json.loads(bk)
            asks = sorted([[float(a["price"]), float(a["size"])] for a in b.get("asks", [])])
        except Exception:
            continue
        if not asks:
            continue
        best = asks[0][0]

        def depth(lim):
            return sum(p * s for p, s in asks if p <= best + lim)
        out.append({"market": r["marketId"], "px": r["px"], "clip": r["ntl"],
                    "best_ask": best, "d1": depth(0.01), "d2": depth(0.02), "d5": depth(0.05)})
    if not out:
        print("   no live books resolved -- probe skipped")
        return
    print(f"   {len(out)} open cheap positions with a live book")
    for k, lab in (("d1", "+1c"), ("d2", "+2c"), ("d5", "+5c")):
        vals = sorted(x[k] for x in out)
        med = np.median(vals)
        mult = [x[k] / x["clip"] for x in out if x["clip"] > 0]
        print(f"   depth within {lab}: median ${med:>8,.0f}  p10 ${np.percentile(vals,10):>7,.0f} "
              f"p90 ${np.percentile(vals,90):>9,.0f}  -> clip multiplier median x{np.median(mult):>5.1f}"
              f"  (min x{min(mult):.2f})")
    thin = [x for x in out if x["d2"] < 2 * x["clip"]]
    print(f"   books where 2x the current clip would NOT fill within +2c: "
          f"{len(thin)}/{len(out)} ({100*len(thin)/len(out):.0f}%)")
    thin10 = [x for x in out if x["d2"] < 10 * x["clip"]]
    print(f"   books that cannot carry 10x the current clip within +2c: "
          f"{len(thin10)}/{len(out)} ({100*len(thin10)/len(out):.0f}%)")
    print(f"   NOTE: this is depth at ONE instant for one side of the book. It bounds the clip,")
    print(f"   it does not model queue position, adverse selection, or the fact that we are")
    print(f"   buying at the ask immediately after a whale prints -- the exact moment the book")
    print(f"   is thinnest on the side we need.")
    with open("data/cheap-tail-fill-probe.json", "w") as f:
        json.dump({"generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                   "rows": out}, f, indent=1)


# ---------------------------------------------------------------- AH
def active_rules(c):
    """The ruleset actually in force, read off the active RuleSet row (read-only)."""
    r = c.execute("SELECT version, rulesJson FROM RuleSet WHERE active=1 "
                  "ORDER BY version DESC LIMIT 1").fetchone()
    if not r:
        return (None, {})
    try:
        return (r["version"], json.loads(r["rulesJson"]))
    except Exception:
        return (r["version"], {})


def load_bets(c, since_ms=0, bot=None):
    """Finished legs carrying (market, outcome) so they can be aggregated into BETS.

    A bet is (marketId, outcome) -- the unit a per-market ceiling actually caps. Every
    sizing number in this repo is per LEG; the question here is what the per-BET total is,
    because 63 legs on one outcome is one position, not 63 decisions.
    """
    sql = """SELECT botId, walletAddress AS wallet, marketId, outcome, entryPrice AS px,
                    simulatedPositionSize AS ntl, realizedPnl AS pnl, openedAt
             FROM PaperTrade
             WHERE isDemo=0 AND status IN ('closed','resolved') AND realizedPnl IS NOT NULL
               AND openedAt >= ?"""
    params = [since_ms]
    if bot:
        sql += " AND botId=?"
        params.append(bot)
    out = []
    for r in c.execute(sql, params).fetchall():
        if not r["px"] or r["px"] <= 0 or not r["ntl"] or r["ntl"] <= 0:
            continue
        out.append({"bot": r["botId"], "wallet": r["wallet"], "market": r["marketId"],
                    "outcome": r["outcome"], "px": r["px"], "ntl": r["ntl"],
                    "pnl": r["pnl"], "ms": r["openedAt"]})
    return out


def apply_bet_cap(legs, cap):
    """Chronologically truncate each bet at `cap` dollars.

    Paper PnL is linear in notional at a fixed entry price, so a partial last leg is
    scaled proportionally -- that is exact for this book, not an approximation.
    Returns (kept_legs, dropped_notional, n_partial).
    """
    by = {}
    for l in legs:
        by.setdefault((l["market"], l["outcome"]), []).append(l)
    kept, dropped, npartial = [], 0.0, 0
    for _, bet in by.items():
        bet.sort(key=lambda l: l["ms"])
        run = 0.0
        for l in bet:
            room = cap - run
            if room <= 1e-9:
                dropped += l["ntl"]
                continue
            if l["ntl"] <= room + 1e-9:
                kept.append(dict(l))
                run += l["ntl"]
            else:
                frac = room / l["ntl"]
                k = dict(l)
                k["ntl"] = room
                k["pnl"] = l["pnl"] * frac
                kept.append(k)
                dropped += l["ntl"] - room
                npartial += 1
                run = cap
    return kept, dropped, npartial


def marginal_bet_dollars(legs, threshold):
    """The dollars a bet accumulated ABOVE `threshold` -- the marginal, not the first, fill.

    This is the honest test of a concentration cap: a cap costs money only if the dollars
    it removes are profitable. Averaging the whole bet hides that, because the first fill
    and the 40th fill are different decisions made at different information sets.
    """
    by = {}
    for l in legs:
        by.setdefault((l["market"], l["outcome"]), []).append(l)
    marg = []
    for _, bet in by.items():
        bet.sort(key=lambda l: l["ms"])
        run = 0.0
        for l in bet:
            before = run
            run += l["ntl"]
            over = max(0.0, run - max(threshold, before))
            if over <= 1e-9:
                continue
            frac = over / l["ntl"]
            marg.append({"market": l["market"], "ntl": over, "pnl": l["pnl"] * frac})
    return marg


def boot_pair(a, b, key_a, key_b, reps=1500, seed=71):
    """Market-clustered bootstrap CI of (sum key_a - sum key_b) over paired leg lists."""
    by = {}
    for tag, legs, key in (("a", a, key_a), ("b", b, key_b)):
        for l in legs:
            d = by.setdefault(l["market"], {"a": 0.0, "b": 0.0})
            d[tag] += l[key]
    keys = list(by)
    if len(keys) < 8:
        return (float("nan"), float("nan"))
    rng = np.random.default_rng(seed)
    vals = []
    for _ in range(reps):
        pick = rng.integers(0, len(keys), len(keys))
        vals.append(sum(by[keys[i]]["a"] - by[keys[i]]["b"] for i in pick))
    return (np.percentile(vals, 2.5), np.percentile(vals, 97.5))


def boot_ratio(items, reps=1500, seed=73):
    """Market-clustered bootstrap CI of sum(pnl)/sum(ntl) as a percent.

    Resamples MARKETS, so both numerator and denominator move -- dividing a PnL CI by a
    fixed notional (the lazy version) understates the interval whenever the big-PnL markets
    are also the big-notional markets, which is exactly this book.
    """
    by = {}
    for x in items:
        d = by.setdefault(x["market"], [0.0, 0.0])
        d[0] += x["pnl"]
        d[1] += x["ntl"]
    keys = list(by)
    if len(keys) < 8:
        return (float("nan"), float("nan"))
    rng = np.random.default_rng(seed)
    vals = []
    for _ in range(reps):
        pick = rng.integers(0, len(keys), len(keys))
        p = sum(by[keys[i]][0] for i in pick)
        n = sum(by[keys[i]][1] for i in pick)
        if n:
            vals.append(100 * p / n)
    if not vals:
        return (float("nan"), float("nan"))
    return (np.percentile(vals, 2.5), np.percentile(vals, 97.5))


def concentration_shadow(c):
    print("\n" + "=" * 100)
    print("AH. CONCENTRATION RAILS ON THE LANE THAT CARRIES THE BOOK")
    print("=" * 100)
    ver, rules = active_rules(c)
    print(f"   active ruleset: v{ver}")
    for k in ("maxMarketNotionalPctOfCap", "maxMarketLegsPerMarketId",
              "maxWalletNotionalPctOfCap", "walletCapBasis", "maxOpenPositions",
              "standardMaxOpenPositions", "minTimeToResolutionHours",
              "standardSkipBandRange", "c200LongshotBandFloor"):
        if k in rules:
            print(f"     {k:34} = {rules[k]}")
    print("   NOTE: the v55 per-market and v58 per-wallet rails are guarded "
          "botId===\"BANKROLL_200\" (v63 commit aace3b5 enumerates the scoping gaps).")
    print("   STANDARD carries the book. Read the two fields above as C-200-ONLY.")

    # ---- open book: is the exposure per BET or per LEG?
    print("\n   (1) OPEN BOOK: legs vs BETS (a bet = marketId + outcome)")
    rows = c.execute(
        """SELECT botId, marketId, outcome, COUNT(*) n, SUM(simulatedPositionSize) ntl,
                  MIN(openedAt) mn, MAX(openedAt) mx
           FROM PaperTrade WHERE isDemo=0 AND status='open'
           GROUP BY botId, marketId, outcome""").fetchall()
    per_bot = {}
    for r in rows:
        d = per_bot.setdefault(r["botId"], {"bets": 0, "legs": 0, "ntl": 0.0, "big": []})
        d["bets"] += 1
        d["legs"] += r["n"]
        d["ntl"] += r["ntl"] or 0
        d["big"].append((r["ntl"] or 0, r["n"], r["marketId"], r["outcome"],
                         (r["mx"] - r["mn"]) / 86_400_000.0))
    for bot, d in sorted(per_bot.items(), key=lambda kv: -kv[1]["ntl"]):
        print(f"   {bot:12} bets {d['bets']:>4}  legs {d['legs']:>4}  "
              f"$ {d['ntl']:>8,.0f}  legs/bet {d['legs']/max(d['bets'],1):>4.1f}  "
              f"$/bet {d['ntl']/max(d['bets'],1):>7.2f}")
        d["big"].sort(reverse=True)
        top = d["big"][:5]
        for ntl, n, mkt, out, span in top:
            print(f"        ${ntl:>7,.2f}  {n:>3} legs  span {span:>6.1f}d  "
                  f"{out[:4]:4} {mkt[:58]}")
        share = sum(x[0] for x in top) / d["ntl"] if d["ntl"] else 0
        print(f"        top-5 bets = {100*share:.0f}% of that lane's open notional")

    # ---- finished book: what do accumulation dollars earn?
    for label, since in (("all-time", 0),
                         ("90d", int((time.time() - 90 * 86400) * 1000)),
                         ("30d", int((time.time() - 30 * 86400) * 1000))):
        legs = load_bets(c, since)
        if not legs:
            continue
        print(f"\n   (2) MARGINAL BET DOLLARS -- {label} (all lanes, cost = dollars at risk)")
        print(f"   {'threshold':>9} {'bets>thr':>8} {'marg ntl':>9} {'marg pnl':>9} "
              f"{'marg ROI%':>9} {'CI low':>8} {'CI hi':>8}")
        for thr in (25, 50, 100, 150, 200, 400):
            m = marginal_bet_dollars(legs, thr)
            if not m:
                continue
            ntl = sum(x["ntl"] for x in m)
            pnl = sum(x["pnl"] for x in m)
            lo, hi = boot_ratio(m)
            print(f"   {('$'+str(thr)):>9} {len({x['market'] for x in m}):>8} "
                  f"{ntl:>9,.0f} {pnl:>+9,.0f} "
                  f"{100*pnl/ntl if ntl else 0:>+9.1f} "
                  f"{lo:>+8.1f} {hi:>+8.1f}")
            # ex-top-5 markets: is the marginal result one market wearing a cohort's clothes?
            by_m = {}
            for x in m:
                by_m.setdefault(x["market"], [0.0, 0.0])
                by_m[x["market"]][0] += x["pnl"]
                by_m[x["market"]][1] += x["ntl"]
            ranked = sorted(by_m.items(), key=lambda kv: -kv[1][0])[5:]
            n5 = sum(v[1] for _, v in ranked)
            p5 = sum(v[0] for _, v in ranked)
            print(f"   {'':>9} ex-top-5 markets: {n5:>9,.0f} {p5:>+9,.0f} "
                  f"{100*p5/n5 if n5 else 0:>+9.1f}")
        print(f"        (bets>thr counted as distinct MARKETS holding marginal dollars)")

    # ---- the cap ladder: what a per-bet ceiling would have produced
    for label, since in (("all-time", 0),
                         ("90d", int((time.time() - 90 * 86400) * 1000))):
        legs = load_bets(c, since)
        if not legs:
            continue
        print(f"\n   (3) PER-BET CAP LADDER -- {label}, all lanes")
        print(f"   {'cap':>6} {'legs kept':>9} {'notional':>9} {'pnl':>9} {'ROI%':>7} "
              f"{'dPnL vs none':>12} {'CI low':>8} {'CI hi':>8} {'drop $':>8}")
        base_pnl = sum(l["pnl"] for l in legs)
        base_ntl = sum(l["ntl"] for l in legs)
        print(f"   {'none':>6} {len(legs):>9} {base_ntl:>9,.0f} {base_pnl:>+9,.0f} "
              f"{100*base_pnl/base_ntl:>+7.1f} {'-':>12} {'-':>8} {'-':>8} {0:>8,.0f}")
        for cap in (25, 50, 100, 150, 200, 400):
            kept, dropped, npart = apply_bet_cap(legs, cap)
            pnl = sum(l["pnl"] for l in kept)
            ntl = sum(l["ntl"] for l in kept)
            lo, hi = boot_pair([], legs_by_market_pnl(legs, kept), "pnl", "pnl")
            print(f"   {('$'+str(cap)):>6} {len(kept):>9} {ntl:>9,.0f} {pnl:>+9,.0f} "
                  f"{100*pnl/ntl:>+7.1f} {pnl-base_pnl:>+12,.0f} "
                  f"{lo:>+8,.0f} {hi:>+8,.0f} {dropped:>8,.0f}")

    # ---- the refutation check: does the cap touch the one leg that made the book?
    print("\n   (4) THE ONE LEG THAT MADE THE BOOK -- does any cap reach it?")
    top = c.execute(
        """SELECT p.id, p.botId, p.walletAddress, p.marketId, p.outcome, p.entryPrice,
                  p.simulatedPositionSize ntl, p.realizedPnl pnl, p.openedAt
           FROM PaperTrade p WHERE p.isDemo=0 AND p.realizedPnl IS NOT NULL
           ORDER BY p.realizedPnl DESC LIMIT 3""").fetchall()
    for r in top:
        agg = c.execute(
            """SELECT COUNT(*) n, SUM(simulatedPositionSize) ntl, SUM(realizedPnl) pnl
               FROM PaperTrade WHERE isDemo=0 AND marketId=? AND outcome=? AND botId=?""",
            (r["marketId"], r["outcome"], r["botId"])).fetchone()
        print(f"   leg {r['id'][:10]} {r['botId']:12} pnl ${r['pnl']:>+9,.2f} "
              f"ntl ${r['ntl']:>7,.2f} | its BET: {agg['n']} legs "
              f"${agg['ntl'] or 0:>8,.2f} pnl ${agg['pnl'] or 0:>+9,.2f} "
              f"-> a $100 bet-cap {'WOULD' if (agg['ntl'] or 0) > 100 else 'would NOT'} bind")

    # ---- per-wallet mirror
    print("\n   (5) PER-WALLET CONCENTRATION -- open book, all lanes")
    wr = c.execute(
        """SELECT walletAddress w, COUNT(DISTINCT marketId||outcome) bets, COUNT(*) legs,
                  SUM(simulatedPositionSize) ntl
           FROM PaperTrade WHERE isDemo=0 AND status='open' GROUP BY 1
           ORDER BY ntl DESC LIMIT 8""").fetchall()
    tot = c.execute("""SELECT SUM(simulatedPositionSize) FROM PaperTrade
                       WHERE isDemo=0 AND status='open'""").fetchone()[0] or 0
    for r in wr:
        print(f"   {r['w'][:14]:14} bets {r['bets']:>4} legs {r['legs']:>4} "
              f"${r['ntl'] or 0:>8,.2f}  {100*(r['ntl'] or 0)/tot:>5.1f}% of open")


def legs_by_market_pnl(legs, kept):
    """Legs NOT kept, as a zero-notional marker per market -- the paired bootstrap arm.

    Returning the dropped legs with their PnL intact lets boot_pair compute
    kept-minus-dropped per market, which is the delta the cap buys.
    """
    idx = {(l["market"], l["outcome"], l["ms"], round(l["ntl"], 8)) for l in kept}
    return [l for l in legs
            if (l["market"], l["outcome"], l["ms"], round(l["ntl"], 8)) not in idx]


def skip_range(rules, key):
    """Parse a "lo-hi" band-skip field into (lo, hi) floats, or None."""
    v = (rules or {}).get(key) or ""
    if not isinstance(v, str) or "-" not in v:
        return None
    try:
        lo, hi = v.split("-", 1)
        return (float(lo), float(hi))
    except Exception:
        return None


def in_range(px, rng):
    return bool(rng) and rng[0] <= px < rng[1]


def ttl_floor_ladder(c):
    """AI. Is the <24h TTL loss ADDITIVE to the v63 band skip, or already covered by it?

    The whole TTL gate is only worth activating if the cohort it blocks still loses money
    after the live band skip removes 0.4-0.6. If the <24h loss lives inside 0.4-0.6, then
    v63 already bought it and raising minTimeToResolutionHours is a no-op dressed as a fix.
    That is the hygiene test this section exists to run, and it is run before any proposal.
    """
    print("\n" + "=" * 100)
    print("AI. TTL FLOOR LADDER -- net of the live band skip (the gate's own hygiene test)")
    print("=" * 100)
    ver, rules = active_rules(c)
    std_skip = skip_range(rules, "standardSkipBandRange")
    c200_skip = skip_range(rules, "c200SkipBandRange")
    live_floor = rules.get("minTimeToResolutionHours")
    print(f"   active v{ver}: minTimeToResolutionHours={live_floor}  "
          f"standardSkipBandRange={rules.get('standardSkipBandRange')!r}  "
          f"c200SkipBandRange={rules.get('c200SkipBandRange')!r}")

    for label, since in (("all-time", 0),
                         ("90d", int((time.time() - 90 * 86400) * 1000)),
                         ("30d", int((time.time() - 30 * 86400) * 1000))):
        legs = ttl_edges(c, since)
        if not legs:
            continue
        # Apply the LIVE skip exactly as the scorer would: STANDARD drops 0.4-0.6, C-200
        # drops its own range. Legs a live rule already refuses can never be blocked by a
        # TTL floor, so including them would credit the floor with v63's work.
        live = [l for l in legs
                if not (l["bot"] == "STANDARD" and in_range(l["px"], std_skip))
                and not (l["bot"] == "BANKROLL_200" and in_range(l["px"], c200_skip))]
        print(f"\n   {label}: {len(legs)} TTL legs -> {len(live)} survive the live band skip "
              f"({len(legs)-len(live)} already refused)")
        print(f"   {'floor':>6} {'blocked n':>9} {'blk ntl':>8} {'blk pnl':>8} {'blk ROI%':>8} "
              f"{'CI low':>7} {'CI hi':>7} {'ex10':>7} {'blk $/1k-cd':>11}")
        for floor in (2, 12, 24, 48, 72, 168):
            blk = [l for l in live if l["ttl"] < floor]
            if len(blk) < 5:
                continue
            ntl = sum(l["ntl"] for l in blk)
            pnl = sum(l["pnl"] for l in blk)
            lo, hi = boot_ratio(blk)
            ex = roi(ex_top(blk, 10)) if len(blk) > 12 else float("nan")
            tag = "LIVE" if floor == live_floor else ""
            print(f"   {floor:>4}h{tag:1} {len(blk):>9} {ntl:>8,.0f} {pnl:>+8,.0f} "
                  f"{100*pnl/ntl if ntl else 0:>+8.1f} {lo:>+7.1f} {hi:>+7.1f} "
                  f"{ex:>+7.1f} {usd_per_1k_cd(blk):>+11.2f}")
        print(f"   {'':>6} {'kept n':>9} {'kept ntl':>8} {'kept pnl':>8} {'kept ROI%':>8} "
              f"{'CI low':>7} {'CI hi':>7} {'ex10':>7} {'kept $/1k-cd':>11}")
        for floor in (2, 12, 24, 48, 72, 168):
            kp = [l for l in live if l["ttl"] >= floor]
            if len(kp) < 5:
                continue
            ntl = sum(l["ntl"] for l in kp)
            pnl = sum(l["pnl"] for l in kp)
            lo, hi = boot_ratio(kp)
            ex = roi(ex_top(kp, 10)) if len(kp) > 12 else float("nan")
            print(f"   {floor:>6}h {len(kp):>9} {ntl:>8,.0f} {pnl:>+8,.0f} "
                  f"{100*pnl/ntl if ntl else 0:>+8.1f} {lo:>+7.1f} {hi:>+7.1f} "
                  f"{ex:>+7.1f} {usd_per_1k_cd(kp):>+11.2f}")

    # The overlap that decides it: how much of the <24h loss sits in the band v63 kills?
    print("\n   OVERLAP -- where the <24h TTL dollars and losses actually live (all-time)")
    legs = ttl_edges(c, 0)
    short = [l for l in legs if l["ttl"] < 24]
    tot_ntl = sum(l["ntl"] for l in legs)
    print(f"   <24h TTL: {len(short)} legs, ${sum(l['ntl'] for l in short):,.0f} "
          f"({100*sum(l['ntl'] for l in short)/tot_ntl:.1f}% of TTL-joined notional), "
          f"pnl ${sum(l['pnl'] for l in short):+,.0f}")
    for nm, lo_, hi_ in zip(NAMES, *zip(*BANDS)):
        sub = [l for l in short if band_of(l["px"]) == nm]
        if not sub:
            continue
        ntl = sum(l["ntl"] for l in sub)
        pnl = sum(l["pnl"] for l in sub)
        print(f"     {nm:9} {len(sub):>5} legs ${ntl:>7,.0f} pnl ${pnl:>+8,.0f} "
              f"ROI {100*pnl/ntl if ntl else 0:>+7.1f}%"
              f"{'   <- v63 refuses this band on STANDARD' if nm == '0.4-0.6' else ''}")
    # And the same cut for STANDARD only, which is the lane the floor would bind on.
    sshort = [l for l in short if l["bot"] == "STANDARD"]
    s0 = [l for l in sshort if band_of(l["px"]) != "0.4-0.6"]
    for nm, grp in (("<24h STANDARD all bands", sshort),
                    ("<24h STANDARD ex-0.4-0.6", s0)):
        ntl = sum(l["ntl"] for l in grp)
        pnl = sum(l["pnl"] for l in grp)
        lo, hi = boot_ratio(grp)
        print(f"     {nm:26} {len(grp):>5} legs ${ntl:>7,.0f} pnl ${pnl:>+8,.0f} "
              f"ROI {100*pnl/ntl if ntl else 0:>+7.1f}% CI [{lo:+.1f},{hi:+.1f}]")


def ttl_shadow_reconciliation(c):
    """AK. Reconcile the PENDING floor's evidence with the live band skip.

    data/ttr-floor-shadow-calibration.json justifies the approved 2h->24h floor with
    "-12.78% on 3,405 legs". scripts/ttr-floor-shadow.py selects that band on TTL ALONE
    (no price filter), so it counts STANDARD legs in 0.4-0.6 -- the band v63 began
    refusing on 2026-10-20, three days before the floor was approved. This replays the
    identical cohort and then removes the legs v63 refuses, on the same axis.
    """
    print("\n" + "=" * 100)
    print("AK. THE PENDING 2h->24h FLOOR: same cohort, with and without the v63 band skip")
    print("=" * 100)
    ver, rules = active_rules(c)
    std_skip = skip_range(rules, "standardSkipBandRange")
    legs = [l for l in ttl_edges(c, 0) if l["bot"] == "STANDARD"]
    band = [l for l in legs if 2.0 <= l["ttl"] < 24.0]
    print(f"   cohort = STANDARD, entry TTL in [2,24)h, all-time -- exactly the shadow's band")
    print(f"   live standardSkipBandRange = {rules.get('standardSkipBandRange')!r} (v63, 2026-10-20)")
    for nm, grp in (("as the shadow measures it", band),
                    ("net of the v63 band skip", [l for l in band
                                                  if not in_range(l["px"], std_skip)]),
                    ("the legs v63 already refuses", [l for l in band
                                                      if in_range(l["px"], std_skip)])):
        if not grp:
            print(f"   {nm:28} (empty)")
            continue
        ntl = sum(l["ntl"] for l in grp)
        pnl = sum(l["pnl"] for l in grp)
        lo, hi = boot_ratio(grp)
        ex = roi(ex_top(grp, 10)) if len(grp) > 12 else float("nan")
        print(f"   {nm:28} {len(grp):>5} legs ${ntl:>8,.0f} pnl ${pnl:>+8,.0f} "
              f"ROI {100*pnl/ntl:>+7.1f}% CI [{lo:+.1f},{hi:+.1f}] ex10 {ex:+.1f}% "
              f"$/1k-cd {usd_per_1k_cd(grp):>+8.2f}")
    print("   DECISION RULE ON THE CARD: 'flip unless shadow >= +3% on >=150 blocked legs'.")
    print("   The row above that excludes v63's band is the one the floor would actually bind on.")
    # The same two rows on the live-leaning windows.
    for label, since in (("90d", int((time.time() - 90 * 86400) * 1000)),
                         ("30d", int((time.time() - 30 * 86400) * 1000))):
        lg = [l for l in ttl_edges(c, since) if l["bot"] == "STANDARD"]
        b2 = [l for l in lg if 2.0 <= l["ttl"] < 24.0]
        net = [l for l in b2 if not in_range(l["px"], std_skip)]
        if not net:
            continue
        n0, p0 = sum(l["ntl"] for l in b2), sum(l["pnl"] for l in b2)
        n1, p1 = sum(l["ntl"] for l in net), sum(l["pnl"] for l in net)
        lo, hi = boot_ratio(net)
        print(f"   {label:>4}: raw {len(b2):>5} ${n0:>7,.0f} {100*p0/n0 if n0 else 0:>+7.1f}%"
              f"   net-of-skip {len(net):>5} ${n1:>7,.0f} {100*p1/n1 if n1 else 0:>+7.1f}%"
              f" CI [{lo:+.1f},{hi:+.1f}]")


def ttl_sizing_shadow(c):
    """AJ. STANDARD sizes flat across a TTL axis whose ROI ranges 9x. What would sizing it do?

    The standing sizing finding is that STANDARD sizes flat across BANDS within 26%. The
    same blindness exists on TTL, which no size rule has ever touched. Reported two ways:
      (a) notional-neutral  -- same dollars deployed, moved between cohorts. The reallocation.
      (b) as-specified      -- the schedule applied literally, total exposure scales. The bet.
    and both on ROI (per dollar) and $/1k-cd (per capital-day), because they disagree.
    """
    print("\n" + "=" * 100)
    print("AJ. TTL-AWARE SIZING ON STANDARD -- realised shadow, notional-neutral and as-specified")
    print("=" * 100)
    ver, rules = active_rules(c)
    if not rules.get("standardMaxEntryPrice"):
        print("   (ruleset has no standardMaxEntryPrice field; sizing shadow runs unfiltered)")
    std_skip = skip_range(rules, "standardSkipBandRange")

    def bucket(ttl):
        return 0 if ttl < 24 else (1 if ttl < 72 else 2)

    def run(legs, schedule, neutral, clamp=True):
        tot0 = sum(l["ntl"] for l in legs)
        scaled = []
        for l in legs:
            w = schedule[bucket(l["ttl"])]
            new = l["ntl"] * w
            if clamp:
                # BOT_LIMITS.STANDARD is {min: 0.25, max: 20.00} (src/lib/safety.ts:19) and
                # clampPaperSize applies it AFTER any size factor, so a schedule that asks for
                # more than $20/leg does not book. Simulating without this clamp would quote an
                # effect the code cannot produce.
                new = min(20.0, max(0.25, new))
            f = (new / l["ntl"]) if l["ntl"] else 1.0
            k = dict(l)
            k["ntl"] = new
            k["pnl"] = l["pnl"] * f
            scaled.append(k)
        if neutral:
            tot1 = sum(k["ntl"] for k in scaled)
            f = tot0 / tot1 if tot1 else 1.0
            for k in scaled:
                k["ntl"] *= f
                k["pnl"] *= f
        return scaled

    for label, since in (("all-time", 0),
                         ("90d", int((time.time() - 90 * 86400) * 1000))):
        legs = [l for l in ttl_edges(c, since)
                if l["bot"] == "STANDARD" and not in_range(l["px"], std_skip)]
        if not legs:
            continue
        print(f"\n   {label}: {len(legs)} STANDARD legs net of the v63 skip, ${sum(l['ntl'] for l in legs):,.0f}")
        print(f"   realised clip by TTL cohort -- is STANDARD sizing TTL-blind?")
        for nm, lo_, hi_ in (("<24h", 0, 24), ("24-72h", 24, 72), (">=72h", 72, 10**9)):
            g = [l for l in legs if lo_ <= l["ttl"] < hi_]
            if not g:
                continue
            print(f"     {nm:7} {len(g):>5} legs  median clip ${np.median([l['ntl'] for l in g]):>6.2f}"
                  f"  p90 ${np.percentile([l['ntl'] for l in g], 90):>6.2f}"
                  f"  ROI {roi(g):>+7.1f}%  $/1k-cd {usd_per_1k_cd(g):>+8.2f}")
        base = run(legs, (1, 1, 1), False)
        print(f"   {'schedule':34} {'notional':>9} {'pnl':>9} {'ROI%':>7} {'$/1k-cd':>8} "
              f"{'dPnL CI low':>12} {'CI hi':>9}")
        b_pnl = sum(l["pnl"] for l in base)
        print(f"   {'flat (live)':34} {sum(l['ntl'] for l in base):>9,.0f} {b_pnl:>+9,.0f} "
              f"{roi(base):>+7.1f} {usd_per_1k_cd(base):>+8.2f} {'-':>12} {'-':>9}")
        for nm, sch in (("mild  0.5/1.0/1.5", (0.5, 1.0, 1.5)),
                        ("strong 0.25/1.0/2.0", (0.25, 1.0, 2.0)),
                        ("inverse 2.0/1.0/0.5", (2.0, 1.0, 0.5))):
            for neutral in (True, False):
                g = run(legs, sch, neutral)
                lo, hi = boot_pair(g, base, "pnl", "pnl")
                tag = f"{nm} {'(neutral)' if neutral else '(as-is)':10}"
                print(f"   {tag:34} {sum(l['ntl'] for l in g):>9,.0f} "
                      f"{sum(l['pnl'] for l in g):>+9,.0f} {roi(g):>+7.1f} "
                      f"{usd_per_1k_cd(g):>+8.2f} {lo:>+12,.0f} {hi:>+9,.0f}")
        print("   'inverse' is the falsification arm: if short TTL were the good cohort, the")
        print("   inverse schedule would win. It is the control, not a proposal.")

        # --- hygiene: is the improvement one market, and where does the up-weight land?
        strong = run(legs, (0.25, 1.0, 2.0), True)
        print(f"\n   ex-top-N on the strong schedule vs flat (notional-neutral):")
        for k in (1, 3, 5, 10):
            a = roi(ex_top(strong, k))
            b = roi(ex_top(base, k))
            print(f"     ex-top-{k:<2} strong {a:>+7.1f}%   flat {b:>+7.1f}%   delta {a-b:>+7.1f}pp")
        by_m = {}
        for l in strong:
            by_m.setdefault(l["market"], 0.0)
            by_m[l["market"]] += l["pnl"]
        topm = sorted(by_m.items(), key=lambda kv: -kv[1])[:5]
        print(f"   top-5 markets under the strong schedule: "
              + ", ".join(f"{k[:26]} ${v:+,.0f}" for k, v in topm))
        # delta notional by TTL cohort: who gets the freed dollars
        print(f"   notional moved (notional-neutral, so it nets to zero):")
        for nm, lo_, hi_ in (("<24h", 0, 24), ("24-72h", 24, 72), (">=72h", 72, 10**9)):
            g0 = [l for l in base if lo_ <= l["ttl"] < hi_]
            g1 = [l for l in strong if lo_ <= l["ttl"] < hi_]
            d = sum(l["ntl"] for l in g1) - sum(l["ntl"] for l in g0)
            print(f"     {nm:7} ${sum(l['ntl'] for l in g0):>8,.0f} -> "
                  f"${sum(l['ntl'] for l in g1):>8,.0f}  ({d:>+8,.0f})")
        # FILLABILITY: how much entry slippage kills the up-weighted cohort's edge?
        g72 = [l for l in legs if l["ttl"] >= 72]
        if g72:
            avgp = sum(l["px"] * l["ntl"] for l in g72) / sum(l["ntl"] for l in g72)
            r = roi(g72) / 100.0
            medclip = np.median([l["ntl"] for l in g72])
            print(f"   FILLABILITY, >=72h cohort: ntl-wtd entry price {avgp:.3f}, "
                  f"ROI {100*r:+.1f}%, median clip ${medclip:.2f}")
            print(f"     BREAKEVEN ENTRY SLIPPAGE = {100*r}% x {avgp:.3f} = "
                  f"{100*r*avgp:.2f} cents per share -- the up-weight doubles the clip, so "
                  f"the fill can worsen by {100*r*avgp:.2f}c before the cohort's edge is gone.")
            print(f"     (doubling the clip needs ${medclip*2:,.2f} of depth at the ask in that market)")
            print(f"   >=72h cohort by entry band -- is the up-weight funding cheap longshots?")
            print(f"     {'band':9} {'legs':>5} {'notional':>9} {'pnl':>8} {'ROI%':>7} {'ex10':>7} {'$/1k-cd':>8}")
            for nm in NAMES:
                gb = [l for l in g72 if band_of(l["px"]) == nm]
                if not gb:
                    continue
                ntl_b = sum(l["ntl"] for l in gb)
                pnl_b = sum(l["pnl"] for l in gb)
                exb = roi(ex_top(gb, 10)) if len(gb) > 12 else float("nan")
                print(f"     {nm:9} {len(gb):>5} {ntl_b:>9,.0f} {pnl_b:>+8,.0f} "
                      f"{100*pnl_b/ntl_b if ntl_b else 0:>+7.1f} {exb:>+7.1f} "
                      f"{usd_per_1k_cd(gb):>+8.2f}")


def main():
    c = con()
    if "--only-ah" in ARGS:
        concentration_shadow(c)
        return
    if "--only-ai" in ARGS:
        ttl_floor_ladder(c)
        return
    if "--only-ak" in ARGS:
        ttl_shadow_reconciliation(c)
        ttl_sizing_shadow(c)
        return
    legs = load_finished(c)
    print(f"loaded {len(legs)} finished real legs (all-time), "
          f"{len({l['market'] for l in legs})} markets")
    velocity_table(legs, "all-time, finished legs, cost = dollars at risk")
    if T30:
        since = int((time.time() - 30 * 86400) * 1000)
        velocity_table(load_finished(c, since), "last 30 days")
    capital_audit(c, legs)
    ground_truth_stop(c, legs)
    sizing_headroom(c, legs)
    implied_capital(legs)
    dedupe_audit(c)
    ttl_report(c)
    ttl_by_lane(c)
    ttl_robustness(c)
    ladder_effect(c)
    calibration_report(c)
    exit_alpha_report(c)
    exit_alpha_report(c, "last 90d", int((time.time() - 90 * 86400) * 1000))
    high_price_audit(c)
    truth_bands(c)
    truth_bands(c, "last 90d", int((time.time() - 90 * 86400) * 1000))
    cheap_tail_decomposition(c)
    # 2026-10-25: the concentration and maturity sections. In the DEFAULT run on purpose --
    # a review whose numbers only exist behind a flag is unreproducible by the next reader.
    concentration_shadow(c)
    ttl_floor_ladder(c)
    ttl_shadow_reconciliation(c)
    ttl_sizing_shadow(c)
    cheap_tail_fill_probe(c)


if __name__ == "__main__":
    main()
