#!/usr/bin/env python3
"""
Marginal-dollar read: where the NEXT dollar of risk goes, and what blocks it.

QUESTION THIS ANSWERS (and the prior two briefs did not):
  The 11-05 brief priced the SIZE levers (clamp $100->150, lane ceiling $20->$30) on a
  59.6-day regime book. That book was built when Kelly was admitting 13 legs a day at the
  $100 clamp. Today the C-200 lane opens 3-16 legs a day and carries $212 in flight against
  a $5,064 cap. So the honest question is not "is the clip too small" but "how many legs a
  day can this funnel actually produce, and which refusal class is holding the count down" --
  because profit = edge x clip x COUNT, and the third term was never measured at the
  candidate level, by price band, in the cheap band where 91% of the PnL is.

SECTIONS
  1  FORWARD BOOK       last 14/30d by lane x band: legs/day, $/day, clip, ROI, hold, %at clamp
  2  CAPITAL            cash / deployed / cap / peak in-flight -- is capital the constraint?
  3  FUNNEL BY BAND     eligible fill rows -> distinct signals -> copies, and the refusal census
  4  DRIFT BY BAND      the 0.004 bar is validated POOLED (-9.3pp). Split by band and by era.
  5  MARGINAL LADDER    what each lever is worth FORWARD at today's leg rate, not the 60d rate

COST BASIS: `PaperTrade.simulatedPositionSize` is DOLLARS at risk, never shares. Every ROI
here divides dollars of PnL by dollars of size. Multiplying by entryPrice is the documented
bug that inflated the cheap band from +47.8% to +407%.

Bet = first leg per (bot|wallet|market|outcome) -- legacy accumulation rows are duplicates.

USAGE
    python3 scripts/profit-marginal-dollar.py
    python3 scripts/profit-marginal-dollar.py --all       # ignore the ruleSetVersion>=49 cut
    python3 scripts/profit-marginal-dollar.py --self-test
"""
import json
import math
import os
import sqlite3
import sys

import numpy as np

DB = "file:prisma/dev.db?mode=ro"
DAY = 86400000.0
BANDS = [(0.0, 0.2, "0.00-0.20"), (0.2, 0.4, "0.20-0.40"), (0.4, 0.6, "0.40-0.60"),
         (0.6, 0.8, "0.60-0.80"), (0.8, 1.0001, "0.80-1.00")]
MIN_RULE = 0 if "--all" in sys.argv else 49
NOW = None  # set in main from the DB clock


def band_of(p):
    for lo, hi, n in BANDS:
        if lo <= p < hi:
            return n
    return None


def con_ro():
    c = sqlite3.connect(DB, uri=True)
    c.row_factory = sqlite3.Row
    return c


def roi(legs, size="ntl", pnl="pnl"):
    cost = sum(b[size] for b in legs)
    return sum(b[pnl] for b in legs) / cost if cost else 0.0


def boot_ci(legs, reps=1500, seed=7, key="marketId"):
    """Market-clustered bootstrap on ROI. Resamples MARKETS, not legs: two legs on the same
    market are one bet on one fact and must move together."""
    by = {}
    for b in legs:
        by.setdefault(b[key], []).append(b)
    keys = list(by)
    if len(keys) < 4:
        return (float("nan"), float("nan"))
    rng = np.random.default_rng(seed)
    out = []
    for _ in range(reps):
        pick = rng.integers(0, len(keys), len(keys))
        sample = [b for i in pick for b in by[keys[i]]]
        out.append(roi(sample))
    return float(np.percentile(out, 2.5)), float(np.percentile(out, 97.5))


def hit_edge(legs, weighted=False):
    """Settlement truth on resolved legs. Break-even hit rate IS the entry price for a BUY."""
    res = [b for b in legs if b["status"] == "resolved"]
    n = len(res)
    if n < 5:
        return None
    if weighted:
        tot = sum(b["ntl"] for b in res)
        hit = sum(b["ntl"] for b in res if b["pnl"] > 0) / tot
        price = sum(b["ntl"] * b["entryPrice"] for b in res) / tot
    else:
        hit = sum(1 for b in res if b["pnl"] > 0) / n
        price = sum(b["entryPrice"] for b in res) / n
    se = math.sqrt(max(hit * (1 - hit), 1e-12) / n)
    return dict(n=n, hit=hit, price=price, edge=hit - price,
                z=(hit - price) / se if se else 0.0)


def load_legs(con, since_ms=None):
    sql = """
        SELECT p.id, p.botId, p.walletAddress, p.marketId, p.outcome, p.entryPrice,
               p.simulatedPositionSize AS ntl, p.realizedPnl AS pnl, p.status,
               p.openedAt, p.closedAt, p.resolvedAt, p.fillStatus,
               j.ruleSetVersion AS rv, j.reasonsJson AS rj
        FROM PaperTrade p LEFT JOIN DecisionJournal j ON p.decisionJournalId = j.id
        WHERE p.isDemo = 0 AND p.venue = 'Polymarket'
          AND COALESCE(j.ruleSetVersion, 0) >= ?
    """
    args = [MIN_RULE]
    if since_ms:
        sql += " AND p.openedAt >= ?"
        args.append(since_ms)
    rows = [dict(r) for r in con.execute(sql, args)]
    seen, bets = set(), []
    for r in sorted(rows, key=lambda r: r["openedAt"] or 0):
        k = (r["botId"], r["walletAddress"], r["marketId"], r["outcome"])
        if k in seen:
            continue
        seen.add(k)
        r["band"] = band_of(r["entryPrice"])
        lane = "main" if r["botId"] == "BANKROLL_200" else "std"
        if r["rj"] and "Short-TTR lane" in r["rj"]:
            lane = "shttr"
        r["lane"] = lane
        end = r["resolvedAt"] or r["closedAt"]
        r["hold"] = max(0.0, (end - r["openedAt"]) / DAY) if end else None
        r["cd"] = r["ntl"] * (r["hold"] or 0) / 1000.0
        r["settled"] = r["status"] in ("closed", "resolved") and r["pnl"] is not None
        bets.append(r)
    return bets


def hdr(t):
    print("\n" + "=" * 104)
    print(t)
    print("=" * 104)


def main():
    con = con_ro()
    global NOW
    NOW = con.execute("SELECT CAST(strftime('%s','now') AS INTEGER)*1000").fetchone()[0]

    rules_row = con.execute(
        "SELECT version, rulesJson FROM RuleSet ORDER BY version DESC LIMIT 1").fetchone()
    rules = json.loads(rules_row["rulesJson"])
    CLAMP = float(rules.get("kellyMaxSizeUsd", 100))
    LEGACY = float(rules.get("standardMaxSizeUsd", rules.get("maxSizeUsd", 20)) or 20)

    legs = load_legs(con)
    settled = [b for b in legs if b["settled"]]
    open_ = [b for b in legs if b["status"] == "open"]

    hdr("0. CLOCKS AND LEVERS")
    print(f"  active RuleSet      : v{rules_row['version']}")
    print(f"  kellyMaxSizeUsd     : ${CLAMP:.0f}   maxBankrollPct {rules.get('kellyMaxBankrollPct')}"
          f"   kellyFraction {rules.get('kellyFraction')}")
    print(f"  band skips          : c200 {rules.get('c200SkipBandRange')!r}"
          f"  standard {rules.get('standardSkipBandRange')!r}")
    print(f"  maxPriceDrift       : {rules.get('maxPriceDrift')}   minEdge {rules.get('kellyMinEdge')}")
    print(f"  rules: {len(rules)} keys")
    print(f"  settled legs (regime) {len(settled):,}   open {len(open_):,}")

    # ------------------------------------------------------------------ 1. forward book
    hdr("1. FORWARD BOOK -- the last 30 days, and the last 7, by band (what the funnel is doing NOW)")
    for wdays in (30, 7):
        cut = NOW - wdays * DAY
        rows = [b for b in settled if b["openedAt"] >= cut]
        opens = [b for b in legs if b["openedAt"] >= cut]
        if not rows:
            continue
        print(f"\n  -- opened in the last {wdays} days --  "
              f"{len(opens)} legs, {len(rows)} settled, {len(opens) - len(rows)} still open")
        print(f"  {'band':<10} {'legs':>5} {'legs/d':>7} {'notl':>9} {'$/d':>7} {'clip':>7} "
              f"{'pnl':>9} {'ROI':>8} {'hit-e':>7} {'hold_h':>7} {'@clamp%':>8}")
        for _, _, bn in BANDS:
            c = [b for b in rows if b["band"] == bn]
            if not c:
                continue
            e = hit_edge(c)
            ntl = sum(b["ntl"] for b in c)
            pnl = sum(b["pnl"] for b in c)
            holds = [b["hold"] for b in c if b["hold"] is not None]
            at_clamp = 100.0 * sum(1 for b in c if b["ntl"] >= CLAMP - 0.01) / len(c)
            es = f"{e['edge']*100:+6.1f}" if e else "    --"
            print(f"  {bn:<10} {len(c):>5} {len(c)/wdays:>7.1f} {ntl:>9,.0f} {ntl/wdays:>7,.0f} "
                  f"{ntl/len(c):>7.2f} {pnl:>9,.1f} {pnl/ntl*100:>+7.1f}% {es:>7} "
                  f"{np.mean(holds) if holds else 0:>7.1f} {at_clamp:>7.1f}%")
        ntl = sum(b["ntl"] for b in rows)
        pnl = sum(b["pnl"] for b in rows)
        print(f"  {'TOTAL':<10} {len(rows):>5} {len(rows)/wdays:>7.1f} {ntl:>9,.0f} "
              f"{ntl/wdays:>7,.0f} {ntl/len(rows):>7.2f} {pnl:>9,.1f} {pnl/ntl*100:>+7.1f}%")
        print(f"           -> ${pnl/wdays:,.2f}/day realised on ${ntl/wdays:,.0f}/day at risk")

    # ------------------------------------------------------------------ 2. capital
    hdr("2. IS CAPITAL THE CONSTRAINT? (in-flight vs cap, cash, and the marginal dollar)")
    br = con.execute("SELECT principal, cashBalance, realizedPnl FROM BotBankroll "
                     "WHERE botId='BANKROLL_200'").fetchone()
    ob = con.execute("SELECT COUNT(*) n, COALESCE(SUM(simulatedPositionSize),0) s FROM PaperTrade "
                     "WHERE botId='BANKROLL_200' AND isDemo=0 AND status='open'").fetchone()
    print(f"  C-200 cash ${br['cashBalance']:,.2f} | realized ${br['realizedPnl']:,.2f} | "
          f"principal ${br['principal']:,.2f}")
    print(f"  C-200 open {ob['n']} legs / ${ob['s']:,.2f} in flight")
    # peak in-flight from the leg ledger itself (opened <= t < closed)
    ev = []
    for b in legs:
        if b["botId"] != "BANKROLL_200" or not b["hold"]:
            continue
        ev.append((b["openedAt"], b["ntl"]))
        ev.append((b["openedAt"] + b["hold"] * DAY, -b["ntl"]))
    ev.sort()
    cur = peak = 0.0
    for _, d in ev:
        cur += d
        peak = max(peak, cur)
    print(f"  peak simultaneous in-flight over the whole regime: ${peak:,.2f}")
    std_ob = con.execute("SELECT COUNT(*) n, COALESCE(SUM(simulatedPositionSize),0) s, "
                         "AVG((? - openedAt)/86400000.0) age FROM PaperTrade "
                         "WHERE botId='STANDARD' AND isDemo=0 AND status='open'", [NOW]).fetchone()
    print(f"  STANDARD open {std_ob['n']} legs / ${std_ob['s']:,.2f} / mean age "
          f"{std_ob['age']:.1f}d")

    # marginal dollar: what one extra $100 of notional per day is worth, at measured band ROI
    best = None
    cut30 = NOW - 30 * DAY
    for _, _, bn in BANDS:
        c = [b for b in settled if b["band"] == bn and b["openedAt"] >= cut30]
        if len(c) < 20:
            continue
        r = roi(c)
        holds = [b["hold"] for b in c if b["hold"]]
        cd = sum(b["ntl"] * b["hold"] / 1000.0 for b in c if b["hold"])
        v = dict(band=bn, roi=r, n=len(c), hold=np.mean(holds) if holds else 0,
                 per_cd=sum(b["pnl"] for b in c) / cd if cd else 0)
        if best is None or v["roi"] > best["roi"]:
            best = v
    if best:
        print(f"  highest-ROI band in the last 30d: {best['band']} {best['roi']*100:+.1f}% "
              f"on {best['n']} legs, mean hold {best['hold']:.1f}h "
              f"(capital recycles {24/best['hold']:.1f}x/day)")

    # ------------------------------------------------------------------ 3. funnel by band
    hdr("3. THE FUNNEL BY BAND -- eligible fills -> distinct signals -> copies, 7 days")
    w7 = NOW - 7 * DAY
    q = """
        SELECT o.id, o.marketId, o.outcome, o.walletAddress, o.detectedPrice AS px,
               o.marketCategoryClass AS cat, o.timestamp AS ts,
               d.decision, d.risksJson, d.simulatedPositionSize AS jsize
        FROM ObservedTrade o JOIN DecisionJournal d ON d.observedTradeId = o.id
        WHERE o.isDemo = 0 AND o.observationOnly = 0 AND o.timestamp >= ?
    """
    rows = [dict(r) for r in con.execute(q, [w7])]
    print(f"  copy-eligible fill rows in 7d: {len(rows):,}")
    # distinct signal = first row per (wallet, market, outcome)
    sig = {}
    for r in rows:
        k = (r["walletAddress"], r["marketId"], r["outcome"])
        if k not in sig or r["ts"] < sig[k]["ts"]:
            sig[k] = r
    print(f"  distinct signals          : {len(sig):,}   (re-offer multiplicity "
          f"{len(rows)/max(len(sig),1):.1f}x)")
    print(f"  {'band':<10} {'signals':>8} {'sig/d':>7} {'copies':>7} {'conv':>7} "
          f"{'mkt':>5} {'wallet':>6}")
    for _, _, bn in BANDS:
        s = [r for r in sig.values() if band_of(r["px"]) == bn]
        if not s:
            continue
        cp = sum(1 for r in s if r["decision"] == "paper_copy")
        print(f"  {bn:<10} {len(s):>8} {len(s)/7:>7.1f} {cp:>7} {100*cp/max(len(s),1):>6.1f}% "
              f"{len({r['marketId'] for r in s}):>5} {len({r['walletAddress'] for r in s}):>6}")

    # refusal census: first skip class per signal, split by band
    def klass(rj):
        try:
            arr = json.loads(rj)
        except Exception:
            return "unparsed"
        s = " | ".join(arr) if isinstance(arr, list) else str(arr)
        low = s.lower()
        if "blacklist" in low:
            return "blacklist (category)"
        if "coalesced" in low or "already open" in low:
            return "already open (dedupe)"
        if "drifted" in low:
            return "price drift"
        if "band skip" in low:
            return "band skip (v62/v63)"
        if "hour blackout" in low:
            return "hour blackout"
        if "no edge" in low or "kelly" in low:
            return "kelly no-edge"
        if "confidence" in low:
            return "confidence floor"
        if "near certainty" in low:
            return "near certainty band"
        if "min 2h" in low or "resolves in" in low:
            return "TTR too short"
        if "cap" in low or "rail" in low:
            return "cap/rail"
        return s[:40]

    print("\n  refusal class on the FINAL decision per signal, split by band:")
    print(f"  {'class':<22} {'<0.20':>7} {'0.2-0.4':>8} {'0.4-0.6':>8} {'0.6+':>7} {'total':>7}")
    agg = {}
    for r in sig.values():
        if r["decision"] != "skip":
            continue
        b = band_of(r["px"])
        k = klass(r["risksJson"])
        d = agg.setdefault(k, {"0.00-0.20": 0, "0.20-0.40": 0, "0.40-0.60": 0,
                               "0.60-0.80": 0, "0.80-1.00": 0})
        d[b] += 1
    for k, d in sorted(agg.items(), key=lambda kv: -sum(kv[1].values()))[:14]:
        print(f"  {k:<22} {d['0.00-0.20']:>7} {d['0.20-0.40']:>8} {d['0.40-0.60']:>8} "
              f"{d['0.60-0.80'] + d['0.80-1.00']:>7} {sum(d.values()):>7}")
    print("  (counts are SIGNALS, not re-offered rows -- read opportunities, not pressure.)")

    # ------------------------------------------------------------------ 4. drift by band
    hdr("4. THE 0.004 DRIFT BAR, SPLIT BY BAND -- pooled -9.3pp hides what?")
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data",
                     "drift-shadow.jsonl")
    if not os.path.exists(p):
        print("  data/drift-shadow.jsonl not found")
    else:
        cand, res = [], {}
        for line in open(p):
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except Exception:
                continue
            if r.get("type") == "resolve":
                res[f"{r.get('marketId')}|{r.get('outcome')}"] = r.get("value")
            elif r.get("type") == "candidate":
                cand.append(r)
        s2 = {}
        for c in cand:
            k = f"{c['marketId']}|{c['outcome']}|{c.get('wallet')}"
            if k not in s2 or str(c["ts"]) < str(s2[k]["ts"]):
                s2[k] = c
        for label, cut in (("ALL-TIME", "0000"), ("post-sign-fix (>=2026-10-26)", "2026-10-26T00:00:00")):
            print(f"\n  -- {label} --   signals {len(s2):,}")
            print(f"  {'band':<10} {'n':>5} {'hit%':>6} {'price':>6} {'edge':>7} {'z':>6} "
                  f"{'stake$':>8} {'$ if admitted':>14}")
            for _, _, bn in BANDS:
                grp = [c for c in s2.values()
                       if str(c["ts"]) >= cut
                       and band_of(float(c.get("currentPrice") or 0)) == bn
                       and res.get(f"{c['marketId']}|{c['outcome']}") is not None
                       and float(c.get("currentPrice") or 0) >= 0.10]
                if len(grp) < 10:
                    continue
                w = sum(1 for c in grp if res[f"{c['marketId']}|{c['outcome']}"] > 0)
                hit = w / len(grp)
                pr = np.mean([float(c["currentPrice"]) for c in grp])
                se = math.sqrt(max(hit * (1 - hit), 1e-12) / len(grp))
                stake = np.mean([float(c.get("stakeUsd") or 10) for c in grp])
                # dollar view: each admitted leg at its own stake, pays (1-p) on a win, -p on loss
                d = sum(stake * ((1 - float(c["currentPrice"])) if res[f"{c['marketId']}|{c['outcome']}"] > 0
                                 else -float(c["currentPrice"])) for c in grp)
                print(f"  {bn:<10} {len(grp):>5} {hit*100:>5.1f}% {pr:>6.3f} "
                      f"{(hit-pr)*100:>+6.1f} {(hit-pr)/se:>+6.1f} {stake:>8.2f} {d:>14,.0f}")
        print("  (edge = hit - blocked price. Positive = the gate refused a bargain.)")

    # ------------------------------------------------------------------ 5. marginal ladder
    hdr("5. MARGINAL LADDER -- what each lever is worth at TODAY'S leg rate, and the gap to $500/day")
    print(f"  {'band':<10} {'legs/d':>7} {'$/d':>8} {'ROI30':>8} {'clip':>7} "
          f"{'1.5x clip = +$/d':>18} {'legs/d for $500/d':>19}")
    tot_roi_num = tot_roi_den = 0.0
    for _, _, bn in BANDS:
        c = [b for b in settled if b["band"] == bn and b["openedAt"] >= cut30]
        if len(c) < 10:
            continue
        ntl = sum(b["ntl"] for b in c)
        pnl = sum(b["pnl"] for b in c)
        r = pnl / ntl
        clip = ntl / len(c)
        legs_d = len(c) / 30
        # 1.5x clip on the legs that are NOT already at the clamp
        delta = sum(0.5 * b["ntl"] * r for b in c if b["ntl"] < CLAMP - 0.01) / 30
        need = 500.0 / (clip * r) if r > 0 else float("inf")
        tot_roi_num += pnl
        tot_roi_den += ntl
        print(f"  {bn:<10} {legs_d:>7.1f} {ntl/30:>8,.0f} {r*100:>+7.1f}% {clip:>7.2f} "
              f"{delta:>18,.2f} {need:>19.0f}")
    print(f"\n  book ROI over the last 30d: {tot_roi_num/tot_roi_den*100:+.1f}% on "
          f"${tot_roi_den:,.0f}")
    print("  (the 1.5x column scales every leg that is NOT pinned at the clamp -- it is the "
          "honest forward version of the 11-05 shadow, which priced a 60-day book.)")

    if "--self-test" in sys.argv:
        hdr("SELF-TEST")
        ok = True
        # payoff identity: for a resolved leg bought at p, pnl == ntl*((1-p) win else -p)
        bad = 0
        for b in settled:
            if b["status"] != "resolved":
                continue
            exp = b["ntl"] * ((1 - b["entryPrice"]) if b["pnl"] > 0 else -b["entryPrice"])
            if abs(exp - b["pnl"]) > max(0.02, 0.02 * abs(b["pnl"])):
                bad += 1
        print(f"  resolved legs failing the payoff identity: {bad}")
        if bad > 0:
            print("  (nonzero is expected only on fill-aware zero rows; inspect before use)")
        if not (0 <= bad <= 20):
            ok = False
        print(f"  band partition covers every leg: "
              f"{sum(1 for b in legs if b['band']) == len(legs)}")
        if sum(1 for b in legs if b["band"]) != len(legs):
            ok = False
        print("  PASS" if ok else "  FAIL")
        return 0 if ok else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
