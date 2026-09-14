#!/usr/bin/env python3
import subprocess, json, time, os

QUERIES = [
    "polymarket insider trading detection", "polymarket wallet clustering",
    "polymarket kelly bet sizing", "kalshi market maker", "polymarket market maker",
    "brier score prediction market", "polymarket backtest", "polymarket analytics dashboard",
    "prediction market dataset", "polymarket data analysis", "polymarket arbitrage bot",
    "polymarket trading bot python", "prediction market research", "polymarket clob",
    "polymarket scoring", "kalshi trading bot", "polymarket whale alert",
    "smart money betting", "closing line value betting", "sharps sports betting model",
    "polymarket copy bot", "prediction market alpha", "polymarket wallet tracker",
    "manifold markets bots", "polymarket liquidity",
]

def run(cmd, timeout=60):
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if out.returncode != 0:
            return {"error": out.stderr.strip()[:150]}
        return json.loads(out.stdout)
    except Exception as e:
        return {"error": str(e)[:150]}

allrepos = {}
errors = []
for q in QUERIES:
    r = run(["gh", "api", "-X", "GET", "search/repositories",
             "-f", f"q={q}", "-f", "sort=stars", "-f", "order=desc", "-f", "per_page=25"])
    if "error" in r: errors.append((q, r["error"])); continue
    for it in r.get("items", []):
        full = it["full_name"]
        if full not in allrepos:
            allrepos[full] = {"full_name": full, "stars": it.get("stargazers_count"),
                "pushed_at": it.get("pushed_at"), "lang": it.get("language"),
                "license": (it.get("license") or {}).get("spdx_id"),
                "desc": (it.get("description") or "")[:160],
                "topics": it.get("topics", []), "forks": it.get("forks_count")}
    time.sleep(0.6)

# CODE SEARCH: find repos containing actual scoring functions
CODE_QUERIES = [
    "wallet_score polymarket", "sharp_money score", "wallet skill estimate",
    "empirical bayes wallet", "copy_score polymarket", "trader_score prediction market",
    "smart_money_score", "wallet_quality", "calibration brier market",
]
code_hits = {}
for q in CODE_QUERIES:
    r = run(["gh", "api", "-X", "GET", "search/code",
             "-f", f"q={q}", "-f", "per_page=40"])
    if "error" in r: errors.append((q, r["error"])); continue
    for it in r.get("items", []):
        repo = it["repository"]["full_name"]
        code_hits.setdefault(repo, []).append(it.get("path"))
    time.sleep(1.5)

with open("/Users/xsnyde2/polymarket-copybot/drafts/_audit_scratch/gh_search2_raw.json", "w") as f:
    json.dump({"repos": allrepos, "code_hits": code_hits}, f, indent=1)

print(f"round2 unique repos={len(allrepos)} code_hit_repos={len(code_hits)} errors={len(errors)}")
print("=== CODE HIT REPOS (repos with scoring-ish code) ===")
for repo, paths in sorted(code_hits.items()):
    print(f"{repo:<60} {paths[:3]}")
print("\n=== TOP ROUND-2 REPOS by stars ===")
for r in sorted(allrepos.values(), key=lambda x: x["stars"] or 0, reverse=True)[:60]:
    print(f"{r['full_name']:<55} {r['stars'] or 0:>5} {(r['pushed_at'] or '')[:10]:>11} {(r['license'] or 'NONE'):>12} {r['lang']}")
