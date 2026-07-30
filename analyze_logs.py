import os
import re
from datetime import datetime

# Path definitions
LOG_DIR = "/Users/xsnyde2/polymarket-copybot/logs/cron"
MONITOR_LOG = os.path.join(LOG_DIR, "copybot-monitor-score.log")
PNL_LOG = os.path.join(LOG_DIR, "copybot-update-pnl.log")
SCAN_LOG = os.path.join(LOG_DIR, "copybot-scan-wallets.log")
EOD_LOG = os.path.join(LOG_DIR, "copybot-eod.log")

CUTOFF_TIME = datetime.strptime("2026-07-20T09:40:00", "%Y-%m-%dT%H:%M:%S")

def parse_runs(file_path):
    if not os.path.exists(file_path):
        return []
    
    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()
        
    # Split by runs
    run_blocks = re.split(r"=== run (2026-07-\d{2}T\d{2}:\d{2}:\d{2}) ===", content)
    
    runs = []
    # run_blocks[0] is everything before first run
    # then pairs of (timestamp, block_content)
    for i in range(1, len(run_blocks), 2):
        ts_str = run_blocks[i]
        block_content = run_blocks[i+1]
        try:
            ts = datetime.strptime(ts_str, "%Y-%m-%dT%H:%M:%S")
        except ValueError:
            continue
            
        if ts >= CUTOFF_TIME:
            runs.append({
                "timestamp": ts,
                "timestamp_str": ts_str,
                "content": block_content
            })
            
    return runs

def analyze_monitor():
    runs = parse_runs(MONITOR_LOG)
    total_runs = len(runs)
    lockfile_skips = 0
    completed = 0
    errored = 0
    rate_limits = 0
    observed_trades = 0
    paper_copies = 0
    watchlist = 0
    skips = 0
    
    for r in runs:
        content = r["content"]
        if "lockfile-skip" in content or "previous run still active — skipping" in content:
            lockfile_skips += 1
            continue
            
        # Check for error or completed
        is_errored = False
        if "Error" in content or "failed" in content.lower() or "aborted" in content.lower():
            # some sub-steps can fail, let's see if we count it as completed scoring
            pass
            
        if "Scoring complete" in content or "No unscored trades" in content:
            completed += 1
        else:
            errored += 1
            
        # Rate limits
        # HTTP 429, Error 1015, rate limited
        if "429" in content or "rate limited" in content.lower() or "1015" in content:
            rate_limits += content.lower().count("429") + content.lower().count("1015") + content.lower().count("rate limited")
            
        # Observed trades
        match_obs = re.search(r"Trade monitor complete:\s*(\d+)\s*new", content)
        if match_obs:
            observed_trades += int(match_obs.group(1))
            
        # Scoring details
        match_score = re.search(r"Scoring complete:\s*(\d+)\s*paper copies,\s*(\d+)\s*watchlist,\s*(\d+)\s*skips", content)
        if match_score:
            paper_copies += int(match_score.group(1))
            watchlist += int(match_score.group(2))
            skips += int(match_score.group(3))
            
    print(f"--- Monitor-Score (Total Runs: {total_runs}) ---")
    print(f"Completed: {completed}")
    print(f"Lockfile Skips: {lockfile_skips}")
    print(f"Errored: {errored}")
    print(f"Rate limits (429/1015/rate limited found in text): {rate_limits}")
    print(f"Observed trades: {observed_trades}")
    print(f"Paper copies: {paper_copies}")
    print(f"Watchlist: {watchlist}")
    print(f"Skips: {skips}")
    print()

def analyze_pnl():
    runs = parse_runs(PNL_LOG)
    total_runs = len(runs)
    lockfile_skips = 0
    completed = 0
    errored = 0
    rate_limits = 0
    
    for r in runs:
        content = r["content"]
        if "lockfile-skip" in content or "previous run still active" in content:
            lockfile_skips += 1
            continue
            
        if "PnL update complete" in content or "Update complete" in content or "complete" in content.lower():
            completed += 1
        else:
            errored += 1
            
        if "429" in content or "rate limited" in content.lower() or "1015" in content:
            rate_limits += 1
            
    print(f"--- Update-PnL (Total Runs: {total_runs}) ---")
    print(f"Completed: {completed}")
    print(f"Lockfile Skips: {lockfile_skips}")
    print(f"Errored: {errored}")
    print(f"Rate limits: {rate_limits}")
    print()

def analyze_scan():
    runs = parse_runs(SCAN_LOG)
    total_runs = len(runs)
    lockfile_skips = 0
    completed = 0
    errored = 0
    rate_limits = 0
    
    for r in runs:
        content = r["content"]
        if "lockfile-skip" in content or "previous run still active" in content:
            lockfile_skips += 1
            continue
            
        if "scan complete" in content.lower() or "complete" in content.lower():
            completed += 1
        else:
            errored += 1
            
        if "429" in content or "rate limited" in content.lower() or "1015" in content:
            rate_limits += 1
            
    print(f"--- Scan-Wallets (Total Runs: {total_runs}) ---")
    print(f"Completed: {completed}")
    print(f"Lockfile Skips: {lockfile_skips}")
    print(f"Errored: {errored}")
    print(f"Rate limits: {rate_limits}")
    print()

def analyze_eod():
    runs = parse_runs(EOD_LOG)
    total_runs = len(runs)
    completed = 0
    errored = 0
    
    for r in runs:
        content = r["content"]
        if "sent to discord" in content.lower() or "complete" in content.lower() or "eod report" in content.lower():
            completed += 1
        else:
            errored += 1
            
    print(f"--- EOD (Total Runs: {total_runs}) ---")
    print(f"Completed: {completed}")
    print(f"Errored: {errored}")
    print()

if __name__ == "__main__":
    analyze_monitor()
    analyze_pnl()
    analyze_scan()
    analyze_eod()
