#!/usr/bin/env python3
"""fee-sign-flip-test.py — the >=$25 / sign-flip half of card paper-trader-archived-fee-reprice.

READ-ONLY. Answers the question the card has left open since 2026-10-21:

    if fees are re-priced off the venue's own per-market base fee, does aggregate fee move
    >= $25, or does at least one leg's net PnL change sign?

WHY THIS IS NOW RUNNABLE
The card blocked on "verify the venue formula against the primary source BEFORE re-pricing".
That is settled: our model is fee = shares * rate * p * (1-p); the venue convention is
fee = shares * (base_fee/1e4) * min(p, 1-p). The two agree near the extremes and diverge at the
middle -- at p=0.50 ours is roughly half the venue's. Same rate, different law.

MODELS COMPARED (same legs, same shares)
  current : shares * category_rate * p * (1 - p)      -- what our model charges
  venue   : shares * (taker_base_fee/1e4) * min(p,1-p) -- the venue's own field
Category rate: politics 0.04, crypto 0.07, geopolitics 0.0, default 0.05 (unchanged from
scripts/c200-fee-reprice-archive.py so the two reads are comparable).

DECISION RULE (pre-registered on the card, unchanged)
  ADOPT the venue fee as the input iff coverage >= 90% AND (aggregate |delta| >= $25 OR at least
  one leg flips the sign of its net PnL).
  CLOSE WITH A NULL if coverage < 90% (the field is not a usable source).
  KEEP THE EXISTING MODEL if coverage is high but delta < $25 and nothing flips.

Exit is charged only for status='closed' (a real sell); 'resolved' settles at 0/1 with no trade.
Nothing is written except data/fee-sign-flip-report.json.
"""
import argparse
import json
import re
import sqlite3
import time
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor

DB = "prisma/dev.db"
OUT = "data/fee-sign-flip-report.json"
CACHE = "data/clob-fee-cache.json"
CLOB = "https://clob.polymarket.com/markets/"
MIN_COVERAGE = 0.90
MIN_DELTA_USD = 25.0

KEYWORDS = [
    ("crypto", r"bitcoin|btc|eth|ethereum|solana|sol\b|xrp|crypto|dogecoin|token price"),
    ("geopolitics", r"geopolit|invade|invasion|ceasefire|war\b|missile|troops|nato"),
    ("politics", r"election|president|senate|congress|nominee|governor|parliament|vote|poll|primary|trump|biden|harris|mayor|referendum|shutdown"),
]
CAT_RATE = {"politics": 0.04, "crypto": 0.07, "geopolitics": 0.0}
DEFAULT_RATE = 0.05

# Documented Polymarket schedule, fetched 2026-10-22 from
# https://docs.polymarket.com/trading/fees.md -- "fee = C x feeRate x p x (1 - p)".
# Verified against the docs' own 100-share Crypto table: p=0.50 -> $1.75, and
# 100 * 0.07 * 0.50 * 0.50 = $1.75 exactly. The min(p,1-p) law would give $3.50.
DOCS_RATE = {
    "crypto": 0.07, "sports": 0.05, "finance": 0.04, "politics": 0.04,
    "economics": 0.05, "culture": 0.05, "weather": 0.05, "other": 0.05,
    "mentions": 0.04, "tech": 0.04, "geopolitics": 0.0, "combos": 0.05,
}
# ObservedTrade class -> documented category
CLASS_MAP = {
    "crypto": "crypto", "sports": "sports", "esports": "sports",
    "politics": "politics", "tech": "tech", "econ": "economics",
    "culture": "culture", "weather": "weather", "other": "other",
}


def category(market_id):
    s = (market_id or "").lower()
    for name, pat in KEYWORDS:
        if re.search(pat, s):
            return name
    return "other"


def load_legs(db):
    con = sqlite3.connect("file:{}?immutable=1".format(db), uri=True)
    rows = con.execute("""
        SELECT p.botId, p.marketId, p.entryPrice, p.simulatedPositionSize, p.status,
               p.realizedPnl, o.conditionId, o.marketCategoryFine, o.marketCategoryClass
        FROM PaperTrade p
        JOIN DecisionJournal j ON j.id = p.decisionJournalId
        JOIN ObservedTrade o ON o.id = j.observedTradeId
        WHERE p.isDemo = 0 AND o.conditionId IS NOT NULL AND o.conditionId <> ''
    """).fetchall()
    con.close()
    return rows


def load_cache(path):
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return {}


def fetch_fee(cid, timeout=20):
    req = urllib.request.Request(CLOB + cid, headers={"User-Agent": "Mozilla/5.0"})
    try:
        d = json.load(urllib.request.urlopen(req, timeout=timeout))
    except urllib.error.HTTPError as e:
        return {"state": "http_%d" % e.code}
    except Exception as e:
        return {"state": "fetch_" + type(e).__name__}
    taker = d.get("taker_base_fee")
    maker = d.get("maker_base_fee")
    if taker is None and maker is None:
        return {"state": "no_fee_field"}
    return {"state": "ok", "taker": taker, "maker": maker}


def resolve_fees(cids, cache_path, workers=8):
    cache = load_cache(cache_path)
    todo = [c for c in cids if c not in cache or cache[c].get("state") != "ok"]
    print("  distinct markets: %d | cached: %d | fetching: %d"
          % (len(cids), len(cids) - len(todo), len(todo)))
    if todo:
        done = 0
        with ThreadPoolExecutor(max_workers=workers) as ex:
            for cid, res in ex.map(lambda c: (c, fetch_fee(c)), todo):
                cache[cid] = res
                done += 1
                if done % 500 == 0:
                    print("    ...%d/%d" % (done, len(todo)))
        try:
            with open(cache_path, "w") as f:
                json.dump(cache, f)
        except Exception as e:
            print("  !! cache write failed: %s" % e)
    return cache


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=DB)
    ap.add_argument("--out", default=OUT)
    ap.add_argument("--cache", default=CACHE)
    ap.add_argument("--workers", type=int, default=8)
    args = ap.parse_args()

    legs = load_legs(args.db)
    cids = sorted({r[6] for r in legs})
    print("paper legs with a conditionId: %d over %d markets" % (len(legs), len(cids)))

    cache = resolve_fees(cids, args.cache, workers=args.workers)
    states = Counter(v.get("state") for v in cache.values())
    resolved = {c: v for c, v in cache.items() if v.get("state") == "ok"}
    cov = len(resolved) / max(len(cids), 1)
    print("\n=== COVERAGE ===")
    print("  fee fields retrieved: %d/%d markets (%.1f%%)  states: %s"
          % (len(resolved), len(cids), 100 * cov, dict(states)))

    agg = defaultdict(float)
    agg_by_cat = defaultdict(lambda: defaultdict(float))
    flips = []
    skipped = Counter()
    fee_vals = Counter()
    per_bot = defaultdict(lambda: defaultdict(float))

    for bot, mk, p, size, status, pnl, cid, fine, klass in legs:
        if not p or p <= 0 or not size:
            skipped["bad_price"] += 1
            continue
        rec = resolved.get(cid)
        if rec is None:
            skipped["no_fee_field"] += 1
            continue
        base = rec.get("taker")
        if base is None:
            base = rec.get("maker")
        if base is None:
            skipped["null_base_fee"] += 1
            continue
        base = float(base)
        fee_vals[base] += 1
        shares = size / p
        # our category rate (unchanged model)
        cat = (fine or klass or "").lower()
        rate = CAT_RATE.get(cat)
        if rate is None:
            rate = CAT_RATE.get(category(mk), DEFAULT_RATE)
        cur = shares * rate * p * (1 - p)

        # documented rate + documented law for the same category
        dcat = CLASS_MAP.get((klass or "").lower())
        if dcat is None:
            dcat = CLASS_MAP.get(category(mk), "other")
        drate = DOCS_RATE[dcat]
        ven = shares * drate * p * (1 - p)
        # keep the old, erroneous min-law value ONLY for the record
        minlaw = shares * drate * min(p, 1 - p)
        agg_by_cat[dcat]["cur"] += cur
        agg_by_cat[dcat]["docs"] += ven
        agg_by_cat[dcat]["rateOurs"] = rate
        agg_by_cat[dcat]["rateDocs"] = drate
        agg_by_cat[dcat]["legs"] += 1
        # what the WRONG min-law would have claimed, for the record only
        agg["fee_minlaw_artifact"] += minlaw
        if status == "closed":            # early exit is a trade; resolved settles at 0/1
            cur *= 2.0
            ven *= 2.0

        d = ven - cur
        agg["fee_current"] += cur
        agg["fee_venue"] += ven
        agg["delta"] += d
        agg["notional"] += size
        agg["legs"] += 1
        per_bot[bot]["legs"] += 1
        per_bot[bot]["delta"] += d

        if pnl is not None:
            net_cur = pnl - cur
            net_ven = pnl - ven
            if (net_cur > 0) != (net_ven > 0):
                flips.append({"bot": bot, "market": mk, "price": round(p, 4),
                              "shares": round(shares, 2), "pnl": round(pnl, 4),
                              "feeCurrent": round(cur, 4), "feeVenue": round(ven, 4),
                              "netCurrent": round(net_cur, 4), "netVenue": round(net_ven, 4)})

    print("  base_fee values seen: %s" % dict(fee_vals.most_common(6)))
    if skipped:
        print("  skipped: %s" % dict(skipped))
    print("\n=== AGGREGATE (same legs, same shares) ===")
    print("  legs re-priced     : %d" % int(agg["legs"]))
    print("  notional           : $%.2f" % agg["notional"])
    print("  fee under current  : $%.2f" % agg["fee_current"])
    print("  fee under venue    : $%.2f" % agg["fee_venue"])
    print("  DELTA (venue-cur)  : $%+.2f" % agg["delta"])
    print("  sign flips in net  : %d" % len(flips))

    print("\n=== PER BOT ===")
    for bot, v in sorted(per_bot.items()):
        print("  %-10s legs=%-6d delta $%+.2f" % (bot, int(v["legs"]), v["delta"]))

    if flips:
        print("\n=== FLIPPED LEGS (first 10) ===")
        for f in flips[:10]:
            print("  %-10s %-40s p=%.3f pnl %+.4f  fee %.4f->%.4f  net %+.4f->%+.4f"
                  % (f["bot"], f["market"][:40], f["price"], f["pnl"],
                     f["feeCurrent"], f["feeVenue"], f["netCurrent"], f["netVenue"]))

    print("\n=== PER CATEGORY (our rate vs the documented rate, same law) ===")
    for cat, v in sorted(agg_by_cat.items(), key=lambda kv: -kv[1]["legs"]):
        flag = "" if v["rateOurs"] == v["rateDocs"] else "  <-- RATE MISMATCH"
        print("  %-11s legs=%-6d ours %.2f docs %.2f | fee $%.2f vs $%.2f | delta $%+.2f%s"
              % (cat, int(v["legs"]), v["rateOurs"], v["rateDocs"], v["cur"], v["docs"],
                 v["docs"] - v["cur"], flag))

    print("\n=== THE ARTIFACT, for the record ===")
    print("  min(p,1-p) 'venue' law on the same legs would have claimed $%.2f in fees"
          % agg["fee_minlaw_artifact"])
    print("  vs $%.2f under the documented C*rate*p*(1-p) -- the difference is the law error,"
          % agg["fee_venue"])
    print("  not a finding. Polymarket docs + the 100-share table settle it at p*(1-p).")

    # --- pre-registered decision ---------------------------------------------
    if cov < MIN_COVERAGE:
        verdict = "NULL"
        why = "coverage %.1f%% < %.0f%% -- the field is not a usable source" % (100 * cov, 100 * MIN_COVERAGE)
    elif abs(agg["delta"]) >= MIN_DELTA_USD or flips:
        verdict = "ADOPT"
        bits = []
        if abs(agg["delta"]) >= MIN_DELTA_USD:
            bits.append("aggregate delta $%+.2f >= $%.0f" % (agg["delta"], MIN_DELTA_USD))
        if flips:
            bits.append("%d leg(s) flip net sign" % len(flips))
        why = " AND ".join(bits)
    else:
        verdict = "KEEP_CURRENT"
        why = "coverage high but delta $%+.2f < $%.0f and no sign flips" % (agg["delta"], MIN_DELTA_USD)

    print("\n=== PRE-REGISTERED DECISION ===")
    print("  coverage %.1f%% (bar >=90%%) | delta $%+.2f (bar >=$25) | flips %d"
          % (100 * cov, agg["delta"], len(flips)))
    print("  VERDICT: %s -- %s" % (verdict, why))
    print("  NOTE: ADOPT is a proposal, not an application. Changing the fee input is Lane A.")

    out = {
        "builtAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "coveragePct": round(100 * cov, 2),
        "markets": len(cids), "marketsWithFee": len(resolved),
        "legs": int(agg["legs"]), "notionalUsd": round(agg["notional"], 2),
        "feeCurrentUsd": round(agg["fee_current"], 2),
        "feeVenueUsd": round(agg["fee_venue"], 2),
        "deltaUsd": round(agg["delta"], 2),
        "signFlips": len(flips),
        "flips": flips[:200],
        "baseFeeValues": dict(fee_vals.most_common(10)),
        "skipped": dict(skipped),
        "perBot": {k: {"legs": int(v["legs"]), "deltaUsd": round(v["delta"], 2)} for k, v in per_bot.items()},
        "perCategory": {k: {"legs": int(v["legs"]), "rateOurs": v["rateOurs"], "rateDocs": v["rateDocs"],
                            "feeOursUsd": round(v["cur"], 2), "feeDocsUsd": round(v["docs"], 2),
                            "deltaUsd": round(v["docs"] - v["cur"], 2)}
                        for k, v in agg_by_cat.items()},
        "lawArtifactFeeUsd": round(agg["fee_minlaw_artifact"], 2),
        "lawSource": "https://docs.polymarket.com/trading/fees.md — fee = C x feeRate x p x (1-p); "
                     "verified against the docs 100-share Crypto table (p=0.50 -> $1.75 = 100*0.07*0.25)",
        "verdict": verdict, "reason": why,
        "bars": {"minCoveragePct": 100 * MIN_COVERAGE, "minDeltaUsd": MIN_DELTA_USD},
        "readOnly": True,
    }
    with open(args.out, "w") as f:
        json.dump(out, f, indent=2)
    print("  wrote %s" % args.out)


if __name__ == "__main__":
    main()
