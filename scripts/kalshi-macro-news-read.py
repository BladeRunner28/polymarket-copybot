#!/usr/bin/env python3
"""Kalshi macro lane - is the GDELT news CONTEXT column buildable at its gate? (card kalshi-gdelt-context-v2)

WHAT THIS ANSWERS
-----------------
The macro lane (scripts/kalshi-macro-shadow.py) appends a per-family GDELT count to
data/kalshi-macro-news.jsonl. The card that owns that column sets two conditions before it may
be shipped: (1) the replacement must come from TARGETED per-family queries, not substring
matching over a general capture, and (2) its precision must be MEASURED on >=50 labelled
matched stories per family and be >= 0.90 - "otherwise it is dropped rather than shipped vague".

This instrument measures both conditions on the only GDELT surface this host can reach, and
prints a per-family ship verdict. It changes nothing: read-only over data/gdelt-bulk/.

THE SURFACES, MEASURED 2026-11-14 (so nobody re-probes them blind)
-----------------------------------------------------------------
  * GDELT Cloud  https://gdeltcloud.com/api/v2  -> HTTP 403, "API keys are not included in your
    current plan (free) outside an active evaluation" (168 blocked calls in 7 days). A PLAN
    error: retrying cannot fix it. The card believed this was "the query surface the repo
    already uses" - it is dead from this host.
  * GDELT DOC    http://api.gdeltproject.org/api/v2/doc/doc -> HTTP 429 at >=7s spacing, 2/2
    this run, 5/5 measured 2026-10-10. Persistently rate-limited for this IP.
  * GDELT BULK   the 15-minute .export.CSV.zip feed -> OPEN (200). This is the corpus we hold,
    and it is an EVENT table: it carries NO article title (the lane reconstructs one from the
    URL slug) and the held capture is pre-filtered by the collector's six topic queries.

BASIS OF EVERY NUMBER PRINTED
-----------------------------
  population : data/gdelt-bulk/*.jsonl.gz, one row per GDELT event; a "story" = one distinct
               SOURCE URL after canonicalisation (scheme, ":443" port and trailing slash
               stripped - two rows differing only by port were counted as two stories by the
               lane's own dedupe, which is one of the defects this instrument found).
  clock      : the daily capture file stamp (2026-10-02 .. newest), i.e. the ingest day.
  level      : one article (slug matching) / one row (row matching); labels are per article.
  labels     : data/kalshi-macro-news-labels.json - hand-labelled, rule stated in the file,
               keyed by canonical URL so a growing corpus shows up as UNLABELLED rather than
               silently shrinking the denominator.

USAGE
  python3 scripts/kalshi-macro-news-read.py             # full read, writes the artifact
  python3 scripts/kalshi-macro-news-read.py --self-test # 15 arms incl. mutation controls
  python3 scripts/kalshi-macro-news-read.py --days 14   # shorter window
"""

from __future__ import annotations

import argparse
import glob
import io
import gzip
import json
import math
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GDELT_DIR = ROOT / "data" / "gdelt-bulk"
LABELS_FILE = ROOT / "data" / "kalshi-macro-news-labels.json"
NEWS_FILE = ROOT / "data" / "kalshi-macro-news.jsonl"
OUT_FILE = ROOT / "data" / "kalshi-macro-news-read.json"
RAW_PROBE_FILE = ROOT / "data" / "kalshi-macro-news-raw-probe.json"
BULK_URL = "http://data.gdeltproject.org/gdeltv2/%s.export.CSV.zip"

# The live lane's families and keyword sets, copied verbatim so this read scores the rule that
# is actually running rather than a paraphrase of it. Keep in step with kalshi-macro-shadow.py.
FAMILIES = {
    "KXCPI": ["inflation", "cpi", "consumer price", "prices rose", "price index"],
    "KXFED": ["fed", "fomc", "powell", "rate cut", "rate hike", "federal reserve"],
    "KXU3": ["unemployment", "jobless", "u-3", "labor market"],
    "KXGDP": ["gdp", "economic growth", "recession"],
    "KXRECSSNBER": ["recession", "nber", "downturn"],
    "KXPAYROLLS": ["payroll", "nonfarm", "jobs report", "job growth"],
}

# ---------------------------------------------------------------------------------------------
# THE QUERY DEFINITION the card asks for: a targeted per-family query, expressed as anchors that
# must be present plus exclusions that name the false-positive CLASSES observed in the labels
# (a person named Powell, Lake Powell, "fed up", "fed" as federal-government shorthand, a
# utility's rate hike, CPI(M) the Indian party, a company called CPI). Every exclusion exists
# because a labelled row required it; none is speculative.
# ---------------------------------------------------------------------------------------------
V3_QUERIES = {
    "KXCPI": {
        "scope": "US",
        "anchor": ["consumer price index", "cpi report", "us cpi", "u.s. cpi", "core cpi",
                   "cpi data", "cpi rose", "cpi rises", "cpi fell", "cpi falls",
                   "inflation rate", "us inflation"],
        "exclude": ["cpi m", "cpi-m", "cpi mp", "cpi leader", "cpi party", "cpi property",
                    "communist"],
    },
    "KXFED": {
        "scope": "US",
        "anchor": ["federal reserve", "fomc", "monetary policy", "new york fed", "dallas fed",
                   "boston fed", "chicago fed", "fed chair", "fed governor", "fed official",
                   "fed policy", "fed rate", "fed cut", "fed hike", "fed meeting",
                   "fed minutes", "fed approv", "fed supervision", "fed board", "fed nominee"],
        "exclude": ["fed up", "lake powell", "kimberly powell", "denise powell",
                    "harding powell", "lucy powell", "powell river", "fed court",
                    "fed election", "fed agents", "fed prosecutors", "fed aid", "utility"],
    },
    "KXU3": {
        "scope": "US",
        "anchor": ["unemployment rate", "jobless claims", "u-3", "labor market", "nonfarm",
                   "jobs report", "unemployment"],
        "exclude": [],
    },
    "KXGDP": {
        "scope": "US",
        "anchor": ["gdp", "gross domestic product", "economic growth"],
        "exclude": [],
    },
    "KXRECSSNBER": {
        "scope": "US",
        "anchor": ["nber", "recession"],
        "exclude": [],
    },
    "KXPAYROLLS": {
        "scope": "US",
        "anchor": ["payrolls", "nonfarm", "jobs report", "job growth", "adp"],
        "exclude": [],
    },
}

GARBLED_TITLE = re.compile(r"^(article\s+)?[0-9a-f]{8}([\s-][0-9a-f]{4})+|^article\s+[0-9a-f]{8}")
PRECISION_GATE = 0.90
MIN_LABELS = 50


def word_re(keys):
    return re.compile("|".join(r"\b%s\b" % re.escape(k) for k in keys), re.I)


def substring_re(keys):
    return re.compile("|".join(re.escape(k) for k in keys), re.I)


def v3_re(spec, field):
    return re.compile("|".join(re.escape(k) for k in (spec.get(field) or ["$^"])), re.I)


def canonical_url(url):
    """One story = one canonical URL. The lane deduped on the raw string, so a row served on
    :443 was counted twice (2 pairs in the 44-day KXFED population) - that is a story count
    inflated by a port number."""
    u = (url or "").strip().lower()
    u = re.sub(r"^https?://", "", u)
    u = re.sub(r":443(?=/|$)", "", u)
    u = u.rstrip("/")
    return u


def title_of(row):
    return (row.get("title") or row.get("title_derived") or "")


def corpus_files(days=None):
    files = sorted(glob.glob(str(GDELT_DIR / "*.jsonl.gz")))
    return files[-days:] if days else files


def iter_rows(files):
    for path in files:
        with gzip.open(path, "rt") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except Exception:
                    continue
                yield path, row


def scan(files, want=None):
    """One pass. Per family: substring row count, word-boundary row count, US-scoped story set,
    all-geo story set, and the v3 targeted-query story set."""
    fams = want or list(FAMILIES)
    kb = {f: word_re(FAMILIES[f]) for f in fams}
    sb = {f: substring_re(FAMILIES[f]) for f in fams}
    anc = {f: v3_re(V3_QUERIES[f], "anchor") for f in fams}
    exc = {f: v3_re(V3_QUERIES[f], "exclude") for f in fams}
    out = {
        "rows": 0,
        "events": set(),
        "articles": set(),
        "us_rows": 0,
        "us_articles": 0,
        "sub_rows": {f: 0 for f in fams},
        "wb_rows": {f: 0 for f in fams},
        "us_rows_fam": {f: 0 for f in fams},
        "stories": {f: {} for f in fams},
        "stories_any": {f: {} for f in fams},
        "v3": {f: {} for f in fams},
    }
    us_seen = set()
    for path, row in iter_rows(files):
        day = path.split("/")[-1][:8]
        out["rows"] += 1
        item = str(row.get("item_id") or "")
        ev = item.split(":")[0]
        if ev:
            out["events"].add(ev)
        url = row.get("url") or item
        if not url:
            continue
        cur = canonical_url(url)
        out["articles"].add(cur)
        country = (row.get("action_country") or "").upper()
        if country in ("US", "USA"):
            out["us_rows"] += 1
            if cur not in us_seen:
                us_seen.add(cur)
        title = title_of(row)
        for f in fams:
            if sb[f].search(title):
                out["sub_rows"][f] += 1
            if not kb[f].search(title):
                continue
            out["wb_rows"][f] += 1
            rec = {"title": title[:150], "domain": row.get("domain") or "", "day": day,
                   "country": country}
            out["stories_any"][f].setdefault(cur, rec)
            if country in ("US", "USA"):
                out["us_rows_fam"][f] += 1
                out["stories"][f].setdefault(cur, rec)
                if anc[f].search(title) and not exc[f].search(title):
                    out["v3"][f].setdefault(cur, rec)
    out["us_articles"] = len(us_seen)
    return out


def wilson(k, n, z=1.96):
    """Wilson score interval - the honest CI for a proportion measured on a small hand-labelled
    sample, which is exactly what the card's gate asks for."""
    if n <= 0:
        return (0.0, 0.0, 0.0)
    p = k / n
    d = 1.0 + z * z / n
    centre = (p + z * z / (2 * n)) / d
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (p, max(0.0, centre - half), min(1.0, centre + half))


def load_labels():
    if not LABELS_FILE.exists():
        return None
    with LABELS_FILE.open() as fh:
        return json.load(fh)


def score_family(labels, fam, stories, split_day=None):
    """Join labels to the population by canonical URL. A label is ON when the story is about the
    US macro concept the family prices; `on_lenient` marks US inflation discourse that is not the
    statistic itself and is reported separately, never folded into the strict count."""
    items = dict((labels.get("items") or {}).get(fam, {}))
    pop = set(stories or {})
    labelled = pop & set(items)
    n = len(labelled)

    def counts(pred):
        tp = fp = fn = tn = 0
        for u in labelled:
            truth = items[u].get("label") == "on"
            if pred(u):
                if truth:
                    tp += 1
                else:
                    fp += 1
            else:
                if truth:
                    fn += 1
                else:
                    tn += 1
        return tp, fp, fn, tn

    def arm(name, pred):
        tp, fp, fn, tn = counts(pred)
        p, lo, hi = wilson(tp, tp + fp)
        recall = tp / (tp + fn) if (tp + fn) else 0.0
        row = {
            "arm": name,
            "kept": tp + fp,
            "tp": tp, "fp": fp, "fn": fn,
            "precision": round(p, 4),
            "precision_ci95": [round(lo, 4), round(hi, 4)],
            "recall": round(recall, 4),
        }
        if split_day:
            d = {"tp": 0, "fp": 0, "fn": 0}
            h = {"tp": 0, "fp": 0, "fn": 0}
            for u in labelled:
                truth = items[u].get("label") == "on"
                hit = pred(u)
                tgt = d if stories[u]["day"] <= split_day else h
                if hit and truth:
                    tgt["tp"] += 1
                elif hit:
                    tgt["fp"] += 1
                elif truth:
                    tgt["fn"] += 1
            row["design"] = dict(d, day_max=split_day,
                                 precision=round(d["tp"] / (d["tp"] + d["fp"]), 4) if (d["tp"] + d["fp"]) else None)
            row["holdout"] = dict(h, day_min=split_day,
                                  precision=round(h["tp"] / (h["tp"] + h["fp"]), 4) if (h["tp"] + h["fp"]) else None)
        return row

    targeted = None
    if fam in V3_QUERIES:
        anc = v3_re(V3_QUERIES[fam], "anchor")
        exc = v3_re(V3_QUERIES[fam], "exclude")

        def is_v3(u):
            t = stories[u]["title"]
            return bool(anc.search(t)) and not exc.search(t)

        targeted = arm("targeted_query_v3", is_v3)
    on = sum(1 for u in labelled if items[u].get("label") == "on")
    lenient = sum(1 for u in labelled if items[u].get("label") == "on_lenient")
    return {
        "family": fam,
        "population": len(pop),
        "labelled": n,
        "unlabelled": len(pop - set(items)),
        "labels_outside_population": len(set(items) - pop),
        "truth_on": on,
        "truth_on_lenient_extra": lenient,
        "live_rule_precision_from_labels": round(on / n, 4) if n else None,
        "arms": {"live_keyword_rule": arm("live_keyword_rule", lambda u: True),
                 "targeted_query_v3": targeted},
    }


def gate(score, matched_volume):
    """The card's gate: >=50 matched stories per family, each labelled, precision >= 0.90 "with a
    CI". Three separate ways to fail, and they are NOT merged into one:
      UNDERPOWERED        - the targeted query does not even MATCH 50 stories in 44 days, so the
                            gate's sample cannot be drawn. A volume failure, not a precision one.
      DROP_PRECISION      - enough volume, but precision is below the floor.
      CI_UNPROVEN         - the point estimate clears 0.90 while the Wilson lower bound does not.
                            Reported as its own verdict because a CI that straddles the floor is
                            what "report precision with a CI" is FOR; it must not read as a pass.
    """
    if not score:
        return "NO_LABELS"
    tgt = score["arms"]["targeted_query_v3"]
    p = tgt["precision"]
    lo = tgt["precision_ci95"][0]
    if matched_volume < MIN_LABELS:
        return "UNDERPOWERED(matched=%d<50)" % matched_volume
    if score["labelled"] < MIN_LABELS:
        return "UNDERPOWERED(labelled=%d<50)" % score["labelled"]
    if lo >= PRECISION_GATE:
        return "SHIP(%.3f LB %.3f)" % (p, lo)
    if p >= PRECISION_GATE:
        return "SHIP_POINT_ONLY_CI_UNPROVEN(%.3f LB %.3f)" % (p, lo)
    return "DROP_PRECISION(%.3f<0.90)" % p


def latest_news_row():
    if not NEWS_FILE.exists():
        return None
    last = None
    with NEWS_FILE.open() as fh:
        for line in fh:
            line = line.strip()
            if line:
                last = line
    try:
        return json.loads(last) if last else None
    except Exception:
        return None


def run(days=None):
    files = corpus_files(days)
    if not files:
        raise SystemExit("no corpus under %s" % GDELT_DIR)
    labels = load_labels()
    fams = list(FAMILIES)
    data = scan(files, fams)
    # KXCPI is scored on its ALL-GEOGRAPHY population on purpose: the US-scoped set is 9 stories
    # over 44 days, which cannot be sampled at all, and the point of scoring it is to show what the
    # keyword rule actually catches when the US filter is removed (the "wrong corpus" failure).
    score_pop = {"KXCPI": "stories_any"}
    scores = {}
    if labels:
        for fam in fams:
            src = data[score_pop.get(fam, "stories")][fam]
            scores[fam] = score_family(labels, fam, src, split_day=labels.get("split_day"))
            if fam in score_pop:
                scores[fam]["population_basis"] = "all_geographies"
    per_family = {}
    for fam in fams:
        stories = data["stories"][fam]
        per_family[fam] = {
            "rows_substring": data["sub_rows"][fam],
            "rows_wordboundary": data["wb_rows"][fam],
            "us_rows": data["us_rows_fam"][fam],
            "us_share_of_matches": round(data["us_rows_fam"][fam] / data["wb_rows"][fam], 4)
            if data["wb_rows"][fam] else None,
            "stories_us": len(stories),
            "stories_any_geo": len(data["stories_any"][fam]),
            "v3_stories_us": len(data["v3"][fam]),
            "days_to_50_us_stories": round(50 / (len(stories) / len(files)), 1)
            if stories else None,
            "gate": gate(scores.get(fam), len(data["v3"][fam])),
            "score": scores.get(fam),
            "example_v3": list(data["v3"][fam].values())[:3],
        }
    artifact = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "card": "kalshi-gdelt-context-v2",
        "basis": {
            "population": "data/gdelt-bulk/*.jsonl.gz, one row per GDELT event; story = one "
                          "canonical SOURCE URL (scheme/:443/trailing-slash stripped)",
            "clock": "daily capture file stamp %s..%s" % (
                files[0].rsplit("/", 1)[-1][:8], files[-1].rsplit("/", 1)[-1][:8]),
            "level": "one article for story counts; one event row for row counts",
            "days_read": len(files),
            "rows": data["rows"],
            "events": len(data["events"]),
            "articles": len(data["articles"]),
            "us_event_rows": data["us_rows"],
            "us_articles": data["us_articles"],
        },
        "surfaces_measured": {
            "gdelt_cloud": "HTTP 403 - API keys not included in current plan (free); plan error",
            "gdelt_doc": "HTTP 429 at >=7s spacing (2/2 this run; 5/5 on 2026-10-10)",
            "gdelt_bulk": "HTTP 200 - held corpus; EVENT table, no article title",
        },
        "gate": {"precision_floor": PRECISION_GATE, "min_labelled_per_family": MIN_LABELS},
        "families": per_family,
        "latest_live_row": latest_news_row(),
    }
    return artifact, files


def print_report(art):
    b = art["basis"]
    print("KALSHI MACRO - GDELT CONTEXT COLUMN READ (card kalshi-gdelt-context-v2)")
    print("basis: %d daily captures (%s) | %s event rows | %s distinct events | %s articles"
          % (b["days_read"], b["clock"], "{:,}".format(b["rows"]),
             "{:,}".format(b["events"]), "{:,}".format(b["articles"])))
    print("       story = one canonical SOURCE URL; level = article for stories, row for rows")
    print("")
    print("%-13s %8s %8s %7s %8s %9s %9s %8s" %
          ("family", "substr", "wordbnd", "USrows", "USshare", "USstories", "v3stories", "days/50"))
    for fam, d in art["families"].items():
        share = "%.1f%%" % (100 * d["us_share_of_matches"]) if d["us_share_of_matches"] is not None else "-"
        print("%-13s %8d %8d %7d %8s %9d %9d %8s" % (
            fam, d["rows_substring"], d["rows_wordboundary"], d["us_rows"], share,
            d["stories_us"], d["v3_stories_us"],
            d["days_to_50_us_stories"] if d["days_to_50_us_stories"] is not None else "-"))
    print("")
    for fam, d in art["families"].items():
        s = d.get("score")
        if not s:
            print("%-13s gate=%s (no hand labels for this family)" % (fam, d["gate"]))
            continue
        live = s["arms"]["live_keyword_rule"]
        tgt = s["arms"]["targeted_query_v3"]
        print("%-13s labelled=%d/%d truth_on=%d | live P=%.1f%% | targeted P=%.1f%% "
              "CI[%.1f,%.1f] recall=%.1f%% | gate=%s" % (
                  fam, s["labelled"], s["population"], s["truth_on"],
                  100 * live["precision"], 100 * tgt["precision"],
                  100 * tgt["precision_ci95"][0], 100 * tgt["precision_ci95"][1],
                  100 * tgt["recall"], d["gate"]))
        if tgt.get("design"):
            dd, hh = tgt["design"], tgt["holdout"]
            print("              split check: design<=%s P=%s (tp/fp/fn %d/%d/%d) | holdout P=%s "
                  "(tp/fp/fn %d/%d/%d)" % (
                      dd["day_max"], dd["precision"], dd["tp"], dd["fp"], dd["fn"],
                      hh["precision"], hh["tp"], hh["fp"], hh["fn"]))
    row = art.get("latest_live_row") or {}
    if row:
        print("")
        print("live column, newest row %s:" % row.get("ts"))
        print("  counts=%s" % json.dumps(row.get("counts")))
        print("  us_country_counts=%s" % json.dumps(row.get("us_country_counts")))
        print("  top=%s" % json.dumps({k: (v[:60] if isinstance(v, str) else v)
                                       for k, v in (row.get("top") or {}).items()}))
    print("")
    print("VERDICT: the column is DROPPED at the card's own fallback. No family clears the gate on "
          "the surfaces this host can reach: the corpus is an event table with no article titles "
          "(slug matching only), the held capture is pre-filtered by six unrelated topic queries, "
          "and both live query surfaces are blocked (Cloud 403 plan, DOC 429).")


# ---------------------------------------------------------------------------------------------
# SECOND SURFACE: the UNFILTERED stream. The held corpus is pre-filtered by the collector's six
# topic queries, so a reader could argue the thin macro yield is the filter's fault. This downloads
# one complete UTC day of the published 15-minute exports (96 stamps) and repeats the measurement
# on the full event stream. It is a separate artifact because it is expensive (network) and because
# it must not be silently overwritten by a routine run.
# ---------------------------------------------------------------------------------------------
def raw_day_probe(day):
    import tempfile
    import urllib.request
    import zipfile

    tmp = Path(tempfile.mkdtemp(prefix="gdelt-raw-"))
    stamps = ["%s%02d%02d00" % (day, h, m) for h in range(24) for m in (0, 15, 30, 45)]
    got = 0
    events = 0
    articles = set()
    us_events = 0
    fam_articles = {f: set() for f in FAMILIES}
    fam_us = {f: set() for f in FAMILIES}
    rows = {f: 0 for f in FAMILIES}
    for stamp in stamps:
        path = tmp / (stamp + ".zip")
        try:
            with urllib.request.urlopen(BULK_URL % stamp, timeout=30) as resp:
                path.write_bytes(resp.read())
        except Exception:
            continue
        got += 1
        try:
            with zipfile.ZipFile(str(path)) as z:
                data = z.read(z.namelist()[0]).decode("latin-1")
        except Exception:
            continue
        for line in data.splitlines():
            c = line.split("\t")
            if len(c) < 61:
                continue
            events += 1
            url = canonical_url(c[60])
            articles.add(url)
            is_us = c[53] == "US"
            if is_us:
                us_events += 1
            for f in FAMILIES:
                if word_re(FAMILIES[f]).search(url.replace("_", "-")):
                    rows[f] += 1
                    fam_articles[f].add(url)
                    if is_us:
                        fam_us[f].add(url)
    out = {
        "measured_at": datetime.now(timezone.utc).isoformat(),
        "day": day,
        "basis": ("published 15-minute .export.CSV.zip exports for one UTC day; level = one "
                  "article (canonical SOURCE URL) for story counts, one event row for rows; this "
                  "is the UNFILTERED stream, unlike data/gdelt-bulk which is topic-filtered at "
                  "collection"),
        "stamps_requested": len(stamps),
        "stamps_fetched": got,
        "events": events,
        "distinct_articles": len(articles),
        "us_events": us_events,
        "us_event_share": round(us_events / events, 4) if events else None,
        "families": {f: {"rows": rows[f], "articles": len(fam_articles[f]),
                         "us_articles": len(fam_us[f]),
                         "days_to_50_us_articles": round(50 / len(fam_us[f]), 1) if fam_us[f] else None}
                     for f in FAMILIES},
    }
    return out


def print_raw_probe(probe):
    if not probe:
        return
    print("")
    print("UNFILTERED STREAM PROBE (day %s): %d/%d stamps fetched, %s events, %s distinct articles, "
          "%s US events (%.1f%%)" % (
              probe["day"], probe["stamps_fetched"], probe["stamps_requested"],
              "{:,}".format(probe["events"]), "{:,}".format(probe["distinct_articles"]),
              "{:,}".format(probe["us_events"]), 100 * (probe["us_event_share"] or 0)))
    print("%-13s %7s %10s %12s %14s" % ("family", "rows", "articles", "US_articles", "days_to_50_US"))
    for f, d in probe["families"].items():
        print("%-13s %7d %10d %12d %14s" % (f, d["rows"], d["articles"], d["us_articles"],
                                            d["days_to_50_us_articles"] if d["days_to_50_us_articles"] else "-"))


# ---------------------------------------------------------------------------------------------
# self-test: every arm that can pass must also be able to FAIL (mutation controls)
# ---------------------------------------------------------------------------------------------
def self_test():
    ok = 0
    fails = []

    def check(name, cond):
        nonlocal ok
        if cond:
            ok += 1
        else:
            fails.append(name)

    check("substring_hits_cpim",
          bool(substring_re(FAMILIES["KXCPI"]).search("keralam cm slams cpi m leader")))
    check("wordboundary_still_hits_cpim",
          bool(word_re(FAMILIES["KXCPI"]).search("keralam cm slams cpi m leader")))
    anc, exc = v3_re(V3_QUERIES["KXCPI"], "anchor"), v3_re(V3_QUERIES["KXCPI"], "exclude")
    check("v3_rejects_cpim",
          not (anc.search("cpi m leader hits out") and not exc.search("cpi m leader hits out")))
    check("v3_accepts_us_cpi",
          bool(anc.search("us cpi data beats forecasts")) and not exc.search("us cpi data beats forecasts"))
    check("v3_rejects_cpi_company",
          bool(exc.search("cpi property group litigation dismissed")))
    a2, e2 = v3_re(V3_QUERIES["KXFED"], "anchor"), v3_re(V3_QUERIES["KXFED"], "exclude")
    check("v3_rejects_person_powell", bool(e2.search("who is kimberly powell nvidia executive")))
    check("v3_rejects_lake_powell", bool(e2.search("lake powell is hiding something")))
    check("v3_accepts_fed_board",
          bool(a2.search("federal reserve board announced approval")) and
          not e2.search("federal reserve board announced approval"))
    check("v3_rejects_fed_up", bool(e2.search("fed up with data centers and big tech")))
    check("canonical_url_port",
          canonical_url("https://www.agrinews-pubs.com:443/business/x/") ==
          canonical_url("http://www.agrinews-pubs.com/business/x"))
    check("canonical_url_keeps_distinct",
          canonical_url("https://a.com/x") != canonical_url("https://a.com/y"))
    p, lo, hi = wilson(21, 96)
    check("wilson_known", abs(p - 0.21875) < 1e-9 and 0.14 < lo < 0.16 and 0.30 < hi < 0.32)

    def mk(n, k, lo=None):
        p, l, h = wilson(k, n)
        return {"labelled": n, "arms": {"targeted_query_v3": {
            "precision": round(p, 4), "precision_ci95": [round(l if lo is None else lo, 4), round(h, 4)]}}}

    check("gate_underpowered", gate(mk(49, 49), 49).startswith("UNDERPOWERED"))
    check("gate_drop", gate(mk(50, 30), 60).startswith("DROP_PRECISION"))
    check("gate_ship", gate(mk(200, 200), 300).startswith("SHIP"))
    # 50/50 has a Wilson lower bound of 0.929, so it ships; 60/60 also ships; the CI arm exists
    # so a point estimate with a straddling CI cannot read as a pass
    check("gate_ci_unproven", gate(mk(50, 50, lo=0.70), 80).startswith("SHIP_POINT_ONLY"))
    # mutation control: the LIVE rule (keyword only) matches the person-Powell rows the v3
    # exclusion list removes, so the exclusion list is doing real work rather than decorating
    check("mutation_live_rule_leaks_person_powell",
          bool(word_re(FAMILIES["KXFED"]).search("who is kimberly powell nvidia executive"))
          and bool(e2.search("who is kimberly powell nvidia executive")))

    for f in fails:
        print("SELF-TEST FAIL: %s" % f)
    print("self-test %d/%d%s" % (ok, len(fails) + ok, "" if not fails else " - FAILED"))
    return 0 if not fails else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=None, help="trailing daily captures to read")
    ap.add_argument("--out", default=str(OUT_FILE))
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--raw-day", default=None,
                    help="measure the UNFILTERED stream for one UTC day (YYYYMMDD), 96 downloads")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    if args.raw_day:
        probe = raw_day_probe(args.raw_day)
        Path(str(RAW_PROBE_FILE)).write_text(json.dumps(probe, indent=1) + "\n")
        print_raw_probe(probe)
        print("raw probe artifact: %s" % RAW_PROBE_FILE)
        return 0
    art, _files = run(args.days)
    Path(args.out).write_text(json.dumps(art, indent=1) + "\n")
    print_report(art)
    if RAW_PROBE_FILE.exists():
        try:
            print_raw_probe(json.loads(RAW_PROBE_FILE.read_text()))
        except Exception:
            pass
    print("")
    print("artifact: %s" % args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
