#!/usr/bin/env python3
"""wallet-17dd-cohort-read.py — card t_6d17488d, Lane-B read-only measurement.

WHY
  Wallet 0x17dd123a… was first journaled 2026-11-06 15:40:10Z and produced 6,639 decisions in six
  days (4,073 of them carrying the journal's `price X near certainty` risk). The near-certainty
  population went ~50/day -> ~650/day on 2026-11-06, three days before the price-side fix
  (fbf9073), so the jump is the wallet, not the operand fix. This instrument answers the card:
  why the wallet entered the copy universe, on what score basis, how concentrated its flow is,
  what its own settled record says, what its 58 admitted legs did, and what the near-certainty
  cohort looks like with it excluded.

WHAT IT MEASURES
  1. Seat & basis      — WalletProfile row, rank in the 25-seat copy set, the observationOnly
                         flip that admitted it, and a reproduction of the stored roi30d /
                         globalScore from the adapter's own TAIL SAMPLE (50 best + 50 worst
                         closed positions by realized PnL + 100 open) against the FULL venue
                         position record.
  2. Concentration     — decisions per day / per market, repeat re-observations of one
                         (market, outcome) key, inter-arrival, mark distribution.
  3. Quality           — the venue's own settlement: full position walk (cost reconstructed as
                         total_size x avg_price — `total_cost_usdc` is unusable on this feed),
                         ROI + win rate with a market-clustered bootstrap CI, by entry-price band
                         and by entry vintage; the tracked set measured on the same basis.
  4. The 58 legs       — every PaperTrade row the wallet produced, by lane/fill status, plus the
                         price of removing the near-certainty clause (sole-blocker ceiling and
                         the settled-outcome ROI of the legs it alone keeps out).
  5. Cohort without it — near-certainty decisions per day, mark mix and decision mix, with and
                         without this wallet.
  6. Verdict           — the card's PRE-REGISTERED bar, evaluated as written.

READ-ONLY on prisma/dev.db (SELECT only). Keyless venue reads only (data-api v2 positions,
cached in data/). Writes data/wallet-17dd-cohort-read.json.

Run: python3 scripts/wallet-17dd-cohort-read.py [--fetch-venue] [--boot 4000]
     (--fetch-venue walks the venue; without it the cached walks in data/ are used)
"""
from __future__ import annotations

import json
import os
import random
import re
import sqlite3
import sys
import time
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if not (ROOT / "package.json").exists():
    ROOT = Path(__file__).resolve().parent
DB = Path(os.environ.get("COPYBOT_DB", str(ROOT / "prisma" / "dev.db")))
META = ROOT / "data" / "nearcert-market-meta.json"
OUT = ROOT / "data" / "wallet-17dd-cohort-read.json"
POS_SUBJECT = ROOT / "data" / "wallet-17dd-positions.json"
POS_TRACKED = ROOT / "data" / "wallet-tracked-positions.json"

W = "0x17dd123a0ad9675e6ed3155724a92b4632af944c"
DATA_API = "https://data-api.polymarket.com"
UA = {"accept": "application/json", "user-agent": "copybot-research/0.1 (paper-trading-only)"}
SETTLE_TOL = 0.005
# first journaled decision for this wallet (card fact), used as the flood cut
FLOOD_CUT = datetime(2026, 11, 6, 15, 40, 10, tzinfo=timezone.utc)
MAX_TRACKED = 25


# ---------------------------------------------------------------- helpers
def nrm(v):
    return re.sub(r"[^a-z0-9]", "", str(v or "").lower())


def day(ms):
    return datetime.fromtimestamp(ms / 1000.0, timezone.utc).strftime("%Y-%m-%d")


def iso(ms):
    if ms is None:
        return None
    return datetime.fromtimestamp(ms / 1000.0, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def pct(x, nd=1):
    if x is None:
        return "n/a"
    return ("%+." + str(nd) + "f%%") % (x * 100)


def get_json(url, tries=5):
    for a in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
                return json.loads(r.read().decode())
        except Exception:  # noqa: BLE001
            if a == tries - 1:
                return None
            time.sleep(1.5 * (a + 1))
    return None


def walk_positions(wallet, status, max_pages=800):
    """Full v2 position walk, cursor-paged. Returns (rows, pages, end_reason)."""
    cur, out, pages, seen = None, [], 0, set()
    while pages < max_pages:
        url = (
            "%s/v2/positions?user=%s&status=%s&limit=50&sort_by=REALIZED_PNL&sort_direction=DESC"
            % (DATA_API, wallet, status)
        )
        if cur:
            url += "&cursor=" + urllib.parse.quote(cur)
        j = get_json(url)
        if j is None:
            return out, pages, "error"
        rows = (j or {}).get("data") or []
        for r in rows:
            k = r.get("token_id")
            if k in seen:
                continue
            seen.add(k)
            out.append(r)
        cur = ((j or {}).get("pagination") or {}).get("next_cursor")
        pages += 1
        if not cur or not rows:
            return out, pages, "done"
        time.sleep(0.08)
    return out, pages, "capped"


def pos_cost(r):
    """Cost basis. `total_cost_usdc` is zero on 28,083 of this wallet's 31,991 closed positions
    (a venue field defect), and `percent_realized_pnl` reproduces exactly as realized_pnl /
    (total_size x avg_price), which is the basis the venue itself uses."""
    return float(r.get("total_size") or 0) * float(r.get("avg_price") or 0)


def pos_pnl(r):
    return float(r.get("realized_pnl") or 0)


def band_of(p):
    """Entry-price band for a leg or position. Kept at module scope: both the venue record and
    the settled-outcome arms split on it."""
    for lo, hi in [(0, 0.05), (0.05, 0.20), (0.20, 0.40), (0.40, 0.60), (0.60, 0.80),
                   (0.80, 0.95), (0.95, 1.01)]:
        if lo <= p < hi:
            return "%.2f-%.2f" % (lo, hi)
    return "other"


def cluster_boot(clusters, n_boot=4000, seed=17):
    """ROI = sum(pnl)/sum(cost), resampling whole CLUSTERS (markets) with replacement.
    Returns (lo, hi) at 95%."""
    keys = list(clusters)
    if not keys:
        return None, None
    rng = random.Random(seed)
    out = []
    for _ in range(n_boot):
        p = c = 0.0
        for _ in range(len(keys)):
            k = keys[rng.randrange(len(keys))]
            p += clusters[k][0]
            c += clusters[k][1]
        if c > 0:
            out.append(p / c)
    if not out:
        return None, None
    out.sort()
    return out[int(0.025 * len(out))], out[int(0.975 * len(out)) - 1]


def roi_arm(legs):
    """legs: list of (cluster_key, cost, pnl)."""
    cost = sum(x[1] for x in legs)
    pnl = sum(x[2] for x in legs)
    cl = defaultdict(lambda: [0.0, 0.0])
    for k, c, p in legs:
        cl[k][0] += p
        cl[k][1] += c
    lo, hi = cluster_boot(cl)
    wins = sum(1 for x in legs if x[2] > 0)
    return {
        "n_legs": len(legs),
        "n_clusters": len(cl),
        "cost": round(cost, 2),
        "pnl": round(pnl, 2),
        "roi": (pnl / cost) if cost else None,
        "roi_ci": [lo, hi],
        "win_rate": (wins / len(legs)) if legs else None,
    }


# ---------------------------------------------------------------- settlement
def load_settlements():
    """(marketId) -> {label_norm: settled_price} for markets the venue has settled 0/1."""
    meta = json.loads(META.read_text()) if META.exists() else {}
    settled = {}
    for mid, mm in meta.items():
        if mm.get("closed") is not True:
            continue
        try:
            labs = [str(x) for x in json.loads(mm.get("outcomes") or "[]")]
            prs = [float(x) for x in json.loads(mm.get("outcomePrices") or "[]")]
        except Exception:  # noqa: BLE001
            continue
        if not labs or len(labs) != len(prs):
            continue
        d = {}
        for lab, pr in zip(labs, prs):
            if abs(pr - round(pr)) > SETTLE_TOL:  # not a terminal 0/1 mark
                continue
            d[nrm(lab)] = round(pr)
        if d:
            settled[mid] = d
    return settled


def settled_price(settled, market_id, outcome):
    d = settled.get(market_id)
    if not d:
        return None
    o = nrm(outcome)
    if o in d:
        return d[o]
    return None


# ---------------------------------------------------------------- main
def main():
    argv = sys.argv[1:]
    fetch_venue = "--fetch-venue" in argv
    n_boot = int(argv[argv.index("--boot") + 1]) if "--boot" in argv else 4000

    con = sqlite3.connect("file:%s?mode=ro" % DB, uri=True)
    con.row_factory = sqlite3.Row

    # ---------- S1 seat & basis
    wp = con.execute("SELECT * FROM WalletProfile WHERE address=?", (W,)).fetchone()
    if wp is None:
        raise SystemExit("wallet row missing")
    wp = dict(wp)
    track = con.execute(
        "SELECT address, globalScore FROM WalletProfile WHERE status='track' AND isDemo=0 "
        "ORDER BY globalScore DESC, address ASC LIMIT ?", (MAX_TRACKED,)).fetchall()
    rank = [i + 1 for i, r in enumerate(track) if r["address"] == W]
    rules = json.loads(con.execute(
        "SELECT rulesJson FROM RuleSet WHERE active=1 ORDER BY version DESC LIMIT 1").fetchone()[0])

    first_dec = con.execute(
        "SELECT MIN(createdAt) m FROM DecisionJournal WHERE walletAddress=?", (W,)).fetchone()["m"]
    first_obs = con.execute(
        "SELECT MIN(timestamp) m FROM ObservedTrade WHERE walletAddress=?", (W,)).fetchone()["m"]
    first_copy_eligible = con.execute(
        "SELECT MIN(timestamp) m FROM ObservedTrade WHERE walletAddress=? AND observationOnly=0",
        (W,)).fetchone()["m"]
    obs_before = con.execute(
        "SELECT COUNT(*) c FROM ObservedTrade WHERE walletAddress=? AND timestamp<?",
        (W, first_dec)).fetchone()["c"]
    obs_before_copyable = con.execute(
        "SELECT COUNT(*) c FROM ObservedTrade WHERE walletAddress=? AND timestamp<? AND observationOnly=0",
        (W, first_dec)).fetchone()["c"]

    # ---------- venue walks
    venue = {"subject": None, "tracked": [], "fetched": False}
    if fetch_venue:
        refetch_subject = "--refetch-subject" in argv
        if POS_SUBJECT.exists() and not refetch_subject:
            print("  subject walk cache present — keeping it (--refetch-subject to redo)", flush=True)
        else:
            c_rows, c_pages, c_end = walk_positions(W, "CLOSED")
            o_rows, o_pages, o_end = walk_positions(W, "OPEN")
            POS_SUBJECT.write_text(json.dumps({"closed": c_rows, "open": o_rows,
                                               "closed_pages": c_pages, "closed_end": c_end,
                                               "open_pages": o_pages, "open_end": o_end}))
        tracked = []
        have_tracked = POS_TRACKED.exists() and "--refetch-tracked" not in argv
        if have_tracked:
            print("  tracked walk cache present — keeping it (--refetch-tracked to redo)", flush=True)
            venue["fetched"] = True
        else:
            for r in track:
                if r["address"] == W:
                    continue
                rows, pages, end = walk_positions(r["address"], "CLOSED", max_pages=260)
                rows30 = [x for x in rows
                          if float(x.get("first_entry_at") or 0) >= (time.time() - 30 * 86400)]
                tracked.append({
                    "address": r["address"],
                    "globalScore": r["globalScore"],
                    "pages": pages,
                    "end": end,
                    "n_positions": len(rows),
                    "cost": round(sum(pos_cost(x) for x in rows), 2),
                    "pnl": round(sum(pos_pnl(x) for x in rows), 2),
                    "win_rate": (sum(1 for x in rows if pos_pnl(x) > 0) / len(rows)) if rows else None,
                    "n_positions_30d": len(rows30),
                    "cost_30d": round(sum(pos_cost(x) for x in rows30), 2),
                    "pnl_30d": round(sum(pos_pnl(x) for x in rows30), 2),
                })
                print("  walked %s pages %d (%s)" % (r["address"][:10], pages, end), flush=True)
            POS_TRACKED.write_text(json.dumps(tracked))
            venue["fetched"] = True
    closed = []
    opened = []
    if POS_SUBJECT.exists():
        sub = json.loads(POS_SUBJECT.read_text())
        if "fields" in sub:  # compact cache form: parallel arrays
            flds = sub["fields"]

            def _rows(arr):
                return [dict(zip(flds, r)) for r in arr]

            closed = _rows(sub["closed"])
            opened = _rows(sub.get("open") or [])
        else:
            closed = sub["closed"]
            opened = sub.get("open") or []
        venue["subject"] = {
            "n_closed": len(closed),
            "n_open": len(opened),
            "closed_pages": sub.get("closed_pages"),
            "walk_end": sub.get("closed_end"),
        }
    if POS_TRACKED.exists():
        venue["tracked"] = json.loads(POS_TRACKED.read_text())
    if not POS_SUBJECT.exists():
        raise SystemExit("no venue walk cache; run with --fetch-venue")

    # ---------- S2 decision stream
    rows = con.execute(
        """SELECT d.id, d.createdAt, d.decision, d.copyScore, d.confidence, d.risksJson,
                  d.reasonsJson, d.simulatedPositionSize, d.ruleSetVersion,
                  o.marketId, o.conditionId, o.marketQuestion, o.outcome, o.detectedPrice,
                  o.walletEntryPrice, o.size, o.timestamp, o.marketCategory
             FROM DecisionJournal d JOIN ObservedTrade o ON o.id=d.observedTradeId
            WHERE d.isDemo=0 AND d.walletAddress=? ORDER BY d.createdAt""", (W,)).fetchall()
    rows = [dict(r) for r in rows]
    for r in rows:
        r["near_cert"] = "near certainty" in (r["risksJson"] or "")
        try:
            r["risks"] = json.loads(r["risksJson"] or "[]")
        except Exception:  # noqa: BLE001
            r["risks"] = []

    per_day = defaultdict(lambda: {"decisions": 0, "markets": set(), "near": 0, "copies": 0,
                                   "keys": set()})
    for r in rows:
        d = day(r["createdAt"])
        b = per_day[d]
        b["decisions"] += 1
        b["markets"].add(r["marketId"])
        b["keys"].add((r["marketId"], r["outcome"]))
        if r["near_cert"]:
            b["near"] += 1
        if r["decision"] == "paper_copy":
            b["copies"] += 1

    key_rows = Counter((r["marketId"], r["outcome"]) for r in rows)
    repeat = [(k, c) for k, c in key_rows.items() if c > 1]
    # inter-arrival on repeated keys
    by_key = defaultdict(list)
    for r in rows:
        by_key[(r["marketId"], r["outcome"])].append(r["createdAt"])
    gaps = []
    for k, ts in by_key.items():
        if len(ts) > 1:
            ts = sorted(ts)
            gaps.extend([(ts[i + 1] - ts[i]) / 1000.0 for i in range(len(ts) - 1)])

    def price_bin(p):
        if p is None:
            return "none"
        if p <= 0.05:
            return "<=0.05"
        if p < 0.20:
            return "0.05-0.20"
        if p < 0.40:
            return "0.20-0.40"
        if p < 0.60:
            return "0.40-0.60"
        if p < 0.80:
            return "0.60-0.80"
        if p < 0.95:
            return "0.80-0.95"
        return ">=0.95"

    marks = Counter(price_bin(r["detectedPrice"]) for r in rows)
    marks_near = Counter(price_bin(r["detectedPrice"]) for r in rows if r["near_cert"])

    # ---------- S3 settled-outcome arms for the decisions
    settled = load_settlements()

    def arm_for(sel, price_field, label):
        legs, unpriced, priced_rows = [], 0, 0
        keyed = defaultdict(lambda: [0.0, 0.0, 0.0])  # key -> shares, cost, payout
        for r in sel:
            sp = settled_price(settled, r["marketId"], r["outcome"])
            px = r[price_field]
            if sp is None or px is None or px <= 0:
                unpriced += 1
                continue
            priced_rows += 1
            shares = float(r["size"] or 0)
            keyed[(r["conditionId"], r["marketId"], r["outcome"])][0] += shares
            keyed[(r["conditionId"], r["marketId"], r["outcome"])][1] += shares * px
            keyed[(r["conditionId"], r["marketId"], r["outcome"])][2] += shares * sp
        for k, (sh, cost, payout) in keyed.items():
            if cost <= 0:
                continue
            legs.append((k[0] or k[1], cost, payout - cost, sh))
        res = roi_arm([(k, c, p) for k, c, p, _ in legs])
        # concentration: a dust-heavy stream can make a cluster CI look tighter than the
        # economic exposure is — quote the share of cost the biggest legs carry.
        costs = sorted((x[1] for x in legs), reverse=True)
        pnls = sorted((x[2] for x in legs), reverse=True)
        tot_c = sum(costs)
        tot_p = sum(pnls)
        res["cost_top10_share"] = (sum(costs[:10]) / tot_c) if tot_c else None
        res["pnl_top10_share"] = (sum(pnls[:10]) / tot_p) if tot_p else None
        res["legs_cost_ge_10usd"] = sum(1 for c in costs if c >= 10)
        # band split by the leg's own average entry price
        bands = defaultdict(lambda: [0.0, 0.0, 0, 0])
        for k, c, p, sh in legs:
            b = band_of(c / sh) if sh else "?"
            bands[b][0] += c
            bands[b][1] += p
            bands[b][2] += 1
            if p > 0:
                bands[b][3] += 1
        res["by_entry_band"] = {
            b: {"legs": v[2], "cost": round(v[0], 2), "pnl": round(v[1], 2),
                "roi": (v[1] / v[0]) if v[0] else None, "win_rate": v[3] / v[2] if v[2] else None}
            for b, v in sorted(bands.items())}
        res["label"] = label
        res["rows"] = len(sel)
        res["rows_priceable"] = priced_rows
        res["rows_unpriceable"] = unpriced
        res["price_field"] = price_field
        return res

    flood = [r for r in rows if r["createdAt"] >= int(FLOOD_CUT.timestamp() * 1000)]
    near = [r for r in rows if r["near_cert"]]
    near_sole = [r for r in near if len(r["risks"]) == 1]

    quality = {
        "flood_window_at_detected": arm_for(flood, "detectedPrice", "flood rows, copier entry = detected mid"),
        "flood_window_at_wallet": arm_for(flood, "walletEntryPrice", "flood rows, entry = wallet's own price"),
        "near_cert_at_detected": arm_for(near, "detectedPrice", "near-certainty rows, copier entry = detected mid"),
        "near_cert_sole_blocker_at_detected": arm_for(
            near_sole, "detectedPrice", "near-certainty rows where the clause is the ONLY blocker"),
        "all_rows_at_detected": arm_for(rows, "detectedPrice", "all of this wallet's journaled rows"),
    }

    # ---------- venue record (subject)
    def venue_block(rs):
        cost = sum(pos_cost(x) for x in rs)
        pnl = sum(pos_pnl(x) for x in rs)
        wins = sum(1 for x in rs if pos_pnl(x) > 0)
        cl = defaultdict(lambda: [0.0, 0.0])
        for x in rs:
            k = x.get("condition_id") or x.get("token_id")
            cl[k][0] += pos_pnl(x)
            cl[k][1] += pos_cost(x)
        lo, hi = cluster_boot(cl, n_boot=n_boot)
        return {"n": len(rs), "cost": round(cost, 2), "pnl": round(pnl, 2),
                "roi": (pnl / cost) if cost else None, "roi_ci": [lo, hi],
                "win_rate": (wins / len(rs)) if rs else None}

    v_bands = defaultdict(list)
    for x in closed:
        v_bands[band_of(float(x.get("avg_price") or 0))].append(x)
    flood_ms = FLOOD_CUT.timestamp()
    venue_subject = {
        "all": venue_block(closed),
        "by_entry_band": {b: venue_block(v) for b, v in sorted(v_bands.items())},
        "vintage": {
            "first_entry_before_flood": venue_block(
                [x for x in closed if float(x.get("first_entry_at") or 0) < flood_ms]),
            "first_entry_after_flood": venue_block(
                [x for x in closed if float(x.get("first_entry_at") or 0) >= flood_ms]),
        },
    }

    # tail-sample reproduction (the adapter's profiling read)
    cs = sorted(closed, key=pos_pnl, reverse=True)
    tail = cs[:50] + cs[-50:]
    open_sorted = sorted(opened, key=lambda r: float(r.get("current_value") or 0), reverse=True)[:100]
    tail_cost = sum(pos_cost(x) for x in tail)
    tail_pnl = sum(pos_pnl(x) for x in tail)
    full_cost = sum(pos_cost(x) for x in closed)
    full_pnl = sum(pos_pnl(x) for x in closed)
    roi_score = min(100.0, max(0.0, 40 + (tail_pnl / tail_cost if tail_cost else 0) * 90)) \
        if tail_cost else 0.0
    seat = {
        "stored": {k: wp[k] for k in ("sourceRank", "status", "roi30d", "consistencyScore",
                                      "copyabilityScore", "oneHitWonderPenalty", "globalScore",
                                      "winRate30d", "tradeCount30d", "resolvedTradeCount30d",
                                      "averageTradeSize", "bestCategory")},
        "created_at": iso(wp.get("createdAt")),
        "last_scanned_at": iso(wp.get("lastScannedAt")),
        "seat_rank_in_copy_set": rank[0] if rank else None,
        "copy_set_size": len(track),
        "margin_to_last_seat": (round(track[-1]["globalScore"], 1) if track else None),
        "recomputed_globalScore": round(
            roi_score * rules["weightRoi"] + wp["consistencyScore"] * rules["weightConsistency"]
            + wp["copyabilityScore"] * rules["weightCopyability"], 1),
        "roi_score_component": round(roi_score, 1),
        "roi_score_saturated": roi_score >= 100,
        "tail_sample": {
            "rows": len(tail),
            "open_rows_sampled": len(open_sorted),
            "cost": round(tail_cost, 2),
            "pnl": round(tail_pnl, 2),
            "roi": (tail_pnl / tail_cost) if tail_cost else None,
            "win_rate": sum(1 for x in tail if pos_pnl(x) > 0) / len(tail) if tail else None,
        },
        "full_record": {"positions": len(closed), "cost": round(full_cost, 2),
                        "pnl": round(full_pnl, 2),
                        "roi": (full_pnl / full_cost) if full_cost else None,
                        "win_rate": sum(1 for x in closed if pos_pnl(x) > 0) / len(closed)},
        "observed_trades_first": iso(first_obs),
        "first_journaled_decision": iso(first_dec),
        "first_copy_eligible_observation": iso(first_copy_eligible),
        "observations_before_first_journal": obs_before,
        "copy_eligible_observations_before_first_journal": obs_before_copyable,
        "days_observed_before_first_journal": (
            (first_dec - first_obs) / 86400000.0 if (first_obs and first_dec) else None),
    }

    # tracked-set venue comparison
    trk = []
    for t in venue["tracked"]:
        trk.append({"address": t["address"], "globalScore": t["globalScore"],
                    "n_positions": t["n_positions"], "cost": t["cost"], "pnl": t["pnl"],
                    "roi": (t["pnl"] / t["cost"]) if t["cost"] else None,
                    "win_rate": t["win_rate"], "walk": t["end"], "pages": t["pages"]})
    trk.sort(key=lambda x: x["roi"] or -9)
    tracked_summary = {
        "n_wallets_walked": len(trk),
        "roi_min": trk[0]["roi"] if trk else None,
        "roi_median": (sorted([x["roi"] for x in trk if x["roi"] is not None])[len(trk) // 2]
                       if trk else None),
        "roi_max": trk[-1]["roi"] if trk else None,
        # rank counting from the WORST ROI up: 1 = this wallet has the lowest venue ROI of the set
        "wallet_roi_rank_worst_first": (
            1 + sum(1 for x in trk if (x["roi"] or -9) < (venue_subject["all"]["roi"] or -9)))
        if trk else None,
        "wallet_n_positions_vs_median": (
            venue_subject["all"]["n"] / sorted(x["n_positions"] for x in trk)[len(trk) // 2])
        if trk else None,
        "rows": trk,
    }

    # ---------- what a tracking change would move (the priced delta)
    flood_ms0 = int(FLOOD_CUT.timestamp() * 1000)
    win_copies = con.execute(
        """SELECT COUNT(*) c FROM DecisionJournal WHERE isDemo=0 AND decision='paper_copy'
            AND createdAt>=?""", (flood_ms0,)).fetchone()["c"]
    win_copies_w = con.execute(
        """SELECT COUNT(*) c FROM DecisionJournal WHERE isDemo=0 AND decision='paper_copy'
            AND createdAt>=? AND walletAddress=?""", (flood_ms0, W)).fetchone()["c"]
    win_dec = con.execute(
        "SELECT COUNT(*) c FROM DecisionJournal WHERE isDemo=0 AND createdAt>=?",
        (flood_ms0,)).fetchone()["c"]
    win_nc = con.execute(
        """SELECT COUNT(*) c FROM DecisionJournal WHERE isDemo=0 AND createdAt>=?
            AND risksJson LIKE '%near certainty%'""", (flood_ms0,)).fetchone()["c"]
    delta = {
        "window": "2026-11-06 -> now",
        "decisions_all": win_dec,
        "decisions_wallet": len(rows),
        "decision_share": (len(rows) / win_dec) if win_dec else None,
        "near_cert_decisions_all": win_nc,
        "near_cert_decisions_wallet": len(near),
        "near_cert_share": (len(near) / win_nc) if win_nc else None,
        "paper_copy_all": win_copies,
        "paper_copy_wallet": win_copies_w,
        "paper_copy_share": (win_copies_w / win_copies) if win_copies else None,
    }

    # ---------- S4 the admitted legs
    legs = con.execute(
        """SELECT p.id, p.botId, p.status, p.entryPrice, p.intentPrice, p.fillStatus, p.fillBasis,
                  p.simulatedPositionSize, p.realizedPnl, p.openedAt, p.closedAt, p.resolvedAt,
                  d.decision, d.risksJson, o.marketId, o.outcome
             FROM PaperTrade p JOIN DecisionJournal d ON d.id=p.decisionJournalId
             JOIN ObservedTrade o ON o.id=d.observedTradeId
            WHERE d.walletAddress=? ORDER BY p.openedAt""", (W,)).fetchall()
    legs = [dict(x) for x in legs]
    by_status = defaultdict(lambda: {"n": 0, "size": 0.0, "pnl": 0.0, "wins": 0})
    for x in legs:
        k = "%s/%s/%s" % (x["botId"], x["status"], x["fillStatus"] or "unstamped")
        b = by_status[k]
        b["n"] += 1
        b["size"] += float(x["simulatedPositionSize"] or 0)
        b["pnl"] += float(x["realizedPnl"] or 0)
        if (x["realizedPnl"] or 0) > 0:
            b["wins"] += 1
    filled = [x for x in legs if x["fillStatus"] == "filled"]
    unfilled = [x for x in legs if x["fillStatus"] == "unfilled"]
    legs_summary = {
        "legs": len(legs),
        "by_status": {k: {"n": v["n"], "size": round(v["size"], 2), "pnl": round(v["pnl"], 2),
                          "wins": v["wins"]} for k, v in sorted(by_status.items())},
        "settled_pnl_all_legs": round(sum(float(x["realizedPnl"] or 0) for x in legs), 2),
        "settled_pnl_filled_only": round(sum(float(x["realizedPnl"] or 0) for x in filled), 2),
        "unfilled_legs": len(unfilled),
        "near_cert_legs": sum(1 for x in legs
                              if "near certainty" in (x["risksJson"] or "")),
    }
    delta["settled_pnl_wallet"] = legs_summary["settled_pnl_all_legs"]
    delta["settled_pnl_filled_only"] = legs_summary["settled_pnl_filled_only"]
    delta["legs"] = legs_summary["legs"]
    delta["unfilled_legs"] = legs_summary["unfilled_legs"]

    # ---------- S5 cohort with / without the wallet
    all_nc = con.execute(
        """SELECT d.createdAt, d.walletAddress, d.decision, d.risksJson, o.detectedPrice
             FROM DecisionJournal d JOIN ObservedTrade o ON o.id=d.observedTradeId
            WHERE d.isDemo=0 AND d.risksJson LIKE '%near certainty%'""").fetchall()
    all_dec = con.execute(
        """SELECT d.createdAt, d.walletAddress FROM DecisionJournal d
            WHERE d.isDemo=0""").fetchall()

    per_day_all = defaultdict(lambda: {"nc_all": 0, "nc_w": 0, "dec_all": 0, "dec_w": 0,
                                       "nc_copy_all": 0, "nc_copy_w": 0,
                                       "nc_sole_all": 0, "nc_sole_w": 0})
    for r in all_nc:
        d = day(r["createdAt"])
        b = per_day_all[d]
        b["nc_all"] += 1
        try:
            sole = len(json.loads(r["risksJson"] or "[]")) == 1
        except Exception:  # noqa: BLE001
            sole = False
        if sole:
            b["nc_sole_all"] += 1
        if r["decision"] == "paper_copy":
            b["nc_copy_all"] += 1
        if r["walletAddress"] == W:
            b["nc_w"] += 1
            if sole:
                b["nc_sole_w"] += 1
            if r["decision"] == "paper_copy":
                b["nc_copy_w"] += 1
    for r in all_dec:
        d = day(r["createdAt"])
        per_day_all[d]["dec_all"] += 1
        if r["walletAddress"] == W:
            per_day_all[d]["dec_w"] += 1

    days = sorted(per_day_all)
    cohort_series = []
    for d in days:
        b = per_day_all[d]
        cohort_series.append({
            "day": d,
            "decisions_all": b["dec_all"],
            "decisions_wallet": b["dec_w"],
            "wallet_share": (b["dec_w"] / b["dec_all"]) if b["dec_all"] else None,
            "near_cert_all": b["nc_all"],
            "near_cert_ex_wallet": b["nc_all"] - b["nc_w"],
            "near_cert_copy_all": b["nc_copy_all"],
            "near_cert_copy_ex_wallet": b["nc_copy_all"] - b["nc_copy_w"],
            "near_cert_sole_all": b["nc_sole_all"],
            "near_cert_sole_ex_wallet": b["nc_sole_all"] - b["nc_sole_w"],
        })

    # rolling 7-day share of decisions (materiality conjunct 1)
    dmap = {b["day"]: b for b in cohort_series}
    rolling = []
    for d in days:
        dt0 = datetime.strptime(d, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        win_days = [(dt0 - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(7)]
        tot = sum(dmap[w]["decisions_all"] for w in win_days if w in dmap)
        mine = sum(dmap[w]["decisions_wallet"] for w in win_days if w in dmap)
        if tot:
            rolling.append({"day": d, "window_decisions": tot, "wallet_decisions": mine,
                            "share": mine / tot})

    # ---------- counterfactual: what a full-record ROI basis would do to the 25 seats
    # Held fixed: consistencyScore and copyabilityScore as stored (only the ROI term moves).
    # Published as a COUNTERFACTUAL on the score basis, not a recommendation to apply it.
    rw, rc, rp = rules["weightRoi"], rules["weightConsistency"], rules["weightCopyability"]
    seats = []
    seats.append({"address": W, "stored_globalScore": wp["globalScore"],
                  "cons": wp["consistencyScore"], "copy": wp["copyabilityScore"],
                  "roi_full": venue_subject["all"]["roi"],
                  "n_positions": venue_subject["all"]["n"]})
    for t in venue["tracked"]:
        row = con.execute(
            "SELECT globalScore, consistencyScore, copyabilityScore FROM WalletProfile WHERE address=?",
            (t["address"],)).fetchone()
        seats.append({"address": t["address"], "stored_globalScore": row["globalScore"],
                      "cons": row["consistencyScore"], "copy": row["copyabilityScore"],
                      "roi_full": (t["pnl"] / t["cost"]) if t["cost"] else None,
                      "n_positions": t["n_positions"]})
    for s in seats:
        roi = s["roi_full"] if s["roi_full"] is not None else 0.0
        roi_score = min(100.0, max(0.0, 40 + roi * 90))
        s["roi_score_full"] = round(roi_score, 1)
        s["globalScore_full_roi"] = round(roi_score * rw + s["cons"] * rc + s["copy"] * rp, 1)
    by_new = sorted(seats, key=lambda x: -x["globalScore_full_roi"])
    for i, s in enumerate(by_new):
        s["seat_full_roi_basis"] = i + 1
    by_old = sorted(seats, key=lambda x: -x["stored_globalScore"])
    for i, s in enumerate(by_old):
        s["seat_stored_basis"] = i + 1
    subject_seat = next(s for s in seats if s["address"] == W)
    score_counterfactual = {
        "basis": "roi term only: roiScore = clamp(40 + roi*90) on the FULL venue record "
                 "(cost = total_size x avg_price); consistency/copyability held at their stored "
                 "values; the v61 top-25 cap then decides the seat",
        "subject": {"stored_globalScore": subject_seat["stored_globalScore"],
                    "stored_seat": subject_seat["seat_stored_basis"],
                    "full_record_roi": subject_seat["roi_full"],
                    "roi_score_full": subject_seat["roi_score_full"],
                    "globalScore_full_roi": subject_seat["globalScore_full_roi"],
                    "seat_full_roi_basis": subject_seat["seat_full_roi_basis"],
                    "would_keep_seat": subject_seat["seat_full_roi_basis"] <= MAX_TRACKED},
        "seats_moving": sum(1 for s in seats
                            if s["seat_full_roi_basis"] != s["seat_stored_basis"]),
        "rows": sorted(seats, key=lambda x: x["seat_full_roi_basis"]),
    }

    # ---------- S6 verdict
    mat_days = [x for x in rolling if x["share"] >= 0.25]

    def _profit_conjunct(arm):
        # "not >0 with a 95% CI excluding zero" — the card's second conjunct
        roi = arm.get("roi")
        ci = arm.get("roi_ci") or [None, None]
        profitable = roi is not None and roi > 0 and ci[0] is not None and ci[0] > 0
        return {"roi": roi, "ci": ci, "profitable_ci_excludes_zero": profitable,
                "conjunct_not_profitable": not profitable}

    bar = {
        "material_share_ge_25pct_days": len(mat_days),
        "material_share_ge_25pct_first": mat_days[0]["day"] if mat_days else None,
        "material_share_ge_25pct_last": mat_days[-1]["day"] if mat_days else None,
        "material_conjunct_met": len(mat_days) > 1,
        "arms": {
            "A_wallet_own_venue_record": _profit_conjunct(venue_subject["all"]),
            "B_wallet_own_legs_settled_entry_its_price": _profit_conjunct(
                quality["flood_window_at_wallet"]),
            "C_copier_legs_settled_entry_detected_mid": _profit_conjunct(
                quality["flood_window_at_detected"]),
            "D_flood_vintage_only_venue": _profit_conjunct(
                venue_subject["vintage"]["first_entry_after_flood"]),
            "E_rich_side_band_0.95_1.01_venue": _profit_conjunct(
                venue_subject["by_entry_band"].get("0.95-1.01", {})),
        },
    }
    bar["roi_arm_venue_full_record"] = venue_subject["all"]
    bar["roi_arm_flood_at_detected"] = quality["flood_window_at_detected"]

    out = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "wallet": W,
        "label": wp.get("label"),
        "flood_cut": FLOOD_CUT.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "seat": seat,
        "decision_stream": {
            "rows": len(rows),
            "flood_rows": len(flood),
            "near_cert_rows": len(near),
            "near_cert_sole_blocker_rows": len(near_sole),
            "decision_mix": dict(Counter(r["decision"] for r in rows)),
            "outcome_mix": dict(Counter(r["outcome"] for r in rows)),
            "distinct_markets": len({r["marketId"] for r in rows}),
            "distinct_keys": len(key_rows),
            "rows_per_key": {
                "max": max(key_rows.values()) if key_rows else 0,
                "mean": (sum(key_rows.values()) / len(key_rows)) if key_rows else 0,
                "keys_observed_more_than_once": len(repeat),
                "share_of_rows_that_are_repeat_observations":
                    (sum(c for _, c in repeat) - len(repeat)) / len(rows) if rows else None,
            },
            "repeat_key_gap_seconds": {
                "median": (sorted(gaps)[len(gaps) // 2] if gaps else None),
                "p10": (sorted(gaps)[int(0.1 * len(gaps))] if gaps else None),
                "p90": (sorted(gaps)[int(0.9 * len(gaps)) - 1] if gaps else None),
                "n": len(gaps),
            },
            "marks_all": dict(marks),
            "marks_near_cert": dict(marks_near),
            "per_day": {d: {"decisions": v["decisions"], "markets": len(v["markets"]),
                            "keys": len(v["keys"]), "near": v["near"], "copies": v["copies"]}
                        for d, v in sorted(per_day.items())},
            "decisions_per_market_per_day": sorted(
                (v["decisions"] / len(v["markets"])) for v in per_day.values() if v["markets"]),
        },
        "quality": quality,
        "venue_subject": venue_subject,
        "venue_tracked": tracked_summary,
        "score_basis_counterfactual": score_counterfactual,
        "legs": legs_summary,
        "tracking_delta": delta,
        "cohort": {"series": cohort_series, "rolling7": rolling},
        "bar": bar,
        "notes": {
            "cost_basis": "venue positions: cost = total_size x avg_price (total_cost_usdc is 0 on "
                          "87.8% of this wallet's closed rows and percent_realized_pnl reproduces "
                          "on the reconstructed basis)",
            "label_basis": "decision arms are settled-outcome: every leg settles at the venue's own "
                           "0/1 outcomePrice for the traded token; no `won`, no realizedPnl",
            "clustering": "bootstrap resamples whole markets (condition_id), 95% percentile CI",
        },
    }
    OUT.write_text(json.dumps(out, indent=1))
    print(json.dumps({k: out[k] for k in ("seat", "quality", "venue_subject", "legs", "bar")},
                     indent=1)[:6000])
    print("\nwrote", OUT)


if __name__ == "__main__":
    main()
