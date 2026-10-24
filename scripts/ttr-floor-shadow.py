#!/usr/bin/env python3
"""Forward shadow for the STANDARD time-to-resolution floor: 2h -> 24h.

APPROVED 2026-10-23 (Lane A). This script does NOT change any rule. It measures the
population the new floor WOULD block, so the 14-day flip decision is made on forward
data instead of the in-sample read that proposed it.

THE DECISION, pre-registered before any forward data existed:
  At n >= 150 settled legs in the at-risk band, FLIP LIVE unless the band's net ROI
  is >= +3.0%. A band that returns +3% or better is profitable work we would be
  throwing away, so "shadow >= +3%" is the REFUTATION, not the pass.
  Otherwise HOLD until n or the window is reached.

  REFUTATION (any one):
    (a) band net ROI >= +3.0% at n >= 150 settled legs          -> do not flip
    (b) flat 0.6-1.0 cells widen to >= +10% on 150 forward legs  -> do not flip
    (c) 3-7d ex-top-10 falls below 0% on a 60d read              -> do not flip
  (b) and (c) are reported here as not-yet-evaluable; they are manual reads at day 14
  so this script cannot quietly declare a pass on a clause it never tested.

WHY THE BAND IS [2, 24): the live RuleSet floor is 2h, so a leg with 2-24h left is
copied TODAY and would be skipped under the proposed floor. TTR below 2h should not
exist (the current floor blocks it) -- if any appear, that is itself a finding and is
reported separately rather than folded into the band.

TTR SOURCE: identical to scripts/profit-velocity.py -- the last MarketSnapshot at or
before entry+15min, timeToResolution in HOURS. Reused deliberately: a shadow that
derives its own axis can disagree with the study that motivated it and the argument
becomes about the instrument instead of the rule.

SETTLEMENT: PaperTrade.realizedPnl ORs early exits (closed) and natural resolutions
(resolved). Both are reported, and the headline is the OR because that is how the lane
books PnL -- but resolved-only is shown beside it, because an exit-rule change during
the window can move the OR without the floor having anything to do with it. If the two
disagree in SIGN, the verdict refuses to flip.

Read-only. Writes data/ttr-floor-shadow.json only.
"""
import json
import os
import sqlite3
import sys
import time
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(ROOT, "prisma", "dev.db")
OUT = os.path.join(ROOT, "data", "ttr-floor-shadow.json")

APPROVAL_DATE = "2026-10-23"
SHADOW_DAYS = 14
BOT = "STANDARD"
BAND_LO_H = 2.0        # live floor today
BAND_HI_H = 24.0       # proposed floor
MIN_LEGS = 150         # pre-registered n
REFUTE_ROI = 0.03      # band ROI at or above this = refuted (do not flip)


def ms(date_str):
    dt = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


def main():
    global APPROVAL_DATE, BAND_LO_H
    # --since / --band-lo exist so the instrument can be CALIBRATED against the
    # historical population before anyone trusts its forward read: replaying the
    # band over all history must reproduce the study that proposed the change
    # (the <24h block, -13.0% on 3,395 legs). A shadow that cannot reproduce the
    # measurement it is shadowing is an instrument defect, not a result.
    quiet = "--quiet" in sys.argv
    for i, a in enumerate(sys.argv):
        if a != "--quiet" and a == "--since" and i + 1 < len(sys.argv):
            APPROVAL_DATE = sys.argv[i + 1]
        elif a == "--band-lo" and i + 1 < len(sys.argv):
            BAND_LO_H = float(sys.argv[i + 1])

    if not os.path.exists(DB):
        sys.exit("no database at %s" % DB)
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    since = ms(APPROVAL_DATE)

    # --- the settled cohort ---------------------------------------------------
    rows = c.execute(
        """SELECT status, marketId, entryPrice AS px, simulatedPositionSize AS ntl,
                  realizedPnl AS pnl, openedAt, closedAt, resolvedAt
           FROM PaperTrade
           WHERE isDemo=0 AND botId=? AND status IN ('closed','resolved')
             AND realizedPnl IS NOT NULL AND openedAt >= ?""",
        (BOT, since),
    ).fetchall()

    # EVERY leg opened since approval, whatever its status. This is the throughput
    # denominator, and it must be openings rather than settlements: a cohort one day
    # old has barely begun to settle, so dividing SETTLED legs by elapsed days reads
    # as ~0.9/day and projects a fantasy ETA. Openings are the honest rate; the
    # settlement lag is a separate term.
    opened_rows = c.execute(
        """SELECT marketId, entryPrice AS px, simulatedPositionSize AS ntl, openedAt
           FROM PaperTrade
           WHERE isDemo=0 AND botId=? AND openedAt >= ?""",
        (BOT, since),
    ).fetchall()

    cache = {}

    def ttr_at_entry(market_id, opened_at):
        """Last MarketSnapshot at or before entry+15min -- same as profit-velocity.py."""
        key = (market_id, opened_at // 3_600_000)
        if key in cache:
            return cache[key]
        s = c.execute(
            """SELECT timeToResolution FROM MarketSnapshot
               WHERE marketId=? AND collectedAt<=? AND timeToResolution IS NOT NULL
               ORDER BY collectedAt DESC LIMIT 1""",
            (market_id, opened_at + 900_000),
        ).fetchone()
        cache[key] = s[0] if s else None
        return cache[key]

    band = []          # 2..24h -- what the new floor would block
    under = []         # <2h -- should not exist under the live floor
    over = []          # >=24h -- kept under both floors
    unknown = 0

    for r in rows:
        if not r["px"] or r["px"] <= 0 or not r["ntl"] or r["ntl"] <= 0:
            continue
        ttl = ttr_at_entry(r["marketId"], r["openedAt"])
        if ttl is None or ttl < 0:
            unknown += 1
            continue
        rec = {
            "market": r["marketId"],
            "ttl": ttl,
            "ntl": r["ntl"],
            "pnl": r["pnl"],
            "resolved": r["status"] == "resolved",
        }
        if ttl < BAND_LO_H:
            under.append(rec)
        elif ttl < BAND_HI_H:
            band.append(rec)
        else:
            over.append(rec)

    def stats(recs):
        n = len(recs)
        if n == 0:
            return {"legs": 0, "markets": 0, "notional": 0.0, "pnl": 0.0, "roi": None,
                    "resolved_legs": 0, "resolved_roi": None}
        ntl = sum(x["ntl"] for x in recs)
        pnl = sum(x["pnl"] for x in recs)
        res = [x for x in recs if x["resolved"]]
        r_ntl = sum(x["ntl"] for x in res)
        r_pnl = sum(x["pnl"] for x in res)
        return {
            "legs": n,
            "markets": len({x["market"] for x in recs}),
            "notional": round(ntl, 2),
            "pnl": round(pnl, 2),
            "roi": (pnl / ntl) if ntl else None,
            "resolved_legs": len(res),
            "resolved_roi": (r_pnl / r_ntl) if r_ntl else None,
        }

    b, o, u = stats(band), stats(over), stats(under)

    # legs opened in the band -- settled or not. The settled subset above is the
    # sample; this is the rate the sample accrues at. MUST be computed before the
    # decision block, which divides by it (and must be OPENINGS, not settlements:
    # a one-day-old cohort has barely settled, so a settled-legs-per-day rate reads
    # as ~0.9/day and projects a fantasy ETA).
    opened_band = 0
    for r in opened_rows:
        if not r["px"] or r["px"] <= 0:
            continue
        ttl = ttr_at_entry(r["marketId"], r["openedAt"])
        if ttl is not None and BAND_LO_H <= ttl < BAND_HI_H:
            opened_band += 1

    # --- the pre-registered decision -----------------------------------------
    days_elapsed = (int(time.time() * 1000) - since) / 86_400_000.0
    verdict, why = "ACCUMULATING", ""
    if b["legs"] >= MIN_LEGS:
        roi = b["roi"]
        r_roi = b["resolved_roi"]
        if roi is None:
            verdict, why = "INSUFFICIENT", "band has legs but no notional"
        elif roi >= REFUTE_ROI:
            verdict = "REFUTED"
            why = ("band net ROI %+.2f%% >= +3.0%% at n=%d -- this is profitable work the "
                   "floor would throw away, so do NOT flip" % (roi * 100, b["legs"]))
        elif r_roi is not None and roi > 0 and r_roi < 0:
            verdict = "INSUFFICIENT"
            why = ("headline %+.2f%% and resolved-only %+.2f%% disagree in SIGN -- an exit-rule "
                   "change can move the OR without the floor being involved; refuse to flip on "
                   "a split result" % (roi * 100, r_roi * 100))
        else:
            verdict = "FLIP"
            why = "band net ROI %+.2f%% < +3.0%% at n=%d" % (roi * 100, b["legs"])
    else:
        need = MIN_LEGS - b["legs"]
        rate = opened_band / days_elapsed if days_elapsed > 0 else 0
        eta = (need / rate) if rate > 0 else None
        why = ("%d of %d settled band legs (from %d opened); %d to go"
               % (b["legs"], MIN_LEGS, opened_band, need))
        if eta is not None:
            why += " (~%.0f days at the current %.1f OPENINGS/day; settlement lag not included)" % (eta, rate)
            if days_elapsed < SHADOW_DAYS and eta > (SHADOW_DAYS - days_elapsed):
                why += (" -- the %d-day window CANNOT reach n=%d at this throughput, so the "
                        "day-%d trigger in the approved rule is unmeetable"
                        % (SHADOW_DAYS, MIN_LEGS, SHADOW_DAYS))
        if days_elapsed >= SHADOW_DAYS:
            why += "; %d-day window has elapsed -- n floor not met, so the answer is a recorded NULL" % SHADOW_DAYS

    out = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "approval_date": APPROVAL_DATE,
        "shadow_days": SHADOW_DAYS,
        "days_elapsed": round(days_elapsed, 2),
        "bot": BOT,
        "rule": {
            "proposed": "minTimeToResolutionHours 2 -> 24 on STANDARD",
            "live_floor_h": BAND_LO_H,
            "proposed_floor_h": BAND_HI_H,
            "at_risk_band_h": [BAND_LO_H, BAND_HI_H],
            "min_settled_legs": MIN_LEGS,
            "refute_if_band_roi_at_or_above": REFUTE_ROI,
            "decision": "flip live unless the at-risk band returns >= +3.0% at n >= 150 settled legs",
        },
        "bands": {
            "at_risk_2_24h": b,
            "kept_24h_plus": o,
            "under_live_floor_lt_2h": u,
        },
        "opened_legs_in_band": opened_band,
        "openings_per_day": round(opened_band / days_elapsed, 2) if days_elapsed > 0 else None,
        "unclassified_ttr": unknown,
        "verdict": verdict,
        "reason": why,
        "not_yet_evaluable": [
            "refutation (b): flat 0.6-1.0 cells widening to >= +10% on 150 forward legs",
            "refutation (c): 3-7d ex-top-10 below 0% on a 60d read",
        ],
        "note": "Read-only shadow. Changing the floor is Lane A and still needs the user.",
    }

    with open(OUT, "w") as f:
        json.dump(out, f, indent=2)

    # --- report ---------------------------------------------------------------
    # --quiet (the cron mode): say NOTHING while the verdict is still accumulating.
    # An empty stdout sends no message, so the watchdog stays silent for the ~35
    # days it takes to reach n=150 and speaks only when the verdict becomes
    # actionable. The JSON is written either way, so the dashboard stays fresh.
    if quiet and verdict == "ACCUMULATING":
        return

    print("TTR floor shadow -- STANDARD, %.2f days since approval (%s)" % (days_elapsed, APPROVAL_DATE))
    print()
    print("  at risk  [2,24)h : %4d legs / %3d mkts  ntl $%9.2f  pnl $%9.2f  ROI %s"
          % (b["legs"], b["markets"], b["notional"], b["pnl"],
             ("%+.2f%%" % (b["roi"] * 100)) if b["roi"] is not None else "n/a"))
    if b["resolved_legs"]:
        print("                    resolved-only: %d legs, ROI %+.2f%%"
              % (b["resolved_legs"], b["resolved_roi"] * 100))
    print("  kept    [24,inf) : %4d legs / %3d mkts  ntl $%9.2f  pnl $%9.2f  ROI %s"
          % (o["legs"], o["markets"], o["notional"], o["pnl"],
             ("%+.2f%%" % (o["roi"] * 100)) if o["roi"] is not None else "n/a"))
    if u["legs"]:
        print("  BELOW LIVE FLOOR : %4d legs  <-- should be impossible under a 2h floor; investigate"
              % u["legs"])
    print("  opened in band   : %4d legs (settled + still open) -> %.2f openings/day"
          % (opened_band, (opened_band / days_elapsed) if days_elapsed > 0 else 0.0))
    if unknown:
        print("  unclassified TTR : %4d legs (no snapshot at entry+15m)" % unknown)
    print()
    print("  VERDICT: %s -- %s" % (verdict, why))
    print()
    print("  not yet evaluable: refutation (b) flat 0.6-1.0 cells >= +10%; (c) 3-7d ex-top-10 < 0%")
    print("  wrote %s" % OUT)


if __name__ == "__main__":
    main()
