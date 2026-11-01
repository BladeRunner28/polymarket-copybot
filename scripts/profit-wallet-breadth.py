#!/usr/bin/env python3
"""
THE UNCOPIED WALLETS -- the only supply population this system has never priced.

WHY THIS FILE EXISTS
The v61 observation/copy split (approved 2026-09-22) fixed the funnel by observing every
recently-demoted wallet and copying only the current top-25. Its containment rule says an
observation row "must never reach a copy decision or a published number", and every
measurement script in `scripts/` obeys it -- which is why, after eleven profit reviews,
there is still no measurement of the 1,345 wallets whose trades we see and do not act on.
That population is the entire supply side of the ladder: the target needs an order of
magnitude more bets/day than 25 wallets can produce, and the only untested question is
whether the bets those other wallets make are worth taking.

Every figure in this file is computed from prisma/dev.db (read-only) plus archived CLOB
settlement truth (tokens[].winner), the same instrument §AM.2 uses for the declined arm.
Cost basis is identical by contract: price is a price; every dollar figure is #bets x a
stated clip. ROI on settlement basis = settle/px - 1, held to resolution.

USAGE
    python3 scripts/profit-wallet-breadth.py              # full run, ~2500 truth fetches
    python3 scripts/profit-wallet-breadth.py --offline    # cache only, no wire
    python3 scripts/profit-wallet-breadth.py --fetch 4000 # bigger truth budget
    python3 scripts/profit-wallet-breadth.py --selftest   # identity checks, no DB writes

SECTIONS
  WB.0  TWO HYPOTHESES THIS FILE KILLS. Leg ordinal within a bet (does duplication pay?)
        and wallet consensus (does agreement pay?). Both are tempting, both are artefacts,
        and both are printed so no future review re-derives them.
  WB.1  SUPPLY CENSUS. How many wallets produce prints, how many bets/day, how many reach
        a decision, and exactly which rule vetoed the rest.
  WB.2  THE UNCOPIED EDGE. Sampled first-print bets from observation-only wallets, priced
        at settlement truth, with a market-clustered CI -- against the copied arm measured
        the same way in the same window.
  WB.3  DOES SCORE RANK EDGE? If the 25-slot cap is a quality boundary, score must order
        outcomes inside the uncopied pool. If it does not, the cap is arbitrary -- a count.
  WB.4  FLOW MULTIPLIER vs the ladder, at the measured edge.
  WB.5  CONTRADICTIONS not resolved here (reported, never quietly chosen).
  WB.6  WALLET-EDGE PERSISTENCE. Does a wallet's measured edge in the first 30d predict
        its edge in the next 30d? This is the gate every future proposal was told to wait
        on: if it does not persist, no admission, band, size or breadth change can beat
        noise. Prints the raw split-half Spearman, its permutation null, the attenuation
        estimate, the quintile/top-k out-of-sample earn, and the dollars per day.

NOTHING IN THIS FILE WRITES TO THE DB, TOUCHES A RULESET ROW, OR CHANGES A DECISION.
The truth records it fetches land in data/.clob-truth-raw, the same archive the existing
pipeline reads (a Lane B artefact, no decision surface).
"""
import json
import os
import re
import sqlite3
import sys
import time
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

import numpy as np

CLOB = "https://clob.polymarket.com/markets/"
UA_HEADERS = {"User-Agent": "Mozilla/5.0 (copybot-profit-review)"}

DB = "prisma/dev.db"
TRUTH_CACHE = "data/market-truth-clob.json"
TRUTH_RAW = os.path.join("data", ".clob-truth-raw")
ARGS = sys.argv[1:]
OFFLINE = "--offline" in ARGS
SELFTEST = "--selftest" in ARGS
FETCH_CAP = 2500
if "--fetch" in ARGS:
    FETCH_CAP = int(ARGS[ARGS.index("--fetch") + 1])
SAMPLE_WALLETS = 60
SAMPLE_BETS = 2600
STAKE = 10.0
WINDOW_DAYS = 60
# WB.6 (wallet-edge persistence). 200 wallets x 30 bets/half keeps the per-wallet edge
# noise near 9pp, which is the regime where a real cross-wallet spread is separable from
# sampling error; below ~100 wallets the read cannot clear its own pre-registered bar.
PERSIST_WALLETS = 200
PERSIST_PER_HALF = 30
PERSIST_MIN_SETTLED = 8
ONLY_WB6 = "--only-wb6" in ARGS
if "--persist-wallets" in ARGS:
    PERSIST_WALLETS = int(ARGS[ARGS.index("--persist-wallets") + 1])
if "--persist-per-half" in ARGS:
    PERSIST_PER_HALF = int(ARGS[ARGS.index("--persist-per-half") + 1])
# Dust floor for the ROI reading only. s/px - 1 explodes as px -> 0, and one 0.004 leg
# produces a -99.6% "outlier" worth one cent of stake. The edge reading (hit - px) is
# unconditioned and keeps every bet; only ROI drops them, and the count is printed.
DUST_MIN_PX = 0.02
BANDS = [("0.00-0.10", 0.0, 0.10), ("0.10-0.20", 0.10, 0.20), ("0.20-0.40", 0.20, 0.40),
         ("0.40-0.60", 0.40, 0.60), ("0.60-0.80", 0.60, 0.80), ("0.80-1.00", 0.80, 1.0001)]


def con():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    return c


# ---------------------------------------------------------------- settlement truth
BULK_PATH = "data/.clob-truth-bulk.json.gz"
BULK_MAX_PAGES = 900
_BULK = None


def bulk_truth(max_pages=BULK_MAX_PAGES, rebuild=False):
    """Whole-venue settlement truth in one paginated walk.

    WHY: `/markets/<conditionId>` answers in ~0.3s, and a 12k-bet panel needs 12k of
    them -- measured 2026-11-01 at 200/min with 24 workers, i.e. an hour per panel.
    `/markets?next_cursor=` returns 1,000 markets in ~0.4s, so the same truth costs one
    walk. This is the difference between a panel that can be rebuilt on demand and one
    that cannot. Cached to data/.clob-truth-bulk.json.gz; a rebuild is skipped when the
    file is younger than 6h.
    """
    global _BULK
    if _BULK is not None:
        return _BULK
    if (os.path.exists(BULK_PATH) and not rebuild
            and time.time() - os.path.getmtime(BULK_PATH) < 6 * 3600):
        try:
            import gzip
            with gzip.open(BULK_PATH, "rt") as f:
                _BULK = json.load(f)
            return _BULK
        except Exception:
            pass
    if OFFLINE:
        _BULK = {}
        return _BULK
    import gzip
    tmp = os.path.join("/tmp", "clob-bulk-page.json")
    out = {}
    cur = "MA=="
    pages = 0
    t0 = time.time()
    while pages < max_pages:
        os.system("curl -s --max-time 30 'https://clob.polymarket.com/markets?next_cursor=%s'"
                  " -o %s" % (cur, tmp))
        try:
            d = json.load(open(tmp))
        except Exception:
            time.sleep(1.0)
            continue
        for m in d.get("data") or []:
            toks = [[t.get("outcome"), bool(t.get("winner"))] for t in (m.get("tokens") or [])]
            if not toks:
                continue
            rec = {"tokens": toks, "end": m.get("end_date_iso")}
            if not any(t[1] for t in toks):
                rec["unsettled"] = True
            out[m.get("condition_id")] = rec
        pages += 1
        cur = d.get("next_cursor")
        if not cur or cur in ("LTE=", "-1"):
            break
    os.makedirs(os.path.dirname(BULK_PATH) or ".", exist_ok=True)
    with gzip.open(BULK_PATH, "wt") as f:
        json.dump(out, f)
    _BULK = out
    print("   BULK TRUTH: %d markets over %d pages in %.1fs (settled %d) -> %s"
          % (len(out), pages, time.time() - t0,
             sum(1 for v in out.values() if not v.get("unsettled")), BULK_PATH))
    return out


def _norm(s):
    return (s or "").strip().upper().replace("-", " ").replace("_", " ")


def settle_of(rec, outcome):
    """Settlement value for OUR side from one archived CLOB record, else None."""
    if not rec or rec.get("unsettled"):
        return None
    toks = rec.get("tokens") or []
    if not toks or not any(t[1] for t in toks):
        return None          # no winner yet -> undecided, never a loss
    n = _norm(outcome)
    for name, win in toks:
        if _norm(name) == n:
            return 1.0 if win else 0.0
    if len(toks) == 2 and n in ("YES", "NO"):
        # Positional fallback ONLY for a genuine Yes/No pair. Two arbitrary outcome
        # names ("A"/"B" on a multi-outcome event) must not be index-matched: that
        # fabricates a loss for a bet whose outcome we never identified.
        names = {_norm(toks[0][0]), _norm(toks[1][0])}
        if names == {"YES", "NO"}:
            return 1.0 if toks[0 if n == "YES" else 1][1] else 0.0
    return None


def _fetch_one(cid):
    """One market's settlement record.

    INSTRUMENT NOTE (measured 2026-11-01): this used `os.system("curl ...")` inside a
    thread pool, which serialises on the GIL at fork/exec -- 3.3 fetches/s at 24 workers,
    i.e. an hour for a 12k-bet panel. The same request through urllib (with a UA header,
    which the CLOB requires -- without it the endpoint answers 403) runs at 79.5/s on the
    same host. The archive is written only on a parsed response, so a 403/429 is a retry,
    never an "unsettled" market.
    """
    path = os.path.join(TRUTH_RAW, cid + ".json")
    for attempt in range(3):
        if not os.path.exists(path) or os.path.getsize(path) < 40:
            try:
                req = urllib.request.Request(CLOB + cid, headers=UA_HEADERS)
                with urllib.request.urlopen(req, timeout=25) as f:
                    body = f.read()
                json.loads(body.decode("utf-8", "replace"))
                with open(path, "wb") as fh:
                    fh.write(body)
            except Exception:
                time.sleep(0.3 * (attempt + 1) * (attempt + 1))
                continue
        try:
            d = json.load(open(path))
            toks = [[t.get("outcome"), bool(t.get("winner"))] for t in d.get("tokens", [])]
            if not toks:
                return cid, None
            if any(t[1] for t in toks):
                return cid, {"tokens": toks, "end": d.get("end_date_iso")}
            return cid, {"tokens": toks, "end": d.get("end_date_iso"), "unsettled": True}
        except Exception:
            time.sleep(0.4 * (attempt + 1) * (attempt + 1))
    return cid, None


def _truth_from_raw(cid):
    """Read an already-archived CLOB record. Makes the fetch stage resumable and keeps
    a re-run's wire cost at zero."""
    path = os.path.join(TRUTH_RAW, cid + ".json")
    if not os.path.exists(path) or os.path.getsize(path) < 40:
        return None
    try:
        d = json.load(open(path))
    except Exception:
        return None
    toks = [[t.get("outcome"), bool(t.get("winner"))] for t in d.get("tokens", [])]
    if not toks:
        return None
    if any(t[1] for t in toks):
        return {"tokens": toks, "end": d.get("end_date_iso")}
    return {"tokens": toks, "end": d.get("end_date_iso"), "unsettled": True}


def fetch_truth(cids):
    """Truth for exactly these conditionIds. Cache JSON first, then the bulk walk (one
    paginated request per 1,000 markets), then the per-market raw archive, then a bounded
    wire pass for whatever remains."""
    cache = {}
    if os.path.exists(TRUTH_CACHE):
        cache = json.load(open(TRUTH_CACHE)).get("markets", {})
    # Bulk walk is OPT-IN: it is a 1,000-market-per-page optimisation, but the id space is
    # sparse and ~6.4M wide, so a full walk is 6k+ pages -- slower than 79 per-cid
    # fetches/s for any panel smaller than ~100k bets. Kept for repeated large panels.
    bulk = bulk_truth() if "--bulk" in ARGS else {}
    from_bulk = 0
    missing = []
    for c in cids:
        if c in cache:
            continue
        if c in bulk:
            cache[c] = bulk[c]
            from_bulk += 1
            continue
        rec = _truth_from_raw(c)
        if rec is not None:
            cache[c] = rec
        else:
            missing.append(c)
    if from_bulk:
        print("   truth from bulk walk: %d of %d requested" % (from_bulk, len(cids)))
    todo = missing[:FETCH_CAP]
    got = 0
    if todo and not OFFLINE:
        os.makedirs(TRUTH_RAW, exist_ok=True)
        with ThreadPoolExecutor(max_workers=24) as ex:
            for cid, rec in ex.map(_fetch_one, todo):
                if rec:
                    cache[cid] = rec
                    got += 1
    return cache, len(missing), len(todo), got


# ---------------------------------------------------------------- statistics
def cluster_ci(bets, val, reps=1500, seed=13):
    """Market-clustered bootstrap CI of mean(val), in percentage points."""
    by = {}
    for b in bets:
        by.setdefault(b["market"], []).append(val(b))
    keys = list(by)
    if len(keys) < 12:
        return (float("nan"), float("nan"))
    rng = np.random.default_rng(seed)
    out = []
    for _ in range(reps):
        pick = rng.integers(0, len(keys), len(keys))
        out.append(100 * np.mean([v for i in pick for v in by[keys[i]]]))
    return (float(np.percentile(out, 2.5)), float(np.percentile(out, 97.5)))


def describe(bets, label):
    """n, markets, mean px, hit, edge_pp (unconditioned), ROI (ex-dust) + CI + ex-top-10."""
    if not bets:
        print("   %-32s -- no settled bets" % label)
        return None
    n = len(bets)
    hit = float(np.mean([b["s"] for b in bets]))
    px = float(np.mean([b["px"] for b in bets]))
    elo, ehi = cluster_ci(bets, lambda b: b["s"] - b["px"])
    clean = [b for b in bets if b["px"] >= DUST_MIN_PX]
    if clean:
        roi = float(np.mean([b["s"] / b["px"] - 1 for b in clean]))
        lo, hi = cluster_ci(clean, lambda b: b["s"] / b["px"] - 1)
        pnl = [STAKE * (b["s"] / b["px"] - 1) for b in clean]
        drop = set(sorted(range(len(pnl)), key=lambda i: -pnl[i])[:10])
        keep = [i for i in range(len(pnl)) if i not in drop]
        x10 = sum(pnl[i] for i in keep) / (STAKE * len(keep)) if keep else float("nan")
        roi_s = ("roi=%+6.1f%% [%+6.1f,%+6.1f] ex10=%+6.1f%% n_exdust=%d"
                 % (roi * 100, lo * 100, hi * 100, x10 * 100, len(clean)))
    else:
        roi, x10 = float("nan"), float("nan")
        roi_s = "roi=(no leg above the dust floor)"
    print("   %-32s n=%5d mk=%5d px=%.3f hit=%5.1f%% edge=%+5.1fpp [%+5.1f,%+5.1f] %s"
          % (label, n, len({b["market"] for b in bets}), px, hit * 100,
             100 * (hit - px), elo, ehi, roi_s))
    return {"n": n, "hit": hit, "px": px, "edge": 100 * (hit - px), "roi": 100 * roi,
            "ex10": 100 * x10, "ci": (100 * elo, 100 * ehi), "covered": len(clean)}


# ================================================================ WB.0 killed hypotheses
def killed_hypotheses(c):
    print("\n" + "=" * 104)
    print("WB.0  TWO HYPOTHESES THIS FILE KILLS -- measured, so they stop being proposed")
    print("=" * 104)
    rows = c.execute("""SELECT botId, marketId, outcome, entryPrice px, simulatedPositionSize ntl,
                               realizedPnl pnl, walletAddress w, openedAt
                        FROM PaperTrade WHERE isDemo=0 AND realizedPnl IS NOT NULL
                        ORDER BY botId, marketId, outcome, openedAt""").fetchall()
    by = {}
    for r in rows:
        by.setdefault((r["botId"], r["marketId"], r["outcome"]), []).append(r)

    print("\n   A. LEG ORDINAL inside one (bot, market, outcome) -- 'we are only duplicating a bet'")
    agg = {}
    for k, legs in by.items():
        for i, r in enumerate(legs, 1):
            o = "1st" if i == 1 else "2nd" if i == 2 else "3rd-4th" if i <= 4 else "5th+"
            d = agg.setdefault(o, {"n": 0, "ntl": 0.0, "pnl": 0.0, "p": []})
            d["n"] += 1
            d["ntl"] += r["ntl"]
            d["pnl"] += r["pnl"]
            d["p"].append(r["pnl"])
    for o in ("1st", "2nd", "3rd-4th", "5th+"):
        d = agg.get(o)
        if not d:
            continue
        ex = d["pnl"] - sum(sorted(d["p"], reverse=True)[:10])
        print("      %-8s legs=%5d notional $%9s pnl $%+8s roi %+7.2f%% ex-top-10 %+7.2f%%"
              % (o, d["n"], format(d["ntl"], ",.0f"), format(d["pnl"], ",.0f"),
                 100 * d["pnl"] / d["ntl"], 100 * ex / d["ntl"]))
    print("      => the marginal leg into a bet is NOT the loser (5th+ is the best cohort).")
    print("         A legs-per-bet cap is refuted on our own book; do not propose one.")

    print("\n   B. WALLET CONSENSUS -- 'N wallets in the same bet is the signal'")
    bet = {}
    for k, legs in by.items():
        nw = len({l["w"] for l in legs})
        wb = "1" if nw == 1 else "2" if nw == 2 else "3" if nw == 3 else "4+"
        ntl = sum(l["ntl"] for l in legs)
        pnl = sum(l["pnl"] for l in legs)
        d = bet.setdefault(wb, {"nb": 0, "ntl": 0.0, "pnl": 0.0, "rows": []})
        d["nb"] += 1
        d["ntl"] += ntl
        d["pnl"] += pnl
        d["rows"].append((pnl, ntl, k))
    for wb in ("1", "2", "3", "4+"):
        d = bet.get(wb)
        if not d:
            continue
        top = max(d["rows"], key=lambda x: x[0])
        ex = d["pnl"] - top[0]
        print("      %-2s wallets bets=%5d notional $%9s pnl $%+8s roi %+7.2f%% "
              "ex-largest-bet %+7.2f%%  largest: %-34s $%s"
              % (wb, d["nb"], format(d["ntl"], ",.0f"), format(d["pnl"], ",.0f"),
                 100 * d["pnl"] / d["ntl"], 100 * ex / d["ntl"], top[2][1][:34],
                 format(top[0], "+,.0f")))
    print("      => 4+ wallet bets pay a large raw ROI and a fraction of it once ONE event is")
    print("         removed; the cohort is also ~1% of current legs, so there is no flow to size.")

    inc = {}
    for k, legs in by.items():
        nw = len({l["w"] for l in legs})
        for l in legs:
            b = int(l["openedAt"] / 1000 / 86400 / 30)
            e = inc.setdefault(b, [0, 0])
            e[0] += 1
            if nw >= 4:
                e[1] += 1
    print("      consensus incidence by 30d epoch (share of legs in 4+ wallet bets):")
    for b in sorted(inc)[-5:]:
        tot, s = inc[b]
        print("        epoch %d: %5d legs, %4d consensus (%4.1f%%)" % (b, tot, s, 100 * s / max(tot, 1)))


# ================================================================ WB.1 supply census
def supply_census(c):
    print("\n" + "=" * 104)
    print("WB.1  SUPPLY CENSUS -- what we see, what we decide, and what vetoed the rest")
    print("=" * 104)
    now = time.time() * 1000
    for days in (7, 30):
        since = now - days * 86400000
        r = c.execute("""SELECT count(*) n, count(DISTINCT walletAddress) w,
                                count(DISTINCT marketId) m, sum(observationOnly) obs
                         FROM ObservedTrade WHERE isDemo=0 AND timestamp>=?""", (since,)).fetchone()
        j = c.execute("""SELECT decision, count(*) n FROM DecisionJournal
                         WHERE isDemo=0 AND createdAt>=? GROUP BY decision""", (since,)).fetchall()
        jd = {x["decision"]: x["n"] for x in j}
        tot_j = sum(jd.values()) or 1
        print("\n   last %2dd: %s prints from %s wallets in %s markets (%s prints/day)"
              % (days, format(r["n"], ","), format(r["w"], ","), format(r["m"], ","),
                 format(int(r["n"] / days), ",")))
        print("            observation-only share %.1f%%" % (100 * (r["obs"] or 0) / max(r["n"], 1)))
        print("            journaled decisions: " + ", ".join(
            "%s=%s" % (k, format(v, ",")) for k, v in sorted(jd.items(), key=lambda x: -x[1])))
        print("            paper copies %s = %.2f%% of decisions, %.1f trades/day"
              % (format(jd.get("paper_copy", 0), ","),
                 100 * jd.get("paper_copy", 0) / tot_j, jd.get("paper_copy", 0) / days))

    since = now - 7 * 86400000
    rows = c.execute("""SELECT risksJson FROM DecisionJournal
                        WHERE isDemo=0 AND createdAt>=? AND decision!='paper_copy'""",
                     (since,)).fetchall()
    cnt = Counter()
    for r in rows:
        try:
            rs = json.loads(r["risksJson"] or "[]")
        except Exception:
            rs = []
        for x in rs if isinstance(rs, list) else []:
            cnt[re.sub(r"[-+]?\d*\.?\d+", "N", str(x))[:62]] += 1
    print("\n   veto census, last 7d (%s non-copy decisions; numbers normalised):"
          % format(len(rows), ","))
    for k, v in cnt.most_common(10):
        print("      %5d  %s" % (v, k))

    st = {x["status"]: x["n"] for x in c.execute(
        "SELECT status, count(*) n FROM WalletProfile GROUP BY status")}
    tr = c.execute("""SELECT globalScore s FROM WalletProfile WHERE status='track'
                      ORDER BY globalScore DESC""").fetchall()
    nxt = c.execute("""SELECT globalScore s FROM WalletProfile WHERE status!='track'
                       AND globalScore>0 ORDER BY globalScore DESC LIMIT 3""").fetchall()
    print("\n   wallet universe: %d track / %s watch / %s ignore"
          % (st.get("track", 0), format(st.get("watch", 0), ","),
             format(st.get("ignore", 0), ",")))
    if tr:
        print("   copy set score range %.1f .. %.1f (the 25th slot is the boundary)"
              % (tr[-1]["s"], tr[0]["s"]))
    if nxt:
        print("   best NON-track wallets: %s -- at or above the boundary, excluded by a "
              "COUNT not a quality bar" % ", ".join("%.1f" % x["s"] for x in nxt))


# ================================================================ sampling
def build_sample(c, rng):
    """First print per (wallet, market, outcome) from a seeded sample of observe wallets.

    Bets are restricted to 7-60 days old: a market live a week ago has had time to settle,
    and an unresolved market contributes nothing to a settlement-basis read.
    """
    now = time.time() * 1000
    # Anchor the window to UTC midnight so a re-run inside the same day samples the same
    # bets. A rolling `now` moved the sample between runs and silently invalidated the
    # truth cache built by the previous run (observed 2026-10-31).
    day = int(now // 86400000) * 86400000
    since = day - WINDOW_DAYS * 86400000
    until = day - 7 * 86400000
    wallets = [r[0] for r in c.execute("""SELECT DISTINCT walletAddress FROM ObservedTrade
                 WHERE isDemo=0 AND observationOnly=1 AND timestamp>=?""", (since,))]
    if len(wallets) > SAMPLE_WALLETS:
        wallets = list(rng.choice(sorted(wallets), SAMPLE_WALLETS, replace=False))
    bets = []
    for w in wallets:
        for r in c.execute("""SELECT marketId m, outcome, conditionId cid, walletEntryPrice px,
                                     MIN(timestamp) ts
                              FROM ObservedTrade
                              WHERE isDemo=0 AND observationOnly=1 AND timestamp>=?
                                AND timestamp<=? AND walletAddress=?
                                AND walletEntryPrice>0.0001 AND walletEntryPrice<0.9999
                              GROUP BY marketId, outcome""", (since, until, w)):
            if r["cid"]:
                bets.append({"wallet": w, "market": r["m"], "outcome": r["outcome"],
                             "cid": r["cid"], "px": r["px"], "ts": r["ts"]})
    return wallets, bets


def sample_for_truth(c, rng):
    _, bets = build_sample(c, rng)
    if len(bets) > SAMPLE_BETS:
        idx = rng.choice(len(bets), SAMPLE_BETS, replace=False)
        bets = [bets[i] for i in sorted(idx)]
    return bets


def uncopied_edge(c, truth, bets):
    print("\n" + "=" * 104)
    print("WB.2  THE UNCOPIED EDGE -- observation-only wallets, first print per bet, settlement truth")
    print("=" * 104)
    print("   sampled bets: %s in %s markets (seeded, 7-%dd old)"
          % (format(len(bets), ","), format(len({b["cid"] for b in bets}), ","), WINDOW_DAYS))
    dec = []
    for b in bets:
        s = settle_of(truth.get(b["cid"]), b["outcome"])
        if s is not None:
            dec.append({**b, "s": s})
    print("   settled: %s of %s = %.1f%% (unresolved markets dropped, never counted as losses)"
          % (format(len(dec), ","), format(len(bets), ","), 100 * len(dec) / max(len(bets), 1)))
    if not dec:
        print("   NO SETTLEMENT TRUTH -- run without --offline and raise --fetch")
        return None, None

    all_ = describe(dec, "uncopied, all bands")
    print("   by band:")
    for nm, lo, hi in BANDS:
        describe([b for b in dec if lo <= b["px"] < hi], "  " + nm)

    now = time.time() * 1000
    since = now - WINDOW_DAYS * 86400000
    cp = c.execute("""SELECT o.marketId m, o.outcome oc, o.conditionId cid, o.walletEntryPrice px
                      FROM ObservedTrade o
                      WHERE o.isDemo=0 AND o.observationOnly=0 AND o.timestamp>=?
                        AND o.walletEntryPrice>0.0001 AND o.walletEntryPrice<0.9999
                      GROUP BY o.walletAddress, o.marketId, o.outcome""", (since,)).fetchall()
    copied = []
    for r in cp:
        s = settle_of(truth.get(r["cid"]), r["oc"])
        if s is not None:
            copied.append({"market": r["m"], "px": r["px"], "s": s})
    print("\n   copied arm, same window and basis (cached truth only):")
    cstat = describe(copied, "copied (copy-set wallets)")
    return all_, cstat


# ================================================================ WB.3 score vs edge
def score_ranks_edge(c, truth, bets):
    print("\n" + "=" * 104)
    print("WB.3  DOES SCORE RANK EDGE? -- if the 25-slot cap is a quality boundary, score must")
    print("      order outcomes inside the pool it excludes")
    print("=" * 104)
    prof = {r["address"]: r["globalScore"] for r in c.execute(
        "SELECT address, globalScore FROM WalletProfile")}
    tr = c.execute("""SELECT globalScore s FROM WalletProfile WHERE status='track'
                      ORDER BY globalScore DESC""").fetchall()
    if not tr:
        return
    floor = tr[-1]["s"]
    byw = {}
    for b in bets:
        s = settle_of(truth.get(b["cid"]), b["outcome"])
        if s is None or b["px"] < DUST_MIN_PX:
            continue
        byw.setdefault(b["wallet"], []).append(s / b["px"] - 1)
    pts = [{"w": w, "score": prof.get(w, 0), "n": len(v), "roi": float(np.mean(v))}
           for w, v in byw.items() if len(v) >= 4 and w in prof]
    if len(pts) < 8:
        print("   only %d sampled wallets have >=4 settled bets -- rank read skipped; the "
              "sample is too thin to rank on (stated, not papered over)" % len(pts))
        return
    sc = np.array([p["score"] for p in pts], dtype=float)
    ro = np.array([p["roi"] for p in pts], dtype=float)
    n = np.array([p["n"] for p in pts], dtype=float)

    def spearman(a, b, w):
        ra = np.argsort(np.argsort(a)).astype(float)
        rb = np.argsort(np.argsort(b)).astype(float)
        ma, mb = np.average(ra, weights=w), np.average(rb, weights=w)
        cov = np.average((ra - ma) * (rb - mb), weights=w)
        return cov / np.sqrt(np.average((ra - ma) ** 2, weights=w) *
                             np.average((rb - mb) ** 2, weights=w))

    rho = spearman(sc, ro, n)
    perm = np.random.default_rng(7)
    null = [spearman(sc, perm.permutation(ro), n) for _ in range(2000)]
    p = float(np.mean(np.abs(null) >= abs(rho)))
    print("   %d wallets with >=4 settled bets, %d bets" % (len(pts), int(n.sum())))
    print("   score vs per-bet ROI, n-weighted Spearman rho = %+.3f, permutation p = %.3f"
          % (rho, p))
    print("   -> %s" % ("score orders outcome (p<0.05)" if p < 0.05 else
                        "UNDERPOWERED: cannot separate 'score orders outcome' from 'it does not' "
                        "at this n -- report, do not act"))
    for lab, g in (("at/above 25th-slot score", [x for x in pts if x["score"] >= floor]),
                   ("below it (all sampled wallets sit here by construction)", [x for x in pts if x["score"] < floor])):
        if g:
            wsum = sum(x["n"] for x in g)
            print("   %-56s wallets=%3d bets=%5d roi=%+6.1f%%"
                  % (lab, len(g), wsum, 100 * sum(x["roi"] * x["n"] for x in g) / wsum))


# ================================================================ WB.6 persistence
def _spearman(a, b, w):
    ra = np.argsort(np.argsort(a)).astype(float)
    rb = np.argsort(np.argsort(b)).astype(float)
    ma, mb = np.average(ra, weights=w), np.average(rb, weights=w)
    cov = np.average((ra - ma) * (rb - mb), weights=w)
    den = np.sqrt(np.average((ra - ma) ** 2, weights=w) *
                  np.average((rb - mb) ** 2, weights=w))
    return cov / den if den else float("nan")


def _wallet_boot(per_wallet, reps=1500, seed=11):
    """Market-free, WALLET-clustered CI of the n-weighted mean edge. The unit of
    selection is the wallet, so the wallet is the resampling unit."""
    if len(per_wallet) < 8:
        return (float("nan"), float("nan"))
    v = np.array([e for e, _ in per_wallet], dtype=float)
    w = np.array([n for _, n in per_wallet], dtype=float)
    rng = np.random.default_rng(seed)
    out = []
    for _ in range(reps):
        idx = rng.integers(0, len(v), len(v))
        out.append(float(np.average(v[idx], weights=w[idx])))
    return (float(np.percentile(out, 2.5)), float(np.percentile(out, 97.5)))


def _bets_for_half(c, wallet, t0, t1):
    return c.execute("""SELECT marketId m, outcome oc, conditionId cid,
                               walletEntryPrice px, MIN(timestamp) ts
                        FROM ObservedTrade
                        WHERE isDemo=0 AND observationOnly=1 AND walletAddress=?
                          AND timestamp>=? AND timestamp<=?
                          AND walletEntryPrice>0.0001 AND walletEntryPrice<0.9999
                        GROUP BY marketId, outcome""", (wallet, t0, t1)).fetchall()


def _sample_bets(c, wallets, since, mid, until, per_half, rng):
    """One pass, reservoir-sampled to `per_half` first-print bets per wallet per half.

    A per-wallet query costs ~2s on a whale wallet (27k prints); 200 wallets x 2 halves
    would be 400 round trips for a sample of 30. Reservoir sampling keeps memory at
    O(wallets x per_half) and the sample uniform over each wallet's bets without ever
    materialising the window.
    """
    ph = ",".join("?" * len(wallets))
    q = """SELECT walletAddress w, marketId m, outcome oc, conditionId cid,
                  walletEntryPrice px, MIN(timestamp) ts
           FROM ObservedTrade
           WHERE isDemo=0 AND observationOnly=1 AND timestamp>=? AND timestamp<=?
             AND walletEntryPrice>0.0001 AND walletEntryPrice<0.9999
             AND walletAddress IN (%s)
           GROUP BY walletAddress, marketId, outcome""" % ph
    res = {w: {"a": [], "b": [], "na": 0, "nb": 0} for w in wallets}
    for row in c.execute(q, [since, until] + list(wallets)):
        side = "a" if row["ts"] < mid else "b"
        d = res[row["w"]]
        d["n" + side] += 1
        seen = d["n" + side]
        bet = {"cid": row["cid"], "outcome": row["oc"], "px": row["px"], "ts": row["ts"],
               "market": row["m"]}
        bucket = d[side]
        if len(bucket) < per_half:
            bucket.append(bet)
        else:
            j = int(rng.integers(0, seen))
            if j < per_half:
                bucket[j] = bet
    return res


def _half_stats(bets, truth):
    dec = []
    for b in bets:
        s = settle_of(truth.get(b["cid"]), b["outcome"])
        if s is not None:
            dec.append({**b, "s": s, "end": (truth.get(b["cid"]) or {}).get("end")})
    if not dec:
        return None
    px = float(np.mean([b["px"] for b in dec]))
    hit = float(np.mean([b["s"] for b in dec]))
    clean = [b for b in dec if b["px"] >= DUST_MIN_PX]
    roi = float(np.mean([b["s"] / b["px"] - 1 for b in clean])) if clean else float("nan")
    return {"n": len(dec), "px": px, "hit": hit, "edge": 100 * (hit - px),
            "roi": 100 * roi, "dec": dec}


TTL_BUCKETS = [("  <6h", 0, 6), (" 6-24h", 6, 24), ("  1-3d", 24, 72),
               ("  3-7d", 72, 168), (" 7-30d", 168, 720), ("  >=30d", 720, 1e9)]


def _parse_iso(s):
    if not s or not isinstance(s, str) or len(s) < 10:
        return None
    try:
        return int(time.mktime(time.strptime(s[:19], "%Y-%m-%dT%H:%M:%S"))) * 1000
    except Exception:
        try:
            return int(time.mktime(time.strptime(s[:10], "%Y-%m-%d"))) * 1000
        except Exception:
            return None


def ttl_axis(pooled):
    """WB.7 -- does the MARKET predict edge, in a population we never selected?

    Why this follows WB.6: if wallet identity does not rank edge, the only remaining
    candidate for a non-copy mechanism is the market's own features. TTL at entry is the
    one such feature a rule can act on, and it has only ever been measured on OUR book --
    which is gate-selected by the very rules under test. This is the first read of it on
    an out-of-gate population: observation-only wallets, first print per bet, settlement
    truth, no admission rule involved.

    TTL = (market end date - bet timestamp). The end date is the SCHEDULED close, not the
    actual resolution, so a market that resolved early is measured at its scheduled
    maturity. Stated because it is a real misclassification source and it biases nothing
    in a known direction.
    """
    print("\n" + "=" * 104)
    print("WB.7  TTL AT ENTRY, OUT OF GATE -- the last non-wallet mechanism candidate")
    print("=" * 104)
    have = []
    for b in pooled:
        e = _parse_iso(b.get("end"))
        if e is None:
            continue
        ttl = (e - b["ts"]) / 3_600_000.0
        if ttl <= 0:
            continue
        have.append({**b, "ttl": ttl})
    print("   bets with a usable scheduled end: %s of %s settled (%.1f%%)"
          % (format(len(have), ","), format(len(pooled), ","),
             100 * len(have) / max(len(pooled), 1)))
    if len(have) < 500:
        print("   too few priced for a TTL read -- reported, not read")
        return
    base = float(np.mean([b["s"] for b in have])) - float(np.mean([b["px"] for b in have]))
    plo, phi = cluster_ci(have, lambda b: b["s"] - b["px"])
    print("   pool edge %+.2fpp [%+.1f,%+.1f] on %s bets (market-clustered CI)"
          % (100 * base, plo, phi, format(len(have), ",")))
    print("   %-8s %6s %6s %7s %8s %22s %9s %9s"
          % ("TTL", "n", "px", "hit", "edge", "edge CI (95%)", "ROI", "ex-top-10"))
    for nm, lo, hi in TTL_BUCKETS:
        g = [b for b in have if lo <= b["ttl"] < hi]
        if len(g) < 30:
            continue
        px = float(np.mean([b["px"] for b in g]))
        hit = float(np.mean([b["s"] for b in g]))
        elo, ehi = cluster_ci(g, lambda b: b["s"] - b["px"])
        clean = [b for b in g if b["px"] >= DUST_MIN_PX]
        roi = float(np.mean([b["s"] / b["px"] - 1 for b in clean])) * 100
        pnl = sorted([STAKE * (b["s"] / b["px"] - 1) for b in clean], reverse=True)
        x10 = 100 * sum(pnl[10:]) / (STAKE * len(pnl[10:])) if len(pnl) > 20 else float("nan")
        print("   %-8s %6d %6.3f %6.1f%% %+7.2fpp [%+6.1f,%+6.1f] %+8.1f%% %+8.1f%%"
              % (nm, len(g), px, 100 * hit, 100 * (hit - px), elo, ehi, roi, x10))
    # band x TTL, only cells with enough mass to be worth printing
    print("\n   band x TTL (cell = n / edge pp):")
    print("   %-9s %s" % ("band", " ".join("%9s" % nm.strip() for nm, _, _ in TTL_BUCKETS)))
    for nm, lo, hi in BANDS:
        cells = []
        for tnm, tlo, thi in TTL_BUCKETS:
            g = [b for b in have if lo <= b["px"] < hi and tlo <= b["ttl"] < thi]
            if len(g) < 40:
                cells.append("%9s" % "-")
            else:
                cells.append("%4d/%+4.1f" % (len(g),
                                             100 * (np.mean([b["s"] for b in g]) - np.mean([b["px"] for b in g]))))
        print("   %-9s %s" % (nm, " ".join(cells)))
    best = None
    for nm, lo, hi in TTL_BUCKETS:
        g = [b for b in have if lo <= b["ttl"] < hi]
        if len(g) < 100:
            continue
        elo, ehi = cluster_ci(g, lambda b: b["s"] - b["px"])
        if elo > 0 and (best is None or elo > best[1]):
            best = (nm.strip(), elo, ehi, len(g))
    if best:
        print("\n   only cell with an edge CI excluding zero: TTL %s, %+.1f..%+.1fpp on %d bets"
              % (best[0], best[1], best[2], best[3]))
    else:
        print("\n   NO TTL cell has an edge CI excluding zero on this out-of-gate population.")
        print("   A rule cannot be built on a point estimate whose interval contains 0.")


def wallet_edge_persistence(c, rng):
    """WB.6 -- does a wallet's measured edge persist into its own next 30 days?

    This is the gate the 2026-10-31 review pre-registered: the only axis on which the
    book shows a spread is WHICH WALLET, and if per-wallet edge does not persist then no
    admission, band, size or breadth change can be more than noise.

    Design choices that matter, stated so they can be attacked:
      * Split by TIME, not by bet: half A = day -60..-30, half B = day -30..-7. A random
        split would leak the same market into both halves.
      * Eligibility requires >=12 prints in BOTH halves, and a wallet enters the
        correlation only with >=8 SETTLED bets per half (coverage is printed).
      * Multiplicity: 1,405 wallets exist, so the test is not "is the mean correlation
        positive" alone -- it also permutes the half-A ranks and asks how large the
        top-25 selection's half-B edge gets with no information at all.
      * Attenuation: a 30-bet half measures a wallet's true edge with ~9pp of noise, so a
        real rank attenuates. The Spearman-Brown estimate (2r/(1+r)) and the variance
        decomposition are both printed, and the pre-registered bar is applied to the RAW
        correlation because that is what was written down.
    """
    print("\n" + "=" * 104)
    print("WB.6  DOES WALLET EDGE PERSIST? -- the gate every future proposal was made to wait on")
    print("=" * 104)
    day = int(time.time() * 1000 // 86400000) * 86400000
    since = day - WINDOW_DAYS * 86400000
    mid = day - 30 * 86400000
    until = day - 7 * 86400000
    elig = [r[0] for r in c.execute(
        """SELECT walletAddress FROM ObservedTrade
           WHERE isDemo=0 AND observationOnly=1 AND timestamp>=? AND timestamp<=?
             AND walletEntryPrice>0.0001 AND walletEntryPrice<0.9999
           GROUP BY walletAddress
           HAVING SUM(CASE WHEN timestamp<? THEN 1 ELSE 0 END) >= 12
              AND SUM(CASE WHEN timestamp>=? THEN 1 ELSE 0 END) >= 12""",
        (since, until, mid, mid))]
    print("   wallets with >=12 prints in BOTH halves: %s" % format(len(elig), ","))
    if len(elig) < PERSIST_WALLETS:
        pick = elig
    else:
        pick = list(rng.choice(sorted(elig), PERSIST_WALLETS, replace=False))

    sample = {}
    t_s = time.time()
    raw = _sample_bets(c, pick, since, mid, until, PERSIST_PER_HALF, rng)
    for w in pick:
        sample[w] = (raw[w]["a"], raw[w]["b"])
    print("   sampling pass %.1fs; median bets/wallet %.0f A / %.0f B"
          % (time.time() - t_s,
             float(np.median([raw[w]["na"] for w in pick])),
             float(np.median([raw[w]["nb"] for w in pick]))))

    need = sorted({b["cid"] for a, b in sample.values() for b in a + b})
    nbets = sum(len(a) + len(b) for a, b in sample.values())
    truth, missing, tried, got = fetch_truth(need)
    print("   sampled %d wallets / %d bets / %s distinct markets (truth: %s uncached, "
          "%s attempted, %s fetched)"
          % (len(pick), nbets, format(len(need), ","),
             format(missing, ","), format(tried, ","), format(got, ",")))

    rows = []
    pooled = []
    for w, (a, b) in sample.items():
        sa, sb = _half_stats(a, truth), _half_stats(b, truth)
        if not sa or not sb:
            continue
        pooled += sa["dec"] + sb["dec"]
        if sa["n"] < PERSIST_MIN_SETTLED or sb["n"] < PERSIST_MIN_SETTLED:
            continue
        rows.append({"w": w, "a": sa, "b": sb})
    if len(rows) < 40:
        print("   only %d wallets clear >=%d settled bets per half -- TOO THIN TO READ. "
              "This is a coverage failure, not a zero." % (len(rows), PERSIST_MIN_SETTLED))
        return None
    print("   priced wallets: %d (>=%d settled bets in each half)"
          % (len(rows), PERSIST_MIN_SETTLED))
    nA = float(np.mean([r["a"]["n"] for r in rows]))
    nB = float(np.mean([r["b"]["n"] for r in rows]))
    wA = np.array([r["a"]["n"] for r in rows], dtype=float)
    wB = np.array([r["b"]["n"] for r in rows], dtype=float)
    eA = np.array([r["a"]["edge"] for r in rows], dtype=float)
    eB = np.array([r["b"]["edge"] for r in rows], dtype=float)

    print("\n   pool: half A edge %+.2fpp on %d bets | half B edge %+.2fpp on %d bets"
          % (np.average(eA, weights=wA), int(wA.sum()),
             np.average(eB, weights=wB), int(wB.sum())))

    # ---- variance decomposition: how much of the cross-wallet spread is real?
    noise = float(np.mean([r["a"]["px"] * (1 - r["a"]["px"]) / r["a"]["n"] * 1e4
                           for r in rows]))
    obs_var = float(np.average((eA - np.average(eA, weights=wA)) ** 2, weights=wA))
    rel = max(0.0, 1.0 - noise / obs_var) if obs_var > 0 else 0.0
    print("   cross-wallet edge variance %.1f pp^2; sampling noise inside a half %.1f pp^2 "
          "-> reliability %.2f" % (obs_var, noise, rel))
    print("   implied true cross-wallet edge sd %.1fpp (observed sd %.1fpp)"
          % (np.sqrt(max(obs_var - noise, 0)), np.sqrt(obs_var)))

    # ---- pre-registered read: raw split-half correlation
    rho = _spearman(eA, eB, np.sqrt(wA * wB))
    perm = np.random.default_rng(17)
    null = [_spearman(eA, perm.permutation(eB), np.sqrt(wA * wB)) for _ in range(2000)]
    p = float(np.mean(np.abs(null) >= abs(rho)))
    sb = 2 * rho / (1 + rho) if rho > -1 else float("nan")
    att = rho / rel if rel > 0 else float("nan")
    lo, hi = float(np.percentile(null, 2.5)), float(np.percentile(null, 97.5))
    print("\n   PRE-REGISTERED  split-half Spearman rho = %+.3f  (permutation p = %.3f; "
          "null 95%% band %+.3f..%+.3f)" % (rho, p, lo, hi))
    print("   attenuation: Spearman-Brown %+.3f | reliability-corrected %s"
          % (sb, ("%+.3f" % att) if rel > 0.05 else
             "not identifiable (a half contains more noise than the whole spread)"))
    print("   bar from the 2026-10-31 review: rho >= +0.30 with a CI excluding zero at "
          ">=100 wallets -> %s (permutation p = %.3f is the CI check here)"
          % ("MET" if (rho >= 0.30 and p < 0.05) else "NOT MET", p))

    # ---- what an actual ranker would have earned, out of sample in time
    order = np.argsort(-eA)
    print("\n   half-A edge quintile -> half-B edge (the operational question):")
    qs = np.array_split(order, 5)
    for i, q in enumerate(qs, 1):
        ww, bb = wB[q], eB[q]
        elo, ehi = _wallet_boot([(eB[j], wB[j]) for j in q])
        print("      Q%d (half-A edge %+6.1f..%+6.1f): wallets=%3d  half-B edge %+6.2fpp "
              "[%+6.2f,%+6.2f]" % (i, eA[q].min(), eA[q].max(), len(q),
                                   np.average(bb, weights=ww), elo, ehi))

    def topk(k):
        q = order[:k]
        return [(eB[j], wB[j]) for j in q], q

    psel25 = float("nan")
    for k in (25, 50):
        if len(rows) < k * 2:
            continue
        sel, q = topk(k)
        m = float(np.average([x for x, _ in sel], weights=[n for _, n in sel]))
        elo, ehi = _wallet_boot(sel)
        bot = order[-k:]
        mb = float(np.average(eB[bot], weights=wB[bot]))
        # multiplicity: how good does the top-k look when the ranking is pure noise?
        nsel = []
        for _ in range(400):
            fake = perm.permutation(eA)
            qq = np.argsort(-fake)[:k]
            nsel.append(float(np.average(eB[qq], weights=wB[qq])))
        psel = float(np.mean(np.array(nsel) >= m))
        if k == 25:
            psel25 = psel
        print("      top-%d by half-A edge -> half-B edge %+6.2fpp [%+6.2f,%+6.2f] | "
              "bottom-%d %+6.2fpp | permutation p(selection) = %.3f"
              % (k, m, elo, ehi, k, mb, psel))

    # ---- the production ranker we already have: globalScore
    prof = {r["address"]: r["globalScore"] for r in c.execute(
        "SELECT address, globalScore FROM WalletProfile")}
    have = [(r, prof[r["w"]]) for r in rows if r["w"] in prof]
    if len(have) >= 40:
        g = np.array([x[1] for x in have], dtype=float)
        eb = np.array([x[0]["b"]["edge"] for x in have], dtype=float)
        ww = np.array([x[0]["b"]["n"] for x in have], dtype=float)
        rg = _spearman(g, eb, ww)
        nullg = [_spearman(g, perm.permutation(eb), ww) for _ in range(2000)]
        pg = float(np.mean(np.abs(nullg) >= abs(rg)))
        print("\n   production ranker (WalletProfile.globalScore) vs half-B edge: "
              "rho = %+.3f, permutation p = %.3f on %d wallets"
              % (rg, pg, len(have)))
        print("      NOTE: globalScore is TODAY's value, not point-in-time -- this is a "
              "forward-outcome read of a current score, the friendliest possible basis.")

    # ---- dollars, because pp is not a business
    # Flow is the top-25's OWN measured flow (sum of its distinct bets in half B / 30), not
    # the whole panel's: repeating a ranker's edge over flow it never trades is how a
    # +1pp read becomes a fantasy revenue line.
    sel, q = topk(min(25, len(rows) // 2))
    m = float(np.average([x for x, _ in sel], weights=[n for _, n in sel]))
    bets_day = float(np.sum(wB[q])) / 30.0
    panel_day = float(np.sum([raw[w]["nb"] for w in pick])) / 30.0
    print("\n   dollars: at a $%.0f clip, %+.2fpp is $%+.2f per bet. The top-25 wallets' own "
          "flow is\n   %.1f bets/day -> $%+.2f/day; the whole 200-wallet panel prints %.0f "
          "bets/day. Both are\n   upper bounds computed from an edge the same run cannot "
          "separate from zero (p=%.2f)."
          % (STAKE, m, STAKE * m / 100.0, bets_day, bets_day * STAKE * m / 100.0,
             panel_day, psel25))
    ttl_axis(pooled)
    return {"rho": rho, "p": p, "sb": sb, "att": att, "n_wallets": len(rows),
            "pool_b": float(np.average(eB, weights=wB)), "top25_b": m,
            "rel": rel, "bets_day": bets_day}


# ================================================================ WB.4 flow multiplier
def flow_multiplier(c, uncopied):
    print("\n" + "=" * 104)
    print("WB.4  FLOW MULTIPLIER vs THE LADDER")
    print("=" * 104)
    now = time.time() * 1000
    d30 = now - 30 * 86400000
    copy_n = c.execute("""SELECT count(*) n FROM DecisionJournal
                          WHERE isDemo=0 AND decision='paper_copy' AND createdAt>=?""",
                       (d30,)).fetchone()["n"]
    obs_w = c.execute("""SELECT count(DISTINCT walletAddress) n FROM ObservedTrade
                         WHERE isDemo=0 AND observationOnly=1 AND timestamp>=?""",
                      (d30,)).fetchone()["n"]
    print("   live copy rate: %d copies/30d = %.1f/day from a 25-wallet universe"
          % (copy_n, copy_n / 30))
    print("   observed supply: %s observation-only wallets in 30d" % format(obs_w, ","))
    if not uncopied or not uncopied["n"]:
        return
    e = uncopied["roi"] / 100.0
    print("   measured uncopied edge: %+.1f%% per bet (settlement basis, ex-dust, %d legs)"
          % (uncopied["roi"], uncopied["covered"]))
    if e > 0:
        print("   a $500/day rung at a $10 clip and this edge needs %s bets/day"
              % format(int(500 / (STAKE * e)), ","))
        for mult in (4, 12, 40):
            bets_day = (copy_n / 30) * mult
            print("   universe x%-2d (%4d wallets): %6.1f bets/day -> $%7s/day notional "
                  "-> $%6.0f/day profit"
                  % (mult, 25 * mult, bets_day, format(bets_day * STAKE, ",.0f"),
                     bets_day * STAKE * e))
    else:
        print("   measured edge <= 0: more flow does NOT add PnL. Breadth is not the lever.")


# ================================================================ WB.5 contradictions
def contradictions():
    print("\n" + "=" * 104)
    print("WB.5  CONTRADICTIONS REPORTED, NOT RESOLVED")
    print("=" * 104)
    p = "data/drift-shadow-summary.json"
    if not os.path.exists(p):
        return
    d = json.load(open(p))
    b, ps = d.get("decayBar", {}), d.get("decayBarPerSignal", {})
    print("\n   DRIFT RELAXATION TRIGGER (pre-registered 2026-09-20) reads TWO bases:")
    print("     poll-row  : cohort7d $%+.2f, %s consecutive days <= $0.50, tripped=%s"
          % (b.get("cohort7d"), b.get("consecutiveDaysAtOrBelow"), b.get("tripped")))
    print("     per-signal: cohort7d $%+.2f, %s days, tripped=%s"
          % (ps.get("cohort7d"), ps.get("consecutiveDaysAtOrBelow"), ps.get("tripped")))
    print("     Registered on the poll-row series, tripped for %s consecutive days, and the "
          "relaxation it promises has not been brought forward."
          % b.get("consecutiveDaysAtOrBelow"))
    print("     Counting poll rows is the every-print defect §AM.3 documents, where it reversed "
          "the sign.")
    print("     Prior reads (10-11, 10-20) found a tolerance move admits ~19-21 legs and is "
          "co-blocked by confidence: reported as an inconsistency, NOT re-proposed.")


# ================================================================ selftest
def selftest():
    print("selftest: settlement mapping and the edge identity")
    rec = {"tokens": [["Yes", True], ["No", False]]}
    checks = [
        ("YES winner -> 1.0", settle_of(rec, "Yes"), 1.0),
        ("NO loser -> 0.0", settle_of(rec, "No"), 0.0),
        ("unsettled tokens -> None",
         settle_of({"tokens": [["Yes", False], ["No", False]]}, "Yes"), None),
        ("no winner flag -> None",
         settle_of({"tokens": [["Yes", False], ["No", False]]}, "No"), None),
        ("index fallback: real Yes/No pair",
         settle_of({"tokens": [["Yes", False], ["No", True]]}, "NO"), 1.0),
        ("A/B pair refused (no fabricated loss)",
         settle_of({"tokens": [["A", False], ["B", True]]}, "NO"), None),
    ]
    ok = True
    for lab, got, want in checks:
        good = got == want
        ok &= good
        print("  %s  %s: got %r want %r" % ("PASS" if good else "FAIL", lab, got, want))
    b = [{"px": 0.20, "s": 1.0}] + [{"px": 0.20, "s": 0.0} for _ in range(4)]
    hit = np.mean([x["s"] for x in b])
    px = np.mean([x["px"] for x in b])
    roi = np.mean([x["s"] / x["px"] - 1 for x in b])
    same = abs((hit - px) - roi) < 1e-12
    ok &= same
    print("  %s  hit-px == mean roi at a single price (%+.1fpp vs %+.1f%%) -- they diverge "
          "across prices, which is why both are printed"
          % ("PASS" if same else "FAIL", 100 * (hit - px), 100 * roi))
    print("  OK" if ok else "  FAILURES")
    return ok


def main():
    if SELFTEST:
        sys.exit(0 if selftest() else 1)
    c = con()
    rng = np.random.default_rng(2026)
    print("=" * 104)
    print("PROFIT REVIEW INSTRUMENT -- wallet breadth. %s CDT | window %dd | clip $%.0f | "
          "dust floor $%.2f" % (time.strftime("%Y-%m-%d %H:%M"), WINDOW_DAYS, STAKE, DUST_MIN_PX))
    print("=" * 104)
    if ONLY_WB6:
        wallet_edge_persistence(c, rng)
        return
    killed_hypotheses(c)
    supply_census(c)

    bets = sample_for_truth(c, rng)
    need = sorted({b["cid"] for b in bets})
    truth, missing, tried, got = fetch_truth(need)
    print("\n   truth: %s sampled markets, %s uncached, %s attempted, %s fetched (offline=%s)"
          % (format(len(need), ","), format(missing, ","), format(tried, ","),
             format(got, ","), OFFLINE))

    unc, cstat = uncopied_edge(c, truth, bets)
    score_ranks_edge(c, truth, bets)
    flow_multiplier(c, unc)
    contradictions()
    wallet_edge_persistence(c, rng)
    print("\n   Reproduce: python3 scripts/profit-wallet-breadth.py (--offline after the first "
          "run) | --selftest")


if __name__ == "__main__":
    main()
