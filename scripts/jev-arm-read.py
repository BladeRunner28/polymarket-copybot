#!/usr/bin/env python3
"""Read the JEV shadow lane's arms — including the one thing the summary cannot see.

`data/jev-shadow-summary.json` (written by scripts/mark-shadow-jev.ts) already prints the
pre-registered comparison: PRICE arm vs JEV arm on the SAME resolved legs, plus the gate. This
script reads the same append-only log and adds the diagnostics that decide whether that comparison
MEANS anything:

  1. anchoring / parroting — a chat model handed `implied_probability` in the state can answer the
     market price back at us. If |jev - entryPrice| is ~0, the arm re-derives the price and its
     AUC/tie profile is the price's own, not a second opinion. Measured as: exact-equality share,
     mean |delta|, correlation, and the share of answers within 1 cent.
  2. spread — the public scanner's own caveat on this model class was that its probabilities came
     back less than half as spread out as the order book. A flattened arm cannot rank.
  3. action mix — copy/watch/skip shares and each bucket's realised PnL/leg, because a veto lane
     earns by what it SKIPS (a veto count is not a cost).
  4. per-category read at n>=50, or the bucket is reported unreadable rather than quoted.
  5. instrument health for the drain itself: parse-failure share, latency, token counts.

Read-only. Usage: python3 scripts/jev-arm-read.py [--file data/jev-shadow.jsonl]
"""

from __future__ import annotations

import argparse
import collections
import json
import math
import statistics
import sys

MIN_N = 50  # the pre-registered minimum; below it everything is "unreadable", not "failed"


def auc(scores: list[float], labels: list[int]) -> float | None:
    """Rank AUC with ties handled by average rank (identical to the lane's TS implementation)."""
    if not scores:
        return None
    pos = sum(labels)
    neg = len(labels) - pos
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
    if not probs:
        return None
    return sum((p - y) ** 2 for p, y in zip(probs, labels)) / len(probs)


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


def pct(x: float | None) -> str:
    return "—" if x is None else f"{100 * x:.1f}%"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", default="data/jev-shadow.jsonl")
    ap.add_argument("--summary", default="data/jev-shadow-summary.json")
    args = ap.parse_args()

    rows = [json.loads(line) for line in open(args.file) if line.strip()]

    # Dedupe exactly as the lane does: one row per leg, preferring the row with a model arm.
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
    cand = list(by_key.values())
    resolves = {f"{r.get('marketId')}|{r.get('outcome')}": r.get("value") for r in rows if r.get("type") == "resolve"}

    with_arm = [c for c in cand if c.get("jevProbability") is not None]
    print(f"legs: {len(cand)} deduped candidates, {len(with_arm)} carry a model arm "
          f"({len(cand) - len(with_arm)} without), {len(resolves)} resolved markets")
    print(f"provider/model on the newest arm row: {with_arm[-1].get('model') if with_arm else '—'}")

    # ---- instrument health of the arm itself ------------------------------------------------
    errs = collections.Counter()
    lat, toks = [], []
    for c in cand:
        if c.get("jevProbability") is None:
            errs[str(c.get("jevError"))[:60]] += 1
    for c in with_arm:
        if isinstance(c.get("jevLatencyMs"), (int, float)):
            lat.append(float(c["jevLatencyMs"]))
        if isinstance(c.get("jevInputTokens"), (int, float)):
            toks.append(float(c["jevInputTokens"]))
    print(f"calls answered: {len(with_arm)} / {len(cand)}  (failures: {dict(errs.most_common(5)) or 'none'})")
    print(f"latency ms/call: median {median(lat):.0f} p90 {sorted(lat)[int(0.9 * len(lat))] if lat else 0:.0f}"
          if lat else "latency: no samples")
    print(f"prompt tokens: median {median(toks):.0f}" if toks else "prompt tokens: no samples")

    # ---- scored legs: price arm vs jev arm on the SAME rows ---------------------------------
    scored = []
    for c in cand:
        v = resolves.get(f"{c.get('marketId')}|{c.get('outcome')}")
        if v is None:
            continue
        entry = c.get("entryPrice")
        if not isinstance(entry, (int, float)) or not 0 < entry < 1:
            continue
        scored.append({"label": 1 if v > entry else 0, "price": float(entry),
                       "jev": None if c.get("jevProbability") is None else float(c["jevProbability"]),
                       "action": c.get("jevAction"), "cat": c.get("marketCategory") or "?",
                       "copyScore": c.get("copyScore")})
    both = [s for s in scored if s["jev"] is not None]
    print(f"\nresolved legs: {len(scored)}  |  resolved WITH a model arm: {len(both)}"
          f"  ({'readable' if len(both) >= MIN_N else 'BELOW the pre-registered n>=%d — unreadable' % MIN_N})")
    if scored:
        p = [s["price"] for s in scored]
        y = [s["label"] for s in scored]
        print(f"PRICE arm on those rows: AUC {auc(p, y):.4f}  Brier {brier(p, y):.4f}")
    if len(both) >= MIN_N:
        jp = [s["jev"] for s in both]
        pr = [s["price"] for s in both]
        y = [s["label"] for s in both]
        print(f"JEV   arm on the same rows: AUC {auc(jp, y):.4f}  Brier {brier(jp, y):.4f}")
        print(f"PRICE arm on the same rows: AUC {auc(pr, y):.4f}  Brier {brier(pr, y):.4f}")

        # ---- 1. anchoring / parroting ------------------------------------------------------
        d = [abs(a - b) for a, b in zip(jp, pr)]
        exact = sum(1 for a, b in zip(jp, pr) if abs(a - b) < 1e-9) / len(jp)
        within1 = sum(1 for a, b in zip(jp, pr) if abs(a - b) <= 0.01) / len(jp)
        print(f"\nANCHORING: exact price echo {pct(exact)} | within 1c {pct(within1)} | "
              f"mean |jev-price| {sum(d) / len(d):.4f} | median {median(d):.4f} | "
              f"corr {pearson(jp, pr):.4f}")
        pspread = statistics.pstdev(pr)
        jspread = statistics.pstdev(jp)
        print(f"SPREAD: stdev(price) {pspread:.4f} vs stdev(jev) {jspread:.4f} "
              f"({jspread / pspread:.2f}x the book's spread)" if pspread else "SPREAD: degenerate")

        # ---- 3. action mix ----------------------------------------------------------------
        print("\nACTION mix (realised PnL per stake, natural label):")
        for act in ("copy", "watch", "skip", None):
            sub = [s for s in both if (s["action"] or None) == act]
            if not sub:
                continue
            yy = [s["label"] for s in sub]
            pnl = sum(((1 - s["price"]) / s["price"]) if s["label"] == 1 else -1 for s in sub) / len(sub)
            print(f"  {str(act):6s} n={len(sub):5d} win {pct(sum(yy) / len(yy)):>6s} "
                  f"mean PnL/leg {pnl:+.4f}")

        # ---- 4. per-category, at n>=MIN_N only --------------------------------------------
        print(f"\nPER-CATEGORY (only buckets with n>={MIN_N}):")
        cats = collections.Counter(s["cat"] for s in both)
        for cat, n in cats.most_common():
            if n < MIN_N:
                continue
            sub = [s for s in both if s["cat"] == cat]
            yy = [s["label"] for s in sub]
            a_j = auc([s["jev"] for s in sub], yy)
            a_p = auc([s["price"] for s in sub], yy)
            print(f"  {cat[:28]:28s} n={n:4d} AUC jev {a_j:.3f} price {a_p:.3f} "
                  f"Brier jev {brier([s['jev'] for s in sub], yy):.4f} "
                  f"price {brier([s['price'] for s in sub], yy):.4f}")
        thin = [f"{c}({n})" for c, n in cats.most_common() if n < MIN_N]
        if thin:
            print(f"  unreadable buckets: {', '.join(thin)}")

    # ---- the pre-registered verdict, quoted from the summary the lane wrote -----------------
    try:
        s = json.load(open(args.summary))
        print(f"\nLANE SUMMARY ({s.get('generatedAt')}): candidates {s.get('candidates')}, "
              f"withModel {s.get('withModel')}, resolvedWithModel {s.get('resolvedWithModel')}, "
              f"barReadable {s.get('barReadable')}, beatsPriceOnly {s.get('beatsPriceOnly')}")
        g = s.get("gate", {})
        print(f"  gate @{g.get('threshold')}: kept n={g.get('keptN')} net/leg "
              f"{g.get('keptMeanPnlPerStakeNetOfFee')} vs copy-all "
              f"{g.get('copyAllMeanPnlPerStakeNetOfFee')}; vetoed n={g.get('vetoedN')} net/leg "
              f"{g.get('vetoedMeanPnlPerStakeNetOfFee')}")
    except FileNotFoundError:
        print(f"\n(no {args.summary} yet)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
