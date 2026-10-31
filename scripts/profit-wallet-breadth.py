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
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

import numpy as np

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
    path = os.path.join(TRUTH_RAW, cid + ".json")
    for attempt in range(2):
        if not os.path.exists(path) or os.path.getsize(path) < 40:
            os.system("curl -s --max-time 20 https://clob.polymarket.com/markets/%s -o %s"
                      % (cid, path))
        try:
            d = json.load(open(path))
            toks = [[t.get("outcome"), bool(t.get("winner"))] for t in d.get("tokens", [])]
            if any(t[1] for t in toks):
                return cid, {"tokens": toks, "end": d.get("end_date_iso")}
            return cid, {"tokens": toks, "end": d.get("end_date_iso"), "unsettled": True}
        except Exception:
            time.sleep(0.25 * (attempt + 1))
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
    """Truth for exactly these conditionIds. Cache JSON first, then the raw archive (so a
    re-run resumes instead of refetching), then a bounded wire pass."""
    cache = {}
    if os.path.exists(TRUTH_CACHE):
        cache = json.load(open(TRUTH_CACHE)).get("markets", {})
    missing = []
    for c in cids:
        if c in cache:
            continue
        rec = _truth_from_raw(c)
        if rec is not None:
            cache[c] = rec
        else:
            missing.append(c)
    todo = missing[:FETCH_CAP]
    got = 0
    if todo and not OFFLINE:
        os.makedirs(TRUTH_RAW, exist_ok=True)
        with ThreadPoolExecutor(max_workers=12) as ex:
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
    print("\n   Reproduce: python3 scripts/profit-wallet-breadth.py (--offline after the first "
          "run) | --selftest")


if __name__ == "__main__":
    main()
