#!/usr/bin/env python3
import subprocess, json, os, time

SHORTLIST = [
    # prediction-market scoring / ranking / wallet skill
    "vobornij/polymarket", "DavidSMazur/gnosicular", "Cachaza/polymarket-scanner",
    "Gurdiel07/polymarket-bot", "JamesFletty/maths", "curtisgc1/trader-curtis-public",
    "aAAaqwq/AGI-Super-Team", "tmk11/PolymarketWalletScan", "winder87-stack/-polymarket-copy-bot",
    "lbsm2017/polyMDash", "leoaguiarguedes/CopyTraderPolymarket", "seer-pm/demo",
    "meta-xucong/POLY_SMARTMONEY", "mateogon/hermes-polymarket-clob2-agent",
    "jt8530-beep/weather", "samuraifrenchienft/Prediction-Agent", "abhinandan202004/Vantage",
    "Marzel7/flex", "feecrookz-bit/basement-archive", "pdqrobinson/trading-desk",
    "tshore2004/polymarket-trader", "Ksmith18skc/SignalForge", "AntoineROYERB/polymarketpricer",
    "hackfly-bit/PolyDeeper", "nirholas/three.ws", "nexiumito/polycopy",
    "Timaroc13/polymarket-engine", "pselamy/polymarket-insider-tracker",
    "chainstacklabs/polymarket-alpha-bot", "al1enjesus/polymarket-whales",
    "NickNaskida/polymarket-insider-bot", "devfchen/joker", "BRKME/Polymarket_insider",
    "suislanchez/polymarket-insider-detector", "ent0n29/aware",
    # sportsbook sharp-money / edge scoring (cross-domain)
    "anashp78/MaxEvSports", "PGRSPORTSANALYTICS/Sportsanalytics", "childersjac-max/Line-Tracker-Model",
    "ddcolletti-edgesetter/edge-setter", "Griff843/unit-talk-production", "jeat14/sports-betting-bot",
    # manifold / microprediction
    "microprediction/manifoldbot", "manifoldmarkets/market-maker", "vluzko/manifoldpy",
    "ksadov/manifold-llm-bot", "minosvasilias/gpt-manifold",
    # other
    "kachence/prediction-almanac", "humanplane/terminal", "Drakkar-Software/OctoBot-Prediction-Market",
    "realfishsam/Polymarket-Copy-Trader", "shmlkv/polymarket-copy-trading-bot",
    "dexoryn-china/polymarket-copy-trading-bot", "dexorynlabs/polymarket-copy-trading-bot",
    "jeknuzz/predict-raven", "caiovicentino/polymarket-mcp-server",
    # known project repos
    "YichengYang-Ethan/oracle3", "braedonsaunders/homerun", "yorkeccak/Polyseer",
]

def get(full):
    out = subprocess.run(["gh","api",f"repos/{full}"], capture_output=True, text=True, timeout=45)
    if out.returncode != 0:
        return {"full_name": full, "error": out.stderr.strip()[:100]}
    try:
        d = json.loads(out.stdout)
    except Exception as e:
        return {"full_name": full, "error": str(e)[:100]}
    return {
        "full_name": d.get("full_name"), "stars": d.get("stargazers_count"),
        "forks": d.get("forks_count"), "pushed_at": (d.get("pushed_at") or "")[:10],
        "created_at": (d.get("created_at") or "")[:10], "lang": d.get("language"),
        "size_kb": d.get("size"), "license": (d.get("license") or {}).get("spdx_id"),
        "desc": (d.get("description") or "")[:150], "archived": d.get("archived"),
        "topics": d.get("topics", [])[:10], "open_issues": d.get("open_issues_count"),
        "default_branch": d.get("default_branch"),
    }

res = []
for f in SHORTLIST:
    r = get(f)
    res.append(r)
    time.sleep(0.25)

with open("/Users/xsnyde2/polymarket-copybot/drafts/_audit_scratch/shortlist_meta.json","w") as fh:
    json.dump(res, fh, indent=1)

print(f"{'REPO':<52} {'LIC':>13} {'STARS':>6} {'KB':>7} {'PUSHED':>11} LANG")
for r in sorted(res, key=lambda x: x.get("stars") or 0, reverse=True):
    if "error" in r:
        print(f"{r['full_name']:<52} !! {r['error']}")
    else:
        print(f"{r['full_name']:<52} {str(r['license']):>13} {r['stars'] or 0:>6} {r['size_kb'] or 0:>7} {r['pushed_at']:>11} {r['lang']}")
