#!/usr/bin/env python3
"""
Pull work from data/roadmap.json onto the kanban board so the dispatcher has something to spawn.

WHY THIS EXISTS: the kanban dispatcher and the roadmap were two disconnected systems. Nothing in the
repo or in ~/.hermes/scripts ever called `kanban create`, so the board only ever held cards a human
had seeded by hand. Three parallel worker lanes were stood up and drained in ~30 minutes, then sat
idle while 87 open roadmap cards waited behind a single cron agent that does ONE item per run, twice
a day (~44 days to touch each card once). The parallelism was capacity with no feed. This is the feed.

THE SAFETY MODEL — a whitelist, never a blacklist. Classification is by roadmap tags:
  lane-a            -> Lane A: rules/sizing/strategy. WORKED but never APPLIED (see contract below).
  measurement       -> Lane B: instrument/measurement only. Safe to run unattended.
  awaiting-approval -> already with the operator. Skip.
  anything else     -> UNCLASSIFIED. NOT promoted. 47 of the 87 open cards are here and most of them
                       change what the bot decides, so guessing "probably fine" is exactly the
                       mistake this file exists to avoid. Tag the card first.

LANE A SEQUENCING (operator's instruction, 2026-10-29): Lane A cards are only fed once the Lane B
queue is drained — "work through lane-a cards and spawn approvals when they are finished working
lane-b". A Lane A worker produces a PROPOSAL and adds `awaiting-approval` to the roadmap card, which
is the tag the approval gate (scripts/cron-gates/approval-queue-signature.py) keys on. Merging to
main is the apply step and no worker is authorised to do it.

THE RESIDUAL RISK, STATED PLAINLY: a git worktree isolates the CODE, not the DATABASE. prisma/dev.db
is shared with the live lane, so a misbehaving Lane A worker could run scripts/apply-vNN.ts and
mutate the live RuleSet. The contract in the card body forbids it and the worker is instructed to
stop at product decisions, but this is instruction-enforced, not sandbox-enforced. Telemetry that
would sandbox it does not exist in this repo today.

Usage:
  python3 scripts/backlog-feeder.py --dry-run
  python3 scripts/backlog-feeder.py --max-promote 3 --max-active 3
  python3 scripts/backlog-feeder.py --lane-a --dry-run      # would it feed Lane A right now?
"""
import argparse
import json
import os
import sqlite3
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROADMAP = os.path.join(ROOT, "data", "roadmap.json")
BOARD_DB = os.path.expanduser("~/.hermes/kanban/boards/medusa/kanban.db")
OPEN_COLUMNS = ("Backlog", "Scheduled", "In Review")
# Statuses that mean "a worker is on it or about to be". `blocked` is excluded on purpose: a blocked
# card is waiting on the operator, so counting it would jam the feeder forever.
ACTIVE_STATUSES = ("todo", "ready", "running")


def load_roadmap():
    with open(ROADMAP, encoding="utf-8") as fh:
        data = json.load(fh)
    return data if isinstance(data, list) else data.get("cards", data.get("items", []))


def board_tasks():
    """Read the kanban board. Retried once: WAL can refuse a read while the dispatcher holds the shm.

    Selects `body`/`created_by` and an `open_parents` count because a card created by a WORKER as a
    child of its own card carries no roadmap idempotency key -- the roadmap loop below cannot see it,
    so without this it would sit blocked forever with nobody to promote it. That is the exact shape of
    t_d9736b86 (created by its parent, parent finished, fully specced, never promoted).
    """
    sql = """
        SELECT t.id, t.title, t.status, t.idempotency_key, t.created_by, t.body,
               (SELECT COUNT(*) FROM task_links l JOIN tasks p ON p.id = l.parent_id
                 WHERE l.child_id = t.id AND p.status NOT IN ('done')) AS open_parents
        FROM tasks t
    """
    last = None
    for attempt in range(2):
        for mode in (["-readonly"], []):
            try:
                out = subprocess.run(
                    ["sqlite3", *mode, BOARD_DB, "-json", sql],
                    capture_output=True, text=True, timeout=15,
                )
            except Exception as exc:  # noqa: BLE001
                last = str(exc)
                continue
            if out.returncode == 0:
                t = out.stdout.strip()
                return json.loads(t) if t else []
            last = (out.stderr or "").strip()
        if attempt == 0:
            import time
            time.sleep(0.15)
    # A failed read must NOT look like an empty board -- that would re-promote every card at once.
    print("BOARD-READ-FAILED: %s" % last, file=sys.stderr)
    sys.exit(2)


def stranded_lane_b(tasks):
    """Blocked cards a WORKER created that are safe to run, but which nothing will ever promote.

    Conditions are deliberately narrow. The body must carry the Lane B banner the feeder itself writes
    (and NOT the Lane A one, and not an awaiting-approval instruction); the creator must not be the
    operator or the feeder; and every parent must be `done`, so a child never starts before the work
    it depends on has finished. Lane A card bodies fail the marker test, so those still wait for the
    operator -- which is the whole point.
    """
    out = []
    for t in tasks:
        if t.get("status") != "blocked":
            continue
        if t.get("idempotency_key"):
            continue  # roadmap-fed; the roadmap loop owns it
        if t.get("open_parents"):
            continue
        body = t.get("body") or ""
        if "LANE B" not in body:
            continue
        if "LANE A" in body or "awaiting-approval" in body:
            continue
        if (t.get("created_by") or "") in ("user", "backlog-feeder"):
            continue
        out.append(t)
    return out


def tags_of(card):
    return [str(t) for t in (card.get("tags") or [])]


def classify(card):
    tags = tags_of(card)
    if "lane-a" in tags:
        return "a"
    if "measurement" in tags:
        # A `measurement` tag is NOT sufficient on its own: several cards carry it while their title
        # or note asks for a DECISION (e.g. "kalshi-lane-ontology-not-coverage ... park or fund
        # semantics (decision)", "exit-exemption-20-40-decision"). A worker can measure those but
        # cannot choose, so promoting them unattended just burns a lane and produces a comment. Park
        # them for the operator instead.
        blob = ("%s %s" % (card.get("title") or "", card.get("note") or "")).lower()
        # Match decision-SEEKING language, not any occurrence of the word "decision". The old substring
        # test also fired on "decision rule" and "DECISION RULE:" -- which is exactly how this repo writes
        # every pre-registered card. The effect was that any properly-written Lane B instrument got parked
        # as an operator decision and never dispatched: the tag said lane-b, the classifier said decision,
        # and the card sat there. Measured 2026-10-29 on ml-feed-recorder-audit-external-pm.
        DECISION_SEEKING = (
            "decision needed", "decision required", "needs a call from", "needs your call",
            "awaiting decision", "park or fund", "(decision)", "decide whether", "decide if",
            "choose between", "your call on", "operator must choose",
        )
        if any(k in blob for k in DECISION_SEEKING):
            return "decision"
        return "b"
    if "awaiting-approval" in tags:
        return "awaiting"
    return "unclassified"


def body_for(card, lane):
    note = (card.get("note") or "").strip()
    eff = card.get("effort")
    head = (
        "FEEDER-CREATED from data/roadmap.json\n"
        "  roadmap id : %s\n"
        "  column     : %s\n"
        "  effort     : %s\n"
        "  tags       : %s\n"
        "  lane       : %s\n\n"
        "WHY (from the roadmap card):\n%s\n\n"
        % (card.get("id"), card.get("column"), eff or "unspecified",
           ", ".join(tags_of(card)) or "(none)", lane.upper(), note or "(no note recorded)")
    )
    common = (
        "\nREPO: /Users/xsnyde2/polymarket-copybot. Other sessions edit this repo concurrently -- re-read a\n"
        "file immediately before patching it. You are in your own git worktree; leave work UNCOMMITTED\n"
        "and DO NOT merge to main. Merging is the operator's step, not yours.\n\n"
        "VERIFY before you report: run the checks that apply (npx tsc --noEmit, npx vitest run for TS;\n"
        "python3 -m py_compile for Python) and paste REAL command output. A figure you did not measure\n"
        "does not go in the summary. If a command fails, say it failed rather than reporting a zero.\n"
    )
    if lane == "a":
        return head + (
            "*** LANE A -- WORK IT, DO NOT APPLY IT. ***\n"
            "This card can change what the bot decides or how much it risks. Your job is to produce the\n"
            "PROPOSAL, with its measurement, so the operator can decide. Explicitly FORBIDDEN:\n"
            "  - running any scripts/apply-v*.ts or applying a RuleSet change of any kind;\n"
            "  - any write to prisma/dev.db (the worktree isolates CODE, not the DATABASE -- it is shared\n"
            "    with the live lane, so a write there is a live change);\n"
            "  - changing a rule, size, gate, booking or threshold;\n"
            "  - merging to main.\n"
            "INSTEAD: write the proposal to drafts/<slug>-<date>.md with the decision rule, the measured\n"
            "basis, and what result would REFUTE it. A proposal with no refutation condition is not one.\n\n"
            "ON SUCCESS you MUST add the tag `awaiting-approval` to roadmap card `%s` in data/roadmap.json\n"
            "so it surfaces in the operator's approval queue. That tag is the whole delivery mechanism --\n"
            "an un-tagged proposal is invisible.\n" % card.get("id")
        ) + common
    return head + (
        "*** LANE B -- MEASUREMENT / INSTRUMENT ONLY. ***\n"
        "Do NOT change any rule, size, gate, booking, threshold, or anything that affects what the bot\n"
        "decides or how much it risks. If the work appears to need one, STOP and post a comment on the\n"
        "card explaining what needs deciding -- do not decide it yourself.\n"
        "No write to prisma/dev.db beyond read-only SELECTs.\n"
    ) + common


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--max-promote", type=int, default=3, help="cards to promote this run")
    ap.add_argument("--max-active", type=int, default=3, help="stop feeding at this many todo/ready/running")
    ap.add_argument("--max-runtime", default="45m")
    ap.add_argument("--assignee", default="default")
    ap.add_argument("--lane-a", action="store_true", help="allow Lane A feeding when Lane B is drained")
    ap.add_argument("--quiet", action="store_true",
                    help="print NOTHING unless something was promoted or something failed. Required for "
                         "the no_agent cron form, where stdout is delivered verbatim: without it the "
                         "operator gets a 12-line status report every tick.")
    args = ap.parse_args()

    # The stat block and the at-cap/drained notices are routine; under --quiet they are suppressed
    # entirely so an empty stdout means "nothing happened", which is what the scheduler keys on.
    def say(msg=""):
        if not args.quiet:
            print(msg)

    def report(msg):
        print(msg)

    cards = load_roadmap()
    tasks = board_tasks()

    on_board = set()
    for t in tasks:
        key = t.get("idempotency_key") or ""
        if key.startswith("roadmap:"):
            on_board.add(key.split(":", 1)[1])

    active = [t for t in tasks if t.get("status") in ACTIVE_STATUSES]
    open_cards = [c for c in cards if c.get("column") in OPEN_COLUMNS and c.get("id") not in on_board]

    bucket = {"a": [], "b": [], "decision": [], "unclassified": [], "awaiting": []}
    for c in open_cards:
        bucket[classify(c)].append(c)

    say("roadmap open (not Done/In Progress, not already on board): %d" % len(open_cards))
    say("  lane b (measurement) : %d" % len(bucket["b"]))
    say("  lane a               : %d" % len(bucket["a"]))
    say("  decision cards       : %d (parked -- a worker cannot choose)" % len(bucket["decision"]))
    say("  awaiting approval    : %d (skipped)" % len(bucket["awaiting"]))
    say("  unclassified         : %d (NOT promoted -- tag them first)" % len(bucket["unclassified"]))
    say("board: %d active (todo/ready/running), cap %d" % (len(active), args.max_active))

    if len(active) >= args.max_active:
        say("AT CAP -- promoting nothing this run.")
        return 0

    room = min(args.max_promote, args.max_active - len(active))

    # 0. Stranded worker-created Lane B children FIRST. These are continuations of work that was
    #    already approved and already started by a parent card, and no other code path will ever
    #    promote them: they carry no roadmap key, so the roadmap loop cannot see them. Ordering them
    #    ahead of fresh roadmap cards also keeps a multi-stage measurement from stalling mid-way.
    promoted_stranded = 0
    for t in stranded_lane_b(tasks):
        if promoted_stranded >= room:
            break
        title = (t.get("title") or "")[:100]
        if args.dry_run:
            report("WOULD PROMOTE (stranded) %s %s" % (t["id"], title))
        else:
            p = subprocess.run(
                ["hermes", "kanban", "--board", "medusa", "promote", t["id"]],
                capture_output=True, text=True,
            )
            if p.returncode != 0:
                report("   UNBLOCK FAILED (%s): %s" % (t["id"], (p.stderr or p.stdout).strip()[:200]))
                continue
            report("PROMOTED (stranded) %s -> dispatchable\n   %s" % (t["id"], title))
        promoted_stranded += 1
    room -= promoted_stranded

    # Lane B first, always. Lane A only once no Lane B work is queued or running.
    lane_b_active = [
        t for t in active
        if t.get("idempotency_key", "").startswith("roadmap:")
        and classify({"tags": next((c.get("tags") for c in cards
                                    if c.get("id") == t["idempotency_key"].split(":", 1)[1]), [])}) == "b"
    ]
    lane_b_drained = len(lane_b_active) == 0

    picks = []
    for c in bucket["b"][:room]:
        picks.append((c, "b"))
    if len(picks) < room and lane_b_drained and args.lane_a and not bucket["b"]:
        for c in bucket["a"][: room - len(picks)]:
            picks.append((c, "a"))

    if not picks:
        if not promoted_stranded:
            if not lane_b_drained:
                say("Lane B still active (%d) -- Lane A not fed yet, by design." % len(lane_b_active))
            elif bucket["b"]:
                say("nothing to promote (room=0)")
            elif not args.lane_a:
                say("Lane B drained and no Lane A feeding requested (--lane-a to allow).")
            else:
                say("nothing to promote")
        return 0

    say()
    for card, lane in picks:
        cid = card.get("id")
        title = (card.get("title") or cid)[:120]
        report("%s PROMOTE %-42s [lane %s] %s" % ("WOULD" if args.dry_run else "->", cid, lane, title))
        if args.dry_run:
            continue
        body = body_for(card, lane)
        cmd = [
            "hermes", "kanban", "--board", "medusa", "create", title,
            "--assignee", args.assignee,
            "--workspace", "worktree",
            "--branch", "wt/%s" % cid,
            "--idempotency-key", "roadmap:%s" % cid,
            "--max-runtime", args.max_runtime,
            "--initial-status", "blocked",
            "--created-by", "backlog-feeder",
            "--body-file", "-",
        ]
        r = subprocess.run(cmd, input=body, capture_output=True, text=True)
        if r.returncode != 0:
            report("   CREATE FAILED: %s" % (r.stderr or r.stdout).strip()[:300])
            continue
        out = (r.stdout or "").strip()
        report("   created: %s" % out.splitlines()[-1][:120])
        tid = None
        for tok in out.split():
            if tok.startswith("t_"):
                tid = tok.strip(",():")
                break
        if not tid:
            report("   could not parse task id from: %s" % out[:200])
            continue
        p = subprocess.run(["hermes", "kanban", "--board", "medusa", "promote", tid],
                           capture_output=True, text=True)
        if p.returncode != 0:
            report("   PROMOTE FAILED (%s): %s" % (tid, (p.stderr or p.stdout).strip()[:200]))
        else:
            report("   promoted %s -> dispatchable" % tid)
    return 0


if __name__ == "__main__":
    sys.exit(main())
