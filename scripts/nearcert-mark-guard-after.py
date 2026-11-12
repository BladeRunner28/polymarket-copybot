#!/usr/bin/env python3
"""nearcert-mark-guard-after.py — card t_4d29ae55, post-fix re-measure (read-only).

WHY
  The card was filed because 39% of the sub-0.05 near-certainty cohort carried a mark under
  the venue's 0.001 tick floor, 479 of them exactly 0.000000. The 2026-10-29 read found the
  cause one level down: `yesPrice = outcomePrices[0]` + `outcome === "NO" ? noPrice : yesPrice`
  priced every label-named market with the FIRST token, so a leg on the second token stored its
  SIBLING's price (strict test on closed markets: 359/359 second-listed marks were the sibling).

  That operand was fixed on 2026-11-09 (commit fbf9073, approved) at all four call sites:
  monitor-trades (detection price), score-trades (booking), update-pnl (marking),
  exit-recovery (early-exit value). This instrument measures the BEFORE/AFTER the card owed.

WHAT IT MEASURES (two windows, same cut as the fix)
  * near-certainty rows (the journal's `price X near certainty` reason) and the sub-0.05 cohort
  * marks below the venue tick floor / exactly zero — the card's headline defect
  * the STRICT positional test: decisions stamped AFTER the market's closedTime, where the
    venue's outcomePrices are frozen 0/1 and the true price of the traded token is knowable.
    A mark equal to our token's settled price is CONSISTENT; one equal to the sibling's is the
    label/position bug. Before the fix: second-listed 0/359 consistent. After: expect ~100%.
  * how many decisions are stamped on a market that had already closed (stale detection)
  * drift rejections whose stored sign contradicts (mark - walletEntry)

READ-ONLY on prisma/dev.db (SELECT only). Writes data/nearcert-mark-guard-after.json.
Reuses the label cache data/nearcert-market-meta.json, fetching only markets missing from it.

Run: python3 scripts/nearcert-mark-guard-after.py [--pre-days 7] [--no-fetch]
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import sys
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if not (ROOT / "package.json").exists():
    ROOT = Path(__file__).resolve().parent
DB = Path(os.environ.get("COPYBOT_DB", "/Users/xsnyde2/polymarket-copybot/prisma/dev.db"))
OUT = ROOT / "data" / "nearcert-mark-guard-after.json"
META = ROOT / "data" / "nearcert-market-meta.json"

GAMMA = "https://gamma-api.polymarket.com"
UA = {"accept": "application/json", "user-agent": "copybot-research/0.1 (paper-trading-only)"}
# commit fbf9073, 2026-11-09 09:15:16 -0600
FIX_CUT = datetime(2026, 11, 9, 15, 15, 16, tzinfo=timezone.utc)
TICK = 0.001
SETTLE_TOL = 0.005


def nrm(v):
    return re.sub(r"[^a-z0-9]", "", str(v or "").lower())


def parse_ts(s):
    if not s:
        return None
    t = str(s).strip().replace(" ", "T", 1)
    if t.endswith("+00"):
        t = t[:-3] + "+00:00"
    try:
        return datetime.fromisoformat(t.replace("Z", "+00:00"))
    except ValueError:
        return None


def fetch_market(mid):
    for attempt in range(4):
        try:
            req = urllib.request.Request(GAMMA + "/markets/slug/" + mid, headers=UA)
            with urllib.request.urlopen(req, timeout=20) as r:
                return mid, json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return mid, {"error": "404"}
            if e.code in (429, 500, 502, 503, 504):
                import time

                time.sleep(1.5 * (attempt + 1))
                continue
            return mid, {"error": str(e)[:100]}
        except Exception as e:  # noqa: BLE001
            import time

            time.sleep(1.0 * (attempt + 1))
            if attempt == 3:
                return mid, {"error": str(e)[:100]}
    return mid, {"error": "429 exhausted"}


def slim(mm):
    """Keep only the fields every reader of this cache needs.

    The venue payload is ~8 KB per market; the cache is 4,000+ markets and grows with every
    window, so storing it whole turns a cache into a 46 MB blob in the repo. `outcomes` and
    `outcomePrices` stay in their raw JSON-string form so the readers parse them identically.
    """
    return {k: mm[k] for k in ("outcomes", "outcomePrices", "closed", "closedTime", "error") if k in mm}


def main():
    argv = sys.argv[1:]
    pre_days = float(argv[argv.index("--pre-days") + 1]) if "--pre-days" in argv else 7.0
    do_fetch = "--no-fetch" not in argv

    now = datetime.now(timezone.utc)
    post_start = FIX_CUT
    post_end = now
    pre_start = FIX_CUT - timedelta(days=pre_days)
    pre_end = FIX_CUT
    # same-length slice of the pre window, for an apples-to-apples comparison
    span = post_end - post_start
    eq_start = pre_end - span
    eq_end = pre_end

    meta = json.loads(META.read_text()) if META.exists() else {}
    meta = {mid: slim(mm) for mid, mm in meta.items()}
    con = sqlite3.connect("file:%s?mode=ro" % DB, uri=True)
    con.row_factory = sqlite3.Row

    def rng(w):
        return int(w[0].timestamp() * 1000), int(w[1].timestamp() * 1000)

    windows = {
        "pre": (pre_start, pre_end, pre_days),
        "pre_equal": (eq_start, eq_end, span.total_seconds() / 86400.0),
        "post": (post_start, post_end, span.total_seconds() / 86400.0),
    }
    if "--custom-from" in argv and "--custom-to" in argv:
        cf = datetime.fromisoformat(argv[argv.index("--custom-from") + 1]).replace(tzinfo=timezone.utc)
        ct = datetime.fromisoformat(argv[argv.index("--custom-to") + 1]).replace(tzinfo=timezone.utc)
        windows["custom"] = (cf, ct, (ct - cf).total_seconds() / 86400.0)

    needed = set()
    for name, (s, e, _) in windows.items():
        s_ms, e_ms = rng((s, e))
        for r in con.execute(
            """SELECT DISTINCT o.marketId FROM DecisionJournal d
                 JOIN ObservedTrade o ON o.id = d.observedTradeId
                WHERE d.isDemo = 0 AND d.createdAt >= ? AND d.createdAt < ?""",
            (s_ms, e_ms),
        ):
            if r[0] and r[0] not in meta:
                needed.add(r[0])
    print("markets missing from label cache: %d" % len(needed), flush=True)
    if do_fetch and needed:
        with ThreadPoolExecutor(max_workers=6) as ex:
            for mid, payload in ex.map(fetch_market, sorted(needed)):
                meta[mid] = payload
        meta = {mid: slim(mm) for mid, mm in meta.items()}
        META.write_text(json.dumps(meta, separators=(",", ":")))
        print("  fetched %d (errors %d)"
              % (len(needed), sum(1 for m in needed if meta.get(m, {}).get("error"))), flush=True)

    labels, settled, closed_ts = {}, {}, {}
    for mid, mm in meta.items():
        try:
            labs = [str(x) for x in json.loads(mm.get("outcomes") or "[]")]
            prs = [float(x) for x in json.loads(mm.get("outcomePrices") or "[]")]
        except Exception:  # noqa: BLE001
            labs, prs = [], []
        labels[mid] = labs
        settled[mid] = prs if (mm.get("closed") is True and len(prs) == len(labs) and labs) else None
        closed_ts[mid] = parse_ts(mm.get("closedTime"))

    def position(mid, outcome):
        labs = labels.get(mid) or []
        o = nrm(outcome)
        if o in ("yes", "no"):
            return "YES_NO"
        if len(labs) == 2:
            if o == nrm(labs[0]):
                return "FIRST_LABEL"
            if o == nrm(labs[1]):
                return "SECOND_LABEL"
            return "LABEL_NOT_IN_MARKET"
        return "NO_LABELS"

    def truth(mid, outcome):
        prs, labs = settled.get(mid), labels.get(mid) or []
        if prs is None or len(prs) != len(labs):
            return None, None
        o = nrm(outcome)
        for i, lab in enumerate(labs):
            if nrm(lab) == o:
                return prs[i], 1.0 - prs[i]
        return None, None

    def closed_before(mid, ts_ms):
        ct = closed_ts.get(mid)
        return ct is not None and datetime.fromtimestamp(ts_ms / 1000.0, timezone.utc) > ct

    report = {
        "card": "t_4d29ae55",
        "read_at": now.isoformat(),
        "fix_cut_utc": FIX_CUT.isoformat(),
        "fix_commit": "fbf9073 price-side: price the token the leg holds, by the venue's own label",
        "windows": {},
    }

    for name, (s, e, days) in windows.items():
        s_ms, e_ms = rng((s, e))
        total = con.execute(
            """SELECT COUNT(*) FROM DecisionJournal d JOIN ObservedTrade o ON o.id = d.observedTradeId
                WHERE d.isDemo = 0 AND o.isDemo = 0 AND d.createdAt >= ? AND d.createdAt < ?""",
            (s_ms, e_ms),
        ).fetchone()[0]

        rows = []
        for r in con.execute(
            """SELECT d.createdAt, d.risksJson, d.decision, o.marketId, o.outcome,
                      o.detectedPrice, o.walletEntryPrice
                 FROM DecisionJournal d JOIN ObservedTrade o ON o.id = d.observedTradeId
                WHERE d.isDemo = 0 AND o.isDemo = 0 AND d.createdAt >= ? AND d.createdAt < ?
                  AND (d.risksJson LIKE '%near certainty%' OR d.risksJson LIKE '%drifted%')""",
            (s_ms, e_ms),
        ):
            risks = r["risksJson"] or ""
            m = re.search(r"price ([\d.]+) near certainty", risks)
            d = re.search(r"price drifted ([\d.]+) against us", risks)
            rows.append(
                {
                    "ts": int(r["createdAt"]),
                    "p": float(m.group(1)) if m else None,
                    "drift": float(d.group(1)) if d else None,
                    "w": None if r["walletEntryPrice"] is None else float(r["walletEntryPrice"]),
                    "det": None if r["detectedPrice"] is None else float(r["detectedPrice"]),
                    "mid": r["marketId"],
                    "out": r["outcome"],
                }
            )

        nc = [r for r in rows if r["p"] is not None]
        cheap = [r for r in nc if r["p"] < 0.05]
        rich = [r for r in nc if r["p"] > 0.95]
        driftrows = [r for r in rows if r["drift"] is not None]

        w = {
            "start_utc": s.isoformat(),
            "end_utc": e.isoformat(),
            "days": round(days, 2),
            "decisions": total,
            "near_certainty_rows": len(nc),
            "cheap_rows_lt_0.05": len(cheap),
            "rich_rows_gt_0.95": len(rich),
            "cheap_below_tick": sum(1 for r in cheap if r["p"] < TICK),
            "cheap_exactly_zero": sum(1 for r in cheap if r["p"] == 0.0),
            "cheap_positions": dict(Counter(position(r["mid"], r["out"]) for r in cheap)),
            "cheap_on_closed_market": sum(1 for r in cheap if closed_before(r["mid"], r["ts"])),
            "decisions_on_closed_market": None,
            "strict": {},
            "drift": {},
        }

        # decisions stamped after the market had already closed
        closed_n = 0
        for r in con.execute(
            """SELECT d.createdAt, o.marketId FROM DecisionJournal d
                 JOIN ObservedTrade o ON o.id = d.observedTradeId
                WHERE d.isDemo = 0 AND o.isDemo = 0 AND d.createdAt >= ? AND d.createdAt < ?""",
            (s_ms, e_ms),
        ):
            if closed_before(r["marketId"], int(r["createdAt"])):
                closed_n += 1
        w["decisions_on_closed_market"] = closed_n

        # STRICT positional test on closed markets, decisions stamped after closedTime
        by = defaultdict(lambda: Counter())
        for r in nc:
            if not closed_before(r["mid"], r["ts"]):
                continue
            t, sib = truth(r["mid"], r["out"])
            pos = position(r["mid"], r["out"])
            if t is None:
                by[pos]["unsettled"] += 1
            elif abs(r["p"] - t) <= SETTLE_TOL:
                by[pos]["consistent"] += 1
            elif abs(r["p"] - sib) <= SETTLE_TOL:
                by[pos]["sibling"] += 1
            else:
                by[pos]["neither"] += 1
        w["strict"] = {k: dict(v) for k, v in by.items()}

        # drift sign, measured where truth is knowable: decisions stamped after the market
        # closed, on a market whose settled prices are known. The stored delta and the reason
        # string are derived from the SAME operand, so the only way to see an inverted sign is
        # to compare the stored direction against the label-correct one.
        inv = checked = sec_n = sec_inv = 0
        for r in driftrows:
            if r["w"] is None or r["p"] is None:
                continue
            if not closed_before(r["mid"], r["ts"]):
                continue
            t, _sib = truth(r["mid"], r["out"])
            if t is None:
                continue
            checked += 1
            pos = position(r["mid"], r["out"])
            if pos == "SECOND_LABEL":
                sec_n += 1
            ds, dt = r["p"] - r["w"], t - r["w"]
            if ds * dt < 0 and abs(ds) > 0.002 and abs(dt) > 0.002:
                inv += 1
                if pos == "SECOND_LABEL":
                    sec_inv += 1
        w["drift"] = {"rows": len(driftrows), "sign_checked": checked, "sign_inverted": inv,
                      "second_label_rows": sec_n, "second_label_sign_inverted": sec_inv}

        report["windows"][name] = w

        print("\n== %s  %s .. %s  (%.2fd)" % (name, s.date(), e.date(), days))
        print("   decisions %d | near-cert %d | cheap<0.05 %d | below tick %d | exactly 0 %d"
              % (total, len(nc), len(cheap), w["cheap_below_tick"], w["cheap_exactly_zero"]))
        print("   cheap positions: %s" % w["cheap_positions"])
        print("   decisions on an already-closed market: %d (%.1f%%)"
              % (closed_n, 100.0 * closed_n / total if total else 0))
        print("   STRICT (post-close) positional test:")
        for pos, d in sorted(by.items(), key=lambda kv: -sum(kv[1].values())):
            print("     %-16s n=%-5d consistent=%-5d sibling=%-5d neither=%-4d unsettled=%d"
                  % (pos, sum(d.values()), d["consistent"], d["sibling"], d["neither"], d["unsettled"]))
        print("   drift rows %d | sign checked %d | inverted %d"
              % (len(driftrows), checked, inv))

    META.write_text(json.dumps(meta, separators=(",", ":")))
    OUT.write_text(json.dumps(report, indent=1))
    print("\nwrote %s" % OUT)


if __name__ == "__main__":
    main()
