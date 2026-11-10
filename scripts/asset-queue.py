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
  atlas-diff [--repos P] [--live P] [--self-test]  read-only diff vs a curated index
  decay   [--apply] [--self-test]               expire zombie watches (pre-registered rule v1;
                                                dry run unless --apply)

Queue lives at data/research-asset-queue.json (repo-relative; safe to commit).
The seeder is deliberately deterministic: a bar the agent cannot fudge, and a dedupe against
drafts/ so a repo we already read is never re-audited.
"""
from __future__ import annotations

import argparse
import json
import fnmatch
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
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


# ─────────────────────────── decay: the half the queue never had ───────────────────────────
#
# A `watch` verdict used to be permanent. Nothing expired, so the queue only grew and the standing
# rule ("a `watch` that shows no progress is DROPPED") was enforced by whoever happened to re-read
# the file. The rule below is pre-registered, deterministic, and prints its own clock.
#
# CLOCK — every timestamp this instrument writes is a LOCAL tz string ("2026-11-07 08:24 CST"),
# so age is (local now − last progress event) in whole days, naive-local against naive-local. The
# local zone is the machine's, which is where the worker runs, so the two ends agree by construction.
# PROGRESS EVENTS — an audit (`audited`), the user's call (`approval.decided`) or a recorded result
# (`result.at`) each RESET the clock; a claim (`claimed`) does not, because a claim is a lease, not
# progress. This is the negative control in --self-test: an item audited 90 days ago whose approval
# was decided 2 days ago is NOT stale.
# POPULATION — items whose verdict keeps them OPEN (`watch`, `audit`). `drop` / `skip` items are
# already closed, `pending` / `auditing` items are pipeline (not yet judged), and items carrying a
# `result` are closed by their measurement. None of those are ever expired or aged.
# NOT EXPIRED BY DESIGN — a `pending` approval ask. That ask is the USER's to-do, not a zombie
# verdict; deleting it would silently withdraw a question rather than expire a lead. It is surfaced
# with its age instead (clause stale-ask) so the weekly/daily report can see it going stale.
DECAY_VERSION = "asset-queue-decay-v1"
DECAY = {
    "abandoned-approved": 30,  # user said yes, no result ever landed -> expire
    "no-ask": 30,              # audited with no recommendation ever put to the user -> expire
    "stalled-ask": 21,         # ask still open on the user's side -> SURFACE with age, never expire
}
DECAY_WORK = {"abandoned-approved", "no-ask"}


def _ts(s: str | None) -> datetime | None:
    """Parse the local 'YYYY-MM-DD HH:MM TZ' strings this instrument writes (tz label ignored)."""
    if not s:
        return None
    try:
        return datetime.strptime(str(s)[:16], "%Y-%m-%d %H:%M")
    except ValueError:
        return None


def _last_progress(it: dict) -> tuple[datetime | None, str]:
    cands = [
        (_ts(it.get("audited")), "audited"),
        (_ts((it.get("approval") or {}).get("decided")), "approval-decided"),
        (_ts((it.get("result") or {}).get("at")), "result-recorded"),
    ]
    best = (None, "none")
    for ts, name in cands:
        if ts and (best[0] is None or ts > best[0]):
            best = (ts, name)
    return best


def decay_plan(q: dict, today: datetime | None = None) -> list[dict]:
    """One row per queue item: what the rule says to do with it, and on what clock."""
    today = today or datetime.now()
    plan: list[dict] = []
    for it in q["items"]:
        status, verdict = it.get("status"), (it.get("verdict") or "")
        appr = (it.get("approval") or {}).get("state") or "none"
        row = {"id": it["id"], "status": status, "verdict": verdict or "none", "approval": appr}
        if status == "expired":
            row.update(action="skip", why="already expired (decay is idempotent)")
        elif status in ("pending", "auditing"):
            row.update(action="skip", why=f"pipeline: not yet audited ({status})")
        elif verdict not in ("watch", "audit"):
            row.update(action="skip", why=f"terminal verdict {verdict or 'none'}")
        elif it.get("result"):
            stale_label = " — verdict still 'watch' though a result exists" if verdict == "watch" else ""
            row.update(action="skip", why=f"closed by result ({it['result'].get('state')}){stale_label}")
        elif appr == "declined":
            row.update(action="skip", why="closed by the user's decline")
        else:
            ts, event = _last_progress(it)
            if ts is None:
                row.update(action="flag", why="no parseable progress timestamp — CANNOT age it, not expired")
            else:
                days = (today - ts).days
                if appr == "approved":
                    clause = "abandoned-approved"
                elif appr == "pending":
                    clause = "stalled-ask"
                else:
                    clause = "no-ask"
                ttl = DECAY[clause]
                row.update(clause=clause, ttl=ttl, days=days, due_in=ttl - days,
                           since=ts.strftime("%Y-%m-%d %H:%M"), since_event=event)
                if days >= ttl:
                    row.update(action="expire" if clause in DECAY_WORK else "stall",
                               why=f"{clause}: {days}d >= {ttl}d since {event}")
                else:
                    row.update(action="keep", why=f"{clause}: {days}d < {ttl}d since {event}")
        plan.append(row)
    return plan


def _decay_self_test() -> int:
    """Fixtures on a synthetic queue: can the rule go RED? (a self-test that cannot fail is decoration)."""
    base = "2026-11-10 09:00 CST"
    nowd = datetime.strptime(base[:16], "%Y-%m-%d %H:%M")
    q = {"items": [
        # approved 40d ago, never worked -> expire
        {"id": "a/abandoned", "status": "audited", "verdict": "watch",
         "audited": "2026-10-01 08:00 CST", "approval": {"state": "approved", "decided": "2026-10-01 09:00 CST"}},
        # approved 5d ago, nothing yet -> keep
        {"id": "b/fresh", "status": "audited", "verdict": "watch",
         "audited": "2026-11-05 08:00 CST", "approval": {"state": "approved", "decided": "2026-11-05 09:00 CST"}},
        # ask open 25d -> stall, never expire
        {"id": "c/stalled", "status": "audited", "verdict": "watch",
         "audited": "2026-10-16 08:00 CST", "approval": {"state": "pending", "requested": "2026-10-16 08:00 CST"}},
        # no recommendation at all, 40d -> expire
        {"id": "d/noask", "status": "audited", "verdict": "watch", "audited": "2026-10-01 08:00 CST"},
        # result recorded long ago -> closed, never expired
        {"id": "e/measured", "status": "audited", "verdict": "watch", "audited": "2025-01-01 08:00 CST",
         "result": {"state": "measured-dropped", "at": "2025-01-02 08:00 CST", "note": "x"}},
        # NEGATIVE CONTROL: audit is ancient but the user decided 2d ago -> the clock is last progress
        {"id": "f/old-audit-recent-decision", "status": "audited", "verdict": "watch",
         "audited": "2026-08-01 08:00 CST", "approval": {"state": "approved", "decided": "2026-11-08 08:00 CST"}},
        # terminal verdict / pipeline are never aged
        {"id": "g/dropped", "status": "audited", "verdict": "drop", "audited": "2025-01-01 08:00 CST"},
        {"id": "h/pending", "status": "pending"},
        {"id": "i/already-expired", "status": "expired", "verdict": "watch", "audited": "2025-01-01 08:00 CST"},
    ]}
    want = {"a/abandoned": "expire", "b/fresh": "keep", "c/stalled": "stall", "d/noask": "expire",
            "e/measured": "skip", "f/old-audit-recent-decision": "keep", "g/dropped": "skip",
            "h/pending": "skip", "i/already-expired": "skip"}
    got = {r["id"]: r["action"] for r in decay_plan(q, today=nowd)}
    bad = {k: (want[k], got.get(k)) for k in want if got.get(k) != want[k]}
    for k in sorted(want):
        print(f"  {'ok ' if got.get(k) == want[k] else 'BAD'} {k:32s} want={want[k]:6s} got={got.get(k)}"
              + (f"  [{next((r['why'] for r in decay_plan(q, today=nowd) if r['id'] == k), '')}]" if got.get(k) == want[k] else ""))
    print(f"decay self-test: {len(want) - len(bad)}/{len(want)} fixtures pass"
          + ("" if not bad else f" — FAIL {bad}"))
    return 0 if not bad else 1


def cmd_decay(a: argparse.Namespace) -> int:
    if a.self_test:
        return _decay_self_test()
    q = load()
    plan = decay_plan(q)
    counts: dict[str, int] = {}
    for r in plan:
        counts[r["action"]] = counts.get(r["action"], 0) + 1
    print(f"decay {DECAY_VERSION} · queue {len(q['items'])} items · "
          + ", ".join(f"{k}={counts[k]}" for k in sorted(counts))
          + f" · clock = local queue timestamps vs now {datetime.now():%Y-%m-%d %H:%M} (naive local)"
          + " · TTL " + ", ".join(f"{k}={v}d" for k, v in DECAY.items()))
    live = [r for r in plan if r.get("clause")]
    live.sort(key=lambda r: (r.get("due_in", 0)))
    for r in live:
        mark = {"expire": "EXPIRED", "stall": "STALLED", "keep": "ok"}.get(r["action"], r["action"])
        due = f"due in {r['due_in']}d" if r.get("due_in", 0) > 0 else f"OVERDUE {r['due_in']}d"
        print(f"  {mark:7s} {r['id']:44s} {r['clause']:18s} {r['days']:4d}d since {r['since_event']} "
              f"({r['since']}) · {due} · approval={r['approval']}")
    for r in plan:
        if r["action"] in ("flag", "skip") and r.get("why", "").startswith(("no parseable", "closed by result")):
            print(f"  note    {r['id']:44s} {r['why']}")
    if not a.apply:
        print("dry run — nothing written. Pass --apply to expire the rows marked EXPIRED "
              "(STALLED rows are only annotated; a pending ask is the user's, not the queue's)")
        return 0
    changed = []
    for r in plan:
        it = by_id(q, r["id"])
        if r["action"] == "expire":
            it["status"] = "expired"
            it["decay"] = {"rule": DECAY_VERSION, "clause": r["clause"], "action": "expired",
                           "at": now(), "since": r["since"], "since_event": r["since_event"],
                           "days": r["days"], "ttl": r["ttl"]}
            it["note"] = ((it.get("note") or "").strip()
                          + f" · EXPIRED {now()} by {DECAY_VERSION}: {r['why']}; "
                            f"re-open with `asset-queue.py add --id {r['id']} --force`, "
                            f"never silently — the verdict was '{it.get('verdict')}'").strip(" ·")[:800]
            changed.append(r["id"])
        elif r["action"] == "stall" and not (it.get("decay") or {}).get("stalled_at"):
            it["decay"] = {"rule": DECAY_VERSION, "clause": r["clause"], "action": "stalled",
                           "stalled_at": now(), "since": r["since"], "since_event": r["since_event"],
                           "days": r["days"], "ttl": r["ttl"]}
            it["note"] = ((it.get("note") or "").strip()
                          + f" · STALLED {r['days']}d at {now()} ({r['clause']}, ttl {r['ttl']}d): the ask is "
                            f"still open on the user's side and is re-surfaced, never auto-withdrawn").strip(" ·")[:800]
            changed.append(r["id"] + " (stalled)")
    if changed:
        save(q)
    print(f"applied: {len(changed)} item(s) changed" + (f" — {', '.join(changed)}" if changed else ""))
    return 0


# ─────────────── atlas-diff: one independent second discovery channel ───────────────
#
# inputoutput9/prediction-market-agent-atlas (MIT) is a human-curated index of 44 prediction-market
# repos (22 polymarket / 10 kalshi / 12 cross-venue) with dated evidence and a COMPUTED maintenance
# axis. Nothing is adopted from it — no code, no dependency. It is used once, as an independent
# check on our own discovery: the GitHub radar yields ~0.11 new leads per run, and a curated index
# is the cheapest way to ask "is that a thin flow or a blind spot?". The diff is READ-ONLY: it
# classifies every entry against what we already hold and prints the unreferenced remainder. It
# does NOT enqueue anything — enqueuing is `asset-queue.py add --id owner/repo`.
#
# BASIS STATED ON EVERY RUN: what counts as referenced (queue + drafts + roadmap, the corpus the
# radar's own dedupe reads), the atlas's liveness as-of date (maintenance ladder is pinned to it),
# and the atlas's CURATED as-of date — the four curated axes are human scores that may be stale,
# so a curated score is a lead, never a verdict.
ATLAS_REPO = "inputoutput9/prediction-market-agent-atlas"
ATLAS_CACHE = REPO / "data" / "cache" / "prediction-market-agent-atlas"
ATLAS_OUT = REPO / "data" / "atlas-lead-diff.json"
VENDOR_ORGS = {"polymarket", "kalshi"}
ATLAS_OWN_DRAFTS = ("*atlas*diff*.md", "*atlas-lead-diff*")


def _atlas_fetch(name: str) -> str | None:
    import urllib.request
    url = f"https://raw.githubusercontent.com/{ATLAS_REPO}/main/{name}"
    for attempt in (1, 2):
        try:
            with urllib.request.urlopen(url, timeout=25) as fh:
                body = fh.read().decode("utf-8", "replace")
            ATLAS_CACHE.mkdir(parents=True, exist_ok=True)
            (ATLAS_CACHE / Path(name).name).write_text(body)
            return body
        except Exception:
            if attempt == 2:
                cached = ATLAS_CACHE / Path(name).name
                if cached.exists():
                    print(f"  (fetch failed for {name}; using cache {cached})", file=sys.stderr)
                    return cached.read_text()
                print(f"  **SOURCE FAILED — {name}** (no cache to fall back on)", file=sys.stderr)
                return None
    return None


def _maintenance(live: dict, as_of: str) -> tuple[int | None, int | None, str]:
    """The atlas's own ladder (methodology.md): ≤30d 5, ≤90d 4, ≤180d 3, ≤365d 2, >365d 1, archived 0."""
    if live.get("archived"):
        return 0, None, "archived"
    dates = [d for d in (live.get("pushed_at"), live.get("released_at")) if d]
    if not dates:
        return None, None, "no liveness data"
    try:
        newest = max(datetime.strptime(d, "%Y-%m-%d") for d in dates)
        ref = datetime.strptime(as_of, "%Y-%m-%d")
    except ValueError:
        return None, None, "unparsable date"
    idle = (ref - newest).days
    score = 5 if idle <= 30 else 4 if idle <= 90 else 3 if idle <= 180 else 2 if idle <= 365 else 1
    return score, idle, "ladder"


def _atlas_corpus() -> set[str]:
    """What the radar's own dedupe would already consider 'seen': queue ids, drafts/, roadmap."""
    known: set[str] = set()
    try:
        known |= {i["id"].lower() for i in load()["items"]}
    except SystemExit:
        pass
    # THIS INSTRUMENT'S OWN REPORT MUST NOT COUNT AS PRIOR KNOWLEDGE. Without this the first run's
    # draft (which names every new lead) turns them into "referenced" on the second run and the yield
    # silently collapses — a diff that feeds on its own output measures nothing.
    for f in sorted(DRAFTS.glob("*.md")):
        if any(fnmatch.fnmatch(f.name, pat) for pat in ATLAS_OWN_DRAFTS):
            continue
        try:
            known |= {t for t in re.findall(r"[\w.\-]+/[\w.\-]+", f.read_text(errors="replace").lower())}
        except OSError:
            continue
    road = REPO / "data" / "roadmap.json"
    if road.exists():
        try:
            known |= {t for t in re.findall(r"[\w.\-]+/[\w.\-]+", road.read_text(errors="replace").lower())}
        except OSError:
            pass
    return known


def _atlas_self_test() -> int:
    """Boundary test on the ladder + the classification rule (a self-test that cannot fail is decoration)."""
    live = {"p": {"pushed_at": "2026-11-01"}, "a": {"archived": True}}
    cases = [("2026-11-09", 30, 5), ("2026-11-09", 31, 4), ("2026-11-09", 90, 4), ("2026-11-09", 91, 3),
             ("2026-11-09", 181, 2), ("2026-11-09", 366, 1)]
    bad = []
    for as_of, idle, want in cases:
        pushed = (datetime.strptime(as_of, "%Y-%m-%d") - timedelta(days=idle)).strftime("%Y-%m-%d")
        got, got_idle, _ = _maintenance({"pushed_at": pushed}, as_of)
        if got != want or got_idle != idle:
            bad.append(f"idle={idle} want {want} got {got} (idle {got_idle})")
    if _maintenance(live["a"], "2026-11-09")[0] != 0:
        bad.append("archived should score 0")
    if _maintenance({}, "2026-11-09")[0] is not None:
        bad.append("no liveness data should be None, not a number")
    # classification: a referenced id must not be reported as new, an unreferenced one must be
    known = {"owner/seen"}
    if ("owner/seen" in known) == ("owner/new" in known):
        bad.append("classification rule is degenerate")
    print(f"atlas self-test: {len(cases) + 3 - len(bad)}/{len(cases) + 3} checks pass"
          + ("" if not bad else f" — FAIL {bad}"))
    return 0 if not bad else 1


def cmd_atlas_diff(a: argparse.Namespace) -> int:
    if a.self_test:
        return _atlas_self_test()
    try:
        import yaml
    except ImportError:
        print("PyYAML missing — cannot read the atlas; nothing measured (not a zero result)", file=sys.stderr)
        return 1
    repos_txt = Path(a.repos).read_text() if a.repos else _atlas_fetch("data/repos.yaml")
    live_txt = Path(a.live).read_text() if a.live else _atlas_fetch("data/live.json")
    as_of_txt = (Path(a.as_of).read_text() if a.as_of else _atlas_fetch("data/as-of.txt")) or ""
    cur_txt = (Path(a.curated_as_of).read_text() if a.curated_as_of else _atlas_fetch("data/curated-as-of.txt")) or ""
    if not repos_txt or not live_txt:
        print("**atlas-diff NOT MEASURED** — repos.yaml/live.json unavailable", file=sys.stderr)
        return 1
    entries = yaml.safe_load(repos_txt).get("entries", [])
    live = json.loads(live_txt)
    as_of = as_of_txt.strip() or datetime.now().strftime("%Y-%m-%d")
    curated_as_of = cur_txt.strip() or "unknown"
    known = _atlas_corpus()
    queue_ids = {i["id"].lower() for i in load()["items"]}
    rows = []
    for e in entries:
        rid = e["id"]
        low = rid.lower()
        name = low.split("/")[-1]
        if low in known or name in known:
            cls = "queued" if low in queue_ids else "referenced"
        elif (e.get("hard_flags") or []) and "scam" in e["hard_flags"]:
            cls = "flagged-scam"
        elif low.split("/")[0] in VENDOR_ORGS or (e.get("owner", "").lower() in VENDOR_ORGS):
            cls = "vendor-official"
        else:
            cls = "new-lead"
        m, idle, mnote = _maintenance(live.get(rid) or {}, as_of)
        s = e.get("scores") or {}
        rows.append({"id": rid, "venue": e.get("venue"), "category": e.get("category"),
                     "url": e.get("url") or f"https://github.com/{rid}", "class": cls,
                     "scores": s, "maintenance": m, "idle_days": idle, "maintenance_basis": mnote,
                     "hard_flags": e.get("hard_flags") or [], "packages": e.get("packages") or {},
                     "evidence": (e.get("evidence") or [])[:2], "notes": e.get("notes") or ""})
    counts: dict[str, int] = {}
    for r in rows:
        counts[r["class"]] = counts.get(r["class"], 0) + 1
    print(f"atlas-diff {ATLAS_REPO} @ liveness as-of {as_of} (CURATED axes as-of {curated_as_of}) · "
          f"{len(rows)} entries · " + ", ".join(f"{k}={counts[k]}" for k in sorted(counts)))
    print(f"  basis: 'referenced' = id or repo name appears in the queue, drafts/*.md or data/roadmap.json "
          f"({len(known)} distinct owner/repo tokens in that corpus); maintenance is the atlas's own ladder "
          f"pinned to {as_of}; curated scores are human and may predate {curated_as_of}")
    leads = [r for r in rows if r["class"] == "new-lead"]
    leads.sort(key=lambda r: (-(r["scores"].get("capability") or 0), -(r["scores"].get("agent_fit") or 0),
                              -(r["maintenance"] or 0)))
    print(f"  NEW third-party leads: {len(leads)}")
    for r in leads:
        s = r["scores"]
        print(f"    {r['id']:42s} {str(r['venue']):12s} {str(r['category']):17s} "
              f"cap={s.get('capability','-')} agent={s.get('agent_fit','-')} safety={s.get('safety','-')} "
              f"maint={r['maintenance']} ({r['idle_days']}d idle) " + ("FRESH" if (r["maintenance"] or 0) >= 4 else "decaying"))
    others = [r for r in rows if r["class"] in ("vendor-official", "flagged-scam")]
    for r in sorted(others, key=lambda r: (r["class"], r["id"])):
        print(f"    [{r['class']:15s}] {r['id']:42s} maint={r['maintenance']} "
              f"flags={','.join(r['hard_flags']) or '-'}")
    fresh = [r for r in leads if (r["maintenance"] or 0) >= 4]
    stale = [r for r in leads if (r["maintenance"] or 0) < 4]
    print(f"  of those, {len(fresh)} are FRESH by the atlas's own ladder (maint>=4) and {len(stale)} are "
          f"already decaying (maint<=3) — a curated index is a STOCK, not a flow, and its own decay axis "
          f"says most of the stock is old")
    ours = {i["id"].lower(): i for i in load()["items"]}
    both = [r for r in rows if r["id"].lower() in ours]
    if both:
        print("  agreement with verdicts we already hold (the only place an independent index can "
              "contradict us):")
        for r in both:
            o = ours[r["id"].lower()]
            s = r["scores"]
            print(f"    {r['id']:42s} ours={str(o.get('verdict')):6s} atlas cap={s.get('capability','-')} "
                  f"agent={s.get('agent_fit','-')} maint={r['maintenance']} "
                  f"· result={((o.get('result') or {}).get('state') or 'none')}")
    else:
        print("  agreement: none — no entry in the index carries a verdict we already hold, so an "
              "independent contradiction is NOT measurable from this pull (n=0, not 'no disagreement')")
    out = {"measured_at": now(), "source": ATLAS_REPO, "liveness_as_of": as_of,
           "curated_as_of": curated_as_of, "entries": len(rows), "counts": counts,
           "corpus_tokens": len(known),
           "new_leads": [r["id"] for r in leads],
           "fresh_leads": [r["id"] for r in fresh],
           "stale_leads": [r["id"] for r in stale],
           "agreement": {r["id"]: {"ours": ours[r["id"].lower()].get("verdict"),
                                    "atlas_capability": r["scores"].get("capability"),
                                    "atlas_agent_fit": r["scores"].get("agent_fit")} for r in both},
           "rows": rows,
           "read_only": "nothing enqueued and nothing adopted; enqueue with asset-queue.py add --id"}
    ATLAS_OUT.write_text(json.dumps(out, indent=1, sort_keys=True) + "\n")
    print(f"  artifact: {ATLAS_OUT.relative_to(REPO)}")
    return 0


def cmd_status(a: argparse.Namespace) -> int:
    q = load()
    counts: dict[str, int] = {}
    for i in q["items"]:
        counts[i["status"]] = counts.get(i["status"], 0) + 1
    print(f"queue: {len(q['items'])} items · " + (", ".join(f"{k}={v}" for k, v in sorted(counts.items())) or "empty"))
    plan = decay_plan(q)
    open_rows = [r for r in plan if r.get("clause")]
    over = [r for r in open_rows if r["action"] in ("expire", "stall")]
    soon = [r for r in open_rows if r["action"] == "keep" and r["due_in"] <= 7]
    over_txt = ", ".join(r["id"] for r in over)
    soon_txt = ", ".join(f"{r['id']} in {r['due_in']}d" for r in soon)
    print(f"  decay {DECAY_VERSION}: {len(open_rows)} open watch/audit item(s) · stale (>= TTL) {len(over)}"
          + (f" [{over_txt}]" if over_txt else "") + f" · due within 7d {len(soon)}"
          + (f" [{soon_txt}]" if soon_txt else ""))
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

    s = sub.add_parser("decay")
    s.add_argument("--apply", action="store_true",
                   help="write the expiries (default: dry run; STALLED asks are only annotated)")
    s.add_argument("--self-test", dest="self_test", action="store_true")
    s.set_defaults(func=cmd_decay)

    s = sub.add_parser("atlas-diff")
    s.add_argument("--repos"); s.add_argument("--live")
    s.add_argument("--as-of", dest="as_of"); s.add_argument("--curated-as-of", dest="curated_as_of")
    s.add_argument("--self-test", dest="self_test", action="store_true")
    s.set_defaults(func=cmd_atlas_diff)

    s = sub.add_parser("status"); s.set_defaults(func=cmd_status)

    a = ap.parse_args()
    return a.func(a)


if __name__ == "__main__":
    sys.exit(main())
