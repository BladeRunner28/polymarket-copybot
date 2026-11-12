#!/usr/bin/env python3
"""Wallet selection vs BH-FDR -- does any tracked wallet's edge survive multiple testing?

CARD (roadmap `crowdintel-wallet-fdr-audit`, approved 2026-10-21):
  HYPOTHESIS  per-wallet ROI in the tracked set is indistinguishable from selection across the
              screened population once you correct for the number of wallets scanned.
  MEASUREMENT per-wallet excess return over the price implied by entry band, event-clustered
              effective n (cluster by market, not leg), BH-FDR q-values across the full screened
              population.
  DECISION    >=30% of current `track` wallets with q>0.10 (or n_eff<8) => propose a q-gated
              shadow ranking (Lane A, recommendation only, shadow-first); else DROP the item
              permanently and record the null.
  REFUTATION  <30% fall below q<=0.10 AND H1->H2 wallet-rank correlation >= +0.30 on >=30
              overlapping wallets => wallet selection is real, the band thesis is incomplete,
              escalate instead of dropping.
  GUARD       the SAME question as profit-recs #3 (per-wallet forward ROI Spearman -0.018,
              p=0.942, n=16 on 10-21; -0.100, p=0.616, n=27 on 10-29). ONE instrument, ONE
              decision rule, no two conflicting numbers: §D reproduces the prior statistic on the
              prior population, then states the ONE rank-correlation this card reports.

DEFINITIONS (all printed with the numbers they produce)
  bet        first print per (wallet, conditionId, outcome) BUY row in ObservedTrade, joined to
             the venue's own settlement truth (archived CLOB /markets/<cid> tokens[].winner).
             price  = detectedPrice (our detection price; walletEntryPrice when dp is unusable),
             identical to scripts/profit-sellside.py §SS.6 so the two are the same population.
  edge       settle value - price paid, in probability points. Dollars never enter: a $1 bet and
             a $10,000 bet count the same, so the statistic cannot be taken by the biggest book.
  band       0.00-0.20 / 0.20-0.40 / 0.40-0.60 / 0.60-0.80 / 0.80-1.00 (same bands as
             src/lib/rules.ts and profit-band-report.py).
  excess     edge - the band's mean edge for the SAME band, computed across the whole screened
             population with the wallet under test LEFT OUT (leave-one-wallet-out). This is the
             card's "excess return over the price implied by entry band": it removes the part of
             a wallet's result that is just "it bought a well-priced band".
  n_eff      number of DISTINCT markets (conditionId) the wallet's bets sit in -- clusters, not
             legs. A wallet that buys 20 legs of one event has n_eff 1.
  t stat     one-sample t over the per-market mean excess (each market one observation), the
             conservative event-clustered read. p_pos is one-sided for skill (alpha > 0).
  q          Benjamini-Hochberg over the ONE-SIDED p of every TESTED wallet in the screened
             population (family = wallets with n_eff >= MIN_NEFF_TEST), so the correction carries
             the size of the screen, which is the whole question.

LABEL BASIS / CONTAMINATION (the card requires this be stated)
  The prior card `label-integrity-wallet-win-filter` flagged `won = curPrice>0.5 ||
  realizedPnl>0` feeding winRate30d/roi30d -> copyScore. Measured 2026-10-29: NO scoring arm
  reads `won` (scoreWallet takes its win-rate terms from `pnl > 0`, src/lib/scoring/wallet.ts),
  and its label half is shipped. This instrument reads NEITHER copyScore NOR any wallet score --
  it joins raw prints to the venue's settlement and prices them at the detected price. So the
  `won` label cannot contaminate the statistic. The only channel it could travel is the COMPOSITION
  of the `track` set, and that composition is the object under test, not an input to it.

COST BASIS / TRUTH COVERAGE
  Settlement truth comes from the keyless archived CLOB endpoint and is cached:
  data/market-truth-clob.json (4,005 markets, shared with profit-velocity/sellside) plus
  data/wallet-fdr-truth.json (this instrument's expansion, one record per market, no raw bodies
  committed). The cache is what binds the sample: 4,005 markets against 299,421 distinct
  conditionIds in ObservedTrade is 1.3%. `--fetch N` widens it, prioritizing markets that carry
  the most distinct wallets and every market a currently `track` wallet printed in; coverage is
  PRINTED, never assumed, and a market that is not settled is recorded as unsettled rather than
  dropped silently.

USAGE
  python3 scripts/wallet-fdr-audit.py --fetch 6000      # widen the truth cache (keyless, ~5 min)
  python3 scripts/wallet-fdr-audit.py --offline         # report from cache only
  python3 scripts/wallet-fdr-audit.py --json data/wallet-fdr-audit.json

Read-only on prisma/dev.db (mode=ro). Writes only: data/wallet-fdr-truth.json (with --fetch) and
the --json path.
"""
from __future__ import annotations

import argparse
import collections
import importlib.util
import json
import math
import os
import random
import sqlite3
import statistics
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _resolve_db():
    """$COPYBOT_DB, else <root>/prisma/dev.db, else the primary tree's DB when run in a worktree.

    A git worktree carries no prisma/ directory (dev.db is 12 GB and lives only in the primary
    checkout), so the default read must fall through to the common dir rather than fail.
    """
    env = os.environ.get("COPYBOT_DB")
    if env:
        return env
    here = os.path.join(ROOT, "prisma", "dev.db")
    if os.path.exists(here):
        return here
    try:
        import subprocess
        common = subprocess.check_output(
            ["git", "-C", ROOT, "rev-parse", "--git-common-dir"], text=True).strip()
        cand = os.path.join(os.path.dirname(os.path.abspath(os.path.join(ROOT, common))),
                            "prisma", "dev.db")
        if os.path.exists(cand):
            return cand
    except Exception:
        pass
    return here


DB = _resolve_db()
SHARED_TRUTH = os.path.join(ROOT, "data", "market-truth-clob.json")
FDR_TRUTH = os.path.join(ROOT, "data", "wallet-fdr-truth.json")

BANDS = [(0.0, 0.2), (0.2, 0.4), (0.4, 0.6), (0.6, 0.8), (0.8, 1.0001)]
BAND_NAMES = ["0.00-0.20", "0.20-0.40", "0.40-0.60", "0.60-0.80", "0.80-1.00"]
CUT = 1787300000000          # 2026-08-20 -- the split profit-recs #3 pre-registered
MIN_HALF_BETS = 8            # profit-recs #3's per-half bar
MIN_NEFF_TEST = 3            # a wallet needs >=3 market clusters before a t exists at all
MIN_NEFF_DECISION = 8        # the card's "or n_eff<8" arm
Q_BAR = 0.10                 # the card's q bar
SHARE_BAR = 0.30             # the card's >=30% share
RHO_BAR = 0.30               # the card's refutation bar
PERM_REPS = 5000


def band_of(p):
    for (lo, hi), nm in zip(BANDS, BAND_NAMES):
        if lo <= p < hi:
            return nm
    return None


# ---------------------------------------------------------------- statistics
def _betacf(a, b, x):
    """Continued fraction for the incomplete beta (Numerical Recipes 6.4)."""
    MAXIT, EPS, FPMIN = 200, 3e-12, 1e-300
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
    if abs(d) < FPMIN:
        d = FPMIN
    d = 1.0 / d
    h = d
    for m in range(1, MAXIT + 1):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        if abs(d) < FPMIN:
            d = FPMIN
        c = 1.0 + aa / c
        if abs(c) < FPMIN:
            c = FPMIN
        d = 1.0 / d
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        if abs(d) < FPMIN:
            d = FPMIN
        c = 1.0 + aa / c
        if abs(c) < FPMIN:
            c = FPMIN
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < EPS:
            break
    return h


def _betai(a, b, x):
    """Regularized incomplete beta I_x(a,b)."""
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    lbeta = math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b)
    front = math.exp(lbeta + a * math.log(x) + b * math.log(1.0 - x))
    if x < (a + 1.0) / (a + b + 2.0):
        return front * _betacf(a, b, x) / a
    return 1.0 - front * _betacf(b, a, 1.0 - x) / b


def t_sf(t, df):
    """P(T > t) for Student t with df degrees of freedom."""
    if df <= 0 or not math.isfinite(t):
        return float("nan")
    x = df / (df + t * t)
    tail = 0.5 * _betai(df / 2.0, 0.5, x)
    return tail if t > 0 else 1.0 - tail


def one_sample_t(vals):
    n = len(vals)
    if n < 2:
        return None
    m = statistics.mean(vals)
    sd = statistics.stdev(vals)
    if sd == 0:
        return (m, 0.0 if m == 0 else math.copysign(float("inf"), m), n - 1)
    return (m, m / (sd / math.sqrt(n)), n - 1)


def bh_q(pvals):
    """Benjamini-Hochberg q-values, same order as the input."""
    m = len(pvals)
    order = sorted(range(m), key=lambda i: pvals[i])
    q = [1.0] * m
    prev = 1.0
    for rank in range(m, 0, -1):
        i = order[rank - 1]
        prev = min(prev, pvals[i] * m / rank)
        q[i] = prev
    return q


def spearman(a, b):
    def rank(x):
        s = sorted(range(len(x)), key=lambda i: x[i])
        r = [0.0] * len(x)
        i = 0
        while i < len(s):                     # average ties
            j = i
            while j + 1 < len(s) and x[s[j + 1]] == x[s[i]]:
                j += 1
            avg = (i + j) / 2.0
            for t in range(i, j + 1):
                r[s[t]] = avg
            i = j + 1
        return r
    if len(a) < 3:
        return None
    ra, rb = rank(a), rank(b)
    ma, mb = statistics.mean(ra), statistics.mean(rb)
    num = sum((x - ma) * (y - mb) for x, y in zip(ra, rb))
    den = math.sqrt(sum((x - ma) ** 2 for x in ra) * sum((y - mb) ** 2 for y in rb))
    return num / den if den else None


# ---------------------------------------------------------------- truth cache
def load_truth():
    cache = {}
    for path in (SHARED_TRUTH, FDR_TRUTH):
        if not os.path.exists(path):
            continue
        try:
            d = json.load(open(path))
        except Exception as exc:            # a corrupt cache must not look like empty truth
            print(f"  !! truth cache unreadable ({path}): {exc}")
            continue
        for cid, rec in (d.get("markets") or {}).items():
            if rec:
                cache[cid] = rec
    settled = {k for k, v in cache.items() if not v.get("unsettled")}
    return cache, settled


def _fetch_one(cid):
    url = "https://clob.polymarket.com/markets/" + cid
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "copybot-research/1.0"})
            with urllib.request.urlopen(req, timeout=25) as r:
                d = json.loads(r.read().decode())
            toks = [[t.get("outcome"), bool(t.get("winner"))] for t in (d.get("tokens") or [])]
            if not toks:
                return cid, None
            rec = {"tokens": toks, "end": d.get("end_date_iso"), "closed": bool(d.get("closed"))}
            if not any(t[1] for t in toks):
                rec["unsettled"] = True
            return cid, rec
        except Exception:
            time.sleep(0.4 * (attempt + 1))
    return cid, None


def fetch_truth(c, cache, budget):
    """Spend the budget on the markets that carry the most distinct wallets.

    Order: (1) every market a currently `track` wallet printed in -- without these the tracked
    set is unmeasurable and the decision rule is read off missing data; (2) the rest by descending
    distinct-wallet count, tie-broken by bet count. Markets already settled are skipped; known
    unsettled records are re-tried only when their scheduled end has passed.
    """
    now = time.time() * 1000
    mk_wallets = collections.defaultdict(set)
    mk_bets = collections.Counter()
    mk_last = {}
    track = {r[0] for r in c.execute("SELECT address FROM WalletProfile WHERE status='track'")}
    seen = set()
    for r in c.execute("""SELECT walletAddress w, conditionId cid, outcome o, timestamp ts
                          FROM ObservedTrade
                          WHERE isDemo=0 AND side='BUY' AND conditionId IS NOT NULL
                          ORDER BY timestamp"""):
        key = (r["w"], r["cid"], (r["o"] or "").strip().upper())
        if key in seen:
            continue
        seen.add(key)
        mk_wallets[r["cid"]].add(r["w"])
        mk_bets[r["cid"]] += 1
        mk_last[r["cid"]] = r["ts"]

    def needs_fetch(cid):
        rec = cache.get(cid)
        if not rec:
            return True
        if not rec.get("unsettled"):
            return False
        end = rec.get("end")
        if not end:
            return True
        try:
            return time.mktime(time.strptime(end[:19], "%Y-%m-%dT%H:%M:%S")) * 1000 <= now
        except Exception:
            return True

    track_mk = [cid for cid, ws in mk_wallets.items() if (ws & track) and needs_fetch(cid)]
    track_mk.sort(key=lambda cid: -mk_bets[cid])
    tset = set(track_mk)
    rest = [cid for cid in mk_wallets if cid not in tset and needs_fetch(cid)]
    rest.sort(key=lambda cid: (-len(mk_wallets[cid]), -mk_bets[cid]))
    todo = (track_mk + rest)[:budget]
    print(f"\n  truth fetch: {len(mk_wallets):,} markets printed, {len(track_mk):,} of them carry a "
          f"current track wallet; spending {len(todo):,} fetches "
          f"(budget {budget:,}) -> keyless archived CLOB")
    if not todo:
        return cache
    got = fail = 0
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=8) as ex:
        for i, (cid, rec) in enumerate(ex.map(_fetch_one, todo), 1):
            if rec:
                cache[cid] = rec
                got += 1
            else:
                fail += 1
            if i % 2000 == 0:
                print(f"    {i:,}/{len(todo):,}  ok {got:,}  failed {fail:,}  "
                      f"{time.time() - t0:.0f}s")
    payload = {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
               "source": "https://clob.polymarket.com/markets/<conditionId> tokens[].winner",
               "note": "wallet-FDR truth expansion; merged with data/market-truth-clob.json at read",
               "markets": {k: v for k, v in cache.items()}}
    with open(FDR_TRUTH, "w") as f:
        json.dump(payload, f, separators=(",", ":"), sort_keys=True)
    print(f"  fetched {got:,} markets, {fail:,} failed, in {time.time() - t0:.0f}s; "
          f"cache now {len(cache):,} markets -> {os.path.relpath(FDR_TRUTH, ROOT)}")
    return cache


# ---------------------------------------------------------------- population
def load_bets(c, cache):
    """First print per (wallet, conditionId, outcome), priced at the detection price.

    FIRST PRINT ONLY, and that is load-bearing: the 10-27 review measured that per-print
    weighting reverses the sign of the wallet-rank read (a wallet that reprints one market 40
    times is one bet, not 40), so the same rule as scripts/profit-sellside.py §SS.6 applies here.
    """
    stats = collections.Counter()
    bets = []
    seen = set()
    for r in c.execute("""SELECT walletAddress w, conditionId cid, outcome o, detectedPrice dp,
                                 walletEntryPrice wp, timestamp ts, marketId m
                          FROM ObservedTrade
                          WHERE isDemo=0 AND side='BUY' AND conditionId IS NOT NULL
                          ORDER BY timestamp"""):
        key = (r["w"], r["cid"], (r["o"] or "").strip().upper())
        if key in seen:
            stats["repeat_print"] += 1
            continue
        seen.add(key)
        rec = cache.get(r["cid"])
        if not rec or rec.get("unsettled"):
            stats["no_record"] += 1
            continue
        toks = rec.get("tokens") or []
        name = (r["o"] or "").strip().upper().replace("-", " ").replace("_", " ")
        val = None
        for tn, win in toks:
            if (tn or "").strip().upper().replace("-", " ").replace("_", " ") == name:
                val = 1.0 if win else 0.0
                stats["name_match"] += 1
                break
        if val is None:
            if len(toks) == 2 and name in ("YES", "NO"):
                val = 1.0 if toks[0 if name == "YES" else 1][1] else 0.0
                stats["index_fallback"] += 1
            else:
                stats["no_match"] += 1
                continue
        px = r["dp"] if r["dp"] and 0 < r["dp"] < 1 else r["wp"]
        if not px or not (0 < px < 1):
            stats["bad_price"] += 1
            continue
        bets.append({"w": r["w"], "cid": r["cid"], "m": r["m"], "px": px,
                     "ts": r["ts"], "v": val, "edge": 100.0 * (val - px),
                     "band": band_of(px)})
    return bets, stats


def band_excess(bets):
    """edge - leave-one-wallet-out band mean, in pp."""
    per_band = collections.defaultdict(lambda: [0.0, 0])
    per_wallet_band = collections.defaultdict(lambda: collections.defaultdict(lambda: [0.0, 0]))
    for b in bets:
        per_band[b["band"]][0] += b["edge"]
        per_band[b["band"]][1] += 1
        cell = per_wallet_band[b["w"]][b["band"]]
        cell[0] += b["edge"]
        cell[1] += 1
    baseline = {}
    for band, (s, n) in per_band.items():
        baseline[band] = s / n
    for b in bets:
        s, n = per_band[b["band"]]
        ws, wn = per_wallet_band[b["w"]][b["band"]]
        rest = (s - ws) / (n - wn) if n - wn > 0 else baseline[b["band"]]
        b["xedge"] = b["edge"] - rest
    return baseline


def wallet_table(bets):
    """Per-wallet: market-clustered mean excess, t, and the band composition."""
    by_w = collections.defaultdict(list)
    for b in bets:
        by_w[b["w"]].append(b)
    out = {}
    for w, rows in by_w.items():
        per_mk = collections.defaultdict(list)
        per_mk_mid = collections.defaultdict(list)
        for b in rows:
            per_mk[b["cid"]].append(b["xedge"])
            per_mk_mid[b["m"]].append(b["xedge"])
        mk_means = [statistics.mean(v) for v in per_mk.values()]
        mid_means = [statistics.mean(v) for v in per_mk_mid.values()]
        t = one_sample_t(mk_means)
        # A zero-variance cluster set (every market mean identical) yields t = +-inf. That is not
        # evidence and it poisons a rank sort, so it is carried as DEGENERATE and kept out of the
        # BH family rather than reported as a p of 0.
        degenerate = bool(t) and not math.isfinite(t[1])
        p_pos = t_sf(t[1], t[2]) if (t and not degenerate) else None
        if p_pos is not None and not math.isfinite(p_pos):
            p_pos = None
        rec = {
            "w": w, "bets": len(rows), "n_eff": len(per_mk), "n_eff_event": len(per_mk_mid),
            "xmean": statistics.mean([b["xedge"] for b in rows]),
            "raw_mean": statistics.mean([b["edge"] for b in rows]),
            "t": None if degenerate else (t[1] if t else None),
            "t_df": t[2] if t else None,
            "n_eff_mean": t[0] if t else None,
            "degenerate": degenerate,
            "p_pos": p_pos,
        }
        out[w] = rec
    return out


def persistence(bets, key, min_half=MIN_HALF_BETS, cut=CUT):
    """H1 -> H2 rank persistence on one key ('edge' raw, 'xedge' band-excess)."""
    h1, h2 = collections.defaultdict(list), collections.defaultdict(list)
    for b in bets:
        (h1 if b["ts"] < cut else h2)[b["w"]].append(b[key])
    both = [w for w in h1 if len(h1[w]) >= min_half and len(h2.get(w, [])) >= min_half]
    if len(both) < 3:
        return {"n": len(both), "rho": None}
    rho = spearman([statistics.mean(h1[w]) for w in both], [statistics.mean(h2[w]) for w in both])
    rnd = random.Random(7)
    ys = [statistics.mean(h2[w]) for w in both]
    xs = [statistics.mean(h1[w]) for w in both]
    null = []
    for _ in range(2000):
        sh = ys[:]
        rnd.shuffle(sh)
        v = spearman(xs, sh)
        if v is not None:
            null.append(v)
    if not null:
        return {"n": len(both), "rho": rho, "p": None}
    p = sum(1 for v in null if abs(v) >= abs(rho)) / len(null)
    return {"n": len(both), "rho": rho, "p": p}


# ---------------------------------------------------------------- report
def run(args):
    c = sqlite3.connect("file:" + DB + "?mode=ro", uri=True)
    c.row_factory = sqlite3.Row
    cache, settled = load_truth()
    print(f"truth cache: {len(cache):,} markets, {len(settled):,} settled "
          f"(shared {os.path.basename(SHARED_TRUTH)} + {os.path.basename(FDR_TRUTH)})")
    if args.fetch:
        cache = fetch_truth(c, cache, args.fetch)
        settled = {k for k, v in cache.items() if not v.get("unsettled")}

    status = {r[0]: r[1] for r in c.execute("SELECT address, status FROM WalletProfile")}
    bets, stats = load_bets(c, cache)
    if not bets:
        print("no truth-joined bets -- nothing to measure")
        return 1
    baseline = band_excess(bets)
    wallets = wallet_table(bets)
    pop = len(wallets)

    print(f"\nbets joined to settlement truth: {len(bets):,} over {pop:,} wallets "
          f"(join: {dict(stats)})")
    dist_cid = c.execute("SELECT COUNT(DISTINCT conditionId) FROM ObservedTrade "
                         "WHERE conditionId IS NOT NULL").fetchone()[0]
    print(f"truth coverage: {len(settled):,} settled markets against {dist_cid:,} distinct "
          f"conditionIds seen in ObservedTrade = {100.0 * len(settled) / dist_cid:.2f}%")

    # ---- A. what the bands pay the population (the baseline the excess is measured against)
    print("\n=== A. BAND BASELINE -- mean edge (settle - price) by entry band, whole population ===")
    per_band = collections.defaultdict(list)
    for b in bets:
        per_band[b["band"]].append(b["edge"])
    for nm in BAND_NAMES:
        v = per_band.get(nm) or []
        if v:
            t = one_sample_t(v)
            print(f"  {nm}  n={len(v):>6,}  edge {statistics.mean(v):+7.2f}pp  "
                  f"median {statistics.median(v):+7.2f}pp  win {100.0 * sum(1 for x in v if x > 0) / len(v):5.1f}%")

    # ---- B. BH-FDR over the screened population
    tested = [w for w, r in wallets.items()
              if r["n_eff"] >= MIN_NEFF_TEST and r["p_pos"] is not None]
    tested.sort()
    qs = bh_q([wallets[w]["p_pos"] for w in tested])
    for w, q in zip(tested, qs):
        wallets[w]["q"] = q
    for w, r in wallets.items():
        r.setdefault("q", None)
    m = len(tested)
    degenerate = sorted(w for w, r in wallets.items() if r.get("degenerate"))
    viol = sum(1 for w in tested if wallets[w]["q"] < wallets[w]["p_pos"] - 1e-12)
    print(f"\n=== B. BH-FDR OVER THE SCREENED POPULATION (family m={m:,} tested wallets) ===")
    print(f"  tested = wallets with n_eff >= {MIN_NEFF_TEST} market clusters AND a finite t; "
          f"wallets screened in WalletProfile: {len(status):,} "
          f"({dict(collections.Counter(status.values()))})")
    print(f"  instrument check: q < p violations {viol} (must be 0), degenerate cluster sets "
          f"excluded {len(degenerate)}")
    for bar in (0.05, 0.10, 0.20):
        pos = sum(1 for w in tested if wallets[w]["xmean"] > 0 and wallets[w]["q"] <= bar)
        print(f"  q <= {bar:.2f} with positive excess: {pos} wallets "
              f"({100.0 * pos / m:.1f}% of tested)")
    survive = sorted([w for w in tested if wallets[w]["q"] <= Q_BAR],
                     key=lambda w: wallets[w]["q"])
    print(f"  q <= {Q_BAR:.2f} (either sign): {len(survive)} wallets")
    for w in survive[:10]:
        r = wallets[w]
        print(f"    {w[:12]}.. {status.get(w, '?'):6} n_eff {r['n_eff']:>3} bets {r['bets']:>4} "
              f"excess {r['xmean']:+6.2f}pp t {r['t']:+5.2f} q {r['q']:.6f}")

    # ---- C. the tracked set against the rule
    track = sorted([w for w, s in status.items() if s == "track"])
    print(f"\n=== C. THE CURRENT TRACK SET ({len(track)} wallets) AGAINST THE CARD'S RULE ===")
    print(f"  {'wallet':14} {'n_eff':>5} {'bets':>5} {'excess':>8} {'clust':>8} {'raw':>8} {'t':>6} {'q':>7}  flag")
    flagged = []
    for w in track:
        r = wallets.get(w)
        if not r:
            flagged.append((w, "no settled bet in truth cache"))
            print(f"  {w[:12]}..     --    --       --       --       --     --      --  UNMEASURED (no truth join)")
            continue
        n_eff = r["n_eff"]
        q = r["q"]
        reasons = []
        if n_eff < MIN_NEFF_DECISION:
            reasons.append(f"n_eff<{MIN_NEFF_DECISION}")
        if q is None:
            reasons.append("degenerate cluster set" if r.get("degenerate")
                           else f"no t (n_eff<{MIN_NEFF_TEST})")
        elif q > Q_BAR:
            reasons.append(f"q>{Q_BAR:.2f}")
        if reasons:
            flagged.append((w, ",".join(reasons)))
        cm = r["n_eff_mean"] if r["n_eff_mean"] is not None else float("nan")
        print(f"  {w[:12]}.. {n_eff:>5} {r['bets']:>5} {r['xmean']:>+7.2f} {cm:>+7.2f} {r['raw_mean']:>+7.2f} "
              f"{r['t'] if r['t'] is not None else float('nan'):>+6.2f} "
              f"{(f'{q:.4f}' if q is not None else '   --'):>7}  {','.join(reasons) or 'PASS'}")
    share = len(flagged) / len(track) if track else 0.0
    print(f"\n  flagged: {len(flagged)}/{len(track)} track wallets = {100.0 * share:.1f}% "
          f"(bar: >= {100 * SHARE_BAR:.0f}%)")

    # The per-wallet FDR above is the card's rule; this is the portfolio version of the same
    # question, because a q-gated ranking would trade the SET, and 25 individually-insignificant
    # wallets can still be jointly positive.
    tr_bets = [b for b in bets if status.get(b["w"]) == "track"]
    cohort = None
    if tr_bets:
        per_mk = collections.defaultdict(list)
        for b in tr_bets:
            per_mk[b["cid"]].append(b["xedge"])
        mk_means = [statistics.mean(v) for v in per_mk.values()]
        tt = one_sample_t(mk_means)
        if tt and math.isfinite(tt[1]):
            cohort = {"bets": len(tr_bets), "markets": len(mk_means),
                      "mean_excess": statistics.mean(mk_means), "t": tt[1], "df": tt[2],
                      "p_pos": t_sf(tt[1], tt[2])}
            print(f"  cohort read: the tracked set POOLED ({cohort['bets']:,} bets in "
                  f"{cohort['markets']:,} markets) is {cohort['mean_excess']:+.2f}pp over its "
                  f"bands, market-clustered t {cohort['t']:+.2f}, one-sided p "
                  f"{cohort['p_pos']:.4f} -- the portfolio question, not the per-wallet one")

    # selection control: are the tracked wallets better than matched non-tracked wallets?
    def matched_control(reps=PERM_REPS):
        buckets = collections.defaultdict(list)
        for w, r in wallets.items():
            if status.get(w) != "track":
                b = 0 if r["n_eff"] < 3 else (1 if r["n_eff"] < 8 else (2 if r["n_eff"] < 20 else 3))
                buckets[b].append(w)
        measured = [(w, r) for w, r in ((w, wallets.get(w)) for w in track) if r]
        if len(measured) < 5:
            return None
        rnd = random.Random(11)
        obs = statistics.mean([r["xmean"] for _, r in measured])

        def bucket_of(r):
            return 0 if r["n_eff"] < 3 else (1 if r["n_eff"] < 8 else (2 if r["n_eff"] < 20 else 3))
        strat = collections.Counter(bucket_of(r) for _, r in measured)
        if any(len(buckets[b]) < strat[b] for b in strat):
            return None
        null = []
        for _ in range(reps):
            pick = [rnd.choice(buckets[b]) for b in strat for _ in range(strat[b])]
            null.append(statistics.mean([wallets[w]["xmean"] for w in pick]))
        p = sum(1 for v in null if v >= obs) / len(null)
        return {"n": len(measured), "obs": obs, "p": p,
                "null_mean": statistics.mean(null), "null_p95": sorted(null)[int(0.95 * len(null))]}

    sel = matched_control()
    if sel:
        print(f"  selection control: tracked wallets' mean excess {sel['obs']:+.2f}pp on "
              f"{sel['n']} measured wallets vs n_eff-matched non-tracked draws "
              f"{sel['null_mean']:+.2f}pp (null p95 {sel['null_p95']:+.2f}pp), "
              f"permutation p = {sel['p']:.3f}")
    else:
        print("  selection control: not enough matched non-tracked wallets to build the null")

    # ---- D. the ONE rank-correlation this card reports (guard with profit-recs #3)
    print("\n=== D. RANK PERSISTENCE -- the SAME instrument as profit-recs #3, one number ===")
    # Reproduction FIRST, on exactly the shared cache the 10-29 review read, so the check is
    # "does this code reproduce a known figure" and not "here is another number".
    shared_cache = {}
    if os.path.exists(SHARED_TRUTH):
        shared_cache = {k: v for k, v in (json.load(open(SHARED_TRUTH)).get("markets") or {}).items()
                        if v and not v.get("unsettled")}
    bets_shared = [b for b in bets if b["cid"] in shared_cache]
    prior = persistence(bets_shared, "edge")
    prho = "n/a" if prior["rho"] is None else f"{prior['rho']:+.3f}"
    print(f"  CHECK -- prior instrument, shared 4,005-market cache only (raw edge, >=8 per half, "
          f"cut 2026-08-20): rho {prho} on n={prior['n']}  "
          f"[10-29 review printed -0.100 on n=27 with this cache]")
    xp = persistence(bets, "xedge")
    xrho = "n/a" if xp["rho"] is None else f"{xp['rho']:+.3f}"
    xp_p = "n/a" if xp.get("p") is None else f"{xp['p']:.3f}"
    raw_x = persistence(bets, "edge")
    rrho = "n/a" if raw_x["rho"] is None else f"{raw_x['rho']:+.3f}"
    print(f"  THIS CARD's reading (band-excess, expanded truth, same halves/bars): rho {xrho}  "
          f"permutation p {xp_p}  on n={xp['n']} wallets   <- THE number this card reports")
    print(f"  same population, raw edge instead of band-excess (for the record, not a second "
          f"verdict): rho {rrho} on n={raw_x['n']}")

    # ---- verdict
    print("\n=== VERDICT (pre-registered on the card, applied literally) ===")
    if share >= SHARE_BAR:
        decision = "PROPOSE q-gated shadow ranking (Lane A, recommendation only, shadow-first)"
        why = (f"{100 * share:.0f}% of track wallets are not distinguishable from selection at "
               f"q<={Q_BAR} with n_eff>={MIN_NEFF_DECISION} -- at or above the 30% bar")
    elif share < SHARE_BAR and xp["rho"] is not None and xp["rho"] >= RHO_BAR and xp["n"] >= 30:
        decision = "ESCALATE -- wallet selection is real and the band thesis is incomplete"
        why = (f"only {100 * share:.0f}% flagged AND rank persistence rho {xp['rho']:+.3f} >= "
               f"+{RHO_BAR} on n={xp['n']}")
    else:
        decision = "DROP the item permanently and record the null"
        why = (f"only {100 * share:.0f}% flagged, rank persistence rho "
               f"{xp['rho'] if xp['rho'] is None else round(xp['rho'], 3)} below +{RHO_BAR}")
    print(f"  {decision}")
    print(f"  basis: {why}")

    out = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "truth_markets": len(cache), "truth_settled": len(settled),
        "truth_coverage_pct": round(100.0 * len(settled) / dist_cid, 3),
        "bets": len(bets), "wallets_with_bets": pop,
        "screened_profiles": len(status),
        "tested_family_m": m,
        "band_baseline_pp": {k: round(v, 4) for k, v in baseline.items()},
        "q_survivors_q010": len(survive),
        "track_total": len(track), "track_flagged": len(flagged),
        "track_flagged_share": round(share, 4),
        "track_flags": {w: why for w, why in flagged},
        "track_cohort": cohort,
        "selection_control": sel,
        "persistence_prior_raw": prior,
        "persistence_band_excess": xp,
        "decision": decision,
        "wallets": wallets,
    }
    if args.json:
        with open(args.json, "w") as f:
            json.dump(out, f, indent=1)
        print(f"\n  json -> {args.json}")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fetch", type=int, default=0,
                    help="fetch up to N markets of settlement truth before reporting")
    ap.add_argument("--offline", action="store_true", help="cache only (default; kept for symmetry)")
    ap.add_argument("--json", default=None, help="write the full per-wallet table here")
    return run(ap.parse_args())


if __name__ == "__main__":
    sys.exit(main())
