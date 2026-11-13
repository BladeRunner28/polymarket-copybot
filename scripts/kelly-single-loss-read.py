#!/usr/bin/env python3
"""kelly-single-loss-read -- the measurement the card `kelly-single-loss-concentration-test`
pre-registered on 2026-10-21 (kelly rec 4, APPROVED AS THE TEST ONLY).

WHY THIS FILE EXISTS
--------------------
The card's DECISION RULE is arithmetic and was never run: "propose a per-position cap or a
concurrent-long-shot limit ONLY if the measured concurrent-full-loss exposure exceeded 10% of
net worth on >=1 day in the read window, or a single leg lost >1.3% of net worth twice in
30 days. REFUTATION: if it never exceeded 10%, close with that null."

OVERLAP, STATED SO NOTHING IS RE-DERIVED
----------------------------------------
`scripts/standard-longshot-concentration.py` (Lane B) already prints S1/S2 on the SAME
population and the SAME bases at the 10% level, plus a 10%-cap counterfactual on STANDARD.
This script does NOT re-argue those figures: it recomputes the live open book only as a
cross-check (arm A) and adds what the card needs and neither tool printed:
  * the concurrent LONG-SHOT LEG-COUNT distribution (the card says "positions", not dollars)
  * day counts at 5% / 10% / 15% of net worth, not just 10%
  * per-leg loss as a share of net worth, and the "twice in 30 days" clause
  * the realized-outcome replay, and whether the concurrent set is same-event (the card's
    "correlated drawdown" premise)

BASES EACH NUMBER CARRIES (each can flip a level, so each is printed, never implied)
  * population: PaperTrade.isDemo = 0 only -- a demo leg is not a decision.
  * level: one open-position SET at one entry instant; days are calendar days (UTC) of entry.
  * clock: entry = openedAt; exit = closedAt ?? resolvedAt (a leg is risk until it is closed).
  * dollars at risk = simulatedPositionSize (the stake that can go to zero), NEVER size x price.
  * long-shot = entryPrice < longshotMaxPrice read from the ACTIVE RuleSet.
  * net worth(t) = principal + realised PnL of legs closed before t. REALIZED ONLY: unrealised
    marks would RAISE net worth and LOOSEN the percentage, so this is the strict direction.

READ-ONLY: opens prisma/dev.db with ?mode=ro. Writes only data/kelly-single-loss-read.json.
"""
from __future__ import annotations

import bisect
import datetime
import json
import os
import re
import sqlite3
import sys

DB = "prisma/dev.db"
ARTIFACT = "data/kelly-single-loss-read.json"
LANES = ("BANKROLL_200", "STANDARD")
LONG_SHOT_PCT_BAR = 1.3   # card: a single leg losing more than 1.3% of net worth
WINDOW_DAYS = 30


def ms(v):
    """Prisma DATETIME is Unix-ms in this DB."""
    return None if v is None else int(v) / 1000.0


def utc_day(t):
    return datetime.datetime.utcfromtimestamp(t).strftime("%Y-%m-%d")


def event_key(market_id: str) -> str:
    """Same-EVENT proxy: the leading league/team tokens of a slugged marketId.

    'nba-okc-por-2026-11-11-total-196pt5' -> 'nba-okc-por'. A PROXY for "one event can settle
    many legs together", labelled as such wherever used; never the basis of a level.
    """
    m = re.match(r"^([a-z]{2,5}(?:-[a-z0-9]{2,5}){0,3})-\d{4}-\d{2}-\d{2}", market_id or "")
    return m.group(1) if m else (market_id or "?")


def active_rules(con):
    row = con.execute(
        "SELECT version, rulesJson FROM RuleSet WHERE active=1 ORDER BY version DESC LIMIT 1"
    ).fetchone()
    if not row:
        raise SystemExit("no active RuleSet")
    return row["version"], json.loads(row["rulesJson"])


def bankrolls(con):
    out = {}
    for r in con.execute("SELECT botId, principal, realizedPnl FROM BotBankroll"):
        out[r["botId"]] = {"principal": r["principal"] or 0.0, "realized": r["realizedPnl"] or 0.0}
    return out


def legs(con, lane):
    q = """
    SELECT id, entryPrice, simulatedPositionSize AS ntl, realizedPnl AS pnl, status,
           openedAt, closedAt, resolvedAt, marketId
    FROM PaperTrade
    WHERE botId = ? AND isDemo = 0 AND simulatedPositionSize > 0 AND openedAt IS NOT NULL
    ORDER BY openedAt
    """
    out = []
    for r in con.execute(q, (lane,)):
        d = dict(r)
        d["open_s"] = ms(r["openedAt"])
        c = ms(r["closedAt"])
        if c is None:
            c = ms(r["resolvedAt"])
        d["close_s"] = c if c is not None else float("inf")
        d["event"] = event_key(r["marketId"])
        out.append(d)
    return out


class NetWorth:
    """Realised-only net worth as it stood at an arbitrary entry instant."""

    def __init__(self, rows, principal):
        self.principal = principal
        self.times, self.cum = [], []
        closes = sorted(
            (r["close_s"], r["pnl"] or 0.0) for r in rows if r["close_s"] != float("inf")
        )
        running = 0.0
        for t, pnl in closes:
            running += pnl
            self.times.append(t)
            self.cum.append(running)

    def at(self, t):
        i = bisect.bisect_right(self.times, t)
        return self.principal + (self.cum[i - 1] if i else 0.0)


def sweep(rows, nw):
    """Walk entry instants; return per-entry concurrent long-shot state and per-day peaks."""
    live = []            # (close_s, cost, event) of long-shot legs still at risk
    per_entry = []
    peaks = {}
    for r in rows:
        t = r["open_s"]
        live = [x for x in live if x[0] > t]
        if r["_ls"]:
            live.append((r["close_s"], r["ntl"], r["event"]))
        cost = sum(x[1] for x in live)
        worth = nw.at(t)
        pct = (cost / worth * 100.0) if worth > 0 else 0.0
        per_entry.append({"t": t, "cost": cost, "n": len(live), "pct": pct, "nw": worth,
                          "events": sorted({x[2] for x in live})})
        day = utc_day(t)
        cur = peaks.get(day)
        if cur is None or pct > cur["pct"]:
            peaks[day] = {"pct": pct, "n": len(live), "cost": cost, "nw": worth, "t": t,
                          "events": list({x[2] for x in live})}
    return per_entry, peaks


def pct_stats(vals):
    if not vals:
        return {}
    v = sorted(vals)
    n = len(v)
    med = v[n // 2] if n % 2 else (v[n // 2 - 1] + v[n // 2]) / 2.0
    return {
        "n": n,
        "median": round(med, 2),
        "p90": round(v[min(n - 1, int(n * 0.9))], 2),
        "p99": round(v[min(n - 1, int(n * 0.99))], 2),
        "max": round(v[-1], 2),
    }


def arm_concurrency(label, peaks, per_entry, out):
    pcts = [p["pct"] for p in peaks.values()]
    st = pct_stats(pcts)
    days = {"gt5": sum(1 for x in pcts if x > 5), "gt10": sum(1 for x in pcts if x > 10),
            "gt15": sum(1 for x in pcts if x > 15)}
    counts = pct_stats([p["n"] for p in per_entry])
    worst = sorted(peaks.items(), key=lambda kv: -kv[1]["pct"])[:5]
    print(f"  {label:13s} entry-days {st.get('n', 0):4d} | concurrent cost as %NW: "
          f"median {st.get('median', 0):5.2f} p90 {st.get('p90', 0):5.2f} "
          f"p99 {st.get('p99', 0):5.2f} max {st.get('max', 0):5.2f}")
    nd = max(1, st.get("n", 1))
    print(f"                entry-days >5%: {days['gt5']} ({days['gt5'] / nd * 100:.0f}%)"
          f"  >10%: {days['gt10']} ({days['gt10'] / nd * 100:.0f}%)  >15%: {days['gt15']}")
    print(f"                concurrent LEG count: median {counts.get('median', 0):.0f} "
          f"p90 {counts.get('p90', 0):.0f} max {counts.get('max', 0):.0f}")
    print("                worst days: " + " · ".join(
        f"{d} {v['pct']:.1f}% ({v['n']} legs ${v['cost']:.0f} on NW ${v['nw']:.0f})" for d, v in worst))
    out.update({"days": st, "threshold_days": days, "leg_count": counts,
                "worst_days": [{"day": d, "pct": round(v["pct"], 2), "legs": v["n"],
                                "cost": round(v["cost"], 2), "nw": round(v["nw"], 2), "distinct_events": len(v["events"])}
                               for d, v in worst]})
    cutoff = (datetime.datetime.utcnow() - datetime.timedelta(days=30)).strftime("%Y-%m-%d")
    recent = [p["pct"] for d, p in peaks.items() if d >= cutoff]
    if recent:
        rst = pct_stats(recent)
        print(f"                trailing 30d (since {cutoff}): {rst['n']} entry-days, "
              f"median {rst['median']:.2f} max {rst['max']:.2f}, "
              f"days >10%: {sum(1 for x in recent if x > 10)}")
        out["days_30d"] = rst
    return days


def arm_per_leg(label, rows, nw, out, now):
    done = [r for r in rows if r["_ls"] and r["pnl"] is not None and r["close_s"] != float("inf")]
    shares, full_loss, breaches_30, breaches_all = [], 0, [], []
    for r in done:
        worth = nw.at(r["open_s"])
        loss = max(0.0, -(r["pnl"] or 0.0))
        share = (loss / worth * 100.0) if worth > 0 else 0.0
        shares.append(share)
        if loss >= 0.999 * r["ntl"]:
            full_loss += 1
        if share > LONG_SHOT_PCT_BAR:
            rec = {"id": r["id"], "day": utc_day(r["open_s"]), "share": round(share, 2),
                   "loss": round(loss, 2), "cost": round(r["ntl"], 2),
                   "closed": utc_day(r["close_s"]), "marketId": r["marketId"]}
            breaches_all.append(rec)
            if (now - r["close_s"]) <= WINDOW_DAYS * 86400:
                breaches_30.append(rec)
    st = pct_stats(shares)
    print(f"  {label:13s} settled long-shot legs {len(done):5d} | loss as %NW: "
          f"median {st.get('median', 0):5.2f} p99 {st.get('p99', 0):5.2f} max {st.get('max', 0):5.2f}"
          f" | full-loss legs {full_loss}")
    print(f"                legs with loss > {LONG_SHOT_PCT_BAR}% of NW: all-time {len(breaches_all)}, "
          f"closed in last {WINDOW_DAYS}d {len(breaches_30)}")
    if breaches_30:
        print("                last-30d breaches: " + " · ".join(
            f"{b['day']} {b['share']:.2f}% (${b['loss']:.2f})" for b in breaches_30[:6]))
    out.update({"settled_legs": len(done), "loss_share_pct": st, "full_loss_legs": full_loss,
                "breaches_over_bar_all": breaches_all, "breaches_over_bar_30d": breaches_30})
    return len(breaches_30)


def arm_realized(label, rows, peaks, out):
    """What the peak-exposure days actually realised."""
    by_day = {}
    for r in rows:
        if not r["_ls"] or r["pnl"] is None:
            continue
        by_day.setdefault(utc_day(r["open_s"]), []).append(r)
    rows_out = []
    for day, ls in sorted(by_day.items()):
        peak = peaks.get(day)
        if not peak:
            continue
        rows_out.append({"day": day, "peak_pct": round(peak["pct"], 2),
                         "concurrent_cost": round(peak["cost"], 2), "opened": len(ls),
                         "opened_cost": round(sum(r["ntl"] for r in ls), 2),
                         "realised": round(sum(r["pnl"] or 0.0 for r in ls), 2),
                         "worst_leg": round(min((r["pnl"] or 0.0) for r in ls), 2)})
    hot = [x for x in rows_out if x["peak_pct"] > 10]
    if hot:
        print(f"  {label:13s} days with peak >10%: {len(hot)} | realised on those days "
              f"${sum(x['realised'] for x in hot):+,.2f} on ${sum(x['opened_cost'] for x in hot):,.2f} opened")
        print("                " + " · ".join(
            f"{x['day']} {x['peak_pct']:.1f}%->${x['realised']:+.0f}" for x in hot[:6]))
    else:
        print(f"  {label:13s} no day exceeded 10% -- nothing to replay")
    worst = sorted(rows_out, key=lambda x: x["realised"])[:3]
    if worst:
        print("                worst realised days (any peak): " + " · ".join(
            f"{x['day']} peak {x['peak_pct']:.1f}% -> ${x['realised']:+.0f}" for x in worst))
    out["days"] = rows_out
    out["peak_days_realised"] = hot



def arm_cap_cost(label, rows, nw, out, pcts=(10.0, 15.0, 20.0, 25.0, 30.0)):
    """Counterfactual: admit long-shot legs in order, block any that would push concurrent
    long-shot cost above pct% of net worth. A blocked leg never happens, so its realised PnL
    must NOT raise the net worth the same cap is measured against -- the pre-2026-11-09 bug that
    loosened this very rail. Same admission rule as standard-longshot-concentration.py S4."""
    print(f"  {label:13s} cost of a concurrent long-shot cap (what the rail would have BLOCKED)")
    print(f"  {'pct':>6} {'blocked':>8} {'blocked $':>11} {'realised':>10} {'net effect':>11}")
    tbl = {}
    for p in pcts:
        live, blocked = [], []
        for r in rows:
            t = r["open_s"]
            live = [x for x in live if x[0] > t]
            cost = sum(x[1] for x in live)
            lost = sum(rr["pnl"] or 0.0 for rr in blocked if rr["close_s"] <= t)
            worth = nw.at(t) - lost
            if r["_ls"] and worth > 0 and cost + r["ntl"] > p / 100.0 * worth:
                blocked.append(r)
                continue
            if r["_ls"]:
                live.append((r["close_s"], r["ntl"]))
        ntl = sum(r["ntl"] for r in blocked)
        pnl = sum(r["pnl"] or 0.0 for r in blocked)
        print(f"  {p:5.1f}% {len(blocked):8d} {ntl:11.2f} {pnl:+10.2f} {-pnl:+11.2f}")
        worstn = sorted(blocked, key=lambda r: (r["pnl"] or 0.0))[:3]
        w3 = sum(r["pnl"] or 0.0 for r in worstn)
        if blocked:
            share = (w3 / pnl * 100.0) if pnl else 0.0
            print("               worst-3 blocked legs: " + " · ".join(
                f"{(r['marketId'] or '?')[:24]} ${(r['pnl'] or 0):+.0f}" for r in worstn)
                + f"  ({share:.0f}% of blocked PnL)")
        tbl[f"{p:.1f}"] = {"blocked": len(blocked), "blocked_cost": round(ntl, 2),
                           "blocked_realised": round(pnl, 2), "net_effect": round(-pnl, 2)}
        tbl[f"{p:.1f}"]["worst3_pnl"] = round(w3, 2)
    out["cap_counterfactual"] = tbl


def self_test():
    """Synthetic fixture with hand-computable answers; the mutation arm must go RED."""
    def lag(open_s, ntl, pnl=None, close_s=None, mid="nba-okc-por-2026-11-11"):
        return {"id": f"L{open_s}", "open_s": float(open_s),
                "close_s": float(close_s) if close_s is not None else float("inf"),
                "ntl": float(ntl), "pnl": pnl, "marketId": mid, "event": event_key(mid), "_ls": True}

    rows = [lag(0, 10, -10.0, 100), lag(10, 20, -20.0, 20), lag(30, 30, None, None)]
    nw = NetWorth(rows, 100.0)
    _, peaks = sweep(rows, nw)
    per_entry, _ = sweep(rows, nw)
    # t=0: 10/100 = 10.0%; t=10: leg0(10)+leg1(20)=30 -> 30% of 100 (no close before t=10)
    assert abs(per_entry[0]["pct"] - 10.0) < 1e-9, per_entry[0]
    assert per_entry[1]["cost"] == 30 and abs(per_entry[1]["pct"] - 30.0) < 1e-9, per_entry[1]
    # t=30: leg1 (closed at 20) is gone; NW = 100 - 20 = 80; cost = 10 + 30 = 40 -> 50%
    assert per_entry[2]["cost"] == 40 and abs(per_entry[2]["pct"] - 50.0) < 1e-9, per_entry[2]
    assert len(per_entry[2]["events"]) == 1, "same-event proxy must collapse one event"
    days = arm_concurrency("selftest", peaks, per_entry, {})
    assert days["gt10"] == 1 and days["gt15"] == 1 and days["gt5"] == 1, days
    art = {}
    n30 = arm_per_leg("selftest", rows, nw, art, now=101 * 86400 + 86400 * 40)
    # leg0 loses 10 on NW 100 = 10% (closed day 0, ~40d old -> not in 30d); leg1 20% (old too)
    assert len(art["breaches_over_bar_all"]) == 2, art["breaches_over_bar_all"]
    assert n30 == 0, "both breaches must fall OUTSIDE the 30d window on this clock"
    near = [lag(1, 10, -10.0, 2)]
    nw2 = NetWorth(near, 100.0)
    art2 = {}
    assert arm_per_leg("within30", near, nw2, art2, now=20 * 86400) == 1, art2
    mut = [lag(1, 10, -0.05, 2)]
    nw3 = NetWorth(mut, 100.0)
    art3 = {}
    assert arm_per_leg("mutated", mut, nw3, art3, now=20 * 86400) == 0, "mutation must go RED"
    print("self-test: 10/10 assertions held (the 'mutated' arm above must show 0 breaches)")
    return 0


def main():
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    version, rules = active_rules(con)
    thr = float(rules.get("longshotMaxPrice", 0.20))
    br = bankrolls(con)
    now = datetime.datetime.utcnow().timestamp()
    artifact = {"generated_at": datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
                "read_window": f"2026-07-14..{datetime.datetime.utcnow().strftime('%Y-%m-%d')}",
                "ruleset_version": version, "longshot_max_price": thr,
                "bases": "isDemo=0; level=one open-position set at one entry instant; "
                         "clock=openedAt (exit closedAt??resolvedAt); at-risk=simulatedPositionSize; "
                         "NW=principal+realised PnL closed before entry; days=UTC",
                "lanes": {}}

    print("=" * 92)
    print("KELLY SINGLE-LOSS CONCENTRATION -- card kelly-single-loss-concentration-test")
    print(f"long-shot = entryPrice < {thr} (active RuleSet v{version}) | isDemo=0 | NW realised-only")
    print("=" * 92)

    print("\nA  OPEN BOOK NOW (a full loss of every open leg is the worst case)")
    for lane in LANES:
        rows = con.execute(
            "SELECT entryPrice, simulatedPositionSize AS ntl FROM PaperTrade "
            "WHERE botId=? AND status='open' AND isDemo=0 AND simulatedPositionSize>0", (lane,)
        ).fetchall()
        ls = [r for r in rows if r["entryPrice"] is not None and r["entryPrice"] < thr]
        worth = br.get(lane, {}).get("principal", 0.0) + br.get(lane, {}).get("realized", 0.0)
        ls_cost = sum(r["ntl"] for r in ls)
        print(f"  {lane:13s} open legs {len(rows):4d} cost ${sum(r['ntl'] for r in rows):9.2f} | "
              f"long-shot {len(ls):4d} ${ls_cost:9.2f} = "
              f"{(ls_cost / worth * 100) if worth else 0:5.2f}% of NW ${worth:,.2f}")
        artifact["lanes"].setdefault(lane, {})["open_book"] = {
            "open_legs": len(rows), "open_cost": round(sum(r["ntl"] for r in rows), 2),
            "longshot_legs": len(ls), "longshot_cost": round(ls_cost, 2),
            "net_worth": round(worth, 2),
            "longshot_pct_nw": round(ls_cost / worth * 100, 2) if worth else None,
        }

    for lane in LANES:
        rows = legs(con, lane)
        for r in rows:
            r["_ls"] = r["entryPrice"] is not None and r["entryPrice"] < thr
        worth = br.get(lane, {}).get("principal", 0.0) + br.get(lane, {}).get("realized", 0.0)
        nw = NetWorth(rows, br.get(lane, {}).get("principal", 0.0))
        per_entry, peaks = sweep(rows, nw)
        out = artifact["lanes"].setdefault(lane, {})
        out["net_worth_realized_only"] = round(worth, 2)
        out["legs"] = len(rows)
        print(f"\nB  CONCURRENT LONG-SHOT EXPOSURE -- {lane}  (population {len(rows)} non-demo legs)")
        days = arm_concurrency(lane, peaks, per_entry, out)
        print(f"\nC  PER-LEG LOSS AS SHARE OF NET WORTH -- {lane}")
        n30 = arm_per_leg(lane, rows, nw, out, now)
        print(f"\nD  REALIZED REPLAY -- {lane}")
        arm_realized(lane, rows, peaks, out)

        print(f"\nF  COST OF THE RAIL -- {lane}")
        arm_cap_cost(lane, rows, nw, out, pcts=(10.0, 15.0, 20.0, 25.0))
        out["rule_fired_concurrency"] = days["gt10"] >= 1
        out["rule_fired_single_leg_30d"] = n30 >= 2
        cap = float(rules.get("kellyMaxSizeUsd", 0) or 0)
        at_cap = [r for r in rows if r["_ls"] and cap and abs(r["ntl"] - cap) < 0.01]
        maxcost = max([r["ntl"] for r in rows if r["_ls"]], default=0)
        print(f"\nE  SIZE PREMISE -- long-shot legs at the ${cap:.0f} kelly cap: {len(at_cap)}; "
              f"max long-shot cost ${maxcost:.2f} = "
              f"{(maxcost / worth * 100) if worth else 0:.2f}% of NW")
        out["cap_legs"] = len(at_cap)
        out["max_longshot_cost_pct_nw"] = round(maxcost / worth * 100, 2) if worth else None

    verdict = any(v.get("rule_fired_concurrency") or v.get("rule_fired_single_leg_30d")
                  for v in artifact["lanes"].values())
    artifact["verdict"] = "FIRED -- proposal required" if verdict else "NULL -- refuted"
    print("\n" + "=" * 92)
    print(f"VERDICT: {artifact['verdict']}")
    print("=" * 92)
    os.makedirs("data", exist_ok=True)
    with open(ARTIFACT, "w") as f:
        json.dump(artifact, f, indent=2)
    print(f"artifact -> {ARTIFACT}")
    con.close()
    return 0


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        sys.exit(self_test())
    sys.exit(main())
