#!/usr/bin/env python3
"""Compare rule-based vs local-LLM sentiment scores (Phase Local-1 A/B).

Reads ~/polymarket-copybot/data/sentiment-ab.jsonl (written in shadow mode by
the research bot's local_sentiment.py) and reports:

  * coverage (how many items got a local score — server uptime proxy)
  * Pearson correlation rule vs local
  * sign-agreement rate (bullish/bearish/neutral agreement)
  * direction flips with samples (the actionable disagreements)
  * largest magnitude disagreements

Output: console summary + data/sentiment-ab-summary.json.

Usage:  python3 scripts/compare-sentiment.py
"""
import json
import math
import os
import statistics
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AB_PATH = os.path.join(ROOT, "data", "sentiment-ab.jsonl")
OUT = os.path.join(ROOT, "data", "sentiment-ab-summary.json")

POS = 0.05  # |s| above this counts as directional


def sign(s):
    if s is None:
        return None
    return 1 if s > POS else -1 if s < -POS else 0


def pearson(xs, ys):
    n = len(xs)
    if n < 3:
        return None
    mx, my = statistics.mean(xs), statistics.mean(ys)
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    vx = sum((x - mx) ** 2 for x in xs)
    vy = sum((y - my) ** 2 for y in ys)
    if vx == 0 or vy == 0:
        return None
    return cov / math.sqrt(vx * vy)


def main():
    rows = []
    if os.path.exists(AB_PATH):
        with open(AB_PATH) as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        rows.append(json.loads(line))
                    except Exception:
                        pass

    if not rows:
        print("No A/B rows yet — run the research bot a few cycles (shadow mode) and re-run.")
        return

    n = len(rows)

    def model_of(r):
        return r.get("model") or "qwen2.5:7b-instruct"  # legacy rows pre-2026-09-08

    def stats_for(rs, dedupe=False):
        rr = rs
        if dedupe:  # item-level honesty: the log re-scores the same bills every 6h cycle
            seen = {}
            for r in rs:
                seen[(r.get("source"), r.get("item_id"))] = r
            rr = list(seen.values())
        with_local = [r for r in rr if r.get("local_sentiment") is not None]
        pairs = [(r["rule_sentiment"], r["local_sentiment"]) for r in with_local
                 if r.get("rule_sentiment") is not None and r.get("local_sentiment") is not None]
        if not pairs:
            return None
        corr = pearson([p[0] for p in pairs], [p[1] for p in pairs])
        agree = sum(1 for r, l in pairs if sign(r) == sign(l))
        return {
            "n": len(rr), "withLocal": len(with_local),
            "coverage": len(with_local) / len(rr),
            "correlation": corr, "signAgreement": agree / len(pairs),
            "agree": agree, "pairs": len(pairs),
        }

    by_model = {}
    for r in rows:
        by_model.setdefault(model_of(r), []).append(r)

    overall = stats_for(rows)
    per_model = {m: stats_for(rs) for m, rs in sorted(by_model.items())}
    per_model_unique = {m: stats_for(rs, dedupe=True) for m, rs in sorted(by_model.items())}

    # current lane = model that produced the most recent row
    current = model_of(rows[-1])
    cur_rows = by_model.get(current, [])

    flips = [r for r in cur_rows
             if r.get("rule_sentiment") is not None and r.get("local_sentiment") is not None
             and sign(r["rule_sentiment"]) == 1 and sign(r["local_sentiment"]) == -1]
    flips2 = [r for r in cur_rows
              if r.get("rule_sentiment") is not None and r.get("local_sentiment") is not None
              and sign(r["rule_sentiment"]) == -1 and sign(r["local_sentiment"]) == 1]
    diffs = sorted(
        cur_rows,
        key=lambda r: abs((r.get("rule_sentiment") or 0) - (r.get("local_sentiment") or 0)),
        reverse=True,
    )[:5]

    summary = {
        "analyzedAt": datetime.now(timezone.utc).isoformat(),
        "n": n,
        "withLocal": overall["withLocal"] if overall else 0,
        "coverage": round(overall["coverage"], 3) if overall else None,
        "correlation": round(overall["correlation"], 3) if overall and overall["correlation"] is not None else None,
        "signAgreement": round(overall["signAgreement"], 3) if overall else None,
        "currentModel": current,
        "ruleBullishLocalBearish": len(flips),
        "ruleBearishLocalBullish": len(flips2),
        "byModel": {m: {"n": s["n"], "rows": s["pairs"],
                        "signAgreement": round(s["signAgreement"], 3),
                        "correlation": round(s["correlation"], 3) if s["correlation"] is not None else None}
                    for m, s in per_model.items() if s},
        "uniqueItems": {m: {"n": s["n"], "signAgreement": round(s["signAgreement"], 3)}
                        for m, s in per_model_unique.items() if s},
    }

    def fmt(m, s):
        if not s or not s["pairs"]:
            return None
        unique = per_model_unique.get(m)
        u = f" · {unique['agree']}/{unique['pairs']} unique ({unique['signAgreement'] * 100:.0f}%)" if unique and unique["pairs"] else ""
        c = f" · corr {s['correlation']:.2f}" if s["correlation"] is not None else ""
        return f"**{m}**: {s['agree']}/{s['pairs']} rows ({s['signAgreement'] * 100:.0f}%){u}{c}"

    lines = ["🧪 **Sentiment A/B — Rules vs Local LLM (per model)**"]
    if overall and per_model.get(current):
        lines.append(f"Current lane {fmt(current, per_model[current])}")
    for m in sorted(per_model):
        if m != current:
            f = fmt(m, per_model[m])
            if f:
                lines.append(f"Legacy {f}")
    if flips:
        lines.append("**Bullish→bearish samples (current lane):**")
        for r in flips[:3]:
            lines.append(f"- [{r['source']}] {r['text'][:70]}… rule {r['rule_sentiment']} vs local {r['local_sentiment']} ({r.get('local_reason', '')})")
    if flips2:
        lines.append("**Bearish→bullish samples (current lane):**")
        for r in flips2[:3]:
            lines.append(f"- [{r['source']}] {r['text'][:70]}… rule {r['rule_sentiment']} vs local {r['local_sentiment']} ({r.get('local_reason', '')})")
    if diffs:
        lines.append("**Largest magnitude disagreements (current lane):**")
        for r in diffs[:3]:
            lines.append(f"- [{r['source']}] rule {r['rule_sentiment']} vs local {r['local_sentiment']} — {r['text'][:60]}…")

    digest = "\n".join(lines)
    with open(OUT, "w") as f:
        json.dump(summary, f, indent=2)
    print(digest)
    print(f"\nWrote {OUT}")


if __name__ == "__main__":
    main()
