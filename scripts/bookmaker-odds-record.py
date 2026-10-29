#!/usr/bin/env python3
"""
bookmaker-odds-record.py — record bookmaker CONSENSUS pre-match prices as a forward corpus.

WHY: bookmaker consensus is the one external quantity that is genuinely orthogonal to a Polymarket
price -- it is an independent estimate of the same probability, from 60+ books, with no shared order
book. REC 2 of the data-feed research (2026-10-29). It cannot be backfilled: the vendor states plainly
that there is no history and no closing prices in the feed, so this corpus only grows at the speed of
settlement and is worth exactly what we start recording now.

THE VIG IS THE WHOLE PROBLEM. A bookmaker's 1.65 decimal price implies 60.6%, but that number is
1.65 INCLUDING a margin -- median margin on the soccer result market in the sample is 8.7% (american
football 6.2%, baseball 7.0%, ice hockey 7.8%, basketball 8.1%). Comparing a raw implied probability
to a Polymarket price would show Polymarket as better on essentially every market, and that "finding"
would be nothing but the vig. So every price here is DE-VIGGED first: normalize 1/price so the
bookmaker's own outcomes sum to 1, which recovers their fair probability. Consensus is then the
MEDIAN of those fair probabilities across books, not the mean -- a single stale or fat-fingered quote
should not move it.

MODES
  --mode sample      validate + seed from the CC BY 4.0 HF sample (events.csv + matched_prices.csv).
                     Keyless. Proves the transform and writes the first rows.
  --mode board-json  the API's OWN JSON shape (the sample ships standard_board.json in exactly that
                     shape). This is the code path that will run unchanged once a token exists, so it
                     is validated against real API-shaped payloads today rather than guessed at.
  --mode api         the live feed. Requires ODDSRELAY_TOKEN in ~/.hermes/.env. The HTTP endpoint is
                     UNVERIFIED -- see the note in fetch_api(); this mode refuses rather than inventing
                     a URL and silently recording nothing.

Output: data/bookmaker-odds.jsonl  (append-only, one row per event/market/outcome/as-of)
        data/bookmaker-odds-summary.json

Usage:
  python3 scripts/bookmaker-odds-record.py --mode sample
  python3 scripts/bookmaker-odds-record.py --mode board-json --path data/cache/oddsrelay-sample/standard_board.json
  python3 scripts/bookmaker-odds-record.py --mode api --dry-run
"""
from __future__ import annotations

import argparse
import collections
import csv
import datetime as dt
import json
import os
import statistics
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SAMPLE_DIR = os.path.join(ROOT, "data", "cache", "oddsrelay-sample")
OUT = os.path.join(ROOT, "data", "bookmaker-odds.jsonl")
SUMMARY = os.path.join(ROOT, "data", "bookmaker-odds-summary.json")
ENV = os.path.expanduser("~/.hermes/.env")


def load_env_token(name: str = "ODDSRELAY_TOKEN") -> str | None:
    """Read one key out of ~/.hermes/.env. Never print the value."""
    if not os.path.exists(ENV):
        return None
    with open(ENV, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            if k.strip() == name:
                v = v.strip().strip('"').strip("'")
                return v or None
    return None


def devig(prices: dict[str, float]) -> dict[str, float] | None:
    """Turn one bookmaker's prices on one market into fair probabilities.

    Returns None when any price is malformed or <= 1.0 -- a decimal price at or below 1.0 is not a price,
    and letting one through would poison the normalization for every other outcome in the market.
    """
    inv = {}
    for outcome, price in prices.items():
        try:
            p = float(price)
        except (TypeError, ValueError):
            return None
        if p <= 1.0:
            return None
        inv[outcome] = 1.0 / p
    total = sum(inv.values())
    if total <= 0:
        return None
    return {k: v / total for k, v in inv.items()}


def consensus(book_probs: list[dict[str, float]]) -> dict[str, dict]:
    """Median fair probability per outcome across books, with dispersion and a book count.

    Only books pricing the SAME outcome set are compared. An earlier version intersected the sets, which
    looked reasonable and was wrong: dropping the favourite from a three-way market left the survivors
    summing to 0.30, so every consensus for that market was silently scaled down. Measured on the sample,
    the worst deviation was 0.6987 -- a 70% error that nothing downstream would have flagged.
    """
    if not book_probs:
        return {}
    sigs = collections.Counter(frozenset(bp.keys()) for bp in book_probs)
    modal, n_modal = sigs.most_common(1)[0]
    if n_modal < 2:
        return {}
    book_probs = [bp for bp in book_probs if frozenset(bp.keys()) == modal]
    outcomes = set(modal)
    out = {}
    for o in outcomes:
        vals = sorted(bp[o] for bp in book_probs)
        med = statistics.median(vals)
        out[o] = {
            "consensus_fair_p": round(med, 6),
            "n_books": len(vals),
            "p10": round(vals[max(0, int(0.10 * (len(vals) - 1)))], 6),
            "p90": round(vals[min(len(vals) - 1, int(0.90 * (len(vals) - 1)))], 6),
        }
    return out


def rows_from_sample() -> tuple[list[dict], dict]:
    ev_path = os.path.join(SAMPLE_DIR, "events.csv")
    px_path = os.path.join(SAMPLE_DIR, "matched_prices.csv")
    for p in (ev_path, px_path):
        if not os.path.exists(p):
            sys.exit(f"missing {p} — run: curl -sL -o {p} <hf raw url>")
    events = {}
    with open(ev_path, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            events[r["event_id"]] = r

    # group[event][market][point][bookmaker][outcome] = price
    group: dict = collections.defaultdict(
        lambda: collections.defaultdict(lambda: collections.defaultdict(lambda: collections.defaultdict(dict))))
    with open(px_path, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            group[r["event_id"]][r["market"]][r.get("point") or ""][r["bookmaker_key"]][r["outcome"]] = r["price"]

    as_of = "2026-10-11T20:16:34Z"   # the snapshot instant, stated by the vendor's own summary.md
    rows = []
    for eid, markets in group.items():
        ev = events.get(eid, {})
        for market, points in markets.items():
            for point, books in points.items():
                probs = [devig(px) for px in books.values()]
                probs = [p for p in probs if p]
                cons = consensus(probs)
                for outcome, c in cons.items():
                    rows.append({
                        "as_of": as_of, "source": "sample", "event_id": eid,
                        "sport": ev.get("sport"), "competition": ev.get("competition"),
                        "commence_time": ev.get("commence_time"),
                        "home_team": ev.get("home_team"), "away_team": ev.get("away_team"),
                        "event_name": ev.get("event_name") or None,
                        "market": market, "point": point or None, "outcome": outcome,
                        "consensus_fair_p": c["consensus_fair_p"], "n_books": c["n_books"],
                        "p10": c["p10"], "p90": c["p90"],
                        "dispersion_p": round(c["p90"] - c["p10"], 6),
                    })
    meta = {"as_of": as_of, "events": len(group), "bookmakers": None}
    return rows, meta


def rows_from_board_json(path: str) -> tuple[list[dict], dict]:
    """Read the API's own board shape.

    The sample ships standard_board.json in the API's JSON shape, so this path is exercised on real
    API-shaped data. The parser is deliberately tolerant about the envelope (a list, or a dict with a
    data/events/board key) because the live envelope is the one thing not yet seen.
    """
    with open(path, "r", encoding="utf-8") as fh:
        raw = json.load(fh)
    if isinstance(raw, list):
        events = raw
    else:
        events = raw.get("data") or raw.get("events") or raw.get("board") or []
        if isinstance(events, dict):
            events = events.get("events") or []
    if not isinstance(events, list):
        sys.exit(f"unrecognised board shape in {path} — refusing to guess")

    as_of = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    rows = []
    for ev in events:
        eid = ev.get("event_id") or ev.get("id")
        books = ev.get("bookmakers") or ev.get("books") or []
        # group[market][point][book][outcome]
        group: dict = collections.defaultdict(
            lambda: collections.defaultdict(lambda: collections.defaultdict(lambda: collections.defaultdict(dict))))
        for b in books:
            bkey = b.get("bookmaker_key") or b.get("key") or b.get("name")
            for m in (b.get("markets") or []):
                mkey = m.get("market") or m.get("key")
                for o in (m.get("outcomes") or []):
                    group[mkey][o.get("point") or ""][bkey][o.get("name") or o.get("outcome")] = o.get("price")
        for market, points in group.items():
            for point, bks in points.items():
                probs = [devig(px) for px in bks.values()]
                probs = [p for p in probs if p]
                for outcome, c in consensus(probs).items():
                    rows.append({
                        "as_of": as_of, "source": "board_json", "event_id": eid,
                        "sport": ev.get("sport"), "competition": ev.get("competition"),
                        "commence_time": ev.get("commence_time"),
                        "home_team": ev.get("home_team"), "away_team": ev.get("away_team"),
                        "event_name": ev.get("event_name"),
                        "market": market, "point": point or None, "outcome": outcome,
                        "consensus_fair_p": c["consensus_fair_p"], "n_books": c["n_books"],
                        "p10": c["p10"], "p90": c["p90"],
                        "dispersion_p": round(c["p90"] - c["p10"], 6),
                    })
    return rows, {"as_of": as_of, "events": len(events)}


def fetch_api() -> tuple[list[dict], dict]:
    """The live feed.

    DELIBERATELY NOT IMPLEMENTED AS A GUESS. The endpoint path, auth header and pagination of the
    OddsRelay API are not documented anywhere this machine can read, and inventing a plausible URL
    would produce a request that returns 404 or an empty board -- which parses identically to "no
    events listed". That is the exact failure the probes in this repo are required to print HTTP status
    and byte size to avoid. So this mode refuses until the endpoint is confirmed.
    """
    token = load_env_token("ODDSRELAY_TOKEN")
    if not token:
        sys.exit(
            "No ODDSRELAY_TOKEN in ~/.hermes/.env.\n\n"
            "  Add it yourself (never through chat):\n"
            "    echo 'ODDSRELAY_TOKEN=<your token>' >> ~/.hermes/.env && chmod 600 ~/.hermes/.env\n\n"
            "  Until the endpoint is confirmed against the API docs, also set:\n"
            "    ODDSRELAY_BASE=https://<host from the docs>\n"
            "    ODDSRELAY_PATH=/<path from the docs>\n"
        )
    base = load_env_token("ODDSRELAY_BASE")
    path = load_env_token("ODDSRELAY_PATH")
    if not base or not path:
        sys.exit(
            "ODDSRELAY_TOKEN is present but ODDSRELAY_BASE / ODDSRELAY_PATH are not, and the endpoint is\n"
            "not documented anywhere readable from this host. Refusing to invent a URL — a wrong endpoint\n"
            "returns an empty board that is indistinguishable from a feed with no events.\n"
            "Set both from the API docs, then re-run --mode api."
        )
    url = base.rstrip("/") + "/" + path.lstrip("/")
    print(f"[api] would GET {url} with a bearer token ({len(token)} chars) — not yet enabled")
    sys.exit("api mode is staged but disabled pending endpoint confirmation.")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["sample", "board-json", "api"], default="sample")
    ap.add_argument("--path", help="board json path for --mode board-json")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if args.mode == "sample":
        rows, meta = rows_from_sample()
    elif args.mode == "board-json":
        if not args.path:
            sys.exit("--mode board-json requires --path")
        rows, meta = rows_from_board_json(args.path)
    else:
        rows, meta = fetch_api()

    # Sanity: a consensus market must sum to 1. If it does not, the de-vig is wrong and every number
    # downstream inherits the error.
    by_mkt = collections.defaultdict(float)
    for r in rows:
        by_mkt[(r["event_id"], r["market"], r["point"])] += r["consensus_fair_p"]
    sums = sorted(by_mkt.values())
    worst = max((abs(s - 1.0) for s in sums), default=0.0)

    print(f"rows: {len(rows)}  events: {meta.get('events')}  markets: {len(by_mkt)}")
    print(f"consensus-sum check: min {sums[0]:.4f} median {statistics.median(sums):.4f} "
          f"max {sums[-1]:.4f}  worst deviation {worst:.4f}")
    if worst > 0.02:
        print("  !! a market's consensus probabilities do not sum to 1 — de-vig or grouping is wrong")
    sports = collections.Counter(r["sport"] for r in rows)
    print("sports:", dict(sports.most_common(8)))

    summary = {
        "generated_at": dt.datetime.now().isoformat(timespec="seconds"),
        "mode": args.mode, "as_of": meta.get("as_of"), "rows": len(rows),
        "events": meta.get("events"), "markets": len(by_mkt),
        "worst_consensus_sum_deviation": round(worst, 6),
        "sports": dict(sports),
        "coverage_note": ("our traded book: 4091 distinct markets, 890 (21.8%) sport, and 100% of those "
                          "sport markets are in families this feed covers (measured 2026-10-29)"),
    }

    if args.dry_run:
        print("[dry-run] nothing written")
        return 0

    with open(OUT, "a", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, sort_keys=True) + "\n")
    with open(SUMMARY, "w", encoding="utf-8") as fh:
        json.dump(summary, fh, indent=2)
    print(f"appended {len(rows)} rows -> {os.path.relpath(OUT, ROOT)}; summary -> {os.path.relpath(SUMMARY, ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
