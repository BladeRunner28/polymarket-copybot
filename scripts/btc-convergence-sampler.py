#!/usr/bin/env python3
"""Deterministic-convergence SAMPLER (card btx2) — measurement only, read-only, keyless.

PRE-REGISTRATION: read `drafts/btc-convergence-prereg-20261013.md` for the frozen gate. This file
only records; it never decides. The gate was committed BEFORE the first sample row existed.

WHAT MAKES THIS LANE DIFFERENT FROM EVERY OTHER BTC LANE WE RUN
-------------------------------------------------------------
Polymarket's price/threshold families name **Binance itself** as the resolution source, and our own
keyless pull reproduces the venue's recorded verdicts EXACTLY (1,617/1,617 markets). So here — and
only here — **oracle risk is identically zero**: we can compute the outcome to the cent, before or
after the venue does. That is what makes a "determined leg" a well-defined object.

THE TWO QUESTIONS (falsifiers frozen in the pre-registration)
------------------------------------------------------------
Q1 (determined legs) — when a market's outcome is ALREADY DETERMINED from the tape, is the determined
   side still buyable for less than 1.00 minus fees, at an executable size >= S?
Q2 (undetermined ladders) — for a strike not yet touched, is the venue's implied probability
   calibrated against the physical hit-rate implied by the remaining-horizon range?

Determination is computed from Binance 1m/1h tape ONLY (never from the venue's own price):
  * hourly above-ladder `<asset>-above-on-<date>-<h><am|pm>-et`  -> the 1m candle CLOSING at that hour
  * hourly up-or-down   `<asset>-up-or-down-...`                 -> the 1h candle BEGINNING at that hour
  * daily hit-ladder    `what-price-will-<asset>-hit-on-<date>`  -> up-arrow: any 1m High >= strike;
                                                                   down-arrow: any 1m Low <= strike
  (labels are semantic: up-arrow reads High, down-arrow reads Low — mixing them scored 54% on 48
   markets before it was fixed; and a 1h up-or-down candle BEGINS at the stated hour, not ends.)

FEE LAW (a change VOIDS the sample; read from the venue's own fields, never from a constant)
  Polymarket: the MARKET's own `feeType`/`feeSchedule` is recorded on every row. The law is
  `taker = rate * shares * min(p, 1-p)` with `exponent: 1`, makers 0 — established by the archive
  fee calibration (`bt-fee-maker-calibration`, $1.21B of fees). TRAP: `takerBaseFee`/`makerBaseFee`
  and CLOB `/fee-rate` are a legacy constant 1000 on ~85% of markets regardless of schedule; pricing
  base/1e4 charges 0.10/share and would erase any real edge. Never used here.

READ-ONLY: public keyless endpoints; no key, no order surface, nothing written to any book.
Silent on success (stdout is an observability channel, not a log).

Usage: python3 scripts/btc-convergence-sampler.py [--assets bitcoin,ethereum] [--verbose]
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
SAMPLES_DIR = ROOT / "data"
GAMMA = "https://gamma-api.polymarket.com"
CLOB = "https://clob.polymarket.com"
BV = "https://data-api.binance.vision"
ET = ZoneInfo("America/New_York")
UA = {"User-Agent": "copybot-btc-convergence/1.0 (read-only measurement)"}

# frozen universe (validated by reproducing the venue's own recorded verdicts - see btx1)
ASSETS = {"bitcoin": "BTCUSDT", "ethereum": "ETHUSDT", "solana": "SOLUSDT", "xrp": "XRPUSDT",
          "dogecoin": "DOGEUSDT", "bnb": "BNBUSDT", "hyperliquid": "HYPEUSDT"}
SIZE_FLOOR = 50            # the gate is evaluated at >= 50 executable shares


def code_hash():
    """sha256[:12] of THIS file, stamped on every row and coverage line.

    The sample series is only auditable if a row can be traced to the exact revision that wrote it,
    so an analysis can restrict to the code revision pinned in the pre-registration (and a later
    change to the estimator can never silently ride on rows written before it existed).
    """
    try:
        return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()[:12]
    except OSError:
        return "unknown"


def get(url, timeout=25, tries=3):
    last = None
    for i in range(tries):
        try:
            return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout).read()
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(0.8 * (i + 1))
    raise last  # type: ignore[misc]


def jget(url, timeout=25, tries=3):
    return json.loads(get(url, timeout, tries))


def fnum(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


# ------------------------------------------------------------------ physical state (Binance)
def tape(symbol, interval, start_ms, end_ms):
    out = []
    cur = start_ms
    while cur < end_ms:
        b = jget(f"{BV}/api/v3/klines?symbol={symbol}&interval={interval}"
                 f"&startTime={cur}&endTime={end_ms}&limit=1000")
        if not b:
            break
        out += [{"open_ms": k[0], "close_ms": k[6], "open": float(k[1]), "high": float(k[2]),
                 "low": float(k[3]), "close": float(k[4])} for k in b]
        nxt = b[-1][6] + 1
        if nxt <= cur:
            break
        cur = nxt
        if len(b) < 1000:
            break
    return out


def et_utc_ms(ds, hour, minute=0):
    return int(datetime.fromisoformat(f"{ds}T{hour:02d}:{minute:02d}:00")
               .replace(tzinfo=ET).astimezone(timezone.utc).timestamp() * 1000)


def state_today(symbol, ds):
    """Physical state so far today: max High, min Low, latest close, and the last 1m bars."""
    o0 = et_utc_ms(ds, 0)
    bars = tape(symbol, "1m", o0, int(time.time() * 1000))
    if not bars:
        return None
    return {"max_so_far": max(b["high"] for b in bars), "min_so_far": min(b["low"] for b in bars),
            "last_close": bars[-1]["close"], "last_bar_ms": bars[-1]["open_ms"], "bars": bars}


# ------------------------------------------------------------------ venue book (never Gamma's)
def pm_book(market):
    """Real executable book for BOTH tokens straight from the CLOB (Gamma's bestBid/Ask is stale)."""
    try:
        outcomes = json.loads(market.get("outcomes") or "[]")
        tokens = json.loads(market.get("clobTokenIds") or "[]")
    except Exception:  # noqa: BLE001
        return None
    if not outcomes or not tokens:
        return None
    try:
        i_yes = outcomes.index("Yes")
    except ValueError:
        try:
            i_yes = outcomes.index("Up")
        except ValueError:
            i_yes = 0
    rec = {"outcomes": outcomes, "feeType": market.get("feeType"),
           "feeSchedule": market.get("feeSchedule"), "accepting_orders": market.get("acceptingOrders"),
           "closed": market.get("closed"), "spread": market.get("spread")}
    levels = {}
    for i, tok in enumerate(tokens):
        try:
            bk = jget(f"{CLOB}/book?token_id={tok}")
        except Exception as e:  # noqa: BLE001
            rec[f"token{i}_error"] = str(e)[:80]
            continue
        bids = sorted([(fnum(x.get("price")), fnum(x.get("size"))) for x in (bk.get("bids") or [])
                       if fnum(x.get("price")) is not None], reverse=True)
        asks = sorted([(fnum(x.get("price")), fnum(x.get("size"))) for x in (bk.get("asks") or [])
                       if fnum(x.get("price")) is not None])
        levels[i] = {"best_bid": bids[0] if bids else None, "best_ask": asks[0] if asks else None,
                     "min_order_size": bk.get("min_order_size"), "tick_size": bk.get("tick_size")}
        rec[f"token{i}"] = levels[i]
    y, n = levels.get(i_yes, {}), levels.get(1 - i_yes, {})
    rec["yes_bid"], rec["size_yes_bid"] = (y.get("best_bid") or (None, None))
    rec["yes_ask"], rec["size_yes_ask"] = (y.get("best_ask") or (None, None))
    rec["no_bid"], rec["size_no_bid"] = (n.get("best_bid") or (None, None))
    rec["no_ask"], rec["size_no_ask"] = (n.get("best_ask") or (None, None))
    return rec


def taker_fee(price, fee_type, fee_schedule):
    """Polymarket taker fee law, from the MARKET's own schedule. Returns (fee, law).

    `law` is a stable machine-readable string, because the analysis needs to know WHY a fee is zero:
      "schedule"          -> a fee schedule is published on the market; fee = rate*min(p,1-p)
      "no_schedule_zero"  -> the market publishes NO schedule (feeType=None) => taker fee is 0
      "unpinned_exponent" -> a schedule exists with an exponent we have not pinned => UNUSABLE row
      "no_price"          -> no executable ask, nothing to price
    A row with `no_schedule_zero` is still usable at fee 0, but the pre-registration carries a
    SENSITIVITY ARM that charges 0.07*min(p,1-p) on every such row, so no verdict can rest on the
    assumption "no schedule means free".
    """
    if not price:
        return None, "no_price"
    rate = None
    if isinstance(fee_schedule, dict):
        rate = fnum(fee_schedule.get("rate"))
        if fee_schedule.get("exponent") not in (None, 0, 1):
            return None, "unpinned_exponent"
    if rate is None:
        return 0.0, "no_schedule_zero"
    return rate * min(price, 1.0 - price), "schedule"


def edge_of(side, book):
    """edge for buying the DETERMINED side at its executable ask, net of the venue's taker fee.

    `reason` is recorded on EVERY row, because "no ask at all" is a structural finding, not a
    missing number: on a decided leg the venue's book is routinely BID-ONLY on the winner (20 bid
    levels at <=0.999 and ZERO asks — measured on the first live tick), so the determined side is
    unbuyable at any price and there is nothing to price. That case must be countable separately
    from "an ask exists but the edge is negative" and from "an ask exists but the size is thin".
    """
    if side == "yes":
        px, sz = book.get("yes_ask"), book.get("size_yes_ask")
    else:
        px, sz = book.get("no_ask"), book.get("size_no_ask")
    if px is None:
        return {"determined_side": side, "ask": None, "size": None, "edge": None,
                "fee": None, "fee_law": None, "reason": "no_ask",
                "executable_at_floor": False}
    fee, law = taker_fee(px, book.get("feeType"), book.get("feeSchedule"))
    return {"determined_side": side, "ask": px, "size": sz,
            "fee_law": law, "fee": None if fee is None else round(fee, 6),
            "edge": None if fee is None else round((1.0 - px - fee), 6),
            "reason": "priced" if fee is not None else law,
            "executable_at_floor": bool(sz is not None and sz >= SIZE_FLOOR)}


# ------------------------------------------------------------------ families
def strike_of(label):
    """-> (value, kind). '↑' ladders use the High, '↓' the Low."""
    lab = label or ""
    s = lab.replace(",", "").replace("↑", "").replace("↓", "").strip()
    if "-" in s and not s.startswith("-"):
        a, b = s.split("-")[:2]
        try:
            return (float(a), float(b)), "range"
        except ValueError:
            return None, None
    if s.startswith("<"):
        return float(s[1:]), "lt"
    if s.startswith(">"):
        return float(s[1:]), "gt"
    try:
        v = float(s)
    except ValueError:
        return None, None
    return v, ("down" if "↓" in lab else "up" if "↑" in lab else "eq")


def event(slug):
    try:
        r = jget(f"{GAMMA}/events?slug={slug}")
    except Exception:  # noqa: BLE001
        return None
    return r[0] if r else None


def row_base(kind, asset, fam, instr, ts):
    return {"kind": kind, "venue": "polymarket", "asset": asset, "family": fam,
            "instrument": instr, "ts": ts, "sampled_at_ms": int(time.time() * 1000)}


def sample_daily_hit(asset, symbol, ds, ts, verbose, hours_back=2):
    """Q1 (determined) + Q2 (undetermined): the day's 'what price will X hit' ladder."""
    ld = datetime.fromisoformat(ds).strftime("%B").lower() + f"-{int(ds[8:10])}-{ds[0:4]}"
    e = event(f"what-price-will-{asset}-hit-on-{ld}")
    if not e:
        return []
    st = state_today(symbol, ds)
    if not st:
        return []
    rows = []
    for m in e.get("markets") or []:
        if m.get("closed"):
            continue
        val, kind = strike_of(m.get("groupItemTitle"))
        if val is None:
            continue
        book = pm_book(m)
        if not book:
            continue
        determined, side, det_why = None, None, None
        det_at = None
        if kind == "down":
            determined = st["min_so_far"] <= val
            side = "yes"                      # a touched LOW makes YES (it dropped to X) certain
            det_why = f"min_so_far {st['min_so_far']:.2f} <= {val}"
            dist = st["last_close"] - val
            touched = next((b for b in st["bars"] if b["low"] <= val), None)
        else:
            determined = st["max_so_far"] >= val
            side = "yes"
            det_why = f"max_so_far {st['max_so_far']:.2f} >= {val}"
            dist = val - st["last_close"]
            touched = next((b for b in st["bars"] if b["high"] >= val), None)
        if touched:
            # the verdict exists once that 1m candle CLOSES (conservative: the bar that first touched)
            det_at = touched["close_ms"]
        r = row_base("bracket", asset, "hit_day", m.get("slug"), ts)
        r.update({"label": m.get("groupItemTitle"), "strike": val, "strike_kind": kind,
                  "determined": determined, "determination_basis": det_why,
                  "determined_at_ms": det_at,
                  "max_so_far": st["max_so_far"], "min_so_far": st["min_so_far"],
                  "last_close": st["last_close"], "distance_to_strike": dist,
                  "yes_bid": book.get("yes_bid"), "size_yes_bid": book.get("size_yes_bid"),
                  "yes_ask": book.get("yes_ask"), "size_yes_ask": book.get("size_yes_ask"),
                  "no_bid": book.get("no_bid"), "size_no_bid": book.get("size_no_bid"),
                  "no_ask": book.get("no_ask"), "size_no_ask": book.get("size_no_ask"),
                  "feeType": book.get("feeType"), "feeSchedule": book.get("feeSchedule"),
                  "accepting_orders": book.get("accepting_orders"),
                  "executable_size_floor": SIZE_FLOOR})
        if determined:
            r["q1"] = edge_of(side, book)
        else:
            r["q2"] = {"distance_to_strike": dist, "strike": val,
                       "implied_yes": book.get("yes_bid") if book.get("yes_bid") is not None else book.get("yes_ask")}
        rows.append(r)
    if verbose and rows:
        det = [x for x in rows if x.get("determined")]
        print(f"  {asset} hit_day: {len(rows)} open brackets, {len(det)} DETERMINED")
    return rows


def sample_hourly_above(asset, symbol, ds, ts, verbose, hours_back=2):
    """The hour's 20-strike above-ladder: the 1m candle closing at the hour determines all strikes."""
    rows = []
    now = datetime.now(ET)
    for hour in range(now.hour, max(-1, now.hour - hours_back), -1):
        if hour < 0:
            continue
        hr, ap = hour % 12 or 12, ("am" if hour < 12 else "pm")
        ld = f"{now.strftime('%B').lower()}-{now.day}-{now.year}"
        e = event(f"{asset}-above-on-{ld}-{hr}{ap}-et")
        if not e:
            continue
        anchor = et_utc_ms(ds, hour)
        closing = tape(symbol, "1m", anchor - 3_600_000, anchor)
        bar = next((b for b in closing if b["open_ms"] == anchor - 60_000), None)
        if bar is None:
            continue
        for m in e.get("markets") or []:
            if m.get("closed"):
                continue
            val, kind = strike_of(m.get("groupItemTitle"))
            if val is None or kind not in ("up", "eq"):
                continue
            book = pm_book(m)
            if not book:
                continue
            verdict_yes = bar["close"] > val
            r = row_base("bracket", asset, "hourly_above", m.get("slug"), ts)
            r.update({"label": m.get("groupItemTitle"), "strike": val, "hour_et": hour,
                      "determining_close": bar["close"], "determined": True,
                      "verdict": "Yes" if verdict_yes else "No",
                      "determined_at_ms": bar["close_ms"],
                      "determination_basis": f"1m candle closing {hr}{ap} ET close {bar['close']:.2f} > {val}",
                      "yes_bid": book.get("yes_bid"), "size_yes_bid": book.get("size_yes_bid"),
                      "yes_ask": book.get("yes_ask"), "size_yes_ask": book.get("size_yes_ask"),
                      "no_bid": book.get("no_bid"), "size_no_bid": book.get("size_no_bid"),
                      "no_ask": book.get("no_ask"), "size_no_ask": book.get("size_no_ask"),
                      "feeType": book.get("feeType"), "feeSchedule": book.get("feeSchedule"),
                      "accepting_orders": book.get("accepting_orders"),
                      "executable_size_floor": SIZE_FLOOR})
            r["q1"] = edge_of("yes" if verdict_yes else "no", book)
            rows.append(r)
    if verbose and rows:
        print(f"  {asset} hourly_above: {len(rows)} brackets")
    return rows


def sample_hourly_updown(asset, symbol, ds, ts, verbose, hours_back=2):
    """The hour's up-or-down pair: the 1h candle BEGINNING at the stated hour decides it.

    TRAP (measured in btx1): anchoring on the candle that ENDS at the stated hour scored 43% — worse
    than a coin flip. The stated hour is the candle's OPEN. The verdict exists only once that candle
    has CLOSED, so an in-progress candle is skipped rather than half-scored.
    """
    rows = []
    now = datetime.now(ET)
    now_ms = int(time.time() * 1000)
    for hour in range(now.hour, max(-1, now.hour - hours_back), -1):
        hr, ap = (hour % 12 or 12), ("am" if hour < 12 else "pm")
        ld = f"{now.strftime('%B').lower()}-{now.day}-{now.year}"
        e = event(f"{asset}-up-or-down-{ld}-{hr}{ap}-et")
        if not e:
            continue
        anchor = et_utc_ms(ds, hour)
        bar = next((b for b in tape(symbol, "1h", anchor, anchor + 3_600_000)
                    if b["open_ms"] == anchor), None)
        if bar is None or bar["close_ms"] >= now_ms:
            continue                                    # not decided yet — no verdict to price
        verdict_up = bar["close"] >= bar["open"]
        for m in e.get("markets") or []:
            if m.get("closed"):
                continue
            book = pm_book(m)
            if not book:
                continue
            r = row_base("pair", asset, "updown_1h", m.get("slug"), ts)
            r.update({"label": m.get("groupItemTitle"), "hour_et": hour, "candle_open_ms": anchor,
                      "candle_open": bar["open"], "candle_close": bar["close"],
                      "determined": True, "verdict": "Up" if verdict_up else "Down",
                      "determined_at_ms": bar["close_ms"],
                      "determination_basis": (f"1h candle {hr}{ap} ET (OPEN at the hour): "
                                              f"close {bar['close']:.2f} vs open {bar['open']:.2f}"),
                      "yes_bid": book.get("yes_bid"), "size_yes_bid": book.get("size_yes_bid"),
                      "yes_ask": book.get("yes_ask"), "size_yes_ask": book.get("size_yes_ask"),
                      "no_bid": book.get("no_bid"), "size_no_bid": book.get("size_no_bid"),
                      "no_ask": book.get("no_ask"), "size_no_ask": book.get("size_no_ask"),
                      "feeType": book.get("feeType"), "feeSchedule": book.get("feeSchedule"),
                      "accepting_orders": book.get("accepting_orders"),
                      "executable_size_floor": SIZE_FLOOR})
            r["q1"] = edge_of("yes" if verdict_up else "no", book)
            rows.append(r)
    if verbose and rows:
        print(f"  {asset} updown_1h: {len(rows)} decided pairs")
    return rows


def sample_noon_ranges(asset, symbol, ds, ts, verbose, hours_back=2):
    """The day's noon-close ladder: the 1m candle CLOSING at 12:00 ET decides every bucket.

    Both sides are decided at that instant (a bucket either contains the noon close or it does not),
    so this family yields a Q1 observation for every bucket in the ladder, not just touched ones.
    """
    rows = []
    now_ms = int(time.time() * 1000)
    ld = datetime.fromisoformat(ds).strftime("%B").lower() + f"-{int(ds[8:10])}-{ds[0:4]}"
    anchor = et_utc_ms(ds, 12, 0)
    if anchor - 60_000 >= now_ms:
        return rows                                     # noon has not closed yet
    bars = tape(symbol, "1m", anchor - 3_600_000, anchor)
    bar = next((b for b in bars if b["open_ms"] == anchor - 60_000), None)
    if bar is None:
        return rows
    for slug in (f"{asset}-price-on-{ld}", f"{asset}-above-on-{ld}"):
        e = event(slug)
        if not e:
            continue
        for m in e.get("markets") or []:
            if m.get("closed"):
                continue
            val, kind = strike_of(m.get("groupItemTitle"))
            if val is None:
                continue
            if kind == "range":
                lo, hi = val if isinstance(val, tuple) else (val, val)
                verdict = lo < bar["close"] <= hi
            elif kind == "lt":
                verdict = bar["close"] < val
            elif kind == "gt":
                verdict = bar["close"] > val
            else:
                continue
            book = pm_book(m)
            if not book:
                continue
            r = row_base("bracket", asset, "noon_close", m.get("slug"), ts)
            r.update({"label": m.get("groupItemTitle"), "strike": val, "strike_kind": kind,
                      "noon_close": bar["close"], "determined": True,
                      "verdict": "Yes" if verdict else "No",
                      "determined_at_ms": bar["close_ms"],
                      "determination_basis": f"1m candle closing 12pm ET close {bar['close']:.2f} vs {val}",
                      "yes_bid": book.get("yes_bid"), "size_yes_bid": book.get("size_yes_bid"),
                      "yes_ask": book.get("yes_ask"), "size_yes_ask": book.get("size_yes_ask"),
                      "no_bid": book.get("no_bid"), "size_no_bid": book.get("size_no_bid"),
                      "no_ask": book.get("no_ask"), "size_no_ask": book.get("size_no_ask"),
                      "feeType": book.get("feeType"), "feeSchedule": book.get("feeSchedule"),
                      "accepting_orders": book.get("accepting_orders"),
                      "executable_size_floor": SIZE_FLOOR})
            r["q1"] = edge_of("yes" if verdict else "no", book)
            rows.append(r)
    if verbose and rows:
        print(f"  {asset} noon_close: {len(rows)} decided buckets")
    return rows


FAMILIES = {
    "hit_day": sample_daily_hit,          # 'what price will X hit' — YES locks when a 1m High/Low touches
    "hourly_above": sample_hourly_above,  # hour ladder — decided by the 1m candle closing at the hour
    "updown_1h": sample_hourly_updown,    # up-or-down — decided by the 1h candle OPENING at the hour
    "noon_close": sample_noon_ranges,     # noon ladder — decided by the 1m candle closing at 12:00 ET
}


def rotate_done_days(out_dir, today_ds):
    """gzip every finished day's raw sample file (raw jsonl for today only).

    STORAGE IS PART OF THE INSTRUMENT'S HONESTY. Measured on the first live ticks: a row is ~912 B
    and a tick captures every strike of every ladder, so raw capture is ~34 MB/day for the coverage
    cadence and ~13 MB/day for the window cadence — 47 MB/day would swallow the nightly backup's
    95 MB guard inside one day and make the repo the warehouse. Gzipped, the same series is ~2 MB/day.
    Rotation (not deletion) is the point: the raw rows stay available, just compressed, and today's
    file stays readable while the instrument is live.
    """
    import glob as _glob
    for path in _glob.glob(str(Path(out_dir) / "btc-convergence-samples-*.jsonl")):
        p = Path(path)
        ds = p.stem.rsplit("-", 3)[-3:]
        if len(ds) != 3 or f"{ds[0]}-{ds[1]}-{ds[2]}" == today_ds:
            continue
        gz = p.with_suffix(".jsonl.gz")
        try:
            with p.open("rb") as src, gzip.open(gz, "wb", compresslevel=6) as dst:
                while chunk := src.read(1 << 20):
                    dst.write(chunk)
            p.unlink()
        except OSError:
            continue          # never fail a tick over housekeeping


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--out-dir", default=str(SAMPLES_DIR))
    ap.add_argument("--assets", default="all", help="comma list of %s, or 'all'" % ",".join(ASSETS))
    ap.add_argument("--families", default="all", help="comma list of %s, or 'all'" % ",".join(FAMILIES))
    ap.add_argument("--hours-back", type=int, default=2,
                    help="how many anchor hours the hourly families look back (window is ~11-12 min)")
    ap.add_argument("--max-minutes-since-determined", type=float, default=None,
                    help="drop decided rows observed later than this (the post-determination window)")
    ap.add_argument("--undetermined-max-minute", type=int, default=5,
                    help="undetermined (Q2-candidate) rows are kept only in the first N minutes of the "
                         "hour — they do not need 15-minute resolution, and this is the volume lever")
    a = ap.parse_args()
    assets = list(ASSETS) if a.assets == "all" else [x.strip() for x in a.assets.split(",") if x.strip()]
    fams = list(FAMILIES) if a.families == "all" else [x.strip() for x in a.families.split(",") if x.strip()]
    bad_a = [x for x in assets if x not in ASSETS]
    bad_f = [x for x in fams if x not in FAMILIES]
    if bad_a or bad_f:
        print(f"🔴 btc-convergence: unknown {'assets' if bad_a else 'families'}: {bad_a or bad_f}")
        return 2

    now = datetime.now(ET)
    ts = now.astimezone(timezone.utc).isoformat(timespec="seconds")
    ds = now.strftime("%Y-%m-%d")
    code = code_hash()
    rows, cov = [], {"kind": "coverage", "ts": ts, "assets": assets, "families": fams, "code": code,
                     "rows": 0, "determined": 0, "family_counts": {}, "fee_laws": {},
                     "q1_reasons": {}, "dropped_stale": 0, "dropped_undetermined_offhour": 0,
                     "hours_back": a.hours_back,
                     "errors": [], "size_floor": SIZE_FLOOR}

    for asset in assets:
        symbol = ASSETS[asset]
        for fam in fams:
            fn = FAMILIES[fam]
            try:
                got = fn(asset, symbol, ds, ts, a.verbose, a.hours_back)
            except Exception as e:  # noqa: BLE001
                cov["errors"].append(f"{asset} {fam}: {type(e).__name__}: {str(e)[:80]}")
                continue
            kept = []
            for r in got:
                r["code"] = code
                if r.get("determined_at_ms"):
                    r["minutes_since_determined"] = round(
                        (r["sampled_at_ms"] - r["determined_at_ms"]) / 60_000.0, 2)
                if (a.max_minutes_since_determined is not None and r.get("determined")
                        and r.get("minutes_since_determined") is not None
                        and r["minutes_since_determined"] > a.max_minutes_since_determined):
                    cov["dropped_stale"] += 1
                    continue
                if not r.get("determined") and now.minute > a.undetermined_max_minute:
                    cov["dropped_undetermined_offhour"] += 1
                    continue
                kept.append(r)
            cov["family_counts"][f"{asset}|{fam}"] = len(kept)
            rows += kept

    cov["rows"] = len(rows)
    cov["determined"] = sum(1 for r in rows if r.get("determined"))
    for r in rows:
        q1 = r.get("q1") or {}
        if q1.get("reason"):
            cov["q1_reasons"][q1["reason"]] = cov["q1_reasons"].get(q1["reason"], 0) + 1
        if q1.get("fee_law"):
            cov["fee_laws"][q1["fee_law"]] = cov["fee_laws"].get(q1["fee_law"], 0) + 1
    if not rows:
        print(f"🟠 btc-convergence: no brackets captured this tick ({ts}) errors={cov['errors'][:2]}")
        return 0

    out_dir = Path(a.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    day_file = out_dir / f"btc-convergence-samples-{ds}.jsonl"
    with day_file.open("a") as fh:
        for r in rows:
            fh.write(json.dumps(r, separators=(",", ":")) + "\n")
    with (out_dir / "btc-convergence-coverage.jsonl").open("a") as fh:
        fh.write(json.dumps(cov, separators=(",", ":")) + "\n")
    rotate_done_days(out_dir, ds)
    if a.verbose:
        print(f"{ts} rows={cov['rows']} determined={cov['determined']} errors={len(cov['errors'])}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001
        print(f"🔴 btc-convergence sampler crashed: {type(exc).__name__}: {exc}")
        sys.exit(0)   # never fail a cron tick loudly; the reader's freshness check reports it
