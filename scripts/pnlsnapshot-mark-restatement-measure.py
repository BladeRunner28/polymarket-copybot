#!/usr/bin/env python3
"""pnlsnapshot-mark-restatement-measure.py -- READ-ONLY measurement + restatement
PRICING for card `pnlsnapshot-mark-restatement` (Lane A: proposal only; this script
writes nothing to the DB, it opens it `mode=ro`).

Population: the 233 finished PaperTrade legs repaired by `apply-ledger-price-side.py`
(approval apr-ledger-price-side-repair, applied 2026-11-11T18:39:34Z), and every
PnlSnapshot mark row attached to them (2,680 rows).

What it measures, per mark row:
 (a) PHASE -- pre-fix (before the write fix, update-pnl commit fbf9073 at
     2026-11-09T15:15:16Z), post-fix (fix on, ledger repair not yet applied), or
     repair-appended (the 196 corrected finals the repair appended; identified by
     snapshotId inside the applied ledger, NOT by timestamp -- the repair backdates
     them to the leg's end time).
 (b) FRAME -- is the stored mark price the SIBLING token's price (the pre-fix
     positional read) or the leg's OWN token's price? The leg's token index comes
     from the venue's own archived token list (CLOB /markets/<conditionId>, keyless);
     the price comes from the nearest stored MarketSnapshot of that market
     (yesPrice = index 0, noPrice = index 1). Per mark:
        d_own    = |mark - own_px|         -> the mark is already ours
        d_mirror = |(1 - mark) - own_px|   -> the mark is the sibling; 1-p maps back
     Control arm: the same test on marks of legs the repair did NOT touch, in both
     windows -- so the classifier is shown to separate the two frames.
 (c) RESTATEMENT -- the price/pnl each mark should have carried, and the delta on
     the mark series, on SUM(PnlSnapshot.pnl), and on the hourly rollup cells.
     Mapping is taken from the MEASURED frame where a mark was measurable and from
     the phase where it was not; both are reported separately.

USAGE
  COPYBOT_DB=/Users/xsnyde2/polymarket-copybot/prisma/dev.db \
      python3 scripts/pnlsnapshot-mark-restatement-measure.py
"""
import sqlite3, json, os, time, datetime, urllib.request
from collections import Counter, defaultdict

DB = os.environ.get("COPYBOT_DB", "prisma/dev.db")
ROOT = os.environ.get("COPYBOT_ROOT", "/Users/xsnyde2/polymarket-copybot")
MANIFEST = os.path.join(ROOT, "data/repair-manifests/ledger-price-side-20261111.jsonl")
APPLIED = os.path.join(ROOT, "data/repair-manifests/ledger-price-side-applied-20261111T123934.jsonl")
CACHE = "/tmp/mark-restate-tokens-v3.json"
DETAIL = "/tmp/mark-restate-detail-v3.json"

CODE_FIX_MS = 1794237316000   # 2026-11-09T15:15:16Z -- commit fbf9073 (-0600 09:15:16)
NEAR_MS = 30 * 60 * 1000      # "tight" venue match window
WIDE_MS = 180 * 60 * 1000     # widened fallback; reported per lag band
AMBIG = 0.02                  # |d_own - d_mirror| below this = no call


def con():
    c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=60)
    c.row_factory = sqlite3.Row
    return c


def d(ms):
    return datetime.datetime.utcfromtimestamp(ms / 1000).strftime("%Y-%m-%d %H:%M")


def pnl(entry, price, size):
    """src/lib/paper.ts computePnl."""
    if not entry or entry <= 0:
        return 0.0
    return round((size / entry) * price - size, 2)


def norm(s):
    return "".join(ch for ch in (s or "").upper() if ch.isalnum())


def fetch_tokens(conds):
    cache = {}
    if os.path.exists(CACHE):
        cache = {k: v for k, v in json.load(open(CACHE)).items() if isinstance(v, list)}
    miss = [x for x in conds if x and x not in cache]
    print(f"token cache: {len(cache)} known, {len(miss)} to fetch")
    for i, cond in enumerate(miss):
        try:
            req = urllib.request.Request(
                f"https://clob.polymarket.com/markets/{cond}",
                headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                                       "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36",
                         "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=25) as r:
                m = json.load(r)
            cache[cond] = [{"outcome": t.get("outcome"), "winner": t.get("winner"),
                            "price": t.get("price")} for t in (m.get("tokens") or [])]
        except Exception as e:
            cache[cond] = [{"error": str(e)[:120]}]
        if i and i % 40 == 0:
            print(f"  fetched {i}/{len(miss)}")
        time.sleep(0.25)
    json.dump(cache, open(CACHE, "w"), indent=1)
    ok = sum(1 for v in cache.values() if v and "error" not in v[0])
    print(f"  token cache: {ok} ok / {len(cache)}")
    return cache


def leg_index(toks, cond, outcome):
    lst = toks.get(cond)
    if not isinstance(lst, list) or len(lst) != 2 or "error" in lst[0]:
        return None
    tgt = norm(outcome)
    hit = [k for k, t in enumerate(lst) if norm(t.get("outcome")) == tgt]
    if len(hit) == 1:
        return hit[0]
    hit = [k for k, t in enumerate(lst)
           if norm(t.get("outcome")) and (norm(t.get("outcome")) in tgt or tgt in norm(t.get("outcome")))]
    return hit[0] if len(hit) == 1 else None


def venue_px(c, market, at, window):
    """Nearest stored MarketSnapshot for `market` within +-window; (lag_min, yes, no)."""
    best = None
    for row in c.execute(
            "SELECT collectedAt, yesPrice, noPrice FROM MarketSnapshot "
            "WHERE marketId=? AND collectedAt BETWEEN ? AND ?",
            (market, at - window, at + window)):
        dt = abs(row["collectedAt"] - at)
        if best is None or dt < best[0]:
            best = (dt, row["yesPrice"], row["noPrice"])
    return (best[0] / 60000.0, best[1], best[2]) if best else (None, None, None)


def main():
    t00 = time.time()
    c = con()
    man = [json.loads(l) for l in open(MANIFEST) if l.strip()]
    app = [json.loads(l) for l in open(APPLIED) if l.strip()]
    hdr, approws = app[0], app[1:]
    repair_ms = hdr["appliedAt"]
    byid = {r["paperTradeId"]: r for r in man}
    ids = list(byid)
    appended = {r["snapshotId"] for r in approws if r.get("snapshotId")}
    print(f"REPAIR POPULATION: {len(ids)} legs, {len(approws)} ledger rows, "
          f"{len(appended)} repair-appended snapshots")
    print(f"  repair applied {d(repair_ms)}   write fix {d(CODE_FIX_MS)}")

    ph = ",".join("?" * len(ids))
    trades = {r["id"]: dict(r) for r in c.execute(f"SELECT * FROM PaperTrade WHERE id IN ({ph})", ids)}
    snaps = [dict(r) for r in c.execute(
        f"SELECT id, paperTradeId, price, pnl, collectedAt FROM PnlSnapshot "
        f"WHERE paperTradeId IN ({ph}) ORDER BY collectedAt", ids)]
    print(f"  mark rows on those legs: {len(snaps)}")

    # PaperTrade carries no conditionId; ObservedTrade does. Resolve it on the
    # (marketId, outcome) key, and use the CLOB token list only when found.
    def cond_of(market, outcome):
        row = c.execute(
            "SELECT conditionId FROM ObservedTrade WHERE marketId=? AND outcome LIKE ? "
            "AND conditionId IS NOT NULL LIMIT 1", (market, outcome)).fetchone()
        return row["conditionId"] if row else None

    leg_cond = {}
    for i in ids:
        cond = byid[i].get("conditionId") or cond_of(trades[i]["marketId"], trades[i]["outcome"])
        leg_cond[i] = cond
    got = sum(1 for v in leg_cond.values() if v)
    print(f"  conditionId resolved for {got}/{len(ids)} legs "
          f"(manifest {sum(1 for v in byid.values() if v.get('conditionId'))}, "
          f"ObservedTrade {got - sum(1 for v in byid.values() if v.get('conditionId'))})")

    conds = sorted({v for v in leg_cond.values() if v})
    toks = fetch_tokens(conds)

    idx = {}
    for i in ids:
        idx[i] = leg_index(toks, leg_cond[i], trades[i]["outcome"])
    print(f"\nTOKEN INDEX (venue list): resolved {sum(1 for v in idx.values() if v is not None)}/{len(ids)}"
          f"  index0 {sum(1 for v in idx.values() if v == 0)}"
          f"  index1 {sum(1 for v in idx.values() if v == 1)}"
          f"  unmapped {sum(1 for v in idx.values() if v is None)}")

    # ---- per-mark rows ---------------------------------------------------------
    marks = []
    for s in snaps:
        t, m = trades[s["paperTradeId"]], byid[s["paperTradeId"]]
        pre_e, post_e, size = m["pre"]["entryPrice"], m["post"]["entryPrice"], t["simulatedPositionSize"]
        marks.append(dict(
            snap=s["id"], pid=s["paperTradeId"], bot=t["botId"], market=t["marketId"],
            outcome=t["outcome"], size=size, price=s["price"], pnl=s["pnl"], at=s["collectedAt"],
            fill=t.get("fillStatus"),
            phase=("repair-appended" if s["id"] in appended else
                   "pre-fix" if s["collectedAt"] < CODE_FIX_MS else "post-fix"),
            pre_e=pre_e, post_e=post_e, idx=idx[s["paperTradeId"]],
            fit_pre=abs(s["pnl"] - pnl(pre_e, s["price"], size)) <= 0.011,
            fit_post=abs(s["pnl"] - pnl(post_e, s["price"], size)) <= 0.011))

    # ---- (a) phase x entry frame ----------------------------------------------
    print("\n(a) PHASE x which entryPrice reproduces the stored pnl")
    for k, v in sorted(Counter(
            (r["phase"], "sibling-entry" if r["fit_pre"] and not r["fit_post"]
             else "repaired(own)-entry" if r["fit_post"] and not r["fit_pre"]
             else "both entries fit" if r["fit_pre"] and r["fit_post"] else "neither") for r in marks).items()):
        print(f"   {k[0]:<16} {k[1]:<20} {v:>5}")

    neither = [r for r in marks if not r["fit_pre"] and not r["fit_post"]]
    if neither:
        zero = sum(1 for r in neither if abs(r["pnl"]) < 1e-9)
        impl = Counter(round(r["size"] * r["price"] / (r["size"] + r["pnl"]), 3)
                       for r in neither if r["size"] + r["pnl"] > 1e-9)
        print(f"   neither: n={len(neither)}  pnl==0 on {zero}  "
              f"top implied entries {impl.most_common(4)}")

    # ---- (b) frame, measured against the venue --------------------------------
    print("\n(b) FRAME vs the venue's own token list (nearest MarketSnapshot)")
    for w, label in ((NEAR_MS, "<=30 min"), (WIDE_MS, "<=180 min")):
        b = Counter()
        for r in marks:
            if r["phase"] == "repair-appended" or r["idx"] is None:
                continue
            lag, y, n = venue_px(c, r["market"], r["at"], w)
            if lag is None:
                b[(r["phase"], "no snapshot")] += 1
                continue
            own = y if r["idx"] == 0 else n
            if own is None:
                b[(r["phase"], "unpriced")] += 1
                continue
            d_own, d_mir = abs(r["price"] - own), abs((1.0 - r["price"]) - own)
            r.update(lag_min=lag, own_px=own, d_own=d_own, d_mir=d_mir)
            r["frame"] = "ambiguous" if abs(d_own - d_mir) <= AMBIG else ("own" if d_own < d_mir else "sibling")
            b[(r["phase"], r["frame"])] += 1
        print(f"   window {label}")
        for k in sorted(b):
            print(f"     {k[0]:<10} {k[1]:<12} {b[k]:>5}")
        for phase in ("pre-fix", "post-fix"):
            o = b[(phase, "own")]
            s = b[(phase, "sibling")]
            if o + s:
                print(f"     {phase:<10} own-closer {o*100/(o+s):5.1f}%  ({o}/{o+s})")

    # index split: an index0 leg's positional read WAS its own token
    print("\n   frame by token index (pre+post fix sets):")
    for k in (0, 1):
        for phse in ("pre-fix", "post-fix"):
            sub = [r for r in marks if r["idx"] == k and r["phase"] == phse and r.get("frame") in ("own", "sibling")]
            if sub:
                o = sum(1 for r in sub if r["frame"] == "own")
                print(f"     index{k} {phse:<10} own-closer {o*100/len(sub):5.1f}%  (n={len(sub)})")

    # lag band: does the discriminator survive a worse match?
    print("\n   pre-fix discriminator by match lag:")
    for lo, hi in ((0, 30), (30, 60), (60, 180)):
        sub = [r for r in marks if r["phase"] == "pre-fix" and r.get("frame") in ("own", "sibling")
               and lo <= r["lag_min"] < hi]
        if sub:
            o = sum(1 for r in sub if r["frame"] == "own")
            print(f"     {lo:>3}-{hi:<3} min  n={len(sub):>4}  own-closer {o*100/len(sub):5.1f}%  "
                  f"mean d_own {sum(r['d_own'] for r in sub)/len(sub):.3f}  "
                  f"mean d_mirror {sum(r['d_mir'] for r in sub)/len(sub):.3f}")

    # ---- (b2) token-order validation ------------------------------------------
    print("\n(b2) token order validation: tokens[0].winner vs the market's last stored snapshot")
    agree = dis = skip = 0
    for i in ids:
        lst = toks.get(byid[i].get("conditionId"))
        if not isinstance(lst, list) or len(lst) != 2 or lst[0].get("winner") is None:
            skip += 1
            continue
        row = c.execute("SELECT yesPrice, noPrice FROM MarketSnapshot WHERE marketId=? "
                        "ORDER BY collectedAt DESC LIMIT 1", (trades[i]["marketId"],)).fetchone()
        if not row or row["yesPrice"] is None or row["noPrice"] is None:
            skip += 1
            continue
        if abs(row["yesPrice"] - row["noPrice"]) < 0.9:   # not decisive: no resolution print
            skip += 1
            continue
        ok = (lst[0]["winner"] and row["yesPrice"] > 0.5) or (not lst[0]["winner"] and row["yesPrice"] < 0.5)
        agree += 1 if ok else 0
        dis += 0 if ok else 1
    print(f"   agree {agree}  disagree {dis}  not decisive {skip}")

    # ---- (b3) control arm: legs the repair did not touch -----------------------
    print("\n(b3) CONTROL: marks on non-repaired legs, same test")
    ctrl = []
    for lo, hi, tag in ((1794000000000, CODE_FIX_MS, "pre-fix"), (CODE_FIX_MS, repair_ms, "post-fix")):
        rows = [dict(r) for r in c.execute(
            "SELECT s.price, s.pnl, s.collectedAt, t.id pid, t.marketId, t.outcome "
            "FROM PnlSnapshot s JOIN PaperTrade t ON s.paperTradeId=t.id "
            "WHERE s.collectedAt >= ? AND s.collectedAt < ? AND t.id NOT IN (%s) "
            "ORDER BY s.collectedAt LIMIT 400000" % ph, [lo, hi] + ids)]
        step = max(1, len(rows) // 500)
        for r in rows[::step]:
            r["phase"] = tag
            ctrl.append(r)
    print(f"   sampled {len(ctrl)} marks from {len({r['pid'] for r in ctrl})} legs")
    ctrl_conds = sorted({cond_of(r["marketId"], r["outcome"]) for r in ctrl} - {None})
    print(f"   conditionIds resolved: {len(ctrl_conds)} distinct")
    toks2 = fetch_tokens(ctrl_conds)
    cb = Counter()
    ctrl_idx = {}
    for r in ctrl:
        key = (r["marketId"], r["outcome"])
        if key not in ctrl_idx:
            ctrl_idx[key] = leg_index(toks2, cond_of(*key), r["outcome"])
        k = ctrl_idx[key]
        if k is None:
            continue
        lag, y, n = venue_px(c, r["marketId"], r["collectedAt"], NEAR_MS)
        if lag is None:
            continue
        own = y if k == 0 else n
        if own is None:
            continue
        d_own, d_mir = abs(r["price"] - own), abs((1.0 - r["price"]) - own)
        if abs(d_own - d_mir) <= AMBIG:
            cb[(r["phase"], "ambiguous")] += 1
            continue
        cb[(r["phase"], "own" if d_own < d_mir else "sibling")] += 1
    for k in sorted(cb):
        print(f"     {k[0]:<10} {k[1]:<12} {cb[k]:>5}")
    for phse in ("pre-fix", "post-fix"):
        o, s = cb[(phse, "own")], cb[(phse, "sibling")]
        if o + s:
            print(f"     {phse:<10} own-closer {o*100/(o+s):5.1f}%  ({o}/{o+s})")

    # ---- (c) restatement ------------------------------------------------------
    print("\n(c) RESTATEMENT -- price/pnl each mark should have carried")
    # RULE (from the measurement, not from the phase):
    #   a pre-fix mark is the FIRST token's price (positional read) => it carries
    #   the sibling's price exactly when our leg holds index 1; for an index-0 leg
    #   the positional read already WAS its own token. Either way the pnl was
    #   computed against the sibling ENTRY, so every non-appended mark is re-based
    #   onto the repaired entry.
    agg = defaultdict(lambda: {"n": 0, "old": 0.0, "new": 0.0, "moved": 0, "fallback": 0})
    per_hour = defaultdict(float)
    src = Counter()
    agree = Counter()
    excluded = {"unfilled (booked zero by design)": [0, 0.0],
                "zero-pnl but off-entry (writer formula unknown)": [0, 0.0]}
    for r in marks:
        if r["phase"] == "repair-appended":
            continue
        if r["phase"] == "pre-fix":
            use_mirror = r["idx"] != 0      # only the sibling token is index 0
            if r["idx"] is None:
                src[f"{r['phase']}/idx unknown"] += 1
            else:
                src[f"{r['phase']}/idx{r['idx']}->" + ("mirror" if use_mirror else "keep")] += 1
        else:
            use_mirror = False              # writer already reads our own token
            src[f"{r['phase']}/keep"] += 1
        if r.get("frame") in ("own", "sibling"):
            agree[("measured " + r["frame"], "rule " + ("mirror" if use_mirror else "keep"))] += 1
        new_px = round(1.0 - r["price"], 6) if use_mirror else r["price"]
        new_pnl = pnl(r["post_e"], new_px, r["size"])
        r["restated_px"] = new_px
        if r["fill"] == "unfilled":
            # bookedPnl() forces 0 on an unfilled leg -- restating pnl here would
            # invent a mark on a position that never existed.
            new_pnl = 0.0
            r["class"] = "unfilled"
            excluded["unfilled (booked zero by design)"][0] += 1
        elif abs(r["pnl"]) < 1e-9 and abs(r["price"] - r["pre_e"]) > 1e-6 and r.get("frame") not in ("own", "sibling"):
            r["class"] = "zero-offentry"
            excluded["zero-pnl but off-entry (writer formula unknown)"][0] += 1
            excluded["zero-pnl but off-entry (writer formula unknown)"][1] += new_pnl
        else:
            r["class"] = "restate"
        r["restated_pnl"] = new_pnl
        r["delta"] = new_pnl - r["pnl"]
        a = agg[(r["phase"], r["bot"])]
        a["n"] += 1
        a["old"] += r["pnl"]
        a["new"] += new_pnl
        a["moved"] += int(abs(r["delta"]) > 0.005)
        a["fallback"] += int(r["idx"] is None)
        per_hour[(r["at"] // 3600000, r["bot"])] += r["delta"]

    print("   mapping source:")
    for k, v in sorted(src.items()):
        print(f"     {k:<32} {v:>5}")
    print("   rule vs MEASURED frame (rows where the venue could decide):")
    for k, v in sorted(agree.items()):
        print(f"     {k[0]:<18} {k[1]:<12} {v:>5}")
    ok = agree[("measured sibling", "rule mirror")] + agree[("measured own", "rule keep")]
    tot = sum(agree.values())
    if tot:
        print(f"     rule agrees with the venue on {ok}/{tot} = {ok*100/tot:.1f}% of measurable rows")
    tot_old = tot_new = 0.0
    for k in sorted(agg):
        a = agg[k]
        tot_old += a["old"]
        tot_new += a["new"]
        print(f"   {k[0]:<10} {k[1]:<13} rows {a['n']:>5} moved {a['moved']:>5}  "
              f"stored {a['old']:>+11,.2f} -> restated {a['new']:>+11,.2f}  "
              f"delta {a['new']-a['old']:>+10,.2f}  [phase-fallback {a['fallback']}]")
    print(f"   TOTAL (2,484 non-appended marks) stored {tot_old:+,.2f} -> restated {tot_new:+,.2f}  "
          f"delta {tot_new-tot_old:+,.2f}")
    for k, (n, val) in excluded.items():
        print(f"   excluded class: {k:<48} {n:>4} rows"
              + (f"  (would add {val:+,.2f} if restated)" if n and k.startswith("zero") else ""))

    pre = [r for r in marks if r["phase"] == "pre-fix"]
    print(f"   pre-fix only: n={len(pre)} stored {sum(r['pnl'] for r in pre):+,.2f} -> "
          f"restated {sum(r['restated_pnl'] for r in pre):+,.2f} "
          f"(delta {sum(r['restated_pnl']-r['pnl'] for r in pre):+,.2f})")
    post = [r for r in marks if r["phase"] == "post-fix"]
    print(f"   post-fix/pre-repair only: n={len(post)} stored {sum(r['pnl'] for r in post):+,.2f} -> "
          f"restated {sum(r['restated_pnl'] for r in post):+,.2f} "
          f"(delta {sum(r['restated_pnl']-r['pnl'] for r in post):+,.2f})")

    # ---- (c2) two CHEQUES on the mapping --------------------------------------
    print("\n(c2) VALIDATION of the mapping")
    # 1) a sibling-frame mark carries the sibling's RETURN, i.e. the opposite sign.
    #    If the mapping is right, stored and restated pnl must be strongly anti-correlated.
    def corr(xs, ys):
        n = len(xs)
        if n < 3:
            return float("nan")
        mx, my = sum(xs) / n, sum(ys) / n
        sxy = sum((a - mx) * (b - my) for a, b in zip(xs, ys))
        sxx = sum((a - mx) ** 2 for a in xs)
        syy = sum((b - my) ** 2 for b in ys)
        return sxy / ((sxx * syy) ** 0.5) if sxx > 0 and syy > 0 else float("nan")

    for phse in ("pre-fix", "post-fix"):
        sub = [r for r in marks if r["phase"] == phse and r["class"] != "unfilled"]
        if len(sub) > 3:
            print(f"   {phse:<10} corr(stored pnl, restated pnl) = "
                  f"{corr([r['pnl'] for r in sub], [r['restated_pnl'] for r in sub]):+.3f}   n={len(sub)}")
    hi = [r for r in marks if r["phase"] == "pre-fix" and r["idx"] == 1 and r["class"] != "unfilled"]
    if len(hi) > 3:
        print(f"   pre-fix idx1 (the mispriced class) corr = "
              f"{corr([r['pnl'] for r in hi], [r['restated_pnl'] for r in hi]):+.3f}   n={len(hi)}")

    # 2) seam continuity: the last mark before the leg's final should land near the
    #    final after restatement. Compare |last mark jump to the appended final| before
    #    and after, on the repair-appended legs only.
    fin = {r["pid"]: r for r in marks if r["phase"] == "repair-appended"}
    jumps_old, jumps_new = [], []
    for pid, f in fin.items():
        pre_marks = [r for r in marks if r["pid"] == pid and r["phase"] != "repair-appended"
                     and r["class"] != "unfilled"]
        if not pre_marks:
            continue
        last = max(pre_marks, key=lambda r: r["at"])
        jumps_old.append(abs(last["pnl"] - f["pnl"]))
        jumps_new.append(abs(last["restated_pnl"] - f["pnl"]))
    if jumps_old:
        jumps_old.sort()
        jumps_new.sort()
        med = lambda xs: xs[len(xs) // 2]
        print(f"   seam |last mark - appended final|: stored median ${med(jumps_old):.2f} "
              f"(mean ${sum(jumps_old)/len(jumps_old):.2f})  ->  restated median ${med(jumps_new):.2f} "
              f"(mean ${sum(jumps_new)/len(jumps_new):.2f})   n={len(jumps_old)} legs")
        better = sum(1 for a, b in zip(jumps_old, jumps_new) if b < a)
        print(f"   restatement closes the seam on {better}/{len(jumps_old)} legs")

    # ---- rollup ---------------------------------------------------------------
    tot_all = c.execute("SELECT COUNT(*) n, SUM(pnl) s FROM PnlSnapshot").fetchone()
    roll = c.execute("SELECT COUNT(*) n, SUM(totalPnl) s FROM PnlHourlyRollup").fetchone()
    moved_cells = {k: v for k, v in per_hour.items() if abs(v) > 0.005}
    print(f"\n  SERIES: SUM(PnlSnapshot.pnl) {tot_all['s']:,.2f} over {tot_all['n']:,} rows")
    print(f"          SUM(PnlHourlyRollup)  {roll['s']:,.2f} over {roll['n']:,} hour-rows "
          f"(rebuild lands at {tot_all['s'] + (tot_new-tot_old):,.2f})")
    print(f"          rollup cells moved: {len(moved_cells)} / {roll['n']:,} "
          f"({len(moved_cells)*100/roll['n']:.1f}%)")
    for (h, bot), dd in sorted(moved_cells.items(), key=lambda kv: -abs(kv[1]))[:12]:
        print(f"            {d(h*3600000)}  {bot:<13} {dd:>+9,.2f}")

    # price of the rebuild: the same aggregate the script runs, timed read-only
    t0 = time.time()
    n = c.execute("SELECT COUNT(*) FROM (SELECT strftime('%Y-%m-%d %H:00:00', s.collectedAt/1000,'unixepoch') h, "
                  "t.botId b, SUM(s.pnl) FROM PnlSnapshot s JOIN PaperTrade t ON s.paperTradeId=t.id "
                  "GROUP BY h, b)").fetchone()[0]
    print(f"          rebuild aggregate: {n} hour-rows over {tot_all['n']:,} marks in {time.time()-t0:.1f}s "
          f"(read-only timing; the write is a deleteMany+createMany of {n} rows)")

    json.dump({"marks": marks, "per_hour": {f"{k[0]}|{k[1]}": v for k, v in per_hour.items()},
               "totals": {"stored": tot_old, "restated": tot_new,
                          "pre_stored": sum(r["pnl"] for r in pre),
                          "pre_restated": sum(r["restated_pnl"] for r in pre),
                          "post_stored": sum(r["pnl"] for r in post),
                          "post_restated": sum(r["restated_pnl"] for r in post),
                          "rows": len(pre) + len(post)},
               "table_sum": tot_all["s"], "rollup_sum": roll["s"]},
              open(DETAIL, "w"), default=str)
    print(f"\n  detail -> {DETAIL}   ({time.time()-t00:.0f}s)")


if __name__ == "__main__":
    main()
