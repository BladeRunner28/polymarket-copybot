#!/usr/bin/env python3
"""Fetch Atlas stories from the KEYLESS GDELT bulk route.

Replaces `fetch_stories.py` (GDELT Cloud, https://gdeltcloud.com/api/v2/stories), which is dead from
this host: the Cloud plan answers 403 "API keys are not included in your current plan (free) outside
an active evaluation", so the rebuild cron had been keeping its previous snapshot since 2026-10-02.
This reads the same keyless bulk corpus the GDELT shadow lane already consumes
(`~/polymarket-copybot/data/gdelt-bulk/YYYYMMDD.jsonl.gz`, written by
political-research-bot/src/gdelt_bulk.py from GDELT's 15-minute published event exports).

Shape mismatch, handled here rather than in the atlas:
  * the bulk corpus is EVENT-level (~24k rows/day) and the atlas is STORY-level -> events are grouped
    by (domain, url), so one record = one article URL.
  * it carries no `significance` (that is the Cloud's paid score). The replacement is a DERIVED
    salience proxy, documented in `score()` and labelled as derived in the atlas UI. Nothing reads it
    but the viewer; no decision path imports this file.
  * it carries no country name field: `action_geo` is a geo STRING ("Delhi, Delhi, India"), so the
    country is its last component, resolved to ISO3 through build.clean_country (the same alias table
    the map uses). When action_geo is absent, actor1_country / actor2_country (already ISO3) is used.
  * it carries no article title: `title_derived` is GDELT's URL-slug reconstruction, used as-is.

Exit codes match the old fetcher so the cron wrapper's logic is unchanged:
  0 = wrote the snapshot, 2 = too few stories (keep the previous snapshot), 1 = hard failure.
"""
import argparse
import collections
import glob
import gzip
import hashlib
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
from build import clean_country  # noqa: E402  (ISO3 alias table + ISO3 passthrough)

DEFAULT_BULK = os.path.expanduser("~/polymarket-copybot/data/gdelt-bulk")
DEFAULT_OUT = os.path.join(ROOT, "data", "stories_latest.json")
MIN_STORIES = 50

# Derived-salience constants. Hand-set on purpose and stated in the UI: this is a visualisation
# ordering score, not a calibrated measurement (the atlas gates nothing).
BREADTH_AT = 50.0   # article count that maxes the coverage term (p90 of the corpus is ~10)
GOLDSTEIN_MAX = 10.0


def clean_title(raw, domain):
    """`title_derived` is GDELT's URL-slug reconstruction. Two artifacts are worth removing:
    a leading numeric article id ("264820982 pentagon says ...") and opaque token slugs that are not
    words at all ("YPCMAT6S22TS/CF2VJ/SOKHXPA5M" — tracking/redirect paths) -> fall back to the
    domain so the feed never shows a hash as a headline."""
    t = (raw or "").strip()
    t = re.sub(r"^\d{5,}[\s\-_/.]+", "", t)
    if not t or not re.search(r"[a-z]", t):   # no lowercase letter anywhere = not a phrase
        return domain or "(untitled)"
    return t


def score(num_articles, abs_goldstein):
    """Derived salience in [0,1]: 0.6 x coverage breadth + 0.4 x event magnitude."""
    breadth = min((num_articles or 0) / BREADTH_AT, 1.0)
    magnitude = min((abs_goldstein or 0.0) / GOLDSTEIN_MAX, 1.0)
    return round(0.6 * breadth + 0.4 * magnitude, 4)


def last_component(geo):
    """'Delhi, Delhi, India' -> 'India'; 'United States' -> 'United States'."""
    if not geo:
        return None
    return geo.split(",")[-1].strip() or None


def load_days(bulk_dir, days):
    """Newest `days` day-files, oldest first."""
    files = sorted(glob.glob(os.path.join(os.path.expanduser(bulk_dir), "*.jsonl.gz")))
    if not files:
        raise SystemExit(f"no bulk files under {bulk_dir}")
    return files[-days:]


def group_stories(files):
    """Fold event rows into one record per (domain, url)."""
    by_url = {}
    rows = 0
    for path in files:
        with gzip.open(path, "rt") as fh:
            for line in fh:
                try:
                    r = json.loads(line)
                except json.JSONDecodeError:
                    continue
                url = r.get("url") or ""
                if not url:
                    continue
                rows += 1
                key = (r.get("domain") or "", url)
                s = by_url.get(key)
                if s is None:
                    s = by_url[key] = {
                        "n_events": 0, "articles": 0, "mentions": 0,
                        "abs_goldstein": 0.0, "min_tone": 0.0, "first_ts": r.get("ts") or "",
                        "cats": collections.Counter(), "geos": collections.Counter(),
                        "title": r.get("title_derived") or r.get("title") or "",
                        "event_code": r.get("event_code") or "", "event_root": r.get("event_root") or "",
                        "ac1": r.get("actor1_country") or "", "ac2": r.get("actor2_country") or "",
                    }
                s["n_events"] += 1
                for k, cast, cap in (("num_articles", int, "articles"), ("num_mentions", int, "mentions")):
                    try:
                        v = int(r.get(k) or 0)
                    except (TypeError, ValueError):
                        v = 0
                    if v > s[cap]:
                        s[cap] = v
                try:
                    g = abs(float(r.get("goldstein") or 0.0))
                except (TypeError, ValueError):
                    g = 0.0
                if g > s["abs_goldstein"]:
                    s["abs_goldstein"] = g
                    s["event_code"] = r.get("event_code") or s["event_code"]
                    s["event_root"] = r.get("event_root") or s["event_root"]
                try:
                    tone = float(r.get("tone") or 0.0)
                except (TypeError, ValueError):
                    tone = 0.0
                if tone < s["min_tone"]:
                    s["min_tone"] = tone
                if r.get("category"):
                    s["cats"][r["category"]] += 1
                geo = last_component(r.get("action_geo"))
                if geo:
                    s["geos"][geo] += 1
    return by_url, rows


def to_record(key, s):
    domain, url = key
    cat = s["cats"].most_common(1)[0][0] if s["cats"] else "Uncategorized"
    geo_name = s["geos"].most_common(1)[0][0] if s["geos"] else None
    iso3 = clean_country(geo_name) or clean_country(s["ac1"]) or clean_country(s["ac2"])
    return {
        "id": hashlib.sha1(url.encode("utf-8")).hexdigest()[:12],
        "title": clean_title(s["title"], domain),
        "url": url,
        "story_date": (s["first_ts"] or "")[:10],
        "category": cat,
        "subcategory": f"cameo:{s['event_root']}" if s["event_root"] else "",
        "geo": {"country": geo_name or ""},
        "metrics": {"significance": score(s["articles"], s["abs_goldstein"]),
                    "article_count": s["articles"], "mentions": s["mentions"]},
        "_iso3": iso3 or "",
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=3, help="how many daily bulk files to fold in")
    ap.add_argument("--bulk-dir", default=DEFAULT_BULK)
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--min-stories", type=int, default=MIN_STORIES)
    ap.add_argument("--max-stories", type=int, default=0, help="0 = keep every grouped story")
    args = ap.parse_args()

    files = load_days(args.bulk_dir, args.days)
    by_url, rows = group_stories(files)
    records = [to_record(k, s) for k, s in by_url.items()]
    records.sort(key=lambda r: (-r["metrics"]["significance"], r["story_date"]), reverse=False)
    if args.max_stories and len(records) > args.max_stories:
        records = records[: args.max_stories]

    covered = len({r["_iso3"] for r in records if r["_iso3"]})
    cats = collections.Counter(r["category"] for r in records)
    print(f"bulk files: {', '.join(os.path.basename(f) for f in files)}", flush=True)
    print(f"event rows {rows} -> unique article URLs {len(by_url)} | stories kept {len(records)}", flush=True)
    print(f"countries resolvable: {covered} | cats: {dict(cats.most_common())}", flush=True)

    if len(records) < args.min_stories:
        print(f"below MIN_STORIES ({args.min_stories}) — keeping previous snapshot, exiting 2", flush=True)
        sys.exit(2)

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w") as f:
        json.dump(records, f, ensure_ascii=False)
    print(f"saved {args.out} ({len(records)} stories, {os.path.getsize(args.out) / 1e6:.2f} MB)", flush=True)


if __name__ == "__main__":
    main()
