#!/usr/bin/env python3
"""profit-band-allocation-negative-fstar — the measurement the card's own DECISION RULE asks for.

The card says: "do not propose a cut from this card. First measure what a 0.4-1.0 notional
reduction would actually reach — the sole-blocker and co-blocker structure of the admission
funnel for those bands (a cut whose candidates are already blocked by another gate is worth
zero), and the per-band realised ROI ex-top-5 wallets and ex-top-5 markets on the FINISHED
basis in the live regime."

So this instrument answers three questions and nothing else. Read-only; opens the DB mode=ro.

  1. SIZE      per band: legs, notional (dollars at risk = sum simulatedPositionSize),
               realised PnL, ROI, hit rate h, notional-weighted price p and f* = h-(1-h)p/(1-p).
  2. REACH     the admission funnel for the same bands: how much of the candidate population
               becomes a leg at all (a size cut can only reach the admitted part), and among
               the refusals, the sole-blocker vs co-blocker structure of risksJson.
  3. TAILS     every band's ROI and f* after removing the 5 best wallets and, separately,
               the 5 best markets; plus the top-10-leg share of the band's PnL.

BASES THAT MUST TRAVEL WITH EVERY NUMBER (printed in the output header):
  level = one finished PaperTrade leg (deduped: first leg per botId|wallet|market|outcome)
  clock = entry at openedAt, settled at COALESCE(closedAt, resolvedAt)
  basis = non-demo (isDemo=0) only; hit rate is the EXIT sign (realizedPnl > 0), NOT the
          market outcome — those disagree on ~11% of legs (label-basis-audit.py)
  regime = the admitting journal.ruleSetVersion, >= REGIME_MIN (default 68, i.e. the
          post-2026-10-26 profit-review cohort). PaperTrade has no ruleSetVersion column;
          the join through decisionJournalId is the only correct regime key.

Usage:
  python3 scripts/profit-band-fstar-funnel-read.py            # live read
  python3 scripts/profit-band-fstar-funnel-read.py --self-test
"""
import argparse
import json
import sqlite3
import sys
from collections import Counter, defaultdict

BANDS = [(0.0, 0.2), (0.2, 0.4), (0.4, 0.6), (0.6, 0.8), (0.8, 1.0)]
REGIME_MIN = 68
P_CLAMP = 0.999


def band_of(price):
    if price is None:
        return None
    p = float(price)
    if p < 0 or p > 1:
        return None
    for lo, hi in BANDS:
        if lo <= p < hi:
            return (lo, hi)
    return (0.8, 1.0) if p >= 1.0 else None


def fstar(h, p):
    """Kelly fraction for a binary buy at price p with hit rate h."""
    if h is None or p is None:
        return None
    pc = min(max(float(p), 0.0), P_CLAMP)
    if pc >= 1.0:
        return None
    return h - (1.0 - h) * pc / (1.0 - pc)


def agg(legs):
    """legs: list of dicts with pnl, size, price, wallet, market. Returns the band block."""
    n = len(legs)
    if n == 0:
        return {"legs": 0, "notional": 0.0, "pnl": 0.0, "roi": None, "h": None, "p": None, "fstar": None}
    notional = sum(l["size"] for l in legs)
    pnl = sum(l["pnl"] for l in legs)
    wins = sum(1 for l in legs if l["pnl"] > 0)
    h = wins / n
    p = (sum(l["price"] * l["size"] for l in legs) / notional) if notional > 0 else None
    # Per-leg Kelly fraction at each leg's OWN price, averaged over legs. This has no
    # aggregation bias: f*(h, mean p) is NOT the population's fraction when p disperses
    # (measured here: 0.8-1.0 live regime has f*(h,pbar) -89.8% while realised ROI is +8.2%,
    # because the wins sit at lower prices than the losses).
    fstars = [fstar(1.0 if l["pnl"] > 0 else 0.0, l["price"]) for l in legs]
    fstars = [x for x in fstars if x is not None]
    fstar_legavg = (sum(fstars) / len(fstars)) if fstars else None
    # The per-leg fraction has a pole as p->1 (p/(1-p)), so the MEAN is unusable on the
    # top band. The median is the robust read; `sat` is the share of legs whose |f*| > 1,
    # i.e. legs where the formula has saturated and only its SIGN is meaningful.
    fs_sorted = sorted(fstars)
    fstar_legmed = None
    if fs_sorted:
        mid = len(fs_sorted) // 2
        fstar_legmed = fs_sorted[mid] if len(fs_sorted) % 2 else 0.5 * (fs_sorted[mid - 1] + fs_sorted[mid])
    fstar_sat = (sum(1 for x in fstars if abs(x) > 1.0) / len(fstars)) if fstars else None
    # CORRECT per-band fraction for heterogeneous prices: f_i = h - (1-h)*p_i/(1-p_i), so the
    # population value uses mean_i[p/(1-p)] -- NOT p-bar/(1-p-bar). The two differ whenever p
    # disperses inside a band, and the top-10 ratio is unstable when a band's PnL is near zero,
    # so the absolute top-10 sum is printed with it.
    odds = [l["price"] / (1.0 - l["price"]) for l in legs if 0 < l["price"] < 1]
    fstar_exact = fstar(h, None) if False else None
    if odds:
        fstar_exact = h - (1.0 - h) * (sum(odds) / len(odds))
    top10_abs = sum(sorted((l["pnl"] for l in legs), reverse=True)[:10]) if legs else None
    roi_implied = None
    if p is not None and 0 < p < 1:
        roi_implied = h * (1.0 - p) / p - (1.0 - h)
    return {
        "legs": n,
        "notional": notional,
        "pnl": pnl,
        "roi": (pnl / notional) if notional > 0 else None,
        "h": h,
        "p": p,
        "fstar": fstar(h, p),
        "exit_share": sum(1 for l in legs if l.get("early_exit")) / n,
        "roi_implied": roi_implied,
        "fstar_legavg": fstar_legavg,
        "fstar_legmed": fstar_legmed,
        "fstar_sat": fstar_sat,
        "fstar_exact": fstar_exact,
        "top10_abs": top10_abs,
    }


def ex_top(legs, key, k=5):
    """Drop the k members with the largest PnL sum on `key` and re-aggregate."""
    if not legs:
        return []
    by = defaultdict(float)
    for l in legs:
        by[l[key]] += l["pnl"]
    ordered = sorted(by.items(), key=lambda kv: -kv[1])
    drop = {kk for kk, _ in ordered[:k]}
    return [l for l in legs if l[key] not in drop]


def top10_share(legs):
    if not legs:
        return None
    pnls = sorted((l["pnl"] for l in legs), reverse=True)
    total = sum(pnls)
    if total == 0:
        return None
    return sum(pnls[:10]) / total


def load_legs(db, regime_min):
    """Finished, non-demo, deduped legs with the regime key from the admitting journal row."""
    sql = """
    SELECT p.id, p.botId, p.walletAddress, p.marketId, p.outcome, p.entryPrice,
           p.simulatedPositionSize, p.realizedPnl, p.openedAt, p.closedAt, p.resolvedAt,
           j.ruleSetVersion
    FROM PaperTrade p JOIN DecisionJournal j ON j.id = p.decisionJournalId
    WHERE p.isDemo = 0 AND p.realizedPnl IS NOT NULL
      AND (p.closedAt IS NOT NULL OR p.resolvedAt IS NOT NULL)
    ORDER BY p.openedAt
    """
    seen = set()
    out = []
    for r in db.execute(sql):
        key = (r["botId"], r["walletAddress"], r["marketId"], r["outcome"])
        if key in seen:
            continue
        seen.add(key)
        b = band_of(r["entryPrice"])
        if b is None:
            continue
        out.append(
            {
                "band": b,
                "wallet": r["walletAddress"],
                "market": r["marketId"],
                "size": float(r["simulatedPositionSize"] or 0.0),
                "pnl": float(r["realizedPnl"]),
                "price": float(r["entryPrice"]),
                "v": r["ruleSetVersion"],
                "early_exit": r["closedAt"] is not None,
                "regime": (r["ruleSetVersion"] is not None and r["ruleSetVersion"] >= regime_min),
            }
        )
    return out


def load_funnel(db, regime_min):
    """Decisions with a price the bot actually saw, bucketed by band and decision."""
    sql = """
    SELECT d.decision, d.risksJson, o.detectedPrice, o.walletEntryPrice, d.ruleSetVersion
    FROM DecisionJournal d JOIN ObservedTrade o ON o.id = d.observedTradeId
    WHERE d.isDemo = 0 AND o.isDemo = 0 AND o.observationOnly = 0
    """
    per_band = defaultdict(lambda: {"paper_copy": 0, "watchlist": 0, "skip": 0, "co_cand": 0})
    sole = defaultdict(Counter)
    co = defaultdict(Counter)
    n = 0
    for r in db.execute(sql):
        price = r["detectedPrice"] if r["detectedPrice"] is not None else r["walletEntryPrice"]
        b = band_of(price)
        if b is None:
            continue
        if regime_min is not None and (r["ruleSetVersion"] is None or r["ruleSetVersion"] < regime_min):
            continue
        n += 1
        dec = r["decision"] or "skip"
        per_band[b][dec if dec in ("paper_copy", "watchlist", "skip") else "skip"] += 1
        if dec == "paper_copy":
            continue
        keys = normalized_blockers(r["risksJson"])
        if not keys:
            sole[b]["<no blocker recorded>"] += 1
        elif len(set(keys)) == 1:
            sole[b][keys[0]] += 1
        else:
            per_band[b]["co_cand"] += 1
            for k in set(keys):
                co[b][k] += 1
    return per_band, sole, co, n


def normalized_blockers(raw):
    if not raw:
        return []
    try:
        arr = json.loads(raw)
    except Exception:
        return []
    if not isinstance(arr, list):
        return []
    out = []
    for item in arr:
        if not isinstance(item, str):
            continue
        k = item.split(":")[0].strip()
        if k:
            out.append(k)
    return out


def pct(x):
    return "  n/a" if x is None else "%6.1f%%" % (100.0 * x)


def usd(x):
    return "  n/a" if x is None else "%+9.2f" % x


def report(legs, regime_min, label):
    print("\n=== %s (level=leg, EXIT basis, deduped, isDemo=0) ===" % label)
    hdr = "band        legs     notional        PnL     ROI      h        p    f*(pbar)   f*(exact)  top10$   exit%"
    print(hdr)
    for b in BANDS:
        sub = [l for l in legs if l["band"] == b]
        a = agg(sub)
        name = "%.1f-%.1f" % b
        print(
            "%-9s %6d %11.2f %10.2f %7s %7s %7s %8s %10s %9s %7s"
            % (
                name,
                a["legs"],
                a["notional"],
                a["pnl"],
                pct(a["roi"]),
                pct(a["h"]),
                "  n/a" if a["p"] is None else "%6.3f" % a["p"],
                pct(a["fstar"]),
                pct(a["fstar_exact"]),
                "  n/a" if a["top10_abs"] is None else "%+8.2f" % a["top10_abs"],
                pct(a["exit_share"]),
            )
        )
    tot = agg(legs)
    print(
        "%-9s %6d %11.2f %10.2f"
        % ("TOTAL", tot["legs"], tot["notional"], tot["pnl"])
    )
    neg = [b for b in BANDS if b[0] >= 0.4]
    neg_notional = sum(agg([l for l in legs if l["band"] == b])["notional"] for b in neg)
    print(
        "f*(pbar) = h - (1-h)*pbar/(1-pbar) at the band's notional-weighted mean price -- the card's own "
        "method. f*(exact) = h - (1-h)*mean_i[p_i/(1-p_i)], which is the correct population value when prices "
        "differ inside the band; the two disagree exactly when wins and losses sit at different prices. "
        "Above p~0.9 the first term saturates: there read only the SIGN."
    )
    print(
        "BASIS CHECK: ROI@settle is what the band's (h,p) pair implies if every leg were held to settlement; "
        "where it disagrees with ROI, the gap is early exits (exit% column) and f* is a RANKER on that band, "
        "not a size -- f* is only a Kelly fraction on hold-to-settlement book."
    )
    print("0.4-1.0 share of notional: %s of %.2f" % (pct(neg_notional / tot["notional"] if tot["notional"] else None), tot["notional"]))

    print("\n--- TAILS: ROI and f* after removing the 5 best wallets / 5 best markets ---")
    for b in BANDS:
        sub = [l for l in legs if l["band"] == b]
        if not sub:
            continue
        a = agg(sub)
        aw = agg(ex_top(sub, "wallet"))
        am = agg(ex_top(sub, "market"))
        print(
            "%.1f-%.1f  all ROI %s f* %s | ex-top5-wallets ROI %s f* %s (%d legs) | ex-top5-markets ROI %s f* %s (%d legs)"
            % (
                b[0],
                b[1],
                pct(a["roi"]),
                pct(a["fstar"]),
                pct(aw["roi"]),
                pct(aw["fstar"]),
                aw["legs"],
                pct(am["roi"]),
                pct(am["fstar"]),
                am["legs"],
            )
        )


def funnel_report(per_band, sole, co, n, regime_min):
    print(
        "\n=== REACH: admission funnel, same bands (population=%d decisions with a price the bot saw, "
        "journal ruleSetVersion>=%s, level=one decision, observationOnly excluded) ===" % (n, regime_min)
    )
    print("band        candidates  admitted  admit%   watchlist     skip   sole-blocked  co-blocked")
    for b in BANDS:
        d = per_band[b]
        tot = d["paper_copy"] + d["watchlist"] + d["skip"]
        s = sum(sole[b].values())
        c = d["co_cand"]
        print(
            "%.1f-%.1f %11d %9d %6s %10d %8d %13d %12d"
            % (b[0], b[1], tot, d["paper_copy"], pct(d["paper_copy"] / tot if tot else None), d["watchlist"], d["skip"], s, c)
        )
    print("\n--- sole blockers of REFUSED candidates, 0.4-1.0 (only gate that fired) ---")
    merged = Counter()
    for b in BANDS:
        if b[0] >= 0.4:
            merged.update(sole[b])
    for k, v in merged.most_common(12):
        print("  %6d  %s" % (v, k))
    print("\n--- co-blocker KEYS on REFUSED candidates, 0.4-1.0 (>=2 gates fired; a candidate can carry several, "
          "so these do not sum to the co-blocked candidate count) ---")
    coall = Counter()
    for b in BANDS:
        if b[0] >= 0.4:
            coall.update(co[b])
    for k, v in coall.most_common(12):
        print("  %6d  %s" % (v, k))
    print(
        "\nNOTE: legs and admitted decisions do not reconcile 1:1 -- one decision can carry two legs "
        "(different outcome or re-entry) and legs are deduped per bot|wallet|market|outcome."
    )
    print(
        "\nREAD THIS AS: a size cut reaches only ADMITTED legs. Every refused candidate is unreachable "
        "by a sizing change unless the gate that refused it moves, so the admitted column is the ceiling "
        "on reach and the sole/co columns say what would have to break for the rest to be in scope."
    )


def self_test():
    fails = []

    def check(name, got, want, tol=1e-9):
        if isinstance(got, list) or isinstance(want, list):
            ok = got == want
        else:
            ok = (got is None and want is None) or (
                got is not None and want is not None and abs(float(got) - float(want)) <= tol
            )
        print(("PASS " if ok else "FAIL ") + name + ("  got=%r want=%r" % (got, want)))
        if not ok:
            fails.append(name)

    # f* arithmetic, including the card's own -101.3% shape
    check("f* h=.55 p=.10", fstar(0.55, 0.10), 0.55 - 0.45 * 0.10 / 0.90)
    check("f* h==p -> 0 (breakeven)", fstar(0.6666666667, 0.6666666667), 0.0, 1e-8)
    check("f* h=.50 p=.6667 -> -0.5", fstar(0.5, 0.6666666667), -0.5, 1e-8)
    check("f* h=.278 p=.857 -> negative", fstar(0.278, 0.857), 0.278 - 0.722 * 0.857 / 0.143)
    check("f* clamps p at 1.0", fstar(0.5, 1.0), 0.5 - 0.5 * P_CLAMP / (1 - P_CLAMP))
    # band edges: 0.2 belongs to 0.2-0.4, 1.0 still lands in a band
    check("band(0.1999)", band_of(0.1999)[0], 0.0)
    check("band(0.2)", band_of(0.2)[0], 0.2)
    check("band(1.0)", band_of(1.0)[0], 0.8)
    check("band(1.4)=None", band_of(1.4), None)
    # ex-top-5 removal + a mutation arm: keeping the tail must MOVE the number
    legs = [
        {"band": (0.4, 0.6), "wallet": "a", "market": "m1", "size": 10.0, "pnl": 100.0, "price": 0.5},
        {"band": (0.4, 0.6), "wallet": "b", "market": "m2", "size": 10.0, "pnl": -5.0, "price": 0.5},
        {"band": (0.4, 0.6), "wallet": "c", "market": "m3", "size": 10.0, "pnl": -5.0, "price": 0.5},
    ]
    check("all-legs ROI", agg(legs)["roi"], 3.0)
    check("ex-top5-wallets ROI (only 3 wallets -> empty)", agg(ex_top(legs, "wallet"))["roi"], None)
    check("ex-top1-wallet ROI", agg(ex_top(legs, "wallet", 1))["roi"], -0.5)
    # sole vs co classification
    check("sole blockers on one reason", len(set(normalized_blockers('["near-certainty: price 0.02"]'))), 1)
    check(
        "co blockers on two reasons",
        len(set(normalized_blockers('["drawdown: 25% > 20%", "liquidity: $900 < $5000"]'))),
        2,
    )
    check("unparseable risksJson -> no blockers", normalized_blockers("not json"), [])
    check("empty risksJson -> no blockers", normalized_blockers(None), [])
    # top10 share
    check("top10 share on 3 legs (fraction)", top10_share(legs), 1.0)
    if fails:
        print("\nSELF-TEST FAILED: %s" % ", ".join(fails))
        return 1
    print("\nSELF-TEST PASS")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--regime-min", type=int, default=REGIME_MIN)
    ap.add_argument("--db", default="prisma/dev.db")
    ap.add_argument("--json-out", default=None)
    args = ap.parse_args()
    if args.self_test:
        return self_test()

    db = sqlite3.connect("file:%s?mode=ro" % args.db, uri=True)
    db.row_factory = sqlite3.Row
    legs = load_legs(db, args.regime_min)
    print(
        "BASIS: population=finished non-demo PaperTrade legs (deduped first leg per bot|wallet|market|outcome); "
        "clock=openedAt entry, COALESCE(closedAt,resolvedAt) settle; level=leg; "
        "hit rate = EXIT sign (realizedPnl>0), not market outcome; regime = journal.ruleSetVersion >= %d"
        % args.regime_min
    )
    report(legs, args.regime_min, "ALL TIME (finished legs)")
    report([l for l in legs if l["regime"]], args.regime_min, "LIVE REGIME (journal.ruleSetVersion >= %d)" % args.regime_min)
    per_band, sole, co, n = load_funnel(db, args.regime_min)
    funnel_report(per_band, sole, co, n, args.regime_min)
    if args.json_out:
        payload = {
            "basis": {
                "population": "finished non-demo PaperTrade legs, deduped",
                "clock": "openedAt .. COALESCE(closedAt,resolvedAt)",
                "level": "leg",
                "hit_basis": "EXIT (realizedPnl>0)",
                "regime_min": args.regime_min,
            },
            "bands": [
                {
                    "band": "%.1f-%.1f" % b,
                    "all_time": agg([l for l in legs if l["band"] == b]),
                    "regime": agg([l for l in legs if l["band"] == b and l["regime"]]),
                }
                for b in BANDS
            ],
        }
        with open(args.json_out, "w") as fh:
            json.dump(payload, fh, indent=2)
        print("\nwrote %s" % args.json_out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
