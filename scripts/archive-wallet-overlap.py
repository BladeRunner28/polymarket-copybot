#!/usr/bin/env python3
# NOTE: wallet/token lists for the duckdb joins are built from the live DB at import time when absent.
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from archive_lists import build_lists  # noqa: E402

build_lists()

import json
import time

import duckdb

F = "/Volumes/Storage/pm-data/polymarket-v1/OrderFilled/*.parquet"
con = duckdb.connect()
t0 = time.time()

con.sql("CREATE TABLE ourw AS SELECT DISTINCT lower(column0) AS addr FROM read_csv('/tmp/our_wallets.txt', header=false, all_varchar=true)")
con.sql("CREATE TABLE copyw AS SELECT DISTINCT lower(column0) AS addr FROM read_csv('/tmp/copied_wallets.txt', header=false, all_varchar=true)")
con.sql("CREATE TABLE ours AS SELECT DISTINCT lower(column0) AS asset FROM read_csv('/tmp/our_assets.txt', header=false, all_varchar=true)")
print("build side:", con.sql("SELECT (SELECT COUNT(*) FROM ourw) w, (SELECT COUNT(*) FROM copyw) c, (SELECT COUNT(*) FROM ours) a").fetchall(), flush=True)

con.sql(f"""
CREATE TABLE hit AS
SELECT lower(f.maker) AS maker_l, lower(f.taker) AS taker_l, f.token_asset_id AS asset,
       f.block_timestamp AS ts, f.price AS price, f.usdc_amount AS usdc, f.fee_usdc AS fee,
       f.maker_direction AS md, f.taker_direction AS td
FROM read_parquet('{F}') f
WHERE lower(f.maker) IN (SELECT addr FROM ourw)
   OR lower(f.taker) IN (SELECT addr FROM ourw)
   OR lower(f.token_asset_id) IN (SELECT asset FROM ours)
""")
print(f"hit table built in {time.time() - t0:.0f}s", flush=True)

out = {}
out["our_wallets"] = con.sql("SELECT COUNT(*) FROM ourw").fetchone()[0]
out["copied_wallets"] = con.sql("SELECT COUNT(*) FROM copyw").fetchone()[0]
out["our_assets"] = con.sql("SELECT COUNT(*) FROM ours").fetchone()[0]

out["hit_fills"] = con.sql("SELECT COUNT(*) FROM hit").fetchone()[0]
out["wallets_with_history"] = con.sql("""
  SELECT COUNT(DISTINCT a) FROM (
    SELECT maker_l a FROM hit WHERE maker_l IN (SELECT addr FROM ourw)
    UNION SELECT taker_l FROM hit WHERE taker_l IN (SELECT addr FROM ourw))""").fetchone()[0]
out["copied_wallets_with_history"] = con.sql("""
  SELECT COUNT(DISTINCT a) FROM (
    SELECT maker_l a FROM hit WHERE maker_l IN (SELECT addr FROM copyw)
    UNION SELECT taker_l FROM hit WHERE taker_l IN (SELECT addr FROM copyw))""").fetchone()[0]
out["our_tokens_seen"] = con.sql("SELECT COUNT(DISTINCT asset) FROM hit WHERE asset IN (SELECT asset FROM ours)").fetchone()[0]
out["price_range"] = con.sql("SELECT MIN(price), MAX(price) FROM hit WHERE asset IN (SELECT asset FROM ours)").fetchone()
out["span"] = con.sql("SELECT MIN(ts), MAX(ts) FROM hit").fetchone()

# per-wallet fill counts (the feature substrate): how much history per wallet?
con.sql(f"""CREATE TABLE wc AS
SELECT a AS addr, COUNT(*) fills, MIN(ts) first_ts, MAX(ts) last_ts, SUM(usdc) usdc, SUM(fee) fee
FROM (SELECT maker_l a, ts, usdc, fee FROM hit WHERE maker_l IN (SELECT addr FROM ourw)
      UNION ALL SELECT taker_l, ts, usdc, fee FROM hit WHERE taker_l IN (SELECT addr FROM ourw))
GROUP BY 1""")
out["per_wallet"] = con.sql("""SELECT COUNT(*) n,
   ROUND(MEDIAN(fills),0) median_fills, ROUND(AVG(fills),0) mean_fills, MAX(fills) max_fills,
   ROUND(AVG(usdc),0) mean_usdc, ROUND(AVG(fee),2) mean_fee
   FROM wc""").fetchone()
out["per_wallet_top10"] = con.sql("SELECT addr, fills, ROUND(usdc,0) usdc FROM wc ORDER BY fills DESC LIMIT 10").fetchall()
out["per_wallet_buckets"] = con.sql("""SELECT CASE WHEN fills>=10000 THEN '10k+' WHEN fills>=1000 THEN '1k-10k'
   WHEN fills>=100 THEN '100-1k' WHEN fills>=10 THEN '10-100' ELSE '<10' END bucket,
   COUNT(*) wallets FROM wc GROUP BY 1 ORDER BY 2 DESC""").fetchall()
out["elapsed_s"] = round(time.time() - t0, 1)

json.dump(out, open("/tmp/arch_overlap.json", "w"), indent=1, default=str)
print(json.dumps(out, indent=1, default=str))
