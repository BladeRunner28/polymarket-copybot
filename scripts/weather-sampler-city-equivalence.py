#!/usr/bin/env python3
"""Byte-identity gate for the weather sampler's CITY TABLE (card weather-city-dfw-set1, gate condition 3).

WHAT IT PROVES
--------------
"The one parameterised path leaves NYC's output byte-identical." A refactor that moves the established
city silently would make every later city inherit the break, and the wx2 sample is frozen, so this is
checked mechanically rather than by eye.

HOW (no network twice, no timing luck)
--------------------------------------
1. `git show <ref>:scripts/weather-nowcast-sampler.py` -> a module holding the PRE-change sampler.
2. Run the OLD module with a fixed `--now` while RECORDING every URL it fetches (url -> raw bytes).
3. Run the NEW module (`--city nyc`) with `--now` pinned to the same instant, serving every request from
   that recording. A URL the old sampler never asked for is a hard failure ("cache miss") — that is how a
   changed station, series, slug prefix or timezone shows up, and it is also why the comparison cannot
   pass on two live snapshots that merely happened to agree.
4. Compare, exactly: exit code, stdout, the URL SET (nothing added, nothing dropped) and the output FILE
   BYTES (the frozen sample's row shape, key order, labels and values).

Read-only. Writes only to a scratch dir. Exit 0 = PASS, 1 = FAIL, 2 = could not set up the comparison.

Usage: python3 scripts/weather-sampler-city-equivalence.py [--ref HEAD] [--city nyc] [--keep DIR]
"""
from __future__ import annotations

import argparse
import importlib.util
import io
import re
import subprocess
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SAMPLER = REPO / "scripts" / "weather-nowcast-sampler.py"


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def norm_stdout(s: str) -> str:
    """The verbose line now names the city it sampled (`city=nyc`), which is an observability improvement
    the pre-change sampler could not print (it had one city). Everything else on stdout is the contract,
    so the tag is stripped from BOTH sides and any other difference still fails."""
    return re.sub(r"city=\S+ ", "", s)


def run_main(mod, argv: list[str]) -> tuple[int, str]:
    """Call the module's main() with argv, capturing stdout (stdout IS a contract here)."""
    saved = sys.argv[:]
    buf = io.StringIO()
    sys.argv = [str(SAMPLER)] + argv
    try:
        with redirect_stdout(buf):
            rc = mod.main()
    finally:
        sys.argv = saved
    return rc, buf.getvalue()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ref", default="HEAD", help="git ref holding the PRE-change sampler")
    ap.add_argument("--city", default="nyc", help="city to compare (default nyc — the frozen sample)")
    ap.add_argument("--now", default=None, help="ISO instant to pin both runs to (default: now)")
    ap.add_argument("--keep", default=None, help="keep the two outputs here instead of a temp dir")
    a = ap.parse_args()

    try:
        old_src = subprocess.run(["git", "show", f"{a.ref}:scripts/weather-nowcast-sampler.py"],
                                 cwd=REPO, capture_output=True, text=True, check=True).stdout
    except subprocess.CalledProcessError as exc:
        print(f"SETUP-FAIL: cannot read the pre-change sampler from {a.ref}: {exc.stderr.strip()[:200]}")
        return 2
    if old_src.strip() == SAMPLER.read_text().strip():
        print("SETUP-FAIL: the working-tree sampler is identical to the ref — nothing to compare "
              "(commit or revert first)")
        return 2

    scratch = Path(a.keep) if a.keep else Path(tempfile.mkdtemp(prefix="wx-city-eq-"))
    scratch.mkdir(parents=True, exist_ok=True)
    old_path = scratch / "sampler_at_ref.py"
    old_path.write_text(old_src)
    out_old, out_new = scratch / "nyc_at_ref.jsonl", scratch / "nyc_now.jsonl"

    now = a.now
    if now is None:
        # one instant for BOTH runs, so `ts` and the cycle days cannot drift between them
        import datetime as _dt
        now = _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")

    old = load_module(old_path, "wx_sampler_at_ref")
    new = load_module(SAMPLER, "wx_sampler_now")

    cache: dict[str, bytes] = {}
    real_get = old.get

    def recording_get(url: str, tries: int = 3) -> bytes:
        b = real_get(url, tries)
        cache[url] = b
        return b

    hits: list[str] = []
    misses: list[str] = []

    def replay_get(url: str, tries: int = 3) -> bytes:
        if url in cache:
            hits.append(url)
            return cache[url]
        misses.append(url)
        raise RuntimeError(f"cache miss (URL the pre-change sampler never requested): {url}")

    old.get = recording_get
    new.get = replay_get

    print(f"== city-equivalence gate [{a.city}] ref={a.ref} now={now}")
    print(f"   old run: {old_path}")
    rc_old, so_old = run_main(old, ["--now", now, "--out", str(out_old), "--verbose"])
    print(f"   old rc={rc_old} urls={len(cache)}")
    rc_new, so_new = run_main(new, ["--city", a.city, "--now", now, "--out", str(out_new), "--verbose"])
    print(f"   new rc={rc_new} replayed_urls={len(set(hits))} cache_misses={len(misses)}")

    fails = []
    if rc_old != rc_new:
        fails.append(f"exit code differs: {rc_old} -> {rc_new}")
    if norm_stdout(so_old) != norm_stdout(so_new):
        fails.append("stdout differs (beyond the city= tag)")
    added = sorted(set(misses))
    dropped = sorted(set(cache) - set(hits))
    if added:
        fails.append(f"{len(added)} NEW url(s) requested, e.g. {added[:2]}")
    if dropped:
        fails.append(f"{len(dropped)} url(s) no longer requested, e.g. {dropped[:2]}")
    b_old = out_old.read_bytes() if out_old.exists() else b""
    b_new = out_new.read_bytes() if out_new.exists() else b""
    if b_old != b_new:
        # report the first differing line so a failure is diagnosable without a diff tool
        lo = b_old.decode().splitlines()
        ln = b_new.decode().splitlines()
        first = next((i for i, (x, y) in enumerate(zip(lo, ln)) if x != y), min(len(lo), len(ln)))
        fails.append(f"output bytes differ at line {first + 1} of {max(len(lo), len(ln))}")
        print(f"   line {first + 1} at ref: {lo[first][:300] if first < len(lo) else '<none>'}")
        print(f"   line {first + 1} now   : {ln[first][:300] if first < len(ln) else '<none>'}")

    rows = len(b_old.decode().splitlines()) if b_old else 0
    print(f"   rows={rows} bytes_at_ref={len(b_old)} bytes_now={len(b_new)} "
          f"stdout_match={norm_stdout(so_old) == norm_stdout(so_new)} "
          f"urls_added={len(added)} urls_dropped={len(dropped)}")
    if fails:
        for f in fails:
            print(f"FAIL: {f}")
        print(f"   artifacts kept in {scratch}")
        return 1
    print("PASS: NYC output byte-identical across the parameterisation; no URL added or dropped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
