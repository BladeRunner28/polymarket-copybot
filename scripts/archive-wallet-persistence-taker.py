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

t0 = time.time()
con = duckdb.connect()
con.sql("CREATE TABLE ourw AS SELECT DISTINCT lower(column0) AS addr FROM read_csv('/tmp/our_wallets.txt', header=false, all_varchar=true)")
con.sql("""
CREATE TABLE hit AS
SELECT lower(maker) m, lower(taker) t, token_asset_id asset, block_timestamp ts, price,
       maker_direction md, taker_direction td
FROM read_parquet('/Volumes/Storage/pm-data/polymarket-v1/OrderFilled/*.parquet')
WHERE lower(maker) IN (SELECT addr FROM ourw) OR lower(taker) IN (SELECT addr FROM ourw)
""")
con.sql("""
CREATE TABLE lab AS
SELECT asset_id, any_value(outcome_label) olab, any_value(winning_outcome_label) wlab
FROM read_parquet('/Volumes/Storage/pm-data/polymarket-v1/daily_aligned/*.parquet')
WHERE asset_id IN (SELECT DISTINCT asset FROM hit) GROUP BY 1
""")
# the copy-relevant side: the wallet is the TAKER and buys the token
con.sql("""
CREATE TABLE buys AS
SELECT h.t AS addr, h.ts, h.price, h.asset, CASE WHEN l.olab = l.wlab THEN 1 ELSE 0 END win
FROM hit h JOIN lab l ON l.asset_id = h.asset
WHERE h.td = 'BUY' AND h.t IN (SELECT addr FROM ourw) AND l.olab IS NOT NULL
""")
print(f"labelled taker-buys: {con.sql('SELECT COUNT(*) FROM buys').fetchone()[0]:,} ({time.time()-t0:.0f}s)", flush=True)

out = {"elapsed_s": None, "labelled_taker_buys": con.sql("SELECT COUNT(*) FROM buys").fetchone()[0],
       "overall_excess": con.sql("SELECT AVG(win)-AVG(price) FROM buys").fetchone()[0],
       "overall_winrate": con.sql("SELECT AVG(win) FROM buys").fetchone()[0],
       "overall_mean_price": con.sql("SELECT AVG(price) FROM buys").fetchone()[0]}

for tag, extra in (("all_prices", "1=1"), ("mid_prices_05_95", "price BETWEEN 0.05 AND 0.95")):
    con.sql(f"""
    CREATE OR REPLACE TABLE span AS
    SELECT addr, (MIN(ts)+MAX(ts))/2 tmid, COUNT(*) n FROM buys WHERE {extra} GROUP BY 1 HAVING COUNT(*) >= 400
    """)
    con.sql(f"""
    CREATE OR REPLACE TABLE halves AS
    SELECT addr, COUNT(*) n,
      AVG(win) FILTER (WHERE ts < tmid) - AVG(price) FILTER (WHERE ts < tmid) exc_a,
      COUNT(*) FILTER (WHERE ts < tmid) n_a,
      AVG(win) FILTER (WHERE ts >= tmid) - AVG(price) FILTER (WHERE ts >= tmid) exc_b,
      COUNT(*) FILTER (WHERE ts >= tmid) n_b
    FROM buys JOIN span USING (addr) WHERE {extra} GROUP BY 1
    """)
    con.sql("CREATE OR REPLACE TABLE paired AS SELECT * FROM halves WHERE n_a >= 200 AND n_b >= 200")
    n = con.sql("SELECT COUNT(*) FROM paired").fetchone()[0]
    out[f"wallets__{tag}"] = n
    if n:
        out[f"pearson__{tag}"] = con.sql("SELECT corr(exc_a, exc_b) FROM paired").fetchone()[0]
        out[f"spearman__{tag}"] = con.sql("""SELECT corr(r1,r2) FROM (
            SELECT rank() OVER (ORDER BY exc_a) r1, rank() OVER (ORDER BY exc_b) r2 FROM paired)""").fetchone()[0]
        out[f"quartiles__{tag}"] = con.sql("""
            WITH q AS (SELECT *, NTILE(4) OVER (ORDER BY exc_a) b FROM paired)
            SELECT b, COUNT(*) wallets, ROUND(AVG(exc_a)*100,2) excA_pct, ROUND(AVG(exc_b)*100,2) excB_pct,
                   ROUND(AVG(n_a+n_b),0) avg_fills FROM q GROUP BY 1 ORDER BY 1""").fetchall()
        out[f"deciles__{tag}"] = con.sql("""
            WITH q AS (SELECT *, NTILE(10) OVER (ORDER BY exc_a) d FROM paired)
            SELECT d, COUNT(*) wallets, ROUND(AVG(exc_a)*100,2) excA_pct, ROUND(AVG(exc_b)*100,2) excB_pct
            FROM q GROUP BY 1 ORDER BY 1""").fetchall()

# how MM-heavy is this population? (a wallet with 100k+ taker-buys is not a copy target)
out["taker_buy_volume_by_wallet_bucket"] = con.sql("""
SELECT CASE WHEN n >= 100000 THEN '100k+' WHEN n >= 10000 THEN '10k-100k' WHEN n >= 1000 THEN '1k-10k'
            WHEN n >= 100 THEN '100-1k' ELSE '<100' END bucket, COUNT(*) wallets, SUM(n) fills
FROM (SELECT addr, COUNT(*) n FROM buys GROUP BY 1) GROUP BY 1 ORDER BY 3 DESC""").fetchall()

out["elapsed_s"] = round(time.time() - t0, 1)
json.dump(out, open("/tmp/arch_persistence2.json", "w"), indent=1, default=str)
print(json.dumps(out, indent=1, default=str))
