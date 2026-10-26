#!/usr/bin/env python3
"""Deployed entry point for the btx2 deterministic-convergence gate.

Source of truth: the repo copy (scripts/cron-gates/copybot-btc-convergence-gate.py), versioned
and carried by the nightly backup. ~/.hermes/scripts is not a git repo and is not in the backup
REPOS list, so the logic must live in the repo. run_name="__main__" preserves the exit code.
"""
import runpy
import sys

TARGET = "/Users/xsnyde2/polymarket-copybot/scripts/cron-gates/copybot-btc-convergence-gate.py"

if __name__ == "__main__":
    runpy.run_path(TARGET, run_name="__main__")
    sys.exit(0)
