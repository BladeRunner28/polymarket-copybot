#!/usr/bin/env python3
# NOTE: wallet/token lists for the duckdb joins are built from the live DB at import time when absent.
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from archive_lists import build_lists  # noqa: E402

build_lists()

import glob
import json

import duckdb

con = duckdb.connect()
DA = sorted(glob.glob("/Volumes/Storage/pm-data/polymarket-v1/daily_aligned/*.parquet"))
sample = [DA[0], DA[len(DA) // 2], DA[-1]]
out = {"sampled_files": [f.split("/")[-1] for f in sample]}

q = con.sql(f"""
SELECT COUNT(*) AS nrows,
       COUNT(DISTINCT condition_id) markets,
       SUM(CASE WHEN winning_outcome_label IS NOT NULL THEN 1 ELSE 0 END) with_win_label,
       SUM(CASE WHEN resolution_status IS NOT NULL THEN 1 ELSE 0 END) with_status,
       SUM(CASE WHEN p_event IS NOT NULL THEN 1 ELSE 0 END) with_p_event,
       COUNT(DISTINCT category_refined) categories,
       MIN(opens_at) opens_min, MAX(resolved_at) resolved_max
FROM read_parquet({sample!r})
""").fetchone()
out["sampled_daily_aligned"] = dict(zip(
    ["rows", "markets", "with_win_label", "with_status", "with_p_event", "categories", "opens_min", "resolved_max"], q))

out["categories_top"] = con.sql(f"""
SELECT category_refined, COUNT(DISTINCT condition_id) mkts
FROM read_parquet({sample!r}) GROUP BY 1 ORDER BY 2 DESC LIMIT 12""").fetchall()

B = sorted(glob.glob("/Volumes/Storage/pm-data/quant-bench/polymarket/bars_hourly/*.parquet"))
bs = [B[0], B[len(B) // 2], B[-1]]
out["bars_hourly_sample"] = con.sql(f"""
SELECT COUNT(*) bars, COUNT(DISTINCT token_id) tokens, MIN(period_start) t0, MAX(period_end) t1,
       ROUND(AVG(n_trades),1) avg_trades, ROUND(MEDIAN(volume_usd),1) median_vol
FROM read_parquet({bs!r})""").fetchone()

M = glob.glob("/Volumes/Storage/pm-data/quant-bench/polymarket/markets/*.parquet")
con.sql(f"CREATE TABLE qbm AS SELECT * FROM read_parquet({M!r})")
out["qb_markets_cols"] = [r[0] for r in con.sql("DESCRIBE qbm").fetchall()]
out["qb_markets_n"] = con.sql("SELECT COUNT(*) FROM qbm").fetchone()[0]
out["qb_markets_resolved"] = con.sql("""
SELECT COUNT(*) total,
       SUM(CASE WHEN lower(coalesce(CAST(closed AS VARCHAR),'')) IN ('true','1') THEN 1 ELSE 0 END) closed_flag
FROM qbm""").fetchone()

print(json.dumps(out, indent=1, default=str))
json.dump(out, open("/tmp/arch_labels.json", "w"), indent=1, default=str)
