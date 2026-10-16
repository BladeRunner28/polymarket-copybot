#!/usr/bin/env python3
"""
radar-yield.py — the instrument behind the research agent's REC 1 (pre-registered radar yield).

REC 1 asks: over 12 daily runs, do the two `updated`-sorted GitHub queries yield zero *usable* slots
while the MCP/stars blocks yield at least one, and does the rotating Reddit feed 429 more than half
the time? This script answers it from data the collector logs on every run (data/radar-yield.jsonl),
so the verdict is a table lookup rather than an impression.

  python3 scripts/radar-yield.py                # aggregate + verdict state
  python3 scripts/radar-yield.py --report       # also write drafts/radar-yield-YYYYMMDD.md

"Usable" is defined once, in the collector, and never re-defined here: licence != no-licence AND
stars >= 5 AND last push within 90 days. The `drafts/` dedupe check lives in asset-queue.py's seeder
(a repo we already read is a different question from a repo that is usable).
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
LOG = REPO / "data" / "radar-yield.jsonl"
SEED_LOG = REPO / "data" / "radar-yield-seed.jsonl"
DRAFTS = REPO / "drafts"
NEEDED_RUNS = 12          # pre-registered in REC 1
UPDATED_QUERIES = ("newest Polymarket tooling", "newest Kalshi tooling")


def load() -> list[dict]:
    if not LOG.exists():
        return []
    out = []
    for line in LOG.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", action="store_true", help="write drafts/radar-yield-YYYYMMDD.md")
    a = ap.parse_args()

    runs = load()
    if not runs:
        print(f"no runs logged yet at {LOG} — the collector appends one line per run; "
              f"the verdict needs {NEEDED_RUNS}.")
        return 0

    per_query: dict[str, list[dict]] = defaultdict(list)
    reddit_status: Counter[str] = Counter()
    reddit_fail: Counter[str] = Counter()
    for r in runs:
        for q in r.get("github", []):
            per_query[q["query"]].append(q)
        for f in r.get("reddit", []):
            reddit_status[f.get("state", "?")] += 1
            if f.get("state") in ("429", "error"):
                reddit_fail[f["label"]] += 1

    n = len(runs)
    lines = [f"# Radar yield — {n} run(s) logged (need {NEEDED_RUNS} for the pre-registered verdict)", ""]
    lines.append(f"Log: `{LOG.relative_to(REPO)}` · first {runs[0].get('ts')} · last {runs[-1].get('ts')}")
    lines.append("")
    lines.append("## Per query")
    lines.append("| query | sort | runs | slots | usable | usable/run |")
    lines.append("|---|---|---|---|---|---|")
    tot_usable = 0
    for q, rows in per_query.items():
        slots = sum(x.get("slots", 0) for x in rows)
        usable = sum(x.get("usable", 0) for x in rows)
        tot_usable += usable
        lines.append(f"| {q} | {rows[0].get('sort', '?')} | {len(rows)} | {slots} | {usable} | "
                     f"{usable / max(len(rows), 1):.2f} |")
    lines.append("")
    lines.append(f"**Total usable slots: {tot_usable} over {n} run(s)** "
                 f"({tot_usable / n:.2f}/run across all queries).")
    lines.append("")
    lines.append("## Novelty (what actually reached the audit queue — usability deduped against drafts/)")
    seeds = []
    if SEED_LOG.exists():
        for line in SEED_LOG.read_text().splitlines():
            try:
                seeds.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    if not seeds:
        lines.append("- no seed runs logged yet (`asset-queue.py seed` appends one line per run)")
    else:
        added_total = sum(len(x.get("added", [])) for x in seeds)
        checked = sum(x.get("slots_checked", 0) for x in seeds)
        lines.append(f"- runs={len(seeds)} · slots checked={checked} · **added={added_total}** "
                     f"({added_total / len(seeds):.2f} new leads/run)")
        rc: Counter[str] = Counter()
        for x in seeds:
            rc.update(x.get("skip_reasons", {}))
        lines.append("- skip reasons: " + ", ".join(f"{k}={v}" for k, v in rc.most_common(6)))
        # attribute each added repo to the query that surfaced it (needs GH_STATS.repos, collector >= 2026-10-15)
        owner: dict[str, str] = {}
        for run in runs:
            for qq in run.get("github", []):
                for rp in qq.get("repos") or []:
                    owner.setdefault(rp, qq["query"])
        per_q: Counter[str] = Counter()
        unattributed = 0
        for x in seeds:
            for rp in x.get("added", []):
                if rp in owner:
                    per_q[owner[rp]] += 1
                else:
                    unattributed += 1
        if per_q:
            lines.append("- new leads by query: " + ", ".join(f"{k}={v}" for k, v in per_q.most_common()))
        if unattributed:
            lines.append(f"- {unattributed} addition(s) could not be attributed to a query "
                         f"(collector predates per-query repo logging)")

    lines.append("")
    lines.append("## Reddit feeds")
    lines.append(f"- states seen: " + ", ".join(f"{k}={v}" for k, v in sorted(reddit_status.items())))
    if reddit_fail:
        lines.append(f"- failures by feed: " + ", ".join(f"{k}={v}" for k, v in reddit_fail.most_common()))
    else:
        lines.append("- failures by feed: none logged (the 26h TTL + 3-request rotation + backoff retry)")

    # ---- verdict, only at n >= 12. Below that, say so plainly rather than half-answering.
    upd_usable = sum(x.get("usable", 0) for q in UPDATED_QUERIES for x in per_query.get(q, []))
    other_usable = tot_usable - upd_usable
    lines.append("")
    lines.append("## Pre-registered decision rule")
    if n < NEEDED_RUNS:
        lines.append(f"**INSUFFICIENT — n={n} of {NEEDED_RUNS}.** No verdict yet, by design: the rule was "
                     f"pre-registered at 12 runs, and answering early is exactly the thin-window error the "
                     f"agent is told to refuse. Current direction so far: `updated` queries "
                     f"{upd_usable} usable, other blocks {other_usable} usable.")
        if upd_usable == 0 and n >= 3:
            lines.append(f"- Note: the `updated` queries have now yielded 0 usable in {n} runs "
                         f"({sum(x.get('slots', 0) for q in UPDATED_QUERIES for x in per_query.get(q, []))} "
                         f"slots examined) — worth watching, not yet actionable.")
    else:
        if upd_usable == 0 and other_usable >= NEEDED_RUNS:
            lines.append(f"**RULE FIRES: add a `stars:>=5` (or `topic:`) floor to the two `updated`-sorted "
                         f"queries, or drop them.** Evidence: 0 usable from those queries vs {other_usable} "
                         f"from the other blocks over {n} runs.")
        elif other_usable == 0:
            lines.append(f"**RULE FIRES THE OTHER WAY: the radar yields nothing usable at all over {n} runs** "
                         f"— the queries, not the floor, are the problem. Re-scope the sources before the gate.")
        else:
            lines.append(f"**RULE DOES NOT FIRE:** `updated` {upd_usable} usable vs other blocks "
                         f"{other_usable} over {n} runs — leave `GH_QUERIES` untouched.")

    text = "\n".join(lines)
    print(text)

    if a.report:
        DRAFTS.mkdir(exist_ok=True)
        f = DRAFTS / f"radar-yield-{datetime.now().strftime('%Y%m%d')}.md"
        f.write_text(text + "\n\n*(Generated by `scripts/radar-yield.py` — read-only over "
                            "`data/radar-yield.jsonl`; no live-lane change.)*\n")
        print(f"\nwrote drafts/{f.name} → http://localhost:3013/drafts/{f.stem}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
