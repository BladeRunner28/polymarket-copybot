#!/bin/bash
# CopyBot: refit the Wang-Transform premium calibration table (Phase A).
# Reads resolved C-200 paper trades, fits per-band lambda via the vendored
# oracle3 WangMLE, writes data/premium-calibration.json, posts the summary
# to Discord itself. Biweekly cadence (1st & 15th, 06:00).
set -uo pipefail
cd /Users/xsnyde2/polymarket-copybot
./venv-calib/bin/python scripts/calibrate-premium.py
