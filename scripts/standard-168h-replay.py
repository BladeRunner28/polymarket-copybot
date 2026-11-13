#!/usr/bin/env python3
"""
S. THE STANDARD 168h REPLAY -- scoped before any change.

WHY THIS EXISTS
---------------
The 2026-10-20 profit review found the whole stale-exit / capital-recycling block
guarded `botId === "BANKROLL_200"` and read STANDARD's 1.03M open capital-days as
stranded capital with no time exit. Two rules have since been armed and retired on
exactly that premise:

  v66 (2026-10-23, approved)  standardStaleExitHours = 168, entry >= 0.60 -- fired
      once, on 2026-10-24, closing 701 legs / $7,321.20 for -$350.52.
  v70 (2026-10-29, approved)  standardStaleExitHours = 0 -- retired because STANDARD
      has no notional cap, its 1,300-leg cap was not binding, and a calendar trigger
      cannot be answering cap pressure that does not exist.

This script answers the question the card asks BEFORE anything is re-armed: what does a
168h hard exit actually do to the WHOLE STANDARD book -- capital-days released, PnL
given up -- measured from stored marks, not from a narrative.

ARMS
----
  A (hold)   what the book did: realizedPnl on closed/resolved legs, unrealizedPnl on
             open ones (last mark).
  B (168h)   close at the first recorded mark at or after openedAt + 168h, when the leg
             was still open at that moment; otherwise arm B == arm A (the rule never
             touches a leg that had already exited).

PRICE SOURCE: PnlSnapshot -- one row per leg per hourly mark, stamped by
priceForOutcome() at mark time, so label-correct by construction. MarketSnapshot's
yesPrice/noPrice are POSITIONAL and misprice named outcomes, so they are NOT used for
the primary arm (profit-velocity.py's ground_truth_stop() does use them, which is why
this script exists beside it rather than instead of it). Agreement between the two is
printed in S.8.

CAPITAL-DAYS: notional x (exit - openedAt)/1 day, summed. Exit is closedAt/resolvedAt
(arm A) or min(exit, openedAt+H) (arm B); an open leg exits "now" in arm A.

DECISION RULE (pre-registered on the card, not restated after the fact)
  ADOPT the exit when capital-days fall >= 50% while booked PnL falls < $150 over 90d.

READ-ONLY. No prisma write, no RuleSet row, no rule edit.

RUN
  python3 scripts/standard-168h-replay.py
  python3 scripts/standard-168h-replay.py --lane BANKROLL_200
"""
from __future__ import annotations

import argparse
import bisect
import json
import os
import sqlite3
import time
from collections import defaultdict
from datetime import datetime, timezone
from statistics import median

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
DB = "prisma/dev.db"
H168 = 168 * 3_600_000
DAY = 86_400_000.0
BANDS = (("<0.20", 0.0, 0.20), ("0.20-0.40", 0.20, 0.40), ("0.40-0.60", 0.40, 0.60),
         ("0.60-0.80", 0.60, 0.80), ("0.80-1.00", 0.80, 1.01))
HORIZONS = (24, 72, 168, 336, 720, 1440)


def con():
    c = sqlite3.connect("file:%s?mode=ro" % DB, uri=True)
    c.row_factory = sqlite3.Row
    return c


def d(ms):
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d")


def band_of(px):
    for nm, lo, hi in BANDS:
        if lo <= px < hi:
            return nm
    return "0.80-1.00"


def boot_delta(legs, reps=2000, seed=17):
    """Market-clustered bootstrap of sum(delta): resample MARKETS, not legs."""
    bym = defaultdict(list)
    for l in legs:
        bym[l["marketId"]].append(l["delta"])
    keys = list(bym)
    if len(keys) < 2:
        return (float("nan"), float("nan"))
    rng = np.random.default_rng(seed)
    sums = []
    for _ in range(reps):
        pick = rng.choice(len(keys), len(keys), replace=True)
        sums.append(sum(sum(bym[keys[i]]) for i in pick))
    return (float(np.percentile(sums, 2.5)), float(np.percentile(sums, 97.5)))


def load_legs(c, lane):
    rows = c.execute(
        """SELECT id, botId, marketId, outcome, side, entryPrice AS px,
                  simulatedPositionSize AS ntl, currentPrice AS cur,
                  realizedPnl AS pnl, unrealizedPnl AS upnl, status,
                  openedAt, closedAt, resolvedAt
           FROM PaperTrade
           WHERE botId=? AND isDemo=0 AND entryPrice > 0 AND simulatedPositionSize > 0
             AND openedAt IS NOT NULL""", (lane,)).fetchall()
    return [dict(r) for r in rows]


def marks_for(c, ids):
    """All stored marks for the given legs, as {id: [(collectedAt, price), ...]}."""
    out = defaultdict(list)
    chunk = 800
    ids = list(ids)
    for i in range(0, len(ids), chunk):
        part = ids[i:i + chunk]
        q = ("SELECT paperTradeId, collectedAt, price FROM PnlSnapshot "
             "WHERE paperTradeId IN (%s) ORDER BY paperTradeId, collectedAt" % ",".join("?" * len(part)))
        for r in c.execute(q, part):
            out[r[0]].append((r[1], r[2]))
    return out


def replay(legs, marks, now_ms, horizon_ms=H168, gap_h=12):
    """Attach arm A / arm B to every leg for one horizon. Returns (priced, reasons)."""
    reasons = defaultdict(int)
    priced = []
    for base in legs:
        l = dict(base)
        seq = marks.get(l["id"]) or []
        if not seq:
            reasons["no stored mark"] += 1
            continue
        target = l["openedAt"] + horizon_ms
        times = [t for t, _ in seq]
        j = bisect.bisect_left(times, target)
        exit_actual = l["closedAt"] or l["resolvedAt"] or now_ms
        l["exit_actual"] = exit_actual
        live_at_target = exit_actual > target
        if live_at_target:
            if j >= len(seq):
                reasons["open past horizon but no mark at/after it"] += 1
                continue
            stop_at, stop_px = seq[j]
            if stop_at - target > gap_h * 3_600_000:
                reasons["no mark within %dh of horizon (marker gap)" % gap_h] += 1
                continue
            l["stop_at"], l["stop_px"] = stop_at, stop_px
            l["stop_lag_h"] = (stop_at - target) / 3_600_000.0
            l["fires"] = True
        else:
            l["stop_at"], l["stop_px"] = exit_actual, seq[-1][1]
            l["fires"] = False
        if l["status"] == "open":
            l["pnl_a"] = l["upnl"] if l["upnl"] is not None else l["ntl"] * (seq[-1][1] / l["px"] - 1.0)
        elif l["pnl"] is not None:
            l["pnl_a"] = l["pnl"]
        else:
            reasons["finished without realizedPnl"] += 1
            continue
        l["pnl_b"] = l["ntl"] * (l["stop_px"] / l["px"] - 1.0) if l["fires"] else l["pnl_a"]
        l["delta"] = l["pnl_b"] - l["pnl_a"]
        l["cd_a"] = l["ntl"] * (exit_actual - l["openedAt"]) / DAY
        l["cd_b"] = l["ntl"] * ((min(exit_actual, l["stop_at"]) if l["fires"] else exit_actual)
                                - l["openedAt"]) / DAY
        l["age_d"] = (exit_actual - l["openedAt"]) / DAY
        l["band"] = band_of(l["px"])
        priced.append(l)
    return priced, reasons


def line(label, sub, width=28):
    if not sub:
        print("   %-*s  (none)" % (width, label))
        return
    nt = sum(l["ntl"] for l in sub)
    a = sum(l["pnl_a"] for l in sub)
    b = sum(l["pnl_b"] for l in sub)
    cda = sum(l["cd_a"] for l in sub)
    cdb = sum(l["cd_b"] for l in sub)
    lo, hi = boot_delta(sub)
    fired = sum(1 for l in sub if l["fires"])
    print("   %-*s %5d %6.0f%% %8.1f %9.0f %9.0f %7.1f%% %+9.0f [%+7.0f,%+7.0f] %10.0f %10.0f"
          % (width, label, len(sub), 100.0 * fired / len(sub), nt / 1000.0, a, b,
             100.0 * (b - a) / nt if nt else 0.0, b - a, lo, hi, cda, cdb))


def rule_verdict(label, sub, cut):
    if not sub:
        print("   %-34s (none)" % label)
        return
    cda = sum(l["cd_a"] for l in sub)
    cdb = sum(l["cd_b"] for l in sub)
    delta = sum(l["delta"] for l in sub)
    cut_pct = 100.0 * (cda - cdb) / cda if cda else 0.0
    ok_cd = cut_pct >= 50.0
    ok_pnl = delta > -150.0
    print("   %-34s n=%4d  cap-days %9.0f -> %9.0f (%+5.1f%%)  dPnL %+9.2f  "
          "cd>=50%%:%-3s  dPnL>-$150:%-3s  -> %s"
          % (label, len(sub), cda, cdb, -cut_pct, delta,
             "yes" if ok_cd else "NO", "yes" if ok_pnl else "NO",
             "ADOPT" if (ok_cd and ok_pnl) else "DO NOT ADOPT"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lane", default="STANDARD")
    args = ap.parse_args()
    c = con()
    now_ms = int(time.time() * 1000)
    ver, rules_json = c.execute(
        "SELECT version, rulesJson FROM RuleSet ORDER BY version DESC LIMIT 1").fetchone()
    rules = json.loads(rules_json)

    legs = load_legs(c, args.lane)
    marks = marks_for(c, [l["id"] for l in legs])
    priced, reasons = replay(legs, marks, now_ms)

    print("=" * 118)
    print("S.1  POPULATION -- %s, isDemo=0, %d legs in the DB" % (args.lane, len(legs)))
    print("=" * 118)
    print("   live RuleSet v%d: standardStaleExitHours=%s standardStaleExitBandMin=%s "
          "staleExitHardHours=%s standardMaxOpenPositions=%s"
          % (ver, rules.get("standardStaleExitHours"), rules.get("standardStaleExitBandMin"),
             rules.get("staleExitHardHours"), rules.get("standardMaxOpenPositions")))
    print("   priceable legs: %d (%.1f%%)   excluded: %s"
          % (len(priced), 100.0 * len(priced) / len(legs),
             ", ".join("%s=%d" % kv for kv in sorted(reasons.items())) or "none"))
    by_st = defaultdict(list)
    for l in priced:
        by_st[l["status"]].append(l)
    for st in sorted(by_st):
        print("     %-9s %5d legs  $%9.0f notional" % (st, len(by_st[st]),
                                                       sum(l["ntl"] for l in by_st[st])))

    print()
    print("=" * 118)
    print("S.2  THE CARD'S PREMISE, RE-MEASURED TODAY (and reconstructed as of 2026-10-20)")
    print("=" * 118)

    def open_state(t_ms):
        return c.execute(
            """SELECT botId, COUNT(*) n, SUM(simulatedPositionSize) nt,
                      SUM(simulatedPositionSize * ((?-openedAt)/86400000.0)) cd,
                      COUNT(DISTINCT marketId || '|' || outcome) bets
               FROM PaperTrade
               WHERE isDemo=0 AND openedAt < ?
                 AND (closedAt IS NULL OR closedAt > ?)
                 AND (resolvedAt IS NULL OR resolvedAt > ?)
               GROUP BY botId""", (t_ms, t_ms, t_ms, t_ms)).fetchall()

    fin = c.execute(
        """SELECT SUM(simulatedPositionSize * ((COALESCE(closedAt,resolvedAt)-openedAt)/86400000.0)) cd
           FROM PaperTrade WHERE isDemo=0 AND status<>'open'
             AND COALESCE(closedAt,resolvedAt) IS NOT NULL""").fetchone()[0] or 0.0
    t_oct20 = int(datetime(2026, 10, 20, tzinfo=timezone.utc).timestamp() * 1000)
    for label, t in (("as of 2026-10-20", t_oct20), ("now", now_ms)):
        rows = open_state(t)
        n = sum(r["n"] for r in rows)
        nt = sum(r["nt"] for r in rows)
        cd = sum(r["cd"] for r in rows)
        bets = sum(r["bets"] for r in rows)
        print("   %-16s open legs %5d  distinct bets(market+outcome) %4d  notional $%8.0f  "
              "weighted age %5.1fd  capital-days %10.0f" % (label, n, bets, nt, cd / nt if nt else 0, cd))
        for r in sorted(rows, key=lambda x: -x["cd"]):
            print("        %-13s %5d legs $%8.0f  capital-days %10.0f"
                  % (r["botId"], r["n"], r["nt"], r["cd"]))
    print("   finished-history capital-days (all lanes, all time): %10.0f" % fin)
    fin2 = c.execute(
        """SELECT botId,
                  SUM(simulatedPositionSize * ((COALESCE(closedAt,resolvedAt)-openedAt)/86400000.0)) cd,
                  COUNT(*) n
           FROM PaperTrade WHERE isDemo=0 AND status<>'open'
             AND COALESCE(closedAt,resolvedAt) IS NOT NULL GROUP BY botId""").fetchall()
    for r in fin2:
        print("        %-13s %5d finished legs  capital-days %10.0f" % (r["botId"], r["n"], r["cd"]))
    fin3 = c.execute(
        """SELECT SUM(simulatedPositionSize * ((COALESCE(closedAt,resolvedAt)-openedAt)/86400000.0)) cd,
                  COUNT(*) n
           FROM PaperTrade WHERE isDemo=0 AND status='resolved' AND resolvedAt IS NOT NULL""").fetchone()
    print("   finished, RESOLVED-only basis: %d legs, %10.0f capital-days" % (fin3["n"], fin3["cd"]))
    print("   -> the card's 566,915 'finished history' does not reproduce on any basis printed here;")
    print("      the open book did NOT hold 1.8x a full finished history. Basis unknown, claim withdrawn.")

    print()
    print("=" * 118)
    print("S.2b  THE OPEN BOOK'S HOLD COST TODAY (is it actually bleeding?)")
    print("=" * 118)
    op0 = c.execute(
        """SELECT COUNT(*) n, SUM(simulatedPositionSize) nt, SUM(unrealizedPnl) up,
                  AVG((?-openedAt)/86400000.0) age
           FROM PaperTrade WHERE botId=? AND isDemo=0 AND status='open'""",
        (now_ms, args.lane)).fetchone()
    print("   %d open legs, $%.0f at risk, unrealised %+.2f (%+.2f%%), mean age %.0fd"
          % (op0["n"], op0["nt"], op0["up"], 100.0 * op0["up"] / op0["nt"], op0["age"]))
    print("   CARD CLAIMED: 1,269 open legs / 357 bets / $13,623 notional / 76.3d weighted age /")
    print("                 1,033,886 open capital-days vs 566,915 finished")

    print()
    print("=" * 118)
    print("S.3  THE REPLAY -- arm A (hold) vs arm B (168h hard exit), all priceable legs")
    print("=" * 118)
    print("   %-28s %5s %7s %8s %9s %9s %8s %9s %18s %10s %10s"
          % ("cohort", "legs", "fired%", "$k ntl", "$A pnl", "$B pnl", "B vs A",
             "d $", "mkt-clust 95% CI", "cd A", "cd B"))
    line("ALL", priced)
    for st in ("open", "closed", "resolved"):
        line("status " + st, [l for l in priced if l["status"] == st])
    for nm, lo, hi in BANDS:
        line("band " + nm, [l for l in priced if l["band"] == nm])
    line("scope entry>=0.60 (v66)", [l for l in priced if l["px"] >= 0.60])
    line("scope entry<0.60", [l for l in priced if l["px"] < 0.60])
    line("fired (rule moves them)", [l for l in priced if l["fires"]])
    line("untouched (exited <168h)", [l for l in priced if not l["fires"]])

    print()
    print("=" * 118)
    print("S.4  WHERE THE MONEY COMES FROM -- settlement truth on the RESOLVED subset")
    print("=" * 118)
    res = [l for l in priced if l["status"] == "resolved" and l["fires"]]
    if res:
        nt = sum(l["ntl"] for l in res)
        a = sum(l["pnl_a"] for l in res)
        b = sum(l["pnl_b"] for l in res)
        lo, hi = boot_delta(res)
        print("   fired AND already settled: %d legs, %d markets, $%.0f notional" % (
            len(res), len({l["marketId"] for l in res}), nt))
        print("     hold to settlement : $%+9.2f (%+7.2f%%)" % (a, 100 * a / nt))
        print("     168h exit at mark  : $%+9.2f (%+7.2f%%)" % (b, 100 * b / nt))
        print("     EXIT ALPHA (B - A) : $%+9.2f (%+7.2f%%)  mkt-clustered 95%% CI [%+.0f, %+.0f]" % (
            b - a, 100 * (b - a) / nt, lo, hi))
        print("     marks at 168h vs settlement: mean |error| %.3f, mean (mark - settle) %+.3f"
              % (np.mean([abs(l["stop_px"] - (1.0 if l["pnl_a"] > 0 else 0.0)) for l in res]),
                 np.mean([l["stop_px"] - (1.0 if l["pnl_a"] > 0 else 0.0) for l in res])))
        bym = defaultdict(float)
        for l in res:
            bym[l["marketId"]] += l["delta"]
        srt = sorted(bym.items(), key=lambda kv: kv[1])
        print("     %d markets carry it; 3 worst %+.0f, 3 best %+.0f, ex-those-6 %+.0f" % (
            len(bym), sum(v for _, v in srt[:3]), sum(v for _, v in srt[-3:]),
            sum(v for _, v in srt[3:-3])))
        print()
        print("   %-14s %5s %8s %9s %9s %9s %9s %10s" % (
            "band", "legs", "$ntl", "hold$", "stop$", "delta$", "d%ntl", "settleWin%"))
        for nm, lo_, hi_ in list(BANDS) + [("SCOPE >=0.60", 0.60, 1.01), ("SCOPE <0.60", 0.0, 0.60)]:
            g = [l for l in res if lo_ <= l["px"] < hi_]
            if not g:
                continue
            gnt = sum(l["ntl"] for l in g)
            ga = sum(l["pnl_a"] for l in g)
            gb = sum(l["pnl_b"] for l in g)
            win = 100.0 * sum(1 for l in g if l["pnl_a"] > 0) / len(g)
            bym_g = defaultdict(float)
            for l in g:
                bym_g[l["marketId"]] += l["delta"]
            sg = sorted(bym_g.values())
            ex3 = sum(sg[1:-1]) if len(sg) > 2 else 0.0
            print("   %-14s %5d %8.0f %+9.0f %+9.0f %+9.0f %+8.1f%% %9.0f%%   ex-worst/best mkt %+.0f"
                  % (nm, len(g), gnt, ga, gb, gb - ga, 100 * (gb - ga) / gnt, win, ex3))
        print("   mark lag: the exit mark is the first snapshot at/after the horizon; "
              "median %.1fh late (n=%d)" % (median([l["stop_lag_h"] for l in res]), len(res)))
    else:
        print("   no fired-and-settled legs")

    print()
    print("=" * 118)
    print("S.5  THE CARD'S DECISION RULE (capital-days >= -50%, booked PnL > -$150), APPLIED")
    print("=" * 118)
    cut90 = now_ms - 90 * DAY
    rule_verdict("whole book (all priceable)", priced, cut90)
    rule_verdict("fired only", [l for l in priced if l["fires"]], cut90)
    rule_verdict("fired & exited in last 90d", [l for l in priced if l["fires"] and l["exit_actual"] >= cut90], cut90)
    rule_verdict("open book only (first tick)", [l for l in priced if l["status"] == "open"], cut90)
    rule_verdict("scope entry>=0.60 (v66)", [l for l in priced if l["px"] >= 0.60], cut90)
    rule_verdict("scope entry<0.60", [l for l in priced if l["px"] < 0.60], cut90)
    print()
    print("   per band (fired legs only; the rule's own test):")
    for nm, lo_, hi_ in BANDS:
        rule_verdict("  " + nm, [l for l in priced if l["fires"] and lo_ <= l["px"] < hi_], cut90)

    print()
    print("=" * 118)
    print("S.6  HORIZON SENSITIVITY -- is 168h the problem, or is any calendar cut the problem?")
    print("=" * 118)
    print("   %-8s %5s %8s %9s %9s %9s %9s %10s %10s" % (
        "horizon", "fired", "cd cut%", "d all$", "d >=.60$", "d <.60$", "d resolved$", "CI lo", "CI hi"))
    for h in HORIZONS:
        pz, _ = replay(legs, marks, now_ms, h * 3_600_000)
        fired = [l for l in pz if l["fires"]]
        if not fired:
            print("   %-8s (none)" % ("%dh" % h))
            continue
        cda = sum(l["cd_a"] for l in pz)
        cdb = sum(l["cd_b"] for l in pz)
        lo, hi = boot_delta(fired)
        print("   %-8s %5d %7.1f%% %+9.0f %+9.0f %+9.0f %+9.0f %+10.0f %+10.0f" % (
            "%dh" % h, len(fired), 100.0 * (cdb - cda) / cda,
            sum(l["delta"] for l in fired),
            sum(l["delta"] for l in fired if l["px"] >= 0.60),
            sum(l["delta"] for l in fired if l["px"] < 0.60),
            sum(l["delta"] for l in pz if l["status"] == "resolved"), lo, hi))

    print()
    print("=" * 118)
    print("S.7  IS THE CAPITAL SCARCE AT ALL -- the resource the rule claims to free")
    print("=" * 118)
    cap = rules.get("standardMaxOpenPositions") or 0
    cur = c.execute("SELECT COUNT(*) n, COALESCE(SUM(simulatedPositionSize),0) nt FROM PaperTrade "
                    "WHERE botId=? AND isDemo=0 AND status='open'", (args.lane,)).fetchone()
    gross = rules.get("maxGrossExposureUsd") or 0
    print("   standardMaxOpenPositions=%s  open now=%d (headroom %s)  open notional $%.0f  "
          "(gross-exposure base $%s is C-200-only)" % (
              cap, cur["n"], (cap - cur["n"]) if cap else "n/a", cur["nt"], gross))
    blk = c.execute(
        """SELECT COUNT(*) n FROM DecisionJournal
           WHERE decision='skip' AND risksJson LIKE '%open-position cap%' AND createdAt >= ?""",
        (now_ms - 30 * DAY,)).fetchone()["n"]
    print("   leg blocks naming `open-position cap`, last 30d (all lanes): %d" % blk)
    print("   v70's pre-registered refutation (>=20 in 30d) is therefore %s"
          % ("MET -- the rail should be re-armed" if blk >= 20 else "not met"))
    net = c.execute(
        """SELECT (SELECT COUNT(*) FROM PaperTrade WHERE botId=? AND isDemo=0 AND openedAt>=?) o,
                  (SELECT COUNT(*) FROM PaperTrade WHERE botId=? AND isDemo=0 AND resolvedAt>=?) r""",
        (args.lane, now_ms - 30 * DAY, args.lane, now_ms - 30 * DAY)).fetchone()
    print("   trailing 30d flow: %d opens vs %d resolutions = %+.2f legs/day net"
          % (net["o"], net["r"], (net["o"] - net["r"]) / 30.0))

    print()
    print("=" * 118)
    print("S.7b  THE OPEN BOOK BY BAND -- what a first tick would touch, and what it would sell")
    print("=" * 118)
    op = [l for l in priced if l["status"] == "open"]
    print("   %-14s %5s %9s %11s %11s %9s %9s" % (
        "band", "legs", "$ntl", "cap-days", "unrealised", "avg age", "med age"))
    for nm, lo_, hi_ in BANDS:
        g = [l for l in op if lo_ <= l["px"] < hi_]
        if not g:
            continue
        print("   %-14s %5d %9.0f %11.0f %+11.2f %8.0fd %8.0fd" % (
            nm, len(g), sum(l["ntl"] for l in g), sum(l["cd_a"] for l in g),
            sum(l["pnl_a"] for l in g), sum(l["age_d"] for l in g) / len(g),
            median([l["age_d"] for l in g])))
    ttr = [l["age_d"] for l in priced if l["status"] == "resolved"]
    print("   median time-to-resolution on the lane's resolved legs: %.0fd (n=%d); "
          "open book median age %.0fd"
          % (median(ttr), len(ttr), median([l["age_d"] for l in op])))

    print()
    print("=" * 118)
    print("S.7c  STRANDED OR LONG-DATED -- where each open leg's MARKET actually ends")
    print("=" * 118)
    mk = {}
    for l in op:
        if l["marketId"] in mk:
            continue
        r = c.execute(
            """SELECT collectedAt, timeToResolution FROM MarketSnapshot
               WHERE marketId=? AND timeToResolution IS NOT NULL
               ORDER BY collectedAt DESC LIMIT 1""", (l["marketId"],)).fetchone()
        if r and r["timeToResolution"] is not None:
            mk[l["marketId"]] = r["collectedAt"] + float(r["timeToResolution"]) * 3_600_000
    buckets = (("past end date (overdue)", -10**9, 0.0), ("ends within 30d", 0.0, 30.0),
               ("ends 30-90d", 30.0, 90.0), ("ends 90-365d", 90.0, 365.0),
               ("ends >365d", 365.0, 10**9))
    cov = [l for l in op if l["marketId"] in mk]
    print("   coverage: %d/%d open legs have a market end date from MarketSnapshot.timeToResolution"
          % (len(cov), len(op)))
    print("   %-26s %5s %9s %11s %8s" % ("bucket", "legs", "% legs", "$ntl", "cap-days"))
    nt_all = sum(l["ntl"] for l in op)
    for nm, lo_, hi_ in buckets:
        g = [l for l in cov if lo_ <= (mk[l["marketId"]] - now_ms) / DAY < hi_]
        if not g:
            continue
        print("   %-26s %5d %8.0f%% %11.0f %8.0f" % (
            nm, len(g), 100.0 * len(g) / len(op), sum(l["ntl"] for l in g),
            sum(l["cd_a"] for l in g)))
    od = [l for l in cov if (mk[l["marketId"]] - now_ms) / DAY < 0]
    print("   implied-overdue share: %.1f%% of legs, %.1f%% of open notional"
          % (100.0 * len(od) / len(op), 100.0 * sum(l["ntl"] for l in od) / nt_all))

    print()
    print("=" * 118)
    print("S.8  CROSS-CHECK against the committed instrument (profit-velocity.ground_truth_stop)")
    print("=" * 118)
    try:
        ref = c.execute(
            """SELECT id, marketId, entryPrice px, simulatedPositionSize ntl, realizedPnl pnl, openedAt
               FROM PaperTrade WHERE botId=? AND isDemo=0 AND status='resolved'
                 AND resolvedAt IS NOT NULL AND (resolvedAt-openedAt) > ? AND realizedPnl IS NOT NULL""",
            (args.lane, H168)).fetchall()
        mine = {l["id"]: l for l in priced}
        diffs = []
        for r in ref:
            m = mine.get(r["id"])
            if not m or not m["fires"]:
                continue
            snaps = c.execute("SELECT collectedAt, yesPrice, noPrice FROM MarketSnapshot "
                              "WHERE marketId=? ORDER BY collectedAt", (r["marketId"],)).fetchall()
            if not snaps:
                continue
            times = [s["collectedAt"] for s in snaps]
            i = bisect.bisect_left(times, r["openedAt"] + H168)
            if i >= len(snaps):
                continue
            s = snaps[i]
            px = s["yesPrice"] if c.execute("SELECT outcome FROM PaperTrade WHERE id=?",
                                            (r["id"],)).fetchone()[0] == "YES" else s["noPrice"]
            if px is None or not (0 <= px <= 1):
                continue
            stop_pv = r["ntl"] * (px / r["px"] - 1.0)
            diffs.append((m["pnl_b"], stop_pv))
        if diffs:
            med = median([abs(a - b) for a, b in diffs])
            print("   %d legs priced by both instruments; median |PnlSnapshot mark - MarketSnapshot mark| "
                  "= $%.3f" % (len(diffs), med))
            print("   sum PnL  PnlSnapshot %.2f   MarketSnapshot %.2f"
                  % (sum(a for a, _ in diffs), sum(b for _, b in diffs)))
        else:
            print("   no overlapping priceable legs")
    except Exception as e:  # cross-check must never block the read
        print("   cross-check skipped: %s" % e)

    print()
    print("=" * 118)
    print("S.9  PRICE-SOURCE SENSITIVITY -- does the band the scope decision rests on survive it?")
    print("=" * 118)
    print("   Same legs, same horizon: PnlSnapshot (label-correct, per-token) vs MarketSnapshot")
    print("   (yesPrice/noPrice POSITIONAL -- correct only on binary YES/NO markets).")
    print("   %-14s %5s %9s %10s %10s %10s" % ("band", "legs", "$ntl", "d PnlSnap", "d MktSnap", "sign flip?"))
    rows = []
    for l in res:
        snaps = c.execute("SELECT collectedAt, yesPrice, noPrice FROM MarketSnapshot "
                          "WHERE marketId=? ORDER BY collectedAt", (l["marketId"],)).fetchall()
        if not snaps:
            continue
        times = [s["collectedAt"] for s in snaps]
        i = bisect.bisect_left(times, l["openedAt"] + H168)
        if i >= len(snaps):
            continue
        s = snaps[i]
        px = s["yesPrice"] if l["outcome"] == "YES" else s["noPrice"]
        if px is None or not (0 <= px <= 1):
            continue
        rows.append((l, l["ntl"] * (px / l["px"] - 1.0) - l["pnl_a"]))
    for nm, lo_, hi_ in BANDS:
        g = [r for r in rows if lo_ <= r[0]["px"] < hi_]
        if not g:
            continue
        a = sum(r[0]["delta"] for r in g)
        b = sum(r[1] for r in g)
        print("   %-14s %5d %9.0f %+10.0f %+10.0f %10s" % (
            nm, len(g), sum(r[0]["ntl"] for r in g), a, b,
            "YES" if a * b < 0 else "no"))


if __name__ == "__main__":
    main()
