#!/usr/bin/env python3
"""closed-market-skip-taxonomy.py — card t_d246fc66 (Lane A proposal, READ-ONLY).

WHY
  The pipeline keeps scoring wallet trades observed AFTER their market resolved, then
  journals a settled price (`0.000`) through the same `price X near certainty` clause it
  uses on a live quote. The card asks WHERE the guard should live and WHAT it should say,
  and forbids the worker from deciding. This instrument supplies the before/after each
  option owes; it changes nothing.

WHAT IT MEASURES (per window, and split by decision liveness)
  * liveness: live / post-close / unknown — the SAME three-state rule as
    `decisionLiveness()` in src/lib/nearcertainty-tail.ts (closed!==true -> live;
    closed with no readable clock -> unknown, never coerced to live; else compare the
    decision's createdAt against the venue's closedTime).
  * the decision mix on post-close rows and whether any of them booked a leg
    (PaperTrade child) — the "admissions change: 0" claim, measured not quoted.
  * journal honesty: is `price ... near certainty` the row's FIRST/ONLY risk, or does
    `resolves in 0.0h < min ...` already precede it? A row whose first risk is the true
    cause is a labelling nit; a row whose ONLY risk is the near-certainty clause is the
    false claim the card names.
  * the sub-0.05 cohort impact of each option (rows leaving the population under (a),
    rows relabelled under (b)).
  * the intake-side population (a) would catch: observation-only=false ObservedTrade
    rows in the window that never got a decision at all.
  * swarm-window contamination (a) removes: share of copy-eligible observations in the
    window sitting on an already-closed market (the 1h `swarmCount` input).

READ-ONLY on prisma/dev.db (`mode=ro`). Reuses data/nearcert-market-meta.json and only
fetches markets missing from it. Writes data/closed-market-skip-taxonomy.json.

Run: python3 scripts/closed-market-skip-taxonomy.py [--no-fetch] [--fetch-cap 4000]
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import sys
import time
import urllib.error
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = Path(os.environ.get("COPYBOT_DB", str(ROOT / "prisma" / "dev.db")))
OUT = ROOT / "data" / "closed-market-skip-taxonomy.json"
META = ROOT / "data" / "nearcert-market-meta.json"
GAMMA = "https://gamma-api.polymarket.com"
UA = {"accept": "application/json", "user-agent": "copybot-research/0.1 (paper-trading-only)"}

# Anchors copied from the card / the parent read (t_4d29ae55).
FIX_CUT = datetime(2026, 11, 9, 15, 15, 16, tzinfo=timezone.utc)
POST_END = datetime(2026, 11, 12, 19, 43, 12, tzinfo=timezone.utc)
PRE_EQUAL_START = datetime(2026, 11, 6, 10, 47, 19, tzinfo=timezone.utc)
D30_START = datetime(2026, 9, 29, 21, 36, 0, tzinfo=timezone.utc)
D30_END = datetime(2026, 10, 29, 21, 36, 0, tzinfo=timezone.utc)
NEARCERT_CHEAP = 0.05
NEARCERT_RE = re.compile(r"price ([\d.]+) near certainty")
TTR_RE = re.compile(r"resolves in ([\d.]+)h")
ZERO_TTR_RE = re.compile(r"resolves in 0\.0h")


def parse_venue_clock(iso):
    """Mirror of parseVenueClock(): the venue writes `2026-10-15 21:00:00+00`.

    A space separator and a 2-digit offset are BOTH unparseable by naivety, and a
    swallowed failure silently turns every row 'live'. Explicit None on failure.

    THIRD trap, found the hard way on this card: the venue also writes FIVE-digit
    fractional seconds (`2026-11-10 19:01:58.31905+00`). JS `Date.parse` accepts
    that; Python's `datetime.fromisoformat` requires exactly 3 or 6, so an
    unnormalized clock made 295 of 5,588 rows read 'unknown' — a 5.3% silent
    false-negative that would have understated the population this card is about.
    Normalize the fraction to microseconds before parsing.
    """
    if not iso:
        return None
    s = str(iso).strip().replace(" ", "T", 1)
    s = re.sub(r"\.(\d+)", lambda m: "." + (m.group(1) + "000000")[:6], s, count=1)
    if re.search(r"[+-]\d{2}$", s):
        s += ":00"
    elif not re.search(r"([zZ]|[+-]\d{2}:\d{2})$", s):
        s += "Z"
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def decision_liveness(decided_at, closed, closed_iso):
    """Same contract as decisionLiveness(): 'live' | 'post-close' | 'unknown'."""
    if closed is not True:
        return "live"
    t = parse_venue_clock(closed_iso)
    if t is None:
        return "unknown"
    return "live" if decided_at < t else "post-close"


def fetch_market(mid):
    for attempt in range(4):
        try:
            req = urllib.request.Request(GAMMA + "/markets/slug/" + mid, headers=UA)
            with urllib.request.urlopen(req, timeout=20) as r:
                return mid, json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return mid, {"error": "404"}
            if e.code in (429, 500, 502, 503, 504):
                time.sleep(1.5 * (attempt + 1))
                continue
            return mid, {"error": str(e)[:100]}
        except Exception as e:  # noqa: BLE001
            time.sleep(1.0 * (attempt + 1))
            if attempt == 3:
                return mid, {"error": str(e)[:100]}
    return mid, {"error": "429 exhausted"}


def slim(mm):
    return {k: mm[k] for k in ("outcomes", "outcomePrices", "closed", "closedTime", "error") if k in mm}


def selftest():
    """The three assertions the TS self-test pins, plus the boundary case."""
    cases = [
        ("post-close recognised",
         decision_liveness(datetime(2026, 10, 16, tzinfo=timezone.utc), True, "2026-10-15 21:00:00+00") == "post-close"),
        ("open market is live even with no close time",
         decision_liveness(datetime.now(timezone.utc), False, None) == "live"),
        ("closed market with no clock is unknown, never live",
         decision_liveness(datetime.now(timezone.utc), True, None) == "unknown"),
        ("decided exactly at closedTime is post-close (>=)",
         decision_liveness(datetime(2026, 10, 15, 21, 0, 0, tzinfo=timezone.utc), True, "2026-10-15 21:00:00+00") == "post-close"),
        ("one second before closedTime is live",
         decision_liveness(datetime(2026, 10, 15, 20, 59, 59, tzinfo=timezone.utc), True, "2026-10-15 21:00:00+00") == "live"),
        ("5-digit fractional second parses (Date.parse does; fromisoformat does not)",
         parse_venue_clock("2026-11-10 19:01:58.31905+00") is not None),
        ("5-digit fraction still orders correctly",
         decision_liveness(datetime(2026, 11, 10, 19, 2, tzinfo=timezone.utc), True,
                           "2026-11-10 19:01:58.31905+00") == "post-close"),
    ]
    bad = [n for n, ok in cases if not ok]
    if bad:
        raise SystemExit("SELFTEST FAILED: " + "; ".join(bad))
    return [n for n, _ in cases]


def main():
    argv = sys.argv[1:]
    do_fetch = "--no-fetch" not in argv
    fetch_cap = int(argv[argv.index("--fetch-cap") + 1]) if "--fetch-cap" in argv else 4000
    now = datetime.now(timezone.utc)
    tests = selftest()

    windows = {
        "post": (FIX_CUT, POST_END),
        "post_now": (FIX_CUT, now),
        "pre_equal": (PRE_EQUAL_START, FIX_CUT),
        "d30": (D30_START, D30_END),
    }

    con = sqlite3.connect("file:%s?mode=ro" % DB, uri=True)
    con.row_factory = sqlite3.Row
    meta = json.loads(META.read_text()) if META.exists() else {}

    def ms(w):
        return int(w[0].timestamp() * 1000), int(w[1].timestamp() * 1000)

    # ---- label cache: only what the windows need, fetching only what is missing ----
    needed = set()
    for name, (s, e) in windows.items():
        s_ms, e_ms = ms((s, e))
        for r in con.execute(
            """SELECT DISTINCT o.marketId FROM DecisionJournal d
                 JOIN ObservedTrade o ON o.id = d.observedTradeId
                WHERE d.isDemo = 0 AND d.createdAt >= ? AND d.createdAt < ?""",
            (s_ms, e_ms),
        ):
            if r[0] and r[0] not in meta:
                needed.add(r[0])
    print("markets missing from label cache: %d" % len(needed), flush=True)
    fetched = errors = 0
    if do_fetch and needed:
        todo = sorted(needed)[:fetch_cap]
        with ThreadPoolExecutor(max_workers=6) as ex:
            for mid, payload in ex.map(fetch_market, todo):
                meta[mid] = payload
        fetched = len(todo)
        errors = sum(1 for m in todo if meta.get(m, {}).get("error"))
        meta = {mid: slim(mm) for mid, mm in meta.items()}
        META.write_text(json.dumps(meta, separators=(",", ":")))
        print("  fetched %d (errors %d); %d still missing"
              % (fetched, errors, len(needed) - fetched), flush=True)

    closed_flag, closed_ts = {}, {}
    for mid, mm in meta.items():
        closed_flag[mid] = mm.get("closed") is True
        closed_ts[mid] = parse_venue_clock(mm.get("closedTime"))

    def live_of(mid, ts_ms):
        if mid not in closed_flag:
            return "uncached"
        return decision_liveness(datetime.fromtimestamp(ts_ms / 1000.0, timezone.utc),
                                 closed_flag[mid], closed_ts[mid])

    report = {
        "card": "t_d246fc66",
        "lane": "A proposal — read-only, no rule/gate/size/exit touched",
        "read_at": now.isoformat(),
        "db": str(DB),
        "classifier": "decisionLiveness() semantics (src/lib/nearcertainty-tail.ts)",
        "selftest": tests,
        "windows": {},
    }

    # DecisionJournal.observedTradeId is not indexed, so a NOT EXISTS / anti-join per
    # observation row is O(obs x decisions) — it ran past 5 minutes on the 30d window.
    # One pass over the table into a set is O(n) and exact.
    decided_ids = {r[0] for r in con.execute("SELECT observedTradeId FROM DecisionJournal")}
    print("decision rows indexed: %d" % len(decided_ids), flush=True)

    for name, (s, e) in windows.items():
        s_ms, e_ms = ms((s, e))
        rows = list(con.execute(
            """SELECT d.id AS did, d.createdAt AS ts, d.decision AS decision, d.risksJson AS risks,
                      o.marketId AS mid, o.outcome AS outcome, o.detectedPrice AS det,
                      o.walletEntryPrice AS wentry, o.timestamp AS obsts, o.createdAt AS ingest
                 FROM DecisionJournal d JOIN ObservedTrade o ON o.id = d.observedTradeId
                WHERE d.isDemo = 0 AND o.isDemo = 0 AND d.createdAt >= ? AND d.createdAt < ?""",
            (s_ms, e_ms),
        ))
        legs = {r[0] for r in con.execute(
            "SELECT DISTINCT decisionJournalId FROM PaperTrade WHERE decisionJournalId IS NOT NULL")}

        w = {
            "start_utc": s.isoformat(), "end_utc": e.isoformat(),
            "days": round((e - s).total_seconds() / 86400.0, 2),
            "decisions": len(rows),
            "liveness": Counter(),
            "decision_mix": {},          # liveness -> Counter(decision)
            "legs_booked_on_post_close": 0,
            "legs_booked_on_unknown": 0,
            "post_close": {},
            "zero_ttr": {},
            "cohort": {},
            "intake": {},
        }

        nc_all = nc_cheap = 0
        nc_post = nc_cheap_post = 0
        nc_cheap_zero_post = 0
        first_risk_nc = 0
        sole_risk_nc = 0
        nc_after_ttr = 0
        det_zero = 0
        det_sum = 0.0
        det_n = 0
        ttr_zero_rows = 0
        ttr_zero_mix = Counter()
        ttr_zero_nc = 0
        ttr_zero_post = 0
        # post-close mechanism: was this a scoring-LAG race or a stale re-score?
        lag_buckets = Counter()
        lag_secs = []
        obs_lag_secs = []
        by_day = Counter()
        top_markets = Counter()
        first_risk = Counter()
        # Option coverage. (a) intake: the market was ALREADY closed when the monitor
        # fetched the payload (closedTime <= ObservedTrade.createdAt). (b) scoring: it was
        # closed when the decision was stamped. A row can be post-close on the trade's own
        # clock and still be live at ingest if the print arrives late — which is the whole
        # mechanism here (data-api prints up to 22 h old).
        closure_class = Counter()
        # unknown-clock rows: closed now, clock unreadable — an UPPER BOUND on a
        # `resolved`-based guard, never a count of post-close decisions.
        unk = {"rows": 0, "det_zero": 0, "det_sum": 0.0, "det_n": 0, "near_cert": 0,
               "cheap": 0, "legs": 0}

        for r in rows:
            lv = live_of(r["mid"], int(r["ts"]))
            w["liveness"][lv] += 1
            d = w["decision_mix"].setdefault(lv, Counter())
            d[r["decision"]] += 1
            if lv == "post-close" and r["did"] in legs:
                w["legs_booked_on_post_close"] += 1
            if lv == "unknown" and r["did"] in legs:
                w["legs_booked_on_unknown"] += 1

            risks = r["risks"] or ""
            try:
                entries = [str(x) for x in json.loads(risks)]
            except Exception:  # noqa: BLE001
                entries = []
            m = NEARCERT_RE.search(risks)
            p = float(m.group(1)) if m else None
            if p is not None:
                nc_all += 1
                if p < NEARCERT_CHEAP:
                    nc_cheap += 1
            if ZERO_TTR_RE.search(risks):
                ttr_zero_rows += 1
                ttr_zero_mix[r["decision"]] += 1
                if p is not None:
                    ttr_zero_nc += 1
                if lv == "post-close":
                    ttr_zero_post += 1

            if lv == "unknown":
                unk["rows"] += 1
                if r["det"] is not None:
                    unk["det_n"] += 1
                    unk["det_sum"] += float(r["det"])
                    if float(r["det"]) == 0.0:
                        unk["det_zero"] += 1
                if p is not None:
                    unk["near_cert"] += 1
                    if p < NEARCERT_CHEAP:
                        unk["cheap"] += 1
                if r["did"] in legs:
                    unk["legs"] += 1

            if lv != "post-close":
                continue
            # mechanism: how long after the venue closed was this decision stamped,
            # and how long after the wallet's own fill?
            ct = closed_ts.get(r["mid"])
            if ct is not None:
                lag = (int(r["ts"]) / 1000.0) - ct.timestamp()
                lag_secs.append(lag)
                for label, cap in (("<5m", 300), ("5-60m", 3600), ("1-6h", 21600), (">=6h", None)):
                    if cap is None or lag < cap:
                        lag_buckets[label] += 1
                        break
                if ct.timestamp() * 1000 <= r["ingest"]:
                    closure_class["caught_at_intake"] += 1
                else:
                    closure_class["scoring_only"] += 1
            if r["obsts"] is not None:
                obs_lag_secs.append((int(r["ts"]) - int(r["obsts"])) / 1000.0)
            by_day[datetime.fromtimestamp(int(r["ts"]) / 1000.0, timezone.utc).strftime("%Y-%m-%d")] += 1
            top_markets[r["mid"]] += 1
            if entries:
                first_risk[re.sub(r"[\d.]+", "#", entries[0])[:90]] += 1
            if p is not None:
                nc_post += 1
                if p < NEARCERT_CHEAP:
                    nc_cheap_post += 1
                    if p == 0.0:
                        nc_cheap_zero_post += 1
                idx = next((i for i, x in enumerate(entries) if "near certainty" in x), None)
                if idx == 0:
                    first_risk_nc += 1
                if len(entries) == 1 and idx == 0:
                    sole_risk_nc += 1
                if idx is not None and any("resolves in" in x for x in entries[:idx]):
                    nc_after_ttr += 1
            if r["det"] is not None:
                det_n += 1
                det_sum += float(r["det"])
                if float(r["det"]) == 0.0:
                    det_zero += 1

        w["decision_mix"] = {k: dict(v) for k, v in w["decision_mix"].items()}
        w["post_close"] = {
            "decisions": w["liveness"].get("post-close", 0),
            "share_pct": round(100.0 * w["liveness"].get("post-close", 0) / len(rows), 2) if rows else 0.0,
            "decision_mix": w["decision_mix"].get("post-close", {}),
            "near_certainty_rows": nc_post,
            "near_certainty_first_risk": first_risk_nc,
            "near_certainty_sole_risk": sole_risk_nc,
            "near_certainty_preceded_by_ttr_reason": nc_after_ttr,
            "detected_price_zero": det_zero,
            "detected_price_mean": round(det_sum / det_n, 4) if det_n else None,
            "closed_to_decision_lag_s": {
                "n": len(lag_secs),
                "median": sorted(lag_secs)[len(lag_secs) // 2] if lag_secs else None,
                "p90": sorted(lag_secs)[int(len(lag_secs) * 0.9)] if lag_secs else None,
                "buckets": dict(lag_buckets),
            },
            "observed_to_decision_lag_s": {
                "n": len(obs_lag_secs),
                "median": sorted(obs_lag_secs)[len(obs_lag_secs) // 2] if obs_lag_secs else None,
            },
            "by_day": dict(sorted(by_day.items())),
            "top_markets": dict(top_markets.most_common(5)),
            "first_risk": dict(first_risk.most_common(6)),
            "unknown_clock": {
                **{k: v for k, v in unk.items() if k not in ("det_sum", "det_n")},
                "detected_price_mean": round(unk["det_sum"] / unk["det_n"], 4) if unk["det_n"] else None,
                "note": "closed at cache time with no readable closedTime — UPPER BOUND only",
            },
            "guard_upper_bound_closed_now": w["liveness"].get("post-close", 0) + unk["rows"],
            "option_coverage": {
                "caught_at_intake": closure_class["caught_at_intake"],
                "scoring_only": closure_class["scoring_only"],
                "intake_pct": round(100.0 * closure_class["caught_at_intake"] /
                                    max(1, closure_class["caught_at_intake"] + closure_class["scoring_only"]), 1),
            },
        }
        w["zero_ttr"] = {
            "rows": ttr_zero_rows,
            "decision_mix": dict(ttr_zero_mix),
            "near_certainty_rows": ttr_zero_nc,
            "post_close_rows": ttr_zero_post,
            "live_rows": ttr_zero_rows - ttr_zero_post,
        }
        w["cohort"] = {
            "near_certainty_rows_all": nc_all,
            "near_certainty_rows_all_live_only": nc_all - nc_post,
            "cheap_lt_0_05": nc_cheap,
            "cheap_lt_0_05_live_only": nc_cheap - nc_cheap_post,
            "cheap_lt_0_05_post_close": nc_cheap_post,
            "cheap_lt_0_05_post_close_exactly_zero": nc_cheap_zero_post,
        }
        # intake-side population: copy-eligible observations that never got a decision
        # (id is selected so the anti-join runs against the preloaded set, not the DB)
        obs = list(con.execute(
            """SELECT o.id AS oid, o.marketId AS mid, o.timestamp AS ts, o.createdAt AS ingest
                 FROM ObservedTrade o
                WHERE o.isDemo = 0 AND o.observationOnly = 0
                  AND o.timestamp >= ? AND o.timestamp < ?""",
            (s_ms, e_ms),
        ))
        obs_lv = Counter(live_of(r["mid"], int(r["ts"])) for r in obs)
        obs_lv_ingest = Counter(live_of(r["mid"], int(r["ingest"])) for r in obs)
        unr = [r for r in obs if r["oid"] not in decided_ids]
        unr_lv = Counter(live_of(r["mid"], int(r["ingest"])) for r in unr)
        w["intake"] = {
            "copy_eligible_observations": len(obs),
            "liveness_at_trade_clock": dict(obs_lv),
            "liveness_at_ingest_clock": dict(obs_lv_ingest),
            "closed_at_ingest_pct": round(100.0 * obs_lv_ingest.get("post-close", 0) / len(obs), 2) if obs else 0.0,
            "unscored_observations": len(unr),
            "unscored_liveness_at_ingest": dict(unr_lv),
            "uncached_market_rows": w["liveness"].get("uncached", 0),
        }
        report["windows"][name] = w

        pc = w["post_close"]
        print("\n== %s  %s .. %s  (%.2fd)" % (name, s.date(), e.date(), w["days"]))
        print("   decisions %-6d liveness %s" % (len(rows), dict(w["liveness"])))
        print("   post-close decisions %d (%.2f%%) mix %s | legs booked %d"
              % (pc["decisions"], pc["share_pct"], pc["decision_mix"], w["legs_booked_on_post_close"]))
        print("   post-close near-cert rows %d (first risk %d, SOLE risk %d, after a ttr reason %d)"
              % (pc["near_certainty_rows"], pc["near_certainty_first_risk"],
                 pc["near_certainty_sole_risk"], pc["near_certainty_preceded_by_ttr_reason"]))
        print("   post-close lag after closedTime: %s median %ss | first risk: %s"
              % (pc["closed_to_decision_lag_s"]["buckets"], pc["closed_to_decision_lag_s"]["median"],
                 list(pc["first_risk"].items())[:2]))
        print("   post-close by day %s | top markets %s"
              % (pc["by_day"], list(pc["top_markets"].items())[:3]))
        print("   unknown-clock rows %d (cheap %d, det=0 %d, legs %d) -> resolved-guard upper bound %d"
              % (pc["unknown_clock"]["rows"], pc["unknown_clock"]["cheap"],
                 pc["unknown_clock"]["det_zero"], pc["unknown_clock"]["legs"],
                 pc["guard_upper_bound_closed_now"]))
        print("   cheap<0.05 cohort %d -> live-only %d (post-close %d, of which exactly 0.000: %d)"
              % (w["cohort"]["cheap_lt_0_05"], w["cohort"]["cheap_lt_0_05_live_only"],
                 nc_cheap_post, nc_cheap_zero_post))
        print("   'resolves in 0.0h' rows %d mix %s" % (ttr_zero_rows, dict(ttr_zero_mix)))
        print("   option coverage %s (a=intake, b=scoring)"
              % pc["option_coverage"])
        print("   intake: %d copy-eligible obs; closed at TRADE clock %d, at INGEST clock %d (%s)"
              % (len(obs), obs_lv.get("post-close", 0), obs_lv_ingest.get("post-close", 0),
                 w["intake"]["liveness_at_ingest_clock"]))

    OUT.write_text(json.dumps(report, indent=1))
    print("\nwrote %s" % OUT)


if __name__ == "__main__":
    main()
