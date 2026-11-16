#!/usr/bin/env python3
"""LADDER CREDIT BASIS — booked rows vs positions only.

WHY THIS EXISTS
---------------
The C-200 advance gate (GOAL POLICY v2) sums `PaperTrade.realizedPnl` over the trailing
7 SETTLED local days and compares it with `target x 7`. `query_bankroll.js`, the overview
ladder card (`src/app/page.tsx`) and `src/app/analytics/page.tsx` all sum the STORED
realizedPnl with no fill-class filter.

Since the fill-aware booking flip (2026-10-28) `src/lib/paper.ts::bookedPnl()` forces a
proven-unfilled leg to 0 -- but only on the WRITE path. A leg that settled BEFORE the
resolver stamped it `fillStatus='unfilled'` keeps the realizedPnl it was booked with, and
every read path above still sums it. This instrument prices that class: the same window
read as BOOKED ROWS (what the gate reads today) and as POSITIONS ONLY (stamped-unfilled
credited at zero, exactly as bookedPnl() would).

READ-ONLY. sqlite3 opened mode=ro. No prisma write, no RuleSet write, no rule edit.

RUN
  python3 scripts/ladder-credit-positions-only.py [--reference YYYY-MM-DD]
"""
from __future__ import annotations

import argparse
import os
import sqlite3
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DB = os.path.join(ROOT, "prisma", "dev.db")

LANE = "BANKROLL_200"
REGIME_MIN_VERSION = 68          # regime = DecisionJournal.ruleSetVersion >= this
SETTLE_DAYS = 3                  # query_bankroll.js SETTLE_DAYS
GATE_DAYS = 7                    # GATE_WINDOW_DAYS
PHASES = [("Phase 1", 250), ("Phase 2", 500), ("Phase 3", 1000), ("Phase 4", 2000), ("Ultimate", 5000)]
FLIP = datetime(2026, 10, 28)    # fill-aware booking flip (code default ON)


def con():
    c = sqlite3.connect("file:" + DB + "?mode=ro", uri=True)
    c.row_factory = sqlite3.Row
    return c


def day(ts_ms):
    return datetime.fromtimestamp(ts_ms / 1000.0).strftime("%Y-%m-%d")


def load(c):
    q = """
      SELECT p.id, p.fillStatus, p.fillResolvedAt, p.status, p.realizedPnl,
             p.simulatedPositionSize, p.openedAt, p.closedAt, p.resolvedAt,
             d.ruleSetVersion AS rv
        FROM PaperTrade p
        LEFT JOIN DecisionJournal d ON d.id = p.decisionJournalId
       WHERE p.botId = ? AND p.isDemo = 0 AND p.status IN ('closed','resolved')
    """
    rows = [dict(r) for r in c.execute(q, (LANE,))]
    for r in rows:
        end = r["closedAt"] if r["closedAt"] is not None else r["resolvedAt"]
        r["end"] = end
        r["day"] = day(end) if end is not None else None
        r["pnl"] = r["realizedPnl"] or 0.0
        r["pos_pnl"] = 0.0 if r["fillStatus"] == "unfilled" else r["pnl"]
        r["stamped_after_settle"] = bool(
            r["fillResolvedAt"] is not None and end is not None and r["fillResolvedAt"] > end
        )
    return rows


def gate(rows, ref, key):
    """Mirror query_bankroll.js: 14 local days, settled window = days[3..10)."""
    by = {}
    for r in rows:
        if r["day"]:
            by.setdefault(r["day"], []).append(r)
    daily = []
    for i in range(14):
        d = (ref - timedelta(days=i)).strftime("%Y-%m-%d")
        daily.append((d, sum(x[key] for x in by.get(d, [])), len(by.get(d, []))))
    settled = [x[1] for x in daily[SETTLE_DAYS:SETTLE_DAYS + GATE_DAYS]]
    t0 = [x[1] for x in daily[:GATE_DAYS]]
    idx = 0
    for i, (_, target) in enumerate(PHASES):
        if len(settled) == GATE_DAYS and sum(settled) >= target * GATE_DAYS:
            idx = i + 1
        else:
            break
    idx = min(idx, len(PHASES) - 1)
    return {
        "daily": daily,
        "settled_sum": sum(settled),
        "t0_sum": sum(t0),
        "goal": PHASES[idx],
        "need": PHASES[idx][1] * GATE_DAYS,
        "window": (daily[SETTLE_DAYS + GATE_DAYS - 1][0], daily[SETTLE_DAYS][0]),
        "legs": sum(x[2] for x in daily[SETTLE_DAYS:SETTLE_DAYS + GATE_DAYS]),
    }


def window_stats(rows, start_day, end_day, key):
    sel = [r for r in rows if r["day"] and start_day <= r["day"] <= end_day]
    days = (datetime.strptime(end_day, "%Y-%m-%d") - datetime.strptime(start_day, "%Y-%m-%d")).days + 1
    pnl = sum(r[key] for r in sel)
    notional = sum(r["simulatedPositionSize"] for r in sel)
    return {"legs": len(sel), "notional": notional, "pnl": pnl, "days": days,
            "per_day": pnl / days if days else 0.0}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--reference", help="window end date YYYY-MM-DD (default: today, local)")
    a = ap.parse_args()
    ref = datetime.strptime(a.reference, "%Y-%m-%d") if a.reference else datetime.now()
    ref = datetime(ref.year, ref.month, ref.day)

    c = con()
    rows = load(c)
    print(f"LADDER CREDIT BASIS | lane {LANE} | reference {ref:%Y-%m-%d} (local calendar day)")
    print(f"finished legs: {len(rows):,} | classes: "
          + ", ".join(f"{k or 'NULL'}={sum(1 for r in rows if (r['fillStatus'] or 'NULL') == (k or 'NULL'))}"
                      for k in ("filled", "unfilled", None)))

    print("\nS1. THE LADDER'S OWN 14-DAY SERIES (query_bankroll.js convention, local days)")
    gb, gp = gate(rows, ref, "pnl"), gate(rows, ref, "pos_pnl")
    print(f"  {'day':<12} {'legs':>5} {'BOOKED':>10} {'POSITIONS':>10} {'delta':>9}")
    for (d, b, n), (_, p, _) in zip(gb["daily"], gp["daily"]):
        print(f"  {d:<12} {n:>5} {b:>+10.2f} {p:>+10.2f} {b - p:>+9.2f}")

    print("\nS2. THE ADVANCE GATE, EACH BASIS (settled 7d SUM >= target x 7)")
    for label, g in (("BOOKED ROWS (live today)", gb), ("POSITIONS ONLY (proposed)", gp)):
        need = g["need"]
        verdict = "PASS" if g["settled_sum"] >= need else f"fail at {g['settled_sum'] / need * 100:.1f}%"
        print(f"  {label:<28} settled {g['settled_sum']:>+9.2f} vs need {need:>6} "
              f"-> rung {g['goal'][0]:<8} {verdict} | window {g['window'][0]} .. {g['window'][1]} "
              f"| {g['legs']} legs | T+0 {g['t0_sum']:>+9.2f}")

    print("\nS3. THE WINDOWS QUOTED IN THE CARD")
    today = ref.strftime("%Y-%m-%d")
    lo7 = (ref - timedelta(days=6)).strftime("%Y-%m-%d")
    lo14 = (ref - timedelta(days=13)).strftime("%Y-%m-%d")
    reg = [r for r in rows if r["rv"] is not None and r["rv"] >= REGIME_MIN_VERSION]
    reg_start = min(r["day"] for r in reg)
    reg_end = max(r["day"] for r in reg)
    hdr = f"  {'window':<30} {'legs':>5} {'notional':>10} {'BOOKED':>10} {'$/day':>8} {'POSITIONS':>10} {'$/day':>8} {'delta':>9}"
    print(hdr)
    for label, sub, s, e in (
        ("last 7d (trailing, local)", rows, lo7, today),
        ("last 14d (trailing, local)", rows, lo14, today),
        ("regime v>=68 (settle span)", reg, reg_start, reg_end),
        ("whole book", rows, min(r["day"] for r in rows), max(r["day"] for r in rows)),
    ):
        b = window_stats(sub, s, e, "pnl")
        p = window_stats(sub, s, e, "pos_pnl")
        print(f"  {label:<30} {b['legs']:>5} {b['notional']:>10,.0f} {b['pnl']:>+10.2f} "
              f"{b['per_day']:>+8.2f} {p['pnl']:>+10.2f} {p['per_day']:>+8.2f} {b['pnl'] - p['pnl']:>+9.2f}")
    print(f"  regime v>={REGIME_MIN_VERSION}: {len(reg)} legs, settle span {reg_start} .. {reg_end} "
          f"({(datetime.strptime(reg_end, '%Y-%m-%d') - datetime.strptime(reg_start, '%Y-%m-%d')).days + 1} days)")

    print("\nS4. THE CLASS THE FIX TARGETS — stamped 'unfilled' AND still carrying realizedPnl")
    unf = [r for r in rows if r["fillStatus"] == "unfilled"]
    carry = [r for r in unf if abs(r["pnl"]) >= 0.005]
    print(f"  stamped-unfilled finished legs: {len(unf):,} | of them carrying non-zero realizedPnl: {len(carry):,}")
    print(f"  carried PnL {sum(r['pnl'] for r in carry):+,.2f} on ${sum(r['simulatedPositionSize'] for r in carry):,.0f} notional")
    print(f"  of those, stamped AFTER they settled: {sum(1 for r in carry if r['stamped_after_settle']):,} "
          f"(the resolver's normal order: settle books p(fill)=1, the stamp arrives later)")
    print(f"  inside the trailing 7d: {sum(1 for r in carry if r['day'] >= lo7):,} legs "
          f"{sum(r['pnl'] for r in carry if r['day'] >= lo7):+,.2f} | "
          f"inside 14d: {sum(1 for r in carry if r['day'] >= lo14):,} legs "
          f"{sum(r['pnl'] for r in carry if r['day'] >= lo14):+,.2f} | "
          f"in regime: {sum(1 for r in carry if r['rv'] is not None and r['rv'] >= REGIME_MIN_VERSION):,} legs")
    bym = {}
    for r in carry:
        bym.setdefault(r["day"][:7], [0, 0.0])
        bym[r["day"][:7]][0] += 1
        bym[r["day"][:7]][1] += r["pnl"]
    print("  by settle month: " + " | ".join(f"{m} {n} legs {p:+.2f}" for m, (n, p) in sorted(bym.items())))
    pos_carry = [r for r in carry if r["pnl"] > 0]
    print(f"  sign split: {len(pos_carry)} winners {sum(r['pnl'] for r in pos_carry):+,.2f} · "
          f"{len(carry) - len(pos_carry)} losers {sum(r['pnl'] for r in carry if r['pnl'] <= 0):+,.2f}")

    print("\nS5. EVERY PUBLISHED FIGURE THAT MOVES (all-time + the ledger)")
    tot = sum(r["pnl"] for r in rows)
    totp = sum(r["pos_pnl"] for r in rows)
    print(f"  overview card / EOD 'realized (all time)'   {tot:+,.2f} -> {totp:+,.2f}  ({totp - tot:+,.2f})")
    b = c.execute("SELECT principal, realizedPnl, cashBalance FROM BotBankroll WHERE botId=?", (LANE,)).fetchone()
    if b:
        print(f"  BotBankroll.realizedPnl (ledger, NOT a row sum) {b['realizedPnl']:+,.2f} "
              f"-- a read-path fix does not touch it; principal ${b['principal']:,.2f} cash ${b['cashBalance']:,.2f}")
    print(f"  ledger-vs-rows gap {((b['realizedPnl'] if b else 0) - tot):+,.2f}")

    print("\nS7. THE PAYOFF FIGURES THAT MOVE WITH THE SAME COLUMN (win rate / ROI, settled rows)")
    def payoff(sub, key):
        pnl = [r[key] for r in sub]
        stake = sum(r["simulatedPositionSize"] for r in sub)
        wins = [p for p in pnl if p > 0]
        total = sum(pnl)
        return (len(sub), len(wins), len(wins) / max(1, len(sub)) * 100, total,
                total / stake * 100 if stake else 0.0)
    for label, sub in (("whole book", rows), ("trailing 14d", [r for r in rows if r["day"] >= lo14]),
                       ("regime v>=68", reg)):
        ba = payoff(sub, "pnl")
        pa = payoff(sub, "pos_pnl")
        print(f"  {label:<14} legs {ba[0]:>5}  win {ba[1]:>4} ({ba[2]:>5.1f}%)  PnL {ba[3]:>+9.2f}  ROI {ba[4]:>+6.2f}%"
              f"   ->  legs {pa[0]:>5}  win {pa[1]:>4} ({pa[2]:>5.1f}%)  PnL {pa[3]:>+9.2f}  ROI {pa[4]:>+6.2f}%")

    print("\nS8. REALITY CHECK — DOES THE LEDGER CHANNEL BIND? (netWorth -> exposure cap)")
    try:
        rules = c.execute("SELECT version, rulesJson FROM RuleSet ORDER BY version DESC LIMIT 1").fetchone()
        import json
        live = json.loads(rules["rulesJson"])
        base = live.get("maxGrossExposureUsd", 250)
        if b:
            un = c.execute("SELECT COALESCE(SUM(unrealizedPnl),0) FROM PaperTrade WHERE isDemo=0 "
                           "AND botId=? AND status='open'", (LANE,)).fetchone()[0]
            open_n = c.execute("SELECT COALESCE(SUM(simulatedPositionSize),0) FROM PaperTrade "
                               "WHERE isDemo=0 AND botId=? AND status='open'", (LANE,)).fetchone()[0]
            principal = b["principal"] or 0.0
            nw = principal + (b["realizedPnl"] or 0.0) + un
            nw_p = principal + totp + un
            capf = lambda n: base + 0.5 * max(0.0, n - principal)
            print(f"  active RuleSet v{rules['version']}: maxGrossExposureUsd={base}")
            print(f"  netWorth booked ${nw:,.2f} -> cap ${capf(nw):,.0f} | positions-only ${nw_p:,.2f} -> cap ${capf(nw_p):,.0f}")
            print(f"  OPEN C-200 notional ${open_n:,.2f} — the cap is not binding either way "
                  f"({open_n / capf(nw) * 100:.1f}% of the booked cap), so the ledger channel is deferred, not urgent.")
    except Exception as e:  # noqa: BLE001 - instrument must not fail on a missing table
        print(f"  cap read skipped: {e}")

    print("\nS6. READERS THAT SUM THE STORED COLUMN WITHOUT A FILL FILTER")
    hits = []
    for rel in ("query_bankroll.js", "src/app/page.tsx", "src/app/analytics/page.tsx", "src/lib/report.ts"):
        p = os.path.join(ROOT, rel)
        try:
            txt = open(p, encoding="utf-8").read()
        except OSError:
            continue
        n = txt.count("realizedPnl")
        f = txt.count("fillStatus")
        hits.append(f"  {rel:<28} realizedPnl x{n:<3} fillStatus x{f}")
    print("\n".join(hits))
    print("  (fillStatus x0 on every read path = the gate, the overview ladder, the analytics ladder")
    print("   and the EOD all credit a proven-unfilled leg; only src/lib/paper.ts applies bookedPnl)")


if __name__ == "__main__":
    main()
