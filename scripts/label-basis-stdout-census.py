#!/usr/bin/env python3
"""LABEL-BASIS CENSUS: does every arm that PRINTS a probability metric name its BASIS?

Card `label-integrity-stdout-basis`. Three bases, one printed figure each:
  OUTCOME  did the token we hold resolve as the winner (venue settlement / archive label)
  EXIT     did OUR leg make money (realizedPnl > 0) -- depends on the exit policy under test
  MARK     a live mark / curPrice read, never a resolution
An arm that prints "win rate 0.484" without saying which of the three it is reproduces the
2026-10-26 defect measured in scripts/label-basis-audit.py: on the SAME legs, switching the
basis moves win rate 0.484 -> 0.626, price-arm AUC 0.6508 -> 0.7427 and Brier 0.2373 -> 0.2067.

READ-ONLY: no DB, no network. It reads the printed line, not the number.
  --self-test  proves the detector can go RED (a gate that cannot fail is not a gate)
Exit 1 while any censused arm prints a metric without a basis token.

POPULATION (2026-11-06, Lane B): the census reads the HAND-LISTED files in CENSUS only, so
"RESULT: PASS" describes those files and nothing else. A discovery pass now prints every other
file in scope that prints a metric, with how many of its arms lack a basis token -- before it
existed the PASS was read as universal while the daily-delivered cron status blocks were never
in the population at all.
"""
import os
import re
import sys

VALUE = re.compile(r":\s*[^}]*[fdeg]\s*\}|%[-+ 0-9.]*[fd]|fmt\(")
TOKEN_RE = re.compile(r"basis|outcome|(?:^|[^a-z])exit(?:$|[^a-z])|(?:^|[^a-z])mark(?:$|[^a-z])", re.I)
# 2026-11-06 (self-audit, Lane B): the original pattern missed the form our cron status
# blocks actually use -- `win=46%` / `win=  49%` (copybot-kalshi-shadow.sh), `win%`-only.
# A census whose detector cannot see the printed form reports a clean screen, not a clean
# corpus: the delivered Kalshi block carried 3 such arms and scored 0 lines.
METRIC = re.compile(r"win[ _-]?rate|winrate|win%|\bwin(?:%?\[[A-Za-z_]+\]|%)?\s*=|AUC|Brier|brier|hit rate|hit%")
EMIT = re.compile("print[(]|console[.](log|warn|error)")

# Files this instrument actually reads. It is a HAND-MAINTAINED list, so a PASS describes
# these files ONLY -- discovery() below prints what the list misses, every run.
DISCOVERY_DIRS = ("scripts", "scripts/cron-scripts", "scripts/cron-gates", "src/lib", "src/app")
DISCOVERY_EXTS = (".py", ".ts", ".sh", ".js")

CENSUS = {
 "scripts/analyze-calibration.py": "exit+outcome (both printed)",
 "scripts/analyze-band-exit-exemption.ts": "outcome (settlementSource per row)",
 "scripts/analyze-score-separation.py": "EXIT (closed+resolved, realizedPnl>0)",
 "scripts/analyze-change2-gates.py": "EXIT (closed+resolved, pnl>0)",
 "scripts/drift-band-winrate-read.py": "OUTCOME (resolved token value)",
 "scripts/entry-floor-replay.py": "EXIT (replay pnl>0)",
 "scripts/fit-price-edge.py": "EXIT (y_win = pnl>0)",
 "scripts/jev-arm-read.py": "OUTCOME (resolved value vs entry)",
 "scripts/kalshi-lane-status.py": "OUTCOME (window direction)",
 "scripts/measure-category-fit-basis.py": "EXIT (pnl>0 on closed+resolved)",
 "scripts/ml-near-certainty-read.py": "EXIT (roi_net>0)",
 "scripts/ml-online.py": "OUTCOME (y_side_win)",
 "scripts/ml-prepare.py": "OUTCOME (y_side_win)",
 "scripts/ml-train.py": "OUTCOME (y_side_win)",
 "scripts/ml-train-market.py": "EXIT (roi_net>0)",
 "scripts/ml1-bar-restatement.ts": "EXIT (pnl_net_entry>0)",
 "scripts/pilot-score-separation.py": "OUTCOME (finalOutcome vs outcome)",
 "scripts/pilot-score-separation-papers.py": "EXIT (realizedPnl>0, stated in header)",
 "scripts/profit-exits.py": "EXIT (realizedPnl>0)",
 "scripts/profit-velocity.py": "EXIT (realizedPnl>0)",
 "scripts/rag-vs-price-baseline.py": "EXIT, resolvedAt-only subset (caveat printed)",
 "scripts/skip-edge-probe.py": "OUTCOME proxy for skips, EXIT for copies",
 "scripts/wallet-concentration-test.py": "EXIT (pnl>0, printed as leg won)",
 "scripts/wallet-depth-floor-test.py": "EXIT (pnl>0, printed as leg won)",
 "scripts/wallet-selection-test.py": "EXIT (y_win and net>0)",
 "scripts/wallet-selection-score-information.py": "EXIT (states basis at L291)",
 "scripts/build-decision-dataset.py": "EXIT (y_win = pnl>0)",
 "scripts/archive-wallet-persistence-bandneutral.py": "OUTCOME (archive outcome_label)",
 "scripts/label-basis-audit.py": "all three, side by side (this is the oracle)",
}


def strip_quoted(s):
    out, q = [], None
    for ch in s:
        if q:
            if ch == q:
                q = None
            continue
        if ch in (chr(39), chr(34), chr(96)):
            q = ch
            continue
        out.append(ch)
    return "".join(out)


def classify(lines):
    metric, last = [], -1000
    for i, l in enumerate(lines, 1):
        s = l.strip()
        if not s or s[0] in ("#", "*"):
            continue
        if EMIT.search(s) and TOKEN_RE.search(s):
            last = i
        if EMIT.search(s) and METRIC.search(s) and VALUE.search(s):
            metric.append((i, s, i - last <= 12))
    unnamed = [(i, s) for i, s, named in metric if not named]
    return metric, unnamed


def discover(root):
    """Files that PRINT a metric but are NOT in CENSUS -- the population the pass misses.

    2026-11-06 (self-audit, Lane B): CENSUS is hand-written, so "RESULT: PASS" used to be
    read as "every arm names its basis" when it meant "every arm in these 29 files". Measured
    before this function existed: the shipped cron status blocks (scripts/cron-scripts/*.sh,
    delivered to Discord daily) carried win arms that were never in the population at all.
    """
    out = {}
    for sub in DISCOVERY_DIRS:
        d = os.path.join(root, sub)
        if not os.path.isdir(d):
            continue
        for fn in sorted(os.listdir(d)):
            if not fn.endswith(DISCOVERY_EXTS):
                continue
            rel = (sub + "/" + fn)
            if rel in CENSUS:
                continue
            try:
                lines = open(os.path.join(d, fn), errors="replace").read().split("\n")
            except OSError:
                continue
            metric, unnamed = classify(lines)
            if metric:
                out[rel] = (len(metric), len(unnamed))
    return out


def main(argv):
    if "--self-test" in argv:
        good, ug = classify(["print(  win rate[EXIT: pnl>0] {x:.3f}"])
        bad, ub = classify(["print(  win rate {x:.3f}"])
        ok = len(ug) == 0 and len(ub) == 1 and len(good) == 1 and len(bad) == 1
        print("self-test: named line clean = %s | unnamed line flagged = %s" % (len(ug) == 0, len(ub) == 1))
        print("SELF-TEST " + ("PASS" if ok else "FAIL"))
        return 0 if ok else 1
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    total = named = unnamed_n = 0
    failed = []
    print("LABEL-BASIS CENSUS -- every arm that PRINTS a win-rate/AUC/Brier/hit-rate line")
    print("%-54s %-46s %5s %5s %5s" % ("file", "basis", "lines", "named", "UNNAMED"))
    for rel, basis in sorted(CENSUS.items()):
        p = os.path.join(root, rel)
        if not os.path.exists(p):
            print("%-54s %-46s %5s %5s %5s" % (rel, basis, "-", "-", "MISSING"))
            failed.append(rel)
            continue
        metric, unnamed = classify(open(p).read().split("\n"))
        total += len(metric)
        named += len(metric) - len(unnamed)
        unnamed_n += len(unnamed)
        print("%-54s %-46s %5d %5d %5d" % (rel, basis, len(metric), len(metric) - len(unnamed), len(unnamed)))
        for i, s in unnamed:
            print("    UNNAMED L%d: %s" % (i, s[:100]))
            failed.append(rel)
    print("")
    stray = discover(root)
    stray_lines = sum(v[0] for v in stray.values())
    print("OUTSIDE THIS CENSUS (prints a metric, not in the hand-written file list): %d files / %d arm lines"
          % (len(stray), stray_lines))
    for rel, (m, u) in sorted(stray.items(), key=lambda kv: -kv[1][0]):
        print("    %-52s %3d arms %2d without a basis token" % (rel, m, u))
    print("")
    print("ARM LINES %d | NAMED %d | UNNAMED %d  (population: %d hand-listed files)" % (total, named, unnamed_n, len(CENSUS)))
    print("An UNNAMED arm is not by itself a wrong NUMBER -- it is a printed figure that does not")
    print("say what it measures, which is the exact class this card closed. Any UNNAMED line is FAIL.")
    print("SCOPE: this PASS/FAIL covers the %d hand-listed files ONLY. The %d files / %d lines above are"
          % (len(CENSUS), len(stray), stray_lines))
    print("NOT covered and were NOT audited -- a PASS here is not a statement about them.")
    print("RESULT: " + ("FAIL" if failed else "PASS"))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
