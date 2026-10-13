#!/usr/bin/env python3
"""PM intraday-BTC skip counterfactual — do the COPY-gate skips on btc-updown markets carry edge?

WHY
---
Tracked wallets trade Polymarket's intraday BTC up/down markets (`btc-updown-5m-*`,
`btc-updown-15m-*`) and every decision our engine has ever made on them is `skip` (1,469 of
1,469, RuleSet v61-v62 era). The C-200 blacklist names the token "bitcoin"; these markets
carry category token `btc`, and `score-trades.ts` compares the blacklist with an exact token
match (`botBlacklist.includes(t.marketCategory)`), so the blacklist is NOT what excludes them.
They die on generic gates:
  - "price drifted X since entry > max 0.0040 (too late)"
  - "resolves in 0.0h < min 2h"        (structural: a 5-minute market can never clear 2h)
  - "liquidity $0 < min $750"
  - "price 1.000 near certainty"
So the question is not "should we unblacklist bitcoin" — it is: did those gates walk away
from money? That is a measurement, and this probe makes it.

METHOD (read-only: private DB snapshot + keyless Gamma; no live-path change, nothing written
to the book)
  * decisions = DecisionJournal rows whose marketId starts with `btc-updown`, joined to the
    ObservedTrade that triggered them (outcome UP/DOWN, side BUY).
  * GROUND TRUTH = the venue's own resolution, read keylessly from Gamma
    (`/events?slug=btc-updown-<kind>-<bucket>` must be `closed` with a 1/0 price leg).
    This is the upgrade over scripts/skip-edge-probe.py, which infers winners from the last
    snapshot.
  * TWO ENTRY VARIANTS, because the answer depends entirely on what price we could get:
      snapshot  = last MarketSnapshot at/before the decision, lag-bounded (--max-lag, default
                  180s; a stale snapshot on a 5-minute market is not an entry price)
      detected  = ObservedTrade.detectedPrice, the price our engine actually saw at decision
                  time
  * edge = won - entry - fee(entry), fee = 0.07*p*(1-p) (Polymarket crypto taker schedule,
    the same constant build-decision-dataset.py uses).
  * CI = market-clustered bootstrap (decisions cluster hard per market).

CAVEATS (printed with every number)
  * Exit-blind: this holds to resolution, while live copies are subject to exit rules.
  * Liquidity was $0 < $750 min on the sampled rows, so a real fill at either entry price is
    an ASSUMPTION, not a measurement.
  * This measures the COPY question, not the cross-venue question. For the venue pair see
    scripts/kalshi-pm-btc-updown-read.py (oracle basis: 1.74% of 15-minute windows resolved in
    opposite directions, 282/287 agree over 3 days, 95% CI 0.75-4.01%).

Usage: python3 scripts/pm-btc-intraday-skip-probe.py [--max-lag 60] [--boot 4000] [--out PATH]
"""

from __future__ import annotations

import argparse
import json
import os
import random
import shutil
import sqlite3
import sys
import tempfile
import time
import urllib.error
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone

GAMMA = "https://gamma-api.polymarket.com"
UA = {"User-Agent": "copybot-btc-skip-probe/1.1"}
FEE_RATE = 0.07  # crypto taker schedule, as in build-decision-dataset.py
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def open_db():
    """Read-only connect on a private snapshot copy of prisma/dev.db.

    WHY A COPY: the live engine holds the DB in WAL mode and writes continuously, so a
    `?mode=ro` connect can fail with 'unable to open database file' depending on cwd/state,
    and an `immutable=1` URI would silently ignore the WAL and read stale pages. Copying the
    DB with its -wal/-shm to scratch and reading the copy is repeatable, and cannot disturb
    the live path.
    """
    src = os.path.join(ROOT, "prisma", "dev.db")
    tmp = os.path.join(tempfile.mkdtemp(prefix="btcskip-"), "dev.db")
    for suffix in ("", "-wal", "-shm"):
        if os.path.exists(src + suffix):
            shutil.copy2(src + suffix, tmp + suffix)
    con = sqlite3.connect(tmp)
    con.row_factory = sqlite3.Row
    return con


def get_json(url, timeout=25, retries=3):
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as exc:
            last = "HTTP %s" % exc.code
            if exc.code == 429:
                time.sleep(1.5 * (attempt + 1))
                continue
            break
        except Exception as exc:
            last = str(exc)[:120]
            time.sleep(0.8)
    raise RuntimeError("gamma failed: %s (%s)" % (url, last))


def bucket_of(market_id):
    """btc-updown-15m-<epoch> / btc-updown-5m-<epoch> -> (kind, epoch)."""
    parts = market_id.split("-")
    for i, p in enumerate(parts):
        if p.endswith("m") and p[:-1].isdigit():
            try:
                return p, int(parts[i + 1])
            except (IndexError, ValueError):
                return None, None
    return None, None


def winner_for(market_id, cache):
    """'up' | 'down' | None — from the venue's own resolution, never a snapshot guess."""
    if market_id in cache:
        return cache[market_id]
    kind, ts = bucket_of(market_id)
    winner = None
    if kind and ts:
        try:
            data = get_json("%s/events?slug=btc-updown-%s-%d" % (GAMMA, kind, ts))
        except Exception:
            data = None
        if isinstance(data, list) and data:
            event = data[0]
            markets = event.get("markets") or []
            # A verdict requires closed=True AND a leg at settlement (>=0.999). The closed
            # guard exists because of a measured counter-example (2026-10-13): PM printed
            # 0.9995/0.0005 while `closed: False` — a live last-trade price near certainty,
            # not a result — which manufactured a fake oracle disagreement against Kalshi.
            if markets and bool(event.get("closed")):
                m = markets[0]
                try:
                    raw_o, raw_p = m.get("outcomes"), m.get("outcomePrices")
                    outs = json.loads(raw_o) if isinstance(raw_o, str) else raw_o
                    prices = [float(x) for x in (json.loads(raw_p) if isinstance(raw_p, str) else raw_p or [])]
                    ranked = sorted(zip(outs or [], prices), key=lambda t: -t[1])
                    if outs and prices and len(outs) == len(prices) and ranked[0][1] >= 0.999:
                        winner = str(ranked[0][0]).strip().lower()
                except Exception:
                    winner = None
    cache[market_id] = winner
    return winner


def outcome_is_up(outcome):
    """UP/DOWN are this family's labels (not YES/NO — the bug this function exists to kill)."""
    o = (outcome or "").strip().upper()
    if o in ("UP", "YES"):
        return True
    if o in ("DOWN", "NO"):
        return False
    return None


def edge_rows(pairs):
    """[(marketId, won, entry)] -> mean edge + market-clustered bootstrap CI."""
    per_market = defaultdict(lambda: {"n": 0, "sum": 0.0, "wins": 0})
    for market_id, won, entry in pairs:
        b = per_market[market_id]
        b["n"] += 1
        b["sum"] += won - entry - FEE_RATE * entry * (1.0 - entry)
        b["wins"] += int(won)
    n = sum(b["n"] for b in per_market.values())
    return per_market, n


def cluster_ci(per_market, boot, seed=7):
    markets = list(per_market.values())
    if not markets:
        return (0.0, 0.0)
    rng = random.Random(seed)
    boots = []
    for _ in range(boot):
        sample = [markets[rng.randrange(len(markets))] for _ in range(len(markets))]
        n = sum(s["n"] for s in sample)
        boots.append(sum(s["sum"] for s in sample) / n if n else 0.0)
    boots.sort()
    return boots[int(0.025 * len(boots))], boots[int(0.975 * len(boots)) - 1]


def build_variant(name, pairs, boot):
    if not pairs:
        return None
    per_market, n = edge_rows(pairs)
    mean = sum(b["sum"] for b in per_market.values()) / n
    wins = sum(b["wins"] for b in per_market.values())
    lo, hi = cluster_ci(per_market, boot)
    return {"name": name, "n": n, "markets": len(per_market), "win_rate": wins / n,
            "mean_edge": mean, "ci95": [lo, hi],
            "excludes_zero": bool(lo > 0 or hi < 0)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=None)
    ap.add_argument("--boot", type=int, default=2000)
    ap.add_argument("--max-lag", type=int, default=180, help="max seconds between snapshot and decision")
    args = ap.parse_args()

    con = open_db()
    rows = con.execute(
        """
        SELECT d.id, d.marketId, d.createdAt, d.ruleSetVersion, d.risksJson,
               o.outcome, o.side, o.walletEntryPrice, o.detectedPrice, o.size
        FROM DecisionJournal d
        LEFT JOIN ObservedTrade o ON o.id = d.observedTradeId
        WHERE d.marketId LIKE 'btc-updown%'
        """
    ).fetchall()
    print("decisions on btc-updown markets: %d" % len(rows))

    snaps = defaultdict(list)
    for s in con.execute(
        "SELECT marketId, collectedAt, yesPrice FROM MarketSnapshot "
        "WHERE marketId LIKE 'btc-updown%' ORDER BY collectedAt"
    ):
        if s["yesPrice"] is not None:
            snaps[s["marketId"]].append((s["collectedAt"], s["yesPrice"]))

    cache = {}
    snap_pairs, det_pairs, lags = [], [], []
    kinds = defaultdict(int)
    unlabeled = no_verdict = no_snap = stale = 0
    for r in rows:
        up = outcome_is_up(r["outcome"])
        if up is None:
            unlabeled += 1
            continue
        kinds[bucket_of(r["marketId"])[0] or "?"] += 1
        w = winner_for(r["marketId"], cache)
        if w not in ("up", "down"):
            no_verdict += 1
            continue
        won = 1.0 if ((w == "up") == up) else 0.0
        cand = [s for s in snaps.get(r["marketId"], []) if s[0] <= r["createdAt"]]
        if cand:
            ts, yes = cand[-1]
            lag = (r["createdAt"] - ts) / 1000.0
            lags.append(lag)
            if lag <= args.max_lag:
                entry = yes if up else 1.0 - yes
                if 0.0 < entry < 1.0:
                    snap_pairs.append((r["marketId"], won, entry))
            else:
                stale += 1
        else:
            no_snap += 1
        det = r["detectedPrice"]
        if det is not None and 0.0 < det < 1.0:
            det_pairs.append((r["marketId"], won, det))

    print("  distinct markets: %d with a venue verdict (of %d seen)"
          % (len([k for k, v in cache.items() if v]), len(set(r["marketId"] for r in rows))))
    print("  skipped rows: %d unlabeled outcome, %d no verdict yet, %d no snapshot at/before, "
          "%d snapshot older than %ds" % (unlabeled, no_verdict, no_snap, stale, args.max_lag))
    print("  market kinds: %s" % dict(kinds))
    if lags:
        lags.sort()
        print("  snapshot lag (s): median %.0f  p90 %.0f  max %.0f"
              % (lags[len(lags) // 2], lags[int(0.9 * len(lags))], lags[-1]))

    print("\nCOUNTERFACTUAL EDGE on the trades the gates walked away from (held to resolution):")
    variants = []
    for name, pairs in (("snapshot", snap_pairs), ("detected", det_pairs)):
        v = build_variant(name, pairs, args.boot)
        if not v:
            print("  %-9s no usable rows" % name)
            continue
        variants.append(v)
        print("  %-9s n=%4d markets=%3d win=%.1f%%  MEAN EDGE %+.4f/$1  clustered 95%% CI [%+.4f, %+.4f]%s"
              % (v["name"], v["n"], v["markets"], 100 * v["win_rate"], v["mean_edge"],
                 v["ci95"][0], v["ci95"][1], "  <-- CI EXCLUDES 0" if v["excludes_zero"] else ""))

    print("\nREAD: a CI that excludes 0 means the exclusion is forgoing measured edge and the")
    print("gates are worth fixing on purpose. A CI spanning 0 means these skips cost nothing")
    print("measurable and the gap is hygiene, not edge. Either way the blacklist is not the")
    print("cause: category token is `btc`, the blacklist names `bitcoin`, and the skips come")
    print("from the 2h min-time-to-resolution and drift gates.")

    out = args.out or os.path.join(ROOT, "data", "pm-btc-skip-probe-%s.json"
                                   % datetime.now(timezone.utc).strftime("%Y%m%d"))
    payload = {
        "asOf": datetime.now(timezone.utc).isoformat(),
        "market_pattern": "btc-updown%",
        "decisions_total": len(rows),
        "distinct_markets": len(set(r["marketId"] for r in rows)),
        "skipped_rows": {"unlabeled_outcome": unlabeled, "no_verdict": no_verdict,
                         "no_snapshot": no_snap, "snapshot_stale": stale},
        "snapshot_lag_s": {"median": lags[len(lags) // 2] if lags else None,
                           "p90": lags[int(0.9 * len(lags))] if lags else None,
                           "max": lags[-1] if lags else None,
                           "max_lag_allowed": args.max_lag},
        "market_kinds": dict(kinds),
        "variants": variants,
        "fee_rate": FEE_RATE,
        "caveats": [
            "exit-blind: holds to resolution, live copies also face exit rules",
            "liquidity was $0 < $750 min on the sampled rows, so a fill at either entry price is an assumption",
            "ground truth is the venue's own resolution read keylessly (closed event + 1/0 leg), not a snapshot heuristic",
            "category token is `btc`; the C-200 blacklist names `bitcoin`, so the blacklist is not the exclusion cause",
        ],
    }
    with open(out, "w") as fh:
        json.dump(payload, fh, indent=1)
    print("\nwrote %s" % out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
