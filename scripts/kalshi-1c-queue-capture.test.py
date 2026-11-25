"""Unit check for the capture's timestamp normaliser (Kalshi emits two fractional formats).

Expected values are computed with an independent path (datetime with an explicit tzinfo), not
hardcoded, so the test cannot agree with itself by construction.
"""
import importlib.util
import sys
from datetime import datetime, timedelta, timezone

PATH = "/Users/xsnyde2/polymarket-copybot/.worktrees/t_0cb77acd/scripts/kalshi-1c-queue-capture.py"
spec = importlib.util.spec_from_file_location("cap", PATH)
assert spec is not None and spec.loader is not None
cap = importlib.util.module_from_spec(spec)
sys.modules["cap"] = cap
spec.loader.exec_module(cap)

base = datetime(2026, 10, 29, 22, 57, 42, tzinfo=timezone.utc)
cases = [
    ("2026-10-29T22:57:42.4189+00:00", base + timedelta(microseconds=418900)),
    ("2026-10-29T22:57:42.418900Z", base + timedelta(microseconds=418900)),
    ("2026-10-29T22:57:42Z", base),
    ("2026-10-29T22:57:42.4189-05:00", base + timedelta(microseconds=418900, hours=5)),
    ("2026-10-29T22:57:42.001Z", base + timedelta(microseconds=1000)),
    ("2026-10-29T22:57:42.123456789Z", base + timedelta(microseconds=123457)),
]
bad = 0
for s, want_dt in cases:
    got = cap.parse_ts(s)
    want = want_dt.timestamp()
    ok = abs(got - want) < 0.002
    bad += 0 if ok else 1
    print("%-34s -> %.4f  want %.4f  %s" % (s, got, want, "ok" if ok else "MISMATCH"))

n = cap.now_iso()
rt = datetime.fromtimestamp(cap.parse_ts(n), timezone.utc)
print("\nnow_iso() = %s  ->  round-trip %s  (drift %.3fs)"
      % (n, rt.isoformat(), abs((rt - datetime.now(timezone.utc)).total_seconds())))
print("failures:", bad)
sys.exit(1 if bad else 0)
