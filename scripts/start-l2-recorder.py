#!/usr/bin/env python3
"""Detached launcher for the L2 recorder.

Why not the gateway's background runner: that process is a child of the Hermes gateway, so a gateway
session boundary reaps it (proven on 2026-09-26 at 03:28:38 — an instance started the same way died
mid-collection with no alarm). start_new_session=True gives the recorder its own session and reparents
it to launchd, so it survives the gateway. KeepAlive supervision is the LaunchAgent's job
(~/Library/LaunchAgents/com.xsnyde2.copybot-l2-recorder.plist), which needs a human to bootstrap.
"""
import os
import subprocess

REPO = "/Users/xsnyde2/polymarket-copybot"
LOG = os.path.join(REPO, "logs", "record-l2.log")

env = dict(os.environ, DATABASE_URL="file:./dev.db")
log = open(LOG, "ab", buffering=0)
p = subprocess.Popen(
    ["/opt/homebrew/bin/node", "node_modules/tsx/dist/cli.mjs", "scripts/record-l2.ts"],
    cwd=REPO, stdout=log, stderr=log, stdin=subprocess.DEVNULL,
    start_new_session=True, env=env,
)
print("pid", p.pid)
