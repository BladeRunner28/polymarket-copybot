#!/bin/bash
# TTR floor shadow watchdog (2026-10-23, Lane A approved).
# Silent while the forward read is still accumulating (empty stdout = nothing sent);
# prints the report only when the verdict becomes FLIP / REFUTED / INSUFFICIENT.
# The script is read-only: it never changes the rule. Flipping the floor stays Lane A.
set -uo pipefail
cd /Users/xsnyde2/polymarket-copybot || exit 3
exec python3 scripts/ttr-floor-shadow.py --quiet
