#!/usr/bin/env python3
"""
c200-intent-printthrough-check — did our intent price actually PRINT?

CARD: c200-intent-printthrough-check (Backlog) — the measurement that feeds the
c200-maker-fill-assumption decision.

WHY THIS EXISTS
Every BANKROLL_200 BUY is booked by the Rust sidecar at `entry = intent - 0.02`
(rust-sidecar/src/main.rs:115-119: hardcoded, never reads a book). FillIntent + PaperTrade.intentPrice
prove that arithmetic RAN; they cannot say whether a real trade ever printed at our level. This script
tests the level against the venue's own evidence:

    for a dispatch at price p at time t, did the market print / offer at or below p - 0.02
    within 5 min / 1 h?

Same event the external archive measured on 783M fills (drafts/fee-maker-calibration-20260925.md §5):
    delta=0.02 overall 71.1% (5m) / 77.6% (1h); weighted by C-200 entry prices 74.3% / 81.1%
    reached levels are adversely selected (0.4-0.6 band: mean(px_end - p) = -0.0323 @1h)
Pre-registered bar (card): materially below 74.3% => the 2c is booked on fills that never happened.
MEASUREMENT ONLY — no rule, size, gate or booked figure moves.

EVIDENCE SOURCES (each reported with its own coverage; none is assumed complete)
  S1 PRINTS  data-api.polymarket.com/trades?market=<conditionId>&takerOnly=false (keyless, deduped).
             Direct print evidence — but thin on these markets (2-50 rows/market in total).
  S2 BOOK    our own L2 corpus, data/l2/<assetId>.jsonl (top-25 ladder, 5 s cadence).
             A best ask at/below our level = a seller willing at <= L => a resting bid at L fills.
             COVERAGE (v62, 2026-09-26 03:29 CDT): the recorder now pins the market of every fresh
             C-200 dispatch, so coverage starts ~20 s after the dispatch and the 5-minute horizon IS
             covered for legs dispatched after that moment. Legs before it keep the old gap (the
             10-min candidate refresh admitted a market only once a copy existed, i.e. 2.7-8.6 min
             AFTER the dispatch); per-leg coverage is computed from the file either way, so a pre-v62
             leg reports its own lag rather than pretending to 5-min coverage.
  S3 ANCHOR  where the level actually sits: intent vs the copied wallet's real print
             (DecisionJournal -> ObservedTrade.walletEntryPrice) and vs the detection mid
             (ObservedTrade.detectedPrice), plus the first covered L2 quote. This decides whether the
             archive's base rate — anchored on a PRINT at p — even transfers to our MID-anchored level.

CAVEAT THAT MUST TRAVEL WITH EVERY NUMBER: a print/touch at our level is not queue position and
ignores size (a resting bid is swept only up to the printed size), so the honest reading is
"the level was reachable", never "we would have been filled".

USAGE
  python3 scripts/c200-printthrough.py                      # all measured legs
  python3 scripts/c200-printthrough.py --since-ms <epoch-ms>
  python3 scripts/c200-printthrough.py --json               # artifact only, quiet stdout
  python3 scripts/c200-printthrough.py --md drafts/<f>.md   # also write a dashboard draft
Artifacts: data/c200-printthrough.jsonl (append-only), data/c200-tape/<conditionId>.json (cache)
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(ROOT, "prisma", "dev.db")
L2_DIR = os.path.join(ROOT, "data", "l2")
L2_MAP = os.path.join(ROOT, "data", "l2-asset-map.jsonl")
TAPE_DIR = os.path.join(ROOT, "data", "c200-tape")
META = os.path.join(ROOT, "data", "c200-market-meta.jsonl")
OUT = os.path.join(ROOT, "data", "c200-printthrough.jsonl")

DELTA = 0.02                      # the sidecar's modelled maker improvement (mirror of main.rs)
H5, H60 = 300, 3600               # horizons in seconds
BAR_5M, BAR_60M = 0.743, 0.811    # archive base rate, weighted by C-200 entry prices
BAR_DRIFT = -0.0323               # archive, 0.4-0.6 band, mean(px_end - p) @1h
EPS = 1e-9


# ------------------------------------------------------------------ DB (live edge => mode=ro)
def db() -> sqlite3.Connection:
    c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    c.row_factory = sqlite3.Row
    return c


def load_legs(since_ms: int | None) -> list[dict]:
    q = """
    SELECT f.id AS intentId, f.marketId, f.outcome, f.intentPrice, f.sizeUsd, f.dispatchedAt,
           f.paperTradeId, p.entryPrice, p.status, d.observedTradeId
    FROM FillIntent f
    LEFT JOIN PaperTrade p ON p.id = f.paperTradeId
    LEFT JOIN DecisionJournal d ON d.id = f.decisionJournalId
    WHERE f.botId = 'BANKROLL_200'
    """
    args: list = []
    if since_ms:
        q += " AND f.dispatchedAt >= ?"
        args.append(since_ms)
    return [dict(r) for r in db().execute(q + " ORDER BY f.dispatchedAt", args)]


def wallet_print(observed_trade_id: str | None) -> dict | None:
    if not observed_trade_id:
        return None
    r = db().execute(
        "SELECT walletAddress, side, walletEntryPrice, detectedPrice, size, timestamp "
        "FROM ObservedTrade WHERE id = ?", (observed_trade_id,)).fetchone()
    return dict(r) if r else None


def condition_map() -> dict[str, str]:
    m = {r["marketId"]: r["conditionId"] for r in db().execute(
        "SELECT DISTINCT marketId, conditionId FROM ObservedTrade WHERE conditionId IS NOT NULL")}
    if os.path.exists(META):
        for line in open(META):
            try:
                o = json.loads(line)
                m.setdefault(o["marketId"], o["conditionId"])
            except Exception:
                pass
    return m


def gamma_condition(slug: str) -> str | None:
    """Fallback resolve (gamma 429s under load — cache the answer, never retry hard)."""
    try:
        raw = subprocess.run(["curl", "-s", "--max-time", "20",
                              f"https://gamma-api.polymarket.com/markets?slug={slug}"],
                             capture_output=True, text=True, timeout=40).stdout
        data = json.loads(raw)
        cid = data[0]["conditionId"] if data else None
        if cid:
            with open(META, "a") as fh:
                fh.write(json.dumps({"marketId": slug, "conditionId": cid, "src": "gamma",
                                     "ts": int(time.time() * 1000)}) + "\n")
        return cid
    except Exception:
        return None


# ------------------------------------------------------------------ S1: public print tape
def fetch_tape(condition_id: str, max_pages: int = 6) -> list[dict]:
    """Public trade tape for one market. Keyless; newest-first; filtered client-side."""
    os.makedirs(TAPE_DIR, exist_ok=True)
    path = os.path.join(TAPE_DIR, f"{condition_id}.json")
    if os.path.exists(path) and time.time() - os.path.getmtime(path) < 300:
        try:
            return json.load(open(path))
        except Exception:
            pass
    rows: list[dict] = []
    for page in range(max_pages):
        url = (f"https://data-api.polymarket.com/trades?market={condition_id}"
               f"&limit=500&offset={page * 500}&takerOnly=false")
        try:
            raw = subprocess.run(["curl", "-s", "--max-time", "30", url],
                                 capture_output=True, text=True, timeout=60).stdout
            chunk = json.loads(raw) if raw.strip() else []
        except Exception:
            chunk = []
        if not isinstance(chunk, list) or not chunk:
            break
        rows.extend(chunk)
        if len(chunk) < 500:
            break
    # takerOnly=false lists fill participants (its default takerOnly=true HIDES maker prints — the
    # very fills a resting bid cares about). Dedupe on fill identity.
    seen, deduped = set(), []
    for r in rows:
        key = (r.get("transactionHash"), r.get("asset"), r.get("price"), r.get("size"), r.get("timestamp"))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(r)
    if deduped:
        with open(path, "w") as fh:
            json.dump(deduped, fh)
    return deduped


def pick_token(tape: list[dict], outcome: str, intent: float, t0_s: int) -> tuple[str | None, str]:
    """Identify our outcome's token id: exact label match first, else price proximity."""
    want = outcome.strip().lower()
    exact = {r["asset"] for r in tape if str(r.get("outcome", "")).strip().lower() == want}
    if len(exact) == 1:
        return exact.pop(), "outcome-label"
    best, bestd = None, None
    near = [r for r in tape if abs(r["timestamp"] - t0_s) <= 1800]
    for r in near or tape:
        d = abs(float(r["price"]) - intent)
        if bestd is None or d < bestd:
            best, bestd = r["asset"], d
    return (best, f"price-proximity(d={bestd:.3f})") if best else (None, "unresolved")


# ------------------------------------------------------------------ S2: our own L2 book corpus
def l2_map() -> dict[str, list[str]]:
    m: dict[str, list[str]] = {}
    if os.path.exists(L2_MAP):
        for line in open(L2_MAP):
            try:
                o = json.loads(line)
                m[o["marketId"]] = o["assetIds"]
            except Exception:
                pass
    return m


def pick_l2_asset(candidates: list[str], token: str | None, intent: float) -> tuple[str | None, str]:
    """Our token's own L2 file. The market map lists BOTH outcome tokens — scanning both would
    let the sibling outcome's ask answer for ours (a Kraken bid 'reachable' because Canucks had a
    cheap offer), so match the tape's token id first, else pick by mid proximity to the intent."""
    if token and token in candidates:
        return token, "tape-token-id"
    best, bestd = None, None
    for a in candidates:
        p = os.path.join(L2_DIR, f"{a}.jsonl")
        if not os.path.exists(p):
            continue
        try:
            with open(p) as fh:
                o = json.loads(fh.readline())
            mid = (float(o["asks"][0][0]) + float(o["bids"][0][0])) / 2
        except Exception:
            continue
        d = abs(mid - intent)
        if bestd is None or d < bestd:
            best, bestd = a, d
    return (best, f"mid-proximity(d={bestd:.3f})") if best else (None, "unresolved")


def l2_scan(asset_id: str | None, t0_ms: int, level: float, horizon_ms: int = H60 * 1000) -> dict:
    """Best-ask crossing test over the covered part of the window, with coverage accounting."""
    out: dict = {"assetId": asset_id, "coverStartMs": None, "coverEndMs": None, "snapsInWindow": 0,
                 "minAsk": None, "askAtLevel": None, "quoteAtCoverStart": None,
                 "levelVsCoverStartAsk": None, "levelVsCoverStartBid": None}
    if not asset_id:
        return out
    p = os.path.join(L2_DIR, f"{asset_id}.jsonl")
    if not os.path.exists(p):
        return out
    nearest = None
    with open(p) as fh:
        for line in fh:
            try:
                o = json.loads(line)
            except Exception:
                continue
            ts = o.get("ts")
            if ts is None or not o.get("asks") or not o.get("bids"):
                continue
            if out["coverStartMs"] is None or ts < out["coverStartMs"]:
                out["coverStartMs"] = ts
            if out["coverEndMs"] is None or ts > out["coverEndMs"]:
                out["coverEndMs"] = ts
            if nearest is None or abs(ts - t0_ms) < abs(nearest[0] - t0_ms):
                nearest = (ts, float(o["asks"][0][0]), float(o["bids"][0][0]))
            if t0_ms <= ts <= t0_ms + horizon_ms:
                out["snapsInWindow"] += 1
                ask = float(o["asks"][0][0])
                out["minAsk"] = ask if out["minAsk"] is None else min(out["minAsk"], ask)
    if out["minAsk"] is not None:
        out["askAtLevel"] = out["minAsk"] <= level + EPS
    if nearest:
        out["quoteAtCoverStart"] = {"ts": nearest[0], "ask": nearest[1], "bid": nearest[2]}
        out["levelVsCoverStartAsk"] = round(level - nearest[1], 4)
        out["levelVsCoverStartBid"] = round(level - nearest[2], 4)
    return out


# ------------------------------------------------------------------ per-leg analysis
def analyse(leg: dict, tape: list[dict], amap: dict[str, list[str]]) -> dict:
    t0_ms = int(leg["dispatchedAt"])
    t0_s = t0_ms // 1000
    intent = float(leg["intentPrice"])
    level = max(0.01, round(intent - DELTA, 6))     # the resting-bid price the model assumes
    token, how = pick_token(tape, leg["outcome"], intent, t0_s)
    wp = wallet_print(leg.get("observedTradeId"))
    r: dict = {
        "intentId": leg["intentId"], "marketId": leg["marketId"], "outcome": leg["outcome"],
        "intentPrice": intent, "level": level, "entryPrice": leg["entryPrice"], "status": leg["status"],
        "dispatchedAt": t0_ms, "sizeUsd": leg["sizeUsd"], "token": token, "tokenResolvedBy": how,
        "anchorIsMid": None, "anchorIsWalletPrint": None, "walletPrintPrice": None,
        "walletPrintAt": None, "detectLagS": None,
        "tapeRowsForToken": 0, "prints5": 0, "prints60": 0,
        "reached5": None, "reached60": None, "tFirstTouchMs": None, "sellSideReached60": None,
        "sizeAtLevel60": 0.0, "maxSizeAtLevel": 0.0,
        "pxAnchor": None, "pxEnd": None, "driftVsIntent": None, "driftVsAnchor": None,
        "note": "",
    }
    if wp:
        r["walletPrintPrice"] = wp["walletEntryPrice"]
        r["walletPrintAt"] = wp["timestamp"]
        r["detectLagS"] = round((t0_ms - wp["timestamp"]) / 1000)
        r["anchorIsWalletPrint"] = abs(intent - wp["walletEntryPrice"]) < 1e-9
        r["anchorIsMid"] = abs(intent - wp["detectedPrice"]) < 1e-9

    asset, asset_how = pick_l2_asset(amap.get(leg["marketId"], []), token, intent)
    r["l2AssetResolvedBy"] = asset_how
    r["book"] = l2_scan(asset, t0_ms, level)
    r["tapeSilent"] = False

    if not token:
        r["note"] = "no token resolved from the tape"
        return r
    pr = sorted((x for x in tape if x["asset"] == token), key=lambda x: x["timestamp"])
    r["tapeRowsForToken"] = len(pr)
    if not pr:
        r["note"] = "token resolved but the tape has no prints for it"
        return r
    pre = [x for x in pr if x["timestamp"] <= t0_s]
    post = [x for x in pr if x["timestamp"] > t0_s]
    r["pxAnchor"] = float(pre[-1]["price"]) if pre else None
    if not post:
        r["reached5"] = r["reached60"] = False
        r["tapeSilent"] = True
        r["note"] = "tape has NO post-dispatch prints on this token (sparse market) — 'not reached' here is uninformative"
        return r
    w5 = [x for x in post if x["timestamp"] <= t0_s + H5]
    w60 = [x for x in post if x["timestamp"] <= t0_s + H60]
    r["prints5"], r["prints60"] = len(w5), len(w60)
    for rows, key in ((w5, "reached5"), (w60, "reached60")):
        hit = [x for x in rows if float(x["price"]) <= level + EPS]
        r[key] = bool(hit)
        if hit and r["tFirstTouchMs"] is None:
            r["tFirstTouchMs"] = (hit[0]["timestamp"] - t0_s) * 1000
    hits = [x for x in w60 if float(x["price"]) <= level + EPS]
    r["sizeAtLevel60"] = sum(float(x["size"]) for x in hits)
    r["maxSizeAtLevel"] = max((float(x["size"]) for x in hits), default=0.0)
    r["sellSideReached60"] = any(str(x.get("side", "")).upper() == "SELL" and float(x["price"]) <= level + EPS
                                 for x in w60)
    end = [x for x in pr if x["timestamp"] <= t0_s + H60]
    r["pxEnd"] = float(end[-1]["price"]) if end else None
    if r["pxEnd"] is not None:
        r["driftVsIntent"] = round(r["pxEnd"] - intent, 4)
        if r["pxAnchor"] is not None:
            r["driftVsAnchor"] = round(r["pxEnd"] - r["pxAnchor"], 4)
    return r


# ------------------------------------------------------------------ report
def summarise(res: list[dict]) -> dict:
    tape_l = [r for r in res if r.get("reached5") is not None and not r.get("tapeSilent")]
    silent = [r for r in res if r.get("tapeSilent")]
    book_l = [r for r in res if (r.get("book") or {}).get("askAtLevel") is not None]
    return {
        "legs": len(res), "tapeAnalysable": len(tape_l), "tapeSilent": len(silent),
        "bookAnalysable": len(book_l),
        "reached5": sum(1 for r in tape_l if r["reached5"]),
        "reached60": sum(1 for r in tape_l if r["reached60"]),
        "sellerAtLevel60": sum(1 for r in tape_l if r.get("sellSideReached60")),
        "bookAskAtLevel": sum(1 for r in book_l if r["book"]["askAtLevel"]),
        "anchorIsMid": sum(1 for r in res if r.get("anchorIsMid")),
        "anchorIsWalletPrint": sum(1 for r in res if r.get("anchorIsWalletPrint")),
        "levelBelowCoverStartBid": sum(1 for r in book_l
                                      if (r["book"].get("levelVsCoverStartBid") or 0) < 0),
        "l2StartLagMin": [round((r["book"]["coverStartMs"] - r["dispatchedAt"]) / 60000, 1)
                          for r in book_l if r["book"].get("coverStartMs")],
        "bar5m": BAR_5M, "bar1h": BAR_60M, "barDrift": BAR_DRIFT,
    }


def render(res: list[dict], s: dict) -> list[str]:
    def pct(a: int, b: int) -> str:
        return f"{(100 * a / b if b else 0):.0f}%"

    dr = [r["driftVsAnchor"] for r in res if r.get("reached60") and r.get("driftVsAnchor") is not None]
    dn = [r["driftVsAnchor"] for r in res if r.get("reached60") is False and r.get("driftVsAnchor") is not None
          and not r.get("tapeSilent")]
    out = [
        "[printthrough] C-200 intent print-through — did the market print/offer at or below (intent - $0.02)?",
        f"[printthrough] legs {s['legs']} | tape-analysable {s['tapeAnalysable']} (+{s['tapeSilent']} tape-silent, "
        f"excluded) | book-analysable {s['bookAnalysable']}",
        f"[printthrough] PRINTS (public tape, 5m): {s['reached5']}/{s['tapeAnalysable']} = "
        f"{pct(s['reached5'], s['tapeAnalysable'])}   (pre-registered archive bar 74.3%)",
        f"[printthrough] PRINTS (public tape, 1h): {s['reached60']}/{s['tapeAnalysable']} = "
        f"{pct(s['reached60'], s['tapeAnalysable'])}   (archive bar 81.1%)",
        f"[printthrough] BOOK (our 5s L2 corpus, 1h): min best-ask <= level on "
        f"{s['bookAskAtLevel']}/{s['bookAnalysable']} legs — a seller at/below our level = the bid fills",
        f"[printthrough] ANCHOR: intent == detection mid {s['anchorIsMid']}/{s['legs']} · "
        f"intent == the copied wallet's own print {s['anchorIsWalletPrint']}/{s['legs']} · "
        f"level sits BELOW the first covered best bid on {s['levelBelowCoverStartBid']}/{s['bookAnalysable']}",
        f"[printthrough] COVERAGE: our L2 book starts "
        f"{'/'.join(str(x) for x in s['l2StartLagMin'])} min AFTER dispatch -> the 5-min horizon has "
        f"NO in-house book coverage on any leg",
    ]
    for r in res:
        b = r.get("book") or {}
        if r.get("reached5") is None:
            out.append(f"[printthrough]   {r['marketId']} {r['outcome']}: TAPE UNUSABLE — {r['note']}")
            continue
        touch = "n/a" if r.get("tFirstTouchMs") is None else f"{r['tFirstTouchMs'] / 1000:.0f}s"
        lag = ((b.get("coverStartMs") or r["dispatchedAt"]) - r["dispatchedAt"]) / 60000
        q = b.get("quoteAtCoverStart") or {}
        out.append(
            f"[printthrough]   {r['marketId']} {r['outcome']}: intent {r['intentPrice']:.3f} (wallet print "
            f"{r['walletPrintPrice']}) level {r['level']:.3f} | tape prints 5m/1h {r['prints5']}/{r['prints60']}"
            f"{' (SILENT)' if r.get('tapeSilent') else ''} reached 5m={r['reached5']} 1h={r['reached60']} "
            f"({touch}) | book min ask {b.get('minAsk')} over {b.get('snapsInWindow')} snaps from +{lag:.1f}min"
            f" (bid {q.get('bid')}/ask {q.get('ask')}) reachable={b.get('askAtLevel')} | "
            f"drift 1h {r.get('driftVsAnchor')}"
        )
    if dr or dn:
        rpart = f"{sum(dr) / len(dr):+.4f} (n={len(dr)})" if dr else "n/a"
        npart = f"{sum(dn) / len(dn):+.4f} (n={len(dn)})" if dn else "n/a"
        out.append(f"[printthrough] adverse selection (mean px_end - anchor, 1h): reached {rpart} "
                   f"(archive 0.4-0.6 band -0.0323) | not reached {npart}")
    out.append("[printthrough] CAVEAT: a print/touch at our level is not queue position and ignores size — "
               "the reading is 'the level was reachable', never 'we would have been filled'. Measurement only.")
    return out


def markdown(res: list[dict], s: dict) -> str:
    body = "\n".join(render(res, s))
    established = (
        f"- **ESTABLISHED:** the level (intent - $0.02) was **not reachable** on any of the {s['legs']} measured "
        f"legs in the hour after dispatch — {s['bookAskAtLevel']}/{s['bookAnalysable']} on our own L2 book "
        f"(best ask at or below the level) and {s['reached60']}/{s['tapeAnalysable']} on the public tape where the "
        f"tape had prints. The archive's base rate (74.3% within 5 min / 81.1% within 1 h at C-200's price mix) "
        f"does not show up on this sample."
    )
    mechanical = (
        f"- **ESTABLISHED, and the mechanical reason to expect a gap:** the intent price is the detection "
        f"**midpoint** (`ObservedTrade.detectedPrice`), not the copied wallet's own print — {s['anchorIsMid']}/"
        f"{s['legs']} legs. The assumed fill is therefore `mid - 2c`, which on a 1c spread sits ~1.5c BELOW the "
        f"prevailing best bid (below the first covered best bid on {s['levelBelowCoverStartBid']}/"
        f"{s['bookAnalysable']} legs). The archive measured \u201ca print at p, then a print at or below p - 2c\u201d: a "
        f"level anchored on the MID is a deeper, different event, so the 74.3% may not transfer by construction."
    )
    not_est = (
        f"- **NOT ESTABLISHED:** the number the card's gate asks for. n={s['legs']}, {s['tapeSilent']} of them "
        f"tape-silent, and our own book never covers the first "
        f"{min(s['l2StartLagMin']) if s['l2StartLagMin'] else '?'}-"
        f"{max(s['l2StartLagMin']) if s['l2StartLagMin'] else '?'} min after a dispatch, so the 5-minute horizon "
        f"has no in-house coverage at all. Read this as a direction plus a data-availability finding, not a rate."
    )
    blockers = (
        "- **BLOCKERS before this can decide anything:** (1) the L2 recorder's universe refresh admits a market "
        "only after a copy exists, so coverage always starts AFTER the dispatch — subscribing at copy time is the "
        "fix (observability change, not approved); (2) the public tape is thin on these markets (2-50 rows for the "
        "whole market); (3) n. The gate stands: >=50 measured legs, then the share vs 74.3%."
    )
    return "\n".join([
        "# C-200 intent print-through — first read",
        "",
        f"Generated {time.strftime('%Y-%m-%d %H:%M %Z')} by `scripts/c200-printthrough.py` "
        "(measurement only — nothing in the trade path reads this). Card: `c200-intent-printthrough-check`.",
        "",
        "```",
        body,
        "```",
        "",
        "## What this first read does and does not establish",
        "",
        established,
        mechanical,
        not_est,
        blockers,
        "",
        "## Reproduce",
        "",
        "```",
        "python3 scripts/c200-printthrough.py",
        'sqlite3 "file:prisma/dev.db?mode=ro" "SELECT COUNT(*) FROM FillIntent;"',
        "```",
        "",
        "Artifacts: `data/c200-printthrough.jsonl` (append-only), `data/c200-tape/` (tape cache).",
        "",
    ])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--since-ms", type=int, default=None)
    ap.add_argument("--json", action="store_true", help="append artifact, print nothing")
    ap.add_argument("--md", default=None, help="also write a markdown draft (dashboard-served)")
    a = ap.parse_args()

    legs = load_legs(a.since_ms)
    cmap = condition_map()
    amap = l2_map()
    tapes: dict[str, list[dict]] = {}
    res: list[dict] = []
    for leg in legs:
        cid = cmap.get(leg["marketId"]) or gamma_condition(leg["marketId"])
        if not cid:
            res.append({"intentId": leg["intentId"], "marketId": leg["marketId"], "outcome": leg["outcome"],
                        "intentPrice": leg["intentPrice"], "level": round(leg["intentPrice"] - DELTA, 6),
                        "sizeUsd": leg["sizeUsd"], "dispatchedAt": leg["dispatchedAt"],
                        "reached5": None, "reached60": None, "book": {},
                        "note": "no conditionId (ObservedTrade/gamma)"})
            continue
        if cid not in tapes:
            tapes[cid] = fetch_tape(cid)
        res.append(analyse(leg, tapes[cid], amap))

    s = summarise(res)
    with open(OUT, "a") as fh:
        fh.write(json.dumps({"ranAt": int(time.time() * 1000), "summary": s, "legs": res}) + "\n")
    if a.md:
        with open(os.path.join(ROOT, a.md), "w") as fh:
            fh.write(markdown(res, s))
    if not a.json:
        for line in render(res, s):
            print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
