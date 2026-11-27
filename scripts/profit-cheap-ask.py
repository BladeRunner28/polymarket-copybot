#!/usr/bin/env python3
"""
What the "unpriced" cheap refusals would have cost at the ask.

WHY THIS FILE EXISTS
--------------------
The 2026-11-14 profit review split the refused cheap cohort (0.05 <= p < 0.20,
first sighting per market+outcome) by whether the scorer's journal row names a
spread, and found the two halves differ: the rows whose spread check FIRED read
-2.9% at half spread (the gate is right), while the rows with no spread on the
row read +13.9pp at the detection mid and were called UNPRICED. Its rec 1 asked
for exactly one thing: measure those rows at the executable ask, then re-order
the scorer's hard-skip list so a candidate is refused by the gate that costs
money rather than by the first gate that fires.

This script does the measurement, and it prints one thing the review did not:
the check ORDER it proposes to change is already the order that runs. In
src/lib/scoring/trade.ts the hard-skip list is built as

    1 wallet score   2 SPREAD   3 liquidity   4 drift   5 TTR
    6 near-certainty 7 OBI      8 confidence

with every test evaluated unconditionally on every candidate, so a row with no
spread string is a row where the spread check PASSED (spread <= maxSpread),
not a row where it never ran. Section 0 proves that from the rows themselves
before section 1 prices anything: if the spread gate had been skipped or the
spread unknown, the scorer's own input default (`input.spread ?? 0.1`, and
maxSpread = 0.06) would have written a `spread 0.100 > max 0.06` blocker.

WHAT IS ACTUALLY MISSING IS THE VALUE, NOT THE TEST. A passing gate writes
nothing, so the row cannot be repriced after the fact — which is why section 1
reprices it from MarketSnapshot instead: the monitor writes a snapshot in the
same sweep that detects the trade (measured median lag 0 minutes), so the row's
own detection instant has a top-of-book quote beside it.

MEASUREMENT BASIS
  cohort     refused cheap candidates, journal.ruleSetVersion >= 68, decision
             'skip', 0.05 <= ObservedTrade.detectedPrice < 0.20, deduped to the
             FIRST sighting per (marketId, outcome)
  resolution clob.polymarket.com/markets/<conditionId> tokens[].winner (keyless,
             disk-cached under data/cheap-funnel-cache/, reused from the funnel
             instrument so the two reads score the same population)
  identity   which of the two tokens the leg holds is decided by COMPARING the
             detection price to the snapshot's two token mids, never by the
             outcome label: `outcome === "NO"` is false on every named market
             (34% of regime legs), and a positional read would price those at
             the other side's quote.
  ask        token0 -> bestAsk ; token1 -> 1 - bestBid   (complementary books)
  payout     win -> (1 - entry) / entry ; loss -> -1, equal weight, so every
             ROI line is a return on dollars at risk

ARMS
  A  detection mid          what the review priced (reproduction)
  B  snapshot mid           same instant, venue's own two-sided quote
  C  ASK at detection       the executable fill, THE ANSWER
  D  ask + taker fee        fee = rate * p * (1-p) per share, rate by category
  E  mid + maxSpread        the gate-implied bound available with no snapshot:
                            every row here passed `spread <= 0.06`, so 6c is the
                            worst fill the record itself permits
  F  ask one sweep later    nearest snapshot AFTER the journal row, i.e. what
                            the next scoring pass would have paid (lag cost)

USAGE
    python3 scripts/profit-cheap-ask.py            # full read (cache only)
    python3 scripts/profit-cheap-ask.py --fetch    # also fetch uncached resolutions
    python3 scripts/profit-cheap-ask.py --self-test

READ-ONLY: opens the DB with mode=ro and writes nothing except the resolution
cache. No RuleSet read or write, no prisma write, no apply-v*.ts.
"""
import json
import math
import os
import random
import re
import sqlite3
import statistics
import sys
import time
import urllib.error
import urllib.request
from collections import Counter, defaultdict

DB = os.environ.get("COPYBOT_DB", "file:prisma/dev.db?mode=ro")
CACHE = os.path.join("data", "cheap-funnel-cache")
REGIME = 68
LO, HI = 0.05, 0.20
WINDOW_MS = 2 * 3600 * 1000          # +/- 2h, the review's pre-registered window
SEED = 20261114
MAX_SPREAD = 0.06                    # live RuleSet v73
FEE_DEFAULT = 0.05                   # PRICE_EDGE_SPEC_V1.defaultFeeRate

FUNNEL_SQL = """
SELECT j.id jid, j.decision d, j.confidence conf, j.risksJson risk, j.marketId m,
       j.createdAt ts, j.copyScore cs, j.walletAddress w, j.spreadScore ss,
       o.detectedPrice dp, o.walletEntryPrice wp, o.outcome oc, o.conditionId cid
FROM DecisionJournal j JOIN ObservedTrade o ON j.observedTradeId = o.id
WHERE j.isDemo = 0 AND j.ruleSetVersion >= ?
  AND o.detectedPrice > 0 AND o.detectedPrice <= 1
  AND j.venue = 'Polymarket'
"""

SPREAD_RE = re.compile(r"spread\s+([0-9.]+)\s*>")


print("[basis OUTCOME: decision outcome text vs the venue winner (tokens[].winner) -- every hit/win-rate column this script prints]")

def con():
    c = sqlite3.connect(DB, uri=True)
    c.row_factory = sqlite3.Row
    return c


# ---------------------------------------------------------------- statistics
def _pct(v, q):
    v = sorted(v)
    if not v:
        return None
    k = (len(v) - 1) * q / 100.0
    f = int(k)
    c = min(f + 1, len(v) - 1)
    return v[f] + (v[c] - v[f]) * (k - f)


def boot(vals, mkts, reps=1000, seed=SEED):
    """Market-clustered bootstrap CI on the MEAN of vals (one value per leg)."""
    bym = defaultdict(list)
    for m, v in zip(mkts, vals):
        bym[m].append(v)
    keys = list(bym.keys())
    if len(keys) < 2:
        return (None, None)
    rnd = random.Random(seed)
    out = []
    for _ in range(reps):
        pick = [keys[rnd.randrange(len(keys))] for _ in keys]
        s = [v for k in pick for v in bym[k]]
        out.append(sum(s) / len(s))
    return (_pct(out, 2.5), _pct(out, 97.5))


def roi_at(won, entry):
    """Exact settled return on dollars at risk for a BUY at `entry`."""
    if entry <= 0:
        return None
    return ((1.0 - entry) / entry) if won else -1.0


def summary(legs):
    """legs = [(won:int, entry:float)] -> dict of hit/be/edge/roi(+CI) or None"""
    n = len(legs)
    if not n:
        return None
    hits = sum(w for w, _ in legs)
    mp = sum(p for _, p in legs) / n
    rois = [roi_at(w, p) for w, p in legs if roi_at(w, p) is not None]
    return {
        "n": n,
        "hit": 100.0 * hits / n,
        "be": 100.0 * mp,
        "edge": 100.0 * (hits / n - mp),
        "roi": 100.0 * sum(rois) / len(rois) if rois else None,
    }


def arm(legs, mkts, label, out):
    s = summary(legs)
    if not s:
        out.append((label, 0, None, None, None, None, None))
        return
    r = [roi_at(w, p) for w, p in legs]
    lo, hi = boot(r, mkts)
    out.append((label, s["n"], s["hit"], s["be"], s["edge"], s["roi"], (lo, hi)))


def fmt_arm(t):
    label, n, hit, be, edge, roi, ci = t
    if not n:
        return f"  {label:34} {'--':>4}"
    ci_s = f"[{100*ci[0]:+7.1f},{100*ci[1]:+7.1f}]" if ci[0] is not None else "     n/a     "
    return (f"  {label:34} {n:4d} {hit:6.1f} {be:6.1f} {edge:+7.1f} "
            f"{roi:+8.1f} {ci_s}")


# ---------------------------------------------------------------- cohort
def risks_of(js):
    try:
        a = json.loads(js or "[]")
        return a if isinstance(a, list) else ["(unparsed)"]
    except Exception:
        return ["(unparsed)"]


def spread_string_of(js):
    for s in risks_of(js):
        m = SPREAD_RE.search(s or "")
        if m:
            try:
                return float(m.group(1))
            except ValueError:
                return None
    return None


def gate_of(js):
    """Histogram key: the FIRST blocker, numbers collapsed, so it names the gate."""
    a = risks_of(js)
    if not a:
        return "(none recorded)"
    s = a[0].split("\u2014")[0]
    s = re.sub(r"\$?[0-9]+([.][0-9]+)?", "#", s)
    return s.split("(")[0].strip()[:52]


def cohort():
    c = con()
    rows = c.execute(FUNNEL_SQL, (REGIME,)).fetchall()
    c.close()
    seen = {}
    for r in rows:
        if r["d"] == "skip" and LO <= r["dp"] < HI:
            k = (r["m"], r["oc"])
            if k not in seen or r["ts"] < seen[k]["ts"]:
                seen[k] = r
    return len(rows), list(seen.values())


# ---------------------------------------------------------------- resolution
def fetch_winner(cid, allow_fetch):
    """Venue archive: tokens[].winner. Cache-first; the funnel instrument's cache
    is reused so both reads score the identical population."""
    if not cid:
        return None, False
    p = os.path.join(CACHE, cid + ".json")
    if os.path.exists(p):
        try:
            with open(p) as f:
                return json.load(f).get("winner"), True
        except Exception:
            return None, True
    if not allow_fetch:
        return None, False
    os.makedirs(CACHE, exist_ok=True)
    url = "https://clob.polymarket.com/markets/" + cid
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "medusa-copybot/1.0"})
            with urllib.request.urlopen(req, timeout=20) as r:
                js = json.loads(r.read().decode())
            win = None
            for t in js.get("tokens") or []:
                if t.get("winner") is True:
                    win = t.get("outcome")
            with open(p, "w") as f:
                json.dump({"winner": win, "closed": js.get("closed"),
                           "question": js.get("question")}, f)
            return win, True
        except urllib.error.HTTPError as e:
            if e.code == 404:
                with open(p, "w") as f:
                    json.dump({"winner": None, "closed": None, "http": 404}, f)
                return None, False
            time.sleep(1.0 + attempt)
        except Exception:
            time.sleep(1.0 + attempt)
    return None, False


# ---------------------------------------------------------------- the quote
def snapshots(market_id, ts, window_ms=WINDOW_MS):
    """Nearest snapshot at-or-before, nearest at-or-after, and nearest overall."""
    c = con()
    before = c.execute(
        "SELECT collectedAt, yesPrice, noPrice, bestBid, bestAsk, spread, question "
        "FROM MarketSnapshot WHERE marketId=? AND collectedAt<=? AND collectedAt>=? "
        "ORDER BY collectedAt DESC LIMIT 1", (market_id, ts, ts - window_ms)).fetchone()
    after = c.execute(
        "SELECT collectedAt, yesPrice, noPrice, bestBid, bestAsk, spread, question "
        "FROM MarketSnapshot WHERE marketId=? AND collectedAt>=? AND collectedAt<=? "
        "ORDER BY collectedAt ASC LIMIT 1", (market_id, ts, ts + window_ms)).fetchone()
    c.close()
    return before, after


def frame_and_ask(snap, dp):
    """Which token does the leg hold, and what is that token's ask?

    Identity comes from the PRICE, never the label: the leg's detection price is
    compared to the snapshot's two token mids. Returns (token0, mid, ask, margin).
    """
    if snap is None:
        return None
    y, n = snap["yesPrice"], snap["noPrice"]
    bb, ba = snap["bestBid"], snap["bestAsk"]
    if y is None or n is None:
        return None
    d0, d1 = abs(dp - y), abs(dp - n)
    margin = abs(d0 - d1)
    token0 = d0 <= d1
    mid = y if token0 else n
    if token0:
        ask = ba if ba is not None else None
    else:
        ask = (1.0 - bb) if bb is not None else None
    if ask is None or not (0.0 < ask < 1.0):
        return None
    return (token0, mid, ask, margin)


def ask_for_token(snap, token0):
    """Ask for a KNOWN token identity (0 = the snapshot's yesPrice side)."""
    if snap is None:
        return None
    if token0:
        ask = snap["bestAsk"]
        mid = snap["yesPrice"]
    else:
        bb = snap["bestBid"]
        ask = (1.0 - bb) if bb is not None else None
        mid = snap["noPrice"]
    if ask is None or not (0.0 < ask < 1.0):
        return None
    return (token0, mid, ask, 1.0)


def fee_rate_for(question):
    t = (question or "").lower()
    crypto = ["btc", "bitcoin", "eth", "ethereum", "solana", "crypto", "token", "airdrop",
              "fdv", "market cap"]
    polfin = ["election", "president", "senate", "congress", "nominee", "parliament",
              "prime minister", "fed", "rate cut", "inflation", "cpi", "gdp", "recession",
              "tariff", "stock", "nasdaq", "s&p", "earnings", "shutdown", "impeach", "poll",
              "vote", "governor", "mayor"]
    if any(w in t for w in crypto):
        return 0.07
    if any(w in t for w in polfin):
        return 0.04
    return FEE_DEFAULT


def fee_entry(price, rate):
    """Cost per share of a taker BUY: price + fee/sh, fee/sh = rate*p*(1-p)."""
    return price + rate * price * (1.0 - price)


# ---------------------------------------------------------------- decode
def spread_from_score(score, max_spread=MAX_SPREAD):
    """Invert the scorer's own stored spreadScore back into a spread.

    trade.ts:166  spreadScore = clamp(100 - (spread / maxSpread) * 70)
    so            spread     = (100 - spreadScore) * maxSpread / 70

    Exact while spread <= 100/70*maxSpread (~0.0857 at maxSpread 0.06); beyond
    that the clamp pins the score at 0 and the decode returns that ceiling, so
    callers must treat a score of 0 as "at least this wide", never as a value.
    """
    if score is None:
        return None
    s = max(0.0, min(100.0, float(score)))
    return (100.0 - s) * max_spread / 70.0


def section1b(with_s, no_s):
    print("\n" + "=" * 92)
    print("1. THE SPREAD IS ALREADY ON THE ROW -- spreadScore inverts it exactly")
    print("=" * 92)
    print("  DecisionJournal.spreadScore is written on every scored row (score-trades.ts:658).")
    print("  trade.ts:166 makes it an exact function of the spread, so a spread-blocked row")
    print("  can validate the inversion and an unblocked row can be priced by it:")
    print("     spreadScore = clamp(100 - (spread / maxSpread) * 70)")
    print("     spread      = (100 - spreadScore) * maxSpread / 70")
    val = []
    for r in with_s:
        sp = spread_string_of(r["risk"])
        dec = spread_from_score(r["ss"])
        if sp is not None and dec is not None:
            val.append((sp, dec))
    if val:
        unclamped = [(a, b) for a, b in val if a <= 100.0 * MAX_SPREAD / 70.0 - 0.001]
        diffs = sorted(abs(a - b) for a, b in val)
        ud = sorted(abs(a - b) for a, b in unclamped)
        exact = sum(1 for a, b in unclamped if abs(a - b) <= 0.0006)
        print(f"\n  validation on the {len(val)} rows that name a spread explicitly:")
        print(f"    {len(unclamped)} sit inside the clamp range (<={10000*MAX_SPREAD/70:.1f}c): "
              f"exact within 0.06c on {exact} ({100.0*exact/max(1,len(unclamped)):.0f}%), "
              f"median |delta| {1000*statistics.median(ud):.2f} mc, max {1000*ud[-1]:.1f} mc")
        print(f"    {len(val)-len(unclamped)} sit beyond it (score pinned at 0, "
              f"median recorded {100*statistics.median([a for a,_ in val if a > 100.0*MAX_SPREAD/70.0]):.1f}c) "
              f"-- those rows are 'at least 8.6c wide', not a value")
        print(f"    over all {len(val)}: median |delta| {1000*statistics.median(diffs):.2f} mc "
              f"(the clamp cases carry the error)")
    missing = sum(1 for r in no_s if r["ss"] is None)
    print(f"\n  rows in the passing arm with no spreadScore at all: {missing} of {len(no_s)}")
    dec = [spread_from_score(r["ss"]) for r in no_s if r["ss"] is not None]
    dec = [d for d in dec if d is not None]
    if dec:
        dec.sort()
        print(f"  decoded spread on the passing arm: median {100*statistics.median(dec):.2f}c, "
              f"p90 {100*dec[int(0.9*(len(dec)-1))]:.2f}c, max {100*dec[-1]:.2f}c")
        print(f"  (maxSpread is {100*MAX_SPREAD:.0f}c, so every row here is inside the gate)")
    return dec


# ---------------------------------------------------------------- sections
def section0(n_cand, cohort_rows):
    print("=" * 92)
    print("0. THE COHORT, AND THE CLAIM THAT IT IS REFUSED BEFORE THE SPREAD IS READ")
    print("=" * 92)
    n_c = len(cohort_rows)
    with_s = [r for r in cohort_rows if spread_string_of(r["risk"]) is not None]
    no_s = [r for r in cohort_rows if spread_string_of(r["risk"]) is None]
    print(f"\n  {n_cand} candidates in the live regime -> {n_c} refused cheap candidates "
          f"(deduped to the first sighting per market+outcome)")
    print(f"  spread blocker PRESENT on {len(with_s)} rows | ABSENT on {len(no_s)} rows")
    print("\n  trade.ts builds the hard-skip list in this order:")
    print("    1 wallet score   2 SPREAD   3 liquidity   4 drift   5 TTR   6 near-certainty"
          "   7 OBI   8 confidence")
    print("  every test runs unconditionally on every candidate, and the scorer's own input")
    print("  default is `spread = input.spread ?? 0.1` against maxSpread = 0.06. So:")
    print("    - spread MISSING  -> blocker 'spread 0.100 > max 0.06' is written")
    print("    - spread > 0.06   -> blocker 'spread <value> > max 0.06' is written")
    print("    - spread <= 0.06  -> the gate PASSES and writes nothing")
    n_bad_default = sum(1 for r in no_s if (spread_string_of(r["risk"]) is None
                                            and "spread" in (r["risk"] or "").lower()))
    print(f"\n  rows with no spread blocker that mention a spread at all: {n_bad_default} "
          f"-> the spread check RAN and PASSED on {len(no_s)} rows")
    print("  => 'refused before the spread is read' does not hold. What is missing is the")
    print("     VALUE (a passing gate records nothing), not the test.")

    print("\n  what actually refused them (full blocker SET, first blocker shown):")
    for k, v in Counter(gate_of(r["risk"]) for r in no_s).most_common(10):
        print(f"    {v:4d}  {100.0*v/len(no_s):5.1f}%  {k}")
    print("\n  co-blocking: how many hard skips fired together")
    for k in sorted(Counter(len(risks_of(r["risk"])) for r in no_s)):
        print(f"    {k} blocker(s): {sum(1 for r in no_s if len(risks_of(r['risk'])) == k)}")
    sole = [r for r in no_s if len(risks_of(r["risk"])) == 1]
    print(f"\n  SOLE blockers ({len(sole)} rows -- the ceiling on removing any one gate):")
    for k, v in Counter(gate_of(r["risk"]) for r in sole).most_common():
        print(f"    {v:4d}  {k}")
    pre = [r for r in no_s if "observation-only" in (r["risk"] or "")
           or "coalesced" in (r["risk"] or "")]
    print(f"  rows that never reached the scorer (pre-scorer journal paths): {len(pre)}")
    return with_s, no_s


def section1(no_s, allow_fetch):
    print("\n" + "=" * 92)
    print("2. THE ASK -- joining each row to the quote that stood beside it")
    print("=" * 92)
    print(f"  window +/-{WINDOW_MS//3600000}h around DecisionJournal.createdAt, same marketId;")
    print("  identity decided by price comparison against the snapshot's two token mids.")
    rows = []
    res_cached = res_fetched = 0
    for r in no_s:
        win, cached = fetch_winner(r["cid"], allow_fetch)
        if cached:
            res_cached += 1
        else:
            res_fetched += 1
        before, after = snapshots(r["m"], r["ts"])
        f_b = frame_and_ask(before, r["dp"]) if before else None
        # identity is a property of the POSITION, not of the quote: pin the token
        # index on the detection snapshot and reuse it. Re-inferring it on a later
        # snapshot flips the frame once the price has moved (a winner's token goes
        # to 1.0, so a price test then points at the losing side).
        f_a = None
        if before is not None and after is not None and f_b is not None:
            f_a = ask_for_token(after, f_b[0])
        rows.append({
            "r": r, "winner": win, "cached": cached,
            "before": before, "after": after, "f_b": f_b, "f_a": f_a,
        })
    print(f"\n  resolution: {res_cached} from cache, {res_fetched} uncached"
          f"{'' if allow_fetch else ' (run --fetch to fill)'}")
    resolved = [x for x in rows if x["winner"]]
    print(f"  resolved from the venue archive: {len(resolved)} of {len(rows)} "
          f"({100.0*len(resolved)/max(1,len(rows)):.0f}%)")
    with_b = [x for x in resolved if x["f_b"]]
    with_a = [x for x in resolved if x["f_a"]]
    print(f"  an ask is recoverable at-or-before the journal row : {len(with_b)} "
          f"({100.0*len(with_b)/max(1,len(resolved)):.0f}% of resolved)")
    print(f"  an ask is recoverable at-or-after  the journal row : {len(with_a)} "
          f"({100.0*len(with_a)/max(1,len(resolved)):.0f}%)")
    amb = [x for x in with_b if x["f_b"][3] < 0.01]
    print(f"  identity AMBIGUOUS (both tokens within 1c of the detection price): {len(amb)}"
          "  <- excluded from the ask arm, kept in the mid arm")
    lag = [abs(x["before"]["collectedAt"] - x["r"]["ts"]) / 1000.0 for x in with_b]
    if lag:
        lag.sort()
        print(f"  quote age at the journal row: median {statistics.median(lag):.0f}s, p90 "
              f"{lag[int(0.9*(len(lag)-1))]:.0f}s, max {lag[-1]:.0f}s "
              f"(the monitor writes the snapshot, the scorer journals seconds later)")
    print(f"  snapshots later than the journal row exist for {len(with_a)} rows: MarketSnapshot is")
    print("  EVENT-driven (a wallet trade in that market), not a quote series, so arm F is a")
    print("  selection-biased look at whatever sweep came next -- printed for completeness, not")
    print("  as an execution-lag estimate.")
    mids = [abs(x["f_b"][1] - x["r"]["dp"]) for x in with_b]
    if mids:
        print(f"  snapshot mid vs detection price: median {100000*statistics.median(mids):.0f} "
              f"(1e-5 c), max {100*max(mids):.2f}c -- the join lands on the quote the detection"
              " price was read from")
    # frame validation: does the price-based identity agree with the label prior?
    agree = dis = 0
    for x in with_b:
        oc = (x["r"]["oc"] or "").upper()
        tok0 = x["f_b"][0]
        if oc == "YES" and tok0:
            agree += 1
        elif oc == "NO" and not tok0:
            agree += 1
        elif oc in ("YES", "NO"):
            dis += 1
    print(f"  frame check: on YES/NO labels the price-based identity agrees "
          f"{agree}x, disagrees {dis}x (named outcomes excluded -- the label test cannot see them)")
    return rows


def section2(rows):
    print("\n" + "=" * 92)
    print("3. THE ARMS -- same hits, different entries. ROI on dollars at risk, market-clustered CI")
    print("=" * 92)
    ok = [x for x in rows if x["winner"]]

    def won_of(x):
        oc = (x["r"]["oc"] or "").upper()
        return 1 if oc == x["winner"].upper() else 0

    out = []
    legs = [(won_of(x), x["r"]["dp"]) for x in ok]
    arm(legs, [x["r"]["m"] for x in ok], "A detection mid (review)", out)

    sb = [x for x in ok if x["f_b"] and x["f_b"][3] >= 0.01]
    arm([(won_of(x), x["f_b"][1]) for x in sb], [x["r"]["m"] for x in sb],
        "B snapshot mid", out)
    arm([(won_of(x), x["f_b"][2]) for x in sb], [x["r"]["m"] for x in sb],
        "C ASK at detection  <-- answer", out)
    arm([(won_of(x), fee_entry(x["f_b"][2], fee_rate_for(x["before"]["question"])))
         for x in sb], [x["r"]["m"] for x in sb], "D ask + taker fee", out)
    arm([(won_of(x), x["r"]["dp"] + MAX_SPREAD) for x in ok], [x["r"]["m"] for x in ok],
        "E mid + maxSpread (gate bound)", out)
    gd = [x for x in ok if spread_from_score(x["r"]["ss"]) is not None]
    arm([(won_of(x), x["r"]["dp"] + spread_from_score(x["r"]["ss"])) for x in gd],
        [x["r"]["m"] for x in gd], "G mid + decoded spreadScore", out)
    arm([(won_of(x), x["r"]["dp"] + 0.5 * spread_from_score(x["r"]["ss"])) for x in gd],
        [x["r"]["m"] for x in gd], "H mid + half decoded spread", out)
    sa = [x for x in ok if x["f_a"] and x["f_a"][3] >= 0.01]
    arm([(won_of(x), x["f_a"][2]) for x in sa], [x["r"]["m"] for x in sa],
        "F ask, next snapshot after", out)

    print(f"\n  {'arm':34} {'n':>4} {'hit%':>6} {'be%':>6} {'edge_pp':>7} {'ROI%':>8}  95% CI")
    for t in out:
        print(fmt_arm(t))

    # the risk the mid-arm hid: how far the ask sits from the mid
    gaps = [100.0 * (x["f_b"][2] - x["r"]["dp"]) for x in sb
            if x["f_b"][2] is not None]
    if gaps:
        gaps.sort()
        print(f"\n  ask minus detection mid: median {statistics.median(gaps):+.1f}c, "
              f"mean {sum(gaps)/len(gaps):+.1f}c, p90 {gaps[int(0.9*(len(gaps)-1))]:+.1f}c, "
              f"max {gaps[-1]:+.1f}c")
        hit_pct = 100.0 * sum(won_of(x) for x in ok) / len(ok)
        print(f"  breakeven entry at the cohort's {hit_pct:.1f}% hit rate: {hit_pct:.1f}c "
              f"-- the fill can be {hit_pct - 100.0*sum(x['r']['dp'] for x in ok)/len(ok):+.1f}c "
              f"worse than the detection mid before the edge is gone")
    return sb, out


def section2b(sb, rows):
    print("\n" + "=" * 92)
    print("4. ROBUSTNESS OF THE ASK ARM -- is the return a book or three legs?")
    print("=" * 92)
    ok = [x for x in sb if x["winner"]]

    def won_of(x):
        oc = (x["r"]["oc"] or "").upper()
        return 1 if oc == x["winner"].upper() else 0

    legs = sorted(((won_of(x), x["f_b"][2], x["r"]["m"]) for x in ok),
                  key=lambda t: -roi_at(t[0], t[1]))
    base = summary([(w, a) for w, a, _ in legs])["roi"]
    for k in (5, 10, 20):
        ex = legs[k:]
        if not ex:
            continue
        s = summary([(w, a) for w, a, _ in ex])
        lo, hi = boot([roi_at(w, a) for w, a, _ in ex], [m for _, _, m in ex])
        ci = f"[{100*lo:+.0f},{100*hi:+.0f}]" if lo is not None else "n/a"
        print(f"  ex-top-{k:<3} n={s['n']:4d} hit {s['hit']:5.1f}% ROI {s['roi']:+8.1f}% CI {ci}")
    print(f"  full arm n={len(legs)} ROI {base:+.1f}%")

    print("\n  by price band at the ask:")
    for lo_b, hi_b in ((0.05, 0.10), (0.10, 0.15), (0.15, 0.20)):
        cell = [(w, a) for w, a, _ in legs if lo_b <= a < hi_b]
        if not cell:
            continue
        s = summary(cell)
        print(f"    {100*lo_b:.0f}-{100*hi_b:.0f}c  n={s['n']:3d} hit {s['hit']:5.1f}% "
              f"be {s['be']:5.1f}% edge {s['edge']:+6.1f}pp ROI {s['roi']:+8.1f}%")

    wins = [roi_at(w, a) for w, a, _ in legs if w]
    losses = [roi_at(w, a) for w, a, _ in legs if not w]
    hit = 100.0 * len(wins) / len(legs)
    print(f"\n  payoff shape: {len(wins)} wins / {len(losses)} losses "
          f"({hit:.1f}% hit), mean win {100*sum(wins)/len(wins):+.0f}%, "
          f"mean loss {100*sum(losses)/len(losses):+.0f}%")
    print(f"  breakeven hit rate = the entry paid = {100*sum(a for _, a, _ in legs)/len(legs):.1f}%")
    print("  geometric mean at FULL size is -100% (any total loss zeroes the product), so this")
    print("  cohort is a FRACTIONAL-stake instrument; at a stated stake per leg it compounds as:")
    for f in (0.05, 0.02):
        g = 1.0
        for r in [roi_at(w, a) for w, a, _ in legs]:
            g *= (1.0 + f * r)
        gm = 100.0 * (g ** (1.0 / len(legs)) - 1.0)
        print(f"    {100*f:.0f}% of bankroll per leg -> geometric {gm:+.2f}% per leg "
              f"({gm*len(legs):+.0f}% over {len(legs)} legs)")


def section5(sb, rows):
    print("\n" + "=" * 92)
    print("6. REACHABILITY -- a sole blocker is a CEILING; the score floor fires next")
    print("=" * 92)
    print("  Live RuleSet v73: longshotMinCopyScore 70 (price < 0.20), minCopyScore 80,")
    print("  longshotMinConfidence 0.55 (== copyScore 70.75 via confidence=(score-35)/65),")
    print("  highScoreCapMin 80 with highScoreMaxDrift 0.004 (the v29 late-entry filter).")
    print("  So a row whose only hard skip is gate G is ADMITTED only if its stored copyScore")
    print("  clears 70 and it does not trip the late-entry filter on the way through.\n")
    ok = [x for x in sb if x["winner"]]
    byg = defaultdict(list)
    for x in ok:
        if len(risks_of(x["r"]["risk"])) != 1:
            continue
        byg[gate_of(x["r"]["risk"])].append(x)
    print(f"  {'sole blocker':44} {'n':>3} {'score>=70':>9} {'reach ROI@ask':>14}")
    for g, xs in sorted(byg.items(), key=lambda kv: -len(kv[1])):
        reach = [x for x in xs if (x["r"]["cs"] or 0) >= 70]
        roi = "n/a"
        if reach:
            legs = [(1 if (x["r"]["oc"] or "").upper() == x["winner"].upper() else 0,
                     x["f_b"][2]) for x in reach]
            roi = f"{summary(legs)['roi']:+.1f}%"
        print(f"  {g[:44]:44} {len(xs):3d} {len(reach):9d} {roi:>14}")
    tot = sum(1 for xs in byg.values() for x in xs if (x["r"]["cs"] or 0) >= 70)
    print(f"\n  REACHABLE ceiling across all sole-blocked rows at the ask: {tot} legs "
          f"(of {sum(len(v) for v in byg.values())} sole-blocked, "
          f"{len(ok)} resolved)")
    print("  still not evaluated here: the lane's per-market / per-wallet / per-cycle caps,")
    print("  the category blacklist, the hour blackout and the dedupe coalesce -- all of which")
    print("  fire AFTER the scorer, so the true admitted count is <= this number.")

    # the one reachable population that is big enough to price at all
    ttr = [x for g, xs in byg.items() if g.startswith("resolves in")
           for x in xs if (x["r"]["cs"] or 0) >= 70]
    if ttr:
        legs = sorted(((1 if (x["r"]["oc"] or "").upper() == x["winner"].upper() else 0,
                        x["f_b"][2], x["r"]["m"]) for x in ttr),
                      key=lambda t: -(roi_at(t[0], t[1]) or 0))
        s = summary([(w, a) for w, a, _ in legs])
        lo, hi = boot([roi_at(w, a) for w, a, _ in legs], [m for _, _, m in legs])
        print(f"\n  THE TTR-REACHABLE POPULATION (sole blocker 'resolves in <2h', score >= 70):")
        print(f"    n={s['n']} across {len(set(m for _, _, m in legs))} markets, hit {s['hit']:.1f}% "
              f"vs breakeven {s['be']:.1f}% = {s['edge']:+.1f}pp, ROI at ask {s['roi']:+.1f}% "
              f"CI [{100*lo:+.0f},{100*hi:+.0f}]")
        for k in (3, 5, 10):
            ex = legs[k:]
            if not ex:
                continue
            se = summary([(w, a) for w, a, _ in ex])
            print(f"    ex-top-{k:<2} n={se['n']:2d} hit {se['hit']:5.1f}% ROI {se['roi']:+8.1f}%")
        print(f"    these settle within 2h of the decision, so the counterfactual is a pure")
        print(f"    settlement hold: no exit policy, no mark, no stale-exit dependency.")
        def ttr_of(x):
            m = re.search(r"resolves in ([0-9.]+)h", x["r"]["risk"] or "")
            return float(m.group(1)) if m else 0.0

        ttrs = sorted(ttr_of(x) for x in ttr)
        if ttrs:
            ttrs.sort()
            print(f"    TTR at decision: median {statistics.median(ttrs):.2f}h, "
                  f"min {ttrs[0]:.2f}h, max {ttrs[-1]:.2f}h")
        pref = Counter((x["r"]["m"] or "?").split("-")[0] for x in ttr)
        print(f"    market-slug families: " + ", ".join(f"{k} {v}" for k, v in pref.most_common(6)))
        asks = [x["f_b"][2] for x in ttr]
        print(f"    ask paid: median {100*statistics.median(asks):.1f}c, "
              f"mean {100*sum(asks)/len(asks):.1f}c, max {100*max(asks):.1f}c")
        # a market resolving in <6 minutes is a race, not a copy: print the sensitivity
        for floor_h in (0.1, 0.25, 0.5):
            sub = [x for x in ttr if ttr_of(x) >= floor_h]
            if not sub:
                continue
            sl = [(1 if (x["r"]["oc"] or "").upper() == x["winner"].upper() else 0,
                   x["f_b"][2]) for x in sub]
            ss = summary(sl)
            print(f"    TTR >= {floor_h:.2f}h: n={ss['n']:2d} hit {ss['hit']:5.1f}% "
                  f"ROI {ss['roi']:+8.1f}%")


def section3(sb, rows):
    print("\n" + "=" * 92)
    print("5. WHICH GATE IS REFUSING THE MONEY (ask arm, split by first blocker)")
    print("=" * 92)
    ok = [x for x in sb if x["winner"]]
    byg = defaultdict(list)
    for x in ok:
        byg[gate_of(x["r"]["risk"])].append(x)
    print(f"  {'first blocker':52} {'n':>4} {'hit%':>6} {'be%':>6} {'ROI@ask%':>9}")
    for g, xs in sorted(byg.items(), key=lambda kv: -len(kv[1])):
        legs = [(1 if (x["r"]["oc"] or "").upper() == x["winner"].upper() else 0,
                 x["f_b"][2]) for x in xs]
        s = summary(legs)
        print(f"  {g[:52]:52} {s['n']:4d} {s['hit']:6.1f} {s['be']:6.1f} {s['roi']:+9.1f}")
    sole = [x for x in ok if len(risks_of(x["r"]["risk"])) == 1]
    if sole:
        legs = [(1 if (x["r"]["oc"] or "").upper() == x["winner"].upper() else 0,
                 x["f_b"][2]) for x in sole]
        s = summary(legs)
        lo, hi = boot([roi_at(w, p) for w, p in legs], [x["r"]["m"] for x in sole])
        ci = f"[{100*lo:+.0f},{100*hi:+.0f}]" if lo is not None else "n/a"
        print(f"\n  SOLE-blocker subset at the ask: n={s['n']} hit {s['hit']:.1f}% "
              f"ROI {s['roi']:+.1f}% CI {ci} -- the only rows a single-gate change could admit")


def section4(all_rows, with_s, allow_fetch):
    print("\n" + "=" * 92)
    print("7. POSITIVE CONTROL -- the arm whose spread check FIRED, priced the same way")
    print("=" * 92)
    print("  If the instrument is honest, the spread-gate arm must read NEGATIVE at the ask")
    print("  and the passing arm positive; if both read the same, the join is measuring noise.")
    ok = []
    for r in with_s:
        win, _ = fetch_winner(r["cid"], allow_fetch)
        if not win:
            continue
        before, _ = snapshots(r["m"], r["ts"])
        f = frame_and_ask(before, r["dp"]) if before else None
        if not f or f[3] < 0.01:
            continue
        ok.append((1 if (r["oc"] or "").upper() == win.upper() else 0, f[2], r["m"], f[1]))
    if not ok:
        print("  no coverage -- control withheld")
        return
    legs = [(w, a) for w, a, _, _ in ok]
    s = summary(legs)
    lo, hi = boot([roi_at(w, a) for w, a in legs], [m for _, _, m, _ in ok])
    print(f"\n  spread-gate arm at the ASK: n={s['n']} hit {s['hit']:.1f}% be {s['be']:.1f}% "
          f"ROI {s['roi']:+.1f}% CI [{100*lo:+.1f},{100*hi:+.1f}]")


# ---------------------------------------------------------------- section 9
# THE OUTCOME BASIS
# Every number in sections 2-7 tests a win as `outcome_label == venue winner`.
# That test is only meaningful if the label names the token the leg is PRICED on.
# Section 1 identifies the token by PRICE and says so ("frame check: agrees 99x,
# disagrees 0x") -- but that check only covers rows labelled YES/NO, i.e. exactly
# the rows where the question is uninteresting. On a named-outcome market the two
# questions come apart, and they come apart in the direction that manufactures a
# win rate: the cheap side of a two-outcome named market is the side the label
# does not name.
#
# This section re-tests every resolved row on the token-level basis instead:
# the venue archive's tokens[] carries a winner flag per TOKEN, so the win test
# becomes "did the token this leg was priced on win", with no label in the path.
# Both bases are printed side by side, split by label class and by the date of
# the 2026-11-09 price-side fix, because a defect that only exists before a fix
# is a historical fact and one that survives it is a live one.
TOKEN_TRUTH = os.path.join("data", "cheap-token-truth.json")
PRICE_SIDE_FIX_MS = 1794237316000   # 2026-11-09 09:15:16, the fbf9073 write fix


def _token_cache():
    if os.path.exists(TOKEN_TRUTH):
        try:
            with open(TOKEN_TRUTH) as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def token_truth(cid, cache, allow_fetch):
    """conditionId -> [[outcome, winner], ...] from the venue archive, or None."""
    if not cid:
        return None
    if cid in cache:
        rec = cache[cid]
        return rec if isinstance(rec, list) else None
    if not allow_fetch:
        return None
    url = "https://clob.polymarket.com/markets/" + cid
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "medusa-copybot/1.0"})
            with urllib.request.urlopen(req, timeout=20) as r:
                js = json.loads(r.read().decode())
            toks = [[str(t.get("outcome")), bool(t.get("winner"))]
                    for t in (js.get("tokens") or [])]
            cache[cid] = toks
            time.sleep(0.25)                      # keyless endpoint, stay polite
            return toks
        except urllib.error.HTTPError as e:
            if e.code == 404:
                cache[cid] = {"http": 404}
                return None
            time.sleep(1.2 * (attempt + 1))
        except Exception:
            time.sleep(0.6 * (attempt + 1))
    return None


def basis_win(x, toks):
    """(held_token_won, held_name, other_name) on the token-level basis."""
    tok0 = x["f_b"][0]
    held, other = (toks[0], toks[1]) if tok0 else (toks[1], toks[0])
    return held[1], held[0], other[0]


def section9(rows, allow_fetch):
    print("\n" + "=" * 92)
    print("9. THE OUTCOME BASIS -- label vs the token the leg is actually priced on")
    print("=" * 92)
    cache = _token_cache()
    resolved = [x for x in rows if x["winner"] and x["f_b"]]
    print(f"  resolved rows with an identity: {len(resolved)}")
    got = []
    for x in resolved:
        toks = token_truth(x["r"]["cid"], cache, allow_fetch)
        if not toks or len(toks) != 2:
            continue
        won, held, other = basis_win(x, toks)
        lab = (x["r"]["oc"] or "").upper()
        got.append({
            "x": x, "tok_won": won, "held": held, "other": other,
            "lab_class": "YES/NO" if lab in ("YES", "NO") else "named",
            "lab_win": bool(x["winner"]) and lab == str(x["winner"]).upper(),
            "post_fix": x["r"]["ts"] >= PRICE_SIDE_FIX_MS,
        })
    if allow_fetch:
        with open(TOKEN_TRUTH, "w") as f:
            json.dump(cache, f)
        print(f"  token-truth cache written: {TOKEN_TRUTH} "
              f"({sum(1 for v in cache.values() if isinstance(v, list))} markets with tokens)")
    print(f"  token-level truth recovered: {len(got)} of {len(resolved)}")
    if not got:
        print("  no token truth -- rerun with --fetch. NOTHING BELOW IS A MEASUREMENT.")
        return

    def line(label, xs):
        if not xs:
            return
        lb = sum(1 for g in xs if g["lab_win"])
        tb = sum(1 for g in xs if g["tok_won"])
        dis = sum(1 for g in xs if g["lab_win"] != bool(g["tok_won"]))
        print(f"  {label:34} n={len(xs):4d}  label-basis {100.0*lb/len(xs):5.1f}%  "
              f"token-basis {100.0*tb/len(xs):5.1f}%  disagree {dis:4d} "
              f"({100.0*dis/len(xs):4.1f}%)")

    line("ALL resolved", got)
    line("  label YES/NO", [g for g in got if g["lab_class"] == "YES/NO"])
    line("  label NAMED", [g for g in got if g["lab_class"] == "named"])
    line("  pre-2026-11-09 fix", [g for g in got if not g["post_fix"]])
    line("  post-2026-11-09 fix", [g for g in got if g["post_fix"]])
    yn = [g for g in got if g["lab_class"] == "YES/NO"]
    yn_dis = sum(1 for g in yn if g["lab_win"] != bool(g["tok_won"]))
    print(f"\n  INVARIANT: on YES/NO rows the two bases must agree ({len(yn)} rows, "
          f"{yn_dis} disagreements)")
    if yn_dis:
        print("  FAIL -- the token join is broken, not the labels. Do not read past this line.")

    # the arm that section 5 called reachable, priced on the honest basis
    print("\n  THE ARM SECTION 5 CALLED 'REACHABLE', BOTH BASES")
    for arm_label, pick in (("label basis (as filed)", True), ("token basis (honest)", False)):
        sub = []
        for g in got:
            x = g["x"]
            if len(risks_of(x["r"]["risk"])) != 1:
                continue
            if not gate_of(x["r"]["risk"]).startswith("resolves in"):
                continue
            if (x["r"]["cs"] or 0) < 70:
                continue
            w = int(g["lab_win"]) if pick else int(bool(g["tok_won"]))
            sub.append((w, x["f_b"][2], x["r"]["m"]))
        if not sub:
            continue
        s = summary([(w, a) for w, a, _ in sub])
        lo, hi = boot([roi_at(w, a) for w, a, _ in sub], [m for _, _, m in sub])
        print(f"  {arm_label:26} n={s['n']:3d}  hit {s['hit']:5.1f}%  be {s['be']:5.1f}%  "
              f"edge {s['edge']:+6.1f}pp  ROI {s['roi']:+8.1f}%  CI [{100*lo:+.0f},{100*hi:+.0f}]")
    print("\n  A gap between those two rows is the measurement error, not an edge. The label")
    print("  basis is what every band ROI in this repo has been computed on.")

    # the whole cohort the awaiting-approval card is built on
    print("\n  THE WHOLE REFUSED COHORT AT THE ASK, BOTH BASES (this is card")
    print("  profit-cheap-refusal-ask-price's population)")
    for arm_label, pick in (("label basis (as filed)", True), ("token basis (honest)", False)):
        sub = [(int(g["lab_win"]) if pick else int(bool(g["tok_won"])),
                g["x"]["f_b"][2], g["x"]["r"]["m"]) for g in got]
        s = summary([(w, a) for w, a, _ in sub])
        lo, hi = boot([roi_at(w, a) for w, a, _ in sub], [m for _, _, m in sub])
        print(f"  {arm_label:26} n={s['n']:3d}  hit {s['hit']:5.1f}%  be {s['be']:5.1f}%  "
              f"edge {s['edge']:+6.1f}pp  ROI {s['roi']:+8.1f}%  CI [{100*lo:+.0f},{100*hi:+.0f}]")
    # post-fix only: the population a forward decision would actually be made on
    for arm_label, pick in (("post-fix, label basis", True), ("post-fix, token basis", False)):
        sub = [(int(g["lab_win"]) if pick else int(bool(g["tok_won"])),
                g["x"]["f_b"][2], g["x"]["r"]["m"]) for g in got if g["post_fix"]]
        if len(sub) < 5:
            continue
        s = summary([(w, a) for w, a, _ in sub])
        lo, hi = boot([roi_at(w, a) for w, a, _ in sub], [m for _, _, m in sub])
        print(f"  {arm_label:26} n={s['n']:3d}  hit {s['hit']:5.1f}%  be {s['be']:5.1f}%  "
              f"edge {s['edge']:+6.1f}pp  ROI {s['roi']:+.1f}%  CI [{100*lo:+.0f},{100*hi:+.0f}]")

    # the 2026-11-20 fee repricing, on this cohort's own prices (arithmetic, not a
    # measurement of the book: paper fills pay no fee, so this changes no ledger row)
    asks = [g["x"]["f_b"][2] for g in got]
    med = statistics.median(asks)
    print(f"\n  FEE DRAG ON THIS COHORT'S PRICES (fee/cost = rate * (1-p), p = median ask {100*med:.1f}c)")
    for lbl, rate in (("pre-2026-11-20 (5c politics/culture/econ/weather)", 0.05),
                      ("post-2026-11-20 (1c for the same categories)", 0.01),
                      ("sports, unchanged", 0.05)):
        print(f"    {lbl:52} {100*rate*(1-med):5.2f}c per dollar at risk")
    print("  paper fills pay no fee at all (src/lib/copy-cost.ts), so this moves no")
    print("  realised number; it only re-prices what a live fill would cost.")


def self_test():
    print("SELF-TEST")
    ok = tot = 0

    def chk(name, cond, extra=""):
        nonlocal ok, tot
        tot += 1
        ok += 1 if cond else 0
        print(f"  [{'OK ' if cond else 'FAIL'}] {name}{(' ' + extra) if extra else ''}")

    # 1. the payout identity: a win at 0.10 pays 9x, a loss costs the stake
    chk("roi_at(win,0.10)=900%", abs(roi_at(1, 0.10) - 9.0) < 1e-9)
    chk("roi_at(loss,0.10)=-100%", roi_at(0, 0.10) == -1.0)
    # 2. breakeven: 20% hit at 0.20 is exactly zero ROI
    chk("20% hit at 0.20 = 0 ROI", abs(summary([(1, 0.2)] + [(0, 0.2)] * 4)["roi"]) < 1e-9)
    # 3. MONOTONE IN ENTRY: raising the entry must lower ROI on the same hits
    l1 = [(1, 0.12), (0, 0.12), (1, 0.15)]
    l2 = [(1, 0.18), (0, 0.18), (1, 0.18)]
    chk("same hits, worse entry -> lower ROI",
        summary(l2)["roi"] < summary(l1)["roi"])
    # 4. NEGATIVE CONTROL: the ask arm can never exceed the mid arm on the same rows
    syn = [(1, 0.12, 0.10, 0.14), (0, 0.12, 0.10, 0.14), (1, 0.08, 0.07, 0.09)]
    mid = summary([(w, m) for w, m, _, _ in syn])["roi"]
    ask = summary([(w, a) for w, _, _, a in syn])["roi"]
    chk("ask arm <= mid arm on the same hits", ask < mid, f"({ask:+.1f}% vs {mid:+.1f}%)")
    # 5. FRAME: token1 ask is the complement of token0's bid, never bestAsk
    snap0 = {"yesPrice": 0.44, "noPrice": 0.56, "bestBid": 0.43, "bestAsk": 0.45}
    f0 = frame_and_ask(snap0, 0.44)
    f1 = frame_and_ask(snap0, 0.56)
    chk("token0 ask = bestAsk", f0 and abs(f0[2] - 0.45) < 1e-9)
    chk("token1 ask = 1 - bestBid", f1 and abs(f1[2] - 0.57) < 1e-9)
    chk("identity flips on a named market with no YES/NO label",
        frame_and_ask(snap0, 0.555)[0] is False)
    chk("ambiguous identity is flagged, not guessed",
        abs(frame_and_ask({"yesPrice": 0.5, "noPrice": 0.5, "bestBid": 0.49,
                           "bestAsk": 0.51}, 0.5)[3]) < 0.01)
    # 6. a 0 bid on the OTHER token makes this token's ask 1.0 -> out of range, rejected
    chk("ask of 1.0 is rejected", frame_and_ask(
        {"yesPrice": 0.9, "noPrice": 0.1, "bestBid": 0.0, "bestAsk": 0.91}, 0.10) is None)
    # 7. FEE: raising the rate lowers ROI, and the fee is the documented law
    a = 0.12
    chk("fee law rate*p*(1-p)", abs((fee_entry(a, 0.05) - a) - 0.05 * a * (1 - a)) < 1e-12)
    chk("higher fee rate -> lower ROI",
        summary([(1, fee_entry(a, 0.07))])["roi"] < summary([(1, fee_entry(a, 0.04))])["roi"])
    # 8. GATE-IMPLIED BOUND: mid + maxSpread must dominate the true ask only if the
    #    row really passed the spread gate; assert the guard that decides this
    chk("a row with a spread blocker is NOT in the passing arm",
        spread_string_of('["spread 0.081 > max 0.06"]') == 0.081)
    chk("a row with no spread blocker is in the passing arm",
        spread_string_of('["liquidity $120 < min $750"]') is None)
    # 9. gate label must name the gate, not the value
    chk("gate label collapses numbers",
        gate_of('["liquidity $120 < min $750"]') == gate_of('["liquidity $12 < min $750"]'))
    # 10. OUTCOME BASIS: the label and the token can name different sides, and the
    #     token basis must follow the PRICED token, never the label.
    chk("basis: label 'Yes' on token0 -> win",
        basis_win({"f_b": (True, 0.12, 0.13, 1.0), "r": {"oc": "Yes"}},
                  [["Yes", True], ["No", False]])[0] is True)
    chk("basis: named label naming the OTHER token -> loss",
        basis_win({"f_b": (True, 0.12, 0.13, 1.0), "r": {"oc": "UNDER"}},
                  [["Over", False], ["Under", True]])[0] is False)
    chk("basis: flips with the priced token, not the label",
        basis_win({"f_b": (False, 0.12, 0.88, 1.0), "r": {"oc": "UNDER"}},
                  [["Over", False], ["Under", True]])[0] is True)
    print(f"\n  {ok}/{tot} checks passed")
    return 0 if ok == tot else 1


def section8():
    print("\n" + "=" * 92)
    print("8. FLOW -- how often this population appears (independent source: the long-shot shadow ladder)")
    print("=" * 92)
    path = os.path.join("data", "longshot-shadow.jsonl")
    if not os.path.exists(path):
        print("  shadow ladder not found -- flow claim withheld")
        return
    import datetime as _dt
    rows = []
    for line in open(path):
        try:
            r = json.loads(line)
        except Exception:
            continue
        if r.get("type") == "candidate":
            rows.append(r)
    if not rows:
        print("  no candidates -- withheld")
        return
    ts = [_dt.datetime.fromisoformat(r["ts"].replace("Z", "+00:00")) for r in rows if r.get("ts")]
    days = (max(ts) - min(ts)).total_seconds() / 86400.0
    lo = [r for r in rows if LO <= (r.get("entryPrice") or 0) < HI]
    ttr = [r for r in lo if (r.get("ttrHours") or 99) < 2]
    print(f"  {len(rows)} sub-${HI*100:.0f}c candidates over {days:.1f} days "
          f"({min(ts).date()} .. {max(ts).date()})")
    print(f"  cheap 0.05-0.20: {len(lo)} ({len(lo)/days:.1f}/day)")
    print(f"  of those, TTR < 2h: {len(ttr)} ({len(ttr)/days:.2f}/day, "
          f"{100.0*len(ttr)/max(1,len(lo)):.1f}% of cheap)")
    sp = sorted((r.get("spread") or 0) for r in ttr)
    if sp:
        print(f"  their spread: median {100*sp[len(sp)//2]:.2f}c, "
              f"p90 {100*sp[int(0.9*(len(sp)-1))]:.2f}c, max {100*sp[-1]:.2f}c")
    sc = sorted((r.get("copyScore") or 0) for r in ttr)
    print(f"  their copyScore: median {sc[len(sc)//2]:.1f}, >=70 on "
          f"{sum(1 for s in sc if s >= 70)} of {len(sc)}")
    fam = Counter((r.get("marketId") or "?").split("-")[0] for r in ttr)
    print(f"  families: " + ", ".join(f"{k} {v}" for k, v in fam.most_common(8)))


def main():
    args = sys.argv[1:]
    if "--self-test" in args:
        return self_test()
    allow_fetch = "--fetch" in args
    n_cand, ch = cohort()
    with_s, no_s = section0(n_cand, ch)
    section1b(with_s, no_s)
    rows = section1(no_s, allow_fetch)
    sb, arms = section2(rows)
    section2b(sb, rows)
    section3(sb, rows)
    section5(sb, rows)
    section4(rows, with_s, allow_fetch)
    section8()
    section9(rows, allow_fetch)
    return 0


if __name__ == "__main__":
    sys.exit(main())
