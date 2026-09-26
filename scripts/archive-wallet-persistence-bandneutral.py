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
SELECT lower(maker) m, lower(taker) t, token_asset_id asset, block_timestamp ts, price, taker_direction td
FROM read_parquet('/Volumes/Storage/pm-data/polymarket-v1/OrderFilled/*.parquet')
WHERE lower(maker) IN (SELECT addr FROM ourw) OR lower(taker) IN (SELECT addr FROM ourw)
""")
con.sql("""
CREATE TABLE lab AS
SELECT asset_id, any_value(outcome_label) olab, any_value(winning_outcome_label) wlab
FROM read_parquet('/Volumes/Storage/pm-data/polymarket-v1/daily_aligned/*.parquet')
WHERE asset_id IN (SELECT DISTINCT asset FROM hit) GROUP BY 1
""")
con.sql("""
CREATE TABLE f AS
SELECT h.t AS addr, h.ts, h.price, CASE WHEN l.olab = l.wlab THEN 1 ELSE 0 END win,
       CAST(FLOOR(h.price * 10) AS INT) band
FROM hit h JOIN lab l ON l.asset_id = h.asset
WHERE h.td = 'BUY' AND h.t IN (SELECT addr FROM ourw) AND l.olab IS NOT NULL
  AND h.price BETWEEN 0.05 AND 0.95
""")
out = {"fills": con.sql("SELECT COUNT(*) FROM f").fetchone()[0]}
out["band_table"] = con.sql("""
SELECT band/10.0 || '-' || (band+1)/10.0 AS price_band, COUNT(*) fills,
       ROUND(AVG(win),4) win_rate, ROUND(AVG(win - price),4) raw_excess
FROM f GROUP BY 1 ORDER BY 1""").fetchall()
con.sql("CREATE TABLE bandwr AS SELECT band, AVG(win) bwr FROM f GROUP BY 1")
# NOTE the trap found here: residualising BOTH win and price by the same per-band constant cancels in
# (win - price) and is a no-op. The band-neutral skill metric has to be win measured against the band's
# own realised frequency: skill = win - bwr(band).
con.sql("""
CREATE TABLE resid AS
SELECT f.addr, f.ts, f.price, f.win, f.band, f.win - b.bwr AS skill
FROM f JOIN bandwr b USING (band)
""")
print("skill defined as win - band_winrate; now persistence", flush=True)

con.sql("""
CREATE TABLE span AS SELECT addr, (MIN(ts)+MAX(ts))/2 tmid, COUNT(*) n FROM resid GROUP BY 1 HAVING COUNT(*) >= 400
""")
con.sql("""
CREATE TABLE halves AS
SELECT addr, COUNT(*) n,
  AVG(skill) FILTER (WHERE ts <  tmid) exc_a,
  COUNT(*)   FILTER (WHERE ts <  tmid) n_a,
  AVG(skill) FILTER (WHERE ts >= tmid) exc_b,
  COUNT(*)   FILTER (WHERE ts >= tmid) n_b
FROM resid JOIN span USING (addr) GROUP BY 1
""")
con.sql("CREATE TABLE paired AS SELECT * FROM halves WHERE n_a >= 200 AND n_b >= 200")
out["wallets_paired"] = con.sql("SELECT COUNT(*) FROM paired").fetchone()[0]
out["pearson_resid"] = con.sql("SELECT corr(exc_a, exc_b) FROM paired").fetchone()[0]
out["spearman_resid"] = con.sql("""SELECT corr(r1,r2) FROM (
   SELECT rank() OVER (ORDER BY exc_a) r1, rank() OVER (ORDER BY exc_b) r2 FROM paired)""").fetchone()[0]
out["quartiles_resid"] = con.sql("""
WITH q AS (SELECT *, NTILE(4) OVER (ORDER BY exc_a) b FROM paired)
SELECT b, COUNT(*) wallets, ROUND(AVG(exc_a)*100,2) excA_pct, ROUND(AVG(exc_b)*100,2) excB_pct
FROM q GROUP BY 1 ORDER BY 1""").fetchall()
out["deciles_resid"] = con.sql("""
WITH q AS (SELECT *, NTILE(10) OVER (ORDER BY exc_a) d FROM paired)
SELECT d, COUNT(*) wallets, ROUND(AVG(exc_a)*100,2) excA_pct, ROUND(AVG(exc_b)*100,2) excB_pct
FROM q GROUP BY 1 ORDER BY 1""").fetchall()
out["elapsed_s"] = round(time.time() - t0, 1)
json.dump(out, open("/tmp/arch_persistence_resid.json", "w"), indent=1, default=str)
print(json.dumps(out, indent=1, default=str))
