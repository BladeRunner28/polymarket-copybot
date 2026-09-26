#!/usr/bin/env python3
"""archive-fee-maker-analysis — fee-model calibration + maker/taker split on the
Polymarket-v1 archive (TimeSeventeen/Polymarket-v1, /Volumes/Storage/pm-data).

Measurement only: reads parquet, writes JSON under data/archive-analysis/. Nothing
in the live stack (rules, sizing, booked PnL) is touched.

Modes
  split   per (month, price band, taker_direction): fills, USDC, fee, fee-bearing rows
  fee     fee-formula fit: is fee == rate_eff * shares * min(p, 1-p) on fee-bearing rows?
  fill    maker-fill hazard: P(a later print at <= p - delta within horizon | a print at p)

Run with the archive venv (duckdb 1.5.5, pyarrow):
  /Volumes/Storage/pm-data/.venv/bin/python scripts/archive-fee-maker-analysis.py split
"""
import glob
import json
import os
import sys
import time

import duckdb

ROOT = "/Volumes/Storage/pm-data/polymarket-v1"
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "archive-analysis")
os.makedirs(OUT, exist_ok=True)


def con(threads=6):
    c = duckdb.connect()
    c.execute(f"SET threads={threads}; SET enable_progress_bar=false;")
    return c


def of_files():
    return sorted(glob.glob(f"{ROOT}/OrderFilled/*.parquet"))


def month(f):
    return os.path.basename(f).replace(".parquet", "")


def mode_split():
    """Per (month, band, taker_direction): counts, USDC notional, fee. One scan of the
    whole OrderFilled config (1.2B fills), aggregated per monthly file so progress is
    visible and a timeout cannot lose everything."""
    c = con()
    out_path = os.path.join(OUT, "fee-maker-split.jsonl")
    done = set()
    if os.path.exists(out_path):
        for line in open(out_path):
            try:
                done.add(json.loads(line)["month"])
            except Exception:
                pass
    rows = 0
    for f in of_files():
        m = month(f)
        if m in done:
            print(f"skip {m} (already aggregated)", flush=True)
            continue
        t0 = time.time()
        q = f"""
        SELECT '{m}' AS month,
               CAST(floor(price*10) AS INT) AS band10,
               taker_direction AS td,
               COUNT(*) AS n_fills,
               SUM(usdc_amount) AS usdc,
               SUM(fee_usdc) AS fee,
               SUM(CASE WHEN fee_usdc > 0 THEN 1 ELSE 0 END) AS n_fee_rows,
               SUM(CASE WHEN fee_usdc > 0 THEN usdc_amount ELSE 0 END) AS usdc_fee_rows,
               SUM(token_amount * LEAST(price, 1-price)) AS shares_minp
        FROM read_parquet('{f}')
        GROUP BY 2,3
        """
        agg = c.execute(q).fetchall()
        with open(out_path, "a") as fh:
            for r in agg:
                fh.write(json.dumps({"month": r[0], "band10": r[1], "td": r[2],
                                     "n_fills": r[3], "usdc": r[4], "fee": r[5],
                                     "n_fee_rows": r[6], "usdc_fee_rows": r[7],
                                     "shares_minp": r[8]}) + "\n")
        rows += len(agg)
        print(f"{m}: {len(agg)} groups in {time.time()-t0:.1f}s", flush=True)
    print(f"split done: {rows} groups this run -> {out_path}")


def mode_fee():
    """Fee-formula fit on fee-bearing rows of the modern era. For each taker side and
    price band: median implied multiplier fee / (shares * min(p,1-p)) and the share of
    rows matching that multiplier to within 1e-6 relative error."""
    c = con()
    out = []
    files = [f for f in of_files() if os.path.basename(f) >= "2026_01.parquet"]
    for f in files:
        m = month(f)
        q = f"""
        WITH base AS (
          SELECT taker_direction AS td,
                 CAST(floor(price*10) AS INT) AS band10,
                 token_amount * LEAST(price, 1-price) AS denom,
                 fee_usdc AS fee
          FROM read_parquet('{f}')
          WHERE fee_usdc > 0
        ), f2 AS (
          SELECT td, band10, fee / NULLIF(denom, 0) AS mult FROM base
        )
        SELECT td, band10, COUNT(*) n,
               median(mult) AS med_mult,
               SUM(CASE WHEN abs(mult - 0.1) < 1e-6 THEN 1 ELSE 0 END) AS n_exact_01,
               SUM(CASE WHEN abs(mult - 0.05) < 1e-6 THEN 1 ELSE 0 END) AS n_exact_005,
               SUM(CASE WHEN abs(mult - 0.07) < 1e-6 THEN 1 ELSE 0 END) AS n_exact_007,
               SUM(CASE WHEN abs(mult - 0.04) < 1e-6 THEN 1 ELSE 0 END) AS n_exact_004
        FROM f2 GROUP BY 1,2 ORDER BY 1,2
        """
        for r in c.execute(q).fetchall():
            out.append({"month": m, "td": r[0], "band10": r[1], "n": r[2],
                        "med_mult": r[3], "n_0.10": r[4], "n_0.05": r[5],
                        "n_0.07": r[6], "n_0.04": r[7]})
            print(out[-1], flush=True)
    json.dump(out, open(os.path.join(OUT, "fee-formula-fit.json"), "w"), indent=1)
    print("fee fit ->", os.path.join(OUT, "fee-formula-fit.json"))


def mode_fill():
    """Maker-fill hazard. For every fill at price p on a token, how far BELOW p does the
    tape print again within a horizon? A resting BUY placed at p - delta is filled exactly
    when a later print lands at or below p - delta, which is the event the C-200 sidecar
    assumes when it books entry at intent - $0.02.

    Sharded by token hash (a whole-file window blows up memory) and bucketed by the
    improvement available, so one pass answers every horizon/delta pair:

      improvement = p - min(price) over fills on the same token in (t, t + horizon]

    horizon and delta are env-configurable; the buckets cover the sweep.
    """
    horizons = [int(x) for x in os.environ.get("FILL_HORIZONS", "300,1800,3600").split(",")]
    months = os.environ.get("FILL_MONTHS", "2026_04").split(",")
    shards = int(os.environ.get("FILL_SHARDS", "20"))
    c = con(threads=6)
    c.execute("SET memory_limit='6GB'")
    out_path = os.path.join(OUT, "maker-fill-hazard.jsonl")
    done = set()
    if os.path.exists(out_path):
        for line in open(out_path):
            try:
                d = json.loads(line)
                done.add((d["month"], d["shard"]))
            except Exception:
                pass
    buckets = [0.005, 0.01, 0.02, 0.03, 0.05, 0.10, 0.20]
    for m in months:
        f = f"{ROOT}/OrderFilled/{m}.parquet"
        for sh in range(shards):
            if (m, sh) in done:
                continue
            wins = ",\n".join(
                f"MIN(price) OVER (PARTITION BY tok ORDER BY ts RANGE BETWEEN 1 FOLLOWING AND {h} FOLLOWING) AS mn{h}"
                for h in horizons)
            sel = ",\n".join(
                f"SUM(CASE WHEN mn{h} <= price - {b} THEN 1 ELSE 0 END) AS h{h}_b{str(b).replace('.','_')}"
                for h in horizons for b in buckets)
            nulls = ",\n".join(f"SUM(CASE WHEN mn{h} IS NULL THEN 1 ELSE 0 END) AS h{h}_null" for h in horizons)
            q = f"""
            WITH s AS (
              SELECT token_asset_id AS tok, block_timestamp AS ts, price,
                     CAST(floor(price*10) AS INT) AS band10
              FROM read_parquet('{f}')
              WHERE price > 0.02 AND price < 0.98 AND hash(token_asset_id) % {shards} = {sh}
            ), w AS (
              SELECT tok, ts, price, band10, {wins}
              FROM s
            )
            SELECT band10, COUNT(*) AS n_fills, {nulls}, {sel}
            FROM w GROUP BY 1 ORDER BY 1
            """
            t0 = time.time()
            try:
                rows = c.execute(q).fetchall()
                cols = [d[0] for d in c.description]
            except Exception as e:
                print(f"{m} shard {sh}: ERROR {type(e).__name__}: {str(e)[:160]}", flush=True)
                continue
            with open(out_path, "a") as fh:
                for r in rows:
                    fh.write(json.dumps({"month": m, "shard": sh,
                                         "cols": cols, "vals": list(r)}) + "\n")
            print(f"{m} shard {sh}: {sum(r[1] for r in rows):,} fills in {time.time()-t0:.1f}s", flush=True)
    print("hazard ->", out_path)


def mode_drift():
    """Adverse selection on the same event. If our resting bid at p - delta does get filled,
    is that fill good or is it a market moving against us? For each fill at p:
      px_end = last traded price on the token within (t, t + horizon]
      mn     = lowest price on the token within (t, t + horizon]
    bucketed by whether the resting bid would have filled (mn <= p - delta), so the two
    populations are directly comparable. Prices are in probability points.
    """
    horizon = int(os.environ.get("FILL_HORIZON_S", "3600"))
    delta = float(os.environ.get("FILL_DELTA", "0.02"))
    months = os.environ.get("FILL_MONTHS", "2026_04").split(",")
    shards = int(os.environ.get("FILL_SHARDS", "20"))
    c = con(threads=6)
    c.execute("SET memory_limit='6GB'")
    out_path = os.path.join(OUT, f"maker-fill-drift-h{horizon}-d{int(delta*100)}.jsonl")
    done = set()
    if os.path.exists(out_path):
        for line in open(out_path):
            try:
                d = json.loads(line)
                done.add((d["month"], d["shard"]))
            except Exception:
                pass
    for m in months:
        f = f"{ROOT}/OrderFilled/{m}.parquet"
        for sh in range(shards):
            if (m, sh) in done:
                continue
            q = f"""
            WITH s AS (
              SELECT token_asset_id AS tok, block_timestamp AS ts, price,
                     CAST(floor(price*10) AS INT) AS band10
              FROM read_parquet('{f}')
              WHERE price > 0.02 AND price < 0.98 AND hash(token_asset_id) % {shards} = {sh}
            ), w AS (
              SELECT tok, ts, price, band10,
                     MIN(price) OVER (PARTITION BY tok ORDER BY ts RANGE BETWEEN 1 FOLLOWING AND {horizon} FOLLOWING) AS mn,
                     arg_max(price, ts) OVER (PARTITION BY tok ORDER BY ts RANGE BETWEEN 1 FOLLOWING AND {horizon} FOLLOWING) AS px_end
              FROM s
            )
            SELECT band10,
                   CASE WHEN mn <= price - {delta} THEN 1 ELSE 0 END AS filled,
                   COUNT(*) n,
                   AVG(px_end - price) avg_end_minus_p,
                   AVG(mn - price) avg_min_minus_p,
                   AVG(CASE WHEN px_end < price THEN 1.0 ELSE 0.0 END) share_below_p
            FROM w WHERE px_end IS NOT NULL GROUP BY 1,2 ORDER BY 1,2
            """
            t0 = time.time()
            try:
                rows = c.execute(q).fetchall()
            except Exception as e:
                print(f"{m} shard {sh}: ERROR {type(e).__name__}: {str(e)[:160]}", flush=True)
                continue
            with open(out_path, "a") as fh:
                for r in rows:
                    fh.write(json.dumps({"month": m, "shard": sh, "band10": r[0], "filled": r[1],
                                         "n": r[2], "avg_end_minus_p": r[3], "avg_min_minus_p": r[4],
                                         "share_end_below_p": r[5]}) + "\n")
            print(f"{m} shard {sh}: {sum(r[2] for r in rows):,} fills in {time.time()-t0:.1f}s", flush=True)
    print("drift ->", out_path)


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "split"
    {"split": mode_split, "fee": mode_fee, "fill": mode_fill, "drift": mode_drift}[mode]()
