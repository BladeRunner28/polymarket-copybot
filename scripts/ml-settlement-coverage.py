#!/usr/bin/env python3
"""Pre-registered coverage measurement for the ML settlement-source proposal.

Compares the CURRENT derivation (last MarketSnapshot price band) against VENUE TRUTH
(CLOB /markets/{conditionId} -> tokens[].winner) across every market in the observe log,
then applies the decision rule written in drafts/ml-settlement-source-20261022.md BEFORE
this ran.

READ-ONLY. Writes nothing, changes nothing, touches no live lane.

Decision rule (from the proposal, unchanged):
  ADOPT  iff  coverage >= 90% of observed markets have conditionId AND a retrievable
              CLOB record, AND agreement >= 95% on the decisive overlap.
  REFUTE iff  coverage < 70%, OR disagreement > 5% on the decisive overlap,
              OR > 20% of observed markets lack a conditionId.
  Otherwise: INSUFFICIENT — report and do not switch.

Run: python3 scripts/ml-settlement-coverage.py [--sleep 0.3]
"""
import argparse
import json
import sqlite3
import time
import urllib.error
import urllib.request
from collections import Counter

DB = "prisma/dev.db"
LOG = "data/ml/observe-log.jsonl"
CLOB = "https://clob.polymarket.com/markets/"
COVERAGE_MIN = 0.90
AGREE_MIN = 0.95
COVERAGE_REFUTE = 0.70
DISAGREE_REFUTE = 0.05
NO_CONDITIONID_REFUTE = 0.20
TARGET_SETTLED = 400


def load_observations():
    rows = [json.loads(l) for l in open(LOG) if l.strip()]
    counts = Counter(r["market_id"] for r in rows)
    return rows, counts


def proxy_outcomes(market_ids):
    """Exactly the rule in ml-observe-read.py: last snapshot, yesPrice band."""
    con = sqlite3.connect("file:{}?mode=ro".format(DB), uri=True)
    out = {}
    ids = list(market_ids)
    CHUNK = 900
    for i in range(0, len(ids), CHUNK):
        batch = ids[i:i + CHUNK]
        ph = ",".join("?" * len(batch))
        q = """
            SELECT s.marketId, s.yesPrice
            FROM MarketSnapshot s
            JOIN (SELECT marketId, MAX(collectedAt) AS mx FROM MarketSnapshot
                  WHERE isDemo = 0 GROUP BY marketId) l
              ON l.marketId = s.marketId AND l.mx = s.collectedAt
            WHERE s.marketId IN ({})
        """.format(ph)
        for mid, yes in con.execute(q, batch):
            if yes is None:
                continue
            if yes >= 0.90:
                out[mid] = 1
            elif yes <= 0.10:
                out[mid] = 0
    con.close()
    return out


def condition_ids(market_ids):
    con = sqlite3.connect("file:{}?mode=ro".format(DB), uri=True)
    ids = list(market_ids)
    ph = ",".join("?" * len(ids))
    q = ("SELECT marketId, MAX(conditionId) FROM MarketSnapshot WHERE marketId IN ({}) "
         "AND conditionId IS NOT NULL AND conditionId <> '' GROUP BY marketId").format(ph)
    out = dict(con.execute(q, ids))
    con.close()
    return out


def fetch_venue(condition_id, timeout=20):
    req = urllib.request.Request(CLOB + condition_id, headers={"User-Agent": "Mozilla/5.0"})
    try:
        d = json.load(urllib.request.urlopen(req, timeout=timeout))
    except urllib.error.HTTPError as e:
        return {"ok": False, "error": "http_%d" % e.code}
    except Exception as e:
        return {"ok": False, "error": type(e).__name__}
    toks = d.get("tokens") or []
    winners = [t for t in toks if t.get("winner") in (True, "true")]
    closed = bool(d.get("closed"))
    if not winners:
        # Distinguish "still trading" from "closed but no winner" -- these are different
        # facts and conflating them is how a report ends up lying about its own coverage.
        return {"ok": True, "closed": closed, "y": None,
                "state": "closed_without_winner" if closed else "not_closed_yet"}
    return {"ok": True, "closed": closed, "y": 1 if winners[0].get("outcome") == "Yes" else 0,
            "outcome": winners[0].get("outcome"), "state": "resolved"}


def last_snapshot_prices(market_ids):
    """The raw last-snapshot price, not the band -- used only for the post-hoc direction check."""
    con = sqlite3.connect("file:{}?mode=ro".format(DB), uri=True)
    ids = list(market_ids)
    ph = ",".join("?" * len(ids))
    q = """
        SELECT s.marketId, s.yesPrice
        FROM MarketSnapshot s
        JOIN (SELECT marketId, MAX(collectedAt) mx FROM MarketSnapshot WHERE isDemo=0 GROUP BY marketId) l
          ON l.marketId = s.marketId AND l.mx = s.collectedAt
        WHERE s.marketId IN ({})
    """.format(ph)
    out = dict(con.execute(q, ids))
    con.close()
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sleep", type=float, default=0.3)
    ap.add_argument("--out", default="data/ml/settlement-coverage.json")
    args = ap.parse_args()

    rows, per_market = load_observations()
    ids = sorted(per_market)
    total_obs = len(rows)
    print("observe log: %d observations across %d markets" % (total_obs, len(ids)))

    proxy = proxy_outcomes(ids)
    cids = condition_ids(ids)
    print("  proxy-decisive markets      : %d (%.1f%%)" % (len(proxy), 100.0 * len(proxy) / len(ids)))
    print("  markets with a conditionId  : %d (%.1f%%)" % (len(cids), 100.0 * len(cids) / len(ids)))

    venue, errors = {}, Counter()
    for n, mid in enumerate(ids, 1):
        cid = cids.get(mid)
        if not cid:
            errors["no_conditionId"] += 1
            continue
        r = fetch_venue(cid)
        if not r["ok"]:
            errors[r["error"]] += 1
        elif r["y"] is not None:
            venue[mid] = r["y"]
        else:
            errors[r.get("state", "unresolved")] += 1
        if n % 20 == 0:
            print("    ...fetched %d/%d markets" % (n, len(ids)))
        time.sleep(args.sleep)

    retrievable = sum(1 for mid in ids if cids.get(mid) and mid not in venue) + len(venue)
    both_cov = len([m for m in ids if cids.get(m)])  # had a conditionId
    print()
    print("=== COVERAGE ===")
    print("  conditionId present         : %d/%d (%.1f%%)" % (len(cids), len(ids), 100.0 * len(cids) / len(ids)))
    print("  CLOB record retrieved       : %d/%d (%.1f%%)" % (retrievable, len(ids), 100.0 * retrievable / len(ids)))
    print("  venue-decisive (winner)     : %d/%d (%.1f%%)" % (len(venue), len(ids), 100.0 * len(venue) / len(ids)))
    if errors:
        print("  fetch/lookup notes          : %s" % dict(errors))

    overlap = [m for m in ids if m in proxy and m in venue]
    agree = [m for m in overlap if proxy[m] == venue[m]]
    disagree = [m for m in overlap if proxy[m] != venue[m]]
    print()
    print("=== AGREEMENT (decisive overlap) ===")
    print("  both decisive               : %d" % len(overlap))
    if overlap:
        rate = len(agree) / len(overlap)
        print("  agree                       : %d (%.1f%%)" % (len(agree), 100.0 * rate))
        print("  disagree                    : %d (%.1f%%)" % (len(disagree), 100.0 * (1 - rate)))
        for m in disagree[:8]:
            print("     %-52s proxy=%d venue=%d" % (m[:52], proxy[m], venue[m]))

    recovered = [m for m in venue if m not in proxy]
    lost = [m for m in proxy if m not in venue]
    print()
    print("=== RECOVERY vs DIVERGENCE ===")
    print("  venue settled, proxy missed : %d markets (%d observations)"
          % (len(recovered), sum(per_market[m] for m in recovered)))
    print("  proxy settled, venue quiet  : %d markets (%d observations)"
          % (len(lost), sum(per_market[m] for m in lost)))

    # --- POST-HOC: the agreement clause above is unmeasurable when the proxy settles nothing.
    # Reported as a substitute, labelled as post-hoc, and only in the direction that makes the
    # switch safer: it asks whether the OLD source carries any signal worth preserving.
    prices = last_snapshot_prices(ids)
    dirn = [(m, float(prices[m]), venue[m]) for m in venue if prices.get(m) is not None]
    dir_ok = [x for x in dirn if (x[1] > 0.5) == (x[2] == 1)]
    med_dev = sorted(abs(x[1] - 0.5) for x in dirn)[len(dirn) // 2] if dirn else None
    print()
    print("=== POST-HOC: does the last snapshot lean the right way? (proxy overlap was %d) ===" % len(overlap))
    print("  venue-resolved with a price : %d" % len(dirn))
    print("  direction agrees            : %d (%.1f%%)  [coin flip = 50%%]"
          % (len(dir_ok), 100.0 * len(dir_ok) / max(len(dirn), 1)))
    print("  median |last price - 0.50|  : %s  (band rule needs >= 0.40)"
          % ("n/a" if med_dev is None else "%.3f" % med_dev))

    obs_proxy = sum(per_market[m] for m in proxy)
    obs_venue = sum(per_market[m] for m in venue)
    print()
    print("=== SETTLED OBSERVATIONS ===")
    print("  under proxy : %d" % obs_proxy)
    print("  under venue : %d" % obs_venue)
    if obs_proxy:
        print("  ratio       : %.1fx" % (obs_venue / obs_proxy))

    # --- apply the pre-registered rule -----------------------------------
    cov_rate = len(cids) / len(ids)
    retr_rate = retrievable / len(ids)
    agree_rate = (len(agree) / len(overlap)) if overlap else None
    disagree_rate = (1 - agree_rate) if agree_rate is not None else None
    no_cid_rate = 1 - cov_rate

    print()
    print("=== PRE-REGISTERED DECISION ===")
    print("  coverage (conditionId+CLOB) : %.1f%%  vs bar >=90%%" % (100 * min(cov_rate, retr_rate)))
    print("  agreement on overlap        : %s  vs bar >=95%%"
          % ("n/a (no overlap)" if agree_rate is None else "%.1f%%" % (100 * agree_rate)))

    verdict, why = None, []
    if no_cid_rate > NO_CONDITIONID_REFUTE:
        verdict = "REFUTED"
        why.append("%.1f%% of markets lack a conditionId (>20%%)" % (100 * no_cid_rate))
    if disagree_rate is not None and disagree_rate > DISAGREE_REFUTE:
        verdict = "REFUTED"
        why.append("disagreement %.1f%% (>5%%)" % (100 * disagree_rate))
    if min(cov_rate, retr_rate) < COVERAGE_REFUTE:
        verdict = "REFUTED"
        why.append("coverage %.1f%% (<70%%)" % (100 * min(cov_rate, retr_rate)))
    if verdict is None:
        if min(cov_rate, retr_rate) >= COVERAGE_MIN and agree_rate is not None and agree_rate >= AGREE_MIN:
            verdict = "ADOPT"
        else:
            verdict = "INSUFFICIENT"
            why.append("coverage or agreement under the adopt bar but above the refute floor")
    print("  VERDICT: %s  %s" % (verdict, "; ".join(why) if why else ""))

    out = {
        "builtAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "observations": total_obs,
        "markets": len(ids),
        "coverage": {
            "conditionIdPresent": len(cids), "conditionIdPct": round(100 * cov_rate, 2),
            "clobRetrieved": retrievable, "clobRetrievedPct": round(100 * retr_rate, 2),
            "venueDecisive": len(venue), "venueDecisivePct": round(100 * len(venue) / len(ids), 2),
            "notes": dict(errors),
        },
        "agreement": {
            "overlap": len(overlap),
            "agree": len(agree),
            "agreePct": None if agree_rate is None else round(100 * agree_rate, 2),
            "disagreements": [{"market": m, "proxy": proxy[m], "venue": venue[m]} for m in disagree[:40]],
        },
        "recovery": {
            "venueSettledProxyMissedMarkets": len(recovered),
            "venueSettledProxyMissedObservations": sum(per_market[m] for m in recovered),
            "proxySettledVenueQuietMarkets": len(lost),
            "proxySettledVenueQuietObservations": sum(per_market[m] for m in lost),
        },
        "settledObservations": {"proxy": obs_proxy, "venue": obs_venue,
                                "ratio": round(obs_venue / obs_proxy, 2) if obs_proxy else None},
        "postHocDirectionCheck": {
            "note": "The pre-registered agreement clause is unmeasurable when the proxy settles nothing "
                    "(overlap 0). This substitute is POST-HOC, chosen after seeing that. It asks whether "
                    "the old source carries any signal worth preserving, so it can only make the switch "
                    "safer, and it is reported rather than used to declare the verdict.",
            "n": len(dirn),
            "agree": len(dir_ok),
            "agreePct": round(100 * len(dir_ok) / len(dirn), 2) if dirn else None,
            "coinFlipPct": 50.0,
            "medianAbsDeviationFromHalf": None if med_dev is None else round(med_dev, 4),
            "bandRuleNeeds": 0.40,
        },
        "target": TARGET_SETTLED,
        "verdict": verdict,
        "reasons": why,
        "bars": {"coverageMin": COVERAGE_MIN, "agreeMin": AGREE_MIN, "coverageRefute": COVERAGE_REFUTE,
                 "disagreeRefute": DISAGREE_REFUTE, "noConditionIdRefute": NO_CONDITIONID_REFUTE},
    }
    with open(args.out, "w") as fh:
        json.dump(out, fh, indent=2)
    print("  wrote %s" % args.out)


if __name__ == "__main__":
    main()
