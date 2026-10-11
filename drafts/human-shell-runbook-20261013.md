# Human-shell runbook — Tuesday 2026-10-13 (local to the Mac)

Two jobs need the physical machine, because both are `launchctl bootstrap` calls and the supervised Hermes
gateway **hard-blocks** that verb by design:

> `launchctl submit/bootstrap is restricted inside a supervised gateway regardless of the job label... Perform
> authorized LaunchAgent maintenance from a separate shell outside the gateway, not by switching launchctl
> verbs to bypass this rejection.`

So: one sitting at the Mac, in **Terminal.app** (not through me). Carded as `dashboard-launchd-qos`
(Scheduled) with the optional second item riding along on `l2-recorder-supervision`.

---

## Step 0 — preflight (10 s, read-only)

Establishes the before-state so the after-read is comparable. Run it in the same shell.

```
L=gui/$UID
echo "=== dashboard ==="
launchctl print $L/com.xsnyde2.copybot-dashboard | grep -E 'state =|pid =|spawn type'
curl -s -o /dev/null -w '/paper-trades %{time_total}s\n' --max-time 60 http://localhost:3013/paper-trades
curl -s -o /dev/null -w '/signals      %{time_total}s\n' --max-time 60 http://localhost:3013/signals
curl -s -o /dev/null -w '/journal      %{time_total}s\n' --max-time 60 http://localhost:3013/journal
ls -la ~/Library/LaunchAgents/com.xsnyde2.copybot-dashboard.plist.bak-qos-interactive-20261011
```

**State staged for you (verified 2026-10-11 17:4x CDT, before your reload):**

| item | value |
|---|---|
| plist | already carries `<key>ProcessType</key><string>Interactive</string>` (written 07:05 today) |
| launchd's cached definition | still `spawn type = background (5)` — the reload is what makes the plist take effect |
| running process | pid 77221, uptime 11h02m, RSS 137 MB, `state = running`, `last exit code = 0` |
| latency baseline (that aged process) | /paper-trades **0.78 s** · /signals **2.46 s** · /journal **2.26 s** |
| rollback plist | `com.xsnyde2.copybot-dashboard.plist.bak-qos-interactive-20261011` (1247 B, the pre-`ProcessType` version) |

---

## Step 1 — the dashboard QoS reload (~5 s of downtime, KeepAlive brings it straight back)

```
L=gui/$UID
launchctl bootout $L/com.xsnyde2.copybot-dashboard
launchctl bootstrap $L ~/Library/LaunchAgents/com.xsnyde2.copybot-dashboard.plist
launchctl print $L/com.xsnyde2.copybot-dashboard | grep -E 'state =|pid =|spawn type'
```

**Pass condition:** `spawn type = interactive` (not `background (5)`), and the job is back with a **new** pid.

**Rollback** (only if the page misbehaves):

```
launchctl bootout $L/com.xsnyde2.copybot-dashboard
cp ~/Library/LaunchAgents/com.xsnyde2.copybot-dashboard.plist.bak-qos-interactive-20261011 \
   ~/Library/LaunchAgents/com.xsnyde2.copybot-dashboard.plist
launchctl bootstrap $L ~/Library/LaunchAgents/com.xsnyde2.copybot-dashboard.plist
```

**Do not judge the speed change on a fresh process.** A restart moves these numbers on its own (fresh heap);
the gate explicitly requires an **aged** re-measure. So: note the spawn-type line now, and re-read
/paper-trades, /signals, /journal after the process has been up **≥1 h** — the honest comparison is
0.78 / 2.46 / 2.26 s above. Non-DB pages (/roadmap) should stay flat either way.

---

## Step 2 (optional, same sitting) — L2 recorder LaunchAgent

`com.xsnyde2.copybot-l2-recorder.plist` (KeepAlive + RunAtLoad) has been written since 2026-09-26 but never
loaded, because bootstrap is blocked from here. Today a **cron watchdog** (every 5 min, silent while healthy)
provides the same recovery with a ≤5-minute window. Loading the agent buys: restart **at login** (before the
gateway is even up) and an instant restart instead of up to 5 minutes of lost tape. Optional — the watchdog
path already works.

**Order matters: load first, then retire the hand-started instance.** Killing first opens a 0-instance window
that the 5-minute watchdog tick can race into, which would leave a detached recorder and a launchd recorder
running side by side (double-writing the tape).

```
L=gui/$UID
echo "=== who is alive now (record these pids) ==="
pgrep -fl 'scripts/record-l2.ts'

launchctl bootstrap $L ~/Library/LaunchAgents/com.xsnyde2.copybot-l2-recorder.plist
sleep 3
launchctl print $L/com.xsnyde2.copybot-l2-recorder | grep -E 'state =|pid =|last exit code'

# kill ONLY the pids from the first listing (the detached ones) — the agent's pid is the one launchd just printed
kill <pids from the first listing>
sleep 2
echo "=== expect exactly 2 (tsx + its child) ==="
pgrep -f 'scripts/record-l2.ts' | wc -l
tail -1 ~/polymarket-copybot/logs/record-l2.log
```

**Pass condition:** `launchctl print` shows the job running, `pgrep … | wc -l` = **2** (never 4 — that would
be two recorders, i.e. a duplicate tape), and the log's last line is a fresh `lastPoll=`.

**Rollback** (back to the watchdog-only world):

```
launchctl bootout $L/com.xsnyde2.copybot-l2-recorder
python3 ~/polymarket-copybot/scripts/start-l2-recorder.py
```

**Noticed, not actioned:** that plist carries `ProcessType = Background` — the same QoS key the dashboard card
exists to fix. Whether a continuously-writing recorder is being throttled is **unmeasured**, so leave it alone
Tuesday; if you want it priced, that is a separate measurement card, not a plist edit on the day.

---

## What I do the moment you say it's done

- read back the `spawn type` line (the diagnostic) and confirm the new pid;
- re-read the three latencies against the 0.78 / 2.46 / 2.26 s baseline, quoting the process age with them;
- confirm exactly one recorder pair if you also did Step 2, and check the watchdog stayed silent;
- then close `dashboard-launchd-qos` (and move `l2-recorder-supervision` to Done if Step 2 went through).

## Reproduce / reference

```
launchctl print gui/$UID/com.xsnyde2.copybot-dashboard | grep "spawn type"
pgrep -f 'scripts/record-l2.ts' | wc -l
```
Skill reference: `polymarket-copybot-ops` → `references/dashboard-performance.md`, section
"A live process can be slow for a reason the code does not have: QoS".
