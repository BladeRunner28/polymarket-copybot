#!/usr/bin/env python3
"""Long-shot FLOW funnel — card `longshot-flow-funnel`.

Answers the card's pre-registered question, measurement only: over a trailing 7d window,
for C-200 candidates, WHERE do the legs die, with counts — and specifically whether the
<0.20 band (94% of book PnL) is limited by SIZE levers or by ADMISSION.

Read-only. Writes data/longshot-flow-funnel.json and prints the ranked blocker list.

Card gate (pre-registered): "over a trailing 7d window report, per blocker, the COUNT of
otherwise-eligible C-200 candidates lost at each stage — wallet/market dedupe, price-drift
gate, minConfidence, category blacklist, hour blackout, v55 per-market cap, v58 per-wallet
ceiling, open-position cap, v62 band skip — plus the observed <0.20 legs/day and the
wallet-depth distribution of the candidates that reach the band. Output is a ranked blocker
list with counts; any lever it suggests needs its own approval. Do NOT relax the drift gate
or any threshold off this read."
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(ROOT, "prisma", "dev.db")
OUT = os.path.join(ROOT, "data", "longshot-flow-funnel.json")

LOCAL_OFFSET_S = 5 * 3600  # America/Chicago CDT (UTC-5) — the daily reports' basis
WINDOW_DAYS = 7

# --- window: the last 7 COMPLETE local calendar days -------------------------------
today_local = (datetime.now(timezone.utc) - timedelta(seconds=LOCAL_OFFSET_S)).date()
win_end = today_local - timedelta(days=1)          # yesterday (complete)
win_start = win_end - timedelta(days=WINDOW_DAYS - 1)
start_utc = datetime(win_start.year, win_start.month, win_start.day, tzinfo=timezone.utc) + timedelta(seconds=LOCAL_OFFSET_S)
end_utc = datetime(win_end.year, win_end.month, win_end.day, tzinfo=timezone.utc) + timedelta(seconds=LOCAL_OFFSET_S + 86400)
start_ms, end_ms = int(start_utc.timestamp() * 1000), int(end_utc.timestamp() * 1000)

# --- blocker taxonomy --------------------------------------------------------------
# Order matters only for reporting; classification is by pattern.
TAXONOMY = [
    ("DEDUPE (same wallet/market/outcome already open)", r"coalesced into open copy"),
    ("DRIFT (price drifted since wallet entry)", r"price drifted"),
    ("CONFIDENCE (below minConfidence)", r"^confidence .* < min"),
    ("BLACKLIST (v45 category)", r"blacklist category"),
    ("TTR (resolves sooner than min)", r"resolves in .* < min"),
    ("LIQUIDITY", r"liquidity .* < min"),
    ("SPREAD", r"spread .* > max"),
    ("NEAR-CERTAINTY (band)", r"near certainty"),
    ("HOUR BLACKOUT", r"hour blackout"),
    ("KELLY NO-EDGE", r"kelly no-edge"),
    ("SLUG CAP (v45 15/slug)", r"market-slug cap"),
    ("HIGH-ENTRY CAP", r"high-entry cap"),
    ("BAND SKIP (v62)", r"band skip"),
    ("PER-MARKET CAP (v55)", r"v5[0-9] per-market cap"),
    ("PER-WALLET CAP (v58)", r"v5[0-9] per-wallet cap|per-wallet"),
    ("OPEN-POSITION CAP", r"open-position cap"),
    ("ANNOTATION (not a gate)", r"Mean Reversion Risk|Spread eats into edge|Price already near certainty"),
]
NOT_A_BLOCKER = re.compile(r"short-ttr lane \(relaxed drift & score bar\)")


def classify(s: str) -> str | None:
    if NOT_A_BLOCKER.search(s):
        return None
    for label, pat in TAXONOMY:
        if re.search(pat, s, re.I):
            return label
    return f"OTHER: {s[:70]}"


def band(p: float) -> str:
    if p < 0.20:
        return "0.00-0.20"
    if p < 0.40:
        return "0.20-0.40"
    if p < 0.60:
        return "0.40-0.60"
    if p < 0.80:
        return "0.60-0.80"
    return "0.80-1.01"


BANDS = ["0.00-0.20", "0.20-0.40", "0.40-0.60", "0.60-0.80", "0.80-1.01"]


def main() -> int:
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    q = con.execute

    rep: dict = {
        "window": {"label": f"{win_start} .. {win_end} local (7 complete days)",
                   "basis": "America/Chicago (closedAt ?? resolvedAt; candidate prices = ObservedTrade.detectedPrice)",
                   "start_utc": start_utc.isoformat(), "end_utc": end_utc.isoformat()},
        "read_at": datetime.now(timezone.utc).isoformat(),
    }

    # ---------- 0. denominator: what was DETECTED -----------------------------------
    obs = q("""SELECT COUNT(*) n,
                      SUM(CASE WHEN observationOnly=0 THEN 1 ELSE 0 END) copy_eligible,
                      SUM(CASE WHEN observationOnly=1 THEN 1 ELSE 0 END) observation_only,
                      COUNT(DISTINCT walletAddress) wallets
               FROM ObservedTrade WHERE isDemo=0 AND timestamp >= ? AND timestamp < ?""",
            (start_ms, end_ms)).fetchone()
    rep["detected"] = dict(obs)

    # ---------- 1. the <0.20 admission funnel, stage by stage -----------------------
    # Stage 1: copy-eligible candidates whose DETECTED price sits in each band.
    stage1 = {b: 0 for b in BANDS}
    for r in q("""SELECT detectedPrice p, COUNT(*) n FROM ObservedTrade
                  WHERE isDemo=0 AND observationOnly=0 AND timestamp >= ? AND timestamp < ?
                  GROUP BY 1""", (start_ms, end_ms)):
        stage1[band(r["p"])] += r["n"]

    # Stage 2/3/4: join to the decision row, then to any booked leg.
    dec = defaultdict(lambda: {"scored": 0, "copied": 0, "skip": 0, "watch": 0})
    blockers_all: dict[str, Counter] = {b: Counter() for b in BANDS}
    blockers_first: dict[str, Counter] = {b: Counter() for b in BANDS}
    skip_rows: dict[str, list] = {b: [] for b in BANDS}

    rows = q("""SELECT d.decision, d.risksJson, o.detectedPrice p, o.walletAddress w,
                       o.marketId m, o.marketCategoryClass cc, d.ruleSetVersion v,
                       d.rawConfidence rc, d.confidence c
                FROM DecisionJournal d JOIN ObservedTrade o ON o.id = d.observedTradeId
                WHERE d.isDemo=0 AND d.createdAt >= ? AND d.createdAt < ?""",
             (start_ms, end_ms))
    for r in rows:
        b = band(r["p"])
        rec = dec[b]
        rec["scored"] += 1
        if r["decision"] == "paper_copy":
            rec["copied"] += 1
        elif r["decision"] == "watch":
            rec["watch"] += 1
        else:
            rec["skip"] += 1
            try:
                arr = json.loads(r["risksJson"] or "[]")
            except Exception:
                arr = []
            cats, seen = [], set()
            for s in arr:
                lab = classify(str(s))
                if lab and lab not in seen:
                    seen.add(lab)
                    cats.append(lab)
            for lab in cats:
                blockers_all[b][lab] += 1
            if cats:
                blockers_first[b][cats[0]] += 1
            skip_rows[b].append({"m": r["m"], "p": r["p"], "w": r["w"], "cats": cats,
                                 "v": r["v"], "rc": r["rc"], "c": r["c"],
                                 "raw": [str(x) for x in arr]})

    rep["bands"] = {b: {"detected_copy_eligible": stage1[b], **dec[b]} for b in BANDS}

    # ---------- 2. booked C-200 legs: legs/day and the long-shot share --------------
    legs = defaultdict(list)
    for r in q("""SELECT entryPrice e, simulatedPositionSize s, realizedPnl pnl, status st,
                         datetime((openedAt/1000)-?, 'unixepoch') d
                  FROM PaperTrade WHERE botId='BANKROLL_200' AND isDemo=0
                    AND openedAt >= ? AND openedAt < ?""", (LOCAL_OFFSET_S, start_ms, end_ms)):
        legs[band(r["e"])].append(r)

    legstats = {}
    total_legs = sum(len(v) for v in legs.values())
    total_notional = sum(r["s"] for v in legs.values() for r in v)
    for b in BANDS:
        v = legs.get(b, [])
        n = len(v)
        notional = sum(r["s"] for r in v)
        settled = [r for r in v if r["st"] in ("closed", "resolved")]
        pnl = sum(r["pnl"] or 0 for r in settled)
        legstats[b] = {
            "legs": n,
            "legs_per_day": round(n / WINDOW_DAYS, 2),
            "notional": round(notional, 2),
            "notional_share_pct": round(100 * notional / total_notional, 1) if total_notional else 0.0,
            "avg_clip": round(notional / n, 2) if n else 0.0,
            "settled": len(settled), "realized_pnl": round(pnl, 2),
            "settled_roi_pct": round(100 * pnl / sum(r["s"] for r in settled), 1) if settled and sum(r["s"] for r in settled) else None,
        }
    rep["c200_legs"] = {"total": total_legs, "notional": round(total_notional, 2),
                        "per_day": round(total_legs / WINDOW_DAYS, 2), "by_band": legstats}

    # ---------- 3. the long-shot band, in detail -----------------------------------
    ls = legstats["0.00-0.20"]
    rep["longshot"] = {
        "legs": ls["legs"], "legs_per_day": ls["legs_per_day"],
        "avg_clip": ls["avg_clip"], "notional": ls["notional"],
        "settled_roi_pct": ls["settled_roi_pct"], "realized_pnl": ls["realized_pnl"],
        "share_of_legs_pct": round(100 * ls["legs"] / total_legs, 1) if total_legs else 0.0,
        "share_of_notional_pct": ls["notional_share_pct"],
        "ranked_blockers_first": blockers_first["0.00-0.20"].most_common(),
        "ranked_blockers_all": blockers_all["0.00-0.20"].most_common(),
    }

    # ---------- 4. drift magnitude distribution on <0.20 candidates -----------------
    # COUNTS ONLY. The card forbids deriving a threshold from this read; this exists to
    # say HOW EARLY the band is lost, not where a new bar should sit.
    drift_hist = Counter()
    drift_vals = []
    for r in skip_rows["0.00-0.20"]:
        for s in r["raw"]:
            mm = re.search(r"price drifted ([\d.]+)", s)
            if mm:
                d = float(mm.group(1))
                drift_vals.append(d)
                drift_hist["<=0.0040 (would pass today)" if d <= 0.0040 else
                            "0.0040-0.0100" if d <= 0.01 else
                            "0.0100-0.0500" if d <= 0.05 else
                            "0.0500-0.1000" if d <= 0.1 else
                            ">0.1000"] += 1
                break
    rep["longshot_drift"] = {
        "candidates_blocked_by_drift": len(drift_vals),
        "median_drift": sorted(drift_vals)[len(drift_vals) // 2] if drift_vals else None,
        "histogram": drift_hist.most_common(),
        "note": "COUNTS ONLY — no threshold is proposed from this. The drift bar has its own pre-registered decision (tr31-rec2-drift-decay-bar = HOLD).",
    }

    # ---------- 4b. SOLE vs CO-OCCURRING blockers (the "otherwise-eligible" count) ---
    # risksJson[0] is the scorer's own check ORDER (drift is checked early), so "primary
    # blocker" is an ordering artifact. What the card asks for is which candidates would be
    # admitted if ONE gate were removed — i.e. rows whose classified blocker set is a SINGLE
    # gate. That is the only honest "otherwise-eligible" number.
    sole_all: Counter = Counter()
    sole_ls: Counter = Counter()
    pair_ls: Counter = Counter()
    setsize_ls: Counter = Counter()
    for b, rowsb in skip_rows.items():
        for r in rowsb:
            cats = r["cats"]
            setsize_ls[len(cats)] += 1 if b == "0.00-0.20" else 0
            if len(cats) == 1:
                sole_all[cats[0]] += 1
                if b == "0.00-0.20":
                    sole_ls[cats[0]] += 1
            if b == "0.00-0.20":
                for i in range(len(cats)):
                    for j in range(i + 1, len(cats)):
                        pair_ls[" + ".join(sorted((cats[i], cats[j])))] += 1
    rep["longshot_sole_blocker"] = {
        "note": "rows whose classified blocker set is a SINGLE gate — the count a one-gate "
                "change would actually admit. risksJson[0] is check ORDER, not priority.",
        "sole": sole_ls.most_common(),
        "setsize": sorted(setsize_ls.items()),
        "pairs": pair_ls.most_common(8),
        "all_bands_sole": sole_all.most_common(10),
    }

    # ---------- 5. wallet depth of the candidates reaching <0.20 --------------------
    depth = Counter()
    for r in q("""SELECT w.resolvedTradeCount30d d, w.depthCensored cen, COUNT(*) n
                  FROM DecisionJournal j JOIN ObservedTrade o ON o.id=j.observedTradeId
                  JOIN WalletProfile w ON w.address=o.walletAddress
                  WHERE j.isDemo=0 AND j.createdAt >= ? AND j.createdAt < ? AND o.detectedPrice < 0.20
                  GROUP BY 1,2""", (start_ms, end_ms)):
        k = ("censored@cap" if r["cen"] else
             "<10" if (r["d"] or 0) < 10 else
             "10-49" if r["d"] < 50 else
             "50-99" if r["d"] < 100 else
             "100-299" if r["d"] < 300 else ">=300")
        depth[k] += r["n"]
    rep["longshot_wallet_depth"] = depth.most_common()

    # ---------- 6. throughput ceiling: is the gap size or flow? ---------------------
    # Pure arithmetic off THIS window, stated as such (not a forecast).
    potential = None
    if ls["legs"] and ls["settled_roi_pct"] is not None:
        pnl = ls["realized_pnl"]
        potential = {
            "basis": "this window's own <0.20 legs and settled ROI",
            "current_pnl_per_day": round(pnl / WINDOW_DAYS, 2),
            "legs_per_day": ls["legs_per_day"],
            "roi_pct": ls["settled_roi_pct"],
            "pnl_per_leg": round(pnl / ls["legs"], 2) if ls["legs"] else None,
        }
    rep["longshot_ceiling"] = potential

    # ---------- 7. are candidates ever dropped without a decision row? --------------
    rep["containment"] = dict(q("""SELECT
            (SELECT COUNT(*) FROM ObservedTrade WHERE isDemo=0 AND observationOnly=0
               AND timestamp >= ? AND timestamp < ?) copy_eligible,
            (SELECT COUNT(*) FROM DecisionJournal WHERE isDemo=0 AND createdAt >= ? AND createdAt < ?) decided""",
        (start_ms, end_ms, start_ms, end_ms)).fetchone())

    with open(OUT, "w") as fh:
        json.dump(rep, fh, indent=1, ensure_ascii=True)

    # ------------------------------- console report --------------------------------
    P = print
    P("=" * 96)
    P(f"LONG-SHOT FLOW FUNNEL — {rep['window']['label']}")
    P("=" * 96)
    d = rep["detected"]
    P(f"detected: {d['n']:,} rows | copy-eligible {d['copy_eligible']:,} | observation-only {d['observation_only']:,} "
      f"| {d['wallets']:,} wallets | containment {rep['containment']['copy_eligible']:,} elig / {rep['containment']['decided']:,} decided")
    P("")
    P(f"{'band':<10}{'detected':>10}{'scored':>9}{'copied':>8}{'skip':>8}")
    for b in BANDS:
        r = rep["bands"][b]
        P(f"{b:<10}{r['detected_copy_eligible']:>10,}{r['scored']:>9,}{r['copied']:>8,}{r['skip']:>8,}")
    P("")
    P("BOOKED C-200 LEGS BY BAND (7d)")
    P(f"{'band':<10}{'legs':>7}{'legs/day':>10}{'notional':>11}{'%notional':>11}{'avg clip':>10}{'settled ROI':>13}")
    for b in BANDS:
        r = legstats[b]
        roi = f"{r['settled_roi_pct']}%" if r['settled_roi_pct'] is not None else "-"
        P(f"{b:<10}{r['legs']:>7}{r['legs_per_day']:>10}{r['notional']:>11,.2f}{r['notional_share_pct']:>10}%{r['avg_clip']:>10}{roi:>13}")
    P(f"{'TOTAL':<10}{total_legs:>7}{total_legs / WINDOW_DAYS:>10.2f}{total_notional:>11,.2f}")
    P("")
    P("WHERE <0.20 CANDIDATES DIE — primary blocker (index 0 of risksJson)")
    tot = sum(v for _, v in blockers_first["0.00-0.20"].most_common())
    other = 0
    for lab, n in blockers_first["0.00-0.20"].most_common():
        if lab.startswith("OTHER"):
            other += n
            continue
        P(f"  {n:7,}  {100 * n / tot:5.1f}%  {lab}")
    if other:
        P(f"  {other:7,}  {100 * other / tot:5.1f}%  OTHER (unclassified)")
    P(f"  {tot:7,}  total skip rows that carry a classified primary blocker")
    P("")
    P("WHERE <0.20 CANDIDATES DIE — ALL blockers on the row (co-occurrence; a row can have several)")
    for lab, n in blockers_all["0.00-0.20"].most_common(12):
        if lab.startswith("OTHER"):
            continue
        P(f"  {n:7,}  {lab}")
    P("")
    P("SAME TABLE, ALL BANDS — primary blocker share (for contrast)")
    labs = [l for l, _ in blockers_first["0.00-0.20"].most_common(8) if not l.startswith("OTHER")]
    P(f"  {'primary blocker':<46}" + "".join(f"{b:>13}" for b in BANDS))
    for lab in labs:
        line = f"  {lab:<46}"
        for b in BANDS:
            t = sum(blockers_first[b].values()) or 1
            line += f"{100 * blockers_first[b].get(lab, 0) / t:>12.1f}%"
        P(line)
    P("")
    P("SOLE-BLOCKER SETS on <0.20 (the count a ONE-GATE change would actually admit)")
    sb = rep["longshot_sole_blocker"]
    for lab, n in sb["sole"]:
        P(f"  {n:7,}  {lab}")
    P("  blocker-set size distribution (how many gates fire per row):")
    for k, n in sb["setsize"]:
        P(f"    {n:7,}  {k} gate(s)")
    P("  top co-occurring pairs:")
    for lab, n in sb["pairs"][:5]:
        P(f"    {n:7,}  {lab}")
    P("")
    P("DRIFT MAGNITUDE at which <0.20 candidates are lost (COUNTS ONLY, no threshold proposed)")
    for lab, n in rep["longshot_drift"]["histogram"]:
        P(f"  {n:7,}  {lab}")
    P(f"  median drift {rep['longshot_drift']['median_drift']}")
    P("")
    P("WALLET DEPTH (resolvedTradeCount30d) of candidates reaching <0.20")
    for k, n in depth.most_common():
        P(f"  {n:7,}  {k}")
    P("")
    P(f"artifact -> {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
