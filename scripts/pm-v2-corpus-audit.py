#!/usr/bin/env python3
"""Audit our recorder against an EXTERNAL prediction-market corpus. READ-ONLY on the database.

Card `ml-feed-recorder-audit-external-pm` (Lane B, measurement). The card named four Kaggle/GitHub
corpora and pre-registered one rule. Two things had to be settled before anything was built, and
both are recorded here because they change what the card can mean:

1. THE CARD'S NAMED CORPORA ARE NOT REACHABLE (probed 2026-11-16T20:0xZ, from this host):
     manja316/crypto-prediction-market-signals   Kaggle 403 "datasets.get was denied" (no
                                                 ~/.kaggle/kaggle.json exists)
     thomaswmitch/kalshi-prediction-markets-*    Kaggle 403 (same); github.com path 404
     lowskillcoding/pdata-prediction-markets     github.com 404
     iiiitips/prediction-market-pro-stats        REACHABLE (HF, cc-by-4.0, refreshed 2026-11-16)
                                                 but aggregate-only: 4 CSVs of band/sport win rates
                                                 and pro leaderboards, NO per-market rows and no
                                                 resolution labels -- nothing to join a leg to.
   The archive we already hold (Polymarket-v1, /Volumes/Storage/pm-data) is NOT a substitute: it
   ends 2026-04-28, and our first paper trade is 2026-06-18.
   THE REPLACEMENT CORPUS IS TimeSeventeen/Polymarket-v2 (HF, cc-by-4.0, mirrored as
   xfox25/Polymarket-v2), which we verified covers OUR era: daily `OrderFilled` partitions to
   2026-11-12 and cleaned `daily_aligned` partitions (per-fill: condition_id, market_slug,
   outcome_label, winning_outcome_label, resolution_status, price, usdc_amount, fee_usdc) to
   2026-11-10. That is an independent on-chain read of the same venue, which is what the card
   needed.

2. THE CARD'S CITATION OF "$0.0496 pnl_net_full export drift on 7,702 early-closed positions" IS
   ALREADY MEASURED, on card `export-reconciliation-localisable` (measured 2026-10-29), where the
   drift was localised to the EXIT-side fee leg of early-closed rows. It is not re-derived here
   and this script does not touch it.

WHAT THIS MEASURES (every number carries population + clock + level)

  ARM 1 COVERAGE      how much of our book the corpus can even see: legs and distinct markets
                      joined by market_slug, by status.
  ARM 2 VERDICT       our settled verdict, read from PaperTrade.currentPrice (0/1 written by
                      resolvePaperTrade) vs the corpus' winning_outcome_label, compared with the
                      SAME rule the bot uses (src/lib/resolution.ts didOutcomeWin: normalised
                      label equality; a binary-vs-named label pair is UNDETERMINABLE, never a
                      disagreement). Level = leg, clock = resolvedAt.
  ARM 3 SETTLEMENT PNL  the PnL effect of the verdict alone: computePnl(entryPrice, corpus
                      verdict) minus computePnl(entryPrice, our verdict), i.e. entry price and
                      size held FIXED so only the verdict can move the number. This deliberately
                      does NOT re-price fill-aware booking: legs stamped 'unfilled' still carry
                      pre-flag realizedPnl in the ledger (measured below and printed separately),
                      which is a Lane A booking question, not a recorder defect.
  ARM 4 LABEL SET     legs whose recorded outcome label matches NO token the corpus ever printed
                      for that market. Stated as a LOWER bound: a token with zero fills cannot
                      appear, so absence is only definitive when the market's other tokens are
                      present and the leg's third label is not one of them.
  ARM 5 ENTRY PRICE   recorded entryPrice vs the venue's OWN print on the same token at or before
                      openedAt (staleness <= 900 s, no look-ahead), in cents, by lane. Expected
                      signs are stated in the output: BANKROLL_200 books intent-2c (maker model,
                      card c200-maker-fill-assumption), STANDARD books the quote, so a taker pays
                      above it.

DECISION RULE (the card's own, transplanted to the corpus that is reachable): investigate the
recorder if the two reads differ > 2% on >= 100 overlapping markets; REFUTED (instrument retires)
if <= 0.5% on >= 100. Both the PnL basis and the verdict basis are reported so the rule cannot be
satisfied by choosing the flattering one.

RUN
  /Volumes/Storage/pm-data/.venv/bin/python scripts/pm-v2-corpus-audit.py            # measure
  /Volumes/Storage/pm-data/.venv/bin/python scripts/pm-v2-corpus-audit.py --self-test
  ./scripts/pm-v2-corpus-audit.py --self-test   (system python is fine for the self-test: it
                                                 uses an in-memory duckdb only if duckdb exists)
  The corpus cache is NOT in the repo (2.9 GB). Populate /Volumes/Storage/pm-data/v2-audit-cache
  with daily_aligned partitions named da-YYYY_MM_DD.parquet; --cache overrides the path. The run
  fails loud when the cache is missing rather than reporting an empty measurement.
"""
from __future__ import annotations

import argparse
import glob
import json
import random
import urllib.request
import os
import sqlite3
import sys
import time

ROOT = os.path.expanduser("~/polymarket-copybot")
DB = os.path.join(ROOT, "prisma/dev.db")
CACHE = "/Volumes/Storage/pm-data/v2-audit-cache"
OUT = os.path.join(ROOT, "data/pm-v2-corpus-audit.json")

# The card's own thresholds, restated.
INVESTIGATE_PCT = 2.0
REFUTE_PCT = 0.5
MIN_MARKETS = 100
# No look-ahead: the venue print must be at or before the entry, and no staler than this.
STALE_S = 900


# --------------------------------------------------------------------------------------------------
# label normalisation -- the SAME transform as src/lib/resolution.ts normalizeOutcomeLabel
# --------------------------------------------------------------------------------------------------
def norm(label: str | None) -> str:
    return "".join(ch for ch in (label or "").upper() if ch.isalnum())


def is_binary(n: str) -> bool:
    return n in ("YES", "NO")


def did_outcome_win(our_label: str | None, winning_label: str | None) -> int | None:
    """1 = our token won, 0 = lost, None = undeterminable (mirror of didOutcomeWin)."""
    want = norm(our_label)
    if not want:
        return None
    winner = norm(winning_label)
    if winner:
        if winner == want:
            return 1
        if is_binary(winner) != is_binary(want):
            return None
        return 0
    return None


def entry_diff_c(entry_price: float, venue_price: float) -> float:
    """SIGN CONVENTION (stated once, used everywhere): our entry MINUS the venue print, in cents.
    POSITIVE = we booked a price WORSE than the tape actually traded."""
    return round((entry_price - venue_price) * 100, 2)


def compute_pnl(entry_price: float, final_price: float, size_usd: float) -> float:
    if not entry_price or entry_price <= 0:
        return 0.0
    shares = size_usd / entry_price
    return round((shares * final_price - size_usd) * 100) / 100


# --------------------------------------------------------------------------------------------------
# data loading
# --------------------------------------------------------------------------------------------------
def load_legs(db_path: str) -> list[dict]:
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    rows = con.execute(
        """SELECT id, botId, marketId, outcome, side, entryPrice, currentPrice,
                  simulatedPositionSize, realizedPnl, status, fillStatus, fillBasis,
                  openedAt, closedAt, resolvedAt
           FROM PaperTrade
           WHERE isDemo = 0 AND status IN ('resolved', 'closed')"""
    ).fetchall()
    con.close()
    return [dict(r) for r in rows]


def arm_coverage(con, legs_rows: int, legs_markets: int, joined_rows: int, joined_markets: int) -> dict:
    return {
        "legs_in_book": legs_rows,
        "markets_in_book": legs_markets,
        "legs_joined": joined_rows,
        "markets_joined": joined_markets,
        "leg_coverage_pct": round(100.0 * joined_rows / legs_rows, 2) if legs_rows else None,
        "market_coverage_pct": round(100.0 * joined_markets / legs_markets, 2) if legs_markets else None,
    }


def corpus_markets(con, cache: str, slugs: set[str]) -> dict[str, dict]:
    """slug -> {condition_ids, win, tokens, raw_by_norm, fills}. One venue market, one honest read."""
    if not slugs:
        return {}
    con.execute("CREATE OR REPLACE TABLE _slugs(slug VARCHAR)")
    con.executemany("INSERT INTO _slugs VALUES (?)", [(s,) for s in slugs])
    rows = con.execute(
        """SELECT c.market_slug,
                  any_value(c.condition_id) condition_id,
                  max(c.winning_outcome_label) win,
                  max(c.resolution_status) rs,
                  c.outcome_label raw,
                  count(*) fills
           FROM read_parquet(?) c
           JOIN _slugs s ON s.slug = c.market_slug
           WHERE c.market_slug IS NOT NULL
           GROUP BY c.market_slug, c.outcome_label""",
        [os.path.join(cache, "da-*.parquet")],
    ).fetchall()
    markets: dict[str, dict] = {}
    for slug, condition_id, win, rs, raw, fills in rows:
        m = markets.setdefault(
            slug,
            {
                "condition_id": condition_id,
                "condition_ids": set(),
                "win": None,
                "resolution_status": None,
                "tokens": set(),
                "raw_by_norm": {},
                "fills": 0,
            },
        )
        if condition_id:
            m["condition_ids"].add(condition_id)
        if win is not None and (m["win"] is None or (not norm(m["win"]) and norm(win))):
            m["win"] = win
        if rs is not None:
            m["resolution_status"] = rs
        n = norm(raw)
        if n:
            m["tokens"].add(n)
            m["raw_by_norm"].setdefault(n, set()).add(raw)
        m["fills"] += fills or 0
    return markets


def run_arms(con, legs: list[dict], markets: dict[str, dict]) -> dict:
    """Pure measurement over in-memory tables -- the self-test drives this same function."""
    verdicts = []
    label_misses = []
    for leg in legs:
        mk = markets.get(leg["marketId"])
        if mk is None:
            continue
        ours = None
        cp = leg["currentPrice"]
        if cp is not None and cp >= 0.99:
            ours = 1
        elif cp is not None and cp <= 0.01:
            ours = 0
        theirs = did_outcome_win(leg["outcome"], mk["win"])
        label_n = norm(leg["outcome"])
        label_seen = label_n in mk["tokens"] if label_n else None
        if label_seen is False:
            label_misses.append(
                {
                    "marketId": leg["marketId"],
                    "outcome": leg["outcome"],
                    "tokens_seen": sorted(mk["tokens"]),
                    "definitive": len(mk["tokens"]) >= 2,
                    "realizedPnl": leg["realizedPnl"],
                }
            )
        if leg["status"] != "resolved" or ours is None or theirs is None:
            continue
        verdicts.append(
            {
                "id": leg["id"],
                "botId": leg["botId"],
                "marketId": leg["marketId"],
                "outcome": leg["outcome"],
                "winningLabel": mk["win"],
                "ours": ours,
                "theirs": theirs,
                "entryPrice": leg["entryPrice"],
                "size": leg["simulatedPositionSize"],
                "realizedPnl": leg["realizedPnl"],
                "fillStatus": leg["fillStatus"],
                "resolvedAt": leg["resolvedAt"],
            }
        )

    disagree = [v for v in verdicts if v["ours"] != v["theirs"]]
    market_keys = {v["marketId"] for v in verdicts}
    disagree_markets = {v["marketId"] for v in disagree}

    delta = 0.0
    for v in verdicts:
        delta += compute_pnl(v["entryPrice"], float(v["theirs"]), v["size"]) - compute_pnl(
            v["entryPrice"], float(v["ours"]), v["size"]
        )
    booked = sum(v["realizedPnl"] or 0.0 for v in verdicts)

    return {
        "verdict": {
            "knowable_legs": len(verdicts),
            "knowable_markets": len(market_keys),
            "agree_legs": len(verdicts) - len(disagree),
            "disagree_legs": len(disagree),
            "disagree_leg_pct": round(100.0 * len(disagree) / len(verdicts), 2) if verdicts else None,
            "disagree_markets": len(disagree_markets),
            "disagree_market_pct": round(100.0 * len(disagree_markets) / len(market_keys), 2)
            if market_keys
            else None,
            "disagreements": disagree,
        },
        "settlement_pnl": {
            "booked_on_population": round(booked, 2),
            "delta_from_verdict_only": round(delta, 2),
            "delta_pct_of_abs_booked": round(100.0 * abs(delta) / abs(booked), 2) if booked else None,
        },
        "label_set": {
            "legs_with_unseen_label": len(label_misses),
            "definitive": len([m for m in label_misses if m["definitive"]]),
            "detail": label_misses,
        },
    }


def arm_price(con, legs: list[dict], markets: dict[str, dict], fills_glob: str) -> dict:
    """Recorded entry price vs the venue's own print on the SAME token, at or before openedAt.

    The join is on the corpus' own raw outcome_label strings (collected per market in
    corpus_markets), so nothing here re-normalises a label in SQL and nothing can drift.
    """
    rows = []
    for leg in legs:
        mk = markets.get(leg["marketId"])
        if mk is None or leg["openedAt"] is None:
            continue
        n = norm(leg["outcome"])
        raws = mk["raw_by_norm"].get(n)
        if not raws:
            continue
        for raw in raws:
            for cid in mk["condition_ids"]:
                rows.append(
                    {
                        "id": leg["id"],
                        "botId": leg["botId"],
                        "status": leg["status"],
                        "entryPrice": leg["entryPrice"],
                        "condition_id": cid,
                        "raw": raw,
                        "open_s": int(leg["openedAt"] / 1000),
                    }
                )
    if not rows:
        return {"legs_with_venue_read": 0}
    con.execute("CREATE OR REPLACE TABLE _pxlegs(id VARCHAR, botId VARCHAR, status VARCHAR, entryPrice DOUBLE, condition_id VARCHAR, raw VARCHAR, open_s BIGINT)")
    con.executemany("INSERT INTO _pxlegs VALUES (?,?,?,?,?,?,?)", [
        (r["id"], r["botId"], r["status"], float(r["entryPrice"]), r["condition_id"], r["raw"], r["open_s"]) for r in rows
    ])
    con.execute(
        f"""CREATE OR REPLACE TABLE _px AS
        SELECT j.id, any_value(j.botId) botId, any_value(j.status) status,
               any_value(j.entryPrice) entryPrice,
               arg_max(f.price, f.block_timestamp) venue_px,
               count(*) nfills
        FROM _pxlegs j
        JOIN read_parquet('{fills_glob}') f
          ON f.condition_id = j.condition_id
         AND f.outcome_label = j.raw
         AND f.block_timestamp BETWEEN j.open_s - {STALE_S} AND j.open_s
        GROUP BY j.id"""
    )
    stats = con.execute(
        """SELECT botId, count(*) n,
                  round(median((entryPrice - venue_px) * 100), 2) med_c,
                  round(avg((entryPrice - venue_px) * 100), 2) mean_c,
                  round(quantile_cont((entryPrice - venue_px) * 100, 0.1), 2) p10_c,
                  round(quantile_cont((entryPrice - venue_px) * 100, 0.9), 2) p90_c,
                  round(100.0 * sum(CASE WHEN abs((entryPrice - venue_px) * 100) <= 1 THEN 1 ELSE 0 END) / count(*), 1) within_1c_pct
           FROM _px GROUP BY botId ORDER BY n DESC"""
    ).fetchall()
    total = con.execute("SELECT count(*) FROM _px").fetchone()[0]
    return {
        "legs_considered": len({r["id"] for r in rows}),
        "legs_with_venue_read": total,
        "stale_seconds_max": STALE_S,
        "sign_convention": "diff = (our entryPrice - venue print) in cents; POSITIVE = we booked WORSE than the tape traded",
        "by_lane": [
            {
                "botId": s[0],
                "n": s[1],
                "median_c": s[2],
                "mean_c": s[3],
                "p10_c": s[4],
                "p90_c": s[5],
                "within_1c_pct": s[6],
            }
            for s in stats
        ],
    }


def validate_corpus(markets: dict[str, dict], n: int, seed: int = 20261116) -> dict:
    """Does the corpus' winning label agree with the VENUE's own token winner?

    The audit's whole force rests on the corpus being right, so it is never assumed: a seeded
    random sample of markets the corpus calls decided is re-read from CLOB
    /markets/<conditionId> -> tokens[].winner (keyless). Network, so it is a flag, not the default.
    """
    pool = [m for m, v in markets.items() if norm(v["win"]) and v["condition_ids"]]
    random.seed(seed)
    sample = random.sample(pool, min(n, len(pool)))
    agree = mismatch = unreadable = 0
    detail = []
    for slug in sample:
        mk = markets[slug]
        cid = sorted(mk["condition_ids"])[0]
        try:
            req = urllib.request.Request(
                f"https://clob.polymarket.com/markets/{cid}",
                headers={"user-agent": "copybot-research/0.1", "accept": "application/json"},
            )
            d = json.load(urllib.request.urlopen(req, timeout=20))
            winners = [t.get("outcome") for t in d.get("tokens", []) if t.get("winner")]
            if not winners:
                unreadable += 1
                detail.append({"market": slug, "reason": "venue publishes no winner"})
            elif norm(winners[0]) == norm(mk["win"]):
                agree += 1
            else:
                mismatch += 1
                detail.append(
                    {
                        "market": slug,
                        "corpus_win": mk["win"],
                        "venue_win": winners[0],
                        "venue_tokens": [t.get("outcome") for t in d.get("tokens", [])],
                    }
                )
        except Exception as exc:  # network failure is reported, never counted as agreement
            unreadable += 1
            detail.append({"market": slug, "reason": f"read failed: {exc}"[:120]})
        time.sleep(0.25)
    return {
        "sample": len(sample),
        "pool": len(pool),
        "seed": seed,
        "agree": agree,
        "mismatch": mismatch,
        "unreadable": unreadable,
        "basis": "one market, seeded random draw from the corpus-decided markets our book holds; venue = CLOB tokens[].winner",
        "detail": detail,
    }


def apply_rule(v: dict) -> dict:
    m = v["knowable_markets"]
    pct_leg = v["disagree_leg_pct"]
    pct_mkt = v["disagree_market_pct"]
    if m < MIN_MARKETS:
        verdict = "INSUFFICIENT_DATA"
        why = f"{m} overlapping markets < the card's {MIN_MARKETS} floor"
    elif pct_leg is not None and pct_leg > INVESTIGATE_PCT:
        verdict = "INVESTIGATE_RECORDER"
        why = f"{pct_leg}% of knowable legs disagree (> {INVESTIGATE_PCT}%) on {m} markets"
    elif pct_leg is not None and pct_leg <= REFUTE_PCT:
        verdict = "REFUTED_INSTRUMENT_RETIRES"
        why = f"{pct_leg}% of knowable legs disagree (<= {REFUTE_PCT}%) on {m} markets"
    else:
        verdict = "INCONCLUSIVE"
        why = f"{pct_leg}% falls between {REFUTE_PCT}% and {INVESTIGATE_PCT}% on {m} markets"
    return {"verdict": verdict, "reason": why, "market_pct": pct_mkt, "leg_pct": pct_leg}


# --------------------------------------------------------------------------------------------------
# live measurement
# --------------------------------------------------------------------------------------------------
def resolve_disputes(markets: dict[str, dict], disagreements: list[dict]) -> list[dict]:
    """For every disagreeing market, ask the VENUE which token won and say whose side is wrong.

    A disagreement between our book and the corpus is not evidence against either until the
    authoritative read is in: CLOB tokens[].winner is that read. Bounded by the number of
    disagreements, which is expected to be small -- a large number here is itself the finding.
    """
    out = []
    for slug in sorted({d["marketId"] for d in disagreements}):
        mk = markets[slug]
        cid = sorted(mk["condition_ids"])[0]
        entry = {"market": slug, "corpus_win": mk["win"]}
        try:
            req = urllib.request.Request(
                f"https://clob.polymarket.com/markets/{cid}",
                headers={"user-agent": "copybot-research/0.1", "accept": "application/json"},
            )
            d = json.load(urllib.request.urlopen(req, timeout=20))
            toks = [(t.get("outcome"), bool(t.get("winner"))) for t in d.get("tokens", [])]
            entry["venue_tokens"] = [t[0] for t in toks]
            entry["venue_win"] = next((t[0] for t in toks if t[1]), None)
            legs = [x for x in disagreements if x["marketId"] == slug]
            entry["legs"] = legs
            venue_n = norm(entry["venue_win"])
            entry["our_legs_right"] = [x["outcome"] for x in legs if norm(x["outcome"]) == venue_n]
            entry["our_legs_wrong"] = [x["outcome"] for x in legs if norm(x["outcome"]) != venue_n]
            entry["corpus_right"] = venue_n == norm(mk["win"])
            entry["booked_on_wrong_legs"] = round(
                sum(x["realizedPnl"] or 0.0 for x in legs if norm(x["outcome"]) != venue_n), 2
            )
        except Exception as exc:
            entry["venue_read_error"] = str(exc)[:120]
        out.append(entry)
        time.sleep(0.25)
    return out


def measure(cache: str, validate: int = 0) -> dict:
    try:
        import duckdb
    except ImportError:
        sys.exit("duckdb missing -- run with /Volumes/Storage/pm-data/.venv/bin/python")

    files = sorted(glob.glob(os.path.join(cache, "da-*.parquet")))
    if not files:
        sys.exit(
            f"corpus cache is empty at {cache}\n"
            "  the measurement refuses to run on an absent corpus (an empty join is not a refutation).\n"
            "  populate with daily_aligned partitions named da-YYYY_MM_DD.parquet."
        )

    legs = load_legs(DB)
    con = duckdb.connect()
    con.execute("SET threads=4")
    con.execute("SET memory_limit='4GB'")

    # MARKET IDENTITY, read only for the slugs our book actually holds (small by construction).
    # Labels are normalised in PYTHON, with the same function resolution.ts uses -- an ASCII-only
    # SQL normaliser silently mismatched on diacritics ('Leviatán' -> 'LEVIATN' vs 'LEVIATÁN') and
    # manufactured 10 phantom label misses on the first read of this script.
    markets = corpus_markets(con, cache, {l["marketId"] for l in legs})
    joined_legs = [l for l in legs if l["marketId"] in markets]
    cov = arm_coverage(
        con,
        legs_rows=len(legs),
        legs_markets=len({l["marketId"] for l in legs}),
        joined_rows=len(joined_legs),
        joined_markets=len({l["marketId"] for l in joined_legs}),
    )

    res = run_arms(con, legs, markets)
    res["coverage"] = cov
    res["rule"] = apply_rule(res["verdict"])

    # printed separately: legs stamped unfilled that still carry a booked number (Lane A booking)
    unfilled_booked = [l for l in joined_legs if l["fillStatus"] == "unfilled" and (l["realizedPnl"] or 0) != 0]
    res["booking_note"] = {
        "unfilled_legs_with_nonzero_booked_pnl": len(unfilled_booked),
        "sum": round(sum(l["realizedPnl"] or 0 for l in unfilled_booked), 2),
        "basis": "fillStatus='unfilled' but realizedPnl != 0 -- pre-flag rows; the fill-aware booking flip is a Lane A question, not a recorder defect",
    }

    res["price"] = arm_price(con, legs, markets, os.path.join(cache, "da-*.parquet"))
    res["corpus"] = {
        "dataset": "TimeSeventeen/Polymarket-v2 (mirror xfox25/Polymarket-v2), layer daily_aligned",
        "license": "CC BY 4.0",
        "partitions": len(files),
        "first_partition": os.path.basename(files[0]).replace("da-", "").replace(".parquet", ""),
        "last_partition": os.path.basename(files[-1]).replace("da-", "").replace(".parquet", ""),
        "markets_matched_in_corpus": len(markets),
    }
    if validate:
        res["corpus_validation"] = validate_corpus(markets, validate)
        if res["verdict"]["disagreements"]:
            res["verdict"]["disputes_resolved"] = resolve_disputes(markets, res["verdict"]["disagreements"])
    res["generated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    res["read_at_unix"] = int(time.time())
    return res


# --------------------------------------------------------------------------------------------------
# self-test: every arm must be able to FIRE on a fixture that contains the defect
# --------------------------------------------------------------------------------------------------
def self_test() -> int:
    checks: list[tuple[str, bool, str]] = []

    def ck(name, cond, detail=""):
        checks.append((name, bool(cond), detail))

    # ARM 2 -- a verdict swap is detected; a binary-vs-named pair is NOT called a disagreement
    mk = {
        "m1": {"condition_id": "c1", "win": "Jose Henrique", "tokens": {"JOSEHENRIQUE", "JONNYPARSONS"}},
        "m2": {"condition_id": "c2", "win": "Yes", "tokens": {"YES", "NO"}},
        "m3": {"condition_id": "c3", "win": "Under", "tokens": {"UNDER", "OVER"}},
        "m4": {"condition_id": "c4", "win": "Under", "tokens": {"UNDER"}},
    }
    legs = [
        # swap: we booked Souza a win, venue says Henrique won
        _leg("m1", "JOSE SOUZA", cp=1.0, entry=0.685, size=9.0, pnl=4.14),
        _leg("m1", "JOSE HENRIQUE", cp=0.0, entry=0.685, size=9.0, pnl=-9.0),
        # honest loss on a named market -- must NOT be called a disagreement
        _leg("m3", "OVER", cp=0.0, entry=0.5, size=10.0, pnl=-10.0),
        # binary market we agree with
        _leg("m2", "YES", cp=1.0, entry=0.4, size=10.0, pnl=15.0),
        # undeterminable: our label is named, the venue's winner is binary
        _leg("m2", "SOMETHING", cp=1.0, entry=0.4, size=10.0, pnl=15.0),
        # single-token market: an unseen label here is NOT definitive (the side may just be quiet)
        _leg("m4", "OVER", cp=0.0, entry=0.5, size=10.0, pnl=-10.0),
    ]
    res = run_arms(None, legs, mk)
    ck("arm2 finds the swap (2 legs, 1 market)",
       res["verdict"]["disagree_legs"] == 2 and res["verdict"]["disagree_markets"] == 1,
       str(res["verdict"]["disagree_legs"]) + "/" + str(res["verdict"]["disagree_markets"]))
    ck("arm2 does not count an honest loss as a disagreement",
       all(d["marketId"] == "m1" for d in res["verdict"]["disagreements"]))
    # 6 fixture legs, 1 of them named-vs-binary: that one is excluded, never called a disagreement
    ck("arm2 refuses to judge named-vs-binary", res["verdict"]["knowable_legs"] == 5,
       str(res["verdict"]["knowable_legs"]) + " of 6")
    ck("arm3 settlement delta is the verdict swap only", abs(res["settlement_pnl"]["delta_from_verdict_only"]) == 0.0,
       str(res["settlement_pnl"]["delta_from_verdict_only"]))
    # the cancel is the point: one phantom win + one phantom loss on the same stake net to zero
    ck("arm4 flags every label that matches no token", res["label_set"]["legs_with_unseen_label"] == 3,
       str(res["label_set"]["legs_with_unseen_label"]))
    ck("arm4 calls it definitive only when the market's tokens are otherwise present",
       res["label_set"]["definitive"] == 2, str(res["label_set"]["definitive"]))

    # ARM 3 must MOVE when the verdict difference is not symmetric
    # we booked OVER a WIN on a market the venue says resolved UNDER -> an undamped $20 swing
    legs2 = [_leg("m3", "OVER", cp=1.0, entry=0.5, size=10.0, pnl=10.0)]
    r2 = run_arms(None, legs2, {"m3": mk["m3"]})
    ck("arm3 delta moves on an asymmetric disagreement",
       round(r2["settlement_pnl"]["delta_from_verdict_only"], 2) == -20.0,
       str(r2["settlement_pnl"]["delta_from_verdict_only"]))

    # ARM 5 sign convention: we booked 0.60 where the tape traded 0.65 -> +5c (we booked WORSE)
    ck("arm5 sign convention: booking 0.60 where the tape traded 0.65 is -5c (we booked better)",
       entry_diff_c(0.60, 0.65) == -5.0)
    ck("arm5 sign convention: the C-200 maker model MUST read negative",
       entry_diff_c(0.10, 0.12) == -2.0)
    ck("normalisation matches resolution.ts", norm("Jose Henrique") == norm("JOSE HENRIQUE") == "JOSEHENRIQUE")

    # ARM 1 / rule gate
    rule = apply_rule({"knowable_markets": 40, "disagree_leg_pct": 9.9, "disagree_market_pct": 9.9})
    ck("rule refuses to fire under the market floor", rule["verdict"] == "INSUFFICIENT_DATA", rule["verdict"])
    rule = apply_rule({"knowable_markets": 537, "disagree_leg_pct": 0.28, "disagree_market_pct": 0.19})
    ck("rule refutes below 0.5%", rule["verdict"] == "REFUTED_INSTRUMENT_RETIRES", rule["verdict"])
    rule = apply_rule({"knowable_markets": 537, "disagree_leg_pct": 3.0, "disagree_market_pct": 3.0})
    ck("rule investigates above 2%", rule["verdict"] == "INVESTIGATE_RECORDER", rule["verdict"])

    width = max(len(n) for n, _, _ in checks)
    bad = 0
    for name, ok, detail in checks:
        print(f"  {'PASS' if ok else 'FAIL'}  {name.ljust(width)}  {detail}")
        bad += 0 if ok else 1
    print(f"self-test: {len(checks) - bad}/{len(checks)} passed")
    return 1 if bad else 0


def _leg(market, outcome, cp, entry, size, pnl, status="resolved", ts=1794000000000, fill=None):
    return {
        "id": f"leg-{market}-{outcome}-{cp}",
        "botId": "TEST",
        "marketId": market,
        "outcome": outcome,
        "side": "BUY",
        "entryPrice": entry,
        "currentPrice": cp,
        "simulatedPositionSize": size,
        "realizedPnl": pnl,
        "status": status,
        "fillStatus": fill,
        "fillBasis": None,
        "openedAt": ts,
        "closedAt": None,
        "resolvedAt": ts,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", default=CACHE)
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--validate", type=int, default=0, metavar="N",
                    help="re-read N corpus-decided markets from the venue (CLOB) to prove the corpus itself")
    ap.add_argument("--out", default=OUT)
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    res = measure(args.cache, validate=args.validate)
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w") as fh:
        json.dump(res, fh, indent=2, sort_keys=True)

    v, p, s, r = res["verdict"], res["price"], res["settlement_pnl"], res["rule"]
    print(f"CORPUS   {res['corpus']['dataset']}")
    print(f"         {res['corpus']['partitions']} partitions "
          f"{res['corpus']['first_partition']}..{res['corpus']['last_partition']}, "
          f"{res['corpus']['markets_matched_in_corpus']:,} markets matched")
    c = res["coverage"]
    print(f"COVERAGE {c['legs_joined']:,}/{c['legs_in_book']:,} legs ({c['leg_coverage_pct']}%), "
          f"{c['markets_joined']:,}/{c['markets_in_book']:,} markets ({c['market_coverage_pct']}%)")
    print(f"VERDICT  {v['agree_legs']}/{v['knowable_legs']} legs agree on {v['knowable_markets']} markets; "
          f"disagree {v['disagree_legs']} legs ({v['disagree_leg_pct']}%) / {v['disagree_markets']} markets "
          f"({v['disagree_market_pct']}%)")
    print(f"PNL      booked ${s['booked_on_population']:,.2f} on the population; verdict-only delta "
          f"${s['delta_from_verdict_only']:,.2f} ({s['delta_pct_of_abs_booked']}% of |booked|)")
    print(f"LABELS   {res['label_set']['legs_with_unseen_label']} legs carry a label no corpus token matches "
          f"({res['label_set']['definitive']} definitive)")
    for lane in p.get("by_lane", []):
        print(f"PRICE    {lane['botId']:<13} n={lane['n']:<5} median {lane['median_c']:+.2f}c "
              f"mean {lane['mean_c']:+.2f}c p10 {lane['p10_c']:+.2f} p90 {lane['p90_c']:+.2f} "
              f"within1c {lane['within_1c_pct']}%")
    b = res["booking_note"]
    print(f"BOOKING  {b['unfilled_legs_with_nonzero_booked_pnl']} unfilled legs still carry "
          f"${b['sum']:,.2f} booked (Lane A, printed not fixed)")
    print(f"RULE     {r['verdict']}: {r['reason']}")
    for disp in res["verdict"].get("disputes_resolved", []):
        if "venue_win" in disp:
            print(f"DISPUTE  {disp['market']}: venue tokens {disp['venue_tokens']} winner {disp['venue_win']!r}; "
                  f"corpus said {disp['corpus_win']!r} (corpus_right={disp['corpus_right']}); "
                  f"our legs wrong={disp['our_legs_wrong']} booked ${disp['booked_on_wrong_legs']:,.2f}")
    if "corpus_validation" in res:
        cv = res["corpus_validation"]
        print(f"CORPUSOK {cv['agree']}/{cv['sample']} sampled markets: corpus winner == venue winner "
              f"({cv['mismatch']} mismatch, {cv['unreadable']} unreadable; seed {cv['seed']})")
    print(f"artifact {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
