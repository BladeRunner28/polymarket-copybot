#!/usr/bin/env python3
"""nearcert-mark-guard-read.py — card t_4d29ae55 (Lane A decision input, read-only).

WHAT IT ANSWERS
  The near-certainty clause's operand is `currentPrice`, the price the pipeline reads off the
  market payload. On the sub-0.05 cohort that operand is frequently 0.000. This instrument asks
  WHY, and separates the three candidate causes the card names:

    (1) a failed read (no data)              -> a tick-floor guard would fix it
    (2) a stale observation of a dead market -> a re-fetch or a TTR guard would fix it
    (3) THE WRONG TOKEN'S PRICE              -> neither of the above fixes it

GROUND TRUTH
  For a CLOSED market the venue's `outcomePrices` are the settled 0/1 per token, so the true
  price of the token we traded is knowable exactly (1.000 won / 0.000 lost) and so is the
  sibling's. A mark that equals OUR settled price is CONSISTENT; one that equals the SIBLING's
  is a label/position mismatch. Only decisions stamped AFTER `closedTime` are used for that
  test (before it, the field is a live last-trade price and can legitimately differ).

  The positional mapping under test is
     adapters/polymarket.ts:695-696   yesPrice = outcomePrices[0]; noPrice = outcomePrices[1]
     monitor-trades.ts:171 / score-trades.ts:446 / update-pnl.ts:220 / exit-recovery.ts:175
                                      outcome === "NO" ? noPrice : yesPrice
  so any label that is not literally "NO" is priced with the FIRST-listed token.

READ-ONLY on prisma/dev.db (SELECT only). Writes data/nearcert-mark-guard-read.json and the
label cache data/nearcert-market-meta.json. NOTHING in the trade path reads either.

Run: python3 scripts/nearcert-mark-guard-read.py [--days 30] [--no-fetch]
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
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if not (ROOT / "package.json").exists():  # running from outside the repo
    ROOT = Path(__file__).resolve().parent
DB = Path(os.environ.get("COPYBOT_DB", "/Users/xsnyde2/polymarket-copybot/prisma/dev.db"))
OUT = ROOT / "data" / "nearcert-mark-guard-read.json"
META = ROOT / "data" / "nearcert-market-meta.json"
OUT.parent.mkdir(parents=True, exist_ok=True)

GAMMA = "https://gamma-api.polymarket.com"
UA = {"accept": "application/json", "user-agent": "copybot-research/0.1 (paper-trading-only)"}
DAYS = 30
TICK = 0.001
SETTLE_TOL = 0.005  # a settled price is exact 0/1; 0.005 leaves room for a 0.0004 read


def nrm(v):
    return re.sub(r"[^a-z0-9]", "", str(v or "").lower())


def parse_ts(s):
    if not s:
        return None
    t = str(s).strip().replace(" ", "T", 1)
    if t.endswith("+00"):
        t = t[:-3] + "+00:00"
    try:
        return datetime.fromisoformat(t)
    except ValueError:
        return None


def fetch_market(mid):
    for attempt in range(4):
        try:
            req = urllib.request.Request(GAMMA + "/markets/slug/" + mid, headers=UA)
            with urllib.request.urlopen(req, timeout=20) as r:
                m = json.loads(r.read().decode())
            return mid, {
                "closed": m.get("closed"), "closedTime": m.get("closedTime"),
                "endDate": m.get("endDate"), "outcomePrices": m.get("outcomePrices"),
                "outcomes": m.get("outcomes"), "question": m.get("question"),
            }
        except urllib.error.HTTPError as e:
            if e.code in (429, 502, 503):
                time.sleep(1.5 * (attempt + 1))
                continue
            return mid, {"error": "HTTP %s" % e.code}
        except Exception as e:
            time.sleep(0.5 * (attempt + 1))
            if attempt == 3:
                return mid, {"error": str(e)[:100]}
    return mid, {"error": "429 exhausted"}


def main():
    argv = sys.argv[1:]
    days = int(argv[argv.index("--days") + 1]) if "--days" in argv else DAYS
    do_fetch = "--no-fetch" not in argv

    now = datetime.now(timezone.utc)
    end_ms = int(now.timestamp() * 1000)
    start_ms = end_ms - days * 86400000

    meta = json.loads(META.read_text()) if META.exists() else {}
    con = sqlite3.connect("file:%s?mode=ro" % DB, uri=True)
    con.row_factory = sqlite3.Row

    # ---------- 0. every market that reached scoring needs its labels ----------
    scored_markets = [r[0] for r in con.execute(
        """SELECT DISTINCT o.marketId FROM DecisionJournal d JOIN ObservedTrade o ON o.id = d.observedTradeId
            WHERE d.isDemo = 0 AND d.createdAt >= ? AND d.createdAt < ?""", (start_ms, end_ms))]
    todo = [m for m in scored_markets if m and m not in meta]
    print("markets that reached scoring: %d | labels cached: %d | to fetch: %d"
          % (len(scored_markets), len(meta), len(todo)), flush=True)
    if do_fetch and todo:
        with ThreadPoolExecutor(max_workers=8) as ex:
            for mid, payload in ex.map(fetch_market, todo):
                meta[mid] = payload
        META.write_text(json.dumps(meta, indent=1))
        print("  fetched %d (errors %d)" % (len(todo), sum(1 for v in meta.values() if v.get("error"))), flush=True)

    labels, settled = {}, {}
    for mid, mm in meta.items():
        try:
            labs = [str(x) for x in json.loads(mm.get("outcomes") or "[]")]
            prs = [float(x) for x in json.loads(mm.get("outcomePrices") or "[]")]
        except Exception:
            labs, prs = [], []
        labels[mid] = labs
        settled[mid] = prs if (mm.get("closed") is True and len(prs) == len(labs) and labs) else None

    def position(mid, outcome):
        labs = labels.get(mid) or []
        o = nrm(outcome)
        if o in ("yes", "no"):
            return "YES_NO"
        if len(labs) == 2:
            if o == nrm(labs[0]):
                return "FIRST_LABEL"
            if o == nrm(labs[1]):
                return "SECOND_LABEL"
            return "LABEL_NOT_IN_MARKET"
        return "NO_LABELS(%d)" % len(labs)

    def truth(mid, outcome):
        prs, labs = settled.get(mid), labels.get(mid) or []
        if prs is None or len(prs) != len(labs):
            return None, None
        o = nrm(outcome)
        for i, lab in enumerate(labs):
            if nrm(lab) == o:
                return prs[i], 1.0 - prs[i]
        return None, None

    def closed_before(mid, ts_ms):
        ct = parse_ts((meta.get(mid) or {}).get("closedTime"))
        return ct is not None and datetime.fromtimestamp(ts_ms / 1000.0, timezone.utc) > ct

    # ---------- 1. the near-certainty population -------------------------------
    rows = []
    for r in con.execute(
        """SELECT d.createdAt, d.risksJson, d.decision, o.marketId, o.outcome,
                  o.detectedPrice, o.walletEntryPrice, o.timestamp
             FROM DecisionJournal d JOIN ObservedTrade o ON o.id = d.observedTradeId
            WHERE d.isDemo = 0 AND o.isDemo = 0 AND d.createdAt >= ? AND d.createdAt < ?
              AND d.risksJson LIKE '%near certainty (%'""", (start_ms, end_ms)):
        m = re.search(r"price ([\d.]+) near certainty", r["risksJson"] or "")
        if not m:
            continue
        rows.append({"ts": int(r["createdAt"]), "p": float(m.group(1)),
                     "w": None if r["walletEntryPrice"] is None else float(r["walletEntryPrice"]),
                     "det": float(r["detectedPrice"]), "mid": r["marketId"],
                     "out": r["outcome"], "decision": r["decision"]})

    rep = {
        "card": "t_4d29ae55",
        "read_at": now.isoformat(),
        "window": {"start_utc": datetime.fromtimestamp(start_ms / 1000, timezone.utc).isoformat(),
                   "end_utc": datetime.fromtimestamp(end_ms / 1000, timezone.utc).isoformat(),
                   "days": days},
        "label_basis": "venue settled outcomePrices per TOKEN (closed markets only); "
                       "no realizedPnl, no wallet-fill proxy",
        "near_certainty_rows": len(rows),
    }

    def table(name, pop):
        by = defaultdict(lambda: Counter())
        for r in pop:
            t, s = truth(r["mid"], r["out"])
            c = position(r["mid"], r["out"])
            if t is None:
                by[c]["unsettled"] += 1
            elif abs(r["p"] - t) <= SETTLE_TOL:
                by[c]["consistent"] += 1
            elif abs(r["p"] - s) <= SETTLE_TOL:
                by[c]["sibling"] += 1
            else:
                by[c]["neither"] += 1
        print("\n" + name)
        print("  %-18s %-6s %-11s %-9s %-8s %-10s" % ("token position", "n", "consistent", "sibling", "neither", "unsettled"))
        for c, d in sorted(by.items(), key=lambda kv: -sum(kv[1].values())):
            print("  %-18s %-6d %-11d %-9d %-8d %-10d" % (c, sum(d.values()), d["consistent"],
                                                           d["sibling"], d["neither"], d["unsettled"]))
        rep.setdefault("tables", {})[name] = {c: dict(d) for c, d in by.items()}

    cheap = [r for r in rows if r["p"] < 0.05]
    rich = [r for r in rows if r["p"] > 0.95]
    strict = [r for r in rows if closed_before(r["mid"], r["ts"])]
    table("A1 all near-certainty rows, both ends", rows)
    table("A2 cheap side (mark < 0.05) - the card's cohort", cheap)
    table("A3 rich side (mark > 0.95)", rich)
    table("A1s STRICT: decisions stamped AFTER the market closed", strict)
    table("A2s STRICT cheap side", [r for r in strict if r["p"] < 0.05])
    table("A3s STRICT rich side", [r for r in strict if r["p"] > 0.95])

    sub_tick = [r for r in cheap if r["p"] < TICK]
    def tally(pop):
        c = Counter()
        for r in pop:
            t, s = truth(r["mid"], r["out"])
            if t is None:
                c["unsettled"] += 1
            elif abs(r["p"] - t) <= SETTLE_TOL:
                c["consistent"] += 1
            elif abs(r["p"] - s) <= SETTLE_TOL:
                c["sibling"] += 1
            else:
                c["neither"] += 1
        return {"n": len(pop), **dict(c)}

    rep["card_populations"] = {
        "cheap_side_rows": tally(cheap),
        "below_tick_floor_rows": tally(sub_tick),
        "below_tick_floor_all_exactly_zero": sum(1 for r in sub_tick if r["p"] == 0.0),
        "below_tick_floor_on_a_market_already_closed_at_decision":
            sum(1 for r in sub_tick if closed_before(r["mid"], r["ts"])),
    }
    print("\nA4  the card's own populations")
    for k, v in rep["card_populations"].items():
        print("  %-58s %s" % (k, v))

    # ---------- 2. how much of the pipeline reads the sibling's price ----------
    pos = Counter()
    pos_dec = Counter()
    for r in con.execute(
        """SELECT o.marketId, o.outcome, d.decision FROM DecisionJournal d
             JOIN ObservedTrade o ON o.id = d.observedTradeId
            WHERE d.isDemo = 0 AND d.createdAt >= ? AND d.createdAt < ?""", (start_ms, end_ms)):
        p = position(r[0], r[1])
        pos[p] += 1
        if p == "SECOND_LABEL":
            pos_dec[r[2]] += 1
    drift_all = drift_second = 0
    for r in con.execute(
        """SELECT o.marketId, o.outcome FROM DecisionJournal d
             JOIN ObservedTrade o ON o.id = d.observedTradeId
            WHERE d.isDemo = 0 AND d.createdAt >= ? AND d.createdAt < ? AND d.risksJson LIKE '%price drifted%'""",
        (start_ms, end_ms)):
        drift_all += 1
        if position(r[0], r[1]) == "SECOND_LABEL":
            drift_second += 1
    rep["blast_radius"] = {
        "scored_decisions_by_token_position": dict(pos.most_common()),
        "scored_decisions_on_a_second_listed_token": pos.get("SECOND_LABEL", 0),
        "second_token_decision_mix": dict(pos_dec.most_common()),
        "drift_rejections": drift_all,
        "drift_rejections_on_a_second_listed_token": drift_second,
    }
    print("\nB1  scored decisions by token position: %s" % dict(pos.most_common()))
    print("B2  decisions taken on a second-listed token: %s" % dict(pos_dec.most_common()))
    print("B3  drift rejections: %d | on a second-listed token: %d (%.1f%%)"
          % (drift_all, drift_second, 100.0 * drift_second / drift_all if drift_all else 0))

    # ---------- 3. the book those decisions produced --------------------------
    book = Counter()
    second_pnl = 0.0
    second_n = 0
    disagreements = 0
    for r in con.execute(
        """SELECT p.marketId, p.outcome, p.realizedPnl, p.status, p.botId
             FROM PaperTrade p JOIN DecisionJournal d ON d.id = p.decisionJournalId
            WHERE p.isDemo = 0 AND d.createdAt >= ? AND d.createdAt < ?""", (start_ms, end_ms)):
        p = position(r["marketId"], r["outcome"])
        book[p] += 1
        if p == "SECOND_LABEL":
            second_n += 1
            second_pnl += r["realizedPnl"] or 0
            t, _ = truth(r["marketId"], r["outcome"])
            if t is not None and r["status"] in ("closed", "resolved"):
                if ((r["realizedPnl"] or 0) > 0) != (t > 0.5):
                    disagreements += 1
    rep["book"] = {
        "legs_by_token_position": dict(book.most_common()),
        "legs_on_a_second_listed_token": second_n,
        "their_realized_pnl": round(second_pnl, 2),
        "booked_vs_venue_outcome_disagreements": disagreements,
    }
    print("\nC1  book legs by token position: %s" % dict(book.most_common()))
    print("C2  second-token legs: %d | realized PnL %.2f | booked-vs-venue disagreements %d"
          % (second_n, second_pnl, disagreements))

    # ---------- 4. what each option on the card would change ------------------
    inv_cohort = [r for r in cheap if position(r["mid"], r["out"]) == "SECOND_LABEL"]
    rep["options"] = {
        "a_no_data_guard": {
            "rows_relabelled": len(sub_tick),
            "of_those_correct_zero_reads": tally(sub_tick).get("consistent", 0),
            "of_those_inverted_reads": tally(sub_tick).get("sibling", 0),
            "admissions_changed": 0,
            "note": "the guard cannot tell a token that LOST (0.000 is its price) from a token "
                    "read upside-down (0.000 is its sibling's price)",
        },
        "b_refetch_before_scoring": {
            "rows_on_a_market_closed_at_decision": sum(1 for r in sub_tick if closed_before(r["mid"], r["ts"])),
            "rows_that_a_refetch_could_change": 0,
            "note": "a closed market's outcomePrices are frozen 0/1, and the re-fetch runs the "
                    "same three lines, so it re-reads the same slot",
        },
        "c_leave_alone": {
            "near_certainty_admissions_changed": 0,
            "note": "the clause is symmetric, so a sub-0.05 mark on a second token is a >=0.95 "
                    "market read upside-down and the same clause rejects it from the other end",
        },
        "d_label_matched_price": {
            "cohort_rows_affected": len(inv_cohort),
            "cohort_rows_still_rejected_after_repricing": sum(
                1 for r in inv_cohort if (1.0 - r["p"]) > 0.95 or (1.0 - r["p"]) < 0.05),
            "scored_decisions_repriced": pos.get("SECOND_LABEL", 0),
            "drift_rejections_whose_sign_flips": drift_second,
            "book_legs_entered_on_the_complement": second_n,
            "entry_error_rule": "booked entry is off by (1 - 2*p_true): ~0 at 0.50, ~0.8 at 0.90",
        },
    }
    print("\nE1  cohort rows on a second-listed token: %d | still rejected by the same clause "
          "once repriced to 1-p: %d"
          % (len(inv_cohort), rep["options"]["d_label_matched_price"]["cohort_rows_still_rejected_after_repricing"]))

    OUT.write_text(json.dumps(rep, indent=1))
    print("\nwrote", OUT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
