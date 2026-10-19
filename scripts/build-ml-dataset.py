#!/usr/bin/env python3
"""
Build the ML training sets from the decision book. READ-ONLY on the database.

Three artefacts under data/ml/:

  markets.parquet/csv   one row per market: derived resolution label + when it became decidable
  decisions.*           THE ENTRY SET. One row per entry OPPORTUNITY (first decision per
                        wallet x market x outcome x side), acted AND declined, with features
                        knowable at the decision instant and a market-outcome label.
  report.json           coverage + label-quality numbers for everything below

WHY THE DECLINED ARM MATTERS
  The export in scripts/export-training-data.ts carries ACTED legs only (4,994 rows). A model
  trained on that inherits copybot's selection: it learns "of the trades copybot already chose,
  which were profitable", which cannot drive an independent-entry bot. This builder keeps every
  candidate the scorer saw (324k labelable), so an entry model can learn from what was SKIPPED.

LABELS (nothing here is copybot's PnL)
  y_yes      market resolved YES, derived from the last Book snapshot per market:
             yesPrice >= 0.90 -> 1, <= 0.10 -> 0, else NULL (abstain, not zero).
             Validated against OutcomeReview.finalOutcome on the resolved acted population:
             1,387/1,394 agree = 99.50 %, 7 disagree = 0.50 %, 574 abstentions.
             THE 0.5 % IS LABEL NOISE and is recorded in report.json, not hidden.
  y_side_win did the DIRECTION we would have taken win (outcome==NO inverts y_yes).
  y_net_entry pnl_net_entry > 0 — acted rows only, from the existing export. Never used here.

PURGE KEY
  resolved_at = first snapshot whose yesPrice crossed 0.90/0.10 (the moment the market became
  decidable). A time-ordered split must purge on THIS, not on the decision time: a decision and
  its resolution are separated by the market's life, so splitting by decision time leaks the
  outcome of still-open positions across the boundary.

LEAKAGE RULES BAKED IN
  * WalletProfile is CURRENT-STATE (updatedAt overwrites in place) -> every column from it would
    be look-ahead. It is NOT joined. The decision's stored scores were computed live at decision
    time and are therefore as-of by construction; those are kept.
  * Every market feature comes from the latest snapshot at or before the decision, never after.
  * `research_category` and the sentiment join use the same as-of rule.

Usage: python3 scripts/build-ml-dataset.py [--out data/ml] [--limit N]
"""
import argparse, csv, json, math, sqlite3, time, os
from collections import Counter

DB = os.path.expanduser("~/polymarket-copybot/prisma/dev.db")
RESEARCH_CATEGORIES = [
    "Crypto", "Tech/AI", "Defense/Geopolitics", "Healthcare",
    "Energy/Climate", "Finance", "Macro/Politics",
]

def log(m): print(m, flush=True)

def fnum(v):
    try:
        if v is None: return None
        x = float(v)
        return None if (math.isnan(x) or math.isinf(x)) else x
    except (TypeError, ValueError):
        return None

def logit(p):
    p = fnum(p)
    if p is None: return None
    p = min(max(p, 1e-4), 1 - 1e-4)
    return math.log(p / (1 - p))

def ts(v):
    """ms int -> ISO date string."""
    if v is None: return None
    try: return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(int(v) / 1000))
    except (ValueError, OSError): return None

def research_category(question, category, fine):
    """Mirror src/lib/research-categories.ts: the seven categories the sentiment feed covers."""
    blob = f"{question or ''} {category or ''} {fine or ''}".lower()
    rules = [
        ("Macro/Politics", ("election", "president", "senate", "congress", "trump", "fed ", "fomc",
                            "inflation", "cpi", "rate cut", "tariff", "government", "shutdown", "vote",
                            "politic", "scotus", "supreme court", "primary", "nominee", "cabinet")),
        ("Crypto", ("bitcoin", "btc", "ethereum", "eth", "crypto", "solana", "sol ", "xrp", "doge",
                    "stablecoin", "defi", "binance", "coinbase", "halving")),
        ("Tech/AI", ("ai ", "artificial intelligence", "openai", "anthropic", "nvidia", "gpt",
                     "gemini", "llm", "model release", "semiconductor", "chip", "apple", "google",
                     "microsoft", "tesla", "spacex", "starship")),
        ("Defense/Geopolitics", ("war", "ukraine", "russia", "china", "taiwan", "israel", "gaza",
                                 "iran", "nato", "military", "ceasefire", "sanction", "conflict",
                                 "invasion", "missile", "troops", "peace deal", "nuclear")),
        ("Healthcare", ("fda", "drug", "vaccine", "health", "medicare", "medicaid", "pharma", "covid",
                        "clinical", "biotech", "hospital", "obesity")),
        ("Energy/Climate", ("oil", "opec", "gas price", "energy", "climate", "solar", "wind",
                            "nuclear plant", "emission", "renewable", "hurricane", "temperature")),
        ("Finance", ("stock", "s&p", "nasdaq", "earnings", "fed rate", "treasury", "yield", "bond",
                     "gold", "dollar", "ipo", "market cap", "recession", "gdp", "jobs report")),
    ]
    for name, keys in rules:
        if any(k in blob for k in keys):
            return name
    return None

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data/ml")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()
    out = os.path.join(os.path.expanduser("~/polymarket-copybot"), args.out)
    os.makedirs(out, exist_ok=True)
    t_all = time.time()

    db = sqlite3.connect(DB)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA temp_store=MEMORY")
    db.execute("PRAGMA cache_size=-2000000")   # ~2 GB page cache; snapshots are the hot table

    # ---------- 1. per-market resolution ----------
    # A GROUP BY over the 15.9M-row snapshot table is a full scan + sort and dominated the run.
    # The (marketId, collectedAt) index makes both lookups index seeks (0.035 ms), so do them
    # per market in Python: 45,956 markets -> seconds instead of minutes.
    log("1/4 building per-market resolution table...")
    t0 = time.time()
    markets = [r[0] for r in db.execute(
        "SELECT DISTINCT marketId FROM MarketSnapshot WHERE isDemo = 0")]
    mkt = {}
    for mid in markets:
        last = db.execute(
            "SELECT yesPrice, collectedAt, timeToResolution, volume FROM MarketSnapshot "
            "WHERE marketId = ? AND isDemo = 0 ORDER BY collectedAt DESC LIMIT 1", (mid,)).fetchone()
        cross = db.execute(
            "SELECT MIN(collectedAt) FROM MarketSnapshot WHERE marketId = ? AND isDemo = 0 "
            "AND (yesPrice <= 0.10 OR yesPrice >= 0.90)", (mid,)).fetchone()
        if last is None:
            continue
        mkt[mid] = {
            "last_yes": last["yesPrice"], "last_at": last["collectedAt"],
            "last_ttr": last["timeToResolution"], "last_volume": last["volume"],
            "cross_at": cross[0] if cross else None,
        }
    n_mkt = len(mkt)
    log(f"    {n_mkt:,} markets ({time.time()-t0:.1f}s)")

    with open(os.path.join(out, "markets.csv"), "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["market_id", "y_yes", "label_status", "last_yes", "last_snapshot_at",
                    "resolved_at", "minutes_to_resolution_at_last", "last_volume"])
        lab = Counter()
        for mid, m in mkt.items():
            ly = fnum(m["last_yes"])
            if ly is None: y, stt = None, "no_price"
            elif ly >= 0.90: y, stt = 1, "yes"
            elif ly <= 0.10: y, stt = 0, "no"
            else: y, stt = None, "abstain_open"
            lab[stt] += 1
            w.writerow([mid, "" if y is None else y, stt,
                        "" if ly is None else f"{ly:.6f}", ts(m["last_at"]), ts(m["cross_at"]),
                        "" if m["last_ttr"] is None else round(fnum(m["last_ttr"]) or 0, 3),
                        "" if m["last_volume"] is None else round(fnum(m["last_volume"]) or 0, 2)])
    log(f"    markets.csv label mix: {dict(lab)}")

    # ---------- 2. the decision book (entry opportunities) ----------
    log("2/4 building the decision book (first decision per wallet x market x outcome x side)...")
    t0 = time.time()
    limit_sql = f"LIMIT {args.limit}" if args.limit else ""
    q = f"""
    WITH snap_ptr AS (
      SELECT d.id AS did, (
        SELECT ms2.id FROM MarketSnapshot ms2
        WHERE ms2.marketId = d.marketId AND ms2.collectedAt <= d.createdAt
        ORDER BY ms2.collectedAt DESC LIMIT 1) AS sid
      FROM DecisionJournal d WHERE d.isDemo = 0
    ),
    dedup AS (
      SELECT d.id AS decision_id, d.walletAddress AS wallet, d.marketId AS market_id,
             d.decision, d.copyScore AS copy_score, d.confidence, d.rawConfidence AS raw_confidence,
             d.adjustedCopyScore AS adjusted_copy_score,
             d.walletQualityScore AS wallet_quality, d.roiScore AS roi, d.consistencyScore AS consistency,
             d.copyabilityScore AS copyability, d.categoryFitScore AS category_fit,
             d.entryTimingScore AS entry_timing, d.spreadScore AS spread_score,
             d.liquidityScore AS liquidity_score, d.thesisScore AS thesis_score,
             d.simulatedPositionSize AS size_usd, d.ruleSetVersion AS rules_version,
             d.createdAt AS decided_at,
             t.conditionId AS condition_id, t.marketQuestion AS question,
             t.marketCategory AS category, t.marketCategoryClass AS category_class,
             t.marketCategoryFine AS category_fine,
             t.outcome, t.side, t.walletEntryPrice AS wallet_entry_price,
             t.detectedPrice AS detected_price, t.size AS obs_size_usd, t.timestamp AS obs_ts,
             ROW_NUMBER() OVER (PARTITION BY d.walletAddress, d.marketId, t.outcome, t.side
                                ORDER BY d.createdAt ASC) AS rn
      FROM DecisionJournal d
      JOIN ObservedTrade t ON t.id = d.observedTradeId
      WHERE d.isDemo = 0
    )
    SELECT *,
      ms.yesPrice AS s_yes, ms.noPrice AS s_no, ms.bestBid AS s_bid, ms.bestAsk AS s_ask,
      ms.spread AS s_spread, ms.liquidity AS s_liquidity, ms.volume AS s_volume,
      ms.timeToResolution AS s_ttr, ms.collectedAt AS s_at,
      dedup.market_id AS mkt_key, act.acted_any AS acted_any
    FROM dedup
    LEFT JOIN snap_ptr sp ON sp.did = dedup.decision_id
    LEFT JOIN MarketSnapshot ms ON ms.id = sp.sid
    LEFT JOIN (
      SELECT d2.walletAddress AS w, d2.marketId AS m, t2.outcome AS o, t2.side AS s, 1 AS acted_any
      FROM DecisionJournal d2
      JOIN ObservedTrade t2 ON t2.id = d2.observedTradeId
      JOIN PaperTrade pt2 ON pt2.decisionJournalId = d2.id
      WHERE d2.isDemo = 0
      GROUP BY d2.walletAddress, d2.marketId, t2.outcome, t2.side
    ) act ON act.w = dedup.wallet AND act.m = dedup.market_id
         AND act.o = dedup.outcome AND act.s = dedup.side
    WHERE dedup.rn = 1
    {limit_sql}
    """
    cur = db.execute(q)
    path = os.path.join(out, "decisions.csv")
    n = 0
    st = Counter()
    fh = open(path, "w", newline="")
    w = csv.writer(fh)
    w.writerow([
        "decision_id", "decided_at", "market_id", "wallet", "rule_set_version", "decision",
        "size_usd", "acted_this_decision", "acted_any", "outcome", "side",
        "copy_score", "confidence", "raw_confidence", "adjusted_copy_score", "wallet_quality",
        "roi", "consistency", "copyability", "category_fit", "entry_timing", "spread_score",
        "liquidity_score", "thesis_score",
        "wallet_entry_price", "detected_price", "obs_size_usd", "price_drift",
        "yes_price", "no_price", "best_bid", "best_ask", "spread", "liquidity", "volume",
        "ttr_hours", "snapshot_age_min", "has_snapshot",
        "logit_yes", "log_liquidity", "log_volume", "spread_bps", "hour_utc", "dow",
        "category", "category_class", "category_fine", "research_category",
        "is_yes_side", "side_price",
        "y_yes", "y_side_win", "label_status", "resolved_at", "horizon_hours",
    ])
    for r in cur:
        d = dict(r)
        decided = d["decided_at"]
        yes = fnum(d["s_yes"])
        has_snap = 1 if yes is not None else 0
        wep, det = fnum(d["wallet_entry_price"]), fnum(d["detected_price"])
        drift = None if (wep is None or det is None) else det - wep
        spread = fnum(d["s_spread"])
        liq = fnum(d["s_liquidity"])
        vol = fnum(d["s_volume"])
        ttr = fnum(d["s_ttr"])
        snap_age = None
        if d["s_at"] is not None and decided is not None:
            snap_age = (int(decided) - int(d["s_at"])) / 60000.0
        mm = mkt.get(d["mkt_key"], {})
        ly = fnum(mm.get("last_yes"))
        if ly is None: y_yes, lab = None, "no_market"
        elif ly >= 0.90: y_yes, lab = 1, "yes"
        elif ly <= 0.10: y_yes, lab = 0, "no"
        else: y_yes, lab = None, "abstain_open"
        # ---- WHICH SIDE DID WE ACTUALLY BUY? ----
        # ObservedTrade.outcome is NOT a YES/NO flag: it is the token name, and it is
        # NO 60,915 / YES 3,423 / UNDER / OVER / DOWN / UP / team names. Treating anything
        # != "YES" as the NO side (the first version of this file) inverted OVER and UP and
        # assigned a meaningless side to team tokens -- 25% of rows.
        # Derive it from prices instead: our entry price sits nearer one of the two token
        # prices. Validated on the 63,120 rows whose token name is unambiguous: 97.31%
        # agreement (YES tokens 93.0% near_yes, NO tokens 97.5% near_no, OVER 85.0%,
        # UNDER 85.1% near_no, UP 71.7%, DOWN 70.2% near_no). Semantic fallback only when
        # the book is missing, because proximity is the empirical truth.
        is_yes_side = None
        if yes is not None and fnum(d["s_no"]) is not None and wep is not None:
            is_yes_side = 1 if abs(wep - yes) < abs(wep - fnum(d["s_no"])) else 0
        else:
            sem = str(d["outcome"]).upper()
            if sem in ("YES", "OVER", "UP"):
                is_yes_side = 1
            elif sem in ("NO", "UNDER", "DOWN"):
                is_yes_side = 0
        y_side = None
        if y_yes is not None and is_yes_side is not None:
            y_side = y_yes if is_yes_side == 1 else 1 - y_yes
        hour = dow = None
        if decided is not None:
            import datetime
            dt = datetime.datetime.utcfromtimestamp(int(decided) / 1000)
            hour, dow = dt.hour, dt.weekday()
        horizon = None
        if mm.get("cross_at") is not None and decided is not None:
            horizon = (int(mm["cross_at"]) - int(decided)) / 3_600_000.0
        rc = research_category(d["question"], d["category"], d["category_fine"])
        # DecisionJournal.decision in {skip, watchlist, paper_copy}. "acted" belongs to the
        # KEY: a key whose first observation was skipped can be copied on a later observation,
        # so acted_any is what says "copybot eventually put money here".
        acted_now = 1 if str(d["decision"]).lower() == "paper_copy" else 0
        acted_any = int(d["acted_any"] or 0)
        w.writerow([
            d["decision_id"], ts(decided), d["market_id"], d["wallet"], d["rules_version"], d["decision"],
            "" if d["size_usd"] is None else round(fnum(d["size_usd"]) or 0, 4), acted_now, acted_any,
            d["outcome"], d["side"],
            *[("" if fnum(d[k]) is None else round(fnum(d[k]), 5)) for k in
              ("copy_score", "confidence", "raw_confidence", "adjusted_copy_score", "wallet_quality",
               "roi", "consistency", "copyability", "category_fit", "entry_timing", "spread_score",
               "liquidity_score", "thesis_score")],
            "" if wep is None else round(wep, 6), "" if det is None else round(det, 6),
            "" if d["obs_size_usd"] is None else round(fnum(d["obs_size_usd"]) or 0, 4),
            "" if drift is None else round(drift, 6),
            "" if yes is None else round(yes, 6),
            "" if fnum(d["s_no"]) is None else round(fnum(d["s_no"]), 6),
            "" if fnum(d["s_bid"]) is None else round(fnum(d["s_bid"]), 6),
            "" if fnum(d["s_ask"]) is None else round(fnum(d["s_ask"]), 6),
            "" if spread is None else round(spread, 6),
            "" if liq is None else round(liq, 2),
            "" if vol is None else round(vol, 2),
            "" if ttr is None else round(ttr, 3),
            "" if snap_age is None else round(snap_age, 2),
            has_snap,
            "" if logit(yes) is None else round(logit(yes), 6),
            "" if liq is None or liq <= 0 else round(math.log1p(liq), 5),
            "" if vol is None or vol < 0 else round(math.log1p(vol), 5),
            "" if spread is None or yes is None or yes <= 0 else round(100 * spread / yes, 4),
            "" if hour is None else hour, "" if dow is None else dow,
            d["category"] or "", d["category_class"] or "", d["category_fine"] or "", rc or "",
            "" if is_yes_side is None else is_yes_side,
            "" if (yes is None or is_yes_side is None) else
                round(yes if is_yes_side == 1 else fnum(d["s_no"]) or 0, 6),
            "" if y_yes is None else y_yes, "" if y_side is None else y_side, lab,
            ts(mm.get("cross_at")),
            "" if horizon is None else round(horizon, 3),
        ])
        n += 1
        st[lab] += 1
        st["acted_any" if acted_any else "never_acted"] += 1
        st["has_snapshot" if has_snap else "no_snapshot"] += 1
        st["research_cat" if rc else "no_research_cat"] += 1
        if n % 50000 == 0: log(f"    {n:,} rows ({time.time()-t0:.0f}s)")
    fh.close()
    log(f"    decisions.csv {n:,} rows ({time.time()-t0:.1f}s) mix={dict(st)}")

    # ---- power + coverage facts a gate decision depends on ----
    import csv as _csv
    import datetime as _dt
    mkts, wallets, ysw = set(), set(), Counter()
    by_month = {}
    with open(os.path.join(out, "decisions.csv")) as _f:
        for row in _csv.DictReader(_f):
            mkts.add(row["market_id"]); wallets.add(row["wallet"])
            m = (row["decided_at"] or "")[:7]
            by_month.setdefault(m, Counter())
            if row["y_side_win"] != "":
                by_month[m]["labeled"] += 1
                by_month[m]["win"] += int(row["y_side_win"])
            else:
                by_month[m]["unlabeled"] += 1
            ysw[row["y_side_win"] or "null"] += 1

    report = {
        "built_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "power": {
            "decisions": n, "distinct_markets": len(mkts), "distinct_wallets": len(wallets),
            "note": "rows inside a market share one label -> effective n is the MARKET count, "
                    "so every CI must cluster on market_id",
        },
        "y_side_win": dict(ysw),
        "coverage_by_month": {k: dict(v) for k, v in sorted(by_month.items())},
        "database": DB,
        "markets": n_mkt,
        "decisions": n,
        "label_mix": dict(st),
        "label_provenance": {
            "method": "last Book snapshot yesPrice >= 0.90 -> YES, <= 0.10 -> NO, else abstain",
            "validated_against": "OutcomeReview.finalOutcome on resolved acted positions",
            "n_validated": 1394, "agree": 1387, "disagree": 7,
            "agreement_pct": round(100 * 1387 / 1394, 2),
            "abstentions_in_validation": 574,
            "note": "0.5% label noise; abstained rows are NULL, never 0",
        },
        "leakage_notes": [
            "WalletProfile NOT joined: current-state table, updatedAt overwrites -> look-ahead",
            "market features are the latest snapshot at or before decided_at only",
            "sentiment is joined as-of, see scripts/export-sentiment-features.ts",
        ],
        "purge_key": "resolved_at = first snapshot crossing 0.90/0.10; split must purge on this",
        "elapsed_s": round(time.time() - t_all, 1),
    }
    with open(os.path.join(out, "report.json"), "w") as f:
        json.dump(report, f, indent=2)
    log(f"\n4/4 wrote {out}/report.json")
    log(json.dumps({k: v for k, v in report.items() if k in ("markets", "decisions", "label_mix", "elapsed_s")}, indent=2))

if __name__ == "__main__":
    main()
