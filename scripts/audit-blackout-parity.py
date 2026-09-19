"""Read-only audit: is the hour-blackout log<->journal parity a real break?

Log lines are emitted PER LEG (per bot); journal rows are PER DECISION.
  * 20:00 ET is in the shared blackout set -> both books log a line -> 2 lines/decision.
  * 08:00 ET is C-200-only -> 1 line/decision.
So the correct parity test is lines == legs_per_decision * rows, and the rec-4
verify line (lines == rows) cannot hold for the shared 20:00 set.
"""
import sqlite3, collections, datetime, zoneinfo, sys

tz = zoneinfo.ZoneInfo("America/Chicago")
lines = open("logs/cron/copybot-monitor-score.log", errors="replace").read().splitlines()
lo, hi = "2026-09-18T07:00:36", "2026-09-19T06:52:37"

cur = None
runs = collections.OrderedDict()
for l in lines:
    if l.startswith("=== run "):
        cur = l.replace("=== run ", "").split()[0].strip()
        runs.setdefault(cur, [])
    elif cur is not None:
        runs[cur].append(l)

con = sqlite3.connect("prisma/dev.db")


def ms(s):
    d = datetime.datetime.fromisoformat(s).replace(tzinfo=tz)
    return int(d.timestamp() * 1000)


keys = list(runs)
print(f"{'run':22} {'8L':>4} {'8R':>4} | {'20L':>4} {'20R':>4}  note")
tot = collections.Counter()
for i, k in enumerate(keys):
    if not (lo <= k <= hi):
        continue
    start = ms(k)
    end = ms(keys[i + 1]) if i + 1 < len(keys) else start + 20 * 60000
    L8 = sum(1 for l in runs[k] if "hour blackout 8:00 ET" in l)
    L20 = sum(1 for l in runs[k] if "hour blackout 20:00 ET" in l)
    if not (L8 or L20):
        continue
    R8 = con.execute(
        "SELECT COUNT(*) FROM DecisionJournal WHERE createdAt>=? AND createdAt<? AND risksJson LIKE '%hour blackout 8:00%'",
        (start, end)).fetchone()[0]
    R20 = con.execute(
        "SELECT COUNT(*) FROM DecisionJournal WHERE createdAt>=? AND createdAt<? AND risksJson LIKE '%hour blackout 20:00%'",
        (start, end)).fetchone()[0]
    tot['L8'] += L8; tot['R8'] += R8; tot['L20'] += L20; tot['R20'] += R20
    note = []
    if L8 and L8 != R8:
        note.append("8:00 gap")
    if L20 and L20 != 2 * R20:
        note.append("20:00 gap")
    print(f"{k:22} {L8:>4} {R8:>4} | {L20:>4} {R20:>4}  {' '.join(note)}")

print("TOTAL 8:00 lines/rows:", tot['L8'], tot['R8'],
      "| 20:00 lines/rows:", tot['L20'], tot['R20'],
      "-> 20:00 lines/rows =", round(tot['L20'] / tot['R20'], 3) if tot['R20'] else None)
