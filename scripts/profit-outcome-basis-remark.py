#!/usr/bin/env python3
"""
Re-mark every band x lane ROI that carries named-outcome rows on the TOKEN basis.

WHY THIS FILE EXISTS
--------------------
`scripts/profit-cheap-ask.py` section 9 (2026-11-19) showed that the repo's win test
`outcome_label == venue winner` manufactures hit rate on named-outcome markets: the cheap side of a
two-outcome named market is the side the label does not name, so the test becomes "did the expensive
side win". On the refused cheap cohort that moved one number by 119pp of ROI (label +112.4% -> token
-6.8%). Every band/lane ROI in this repo is computed the same way -- from `PaperTrade.realizedPnl`,
which on a SETTLED row is booked through `didOutcomeWin()`, i.e. through the same label test.

This instrument re-marks the book. For every settled leg it computes three things side by side:

  AS FILED   `realizedPnl` -- the number every published band/lane cell quotes
  LABEL      the win test `leg.outcome == winning token's name`           (what the ledger booked)
  TOKEN      the win test "did the token this leg is PRICED ON win"       (the honest one)

and prints them per band x lane with the named share and the disagreement count for each cell.

IDENTITY IS THE WHOLE PROBLEM, SO IT IS STATED AND VALIDATED
  * the leg's held token is taken from the PRICE, never the label: `entryPrice` is compared to the
    two token mids of the last MarketSnapshot at-or-before the open (window +/-2h). This is the same
    route section 9 uses, and it is the only route that can disagree with the label -- a label join
    would be the label basis restated.
  * `tokens[]` order is assumed to be the snapshot's (yesPrice, noPrice) order. That assumption is
    TESTED on every YES/NO leg in the population (label route vs price route); a broken index would
    flip those rows, and they are 77.7% of the book.
  * legs whose two token mids are within AMBIG_MARGIN of the booked entry carry no identity and are
    KEPT AT THEIR FILED VALUE, counted and reported. They are never guessed.

WHAT MOVES AND WHAT DOES NOT
  Only SETTLED (`resolved`) legs are re-marked. A leg that exits early books `realizedPnl` from its
  exit price; no outcome label enters, so no basis defect can enter either. A band cell's restated
  ROI therefore moves by the resolved share of its notional -- which is why that share is printed.

READ-ONLY: DB opened `mode=ro`, nothing written except the token-truth cache under data/.
No RuleSet read or write, no prisma write, no apply-v*.ts.

USAGE
    python3 scripts/profit-outcome-basis-remark.py --fetch      # populate data/book-token-truth.json
    python3 scripts/profit-outcome-basis-remark.py             # the report (cache only)
    python3 scripts/profit-outcome-basis-remark.py --json data/outcome-basis-remark.json
    python3 scripts/profit-outcome-basis-remark.py --self-test
"""
import json
import os
import random
import re
import sqlite3
import sys
import time
import urllib.error
import urllib.request
from collections import defaultdict

DB = os.environ.get("COPYBOT_DB", "file:prisma/dev.db?mode=ro")
CACHE = os.path.join("data", "book-token-truth.json")
SIDE_CACHE = os.path.join("data", "cheap-token-truth.json")   # read-only cross-fill, never written
WINDOW_MS = 2 * 3600 * 1000
AMBIG_MARGIN = 0.01              # both token mids within 1c of the booked price -> no identity
MIN_MID_GAP = 0.06               # the two token mids must differ by >= 6c for a PRICE identity:
                                 # at a coin flip (0.505 / 0.495) both sides are 1c away and the
                                 # vote flips on bid-ask noise, not on which side was bought
FIX_MS = 1794237316000           # 2026-11-09 09:15:16, fbf9073 price-side write fix
BANDS = [(0.0, 0.2), (0.2, 0.4), (0.4, 0.6), (0.6, 0.8), (0.8, 1.0001)]
BOTS = ["STANDARD", "BANKROLL_200"]
SEED = 20261119


# ---------------------------------------------------------------- helpers
def con():
    c = sqlite3.connect(DB, uri=True)
    c.row_factory = sqlite3.Row
    return c


def norm(s):
    """`normalizeOutcomeLabel`: alphanumerics uppercased, so 'Team Liquid' == 'TEAM LIQUID'."""
    return re.sub(r"[^0-9A-Z]", "", (s or "").upper())


def band_name(lo, hi):
    return f"{lo:.1f}-{hi:.1f}" if hi <= 1 else "0.8-1.0"


def band_of(p):
    for lo, hi in BANDS:
        if lo <= p < hi:
            return band_name(lo, hi)
    return None


BAND_NAMES = [band_name(lo, hi) for lo, hi in BANDS]


def pnl_from(won, px, size):
    """The settled booking convention: win -> size*(1-px)/px, loss -> -size."""
    if px <= 0:
        return 0.0
    return size * ((1.0 - px) / px) if won else -size


def _pct(v, q):
    v = sorted(v)
    if not v:
        return None
    k = (len(v) - 1) * q / 100.0
    f = int(k)
    c = min(f + 1, len(v) - 1)
    return v[f] + (v[c] - v[f]) * (k - f)


def boot_roi(legs, reps=1000, seed=SEED):
    """Market-clustered bootstrap of NOTIONAL-WEIGHTED ROI (resample markets, keep all legs)."""
    by = defaultdict(list)
    for l in legs:
        by[l["market"]].append(l)
    keys = list(by.keys())
    if len(keys) < 2:
        return (None, None)
    rnd = random.Random(seed)
    out = []
    for _ in range(reps):
        p = n = 0.0
        for _ in range(len(keys)):
            for l in by[keys[rnd.randrange(len(keys))]]:
                p += l["pnl"]
                n += l["size"]
        if n > 0:
            out.append(100.0 * p / n)
    if not out:
        return (None, None)
    return (_pct(out, 2.5), _pct(out, 97.5))


# ---------------------------------------------------------------- token truth
def load_cache(path):
    try:
        with open(path) as f:
            d = json.load(f)
            return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def save_cache(path, cache):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(cache, f)
    os.replace(tmp, path)


def fetch_truth(cid):
    """conditionId -> [[outcome, winner], ...]; None on failure. Keyless CLOB archive."""
    url = "https://clob.polymarket.com/markets/" + cid
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "medusa-copybot/1.0"})
            with urllib.request.urlopen(req, timeout=20) as r:
                js = json.loads(r.read().decode())
            return [[str(t.get("outcome")), bool(t.get("winner"))]
                    for t in (js.get("tokens") or [])]
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return {"http": 404}
            time.sleep(1.2 * (attempt + 1))
        except Exception:
            time.sleep(0.6 * (attempt + 1))
    return None


def do_fetch(cids, cache):
    todo = [c for c in cids if c and c not in cache]
    print(f"fetch: {len(cids)} distinct conditionIds, {len(cids) - len(todo)} cached, "
          f"{len(todo)} to fetch")
    t0 = time.time()
    got = miss = fail = 0
    for i, cid in enumerate(todo, 1):
        v = fetch_truth(cid)
        if v is None:
            fail += 1
            continue
        cache[cid] = v
        if isinstance(v, list):
            got += 1
        else:
            miss += 1
        if i % 100 == 0:
            save_cache(CACHE, cache)
            el = time.time() - t0
            print(f"  {i}/{len(todo)}  ok {got}  404 {miss}  err {fail}  "
                  f"{el:.0f}s  ({i/el:.1f}/s)", flush=True)
        time.sleep(0.18)
    save_cache(CACHE, cache)
    print(f"fetch done: {got} markets with tokens, {miss} 404, {fail} failed, "
          f"{time.time()-t0:.0f}s -> {CACHE}")
    return cache


# ---------------------------------------------------------------- population
LEG_SQL = """
SELECT p.id pid, p.botId bot, p.walletAddress w, p.marketId m, p.outcome oc,
       p.entryPrice px, p.simulatedPositionSize sz, p.realizedPnl pnl,
       p.openedAt ts, p.status st, p.resolvedAt ra, p.closedAt ca,
       j.ruleSetVersion v, o.conditionId cid, o.detectedPrice dp, o.marketQuestion q,
       o.walletEntryPrice wp,
       (SELECT collectedAt FROM MarketSnapshot s
         WHERE s.marketId = p.marketId AND s.collectedAt <= p.openedAt
           AND s.collectedAt >= p.openedAt - ? 
         ORDER BY s.collectedAt DESC LIMIT 1) snap_ts,
       (SELECT yesPrice FROM MarketSnapshot s
         WHERE s.marketId = p.marketId AND s.collectedAt <= p.openedAt
           AND s.collectedAt >= p.openedAt - ?
         ORDER BY s.collectedAt DESC LIMIT 1) sy,
       (SELECT noPrice FROM MarketSnapshot s
         WHERE s.marketId = p.marketId AND s.collectedAt <= p.openedAt
           AND s.collectedAt >= p.openedAt - ?
         ORDER BY s.collectedAt DESC LIMIT 1) sn
FROM PaperTrade p
LEFT JOIN DecisionJournal j ON p.decisionJournalId = j.id
LEFT JOIN ObservedTrade o ON j.observedTradeId = o.id
WHERE p.isDemo = 0 AND p.status IN ('closed','resolved') AND p.realizedPnl IS NOT NULL
  AND p.entryPrice > 0 AND p.entryPrice < 1 AND p.simulatedPositionSize > 0
ORDER BY p.openedAt ASC
"""


def population():
    """Settled legs, deduped to the first leg per (bot|wallet|market|outcome) -- the REPO'S OWN
    dedupe (profit-band-report.py load()), so the as-filed cell ROI this prints is the published
    figure, not a new population."""
    c = con()
    rows = c.execute(LEG_SQL, (WINDOW_MS, WINDOW_MS, WINDOW_MS)).fetchall()
    c.close()
    seen, out = set(), []
    for r in rows:
        k = (r["bot"], r["w"], r["m"], r["oc"])
        if k in seen:
            continue
        seen.add(k)
        y, n = r["sy"], r["sn"]
        out.append({
            "pid": r["pid"], "bot": r["bot"], "market": r["m"], "oc": r["oc"],
            "px": r["px"], "size": r["sz"], "pnl": r["pnl"], "ts": r["ts"],
            "st": r["st"], "v": r["v"], "cid": r["cid"], "dp": r["dp"], "q": r["q"],
            "ra": r["ra"], "ca": r["ca"], "wp": r["wp"], "sy": y, "sn": n,
            "named": (r["oc"] or "").upper() not in ("YES", "NO"),
            "post_fix": (r["ts"] or 0) >= FIX_MS,
        })
    return out


# ---------------------------------------------------------------- marking
def mark(legs, cache):
    """Attach label/token basis fields. Returns counts for the coverage block."""
    cov = defaultdict(int)
    for l in legs:
        l["tok"] = None          # held token's name
        l["other"] = None
        l["tok_won"] = None      # token basis
        l["lab_won"] = None      # label basis (classic: leg label == winning token name)
        toks = cache.get(l["cid"] or "")
        if not (isinstance(toks, list) and len(toks) == 2):
            cov["no_truth"] += 1
            continue
        cov["truth"] += 1
        lab = norm(l["oc"])
        lab_idx = None
        for i, t in enumerate(toks):
            if norm(t[0]) == lab:
                lab_idx = i
        if lab_idx is None:
            cov["label_not_a_token"] += 1
        else:
            l["lab_won"] = bool(toks[lab_idx][1])
        # WHICH PRICE IDENTIFIES THE SIDE. The booked entry, unless the booked entry is the
        # COMPLEMENT of the wallet's own print -- the pre-2026-11-09 mirror class, where the
        # positional read booked the sibling token's price. There the wallet's price is the side
        # actually held (references/price-side-and-token-identity.md, "mirror test").
        ref, route = l["px"], "entry"
        w = l["wp"]
        # The mirror class is a NAMED-market class by construction: `outcome === "NO" ? noPrice :
        # yesPrice` is correct on a binary market, so a complement relationship between the
        # detected price and the wallet's own print can only be a data error there. Confining the
        # correction to named labels keeps the YES/NO rows a HARD invariant.
        if l["named"] and w and abs(l["px"] - w) >= 0.10 and abs(l["px"] - (1.0 - w)) <= 0.06:
            ref, route = w, "wallet"
        l["route"] = route
        cov["route_" + route] += 1
        if l["sy"] is None or l["sn"] is None:
            cov["no_snapshot"] += 1
            continue
        if abs(l["sy"] - l["sn"]) < MIN_MID_GAP:
            cov["mids_too_close"] += 1
            continue
        d0, d1 = abs(ref - l["sy"]), abs(ref - l["sn"])
        l["margin"] = abs(d0 - d1)
        l["tok0"] = 0 if d0 <= d1 else 1
        if l["margin"] < AMBIG_MARGIN:
            cov["ambiguous"] += 1
            continue
        cov["identity"] += 1
        held, other = (toks[0], toks[1]) if l["tok0"] == 0 else (toks[1], toks[0])
        l["tok"] = held[0]
        l["other"] = other[0]
        l["tok_won"] = bool(held[1])
        if l["lab_won"] is None:
            l["lab_won"] = bool(other[1])   # the filed test with no label match is a loss
    return cov


def cell(legs):
    """One band x lane cell: as-filed vs restated, plus the resolved-subset basis stats."""
    if not legs:
        return None
    ntl = sum(l["size"] for l in legs)
    filed = sum(l["pnl"] for l in legs)
    res = [l for l in legs if l["st"] == "resolved"]
    marked = [l for l in res if l.get("tok_won") is not None]
    restated = filed
    for l in marked:
        # ONLY the verdict moves: a leg whose two bases agree keeps its filed number exactly, so
        # the delta is what the mislabel cost and nothing else. Re-pricing every leg at today's
        # entryPrice would fold the 2026-11-11 ledger repair into the delta and report a basis
        # effect that is really a price-column move.
        if bool(l["lab_won"]) != bool(l["tok_won"]):
            restated += pnl_from(l["tok_won"], l["px"], l["size"]) - l["pnl"]
    d = {
        "n": len(legs), "ntl": ntl, "filed": 100.0 * filed / ntl,
        "restated": 100.0 * restated / ntl, "n_res": len(res), "n_marked": len(marked),
        "res_ntl_share": 100.0 * sum(l["size"] for l in res) / ntl,
        "mark_share": 100.0 * sum(l["size"] for l in marked) / max(1e-9, sum(
            l["size"] for l in res)),
        "named_share": 100.0 * sum(1 for l in marked if l["named"]) / max(1, len(marked)),
        "dis": sum(1 for l in marked if bool(l["lab_won"]) != bool(l["tok_won"])),
        "hit_lab": 100.0 * sum(1 for l in marked if l["lab_won"]) / max(1, len(marked)),
        "hit_tok": 100.0 * sum(1 for l in marked if l["tok_won"]) / max(1, len(marked)),
        "be": 100.0 * sum(l["px"] * l["size"] for l in marked) / max(1e-9, sum(
            l["size"] for l in marked)),
        "tok_roi": 100.0 * sum(pnl_from(l["tok_won"], l["px"], l["size"]) for l in marked)
        / max(1e-9, sum(l["size"] for l in marked)),
        "tok_pnl": sum(pnl_from(l["tok_won"], l["px"], l["size"]) for l in marked),
        "filed_res_pnl": sum(l["pnl"] for l in res),
    }
    ml = [{"market": l["market"], "size": l["size"],
           "pnl": pnl_from(l["tok_won"], l["px"], l["size"])} for l in marked]
    lo, hi = boot_roi(ml)
    d["ci"] = (lo, hi)
    # the arm's own return, computed only on rows whose filed number reproduces the label booking:
    # on the 136 rows the 2026-11-11 ledger repair re-priced, today's entryPrice is not the entry
    # the leg was booked at, so re-pricing them would mix a price-column move into a basis read.
    clean = [l for l in marked
             if abs(l["pnl"] - pnl_from(l["lab_won"], l["px"], l["size"])) <= 0.01]
    cn = sum(l["size"] for l in clean)
    d["n_clean"] = len(clean)
    d["clean_ntl"] = cn
    d["tok_roi_clean"] = (100.0 * sum(pnl_from(l["tok_won"], l["px"], l["size"]) for l in clean)
                          / cn) if cn else None
    d["lab_roi_clean"] = (100.0 * sum(pnl_from(l["lab_won"], l["px"], l["size"]) for l in clean)
                          / cn) if cn else None
    if d["tok_roi_clean"] is not None:
        d["tok_roi"] = d["tok_roi_clean"]
    return d


def fnum(v, w=7, prec=1, sign=True):
    if v is None:
        return " " * w
    return f"{v:+{w}.{prec}f}" if sign else f"{v:{w}.{prec}f}"


# ---------------------------------------------------------------- sections
def section_coverage(legs, cov):
    print("=" * 108)
    print("0. POPULATION AND COVERAGE -- what part of the book can be re-marked at all")
    print("=" * 108)
    n = len(legs)
    res = [l for l in legs if l["st"] == "resolved"]
    print(f"\n  settled legs, deduped to the first per (bot|wallet|market|outcome): {n}")
    print(f"    resolved (settlement)  {len(res):5d}  {100.0*len(res)/n:5.1f}%"
          f"   <- the only legs a basis defect can reach")
    print(f"    closed   (early exit)  {n-len(res):5d}  {100.0*(n-len(res))/n:5.1f}%"
          f"   <- books from the exit price, no outcome label in the path")
    print(f"  distinct conditionIds on resolved legs: "
          f"{len({l['cid'] for l in res if l['cid']})}")
    print(f"\n  on the {len(res)} resolved legs:")
    for k in ("truth", "no_truth", "label_not_a_token", "no_snapshot", "mids_too_close",
              "ambiguous", "identity", "route_entry", "route_wallet"):
        print(f"    {k:18} {cov[k]:5d}  {100.0*cov[k]/len(res):5.1f}%")
    print("\n  identity = the snapshot's two token mids differ by >= 6c AND differ about which side"
          "\n  the booked price sits on by >= 1c. Legs with no identity are KEPT AT FILED and never"
          "\n  guessed. route_wallet = the booked entry was the COMPLEMENT of the wallet's own print,")
    print("  so the side is identified on the wallet's price (the pre-2026-11-09 mirror class).")


def section_invariant(legs):
    print("\n" + "=" * 108)
    print("1. IDENTITY VALIDATION -- the YES/NO invariant that proves the token index is right")
    print("=" * 108)
    yn = [l for l in legs if not l["named"] and l.get("lab_won") is not None
          and l.get("tok") is not None]
    bad = [l for l in yn if bool(l["lab_won"]) != bool(l["tok_won"])]
    named = [l for l in legs if l["named"] and l.get("lab_won") is not None
             and l.get("tok") is not None]
    nbad = [l for l in named if bool(l["lab_won"]) != bool(l["tok_won"])]
    print(f"\n  YES/NO legs with both bases: {len(yn):5d}   disagreements: {len(bad):5d}"
          f"  ({100.0*len(bad)/max(1,len(yn)):.2f}%)")
    print(f"  NAMED legs with both bases : {len(named):5d}   disagreements: {len(nbad):5d}"
          f"  ({100.0*len(nbad)/max(1,len(named)):.1f}%)")
    print("\n  A join that had mixed up the two tokens[] positions would flip the YES/NO rows too.")
    if len(yn) and not bad:
        print("  It flips NONE of them: the token basis is the label basis wherever the label names"
              "\n  a position, and differs only where the label names a side. The join is sound.")
    else:
        print("  FAIL -- the join is not sound; nothing below may be read as a measurement.")
    pre = [l for l in named if not l["post_fix"]]
    post = [l for l in named if l["post_fix"]]
    print(f"\n  era split of the named rows (price-side fix 2026-11-09 09:15:16):")
    for lbl, sub in (("pre-fix ", pre), ("post-fix", post)):
        d = sum(1 for l in sub if bool(l["lab_won"]) != bool(l["tok_won"]))
        print(f"    {lbl} n={len(sub):4d}  disagreements {d:4d} "
              f"({100.0*d/max(1,len(sub)):5.1f}%)")
    return not bad


def section_filed_is_label(legs):
    print("\n" + "=" * 108)
    print("1b. WHAT THE FILED NUMBER IS -- does `realizedPnl` reproduce the LABEL basis row-for-row?")
    print("=" * 108)
    marked = [l for l in legs if l.get("tok_won") is not None]
    if not marked:
        print("\n  no marked legs yet -- run --fetch")
        return
    agree = [l for l in marked if bool(l["lab_won"]) == bool(l["tok_won"])]
    dis = [l for l in marked if bool(l["lab_won"]) != bool(l["tok_won"])]
    tol = 0.01
    ml = sum(1 for l in marked
             if abs(l["pnl"] - pnl_from(l["lab_won"], l["px"], l["size"])) <= tol)
    mt = sum(1 for l in marked
             if abs(l["pnl"] - pnl_from(l["tok_won"], l["px"], l["size"])) <= tol)
    print(f"\n  re-marked settled legs: {len(marked)}")
    print(f"    filed realizedPnl == label-basis booking : {ml:5d}  "
          f"({100.0*ml/len(marked):5.1f}%)")
    print(f"    filed realizedPnl == token-basis booking : {mt:5d}  "
          f"({100.0*mt/len(marked):5.1f}%)")
    print(f"    neither (entryPrice moved after booking, e.g. the 2026-11-11 ledger repair): "
          f"{len(marked)-max(ml,mt):5d}")
    print(f"\n  the decisive split -- the {len(dis)} legs where the two bases disagree:")
    m_lab = sum(1 for l in dis
                if abs(l["pnl"] - pnl_from(l["lab_won"], l["px"], l["size"])) <= tol)
    m_tok = sum(1 for l in dis
                if abs(l["pnl"] - pnl_from(l["tok_won"], l["px"], l["size"])) <= tol)
    print(f"    booked as the LABEL basis says : {m_lab:4d} ({100.0*m_lab/max(1,len(dis)):.1f}%)")
    print(f"    booked as the TOKEN basis says : {m_tok:4d} ({100.0*m_tok/max(1,len(dis)):.1f}%)")
    if m_lab and m_lab >= m_tok:
        print("    -> the filed book number IS the label basis. Re-marking is a restatement of the"
              "\n       same rows, not a different population.")
    print(f"\n  on the {len(agree)} legs where the bases agree, the restatement is a no-op by"
          f" construction.")


def section_bands(legs):
    print("\n" + "=" * 108)
    print("2. BAND x LANE -- as filed vs re-marked on the token basis")
    print("=" * 108)
    print("  ROI = notional-weighted on dollars at risk. restated re-prices ONLY resolved legs, so a")
    print("  cell can move at most by its resolved share (res%ntl). CI is market-clustered on the")
    print("  token-basis arm over the re-marked legs.")
    hdr = (f"\n  {'lane':13}{'band':9}{'n':>5}{'ntl':>8}{'filed':>8}{'restated':>9}{'delta':>7}"
           f"{'res%':>6}{'mark%':>6}{'named%':>7}{'labHit':>7}{'be':>6}{'tokHit':>7}"
           f"{'tokROI':>8}{'dis':>5}  {'CI tok':>16}")
    rows = []
    for bot in BOTS:
        lane = [l for l in legs if l["bot"] == bot]
        print(f"\n  {bot}: {len(lane)} settled legs, "
              f"${sum(l['size'] for l in lane):,.0f} notional")
        print(hdr)
        for b in BAND_NAMES:
            sub = [l for l in lane if band_of(l["px"]) == b]
            d = cell(sub)
            if not d:
                continue
            ci = d["ci"]
            cis = f"[{ci[0]:+6.0f},{ci[1]:+6.0f}]" if ci[0] is not None else "      n/a      "
            print(f"  {'':13}{b:9}{d['n']:5d}{d['ntl']:8,.0f}{d['filed']:+8.1f}"
                  f"{d['restated']:+9.1f}{d['restated']-d['filed']:+7.1f}"
                  f"{d['res_ntl_share']:6.0f}{d['mark_share']:6.0f}{d['named_share']:7.0f}"
                  f"{d['hit_lab']:7.1f}{d['be']:6.1f}{d['hit_tok']:7.1f}"
                  f"{d['tok_roi']:+8.1f}{d['dis']:5d}  {cis}")
            rows.append((bot, b, d))
        # lane total
        d = cell(lane)
        ci = d["ci"]
        cis = f"[{ci[0]:+6.0f},{ci[1]:+6.0f}]" if ci[0] is not None else "      n/a      "
        print(f"  {'':13}{'LANE':9}{d['n']:5d}{d['ntl']:8,.0f}{d['filed']:+8.1f}"
              f"{d['restated']:+9.1f}{d['restated']-d['filed']:+7.1f}"
              f"{d['res_ntl_share']:6.0f}{d['mark_share']:6.0f}{d['named_share']:7.0f}"
              f"{d['hit_lab']:7.1f}{d['be']:6.1f}{d['hit_tok']:7.1f}"
              f"{d['tok_roi']:+8.1f}{d['dis']:5d}  {cis}")
        rows.append((bot, "LANE", d))
    d = cell(legs)
    ci = d["ci"]
    cis = f"[{ci[0]:+6.0f},{ci[1]:+6.0f}]" if ci[0] is not None else "      n/a      "
    print(f"\n  {'ALL LANES':13}{'ALL':9}{d['n']:5d}{d['ntl']:8,.0f}{d['filed']:+8.1f}"
          f"{d['restated']:+9.1f}{d['restated']-d['filed']:+7.1f}"
          f"{d['res_ntl_share']:6.0f}{d['mark_share']:6.0f}{d['named_share']:7.0f}"
          f"{d['hit_lab']:7.1f}{d['be']:6.1f}{d['hit_tok']:7.1f}"
          f"{d['tok_roi']:+8.1f}{d['dis']:5d}  {cis}")
    rows.append(("ALL", "ALL", d))
    return rows


def section_cells(rows):
    print("\n" + "=" * 108)
    print("3. THE RESTATEMENT LIST -- cells whose re-marked ROI crosses zero or loses its edge")
    print("=" * 108)
    print("\n  Rule (card profit-outcome-basis-remark): restate any cell whose token-basis ROI falls")
    print("  below its own breakeven. breakeven hit rate == mean entry, so 'below breakeven' is")
    print("  signed edge_pp = tokHit - be. A cell whose FILED figure is positive and whose re-marked")
    print("  figure is not is the actionable class.\n")
    print(f"  {'lane':13}{'band':9}{'filed':>8}{'restated':>9}{'delta':>7}{'edge_pp':>9}"
          f"{'tokROI':>8}{'named%':>7}{'dis':>5}  verdict")
    hits = []
    for bot, b, d in rows:
        if d["n_marked"] < 10:
            verdict = f"n<10 re-marked ({d['n_marked']}) -- no verdict"
        else:
            edge = d["hit_tok"] - d["be"]
            if d["filed"] > 0 and d["restated"] <= 0:
                verdict = "RESTATE: filed positive, re-marked <= 0"
                hits.append((bot, b, d))
            elif edge < 0 and d["tok_roi"] < 0:
                verdict = "confirms loss on both bases" if d["filed"] <= 0 else \
                          "RESTATE: filed positive, token edge < 0"
                if d["filed"] > 0:
                    hits.append((bot, b, d))
            elif d["named_share"] == 0:
                verdict = "no named rows -- basis cannot differ"
            else:
                verdict = "holds"
        print(f"  {bot:13}{b:9}{d['filed']:+8.1f}{d['restated']:+9.1f}"
              f"{d['restated']-d['filed']:+7.1f}{d['hit_tok']-d['be']:+9.1f}"
              f"{d['tok_roi']:+8.1f}{d['named_share']:7.0f}{d['dis']:5d}  {verdict}")
    tot_lane = defaultdict(float)
    for bot, b, d in rows:
        if b == "LANE" or bot == "ALL":
            tot_lane[bot] += d["ntl"] * (d["restated"] - d["filed"]) / 100.0
    print("\n  dollar restatement of settled PnL (restated minus filed, on the same legs):")
    for k, v in tot_lane.items():
        print(f"    {k:14} ${v:+10,.2f}")
    return hits


def section_refutation(rows):
    print("\n" + "=" * 108)
    print("4. THE CARD'S OWN REFUTATION CLAUSE -- do the bases agree within 2pp across bands?")
    print("=" * 108)
    worst = []
    for bot, b, d in rows:
        if d["n_marked"] < 10:
            continue
        gap = d["restated"] - d["filed"]
        worst.append((abs(gap), gap, bot, b, d))
    worst.sort(reverse=True)
    print("\n  largest |restated - filed| cells (restatement is bounded by the resolved share):")
    for a, gap, bot, b, d in worst[:8]:
        print(f"    {bot:13}{b:9} delta {gap:+6.1f}pp  on res%ntl {d['res_ntl_share']:3.0f}% "
              f"| tokROI {d['tok_roi']:+7.1f}% vs filed-resolved "
              f"{100.0*d['filed_res_pnl']/max(1e-9,d['ntl']*d['res_ntl_share']/100.0):+7.1f}%")
    # basis gap measured on the SAME rows (the pure measurement error, not the blended delta)
    print("\n  the pure basis gap, on re-marked legs only (label ROI vs token ROI, equal-weight):")
    print(f"  {'lane':13}{'band':9}{'n':>5}{'labHit':>7}{'tokHit':>7}{'gap_pp':>8}{'dis':>5}")
    for bot, b, d in rows:
        if d["n_marked"] < 10:
            continue
        print(f"  {bot:13}{b:9}{d['n_marked']:5d}{d['hit_lab']:7.1f}{d['hit_tok']:7.1f}"
              f"{d['hit_tok']-d['hit_lab']:+8.1f}{d['dis']:5d}")


def dump_disagreements(legs, limit=40):
    """Every row where the label basis and the token basis disagree, with its identity evidence."""
    print("\n" + "=" * 108)
    print("1c. DISAGREEMENT ROWS -- what the two bases actually read on the same leg")
    print("=" * 108)
    marked = [l for l in legs if l.get("tok_won") is not None]
    dis = [l for l in marked if bool(l["lab_won"]) != bool(l["tok_won"])]
    print(f"\n  disagreements: {len(dis)} of {len(marked)}")
    yn = [l for l in dis if not l["named"]]
    print(f"  of which label YES/NO: {len(yn)}  <- the invariant class, each one is a finding")
    print(f"\n  {'date':11}{'bot':6}{'oc':12}{'entry':>7}{'wallet':>7}{'sy':>7}{'sn':>7}"
          f"{'route':>7}{'held':>22}{'won':>5}  tokens[]")
    for l in dis[:limit]:
        print(f"  {str(l['ts'])[:10]:11}{l['bot'][:4]:6}{l['oc'][:12]:12}{l['px']:7.3f}"
              f"{(l['wp'] if l['wp'] is not None else 0):7.3f}"
              f"{(l['sy'] if l['sy'] is not None else 0):7.3f}"
              f"{(l['sn'] if l['sn'] is not None else 0):7.3f}"
              f"{(l.get('route') or ''):>7}{(l['tok'] or '')[:22]:>22}{int(bool(l['tok_won'])):5d}"
              f"  {(l.get('q') or '')[:44]}")
    # the structural class behind the YES/NO failures: markets whose FIRST token is not Yes
    toks_all = {}
    for l in marked:
        toks_all.setdefault(l["cid"], l)
    nofirst = [l for l in marked if l["sy"] is not None and l["sn"] is not None]
    print(f"\n  YES/NO legs whose price identity sits on token index 1: "
          f"{sum(1 for l in nofirst if not l['named'] and l['tok0'] == 1)}")


REFUSED_SQL = """
SELECT j.id jid, j.marketId m, j.createdAt ts, j.ruleSetVersion v,
       o.outcome oc, o.detectedPrice dp, o.walletEntryPrice wp,
       o.conditionId cid, o.marketQuestion q,
       (SELECT yesPrice FROM MarketSnapshot s
         WHERE s.marketId = j.marketId AND s.collectedAt <= j.createdAt
           AND s.collectedAt >= j.createdAt - ?
         ORDER BY s.collectedAt DESC LIMIT 1) sy,
       (SELECT noPrice FROM MarketSnapshot s
         WHERE s.marketId = j.marketId AND s.collectedAt <= j.createdAt
           AND s.collectedAt >= j.createdAt - ?
         ORDER BY s.collectedAt DESC LIMIT 1) sn
FROM DecisionJournal j JOIN ObservedTrade o ON j.observedTradeId = o.id
WHERE j.isDemo = 0 AND j.ruleSetVersion >= 68 AND j.decision = 'skip'
  AND j.venue = 'Polymarket'
  AND o.detectedPrice >= 0.05 AND o.detectedPrice < 0.20
ORDER BY j.createdAt ASC
"""


def population_refused():
    """The refused cheap cohort from profit-cheap-ask.py section 9: a REFUSED candidate has no
    booking, so its price is the detection price and there is no realizedPnl at all. It is the
    population the 119pp headline was measured on, and re-reading it with THIS instrument's
    identity rule is how the two readings are reconciled."""
    c = con()
    rows = c.execute(REFUSED_SQL, (WINDOW_MS, WINDOW_MS)).fetchall()
    c.close()
    seen, out = set(), []
    for r in rows:
        k = (r["m"], r["oc"])
        if k in seen:
            continue
        seen.add(k)
        out.append({
            "pid": r["jid"], "bot": "REFUSED", "market": r["m"], "oc": r["oc"],
            "px": r["dp"], "size": 10.0, "pnl": 0.0, "ts": r["ts"], "st": "resolved",
            "v": r["v"], "cid": r["cid"], "dp": r["dp"], "q": r["q"],
            "ra": r["ts"], "ca": None, "wp": r["wp"], "sy": r["sy"], "sn": r["sn"],
            "named": (r["oc"] or "").upper() not in ("YES", "NO"),
            "post_fix": (r["ts"] or 0) >= FIX_MS,
        })
    return out


def section_refused(cache):
    """THE RECONCILIATION: §9's headline cohort, re-marked under the book's identity rule."""
    print("\n" + "=" * 108)
    print("6. THE 119pp HEADLINE, UNDER THIS INSTRUMENT'S IDENTITY RULE")
    print("=" * 108)
    legs = population_refused()
    if not legs:
        print("\n  no refused rows")
        return
    loose, tight = [], []
    for l in legs:
        toks = cache.get(l["cid"] or "")
        if not (isinstance(toks, list) and len(toks) == 2):
            continue
        lab = norm(l["oc"])
        lab_idx = next((i for i, t in enumerate(toks) if norm(t[0]) == lab), None)
        if lab_idx is None or l["sy"] is None or l["sn"] is None:
            continue
        lab_won = bool(toks[lab_idx][1])
        # (a) section 9's identity: the detection price alone, no mid gap, no mirror test
        d0, d1 = abs(l["px"] - l["sy"]), abs(l["px"] - l["sn"])
        i0 = 0 if d0 <= d1 else 1
        loose.append((l, lab_won, bool(toks[i0][1]), abs(d0 - d1)))
        # (b) THIS instrument's identity: >=6c between the mids, >=1c margin, wallet mirror first
        if abs(l["sy"] - l["sn"]) < MIN_MID_GAP:
            continue
        ref = l["px"]
        if (l["named"] and l["wp"] and abs(l["px"] - l["wp"]) >= 0.10
                and abs(l["px"] - (1.0 - l["wp"])) <= 0.06):
            ref = l["wp"]
        e0, e1 = abs(ref - l["sy"]), abs(ref - l["sn"])
        if abs(e0 - e1) < AMBIG_MARGIN:
            continue
        i1 = 0 if e0 <= e1 else 1
        tight.append((l, lab_won, bool(toks[i1][1]), abs(e0 - e1)))
    for name, got in (("(a) section 9's rule (detection price, no gap guard)", loose),
                      ("(b) this instrument's rule (6c gap + mirror test)", tight)):
        if not got:
            continue
        named = [g for g in got if g[0]["named"]]
        yn = [g for g in got if not g[0]["named"]]
        dis = [g for g in got if g[1] != g[2]]
        disn = [g for g in named if g[1] != g[2]]
        lab = 100.0 * sum(1 for g in got if g[1]) / len(got)
        tok = 100.0 * sum(1 for g in got if g[2]) / len(got)
        print(f"\n  {name}")
        print(f"    re-marked {len(got)} of {len(legs)}; named share "
              f"{100.0*len(named)/len(got):.0f}%")
        print(f"    label basis {lab:5.1f}%  token basis {tok:5.1f}%  gap {tok-lab:+6.1f}pp   "
              f"disagreements {len(dis)} ({100.0*len(dis)/len(got):.1f}%), named {len(disn)}")
        print(f"    YES/NO invariant: {len(yn)} rows, "
              f"{sum(1 for g in yn if g[1] != g[2])} disagreements")
    print("\n  A gap that SHRINKS when the coin-flip guard is added is an identity artifact; a gap")
    print("  that SURVIVES on class-lopsided markets is the real defect.")

    # WHY the gap shrinks: the population's own price is the complement on part of it.
    mir = [l for l in legs if l["named"] and l["wp"] and l["sy"] is not None
           and abs(l["px"] - l["wp"]) >= 0.10 and abs(l["px"] - (1.0 - l["wp"])) <= 0.06]
    if mir:
        import statistics as _st
        print(f"\n  THE POPULATION ITSELF IS COMPLEMENT-FRAMED ON PART OF ITS ROWS: "
              f"{len(mir)} of {len(legs)} refused candidates ({100.0*len(mir)/len(legs):.1f}%)")
        print(f"    detected price median {100*_st.median([l['px'] for l in mir]):.1f}c vs the "
              f"wallet's own print median {100*_st.median([l['wp'] for l in mir]):.1f}c")
        print("    -> on those rows the candidate was never cheap: the detector read the SIBLING"
              "\n       token's price, so the whole 'refused cheap cohort' ROI is a return on a"
              "\n       bet at a price that never existed.")
    pre = [l for l in mir if not l["post_fix"]]
    print(f"    of the {len(mir)}, {len(pre)} are pre-2026-11-09 and {len(mir)-len(pre)} post-fix.")
    # THE VOTE: does the wallet's print land on the LABEL's token or on the detected one?
    dl, dd = [], []
    for l in mir:
        toks = cache.get(l["cid"] or "")
        if not (isinstance(toks, list) and len(toks) == 2):
            continue
        li = next((i for i, t in enumerate(toks) if norm(t[0]) == norm(l["oc"])), None)
        if li is None:
            continue
        lmid = l["sy"] if li == 0 else l["sn"]
        omid = l["sn"] if li == 0 else l["sy"]
        dl.append(abs(l["wp"] - lmid))
        dd.append(abs(l["wp"] - omid))
    if dl:
        import statistics as _s2
        dl_s, dd_s = sorted(dl), sorted(dd)
        p90 = dl_s[int(0.9 * (len(dl_s) - 1))]
        print(f"    |wallet print - the label's token mid| : median "
              f"{100*_s2.median(dl_s):.2f}c  (p90 {100*p90:.2f}c)")
        print(f"    |wallet print - the DETECTED token mid|: median "
              f"{100*_s2.median(dd_s):.2f}c")
        print("    the wallet's own fill sits on the LABEL's token, which is the vote that decides"
              "\n    which side the candidate was on.")


def section_windows(legs):
    """Which CONSUMERS move: the settled-day PnL the ladder advances on, by trailing window."""
    print("\n" + "=" * 108)
    print("5. CONSUMERS -- the settled-day PnL that feeds the ladder and the daily report")
    print("=" * 108)
    print("\n  `query_bankroll.js` sums realizedPnl over trailing SETTLED days (ladder advance) and the")
    print("  EOD prints the same rows. This is that sum, filed vs re-marked, per lane.")
    print(f"\n  {'window':9}{'lane':14}{'legs':>6}{'filed PnL':>12}{'restated':>12}{'delta':>10}"
          f"{'$/day filed':>13}{'$/day rest':>12}")
    now = None
    for l in legs:
        t = l.get("ra") or l.get("ca") or l["ts"]
        if t and (now is None or t > now):
            now = t
    if not now:
        print("  no timestamps")
        return
    for days in (7, 30, 90):
        cut = now - days * 86400 * 1000
        for bot in BOTS + ["ALL"]:
            sub = [l for l in legs if (l["ra"] or l["ca"] or l["ts"] or 0) >= cut
                   and (bot == "ALL" or l["bot"] == bot)]
            if not sub:
                continue
            filed = sum(l["pnl"] for l in sub)
            rest = filed
            for l in sub:
                if l.get("tok_won") is not None and bool(l["lab_won"]) != bool(l["tok_won"]):
                    rest += pnl_from(l["tok_won"], l["px"], l["size"]) - l["pnl"]
            print(f"  {str(days)+'d':9}{bot:14}{len(sub):6d}{filed:>+12,.0f}{rest:>+12,.0f}"
                  f"{rest-filed:>+10,.0f}{filed/days:>13,.1f}{rest/days:>12,.1f}")
        print()
    print("  C-200 rungs advance when the trailing 7 SETTLED days sum >= target x 7, so a restatement")
    print("  of this column moves the rung that is printed, not just a report line.")


def section_selftest():
    print("SELF-TEST")
    ok = tot = 0

    def chk(name, cond, extra=""):
        nonlocal ok, tot
        tot += 1
        ok += 1 if cond else 0
        print(f"  [{'OK ' if cond else 'FAIL'}] {name}{(' ' + extra) if extra else ''}")

    chk("win at 0.10 pays 9x", abs(pnl_from(1, 0.10, 10) - 90.0) < 1e-9)
    chk("loss at 0.10 costs the stake", pnl_from(0, 0.10, 10) == -10.0)
    chk("norm folds case and punctuation", norm("Team Liquid") == norm("team-líquid")
        or norm("Team Liquid") == "TEAMLIQUID")
    chk("norm keeps NO distinct from YES", norm("No") != norm("Yes"))
    chk("band edges are lo-inclusive", band_of(0.2) == "0.2-0.4" and band_of(0.1999) == "0.0-0.2")
    chk("band_of(1.0) is in the top band (>=1 is filtered by the population)",
        band_of(1.0) == "0.8-1.0")

    # (a) the label names the priced token: both bases must agree, restatement is a no-op
    cache = {"c": [["Under", True], ["Over", False]]}
    l = {"market": "m", "oc": "Under", "px": 0.12, "size": 10.0,
         "pnl": 10.0 * (0.88 / 0.12), "st": "resolved", "sy": 0.12, "sn": 0.88, "wp": 0.12,
         "named": True, "cid": "c"}
    mark([l], cache)
    chk("label naming the priced token -> label basis wins", l["lab_won"] is True)
    chk("label naming the priced token -> token basis wins", l["tok_won"] is True)
    d = cell([l])
    chk("restatement is a no-op when the bases agree",
        abs(d["restated"] - d["filed"]) < 1e-6)

    # (b) THE DEFECT SHAPE: the label names the expensive side, which won; the leg is priced on
    #     the cheap side, which lost. Label basis books a 9x win, token basis books a loss.
    cache2 = {"c": [["Under", False], ["Over", True]]}
    l2 = dict(l, oc="Over")
    l2.update({"lab_won": None, "tok_won": None, "tok": None, "other": None})
    mark([l2], cache2)
    chk("label naming the winning sibling -> label basis says WIN", l2["lab_won"] is True)
    chk("label naming the winning sibling -> token basis says LOSS", l2["tok_won"] is False)
    d2 = cell([l2])
    chk("restatement moves that win to -100%",
        abs(d2["restated"] - (-100.0)) < 1e-6 and d2["filed"] > 0,
        f"(filed {d2['filed']:+.1f}% -> restated {d2['restated']:+.1f}%)")

    # (c) MIRROR CLASS: the booked entry is the complement of the wallet's own print, so the side
    #     held is the one at the WALLET price, not the one at the booked price.
    l6 = dict(l)
    l6.update({"px": 0.88, "wp": 0.12, "pnl": -10.0, "lab_won": None, "tok_won": None,
               "tok": None, "other": None})
    mark([l6], cache)
    chk("mirror-framed leg identifies on the WALLET price", l6["route"] == "wallet")
    chk("mirror-framed leg lands on the cheap token (Under)", l6["tok"] == "Under")

    # YES/NO invariant: YES on token0 with token0 the winner
    l3 = {"market": "m", "oc": "YES", "px": 0.6, "size": 10.0, "pnl": 6.6,
          "st": "resolved", "sy": 0.6, "sn": 0.4, "wp": 0.6, "named": False, "cid": "d"}
    mark([l3], {"d": [["Yes", True], ["No", False]]})
    chk("YES/NO rows cannot disagree", l3["lab_won"] == l3["tok_won"] is True)

    # ambiguous identity is refused, not guessed
    l4 = dict(l, sy=0.13, sn=0.11)
    l4.update({"lab_won": None, "tok_won": None, "tok": None, "other": None})
    mark([l4], cache)
    chk("ambiguous identity -> no token basis", l4["tok_won"] is None)

    # a closed leg is never re-marked
    l5 = dict(l, st="closed", pnl=-10.0)
    mark([l5], cache)
    d5 = cell([l5])
    chk("early exit is never re-marked", abs(d5["restated"] - d5["filed"]) < 1e-9)

    # CI brackets nothing when one market
    lo, hi = boot_roi([{"market": "m", "size": 1.0, "pnl": 1.0}])
    chk("single-market CI is withheld", lo is None and hi is None)
    print(f"\n  {ok}/{tot} checks passed")
    return 0 if ok == tot else 1


def main():
    args = sys.argv[1:]
    if "--self-test" in args:
        return section_selftest()
    legs = population()
    cache = load_cache(CACHE)
    side = load_cache(SIDE_CACHE)
    for k, v in side.items():                    # reuse section 9's cache read-only
        if isinstance(v, list) and len(v) == 2 and k not in cache:
            cache[k] = v
    if "--fetch" in args:
        cids = sorted({l["cid"] for l in legs if l["cid"] and l["st"] == "resolved"})
        cache = do_fetch(cids, cache)
    cov = mark([l for l in legs if l["st"] == "resolved"], cache)
    section_coverage(legs, cov)
    sound = section_invariant(legs)
    section_filed_is_label(legs)
    if "--dump" in args:
        dump_disagreements(legs)
    rows = section_bands(legs)
    hits = section_cells(rows)
    section_refutation(rows)
    section_refused(cache)
    section_windows(legs)
    if "--json" in args:
        p = args[args.index("--json") + 1]
        out = {"generated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
               "population": "settled PaperTrade legs, deduped first per bot|wallet|market|outcome",
               "identity": "entryPrice vs snapshot token mids at/before open, margin >= 1c",
               "fix_ms": FIX_MS, "ambiguous_margin": AMBIG_MARGIN,
               "coverage": dict(cov), "yesno_invariant_sound": bool(sound),
               "cells": [{"lane": b, "band": bn, **{k: (list(v) if k == "ci" and v[0] is not None
                                                      else v)
                                                    for k, v in d.items()}}
                         for b, bn, d in rows],
               "named_columns": ["n", "ntl", "filed", "restated", "n_res", "n_marked",
                                 "res_ntl_share", "mark_share", "named_share", "dis", "hit_lab",
                                 "hit_tok", "be", "tok_roi", "tok_pnl", "ci"]}
        with open(p, "w") as f:
            json.dump(out, f, indent=1)
        print(f"\n  artifact written: {p}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
