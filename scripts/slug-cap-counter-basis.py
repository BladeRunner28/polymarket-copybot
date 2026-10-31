#!/usr/bin/env python3
"""Measure the v45 per-slug cap's refusal basis (read-only).

Question: when scripts/score-trades.ts journals
  "BANKROLL_200: v45 market-slug cap (<token> would be N/15)"
was there really N-1 (or more) legs of that token OPEN at decision time, or was
the bucket filled by same-run candidates that passed the cap check and then died
at a later gate (kelly / band skip / high-entry / v55 / v58) without opening
anything?

The counter (c200SlugCounts, scripts/score-trades.ts L263/268/778/788) is seeded
from PaperTrade rows with status='open' and then incremented the moment a
candidate PASSES the check; no downstream 'continue' ever decrements it. So the
printed basis can claim positions that do not exist.

Method
  population  DecisionJournal rows, isDemo=0, createdAt in window, risksJson
              containing the C-200 slug-cap block (level = decision)
  basis       true concurrent open count reconstructed from booked C-200 legs'
              [openedAt, COALESCE(closedAt, resolvedAt)) intervals on the same
              raw marketCategory token
  classes     GENUINE  true open >= cap at the decision timestamp
              PHANTOM  true open <  cap at the decision timestamp
  value       unit-notional counterfactual per refused decision:
              win -> (1-p)/p, lose -> -1, at p = ObservedTrade.detectedPrice
              (no maker credit, no fee) -- summed per class, so "$ per $1".
              Outcome read from the market's own resolved PaperTrade legs
              (realizedPnl sign on a naturally resolved leg); undeterminable
              rows are excluded and counted in the coverage line.

Read-only: opens the DB with immutable=1 so it cannot fight the crons for a lock
or write anything. Run: python3 scripts/slug-cap-counter-basis.py [--days 30]
"""
import argparse
import json
import os
import re
import sqlite3
import statistics
import sys
import time
import urllib.request
from collections import Counter, defaultdict

DB = os.environ.get(
    "COPYBOT_DB", "/Users/xsnyde2/polymarket-copybot/prisma/dev.db"
)
SLUG_BLOCK = re.compile(r"BANKROLL_200: v45 market-slug cap \((.+?) would be (\d+)/(\d+)\)")
CAP = 15


def ms(dt_string):
    """SQLite rows are Unix-ms; return epoch ms for a 'YYYY-MM-DDTHH:MM:SSZ' string."""
    return int(time.mktime(time.strptime(dt_string, "%Y-%m-%dT%H:%M:%SZ")) * 1000)


def iso(ms_val):
    if ms_val is None:
        return None
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ms_val / 1000))


def norm(s):
    """Token-label comparison key: alphanumerics only, uppercased (mirrors
    src/lib/resolution.ts normalizeOutcomeLabel)."""
    return re.sub(r"[^a-z0-9]", "", (s or "").lower()).upper()


UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)


def fetch_winner(condition_id):
    """Winning token labels for one conditionId from the keyless CLOB archive.
    Returns [] when the market is not closed / the winner is not published, or
    when the archive refuses every attempt (the caller must not cache those)."""
    url = f"https://clob.polymarket.com/markets/{condition_id}"
    last = None
    for attempt in range(4):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=20) as resp:
                d = json.load(resp)
            if not d.get("closed"):
                return []
            return [t.get("outcome") for t in d.get("tokens", []) if t.get("winner")]
        except Exception as e:  # noqa: BLE001 - network shape is not ours to trust
            last = e
            time.sleep(2.0 * (attempt + 1))  # 403s here are rate/WAF, not absent markets
    sys.stderr.write(f"[clob] {condition_id}: {last}\n")
    return []


def market_clustered_ci(rows, iters=2000, alpha=0.05, seed=20261030):
    """Percentile bootstrap of the MEAN payoff, resampling MARKETS (a token's
    decisions share markets and outcomes, so resampling rows would understate
    the interval). Deterministic: fixed seed."""
    import random

    rng = random.Random(seed)
    clusters = defaultdict(list)
    for r in rows:
        clusters[r["marketId"]].append(r["payoff"])
    keys = list(clusters)
    means = []
    for _ in range(iters):
        pick = [rng.choice(keys) for _ in keys]
        vals = [v for k in pick for v in clusters[k]]
        if vals:
            means.append(sum(vals) / len(vals))
    if not means:
        return (float("nan"), float("nan"))
    means.sort()
    lo = means[int(alpha / 2 * len(means))]
    hi = means[int((1 - alpha / 2) * len(means)) - 1]
    return (lo, hi)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=float, default=30.0)
    ap.add_argument("--end", default=None, help="window end, ISO-Z (default: now)")
    ap.add_argument("--json", default=None, help="write full row dump here")
    ap.add_argument(
        "--cache",
        default=os.path.expanduser("~/.hermes/cache/scratch/slugcap-clob-cache.json"),
        help="conditionId -> winning-token cache (avoid refetching)",
    )
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    end_ms = ms(args.end) if args.end else int(time.time() * 1000)
    start_ms = end_ms - int(args.days * 86400 * 1000)

    con = sqlite3.connect(f"file:{DB}?immutable=1", uri=True)
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    # ---- population: decisions carrying a C-200 slug-cap block ---------------
    t0 = time.time()
    rows = cur.execute(
        """
        SELECT d.id, d.createdAt, d.decision, d.marketId, d.risksJson,
               d.ruleSetVersion AS rulesVersion,
               ot.marketCategory AS token, ot.outcome AS outcome,
               ot.side AS side, ot.detectedPrice AS price,
               ot.walletAddress AS wallet, ot.isDemo AS otDemo
          FROM DecisionJournal d
          JOIN ObservedTrade ot ON ot.id = d.observedTradeId
         WHERE d.isDemo = 0
           AND d.createdAt >= ? AND d.createdAt < ?
           AND d.risksJson LIKE '%v45 market-slug cap (%'
        """,
        (start_ms, end_ms),
    ).fetchall()
    refusals = []
    for r in rows:
        blocks = SLUG_BLOCK.findall(r["risksJson"] or "")
        if not blocks:
            continue
        for token, would, cap in blocks:
            refusals.append(
                {
                    "decisionId": r["id"],
                    "at": r["createdAt"],
                    "decision": r["decision"],
                    "marketId": r["marketId"],
                    "rulesVersion": r["rulesVersion"],
                    "token": token,
                    "wouldBe": int(would),
                    "cap": int(cap),
                    "journalToken": r["token"],
                    "outcome": r["outcome"],
                    "side": r["side"],
                    "price": r["price"],
                    "wallet": r["wallet"],
                }
            )
    if not args.quiet:
        print(
            f"population: {len(refusals)} slug-cap refusals on {len(rows)} decisions "
            f"written in [{iso(start_ms)}, {iso(end_ms)})  ({time.time()-t0:.1f}s)"
        )

    # ---- C-200 leg intervals, by raw slug token -----------------------------
    legs = cur.execute(
        """
        SELECT p.marketId, p.outcome, p.openedAt, p.closedAt, p.resolvedAt,
               p.status, p.realizedPnl, p.simulatedPositionSize,
               ot.marketCategory AS token
          FROM PaperTrade p
          JOIN DecisionJournal d ON d.id = p.decisionJournalId
          JOIN ObservedTrade ot ON ot.id = d.observedTradeId
         WHERE p.botId = 'BANKROLL_200' AND p.isDemo = 0
        """
    ).fetchall()
    by_token = defaultdict(list)
    by_market = defaultdict(list)
    for l in legs:
        start = l["openedAt"]
        end = l["closedAt"] if l["closedAt"] is not None else l["resolvedAt"]
        if start is not None:
            by_token[l["token"]].append((start, end))
            by_market[l["marketId"]].append((start, end))
    if not args.quiet:
        print(
            f"legs: {len(legs)} C-200 non-demo legs across {len(by_token)} tokens "
            f"({sum(1 for l in legs if l['status']=='open')} still open)"
        )

    def true_open(token, at):
        n = 0
        for start, end in by_token.get(token, ()):
            if start <= at and (end is None or end > at):
                n += 1
        return n

    def open_legs_in_market(market_id, at):
        n = 0
        for start, end in by_market.get(market_id, ()):
            if start <= at and (end is None or end > at):
                n += 1
        return n

    # ---- classify -----------------------------------------------------------
    for ref in refusals:
        ref["trueOpen"] = true_open(ref["token"], ref["at"])
        ref["cls"] = "GENUINE" if ref["trueOpen"] >= ref["cap"] else "PHANTOM"

    cls = Counter(r["cls"] for r in refusals)
    per_token = defaultdict(lambda: {"GENUINE": 0, "PHANTOM": 0, "trueOpens": []})
    for r in refusals:
        per_token[r["token"]][r["cls"]] += 1
        per_token[r["token"]]["trueOpens"].append(r["trueOpen"])

    print("\nREFUSALS BY TOKEN (decision clock, true open count at that instant)")
    print(f"{'token':<14}{'refusals':>9}{'genuine':>9}{'phantom':>9}  true-open range")
    for token in sorted(per_token, key=lambda t: -(per_token[t]["GENUINE"] + per_token[t]["PHANTOM"])):
        v = per_token[token]
        tos = v["trueOpens"]
        print(
            f"{token:<14}{v['GENUINE']+v['PHANTOM']:>9}{v['GENUINE']:>9}{v['PHANTOM']:>9}"
            f"  {min(tos)}..{max(tos)}"
        )
    total = len(refusals)
    print(
        f"{'TOTAL':<14}{total:>9}{cls['GENUINE']:>9}{cls['PHANTOM']:>9}"
        f"  phantom share {100.0*cls['PHANTOM']/max(total,1):.1f}%"
    )

    # would-be denominators the journal printed, vs true opens
    overprint = [r for r in refusals if r["wouldBe"] > r["trueOpen"] + 1]
    print(
        f"\nprinted basis vs truth: {len(overprint)}/{total} refusals printed a "
        f"'would be N/cap' where N-1 > true open (i.e. the bucket held "
        f"{'at least one phantom slot' if overprint else 'no phantom slots'})"
    )
    if overprint:
        r = overprint[0]
        print(
            f"  e.g. {iso(r['at'])} token={r['token']} printed would-be {r['wouldBe']}/{r['cap']} "
            f"but {r['trueOpen']} legs were open"
        )

    # ---- settlement: keyless CLOB archive, one fetch per conditionId ---------
    # The DB only carries a settlement read for legs that were actually booked and
    # naturally resolved (8/105 here), so the refused candidates themselves need the
    # venue's published winner. Cache on disk so a re-run costs nothing.
    cond_by_decision = {
        r["id"]: r["conditionId"]
        for r in cur.execute(
            """
            SELECT d.id, ot.conditionId
              FROM DecisionJournal d JOIN ObservedTrade ot ON ot.id = d.observedTradeId
             WHERE d.isDemo = 0 AND d.createdAt >= ? AND d.createdAt < ?
               AND d.risksJson LIKE '%v45 market-slug cap (%'
            """,
            (start_ms, end_ms),
        )
    }
    cache_path = args.cache
    cache = {}
    if cache_path and os.path.exists(cache_path):
        with open(cache_path) as fh:
            cache = json.load(fh)
    winners_by_cond = {}
    fetched = 0
    for cond in {c for c in cond_by_decision.values() if c}:
        if cond not in cache:
            got = fetch_winner(cond)
            fetched += 1
            time.sleep(0.4)
            if got:  # never cache a refusal/empty answer — it would read as "unresolved"
                cache[cond] = got
            winners_by_cond[cond] = got
        else:
            winners_by_cond[cond] = cache[cond]
    if cache_path:
        with open(cache_path, "w") as fh:
            json.dump(cache, fh, indent=1)
    if not args.quiet:
        print(
            f"settlement: {len(winners_by_cond)} conditionIds resolved via CLOB archive "
            f"({fetched} fetched this run, {len(winners_by_cond)-fetched} cached)"
        )

    for ref in refusals:
        ref["won"] = None
        cond = cond_by_decision.get(ref["decisionId"])
        winners = winners_by_cond.get(cond) or []
        if winners and ref["outcome"]:
            want = norm(ref["outcome"])
            hit = [w for w in winners if norm(w) and (norm(w) == want or norm(w) in want or want in norm(w))]
            if hit:
                ref["won"] = True
            elif all(norm(w) for w in winners):
                ref["won"] = False
            ref["winner"] = winners
        p = ref["price"]
        if ref["won"] is not None and p and 0 < p < 1:
            ref["payoff"] = ((1 - p) / p) if ref["won"] else -1.0
        else:
            ref["payoff"] = None

    valued = [r for r in refusals if r["payoff"] is not None]
    print(
        f"\nOUTCOME COVERAGE: {len(valued)}/{total} refusals resolved "
        f"(settled winner published on the market's conditionId)"
    )
    print(
        "\nCOUNTERFACTUAL VALUE (unit notional $1/decision at detectedPrice, hold to "
        "settlement; no maker credit, no fee)"
    )
    for c in ("GENUINE", "PHANTOM"):
        sub = [r for r in valued if r["cls"] == c]
        if not sub:
            continue
        tot = sum(r["payoff"] for r in sub)
        mean = tot / len(sub)
        med = statistics.median(r["payoff"] for r in sub)
        wins = sum(1 for r in sub if r["won"])
        # ex-top-k: drop the k largest absolute contributions inside the class
        ranked = sorted(sub, key=lambda r: -abs(r["payoff"]))
        exk = {
            k: sum(r["payoff"] for r in ranked[k:]) for k in (1, 3, 5, 10)
        }
        ci = market_clustered_ci(sub)
        print(
            f"  {c:<8} n={len(sub):<3} sum=${tot:+.2f}  mean=${mean:+.3f}  median=${med:+.3f}  "
            f"win rate {100.0*wins/len(sub):.1f}%  mean CI[{ci[0]:+.3f},{ci[1]:+.3f}]"
        )
        print(
            "           ex-top-k sum: "
            + "  ".join(f"k={k}: ${v:+.2f}" for k, v in exk.items())
        )

    # ---- price-gate ceiling: what the DOWNSTREAM gates would have done -------
    # The cap fires first and `continue`s, so a cap-refused leg carries no record of
    # what kelly / band / entry-price would have said. Two of those gates are pure
    # functions of (price, ruleSet) and one is (marketId, open legs), all of which we
    # CAN reconstruct -- so the phantom-armed legs that clear them are an upper bound
    # on the legs this fix could admit. Kelly is not reconstructable here and is the
    # reason the bound is an upper one.
    rules_by_version = {}
    for r in cur.execute("SELECT version, rulesJson FROM RuleSet"):
        try:
            rules_by_version[r["version"]] = json.loads(r["rulesJson"])
        except (TypeError, ValueError):
            continue
    latest_version = max(rules_by_version) if rules_by_version else None
    latest_rules = rules_by_version.get(latest_version, {})

    def rule(ref, key, default):
        v = (rules_by_version.get(ref["rulesVersion"]) or latest_rules).get(key)
        return default if v is None else v

    def in_band(price, rng):
        m = re.match(r"^(\d*\.?\d+)\s*-\s*(\d*\.?\d+)$", (rng or "").strip())
        if not m or not price:
            return False
        lo, hi = float(m.group(1)), float(m.group(2))
        return hi > lo and lo <= price < hi

    for ref in refusals:
        p = ref["price"]
        max_entry = rule(ref, "c200MaxEntryPrice", 0.8)
        band_rng = rule(ref, "c200SkipBandRange", "")
        max_legs = rule(ref, "maxMarketLegsPerMarketId", 0)
        ref["gateHighEntry"] = bool(max_entry and max_entry > 0 and p and p > max_entry)
        ref["gateBandSkip"] = in_band(p, band_rng)
        ref["gateV55"] = bool(
            max_legs and max_legs > 0
            and open_legs_in_market(ref["marketId"], ref["at"]) + 1 > max_legs
        )
        ref["survivesPriceGates"] = not (
            ref["gateHighEntry"] or ref["gateBandSkip"] or ref["gateV55"]
        )

    print("\nPRICE-GATE CEILING (rules as of the decision's own ruleSetVersion)")
    print(
        f"{'class':<9}{'n':>4}{'high-entry':>12}{'band skip':>11}{'v55 market':>12}"
        f"{'survive':>9}{'value of survivors':>21}"
    )
    for c in ("GENUINE", "PHANTOM", "ALL"):
        sub = refusals if c == "ALL" else [r for r in refusals if r["cls"] == c]
        if not sub:
            continue
        surv = [r for r in sub if r["survivesPriceGates"]]
        sv = sum(r["payoff"] for r in surv if r["payoff"] is not None)
        print(
            f"{c:<9}{len(sub):>4}{sum(r['gateHighEntry'] for r in sub):>12}"
            f"{sum(r['gateBandSkip'] for r in sub):>11}{sum(r['gateV55'] for r in sub):>12}"
            f"{len(surv):>9}{('$%+.2f' % sv):>21}"
        )
    print(
        "  (survivors = cap-refused legs the price/market gates would still admit; "
        "kelly/confidence not reconstructable, so this is an UPPER bound)"
    )

    # ---- weekly baseline the post-fix read compares against -------------------
    # Pre-registered comparison for refutation clause (d): refusals per ISO week,
    # split by class. Under the fix the PHANTOM rows should vanish and the GENUINE
    # rows (true open == 15) should survive at the same rate.
    weekly = defaultdict(lambda: Counter())
    for r in refusals:
        wk = time.strftime("%G-W%V", time.gmtime(r["at"] / 1000))
        weekly[wk][r["cls"]] += 1
    print("\nWEEKLY BASELINE (refusals per ISO week, by class)")
    for wk in sorted(weekly):
        g, p = weekly[wk]["GENUINE"], weekly[wk]["PHANTOM"]
        print(f"  {wk}  total {g+p:>3}  genuine {g:>3}  phantom {p:>3}")

    # ---- what the same tokens were ALSO refused for -------------------------
    # The cap is checked BEFORE kelly/band/wallet, so a cap-refused leg carries no
    # record of what the later gates would have said. Bound it from the same tokens'
    # OTHER refusal flow in the same window instead. Two distinct populations, never
    # merged: DECISION-level skips (fired before the per-bot leg loop, so the C-200
    # leg was never even evaluated -- drift/confidence) and LEG-level C-200 blocks.
    tok_list = sorted(per_token, key=lambda t: -(per_token[t]["GENUINE"] + per_token[t]["PHANTOM"]))
    if tok_list:
        placeholders = ",".join("?" for _ in tok_list)
        leg_peers = cur.execute(
            f"""
            SELECT ot.marketCategory AS token,
                   CASE
                     WHEN d.risksJson LIKE '%kelly no-edge%' THEN 'kelly no-edge'
                     WHEN d.risksJson LIKE '%band skip%' THEN 'band skip'
                     WHEN d.risksJson LIKE '%high-entry cap%' THEN 'high-entry'
                     WHEN d.risksJson LIKE '%v55 per-market cap%' THEN 'v55 market'
                     WHEN d.risksJson LIKE '%v58 per-wallet cap%' THEN 'v58 wallet'
                     WHEN d.risksJson LIKE '%hour blackout%' THEN 'hour'
                     WHEN d.risksJson LIKE '%blacklist category%' THEN 'blacklist'
                     ELSE 'other' END AS gate,
                   COUNT(*) AS n
              FROM DecisionJournal d
              JOIN ObservedTrade ot ON ot.id = d.observedTradeId
             WHERE d.isDemo = 0 AND d.createdAt >= ? AND d.createdAt < ?
               AND ot.marketCategory IN ({placeholders})
               AND d.risksJson LIKE '%BANKROLL_200:%'
               AND d.risksJson NOT LIKE '%v45 market-slug cap%'
             GROUP BY token, gate
            """,
            [start_ms, end_ms] + tok_list,
        ).fetchall()
        dec_peers = cur.execute(
            f"""
            SELECT ot.marketCategory AS token,
                   CASE
                     WHEN d.risksJson LIKE '%confidence %< min%' THEN 'confidence'
                     WHEN d.risksJson LIKE '%drifted%' THEN 'price drift'
                     WHEN d.risksJson LIKE '%blacklist%' THEN 'blacklist'
                     WHEN d.risksJson LIKE '%slug cap%' THEN 'slug cap'
                     ELSE 'other' END AS gate,
                   COUNT(*) AS n
              FROM DecisionJournal d
              JOIN ObservedTrade ot ON ot.id = d.observedTradeId
             WHERE d.isDemo = 0 AND d.createdAt >= ? AND d.createdAt < ?
               AND ot.marketCategory IN ({placeholders})
               AND d.decision = 'skip'
               AND d.risksJson NOT LIKE '%BANKROLL_200:%'
             GROUP BY token, gate
            """,
            [start_ms, end_ms] + tok_list,
        ).fetchall()
        leg_table = defaultdict(Counter)
        dec_table = defaultdict(Counter)
        for r in leg_peers:
            leg_table[r["token"]][r["gate"]] += r["n"]
        for r in dec_peers:
            dec_table[r["token"]][r["gate"]] += r["n"]
        print("\nSAME-TOKEN REFUSAL FLOW (30d) -- the cap's share of each token's total")
        gates = ["confidence", "price drift", "blacklist", "other"]
        print(
            f"{'token':<12}{'cap':>5}{'dec-skips':>11}{'of which conf':>15}{'drift':>8}"
            f"{'leg kelly':>11}{'leg band':>10}{'leg hi-ent':>12}{'leg blacklist':>15}"
        )
        for token in tok_list:
            print(
                f"{token:<12}{per_token[token]['GENUINE']+per_token[token]['PHANTOM']:>5}"
                f"{sum(dec_table[token].values()):>11}{dec_table[token]['confidence']:>15}"
                f"{dec_table[token]['price drift']:>8}{leg_table[token]['kelly no-edge']:>11}"
                f"{leg_table[token]['band skip']:>10}{leg_table[token]['high-entry']:>12}"
                f"{leg_table[token]['blacklist']:>15}"
            )

    # ---- worked example -----------------------------------------------------
    # largest same-token run of cap refusals with zero true open, by token/day
    if args.json:
        with open(args.json, "w") as fh:
            json.dump(
                [
                    {**r, "atIso": iso(r["at"])}
                    for r in refusals
                ],
                fh,
                indent=1,
                default=str,
            )
        print(f"\nrows -> {args.json}")

    con.close()


if __name__ == "__main__":
    main()
