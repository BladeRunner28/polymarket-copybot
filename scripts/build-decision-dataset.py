#!/usr/bin/env python3
"""Build the decision dataset the score work needs (research pipeline).

SCOPE: read-only against prisma/dev.db. Writes:
  data/decision-dataset.csv        one row per resolved copy decision + outcome + cost
  data/decision-dataset.manifest.json

Why this exists (see drafts/scoring-fix-methods-20260913.md):
  * The OutcomeReview label set is 688 rows / 10 wallets / one ~24h window.
  * 9.6k resolved paper trades DO carry entryPrice + realizedPnl + the full stored
    component breakdown, so the usable labeled set is ~14x larger than the reviewed one.
  * Labels are derived from the trade's own booked result (realizedPnl), NOT from
    wasDecisionGood (which disagrees with the trade's own PnL sign 30% of the time
    because skip rows are judged good = !won).

Targets emitted:
  y_win = 1 if the copied token won (realizedPnl > 0 for a copy leg)
  pnl_gross, pnl_net_entry (entry-leg fee only: the cost a gate can know ex ante),
  pnl_net_full (entry + exit leg, all-taker upper bound)

Fee model: Polymarket taker fee = shares * rate * p * (1-p)  ->  per staked dollar the
ENTRY fee is size * rate * (1 - p). Rate by category (crypto .07, politics/finance/
tech/mentions .04, else .05); inferred from the question text because
MarketSnapshot.category is NULL. Source: drafts/c200-taker-fee-measurement-2026-09-09.md.

Features are taken from what was stored AT DECISION TIME (DecisionJournal component
scores) plus the latest MarketSnapshot collected at or before the decision (raw spread /
liquidity / ttr / volume) — no post-decision data is used.

Usage:  ./venv-calib/bin/python scripts/build-decision-dataset.py [--dedupe/--no-dedupe]
"""

import argparse
import csv
import json
import os
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(ROOT, "prisma", "dev.db")
CSV_OUT = os.path.join(ROOT, "data", "decision-dataset.csv")
MANIFEST = os.path.join(ROOT, "data", "decision-dataset.manifest.json")

# Polymarket taker fee coefficients (docs.polymarket.com/trading/fees), inferred from
# the market question/marketId because the category column is NULL in MarketSnapshot.
FEE_RATE_CRYPTO = 0.07
FEE_RATE_POLITICS_FIN = 0.04
FEE_RATE_DEFAULT = 0.05

KEYWORDS = [
    (FEE_RATE_CRYPTO, ("btc", "bitcoin", "eth", "ethereum", "solana", "crypto", "token", "airdrop", "fdv", "market cap")),
    (FEE_RATE_POLITICS_FIN, ("election", "president", "senate", "congress", "nominee", "parliament", "prime minister",
                             "fed", "rate cut", "inflation", "cpi", "gdp", "recession", "tariff", "stock", "nasdaq",
                             "s&p", "earnings", "shutdown", "impeach", "poll", "vote", "governor", "mayor")),
]

UNRESOLVED_IDENTITY = ("", "unknown")


def fee_rate_for(text: str) -> float:
    t = (text or "").lower()
    for rate, words in KEYWORDS:
        if any(w in t for w in words):
            return rate
    return FEE_RATE_DEFAULT


def pnl_from(entry: float, won: bool, size: float) -> float:
    """Same arithmetic as src/lib/paper.ts computePnl: shares = size/entry."""
    if entry <= 0:
        return 0.0
    shares = size / entry
    return shares - size if won else -size


def load_rows(con, dedupe: bool):
    rows = con.execute(
        """
        SELECT pt.id, pt.botId, pt.venue, pt.walletAddress, pt.marketId, pt.outcome, pt.side,
               pt.entryPrice, pt.currentPrice, pt.simulatedPositionSize, pt.realizedPnl,
               pt.status, pt.openedAt, pt.closedAt,
               d.id, d.copyScore, d.confidence, d.walletQualityScore, d.categoryFitScore,
               d.entryTimingScore, d.spreadScore, d.liquidityScore, d.thesisScore,
               d.ruleSetVersion, d.simulatedPositionSize, d.decision,
               t.marketQuestion, t.marketCategory, t.detectedPrice, t.walletEntryPrice,
               t.size, t.timestamp
        FROM PaperTrade pt
        JOIN DecisionJournal d ON d.id = pt.decisionJournalId
        JOIN ObservedTrade t ON t.id = d.observedTradeId
        WHERE pt.status IN ('resolved','closed') AND pt.isDemo = 0
          AND pt.realizedPnl IS NOT NULL AND pt.entryPrice > 0 AND pt.entryPrice < 1
        ORDER BY pt.openedAt ASC
        """
    ).fetchall()

    if not dedupe:
        return rows, len(rows)

    # Duplicate accumulation rows: the same bet opened repeatedly (documented in
    # scripts/analyze-calibration.py --dedupe). Keep the first entry per position.
    seen = {}
    for r in rows:
        key = (r[1], r[3], r[4], r[5])  # bot, wallet, market, outcome
        if key not in seen:
            seen[key] = r
    return list(seen.values()), len(rows)


def snapshot_at_decision(con):
    """Latest MarketSnapshot at or before each decision (leakage-safe raw features)."""
    cache = {}
    rows = con.execute(
        "SELECT marketId, spread, liquidity, timeToResolution, volume, yesPrice, collectedAt "
        "FROM MarketSnapshot ORDER BY marketId, collectedAt ASC"
    ).fetchall()
    by_market = defaultdict(list)
    for m, spread, liq, ttr, vol, yes, ts in rows:
        by_market[m].append((ts, spread, liq, ttr, vol, yes))
    return by_market


def pick_snapshot(series, when_ms):
    """Last snapshot with collectedAt <= decision time (binary search)."""
    lo, hi, best = 0, len(series) - 1, None
    while lo <= hi:
        mid = (lo + hi) // 2
        if series[mid][0] <= when_ms:
            best = series[mid]
            lo = mid + 1
        else:
            hi = mid - 1
    return best


def fmt_ts(v):
    if v is None:
        return ""
    if isinstance(v, (int, float)):
        return datetime.fromtimestamp(v / 1000, tz=timezone.utc).isoformat()
    return str(v)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dedupe", dest="dedupe", action="store_true", default=True,
                    help="collapse duplicate accumulation rows (default ON)")
    ap.add_argument("--no-dedupe", dest="dedupe", action="store_false")
    args = ap.parse_args()

    if not os.path.exists(DB):
        print(f"DB not found: {DB}", file=sys.stderr)
        return 1
    con = sqlite3.connect(DB)
    rows, raw_count = load_rows(con, args.dedupe)
    snaps = snapshot_at_decision(con)
    con.close()

    header = [
        "trade_id", "bot_id", "venue", "rule_set_version", "decision", "opened_at", "closed_at",
        "wallet", "market_id", "outcome", "side", "market_question",
        "entry_price", "size_usd", "ttr_hours", "raw_spread", "raw_liquidity", "raw_volume",
        "snapshot_at",
        "copy_score", "confidence", "wallet_quality_score", "category_fit_score",
        "entry_timing_score", "spread_score", "liquidity_score", "thesis_score",
        "detected_price", "wallet_entry_price", "observed_size_usd",
        "y_win", "pnl_gross", "pnl_net_entry", "pnl_net_full", "fee_rate", "fee_entry_usd", "fee_exit_usd",
        "time_to_resolution_flag",
    ]

    out_rows = []
    stats = dict(no_snapshot=0, snapshots_used=0, venue=defaultdict(int))
    for r in rows:
        (pt_id, bot, venue, wallet, market, outcome, side, entry, cur, size, pnl, status,
         opened, closed, dj_id, cscore, conf, wq, cfit, etim, spr, liq, thes, rsv, dsize,
         decision, question, category, detected, wep, osize, ots) = r

        y_win = 1 if (pnl is not None and pnl > 0) else 0
        size = float(size or 10.0)
        entry = float(entry)

        text = f"{question or ''} {market or ''}"
        rate = fee_rate_for(text)
        shares = size / entry
        fee_entry = shares * rate * entry * (1 - entry)          # = size * rate * (1 - entry)
        exit_price = float(cur) if (status == "closed" and cur and 0 < cur < 1) else None
        fee_exit = shares * rate * exit_price * (1 - exit_price) if exit_price else 0.0
        # settlement (status='resolved') pays 0/1 with no trade -> no exit fee
        pnl_net_entry = float(pnl) - fee_entry
        pnl_net_full = float(pnl) - fee_entry - fee_exit

        when = opened if isinstance(opened, (int, float)) else 0
        snap = pick_snapshot(snaps.get(market, []), when)
        if snap is None:
            stats["no_snapshot"] += 1
            raw_spread = raw_liq = raw_ttr = raw_vol = ""
            snap_at = ""
        else:
            stats["snapshots_used"] += 1
            _, s_spread, s_liq, s_ttr, s_vol, _yes = snap
            snap_at = fmt_ts(snap[0])
            raw_spread = "" if s_spread is None else round(float(s_spread), 6)
            raw_liq = "" if s_liq is None else round(float(s_liq), 2)
            raw_ttr = "" if s_ttr is None else round(float(s_ttr), 3)
            raw_vol = "" if s_vol is None else round(float(s_vol), 2)
        stats["venue"][venue] += 1

        out_rows.append([
            pt_id, bot, venue, rsv, decision, fmt_ts(opened), fmt_ts(closed),
            wallet, market, outcome, side, (question or "")[:160].replace(",", ";"),
            round(entry, 6), round(size, 2), raw_ttr, raw_spread, raw_liq, raw_vol, snap_at,
            round(float(cscore), 4), round(float(conf), 4), round(float(wq), 4),
            round(float(cfit), 4), round(float(etim), 4), round(float(spr), 4),
            round(float(liq), 4), round(float(thes), 4),
            "" if detected is None else round(float(detected), 6),
            "" if wep is None else round(float(wep), 6),
            "" if osize is None else round(float(osize), 2),
            y_win, round(float(pnl), 4), round(pnl_net_entry, 4), round(pnl_net_full, 4),
            rate, round(fee_entry, 4), round(fee_exit, 4),
            "" if not rsv else "",
        ])

    os.makedirs(os.path.dirname(CSV_OUT), exist_ok=True)
    with open(CSV_OUT, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(out_rows)

    n = len(out_rows)
    wins = sum(r[30] for r in out_rows)
    gross = sum(r[31] for r in out_rows)
    net_e = sum(r[32] for r in out_rows)
    net_f = sum(r[33] for r in out_rows)
    days = sorted({str(r[5])[:10] for r in out_rows if r[5]})
    wallets = {r[7] for r in out_rows}
    markets = {r[8] for r in out_rows}
    bots = defaultdict(int)
    for r in out_rows:
        bots[r[1]] += 1

    manifest = dict(
        generated_at=datetime.now(timezone.utc).isoformat(),
        source="PaperTrade(resolved|closed, isDemo=0, 0<entryPrice<1) JOIN DecisionJournal JOIN ObservedTrade",
        dedupe="first entry per (bot, wallet, market, outcome)" if args.dedupe else "none",
        rows_raw=raw_count, rows_emitted=n,
        dropped_as_duplicate=(raw_count - n) if args.dedupe else 0,
        win_rate=round(wins / n, 4) if n else None,
        pnl_gross=round(gross, 2), pnl_net_entry=round(net_e, 2), pnl_net_full=round(net_f, 2),
        per_trade_gross=round(gross / n, 3) if n else None,
        per_trade_net_entry=round(net_e / n, 3) if n else None,
        per_trade_net_full=round(net_f / n, 3) if n else None,
        per_bot=dict(bots), per_venue=dict(stats["venue"]),
        wallets=len(wallets), markets=len(markets),
        first_day=days[0] if days else None, last_day=days[-1] if days else None,
        distinct_days=len(days),
        rows_without_prior_snapshot=stats["no_snapshot"],
        rows_with_snapshot=stats["snapshots_used"],
        targets=dict(y_win="realizedPnl > 0 for the copied leg",
                     pnl_net_entry="realizedPnl - entry-leg taker fee (ex-ante knowable)",
                     pnl_net_full="realizedPnl - entry fee - exit fee for status='closed' (all-taker upper bound)"),
        fee_model="shares * rate * p * (1-p); entry always, exit only when status='closed'; "
                  "rate by slug/question keyword (crypto .07, politics/finance .04, else .05)",
        csv=os.path.relpath(CSV_OUT, ROOT),
    )
    with open(MANIFEST, "w") as f:
        json.dump(manifest, f, indent=2)

    print(f"wrote {os.path.relpath(CSV_OUT, ROOT)}  rows={n} (raw {raw_count}, "
          f"dropped {manifest['dropped_as_duplicate']} dups)")
    print(f"win_rate={manifest['win_rate']}  per-trade gross ${manifest['per_trade_gross']} "
          f"net(entry-fee) ${manifest['per_trade_net_entry']} net(full) ${manifest['per_trade_net_full']}")
    print(f"wallets={len(wallets)} markets={len(markets)} days={len(days)} "
          f"({manifest['first_day']} -> {manifest['last_day']}) bots={dict(bots)}")
    print(f"snapshots: {stats['snapshots_used']} used, {stats['no_snapshot']} rows without a prior snapshot")
    print(f"wrote {os.path.relpath(MANIFEST, ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
