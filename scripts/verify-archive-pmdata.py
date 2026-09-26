#!/usr/bin/env python3
"""verify-archive-pmdata — durability check for the historical archive on /Volumes/Storage.

The 2026-09-25 pull (TimeSeventeen/Polymarket-v1 + smf-ulm/polymarket-quant-bench) is the
substrate every calibration / ML / maker-taker study reads from, and it lives on a SINGLE
unencrypted external NVMe with no redundancy. This script is the re-runnable gate: it proves
the archive on disk still matches what the Hub published, without re-downloading it.

Checks (offline by default):
  1. per-config row counts vs the published totals (duckdb, parquet-footers only — fast)
  2. parquet file counts + total bytes vs the repo manifests (data/archive-manifests/*.json)
  3. zero-byte / truncated files, and stale *.incomplete leftovers
  4. ground-truth fields still populated: maker/taker_direction + fee_usdc null counts

With --hub it additionally re-fetches the Hub file tree and compares EVERY file's byte size
(the strongest integrity check short of hashing 53 GB) — that is how the original pull was
verified byte-perfect (2,154 + 1,419 files, zero mismatches).

Run:
  /Volumes/Storage/pm-data/.venv/bin/python scripts/verify-archive-pmdata.py
  /Volumes/Storage/pm-data/.venv/bin/python scripts/verify-archive-pmdata.py --hub
Exit code 0 = archive intact, 1 = a check failed (details printed).
"""
import glob
import json
import os
import sys
import urllib.request

ARCHIVE = "/Volumes/Storage/pm-data"
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MANIFEST_DIR = os.path.join(REPO, "data", "archive-manifests")

# Published totals (HuggingFace datasets-server, re-read 2026-09-25).
PUBLISHED = {
    "polymarket-v1": {
        "total": 2_786_380_324,
        "configs": {
            "CTF": 838_688_922,
            "OrderFilled": 1_201_580_990,
            "daily_aligned": 601_934_424,
            "daily_aligned_multi": 144_175_988,
        },
        "hub": "TimeSeventeen/Polymarket-v1",
        "revision": "5aa1b9d52316a8b2e789e81c8ae42c7ed532e8aa",
    },
    "quant-bench": {
        "total": 14_154_379,
        "configs": {
            "polymarket/bars_daily": 1_462_282,
            "polymarket/bars_hourly": 12_655_266,
            "polymarket/markets": 36_831,
        },
        "hub": "smf-ulm/polymarket-quant-bench",
        "revision": "b85406f38db8d9127ca45740a6bde0b5f2c7698e",
    },
}

failures, notes = [], []


def fail(msg):
    failures.append(msg)
    print(f"  FAIL  {msg}")


def ok(msg):
    print(f"  ok    {msg}")


def hub_tree(repo, revision):
    """Full file tree (path -> bytes) from the Hub, paginated."""
    out, url = {}, (
        f"https://huggingface.co/api/datasets/{repo}/tree/{revision}"
        "?recursive=true&limit=1000"
    )
    while url:
        req = urllib.request.Request(url, headers={"User-Agent": "verify-archive-pmdata"})
        with urllib.request.urlopen(req, timeout=60) as r:
            page = json.loads(r.read().decode("utf-8", "replace"))
            out.update(
                {
                    f["path"]: (f.get("size") or (f.get("lfs") or {}).get("size") or 0)
                    for f in page
                    if f.get("type") == "file"
                }
            )
            link = r.headers.get("Link", "")
        nxt = [p for p in link.split(",") if 'rel="next"' in p]
        url = nxt[0].split(">")[0].strip().lstrip("<") if nxt else None
    return out


def local_files(root):
    found = {}
    for dp, dn, fn in os.walk(root):
        dn[:] = [d for d in dn if d not in (".cache", ".git")]
        for f in fn:
            p = os.path.join(dp, f)
            found[os.path.relpath(p, root)] = os.path.getsize(p)
    return found


def main():
    check_hub = "--hub" in sys.argv
    try:
        import duckdb
    except ImportError:
        print("duckdb missing — run with /Volumes/Storage/pm-data/.venv/bin/python")
        return 1
    con = duckdb.connect()
    con.execute("SET threads=4; SET enable_progress_bar=false;")

    for ds, meta in PUBLISHED.items():
        root = os.path.join(ARCHIVE, ds)
        print(f"\n== {ds}  ({root})")
        if not os.path.isdir(root):
            fail(f"{ds}: archive directory missing")
            continue

        # 1 + 2: rows and file counts per config
        total_rows = 0
        for cfg, published_rows in meta["configs"].items():
            pat = os.path.join(root, cfg, "**", "*.parquet")
            files = glob.glob(pat, recursive=True)
            if not files:
                fail(f"{ds}/{cfg}: no parquet files")
                continue
            rows = con.execute(
                f"SELECT COUNT(*) FROM read_parquet('{pat}')"
            ).fetchone()[0]
            total_rows += rows
            if rows != published_rows:
                fail(f"{ds}/{cfg}: rows {rows:,} != published {published_rows:,}")
            else:
                ok(f"{cfg}: {rows:,} rows / {len(files)} files")
        if total_rows != meta["total"]:
            fail(f"{ds}: total rows {total_rows:,} != published {meta['total']:,}")
        else:
            ok(f"total {total_rows:,} rows == published")

        # 2: manifests
        mpath = os.path.join(MANIFEST_DIR, f"{ds}.json")
        if not os.path.exists(mpath):
            fail(f"{ds}: manifest missing at {mpath}")
        else:
            m = json.load(open(mpath))
            on_disk = local_files(root)
            # the pull dropped a local manifest.json next to the data — exclude local-only
            # artifacts from the byte comparison (it is not a Hub file).
            LOCAL_ONLY = {"manifest.json", "download.log", ".DS_Store"}
            hub_side = {p: s for p, s in on_disk.items() if os.path.basename(p) not in LOCAL_ONLY}
            disk_bytes = sum(hub_side.values())
            declared = m.get("bytes_on_disk")
            parq = [p for p in on_disk if p.endswith(".parquet")]
            if declared and declared != disk_bytes:
                fail(f"{ds}: on-disk bytes {disk_bytes:,} != manifest {declared:,}")
            else:
                ok(f"bytes on disk {disk_bytes:,} == manifest (local-only files excluded)")
            if m.get("parquet_files_total") and m["parquet_files_total"] != len(parq):
                fail(f"{ds}: parquet files {len(parq)} != manifest {m['parquet_files_total']}")
            else:
                ok(f"parquet files {len(parq)} == manifest")
            if m.get("hub_revision") != meta["revision"]:
                fail(f"{ds}: manifest revision {m.get('hub_revision')} != expected {meta['revision']}")
            # 3: truncation / leftovers
            zero = [p for p, s in on_disk.items() if s == 0]
            if zero:
                fail(f"{ds}: {len(zero)} zero-byte files (e.g. {zero[:2]})")
            else:
                ok("no zero-byte files")
            inc = glob.glob(os.path.join(root, "**", "*.incomplete"), recursive=True)
            if inc:
                fail(f"{ds}: {len(inc)} stale *.incomplete leftover(s)")
            else:
                ok("no .incomplete leftovers")
            # 4: hub byte-for-byte comparison
            if check_hub:
                exp = hub_tree(meta["hub"], meta["revision"])
                expn = {k.lower(): v for k, v in exp.items()}
                locn = {k.lower(): v for k, v in on_disk.items()}
                miss = [k for k in expn if k not in locn]
                mism = [k for k in expn if k in locn and expn[k] != locn[k]]
                if miss or mism:
                    fail(f"{ds}: hub compare — {len(miss)} missing, {len(mism)} size-mismatched")
                else:
                    ok(f"hub compare: all {len(expn)} published files present at exact byte size")

    # 4b: ground-truth fields still populated (OrderFilled only, first + last month)
    print("\n== ground-truth field integrity (OrderFilled)")
    of = sorted(glob.glob(os.path.join(ARCHIVE, "polymarket-v1", "OrderFilled", "*.parquet")))
    if not of:
        fail("OrderFilled: no monthly files found")
    for p in ([of[0], of[-1]] if of else []):
        r = con.execute(
            f"""SELECT COUNT(*),
                   SUM(CASE WHEN maker_direction IS NULL OR maker_direction='' THEN 1 ELSE 0 END),
                   SUM(CASE WHEN taker_direction IS NULL OR taker_direction='' THEN 1 ELSE 0 END),
                   SUM(CASE WHEN fee_usdc IS NULL THEN 1 ELSE 0 END),
                   SUM(CASE WHEN fee_usdc > 0 THEN 1 ELSE 0 END)
                FROM read_parquet('{p}')"""
        ).fetchone()
        name = os.path.basename(p)
        if r[1] or r[2] or r[3]:
            fail(f"{name}: null direction/fee cells present (md={r[1]}, td={r[2]}, fee={r[3]})")
        else:
            ok(f"{name}: rows {r[0]:,} · 0 null directions · 0 null fees · fee-bearing {r[4]:,} ({100*r[4]/r[0]:.2f}%)")
        notes.append(f"{name} fee-bearing {100*r[4]/r[0]:.2f}%")

    print("\n== summary")
    if failures:
        print(f"FAILED: {len(failures)} check(s)")
        for f in failures:
            print("  -", f)
        return 1
    print("PASS — archive intact (rows, file counts, bytes" + (", hub bytes" if check_hub else "") + ")")
    return 0


if __name__ == "__main__":
    sys.exit(main())
