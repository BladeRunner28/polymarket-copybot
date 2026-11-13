#!/usr/bin/env python3
"""permarket-seat-release — read-only re-derivation of the v55 per-market SEAT
defect on card `permarket-legs-seat-release`.

Answers four questions, all from `prisma/dev.db` opened READ-ONLY:
  1. class split   — how many v55 legs-clause refusals are PHANTOM (true open < max)?
  2. mechanism     — for each phantom, which same-MARKET row consumed the seat, and
                     would releasing it admit the copy (v58 is the only gate below
                     the seat)?
  3. binding       — does the rail hold after activation (no market at 3+ legs)?
  4. carriers      — the openPaperTrade-throw carrier, and the dispatch->row lag that
                     makes "booking point = dispatch" a truthful seat basis for C-200.

Basis, stated so a reader can disagree with it: population = DecisionJournal rows
isDemo=0 carrying `v55 per-market cap (...)`; level = one decision; clock = createdAt
UTC (ms); ground truth = PaperTrade [openedAt, COALESCE(closedAt, resolvedAt)).

Usage:  python3 scripts/permarket-seat-release.py
"""
import collections
import datetime as dt
import json
import os
import re
import sqlite3

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, "..", "prisma", "dev.db")

V55_RE = re.compile(r"v55 per-market cap \((legs (\d+) > max (\d+)|notional \$([\d.]+) > cap \$([\d.]+))\)")
V58_RE = re.compile(r"v58 per-wallet cap \(notional \$([\d.]+) > cap \$([\d.]+)")
GATE_TAGS = ("v58 per-wallet cap", "v55 per-market cap", "gross exposure", "open-position cap",
             "per-cycle copy cap", "wallet daily copy cap", "coalesced")


def iso(ms, frac=False):
    if ms is None:
        return "OPEN"
    t = dt.datetime.utcfromtimestamp(ms / 1000.0)
    return t.strftime("%m-%d %H:%M:%S.%f")[:-3] if frac else t.strftime("%Y-%m-%d %H:%M:%S")


def connect():
    return sqlite3.connect("file:%s?mode=ro" % os.path.abspath(DB), uri=True)


def v55_activation(con):
    row = con.execute("SELECT createdAt FROM RuleSet WHERE version=55").fetchone()
    return row[0]


def main():
    con = connect()
    con.row_factory = sqlite3.Row
    v55_ms = v55_activation(con)
    active = con.execute("SELECT version, rulesJson FROM RuleSet WHERE active=1"
                         " ORDER BY version DESC LIMIT 1").fetchone()
    rules = json.loads(active["rulesJson"])
    print("active RuleSet v%s | maxMarketLegsPerMarketId=%s maxMarketNotionalPctOfCap=%s "
          "maxWalletNotionalPctOfCap=%s | v55 live since %sZ" % (
              active["version"], rules.get("maxMarketLegsPerMarketId"),
              rules.get("maxMarketNotionalPctOfCap"), rules.get("maxWalletNotionalPctOfCap"),
              iso(v55_ms)))

    # ---- booked legs -> intervals per market and per wallet ----
    iv_market = collections.defaultdict(list)
    iv_wallet = collections.defaultdict(list)
    for r in con.execute("SELECT marketId, walletAddress, openedAt, closedAt, resolvedAt,"
                         " simulatedPositionSize FROM PaperTrade"
                         " WHERE botId='BANKROLL_200' AND isDemo=0"):
        end = r["closedAt"] if r["closedAt"] is not None else r["resolvedAt"]
        rec = (r["openedAt"], end, r["simulatedPositionSize"] or 0.0)
        iv_market[r["marketId"]].append(rec)
        iv_wallet[r["walletAddress"]].append(rec)

    def live(rows, at):
        xs = [x for x in rows if x[0] <= at and (x[1] is None or x[1] > at)]
        return len(xs), round(sum(x[2] for x in xs), 2)

    # ---- 1. class split ----
    rows = con.execute("SELECT id, createdAt, walletAddress, marketId, risksJson, simulatedPositionSize"
                       " FROM DecisionJournal WHERE isDemo=0"
                       " AND risksJson LIKE '%v55 per-market cap%' ORDER BY createdAt").fetchall()
    refusals, phantoms = [], []
    for r in rows:
        m = V55_RE.search(r["risksJson"] or "")
        if not m:
            continue
        legs, notional = live(iv_market[r["marketId"]], r["createdAt"])
        if m.group(2) is not None:
            clause, why, max_legs = "legs", "legs %s > max %s" % (m.group(2), m.group(3)), int(m.group(3))
            klass = "genuine" if legs >= max_legs else "phantom"
        else:
            clause, why, max_legs = "notional", "notional $%s > cap $%s" % (m.group(4), m.group(5)), 0
            klass = "genuine" if notional > 0 else "unknown"
        rec = dict(ts=r["createdAt"], wallet=r["walletAddress"], marketId=r["marketId"], id=r["id"],
                   clause=clause, why=why, legs=legs, notional=notional, klass=klass)
        refusals.append(rec)
        if klass == "phantom":
            phantoms.append(rec)

    clause = collections.Counter(r["clause"] for r in refusals)
    klass = collections.Counter(r["klass"] for r in refusals)
    print("\n[1] v55 refusals all-time: %d | clause %s | class %s"
          % (len(refusals), dict(clause), dict(klass)))
    if refusals:
        rail_age_d = (dt.datetime.utcnow().timestamp() * 1000 - v55_ms) / 86400000.0
        print("    first->last refusal span %.1f d | rail age %.1f d | refusal rate %.2f/day"
              " | phantom rate %.3f/day" % (
                  (refusals[-1]["ts"] - refusals[0]["ts"]) / 86400000.0, rail_age_d,
                  len(refusals) / rail_age_d, len(phantoms) / rail_age_d))
        last30 = [r for r in refusals if r["ts"] >= dt.datetime.utcnow().timestamp() * 1000 - 30 * 86400000]
        print("    last 30d: %d refusals, %d phantom"
              % (len(last30), len([r for r in last30 if r["klass"] == "phantom"])))

    # ---- 2. per-phantom mechanism + admission verdict ----
    print("\n[2] phantoms: %d" % len(phantoms))
    for p in phantoms:
        ts = p["ts"]
        wl, wn = live(iv_wallet[p["wallet"]], ts)
        print("\n  %sZ %s  wallet %s" % (iso(ts), p["marketId"][:58], p["wallet"][:12]))
        print("    printed %s | TRUE open in market: %d legs $%.2f | candidate wallet open ACROSS book: %d legs $%.2f"
              % (p["why"], p["legs"], p["notional"], wl, wn))
        for q in con.execute("SELECT createdAt, decision, walletAddress, risksJson FROM DecisionJournal"
                             " WHERE isDemo=0 AND marketId=? AND createdAt BETWEEN ? AND ?"
                             " ORDER BY createdAt", (p["marketId"], ts - 60000, ts + 60000)):
            risks = q["risksJson"] or ""
            tags = [t for t in GATE_TAGS if t in risks]
            v58 = V58_RE.search(risks)
            print("    same-market peer %+8.3fs %-11s %s %s %s" % (
                (q["createdAt"] - ts) / 1000.0, q["decision"], q["walletAddress"][:10],
                ",".join(tags) or "-", ("| " + v58.group(0)) if v58 else ""))
        intents = con.execute("SELECT COUNT(*) FROM FillIntent WHERE decisionJournalId=?",
                              (p["id"],)).fetchone()[0]
        print("    FillIntent rows for the refused decision: %d" % intents)
    # the same wallet's own v58 refusal is the admission verdict: projected vs ceiling
    print("\n  ADMISSION VERDICT — v58 is the only gate below the seat; check the printed ceiling"
          " against the candidate wallet's open notional above. Equal ceilings => 0 admissions.")

    # ---- 3. binding baseline ----
    by_market = {mk: [(a, b) for (a, b, _n) in xs] for mk, xs in iv_market.items()}
    dist = collections.Counter()
    breaches = 0
    opened_post = 0
    for mk, legs in by_market.items():
        if not any(a >= v55_ms for a, _b in legs):
            continue
        ev = []
        for a, b in legs:
            ev.append((a, 1))
            if b is not None:
                ev.append((b, -1))
        ev.sort()
        cur = mx = 0
        for t, d in ev:
            cur += d
            if t >= v55_ms:
                mx = max(mx, cur)
                if cur > 2:
                    breaches += 1
        dist[mx] += 1
    for mk, legs in by_market.items():
        for a, _b in legs:
            if a < v55_ms:
                continue
            opened_post += 1
            live_others = sum(1 for (x, y) in legs if x <= a and (y is None or y > a) and x != a)
            if live_others >= 2:
                breaches += 1
    print("\n[3] markets touched post-v55: %d | max concurrent C-200 legs distribution: %s"
          % (sum(dist.values()), dict(sorted(dist.items()))))
    print("    post-v55 legs: %d | 3+ concurrent-leg instants or admit-on->=2 events: %d"
          % (opened_post, breaches))

    # ---- 4. carriers ----
    carrier = con.execute(
        "SELECT COUNT(*) FROM DecisionJournal d WHERE d.isDemo=0 AND d.decision='paper_copy'"
        " AND NOT EXISTS (SELECT 1 FROM PaperTrade p WHERE p.decisionJournalId=d.id)"
        " AND NOT EXISTS (SELECT 1 FROM FillIntent f WHERE f.decisionJournalId=d.id)").fetchone()[0]
    childless = con.execute(
        "SELECT COUNT(*) FROM DecisionJournal d WHERE d.isDemo=0 AND d.decision='paper_copy'"
        " AND NOT EXISTS (SELECT 1 FROM PaperTrade p WHERE p.decisionJournalId=d.id)").fetchone()[0]
    lag = sorted(r[0] / 1000.0 for r in con.execute(
        "SELECT p.openedAt - f.dispatchedAt FROM FillIntent f JOIN PaperTrade p ON p.id=f.paperTradeId"
        " WHERE f.botId='BANKROLL_200' AND p.openedAt >= f.dispatchedAt"))
    unlinked, total_int = con.execute(
        "SELECT SUM(CASE WHEN NOT EXISTS (SELECT 1 FROM PaperTrade p WHERE p.id=f.paperTradeId)"
        " THEN 1 ELSE 0 END), COUNT(*) FROM FillIntent f WHERE f.botId='BANKROLL_200'").fetchone()
    print("\n[4] openPaperTrade-throw carrier: childless paper_copy %d (of which no FillIntent: %d)"
          % (childless, carrier))
    if lag:
        print("    FillIntent->PaperTrade lag: n=%d median %.2fs p90 %.2fs max %.2fs"
              % (len(lag), lag[len(lag) // 2], lag[int(len(lag) * 0.9)], lag[-1]))
    print("    C-200 FillIntent rows with no linked PaperTrade: %d of %d (fail-closed direction)"
          % (unlinked or 0, total_int))
    con.close()


if __name__ == "__main__":
    main()
