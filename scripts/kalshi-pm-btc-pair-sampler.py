#!/usr/bin/env python3
"""Kalshi x Polymarket BTC up/down PAIRED read — SAMPLER (card kalshi-pm-btc-pair-prereg).

PRE-REGISTRATION — written 2026-10-13 BEFORE the first sample row existed, so the gate
cannot drift to fit the data. Read `scripts/kalshi-pm-btc-pair-read.py` for the decision rule.

WHY THIS PAIR
-------------
`KXBTC15M` (Kalshi) and `btc-updown-15m-*` (Polymarket) are the ONLY cross-venue pair in
either family that aligns exactly: same 15-minute wall-clock window, same binary proposition.
Temperature and oil die on ontology (a one-degree bucket-grid offset; "above 84.99" vs integer
strikes) and produce zero exact-alignment rows. But the two venues settle on DIFFERENT ORACLES
(Kalshi: simple average of sixty seconds of CF Benchmarks' BRTI; Polymarket: Chainlink BTC/USD
60s TWAP), and that basis is the risk this study prices — measured 2026-10-13 at 282/287
windows agreeing over 3 days (1.74% disagreement, 95% CI 0.75-4.01%).

  Legs are bought on BOTH venues, opposite directions, same window:
    direction A = PM Up  + Kalshi No     (both lose only when Kalshi=up AND PM=down)
    direction B = PM Down + Kalshi Yes   (both lose only when Kalshi=down AND PM=up)
  Either pair pays 1.00 per pair whenever the venues agree (the fatal case pays 0.00; the
  "both win" disagreement direction pays 2.00 and is deliberately ignored — conservative).
  So the trade is: pay `cost` + fees now for 1.00, minus the per-direction oracle-fatal rate.

WHAT IT RECORDS (one JSONL row per sample, data/kalshi-pm-btc-pair.jsonl)
  * both venues' touch quotes AND the price+size of each leg actually needed, read
    back-to-back with the measured clock skew between them (`read_skew_ms`, must be <1000);
  * Kalshi's real depth from `/markets/{ticker}/orderbook?depth=10` (`orderbook_fp.yes_dollars`
    / `no_dollars` are resting BIDS; a resting No bid at P is a Yes ask at 1-P), plus the
    market object's own top-of-book as a cross-check (`quote_agreement`);
  * Polymarket's real depth from `clob.polymarket.com/book` for BOTH tokens — NEVER Gamma's
    `bestBid`/`bestAsk`, which is stale by up to ~0.6 on these markets (measured 2026-10-12);
  * for each direction: `cost` (sum of the two ask prices), `fee` (per-leg), `net` (= 1.00 -
    cost - fee), and `pairs` (the executable size = min of the two legs' size at those prices);
  * COVERAGE: one row per invocation in data/kalshi-pm-pair-coverage.jsonl (named with a
    different prefix on purpose — it must not match the sample glob);
  * ROTATION: samples land in data/kalshi-pm-btc-pair-<UTC date>.jsonl (one file per day,
    ~7 MB/day) rather than one ever-growing file, so no single tracked file can approach the
    nightly backup's 95 MB guard; the analyzer globs the whole series.
  * Kalshi's touch exists TWICE and they disagree by ~1c on the live market (measured
    2026-10-13: market-summary `yes_bid` 0.61 vs a resting yes bid at 0.62 in the ladder, i.e.
    a 1c-better No offer), so every row carries BOTH: `cost`/`net` are priced at the WORSE
    (higher) Kalshi ask and `cost_optimistic`/`net_optimistic` at the better one. The gate is
    evaluated on the conservative pair, so a pass cannot be an artefact of snapshot choice.

FEE SCHEDULE — PINNED 2026-10-13 from the venue's own structured fields, not from a constant
  * Polymarket: Gamma publishes `feeType=crypto_fees_v2` and
    `feeSchedule={rate:0.07, exponent:1, takerOnly:true, rebateRate:0.2}` for this market, and
    `scripts/bt-fee-maker-calibration` (archive-measured, $1.21B of fees) established the law
    `taker fee = rate x shares x min(p, 1-p)` with makers at $0. So 0.07 * min(p,1-p) per share.
    TRAP: `takerBaseFee`/`makerBaseFee`/CLOB `/fee-rate` are a legacy constant 1000 on ~85% of
    markets regardless of schedule — pricing base/1e4 would charge 0.10/share here. Not used.
  * Kalshi: taker 0.07 * P * (1-P) per contract (repo constant `KALSHI_FEE_RATE`, published
    schedule; the fee audit still flags it as needing live confirmation), maker 0.
  * Both legs are crossed here (taker/taker) — the cleaner, more conservative read. The PM
    `rebateRate` of 0.2 applies to MAKERS only and is not modelled.

READ-ONLY: public keyless endpoints, no key, no order surface, nothing written to any book.

Usage: python3 scripts/kalshi-pm-btc-pair-sampler.py --seconds 700 --interval 20
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUTFILE = ROOT / "data" / "kalshi-pm-btc-pair.jsonl"
KALSHI = "https://api.elections.kalshi.com/trade-api/v2"
GAMMA = "https://gamma-api.polymarket.com"
CLOB = "https://clob.polymarket.com"
UA = {"User-Agent": "copybot-kalshi-pm-pair/1.0"}
BUCKET = 900  # 15 minutes
PM_FEE_RATE = 0.07   # crypto_fees_v2, pinned (see header)
KALSHI_FEE_RATE = 0.07


def get_json(url, timeout=20, retries=3):
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
            time.sleep(0.6)
    raise RuntimeError("request failed: %s (%s)" % (url, last))


def fnum(v, default=None):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def iso(ts):
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def pm_fee(price):
    return PM_FEE_RATE * min(price, 1.0 - price)


def kalshi_fee(price):
    return KALSHI_FEE_RATE * price * (1.0 - price)


def kalshi_asks(book):
    """orderbook_fp -> ({price: size} ask ladder for YES, same for NO).

    Kalshi's `yes_dollars`/`no_dollars` are resting BIDS. A resting NO bid at P is a YES offer
    at 1-P, and vice versa, so each side's bid ladder becomes the other side's ask ladder.
    """
    yes_bids, no_bids = {}, {}
    for p, s in (book.get("yes_dollars") or []):
        price, size = fnum(p), fnum(s)
        if price and size:
            yes_bids[price] = size
    for p, s in (book.get("no_dollars") or []):
        price, size = fnum(p), fnum(s)
        if price and size:
            no_bids[price] = size
    yes_asks = {round(1.0 - p, 4): s for p, s in no_bids.items()}
    no_asks = {round(1.0 - p, 4): s for p, s in yes_bids.items()}
    return yes_asks, no_asks, yes_bids, no_bids


def kalshi_side(ticker, close_iso, depth):
    """Touch + depth for the KXBTC15M market closing at close_iso."""
    listing = get_json("%s/markets?series_ticker=KXBTC15M&status=open&limit=200" % KALSHI)
    market = None
    for m in listing.get("markets") or []:
        if (m.get("close_time") or "").startswith(close_iso[:16]):
            market = m
            break
    if market is None:
        return None
    yes_bid = fnum(market.get("yes_bid_dollars"))
    yes_ask = fnum(market.get("yes_ask_dollars"))
    yes_bid_sz = fnum(market.get("yes_bid_size_fp"))
    yes_ask_sz = fnum(market.get("yes_ask_size_fp"))
    # TWO sources of the Kalshi touch, recorded side by side (they disagree by ~1c):
    #   object = the market summary's own top-of-book (Kalshi's published quote)
    #   book   = the resting-order ladder, where a resting NO bid at P is a YES offer at 1-P
    # The pair price uses the WORSE of the two for us (see pairs below), so a net number can
    # never be an artefact of picking the friendlier snapshot.
    out = {
        "ticker": market.get("ticker"),
        "yes_bid": yes_bid, "yes_bid_size": yes_bid_sz,
        "yes_ask": yes_ask, "yes_ask_size": yes_ask_sz,
        "no_ask_obj": round(1.0 - yes_bid, 4) if yes_bid else None,
        "no_ask_obj_size": yes_bid_sz,
        "no_ask": round(1.0 - yes_bid, 4) if yes_bid else None,  # kept for continuity
        "no_ask_size": yes_bid_sz,
        "volume": fnum(market.get("volume_fp")),
        "read_at": iso(time.time()),
    }
    try:
        ob = get_json("%s/markets/%s/orderbook?depth=%d" % (KALSHI, market["ticker"], depth))
    except Exception as exc:
        out["book_error"] = str(exc)[:120]
        return out
    book = ob.get("orderbook_fp") or ob.get("orderbook") or {}
    yes_asks, no_asks, yes_bids, no_bids = kalshi_asks(book)
    out["book_yes_levels"] = len(yes_asks)
    out["book_no_levels"] = len(no_asks)
    if yes_asks:
        best = max(yes_asks)
        out["yes_ask_book"] = best
        out["yes_ask_book_size"] = yes_asks[best]
        out["yes_ask_book_size_capped"] = False
        out["quote_agreement"] = (yes_ask is not None and abs(best - yes_ask) <= 0.011)
    if no_asks:
        best = max(no_asks)
        out["no_ask_book"] = best
        out["no_ask_book_size"] = no_asks[best]
    if yes_ask is not None and out.get("yes_ask_book") is not None:
        out["quote_gap_yes_ask"] = round(out["yes_ask_book"] - yes_ask, 4)
    if out.get("no_ask_obj") is not None and out.get("no_ask_book") is not None:
        out["quote_gap_no_ask"] = round(out["no_ask_book"] - out["no_ask_obj"], 4)
    # cumulative size reachable within 1c of the touch, per side
    for label, ladder, touch in (("yes", yes_asks, yes_ask), ("no", no_asks, out["no_ask"])):
        if ladder and touch:
            out["cum_%s_1c" % label] = round(sum(s for p, s in ladder.items()
                                                 if p is not None and p <= touch + 0.0101), 2)
            out["cum_%s_2c" % label] = round(sum(s for p, s in ladder.items()
                                                 if p is not None and p <= touch + 0.0201), 2)
    return out


def pm_side(bucket, depth):
    """Touch + depth for both legs of the PM event at this bucket (CLOB book, not Gamma quotes)."""
    ev = get_json("%s/events?slug=btc-updown-15m-%d" % (GAMMA, bucket))
    if not isinstance(ev, list) or not ev:
        return None
    event = ev[0]
    markets = event.get("markets") or []
    if not markets:
        return None
    m = markets[0]
    raw_o, raw_t = m.get("outcomes"), m.get("clobTokenIds")
    outcomes = json.loads(raw_o) if isinstance(raw_o, str) else raw_o
    tokens = json.loads(raw_t) if isinstance(raw_t, str) else raw_t
    if not outcomes or not tokens:
        return None
    out = {"slug": m.get("slug"), "title": event.get("title"), "closed": bool(event.get("closed")),
           "gamma_quote_stale_check": {"bestBid": m.get("bestBid"), "bestAsk": m.get("bestAsk")},
           "conditionId": m.get("conditionId")}
    for name, token in zip(outcomes, tokens):
        key = str(name).strip().lower()
        try:
            bk = get_json("%s/book?token_id=%s" % (CLOB, token))
        except Exception as exc:
            out["%s_error" % key] = str(exc)[:120]
            continue
        bids = sorted(([(fnum(x["price"]), fnum(x["size"])) for x in bk.get("bids") or []]),
                      key=lambda t: -(t[0] or 0.0))
        asks = sorted(([(fnum(x["price"]), fnum(x["size"])) for x in bk.get("asks") or []]),
                      key=lambda t: (t[0] or 0.0))
        out["%s_bid" % key] = bids[0][0] if bids else None
        out["%s_bid_size" % key] = bids[0][1] if bids else None
        out["%s_ask" % key] = asks[0][0] if asks else None
        out["%s_ask_size" % key] = asks[0][1] if asks else None
        out["%s_ask_levels" % key] = len(asks)
        if asks:
            out["%s_cum_1c" % key] = round(sum((s or 0.0) for p, s in asks
                                               if p is not None and p <= (asks[0][0] or 0) + 0.0101), 2)
            out["%s_cum_2c" % key] = round(sum((s or 0.0) for p, s in asks
                                               if p is not None and p <= (asks[0][0] or 0) + 0.0201), 2)
        out["%s_read_at" % key] = iso(time.time())
    return out


def sample(bucket, depth):
    close_iso = iso(bucket + BUCKET)
    t0 = time.time()
    try:
        pm = pm_side(bucket, depth)
    except Exception as exc:
        return {"bucket": bucket, "error": "pm: %s" % str(exc)[:140]}
    if not pm:
        return {"bucket": bucket, "error": "pm: no event for bucket"}
    try:
        kal = kalshi_side(None, close_iso, depth)
    except Exception as exc:
        return {"bucket": bucket, "error": "kalshi: %s" % str(exc)[:140]}
    if not kal:
        return {"bucket": bucket, "error": "kalshi: no market closing at %s" % close_iso}
    skew_ms = int((time.time() - t0) * 1000)

    now = time.time()
    row = {
        "ts": iso(now), "ts_epoch": round(now, 3), "bucket": bucket, "close": close_iso,
        "secs_into_window": round(now - bucket, 1),
        "read_skew_ms": skew_ms,
        "pm": pm, "kalshi": kal,
        "fee_model": {"pm_rate": PM_FEE_RATE, "pm_law": "rate*min(p,1-p) taker, maker 0",
                      "kalshi_rate": KALSHI_FEE_RATE, "kalshi_law": "rate*p*(1-p) taker, maker 0",
                      "pm_feeType": "crypto_fees_v2"},
        "pairs": {},
    }
    legs = {
        # direction: (pm leg key, kalshi OBJECT ask key, kalshi BOOK ask key)
        "A": ("up", "no_ask_obj", "no_ask_book"),      # PM Up  + Kalshi No
        "B": ("down", "yes_ask", "yes_ask_book"),      # PM Down + Kalshi Yes
    }
    for direction, (pm_key, k_obj_key, k_book_key) in legs.items():
        pm_ask = pm.get("%s_ask" % pm_key)
        pm_sz = pm.get("%s_ask_size" % pm_key)
        candidates = [x for x in (kal.get(k_obj_key), kal.get(k_book_key)) if x]
        if not pm_ask or not candidates:
            row["pairs"][direction] = {"complete": False, "pm_ask": pm_ask,
                                       "kalshi_asks": candidates}
            continue
        # canonical = the WORSE (higher) Kalshi ask; optimistic = the better one
        k_ask = max(candidates)
        k_ask_opt = min(candidates)
        cost = pm_ask + k_ask
        fee = pm_fee(pm_ask) + kalshi_fee(k_ask)
        cost_opt = pm_ask + k_ask_opt
        fee_opt = pm_fee(pm_ask) + kalshi_fee(k_ask_opt)
        k_sz = kal.get("no_ask_size" if direction == "A" else "yes_ask_size")
        row["pairs"][direction] = {
            "complete": True,
            "pm_leg": "PM %s @ %.4f (sz %.1f)" % (pm_key.upper(), pm_ask, pm_sz or 0),
            "kalshi_leg": "KAL @ %.4f (obj %s / book %s)" % (k_ask, kal.get(k_obj_key), kal.get(k_book_key)),
            "cost": round(cost, 6),
            "fee": round(fee, 6),
            "net": round(1.0 - cost - fee, 6),
            "cost_optimistic": round(cost_opt, 6),
            "net_optimistic": round(1.0 - cost_opt - fee_opt, 6),
            "pairs_executable": min([s for s in (pm_sz, k_sz) if s] or [0]),
        }
    return row


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=int, default=700, help="sampling span per invocation")
    ap.add_argument("--interval", type=float, default=20.0, help="seconds between samples")
    ap.add_argument("--depth", type=int, default=10)
    ap.add_argument("--out", default=None,
                    help="exact output file (testing); default is per-UTC-day rotation")
    # NOTE the deliberately different prefix: the samples series is `kalshi-pm-btc-pair-*.jsonl`
    # and the analyzer globs exactly that, so the coverage file must NOT match it (a coverage row
    # has no `bucket`/`pairs` and would otherwise be counted as a sample).
    ap.add_argument("--coverage", default=str(ROOT / "data" / "kalshi-pm-pair-coverage.jsonl"),
                    help="one coverage row per invocation, so coverage is MEASURED not assumed")
    args = ap.parse_args()

    started = time.time()
    written = errors = 0
    row = {}
    err_examples = []
    per_window = {}
    fh = None
    cur_path = None
    while time.time() - started < args.seconds:
        loop_start = time.time()
        bucket = int(loop_start) // BUCKET * BUCKET
        row = sample(bucket, args.depth)
        row["run_id"] = int(started)
        if row.get("error"):
            errors += 1
            if len(err_examples) < 3:
                err_examples.append(row.get("error"))
        else:
            written += 1
            w = per_window.setdefault(row["bucket"], {"samples": 0, "secs": [], "cal": 0})
            w["samples"] += 1
            w["secs"].append(row["secs_into_window"])
            for d in ("A", "B"):
                if (row["pairs"].get(d) or {}).get("complete"):
                    w["cal"] += 1
        target = args.out or str(ROOT / "data" / ("kalshi-pm-btc-pair-%s.jsonl"
                                                 % datetime.now(timezone.utc).strftime("%Y%m%d")))
        if target != cur_path:
            if fh:
                fh.close()
            fh = open(target, "a")
            cur_path = target
        fh.write(json.dumps(row) + "\n")
        fh.flush()
        sleep_for = args.interval - (time.time() - loop_start)
        if sleep_for > 0:
            time.sleep(sleep_for)
    if fh:
        fh.close()
    # coverage row: the analyzer must never have to ASSUME how much of each window was sampled
    cov = {
        "run_id": int(started),
        "started": iso(started), "ended": iso(time.time()),
        "samples_written": written, "errors": errors,
        "wall_seconds": round(time.time() - started, 1),
        "interval_s": args.interval, "requested_seconds": args.seconds,
        "windows": {str(b): {"samples": w["samples"], "with_both_legs": w["cal"],
                             "secs_min": round(min(w["secs"]), 1),
                             "secs_max": round(max(w["secs"]), 1)}
                    for b, w in per_window.items()},
        "error_examples": err_examples,
    }
    with open(args.coverage, "a") as fh:
        fh.write(json.dumps(cov) + "\n")

    # observability contract (matches the other copybot jobs): SILENT when healthy, one line
    # only when degraded, so the 15-minute cron does not spam Discord.
    if errors and errors >= max(1, written // 4):
        print("🟠 kalshi-pm-pair: %d/%d samples failed (e.g. %s)"
              % (errors, errors + written, (err_examples or ["?"])[0][:110]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
