#!/usr/bin/env python3
"""Persist the Kalshi shadow OOS verdict before the model refit resets it.

WHY THIS EXISTS
---------------
data/shadow-score-model.json is refit by ~/.hermes/scripts/copybot-kalshi-shadow.sh
whenever the artifact is older than 7 days. kalshi-shadow.py derives
shadowScoreSplit.oosStartedMs from the artifact's as_of_ms, so EVERY refit moves the
"opened after fit" clock forward and discards the accumulated out-of-sample record
(the only honest forward evidence this shadow has, n<30 and slow to accrue).

This script appends a line to data/kalshi-shadow-oos-history.jsonl whenever the OOS
read changes (new settlement or new PnL), so the record survives the refit and the
frozen artifact copy (data/shadow-score-model-frozen-<fit>.json) still allows an
exact re-score afterwards.

OBSERVABILITY ONLY. Reads data/kalshi-shadow-summary.json and appends a JSONL line.
Never touches rules, sizing, routing, positions, or the live lane. Fully idempotent:
re-running with no change appends nothing.
"""
import json
import os
import sys
import time

SUMMARY = "data/kalshi-shadow-summary.json"
HISTORY = "data/kalshi-shadow-oos-history.jsonl"


def main():
    if not os.path.exists(SUMMARY):
        print("missing %s - nothing to archive" % SUMMARY)
        return 0
    s = json.load(open(SUMMARY))
    ss = s.get("shadowScoreSplit") or {}
    o, r = ss.get("oosSinceFit") or {}, ss.get("oosRejected") or {}
    if not o:
        print("no oosSinceFit block - nothing to archive")
        return 0

    row = {
        "archivedMs": int(time.time() * 1000),
        "asOf": s.get("asOf"),
        "asOfMs": s.get("asOfMs"),
        "oosStartedMs": ss.get("oosStartedMs"),
        "modelFittedAt": (s.get("model") or {}).get("fittedAt"),
        "nTrain": (s.get("model") or {}).get("nTrain"),
        "sel": {k: o.get(k) for k in ("n", "n_settled", "n_open", "pnl", "roi_pct", "win_rate_pct")},
        "rej": {k: r.get(k) for k in ("n", "n_settled", "n_open", "pnl", "roi_pct", "win_rate_pct")},
        "selExTop1": {k: (o.get("exTop1") or {}).get(k) for k in ("n_settled", "pnl", "roi_pct", "droppedTradeId", "droppedPnl")},
        "rejExTop1": {k: (r.get("exTop1") or {}).get(k) for k in ("n_settled", "pnl", "roi_pct", "droppedTradeId", "droppedPnl")},
    }

    last = None
    if os.path.exists(HISTORY):
        try:
            with open(HISTORY) as fh:
                for line in fh:
                    line = line.strip()
                    if line:
                        last = json.loads(line)
        except Exception as exc:  # a corrupt tail must not block new appends
            print("warn: could not parse %s (%s) - appending anyway" % (HISTORY, exc))

    if last:
        same_clock = last.get("oosStartedMs") == row["oosStartedMs"]
        same_read = (
            (last.get("sel") or {}).get("n_settled") == row["sel"]["n_settled"]
            and (last.get("rej") or {}).get("n_settled") == row["rej"]["n_settled"]
            and (last.get("sel") or {}).get("pnl") == row["sel"]["pnl"]
            and (last.get("rej") or {}).get("pnl") == row["rej"]["pnl"]
        )
        if same_clock and same_read:
            print("oos history unchanged (sel n_settled=%s) - no line appended"
                  % row["sel"]["n_settled"])
            return 0
        if not same_clock:
            # The clock moved: this is a refit. Say so in the record, loudly.
            row["note"] = ("CLOCK RESET: oosStartedMs %s -> %s (refit). Rows above this "
                           "line are the archived pre-refit OOS record."
                           % (last.get("oosStartedMs"), row["oosStartedMs"]))

    with open(HISTORY, "a") as fh:
        fh.write(json.dumps(row, sort_keys=True) + "\n")
    print("appended OOS snapshot: sel n_settled=%s pnl=%.2f | rej n_settled=%s pnl=%.2f"
          % (row["sel"]["n_settled"], row["sel"]["pnl"] or 0.0,
             row["rej"]["n_settled"], row["rej"]["pnl"] or 0.0))
    return 0


if __name__ == "__main__":
    sys.exit(main())
