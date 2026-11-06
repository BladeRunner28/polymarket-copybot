#!/usr/bin/env python3
"""
BAND ROTATION read: the size chain is a picture of where the edge WAS, and the edge has moved.

WHY THIS FILE EXISTS (2026-11-06): the 11-05 brief ranked "raise kellyMaxSizeUsd 100 -> 150"
#1 on a cheap-band edge of +16.2pp with ex-top-10 MARKETS at +9.6pp, and separately proposed
lifting the short-TTR lane ceiling. Both were priced on a 59.6-day book. Two things were never
tested, and both change the answer:

  (1) BREADTH BY WALLET, not by market. The cheap band's 30-day +78% is 70% one wallet, and
      ex-top-2-wallets it books -14.6%. The ex-top-N MARKETS test cannot see this: one wallet
      trading 43 different markets passes an ex-top-N-markets test trivially.
  (2) ROTATION OVER TIME, per band. Ex-top-2-wallets, the cheap band runs +78.3% (Sep) ->
      +30.9% (Oct) -> -9.7% (Nov) while 0.20-0.40 runs -0.9% (Sep) -> +21.2% (Oct) -> +59.5%
      (Nov) and stays broad (ex-top-2 +13.7% on 175 legs, 26 wallets). The band factors, the
      Kelly clamp and the v57 rail were all set on the September ordering.

Every ROI here is booked PnL / simulatedPositionSize (DOLLARS at risk), never shares and never
multiplied by entry price -- that mistake inflated the cheap band from +47.8% to +407% once.

USAGE
    python3 scripts/profit-band-rotation.py
    python3 scripts/profit-band-rotation.py --all      # drop the ruleSetVersion >= 49 cut
    python3 scripts/profit-band-rotation.py --self-test
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
REPS = 800


def band_of(p):
    for lo, hi, n in BANDS:
        if lo <= p < hi:
            return n
    return None


def roi(legs, size="ntl", pnl="pnl"):
    cost = sum(b[size] for b in legs)
    return sum(b[pnl] for b in legs) / cost if cost else 0.0


def ci(legs, seed=7):
    """Market-clustered bootstrap on ROI: resample MARKETS (legs on one market are one fact)."""
    by = {}
    for b in legs:
        by.setdefault(b["marketId"], []).append(b)
    keys = list(by)
    if len(keys) < 4:
        return (float("nan"), float("nan"))
    rng = np.random.default_rng(seed)
    out = []
    for _ in range(REPS):
        pick = rng.integers(0, len(keys), len(keys))
        out.append(roi([b for i in pick for b in by[keys[i]]]))
    return float(np.percentile(out, 2.5)), float(np.percentile(out, 97.5))


def drop_top_wallets(legs, k):
    """Remove the k wallets with the largest summed PnL. This is the sizing-relevant breadth
    test: size is per leg, and a band whose edge is one wallet's run is not a band edge."""
    by = {}
    for b in legs:
        by[b["walletAddress"]] = by.get(b["walletAddress"], 0.0) + b["pnl"]
    worst = sorted(by, key=lambda w: -by[w])[:k]
    keep = [b for b in legs if b["walletAddress"] not in worst]
    return keep, worst


def load(con, min_rule=MIN_RULE):
    sql = """
        SELECT p.id, p.botId, p.walletAddress, p.marketId, p.outcome, p.entryPrice,
               p.simulatedPositionSize AS ntl, p.realizedPnl AS pnl, p.status, p.openedAt,
               p.closedAt, p.resolvedAt, j.ruleSetVersion AS rv, j.reasonsJson AS rj
        FROM PaperTrade p LEFT JOIN DecisionJournal j ON j.id = p.decisionJournalId
        WHERE p.isDemo = 0 AND p.venue = 'Polymarket' AND COALESCE(j.ruleSetVersion,0) >= ?
    """
    rows = [dict(r) for r in con.execute(sql, [min_rule])]
    seen, legs = set(), []
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
        r["month"] = sqlmon(r["openedAt"])
        legs.append(r)
    return legs


def sqlmon(ms):
    import datetime
    return datetime.datetime.utcfromtimestamp((ms or 0) / 1000.0).strftime("%Y-%m")


def hdr(t):
    print("\n" + "=" * 106)
    print(t)
    print("=" * 106)


def main():
    con = sqlite3.connect(DB, uri=True)
    con.row_factory = sqlite3.Row
    NOW = con.execute("SELECT CAST(strftime('%s','now') AS INTEGER)*1000").fetchone()[0]
    rr = con.execute("SELECT version, rulesJson FROM RuleSet ORDER BY version DESC LIMIT 1").fetchone()
    rules = json.loads(rr["rulesJson"])
    CLAMP = float(rules.get("kellyMaxSizeUsd", 100))
    all_legs = load(con)
    legs = [b for b in all_legs if b["status"] in ("closed", "resolved") and b["pnl"] is not None]

    hdr("0. CLOCKS")
    print(f"  RuleSet v{rr['version']}  kellyMaxSizeUsd ${CLAMP:.0f}  "
          f"kellyFraction {rules.get('kellyFraction')}  maxBankrollPct {rules.get('kellyMaxBankrollPct')}")
    print(f"  band factors: c200Longshot {rules.get('c200LongshotBandFactor')}  "
          f"c200DeadZone {rules.get('c200DeadZoneBandFactor')}  "
          f"shttrDeadZone {rules.get('shortTtrDeadZoneBandFactor')}  "
          f"shttrPremium {rules.get('shortTtrPremiumBandFactor')}  "
          f"c200Premium {rules.get('c200PremiumBandFactor')}")
    print(f"  skips: c200 {rules.get('c200SkipBandRange')!r}  standard {rules.get('standardSkipBandRange')!r}  "
          f"maxPriceDrift {rules.get('maxPriceDrift')}")
    print(f"  settled legs (regime v{MIN_RULE}+, deduped) {len(legs):,}")

    # ---------------------------------------------------------------- 1. rotation
    hdr("1. BAND ROTATION -- booked ROI by band and month, headline vs ex-top-2-wallets")
    print("  'ex2' removes the two wallets with the largest summed PnL IN THAT CELL (so it is a")
    print("  within-cell breadth test, not a book-wide one). CI = market-clustered 95%.\n")
    print(f"  {'band':<10} {'month':<8} {'n':>4} {'wal':>4} {'notl':>8} {'pnl':>9} {'ROI':>8} "
          f"{'ROI ex2':>8} {'n ex2':>6} {'wal ex2':>8}")
    for _, _, bn in BANDS:
        cells = [b for b in legs if b["band"] == bn]
        if len(cells) < 20:
            continue
        for m in sorted({b["month"] for b in cells}):
            c = [b for b in cells if b["month"] == m]
            if len(c) < 8:
                continue
            ex, _ = drop_top_wallets(c, 2)
            print(f"  {bn:<10} {m:<8} {len(c):>4} {len({b['walletAddress'] for b in c}):>4} "
                  f"{sum(b['ntl'] for b in c):>8,.0f} {sum(b['pnl'] for b in c):>9,.1f} "
                  f"{roi(c)*100:>+7.1f}% {roi(ex)*100 if ex else 0:>+7.1f}% {len(ex):>6} "
                  f"{len({b['walletAddress'] for b in ex}):>8}")
        c = cells
        ex, top2 = drop_top_wallets(c, 2)
        lo, hi = ci(ex)
        print(f"  {'':<10} {'REGIME':<8} {len(c):>4} {len({b['walletAddress'] for b in c}):>4} "
              f"{sum(b['ntl'] for b in c):>8,.0f} {sum(b['pnl'] for b in c):>9,.1f} "
              f"{roi(c)*100:>+7.1f}% {roi(ex)*100:>+7.1f}% {len(ex):>6} "
              f"{len({b['walletAddress'] for b in ex}):>8}   ex2 CI [{lo*100:+.1f},{hi*100:+.1f}]")
        print()

    # 30d view, all bands, with ex2 CI
    hdr("1b. THE LAST 30 DAYS -- which band pays NOW, and does it survive ex-top-2-wallets")
    cut = NOW - 30 * DAY
    print(f"  {'band':<10} {'n':>4} {'legs/d':>7} {'notl/d':>7} {'clip':>6} {'pnl':>9} {'ROI':>8} "
          f"{'ex2 ROI':>8} {'ex2 CI':>18} {'wal':>4}")
    for _, _, bn in BANDS:
        c = [b for b in legs if b["band"] == bn and b["openedAt"] >= cut]
        if len(c) < 10:
            continue
        ex, _ = drop_top_wallets(c, 2)
        lo, hi = ci(ex)
        print(f"  {bn:<10} {len(c):>4} {len(c)/30:>7.1f} {sum(b['ntl'] for b in c)/30:>7,.0f} "
              f"{sum(b['ntl'] for b in c)/len(c):>6.2f} {sum(b['pnl'] for b in c):>9,.1f} "
              f"{roi(c)*100:>+7.1f}% {roi(ex)*100:>+7.1f}%  [{lo*100:>+7.1f},{hi*100:>+7.1f}] "
              f"{len({b['walletAddress'] for b in c}):>4}")
    tot = [b for b in legs if b["openedAt"] >= cut]
    print(f"  {'TOTAL':<10} {len(tot):>4} {len(tot)/30:>7.1f} "
          f"{sum(b['ntl'] for b in tot)/30:>7,.0f}   "
          f"${sum(b['pnl'] for b in tot)/30:,.2f}/day at {roi(tot)*100:+.1f}%")

    # ---------------------------------------------------------------- 2. size chain
    hdr("2. THE SIZE CHAIN -- what each band is ALLOWED to bet, vs its edge rank")
    print(f"  {'band':<10} {'n30':>4} {'clip':>7} {'%at$100':>8} {'%at$18-20':>10} {'max':>7} "
          f"{'>$25':>5} {'ROI30':>8} {'rank':>5}")
    ranked = []
    for _, _, bn in BANDS:
        c = [b for b in legs if b["band"] == bn and b["openedAt"] >= cut]
        if len(c) < 10:
            continue
        clips = [b["ntl"] for b in c]
        ranked.append((roi(c), bn))
        print(f"  {bn:<10} {len(c):>4} {np.mean(clips):>7.2f} "
              f"{100*sum(1 for x in clips if x >= CLAMP-0.01)/len(clips):>7.1f}% "
              f"{100*sum(1 for x in clips if 17.9 <= x <= 20.01)/len(clips):>9.1f}% "
              f"{max(clips):>7.2f} {sum(1 for x in clips if x > 25):>5} {roi(c)*100:>+7.1f}%")
    for i, (r, bn) in enumerate(sorted(ranked, reverse=True), 1):
        print(f"    edge rank {i}: {bn}  {r*100:+.1f}%")

    # ---------------------------------------------------------------- 3. settlement vs booked
    hdr("3. SETTLEMENT EDGE vs BOOKED DOLLARS, by band and lane -- where the stop eats the edge")
    print(f"  {'cell':<20} {'n':>4} {'notl':>8} {'booked':>9} {'ROI booked':>11} "
          f"{'res n':>6} {'ROI res':>9} {'hit%':>6} {'price':>6} {'edge pp':>8} {'z':>6}")
    for _, _, bn in BANDS:
        for lane in ("main", "shttr", "std"):
            c = [b for b in legs if b["band"] == bn and b["lane"] == lane]
            if len(c) < 25:
                continue
            res = [b for b in c if b["status"] == "resolved"]
            if len(res) < 10:
                continue
            hit = sum(1 for b in res if b["pnl"] > 0) / len(res)
            px = np.mean([b["entryPrice"] for b in res])
            se = math.sqrt(max(hit*(1-hit), 1e-12)/len(res))
            rres = sum(b["pnl"] for b in res)/sum(b["ntl"] for b in res)
            print(f"  {lane+'/'+bn:<20} {len(c):>4} {sum(b['ntl'] for b in c):>8,.0f} "
                  f"{sum(b['pnl'] for b in c):>9,.1f} {roi(c)*100:>+10.1f}% {len(res):>6} "
                  f"{rres*100:>+8.1f}% {hit*100:>5.1f} {px:>6.3f} {(hit-px)*100:>+7.1f} "
                  f"{(hit-px)/se:>+5.1f}")

    # ---------------------------------------------------------------- 4. capital
    hdr("4. CAPITAL -- is any of this capital-constrained?")
    br = con.execute("SELECT principal,cashBalance,realizedPnl FROM BotBankroll WHERE botId='BANKROLL_200'").fetchone()
    ob = con.execute("SELECT COUNT(*) n, COALESCE(SUM(simulatedPositionSize),0) s FROM PaperTrade "
                     "WHERE botId='BANKROLL_200' AND isDemo=0 AND status='open'").fetchone()
    ev = []
    for b in all_legs:
        if b["botId"] != "BANKROLL_200" or b["status"] != "open":
            continue
        ev.append(b["ntl"])
    # peak in-flight from settled holds
    pts = []
    for b in legs:
        if b["botId"] != "BANKROLL_200" or b["openedAt"] < cut:
            continue
        end = b["resolvedAt"] or b["closedAt"] or b["openedAt"]
        pts.append((b["openedAt"], b["ntl"]))
        pts.append((end, -b["ntl"]))
    pts.sort()
    cur = peak = 0.0
    for _, d in pts:
        cur += d
        peak = max(peak, cur)
    print(f"  cash ${br['cashBalance']:,.2f} | realized ${br['realizedPnl']:,.2f} | open {ob['n']} legs ${ob['s']:,.2f}")
    print(f"  peak simultaneous in-flight, last 30d: ${peak:,.0f}   gross cap $1,000 base + kicker")
    print(f"  -> capital deployed at peak = {peak/5064*100:.1f}% of the $5,064 effective cap")
    print(f"  -> capital is NOT scarce; the binding number is DAILY NOTIONAL, which is leg count x clip")

    # ---------------------------------------------------------------- 5. funnel
    hdr("5. FUNNEL -- distinct signals per day by band, conversion, and the refusal census (7d)")
    w7 = NOW - 7 * DAY
    rows = [dict(r) for r in con.execute("""
        SELECT o.marketId, o.outcome, o.walletAddress, o.detectedPrice px, o.timestamp ts,
               d.decision, d.risksJson
        FROM ObservedTrade o JOIN DecisionJournal d ON d.observedTradeId = o.id
        WHERE o.isDemo = 0 AND o.observationOnly = 0 AND o.timestamp >= ?""", [w7])]
    sig = {}
    for r in rows:
        k = (r["walletAddress"], r["marketId"], r["outcome"])
        if k not in sig or r["ts"] < sig[k]["ts"]:
            sig[k] = r
    print(f"  {len(rows):,} eligible fill rows -> {len(sig):,} distinct signals "
          f"({len(rows)/max(len(sig),1):.1f}x re-offer multiplicity)")
    print(f"  {'band':<10} {'sig':>5} {'sig/d':>6} {'copies':>7} {'conv':>7} {'mkts':>5}")
    for _, _, bn in BANDS:
        s = [r for r in sig.values() if band_of(r["px"]) == bn]
        if not s:
            continue
        cp = sum(1 for r in s if r["decision"] == "paper_copy")
        print(f"  {bn:<10} {len(s):>5} {len(s)/7:>6.1f} {cp:>7} {100*cp/len(s):>6.1f}% "
              f"{len({r['marketId'] for r in s}):>5}")

    def klass(rj):
        s = (rj or "").lower()
        for k, v in (("blacklist", "blacklist"), ("coalesced", "already open"),
                     ("already open", "already open"), ("drifted", "price drift"),
                     ("band skip", "band skip"), ("hour blackout", "hour blackout"),
                     ("no edge", "kelly no-edge"), ("confidence", "confidence floor"),
                     ("near certainty", "near certainty"), ("resolves in", "TTR"),
                     ("min 2h", "TTR")):
            if k in s:
                return v
        return "other"

    print(f"\n  refusals per SIGNAL (not row):")
    agg = {}
    for r in sig.values():
        if r["decision"] == "skip":
            agg.setdefault(klass(r["risksJson"]), {}).setdefault(band_of(r["px"]), 0)
            agg[klass(r["risksJson"])][band_of(r["px"])] += 1
    print(f"  {'class':<16} {'<0.20':>6} {'0.2-0.4':>8} {'0.4-0.6':>8} {'0.6+':>6} {'tot':>5}")
    for k, d in sorted(agg.items(), key=lambda kv: -sum(kv[1].values()))[:10]:
        print(f"  {k:<16} {d.get('0.00-0.20',0):>6} {d.get('0.20-0.40',0):>8} "
              f"{d.get('0.40-0.60',0):>8} {d.get('0.60-0.80',0)+d.get('0.80-1.00',0):>6} "
              f"{sum(d.values()):>5}")

    # ---------------------------------------------------------------- 6. drift
    hdr("6. DRIFT BAR CONFIRMATION (post sign-fix) -- the 0.004 gate is CORRECT, do not touch it")
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "drift-shadow.jsonl")
    if os.path.exists(p):
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
        cut_ts = "2026-10-26T00:00:00"
        print(f"  {'band':<10} {'n':>4} {'hit%':>6} {'price':>6} {'edge pp':>8} {'z':>6} {'$ at $10 stake':>14}")
        for _, _, bn in BANDS:
            grp = [c for c in s2.values() if str(c["ts"]) >= cut_ts
                   and band_of(float(c.get("currentPrice") or 0)) == bn
                   and res.get(f"{c['marketId']}|{c['outcome']}") is not None
                   and float(c.get("currentPrice") or 0) >= 0.10]
            if len(grp) < 10:
                continue
            w = sum(1 for c in grp if res[f"{c['marketId']}|{c['outcome']}"] > 0)
            hit = w/len(grp)
            pr = np.mean([float(c["currentPrice"]) for c in grp])
            se = math.sqrt(max(hit*(1-hit), 1e-12)/len(grp))
            d = sum(10*((1-float(c["currentPrice"])) if res[f"{c['marketId']}|{c['outcome']}"] > 0
                        else -float(c["currentPrice"])) for c in grp)
            print(f"  {bn:<10} {len(grp):>4} {hit*100:>5.1f}% {pr:>6.3f} {(hit-pr)*100:>+7.1f} "
                  f"{(hit-pr)/se:>+5.1f} {d:>14,.0f}")
        print("  (positive edge at 0.20-0.40 means the gate refuses bargains there; the negative")
        print("   0.60+ cells are what makes the POOLED -9.3pp look like the gate earning its keep.)")
    else:
        print("  data/drift-shadow.jsonl missing")

    # ---------------------------------------------------------------- 7. shadows
    hdr("7. SHADOWS -- priced at the band's OWN forward rate, not the 60-day regime")
    nov = NOW - 6 * DAY
    # (a) un-rail 0.20-0.40: scale only the rail-bound legs (>= $15) to 2x
    for bn_target in ("0.20-0.40",):
        c = [b for b in legs if b["band"] == bn_target and b["openedAt"] >= cut]
        bound = [b for b in c if b["ntl"] >= 15.0]
        rate30 = roi(c)
        novc = [b for b in c if b["openedAt"] >= nov]
        rate_nov = roi(novc) if len(novc) >= 10 else float("nan")
        d30 = sum(b["ntl"] * rate30 for b in bound) / 30.0
        dni = sum((b["ntl"] * (1 + b["pnl"] / b["ntl"]) - b["ntl"]) for b in bound) / 30.0
        print(f"  (a) 0.20-0.40 rail cap x2 (scale the {len(bound)}/{len(c)} legs at >= $15 only):")
        print(f"      cohort-rate shadow  +${d30:,.2f}/day   in-sample shadow +${dni:,.2f}/day "
              f"({len(bound)} legs, 30d)")
        print(f"      band ROI 30d {rate30*100:+.1f}% | last 6d (n={len(novc)}) "
              f"{rate_nov*100 if rate_nov == rate_nov else float('nan'):+.1f}%")
    # (b) clamp 100 -> 150 on the cheap band
    c = [b for b in legs if b["band"] == "0.00-0.20" and b["openedAt"] >= cut]
    at = [b for b in c if b["ntl"] >= CLAMP - 0.01]
    d = sum(0.5 * b["ntl"] * roi(c) for b in at) / 30.0
    print(f"\n  (b) kellyMaxSizeUsd {CLAMP:.0f} -> {CLAMP*1.5:.0f}: {len(at)}/{len(c)} cheap legs "
          f"are pinned at the clamp; cohort-rate shadow +${d:,.2f}/day")
    print(f"      (the 11-05 brief priced this at +$77/day on the 59.6d regime book.)")
    # (c) revert the short-TTR premium factor
    c = [b for b in legs if b["band"] == "0.60-0.80" and b["lane"] == "shttr"]
    cn = [b for b in c if b["openedAt"] >= nov]
    print(f"\n  (c) shortTtrPremium 2.0 -> 0.5: shttr 0.60-0.80 regime {len(c)} legs "
          f"{roi(c)*100:+.1f}% booked; last 6d {len(cn)} legs {roi(cn)*100:+.1f}% on "
          f"${sum(b['ntl'] for b in cn):,.0f}")
    dn = -0.5 * sum(b["ntl"] for b in cn) * roi(cn) / 6.0 if cn else 0.0
    print(f"      halving the clip on the recent cohort is worth ${dn:+,.2f}/day")

    if "--self-test" in sys.argv:
        hdr("SELF-TEST")
        ok = True
        # A BUY of a resolved token pays ntl*(1-p)/p on a win and -ntl on a loss (stake is
        # DOLLARS; shares = ntl/p). Unfilled legs book exactly 0 and are excluded.
        def expect(b):
            if b["pnl"] == 0:
                return 0.0
            return b["ntl"] * (1 - b["entryPrice"]) / b["entryPrice"] if b["pnl"] > 0 else -b["ntl"]
        bad = sum(1 for b in legs if b["status"] == "resolved" and
                  abs(expect(b) - b["pnl"]) > max(0.05, 0.02 * abs(b["pnl"])))
        zeros = sum(1 for b in legs if b["status"] == "resolved" and b["pnl"] == 0)
        print(f"  resolved legs failing the BUY payoff identity: {bad} of "
              f"{sum(1 for b in legs if b['status'] == 'resolved')} ({zeros} book exactly 0)")
        if bad > 0:
            ok = False
        print(f"  every leg has a band: {all(b['band'] for b in legs)}")
        if not all(b["band"] for b in legs):
            ok = False
        ex, top2 = drop_top_wallets(legs[:10], 2)
        print(f"  drop_top_wallets drops <= 2 wallets: "
              f"{len({b['walletAddress'] for b in legs[:10]}) - len({b['walletAddress'] for b in ex}) <= 2}")
        print("  PASS" if ok else "  FAIL")
        return 0 if ok else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
