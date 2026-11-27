#!/usr/bin/env python3
"""congress-polarity-dryrun.py — READ-ONLY instrument for the
`sentiment-keyword-table-constant` Lane A proposal.

Answers three questions without writing anything:

  1. STORED REPLAY  (~/polymarket-copybot/prisma/dev.db, read-only/immutable)
     What does the current `analyze_bill_title()` produce on every congress row
     the book has ever received, and what would a per-item action scorer have
     produced instead? Polarity variance, per-category constants, misroutes.

  2. LIVE YIELD     (congress.gov v3, read-only GETs)
     With the proposed scorer, how many opinionated items does a run actually
     yield — from the Congress the bot polls today (118) versus the current one?
     That is the difference between "a direction" and "a different constant".

  3. SIGN-TEST MIRROR
     A global sign flip of a near-constant feed inverts the sign-test cohorts.
     Reported so nobody mistakes the mirror for evidence.

Nothing here writes to the DB, the RuleSet, or the research bot. It reads
prisma/dev.db with immutable=1 and prints; --json writes one artifact under
data/ (regenerable).

Usage:
  python3 scripts/congress-polarity-dryrun.py --self-test
  python3 scripts/congress-polarity-dryrun.py --stored
  python3 scripts/congress-polarity-dryrun.py --live
  python3 scripts/congress-polarity-dryrun.py --all --json
"""
import argparse
import collections
import datetime
import hashlib
import json
import os
import re
import sys

DB = os.path.expanduser("~/polymarket-copybot/prisma/dev.db")
ARTIFACT = os.path.expanduser("~/polymarket-copybot/data/congress-polarity-dryrun.json")
OPINIONATED = 0.3          # the aggregator's threshold (sentiment.ts)
FRESH_DAYS = 30            # an action older than this is history, not news
# The measurement clock. Pinned so a re-run reproduces the published figures;
# the live path would use date.today().
NOW_DATE = datetime.date(2026, 11, 16)

# ---------------------------------------------------------------- scoring ---

# Categories mirror src/lib/research-categories.ts (the READER's vocabulary).
# Word boundaries: the live table matches raw substrings, so "secretary" ->
# Crypto ("sec") and "Vichai " -> Tech/AI ("ai ").
CATEGORY_RULES = [
    ("Crypto", r"\b(crypto|bitcoin|ethereum|solana|xrp|stablecoin|digital assets?|sec|cftc|coinbase|binance|dogecoin)\b"),
    ("Tech/AI", r"\b(ai|artificial intelligence|openai|anthropic|chatgpt|nvidia|semiconductor|chips act|tech giants?)\b"),
    ("Defense/Geopolitics", r"\b(ukraine|russia|israel|iran|defense|defence|military|nato|taiwan|ceasefire|invasion|missile)\b"),
    ("Healthcare", r"\b(fda|medicare|medicaid|vaccine|health|obamacare|abortion|drug prices?|pharma|pandemic)\b"),
    ("Energy/Climate", r"\b(climate|epa|oil|energy|renewable|fossil fuel|emissions|carbon|paris agreement)\b"),
    ("Finance", r"\b(fed|federal reserve|rate cut|rate hike|interest rate|inflation|cpi|recession|gdp|treasury|stock market|dow jones|nasdaq|tariff|tax|economy)\b"),
    ("Macro/Politics", r"\b(election|president|congress|senate|house|governor|senator|party|democrat|republican|primary|voter|vote|ballot|midterm|minister|parliament|cabinet|presidential|politician|impeach)\b"),
]
_CAT_RE = [(c, re.compile(p, re.I)) for c, p in CATEGORY_RULES]

# Simple (HRES/SRES) and concurrent (HCONRES/SCONRES) resolutions express an
# opinion and have no legal effect, so they cannot reprice anything. Joint
# resolutions (HJRES/SJRES) are kept: CRA disapprovals and constitutional
# amendments are binding instruments.
NON_BINDING_TYPES = ("hres", "sres", "hconres", "sconres")

# Ceremonial/commemorative items carry no market information at all. Dropped
# BEFORE polarity, because a commemorative resolution that "agreed to in
# Senate" would otherwise score opinionated +0.5.
CEREMONIAL = (
    "expressing support", "honoring", "honouring", "recognizing", "recognising",
    "commemorat", "designating", "congratulat", "expressing the sense",
    "acknowledg", "celebrating", "expressing appreciation", "supporting the designation",
    "national day", "heritage month", "designation of",
)

# Action-class polarity. The operative signal is the LATEST ACTION, not the
# title: a bill referred to committee is at its base rate (no news).
ACTION_CLASSES = [
    ("became_law", ("became public law", "signed by president"), 0.9, 0.95),
    ("passed_chamber", ("passed senate", "passed house", "agreed to in the house",
                        "agreed to in the senate", "agreed to without amendment",
                        "agreed to by voice vote", "agreed to by unanimous consent",
                        "concurred in"), 0.5, 0.85),
    ("reported", ("ordered to be reported", "reported by the committee",
                  "placed on the union calendar", "placed on the senate legislative calendar",
                  "reported with an amendment"), 0.3, 0.70),
    ("blocked", ("failed", "rejected", "vetoed", "motion to table", "cloture not invoked",
                 "not invoked", "motion to recommit"), -0.7, 0.85),
    # Base rate: introduced / referred / read twice / held at the desk. NOT news.
    ("not_advanced", ("referred to", "read twice", "held at the desk", "received in the senate",
                      "introduced in"), 0.0, 0.70),
    ("procedural", ("cloture", "motion to proceed", "quorum", "unanimous consent"), 0.0, 0.60),
]


# Explicit policy-subject map: extends the reader's market vocabulary to the
# SUBJECT language bills actually use. Still no catch-all — an unmatched bill is
# dropped, because no market bucket means no market for it to inform.
# Order matters: 'veterans health' is Healthcare, bare 'veteran' is Defense.
SUBJECT_MAP = [
    ("Healthcare", ("health", "medic", "drug", "hospital", "disease", "nih", "cdc",
                    "vaccine", "patient", "nurse", "mental", "cancer", "opioid",
                    "medicaid", "medicare")),
    ("Crypto", ("digital asset", "blockchain", "crypto", "stablecoin", "virtual currency",
                "tokenized", "tokeniz")),
    ("Tech/AI", ("artificial intelligence", "semiconductor", "broadband", "data privacy",
                 "cyber", "internet", "telecommunication", "spectrum", "software",
                 "algorithm", "autonomous")),
    ("Energy/Climate", ("energy", "climate", "environment", "solar", "wind power", "nuclear",
                        "oil", "natural gas", "conservation", "forest", "wildfire",
                        "clean air", "clean water", "emission", "electric", "grid")),
    ("Defense/Geopolitics", ("armed services", "defense", "military", "veteran", "foreign relation",
                             "sanction", "state department", "homeland security", "border",
                             "intelligence", "nato", "arms control", "coast guard")),
    ("Finance", ("tax", "bank", "securit", "budget", "appropriation", "irs", "debt", "tariff",
                 "insurance", "credit", "loan", "small business", "audit", "accounting",
                 "investor", "financial", "securities")),
    ("Macro/Politics", ("election", "campaign", "voting", "congressional", "impeach", "redistrict",
                        "federal employee", "civil service", "census", "ethics", "lobby",
                        "government", "federal agency")),
]


print("[basis EXIT: card §5 sign test, realizedPnl sign on the settled leg -- every hit/win-rate column this script prints]")

def action_class(action_text):
    """-> (class_name, polarity, confidence). Unmatched -> neutral."""
    t = (action_text or "").lower()
    for name, needles, pol, conf in ACTION_CLASSES:
        if any(n in t for n in needles):
            return name, pol, conf
    return "other", 0.0, 0.60


def is_ceremonial(title):
    tl = (title or "").lower()
    return any(k in tl for k in CEREMONIAL)


def classify_category(title, mode="reader"):
    """Corrected category: reader vocabulary with word boundaries.

    mode="reader"        — src/lib/research-categories.ts vocabulary only; an
                           unmatched bill is DROPPED (the reader never routes it
                           to a market, so there is nothing for it to inform).
    mode="reader+subject"— plus an explicit policy-subject map, so a veterans'
                           health bill reaches Healthcare instead of nothing.
                           Unmatched is still dropped: no catch-all bucket.
    """
    for cat, rx in _CAT_RE:
        if rx.search(title or ""):
            return cat
    if mode == "reader+subject":
        tl = (title or "").lower()
        for cat, needles in SUBJECT_MAP:
            if any(n in tl for n in needles):
                return cat
    return None


# ---- the code that runs today, reproduced exactly (congress_api.py:17-32) ----
def legacy_score(title):
    tl = (title or "").lower()
    if any(k in tl for k in ['crypto', 'blockchain', 'digital asset', 'sec']):
        return "Crypto", (0.9 if ("innovation" in tl or "clarity" in tl) else -0.9)
    if any(k in tl for k in ['ai ', 'artificial intelligence', 'semiconductor']):
        return "Tech/AI", 0.8
    if any(k in tl for k in ['defense', 'military', 'ukraine', 'israel', 'taiwan']):
        return "Defense/Geopolitics", 0.85
    if any(k in tl for k in ['health', 'fda', 'medicare']):
        return "Healthcare", 0.7
    if any(k in tl for k in ['banking', 'reserve', 'interest rate', 'tax']):
        return "Finance", (-0.7 if "tax" in tl else 0.7)
    return "Macro/Politics", 0.5


def legacy_confidence(action_text):
    al = (action_text or "").lower()
    if "became public law" in al or "signed by president" in al:
        return 0.95
    if "passed senate" in al or "passed house" in al:
        return 0.85
    if "committee" in al:
        return 0.70
    return 0.60


def legacy_row(title, action_text):
    """Full legacy payload semantics, including the passage magnitude bump."""
    cat, base = legacy_score(title)
    conf = legacy_confidence(action_text)
    al = (action_text or "").lower()
    if "became public law" in al or "signed by president" in al:
        base = 1.0 if base > 0 else -1.0
    elif "passed senate" in al or "passed house" in al:
        base = 0.9 if base > 0 else -0.9
    return cat, base, conf


def proposed_row(title, action_text, action_date, as_of, cat_mode="reader", bill_type=""):
    """The proposed scorer. Returns None when the item is not news.

    Gates, in order (cheapest first):
      1. BINDING INSTRUMENT — HRES/SRES/HCONRES/SCONRES are expressions of
         opinion with no legal effect; they cannot reprice anything.
      2. CEREMONIAL — commemorative designations honour people/places/days.
      3. ROUTE — no market bucket means no market for the item to inform.
      4. FRESHNESS — an action older than FRESH_DAYS is history, not news.
      5. POLARITY — the action class's value must clear the aggregator's own
         opinionated threshold (base-rate/procedural actions do not).
    A dropped item emits NO row (not a neutral one): a neutral row still counts
    toward the aggregator's `n` and toward `consistency`.

    `as_of` is the clock the freshness test runs against — the row's OWN
    processedAt date in a replay, never "today", or a faithful 2023 action is
    judged by a 2026 clock and every historical row looks stale.
    """
    if (bill_type or "").lower() in NON_BINDING_TYPES:
        return None
    if is_ceremonial(title):
        return None
    cat = classify_category(title, cat_mode)
    if cat is None:
        return None                     # unrouted: no category, no signal
    age = action_age_days(action_date, as_of)
    if age is None or age > FRESH_DAYS:
        return None                     # history, not news
    cls, pol, conf = action_class(action_text)
    if abs(pol) < OPINIONATED:
        return None                     # base rate / procedural: no signal
    return cat, pol, conf, cls, age


def drop_reason(title, action_text, action_date, as_of, cat_mode="reader", bill_type=""):
    """Same gates as proposed_row, returning WHICH one dropped the item."""
    if (bill_type or "").lower() in NON_BINDING_TYPES:
        return "non_binding_resolution"
    if is_ceremonial(title):
        return "ceremonial"
    if classify_category(title, cat_mode) is None:
        return "unrouted"
    age = action_age_days(action_date, as_of)
    if age is None or age > FRESH_DAYS:
        return "stale_action"
    if abs(action_class(action_text)[1]) < OPINIONATED:
        return "not_news"
    return ""


def action_age_days(action_date, today):
    try:
        y, m, d = [int(x) for x in str(action_date)[:10].split("-")]
        return (today - datetime.date(y, m, d)).days
    except Exception:
        return None


def row_date(row):
    """The row's own ingest date (UTC) — the clock a replay must use."""
    try:
        return datetime.datetime.utcfromtimestamp(float(row["ts"]) / 1000.0).date()
    except Exception:
        return datetime.date(2026, 11, 16)


def rate_of(score):
    return 1.0 if (score or 0) > 0 else (-1.0 if (score or 0) < 0 else 0.0)


# ------------------------------------------------------------- self-test ---
def self_test():
    ok = fail = 0

    def check(name, got, want):
        nonlocal ok, fail
        if got == want:
            ok += 1
        else:
            fail += 1
            print("  FAIL %-58s got=%r want=%r" % (name, got, want))

    check("legacy: commemorative -> Macro +0.50",
          legacy_row("Honoring the legacy of the Harlem Renaissance", "Referred to the House Committee")[:2],
          ("Macro/Politics", 0.5))
    check("legacy: 'Secretary' substring routes to Crypto",
          legacy_row("To require the Secretary of Agriculture to convey land", "Referred to committee")[0], "Crypto")
    check("legacy: 'Vichai ' substring routes to Tech/AI",
          legacy_row("A bill for the relief of Vichai Sae Tung", "Referred to committee")[0], "Tech/AI")
    check("legacy: became-law bumps magnitude to 1.0",
          legacy_row("Some Act", "Became Public Law No: 118-1.")[1], 1.0)

    check("new: word boundary keeps 'Secretary' out of Crypto",
          classify_category("To require the Secretary of Agriculture to convey land"), None)
    check("new: 'SEC' as a word still routes",
          classify_category("To amend the securities laws and empower the SEC"), "Crypto")
    check("new: no default bucket for an unrouted bill",
          classify_category("Janie Wynn Protecting Elders from Financial Exploitation Act"), None)
    check("new: ceremonial gate",
          is_ceremonial("Expressing support for the designation of national Chuck Brown Day"), True)
    check("new: 'recognizing a person' is ceremonial",
          is_ceremonial("Recognizing the significance of Chicano Heritage Month"), True)

    t = datetime.date(2026, 11, 16)
    check("new: referred-to-committee is NOT news",
          proposed_row("Nuclear Energy Innovation Act", "Referred to the Committee on Energy and Commerce.",
                       "2026-11-10", t), None)
    check("new: passage IS news",
          proposed_row("Crypto Clarity Act", "Passed Senate by voice vote.", "2026-11-10", t),
          ("Crypto", 0.5, 0.85, "passed_chamber", 6))
    check("new: became-law polarity/conf",
          proposed_row("Digital Asset Market Structure Act", "Became Public Law No: 119-4.", "2026-11-12", t),
          ("Crypto", 0.9, 0.95, "became_law", 4))
    check("new: stale passage is history",
          proposed_row("Crypto Clarity Act", "Passed Senate.", "2024-04-11", t), None)
    check("new: blocked is negative",
          proposed_row("Tax Increase Act", "Motion to table agreed to. Failed Senate passage.", "2026-11-01", t)[1], -0.7)
    check("new: ceremonial that passed is still dropped",
          proposed_row("A resolution supporting the designation of International Day",
                       "Resolution agreed to in Senate without amendment", "2026-11-10", t), None)
    check("new: SRES dropped as non-binding even when substantive",
          proposed_row("A resolution expressing the sense of the Senate on tariffs",
                       "Resolution agreed to in Senate without amendment", "2026-11-10", t, "reader", "SRES"),
          None)
    check("new: HJRES kept (binding instrument)",
          proposed_row("Providing for congressional disapproval of the SEC rule on climate disclosure",
                       "Passed Senate by voice vote.", "2026-11-10", t, "reader", "HJRES"),
          ("Crypto", 0.5, 0.85, "passed_chamber", 6))
    check("drop_reason names the first failing gate",
          drop_reason("A resolution expressing the sense of the Senate on tariffs",
                      "Resolution agreed to in Senate", "2026-11-10", t, "reader", "SRES"),
          "non_binding_resolution")
    check("drop_reason: stale beats not-news",
          drop_reason("Crypto Clarity Act", "Referred to committee.", "2024-01-01", t, "reader", "HR"),
          "stale_action")

    print("self-test: %d passed, %d failed" % (ok, fail))
    return fail == 0


# --------------------------------------------------------- stored replay ---
def load_stored():
    import sqlite3
    con = sqlite3.connect("file:%s?immutable=1" % DB, uri=True)
    rows = con.execute(
        "SELECT processedAt, marketCategory, sentimentScore, confidence, rawPayload "
        "FROM RegulatorySignal WHERE source='congress_gov_api' ORDER BY processedAt"
    ).fetchall()
    con.close()
    out = []
    for ts, cat, score, conf, raw in rows:
        try:
            p = json.loads(raw)
        except Exception:
            continue
        la = p.get("latestAction") or {}
        out.append({
            "ts": ts, "cat": cat, "score": score, "conf": conf,
            "title": p.get("title") or "", "action": la.get("text") or "",
            "action_date": la.get("actionDate") or "",
            "type": p.get("type") or "", "number": p.get("number") or "",
        })
    return out


def stored_report(rows, now_ms):
    res = {}
    print("\n" + "=" * 78)
    print("1. STORED REPLAY — %d congress_gov_api rows" % len(rows))
    print("=" * 78)

    # ---- what the feed holds today
    by_cat = collections.defaultdict(collections.Counter)
    for r in rows:
        by_cat[r["cat"]][r["score"]] += 1
    total = float(len(rows))
    print("\n-- today (as stored) --")
    for cat in sorted(by_cat):
        c = by_cat[cat]
        n = sum(c.values())
        modal, mn = c.most_common(1)[0]
        print("   %-20s n=%-5d distinct_polarity=%d  modal=%+.2f (%.1f%%)"
              % (cat, n, len(c), modal, 100.0 * mn / n))
        res.setdefault("stored_by_cat", {})[cat] = {
            "rows": n, "distinct": len(c), "modal": modal, "modal_share": mn / n}
    allc = collections.Counter(r["score"] for r in rows)
    print("   all-time modal polarity %+.2f = %.1f%% of rows"
          % (allc.most_common(1)[0][0], 100.0 * allc.most_common(1)[0][1] / total))
    res["stored_all_time"] = {"rows": len(rows), "modal": allc.most_common(1)[0][0],
                              "modal_share": allc.most_common(1)[0][1] / total,
                              "distinct_values": len(allc)}

    # ---- population by action class, and how old the "news" was at ingest
    cls = collections.Counter()
    ages = []
    for r in rows:
        cls[action_class(r["action"])[0]] += 1
        a = action_age_days(r["action_date"], row_date(r))
        if a is not None:
            ages.append(a)
    ages.sort()
    print("\n-- population by action class (legacy feed) --")
    for k, v in cls.most_common():
        print("   %-14s %5d  (%.1f%%)" % (k, v, 100.0 * v / total))
    if ages:
        print("   action age AT INGEST: median %d d, p90 %d d, fresh<=%dd: %d (%.1f%%)"
              % (ages[len(ages) // 2], ages[int(len(ages) * 0.9)], FRESH_DAYS,
                 len([a for a in ages if a <= FRESH_DAYS]),
                 100.0 * len([a for a in ages if a <= FRESH_DAYS]) / len(ages)))
    res["stored_action_classes"] = dict(cls)
    res["action_age_at_ingest"] = {
        "n": len(ages), "median": ages[len(ages) // 2] if ages else None,
        "p90": ages[int(len(ages) * 0.9)] if ages else None,
        "fresh_share": (len([a for a in ages if a <= FRESH_DAYS]) / len(ages)) if ages else None,
    }

    # ---- proposed scorer, same rows, both category modes
    for mode in ("reader", "reader+subject"):
        keep = collections.Counter()
        prop_by_cat = collections.defaultdict(collections.Counter)
        drops = collections.Counter()
        changed_cat = 0
        cover = 0
        for r in rows:
            as_of = row_date(r)
            nm = classify_category(r["title"], mode)
            if nm is not None:
                cover += 1
                if nm != r["cat"]:
                    changed_cat += 1
            p = proposed_row(r["title"], r["action"], r["action_date"], as_of, mode, r["type"])
            if p is None:
                drops[drop_reason(r["title"], r["action"], r["action_date"], as_of, mode, r["type"])] += 1
                continue
            cat, pol, conf, c, age = p
            prop_by_cat[cat][pol] += 1
            keep[c] += 1
            if cat != r["cat"]:
                changed_cat += 1
        kept = sum(keep.values())
        print("\n-- proposed scorer on the SAME rows [category mode = %s] --" % mode)
        print("   routed (category assigned): %d/%d (%.1f%%)"
              % (cover, len(rows), 100.0 * cover / total))
        print("   kept %d of %d (%.2f%%) | dropped: %s"
              % (kept, len(rows), 100.0 * kept / total, dict(drops)))
        print("   kept by action class: %s" % dict(keep))
        print("   rows whose CATEGORY changes vs stored: %d" % changed_cat)
        for cat in sorted(prop_by_cat):
            c = prop_by_cat[cat]
            print("   %-20s n=%-4d values=%s"
                  % (cat, sum(c.values()), {("%+.2f" % k): v for k, v in sorted(c.items())}))
        res["proposed_" + mode] = {
            "routed": cover, "kept": kept, "dropped": dict(drops), "by_class": dict(keep),
            "category_changes": changed_cat,
            "by_cat": {c: {("%+.2f" % k): v for k, v in sorted(d.items())} for c, d in prop_by_cat.items()},
        }

    # ---- category-misroute examples under the legacy table
    mis = collections.Counter()
    for r in rows:
        new_cat = classify_category(r["title"], "reader")
        if new_cat != r["cat"]:
            mis[(r["cat"], new_cat or "<unrouted>")] += 1
    print("\n-- legacy category vs corrected category (all rows, reader vocabulary) --")
    for (old, new), n in mis.most_common(8):
        print("   %-20s -> %-20s %5d" % (old, new, n))
    res["misroutes"] = {"%s->%s" % k: v for k, v in mis.most_common()}

    # ---- does the stored feed keep exactly one polarity inside a category?
    print("\n-- the constancy test the aggregator needs (per category, 7d) --")
    wk = now_ms - 7 * 86400 * 1000
    w = collections.defaultdict(collections.Counter)
    for r in rows:
        if r["ts"] and float(r["ts"]) >= wk and abs(r["score"]) >= OPINIONATED:
            w[r["cat"]][r["score"]] += 1
    for cat in sorted(w):
        c = w[cat]
        print("   7d %-18s rows=%-4d distinct_polarity=%d %s"
              % (cat, sum(c.values()), len(c), dict(c)))
    res["stored_7d"] = {c: {"rows": sum(d.values()), "distinct": len(d), "values":
                            {("%+.2f" % k): v for k, v in d.items()}} for c, d in w.items()}
    return res


# ------------------------------------------------------------- live yield ---
def load_key():
    for line in open(os.path.expanduser("~/.hermes/.env")):
        line = line.strip()
        if line.startswith("CONGRESS_GOV_API_KEY="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    return None


def http_get(url, key):
    import urllib.request
    import urllib.error
    req = urllib.request.Request(url, headers={
        "accept": "application/json", "x-api-key": key or "",
        "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()[:200]
    except Exception as e:
        return -1, str(e)[:200]


def live_report(limit, key, pages=1, cat_mode="reader"):
    res = {}
    today = datetime.date(2026, 11, 16)
    print("\n" + "=" * 78)
    print("2. LIVE YIELD — congress.gov v3 bill list, %d page(s) of %d, sort=updateDate desc,"
          " category mode=%s" % (pages, limit, cat_mode))
    print("=" * 78)
    for cong in (118, 119):
        bills = []
        st_seen = None
        for pg in range(pages):
            url = ("https://api.congress.gov/v3/bill/%d?limit=%d&offset=%d&sort=updateDate+desc"
                   % (cong, limit, pg * limit))
            st, body = http_get(url, key)
            if st != 200:
                print("   congress %d page %d: HTTP %s %s" % (cong, pg, st, body))
                st_seen = st
                break
            bills.extend(body.get("bills", []))
        if st_seen or not bills:
            continue
        cls = collections.Counter()
        ages = []
        kept = collections.defaultdict(list)
        drops = collections.Counter()
        sign_split = collections.Counter()
        seen = set()
        dupes = 0
        for b in bills:
            la = b.get("latestAction") or {}
            t, num = b.get("type") or "", b.get("number") or ""
            adate = la.get("actionDate") or ""
            k = (cong, t, num, adate)
            if k in seen:
                dupes += 1
            seen.add(k)
            _c, _p, _cf = action_class(la.get("text"))
            cls[_c] += 1
            if abs(_p) >= OPINIONATED:
                sign_split["+" if _p > 0 else "-"] += 1
            a = action_age_days(adate, today)
            if a is not None:
                ages.append(a)
            title = b.get("title") or ""
            act = la.get("text") or ""
            p = proposed_row(title, act, adate, today, cat_mode, t)
            if p:
                kept[p[0]].append((("%s%s" % (t, num)), p[1], p[2], p[3], a, title[:70], act[:50]))
            else:
                drops[drop_reason(title, act, adate, today, cat_mode, t)] += 1
        n = len(bills)
        ages.sort()
        nkeep = sum(len(v) for v in kept.values())
        print("\n   congress %d: %d bills | action age median=%s | fresh<=7d %d | <=30d %d"
              % (cong, n, (ages[len(ages) // 2] if ages else "?"),
                 len([a for a in ages if a <= 7]), len([a for a in ages if a <= 30])))
        print("     action classes: %s" % dict(cls.most_common()))
        print("     sign split of items that are opinionated BY ACTION: +%d / -%d"
              % (sign_split["+"], sign_split["-"]))
        print("     DROP FUNNEL: %s" % dict(drops.most_common()))
        print("     proposed scorer keeps %d (%.2f%%) | duplicate (bill,actionDate) keys %d"
              % (nkeep, 100.0 * nkeep / max(1, n), dupes))
        for cat in sorted(kept):
            vals = collections.Counter(round(x[1], 2) for x in kept[cat])
            print("     %-20s n=%-3d values=%s" % (cat, len(kept[cat]),
                                                  {("%+.2f" % k): v for k, v in sorted(vals.items())}))
            for row in kept[cat][:6]:
                print("        %-9s %+.2f conf=%.2f %-14s age=%-4s %s | %s" % row)
        res["congress_%d" % cong] = {
            "bills": n, "fresh_7d": len([a for a in ages if a <= 7]),
            "fresh_30d": len([a for a in ages if a <= 30]),
            "classes": dict(cls), "kept": nkeep, "drop_funnel": dict(drops),
            "dupe_keys": dupes,
            "by_cat": {c: {("%+.2f" % k): v for k, v in
                           collections.Counter(round(x[1], 2) for x in kept[c]).items()} for c in kept},
            "items": {c: [{"bill": x[0], "pol": x[1], "cls": x[3], "age": x[4], "title": x[5]}
                          for x in kept[c]] for c in kept},
        }
    return res


# ------------------------------------------- sensitivity + policyArea route ---
def load_bills(cong, pages, limit, key):
    bills = []
    for pg in range(pages):
        st, body = http_get(
            "https://api.congress.gov/v3/bill/%d?limit=%d&offset=%d&sort=updateDate+desc"
            % (cong, limit, pg * limit), key)
        if st != 200:
            print("   congress %d page %d: HTTP %s %s" % (cong, pg, st, body))
            return bills
        bills.extend(body.get("bills", []))
    return bills


def sensitivity_report(congresses, pages, limit, key, windows=(7, 30, 90, 365)):
    """Yield vs (freshness window, routing vocabulary) — the §2.5 table."""
    res = {}
    print("\n" + "=" * 78)
    print("2b. SENSITIVITY — kept opinionated items per %d polled bills"
          % (limit * pages))
    print("=" * 78)
    cache = {c: load_bills(c, pages, limit, key) for c in congresses}
    print("%-7s %-16s %s" % ("cong", "routing", "  ".join("%4dd" % w for w in windows)))
    for cong in congresses:
        for mode in ("reader", "reader+subject"):
            row = []
            for fd in windows:
                keep = FRESH_DAYS
                try:
                    globals()["FRESH_DAYS"] = fd
                    n = 0
                    for b in cache[cong]:
                        la = b.get("latestAction") or {}
                        if proposed_row(b.get("title") or "", la.get("text") or "",
                                        la.get("actionDate") or "", NOW_DATE, mode, b.get("type")):
                            n += 1
                    row.append(n)
                finally:
                    globals()["FRESH_DAYS"] = keep
            print("%-7d %-16s %s" % (cong, mode, "  ".join("%5d" % v for v in row)))
            res["congress_%d_%s" % (cong, mode)] = dict(zip([str(w) for w in windows], row))
    print("\n  (the same sample the live report uses; a bill re-polled in a later run is"
          " de-duplicated by the ledger, so these are events, not emissions)")
    return res


# Subject-level mapping used ONLY for the measurement in §2.5 — it routes the
# API's policyArea onto our seven market buckets as a reader would, including
# Public Lands -> Energy/Climate, and the point of the measurement is that this
# is what a "correct" table looks like while still being meaningless.
PA_TO_BUCKET_MEASURE = {
    "Health": "Healthcare",
    "Finance and Financial Sector": "Finance", "Taxation": "Finance",
    "Economics and Public Finance": "Finance", "Foreign Trade and International Finance": "Finance",
    "Energy": "Energy/Climate", "Environmental Protection": "Energy/Climate",
    "Water Resources Development": "Energy/Climate",
    "Public Lands and Natural Resources": "Energy/Climate",
    "Armed Forces and National Security": "Defense/Geopolitics",
    "International Affairs": "Defense/Geopolitics", "Immigration": "Defense/Geopolitics",
    "Science, Technology, Communications": "Tech/AI",
    "Government Operations and Politics": "Macro/Politics", "Congress": "Macro/Politics",
    "Civil Rights and Liberties, Minority Issues": "Macro/Politics",
    "Crime and Law Enforcement": "Macro/Politics", "Education": "Macro/Politics",
    "Labor and Employment": "Macro/Politics", "Social Welfare": "Macro/Politics",
    "Housing and Community Development": "Macro/Politics", "Emergency Management": "Macro/Politics",
    "Agriculture and Food": "Macro/Politics", "Transportation and Public Works": "Macro/Politics",
    "Commerce": "Macro/Politics", "Law": "Macro/Politics", "Native Americans": "Macro/Politics",
}


def routing_report(cong, pages, limit, key):
    """Candidates routed by the API's controlled vocabulary (§2.5 detail table)."""
    res = {}
    print("\n" + "=" * 78)
    print("2c. policyArea ROUTING — congress %d, %d bills" % (cong, limit * pages))
    print("=" * 78)
    bills = load_bills(cong, pages, limit, key)
    cands = []
    for b in bills:
        t = b.get("type") or ""
        la = b.get("latestAction") or {}
        if t.lower() in NON_BINDING_TYPES:
            continue
        cls, pol, conf = action_class(la.get("text"))
        if abs(pol) < OPINIONATED:
            continue
        age = action_age_days(la.get("actionDate"), NOW_DATE)
        if age is None or age > 30:
            continue
        cands.append((b, pol, cls, age))
    print("   %d bills -> %d candidates (binding + fresh<=30d + opinionated action)"
          % (len(bills), len(cands)))
    buckets = collections.defaultdict(list)
    unrouted = []
    subj_populated = 0
    for b, pol, cls, age in cands:
        st, d = http_get("https://api.congress.gov/v3/bill/%d/%s/%s?format=json"
                         % (cong, (b.get("type") or "").lower(), b.get("number")), key)
        if st != 200:
            print("   detail HTTP %s for %s%s" % (st, b.get("type"), b.get("number")))
            continue
        bb = d.get("bill") or {}
        if ((bb.get("subjects") or {}).get("legislativeSubjects") or []):
            subj_populated += 1
        pa = ((bb.get("policyArea") or {}) or {}).get("name")
        rec = (b.get("type") + str(b.get("number")), pol, cls, age, pa, (b.get("title") or "")[:62])
        bucket = PA_TO_BUCKET_MEASURE.get(pa)
        if bucket is None:
            unrouted.append(rec)
        else:
            buckets[bucket].append(rec)
    print("   legislativeSubjects populated: %d of %d" % (subj_populated, len(cands)))
    for bk in sorted(buckets):
        signs = collections.Counter("+" if r[1] > 0 else "-" for r in buckets[bk])
        print("   %-22s n=%d %s" % (bk, len(buckets[bk]), dict(signs)))
        for r in buckets[bk][:5]:
            print("        %-9s %+.2f %-14s age=%-3s %-38s %s" % r)
    print("   unrouted by policyArea: %d" % len(unrouted))
    for r in unrouted[:4]:
        print("        %-9s %+.2f %-14s age=%-3s %-38s %s" % r)
    res["candidates"] = len(cands)
    res["buckets"] = {k: [{"bill": x[0], "pol": x[1], "cls": x[2], "age": x[3],
                           "policyArea": x[4], "title": x[5]} for x in v] for k, v in buckets.items()}
    res["unrouted"] = [{"bill": x[0], "pol": x[1], "policyArea": x[4], "title": x[5]} for x in unrouted]
    return res


# ------------------------------------------------------- sign-test mirror ---
def mirror_report():
    """A near-constant feed flips cohort identities wholesale. Arithmetic on the
    card's own sign test (drafts/sentiment-edge-single-polarity-20261116.md §5)."""
    print("\n" + "=" * 78)
    print("3. SIGN-TEST MIRROR — a global sign flip inverts the cohorts")
    print("=" * 78)
    toward = {"legs": 66, "settled": 62, "markets": 33, "hit": "11/37", "rate": 0.297,
              "edge_share": -0.08, "ci": [-0.22, 0.05]}
    against = {"legs": 53, "settled": 48, "markets": 33, "hit": "9/29", "rate": 0.310,
               "edge_share": 0.05, "ci": [-0.07, 0.20]}
    print("   as measured  : toward %+.2f/share (%.1f%% hit) | against %+.2f/share (%.1f%% hit)"
          % (toward["edge_share"], 100 * toward["rate"], against["edge_share"], 100 * against["rate"]))
    print("   after a flip : toward %+.2f/share (%.1f%% hit) | against %+.2f/share (%.1f%% hit)"
          % (against["edge_share"], 100 * against["rate"], toward["edge_share"], 100 * toward["rate"]))
    print("   -> the flipped read (%.2f/share, CI [%+.2f,%+.2f]) is the SAME two cohorts"
          % (against["edge_share"], against["ci"][0], against["ci"][1]))
    print("      relabelled, not new information: the CI still straddles zero.")
    return {"toward": toward, "against": against}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--stored", action="store_true")
    ap.add_argument("--live", action="store_true")
    ap.add_argument("--sensitivity", action="store_true")
    ap.add_argument("--routing", action="store_true")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--limit", type=int, default=250)
    ap.add_argument("--pages", type=int, default=1)
    ap.add_argument("--cat-mode", default="reader", choices=["reader", "reader+subject"])
    a = ap.parse_args()
    do_all = a.all or not (a.self_test or a.stored or a.live or a.sensitivity or a.routing)

    if a.self_test:
        sys.exit(0 if self_test() else 1)

    out = {}
    out["generated_at"] = datetime.datetime.now().isoformat(timespec="seconds")
    if do_all or a.stored:
        now_ms = datetime.datetime(2026, 11, 16, 22, 30).timestamp() * 1000
        out["stored"] = stored_report(load_stored(), now_ms)
    if do_all or a.live or a.sensitivity or a.routing:
        key = load_key()
        if not key:
            print("\n[skip live] CONGRESS_GOV_API_KEY missing from ~/.hermes/.env")
        else:
            if do_all or a.live:
                out["live"] = live_report(a.limit, key, a.pages, a.cat_mode)
            if do_all or a.sensitivity:
                out["sensitivity"] = sensitivity_report((118, 119), a.pages, a.limit, key)
            if do_all or a.routing:
                out["routing_119"] = routing_report(119, a.pages, a.limit, key)
    if do_all:
        out["mirror"] = mirror_report()

    if a.json:
        os.makedirs(os.path.dirname(ARTIFACT), exist_ok=True)
        with open(ARTIFACT, "w") as f:
            json.dump(out, f, indent=2, default=str)
        print("\nwrote %s" % ARTIFACT)


if __name__ == "__main__":
    main()
