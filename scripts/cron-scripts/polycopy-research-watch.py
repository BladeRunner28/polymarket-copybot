#!/usr/bin/env python3
"""Polycopy research change-detector (deterministic output — no timestamps).

Prints a stable listing of polycopy.app's research catalogue plus two slow-moving
methodology markers. The Hermes cron engine diffs this output between ticks: if it
is byte-identical, the agent is NOT woken (no tokens spent), and their own FAQ puts
publication at 1-2 reports per MONTH — hence a watcher, not a daily scrape.

Determinism rules:
  - no fetch timestamps, no volatile numbers (the PSMI *score* moves daily and is
    deliberately excluded — only its methodologyVersion is watched),
  - on a fetch failure the last good listing is re-printed, so a transient network
    error is not mistaken for a catalogue change. That holds PER MARKER too: a marker
    that cannot be read re-emits its own last good line from STATE (never a substitute
    token such as "unavailable"/"unknown", which would both fake a change and overwrite
    the baseline). After FAIL_NOTICE consecutive misses the line gains a constant
    " STALE(>=n)" suffix — one wake, then stable,
  - robots.txt: /research and the marketing pages are Allow:'/'. /api/ and
    /export-polymarket-trades/ are DISALLOWED — never fetch them here. The single
    exception is the PSMI endpoint Polycopy advertises on its own page as a free
    API ("Free to use with attribution"), which is read for methodologyVersion only.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import urllib.request

RESEARCH = "https://polycopy.app/research"
COPY_SCORE = "https://polycopy.app/copy-score"
PSMI_PUBLIC = "https://polycopy.app/api/indexes/smi/public"

STATE = os.path.expanduser("~/.hermes/cache/polycopy-research-watch.state")
# Consecutive-miss counter for the two markers, kept in a SIDECAR so the diffed artefact
# stays pure. Not in STATE: a counter in the listing would itself change on every miss.
FAILS = STATE + ".fails"
FAIL_NOTICE = 3
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/131 Safari/537.36"
DATE_RE = re.compile(
    r"(?:January|February|March|April|May|June|July|August|September|October|November|December)"
    r"\s+\d{1,2},\s+\d{4}"
)


def _fails() -> dict:
    try:
        with open(FAILS) as fh:
            d = json.load(fh)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}  # no counter yet == zero misses; never fatal


def _set_fails(d: dict) -> None:
    try:
        tmp = FAILS + ".tmp"
        with open(tmp, "w") as fh:
            fh.write(json.dumps(d, sort_keys=True))
        os.replace(tmp, FAILS)
    except Exception as e:
        # Degrades escalation to STALE(n) only; the carried value is still emitted.
        print(f"polycopy-research-watch: cannot record miss count ({e})", file=sys.stderr)


def fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", "replace")


def text_of(html: str) -> str:
    body = re.sub(r"<script.*?</script>", " ", html, flags=re.S)
    body = re.sub(r"<style.*?</style>", " ", body, flags=re.S)
    body = re.sub(r"<[^>]+>", " ", body)
    body = re.sub(r"&nbsp;?", " ", body)
    body = body.replace("&amp;", "&").replace("&#x27;", "'").replace("&quot;", '"')
    return re.sub(r"\s+", " ", body)


def research_lines() -> list[str]:
    html = fetch(RESEARCH)
    slugs = sorted(
        {
            s
            for s in re.findall(r'href="(/research/[a-z0-9\-]+)"', html)
            if s != "/research"
        }
    )
    dates = sorted(set(DATE_RE.findall(html) and DATE_RE.findall(html)))
    out = [f"REPORT {s}" for s in slugs]
    out += [f"DATE-ON-PAGE {d}" for d in dates]
    return out


def copy_score_marker() -> str:
    """The 'What changed' block on /copy-score — revised whenever their signal does."""
    t = text_of(fetch(COPY_SCORE))
    i = t.find("What changed")
    if i < 0:
        # An empty section hashes to a *stable* constant (e3b0c44298fc...), which would be
        # cached as if it were their method and then never change again. Missing block =
        # failed read, not a fingerprint.
        raise ValueError("'What changed' block not found on /copy-score")
    section = t[i : i + 1200]
    section = re.sub(r"[^A-Za-z0-9 ,.%+-]", " ", section)
    section = re.sub(r"\s+", " ", section).strip()
    digest = hashlib.sha256(section.encode()).hexdigest()[:12]
    return f"COPY-SCORE-METHOD-SHA {digest}"


def psmi_method_marker() -> str:
    data = json.loads(fetch(PSMI_PUBLIC))
    version = data.get("methodologyVersion")
    if not version:
        # 'unknown' would be cached as a fingerprint and could never change again.
        raise ValueError("PSMI methodologyVersion absent from the public payload")
    return f"PSMI-METHOD-VERSION {version}"


def marker(name: str, fn, cached: str, fails: dict) -> str:
    """Read one methodology marker, re-printing the LAST GOOD line when it cannot be read.

    Substituting a token ("unavailable" / "unknown") changed the diffed artefact: one
    unreachable fetch looked exactly like a catalogue change to the cron engine, and the
    substituted line was then written over the last good value in STATE, destroying the
    baseline. Carrying the previous line keeps a transient error silent (byte-identical
    output) and keeps the real value on file. Only after FAIL_NOTICE consecutive misses
    does the line gain a " STALE(n)" suffix — one wake, then stable again.
    """
    prev = [ln for ln in cached.splitlines() if ln.startswith(name + " ")]
    try:
        line = fn()
    except Exception as e:
        fails[name] = int(fails.get(name, 0) or 0) + 1
        print(
            f"polycopy-research-watch: {name} unreadable "
            f"({type(e).__name__}: {e}); carrying last good value, miss {fails[name]}",
            file=sys.stderr,
        )
        if not prev:
            raise  # nothing good to carry: let main() re-print the whole cached listing
        line = prev[0]
        if fails[name] >= FAIL_NOTICE:
            # Constant suffix, not the live count: a growing "STALE(4)", "STALE(5)" would
            # change the artefact on every tick and wake the agent daily forever.
            line = f"{line.split(' STALE(')[0]} STALE(>={FAIL_NOTICE})"
    else:
        fails[name] = 0
    return line


def build(cached: str = "") -> str:
    fails = _fails()
    lines: list[str] = list(research_lines())
    lines.append(marker("COPY-SCORE-METHOD-SHA", copy_score_marker, cached, fails))
    lines.append(marker("PSMI-METHOD-VERSION", psmi_method_marker, cached, fails))
    _set_fails(fails)
    return "\n".join(lines)


def main() -> int:
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    cached = ""
    if os.path.exists(STATE):
        cached = open(STATE).read().rstrip("\n")
    try:
        current = build(cached)
    except Exception as e:  # network/parse failure: repeat the last good listing
        print(cached or f"POLYCOPY-WATCH unavailable ({type(e).__name__})")
        return 0
    if current != cached:
        open(STATE, "w").write(current + "\n")
    print(current)
    return 0


if __name__ == "__main__":
    sys.exit(main())
