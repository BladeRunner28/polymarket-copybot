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
    with_local = [r for r in rows if r.get("local_sentiment") is not None]
    coverage = len(with_local) / n

    pairs = [(r["rule_sentiment"], r["local_sentiment"]) for r in with_local
             if r.get("rule_sentiment") is not None and r.get("local_sentiment") is not None]
    corr = pearson([p[0] for p in pairs], [p[1] for p in pairs]) if pairs else None

    agree = sum(1 for r, l in pairs if sign(r) == sign(l))
    agree_rate = agree / len(pairs) if pairs else None

    flips = [r for r in with_local
             if r.get("rule_sentiment") is not None
             and sign(r["rule_sentiment"]) == 1 and sign(r["local_sentiment"]) == -1]
    flips2 = [r for r in with_local
              if r.get("rule_sentiment") is not None
              and sign(r["rule_sentiment"]) == -1 and sign(r["local_sentiment"]) == 1]

    diffs = sorted(
        with_local,
        key=lambda r: abs((r.get("rule_sentiment") or 0) - (r.get("local_sentiment") or 0)),
        reverse=True,
    )[:5]

    by_source = {}
    for r in with_local:
        by_source.setdefault(r.get("source", "?"), [0, 0])
        by_source[r["source"]][1] += 1
        if r.get("local_sentiment") is not None:
            by_source[r["source"]][0] += 1

    summary = {
        "analyzedAt": datetime.now(timezone.utc).isoformat(),
        "n": n,
        "withLocal": len(with_local),
        "coverage": round(coverage, 3),
        "correlation": round(corr, 3) if corr is not None else None,
        "signAgreement": round(agree_rate, 3) if agree_rate is not None else None,
        "ruleBullishLocalBearish": len(flips),
        "ruleBearishLocalBullish": len(flips2),
        "sources": {k: {"withLocal": v[0], "total": v[1]} for k, v in by_source.items()},
    }

    lines = [
        "🧪 **Sentiment A/B — Rules vs Local LLM (qwen2.5:7b)**",
        f"Items: {n} · local coverage: {coverage * 100:.0f}% · "
        f"correlation: {corr:.2f}" if corr is not None else "correlation: n/a",
        f"Sign agreement: {agree_rate * 100:.0f}% ({agree}/{len(pairs)})"
        if agree_rate is not None else "sign agreement: n/a",
        f"Direction flips: rule↔local {len(flips)} bullish→bearish, {len(flips2)} bearish→bullish",
    ]
    if flips:
        lines.append("**Bullish→bearish samples (rule was wrong?):**")
        for r in flips[:3]:
            lines.append(f"- [{r['source']}] {r['text'][:70]}… rule {r['rule_sentiment']} vs local {r['local_sentiment']} ({r.get('local_reason', '')})")
    if flips2:
        lines.append("**Bearish→bullish samples:**")
        for r in flips2[:3]:
            lines.append(f"- [{r['source']}] {r['text'][:70]}… rule {r['rule_sentiment']} vs local {r['local_sentiment']} ({r.get('local_reason', '')})")
    if diffs:
        lines.append("**Largest magnitude disagreements:**")
        for r in diffs[:3]:
            lines.append(f"- [{r['source']}] rule {r['rule_sentiment']} vs local {r['local_sentiment']} — {r['text'][:60]}…")

    digest = "\n".join(lines)
    with open(OUT, "w") as f:
        json.dump(summary, f, indent=2)
    print(digest)
    print(f"\nWrote {OUT}")


if __name__ == "__main__":
    main()
