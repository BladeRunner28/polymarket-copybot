#!/usr/bin/env python3
import subprocess, os, json

CLONES = [
    "pselamy/polymarket-insider-tracker", "chainstacklabs/polymarket-alpha-bot",
    "al1enjesus/polymarket-whales", "shmlkv/polymarket-copy-trading-bot",
    "Gurdiel07/polymarket-bot", "lbsm2017/polyMDash", "AntoineROYERB/polymarketpricer",
    "kachence/prediction-almanac", "microprediction/manifoldbot", "vluzko/manifoldpy",
    "manifoldmarkets/market-maker", "nexiumito/polycopy", "tshore2004/polymarket-trader",
    "Cachaza/polymarket-scanner", "JamesFletty/maths", "winder87-stack/-polymarket-copy-bot",
    "meta-xucong/POLY_SMARTMONEY", "jt8530-beep/weather", "samuraifrenchienft/Prediction-Agent",
    "abhinandan202004/Vantage", "tmk11/PolymarketWalletScan", "Timaroc13/polymarket-engine",
    "seer-pm/demo", "DavidSMazur/gnosicular", "humanplane/terminal",
    "leoaguiarguedes/CopyTraderPolymarket", "mateogon/hermes-polymarket-clob2-agent",
    "feecrookz-bit/basement-archive", "realfishsam/Polymarket-Copy-Trader",
    "dexoryn-china/polymarket-copy-trading-bot", "NickNaskida/polymarket-insider-bot",
    "devfchen/joker", "Ksmith18skc/SignalForge", "childersjac-max/Line-Tracker-Model",
    "Marzel7/flex",
]
BASE = "/tmp/pm_audit"
os.makedirs(BASE, exist_ok=True)
results = []
for f in CLONES:
    name = f.replace("/", "__")
    dest = os.path.join(BASE, name)
    if os.path.isdir(dest):
        results.append((f, "exists", dest)); continue
    r = subprocess.run(["git","clone","--depth","1","--quiet",
                        f"https://github.com/{f}.git", dest],
                       capture_output=True, text=True, timeout=240)
    if r.returncode == 0:
        # size
        try:
            du = subprocess.run(["du","-sk",dest], capture_output=True, text=True).stdout.split()[0]
        except Exception:
            du = "?"
        results.append((f, "ok", f"{du}KB"))
    else:
        results.append((f, "FAIL", r.stderr.strip()[:120]))
for x in results: print(x)
