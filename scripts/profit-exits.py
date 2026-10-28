#!/usr/bin/env python3
"""
AO. THE v66 DISPOSAL, PRICED AS A PURCHASE.

WHY THIS EXISTS
---------------
v66 (user-approved 2026-10-23) gave STANDARD its first stale-exit rail: close any leg
entered at >= standardStaleExitBandMin once it is older than standardStaleExitHours. On
its first tick (2026-10-24 02:06) it closed 701 legs / $7,321.20 cost for -$350.52.

Every write-up since has quoted that -$350.52 as the cost of the rule. It is not a cost:
the mark loss already existed on 10-24, and the sweep converted it to cash (book
realised+unrealised moved $11,481.10 -> $11,495.70 on the night). What the rule actually
bought and paid is therefore TWO things, and neither has been priced:

  1. PAID: exit alpha -- the difference between the mark it sold at and what those
     markets actually settled at. Measurable only against settlement truth.
  2. BOUGHT: leg SLOTS. STANDARD's only scarce resource is `standardMaxOpenPositions`
     (a leg count, not dollars -- the gross-exposure cap is applied to C-200 only, see
     score-trades.ts:198/625). Freed slots are worth whatever a slot earns, times how
     fast the lane refills them.

So the question this section answers is not "was -$350 bad" but "what did 701 slots cost
per slot, and did the marks it sold at beat settlement".

METHOD / CONTRACTS
------------------
* Cohort identified by the v66 PREDICATE (age >= standardStaleExitHours at close,
  entryPrice >= standardStaleExitBandMin, botId=STANDARD) AND the close date, then
  cross-checked against the raw 10-24 close set so no other close path can leak in.
* openPnl / holdPnl identities: dollars at risk n at price p is n/p shares, so a
  settlement at s realises n*(s/p - 1) and an exit at c realises n*(c/p - 1). Verified
  against realizedPnl before use (max abs error printed).
* Settlement truth: archived CLOB /markets/<conditionId> tokens[].winner, keyless,
  cached in data/market-truth-clob.json (same file and semantics as §AB in
  scripts/profit-velocity.py -- imported from there, not re-implemented). Coverage is
  PRINTED: a truth join that silently drops half the book is an instrument that cannot
  fail.
* Slot value is measured on RESOLVED-ONLY legs (natural settlement), never on `closed`
  legs, because `closed` is the exit policy's own output and conditioning on it is the
  error the 2026-10-24 review found in the band ROIs.
* Market-clustered bootstrap on every alpha figure (resamples markets, not legs).

READ-ONLY. No prisma write, no RuleSet row, no rule edit.

RUN
  DATA_MODE=live python3 scripts/profit-exits.py            # default
  DATA_MODE=live python3 scripts/profit-exits.py --no-fetch # offline (cache only)
"""
import importlib.util
import json
import os
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from statistics import median

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)

# ---- reuse the committed truth + bootstrap helpers instead of re-implementing them.
_spec = importlib.util.spec_from_file_location("pv", os.path.join(ROOT, "scripts", "profit-velocity.py"))
pv = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pv)

NAMES = pv.NAMES

DB = "prisma/dev.db"
NO_FETCH = "--no-fetch" in sys.argv
SWEEP_DATE = "2026-10-24"
DAY = 86_400_000.0


def con():
    import sqlite3
    c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    c.row_factory = sqlite3.Row
    return c


def ts(ms):
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")


def live_rules(c):
    row = c.execute("SELECT version, rulesJson FROM RuleSet ORDER BY version DESC LIMIT 1").fetchone()
    return row["version"], json.loads(row["rulesJson"])


def band2(px):
    if px < 0.60:
        return "<0.60"
    if px < 0.80:
        return "0.60-0.80"
    return "0.80-1.00"


# --------------------------------------------------------------------------- AO.1
def sweep_cohort(c, rules):
    """The v66 disposal, identified by its own predicate and cross-checked by date."""
    hours = rules.get("standardStaleExitHours") or 0
    floor = rules.get("standardStaleExitBandMin") or 0.0
    day_lo = int(datetime(2026, 10, 24, tzinfo=timezone.utc).timestamp() * 1000)
    day_hi = day_lo + DAY
    raw = c.execute(
        """SELECT id, marketId, outcome, entryPrice px, currentPrice cur,
                  simulatedPositionSize ntl, realizedPnl pnl, openedAt, closedAt
           FROM PaperTrade
           WHERE botId='STANDARD' AND status='closed' AND isDemo=0
             AND closedAt >= ? AND closedAt < ?""", (day_lo, day_hi)).fetchall()
    cohort, other = [], []
    for r in raw:
        age_h = (r["closedAt"] - r["openedAt"]) / 3_600_000.0
        (cohort if (age_h >= hours and r["px"] >= floor) else other).append(dict(r))
    return cohort, other, hours, floor


def reproduce(c, rules, cohort, other, hours, floor):
    print("=" * 100)
    print("AO.1  THE v66 DISPOSAL -- reproduced from the predicate, not from the report")
    print("=" * 100)
    print(f"   live RuleSet v{rules.get('_v')}: standardStaleExitHours={hours} "
          f"standardStaleExitBandMin={floor}")
    nt = sum(l["ntl"] for l in cohort)
    pnl = sum(l["pnl"] for l in cohort)
    print(f"   STANDARD closes dated {SWEEP_DATE}: {len(cohort) + len(other)}  "
          f"of which predicate-matching {len(cohort)}, non-matching {len(other)}")
    print(f"   cohort: {len(cohort)} legs  ${nt:,.2f} cost  ${pnl:+,.2f} realised  "
          f"({100 * pnl / nt:+.2f}%)  median clip ${median([l['ntl'] for l in cohort]):.2f}  "
          f"mean age {(sum((l['closedAt'] - l['openedAt']) / 3_600_000.0 for l in cohort) / len(cohort)):,.0f}h")
    # identity check: does n*(cur/px-1) reproduce realizedPnl?
    err = max(abs(l["ntl"] * (l["cur"] / l["px"] - 1.0) - l["pnl"]) for l in cohort)
    print(f"   cost-basis identity max |n*(c/p-1) - realizedPnl| = ${err:.4f} "
          f"(dollars-at-risk basis confirmed)")
    print()
    print(f"   {'band':10} {'legs':>5} {'cost':>9} {'realised':>9} {'ROI':>8} "
          f"{'medEntry':>9} {'medExit':>8} {'medMove':>8}")
    for b in ("0.60-0.80", "0.80-1.00"):
        g = [l for l in cohort if band2(l["px"]) == b]
        if not g:
            continue
        bn = sum(l["ntl"] for l in g)
        bp = sum(l["pnl"] for l in g)
        print(f"   {b:10} {len(g):>5} {bn:>9,.0f} {bp:>+9,.2f} {100 * bp / bn:>+7.2f}% "
              f"{median([l['px'] for l in g]):>9.3f} {median([l['cur'] for l in g]):>8.3f} "
              f"{median([l['cur'] - l['px'] for l in g]):>+8.3f}")

    # market concentration of the disposal
    agg = defaultdict(lambda: [0, 0.0, 0.0])
    for l in cohort:
        a = agg[l["marketId"]]
        a[0] += 1
        a[1] += l["ntl"]
        a[2] += l["pnl"]
    top = sorted(agg.items(), key=lambda kv: kv[1][2])[:6]
    print(f"\n   {len(agg)} markets disposed of. Worst six by realised:")
    for m, (n, n2, p) in top:
        print(f"     {p:+9.2f}  {n:>3} legs ${n2:>8.2f}  {m[:66]}")
    print(f"   top-3 markets account for ${sum(v[2] for _, v in sorted(agg.items(), key=lambda kv: kv[1][2])[:3]):+,.2f}"
          f" of ${pnl:+,.2f} disposed")
    return cohort


# --------------------------------------------------------------------------- AO.2
def resource_inventory(c, rules, cohort):
    """Is the thing v66 released scarce at all? Prices the resource, not the rule."""
    print("\n" + "=" * 100)
    print("AO.2  WHAT THE RELEASE WAS FOR -- the lane's actual scarce resource")
    print("=" * 100)
    cap_legs = rules.get("standardMaxOpenPositions") or 0
    gross_base = rules.get("maxGrossExposureUsd") or 0
    # t0 is DATA-DERIVED: the first close in the cohort. A hardcoded 02:06 was CDT when the
    # DB stores UTC, which silently shifted the "before" snapshot by five hours.
    t0 = min(l["closedAt"] for l in cohort)

    def open_at(t):
        return c.execute(
            """SELECT COUNT(*) n, COALESCE(SUM(simulatedPositionSize),0) nt
               FROM PaperTrade WHERE botId='STANDARD' AND isDemo=0 AND openedAt < ?
                 AND (closedAt IS NULL OR closedAt >= ?)
                 AND (resolvedAt IS NULL OR resolvedAt >= ?)""", (t, t, t)).fetchone()

    pre, post = open_at(t0 - 1), open_at(t0 + 3_600_000)
    now = c.execute(
        """SELECT COUNT(*) n, COALESCE(SUM(simulatedPositionSize),0) nt
           FROM PaperTrade WHERE botId='STANDARD' AND status='open' AND isDemo=0""").fetchone()
    print(f"   leg cap (v64, standardMaxOpenPositions) = {cap_legs} legs.  "
          f"gross-exposure base = ${gross_base} -- applied to C-200 ONLY")
    print(f"   STANDARD open notional right now: ${now['nt']:,.2f} = "
          f"{now['nt'] / gross_base:.1f}x that base, which is the arithmetic proof the "
          f"notional cap does not govern this lane.")
    print(f"   open legs: before sweep {pre['n']} (${pre['nt']:,.0f}) -> after "
          f"{post['n']} (${post['nt']:,.0f}) -> today {now['n']} (${now['nt']:,.0f})")
    print(f"   slot headroom: before {cap_legs - pre['n']:,} -> after {cap_legs - post['n']:,} "
          f"-> today {cap_legs - now['n']:,}")
    return t0, pre, post, now, cap_legs


# --------------------------------------------------------------------------- AO.3
def slot_economics(c, t0, pre, post, now, cap_legs, cohort):
    """A slot's worth, the refill rate, and what 701 slots therefore cost per slot."""
    print("\n" + "=" * 100)
    print("AO.3  A SLOT'S PRICE -- measured on natural settlements only, never on exits")
    print("=" * 100)
    era = int(datetime(2026, 9, 15, tzinfo=timezone.utc).timestamp() * 1000)
    rows = c.execute(
        """SELECT realizedPnl pnl, simulatedPositionSize ntl FROM PaperTrade
           WHERE botId='STANDARD' AND isDemo=0 AND status='resolved'
             AND realizedPnl IS NOT NULL AND openedAt >= ?""", (era,)).fetchall()
    per_leg = [r["pnl"] for r in rows]
    nt = sum(r["ntl"] for r in rows)
    if per_leg:
        print(f"   resolved-only, opened >= 2026-09-15: {len(per_leg)} legs  "
              f"${nt:,.2f} cost  ${sum(per_leg):+,.2f}  {100 * sum(per_leg) / nt:+.2f}%")
        print(f"   per-leg: mean ${sum(per_leg) / len(per_leg):+.3f}  "
              f"median ${median(per_leg):+.3f}  "
              f"share positive {100 * sum(1 for p in per_leg if p > 0) / len(per_leg):.0f}%  "
              f"top-1 leg ${max(per_leg):+.2f} = {100 * max(per_leg) / sum(per_leg):+.0f}% of the total")
        p10 = float(np.percentile(per_leg, 10))
        p90 = float(np.percentile(per_leg, 90))
        print(f"   per-leg p10 ${p10:+.2f} / p90 ${p90:+.2f}")

    # refill: how fast does the lane put legs back on?
    days = (time.time() * 1000 - t0) / DAY
    opens = c.execute(
        """SELECT COUNT(*) n, COALESCE(SUM(simulatedPositionSize),0) nt FROM PaperTrade
           WHERE botId='STANDARD' AND isDemo=0 AND openedAt >= ?""", (t0,)).fetchone()
    released = len(cohort)
    fill = opens["n"] / released
    print(f"\n   {days:.1f} days since the sweep: {opens['n']} new STANDARD legs "
          f"(${opens['nt']:.2f}) = {opens['n'] / days:.1f} legs/day")
    print(f"   refill of the {released} released slots: {opens['n']}/{released} = "
          f"{100 * fill:.1f}%  -> at this rate the release is consumed in "
          f"{released / max(opens['n'] / days, 1e-9):,.0f} days")
    ex1 = (sum(per_leg) - max(per_leg)) / max(len(per_leg) - 1, 1) if per_leg else 0.0
    return {"per_leg_mean": (sum(per_leg) / len(per_leg)) if per_leg else 0.0,
            "per_leg_med": median(per_leg) if per_leg else 0.0,
            "per_leg_ex1": ex1, "n": len(per_leg),
            "opens": opens["n"], "days": days, "released": released}


def cap_binding_counterfactual(c, t0, pre, now, cap_legs, cohort, slot):
    """Without the sweep, when would the leg cap bind, and what is that worth?

    The counterfactual book is measured, not assumed: a disposed leg that has since SETTLED
    would have left the book anyway (resolution is an exit path v66 does not own), so only
    the unsettled remainder would still be occupying a slot today.
    """
    print("\n" + "=" * 100)
    print("AO.4  THE COUNTERFACTUAL: what the 701 slots actually bought")
    print("=" * 100)
    still = [l for l in cohort if l.get("settle") is None]
    gone = len(cohort) - len(still)
    cf_open = now["n"] + len(still)
    print(f"   disposed {len(cohort)} legs: {gone} have SETTLED since (a slot released by "
          f"resolution, which v66 does not own), {len(still)} are still unresolved")
    print(f"   without the sweep the book would be {now['n']} + {len(still)} = {cf_open} legs "
          f"today, against a {cap_legs} cap")
    print(f"   sweep-day headroom was {cap_legs - pre['n']} slots ({pre['n']}/{cap_legs})")
    if cf_open >= cap_legs:
        print(f"   -> the cap WOULD be binding today without the sweep by "
              f"{cf_open - cap_legs} legs")
    else:
        print(f"   -> the cap would still have {cap_legs - cf_open} slots of headroom today: "
              f"the sweep bought runway it did not need yet")
    # when does the refilled book reach the cap, at the observed net rate?
    net_rate = (now["n"] - (pre["n"] - len(cohort))) / slot["days"]
    print(f"   net book growth since the sweep (ex-disposal): {net_rate:+.2f} legs/day "
          f"({pre['n'] - len(cohort)} -> {now['n']} over {slot['days']:.1f} days)")
    if net_rate > 0:
        print(f"   -> at that rate the cap binds in "
              f"{(cap_legs - now['n']) / net_rate:,.0f} days")
    else:
        print(f"   -> the book is SHRINKING ex-disposal; no slot pressure exists at all")

    legs_day = slot["opens"] / max(slot["days"], 1e-9)
    print(f"\n   a slot is worth the per-leg realised rate on natural settlements:")
    print(f"     mean ${slot['per_leg_mean']:+.3f} / median ${slot['per_leg_med']:+.3f} / "
          f"EX-TOP-1 mean ${slot['per_leg_ex1']:+.3f} (n={slot['n']}, resolved-only)")
    print(f"   a permanently-binding cap blocks ~{legs_day:.1f} copies/day, so its "
          f"steady-state cost is ${legs_day * slot['per_leg_ex1']:.2f}/day ex-top-1")
    print(f"   the full 701-slot release, if every slot refilled and earned the ex-top-1 rate: "
          f"${701 * slot['per_leg_ex1']:+.2f}")
    print(f"   the {slot['opens']} slots actually refilled so far: "
          f"${slot['opens'] * slot['per_leg_ex1']:+.2f}")

    # THE TRAILING-TREND TEST. Headroom is a stock; what decides whether a cap will ever bind
    # is the FLOW. If the book is already shrinking, a slot cap is a ceiling on a falling line
    # and the entire "recycle the book" premise is void -- which is the whole justification v66
    # carries in its own code comment.
    lo = t0 - 30 * DAY
    o = c.execute("""SELECT COUNT(*) n FROM PaperTrade WHERE botId='STANDARD' AND isDemo=0
                     AND openedAt >= ? AND openedAt < ?""", (lo, t0)).fetchone()["n"]
    r = c.execute("""SELECT COUNT(*) n FROM PaperTrade WHERE botId='STANDARD' AND isDemo=0
                     AND resolvedAt >= ? AND resolvedAt < ?""", (lo, t0)).fetchone()["n"]
    print(f"\n   TRAILING FLOW, the 30 days BEFORE the sweep: {o} opens "
          f"({o / 30:.2f}/day) vs {r} resolutions ({r / 30:.2f}/day) "
          f"= net {(o - r) / 30:+.2f} legs/day")
    if o - r < 0:
        print(f"   the book was SHRINKING without help. At that rate headroom went "
              f"{cap_legs - pre['n']} -> {cap_legs - pre['n'] + (r - o):.0f} over a month: "
              f"the cap was never going to bind, so the sweep's stated purpose "
              f"(\"recycle capital so it does not park\") had no resource to free.")
    else:
        print(f"   the book was growing {((o - r) / 30):.2f} legs/day ex-stop, so slot "
              f"pressure was real and the sweep had a defensible motive")


# --------------------------------------------------------------------------- AO.5
def disposal_alpha(c, cohort):
    """Did the marks it sold at beat settlement? The only real PnL question."""
    print("\n" + "=" * 100)
    print("AO.5  EXIT ALPHA ON THE DISPOSED COHORT -- marks vs settlement truth")
    print("=" * 100)
    m2c, stats = {}, {"name_match": 0, "index_fallback": 0, "no_match": 0, "no_record": 0}
    cache = {"markets": {}}
    if os.path.exists(pv.TRUTH_CACHE):
        cache = json.load(open(pv.TRUTH_CACHE))
    if "markets" not in cache:
        cache = {"markets": {}}
    for m in {l["marketId"] for l in cohort}:
        r = c.execute("""SELECT conditionId FROM MarketSnapshot WHERE marketId=?
                         AND conditionId IS NOT NULL AND conditionId<>'' LIMIT 1""", (m,)).fetchone()
        if r and r[0]:
            m2c[m] = r[0]
    print(f"   {len(cohort)} legs in {len(m2c)} markets, all with a conditionId: "
          f"{len(m2c) == len({l['marketId'] for l in cohort})}")
    # A record marked `unsettled` is a snapshot of an earlier moment, not a verdict: these
    # are long-dated books that settle late. Re-fetch every unsettled record or the whole
    # section reads 0% coverage forever (which is exactly what the first run did).
    want = [cid for cid in set(m2c.values())
            if cid not in cache["markets"] or cache["markets"][cid].get("unsettled")]
    if want and not NO_FETCH:
        from concurrent.futures import ThreadPoolExecutor
        print(f"   fetching settlement truth for {len(want)} markets (keyless CLOB)…")
        # A raw response cached while the market was OPEN is not a verdict; _fetch_one only
        # re-hits the wire when the file is missing, so drop the stale raw before refetching.
        for cid in want:
            p = os.path.join(pv.TRUTH_RAW_DIR, cid + ".json")
            if os.path.exists(p):
                os.remove(p)
        with ThreadPoolExecutor(max_workers=8) as ex:
            for cid, rec in ex.map(pv._fetch_one, want):
                if rec:
                    cache["markets"][cid] = rec
        cache["generated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        cache["source"] = "https://clob.polymarket.com/markets/<conditionId> tokens[].winner"
        with open(pv.TRUTH_CACHE, "w") as f:
            json.dump(cache, f, indent=0, sort_keys=True)
    elif want:
        print(f"   --no-fetch: {len(want)} markets uncached, coverage limited")

    for l in cohort:
        l["market"] = l["marketId"]
        s = pv.truth_of(cache, m2c.get(l["marketId"]), l["outcome"], stats)
        l["settle"] = s
        if s is None:
            continue
        l["hold"] = l["ntl"] * (s / l["px"] - 1.0)
        l["dlt"] = l["pnl"] - l["hold"]          # >0 -> stopping beat holding
    cov = [l for l in cohort if l.get("settle") is not None]
    print(f"   coverage: {len(cov)}/{len(cohort)} legs settled "
          f"({100 * len(cov) / len(cohort):.1f}% of legs); "
          f"name-match {stats['name_match']}, index fallback {stats['index_fallback']}, "
          f"no-match {stats['no_match']}, no record {stats['no_record']}")
    if not cov:
        print("   no settlement coverage -> NO VERDICT POSSIBLE on alpha today.")
        return None
    nt = sum(l["ntl"] for l in cov)
    act, hold = sum(l["pnl"] for l in cov), sum(l["hold"] for l in cov)
    print(f"\n   settled subset: {len(cov)} legs ${nt:,.2f} cost")
    print(f"   stopped as executed : ${act:+8.2f} ({100 * act / nt:+6.2f}%)")
    print(f"   held to settlement  : ${hold:+8.2f} ({100 * hold / nt:+6.2f}%)")
    print(f"   EXIT ALPHA (stop - hold) = ${act - hold:+.2f} ({100 * (act - hold) / nt:+.2f}% of notional)")
    lo, hi = pv._boot_sum(cov, "dlt")
    print(f"   market-clustered 95% CI [${lo:+,.2f}, ${hi:+,.2f}]  "
          f"-> {'EXCLUDES ZERO' if lo * hi > 0 else 'includes zero'}")
    print(f"\n   {'band':10} {'legs':>5} {'cost':>8} {'exitROI':>8} {'holdROI':>8} "
          f"{'alpha$':>9} {'alpha%':>8} {'settleWin%':>10} {'medMove':>8}")
    for b in ("0.60-0.80", "0.80-1.00"):
        g = [l for l in cov if band2(l["px"]) == b]
        if len(g) < 5:
            print(f"   {b:10} {len(g):>5}  (n<5, no line)")
            continue
        bn = sum(l["ntl"] for l in g)
        a, h = sum(l["pnl"] for l in g), sum(l["hold"] for l in g)
        lo_b, hi_b = pv._boot_sum(g, "dlt")
        print(f"   {b:10} {len(g):>5} {bn:>8,.0f} {100 * a / bn:>+7.2f}% {100 * h / bn:>+7.2f}% "
              f"{a - h:>+9.2f} {100 * (a - h) / bn:>+7.2f}% "
              f"{100 * sum(l['settle'] for l in g) / len(g):>9.0f}% "
              f"{median([l['cur'] - l['px'] for l in g]):>+8.3f}   CI [${lo_b:+,.0f}, ${hi_b:+,.0f}]")
    print(f"   settle win rate on the settled subset: "
          f"{100 * sum(l['settle'] for l in cov) / len(cov):.1f}% vs mean entry price "
          f"{100 * sum(l['px'] for l in cov) / len(cov):.1f}c "
          f"-> calibration edge {100 * (sum(l['settle'] for l in cov) / len(cov) - sum(l['px'] for l in cov) / len(cov)):+.1f}pp")
    # the alpha's dependence on a few markets
    bym = defaultdict(float)
    for l in cov:
        bym[l["marketId"]] += l["dlt"]
    srt = sorted(bym.items(), key=lambda kv: kv[1])
    print(f"\n   {len(bym)} settled markets carry the alpha; the 5 most negative are "
          f"{sum(v for _, v in srt[:5]):+.2f} and the 5 most positive "
          f"{sum(v for _, v in srt[-5:]):+.2f}")
    print(f"   ex-those-10 markets: alpha ${sum(v for _, v in srt[5:-5]):+.2f} on "
          f"{len(srt) - 10} markets")
    return {"n": len(cov), "ntl": nt, "act": act, "hold": hold, "lo": lo, "hi": hi,
            "cov_pct": 100 * len(cov) / len(cohort)}


def clearance_curve(c, cohort):
    """Would the disposed legs have freed their slots on their own, and when?

    A slot is only scarce if the cap binds. The sweep's real product is therefore
    SLOT-DAYS BROUGHT FORWARD -- (natural resolution date - sweep date) summed over legs.
    If that number is small, or if headroom exists, the product was worthless.
    """
    print("\n" + "=" * 100)
    print("AO.7  THE CLEARANCE CURVE -- how long the swept slots would have occupied themselves")
    print("=" * 100)
    cache = json.load(open(pv.TRUTH_CACHE))["markets"]
    m2c = {}
    for m in {l["marketId"] for l in cohort}:
        r = c.execute("""SELECT conditionId FROM MarketSnapshot WHERE marketId=?
                         AND conditionId IS NOT NULL AND conditionId<>'' LIMIT 1""", (m,)).fetchone()
        if r and r[0]:
            m2c[m] = r[0]
    sweep_ms = min(l["closedAt"] for l in cohort)
    rows, noend = [], 0
    for l in cohort:
        rec = cache.get(m2c.get(l["marketId"]))
        if not rec or not rec.get("end"):
            noend += 1
            continue
        try:
            end_ms = time.mktime(time.strptime(rec["end"][:19], "%Y-%m-%dT%H:%M:%S")) * 1000
        except Exception:
            noend += 1
            continue
        rows.append({"m": l["marketId"], "ntl": l["ntl"],
                     "days": (end_ms - sweep_ms) / DAY, "settled": l.get("settle") is not None})
    if not rows:
        print("   no end dates available")
        return
    print(f"   {len(rows)} legs have a scheduled end date, {noend} do not")
    tot_nt = sum(l["ntl"] for l in cohort)
    for d in (0, 7, 14, 30, 60, 90, 180, 365):
        n = [r for r in rows if r["days"] <= d]
        print(f"   would have freed themselves within {d:>3}d: {len(n):>4} legs "
              f"({100 * len(n) / len(cohort):>5.1f}% of the cohort)  "
              f"${sum(r['ntl'] for r in n):>8,.0f} ({100 * sum(r['ntl'] for r in n) / tot_nt:>5.1f}% of notional)")
    ds = sorted(r["days"] for r in rows)
    print(f"   median scheduled end is {median(ds):+.0f} days from the sweep; "
          f"p25 {ds[len(ds) // 4]:+.0f}d, p75 {ds[3 * len(ds) // 4]:+.0f}d")
    slot_days = sum(max(r["days"], 0) for r in rows)
    print(f"   slot-days brought forward: {slot_days:,.0f} leg-days = "
          f"{slot_days / 365:,.1f} leg-years")
    print(f"   at the ex-top-1 per-leg rate (${0.168:.3f}/leg lifetime) those slot-days are worth "
          f"at most ${0.168 * len(rows):,.0f} in total -- and $0 while the cap has headroom")
    print(f"   of which already settled since the sweep: "
          f"{sum(1 for r in rows if r['settled'])} legs "
          f"({100 * sum(1 for r in rows if r['settled']) / len(rows):.0f}%)")


def close_path_decomposition(c, cohort):
    """Which STANDARD close path pays the alpha? v66's stop, or the 404 expiry?

    STANDARD has exactly two ways to leave a position without a resolution: the v66 stale
    stop, and the dead-slug expiry that closes at the LAST KNOWN MARK when a market 404s and
    the parent-event lookup returns nothing. The sweep is one identifiable cohort; every
    other STANDARD `closed` leg is, by elimination, a 404 expiry. That split is the whole
    question: an exit priced off a stale mark on a market that later resolves is not an exit
    decision, it is a data outage booked as a loss.
    """
    print("\n" + "=" * 100)
    print("AO.9  CLOSE-PATH DECOMPOSITION -- the stale stop vs the dead-slug expiry")
    print("=" * 100)
    cache, m2c = pv.build_truth(c)
    sweep_ids = {l["id"] for l in cohort}
    rows = c.execute(
        """SELECT id, marketId, outcome, entryPrice px, currentPrice cur,
                  simulatedPositionSize ntl, realizedPnl pnl, openedAt, closedAt
           FROM PaperTrade WHERE botId='STANDARD' AND status='closed' AND isDemo=0""").fetchall()
    stats = {"name_match": 0, "index_fallback": 0, "no_match": 0, "no_record": 0}
    paths = {"v66 stale stop (2026-10-24 sweep)": [], "dead-slug 404 expiry": []}
    for r in rows:
        d = dict(r)
        d["market"] = d["marketId"]
        key = ("v66 stale stop (2026-10-24 sweep)" if d["id"] in sweep_ids
               else "dead-slug 404 expiry")
        s = pv.truth_of(cache, m2c.get(d["marketId"]), d["outcome"], stats)
        d["settle"] = s
        if s is not None:
            d["hold"] = d["ntl"] * (s / d["px"] - 1.0)
            d["dlt"] = d["pnl"] - d["hold"]
        paths[key].append(d)
    print(f"   STANDARD closed: {len(rows)} legs; truth coverage "
          f"{sum(1 for v in paths.values() for l in v if l['settle'] is not None)}"
          f"/{len(rows)} (name-match {stats['name_match']}, no-record {stats['no_record']})")
    for key, legs in paths.items():
        cov = [l for l in legs if l["settle"] is not None]
        if not cov:
            continue
        nt = sum(l["ntl"] for l in cov)
        a, h = sum(l["pnl"] for l in cov), sum(l["hold"] for l in cov)
        lo, hi = pv._boot_sum(cov, "dlt")
        print(f"\n   {key}: {len(cov)} priced legs ${nt:,.0f} "
              f"({100 * len(cov) / len(legs):.0f}% of {len(legs)})")
        print(f"     exit ${a:+,.2f} ({100 * a / nt:+.2f}%)  hold ${h:+,.2f} "
              f"({100 * h / nt:+.2f}%)  ALPHA ${a - h:+,.2f} ({100 * (a - h) / nt:+.2f}%)  "
              f"CI [${lo:+,.0f}, ${hi:+,.0f}]")
        print(f"     {'band':10} {'legs':>5} {'notional':>9} {'alpha$':>9} {'alpha%':>8} "
              f"{'win%exit':>8} {'win%hold':>9} {'medExit':>8} {'medSettle':>10}")
        for b in NAMES:
            g = [l for l in cov if pv.band_of(l["px"]) == b]
            if len(g) < 20:
                continue
            bn = sum(l["ntl"] for l in g)
            ga, gh = sum(l["pnl"] for l in g), sum(l["hold"] for l in g)
            print(f"     {b:10} {len(g):>5} {bn:>9,.0f} {ga - gh:>+9,.2f} "
                  f"{100 * (ga - gh) / bn:>+7.2f}% "
                  f"{100 * sum(1 for l in g if l['cur'] > l['px']) / len(g):>7.0f}% "
                  f"{100 * sum(l['settle'] for l in g) / len(g):>8.0f}% "
                  f"{median([l['cur'] for l in g]):>8.3f} {np.mean([l['settle'] for l in g]):>10.3f}")
    # how many 404 expiries were priced at a mark that was plainly stale?
    exp = [l for l in paths["dead-slug 404 expiry"] if l["settle"] is not None]
    if exp:
        err = [l["settle"] - l["cur"] for l in exp]
        print(f"\n   404 expiries: mark error (settle - exit price) median {median(err):+.3f}, "
              f"p10 {np.percentile(err, 10):+.3f}, p90 {np.percentile(err, 90):+.3f}")
        big = [l for l in exp if abs(l["settle"] - l["cur"]) > 0.30]
        print(f"   {len(big)} of {len(exp)} legs ({100 * len(big) / len(exp):.0f}%) exited at a "
              f"mark more than 30c away from the value they eventually settled at; those legs "
              f"carry ${sum(l['dlt'] for l in big):+,.2f} of the path's alpha "
              f"(${sum(l['dlt'] for l in exp):+,.2f} total)")
        print(f"   their notional is ${sum(l['ntl'] for l in big):,.0f} of "
              f"${sum(l['ntl'] for l in exp):,.0f}")


def band_scope_support(c):
    """How much of the disposed cohort's band has independent settlement-edge support?"""
    print("\n" + "=" * 100)
    print("AO.6  WHERE THE DISPOSAL LANDED vs WHERE THE BOOK'S EDGE IS")
    print("=" * 100)
    rows = c.execute(
        """SELECT entryPrice px, COUNT(*) n FROM PaperTrade
           WHERE botId='STANDARD' AND isDemo=0 AND status='open' GROUP BY 1""").fetchall()
    op = defaultdict(lambda: [0, 0.0])
    for r in rows:
        b = band2(r["px"])
        op[b][0] += r["n"]
    tot_nt = c.execute("""SELECT COALESCE(SUM(simulatedPositionSize),0) nt FROM PaperTrade
                          WHERE botId='STANDARD' AND isDemo=0 AND status='open'""").fetchone()["nt"]
    aged = {}
    for b in ("<0.60", "0.60-0.80", "0.80-1.00"):
        r = c.execute(
            """SELECT COUNT(*) n, COALESCE(SUM(simulatedPositionSize),0) nt,
                      COALESCE(SUM((? - openedAt)/86400000.0*simulatedPositionSize),0) cd
               FROM PaperTrade WHERE botId='STANDARD' AND isDemo=0 AND status='open'
                 AND entryPrice >= ? AND entryPrice < ?""",
            (time.time() * 1000,
             0.0 if b == "<0.60" else (0.60 if b == "0.60-0.80" else 0.80),
             0.60 if b == "<0.60" else (0.80 if b == "0.60-0.80" else 1.01))).fetchone()
        aged[b] = r
    print(f"   {'band':10} {'open legs':>9} {'notional':>9} {'% of open$':>10} "
          f"{'capital-days':>12} {'in stale scope?':>16}")
    for b in ("<0.60", "0.60-0.80", "0.80-1.00"):
        r = aged[b]
        print(f"   {b:10} {r['n']:>9} {r['nt']:>9,.0f} {100 * r['nt'] / tot_nt:>9.1f}% "
              f"{r['cd']:>12,.0f} {'yes (>=0.60)' if b != '<0.60' else 'NO -- out of scope':>16}")
    print("   every open leg in a >=0.60 band is already inside v66's scope; the only legs it")
    print("   cannot touch are the sub-0.60 ones, which are the bands with positive edge.")
    print(f"\n   the surviving book, by band (unrealised = last mark, NOT truth):")
    now_ms = time.time() * 1000
    r = c.execute(
        """SELECT CASE WHEN entryPrice<0.2 THEN '<0.20' WHEN entryPrice<0.4 THEN '0.20-0.40'
                     WHEN entryPrice<0.6 THEN '0.40-0.60' ELSE '>=0.60' END b,
                  COUNT(*) n, SUM(simulatedPositionSize) nt, SUM(unrealizedPnl) up,
                  AVG((?-openedAt)/86400000.0) age
           FROM PaperTrade WHERE botId='STANDARD' AND isDemo=0 AND status='open'
           GROUP BY 1 ORDER BY 1""", (now_ms,)).fetchall()
    print(f"   {'band':10} {'legs':>5} {'notional':>9} {'unrealised':>11} {'%':>7} {'avg age':>8}")
    for x in r:
        print(f"   {x['b']:10} {x['n']:>5} {x['nt']:>9,.0f} {x['up']:>+11,.2f} "
              f"{100 * x['up'] / x['nt']:>+6.1f}% {x['age']:>7.0f}d")


def market_postmortem(c, like):
    """One market's whole life by outcome x status — the attribution check for a headline loss.

    Exists because the 2026-10-27 review priced the Bolsonaro market as one −$1,053 story when
    it is two opposite ones: NO legs the stop sold at a 0.26 mark that settled 1.000, and YES
    legs that resolved to zero. A market-level number that mixes both cannot attribute a loss
    to a mechanism.
    """
    print("\n" + "=" * 100)
    print(f"AO.11  MARKET POST-MORTEM -- {like}")
    print("=" * 100)
    rows = c.execute(
        """SELECT outcome, status, COUNT(*) n, SUM(simulatedPositionSize) nt,
                  SUM(realizedPnl) pnl, AVG(entryPrice) px, AVG(currentPrice) cur
           FROM PaperTrade WHERE botId='STANDARD' AND isDemo=0 AND marketId LIKE ?
           GROUP BY 1,2 ORDER BY 1,2""", (like + "%",)).fetchall()
    if not rows:
        print("   no legs")
        return
    print(f"   {'outcome':8} {'status':9} {'legs':>5} {'notional':>9} {'realised':>9} "
          f"{'avg entry':>9} {'avg mark':>8}")
    tot_nt = tot_pnl = 0.0
    for r in rows:
        tot_nt += r["nt"] or 0
        tot_pnl += r["pnl"] or 0
        print(f"   {r['outcome']:8} {r['status']:9} {r['n']:>5} {r['nt']:>9,.2f} "
              f"{r['pnl']:>+9.2f} {r['px']:>9.3f} {r['cur']:>8.3f}")
    print(f"   {'TOTAL':8} {'':9} {sum(r['n'] for r in rows):>5} {tot_nt:>9,.2f} "
          f"{tot_pnl:>+9.2f}")


def gate_backtest(c, cap_legs):
    """Would a cap-pressure gate ever have allowed the rail to fire?

    The gate: fire only when (a) open legs are within 15% of standardMaxOpenPositions AND
    (b) the book grew over the trailing 7 days (opens > resolutions). Both are computable
    from the DB for every past day, so the gate can be backtested rather than argued about.
    Printed per day: open legs, headroom, trailing-7d net growth, legs in v66's scope.
    """
    print("\n" + "=" * 100)
    print("AO.10  THE GATE'S OWN BACKTEST -- 90 days of 'would the calendar have been allowed to fire?'")
    print("=" * 100)
    now_ms = time.time() * 1000
    ops = {r["d"]: r["n"] for r in c.execute(
        """SELECT date(openedAt/1000,'unixepoch') d, COUNT(*) n FROM PaperTrade
           WHERE botId='STANDARD' AND isDemo=0 AND openedAt >= ? GROUP BY 1""",
        (now_ms - 91 * DAY,))}
    res = {r["d"]: r["n"] for r in c.execute(
        """SELECT date(resolvedAt/1000,'unixepoch') d, COUNT(*) n FROM PaperTrade
           WHERE botId='STANDARD' AND isDemo=0 AND resolvedAt >= ? GROUP BY 1""",
        (now_ms - 91 * DAY,))}
    cls = {r["d"]: r["n"] for r in c.execute(
        """SELECT date(closedAt/1000,'unixepoch') d, COUNT(*) n FROM PaperTrade
           WHERE botId='STANDARD' AND isDemo=0 AND status='closed' AND closedAt >= ? GROUP BY 1""",
        (now_ms - 91 * DAY,))}
    legs = c.execute(
        """SELECT openedAt, closedAt, resolvedAt, entryPrice px FROM PaperTrade
           WHERE botId='STANDARD' AND isDemo=0""").fetchall()
    print(f"   state at 00:00 UTC of each day; cap {cap_legs} legs applied retroactively")
    print(f"   {'date':12} {'open':>5} {'headroom':>9} {'7d net':>7} {'in scope':>9}  gate")
    allowed = fired_days = 0
    allowed_30 = fired_30 = 0
    days = sorted(set(ops) | set(res) | set(cls))
    for d in days:
        t_ms = time.mktime(time.strptime(d + " 00:00:00", "%Y-%m-%d %H:%M:%S")) * 1000
        if t_ms > now_ms:
            continue
        open_n = sum(1 for l in legs
                     if l["openedAt"] < t_ms
                     and (not l["closedAt"] or l["closedAt"] > t_ms)
                     and (not l["resolvedAt"] or l["resolvedAt"] > t_ms))
        t7 = t_ms - 7 * DAY
        d7 = datetime.fromtimestamp(t7 / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
        net7 = sum(v for k, v in ops.items() if d >= k > d7) - \
            sum(v for k, v in res.items() if d >= k > d7)
        scope = sum(1 for l in legs
                    if l["openedAt"] < t_ms and l["px"] >= 0.60
                    and (l["closedAt"] or now_ms) > t_ms
                    and (t_ms - l["openedAt"]) >= 168 * 3_600_000)
        head = cap_legs - open_n
        ok = head < 0.15 * cap_legs and net7 > 0
        if scope:
            fired_days += 1
            if ok:
                allowed += 1
            if t_ms > now_ms - 30 * DAY:
                fired_30 += 1
                if ok:
                    allowed_30 += 1
        print(f"   {d:12} {open_n:>5} {head:>9} {net7:>+7} {scope:>9}  "
              f"{'FIRE' if ok else ('scope-only' if scope else '')}")
    print(f"\n   days in the window with at least one leg in v66's scope: {fired_days}")
    print(f"   of those, days the pressure gate would have ALLOWED a fire: {allowed}")
    if fired_days:
        print(f"   the gate suppresses {100 * (1 - allowed / fired_days):.0f}% of scope-days "
              f"(last 30 days: {allowed_30}/{fired_30})")
    print(f"   NOTE the cap is applied retroactively: in Jul-Aug the book ran 1,500-1,970 legs, "
          f"so a 1,300 ceiling would have bound hard and the gate would have fired daily --")
    print(f"   which is exactly the regime the rail is supposed to serve. It suppresses only "
          f"the flat/declining regime, which is the one the 2026-10-24 sweep happened in.")


def main():
    c = con()
    ver, rules = live_rules(c)
    rules["_v"] = ver
    cohort, other, hours, floor = sweep_cohort(c, rules)
    if not cohort:
        print("no v66 cohort found on " + SWEEP_DATE)
        return
    cohort = reproduce(c, rules, cohort, other, hours, floor)
    t0, pre, post, now, cap_legs = resource_inventory(c, rules, cohort)
    slot = slot_economics(c, t0, pre, post, now, cap_legs, cohort)
    alpha = disposal_alpha(c, cohort)
    cap_binding_counterfactual(c, t0, pre, now, cap_legs, cohort, slot)
    clearance_curve(c, cohort)
    close_path_decomposition(c, cohort)
    band_scope_support(c)
    market_postmortem(c, "will-flvio-bolsonaro-win-the-2026-brazilian-presidential-election")
    gate_backtest(c, cap_legs)


if __name__ == "__main__":
    main()
