#!/usr/bin/env python3
"""
READ-ONLY parity probe: Polymarket Data API v1 -> v2 (migration due 2026-10-24).

Primary source, read 2026-10-17 (docs.polymarket.com/migrate/data-api-v1-to-v2):
  "Data API v1 is retired on October 24, 2026."
Contract changes that actually affect us:
  * envelope  : v1 bare array/object -> v2 { data: ..., pagination: {...} }; a miss is data:null/[] not an error
  * pagination: v1 limit/offset (offset caps at 10,000) -> v2 opaque cursor via pagination.next_cursor (NO offset)
  * casing    : v1 camelCase (proxyWallet, conditionId) -> v2 snake_case (proxy_wallet, condition_id)
                (request params accept both spellings on v2)
  * lifecycle : /closed-positions and /v1/market-positions FOLD into GET /v2/positions?status=CLOSED
                (status: OPEN|REDEEMABLE|REDEEMABLE_LOST|MERGEABLE|CLOSED)
  * routes    : /v1/leaderboard -> /v2/leaderboard ; /activity -> /v2/activity ; /positions -> /v2/positions
  * /v1/accounting/snapshot has NO v2 counterpart and is NOT retired (we do not call it)

This probe makes NO code changes and writes only data/data-api-v2-parity.json. It answers, per call site:
  can v2 serve the same read, with what params, and do the VALUES match v1 today?
"""

from __future__ import annotations

import json
import sqlite3
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DB = REPO / "prisma" / "dev.db"
OUT = REPO / "data" / "data-api-v2-parity.json"
BASE = "https://data-api.polymarket.com"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) polymarket-copybot-parity-probe"


def get(url: str, tries: int = 3) -> dict:
    last = None
    for attempt in range(tries):
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                body = r.read().decode("utf-8", "replace")
                return {"status": r.status, "url": url, "body": body,
                        "retry_after": r.headers.get("Retry-After")}
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "replace")[:400]
            if e.code == 429 and attempt < tries - 1:
                wait = int(e.headers.get("Retry-After") or 2)
                time.sleep(min(wait, 10))
                last = {"status": e.code, "url": url, "body": body,
                        "retry_after": e.headers.get("Retry-After")}
                continue
            return {"status": e.code, "url": url, "body": body,
                    "retry_after": e.headers.get("Retry-After")}
        except Exception as e:  # noqa: BLE001
            last = {"status": None, "url": url, "body": f"{type(e).__name__}: {e}", "retry_after": None}
            time.sleep(1.5)
    return last or {"status": None, "url": url, "body": "no attempt", "retry_after": None}


def shape(res: dict) -> dict:
    """Envelope + field-shape summary without dumping payloads."""
    out = {"status": res["status"], "url": res["url"], "retry_after": res["retry_after"], "_raw": res["body"]}
    try:
        body = json.loads(res["body"])
    except Exception:  # noqa: BLE001
        out["parse"] = "FAILED"
        out["body_head"] = (res["body"] or "")[:200]
        return out
    out["parse"] = "ok"
    if isinstance(body, dict):
        out["envelope"] = sorted(body.keys())
        data = body.get("data")
        out["data_type"] = type(data).__name__
        if isinstance(data, list):
            out["rows"] = len(data)
            out["row_keys"] = sorted(data[0].keys()) if data else []
            out["sample"] = data[0] if data else None
        elif isinstance(data, dict):
            out["data_keys"] = sorted(data.keys())
            out["sample"] = data
        else:
            out["data_value"] = data
        if data is None and "error" in body:
            out["error_body"] = body
        out["pagination"] = body.get("pagination")
    elif isinstance(body, list):
        out["envelope"] = "bare-array"
        out["rows"] = len(body)
        out["row_keys"] = sorted(body[0].keys()) if body else []
        out["sample"] = body[0] if body else None
    return out


def pick_wallet(conn: sqlite3.Connection) -> str:
    row = conn.execute(
        """
        SELECT walletAddress, COUNT(*) c FROM DecisionJournal
         GROUP BY walletAddress ORDER BY c DESC LIMIT 1
        """
    ).fetchone()
    return row[0] if row else "0xeaac36f714563e13d88db7a4f0a0898388f2d71d"


def q(**kw) -> str:
    return urllib.parse.urlencode({k: v for k, v in kw.items() if v is not None})


def main() -> int:
    if not DB.exists():
        print(f"no DB at {DB}", file=sys.stderr)
        return 1
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    try:
        wallet = pick_wallet(conn)
    finally:
        conn.close()

    probes: dict[str, dict] = {}

    # ---- 1. LEADERBOARD  (adapter: /v1/leaderboard?timePeriod=month&orderBy=PNL&limit&offset)
    probes["leaderboard_v1"] = shape(get(
        f"{BASE}/v1/leaderboard?{q(timePeriod='month', orderBy='PNL', limit=5, offset=0)}"))
    time.sleep(0.6)
    probes["leaderboard_v2_camel"] = shape(get(
        f"{BASE}/v2/leaderboard?{q(timePeriod='month', orderBy='PNL', limit=5)}"))
    time.sleep(0.6)
    probes["leaderboard_v2_snake"] = shape(get(
        f"{BASE}/v2/leaderboard?{q(time_period='month', order_by='PNL', limit=5)}"))
    time.sleep(0.6)
    probes["leaderboard_v2_offset_should_fail"] = shape(get(
        f"{BASE}/v2/leaderboard?{q(time_period='month', order_by='PNL', limit=5, offset=5)}"))

    # ---- 2. CLOSED POSITIONS (adapter: /closed-positions?user=..&limit=..&offset=..&sortBy=REALIZEDPNL&sortDirection=)
    probes["closed_v1"] = shape(get(
        f"{BASE}/closed-positions?{q(user=wallet, limit=5, offset=0, sortBy='REALIZEDPNL', sortDirection='DESC')}"))
    time.sleep(0.6)
    probes["closed_v2_positions_status"] = shape(get(
        f"{BASE}/v2/positions?{q(user=wallet, status='CLOSED', limit=5, sort_by='REALIZED_PNL', sort_direction='DESC')}"))
    time.sleep(0.6)
    probes["closed_v2_camel_variant"] = shape(get(
        f"{BASE}/v2/positions?{q(user=wallet, status='CLOSED', limit=5, sortBy='REALIZEDPNL', sortDirection='DESC')}"))

    # ---- 3. OPEN POSITIONS (adapter: /positions?user=..&limit=..&offset=..&sortBy=CURRENT&sortDirection=DESC)
    time.sleep(0.6)
    probes["open_v1"] = shape(get(
        f"{BASE}/positions?{q(user=wallet, limit=5, offset=0, sortBy='CURRENT', sortDirection='DESC')}"))
    time.sleep(0.6)
    probes["open_v2"] = shape(get(
        f"{BASE}/v2/positions?{q(user=wallet, limit=5, status='OPEN', sort_by='CURRENT', sort_direction='DESC')}"))

    # ---- 4. ACTIVITY (adapter: /activity?user=..&type=TRADE&limit=..&offset=..&start=..)
    time.sleep(0.6)
    probes["activity_v1"] = shape(get(
        f"{BASE}/activity?{q(user=wallet, type='TRADE', limit=5, offset=0)}"))
    time.sleep(0.6)
    probes["activity_v2"] = shape(get(
        f"{BASE}/v2/activity?{q(user=wallet, type='TRADE', limit=5)}"))

    # ---- 5. cheap corroboration: does v2 still answer the v1 routes (retirement check)?
    probes["v1_still_live_check"] = shape(get(f"{BASE}/v1/leaderboard?{q(timePeriod='month', orderBy='PNL', limit=1)}"))

    # ---- 6. sort-enum discovery for /v2/positions (v1 used sortBy=CURRENT / REALIZEDPNL)
    for sort_val in ("CURRENT", "CURRENT_VALUE", "UNREALIZED_PNL", "PRICE", "TOKENS"):
        time.sleep(0.5)
        probes[f"v2_open_sort_{sort_val}"] = shape(get(
            f"{BASE}/v2/positions?{q(user=wallet, status='OPEN', limit=3, sort_by=sort_val, sort_direction='DESC')}"))
    time.sleep(0.5)
    probes["v2_open_nosort"] = shape(get(f"{BASE}/v2/positions?{q(user=wallet, status='OPEN', limit=3)}"))

    # ---- 7. ROW-LEVEL VALUE PARITY (the question that decides the migration)
    def rows_of(name: str) -> list:
        try:
            b = json.loads(probes[name]["_raw"])
        except Exception:  # noqa: BLE001
            return []
        if isinstance(b, dict):
            b = b.get("data")
        return b if isinstance(b, list) else []

    v1_closed = rows_of("closed_v1")
    v2_closed = rows_of("closed_v2_positions_status")
    def key(r):
        return f"{r.get('conditionId') or r.get('condition_id')}|{r.get('outcomeIndex') if 'outcomeIndex' in r else r.get('outcome_index')}"
    m1 = {key(r): r for r in v1_closed}
    m2 = {key(r): r for r in v2_closed}
    match = sorted(set(m1) & set(m2))
    pairwise = []
    for k in match:
        a, b = m1[k], m2[k]
        pairwise.append({
            "key": k,
            "v1_realizedPnl": a.get("realizedPnl"),
            "v2_realized_pnl": b.get("realized_pnl"),
            "delta": (round(float(b.get("realized_pnl") or 0) - float(a.get("realizedPnl") or 0), 6)
                      if a.get("realizedPnl") is not None and b.get("realized_pnl") is not None else None),
            "v1_avgPrice": a.get("avgPrice"), "v2_avg_price": b.get("avg_price"),
        })
    lb1 = rows_of("leaderboard_v1")
    lb2 = rows_of("leaderboard_v2_snake")
    lb_parity = {
        "wallet_order_match": [r.get("proxyWallet") for r in lb1] == [r.get("proxy_wallet") for r in lb2],
        "v1_wallets": [r.get("proxyWallet") for r in lb1],
        "v2_wallets": [r.get("proxy_wallet") for r in lb2],
        "pnl_pairs": [(r1.get("pnl"), r2.get("pnl")) for r1, r2 in zip(lb1, lb2)],
    }
    deep = {
        "closed_rows_matched": len(match),
        "closed_v1_only": len(set(m1) - set(m2)),
        "closed_v2_only": len(set(m2) - set(m1)),
        "closed_pairwise": pairwise,
        "leaderboard": lb_parity,
        "activity_v1_vs_v2_shared_value_check": {
            "v1_first": (rows_of("activity_v1") or [{}])[0].get("usdcSize"),
            "v2_first": (rows_of("activity_v2") or [{}])[0].get("usdc_size"),
        },
    }

    # value parity where both sides produced rows
    parity = {}
    for a, b in [("leaderboard_v1", "leaderboard_v2_snake"),
                 ("closed_v1", "closed_v2_positions_status"),
                 ("open_v1", "open_v2"),
                 ("activity_v1", "activity_v2")]:
        ra, rb = probes.get(a, {}), probes.get(b, {})
        if ra.get("rows") is not None and rb.get("rows") is not None:
            parity[f"{a}__vs__{b}"] = {
                "rows_v1": ra.get("rows"), "rows_v2": rb.get("rows"),
                "keys_v1": ra.get("row_keys"), "keys_v2": rb.get("row_keys"),
                "shared_keys": sorted(set(ra.get("row_keys") or []) & set(rb.get("row_keys") or [])),
            }

    deep = locals().get("deep", {})
    for v in probes.values():
        v.pop("_raw", None)
    report = {
        "probe": "data-api-v2-parity",
        "ranAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "wallet": wallet,
        "base": BASE,
        "retirement": "Data API v1 is retired on October 24, 2026 (docs/migrate/data-api-v1-to-v2, read 2026-10-17)",
        "probes": probes,
        "parity": parity,
        "deepParity": deep,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=1, sort_keys=True))

    print(f"wallet probed: {wallet}\n")
    for name, p in probes.items():
        if p.get("parse") != "ok":
            print(f"{name:34} HTTP {p.get('status')}  PARSE/{p.get('body_head','')[:90]}")
            continue
        extra = ""
        if p.get("rows") is not None:
            extra = f"rows={p['rows']}"
        if p.get("envelope") and p["envelope"] != "bare-array":
            extra += f" envelope={p['envelope']}"
        if p.get("pagination"):
            extra += f" pagination={list(p['pagination'].keys()) if isinstance(p['pagination'], dict) else p['pagination']}"
        print(f"{name:34} HTTP {p.get('status')}  {extra}")
        print(f"{'':34} keys={p.get('row_keys') or p.get('data_keys')}")
    print("\n=== parity ===")
    print(json.dumps(parity, indent=1)[:1200])
    print("\n=== deep parity (does v2 return the SAME values?) ===")
    print(json.dumps(deep, indent=1)[:3000])
    print(f"\nwritten -> {OUT.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
