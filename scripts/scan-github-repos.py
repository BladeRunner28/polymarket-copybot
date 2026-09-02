#!/usr/bin/env python3
"""Weekly GitHub scout for prediction-market repositories worth auditing.

Triage layer ONLY (cheap, mechanical): metadata + README skim via the GitHub
search API. Deep audits stay human/agent-side. Applies the pipeline-capacity
gate from data/roadmap.json so the treadmill stays under control.

Filters: not previously seen, stars/activity bar, license flagged (not
filtered — Polyseer had none and was still a useful reference).

Output: ranked digest to stdout (delivered to Discord by the cron job),
seen-repos persisted to data/github-scout-seen.json, digest saved to
data/github-scout-latest.md.

Usage:  python3 scripts/scan-github-repos.py
"""
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SEEN_PATH = os.path.join(ROOT, "data", "github-scout-seen.json")
DIGEST_PATH = os.path.join(ROOT, "data", "github-scout-latest.md")
ROADMAP_PATH = os.path.join(ROOT, "data", "roadmap.json")

API = "https://api.github.com/search/repositories"
HEADERS = {"User-Agent": "copybot-scout", "Accept": "application/vnd.github+json"}
MIN_STARS_ACTIVE = 20  # stars bar for recently-pushed repos
ACTIVE_DAYS = 120  # "recently pushed"
MIN_STARS_MATURE = 150  # stars bar for older-but-mature repos
MAX_QUERIES = 6
SLEEP_BETWEEN = 8  # unauthenticated search limit is 10/min

QUERIES = [
    "topic:prediction-markets",
    "polymarket in:name,description",
    "kalshi in:name,description",
    "prediction market in:name,description",
    "prediction-market in:name",
    "forecasting platform in:description",
]

# Relevance keywords -> weight. The gap map tells us *why* a repo matters.
KEYWORDS = {
    "polymarket": 2, "kalshi": 2, "prediction market": 2, "prediction-market": 2,
    "forecasting": 1, "arbitrage": 1, "arb": 1, "copy trade": 2, "copy-trade": 2,
    "whale": 1, "negrisk": 1, "neg_risk": 1, "backtest": 1, "order book": 1,
    "dashboard": 1, "trading bot": 1, "odds": 1, "betting": 1, "fill": 1,
    "wallet": 1, "crypto": 0, "ml": 0, "ai": 0,
}

# Previously audited / known repos (full_name).
SEEN_DEFAULT = [
    "jon-becker/prediction-market-analysis",
    "braedonsaunders/homerun",
    "yorkeccak/Polyseer",
    "YichengYang-Ethan/oracle3",
    "QURIresearch/metaforecasts",
]


def load_seen():
    try:
        with open(SEEN_PATH) as f:
            return set(json.load(f))
    except Exception:
        return set(SEEN_DEFAULT)


def save_seen(seen):
    os.makedirs(os.path.dirname(SEEN_PATH), exist_ok=True)
    with open(SEEN_PATH, "w") as f:
        json.dump(sorted(seen), f, indent=2)


def api_get(url):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)


def search(query, per_page=30):
    q = urllib.parse.quote(query)
    try:
        d = api_get(f"{API}?q={q}&sort=stars&order=desc&per_page={per_page}")
        return d.get("items", [])
    except Exception as e:
        print(f"  [scout] query failed ({query}): {e}", file=sys.stderr)
        return []


def score_repo(r):
    text = " ".join(
        [
            str(r.get("name", "")),
            str(r.get("description", "") or ""),
            " ".join(r.get("topics", []) or []),
        ]
    ).lower()
    s = 0
    hits = []
    for kw, w in KEYWORDS.items():
        if kw in text:
            s += w
            hits.append(kw)
    # Stars nudge (log scale), tiny repos need more relevance.
    s += min(3, max(0, (r.get("stargazers_count", 0) // 100)))
    return s, sorted(set(hits))


def license_of(r):
    lic = r.get("license")
    if not lic:
        return "NO-LICENSE"
    return lic.get("spdx_id") or lic.get("key") or "?"


def main():
    seen = load_seen()
    now = datetime.now(timezone.utc)
    candidates = {}

    for i, q in enumerate(QUERIES[:MAX_QUERIES]):
        for item in search(q):
            full = item["full_name"]
            if full.lower() in seen:
                continue
            stars = item.get("stargazers_count", 0)
            try:
                pushed = datetime.fromisoformat(item["pushed_at"].replace("Z", "+00:00"))
            except Exception:
                pushed = datetime.min.replace(tzinfo=timezone.utc)
            age_days = (now - pushed).days
            active = age_days <= ACTIVE_DAYS
            if not (stars >= MIN_STARS_MATURE or (stars >= MIN_STARS_ACTIVE and active)):
                continue
            score, hits = score_repo(item)
            if score < 2:
                continue
            candidates[full] = {
                "full_name": full,
                "url": item.get("html_url", ""),
                "stars": stars,
                "license": license_of(item),
                "pushed_days_ago": age_days,
                "desc": (item.get("description") or "")[:160],
                "score": score,
                "hits": hits,
                "lang": item.get("language"),
            }
        if i < MAX_QUERIES - 1:
            time.sleep(SLEEP_BETWEEN)

    # Capacity gate from the roadmap board: if anything is In Progress or
    # Scheduled, the pipeline is full -> candidates are watch-only.
    gate = "audit-candidate"
    try:
        with open(ROADMAP_PATH) as f:
            board = json.load(f)
        busy = [c["title"] for c in board["cards"] if c["column"] in ("In Progress", "Scheduled")]
        if busy:
            gate = "watch-only (pipeline busy: " + "; ".join(t[:40] for t in busy[:2]) + ")"
    except Exception:
        pass

    ranked = sorted(candidates.values(), key=lambda c: -c["score"])
    top = ranked[:5]

    lines = [
        "🔭 **Prediction-Market Repo Scout**",
        f"Scanned {len(QUERIES)} queries · {len(candidates)} new candidates · top {len(top)}",
        f"**Gate:** {gate}",
        "",
    ]
    if not top:
        lines.append("No new candidates cleared the bar this week — nothing to audit.")
    for c in top:
        lines.append(
            f"**{c['full_name']}** — {c['stars']}★ · {c['license']} · {c['lang'] or '?'} · "
            f"pushed {c['pushed_days_ago']}d ago · relevance {c['score']}"
        )
        lines.append(f"> {c['desc']}")
        lines.append(f"> keywords: {', '.join(c['hits'])}")
        lines.append("")
    lines.append("Seen list updated. Deep audit only if it maps to an open gap or pipeline has room.")

    digest = "\n".join(lines)
    os.makedirs(os.path.dirname(DIGEST_PATH), exist_ok=True)
    with open(DIGEST_PATH, "w") as f:
        f.write(digest + "\n")

    for c in top:
        seen.add(c["full_name"].lower())
    save_seen(seen)

    print(digest)


if __name__ == "__main__":
    main()
