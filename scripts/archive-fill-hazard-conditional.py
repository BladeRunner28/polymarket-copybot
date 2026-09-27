#!/usr/bin/env python3
"""U1 — conditional maker-fill hazard + markout cells from the Polymarket-v1 archive.

WHAT IT MEASURES
  For every print at price p on a token at time t, does the tape later print at <= p - delta within
  horizon h?  That is the event a resting BID at (p - delta) needs, i.e. exactly what the sidecar's
  `entry = intent - 0.02` assumes.  The published FLAT version is 71.1% @5m / 77.6% @1h (delta=0.02,
  783M fills, 2026-01..04), C-200-price-weighted 74.3% / 81.1%.  This instrument keeps the
  conditioning, so scripts/fit-fill-model.py can price
      p(fill | band, hour_et, size, ttr, activity, volatility, aggressor side, category)
  instead of one flat rate, and it carries the accompanying MARKOUT (px_end - p) split by filled /
  not-filled -- the adverse-selection term a fill model must pay for.

WHY CELLS AND NOT PER-FILL ROWS
  Pure duckdb, no numpy in the archive venv; 783M fills -> ~1-2e5 populated cells. The fit is a
  weighted logistic regression on cells (scripts/fit-fill-model.py, venv-calib).

SHARDING IS MANDATORY
  A whole-file window over a monthly partition is OOM-killed with an EMPTY log, which reads as "the
  job never ran". Shard by hash(token_asset_id) % N with a memory_limit, then validate the sharded
  numbers against ONE unsharded month (--validate-month) before trusting them.

USAGE
  P=/Volumes/Storage/pm-data/.venv/bin/python
  $P scripts/archive-fill-hazard-conditional.py --months 2026_01,2026_02,2026_03,2026_04 --shards 20
  $P scripts/archive-fill-hazard-conditional.py --months 2026_04 --validate-month 2026_04

OUTPUT (data/archive-analysis/)
  fill-hazard-cells-<tag>.csv          one row per populated cell (all shards summed)
  fill-hazard-cells-<tag>.meta.json    provenance: months, shards, deltas, horizons, counts, timing
  asset-labels-<tag>.parquet           the asset -> (category, close_at, labels) join built once
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

import duckdb

ARCHIVE = "/Volumes/Storage/pm-data/polymarket-v1"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTDIR = os.path.join(ROOT, "data", "archive-analysis")
PARTS = os.path.join(OUTDIR, "cells")

DELTAS = [0.01, 0.02, 0.03, 0.05]
HORIZONS = [300, 1800, 3600]
MB = {"2026_01": "2026_01", "2026_02": "2026_02", "2026_03": "2026_03", "2026_04": "2026_04"}


def month_files(months):
    out = []
    for m in months:
        f = f"{ARCHIVE}/OrderFilled/{m}.parquet"
        if not os.path.exists(f):
            sys.exit(f"missing {f}")
        out.append(f)
    return out


def daily_files(months):
    """daily_aligned partition files covering the requested months."""
    import glob
    allf = sorted(glob.glob(f"{ARCHIVE}/daily_aligned/*.parquet"))
    return [f for f in allf if any(os.path.basename(f).startswith(m) for m in months)]


def build_labels(con, months, tag, threads):
    """asset_id -> (category_refined, close_at, labels, slug). One pass, cached per tag."""
    path = os.path.join(OUTDIR, f"asset-labels-{tag}.parquet")
    if os.path.exists(path):
        print(f"[labels] reusing {os.path.basename(path)}", flush=True)
        return path
    t0 = time.time()
    of = month_files(months)
    df = daily_files(months)
    print(f"[labels] scanning {len(df)} daily files against the fills' token universe ...", flush=True)
    oflist = "[" + ", ".join(f"'{f}'" for f in of) + "]"
    dflist = "[" + ", ".join(f"'{f}'" for f in df) + "]"
    con.sql(f"""
    CREATE OR REPLACE TABLE labels AS
    WITH tk AS (SELECT DISTINCT lower(token_asset_id) AS asset_id FROM read_parquet({oflist}))
    SELECT d.asset_id,
           any_value(d.category_refined)        AS category,
           any_value(d.close_at)                AS close_at,
           any_value(d.outcome_label)           AS outcome_label,
           any_value(d.winning_outcome_label)   AS winning_outcome_label,
           any_value(d.resolution_status)       AS resolution_status,
           any_value(d.market_slug)             AS market_slug,
           any_value(d.condition_id)            AS condition_id
    FROM read_parquet({dflist}) d
    SEMI JOIN tk ON tk.asset_id = d.asset_id
    GROUP BY 1
    """)
    n = con.sql("SELECT COUNT(*) FROM labels").fetchone()[0]
    con.sql(f"COPY labels TO '{path}' (FORMAT parquet)")
    print(f"[labels] {n:,} assets labelled in {time.time()-t0:.1f}s -> {os.path.basename(path)}", flush=True)
    return path


def cell_sql(files, shard, nshards, labels_path):
    """Per-shard: fills + prior/forward windows + label join -> cell aggregates.

    `files` must be a Python list: duckdb needs the list LITERAL form
    read_parquet(['a','b']) -- a comma-joined string of paths binds as multiple
    VARCHAR args and dies with 'No function matches ... read_parquet(VARCHAR, VARCHAR, ...)'.
    """
    where_shard = f"AND hash(lower(token_asset_id)) % {nshards} = {shard}" if shard is not None else ""
    return f"""
CREATE OR REPLACE TEMP TABLE fills AS
SELECT lower(token_asset_id) AS asset, block_timestamp AS ts, price,
       usdc_amount, lower(coalesce(taker_direction,'')) AS tdir,
       MIN(price)        OVER w_prior AS minp_prior1h,
       STDDEV_SAMP(price) OVER w_prior AS vol_prior1h,
       COUNT(*)          OVER w_prior AS n_prior1h,
       MIN(price)        OVER w_h300  AS minp_h300,
       COUNT(*)          OVER w_h300  AS np_h300,
       MIN(price)        OVER w_h1800 AS minp_h1800,
       COUNT(*)          OVER w_h1800 AS np_h1800,
       MIN(price)        OVER w_h3600 AS minp_h3600,
       COUNT(*)          OVER w_h3600 AS np_h3600,
       LAST(price)       OVER w_h300  AS px_h300,
       LAST(price)       OVER w_h1800 AS px_h1800,
       LAST(price)       OVER w_h3600 AS px_h3600
FROM read_parquet({files})
WHERE price BETWEEN 0.02 AND 0.98 {where_shard}
WINDOW tok    AS (PARTITION BY lower(token_asset_id) ORDER BY block_timestamp),
       w_prior AS (tok RANGE BETWEEN 3600 PRECEDING AND 1 PRECEDING),
       w_h300  AS (tok RANGE BETWEEN 1 FOLLOWING AND 300 FOLLOWING),
       w_h1800 AS (tok RANGE BETWEEN 1 FOLLOWING AND 1800 FOLLOWING),
       w_h3600 AS (tok RANGE BETWEEN 1 FOLLOWING AND 3600 FOLLOWING)
"""


def _hit_cols():
    cols = []
    for d in DELTAS:
        for h in HORIZONS:
            t = f"d{int(round(d*100)):02d}_h{h}"
            cols.append(f"SUM(CASE WHEN minp_h{h} <= price - {d} THEN 1 ELSE 0 END) AS hit_{t}")
    return ",\n       ".join(cols)


def aggregate_sql(labels_path):
    return f"""
CREATE OR REPLACE TEMP TABLE cells AS
SELECT
       CAST(FLOOR(price * 10) AS INT)                              AS band,
       CAST(EXTRACT(hour FROM to_timestamp(ts) AT TIME ZONE 'America/New_York') AS INT) AS hour_et,
       CASE WHEN usdc_amount < 10 THEN 0 WHEN usdc_amount < 100 THEN 1
            WHEN usdc_amount < 1000 THEN 2 WHEN usdc_amount < 10000 THEN 3 ELSE 4 END AS size_b,
       CASE WHEN vol_prior1h IS NULL THEN 0 WHEN vol_prior1h < 0.005 THEN 1
            WHEN vol_prior1h < 0.015 THEN 2 WHEN vol_prior1h < 0.04 THEN 3 ELSE 4 END   AS vol_b,
       CASE WHEN n_prior1h IS NULL THEN 0 WHEN n_prior1h <= 5 THEN 1
            WHEN n_prior1h <= 20 THEN 2 WHEN n_prior1h <= 100 THEN 3 ELSE 4 END         AS act_b,
       CASE WHEN l.close_at IS NULL THEN -1
            WHEN l.close_at - to_timestamp(ts) < INTERVAL 1 HOUR THEN 0
            WHEN l.close_at - to_timestamp(ts) < INTERVAL 6 HOUR THEN 1
            WHEN l.close_at - to_timestamp(ts) < INTERVAL 1 DAY  THEN 2
            WHEN l.close_at - to_timestamp(ts) < INTERVAL 3 DAY  THEN 3
            WHEN l.close_at - to_timestamp(ts) < INTERVAL 7 DAY  THEN 4 ELSE 5 END      AS ttr_b,
       tdir,
       coalesce(l.category, 'unknown')                             AS category,
       COUNT(*)                                                    AS n,
       SUM(CASE WHEN np_h300  > 0 THEN 1 ELSE 0 END)               AS f300,
       SUM(CASE WHEN np_h1800 > 0 THEN 1 ELSE 0 END)               AS f1800,
       SUM(CASE WHEN np_h3600 > 0 THEN 1 ELSE 0 END)               AS f3600,
       {_hit_cols()},
       SUM(CASE WHEN np_h300  > 0 THEN px_h300  - price END)       AS mo_sum_h300,
       SUM(CASE WHEN np_h1800 > 0 THEN px_h1800 - price END)       AS mo_sum_h1800,
       SUM(CASE WHEN np_h3600 > 0 THEN px_h3600 - price END)       AS mo_sum_h3600,
       SUM(CASE WHEN np_h3600 > 0 AND minp_h3600 <= price - 0.02 THEN px_h3600 - price END) AS mo_fill_sum_h3600,
       SUM(CASE WHEN np_h3600 > 0 AND minp_h3600 >  price - 0.02 THEN px_h3600 - price END) AS mo_miss_sum_h3600,
       SUM(CASE WHEN np_h300  > 0 AND minp_h300  <= price - 0.02 THEN px_h300  - price END) AS mo_fill_sum_h300,
       SUM(CASE WHEN np_h300  > 0 AND minp_h300  >  price - 0.02 THEN px_h300  - price END) AS mo_miss_sum_h300
FROM fills f
LEFT JOIN read_parquet('{labels_path}') l ON l.asset_id = f.asset
GROUP BY ALL
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--months", default="2026_01,2026_02,2026_03,2026_04")
    ap.add_argument("--shards", type=int, default=20)
    ap.add_argument("--only-shard", type=int, default=None)
    ap.add_argument("--validate-month", default=None, help="single month, UNSHARDED (validation run)")
    ap.add_argument("--memory-limit", default="14GB")
    ap.add_argument("--min-cell", type=int, default=200,
                    help="drop cells thinner than this from the combined CSV (parts keep full grain)")
    ap.add_argument("--threads", type=int, default=6)
    ap.add_argument("--tag", default=None)
    ap.add_argument("--time-shard", action="store_true", help="shard 0 only: print timing, write nothing")
    args = ap.parse_args()

    months = [m.strip() for m in args.months.split(",") if m.strip()]
    if args.validate_month:
        months = [args.validate_month]
    files = month_files(months)
    os.makedirs(PARTS, exist_ok=True)

    tag = args.tag or (f"validate-{args.validate_month}" if args.validate_month else f"{months[0]}_{months[-1]}")
    if len(months) > 1:
        tag = args.tag or f"{months[0]}-{months[-1]}"
    con = duckdb.connect()
    con.sql(f"SET memory_limit='{args.memory_limit}'; SET threads={args.threads}; SET preserve_insertion_order=false;")
    # duckdb needs the LIST literal form: read_parquet(['a','b'])
    flist = "[" + ", ".join(f"'{f}'" for f in files) + "]"

    labels_path = build_labels(con, months, tag if not args.validate_month else args.validate_month, args.threads)

    shards = [None] if args.validate_month else ([args.only_shard] if args.only_shard is not None else list(range(args.shards)))
    run_tag = f"{tag}-{'unsharded' if args.validate_month else f'n{args.shards}'}"
    t_start = time.time()
    total = 0
    for shard in shards:
        t0 = time.time()
        con.sql("DROP TABLE IF EXISTS fills"); con.sql("DROP TABLE IF EXISTS cells")
        con.sql(cell_sql(flist, shard, args.shards, labels_path))
        n = con.sql("SELECT COUNT(*) FROM fills").fetchone()[0]
        if args.time_shard:
            print(f"[timing] shard {shard}: {n:,} fills+windows in {time.time()-t0:.1f}s", flush=True)
            return 0
        con.sql(aggregate_sql(labels_path))
        ncells = con.sql("SELECT COUNT(*) FROM cells").fetchone()[0]
        part = os.path.join(PARTS, f"cells-{run_tag}-shard-{shard if shard is not None else 'all'}.parquet")
        if os.path.exists(part):
            os.remove(part)
        con.sql(f"COPY cells TO '{part}' (FORMAT parquet)")
        total += n
        print(f"[shard {shard}] {n:,} fills -> {ncells:,} cells in {time.time()-t0:.1f}s", flush=True)

    # combine parts
    parts = sorted(__import__("glob").glob(os.path.join(PARTS, f"cells-{run_tag}-shard-*.parquet")))
    out_csv = os.path.join(OUTDIR, f"fill-hazard-cells-{run_tag}.csv")
    con.sql(f"""
    COPY (
      SELECT band, hour_et, size_b, vol_b, act_b, ttr_b, tdir, category,
             SUM(n) n, SUM(f300) f300, SUM(f1800) f1800, SUM(f3600) f3600,
             {', '.join('SUM(hit_' + f"d{int(round(d*100)):02d}_h{h}" + ') AS hit_' + f"d{int(round(d*100)):02d}_h{h}" for d in DELTAS for h in HORIZONS)},
             SUM(mo_sum_h300) mo_sum_h300, SUM(mo_sum_h1800) mo_sum_h1800, SUM(mo_sum_h3600) mo_sum_h3600,
             SUM(mo_fill_sum_h3600) mo_fill_sum_h3600, SUM(mo_miss_sum_h3600) mo_miss_sum_h3600,
             SUM(mo_fill_sum_h300) mo_fill_sum_h300, SUM(mo_miss_sum_h300) mo_miss_sum_h300
      FROM read_parquet({parts})
      GROUP BY ALL
      HAVING SUM(n) >= {args.min_cell}
      ORDER BY n DESC
    ) TO '{out_csv}' (HEADER, DELIMITER ',')
    """)
    nrows = con.sql(f"SELECT COUNT(*) FROM read_csv('{out_csv}', header=true)").fetchone()[0]
    meta = {
        "tag": run_tag, "months": months, "shards": len(shards), "unsharded": bool(args.validate_month),
        "deltas": DELTAS, "horizons_s": HORIZONS, "fills_processed": total,
        "cells": nrows, "csv": os.path.basename(out_csv), "labels": os.path.basename(labels_path),
        "elapsed_s": round(time.time() - t_start, 1),
        "price_filter": [0.02, 0.98], "memory_limit": args.memory_limit,
        "note": "cell aggregates; hit_<delta>_<horizon> counts fills where the tape later printed at or below price-delta",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }
    with open(os.path.join(OUTDIR, f"fill-hazard-cells-{run_tag}.meta.json"), "w") as fh:
        json.dump(meta, fh, indent=1)
    print(json.dumps(meta, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
