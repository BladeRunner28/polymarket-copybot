#!/usr/bin/env python3
import subprocess, json, sys, time, urllib.parse, os

QUERIES = [
    "polymarket wallet score", "polymarket smart money", "polymarket copy trading",
    "polymarket copytrading", "polymarket signal scoring", "polymarket whale tracker",
    "polymarket ranking wallets", "polymarket alpha", "polymarket insider trading",
    "polymarket leaderboard", "kalshi model calibration", "kalshi trading bot score",
    "kalshi smart money", "prediction market calibration", "prediction market model",
    "prediction market smart money", "prediction market ranking", "prediction market machine learning",
    "event contract model", "manifold markets bot", "manifold markets prediction",
    "sharp money detection", "sports betting model calibration", "betting model edge probability",
    "polymarket trader analysis", "polymarket pnl", "prediction market copy trade",
    "polymarket scoring bot", "trader skill estimation", "wallet skill prediction market",
]

def gh_search(q, sort="stars", per_page=30):
    cmd = ["gh", "api", "-X", "GET", "search/repositories",
           "-f", f"q={q}", "-f", f"sort={sort}", "-f", "order=desc",
           "-f", f"per_page={per_page}"]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if out.returncode != 0:
            return {"error": out.stderr.strip()[:200]}
        return json.loads(out.stdout)
    except Exception as e:
        return {"error": str(e)[:200]}

allrepos = {}
errors = []
for q in QUERIES:
    r = gh_search(q)
    items = r.get("items", []) if isinstance(r, dict) else []
    if "error" in r:
        errors.append((q, r["error"]))
    for it in items:
        full = it["full_name"]
        if full not in allrepos:
            allrepos[full] = {
                "full_name": full,
                "stars": it.get("stargazers_count"),
                "pushed_at": it.get("pushed_at"),
                "created_at": it.get("created_at"),
                "lang": it.get("language"),
                "size": it.get("size"),
                "license": (it.get("license") or {}).get("spdx_id"),
                "desc": (it.get("description") or "")[:200],
                "topics": it.get("topics", []),
                "forks": it.get("forks_count"),
                "archived": it.get("archived"),
                "queries": [q],
            }
        else:
            allrepos[full]["queries"].append(q)
    time.sleep(0.6)

os.makedirs("/Users/xsnyde2/polymarket-copybot/drafts/_audit_scratch", exist_ok=True)
with open("/Users/xsnyde2/polymarket-copybot/drafts/_audit_scratch/gh_search_raw.json", "w") as f:
    json.dump(allrepos, f, indent=1)

print(f"QUERIES={len(QUERIES)} unique_repos={len(allrepos)} errors={len(errors)}")
for e in errors: print("ERR", e)
# sort by stars
ranked = sorted(allrepos.values(), key=lambda x: (x["stars"] or 0), reverse=True)
print(f"\n{'REPO':<52} {'STARS':>6} {'PUSHED':>11} {'LIC':>12} LANG")
for r in ranked:
    print(f"{r['full_name']:<52} {r['stars'] or 0:>6} {(r['pushed_at'] or '')[:10]:>11} {(r['license'] or 'NONE'):>12} {r['lang']}")
