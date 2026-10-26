#!/bin/bash
# One-shot: resume the daily copybot tuning review after the 12h series ends.
set -euo pipefail
hermes cron resume 3e9805c12911 && echo "Daily tuning review resumed (12h series complete)."
