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
    error is not mistaken for a catalogue change,
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
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/131 Safari/537.36"
DATE_RE = re.compile(
    r"(?:January|February|March|April|May|June|July|August|September|October|November|December)"
    r"\s+\d{1,2},\s+\d{4}"
)


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


def copy_score_marker() -> list[str]:
    """The 'What changed' block on /copy-score — revised whenever their signal does."""
    t = text_of(fetch(COPY_SCORE))
    i = t.find("What changed")
    section = t[i : i + 1200] if i >= 0 else ""
    section = re.sub(r"[^A-Za-z0-9 ,.%+-]", " ", section)
    section = re.sub(r"\s+", " ", section).strip()
    digest = hashlib.sha256(section.encode()).hexdigest()[:12]
    return [f"COPY-SCORE-METHOD-SHA {digest}"]


def psmi_method_marker() -> list[str]:
    try:
        data = json.loads(fetch(PSMI_PUBLIC))
    except Exception:
        return ["PSMI-METHOD-VERSION unknown"]
    return [f"PSMI-METHOD-VERSION {data.get('methodologyVersion', 'unknown')}"]


def build() -> str:
    lines: list[str] = []
    lines += research_lines()
    try:
        lines += copy_score_marker()
    except Exception:
        lines.append("COPY-SCORE-METHOD-SHA unavailable")
    lines += psmi_method_marker()
    return "\n".join(lines)


def main() -> int:
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    cached = ""
    if os.path.exists(STATE):
        cached = open(STATE).read().rstrip("\n")
    try:
        current = build()
    except Exception as e:  # network/parse failure: repeat the last good listing
        print(cached or f"POLYCOPY-WATCH unavailable ({type(e).__name__})")
        return 0
    if current != cached:
        open(STATE, "w").write(current + "\n")
    print(current)
    return 0


if __name__ == "__main__":
    sys.exit(main())
