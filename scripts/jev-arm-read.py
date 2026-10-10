#!/usr/bin/env python3
"""The JEV shadow lane's read — both model arms against the price, with the diagnostics that decide
whether a comparison MEANS anything.

`data/jev-shadow-summary.json` (written by scripts/mark-shadow-jev.ts) prints the pre-registered
comparison for the LEADING arm. This script reads the same append-only logs and adds what that
summary cannot express:

  1. A SECOND ARM — the blind replay (`data/jev-blind.jsonl`, scripts/jev-blind-replay.ts), which asks
     the same model the same question with every price field withheld.
  2. Anchoring / parroting: the leading arm is handed `implied_probability` and asked to re-derive it,
     so an exact echo is its failure mode. The blind arm's failure modes are the mirror image: a
     CONSTANT answer (no belief at all) and a degenerate spread.
  3. CLUSTERED confidence intervals. Legs inside one market share an outcome, so a plain bootstrap
     understates the error; the intervals here resample MARKET CLUSTERS. A delta whose interval
     straddles zero is noise, however good it looks.
  4. The pre-registered gate's counterfactual (net of the taker fee) for every arm, and the action
     mix — a veto lane earns by what it SKIPS, and a veto count is not a cost.
  5. Per-category reads at n>=50, or the bucket is reported unreadable rather than quoted.

Read-only. Usage: python3 scripts/jev-arm-read.py [--boot 2000] [--file data/jev-shadow.jsonl]
"""

from __future__ import annotations

import argparse
import collections
import json
import math
import random
import statistics
import sys

MIN_N = 50  # pre-registered minimum: below it everything is unreadable, not failed
TAKER = 0.10  # fee per share = TAKER x min(p, 1-p), archive-era schedule
LINE = "-" * 78


def auc(scores: list[float], labels: list[int]) -> float | None:
    """Rank AUC, ties by average rank (identical to the lane's TS implementation)."""
    if not scores:
        return None
    pos, neg = sum(labels), len(labels) - sum(labels)
    if pos == 0 or neg == 0:
        return None
    order = sorted(range(len(scores)), key=lambda i: scores[i])
    ranks = [0.0] * len(scores)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and scores[order[j + 1]] == scores[order[i]]:
            j += 1
        avg = (i + j) / 2 + 1
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    s = sum(ranks[i] for i in range(len(scores)) if labels[i] == 1)
    return (s - pos * (pos + 1) / 2) / (pos * neg)


def brier(probs: list[float], labels: list[int]) -> float | None:
    return sum((p - y) ** 2 for p, y in zip(probs, labels)) / len(probs) if probs else None


def logloss(probs: list[float], labels: list[int]) -> float | None:
    if not probs:
        return None
    eps = 1e-9
    total = 0.0
    for p, y in zip(probs, labels):
        p = min(1 - eps, max(eps, p))
        total += -(y * math.log(p) + (1 - y) * math.log(1 - p))
    return total / len(probs)


def median(xs: list[float]) -> float | None:
    return statistics.median(xs) if xs else None


def pearson(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) < 3:
        return None
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    num = sum((a - mx) * (b - my) for a, b in zip(xs, ys))
    dx = math.sqrt(sum((a - mx) ** 2 for a in xs))
    dy = math.sqrt(sum((b - my) ** 2 for b in ys))
    return num / (dx * dy) if dx and dy else None


def net_pnl(price: float, label: int) -> float:
    """Net-of-fee PnL per unit staked: the lane's own counterfactual."""
    f = TAKER * min(price, 1 - price)
    return (1 - price - f) / price if label == 1 else -1 - f / price


def pct(x: float | None) -> str:
    return "—" if x is None else f"{100 * x:.1f}%"


def fmt(x: float | None, d: int = 4) -> str:
    return "—" if x is None else f"{x:.{d}f}"


def cluster_bootstrap(cells: list[dict], arm: str, base: str, boot: int, seed: int = 20261010) -> dict:
    """Clustered (by market) bootstrap of ΔAUC and ΔBrier between `arm` and `base` on the same legs.

    Legs inside one market are not independent — they share an outcome — so resampling markets (with
    replacement) is the interval that can actually say 'this delta is not noise'.
    """
    clusters: dict[str, list[dict]] = collections.defaultdict(list)
    for c in cells:
        clusters[c["cluster"]].append(c)
    keys = list(clusters)
    rng = random.Random(seed)
    dauc: list[float] = []
    dbrier: list[float] = []
    for _ in range(boot):
        flat = [c for _ in range(len(keys)) for c in clusters[keys[rng.randrange(len(keys))]]]
        y = [c["label"] for c in flat]
        a_auc, b_auc = auc([c[arm] for c in flat], y), auc([c[base] for c in flat], y)
        a_br, b_br = brier([c[arm] for c in flat], y), brier([c[base] for c in flat], y)
        if a_auc is None or b_auc is None or a_br is None or b_br is None:
            continue
        dauc.append(a_auc - b_auc)
        dbrier.append(a_br - b_br)
    if len(dauc) < 100:
        return {"n_boot": len(dauc)}
    dauc.sort()
    dbrier.sort()
    lo, hi = int(0.025 * len(dauc)), int(0.975 * len(dauc)) - 1
    return {
        "n_boot": len(dauc),
        "n_clusters": len(keys),
        "n_legs": len(cells),
        "d_auc": statistics.mean(dauc),
        "auc_ci": (dauc[lo], dauc[hi]),
        "auc_excludes_zero": not (dauc[lo] <= 0 <= dauc[hi]),
        "d_brier": statistics.mean(dbrier),
        "brier_ci": (dbrier[lo], dbrier[hi]),
        "brier_excludes_zero": not (dbrier[lo] <= 0 <= dbrier[hi]),
    }


def load_legs(shadow_file: str) -> tuple[dict, dict]:
    rows = [json.loads(l) for l in open(shadow_file) if l.strip()]
    by_key: dict[str, dict] = {}
    for r in rows:
        if r.get("type") != "candidate":
            continue
        key = f"{r.get('decisionJournalId')}|{r.get('marketId')}|{r.get('outcome')}"
        prev = by_key.get(key)
        if prev is None:
            by_key[key] = r
            continue
        prev_has = prev.get("jevProbability") is not None
        cur_has = r.get("jevProbability") is not None
        if cur_has and not prev_has:
            by_key[key] = r
        elif cur_has == prev_has and str(r.get("ts")) >= str(prev.get("ts")):
            by_key[key] = r
    resolves = {
        f"{r.get('marketId')}|{r.get('outcome')}": r.get("value")
        for r in rows
        if r.get("type") == "resolve"
    }
    return by_key, resolves


def load_blind(blind_file: str) -> dict:
    try:
        rows = [json.loads(l) for l in open(blind_file) if l.strip()]
    except FileNotFoundError:
        return {}
    return {r["key"]: r for r in rows if r.get("jevBlindProbability") is not None}


def leg_key(c: dict) -> str:
    return f"{c.get('decisionJournalId')}|{c.get('marketId')}|{c.get('outcome')}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", default="data/jev-shadow.jsonl")
    ap.add_argument("--blind", default="data/jev-blind.jsonl")
    ap.add_argument("--summary", default="data/jev-shadow-summary.json")
    ap.add_argument("--boot", type=int, default=2000)
    args = ap.parse_args()

    by_key, resolves = load_legs(args.file)
    blind = load_blind(args.blind)
    cand = list(by_key.values())
    leading = [c for c in cand if c.get("jevProbability") is not None]

    print(LINE)
    print(f"legs: {len(cand)} deduped candidates | with a LEADING arm: {len(leading)} | replayed BLIND: {len(blind)}")
    print(f"model on the newest leading row: {leading[-1].get('model') if leading else '—'}"
          f" | blind model: {next(iter(blind.values()), {}).get('model', '—')}")

    # ---- instrument health of each arm ------------------------------------------------------
    lat = [float(c["jevLatencyMs"]) for c in leading if isinstance(c.get("jevLatencyMs"), (int, float))]
    fail = collections.Counter(
        str(c.get("jevError"))[:60] for c in cand if c.get("jevProbability") is None
    )
    print(f"leading arm: {len(leading)}/{len(cand)} legs answered, failures {dict(fail.most_common(4)) or 'none'}"
          + (f", median {median(lat):.0f} ms/call" if lat else ""))
    blat = [float(r["latencyMs"]) for r in blind.values() if isinstance(r.get("latencyMs"), (int, float))]
    bfail = sum(1 for r in blind.values() if r.get("error"))
    print(f"blind  arm: {len(blind)} legs answered, {bfail} with an error recorded"
          + (f", median {median(blat):.0f} ms/call" if blat else ""))

    # ---- the scoring population -------------------------------------------------------------
    scored = []
    for c in cand:
        v = resolves.get(f"{c.get('marketId')}|{c.get('outcome')}")
        entry = c.get("entryPrice")
        if v is None or not isinstance(entry, (int, float)) or not 0 < entry < 1:
            continue
        b = blind.get(leg_key(c)) or {}
        scored.append({
            "cluster": str(c.get("marketId")),
            "label": 1 if v > entry else 0,
            "price": float(entry),
            "leading": None if c.get("jevProbability") is None else float(c["jevProbability"]),
            "blind": b.get("jevBlindProbability"),
            "action": c.get("jevAction"),
            "cat": c.get("marketCategory") or "?",
            "copyScore": c.get("copyScore"),
        })
    if not scored:
        print("no resolved legs with a price — nothing to read")
        return 1

    y_all = [s["label"] for s in scored]
    p_all = [s["price"] for s in scored]
    clusters = len({s["cluster"] for s in scored})
    print(LINE)
    print(f"RESOLVED LEGS: {len(scored)} across {clusters} market clusters"
          f" | base rate (label=1) {pct(sum(y_all) / len(y_all))}"
          f" | copy-all net/leg {fmt(statistics.mean([net_pnl(s['price'], s['label']) for s in scored]))}")
    print(f"PRICE  arm  n={len(scored):5d} AUC {fmt(auc(p_all, y_all))} Brier {fmt(brier(p_all, y_all))} "
          f"logLoss {fmt(logloss(p_all, y_all))}")
    for name, label in (("leading", "LEADING"), ("blind", "BLIND  ")):
        sub = [s for s in scored if s[name] is not None]
        if not sub:
            print(f"{label} arm  n=0 (no rows yet)")
            continue
        ys = [s["label"] for s in sub]
        ps = [s[name] for s in sub]
        print(f"{label} arm  n={len(sub):5d} AUC {fmt(auc(ps, ys))} Brier {fmt(brier(ps, ys))} "
              f"logLoss {fmt(logloss(ps, ys))}")
        cs = [(s["copyScore"], s["label"]) for s in sub if isinstance(s.get("copyScore"), (int, float))]
        if cs:
            print(f"{'':12s}copyScore on those same rows: AUC {fmt(auc([a for a, _ in cs], [b for _, b in cs]))}"
                  f" (n={len(cs)})")

    # ---- anchoring / belief diagnostics, per arm --------------------------------------------
    for name in ("leading", "blind"):
        sub = [s for s in scored if s[name] is not None]
        if len(sub) < MIN_N:
            continue
        vals = [s[name] for s in sub]
        pr = [s["price"] for s in sub]
        exact = sum(1 for a, b in zip(vals, pr) if abs(a - b) < 1e-9) / len(vals)
        within1 = sum(1 for a, b in zip(vals, pr) if abs(a - b) <= 0.01) / len(vals)
        d = [abs(a - b) for a, b in zip(vals, pr)]
        distinct = len(set(round(v, 6) for v in vals))
        half = sum(1 for v in vals if abs(v - 0.5) < 1e-9) / len(vals)
        pspread, jspread = statistics.pstdev(pr), statistics.pstdev(vals)
        print(LINE)
        print(f"{name.upper()} BELIEF: exact price echo {pct(exact)} | within 1c {pct(within1)} | "
              f"mean |delta| {fmt(sum(d) / len(d))} | corr {fmt(pearson(vals, pr))}")
        print(f"{'':14s}distinct values {distinct} | at exactly 0.5 {pct(half)} | "
              f"stdev(price) {fmt(pspread)} vs stdev({name}) {fmt(jspread)}"
              + (f" ({fmt(jspread / pspread, 2)}x)" if pspread else " (degenerate spread)"))

    # ---- clustered intervals on the deltas that matter --------------------------------------
    both = [s for s in scored if s["leading"] is not None and s["blind"] is not None]
    if len(both) >= MIN_N:
        for arm in ("leading", "blind"):
            cells = [{"cluster": s["cluster"], "price": s["price"], "label": s["label"],
                      "arm": s[arm], "base": s["price"]} for s in both]
            r = cluster_bootstrap(cells, "arm", "base", args.boot)
            if "d_auc" in r:
                print(LINE)
                print(f"Δ({arm} - price), same {r['n_legs']} legs / {r['n_clusters']} clusters, "
                      f"{r['n_boot']} bootstraps:")
                print(f"  ΔAUC   {r['d_auc']:+.4f}  95% CI [{r['auc_ci'][0]:+.4f}, {r['auc_ci'][1]:+.4f}]"
                      f"  -> {'EXCLUDES 0' if r['auc_excludes_zero'] else 'STRADDLES 0 (noise)'}")
                print(f"  ΔBrier {r['d_brier']:+.4f}  95% CI [{r['brier_ci'][0]:+.4f}, {r['brier_ci'][1]:+.4f}]"
                      f"  -> {'EXCLUDES 0' if r['brier_excludes_zero'] else 'STRADDLES 0 (noise)'}")
        cells = [{"cluster": s["cluster"], "price": s["price"], "label": s["label"],
                  "arm": s["blind"], "base": s["leading"]} for s in both]
        r = cluster_bootstrap(cells, "arm", "base", args.boot)
        if "d_auc" in r:
            print(LINE)
            print(f"Δ(blind - leading), the same {r['n_legs']} legs:")
            print(f"  ΔAUC   {r['d_auc']:+.4f}  95% CI [{r['auc_ci'][0]:+.4f}, {r['auc_ci'][1]:+.4f}]"
                  f"  -> {'EXCLUDES 0' if r['auc_excludes_zero'] else 'STRADDLES 0 (noise)'}")
            print(f"  ΔBrier {r['d_brier']:+.4f}  95% CI [{r['brier_ci'][0]:+.4f}, {r['brier_ci'][1]:+.4f}]"
                  f"  -> {'EXCLUDES 0' if r['brier_excludes_zero'] else 'STRADDLES 0 (noise)'}")

    # ---- the pre-registered gate's counterfactual, per arm ----------------------------------
    print(LINE)
    copy_all = statistics.mean([net_pnl(s["price"], s["label"]) for s in scored])
    print(f"GATE @0.55 (keep if prob >= 0.55), net of the taker fee. copy-all net/leg {fmt(copy_all)}:")
    for name in ("leading", "blind"):
        sub = [s for s in scored if s[name] is not None]
        if len(sub) < MIN_N:
            continue
        kept = [s for s in sub if s[name] >= 0.55]
        vetoed = [s for s in sub if s[name] < 0.55]
        k = statistics.mean([net_pnl(s["price"], s["label"]) for s in kept]) if kept else None
        v = statistics.mean([net_pnl(s["price"], s["label"]) for s in vetoed]) if vetoed else None
        verdict = "BEATS" if (k is not None and k > copy_all) else "does NOT beat"
        print(f"  {name:8s} kept n={len(kept):5d} net/leg {fmt(k)} vs copy-all -> {verdict} | "
              f"vetoed n={len(vetoed):5d} net/leg {fmt(v)}")

    # ---- action mix (leading arm only: the blind arm answers no action question) -------------
    lead = [s for s in scored if s["leading"] is not None]
    if lead:
        print(LINE)
        print("ACTION mix (leading arm; realised net PnL/stake):")
        for act in ("copy", "watch", "skip", None):
            sub = [s for s in lead if (s["action"] or None) == act]
            if not sub:
                continue
            yy = [s["label"] for s in sub]
            print(f"  {str(act):6s} n={len(sub):5d} win {pct(sum(yy) / len(yy)):>6s} "
                  f"mean PnL/leg {statistics.mean([net_pnl(s['price'], s['label']) for s in sub]):+.4f}")

    # ---- per-category at n>=MIN_N -----------------------------------------------------------
    print(LINE)
    print(f"PER-CATEGORY (n>={MIN_N} only):")
    for name in ("leading", "blind"):
        cats = collections.Counter(s["cat"] for s in scored if s[name] is not None)
        printed = False
        for cat, n in cats.most_common():
            if n < MIN_N:
                continue
            sub = [s for s in scored if s["cat"] == cat and s[name] is not None]
            ys = [s["label"] for s in sub]
            print(f"  {name:8s} {cat[:26]:26s} n={n:4d} AUC {name} {fmt(auc([s[name] for s in sub], ys), 3)} "
                  f"price {fmt(auc([s['price'] for s in sub], ys), 3)}")
            printed = True
        if not printed:
            print(f"  {name}: no bucket reaches n>={MIN_N}")
        thin = [f"{c}({n})" for c, n in cats.most_common() if n < MIN_N]
        if thin:
            print(f"    unreadable buckets ({name}): {', '.join(thin)}")

    # ---- the pre-registered verdict, quoted from the summary the lane wrote -----------------
    try:
        s = json.load(open(args.summary))
        g = s.get("gate", {})
        print(LINE)
        print(f"LANE SUMMARY ({s.get('generatedAt')}): candidates {s.get('candidates')}, "
              f"withModel {s.get('withModel')}, resolvedWithModel {s.get('resolvedWithModel')}, "
              f"barReadable {s.get('barReadable')}, beatsPriceOnly {s.get('beatsPriceOnly')}")
        print(f"  gate already written: kept n={g.get('keptN')} net/leg "
              f"{fmt(g.get('keptMeanPnlPerStakeNetOfFee'))} vs copy-all "
              f"{fmt(g.get('copyAllMeanPnlPerStakeNetOfFee'))}; improves {g.get('improves')}")
    except FileNotFoundError:
        print(f"(no {args.summary} yet)")
    print(LINE)
    return 0


if __name__ == "__main__":
    sys.exit(main())
