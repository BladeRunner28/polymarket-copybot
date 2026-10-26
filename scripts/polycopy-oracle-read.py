#!/usr/bin/env python3
"""
Polycopy public-profile oracle read (READ-ONLY, no account, no API key).

WHY THIS EXISTS
    Card `polycopy-free-account-oracle` claimed Polycopy exposes "a per-fill CSV for ANY public
    wallet". It does not. Their export surface (`/export-polymarket-trades/`) is a user's OWN
    history AND is robots-disallowed. The Copy Score number is also not server-rendered — it is
    drawn client-side from `/api/`, which their robots.txt disallows. So neither the CSV nor the
    Copy Score is obtainable in bulk, and a manual account gives a click-through, not a dataset.

WHAT *IS* AVAILABLE, AND IS BETTER
    `https://polycopy.app/trader/<address>` is a PUBLIC, server-rendered page. robots.txt is
    `Allow: /` with `/api/`, `/profile/`, `/portfolio/`, `/export-polymarket-trades/` disallowed —
    `/trader/` is allowed. Each page embeds a schema.org ProfilePage JSON-LD block carrying the
    trader's display name and a description with P&L, volume, ROI and trade count. That is an
    INDEPENDENT read on the question our `globalScore` is supposed to answer, and unlike Copy
    Score it can be collected and compared.

USAGE
    python3 scripts/polycopy-oracle-read.py            # top 15 wallets by notional we actually copy
    python3 scripts/polycopy-oracle-read.py --limit 30
    python3 scripts/polycopy-oracle-read.py --delay 1.5   # be polite; min 1.0 enforced

WRITES
    data/polycopy/polycopy-profiles.csv  — one row per wallet, our score beside their public stats

The comparison it prints is the point: if our highest-scored wallets are negative-ROI on the venue,
`globalScore` is ranking something other than copyable profitability.
"""
import argparse
import csv
import json
import os
import re
import sqlite3
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(ROOT, "prisma", "dev.db")
OUT_DIR = os.path.join(ROOT, "data", "polycopy")
OUT_CSV = os.path.join(OUT_DIR, "polycopy-profiles.csv")
UA = "Mozilla/5.0 (compatible; MedusaCopyBot research; +https://localhost)"  # identifiable, not spoofed


def our_wallets(limit):
    """Wallets we actually deploy capital against, biggest notional first."""
    con = sqlite3.connect(DB)
    try:
        return con.execute(
            """
            SELECT wp.address, wp.globalScore, COUNT(pt.id) AS legs,
                   ROUND(COALESCE(SUM(pt.simulatedPositionSize), 0), 2) AS notional
            FROM WalletProfile wp
            JOIN PaperTrade pt ON pt.walletAddress = wp.address
            GROUP BY wp.address
            ORDER BY notional DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    finally:
        con.close()


def fetch_profile(addr, timeout=25):
    """Return the JSON-LD Person block for a trader page, or None."""
    url = "https://polycopy.app/trader/%s" % addr
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/html"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        if r.status != 200:
            return None, url
        body = r.read().decode("utf-8", "ignore")
    for m in re.finditer(r'<script type="application/ld\+json">(.*?)</script>', body, re.S):
        try:
            blob = json.loads(m.group(1))
        except Exception:
            continue
        ent = blob.get("mainEntity") if isinstance(blob, dict) else None
        if isinstance(ent, dict) and ent.get("@type") == "Person":
            return ent, url
    return None, url


# The P&L carries an explicit sign, INCLUDING a leading '+' ("+$992.4K P&L"), which a
# '-?'-only pattern silently misses — it matched 1 of 15 before this was fixed.
NUM = r"([+-]?\$?[+-]?[\d,.]+\s*[KM]?)"


def parse_desc(desc):
    """Pull P&L / volume / ROI / trade count out of the JSON-LD description sentence."""
    out = {}
    if not desc:
        return out
    m = re.search(r"with " + NUM + r" P&L", desc)
    if m:
        out["venue_pnl"] = m.group(1).strip()
    m = re.search(r"P&L, " + NUM + r" volume", desc)
    if m:
        out["venue_volume"] = m.group(1).strip()
    m = re.search(r"and " + NUM + r"% ROI", desc)
    if m:
        out["venue_roi_pct"] = m.group(1).strip()
    m = re.search(r"across ([\d,]+) trades", desc)
    if m:
        out["venue_trades"] = m.group(1).strip()
    return out


def money(s):
    """'-$915.6K' -> -915600.0 ; returns None when unparseable."""
    if not s:
        return None
    t = s.replace("$", "").replace(",", "").strip().lstrip("+")
    mult = 1.0
    if t and t[-1] in "Kk":
        mult, t = 1e3, t[:-1]
    elif t and t[-1] in "Mm":
        mult, t = 1e6, t[:-1]
    try:
        return float(t) * mult
    except ValueError:
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=15)
    ap.add_argument("--delay", type=float, default=1.5)
    a = ap.parse_args()
    delay = max(1.0, a.delay)

    os.makedirs(OUT_DIR, exist_ok=True)
    wallets = our_wallets(a.limit)
    print("polycopy public-profile read — %d wallets, %.1fs between requests, robots: /trader/ allowed" % (len(wallets), delay))
    print()

    rows = []
    for i, (addr, our_score, legs, notional) in enumerate(wallets, 1):
        try:
            ent, url = fetch_profile(addr)
            if ent is None:
                print("  %2d. %s  NO JSON-LD (page shape changed?)" % (i, addr[:14]))
                rows.append(dict(address=addr, our_global_score=our_score, legs=legs, notional=notional,
                                 profile_url=url, status="no_jsonld"))
            else:
                d = parse_desc(ent.get("description"))
                rows.append(dict(address=addr, name=ent.get("name"), our_global_score=our_score,
                                 legs=legs, notional=notional, profile_url=url, status="ok", **d))
                print("  %2d. %-12s ours=%-5.1f  venue: P&L %-9s vol %-8s ROI %-7s %s trades" % (
                    i, str(ent.get("name"))[:12], our_score, d.get("venue_pnl", "?"),
                    d.get("venue_volume", "?"), (d.get("venue_roi_pct", "?") + "%"),
                    d.get("venue_trades", "?")))
        except Exception as e:
            print("  %2d. %s  ERROR %s" % (i, addr[:14], e))
            rows.append(dict(address=addr, our_global_score=our_score, legs=legs, notional=notional,
                             profile_url="https://polycopy.app/trader/" + addr, status="error:%s" % e))
        if i < len(wallets):
            time.sleep(delay)

    cols = ["address", "name", "our_global_score", "legs", "notional", "venue_pnl", "venue_volume",
            "venue_roi_pct", "venue_trades", "status", "profile_url"]
    with open(OUT_CSV, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)

    ok = [r for r in rows if r.get("status") == "ok"]
    print()
    print("wrote %s (%d rows, %d readable)" % (OUT_CSV, len(rows), len(ok)))
    if ok:
        roi = [(r["our_global_score"], money(r.get("venue_pnl"))) for r in ok if money(r.get("venue_pnl")) is not None]
        neg = [x for x in roi if x[1] < 0]
        print("venue P&L readable on %d/%d wallets; NEGATIVE on %d (%.0f%%)" % (
            len(roi), len(ok), len(neg), 100.0 * len(neg) / max(1, len(roi))))
        if len(roi) >= 4:
            # Spearman without scipy: rank both, Pearson on ranks.
            def ranks(v):
                order = sorted(range(len(v)), key=lambda i: v[i])
                rk = [0.0] * len(v)
                for pos, idx in enumerate(order):
                    rk[idx] = float(pos + 1)
                return rk
            xs = ranks([p[0] for p in roi]); ys = ranks([p[1] for p in roi])
            n = len(xs)
            mx = sum(xs) / n; my = sum(ys) / n
            num = sum((xs[i] - mx) * (ys[i] - my) for i in range(n))
            den = (sum((x - mx) ** 2 for x in xs) * sum((y - my) ** 2 for y in ys)) ** 0.5
            rho = num / den if den else float("nan")
            print("Spearman(our globalScore, venue P&L) = %+.3f on n=%d  %s" % (
                rho, n, "(no rank relationship)" if abs(rho) < 0.3 else "(relationship present)"))
        print("NOTE: venue P&L is NOT copy-adjusted — it is the wallet's own result. Copy Score")
        print("      subtracts the cost of following; this read cannot, so treat a positive")
        print("      venue P&L as a NECESSARY-not-sufficient filter, never as a copyable edge.")


if __name__ == "__main__":
    sys.exit(main())
