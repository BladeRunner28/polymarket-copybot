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
con.sql("CREATE TABLE ours AS SELECT DISTINCT lower(column0) AS asset FROM read_csv('/tmp/our_assets.txt', header=false, all_varchar=true)")

# 1. our fills from the archive (same pass as arch_overlap.py)
con.sql("""
CREATE TABLE hit AS
SELECT lower(maker) m, lower(taker) t, token_asset_id asset, block_timestamp ts, price,
       maker_direction md, taker_direction td, usdc_amount usdc
FROM read_parquet('/Volumes/Storage/pm-data/polymarket-v1/OrderFilled/*.parquet')
WHERE lower(maker) IN (SELECT addr FROM ourw) OR lower(taker) IN (SELECT addr FROM ourw)
""")
print(f"our fills: {con.sql('SELECT COUNT(*) FROM hit').fetchone()[0]:,} ({time.time()-t0:.0f}s)", flush=True)

# 2. label dim, restricted to the assets those fills touch (keeps the daily_aligned scan small)
con.sql("""
CREATE TABLE lab AS
SELECT asset_id, any_value(condition_id) cond, any_value(outcome_label) olab,
       any_value(winning_outcome_label) wlab, any_value(category_refined) cat,
       COUNT(*) n_rows
FROM read_parquet('/Volumes/Storage/pm-data/polymarket-v1/daily_aligned/*.parquet')
WHERE asset_id IN (SELECT DISTINCT asset FROM hit)
GROUP BY 1
""")
print(f"labelled assets: {con.sql('SELECT COUNT(*) FROM lab').fetchone()[0]:,} ({time.time()-t0:.0f}s)", flush=True)

# 3. the wallet's BUY side, labelled
con.sql("""
CREATE TABLE buys AS
SELECT addr, ts, price, asset, win, cat FROM (
  SELECT h.m AS addr, h.ts, h.price, h.asset,
         CASE WHEN l.olab = l.wlab THEN 1 ELSE 0 END win, l.cat
  FROM hit h JOIN lab l ON l.asset_id = h.asset
  WHERE h.md = 'BUY' AND h.m IN (SELECT addr FROM ourw)
  UNION ALL
  SELECT h.t, h.ts, h.price, h.asset,
         CASE WHEN l.olab = l.wlab THEN 1 ELSE 0 END win, l.cat
  FROM hit h JOIN lab l ON l.asset_id = h.asset
  WHERE h.td = 'BUY' AND h.t IN (SELECT addr FROM ourw)
)
WHERE cat IS NOT NULL
""")
print(f"labelled buys: {con.sql('SELECT COUNT(*) FROM buys').fetchone()[0]:,} ({time.time()-t0:.0f}s)", flush=True)

con.sql("""
CREATE TABLE wspan AS
SELECT addr, MIN(ts) t0, MAX(ts) t1, (MIN(ts)+MAX(ts))/2 tmid, COUNT(*) n,
       MEDIAN(price) med_price, AVG(win) wr, AVG(win) - AVG(price) excess
FROM buys GROUP BY 1 HAVING COUNT(*) >= 400
""")
print("wallets with >=400 labelled buys:", con.sql("SELECT COUNT(*) FROM wspan").fetchone()[0], flush=True)

con.sql("""
CREATE TABLE halves AS
SELECT addr,
  AVG(win) FILTER (WHERE ts < tmid) - AVG(price) FILTER (WHERE ts < tmid) exc_a,
  COUNT(*) FILTER (WHERE ts < tmid) n_a,
  AVG(win) FILTER (WHERE ts >= tmid) - AVG(price) FILTER (WHERE ts >= tmid) exc_b,
  COUNT(*) FILTER (WHERE ts >= tmid) n_b
FROM buys JOIN wspan USING (addr) GROUP BY 1
""")
con.sql("CREATE TABLE paired AS SELECT * FROM halves WHERE n_a >= 200 AND n_b >= 200")
# MM/protocol wallets (hundreds of thousands of fills, $100M+ notional) are not copy targets and would
# dominate any aggregate; the persistence read is reported with and without them.
con.sql("""CREATE TABLE paired_nomm AS
SELECT p.* FROM paired p JOIN wspan w USING (addr) WHERE w.n <= 50000""")

out = {}
out["elapsed_s"] = round(time.time() - t0, 1)
out["our_fills_in_archive"] = con.sql("SELECT COUNT(*) FROM hit").fetchone()[0]
out["labelled_assets"] = con.sql("SELECT COUNT(*) FROM lab").fetchone()[0]
out["labelled_buys"] = con.sql("SELECT COUNT(*) FROM buys").fetchone()[0]
out["wallets_ge400"] = con.sql("SELECT COUNT(*) FROM wspan").fetchone()[0]
out["wallets_paired_200_200"] = con.sql("SELECT COUNT(*) FROM paired").fetchone()[0]
out["wallets_paired_nomm"] = con.sql("SELECT COUNT(*) FROM paired_nomm").fetchone()[0]
out["overall_excess"] = con.sql("SELECT AVG(win) - AVG(price) FROM buys").fetchone()[0]
out["overall_winrate"] = con.sql("SELECT AVG(win) FROM buys").fetchone()[0]
out["overall_mean_price"] = con.sql("SELECT AVG(price) FROM buys").fetchone()[0]

for tag, tbl in (("all", "paired"), ("no_mm", "paired_nomm")):
    out[f"pearson_half_vs_half__{tag}"] = con.sql(f"SELECT corr(exc_a, exc_b) FROM {tbl}").fetchone()[0]
    out[f"spearman_half_vs_half__{tag}"] = con.sql(
        f"""SELECT corr(r1, r2) FROM (
              SELECT rank() OVER (ORDER BY exc_a) r1, rank() OVER (ORDER BY exc_b) r2 FROM {tbl})"""
    ).fetchone()[0]
    out[f"quartile_table__{tag}"] = con.sql(f"""
        WITH q AS (SELECT *, NTILE(4) OVER (ORDER BY exc_a) bucket FROM {tbl})
        SELECT bucket, COUNT(*) wallets, ROUND(AVG(n_a+n_b),0) avg_fills,
               ROUND(AVG(exc_a)*100,2) excessA_pct, ROUND(AVG(exc_b)*100,2) excessB_pct
        FROM q GROUP BY 1 ORDER BY 1""").fetchall()
    out[f"decile_table__{tag}"] = con.sql(f"""
        WITH q AS (SELECT *, NTILE(10) OVER (ORDER BY exc_a) d FROM {tbl})
        SELECT d, COUNT(*) wallets, ROUND(AVG(exc_a)*100,2) excA_pct, ROUND(AVG(exc_b)*100,2) excB_pct
        FROM q GROUP BY 1 ORDER BY 1""").fetchall()

json.dump(out, open("/tmp/arch_persistence.json", "w"), indent=1, default=str)
print(json.dumps(out, indent=1, default=str))
