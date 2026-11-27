#!/usr/bin/env python3
"""Does a wallet's pre-v68 record predict its v68+ record? The one lever the plan still assumes.

WHY THIS FILE EXISTS
--------------------
The 2026-11-27 profit review closed the band axis: on the live era (v68+) headroom (hit% - paid%)
is negative in every band we trade, and it is negative at the COPIED WALLET's own entry price, so
execution cannot be the defect. The ML lane's durable finding says the alpha is WHICH wallets get
copied, not price prediction. `profit-band-report.py --v4` §E6 tried to test that on the live era
and returned UNMEASURED (5 repeat wallets). This file runs the same question on the only window
with enough repeat wallets -- pre-v68 as the FIT set, v68+ as the TEST set -- and asks whether
wallet rank carries forward at all.

If it does not, then demoting/promoting wallets is fitted to a dead regime and no wallet rule can
be shipped on evidence; the correct action is to stop claiming wallet selection is the alpha until
the live era produces repeat wallets. That is a NEGATIVE result with a decision attached, which is
the preferred output of this job.

BASIS (identical to fill-price-truth.py and profit-path-research.py)
--------------------------------------------------------------------
cost   = PaperTrade.simulatedPositionSize  (dollars at risk, NOT notional)
pnl    = realizedPnl, status IN ('closed','resolved'), TR-15 OR, isDemo=0
dedupe = first leg per (botId, walletAddress, marketId, outcome), ordered by openedAt
clock  = entry vintage (openedAt); era = DecisionJournal.ruleSetVersion (>=68 = live)
hit    = realizedPnl > 0 (a PnL label, not the market outcome)
paid   = mean entryPrice, dollar-weighted; headroom = hit% - paid%
CI     = market-clustered bootstrap (resample MARKETS, not legs), 2000 draws
null   = permutation of wallet labels inside the fit era, 2000 draws, for the rank correlation

Read-only. Writes data/wallet-persistence.json. Changes no rule and no threshold.

RUN
    python3 scripts/profit-wallet-persistence.py
    python3 scripts/profit-wallet-persistence.py --selftest
"""
from __future__ import annotations

import json
import os
import random
import sqlite3
import statistics

DB = os.path.join(os.path.dirname(__file__), "..", "prisma", "dev.db")
OUT = os.path.join(os.path.dirname(__file__), "..", "data", "wallet-persistence.json")

BASE = """
WITH legs AS (
  SELECT p.id, p.botId, p.walletAddress AS wallet, p.marketId AS market, p.outcome,
         p.entryPrice, p.realizedPnl AS pnl, p.simulatedPositionSize AS cost,
         p.fillStatus AS fill, p.openedAt, j.ruleSetVersion AS rsv
  FROM PaperTrade p
  LEFT JOIN DecisionJournal j ON j.id = p.decisionJournalId
  WHERE p.isDemo=0 AND p.status IN ('closed','resolved') AND p.realizedPnl IS NOT NULL
    AND p.entryPrice > 0 AND p.simulatedPositionSize > 0
), dedup AS (
  SELECT *, ROW_NUMBER() OVER (
      PARTITION BY botId, wallet, market, outcome ORDER BY openedAt) rn
  FROM legs
)
SELECT * FROM dedup WHERE rn=1
"""

STATUS_SQL = ("SELECT address, status, globalScore, consistencyScore, copyabilityScore, "
              "oneHitWonderPenalty FROM WalletProfile WHERE isDemo=0")


def load():
    con = sqlite3.connect(f"file:{os.path.abspath(DB)}?mode=ro&immutable=1", uri=True)
    con.row_factory = sqlite3.Row
    legs = [dict(r) for r in con.execute(BASE)]
    prof = {r["address"]: dict(r) for r in con.execute(STATUS_SQL)}
    con.close()
    for l in legs:
        l["era"] = "live" if (l["rsv"] or 0) >= 68 else "fit"
        l["hit"] = 1 if (l["pnl"] or 0) > 0 else 0
        pr = prof.get(l["wallet"], {})
        l["walletStatus"] = pr.get("status", "unknown")
        l["globalScore"] = pr.get("globalScore") or 0.0
    return legs


# ---------------------------------------------------------------- stats helpers
def cell(legs):
    if not legs:
        return {"n": 0, "cost": 0.0, "pnl": 0.0, "roi": None, "hit": None, "paid": None,
                "headroom_pp": None, "markets": 0, "wallets": 0}
    cost = sum(l["cost"] for l in legs)
    pnl = sum(l["pnl"] for l in legs)
    paid = sum(l["entryPrice"] * l["cost"] for l in legs) / cost
    hit = sum(l["hit"] for l in legs) / len(legs)
    return {"n": len(legs), "cost": round(cost, 2), "pnl": round(pnl, 2),
            "roi": round(100 * pnl / cost, 1) if cost else None,
            "hit": round(100 * hit, 1), "paid": round(100 * paid, 1),
            "headroom_pp": round(100 * hit - 100 * paid, 1),
            "markets": len({l["market"] for l in legs}),
            "wallets": len({l["wallet"] for l in legs})}


def cluster_ci(legs, reps=2000, seed=7):
    """Market-clustered bootstrap on ROI. Returns (lo, hi) in % or None."""
    if not legs:
        return None
    by = {}
    for l in legs:
        by.setdefault(l["market"], []).append(l)
    keys = list(by)
    if len(keys) < 6:
        return None  # a bootstrap over <6 clusters describes which ones were drawn
    rng = random.Random(seed)
    out = []
    for _ in range(reps):
        pick = [by[keys[rng.randrange(len(keys))]] for _ in range(len(keys))]
        c = sum(l["cost"] for g in pick for l in g)
        p = sum(l["pnl"] for g in pick for l in g)
        if c > 0:
            out.append(100 * p / c)
    out.sort()
    return (round(out[int(0.025 * len(out))], 1), round(out[int(0.975 * len(out))], 1))


def per_wallet(legs, minn=1):
    by = {}
    for l in legs:
        by.setdefault(l["wallet"], []).append(l)
    rows = []
    for w, g in by.items():
        if len(g) < minn:
            continue
        c = cell(g)
        c["wallet"] = w
        c["status"] = g[0]["walletStatus"]
        rows.append(c)
    rows.sort(key=lambda r: -r["roi"] if r["roi"] is not None else 0)
    return rows


def ranks(vals):
    order = sorted(range(len(vals)), key=lambda i: vals[i])
    r = [0.0] * len(vals)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and vals[order[j + 1]] == vals[order[i]]:
            j += 1
        avg = (i + j) / 2 + 1
        for k in range(i, j + 1):
            r[order[k]] = avg
        i = j + 1
    return r


def spearman(x, y):
    if len(x) < 3:
        return None
    rx, ry = ranks(x), ranks(y)
    mx, my = statistics.mean(rx), statistics.mean(ry)
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    den = (sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry)) ** 0.5
    return None if den == 0 else num / den


def rank_power(ns=(9, 15, 17, 20, 30, 45), rhos=(0.4, 0.6), null_reps=2000, alt_reps=400):
    """How many repeat wallets would a rank test need? Simulated, not asserted.

    Null: rho_true=0, one-sided alpha=0.05 -> critical value at each n.
    Alternative: rho_true in `rhos` -> fraction of draws above that critical value.
    """
    import math
    rng = random.Random(31)
    out = {}
    for n in ns:
        crit = []
        for _ in range(null_reps):
            x = [rng.gauss(0, 1) for _ in range(n)]
            y = [rng.gauss(0, 1) for _ in range(n)]
            v = spearman(x, y)
            if v is not None:
                crit.append(v)
        crit.sort()
        c95 = crit[int(0.95 * len(crit))]
        row = {"n": n, "crit95": round(c95, 3), "power": {}}
        for rho in rhos:
            hits = 0
            for _ in range(alt_reps):
                x = [rng.gauss(0, 1) for _ in range(n)]
                y = [rho * a + math.sqrt(1 - rho * rho) * rng.gauss(0, 1) for a in x]
                v = spearman(x, y)
                if v is not None and v >= c95:
                    hits += 1
            row["power"][f"rho={rho}"] = round(hits / alt_reps, 2)
        out[n] = row
    return out


def main():
    legs = load()
    fit = [l for l in legs if l["era"] == "fit"]
    live = [l for l in legs if l["era"] == "live"]

    art = {"basis": {
        "cost": "simulatedPositionSize (dollars at risk)",
        "pnl": "realizedPnl status IN (closed,resolved) TR-15 OR, isDemo=0",
        "dedupe": "first leg per bot|wallet|market|outcome",
        "clock": "entry vintage openedAt; era = DecisionJournal.ruleSetVersion>=68",
        "hit": "realizedPnl>0", "ci": "market-clustered bootstrap 2000 draws"},
        "populations": {"all": cell(legs), "fit_pre_v68": cell(fit), "live_v68": cell(live)}}

    print("=" * 84)
    print("P0. POPULATION (deduped, settled, TR-15 OR)")
    print("=" * 84)
    for k, c in art["populations"].items():
        print(f"  {k:12} n={c['n']:5} mkts={c['markets']:5} wallets={c['wallets']:4} "
              f"cost=${c['cost']:>9.0f} pnl=${c['pnl']:>8.0f} roi={c['roi']:>6}% "
              f"headroom={c['headroom_pp']}pp")

    # ---- P0b basis arms -- the review's warning: a mixed denominator flatters ~5.6x
    print("\n  BASES (same dedupe; the choice of denominator is the difference):")
    arms = {"booked_cost>0": legs,
            "carried_filled": [l for l in legs if l["fill"] == "filled"],
            "unfilled": [l for l in legs if l["fill"] == "unfilled"],
            "unstamped_NULL": [l for l in legs if l["fill"] is None]}
    art["bases"] = {}
    for k, pop in arms.items():
        c = cell(pop)
        art["bases"][k] = c
        print(f"  {k:16} n={c['n']:5} cost=${c['cost']:>9.0f} pnl=${c['pnl']:>8.0f} "
              f"roi={c['roi']}%  ci={cluster_ci(pop)}")
    print(f"  NOTE: STANDARD contributes 0 carried legs (fillStatus never stamped), so every")
    print(f"  carried-basis number is BANKROLL_200 only.")

    # ---- P1 concentration
    print("\n" + "=" * 84)
    print("P1. WALLET CONCENTRATION -- is the book one wallet's book?")
    print("=" * 84)
    art["concentration"] = {}
    for name, pop in (("fit_pre_v68", fit), ("live_v68", live)):
        w = per_wallet(pop, 1)
        tot_cost = sum(r["cost"] for r in w) or 1
        top5 = w[:5]
        art["concentration"][name] = {
            "wallets": len(w), "top5_cost_share_pct": round(100 * sum(r["cost"] for r in top5) / tot_cost, 1),
            "top5": [{"wallet": r["wallet"][:10], "n": r["n"], "roi": r["roi"],
                      "cost": r["cost"]} for r in top5]}
        print(f"  {name}: {len(w)} wallets | top-5 carry "
              f"{art['concentration'][name]['top5_cost_share_pct']}% of at-risk")
        for r in top5:
            print(f"     {r['wallet'][:12]} n={r['n']:4} cost=${r['cost']:8.0f} roi={r['roi']}%")

    # ---- P2 live-era per-wallet headroom
    print("\n" + "=" * 84)
    print("P2. LIVE ERA (v68+) PER-WALLET HEADROOM -- hit% vs paid% (BE price)")
    print("=" * 84)
    lw = [r for r in per_wallet(live, 5)]
    art["live_wallet_headroom"] = lw[:15]
    print(f"  {'wallet':13}{'n':>4}{'cost$':>8}{'roi%':>7}{'hit%':>7}{'paid%':>7}{'head':>7}  status")
    for r in lw[:15]:
        ci = cluster_ci([l for l in live if l["wallet"] == r["wallet"]])
        print(f"  {r['wallet'][:12]:13}{r['n']:>4}{r['cost']:>8.0f}{r['roi']:>7}"
              f"{r['hit']:>7}{r['paid']:>7}{r['headroom_pp']:>7}  {r['status']}  ci={ci}")
    print(f"  wallets with >=5 live legs: {len(lw)} of {len({l['wallet'] for l in live})}")

    # ---- P3 rank persistence
    print("\n" + "=" * 84)
    print("P3. RANK PERSISTENCE -- does pre-v68 wallet ROI predict v68+ wallet ROI?")
    print("=" * 84)
    fit_rows = {r["wallet"]: r for r in per_wallet(fit, 8)}
    live_rows = {r["wallet"]: r for r in per_wallet(live, 3)}
    both = sorted(set(fit_rows) & set(live_rows))
    x = [fit_rows[w]["roi"] for w in both]
    y = [live_rows[w]["roi"] for w in both]
    rho = spearman(x, y)
    null = []
    if rho is not None and len(both) >= 6:
        rng = random.Random(11)
        for _ in range(2000):
            sh = x[:]
            rng.shuffle(sh)
            v = spearman(sh, y)
            if v is not None:
                null.append(v)
        null.sort()
        p_hi = sum(1 for v in null if v >= rho) / len(null)
        left = round(null[int(0.025 * len(null))], 3)
        right = round(null[int(0.975 * len(null))], 3)
    else:
        p_hi, left, right = None, None, None
    art["rank_persistence"] = {"wallets_with_both": len(both),
                               "fit_min_legs": 8, "live_min_legs": 3,
                               "spearman_rho": None if rho is None else round(rho, 3),
                               "perm_p_ge": None if p_hi is None else round(p_hi, 3),
                               "perm_ci95": [left, right] if left is not None else None,
                               "n_pairs": len(both)}
    print(f"  wallets with >=8 fit legs and >=3 live legs: {len(both)}")
    print(f"  Spearman rho = {None if rho is None else round(rho, 3)}   "
          f"permutation CI95 {[left, right]}   p(rho>=obs)={None if p_hi is None else round(p_hi, 3)}")
    # headroom rank (stake-independent): does a wallet's hit%-minus-paid% carry forward?
    hx = [fit_rows[w]["headroom_pp"] for w in both]
    hy = [live_rows[w]["headroom_pp"] for w in both]
    rho_h = spearman(hx, hy)
    art["rank_persistence"]["spearman_headroom_pp"] = None if rho_h is None else round(rho_h, 3)
    print(f"  Spearman rho on HEADROOM (hit%-paid%, stake-independent) = "
          f"{None if rho_h is None else round(rho_h, 3)}")
    if len(both) >= 6:
        # quintile-free read: top third vs bottom third by fit ROI
        srt = sorted(both, key=lambda w: -fit_rows[w]["roi"])
        cut = max(1, len(srt) // 3)
        for label, grp in (("top third (fit)", srt[:cut]), ("bottom third (fit)", srt[-cut:])):
            L = [l for l in live if l["wallet"] in set(grp)]
            c = cell(L)
            print(f"  {label:20} wallets={len(grp):2} -> live n={c['n']:4} cost=${c['cost']:8.0f} "
                  f"roi={c['roi']}% hit={c['hit']}% paid={c['paid']}% ci={cluster_ci(L)}")
            art["rank_persistence"].setdefault("thirds", {})[label] = c

    # P3b power -- the honest bound on what n=9 can decide
    print("\n  P3b. POWER OF THE RANK TEST (simulated null crit at alpha=0.05 one-sided):")
    pw = rank_power()
    art["rank_persistence"]["power"] = pw
    for n, row in pw.items():
        print(f"    n={n:3} crit95={row['crit95']:+.3f}  "
              f"power@{'rho=0.4'}={row['power']['rho=0.4']}  "
              f"power@{'rho=0.6'}={row['power']['rho=0.6']}")
    need = next((n for n, row in pw.items() if row["power"]["rho=0.6"] >= 0.8), None)
    print(f"    repeat wallets needed for 80% power at rho=0.6: {need} "
          f"(we have {len(both)})")
    art["rank_persistence"]["wallets_needed_80pct_at_rho06"] = need

    # ---- P4 out-of-sample selection
    print("\n" + "=" * 84)
    print("P4. SELECTION COUNTERFACTUAL -- pick wallets on fit era, read the live era")
    print("=" * 84)
    art["selection"] = {}
    base_live = cell(live)
    print(f"  take-all live: n={base_live['n']} cost=${base_live['cost']:.0f} roi={base_live['roi']}%")
    for k in (5, 10, 25):
        sel = [w for w in sorted(fit_rows, key=lambda w: -fit_rows[w]["roi"])[:k]]
        L = [l for l in live if l["wallet"] in set(sel)]
        c = cell(L)
        art["selection"][f"top{k}_by_fit_roi"] = c
        print(f"  top{k:<3} by fit ROI   live n={c['n']:4} cost=${c['cost']:8.0f} roi={c['roi']}% "
              f"ci={cluster_ci(L)}")
    # and the converse: the best-performing wallets chosen WITH hindsight on the live era
    sel = [w for w in sorted([w for w in live_rows if live_rows[w]["n"] >= 10],
                             key=lambda w: -live_rows[w]["roi"])[:10]]
    L = [l for l in live if l["wallet"] in set(sel)]
    c = cell(L)
    art["selection"]["top10_live_hindsight_n10"] = c
    print(f"  top10 LIVE wallets (>=10 live legs, hindsight = upper bound) n={c['n']} roi={c['roi']}%")

    # ---- P5 track/watch contrast on the live era
    print("\n" + "=" * 84)
    print("P5. CURRENT WALLET SET -- tracked-25 vs watch, on the live era")
    print("=" * 84)
    art["status_split"] = {}
    for st in ("track", "watch", "ignore"):
        L = [l for l in live if l["walletStatus"] == st]
        c = cell(L)
        art["status_split"][st] = c
        print(f"  {st:7} n={c['n']:4} wallets={c['wallets']:3} cost=${c['cost']:8.0f} "
              f"roi={c['roi']}% hit={c['hit']}% paid={c['paid']}% ci={cluster_ci(L)}")

    print("\n  P5b. same, split by LANE (STANDARD has no fill stamp, so it cannot be carried):")
    art["status_lane_split"] = {}
    for lane in ("BANKROLL_200", "STANDARD"):
        for st in ("track", "watch"):
            L = [l for l in live if l["botId"] == lane and l["walletStatus"] == st]
            c = cell(L)
            art["status_lane_split"][f"{lane}|{st}"] = c
            print(f"  {lane:12} {st:6} n={c['n']:4} cost=${c['cost']:8.0f} roi={c['roi']}% "
                  f"head={c['headroom_pp']}pp ci={cluster_ci(L)}")

    # ---- P7 the selection variable itself: does WalletProfile score rank forward ROI?
    print("\n" + "=" * 84)
    print("P7. SCORE -> FORWARD ROI -- the bot selects wallets by globalScore. Does it rank?")
    print("=" * 84)
    art["score_forward"] = {}
    wl = [r for r in per_wallet(live, 5)]
    for r in wl:
        r["score"] = next((l["globalScore"] for l in live if l["wallet"] == r["wallet"]), 0.0)
    sx = [r["score"] for r in wl]
    sy = [r["roi"] for r in wl]
    rho_s = spearman(sx, sy) if len(wl) >= 6 else None
    p_s = None
    if rho_s is not None:
        rng = random.Random(13)
        draws = []
        for _ in range(2000):
            sh = sx[:]
            rng.shuffle(sh)
            v = spearman(sh, sy)
            if v is not None:
                draws.append(v)
        draws.sort()
        p_s = sum(1 for v in draws if v >= rho_s) / len(draws)
    art["score_forward"] = {"wallets": len(wl), "spearman_score_vs_live_roi":
                            None if rho_s is None else round(rho_s, 3),
                            "perm_p_ge": None if p_s is None else round(p_s, 3)}
    print(f"  wallets with >=5 live legs: {len(wl)} | Spearman(globalScore, live ROI) = "
          f"{None if rho_s is None else round(rho_s, 3)}  p(rho>=obs)="
          f"{None if p_s is None else round(p_s, 3)}")
    for r in sorted(wl, key=lambda r: -r["score"])[:8]:
        print(f"    score={r['score']:7.2f}  n={r['n']:4} roi={r['roi']:>7}% "
              f"head={r['headroom_pp']:>6}pp  {r['status']:6} {r['wallet'][:12]}")

    # ---- P6 live-era headroom by clip size, to keep the clip read honest
    print("\n" + "=" * 84)
    print("P6. LIVE ERA HEADROOM BY CLIP -- is the loss a wallet property or a size property?")
    print("=" * 84)
    art["live_clip"] = {}
    for lo, hi, lab in ((0, 30, "<$30"), (30, 60, "$30-60"), (60, 1e9, ">=$60")):
        L = [l for l in live if lo <= l["cost"] < hi]
        c = cell(L)
        art["live_clip"][lab] = c
        print(f"  {lab:8} n={c['n']:4} cost=${c['cost']:8.0f} roi={c['roi']}% "
              f"hit={c['hit']}% paid={c['paid']}% head={c['headroom_pp']}pp")

    with open(OUT, "w") as f:
        json.dump(art, f, indent=1, default=str)
    print(f"\nartifact -> {os.path.relpath(OUT)}")


def selftest():
    L = [{"market": "a", "wallet": "w1", "cost": 10.0, "pnl": 5.0, "entryPrice": 0.5, "hit": 1},
         {"market": "b", "wallet": "w1", "cost": 10.0, "pnl": -10.0, "entryPrice": 0.5, "hit": 0},
         {"market": "c", "wallet": "w2", "cost": 20.0, "pnl": 0.0, "entryPrice": 0.25, "hit": 0}]
    c = cell(L)
    assert abs(c["cost"] - 40) < 1e-9
    assert abs(c["pnl"] + 5) < 1e-9
    assert abs(c["roi"] - (-12.5)) < 1e-9, c["roi"]
    assert abs(c["hit"] - 33.3) < 0.05 and abs(c["paid"] - 37.5) < 0.05
    assert abs(c["headroom_pp"] - (-4.2)) < 0.06, c["headroom_pp"]
    assert spearman([1, 2, 3], [1, 2, 3]) == 1.0
    assert spearman([1, 2, 3], [3, 2, 1]) == -1.0
    assert cluster_ci(L) is None  # 3 clusters < k=6 guard
    print("selftest PASS")


if __name__ == "__main__":
    import sys
    if "--selftest" in sys.argv:
        selftest()
    else:
        main()
