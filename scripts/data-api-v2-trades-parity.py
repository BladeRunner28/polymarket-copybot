#!/usr/bin/env python3
"""
Print-level /trades parity, v1 vs v2 — the card clause, because this route feeds a
PUBLISHED number (scripts/c200-printthrough.py), not just a fetch.

Compares, per condition: row count and the SET of fill identities
(transactionHash|asset|price|size|timestamp) after v2's snake_case aliases.

Run: python3 scripts/data-api-v2-trades-parity.py [--conditions 24]
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import subprocess
import sys
import time

BASE = "https://data-api.polymarket.com"

_V2_TO_V1 = {
    "transaction_hash": "transactionHash",
    "token_id": "asset",
    "condition_id": "conditionId",
    "proxy_wallet": "proxyWallet",
}


def curl_json(url: str, tries: int = 3):
    for i in range(tries):
        try:
            raw = subprocess.run(
                ["curl", "-s", "--max-time", "30", url], capture_output=True, text=True, timeout=60
            ).stdout
            if raw.strip():
                return json.loads(raw)
        except Exception:
            pass
        time.sleep(1 + i)
    return None


def v1_shape(row: dict) -> dict:
    out = dict(row)
    for k2, k1 in _V2_TO_V1.items():
        if out.get(k1) is None and row.get(k2) is not None:
            out[k1] = row[k2]
    return out


def fill_key(r: dict):
    def f(v):
        try:
            return round(float(v), 6)
        except Exception:
            return v

    return (
        str(r.get("transactionHash") or r.get("transaction_hash") or ""),
        str(r.get("asset") or r.get("token_id") or ""),
        f(r.get("price")),
        f(r.get("size")),
        str(r.get("timestamp") or ""),
    )


def tape_v1(cid: str, pages: int = 3) -> list[dict]:
    rows: list[dict] = []
    for p in range(pages):
        d = curl_json(f"{BASE}/trades?market={cid}&limit=500&offset={p * 500}&takerOnly=false")
        if not isinstance(d, list) or not d:
            break
        rows.extend(d)
        if len(d) < 500:
            break
        time.sleep(0.2)
    return rows


def tape_v2(cid: str, pages: int = 3) -> list[dict]:
    rows: list[dict] = []
    cursor = None
    for _ in range(pages):
        url = f"{BASE}/v2/trades?condition={cid}&limit=500&taker_only=false"
        if cursor:
            url += f"&cursor={cursor}"
        d = curl_json(url)
        if not isinstance(d, dict):
            break
        chunk = d.get("data") or []
        rows.extend(v1_shape(r) for r in chunk)
        cursor = ((d.get("pagination") or {}) or {}).get("next_cursor")
        if not cursor or not chunk:
            break
        time.sleep(0.2)
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--conditions", type=int, default=24)
    args = ap.parse_args()

    con = sqlite3.connect("prisma/dev.db")
    cids = [
        r[0]
        for r in con.execute(
            """SELECT conditionId FROM ObservedTrade
               WHERE conditionId IS NOT NULL AND conditionId != ''
               GROUP BY conditionId ORDER BY COUNT(*) DESC LIMIT ?""",
            (args.conditions,),
        )
    ]
    print(f"print-level parity over {len(cids)} conditions\n")

    exact = 0
    subset_v2_in_v1 = 0
    bad = []
    for cid in cids:
        a = tape_v1(cid)
        b = tape_v2(cid)
        ka = {fill_key(r) for r in a}
        kb = {fill_key(r) for r in b}
        only_a = ka - kb
        only_b = kb - ka
        status = "EXACT" if not only_a and not only_b else ("V2⊂V1" if not only_b else "DIFF")
        if status == "EXACT":
            exact += 1
        elif status == "V2⊂V1":
            subset_v2_in_v1 += 1
        else:
            bad.append((cid, len(only_a), len(only_b)))
        print(
            f"  {cid[:12]}… v1 {len(a):4d} rows v2 {len(b):4d} | keys {len(ka)}/{len(kb)} "
            f"only-v1 {len(only_a):3d} only-v2 {len(only_b):3d} -> {status}"
        )

    print(f"\n=== {exact}/{len(cids)} exact key-set parity, {subset_v2_in_v1} v2-subset-of-v1, {len(bad)} divergent ===")
    out = {
        "probe": "data-api-v2-trades-parity",
        "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "conditions": len(cids),
        "exact": exact,
        "v2_subset": subset_v2_in_v1,
        "divergent": [{"condition": c, "onlyV1": a, "onlyV2": b} for c, a, b in bad],
        "verdict": "PASS" if exact == len(cids) else ("PASS-WITH-SUBSET" if not bad else "FAIL"),
    }
    with open("data/data-api-v2-trades-parity.json", "w") as fh:
        json.dump(out, fh, indent=1)
    print(f"  wrote data/data-api-v2-trades-parity.json  verdict={out['verdict']}")
    return 0 if out["verdict"] != "FAIL" else 1


if __name__ == "__main__":
    sys.exit(main())
