#!/usr/bin/env python3
"""
asset-queue.py — the lead queue between the research agent and the asset-audit worker.

The research agent's job is to NOTICE candidates (GitHub radar / Reddit / papers); the audit worker's
job is to READ them. This file is the hand-off, so an audit cannot be lost when a daily brief fails and
cannot be duplicated when a repo resurfaces in the radar every day.

  seed    [--min-stars 5] [--max-age-days 90]   enqueue radar candidates that clear the bar
  add     --id owner/repo [--stars N] [--license X] [--note ...] [--force]
  pending [--limit 2]                           claim the next N items (status -> auditing)
  complete <id> --verdict V --report PATH [--recommend TEXT --decision-rule TEXT]
  approvals [--limit N]                         items awaiting the user's approval (reports read this)
  decide <id> --approve|--decline [--note ...]  record the user's call from the Discord thread
  result <id> --state X --note TEXT [--artifact PATH]   what the approved work actually produced
  skip    <id> --reason ...                     mark un-auditable (keys required, dead, no licence)
  status                                        counts + the newest audited items

Queue lives at data/research-asset-queue.json (repo-relative; safe to commit).
The seeder is deliberately deterministic: a bar the agent cannot fudge, and a dedupe against
drafts/ so a repo we already read is never re-audited.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
QUEUE = REPO / "data" / "research-asset-queue.json"
DRAFTS = REPO / "drafts"
FACTSHEET = REPO / "data" / "cache" / "research-recon" / "factsheet-latest.md"
SEED_LOG = REPO / "data" / "radar-yield-seed.jsonl"

# Radar lines look like:
#   - `owner/repo` ★123 · pushed 2026-10-15 · MIT · description · https://github.com/owner/repo
RADAR_RE = re.compile(
    r"^\s*-\s*`(?P<id>[\w.\-]+/[\w.\-]+)`\s*★(?P<stars>\d+)\s*·\s*pushed\s*(?P<pushed>[\d\-]+)\s*·\s*"
    r"(?P<lic>[^·]+?)\s*·(?P<rest>.*?)(?P<url>https://github\.com/\S+)?\s*$")


def now() -> str:
    return datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M %Z")


def load() -> dict:
    if QUEUE.exists():
        try:
            return json.loads(QUEUE.read_text())
        except json.JSONDecodeError as e:
            print(f"queue corrupt ({e}); refusing to overwrite — fix or delete {QUEUE}", file=sys.stderr)
            sys.exit(2)
    return {"version": 1, "items": []}


def save(q: dict) -> None:
    QUEUE.parent.mkdir(parents=True, exist_ok=True)
    QUEUE.write_text(json.dumps(q, indent=1, sort_keys=True) + "\n")


def by_id(q: dict, rid: str) -> dict | None:
    return next((i for i in q["items"] if i["id"] == rid), None)


def slug(rid: str) -> str:
    return re.sub(r"\W+", "-", rid.lower()).strip("-")


def already_drafted(rid: str) -> bool:
    """A repo we already wrote about (any draft mentioning it) is not re-audited from scratch."""
    if not DRAFTS.exists():
        return False
    needle = rid.lower()
    for f in DRAFTS.glob("*.md"):
        try:
            if needle in f.read_text(errors="replace").lower():
                return True
        except OSError:
            continue
    return False


def cmd_seed(a: argparse.Namespace) -> int:
    if not FACTSHEET.exists():
        print(f"no fact sheet at {FACTSHEET} — run the collector first (or pass --from)", file=sys.stderr)
        return 1
    text = FACTSHEET.read_text(errors="replace") if not a.from_ else Path(a.from_).read_text(errors="replace")
    q = load()
    today = datetime.now(timezone.utc).date()
    added, skipped, checked = [], [], 0
    for line in text.splitlines():
        m = RADAR_RE.match(line)
        if not m:
            continue
        checked += 1
        rid, stars, lic = m.group("id"), int(m.group("stars")), m.group("lic").strip()
        pushed = m.group("pushed").strip()
        reason = None
        if lic.lower() in ("no-licence", "no-license", "unlicensed", ""):
            reason = "no licence"
        elif stars < a.min_stars:
            reason = f"only ★{stars} (< {a.min_stars})"
        else:
            try:
                age = (today - datetime.strptime(pushed, "%Y-%m-%d").date()).days
                if age > a.max_age_days:
                    reason = f"last push {age}d ago (> {a.max_age_days})"
            except ValueError:
                reason = f"unparsable push date '{pushed}'"
        if reason:
            skipped.append(f"{rid} — {reason}")
            continue
        if by_id(q, rid):
            skipped.append(f"{rid} — already in queue")
            continue
        if already_drafted(rid):
            skipped.append(f"{rid} — already mentioned in drafts/")
            continue
        q["items"].append({
            "id": rid, "url": m.group("url") or f"https://github.com/{rid}",
            "stars": stars, "license": lic, "pushed": pushed,
            "discovered": now(), "source": "radar-seed", "status": "pending",
            "verdict": None, "report": None, "note": (m.group("rest") or "").strip(" ·")[:160],
        })
        added.append(rid)
    save(q)
    # Novelty is what REC 1 actually cares about ("0 usable" really meant "0 NEW usable"), so log it.
    reasons: dict[str, int] = {}
    for line_reason in skipped:
        key = line_reason.split(" — ")[-1].split(" (")[0][:40]
        reasons[key] = reasons.get(key, 0) + 1
    try:
        with SEED_LOG.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"ts": now(), "slots_checked": checked, "added": added,
                                 "skip_reasons": reasons}) + "\n")
    except OSError as e:
        print(f"  (seed log not written: {e})", file=sys.stderr)
    print(f"seeded: {len(added)} added from {checked} radar slots "
          f"(bar: licence ≠ none, ★≥{a.min_stars}, pushed ≤{a.max_age_days}d, not already queued/drafted)")
    for x in added:
        print(f"  + {x}")
    if skipped and a.verbose:
        print(f"  skipped {len(skipped)}: " + "; ".join(skipped[:12]))
    return 0


def cmd_add(a: argparse.Namespace) -> int:
    q = load()
    existing = by_id(q, a.id)
    if existing and not a.force:
        print(f"{a.id} already queued ({existing['status']}) — use --force to re-open")
        return 0
    q["items"] = [i for i in q["items"] if i["id"] != a.id]
    q["items"].append({
        "id": a.id, "url": a.url or f"https://github.com/{a.id}", "stars": a.stars,
        "license": a.license, "pushed": a.pushed, "discovered": now(),
        "source": a.source or "agent", "status": "pending", "verdict": None,
        "report": None, "note": (a.note or "")[:160],
    })
    save(q)
    print(f"queued {a.id} (status pending)")
    return 0


def cmd_pending(a: argparse.Namespace) -> int:
    q = load()
    # Reclaim claims from a run that died (or a job that was disabled mid-audit), otherwise a lead
    # sits in 'auditing' forever and the worker silently has nothing to do.
    import time as _t
    stale_after = a.stale_minutes * 60
    reclaimed = []
    for i in q["items"]:
        if i["status"] == "auditing":
            ts = i.get("claimed_ts")
            if ts and (_t.time() - ts) > stale_after:
                i["status"] = "pending"
                i["note"] = ((i.get("note") or "") + f" · reclaimed after {a.stale_minutes}m stale claim").strip(" ·")
                reclaimed.append(i["id"])
    if reclaimed:
        save(q)
        print(f"reclaimed {len(reclaimed)} stale claim(s): {', '.join(reclaimed)}")
    pend = [i for i in q["items"] if i["status"] == "pending"]
    claim = pend[: a.limit]
    import time as _t
    for i in claim:
        i["status"] = "auditing"
        i["claimed"] = now()
        i["claimed_ts"] = _t.time()
    if claim:
        save(q)
    print(f"pending: {len(pend)} · claiming {len(claim)}")
    for i in claim:
        print(json.dumps(i, sort_keys=True))
    if not claim and not pend:
        print("queue empty — nothing to audit (report [SILENT])")
    return 0


def cmd_complete(a: argparse.Namespace) -> int:
    q = load()
    it = by_id(q, a.id)
    if it is None:
        print(f"{a.id} not in queue", file=sys.stderr)
        return 1
    it.update(status="audited", verdict=a.verdict, report=a.report,
              note=(a.note or it.get("note") or "")[:400], audited=now())
    if a.recommend:
        it["recommendation"] = {
            "text": a.recommend, "decision_rule": a.decision_rule or "",
            "effort": a.effort or "", "reversibility": a.reversibility or "",
        }
        it["approval"] = {"state": "pending", "requested": now(), "decided": None, "decided_note": None}
    save(q)
    tail = " · recommendation recorded, awaiting approval" if a.recommend else ""
    print(f"audited {a.id}: verdict={a.verdict} report={a.report}{tail}")
    return 0


def cmd_approvals(a: argparse.Namespace) -> int:
    """Print items whose recommendation is still awaiting the user's call — the reports quote this."""
    q = load()
    pend = [i for i in q["items"]
            if (i.get("approval") or {}).get("state") == "pending" and i.get("recommendation")]
    pend.sort(key=lambda i: i.get("audited") or "")
    print(f"awaiting approval: {len(pend)}" + ("" if pend else "  (report: no approval asks today)"))
    for i in pend[: a.limit]:
        r = i["recommendation"]
        print(f"\n{i['id']} · verdict={i['verdict']} · audited {i.get('audited')} · report {i.get('report')}")
        print(f"  rec: {r['text']}")
        print(f"  decision rule: {r.get('decision_rule') or '(none stated — do not ask for approval without one)'}")
        if r.get("effort"):
            print(f"  effort: {r['effort']}")
        if r.get("reversibility"):
            print(f"  reversibility: {r['reversibility']}")
        print(f"  to decide: python3 scripts/asset-queue.py decide {i['id']} --approve|--decline --note ...")
    return 0


def cmd_decide(a: argparse.Namespace) -> int:
    q = load()
    it = by_id(q, a.id)
    if it is None:
        print(f"{a.id} not in queue", file=sys.stderr)
        return 1
    if not it.get("recommendation"):
        print(f"{a.id} has no recommendation on file — nothing to decide", file=sys.stderr)
        return 1
    state = "approved" if a.approve else "declined"
    it["approval"] = {"state": state, "requested": (it.get("approval") or {}).get("requested"),
                      "decided": now(), "decided_note": (a.note or "")[:400]}
    save(q)
    print(f"{a.id}: {state}" + (f" — {a.note}" if a.note else ""))
    return 0


def cmd_skip(a: argparse.Namespace) -> int:
    q = load()
    it = by_id(q, a.id)
    if it is None:
        print(f"{a.id} not in queue", file=sys.stderr)
        return 1
    it.update(status="skipped", verdict="skip", note=(a.reason or "")[:400], audited=now())
    save(q)
    print(f"skipped {a.id}: {a.reason}")
    return 0


def cmd_result(a: argparse.Namespace) -> int:
    """The half of the ledger that closes the loop: approval -> measurement -> outcome."""
    q = load()
    it = by_id(q, a.id)
    if it is None:
        print(f"{a.id} not in queue", file=sys.stderr)
        return 1
    it["result"] = {"state": a.state, "note": a.note, "artifact": a.artifact, "at": now()}
    save(q)
    print(f"{a.id}: result recorded — {a.state}")
    return 0


def cmd_status(a: argparse.Namespace) -> int:
    q = load()
    counts: dict[str, int] = {}
    for i in q["items"]:
        counts[i["status"]] = counts.get(i["status"], 0) + 1
    print(f"queue: {len(q['items'])} items · " + (", ".join(f"{k}={v}" for k, v in sorted(counts.items())) or "empty"))
    done = [i for i in q["items"] if i["status"] == "audited"]
    done.sort(key=lambda i: i.get("audited") or "", reverse=True)
    for i in done[:6]:
        print(f"  {i['id']:44s} {i['verdict']:12s} {i.get('audited','')}  {i.get('report') or ''}")
    awaiting = [i for i in q["items"] if (i.get("approval") or {}).get("state") == "pending"]
    if awaiting:
        print(f"  ⏳ awaiting approval ({len(awaiting)}): " + ", ".join(
            f"{i['id']}[{i['verdict']}]" for i in awaiting[:6])
            + "  ← these must appear in the next daily/weekly report until decided")
    done = [i for i in q["items"] if i.get("result")]
    for i in sorted(done, key=lambda x: x["result"].get("at") or "", reverse=True)[:5]:
        r = i["result"]
        print(f"  ✓ {i['id']:40s} {r['state']:22s} {r.get('at','')}  {r.get('artifact') or ''}")
    stale = [i for i in q["items"] if i["status"] == "auditing"]
    if stale:
        print(f"  ⚠ {len(stale)} stuck in 'auditing' (a run died): " + ", ".join(i["id"] for i in stale[:6]))
        print("    requeue with: asset-queue.py add --id <repo> --force")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="research lead queue")
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("seed"); s.add_argument("--min-stars", type=int, default=5)
    s.add_argument("--max-age-days", type=int, default=90); s.add_argument("--from", dest="from_", default=None)
    s.add_argument("--verbose", "-v", action="store_true"); s.set_defaults(func=cmd_seed)

    s = sub.add_parser("add"); s.add_argument("--id", required=True); s.add_argument("--url")
    s.add_argument("--stars", type=int, default=0); s.add_argument("--license", default="unknown")
    s.add_argument("--pushed", default=""); s.add_argument("--source"); s.add_argument("--note")
    s.add_argument("--force", action="store_true"); s.set_defaults(func=cmd_add)

    s = sub.add_parser("pending"); s.add_argument("--limit", type=int, default=2)
    s.add_argument("--stale-minutes", dest="stale_minutes", type=int, default=90,
                   help="reclaim claims older than this (a died run), default 90")
    s.set_defaults(func=cmd_pending)

    s = sub.add_parser("complete"); s.add_argument("id"); s.add_argument("--verdict", required=True)
    s.add_argument("--report", required=True); s.add_argument("--note")
    s.add_argument("--recommend", help="one-line recommendation to put to the user for approval")
    s.add_argument("--decision-rule", dest="decision_rule", help="what would settle it (required with --recommend)")
    s.add_argument("--effort"); s.add_argument("--reversibility"); s.set_defaults(func=cmd_complete)

    s = sub.add_parser("approvals"); s.add_argument("--limit", type=int, default=5)
    s.set_defaults(func=cmd_approvals)

    s = sub.add_parser("decide"); s.add_argument("id")
    g = s.add_mutually_exclusive_group(required=True)
    g.add_argument("--approve", action="store_true"); g.add_argument("--decline", action="store_true")
    s.add_argument("--note"); s.set_defaults(func=cmd_decide)

    s = sub.add_parser("skip"); s.add_argument("id"); s.add_argument("--reason", required=True)
    s.set_defaults(func=cmd_skip)

    s = sub.add_parser("result"); s.add_argument("id"); s.add_argument("--state", required=True)
    s.add_argument("--note", required=True); s.add_argument("--artifact")
    s.set_defaults(func=cmd_result)

    s = sub.add_parser("status"); s.set_defaults(func=cmd_status)

    a = ap.parse_args()
    return a.func(a)


if __name__ == "__main__":
    sys.exit(main())
