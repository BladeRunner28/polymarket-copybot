#!/usr/bin/env python3
"""
profit-ledger-repair-preflight -- what WOULD the 137-row repair write?

WHY THIS EXISTS
---------------
`drafts/profit-recs-20261110.md` (roadmap card ledger-price-side-repair) asks to
"set entryPrice to the token price at the trade minute (the same read
outcome-price.ts now performs), recompute realizedPnl on the payoff identity,
rebuild BotBankroll + PnlSnapshot".

That sentence names an estimator, not a value. Before an operator approves a
137-row write to the live DB, the number it produces has to be measured rather
than assumed, and three things have to be checked that no existing instrument
checks:

  1. IS THE PRESCRIBED READ EVEN AVAILABLE HISTORICALLY?
     MarketSnapshot carries yesPrice/noPrice POSITIONALLY and -- measured by this
     file -- 100% of its 15.9M rows carry `rawMarketJson = '{}'`. The only
     in-house price store is therefore the very positional read that caused the
     bug, so "the token price at the trade minute, by label" cannot be recomputed
     from snapshots at all. The repairs that CAN be measured are:
        V  the venue's own price for our token at the openedAt minute
           (CLOB /markets/<conditionId> -> token_id -> /prices-history)
        W  the copied wallet's fill on the same labelled outcome
           (ObservedTrade.walletEntryPrice; the provenance join)
        C  the arithmetic complement 1 - booked_entry
     This file prices the class under all three and reports where they disagree.

  2. IS THE EXIT SIDE ALSO WRONG?
     A resolved leg's exit is 0/1 and side-independent, so entry-only repair is
     exact. An EARLY-CLOSED leg's `currentPrice` is the price bookkept by the
     same positional read, i.e. the sibling token's price at the close minute. For
     those legs the card's entry-only change divides our entry by the sibling's
     exit -- the same defect, one column over. This file measures how many legs
     are in that bucket and what the correct exit complement does to the ledger.

  3. IS 137 THE WHOLE CLASS?
     The classifier needs an ObservedTrade to compare against. A leg with no
     provenance row cannot be classified, and a leg whose wallet fill is 6-10c
     away from the complement cannot be either. Both are counted here rather than
     assumed empty.

Read-only. Opens the DB with `mode=ro`; writes nothing but the manifest JSONL and
the HTTP cache under the paths given on the command line.

USAGE
  COPYBOT_DB=/path/to/prisma/dev.db python3 scripts/profit-ledger-repair-preflight.py \
      --manifest data/repair-manifests/ledger-price-side-20261110.jsonl \
      --cache   data/repair-manifests/venue-cache.json
  ... --offline     # use the cache only; legs with no cached venue read are UNKNOWN
"""
import argparse
import datetime
import json
import os
import random
import sqlite3
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

DB = os.environ.get("COPYBOT_DB", "prisma/dev.db")
FIX_EPOCH = "2026-11-09 09:15:16"   # fbf9073 write-path fix, local (CST)
MIRROR_TOL = 0.06                    # booked == complement of the fill, within spread
SEP_TOL = 0.10                       # ...and far enough from the fill to be a real error
BANDS = [(0.0, 0.2), (0.2, 0.4), (0.4, 0.6), (0.6, 0.8), (0.8, 1.0001)]
HDR = {"User-Agent": "copybot-repair-preflight/1.0"}
CACHE = {}


# ---------------------------------------------------------------- db (read-only)
def con():
    c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    c.row_factory = sqlite3.Row
    return c


def _ms(v):
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v)
    y, mo, d = int(s[0:4]), int(s[5:7]), int(s[8:10])
    hh = int(s[11:13]) if len(s) > 12 else 0
    mm = int(s[14:16]) if len(s) > 15 else 0
    ss = int(s[17:19]) if len(s) > 18 else 0
    return datetime.datetime(y, mo, d, hh, mm, ss,
                             tzinfo=datetime.timezone.utc).timestamp() * 1000


def load():
    q = """SELECT p.id, p.botId, p.venue, p.walletAddress, p.marketId, p.outcome, p.side,
                  p.entryPrice, p.currentPrice, p.simulatedPositionSize, p.realizedPnl,
                  p.unrealizedPnl, p.status, p.openedAt, p.closedAt, p.resolvedAt,
                  p.isDemo, p.fillStatus, p.fillBasis, p.intentPrice,
                  d.ruleSetVersion AS rv, d.observedTradeId,
                  o.walletEntryPrice AS w, o.conditionId AS cid, o.timestamp AS ots,
                  o.detectedPrice AS dp
             FROM PaperTrade p
             JOIN DecisionJournal d ON d.id = p.decisionJournalId
             LEFT JOIN ObservedTrade o ON o.id = d.observedTradeId"""
    rows = [dict(r) for r in con().execute(q).fetchall()]
    for r in rows:
        r["openedTs"] = _ms(r["openedAt"])
        r["closedTs"] = _ms(r["closedAt"]) if r["closedAt"] else None
        r["resolvedTs"] = _ms(r["resolvedAt"]) if r["resolvedAt"] else None
        r["endTs"] = r["closedTs"] or r["resolvedTs"]
    return rows


def classify(r):
    b, w = r["entryPrice"], r["w"]
    if w is None:
        return "no_fill"
    mirror = abs(b - (1.0 - w))
    if (mirror + 0.01 < abs(b - w) and mirror <= MIRROR_TOL
            and abs(b - w) > SEP_TOL and 0.0 < w < 1.0):
        return "inverted"
    if abs(b - w) <= MIRROR_TOL:
        return "consistent"
    return "ambiguous"   # 6-10c from the fill: neither reproducible nor clearly mirrored


def repair_entry(l):
    """The entry price the repair writes: venue when it corroborates, else 1-b."""
    if classify(l) != "inverted":
        return l["entryPrice"]
    v, c = l.get("v_entry"), 1.0 - l["entryPrice"]
    if v is not None and abs(v - c) <= MIRROR_TOL:
        return v
    return round(c, 5)


def repair_exit(l):
    """The exit price the repair writes, for the token the leg actually holds."""
    if classify(l) != "inverted" or l["status"] == "resolved":
        return l["currentPrice"]
    t = l.get("_token")
    if t and l.get("closedTs"):
        v = fetch_price(t["token_id"], l["closedTs"], OFFLINE)
        if v:
            return v["p"]
    cp = l["currentPrice"]
    if cp is None or not (0.0 < cp < 1.0):
        return cp
    return round(1.0 - cp, 5) if (l["endTs"] or 0) <= _ms(FIX_EPOCH) else cp


def dedupe(legs):
    seen, out = set(), []
    for l in sorted(legs, key=lambda x: x["openedTs"]):
        k = (l["botId"], l["walletAddress"], l["marketId"], l["outcome"])
        if k in seen:
            continue
        seen.add(k)
        out.append(l)
    return out


def band_of(p):
    for lo, hi in BANDS:
        if lo <= p < hi:
            return "0.8-1.0" if hi > 1 else f"{lo:.1f}-{hi:.1f}"
    return None


def true_pnl(l, entry, exit_price=None):
    """PnL if the same exit had been booked at `entry`, dollars-at-risk fixed."""
    ntl, b, booked = l["simulatedPositionSize"], l["entryPrice"], l["realizedPnl"]
    if l["status"] == "open":
        return None
    if booked is not None and booked == 0 and l.get("fillStatus") == "unfilled":
        return 0.0
    if not ntl or ntl <= 0 or not b or b <= 0:
        return booked or 0.0
    if exit_price is None:
        if booked is None:
            return 0.0
        exit_price = b * (1.0 + booked / ntl)
    if entry is None or entry <= 0:
        return booked or 0.0
    return round(ntl * (exit_price / entry - 1.0), 2)


# ------------------------------------------------------------------ venue
def http_json(url, tries=3):
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=HDR)
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            last = e
            if e.code in (429, 502, 503):
                time.sleep(1.5 * (i + 1))
                continue
            raise
        except Exception as e:      # timeouts, resets
            last = e
            time.sleep(1.0 * (i + 1))
    if last is None:
        raise RuntimeError(f"no attempt made for {url}")
    raise last


def norm(s):
    return "".join(ch for ch in str(s or "").upper() if ch.isalnum())


def fetch_market(cid, offline):
    if cid in CACHE:
        return CACHE[cid]
    if offline:
        return None
    try:
        m = http_json(f"https://clob.polymarket.com/markets/{cid}")
    except Exception as e:
        m = {"error": str(e)[:120]}
    toks = []
    for t in (m.get("tokens") or []):
        toks.append({"token_id": t.get("token_id"), "outcome": t.get("outcome"),
                     "winner": t.get("winner"), "price": t.get("price")})
    out = {"question": m.get("question"), "closed": m.get("closed"),
           "tokens": toks, "error": m.get("error")}
    CACHE[cid] = out
    return out


def fetch_price(token_id, ts_ms, offline, window_s=900):
    key = f"{token_id}|{int(ts_ms // 60000)}"
    if key in CACHE:
        return CACHE[key]
    if offline or not token_id:
        return None
    start = int(ts_ms / 1000) - window_s
    end = int(ts_ms / 1000) + window_s
    try:
        h = http_json(f"https://clob.polymarket.com/prices-history?market={token_id}"
                      f"&startTs={start}&endTs={end}&fidelity=1")
        pts = h.get("history", []) if isinstance(h, dict) else (h if isinstance(h, list) else [])
    except Exception:
        pts = []
    best = None
    for p in pts:
        if not isinstance(p, dict) or "t" not in p or "p" not in p:
            continue
        dt = abs(p["t"] * 1000 - ts_ms)
        if best is None or dt < best[1]:
            best = (p["p"], dt, p["t"])
    res = None if best is None else {"p": best[0], "delta_s": best[1] / 1000.0, "t": best[2]}
    CACHE[key] = res
    return res


def pick_token(market, label):
    """Which venue token is the one this leg holds? Returns (token, how)."""
    toks = market.get("tokens") or []
    if not toks:
        return None, "no_tokens"
    want = norm(label)
    for t in toks:
        if norm(t["outcome"]) == want:
            return t, "label_exact"
    if want in ("YES", "NO") and len(toks) == 2:
        return toks[0] if want == "YES" else toks[1], "yes_no_position"
    # prefix / containment (venue labels get truncated or re-cased)
    cands = [t for t in toks if want and (norm(t["outcome"]).startswith(want[:6])
                                          or want.startswith(norm(t["outcome"])[:6]))]
    if len(cands) == 1:
        return cands[0], "label_prefix"
    return None, "label_unmatched"


def other(toks, t):
    for x in toks:
        if x["token_id"] != t["token_id"]:
            return x
    return None


# ------------------------------------------------------------------ sections
def sec_population(rows):
    print("=" * 78)
    print("0. POPULATION -- before any estimator is chosen")
    print("=" * 78)
    live = [r for r in rows if not r["isDemo"]]
    fin = [r for r in live if r["status"] != "open"]
    opn = [r for r in live if r["status"] == "open"]
    print(f"  rows {len(rows):,}   non-demo finished {len(fin):,}   open {len(opn):,}"
          f"   demo rows excluded {len(rows) - len(live):,}")
    cls = {}
    for r in live:
        cls.setdefault(classify(r), []).append(r)
    for k in ("inverted", "consistent", "ambiguous", "no_fill"):
        g = cls.get(k, [])
        f = [r for r in g if r["status"] != "open"]
        print(f"  {k:<11} rows {len(g):>6}   finished {len(f):>6}   "
              f"open {len(g) - len(f):>3}   notional(fin) ${sum(r['simulatedPositionSize'] or 0 for r in f):>10,.0f}")
    inv = cls.get("inverted", [])
    fin_inv = [r for r in inv if r["status"] != "open"]
    st = {}
    for r in fin_inv:
        st[r["status"]] = st.get(r["status"], 0) + 1
    print(f"  inverted finished by status: {st}")
    pre = [r for r in fin_inv if (r["endTs"] or 0) <= _ms(FIX_EPOCH)]
    post = [r for r in fin_inv if (r["endTs"] or 0) > _ms(FIX_EPOCH)]
    print(f"  of those, EXIT booked BEFORE the write fix: {len(pre)}   after: {len(post)}")
    print("  (an exit booked before the fix carries the sibling's price in currentPrice too;")
    print("   an exit booked after it carries our own token's price -- the two need")
    print("   different exit handling in the same repair.)")
    demo_inv = [r for r in rows if r["isDemo"] and classify(r) == "inverted"]
    print(f"  demo rows in the class: {len(demo_inv)} (excluded from every figure below)")
    return cls, fin_inv


def sec_mechanism(fin_inv):
    print()
    print("=" * 78)
    print("1. MECHANISM -- the booked price is the SIBLING token's, at the venue")
    print("=" * 78)
    c = con()
    pos0 = pos1 = miss = 0
    for r in fin_inv:
        row = c.execute(
            "SELECT yesPrice, noPrice, collectedAt, rawMarketJson FROM MarketSnapshot"
            " WHERE marketId = ? AND isDemo = 0"
            " ORDER BY ABS(collectedAt - ?) LIMIT 1", (r["marketId"], r["openedTs"])
        ).fetchone()
        if not row:
            miss += 1
            continue
        if abs(row["yesPrice"] - r["entryPrice"]) <= MIRROR_TOL:
            pos0 += 1
        elif row["noPrice"] is not None and abs(row["noPrice"] - r["entryPrice"]) <= MIRROR_TOL:
            pos1 += 1
    print(f"  snapshot within reach at openedAt: {len(fin_inv) - miss}/{len(fin_inv)}")
    print(f"    booked price sits on the FIRST token (yesPrice) : {pos0}")
    print(f"    booked price sits on the SECOND token (noPrice) : {pos1}")
    print("  -> the write path read position 0 for a leg that holds the other token.")
    raw = c.execute("SELECT COUNT(*) n, SUM(CASE WHEN rawMarketJson = '{}' THEN 1 ELSE 0 END) e"
                    " FROM MarketSnapshot").fetchone()
    print(f"  MarketSnapshot rows {raw['n']:,}, of which rawMarketJson='{{}}': {raw['e']:,}")
    print("  -> there are NO token labels in the price store. Repricing by label from")
    print("     snapshots is not merely lossy, it is impossible; the venue must be asked.")


def sec_venue(fin_inv, offline, workers):
    print()
    print("=" * 78)
    print("2. THE THREE ESTIMATORS -- measured against the venue on every leg")
    print("=" * 78)
    cids = sorted({r["cid"] for r in fin_inv if r["cid"]})
    print(f"  distinct conditionIds in the class: {len(cids)}")
    with ThreadPoolExecutor(max_workers=workers) as ex:
        list(ex.map(lambda cid: fetch_market(cid, offline), cids))

    jobs = []
    for r in fin_inv:
        m = CACHE.get(r["cid"]) or {}
        t, how = pick_token(m, r["outcome"])
        r["_token"], r["_pick"] = t, how
        if t:
            jobs.append((t["token_id"], r["openedTs"]))
            if r["status"] == "closed" and r["closedTs"]:
                jobs.append((t["token_id"], r["closedTs"]))
    with ThreadPoolExecutor(max_workers=workers) as ex:
        list(ex.map(lambda j: fetch_price(j[0], j[1], offline), jobs))

    ag = {"exact": 0, "near": 0, "far": 0}
    wrong_pick = 0
    rows_out = []
    for r in fin_inv:
        t = r["_token"]
        v = fetch_price(t["token_id"], r["openedTs"], offline) if t else None
        r["v_entry"] = v["p"] if v else None
        r["v_delta_s"] = v["delta_s"] if v else None
        # self-check the token pick: the OWN token should track the wallet's fill,
        # and the SIBLING should track the booked price. If it is the other way
        # round, we picked the wrong token and the number is worthless.
        m = CACHE.get(r["cid"]) or {}
        sib = other(m.get("tokens") or [], t) if t else None
        r["v_sibling"] = None
        if sib:
            sv = fetch_price(sib["token_id"], r["openedTs"], offline)
            r["v_sibling"] = sv["p"] if sv else None
        if r["v_entry"] is not None and r["v_sibling"] is not None:
            if abs(r["v_entry"] - r["w"]) + 0.02 < abs(r["v_sibling"] - r["w"]):
                pass
            else:
                wrong_pick += 1
                r["v_entry"] = None      # refuse: the pick contradicts the fill
        if r["v_entry"] is None:
            ag["far"] += 1
        else:
            d = abs(r["v_entry"] - r["w"])
            ag["exact" if d <= 0.02 else "near" if d <= 0.06 else "far"] += 1
    n = len(fin_inv)
    n_v = sum(1 for r in fin_inv if r.get("v_entry") is not None)
    corro = sum(1 for r in fin_inv if r.get("v_entry") is not None
                and abs(r["v_entry"] - r["w"]) <= MIRROR_TOL)
    flagged_ = sum(1 for r in fin_inv if r.get("v_entry") is not None
                   and abs(r["v_entry"] - (1 - r["entryPrice"])) > MIRROR_TOL)
    print(f"  venue read obtained: {n_v}/{n} rows ({n_v / n * 100:.0f}%); of those the venue")
    print(f"  corroborates the wallet's fill within 6c on {corro}  "
          f"(<=2c: {ag['exact']}, 2-6c: {ag['near']})")
    print(f"  no venue read: {n - n_v}   venue contradicts the complement identity by >6c "
          f"(needs_review): {flagged_}")
    print(f"  token picks rejected by the fill cross-check: {wrong_pick}")

    # estimator agreement
    pairs = [(r["v_entry"], r["w"], 1.0 - r["entryPrice"]) for r in fin_inv if r["v_entry"] is not None]
    if pairs:
        def mad(i, j):
            d = sorted(abs(p[i] - p[j]) for p in pairs)
            return d[len(d) // 2]
        print(f"  median |V-W| {mad(0,1):.4f}   |V-C| {mad(0,2):.4f}   |W-C| {mad(1,2):.4f}")
    return fin_inv


def ledger(legs, entry_of, exit_of, label):
    fin = [l for l in legs if l["status"] != "open"]
    tot = 0.0
    ntl = 0.0
    lane = {}
    for l in fin:
        p = true_pnl(l, entry_of(l), exit_of(l))
        tot += p or 0.0
        ntl += l["simulatedPositionSize"] or 0.0
        g = lane.setdefault(l["botId"], [0.0, 0.0, 0])
        g[0] += p or 0.0
        g[1] += l["simulatedPositionSize"] or 0.0
        g[2] += 1
    return {"label": label, "pnl": tot, "ntl": ntl, "lane": lane, "n": len(fin)}


def sec_ledger(cls, fin_inv):
    print()
    print("=" * 78)
    print("3. THE LEDGER UNDER EACH ESTIMATOR (deduped first leg, instrument basis)")
    print("=" * 78)
    live = [r for r in sum(cls.values(), [])]
    fin_all = dedupe([r for r in live if r["status"] != "open"])
    book_b = sum(l["realizedPnl"] or 0 for l in fin_all)
    book_n = sum(l["simulatedPositionSize"] for l in fin_all)
    print(f"  book: n={len(fin_all):,} ntl=${book_n:,.0f} booked {book_b:+,.2f} "
          f"({book_b / book_n * 100:+.1f}%)")

    def booked(l):
        return l["realizedPnl"] or 0.0

    # exit price per leg, under each convention
    def exit_booked(l):
        return None                      # reconstructed from booked pnl (instrument)

    def exit_own(l):
        return repair_exit(l)

    def exit_sibling_left(l):
        """Entry repaired, exit left as the sibling mark -- the card's literal CHANGE."""
        if classify(l) != "inverted" or l["status"] == "resolved":
            return l["currentPrice"]
        return l["currentPrice"]

    def e_booked(l):
        return l["entryPrice"]

    def e_complement(l):
        return 1.0 - l["entryPrice"] if classify(l) == "inverted" else l["entryPrice"]

    def e_wallet(l):
        return l["w"] if classify(l) == "inverted" else l["entryPrice"]

    def e_venue(l):
        """Venue price when it CORROBORATES the complement; the complement otherwise.

        The complement 1-b is the arithmetic identity and reproduces the venue's
        own price to a median of 0.0000 across the class. Where the two disagree by
        more than a spread, one of them is a stale/thin print and we cannot tell
        which from here -- so the repair stays on the identity and the row is
        flagged for manual review rather than taking a 40c swing on a guess.
        """
        return repair_entry(l)

    inv_fin = [l for l in fin_all if classify(l) == "inverted"]

    def class_pnl(ef, xf):
        return sum(true_pnl(l, ef(l), xf(l)) or 0.0 for l in inv_fin)

    def book_pnl(ef, xf):
        tot = 0.0
        for l in fin_all:
            if classify(l) == "inverted":
                tot += true_pnl(l, ef(l), xf(l)) or 0.0
            else:
                tot += l["realizedPnl"] or 0.0
        return tot

    print(f"  inverted finished deduped legs: {len(inv_fin)}  "
          f"notional ${sum(l['simulatedPositionSize'] for l in inv_fin):,.0f}")
    print(f"  {'estimator':<34} {'class pnl':>11} {'book pnl':>11} {'book ROI':>9}")
    variants = [("booked (as printed)", e_booked, exit_booked)]
    for nm, ef in (("C: entry 1-b, exit untouched", e_complement),
                   ("W: entry wallet fill, exit untouched", e_wallet),
                   ("V: entry venue, exit untouched", e_venue)):
        variants.append((nm, ef, exit_sibling_left))
    for nm, ef in (("C+exit: entry 1-b, exit 1-cp", e_complement),
                   ("W+exit: entry fill, exit 1-cp", e_wallet),
                   ("V+exit: entry venue, exit venue", e_venue)):
        variants.append((nm, ef, exit_own))
    out = {}
    for name, ef, xf in variants:
        if xf is exit_booked:
            cp, bp = sum(l["realizedPnl"] or 0 for l in inv_fin), book_b
        else:
            cp, bp = class_pnl(ef, xf), book_pnl(ef, xf)
        out[name] = {"class": cp, "book": bp, "roi": bp / book_n * 100}
        print(f"  {name:<34} {cp:>+11,.2f} {bp:>+11,.2f} {bp / book_n * 100:>+8.1f}%")

    diffs = sorted(abs((l["v_entry"] if l.get("v_entry") else (1 - l["entryPrice"]))
                       - (1 - l["entryPrice"])) for l in inv_fin)
    if diffs:
        print(f"  |V_entry - (1-b)| on finished deduped: median {diffs[len(diffs)//2]:.4f}  "
              f"p90 {diffs[int(0.9 * len(diffs))]:.4f}  max {diffs[-1]:.4f}")

    # Does the early-close mark really hold the sibling's price? Asked of the venue,
    # not of the code's git history.
    early = [l for l in inv_fin if l["status"] == "closed"]
    print()
    print(f"  THE EXIT QUESTION -- {len(early)} early-closed legs in the class")
    if early:
        sib_side = own_side = unknown = 0
        pre_fix_closes = sum(1 for l in early if (l["endTs"] or 0) <= _ms(FIX_EPOCH))
        print(f"    closes booked before the write fix: {pre_fix_closes}/{len(early)}")
        for l in early:
            t = l.get("_token")
            v = fetch_price(t["token_id"], l["closedTs"], OFFLINE) if (t and l.get("closedTs")) else None
            cp = l["currentPrice"]
            if not v or cp is None:
                unknown += 1
                continue
            # v is OUR token's venue price at the close minute.
            #   cp == our price      -> |v - cp| small          (no repair needed)
            #   cp == sibling price  -> |v - (1 - cp)| small     (the exit needs repair)
            d_cp_is_own = abs(v["p"] - cp)
            d_cp_is_sib = abs(v["p"] - (1.0 - cp))
            if min(d_cp_is_own, d_cp_is_sib) > 0.06:
                unknown += 1
            elif d_cp_is_sib < d_cp_is_own:
                sib_side += 1
            else:
                own_side += 1
        print(f"    currentPrice matches the SIBLING's price at close: {sib_side}")
        print(f"    currentPrice matches OUR token's price at close   : {own_side}")
        print(f"    no venue read at the close minute to decide       : {unknown}")
        print(f"    -> {'the exit must be complemented' if sib_side > own_side else 'the exit is already our own price'}"
              f" on the evidence ({sib_side} vs {own_side})")
        print(f"       ({pre_fix_closes}/{len(early)} of these closes were booked before the write fix,"
              f" so the positional read that produced the entry produced that mark too)")
        a = class_pnl(e_complement, exit_own)
        b = class_pnl(e_complement, exit_sibling_left)
        print(f"    class pnl with the exit repaired {a:+,.2f} vs left alone {b:+,.2f} "
              f"(the exit column is worth {a - b:+,.2f})")
    else:
        print("    none -- every leg in the class resolved, so the repair is entry-only.")
    return out, fin_all, variants


def sec_gate(fin_all, variants):
    print()
    print("=" * 78)
    print("4. THE C-200 LADDER GATE (trailing 7 local days, dashboard basis)")
    print("=" * 78)
    now = time.time() * 1000
    cut = now - 7 * 86400 * 1000
    c2 = [l for l in fin_all if l["botId"] == "BANKROLL_200" and l["endTs"] and l["endTs"] >= cut]
    inv_c2 = [l for l in c2 if classify(l) == "inverted"]
    print(f"  legs in window {len(c2)} (of which inverted {len(inv_c2)})   "
          f"rung 1 = $250/day x 7 = $1,750")
    for name, ef, xf in variants:
        if name.startswith("booked"):
            tot = sum(l["realizedPnl"] or 0 for l in c2)
        else:
            tot = sum((true_pnl(l, ef(l), xf(l)) or 0.0) if classify(l) == "inverted"
                      else (l["realizedPnl"] or 0.0) for l in c2)
        print(f"  {name:<34} {tot:>+10,.2f}  -> {'PASS' if tot >= 1750 else 'fail'}")
    return c2, inv_c2


def sec_downstream(fin_inv, fin_all, variants):
    print()
    print("=" * 78)
    print("5. DOWNSTREAM STORES -- what a rebuild would actually change")
    print("=" * 78)
    c = con()
    by_bot = {}
    for l in fin_all:
        g = by_bot.setdefault(l["botId"], [0.0, 0])
        g[0] += l["realizedPnl"] or 0.0
        g[1] += 1
    print("  BotBankroll vs the rows that feed it:")
    print(f"    {'bot':<13} {'rows n':>7} {'sum(realizedPnl)':>18} {'BotBankroll.realizedPnl':>24}")
    for bot, pnl in c.execute("SELECT botId, realizedPnl FROM BotBankroll").fetchall():
        s, n = by_bot.get(bot, (0.0, 0))
        print(f"    {bot:<13} {n:>7} {s:>+18,.2f} {pnl:>+24,.2f}")
    print("  -> a FULL rebuild from rows would move STANDARD by the gap above, which is")
    print("     not a price-side effect. The repair must post a DELTA, not a rebuild.")
    chosen = "V+exit: entry venue, exit venue"
    fix = 0.0
    for name, f_e, f_x in variants:
        if name != chosen:
            continue
        for l in fin_inv:
            fix += (true_pnl(l, f_e(l), f_x(l)) or 0.0) - (l["realizedPnl"] or 0.0)
    print(f"    the price-side delta on the ROW class ({len(fin_inv)} rows, undeduped): {fix:+,.2f}")
    for bot in sorted({l["botId"] for l in fin_inv}):
        d = 0.0
        for name, f_e, f_x in variants:
            if name != chosen:
                continue
            for l in fin_inv:
                if l["botId"] == bot:
                    d += (true_pnl(l, f_e(l), f_x(l)) or 0.0) - (l["realizedPnl"] or 0.0)
        print(f"    {bot:<13} delta {d:+,.2f}"
              f"{'  (STANDARD skips BotBankroll by design -- no bankroll posting)' if bot == 'STANDARD' else ''}")
    n_snap = c.execute("SELECT COUNT(*) n FROM PnlSnapshot").fetchone()["n"]
    print(f"  PnlSnapshot rows: {n_snap:,}; the dashboard reads the LAST row per trade")
    print(f"  (src/app/paper-trades/page.tsx: orderBy collectedAt desc, take 1), so an")
    print(f"  APPENDED corrected row per repaired leg is what the reader picks up; no")
    print(f"  history is destroyed and the append is trivially reversible by id.")
    days = c.execute("SELECT COUNT(*) n FROM DailyReport").fetchone()["n"]
    print(f"  DailyReport rows: {days} (immutable daily statements; a repaired ledger")
    print(f"  makes past statements stale -- the proposal keeps them and states the")
    print(f"  break, rather than rewriting published reports).")


def sec_manifest(fin_inv, path):
    print()
    print("=" * 78)
    print("6. MANIFEST -- the pre-image the repair must dump before it writes")
    print("=" * 78)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    n = 0
    flagged = 0
    f = open(path, "w")
    for l in sorted(fin_inv, key=lambda x: x["openedTs"]):
        c_ = 1.0 - l["entryPrice"]
        v_ = l.get("v_entry")
        post_entry = repair_entry(l)
        if v_ is not None and abs(v_ - c_) > MIRROR_TOL:
            flagged += 1
        post_exit = repair_exit(l)
        rec = {
            "paperTradeId": l["id"], "botId": l["botId"], "status": l["status"],
            "walletAddress": l["walletAddress"],
            "marketId": l["marketId"], "outcome": l["outcome"],
            "conditionId": l["cid"], "openedAt": l["openedAt"],
            "pre": {"entryPrice": l["entryPrice"], "currentPrice": l["currentPrice"],
                    "realizedPnl": l["realizedPnl"],
                    "simulatedPositionSize": l["simulatedPositionSize"],
                    "fillStatus": l["fillStatus"]},
            "evidence": {"walletEntryPrice": l["w"], "venueEntry": v_,
                         "venueDeltaS": l.get("v_delta_s"), "tokenPick": l.get("_pick"),
                         "venueSibling": l.get("v_sibling"),
                         "complement": round(c_, 5),
                         "needs_review": bool(v_ is not None and abs(v_ - c_) > MIRROR_TOL)},
            "post": {"entryPrice": post_entry, "exitPrice": post_exit,
                     "realizedPnl": true_pnl(l, post_entry, post_exit)},
        }
        f.write(json.dumps(rec, sort_keys=True) + "\n")
        n += 1
    f.close()
    print(f"  wrote {n} pre/post image records -> {path}")
    print(f"  rows flagged needs_review (venue and complement disagree by >6c): {flagged}")
    print(f"  every record carries the full pre-image, so rollback is a re-INSERT of")
    print(f"  the `pre` block by paperTradeId; nothing has to be recomputed from history.")


def self_test():
    print()
    print("=" * 78)
    print("7. SELF-TESTS")
    print("=" * 78)
    ok = 0
    tot = 0
    # a favourite bought at 0.80 is booked at 0.20; won at 1.0, $10 at risk
    fake = {"status": "resolved", "entryPrice": 0.20, "simulatedPositionSize": 10.0,
            "realizedPnl": 40.0, "fillStatus": "filled"}
    tot += 1
    if abs(true_pnl(fake, 0.80) - 2.50) < 0.01:
        ok += 1
    print(f"  synthetic: $10 at risk, booked 0.20 (won at 1.0, printed +40.00) repriced to 0.80"
          f" -> {true_pnl(fake, 0.80):+.2f} (expect +2.50)")
    # loss side: same favourite loses -> -10.00 at any entry (all-stake loss)
    fake2 = dict(fake, realizedPnl=-10.0)
    tot += 1
    if abs(true_pnl(fake2, 0.80) + 10.0) < 0.01:
        ok += 1
    print(f"  synthetic: same leg losing (printed -10.00) -> {true_pnl(fake2, 0.80):+.2f} (expect -10.00)")
    # early exit complement: booked at 0.20, exit 0.30, won't hold at own 0.80/0.70
    fake3 = {"status": "closed", "entryPrice": 0.20, "simulatedPositionSize": 10.0,
             "realizedPnl": 5.0, "fillStatus": "filled"}
    tot += 1
    got = true_pnl(fake3, 0.80, 0.70)
    if abs(got + 1.25) < 0.01:
        ok += 1
    print(f"  synthetic: early close booked 0.20->0.30 (+5.00) is really 0.80->0.70 -> {got:+.2f}"
          f" (expect -1.25; the sibling's exit over-corrects to "
          f"{true_pnl(fake3, 0.80, 0.30):+.2f})")
    # unfilled legs must stay booked at zero
    tot += 1
    fake4 = {"status": "resolved", "entryPrice": 0.11, "simulatedPositionSize": 100.0,
             "realizedPnl": 0.0, "fillStatus": "unfilled"}
    if true_pnl(fake4, 0.88) == 0.0:
        ok += 1
    print(f"  unfilled leg stays at 0.00 after repricing -> {true_pnl(fake4, 0.88):+.2f}")
    print("  SELF-TEST PASS" if ok == tot else f"  SELF-TEST FAIL ({ok}/{tot})")
    return ok == tot


def main():
    global OFFLINE
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", default="data/repair-manifests/ledger-price-side.jsonl")
    ap.add_argument("--cache", default="data/repair-manifests/venue-cache.json")
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--workers", type=int, default=8)
    a = ap.parse_args()
    OFFLINE = a.offline
    if os.path.exists(a.cache):
        try:
            CACHE.update(json.load(open(a.cache)))
        except Exception:
            pass
    rows = load()
    cls, fin_inv = sec_population(rows)
    sec_mechanism(fin_inv)
    fin_inv = sec_venue(fin_inv, OFFLINE, a.workers)
    out, fin_all, variants = sec_ledger(cls, fin_inv)
    sec_gate(fin_all, variants)
    sec_downstream(fin_inv, fin_all, variants)
    sec_manifest(fin_inv, a.manifest)
    self_test()
    os.makedirs(os.path.dirname(a.cache) or ".", exist_ok=True)
    json.dump(CACHE, open(a.cache, "w"))


if __name__ == "__main__":
    main()
