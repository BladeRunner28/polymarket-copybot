#!/usr/bin/env python3
"""Fixture test for the v62 coverage gate + recorder alarm in scripts/c200-intent-watch.py.

Temporary tree, in-process imports, no prod DB and no prod state file touched. Proves the verdicts the
gate hands to Discord: OK / gap-spanning-the-dispatch / coverage-starts-after / no-asset-map / and both
recorder_dead branches.
"""
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location("watch", os.path.join(REPO, "scripts/c200-intent-watch.py"))
w = importlib.util.module_from_spec(spec)
spec.loader.exec_module(w)

root = tempfile.mkdtemp(prefix="watchfix-")
os.makedirs(os.path.join(root, "data", "l2"))
os.makedirs(os.path.join(root, "data", "l2-events"))
w.ROOT = root
w.L2_FIX_MS = 0

T0 = 1_800_000_000_000          # arbitrary dispatch time (ms)
MIN = 60_000


def book(asset, spans):
    """spans: list of (start_ms, end_ms, step_ms) — append-only lines in ts order."""
    with open(os.path.join(root, "data", "l2", f"{asset}.jsonl"), "w") as fh:
        for start, end, step in spans:
            t = start
            while t <= end:
                fh.write(json.dumps({"ts": t, "bids": [], "asks": []}) + "\n")
                t += step


def events(asset, n):
    with open(os.path.join(root, "data", "l2-events", f"{asset}.jsonl"), "w") as fh:
        for i in range(n):
            fh.write(json.dumps({"ts": T0 - 5 * MIN + i * 1000, "pc": {"price": "0.5"}}) + "\n")


def asset_map(mapping):
    with open(os.path.join(root, "data", "l2-asset-map.jsonl"), "w") as fh:
        for m, ids in mapping.items():
            fh.write(json.dumps({"marketId": m, "assetIds": ids}) + "\n")


def intent(i):
    return {"id": f"intent{i}", "marketId": f"mkt{i}", "outcome": "YES", "intentPrice": 0.5,
            "dispatchedAt": T0}


cases = []

# A. covered: snapshots every 5s straight through the dispatch -> OK, and remembered as verified
book("A", [(T0 - 5 * MIN, T0 + 5 * MIN, 5000)])
events("A", 40)
cases.append(("A covered", 0, (T0 - 5 * MIN, T0 + 5 * MIN, 5000)))

# B. the market WAS covered days ago, then dropped: book gaps over the dispatch entirely
#    (this is the case the first version of the check passed by mistake)
book("B", [(T0 - 3 * 24 * 60 * MIN, T0 - 30 * MIN, 5000), (T0 + 20 * MIN, T0 + 30 * MIN, 5000)])

# C. pin too late: first data 7 min after the dispatch (pre-v62 signature)
book("C", [(T0 + 7 * MIN, T0 + 20 * MIN, 5000)])

# D. no asset-map entry at all -> gamma never resolved the tokens
asset_map({"mktA": ["A"], "mktB": ["B"], "mktC": ["C"], "mktE": ["E"]})

# E. long quiet market, covered before and after but the recorder stopped 4 min before dispatch and
#    resumed 3 min after: gap
book("E", [(T0 - 60 * MIN, T0 - 4 * MIN, 5000), (T0 + 3 * MIN, T0 + 10 * MIN, 5000)])

st = {"alertedLegs": [], "alertedIntents": [], "verifiedIntents": {}, "flags": {}}
intents = [intent(i) for i in ("A", "B", "C", "D", "E")]
out = w.l2_coverage_gate(intents, st)
print("=== gate verdicts ===")
for o in out:
    print(f"  {o['marketId']:6} -> {o['why']}")
ok_ids = [k for k, v in st["verifiedIntents"].items() if v == "ok"]
assert ok_ids == ["intentA"], ok_ids
assert len(out) == 4, len(out)
assert "book gap" in out[0]["why"] and "spans" in out[0]["why"]
assert "AFTER the" in out[1]["why"], out[1]
assert "no asset-map entry" in out[2]["why"], out[2]

# re-run: verified ones are not rescanned, offenders are still offenders until alerted
out2 = w.l2_coverage_gate(intents, st)
assert len(out2) == 4 and all(o["id"] != "intentA" for o in out2)
print(f"  (re-run: {len(out2)} offenders, intentA not rescanned)  OK")

# F. dedupe: an alerted id is skipped (the watcher appends offender ids to alertedIntents)
st["alertedIntents"] = [o["id"] for o in out2]
assert w.l2_coverage_gate(intents, st) == []
print("  (alerted offenders are skipped on the next tick)  OK")

print("\n=== recorder_alive branches ===")
up, why = w.recorder_alive()
print(f"  live system: up={up} why={why!r}")
assert up is True

real_run, real_mtime = subprocess.run, os.path.getmtime


class Fake:
    stdout = ""          # pgrep finds nothing


subprocess.run = lambda *a, **k: Fake()
up, why = w.recorder_alive()
print(f"  no process : up={up} why={why!r}")
assert up is False and "no `tsx scripts/record-l2.ts`" in why

subprocess.run = real_run
os.path.getmtime = lambda p: time.time() - 1000
up, why = w.recorder_alive()
print(f"  stale beat : up={up} why={why!r}")
assert up is False and "not been written for" in why

os.path.getmtime = real_mtime
print("\nALL FIXTURE ASSERTIONS PASSED")
shutil.rmtree(root)