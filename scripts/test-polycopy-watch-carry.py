#!/usr/bin/env python3
"""Regression: polycopy-research-watch must CARRY a marker it cannot read, never substitute.

Defect under test (fixed in the same commit): copy_score_marker/psmi_method_marker swallowed
their own read failure and re-emitted a token ("COPY-SCORE-METHOD-SHA unavailable",
"PSMI-METHOD-VERSION unknown"). The cron engine diffs this script's stdout, so ONE
unreachable fetch produced a listing that differed from the cached one -> a wake that looked
like a catalogue change; and main() then wrote that token over the last good value in STATE,
so the real baseline was gone after a single transient error.

Run: python3 scripts/test-polycopy-watch-carry.py
"""
from __future__ import annotations

import importlib.util
import inspect
import io
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
TARGET = os.environ.get(
    "POLYCOPY_WATCH_TARGET", os.path.join(HERE, "cron-scripts", "polycopy-research-watch.py")
)

GOOD = (
    "REPORT /research/polymarket-top-100-cost-of-copying\n"
    "DATE-ON-PAGE April 15, 2026\n"
    "COPY-SCORE-METHOD-SHA 0533d3e008f3\n"
    "PSMI-METHOD-VERSION 2.0.0"
)

HTML = """
<h1>Research</h1>
<a href="/research/polymarket-top-100-cost-of-copying">x</a>
<p>April 15, 2026</p>
<p>What changed the method v3</p>
"""

fails = []


def check(name, cond, detail=""):
    if cond:
        print(f"  PASS  {name}")
    else:
        print(f"  FAIL  {name}  {detail}")
        fails.append(name)


def build_with(mod, cached):
    """Call build(cached), tolerating the pre-fix zero-argument signature."""
    if len(inspect.signature(mod.build).parameters):
        return mod.build(cached)
    return mod.build()


def misses(mod, name):
    """Consecutive-miss counter, or None where the script has no such concept (pre-fix)."""
    fn = getattr(mod, "_fails", None)
    return None if fn is None else fn().get(name)


def load(tmp):
    spec = importlib.util.spec_from_file_location("pw_under_test", TARGET)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.STATE = os.path.join(tmp, "state.txt")
    mod.FAILS = mod.STATE + ".fails"
    return mod


def main():
    tmp = tempfile.mkdtemp(prefix="pwtest-")
    mod = load(tmp)
    with open(mod.STATE, "w") as fh:
        fh.write(GOOD + "\n")

    state = {"down": True}

    def fake_fetch(url):
        if url == mod.COPY_SCORE:
            if state["down"]:
                raise OSError("connection refused (simulated)")
            return "<html><p>What changed the method v3</p></html>"
        if url == mod.RESEARCH:
            return HTML
        if url == mod.PSMI_PUBLIC:
            return '{"methodologyVersion": "2.0.0"}'
        raise AssertionError("unexpected url " + url)

    mod.fetch = fake_fetch

    # 1. first miss must be byte-identical to the cached listing (silent)
    out1 = build_with(mod, GOOD)
    check("miss 1 is byte-identical to cache", out1 == GOOD, repr(out1))
    check("miss 1 keeps the real sha", "0533d3e008f3" in out1, repr(out1))
    check("miss 1 writes no token", "unavailable" not in out1 and "unknown" not in out1)

    # 2. third consecutive miss escalates ONCE, with a constant suffix
    build_with(mod, GOOD)  # 2
    out3 = build_with(mod, GOOD)  # 3
    check("miss 3 marks STALE",
          any(ln.endswith(" STALE(>=3)") for ln in out3.splitlines()), repr(out3))
    check("miss counter is 3", misses(mod, "COPY-SCORE-METHOD-SHA") == 3,
          repr(misses(mod, "COPY-SCORE-METHOD-SHA")))
    out4 = build_with(mod, out3)  # 4, carries the stale line forward
    out5 = build_with(mod, out4)
    check("miss 4 does not change again", out4 == out5, f"{out4!r} != {out5!r}")

    # 3. recovery returns the plain marker and resets the counter
    state["down"] = False
    recovered = build_with(mod, out5)
    check("recovery clears STALE", "STALE" not in recovered, repr(recovered))
    check("recovery restores a plain sha line",
          any(ln.startswith("COPY-SCORE-METHOD-SHA ") and len(ln) == len("COPY-SCORE-METHOD-SHA 0123456789ab")
              for ln in recovered.splitlines()), repr(recovered))
    check("recovery resets counter", misses(mod, "COPY-SCORE-METHOD-SHA") == 0)

    # 4. nothing to carry -> raise, so main() re-prints the whole cached listing
    state["down"] = True
    mod.STATE = os.path.join(tmp, "empty.txt")
    mod.FAILS = mod.STATE + ".fails"
    raised = False
    try:
        build_with(mod, "")
    except Exception:
        raised = True
    check("cold start with a dead marker raises (no token guess)", raised)

    print("\n%d assertion(s) failed" % len(fails))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
