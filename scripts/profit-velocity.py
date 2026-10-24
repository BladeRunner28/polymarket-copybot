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
import sqlite3
import sys
import time
import numpy as np

DB = "prisma/dev.db"
ARGS = sys.argv[1:]
T30 = "--t30" in ARGS
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


def main():
    c = con()
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


if __name__ == "__main__":
    main()
