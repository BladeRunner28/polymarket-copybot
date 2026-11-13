#!/usr/bin/env python3
"""bookmaker-gap-corpus-audit.py — audit the FREE bookmaker-vs-Polymarket corpus we already record.

WHY THIS EXISTS
The ML-feed REC 2 card asks a pre-registered question: does bookmaker consensus beat the
Polymarket price at predicting settlement? Before paying any vendor, the cheap question is
whether the corpus we ALREADY collect (`data/odds-gaps.jsonl`, produced by `scripts/odds-gaps.py`
against The Odds API) can answer it. This script answers that honestly, and prints the counts
that decide it — including the ones that say the corpus CANNOT answer it.

WHAT IT MEASURES
  1. CORPUS SHAPE      — rows, markets, sports, date span.
  2. PAIRING HYGIENE   — how many rows pair a Polymarket market with the WRONG bookmaker market
                         (totals / first-5-innings lines matched against a moneyline `h2h` price).
  3. SIDE IDENTITY     — whether the stored `pmProb` is on the SAME side of the bet as
                         `bookImplied` (the book quote is the HOME team). This is the test that
                         decides whether a stored "gap" is a disagreement between venues or a
                         sign convention.
  4. DIRECTION + BRIER — the card's own statistic, on the moneyline subset, at ROW and MARKET
                         level, under the stored pairing and under the side-corrected pairing.

LABEL BASIS (stated beside every number, per the repo's measurement rule)
  Settlement is the VENUE's own resolution, read from gamma `/events?slug=<marketId>` —
  `closed = true` + `umaResolutionStatus = "resolved"` + `outcomePrices` of 1/0 — and mapped onto
  the bookmaker's home side by team-name tokens. That is the same route the repo's own resolver
  uses (`src/lib/dead-market-resolution.ts`). The archived CLOB `/markets/<conditionId>` route
  returns 403 from this host (probed 2026-11-12), so it is not used.
  The target is the MARKET OUTCOME (did the home side win), never `realizedPnl`.

Reads:  data/odds-gaps.jsonl, prisma/dev.db (mode=ro), gamma (cached to data/cache/).
Writes: data/bookmaker-gap-corpus-audit.json, data/cache/bookmaker-gap-labels.json.
"""
from __future__ import annotations

import collections
import json
import os
import re
import sqlite3
import statistics
import sys
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GAPS = os.path.join(ROOT, "data", "odds-gaps.jsonl")
DB = os.path.join(ROOT, "prisma", "dev.db")
OUT = os.path.join(ROOT, "data", "bookmaker-gap-corpus-audit.json")
CACHE = os.path.join(ROOT, "data", "cache", "bookmaker-gap-labels.json")

# A Polymarket marketId that names a LINE is not a moneyline. `odds-gaps.py` matches on team-token
# containment only, so totals and first-5-innings markets get paired against a moneyline `h2h`
# price, and their "gap" is an artefact of comparing two different bets.
LINE_MARKET = re.compile(r"total|over|under|spread|runline|f5|pt5|-o\d|-u\d|prop|half", re.I)
GENERIC = {"fc", "cf", "club", "ac", "sc", "afc", "de", "del", "the", "bk", "sk"}


def load_rows():
    if not os.path.exists(GAPS):
        sys.exit(f"missing {GAPS}")
    return [json.loads(l) for l in open(GAPS) if l.strip()]


def snapshot_index(market_ids):
    """Latest (yesPrice, noPrice, collectedAt) per marketId."""
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    con.execute("PRAGMA busy_timeout=8000")
    last = {}
    ids = sorted(market_ids)
    for start in range(0, len(ids), 400):
        chunk = ids[start:start + 400]
        q = ",".join("?" * len(chunk))
        for mid, yes, no, cat in con.execute(
            f"""SELECT marketId, yesPrice, noPrice, collectedAt FROM MarketSnapshot
                WHERE marketId IN ({q}) ORDER BY collectedAt""",  # noqa: S608 — placeholders only
            chunk,
        ):
            if yes is not None:
                last[mid] = {"yes": yes, "no": no, "collectedAt": cat}
    con.close()
    return last


def tokens(name: str):
    return [t for t in re.findall(r"[a-z']+", (name or "").lower())
            if len(t) > 2 and t not in GENERIC]


def fetch_labels(market_ids, refresh=False):
    """Venue settlement per market slug, cached. Returns {slug: {...}}."""
    cache = {}
    if os.path.exists(CACHE) and not refresh:
        try:
            cache = json.load(open(CACHE))
        except Exception:
            cache = {}
    todo = [m for m in market_ids if m not in cache]
    if todo:
        print(f"[labels] fetching {len(todo)} uncached settlements from gamma …")
    for i, slug in enumerate(todo):
        url = f"https://gamma-api.polymarket.com/events?slug={urllib.parse.quote(slug)}"
        rec = {"slug": slug, "status": None, "outcomes": None, "prices": None, "closed": None}
        ev = None
        for attempt in range(3):
            try:
                req = urllib.request.Request(url, headers={
                    "accept": "application/json",
                    "user-agent": "copybot-research/0.1 (paper-trading-only)"})
                with urllib.request.urlopen(req, timeout=25) as r:
                    rec["status"] = r.status
                    ev = json.loads(r.read())
                break
            except urllib.error.HTTPError as e:
                rec["status"] = e.code
                if e.code in (429, 500, 502, 503):
                    time.sleep(3 * (attempt + 1))
                    continue
                break
            except Exception as e:  # network/timeout
                rec["status"] = f"{type(e).__name__}"
                time.sleep(2 * (attempt + 1))
        if isinstance(rec["status"], int) and rec["status"] == 200:
            ev = ev if isinstance(ev, list) else []
            m = None
            for e in ev:
                for mm in (e.get("markets") or []):
                    if mm.get("slug") == slug:
                        m = mm
                        break
                if m:
                    break
            if m:
                rec.update({"closed": m.get("closed"),
                            "uma": m.get("umaResolutionStatus"),
                            "outcomes": json.loads(m.get("outcomes") or "[]"),
                            "prices": json.loads(m.get("outcomePrices") or "[]")})
        cache[slug] = rec
        if (i + 1) % 20 == 0:
            json.dump(cache, open(CACHE, "w"))
            print(f"[labels] {i + 1}/{len(todo)}")
    json.dump(cache, open(CACHE, "w"), indent=1)
    return cache


def side_labels(label_rec):
    """(first_won, second_won) for a two-outcome venue market, or (None, None)."""
    if not label_rec or not label_rec.get("outcomes") or not label_rec.get("prices"):
        return None, None
    if label_rec.get("closed") is not True or label_rec.get("uma") != "resolved":
        return None, None
    try:
        prices = [float(p) for p in label_rec["prices"]]
    except Exception:
        return None, None
    if len(prices) != 2 or sorted(prices) != [0.0, 1.0]:
        return None, None
    return int(prices[0] == 1.0), int(prices[1] == 1.0)



def main() -> int:
    rows = load_rows()
    out = {"generated_at": __import__("datetime").datetime.now().isoformat(timespec="seconds"),
           "rows": len(rows)}

    ts = sorted(r["ts"] for r in rows)
    out["first_ts"], out["last_ts"] = ts[0], ts[-1]
    out["sports"] = dict(collections.Counter(r["sport"] for r in rows).most_common())

    by_market = collections.defaultdict(list)
    for r in rows:
        by_market[r["pmMarketId"]].append(r)
    out["distinct_markets"] = len(by_market)

    ml = {m: rs for m, rs in by_market.items() if not LINE_MARKET.search(m)}
    line = {m: rs for m, rs in by_market.items() if LINE_MARKET.search(m)}
    out["moneyline_markets"] = len(ml)
    out["line_markets"] = len(line)
    out["moneyline_rows"] = sum(len(v) for v in ml.values())
    out["line_rows"] = sum(len(v) for v in line.values())
    out["de_vigged"] = False  # odds-gaps.py stores ONE side's RAW 1/price; the vig is never removed
    out["abs_book_implied_gt_0_95_rows"] = sum(1 for r in rows if abs(r["bookImplied"]) > 0.95)

    last = snapshot_index(list(by_market))
    out["markets_found_in_db"] = len(last)

    # ---- the side test, which decides whether any "gap" is readable ----
    same = [abs(r["bookImplied"] - r["pmProb"]) for rs in ml.values() for r in rs]
    flip = [abs(r["bookImplied"] - (1 - r["pmProb"])) for rs in ml.values() for r in rs]
    closer_flip = sum(1 for a, b in zip(same, flip) if b < a)
    out["side_identity"] = {
        "n_rows": len(same),
        "median_abs_gap_as_stored": round(statistics.median(same), 4),
        "median_abs_gap_flipped": round(statistics.median(flip), 4),
        "rows_closer_when_flipped": closer_flip,
        "share_closer_when_flipped": round(closer_flip / len(same), 4) if same else None,
        "verdict": ("stored pmProb is on the OPPOSITE side of the book quote"
                    if same and statistics.median(flip) < statistics.median(same) / 2 else
                    "sides consistent"),
    }

    # ---- venue settlement labels ----
    # The venue's two outcomes are printed in the order PM names them, so `prices[0]` settles the
    # FIRST-named side. We do NOT assume which stored column is on which side — the four-way matrix
    # below measures it, which is the only way to tell a disagreement from a sign convention.
    labels = fetch_labels(sorted(ml))
    labelled, unlabelled = [], []
    for mid, rs in ml.items():
        fw, sw = side_labels(labels.get(mid))
        if fw is None:
            unlabelled.append((mid, rs, None))
        else:
            labelled.append((mid, rs, fw, sw))
    out["label_basis"] = "gamma /events?slug= (closed + uma resolved + outcomePrices 1/0)"
    out["moneyline_markets_labelled"] = len(labelled)
    out["moneyline_markets_unlabelled"] = len(unlabelled)
    out["label_failures"] = collections.Counter(
        str((labels.get(m) or {}).get("status")) for m, _rs, _hw in unlabelled).most_common()

    def score(pairs):
        if not pairs:
            return None
        hits = sum(1 for p, w in pairs if (p > 0.5) == bool(w))
        return {"n": len(pairs), "hits": hits, "hit_rate": round(hits / len(pairs), 4),
                "brier": round(sum((p - w) ** 2 for p, w in pairs) / len(pairs), 4)}

    # Row level = every observation. Market level = the first observation per market (the pre-match
    # entry read the card's note quoted).
    m_pm_f, m_book_f, m_pm_s, m_book_s = [], [], [], []
    r_pm_f, r_book_f = [], []
    prematch = []
    for mid, rs, fw, sw in labelled:
        rs_sorted = sorted(rs, key=lambda r: r["ts"])
        f = rs_sorted[0]
        m_pm_f.append((f["pmProb"], fw))
        m_book_f.append((f["bookImplied"], fw))
        m_pm_s.append((f["pmProb"], sw))
        m_book_s.append((f["bookImplied"], sw))
        for r in rs_sorted:
            r_pm_f.append((r["pmProb"], fw))
            r_book_f.append((r["bookImplied"], fw))
        ct = f.get("commenceTime")
        if ct and f["ts"] < ct:
            prematch.append((mid, f, fw))

    # THE MAPPING MATRIX: which stored column prices which side. A correct mapping shows a HIGH
    # hit rate on the matching arm and a LOW one on the crossed arm.
    out["mapping_matrix_market_level"] = {
        "pmProb_vs_first_named_won": score(m_pm_f),
        "pmProb_vs_second_named_won": score(m_pm_s),
        "bookImplied_vs_second_named_won": score(m_book_s),
        "bookImplied_vs_first_named_won": score(m_book_f),
    }
    out["row_level_pmProb_vs_first_named_won"] = score(r_pm_f)
    out["row_level_bookImplied_vs_first_named_won"] = score(r_book_f)

    # Side-corrected comparison: put the book on the FIRST-named side (1 - bookImplied if the
    # matrix says book priced the second-named side) and score both venues against the same target.
    book_on_first = [(1 - f["bookImplied"], fw) for _m, f, fw in prematch] if prematch else []
    out["prematch_first_obs_market_level"] = {
        "markets": len(prematch),
        "pm_as_stored": score([(f["pmProb"], fw) for _m, f, fw in prematch]),
        "book_side_corrected": score(book_on_first),
        "note": "target = first-named side won; both arms on that side; book mapped by the matrix",
    }

    # do the two venues agree on the FAVOURITE once the sides are put on one basis?
    agree = sum(1 for (p, _a), (b, _c) in zip(m_pm_f, m_book_s) if (p > 0.5) == (b <= 0.5))
    out["favourite_agreement_side_corrected"] = {
        "n_agree": agree, "n_markets": len(m_pm_f),
        "rate": round(agree / len(m_pm_f), 4) if m_pm_f else None,
    }

    json.dump(out, open(OUT, "w"), indent=2)

    print(f"corpus: {out['rows']} rows / {out['distinct_markets']} markets, "
          f"{out['first_ts'][:10]} -> {out['last_ts'][:10]}, sports={list(out['sports'])}")
    print(f"pairing: {out['moneyline_rows']} rows / {out['moneyline_markets']} moneyline markets | "
          f"{out['line_rows']} rows / {out['line_markets']} LINE markets = "
          f"{100 * out['line_rows'] / out['rows']:.1f}% of the corpus")
    print(f"junk quotes |bookImplied|>0.95: {out['abs_book_implied_gt_0_95_rows']} rows")
    print(f"side identity: {json.dumps(out['side_identity'])}")
    print(f"labels: {len(labelled)} labelled / {len(unlabelled)} unlabelled "
          f"(basis: venue gamma resolution)")
    for k in ("mapping_matrix_market_level", "prematch_first_obs_market_level"):
        print(f"{k}: {json.dumps(out[k])}")
    print(f"favourite agreement (side-corrected): "
          f"{json.dumps(out['favourite_agreement_side_corrected'])}")
    print(f"-> {os.path.relpath(OUT, ROOT)}")
    return 0


if __name__ == "__main__":
    import urllib.parse  # noqa: E402 — used by fetch_labels
    sys.exit(main())
