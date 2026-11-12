#!/usr/bin/env python3
"""
c200-fill-ordering-audit — is the C-200 settle-vs-fill-stamp ordering safe, and what does a
reconciliation pass cost?

Read-only. Opens prisma/dev.db as `mode=ro`, writes nothing, touches no bankroll or state file.
Every figure quoted in drafts/c200-fill-ordering-20261112.md comes from this script.

WHAT IT MEASURES
  §1 the invariant violation `fillStatus='unfilled' => realizedPnl=0`, re-measured at run time
  §2 WHEN those rows were stamped and how late (backfill vs live tick) — the card's defect claim
  §3 an ordering ledger per settle-week/day: stamp_first / settle_first / unstamped / class
  §4 the live stamp cadence (dispatch -> stamp lag) that sets the race window's real width
  §5 the counterfactual the ordering SAVED (legs stamped unfilled before settling)
  §6 the residual channels a stamp cannot reach (no link / no evidence / pre-instrument)
  §7 what a reconciliation pass moves on the gate: realizedPnl, cash, net worth, the drawdown
     watermark, the ladder window and the exposure cap

TIMESTAMP SEMANTICS: PaperTrade DATETIME columns are Unix milliseconds (not ISO). A leg is
SETTLED at COALESCE(resolvedAt, closedAt) — `resolved` books natural resolution, `closed` books
an early exit, and 73.9% of finished legs exit early, so both count.

USAGE
  python3 scripts/c200-fill-ordering-audit.py            # all sections
  python3 scripts/c200-fill-ordering-audit.py --json     # machine-readable tail
"""

import json
import os
import sqlite3
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DB = os.path.join(ROOT, "prisma", "dev.db")
DD_FILE = os.path.join(ROOT, "data", "c200-drawdown.json")

FLIP_MS = int(time.mktime(time.strptime("2026-10-28", "%Y-%m-%d")) * 1000)  # fill-aware default ON
INTENT_ERA_MS = int(time.mktime(time.strptime("2026-09-26", "%Y-%m-%d")) * 1000)  # first FillIntent
# The first run of the stamping resolver: every stamp in the DB is on/after this day, and 385 of
# them landed in a single apply pass over a 3-week backlog of legs that had ALREADY settled.
BACKFILL_DAY = "2026-10-28"

LINE = "-" * 96


def usd(x):
    return "-" if x is None else ("%.2f" % x)


def h(ts_ms):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts_ms / 1000.0))


def q(con, sql, args=()):
    cur = con.execute(sql, args)
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


# Every C-200 non-demo leg, with the settle timestamp derived once.
LEGS = """
  SELECT id, status, fillStatus, fillResolvedAt, openedAt, resolvedAt, closedAt,
         CASE status WHEN 'resolved' THEN resolvedAt WHEN 'closed' THEN closedAt END AS settled,
         realizedPnl, unrealizedPnl, simulatedPositionSize, entryPrice, currentPrice, decisionJournalId,
         marketId, outcome, side
  FROM PaperTrade WHERE botId='BANKROLL_200' AND isDemo=0
"""


def main():
    con = sqlite3.connect("file:%s?mode=ro" % DB, uri=True)
    con.row_factory = sqlite3.Row
    out = {}
    legs = q(con, LEGS)
    con.execute("CREATE TEMP TABLE leg AS " + LEGS)  # convenience for EXISTS joins
    intent = {}
    for r in q(con, "SELECT id, paperTradeId, decisionJournalId, marketId, outcome, side, "
                    "dispatchedAt FROM FillIntent"):
        intent[r["id"]] = r

    linked_leg = {r["paperTradeId"] for r in intent.values() if r["paperTradeId"]}
    # legs that have an intent row which never got its paperTradeId back (the link race)
    unlinked_key = {(r["decisionJournalId"], r["marketId"], r["outcome"], r["side"])
                    for r in intent.values() if not r["paperTradeId"]}

    def has_intent_key(l):
        return (l["decisionJournalId"], l["marketId"], l["outcome"], l["side"]) in unlinked_key

    print("=== c200 fill-ordering audit ===")
    print("db          : %s (mode=ro)" % DB)
    print("db mtime    : %s" % h(os.path.getmtime(DB) * 1000))
    print("as of       : %s" % h(time.time() * 1000))
    print("flip        : 2026-10-28 (fill-aware booking default ON, commit c6222f7)")
    print("resolution  : scripts/c200-fill-resolve.ts; every stamp in the DB landed on/after %s"
          % BACKFILL_DAY)

    # ---------------------------------------------------------------- §1
    cls = [l for l in legs if l["fillStatus"] == "unfilled" and l["realizedPnl"] and l["realizedPnl"] != 0]
    print("\n§1 INVARIANT VIOLATION (fillStatus='unfilled' AND realizedPnl<>0), re-measured")
    print(LINE)
    pos = [l for l in cls if l["realizedPnl"] > 0]
    neg = [l for l in cls if l["realizedPnl"] < 0]
    print("  legs                %5d    booked %+10.2f    notional %9.2f"
          % (len(cls), sum(l["realizedPnl"] for l in cls),
             sum(l["simulatedPositionSize"] for l in cls)))
    print("  winners             %5d            %+10.2f" % (len(pos), sum(l["realizedPnl"] for l in pos)))
    print("  losers              %5d            %+10.2f" % (len(neg), sum(l["realizedPnl"] for l in neg)))
    months = {}
    for l in cls:
        if l["settled"]:
            k = time.strftime("%Y-%m", time.gmtime(l["settled"] / 1000.0))
            m = months.setdefault(k, [0, 0.0])
            m[0] += 1
            m[1] += l["realizedPnl"]
    print("  settled by month    " + "  ".join("%s:%d(%+.2f)" % (k, v[0], v[1]) for k, v in sorted(months.items())))
    out["class"] = {"n": len(cls), "pnl": round(sum(l["realizedPnl"] for l in cls), 2),
                    "notional": round(sum(l["simulatedPositionSize"] for l in cls), 2),
                    "months": {k: {"n": v[0], "pnl": round(v[1], 2)} for k, v in months.items()}}

    # ---------------------------------------------------------------- §2
    print("\n§2 WHEN WAS EACH ROW STAMPED — one backfill pass, or live ticks?")
    print(LINE)
    stamps = q(con, "SELECT id, fillStatus, fillResolvedAt, realizedPnl, simulatedPositionSize, "
                    "openedAt, CASE status WHEN 'resolved' THEN resolvedAt WHEN 'closed' THEN closedAt END s "
                    "FROM PaperTrade WHERE botId='BANKROLL_200' AND isDemo=0 AND fillResolvedAt IS NOT NULL")
    by_day = {}
    for s in stamps:
        d = time.strftime("%Y-%m-%d", time.gmtime(s["fillResolvedAt"] / 1000.0))
        by_day.setdefault(d, []).append(s)
    print("  stamp day     legs   filled  unfilled   median lag from SETTLE (h)   max (h)")
    for d in sorted(by_day):
        rows = by_day[d]
        lags = sorted((r["fillResolvedAt"] - r["s"]) / 3600000.0 for r in rows if r["s"])
        med = lags[len(lags) // 2] if lags else float("nan")
        mx = lags[-1] if lags else float("nan")
        print("  %s  %5d   %6d  %8d   %24.1f  %8.1f"
              % (d, len(rows), sum(1 for r in rows if r["fillStatus"] == "filled"),
                 sum(1 for r in rows if r["fillStatus"] == "unfilled"), med, mx))
    late_cls = [l for l in cls]
    backfill = [l for l in late_cls if time.strftime("%Y-%m-%d", time.gmtime(l["fillResolvedAt"] / 1000.0)) == BACKFILL_DAY]
    live = [l for l in late_cls if time.strftime("%Y-%m-%d", time.gmtime(l["fillResolvedAt"] / 1000.0)) != BACKFILL_DAY]
    print("\n  class rows stamped on the backfill day : %4d  (%+.2f)" % (len(backfill), sum(l["realizedPnl"] for l in backfill)))
    print("  class rows stamped on a LIVE tick       : %4d  (%+.2f)" % (len(live), sum(l["realizedPnl"] for l in live)))
    for l in live:
        print("    live row  settled %s -> stamped %s   lag %5.2f h   %+.2f"
              % (h(l["settled"]), h(l["fillResolvedAt"]), (l["fillResolvedAt"] - l["settled"]) / 3600000.0,
                 l["realizedPnl"]))
    out["stamp_composition"] = {"backfill": len(backfill), "backfill_pnl": round(sum(l["realizedPnl"] for l in backfill), 2),
                                "live": len(live), "live_pnl": round(sum(l["realizedPnl"] for l in live), 2)}

    # ---------------------------------------------------------------- §3
    print("\n§3 ORDERING LEDGER — settled legs by settle WEEK (UTC), C-200 non-demo")
    print(LINE)
    print("  week        settled  stamp_first  settle_first  unstamped   class(n)  class(pnl)")
    weeks = {}
    for l in legs:
        if not l["settled"]:
            continue
        k = time.strftime("%Y-W%W", time.gmtime(l["settled"] / 1000.0))
        w = weeks.setdefault(k, {"n": 0, "sf": 0, "sxf": 0, "un": 0, "cn": 0, "cp": 0.0})
        w["n"] += 1
        if l["fillStatus"] is None:
            w["un"] += 1
        elif l["fillResolvedAt"] and l["fillResolvedAt"] <= l["settled"]:
            w["sf"] += 1
        else:
            w["sxf"] += 1
        if l["fillStatus"] == "unfilled" and l["realizedPnl"]:
            w["cn"] += 1
            w["cp"] += l["realizedPnl"]
    for k in sorted(weeks)[-8:]:
        w = weeks[k]
        print("  %s  %7d  %11d  %12d  %9d  %8d  %+9.2f" % (k, w["n"], w["sf"], w["sxf"], w["un"], w["cn"], w["cp"]))
    print("\n  daily, the flip window and after (stamp vs settle):")
    print("  date          settled  stamp_first  settle_first  unstamped   class(n)")
    days = {}
    for l in legs:
        if not l["settled"] or l["settled"] < FLIP_MS - 9 * 86400000:
            continue
        k = time.strftime("%Y-%m-%d", time.gmtime(l["settled"] / 1000.0))
        d = days.setdefault(k, {"n": 0, "sf": 0, "sxf": 0, "un": 0, "cn": 0})
        d["n"] += 1
        if l["fillStatus"] is None:
            d["un"] += 1
        elif l["fillResolvedAt"] and l["fillResolvedAt"] <= l["settled"]:
            d["sf"] += 1
        else:
            d["sxf"] += 1
        if l["fillStatus"] == "unfilled" and l["realizedPnl"]:
            d["cn"] += 1
    for k in sorted(days):
        d = days[k]
        print("  %s  %7d  %11d  %12d  %9d  %8d" % (k, d["n"], d["sf"], d["sxf"], d["un"], d["cn"]))
    out["ordering_weekly"] = {k: weeks[k] for k in sorted(weeks)}

    # ---------------------------------------------------------------- §4
    print("\n§4 LIVE STAMP CADENCE — dispatch -> stamp lag for stamps made after the backfill day")
    print(LINE)
    live_stamps = [s for s in stamps
                   if s["fillResolvedAt"] >= FLIP_MS + 86400000
                   and s["id"] in linked_leg]
    lags = []
    for s in live_stamps:
        it = next((r for r in intent.values() if r["paperTradeId"] == s["id"]), None)
        if it:
            lags.append((s["fillResolvedAt"] - it["dispatchedAt"]) / 3600000.0)
    lags.sort()
    if lags:
        print("  legs %d   dispatch->stamp: min %.1fh  median %.1fh  p90 %.1f  max %.1fh"
              % (len(lags), lags[0], lags[len(lags) // 2], lags[int(len(lags) * 0.9)], lags[-1]))
    lsf = sum(1 for s in live_stamps if s["s"] and s["fillResolvedAt"] <= s["s"])
    lsxf = sum(1 for s in live_stamps if s["s"] and s["fillResolvedAt"] > s["s"])
    lopen = sum(1 for s in live_stamps if not s["s"])
    print("  of those legs: stamp_first %d · settle_first %d · still open %d" % (lsf, lsxf, lopen))
    out["live_cadence"] = {"legs": len(lags), "median_lag_h": round(lags[len(lags) // 2], 2) if lags else None,
                           "max_lag_h": round(lags[-1], 2) if lags else None,
                           "stamp_first": lsf, "settle_first": lsxf, "open": lopen}

    # ---------------------------------------------------------------- §5
    print("\n§5 WHAT THE ORDERING SAVED — legs stamped 'unfilled' BEFORE they settled")
    print(LINE)
    saved = [l for l in legs if l["fillStatus"] == "unfilled" and (not l["realizedPnl"] or l["realizedPnl"] == 0)
             and l["settled"] and l["fillResolvedAt"] and l["fillResolvedAt"] <= l["settled"]]
    would = sum(l["simulatedPositionSize"] * ((l["currentPrice"] or 0) / l["entryPrice"] - 1) for l in saved)
    print("  legs %4d   notional %9.2f   booked 0.00   would have booked (p=1 optimistically) %+.2f"
          % (len(saved), sum(l["simulatedPositionSize"] for l in saved), would))
    out["saved"] = {"n": len(saved), "notional": round(sum(l["simulatedPositionSize"] for l in saved), 2),
                    "would_be_pnl": round(would, 2)}

    # ---------------------------------------------------------------- §6
    print("\n§6 RESIDUAL CHANNELS A STAMP CANNOT REACH")
    print(LINE)
    un = [l for l in legs if l["fillStatus"] is None]
    un_settled = [l for l in un if l["settled"]]
    def split(rows):
        r = {"linked": [x for x in rows if x["id"] in linked_leg],
             "unlinked_intent": [x for x in rows if x["id"] not in linked_leg and has_intent_key(x)],
             "no_intent": [x for x in rows if x["id"] not in linked_leg and not has_intent_key(x)]}
        return r
    for label, rows in (("ALL unstamped legs", un), ("  of which settled", un_settled),
                        ("  of which open", [l for l in un if not l["settled"]])):
        sp = split(rows)
        print("  %s: %d" % (label, len(rows)))
        for k, v in sp.items():
            print("      %-16s %5d  notional %9.2f  booked %+10.2f"
                  % (k, len(v), sum(x["simulatedPositionSize"] for x in v),
                     sum(x["realizedPnl"] or 0 for x in v)))
    era = [l for l in un_settled if l["openedAt"] >= INTENT_ERA_MS]
    print("  intent-era (opened >= 2026-09-26) unstamped settled: %d / notional %.2f / booked %+.2f"
          % (len(era), sum(l["simulatedPositionSize"] for l in era), sum(l["realizedPnl"] or 0 for l in era)))
    post = [l for l in legs if l["openedAt"] >= FLIP_MS]
    print("\n  legs OPENED since the flip, by stamp:")
    for fs in (None, "filled", "unfilled"):
        rows = [l for l in post if l["fillStatus"] == fs]
        print("      %-9s %4d  notional %9.2f  booked %+9.2f" % (fs or "(null)", len(rows),
              sum(l["simulatedPositionSize"] for l in rows), sum(l["realizedPnl"] or 0 for l in rows)))
    stamped_open = [l for l in legs if l["fillStatus"] == "unfilled" and l["status"] == "open"]
    print("  open legs stamped unfilled: %d   unrealized sum %.2f (must be 0 — the hourly mark zeroes them)"
          % (len(stamped_open), sum(l["unrealizedPnl"] or 0 for l in stamped_open)))
    out["residual"] = {
        "unstamped_settled": len(un_settled),
        "unstamped_settled_split": {k: len(v) for k, v in split(un_settled).items()},
        "intent_era_unstamped_settled": len(era),
        "intent_era_unstamped_settled_booked": round(sum(l["realizedPnl"] or 0 for l in era), 2),
        "post_flip": {str(fs): {"n": len([l for l in post if l["fillStatus"] == fs]),
                                "pnl": round(sum(l["realizedPnl"] or 0 for l in post if l["fillStatus"] == fs), 2)}
                      for fs in (None, "filled", "unfilled")},
    }

    # ---------------------------------------------------------------- §7
    print("\n§7 WHAT A RECONCILIATION PASS MOVES (option (a): re-zero every stamped-unfilled leg)")
    print(LINE)
    br = q(con, "SELECT principal, cashBalance, realizedPnl FROM BotBankroll WHERE botId='BANKROLL_200'")[0]
    open_unreal = sum(l["unrealizedPnl"] or 0 for l in legs if l["status"] == "open")
    finished = [l for l in legs if l["settled"] and l["realizedPnl"] is not None]
    rows_sum = sum(l["realizedPnl"] for l in finished)
    dd = json.load(open(DD_FILE))
    stored_peak = dd.get("realizedPeak")
    pending_filter = [l for l in legs if l["id"] not in {x["id"] for x in []}]  # no-op, keeps lint quiet
    delta = -sum(l["realizedPnl"] for l in cls)
    nw_now_realized = br["principal"] + br["realizedPnl"]
    nw_after = nw_now_realized + delta

    def hwm(rows, zero=()):
        """max of principal + cumulative realized over settle order; `zero` ids are excluded"""
        zero = set(zero)
        s = 0.0
        peak = br["principal"]
        peak_at = None
        for r in sorted(rows, key=lambda x: x["settled"]):
            if r["id"] not in zero:
                s += r["realizedPnl"]
            if br["principal"] + s > peak:
                peak = br["principal"] + s
                peak_at = r["settled"]
        return peak, peak_at

    pk_now, pk_now_at = hwm(finished)
    pk_after, pk_after_at = hwm(finished, zero=[l["id"] for l in cls])
    print("  ledger identity      : rows_sum %.2f  ==  BotBankroll.realizedPnl %.2f  (drift %+.2f)"
          % (rows_sum, br["realizedPnl"], br["realizedPnl"] - rows_sum))
    print("  principal            : %9.2f" % br["principal"])
    print("  realizedPnl          : %9.2f -> %9.2f  (%+.2f)" % (br["realizedPnl"], br["realizedPnl"] + delta, delta))
    print("  cashBalance          : %9.2f -> %9.2f  (%+.2f)" % (br["cashBalance"], br["cashBalance"] + delta, delta))
    print("  open unrealized      : %9.2f   (realized basis ignores it; MTM net worth adds it)" % open_unreal)
    print("  net worth (realized) : %9.2f -> %9.2f" % (nw_now_realized, nw_after))
    print("  recomputed HWM       : %9.2f @ %s   (standing ledger)" % (pk_now, h(pk_now_at) if pk_now_at else "-"))
    print("  recomputed HWM after : %9.2f @ %s   (class zeroed)" % (pk_after, h(pk_after_at) if pk_after_at else "-"))
    print("  stored watermark     : realizedPeak %9.2f   peak %9.2f" % (stored_peak, dd.get("peak", 0)))
    gate = 20.0
    for label, peak in (("stored 11,068.58, no rebase", stored_peak),
                        ("rebased to standing HWM", pk_now),
                        ("rebased to corrected HWM", pk_after)):
        pct = 100.0 * (peak - nw_after) / peak if peak else 0.0
        print("  DD after pass, %-26s peak %9.2f -> %6.2f%%  gate %.0f%% -> %s"
              % (label, peak, pct, gate, "TRIPPED" if pct > gate else "open"))
    pct_now = 100.0 * (stored_peak - nw_now_realized) / stored_peak
    print("  DD before the pass, stored watermark     peak %9.2f -> %6.2f%%  gate %.0f%% -> %s"
          % (stored_peak, pct_now, gate, "TRIPPED" if pct_now > gate else "open"))
    # ladder window: the class is entirely historical, so a restatement must NOT move the 7d sum
    last7 = [l for l in finished if l["settled"] >= (time.time() - 7 * 86400) * 1000]
    cls7 = [l for l in last7 if l["id"] in {x["id"] for x in cls}]
    print("  trailing-7d settled  : %d legs %+.2f   of which class legs: %d (%+.2f)"
          % (len(last7), sum(l["realizedPnl"] for l in last7), len(cls7),
             sum(l["realizedPnl"] for l in cls7)))
    base_cap = 1000.0
    for label, nw in (("now", nw_now_realized), ("after", nw_after)):
        print("  exposure cap %-5s    : %.2f  (base %.0f + 50%% x max(0, NW - principal))"
              % (label, base_cap + 0.5 * max(0.0, nw - br["principal"]), base_cap))
    out["pass"] = {"delta": round(delta, 2), "realized_after": round(br["realizedPnl"] + delta, 2),
                   "cash_after": round(br["cashBalance"] + delta, 2),
                   "nw_now": round(nw_now_realized, 2), "nw_after": round(nw_after, 2),
                   "hwm_now": round(pk_now, 2), "hwm_after": round(pk_after, 2),
                   "stored_realized_peak": stored_peak, "class_pnl_7d": round(sum(l["realizedPnl"] for l in cls7), 2)}

    print("\n§8 BOTTOM LINE")
    print(LINE)
    print("  class rows           : %d / %+.2f  (of which %d stamped on the %s backfill pass, %d on live ticks)"
          % (len(cls), sum(l["realizedPnl"] for l in cls), len(backfill), BACKFILL_DAY, len(live)))
    live_sf = [l for l in legs if l["settled"] and l["settled"] >= FLIP_MS
               and l["fillResolvedAt"] and l["fillResolvedAt"] > l["settled"]]
    print("  live settle-first    : %d event(s) since the flip — unfilled %d (%+.2f), filled %d (%+.2f)"
          % (len(live_sf),
             sum(1 for l in live_sf if l["fillStatus"] == "unfilled"),
             sum(l["realizedPnl"] or 0 for l in live_sf if l["fillStatus"] == "unfilled"),
             sum(1 for l in live_sf if l["fillStatus"] == "filled"),
             sum(l["realizedPnl"] or 0 for l in live_sf if l["fillStatus"] == "filled")))
    print("  reachable-but-unstamped: %d leg(s) linked with no verdict (evidence gap)"
          % len([l for l in un if l["id"] in linked_leg]))
    print("  unreachable (no link) : %d settled leg(s) / %+.2f booked in the intent era"
          % (len([l for l in era if l["id"] not in linked_leg and has_intent_key(l)]),
             sum(l["realizedPnl"] or 0 for l in era if l["id"] not in linked_leg and has_intent_key(l))))
    if "--json" in sys.argv:
        print("\n" + json.dumps(out, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
