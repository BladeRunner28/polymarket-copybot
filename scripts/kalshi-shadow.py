"""Build the Kalshi shadow ledger + the shadow expectancy-score journal.

Read-only over prisma/dev.db. Writes (idempotent, rebuilt from scratch each run):
  data/kalshi-shadow.jsonl          per-copy shadow rows (one JSON object per line)
  data/kalshi-shadow-summary.json   card + report payload (series, tiles, gate variants)
  data/shadow-score.jsonl           recent decisions scored by the shadow expectancy model

WHAT THIS IS
  A counterfactual ledger, not a venue feed. Real Kalshi trading is currently
  retired (see drafts/kalshi-venue-dormancy-review-20260913.md), so every C-200
  copy is booked on Polymarket. This builder answers two questions separately:
    1. ATTRIBUTION — of the realized C-200 book, which slice *would* have been
       routed to Kalshi under each candidate venue rule? Those rows are priced
       at the Polymarket reference (that is what the paper book actually holds),
       so the slice PnL is an attribution, NOT a venue P&L.
    2. SCORING — what does the shadow expectancy model say about each decision,
       next to the live copyScore?
  The moment live routing is re-enabled (post-Oct-8 decision) the same rows
  carry real Kalshi fills and this file becomes a venue P&L ledger.

USAGE
  python3 scripts/kalshi-shadow.py            # verbose
  python3 scripts/kalshi-shadow.py --quiet    # cron mode (writes files only)
"""
import argparse
import json
import math
import os
import sqlite3
import time

MODEL_PATH = "data/shadow-score-model.json"
OUT_LEDGER = "data/kalshi-shadow.jsonl"
OUT_SUMMARY = "data/kalshi-shadow-summary.json"
OUT_SCORES = "data/shadow-score.jsonl"

# venue-rule variants, evaluated side by side
GATE_VARIANTS = {
    "gate_as_written": "conf > 0.8 AND copyScore >= 80 (live rule, structurally unsatisfiable post-v37)",
    "gate_pre_v37": "copyScore >= 87.5 (confidence read from the post-boost score, pre-v37 semantics)",
    "gate_repaired_raw": "raw pre-boost composite >= 87.33 AND copyScore >= 80 (strict quality bar)",
    "shadow_model": "shadow expectancy score > 0 (model call, decision-time features only)",
}


def feature_vector(row, feats):
    return [float(row[f]) if row.get(f) is not None and not (isinstance(row.get(f), float) and math.isnan(row[f])) else 0.0
            for f in feats]


def score_row(row, art):
    zs = []
    for v, f, mu, sd in zip(feature_vector(row, art["features"]), art["features"], art["mu"], art["sd"]):
        z = (v - mu) / sd if sd else 0.0
        zs.append(max(-10.0, min(10.0, z)))
    return float(art["beta"][0] + sum(b * z for b, z in zip(art["beta"][1:], zs)))


def load_copies():
    con = sqlite3.connect("file:prisma/dev.db?mode=ro", uri=True)
    rows = con.execute(
        """SELECT t.id, t.botId, t.venue, t.status, t.entryPrice, t.simulatedPositionSize,
                  t.realizedPnl, t.openedAt, COALESCE(t.closedAt, t.resolvedAt) finished_at,
                  d.id, d.copyScore, d.confidence, d.reasonsJson, d.ruleSetVersion,
                  d.walletQualityScore, d.categoryFitScore, d.entryTimingScore,
                  d.spreadScore, d.liquidityScore, d.thesisScore,
                  o.marketQuestion, o.walletEntryPrice, o.detectedPrice, o.size, o.marketCategory
           FROM PaperTrade t
           JOIN DecisionJournal d ON d.id = t.decisionJournalId
           JOIN ObservedTrade o ON o.id = d.observedTradeId
           WHERE t.botId = 'BANKROLL_200' AND t.isDemo = 0"""
    ).fetchall()
    con.close()
    return rows


def build_row(r):
    (tid, bot, venue, status, entry, size, pnl, opened, finished, did, cs, conf, reasons,
     rsv, wq, cat, timing, spread, liq, thesis, question, wentry, detp, wsize, mcat) = r
    rj = (reasons or "").lower()
    raw = (wq or 0) * 0.30 + (cat or 0) * 0.15 + (timing or 0) * 0.20 + \
          (spread or 0) * 0.10 + (liq or 0) * 0.15 + (thesis or 0) * 0.10
    return {
        "tradeId": tid, "decisionId": did, "venue": venue, "status": status,
        "openedMs": opened, "finishedMs": finished,
        "question": (question or "")[:110], "category": mcat,
        "entryPrice": entry, "size": float(size or 0.0),
        "pnl": float(pnl) if pnl is not None else None,
        "copyScore": cs, "confidence": conf, "raw_composite": round(raw, 2),
        "ruleSetVersion": rsv,
        "is_lane": 1.0 if (conf == 0 and cs) else 0.0,
        "is_swarm": 1.0 if "swarm" in rj else 0.0,
        "is_sentiment": 1.0 if "sentiment evidence" in rj else 0.0,
        "entryPrice_sq": (entry or 0) ** 2,
        "drift": abs((detp or 0) - (wentry or 0)),
        "trade_size_log": math.log1p(max(0.0, wsize or 0.0)),
        "hour_et": int(((opened or 0) / 3600000.0 - 4) % 24),
        "walletQualityScore": wq, "categoryFitScore": cat, "entryTimingScore": timing,
        "spreadScore": spread, "liquidityScore": liq, "thesisScore": thesis,
    }


def gate_flags(d):
    """Candidate venue rules, evaluated from stored decision-time values."""
    cs, conf, raw = d["copyScore"], d["confidence"], d["raw_composite"]
    return {
        "gate_as_written": bool(conf > 0.8 and cs >= 80),
        "gate_pre_v37": bool(cs >= 87.5 and cs >= 80),
        "gate_repaired_raw": bool(raw >= 87.33 and cs >= 80),
        "shadow_model": bool(d.get("shadowScore", 0.0) > 0.0),
    }


def day_key(ms):
    return time.strftime("%Y-%m-%d", time.localtime((ms or 0) / 1000.0))


# Polymarket taker fee per staked dollar = size * rate * (1 - price)
# (fee = shares * rate * p * (1-p), shares = size/p). Source:
# drafts/c200-taker-fee-measurement-2026-09-09.md. Rates by category keyword
# because MarketSnapshot.category is NULL; the attribution is Polymarket-priced,
# so the Polymarket rate applies even to rows labelled Kalshi.
_FEE_KEYWORDS = [
    (0.07, ("btc", "bitcoin", "eth", "ethereum", "solana", "crypto", "token", "airdrop", "fdv")),
    (0.04, ("election", "president", "senate", "congress", "fed", "cpi", "gdp", "rate cut", "tariff",
            "earnings", "nominee", "parliament", "inflation", "recession", "shutdown", "impeach", "poll")),
]


def fee_rate(text):
    t = (text or "").lower()
    for rate, words in _FEE_KEYWORDS:
        if any(w in t for w in words):
            return rate
    return 0.05


def fee_entry_usd(rows):
    """Entry-leg taker fee for a set of rows (the leg a gate can know ex ante)."""
    total = 0.0
    for d in rows:
        if d.get("pnl") is None:
            continue  # unsettled rows are not in the PnL/pnl comparison
        total += d["size"] * fee_rate(d.get("question", "")) * (1 - d["entryPrice"])
    return total


def stats(rows):
    settled = [d for d in rows if d["pnl"] is not None]
    pnl = sum(d["pnl"] for d in settled)
    staked = sum(d["size"] for d in settled)
    return {
        "n": len(rows), "n_settled": len(settled), "n_open": len(rows) - len(settled),
        "pnl": round(pnl, 2), "staked": round(staked, 2),
        "roi_pct": round(100.0 * pnl / staked, 2) if staked else 0.0,
        "win_rate_pct": round(100.0 * sum(1 for d in settled if (d["pnl"] or 0) > 0) / len(settled), 1) if settled else 0.0,
    }


def stats_ex_top1(rows):
    """stats() with the SINGLE largest-PnL settled row removed.

    2026-09-20 (user-approved, Kalshi-shadow report rec 2): the OOS verdict
    currently hinges on ONE row — cmu6u424e0 (Elon, shadowScore 95.4, ss -0.50)
    at +$1,076.47 is the entire positive side of the rejected arm (+$857.03 with
    it, -$37.1% ROI without it). A reader of the raw line concludes the shadow
    score separates; a reader of the ex-top-1 line concludes it does not (both
    arms negative, 1.2pp apart). Neither is wrong, and the difference is what the
    Oct 8 retire call must be made on — so both are published side by side.
    Measurement only: no gate, rule or routing reads this.
    """
    settled = sorted([d for d in rows if d["pnl"] is not None], key=lambda d: d["pnl"], reverse=True)
    if len(settled) <= 1:
        out = stats(rows)
        out["droppedTradeId"] = None
        out["droppedPnl"] = 0.0
        return out
    top = settled[0]
    kept = [d for d in rows if d is not top]
    out = stats(kept)
    out["droppedTradeId"] = top["tradeId"]
    out["droppedPnl"] = round(top["pnl"], 2)
    out["n_settled_before"] = len(settled)
    return out


def cumulative_series(rows, mask=None):
    """Cumulative realized PnL by finish day (matches the dashboard day convention)."""
    acc = {}
    total = 0.0
    for d in sorted([x for x in rows if x["pnl"] is not None and (mask is None or mask(x))], key=lambda x: x["finishedMs"] or 0):
        total += d["pnl"]
        acc[day_key(d["finishedMs"])] = round(total, 2)
    return acc


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    def say(*a):
        if not args.quiet:
            print(*a)

    if not os.path.exists(MODEL_PATH):
        raise SystemExit("missing %s — run: python3 scripts/shadow-expectancy-model.py --fit" % MODEL_PATH)
    art = json.load(open(MODEL_PATH))

    rows = [build_row(r) for r in load_copies()]
    for d in rows:
        d["shadowScore"] = round(score_row(d, art), 4)

    # ---------------- attribution by candidate venue rule ----------------
    live_total = stats(rows)
    live_fee = fee_entry_usd(rows)
    variants = {}
    for name, desc in GATE_VARIANTS.items():
        sel = [d for d in rows if gate_flags(d)[name]]
        fee = fee_entry_usd(sel)
        sel_stats = stats(sel)
        variants[name] = {
            "label": desc,
            "selected": sel_stats,
            "share_of_book_pct": round(100.0 * len(sel) / len(rows), 1) if rows else 0.0,
            "series_cum": cumulative_series(rows, mask=lambda x, n=name: gate_flags(x)[n]),
            # Comparison fields (2026-09-13): the slice's PnL alone invites reading it
            # as a second venue's profit. These make the two honest readings explicit:
            #   delta_vs_all_pm   = what the rule ADDS over doing nothing (the slice is
            #                       a subset of the book, so it is never additive to it)
            #   pnl_net_entry_fee = the same slice after the entry-leg taker fee, which
            #                       the paper ledger does not charge at all
            "delta_vs_all_pm": round(sel_stats["pnl"] - live_total["pnl"], 2),
            "fee_entry_usd": round(fee, 2),
            "pnl_net_entry_fee": round(sel_stats["pnl"] - fee, 2),
            "in_sample": True,
        }
        say("[%s] %s -> n=%d pnl=$%.2f roi=%.1f%%" % (
            name, desc[:34], variants[name]["selected"]["n"],
            variants[name]["selected"]["pnl"], variants[name]["selected"]["roi_pct"]))

    # ---------------- dashboard series (default variant = shadow_model) ----------------
    dates = sorted({day_key(d["finishedMs"]) for d in rows if d["pnl"] is not None})
    def series_for(pred):
        out, run = [], 0.0
        for dt in dates:
            run += sum(d["pnl"] for d in rows
                       if d["pnl"] is not None and day_key(d["finishedMs"]) == dt and pred(d))
            out.append(round(run, 2))
        return out

    live_series = series_for(lambda d: True)
    kalshi_series = series_for(lambda d: gate_flags(d)["shadow_model"])
    # PM-only remainder keeps the attribution additive: kalshi + pm_only == live
    pm_only_series = [round(a - b, 2) for a, b in zip(live_series, kalshi_series)]

    def window_stats(since_ms, pred=lambda d: True, ex_top1=False):
        sub = [d for d in rows if (d["openedMs"] or 0) >= since_ms and pred(d)]
        out = stats(sub)
        if ex_top1:
            # rec 2: publish the same window with its single biggest winner removed
            out["exTop1"] = stats_ex_top1(sub)
        return out

    SEP5 = 1788677940000  # 2026-09-05 08:39 (breaker clear / Kalshi leg re-priced)
    summary = {
        "asOf": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "asOfMs": int(time.time() * 1000),
        "kind": "counterfactual-attribution",
        "note": ("C-200 book attributed across candidate Kalshi venue rules. Rows are priced at the "
                 "Polymarket reference because live Kalshi routing is retired; slice PnL is an "
                 "attribution, not venue P&L."),
        "model": {
            "fittedAt": art["fitted_at"], "nTrain": art["n_train"],
            "oosRankIcPurged": art["oos_rank_ic_purged"], "target": art["target"],
            "caveats": art["caveats"],
        },
        "live": live_total,
        "liveSinceSep5": window_stats(SEP5),
        "liveFeeEntryUsd": round(live_fee, 2),
        "livePnlNetEntryFee": round(live_total["pnl"] - live_fee, 2),
        "variants": variants,
        "defaultVariant": "shadow_model",
        "series": {
            "dates": dates, "liveCum": live_series,
            "kalshiShadowCum": kalshi_series, "pmOnlyCum": pm_only_series,
        },
        "shadowScoreSplit": {
            "selected": window_stats(0, lambda d: gate_flags(d)["shadow_model"]),
            "rejected": window_stats(0, lambda d: not gate_flags(d)["shadow_model"]),
            # IMPORTANT: the model was fitted on these rows, so the split above is
            # IN-SAMPLE. The honest forward number is this one — trades opened after
            # the fit timestamp score genuinely out-of-sample. It starts empty and
            # fills as the shadow runs.
            "inSample": True,
            "oosSinceFit": window_stats(art.get("as_of_ms") or 0, lambda d: gate_flags(d)["shadow_model"], ex_top1=True),
            "oosRejected": window_stats(art.get("as_of_ms") or 0, lambda d: not gate_flags(d)["shadow_model"], ex_top1=True),
            "oosStartedMs": art.get("as_of_ms"),
        },
    }

    with open(OUT_LEDGER, "w") as fh:
        for d in rows:
            fh.write(json.dumps(d) + "\n")
    with open(OUT_SUMMARY, "w") as fh:
        json.dump(summary, fh, indent=2)

    # ---------------- shadow-score journal for recent decisions ----------------
    con = sqlite3.connect("file:prisma/dev.db?mode=ro", uri=True)
    recent = con.execute(
        """SELECT d.id, d.venue, d.decision, d.copyScore, d.confidence, d.createdAt,
                  d.walletQualityScore, d.categoryFitScore, d.entryTimingScore,
                  d.spreadScore, d.liquidityScore, d.thesisScore, d.reasonsJson,
                  d.ruleSetVersion, o.walletEntryPrice, o.detectedPrice, o.size, o.marketQuestion
           FROM DecisionJournal d JOIN ObservedTrade o ON o.id = d.observedTradeId
           WHERE d.isDemo = 0 AND d.createdAt > ? ORDER BY d.createdAt DESC LIMIT 4000""",
        (int(time.time() * 1000) - 14 * 86400000,),
    ).fetchall()
    con.close()
    n_scored = 0
    with open(OUT_SCORES, "w") as fh:
        for r in recent:
            (did, venue, decision, cs, conf, created, wq, cat, timing, spread, liq, thesis,
             reasons, rsv, wentry, detp, wsize, question) = r
            d = {
                "decisionId": did, "venue": venue, "decision": decision, "createdMs": created,
                "copyScore": cs, "confidence": conf,
                "entryPrice": detp, "entryPrice_sq": (detp or 0) ** 2,
                "drift": abs((detp or 0) - (wentry or 0)),
                "trade_size_log": math.log1p(max(0.0, wsize or 0.0)), "size": 0.0,
                "hour_et": int(((created or 0) / 3600000.0 - 4) % 24),
                "is_swarm": 1.0 if "swarm" in (reasons or "").lower() else 0.0,
                "is_sentiment": 1.0 if "sentiment evidence" in (reasons or "").lower() else 0.0,
                "is_lane": 1.0 if (conf == 0 and cs) else 0.0,
                "walletQualityScore": wq, "categoryFitScore": cat, "entryTimingScore": timing,
                "spreadScore": spread, "liquidityScore": liq, "thesisScore": thesis,
                "ruleSetVersion": rsv,
            }
            raw = (wq or 0) * 0.30 + (cat or 0) * 0.15 + (timing or 0) * 0.20 + \
                  (spread or 0) * 0.10 + (liq or 0) * 0.15 + (thesis or 0) * 0.10
            d["raw_composite"] = round(raw, 2)
            d["shadowScore"] = round(score_row(d, art), 4)
            d["question"] = (question or "")[:110]
            fh.write(json.dumps(d) + "\n")
            n_scored += 1

    say("wrote %s (%d rows), %s (%d decisions scored), %s" % (
        OUT_LEDGER, len(rows), OUT_SCORES, n_scored, OUT_SUMMARY))
    say("live C-200: n=%d pnl=$%.2f roi=%.1f%% | shadow-model slice: n=%d pnl=$%.2f roi=%.1f%%" % (
        live_total["n"], live_total["pnl"], live_total["roi_pct"],
        summary["shadowScoreSplit"]["selected"]["n"], summary["shadowScoreSplit"]["selected"]["pnl"],
        summary["shadowScoreSplit"]["selected"]["roi_pct"]))


if __name__ == "__main__":
    main()
