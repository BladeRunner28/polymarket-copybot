#!/usr/bin/env python3
"""
data-feed-scout.py — find candidate external data feeds for the ML lane (copybot).

WHY THIS EXISTS: the ML-1 era-stratified holdout says the model is not short of capacity, it is short of
INFORMATION. Price-only scores 0.6704 AUC on the held-out era and every wallet feature loses to it
(detected_price +0.0001, wallet_quality 0.4434 — worse than a coin flip). Price itself fell 0.7592 ->
0.6704 between eras, so the binding problem is REGIME, not coverage. The only thing worth adding is
signal that is ORTHOGONAL to price: what the market is a bet on (fixtures, injuries, schedules, news
flow, polls, weather), not another transform of the order book we already hold.

This script is a CANDIDATE FINDER. It does not recommend and it never adopts. A candidate becomes a
recommendation only in a report that carries a decision rule (see the copybot-research-agent skill:
"a recommendation without a decision rule is an opinion").

SOURCES, and why they are shaped this way:
  - Reddit r/datasets: the user's directed starting point for TRAINING data. Reddit's `.json` endpoints
    403 from this host, so this uses the ATOM feeds, exactly as research-collect.py does.
  - HuggingFace /api/datasets: keyless search + the real licence from each dataset's card. Licence is
    fetched, never guessed: "no licence found" and "MIT" are different answers and only one of them is
    usable as a dependency.
  - arXiv RSS (q-fin / stat.ML): papers that RELEASE datasets, because a paper names its own licence
    and its own look-ahead caveats.

FAIL-LOUD CONTRACT (deliberate): every source prints `HTTP <code>` and a byte count, and a failed
source is recorded as FAILED rather than skipped. A zero from a failed request and a zero from an empty
listing are identical once parsed, so the two are never allowed to look the same here.

Outputs:
  data/data-feed-scout.json         machine artefact (all candidates + per-source health)
  drafts/data-feed-scout-<date>.md  human report

Usage:
  python3 scripts/data-feed-scout.py                 # both source families, write artefacts
  python3 scripts/data-feed-scout.py --dry-run       # print, write nothing
  python3 scripts/data-feed-scout.py --sources reddit
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UA = {"User-Agent": "polyhydra-research/1.0 (data-feed-scout)"}
TIMEOUT = 25

# --- Relevance model -------------------------------------------------------------------------------
# Weighted by what this bot is actually exposed to, not by general interest. The single largest fact in
# the book is that ~42/43 admitted news-lead markets are SPORT, so sport feeds outrank everything. Price
# history and order books are deliberately NOT rewarded: we already record L2 (44k book files) and a
# feed that duplicates it adds no orthogonal information.
WEIGHTS = [
    # "injury" on its own is a trap: it retrieved road-traffic, spinal-cord and OSHA datasets, which are
    # a different word entirely. Require sports context within 40 chars, and demote the bare term.
    (4, r"\b(fixture|fixtures|match result|scoreline|lineup|team news|squad|"
        r"sports?|football|soccer|nba|nfl|mlb|nhl|tennis|f1|formula 1|cricket|boxing|ufc|esports?)\b"),
    (3, r"\b(?:player|team|squad|match|fixture|league|season|club)[\w\s,.-]{0,40}\binjur(?:y|ies)\b"),
    (3, r"\binjur(?:y|ies)[\w\s,.-]{0,40}\b(?:player|team|match|fixture|league|season|club)\b"),
    (3, r"\b(headline|news|article|event|press|gdelt|wire|reuters|announcement)\b"),
    (3, r"\b(odds|bookmaker|betting|closing line|implied probability|forecast|forecast(?:s|ing)?)\b"),
    (2, r"\b(poll|polls|polling|election|electoral|approval rating|referendum)\b"),
    (2, r"\b(sentiment|tone|stance|emotion|social)\b"),
    (2, r"\b(weather|forecast|temperature|hurricane|storm|rainfall|climate)\b"),
    (2, r"\b(macro|gdp|cpi|inflation|payroll|unemployment|fred|interest rate|yield)\b"),
    (2, r"\b(calendar|schedule|schedul(?:e|ed|ing)|deadline|kick-?off|start time)\b"),
    (1, r"\b(time series|timeseries|temporal|panel|longitudinal)\b"),
    (1, r"\b(crypto|bitcoin|ethereum|onchain|on-chain)\b"),
    (1, r"\b(resolution|catalyst|event study|surprise|revision)\b"),
]
PENALTIES = [
    (-3, r"\b(synthetic|toy|tutorial|dummy|sample dataset|hello world)\b"),
    (-2, r"\b(benchmark only|academic exercise|kaggle competition)\b"),
    # Wrong-domain senses that the keyword model happily retrieved. A dataset about road-traffic trauma
    # or spinal-cord injury says nothing about whether a striker plays on Saturday.
    (-6, r"\b(road[- ]traffic|spinal cord|neiss|osha|construction|disability|trauma|mortality|"
         r"fatalit(?:y|ies)|hospital|patient|clinical|paraplegia|burn|wound)\b"),
    (-4, r"\b(narrative coding|synth(?:etic)? [a-z]+ (?:injur|disab)|aggregates? \d{4})\b"),
]

# Licence classes. Copyleft and unlicensed are NOT rejected outright — the standing rule is that
# licence-blocked material is often still a source of good design questions; it just cannot become a
# dependency of the live lane.
PERMISSIVE = re.compile(
    r"^(mit|apache-2\.0|bsd-2-clause|bsd-3-clause|cc0-1\.0|cc-by-2\.0|cc-by-3\.0|cc-by-4\.0|"
    r"cc-by-sa-4\.0|odc-by|odbl|public-domain|pddl|wtfpl|unlicense|isc|mpl-2\.0)", re.I)
COPYLEFT = re.compile(r"^(a?gpl|lgpl|gpl-2\.0|gpl-3\.0|agpl-3\.0|cc-by-nc)", re.I)

# Look-ahead / leakage is the failure mode that silently inflates an AUC and cannot be seen in the
# score. These are FLAGS for a human read, never a verdict.
LEAK_FLAGS = [
    (r"\b(post[- ]?match|post[- ]?game|full[- ]?time)\b", "labels/frames reference post-event state"),
    (r"\b(settled|final outcome|winner column|result column)\b", "outcome columns present — check they are labels, not features"),
    (r"\b(backfill(?:ed)?|retrospective|compiled in \d{4}|scraped in \d{4})\b", "compiled retrospectively — verify no later edits"),
    (r"\b(closing (?:line|odds|price))\b", "closing values are outcome-adjacent — usable only as a target, never a feature"),
]

RSS_FEEDS = [
    ("r/datasets new", "https://www.reddit.com/r/datasets/new/.rss"),
    ("r/datasets top/week", "https://www.reddit.com/r/datasets/top/.rss?t=week"),
    ("r/datasets search: prediction", "https://www.reddit.com/r/datasets/search.rss?q=prediction&restrict_sr=1&sort=new&t=year"),
    ("r/datasets search: sports", "https://www.reddit.com/r/datasets/search.rss?q=sports&restrict_sr=1&sort=new&t=year"),
]

HF_QUERIES = [
    "sports results", "football fixtures", "injury", "betting odds", "prediction market",
    "news headlines", "event dataset", "polling", "weather forecast", "macro economic",
]

ARXIV_FEEDS = [
    ("arXiv q-fin.TR", "https://rss.arxiv.org/rss/q-fin.TR"),
    ("arXiv stat.ML", "https://rss.arxiv.org/rss/stat.ML"),
]

SOURCE_HEALTH: list[dict] = []


def fetch(url: str, accept: str = "*/*", retries: int = 2) -> tuple[bytes | None, str]:
    """Return (body, status). Status carries the HTTP code or exception, so a failure is never a zero.

    Reddit rate-limits this host: the FIRST feed answers 200 and later ones 429. That is throttling,
    not a block, so retry with a widening gap before recording a failure — and record it if it still
    fails, because "429 on three of four feeds" is a real limit on what this run saw.
    """
    last = ""
    for attempt in range(retries):
        if attempt:
            time.sleep(4 * attempt)
        try:
            req = urllib.request.Request(url, headers={**UA, "Accept": accept})
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                body = r.read()
                return body, f"HTTP {r.status} {len(body)}B"
        except urllib.error.HTTPError as e:
            last = f"HTTP {e.code}"
            if e.code not in (429, 503):
                return None, last
        except Exception as e:  # noqa: BLE001
            return None, f"{type(e).__name__}: {e}"
    return None, last


# A Reddit post states its licence in the TITLE or body, not in metadata. Extracting it is the
# difference between "ideas-only" and "eligible" for a dataset that is in fact CC BY 4.0 — but it is
# the POST's claim, so it is marked as such and must be re-verified at the primary host.
STATED_LICENCE = re.compile(
    r"\b(CC0(?:\s*1\.0)?|CC[ -]BY(?:[ -]SA)?(?:[ -]\d\.\d)?|MIT|Apache[ -]2\.0|BSD-[23]-Clause|"
    r"ODbL|ODC-By|Public Domain|Unlicense|GPL-?[23]\.0|AGPL-?3\.0)\b", re.I)


def stated_licence(text: str) -> str | None:
    m = STATED_LICENCE.search(text or "")
    return m.group(1) if m else None


# --- cache -----------------------------------------------------------------------------------------
# Reddit throttles this host to roughly one feed per few minutes: a second run inside that window gets
# 429 on EVERY feed, which would read as "the source is broken" when it is merely throttled. Cache each
# body on disk with a TTL (the same shape research-collect.py uses) so a repeat run re-reads rather than
# re-fetches, and report which of fresh / cache / stale-cache a candidate set came from.
CACHE_DIR = os.path.join(ROOT, "data", "cache", "data-feed-scout")
CACHE_TTL_H = 6.0


def cached_fetch(url: str, accept: str = "*/*") -> tuple[bytes | None, str]:
    key = hashlib.sha1(url.encode()).hexdigest()[:16]
    path = os.path.join(CACHE_DIR, key + ".body")
    age_h = (time.time() - os.path.getmtime(path)) / 3600.0 if os.path.exists(path) else None
    if age_h is not None and age_h < CACHE_TTL_H:
        with open(path, "rb") as fh:
            return fh.read(), f"cache ({age_h:.1f}h old)"
    body, st = fetch(url, accept)
    if body is not None:
        os.makedirs(CACHE_DIR, exist_ok=True)
        with open(path, "wb") as fh:
            fh.write(body)
        return body, st
    if age_h is not None:
        with open(path, "rb") as fh:
            return fh.read(), f"STALE cache ({age_h:.1f}h old) after {st}"
    return None, st


def score(text: str) -> tuple[int, list[str]]:
    t = (text or "").lower()
    s, hits = 0, []
    for w, pat in WEIGHTS:
        m = re.search(pat, t)
        if m:
            s += w
            hits.append(m.group(0))
    for w, pat in PENALTIES:
        m = re.search(pat, t)
        if m:
            s += w
            hits.append(f"-{m.group(0)}")
    return s, hits


def licence_class(lic: str | None) -> str:
    if not lic:
        return "none"
    # Normalise BEFORE matching: a post writes "CC BY 4.0" and a dataset card writes "cc-by-4.0", and
    # matching only the hyphenated form silently demoted two genuinely permissive datasets to "review".
    lic = re.sub(r"\s+", "-", lic.strip().lower())
    if PERMISSIVE.match(lic):
        return "permissive"
    if COPYLEFT.match(lic):
        return "copyleft"
    return "other"


def leak_flags(text: str) -> list[str]:
    t = (text or "").lower()
    return [why for pat, why in LEAK_FLAGS if re.search(pat, t)]


def status_for(rel: int, lic_class: str) -> str:
    """The gate. Permissive + on-topic is eligible; unlicensed or copyleft can only ever be ideas."""
    if rel <= 0:
        return "drop"
    if lic_class == "permissive":
        return "eligible" if rel >= 4 else "review"
    if lic_class in ("copyleft", "none"):
        return "ideas-only"      # may still teach us a design question; cannot be a dependency
    return "review"


# --- source: Reddit (Atom) -------------------------------------------------------------------------
def scan_reddit() -> list[dict]:
    out: list[dict] = []
    for label, url in RSS_FEEDS:
        body, st = cached_fetch(url, "application/atom+xml, text/xml, */*")
        SOURCE_HEALTH.append({"source": f"reddit:{label}", "status": st, "url": url,
                              "entries": 0, "ok": body is not None})
        if body is None:
            continue
        try:
            root = ET.fromstring(body)
        except ET.ParseError as e:
            SOURCE_HEALTH[-1]["status"] = f"XML parse error: {e}"
            SOURCE_HEALTH[-1]["ok"] = False
            continue
        ns = {"a": "http://www.w3.org/2005/Atom"}
        n = 0
        for e in root.findall("a:entry", ns):
            title = (e.findtext("a:title", default="", namespaces=ns) or "").strip()
            le = e.find("a:link", ns)
            link = le.get("href", "") if le is not None else ""
            when = (e.findtext("a:updated", default="", namespaces=ns) or "")[:10]
            content = (e.findtext("a:content", default="", namespaces=ns) or "")
            content = re.sub(r"<[^>]+>", " ", content)[:1200]
            rel, hits = score(f"{title} {content}")
            n += 1
            if rel <= 0:
                continue
            # The licence is usually IN THE POST (e.g. "... 19,732 dated timeline events (CC BY 4.0)").
            # Taking it here is what separates a usable dataset from an ideas-only lead; it is recorded
            # as the post's CLAIM and still requires verification at the primary host.
            lic = stated_licence(f"{title} {content}")
            lc = licence_class(lic)
            out.append({
                "source": f"reddit:{label}", "title": title[:180], "url": link,
                "date": when, "relevance": rel, "hits": sorted(set(hits)),
                "licence": lic, "licence_class": lc, "status": status_for(rel, lc),
                "licence_basis": "stated in the reddit post — VERIFY at the primary host" if lic else None,
                "leak_flags": leak_flags(f"{title} {content}"),
                "note": "Reddit post — a LEAD only. Verify at the primary host before believing anything.",
            })
        SOURCE_HEALTH[-1]["entries"] = n
        time.sleep(3)   # Reddit throttles this host: first feed 200, later ones 429 without a gap
    return out


# --- source: HuggingFace (keyless search + real licence from the card) ------------------------------
def hf_detail(ds_id: str) -> dict:
    body, st = cached_fetch(f"https://huggingface.co/api/datasets/{urllib.parse.quote(ds_id)}")
    if body is None:
        return {"licence": None, "licence_status": st, "tags": [], "gated": None}
    try:
        j = json.loads(body)
    except Exception:  # noqa: BLE001
        return {"licence": None, "licence_status": "parse error", "tags": [], "gated": None}
    card = j.get("cardData") or {}
    lic = card.get("license")
    if isinstance(lic, list):
        lic = lic[0] if lic else None
    tags = j.get("tags") or []
    if not lic:
        for t in tags:
            if isinstance(t, str) and t.startswith("license:"):
                lic = t.split(":", 1)[1]
                break
    return {"licence": lic, "licence_status": st, "tags": tags, "gated": j.get("gated"),
            "lastModified": j.get("lastModified"), "downloads": j.get("downloads")}


def scan_hf() -> list[dict]:
    out: list[dict] = []
    seen: set[str] = set()
    for q in HF_QUERIES:
        url = ("https://huggingface.co/api/datasets?search=" + urllib.parse.quote(q)
               + "&limit=12&sort=downloads&direction=-1")
        body, st = cached_fetch(url)
        SOURCE_HEALTH.append({"source": f"hf:{q}", "status": st, "url": url, "entries": 0,
                              "ok": body is not None})
        if body is None:
            continue
        try:
            rows = json.loads(body)
        except Exception:  # noqa: BLE001
            SOURCE_HEALTH[-1]["status"] = "json parse error"
            SOURCE_HEALTH[-1]["ok"] = False
            continue
        SOURCE_HEALTH[-1]["entries"] = len(rows)
        for r in rows:
            ds = r.get("id")
            if not ds or ds in seen:
                continue
            seen.add(ds)
            det = hf_detail(ds)
            # Score the DATASET's own identity (id + tags), never the search query. Including the query
            # scored every hit for its own search terms -- that is how "sports results" produced a list
            # of unrelated datasets with rel=4.
            blob = ds + " " + " ".join(t for t in (det.get("tags") or []) if isinstance(t, str))
            rel, hits = score(blob)
            if rel <= 0:
                continue
            lc = licence_class(det.get("licence"))
            out.append({
                "source": "huggingface", "title": ds, "url": f"https://huggingface.co/datasets/{ds}",
                "date": (det.get("lastModified") or "")[:10], "relevance": rel,
                "hits": sorted(set(hits)), "licence": det.get("licence"),
                "licence_class": lc, "status": status_for(rel, lc),
                "downloads": det.get("downloads"), "gated": det.get("gated"),
                "tags": [t for t in (det.get("tags") or []) if isinstance(t, str)][:8],
                "leak_flags": leak_flags(ds),
                "note": "licence read from the dataset card (never guessed)",
            })
    return out


# --- source: arXiv (papers that release datasets) ---------------------------------------------------
def scan_arxiv() -> list[dict]:
    out: list[dict] = []
    for label, url in ARXIV_FEEDS:
        body, st = cached_fetch(url, "application/rss+xml, text/xml, */*")
        SOURCE_HEALTH.append({"source": f"arxiv:{label}", "status": st, "url": url,
                              "entries": 0, "ok": body is not None})
        if body is None:
            continue
        try:
            root = ET.fromstring(body)
        except ET.ParseError as e:
            SOURCE_HEALTH[-1]["status"] = f"XML parse error: {e}"
            SOURCE_HEALTH[-1]["ok"] = False
            continue
        n = 0
        for item in root.iter("item"):
            title = (item.findtext("title") or "").strip()
            desc = (item.findtext("description") or "")[:1500]
            link = (item.findtext("link") or "").strip()
            when = (item.findtext("pubDate") or "")[:16]
            n += 1
            rel, hits = score(f"{title} {desc}")
            if rel <= 0:
                continue
            out.append({"source": f"arxiv:{label}", "title": title[:180], "url": link,
                        "date": when, "relevance": rel, "hits": sorted(set(hits)),
                        "licence": None, "licence_class": "none", "status": "ideas-only",
                        "leak_flags": leak_flags(desc),
                        "note": "paper — dataset release terms live in the paper, mark unverified until read"})
        SOURCE_HEALTH[-1]["entries"] = n
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sources", default="reddit,hf,arxiv")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--top", type=int, default=25)
    args = ap.parse_args()
    want = {s.strip() for s in args.sources.split(",") if s.strip()}

    cands: list[dict] = []
    if "reddit" in want:
        cands += scan_reddit()
    if "hf" in want:
        cands += scan_hf()
    if "arxiv" in want:
        cands += scan_arxiv()

    # Dedupe across sources by URL. The same Reddit post surfaces from both /new and /top, and without
    # this the artefact double-counts it -- which reads as "two independent feeds agree" when it is one
    # post seen twice.
    by_url: dict[str, dict] = {}
    for c in cands:
        key = (c.get("url") or c.get("title") or "").strip()
        prev = by_url.get(key)
        if prev is None or c["relevance"] > prev["relevance"]:
            if prev is not None:
                c = {**c, "also_seen_in": [prev.get("source")]}
            by_url[key] = c
        elif prev is not None:
            prev.setdefault("also_seen_in", []).append(c.get("source"))
    cands = list(by_url.values())

    rank = {"eligible": 0, "review": 1, "ideas-only": 2, "drop": 3}
    cands.sort(key=lambda c: (rank.get(c["status"], 9), -c["relevance"]))

    failed = [h for h in SOURCE_HEALTH if not h["ok"]]
    today = dt.date.today().isoformat()
    art = {
        "generated_at": dt.datetime.now().isoformat(timespec="seconds"),
        "date": today,
        "sources": SOURCE_HEALTH,
        "sources_failed": len(failed),
        "counts": {
            "total": len(cands),
            "eligible": sum(1 for c in cands if c["status"] == "eligible"),
            "review": sum(1 for c in cands if c["status"] == "review"),
            "ideas_only": sum(1 for c in cands if c["status"] == "ideas-only"),
        },
        "candidates": cands,
    }

    print("=== SOURCE HEALTH ===")
    for h in SOURCE_HEALTH:
        print(f"  {'OK  ' if h['ok'] else 'FAIL'}  {h['source']:34} {h['status']:22} entries={h['entries']}")
    if failed:
        print(f"  !! {len(failed)} source(s) FAILED — reported, not skipped")
    print()
    c = art["counts"]
    print(f"=== CANDIDATES: {c['total']} total | eligible={c['eligible']} review={c['review']} "
          f"ideas-only={c['ideas_only']} ===")
    for cand in cands[: args.top]:
        lic = cand.get("licence") or "none"
        print(f"  [{cand['status']:10}] rel={cand['relevance']:2} lic={lic:14} {cand['title'][:78]}")
        if cand["leak_flags"]:
            print(f"                 LEAK-FLAG: {'; '.join(cand['leak_flags'])[:120]}")

    if args.dry_run:
        print("\n[dry-run] nothing written")
        return 0

    os.makedirs(os.path.join(ROOT, "data"), exist_ok=True)
    with open(os.path.join(ROOT, "data", "data-feed-scout.json"), "w", encoding="utf-8") as fh:
        json.dump(art, fh, indent=2)

    # Report. Deliberately contains NO recommendations: this script cannot state a decision rule.
    lines = [
        f"# Data-feed scout — {today}",
        "",
        f"Generated {art['generated_at']} by `scripts/data-feed-scout.py`.",
        "",
        "**This is a candidate list, not a recommendation set.** Per the research-agent rule, a",
        "recommendation needs a decision rule; this script cannot write one. Reading order: the human",
        "report interprets these candidates and carries at most four pre-registered proposals.",
        "",
        f"## Source health — {len(SOURCE_HEALTH) - len(failed)}/{len(SOURCE_HEALTH)} ok, {len(failed)} failed",
        "",
        "| source | status | entries |",
        "| --- | --- | --- |",
    ]
    for h in SOURCE_HEALTH:
        lines.append(f"| {h['source']} | {'ok' if h['ok'] else '**FAILED**'} {h['status']} | {h['entries']} |")
    lines += ["", f"## Candidates — {c['total']} ({c['eligible']} eligible, {c['review']} review, {c['ideas_only']} ideas-only)", ""]
    for cand in cands[: args.top]:
        lic = cand.get("licence") or "none"
        lines.append(f"- **[{cand['status']}]** `rel={cand['relevance']}` `lic={lic}` — "
                     f"[{cand['title']}]({cand['url']}) · {cand.get('date') or 'undated'} · {cand['source']}")
        if cand["hits"]:
            lines.append(f"  - matched: {', '.join(cand['hits'][:6])}")
        if cand["leak_flags"]:
            lines.append(f"  - **LEAK-FLAG**: {'; '.join(cand['leak_flags'])}")
        lines.append(f"  - {cand['note']}")
    out_md = os.path.join(ROOT, "drafts", f"data-feed-scout-{today}.md")
    os.makedirs(os.path.join(ROOT, "drafts"), exist_ok=True)
    with open(out_md, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    print(f"\nwrote data/data-feed-scout.json and {os.path.relpath(out_md, ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
