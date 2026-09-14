#!/usr/bin/env python3
import subprocess, os, json, re

BASE = "/tmp/pm_audit"
# keyword -> weight; we want real scoring/ranking math, not crypto token stuff
PATTERNS = {
    "wallet_score": r"wallet[_ ]?score|score[_ ]?wallet|trader[_ ]?score|wallet[_ ]?quality|wallet[_ ]?ranking|rank[_ ]?wallet",
    "shrinkage_eb": r"shrinkage|empirical[_ ]?bayes|beta[_ ]?prior|posterior[_ ]?mean|james[_ ]?stein|kelly[_ ]?shrink|credible[_ ]?interval",
    "sharp_money": r"sharp[_ ]?money|smart[_ ]?money|informed[_ ]?trader|sophisticated[_ ]?trader|whale[_ ]?score",
    "winrate_bayes": r"win[_ ]?rate|winrate|hit[_ ]?rate|accuracy.*confidence|laplace[_ ]?smooth",
    "calibration": r"calibrat|brier|log[_ ]?loss|reliability[_ ]?diagram|platt|isotonic",
    "copy_signal": r"copy[_ ]?score|copy[_ ]?signal|signal[_ ]?score|conviction[_ ]?score|confidence[_ ]?score|edge[_ ]?score",
    "elo_glicko": r"\belo\b|glicko|trueskill|elo[_ ]?rating|rank[_ ]?aggregat",
    "roi_pnl_rank": r"\broi\b|pnl|profit[_ ]?factor|sharpe|sortino|drawdown",
    "microstructure": r"order[_ ]?book|orderbook|spread|slippage|depth|microstructure|fill[_ ]?rate|latency|adverse[_ ]?selection",
    "ml_model": r"xgboost|lightgbm|sklearn|random[_ ]?forest|logistic[_ ]?regression|train[_ ]?model|feature[_ ]?importance",
    "predictive_evidence": r"out[_ ]?of[_ ]?sample|walk[_ ]?forward|backtest|auc|roc[_ ]?auc|precision[_ ]?recall|p[_ ]?value|significan",
    "stub_markers": r"\bTODO\b|\bFIXME\b|not[_ ]?implemented|placeholder|raise NotImplementedError|mock",
}

def scan(path):
    try:
        out = subprocess.run(["rg","-l","-i","-g","!*.md","-g","!*.json","-g","!*.csv",
                              "-g","!*.lock","-g","!node_modules","-g","!.git",
                              "-e", PATTERNS["wallet_score"], "-e", PATTERNS["shrinkage_eb"],
                              "-e", PATTERNS["sharp_money"], "-e", PATTERNS["calibration"],
                              "-e", PATTERNS["copy_signal"], "-e", PATTERNS["elo_glicko"],
                              "-e", PATTERNS["microstructure"], "-e", PATTERNS["ml_model"],
                              path],
                             capture_output=True, text=True, timeout=120)
        files = [f for f in out.stdout.strip().split("\n") if f]
        return files
    except Exception as e:
        return []

summary = {}
for name in sorted(os.listdir(BASE)):
    p = os.path.join(BASE, name)
    if not os.path.isdir(p): continue
    files = scan(p)
    # code file count (py/ts/js/rs/go)
    code = subprocess.run(["bash","-c",
        f"find {p} -type f \\( -name '*.py' -o -name '*.ts' -o -name '*.js' -o -name '*.tsx' -o -name '*.rs' -o -name '*.go' \\) -not -path '*/node_modules/*' -not -path '*/.git/*' | wc -l"],
        capture_output=True, text=True).stdout.strip()
    loc = subprocess.run(["bash","-c",
        f"find {p} -type f \\( -name '*.py' -o -name '*.ts' -o -name '*.js' -o -name '*.tsx' -o -name '*.rs' -o -name '*.go' \\) -not -path '*/node_modules/*' -not -path '*/.git/*' -exec cat {{}} + 2>/dev/null | wc -l"],
        capture_output=True, text=True).stdout.strip()
    summary[name] = {"code_files": int(code or 0), "loc": int(loc or 0),
                     "scoring_files": [f.replace(BASE+"/"+name+"/","") for f in files][:18]}

with open("/Users/xsnyde2/polymarket-copybot/drafts/_audit_scratch/grep_summary.json","w") as f:
    json.dump(summary, f, indent=1)

for k,v in summary.items():
    print(f"\n### {k}  (files={v['code_files']} loc={v['loc']})")
    for f in v["scoring_files"]:
        print("   ", f)
