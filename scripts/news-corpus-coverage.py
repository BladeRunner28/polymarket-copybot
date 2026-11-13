#!/usr/bin/env python3
"""news-corpus-coverage.py — read-only: can the REC 3 news corpora supply news for OUR book?

Lane A proposal instrument for roadmap card `ml-feed-news-corpus-structure`
(approval apr-ml-feed-news-corpus-structure, 2026-11-12). Writes nothing except
the JSON artefact named by --out; touches no DB table (immutable=1 read) and no
RuleSet. Every number quoted in drafts/news-corpus-asof-20261112.md comes from a
run of this file.

    .venv-ml/bin/python scripts/news-corpus-coverage.py --cache data/news-corpus-cache

Downloads (first run only, ~50 MB, cached): SuperAGI news texts (CC BY 4.0 file
only, window_a is deliberately NOT fetched), SuperAGI Window B benchmark tables,
dnakhla headline corpus.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
import urllib.request

import pandas as pd

HF = "https://huggingface.co/datasets"
HF_API = "https://huggingface.co/api/datasets"
EMPTY_SHA = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
SA_NEWS = "SuperAGI/llm-vs-prediction-markets-news"
SA_MAIN = "SuperAGI/llm-vs-prediction-markets"
DN = "dnakhla/us-news-headlines-enriched"

FILES = [
    (SA_NEWS, "texts.parquet", "sa_texts.parquet"),
    (SA_MAIN, "benchmark/window_b/market_moments.parquet", "wb_market_moments.parquet"),
    (SA_MAIN, "benchmark/window_b/moment_outcomes.parquet", "wb_moment_outcomes.parquet"),
    (SA_MAIN, "benchmark/window_b/news_articles.parquet", "wb_news_articles.parquet"),
    (DN, "data/train-00000-of-00001.parquet", "dn.parquet"),
]


def fetch(repo: str, path: str, dest: str) -> str:
    if os.path.exists(dest) and os.path.getsize(dest) > 0:
        return dest
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    url = "%s/%s/resolve/main/%s" % (HF, repo, path)
    sys.stderr.write("fetching %s -> %s\n" % (url, dest))
    with urllib.request.urlopen(url, timeout=300) as r, open(dest + ".part", "wb") as f:
        while True:
            chunk = r.read(1 << 20)
            if not chunk:
                break
            f.write(chunk)
    os.replace(dest + ".part", dest)
    return dest


def licence_card(repo: str) -> dict:
    with urllib.request.urlopen("%s/%s" % (HF_API, repo), timeout=60) as r:
        meta = json.load(r)
    return {
        "id": meta["id"],
        "sha": meta["sha"],
        "last_modified": meta.get("lastModified"),
        "licence_tags": [t for t in meta.get("tags", []) if t.startswith("license:")],
        "card_license": meta.get("cardData", {}).get("license"),
        "files": len(meta.get("siblings", [])),
    }


def decisions_gap(root: str) -> dict:
    df = pd.read_parquet(
        os.path.join(root, "data/ml/decisions.parquet"),
        columns=["decision_id", "decided_at", "market_id", "category_class", "acted_any"],
    )
    textish = [
        c
        for c in pd.read_parquet(os.path.join(root, "data/ml/decisions.parquet")).columns
        if re.search(r"text|headline|news|article|url|sha|checksum|capture|question|condition", c, re.I)
    ]
    toks = df["market_id"].map(lambda s: s.split("-")[0] if isinstance(s, str) else "(null)")
    qwords = {"will", "highest", "lowest", "which", "what", "how", "next", "second", "where", "of", "at", "by", "who", "when"}
    return {
        "rows": int(len(df)),
        "cols": 52,
        "text_or_join_columns_present": textish,
        "date_range": [str(df.decided_at.min()), str(df.decided_at.max())],
        "distinct_markets": int(df.market_id.nunique()),
        "acted_rows": int(df.acted_any.sum()),
        "category_class_non_null": int(df.category_class.notna().sum()),
        "category_class_non_null_acted": int(df[df.acted_any == 1].category_class.notna().sum()),
        "distinct_slug_prefixes": int(toks.nunique()),
        "slug_prefix_question_word_rows": int(toks.isin(qwords).sum()),
        "slug_prefix_top20_share": round(float(toks.value_counts().head(20).sum()) / len(df), 4),
    }


def db_reads(root: str) -> dict:
    db = "file:%s?mode=ro" % os.path.join(root, "prisma/dev.db")
    con = sqlite3.connect(db, uri=True, timeout=120)
    con.execute("PRAGMA query_only=1")
    con.execute("PRAGMA busy_timeout=120000")
    q = con.execute(
        "SELECT COUNT(*), SUM(conditionId IS NULL),"
        " datetime(MIN(CASE WHEN conditionId IS NOT NULL THEN timestamp END)/1000,'unixepoch')"
        " FROM ObservedTrade"
    ).fetchone()
    lo, hi = 1784073600000, 1786320000000  # 2026-07-15 .. 2026-08-10 UTC (Window B span)
    n_win, n_cond = con.execute(
        "SELECT COUNT(*), COUNT(DISTINCT conditionId) FROM ObservedTrade"
        " WHERE timestamp >= ? AND timestamp < ?", (lo, hi)
    ).fetchone()
    conds = [r[0] for r in con.execute(
        "SELECT DISTINCT conditionId FROM ObservedTrade"
        " WHERE timestamp >= ? AND timestamp < ? AND conditionId IS NOT NULL", (lo, hi)
    )]
    sig = con.execute(
        "SELECT COUNT(*), datetime(MIN(processedAt)/1000,'unixepoch'),"
        " datetime(MAX(processedAt)/1000,'unixepoch') FROM RegulatorySignal"
    ).fetchone()
    by_source = dict(con.execute("SELECT source, COUNT(*) FROM RegulatorySignal GROUP BY source").fetchall())
    con.close()
    return {
        "observed_trade_rows": int(q[0]),
        "observed_trade_null_condition_id": int(q[1] or 0),
        "condition_id_first_ts": q[2],
        "window_b_span_rows": int(n_win),
        "window_b_span_distinct_condition_ids": int(n_cond),
        "window_b_span_condition_ids": conds,
        "regulatory_signal_rows": int(sig[0]),
        "regulatory_signal_first": sig[1],
        "regulatory_signal_last": sig[2],
        "regulatory_signal_by_source": by_source,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=os.path.expanduser("~/polymarket-copybot"))
    ap.add_argument("--cache", default=None)
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    root = a.root
    cache = a.cache or os.path.join(root, "data/news-corpus-cache")
    out = a.out or os.path.join(root, "data/news-corpus-coverage-20261112.json")

    paths = {dest: fetch(repo, path, os.path.join(cache, dest)) for repo, path, dest in FILES}

    res = {"cards": {}, "sa_texts": {}, "window_b": {}, "dnakhla": {}, "our_book": {}}
    for repo in (SA_NEWS, SA_MAIN, DN):
        res["cards"][repo.split("/")[-1]] = licence_card(repo)

    # --- SuperAGI news texts (CC BY 4.0 file only) ---
    t = pd.read_parquet(paths["sa_texts.parquet"])
    w = t["words"].dropna().sort_values().reset_index(drop=True)
    res["sa_texts"] = {
        "rows": int(len(t)),
        "kind_counts": {k: int(v) for k, v in t["kind"].value_counts().items()},
        "distinct_sha256": int(t["sha256"].nunique()),
        "words_median": int(w.iloc[len(w) // 2]),
        "words_p90": int(w.iloc[int(len(w) * 0.9)]),
        "redacted_rows": int(t["redacted"].sum()),
        "columns": list(t.columns),
        "window_a_fetched": False,
    }

    # --- Window B (Polymarket, CC BY 4.0) ---
    mm = pd.read_parquet(paths["wb_market_moments.parquet"])
    na = pd.read_parquet(paths["wb_news_articles.parquet"])
    nz = mm["news_text_words"].fillna(0) > 0
    res["window_b"] = {
        "market_moments": int(len(mm)),
        "distinct_markets": int(mm["venue_market_id"].nunique()),
        "forecast_range": [str(mm["forecast_ts"].min()), str(mm["forecast_ts"].max())],
        "moments_with_news": int(nz.sum()),
        "news_share": round(float(nz.mean()), 4),
        "empty_sha_sentinel_rows": int((mm["news_text_sha256"] == EMPTY_SHA).sum()),
        "empty_sha_is_empty_string_hash": True,
        "article_count_dist": {int(k): int(v) for k, v in mm["news_article_count"].fillna(-1).astype(int).value_counts().items()},
        "news_articles_rows": int(len(na)),
        "news_articles_distinct_urls": int(na["url"].nunique()),
        "news_capture_range": [str(na["capture_ts"].min()), str(na["capture_ts"].max())],
        "ladder_share": round(float(mm["is_ladder"].mean()), 4),
    }

    # --- our book vs Window B ---
    book = db_reads(root)
    ours = set(book.pop("window_b_span_condition_ids"))
    theirs = set(mm["venue_market_id"])
    inter = ours & theirs
    sub = mm[mm["venue_market_id"].isin(inter)]
    withnews = sub["news_text_words"].fillna(0) > 0
    book.update(
        {
            "overlap_markets": len(inter),
            "overlap_share_of_our_markets": round(len(inter) / max(1, len(ours)), 4),
            "overlap_moments": int(len(sub)),
            "overlap_moments_with_news": int(withnews.sum()),
            "overlap_share_with_news": round(float(withnews.mean()) if len(sub) else 0.0, 4),
            "overlap_share_of_span_book": round(len(inter) / max(1, len(ours)), 4),
        }
    )
    book["decisions"] = decisions_gap(root)
    sf = os.path.join(root, "data/sentiment-features.csv")
    if os.path.exists(sf):
        s = pd.read_csv(sf, usecols=["trade_id", "has_sentiment"])
        book["sentiment_export"] = {
            "rows": int(len(s)),
            "has_sentiment_true": int(s.has_sentiment.fillna(0).sum()),
            "has_sentiment_share": round(float(s.has_sentiment.fillna(0).mean()), 4),
            "note": "the only as-of text-derived feature in the export today",
        }
    res["our_book"] = book

    # --- dnakhla ---
    dn = pd.read_parquet(paths["dn.parquet"], columns=["date", "datetime", "era", "collected_at", "outlet"])
    d = pd.to_datetime(dn["datetime"], errors="coerce", utc=True)
    lo, hi = pd.Timestamp("2026-07-14", tz="UTC"), pd.Timestamp("2026-10-20", tz="UTC")
    c = pd.to_datetime(dn["collected_at"], errors="coerce", utc=True)
    res["dnakhla"] = {
        "rows": int(len(dn)),
        "date_range": [str(dn["date"].min()), str(dn["date"].max())],
        "era": {k: int(v) for k, v in dn["era"].value_counts().items()},
        "outlets": int(dn["outlet"].nunique()),
        "datetime_null": int(d.isna().sum()),
        "datetime_null_share": round(float(d.isna().mean()), 4),
        "rows_inside_our_decision_window": int(((d >= lo) & (d < hi)).sum()),
        "collected_at_range": [str(c.min()), str(c.max())],
        "collected_at_is_single_bulk_snapshot": bool((c.max() - c.min()).days <= 3) if c.notna().any() else None,
    }

    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w") as f:
        json.dump(res, f, indent=2, default=str)
    print(json.dumps(res, indent=2, default=str))
    sys.stderr.write("wrote %s\n" % out)


if __name__ == "__main__":
    main()
