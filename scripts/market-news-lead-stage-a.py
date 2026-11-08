#!/usr/bin/env python3
"""market-news-lead-stage-a -- STAGE A (map quality) of the market->news lead test.

Card: `market-to-news-lead-test` (Backlog; carded 2026-09-18). Its STAGE A is the gate that
decides everything: (1) entity-extraction precision >=85% on a hand-labelled 50-market sample,
(2) coverage reach >=20 markets/day with a resolved entity map AND >=5 news items per market
per week. STAGE B (the lead test itself) is NOT run here and must not be until A passes.

WHAT THIS ANSWERS, AND ONLY THIS: can we resolve a live market's OWN proposition to a specific
named entity that the news index actually carries on a repeated basis? Nothing about price.

PRE-REGISTERED EXTRACTION DOCTRINE (fixed before the audit was read -- ambiguity doctrine,
same as scripts/attention-match.py: return nothing rather than guess):
  E1. Candidates are capitalised token runs in the QUESTION itself, in original case.
  E2. A run is dropped when every token is generic market/date vocabulary (Will, Yes, Above,
      Between, Win, Spread, Price, a month, a weekday, a bare number/currency token).
  E3. A SINGLE-token run is dropped when its casefold is an ordinary English word
      (/usr/share/dict/words) -- "Magic", "Liberty", "Rockets", "Giants", "Trump", "Musk",
      "Tide", "Heat" are team/actor nicknames whose referent cannot be established from the
      question alone. Acronyms (2-5 A-Z chars) survive this test.
  E4. A multi-token run keeps only its leading specific part; trailing generic tokens are cut.
  E5. AMBIGUITY CAP: an entity that resolves more than AMBIGUITY_MAX live markets at the fetch
      clock is not a proposition, it is a theme (the card's own words). Markets whose every
      candidate is over the cap get NO map (reason=ambiguous), and are counted, not hidden.
  E6. Abstention is free; a wrong map is not. The precision gate is measured over MAPPED
      markets only, so a low yield cannot be laundered as high precision.

BASIS (stated, never implied):
  population = live Polymarket markets, active & closed=false, ordered by 24h volume desc,
               first UNIVERSE_N (gamma), fetched at the clock printed in the artifact;
  level      = one MARKET (question), entity map per market;
  clock      = market fetch time (UTC) for the map, news window for coverage (stated below);
  coverage   = per-entity news items from the Google News RSS index (keyless). SUBSTITUTION,
               declared: the card named GDELT Cloud per-entity queries, which have been
               403-dead since 2026-10-02; the keyless GDELT 2.0 EVENT export was tested and
               rejected for this purpose because its Actor1/Actor2 name fields carry countries
               and generic roles (POLICE/PRESIDENT/GOVERNMENT) and ZERO person names -- it
               cannot resolve a proposition entity. Google News RSS is per-entity, keyless,
               and carries pubDate; its ONE limit is a ~100-item cap per query, which is
               reported as saturation rather than papered over.

Read-only. Writes data/market-news-lead-stage-a.json (+ .sample.jsonl for the audit).

USAGE
  python3 scripts/market-news-lead-stage-a.py --fetch-markets        # refresh universe cache
  python3 scripts/market-news-lead-stage-a.py --sample               # emit 50-market audit sample
  python3 scripts/market-news-lead-stage-a.py --labels <path>        # score the audit + coverage
  python3 scripts/market-news-lead-stage-a.py --self-test            # prove the extractor can fail
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
CACHE = os.path.expanduser("~/.hermes/cache/scratch/mlead")
OUT = os.path.join(DATA, "market-news-lead-stage-a.json")
SAMPLE_OUT = os.path.join(DATA, "market-news-lead-stage-a.sample.jsonl")
UNIVERSE_CACHE = os.path.join(CACHE, "universe.json")
NEWS_CACHE = os.path.join(CACHE, "news")

UNIVERSE_N = 2000
SAMPLE_N = 50
AMBIGUITY_MAX = 3
NEWS_DAYS = 7              # gate basis: one week
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"

GENERIC = set("""
a an the and or but if then than that this these those for from with without into onto of on in at by to
as is are was were be been being will would shall should can could may might must do does did done not no nor
yes new says say said report reports reported after before over under again more most less least up down out
off about against between during through above below first second third fourth last next its it his her their
our your my win wins won lose loses lost draw tie game games match team teams vs versus v
price prices close closes closing open opens opening reach reaches hit hits below above under over exceed
exceed highest lowest high low best worst most fewest approval rating rate percent point points spread
exact score total total goals points money line odds favorite underdog series cup league game
how many what which who whom whose when where why whether any all other another more most same
day days week weeks month months year years today tomorrow yesterday end ends ending begin begins
on in by at from since until during before after within between
$ usd million billion thousand hundred
o u bo bo1 bo3 bo5 ot so
handicap spread total totals both teams team overs unders over under half halves quarter quarters
playoffs playoff play playin play-in group groups division divisions round rounds qualifier qualifiers
bracket finals final championship championships cup cups league leagues season seasons tournament
tournaments major majors trophy trophies classic derby awards award bowl series
box office ipo ipo'd market cap valuation valuation world international national global
grand prix grand prix race races
republicans democrats gop independents liberals conservatives
""".split())

# Competition / league / format acronyms: event context, never the proposition subject.
STRUCTURE_ACRONYMS = set("""
nba nfl nhl mlb wnba ncaa ncaaf ufc pga atp wta f1 motogp cs2 csgo lol dota iem pgl b05 b03
ufc epl ucl uel mls nwsl kbo npb cfl
""".split())

MONTHS = set("january february march april may june july august september october november december "
             "jan feb mar apr jun jul aug sep sept oct nov dec".split())
WEEKDAYS = set("monday tuesday wednesday thursday friday saturday sunday mon tue tues wed thu thur thurs fri sat sun".split())
GENERIC |= MONTHS | WEEKDAYS

# Tokens that are capitalised in questions but never a proposition subject on their own.
ROLE_NOISE = set("""
will would can could does do is are was were has have had shall should may might
mr mrs ms dr president prime minister king queen prince official officials government govt party
democratic republican labour conservative nominee nomination candidate candidates election elections
presidential primary primary democratic
the a an
""".split())

WORD_RE = re.compile(r"\([A-Z]{2,3}\)|[A-Za-z\u00C0-\u024F][A-Za-z\u00C0-\u024F'’.\-]*")
NUM_RE = re.compile(r"^[\d$%\.,]+$")


def load_words():
    path = "/usr/share/dict/words"
    out = set()
    try:
        with open(path, "r", errors="ignore") as f:
            for line in f:
                w = line.strip().lower()
                if w:
                    out.add(w)
    except OSError:
        pass
    return out


WORDS = load_words()


# Leading modifiers that are generic-looking but belong to a proper name ("New Zealand",
# "North Carolina", "Los Angeles"): the leading-generic cut must not eat them.
MODIFIERS = set("""
new north south east west upper lower greater central los las el la le san santa saudi hong sri
st saint mount fort port west mid
""".split())

# Acronyms that are never a proposition subject on their own.
THEME_ACRONYMS = set("us usa".split())


def _is_paren_code(tok: str) -> bool:
    """'(FL)' / '(NY)' following a place is a province code, never the proposition subject."""
    return bool(re.fullmatch(r"\([A-Z]{2,3}\)", tok))


def _is_plural_nickname(low: str) -> bool:
    """R1: /usr/share/dict/words has 'magic' but not 'islanders'/'eagles'/'kings' -- a bare
    PLURAL that singularises to an ordinary word is the same nickname ambiguity as E3."""
    if len(low) < 4:
        return False
    for suf, rep in (("ies", "y"), ("es", ""), ("s", "")):
        if low.endswith(suf):
            cand = low[: len(low) - len(suf)] + rep
            if cand in WORDS:
                return True
    return False


def candidate_runs(question: str):
    """Capitalised token runs, in original case, with the doctrine applied (E1-E4)."""
    q = (question or "").strip()
    # R5: quoted content is a TITLE. Polymarket writes songs as "Title - Artist"; keep the
    # artist (the resolvable half), drop the title; a quote with no separator drops entirely.
    def _unquote(m):
        inner = m.group(0)[1:-1]
        return inner.split("\u2013")[-1].split(" - ")[-1] if ("\u2013" in inner or " - " in inner) else " "
    q = re.sub(r'"[^"]*"|\u201c[^\u201d]*\u201d', _unquote, q)
    runs = []
    cur = []
    last_end = None
    for m in WORD_RE.finditer(q):
        tok = m.group(0)
        gap = q[last_end:m.start()] if last_end is not None else ""
        # a run continues only across whitespace / a slash / a hyphen-with-space
        if cur and re.search(r"[^\s/&]", gap):
            runs.append(cur)
            cur = []
        if _is_paren_code(tok):
            continue
        if tok[0].isupper() and not NUM_RE.match(tok):
            cur.append(tok)
            last_end = m.end()
        else:
            if cur:
                runs.append(cur)
            cur = []
            last_end = m.end()
    if cur:
        runs.append(cur)

    out = []
    for run in runs:
        # single-character tokens ("Group B", "Plan A") are never a proposition subject, but a
        # MIDDLE INITIAL ("Stephen A. Smith") is part of a person name and must survive (R3).
        toks = [t for t in run
                if not _is_paren_code(t)
                and (len(t.rstrip(".")) > 1 or re.fullmatch(r"[A-Z]\.", t))]
        # R2: an apostrophe-leading fragment ("Rock' Johnson" out of "The Rock' Johnson") is a
        # broken span, not an entity
        if toks and toks[0].startswith(("'", "\u2019")):
            continue
        # R2b: a token that ENDS in an apostrophe is the other half of the same broken quote
        toks = [t for t in toks if not re.fullmatch(r"[A-Za-z\u00C0-\u024F]+['\u2019]", t)]
        if not toks:
            continue
        # E4: cut LEADING and trailing generic tokens (sentence-initial "Will", "The")
        while toks and (toks[0].lower().strip("'’.-") in GENERIC or toks[0].lower() in ROLE_NOISE) \
                and toks[0].lower().strip("'’.-") not in MODIFIERS:
            toks.pop(0)
        while toks and (toks[-1].lower().strip("'’.-") in GENERIC or toks[-1].lower() in ROLE_NOISE):
            toks.pop()
        if not toks:
            continue
        # E2: drop runs that are all generic
        if all(t.lower().strip("'’.-") in GENERIC for t in toks):
            continue
        # R4: a run headed by a competition/league acronym ("NBA MVP") is event context
        if toks[0].lower().strip(".") in STRUCTURE_ACRONYMS:
            continue
        span = " ".join(toks)
        span = span.replace(" .", ".").strip("'’.- ")
        if not span:
            continue
        # E3: single-token ordinary word -> abstain
        if len(toks) == 1:
            low = span.lower().strip("'’.")
            if low in GENERIC or low in ROLE_NOISE:
                continue
            is_acronym = bool(re.fullmatch(r"[A-Z]{2,5}", span))
            if low in STRUCTURE_ACRONYMS or low in THEME_ACRONYMS:
                continue
            if not is_acronym and (low in WORDS or _is_plural_nickname(low) or len(low) < 3):
                continue
        # drop spans that are only a month/weekday or a country-code parenthetical
        if span.lower() in MONTHS or span.lower() in WEEKDAYS:
            continue
        out.append(span)
    # dedupe preserving order
    seen = set()
    uniq = []
    for s in out:
        k = s.lower()
        if k in seen:
            continue
        seen.add(k)
        uniq.append(s)
    return uniq


def fetch_universe(n=UNIVERSE_N):
    os.makedirs(CACHE, exist_ok=True)
    rows, seen = [], set()
    off = 0
    while len(rows) < n:
        url = ("https://gamma-api.polymarket.com/markets?active=true&closed=false"
               f"&limit=100&offset={off}&order=volume24hr&ascending=false")
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=60) as f:
            batch = json.load(f)
        if not batch:
            break
        for m in batch:
            mid = m.get("id")
            if mid in seen:
                continue
            seen.add(mid)
            rows.append({
                "id": mid, "question": m.get("question"), "slug": m.get("slug"),
                "endDate": m.get("endDate"), "volume24hr": m.get("volume24hr"),
                "liquidity": m.get("liquidity"), "category": m.get("category"),
            })
            if len(rows) >= n:
                break
        off += 100
        if len(batch) < 100:
            break
        time.sleep(0.4)
    payload = {"fetched_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
               "order": "volume24hr desc", "markets": rows}
    with open(UNIVERSE_CACHE, "w") as f:
        json.dump(payload, f)
    return payload


def load_universe(refetch=False):
    if refetch or not os.path.exists(UNIVERSE_CACHE):
        return fetch_universe()
    with open(UNIVERSE_CACHE) as f:
        return json.load(f)


def build_maps(universe, ambiguity_max=AMBIGUITY_MAX):
    """Entity map per market + the ambiguity census (E5)."""
    markets = universe["markets"]
    cands = {m["id"]: candidate_runs(m["question"]) for m in markets}
    # market-count per candidate entity (casefold) -> E5 cap
    support = Counter()
    for mid, cs in cands.items():
        for c in set(x.lower() for x in cs):
            support[c] += 1
    rows = []
    for m in markets:
        cs = cands[m["id"]]
        if not cs:
            rows.append({**m, "entities": [], "reason": "no-candidate"})
            continue
        specific, ambiguous = [], []
        for c in cs:
            (ambiguous if support[c.lower()] > ambiguity_max else specific).append(c)
        if not specific:
            rows.append({**m, "entities": [], "reason": "ambiguous",
                         "ambiguous": ambiguous})
        else:
            rows.append({**m, "entities": specific, "reason": "mapped",
                         "ambiguous": ambiguous})
    return rows, support


def _parse_pubdate(s):
    for fmt in ("%a, %d %b %Y %H:%M:%S %Z", "%a, %d %b %Y %H:%M:%S %z"):
        try:
            dt = datetime.strptime(s, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except ValueError:
            continue
    return None


def news_count(entity, win_start, win_end, pause=0.7):
    """Distinct news items for one entity inside [win_start, win_end). Cached on disk."""
    os.makedirs(NEWS_CACHE, exist_ok=True)
    key = re.sub(r"[^a-z0-9]+", "_", entity.lower()).strip("_")[:80]
    path = os.path.join(NEWS_CACHE, key + ".json")
    if os.path.exists(path):
        with open(path) as f:
            cached = json.load(f)
        items = [(datetime.fromisoformat(t), u) for t, u in cached["items"]]
    else:
        q = urllib.parse.quote('"%s"' % entity)
        url = f"https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en"
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        items = []
        try:
            with urllib.request.urlopen(req, timeout=45) as f:
                raw = f.read()
            root = ET.fromstring(raw)
            for it in root.iter("item"):
                link = (it.findtext("link") or "").strip()
                dt = _parse_pubdate((it.findtext("pubDate") or "").strip())
                if dt:
                    items.append((dt, link))
        except Exception as e:  # a dead query must be visible, never silent
            items = []
            with open(os.path.join(CACHE, "news_errors.log"), "a") as f:
                f.write(f"{datetime.now(timezone.utc).isoformat()} {entity} {type(e).__name__} {e}\n")
        items.sort()
        with open(path, "w") as f:
            json.dump({"entity": entity, "fetched_at": datetime.now(timezone.utc).isoformat(),
                       "items": [[d.isoformat(), u] for d, u in items]}, f)
        time.sleep(pause)
    inwin = [u for d, u in items if win_start <= d < win_end]
    return {"entity": entity, "n_total_returned": len(items),
            "n_in_window": len(set(inwin)), "saturated": len(items) >= 95,
            "first": items[0][0].isoformat() if items else None,
            "last": items[-1][0].isoformat() if items else None}


def emit_sample(rows, offset=0, out_path=None):
    """Deterministic stride over the volume-ordered universe: no cherry-picking, and a second
    offset gives a non-overlapping sample for a re-audit after a rule repair."""
    stride = max(1, len(rows) // SAMPLE_N)
    sample = rows[offset::stride][:SAMPLE_N]
    out_path = out_path or SAMPLE_OUT
    os.makedirs(DATA, exist_ok=True)
    with open(out_path, "w") as f:
        for r in sample:
            f.write(json.dumps({"id": r["id"], "question": r["question"],
                                "entities": r["entities"], "reason": r["reason"],
                                "volume24hr": r["volume24hr"], "endDate": r["endDate"]}) + "\n")
    print(f"sample: {len(sample)} markets (offset {offset}, stride {stride} over the "
          f"volume-ordered universe) -> {out_path}")
    print(f"  of which mapped: {sum(1 for r in sample if r['reason']=='mapped')}, "
          f"no-candidate: {sum(1 for r in sample if r['reason']=='no-candidate')}, "
          f"ambiguous: {sum(1 for r in sample if r['reason']=='ambiguous')}")
    return sample


def score_labels(rows, labels_path):
    with open(labels_path) as f:
        labels = json.load(f)
    lab = labels.get("labels", labels)
    sample_ids = [r["id"] for r in rows]
    verdicts = []
    for mid, v in lab.items():
        verdicts.append((mid, v.get("verdict"), v.get("reason", "")))
    mapped = [(mid, v, why) for mid, v, why in verdicts if v in ("PRECISE", "WRONG", "ABSTAIN-OK", "ABSTAIN-BAD")]
    prec_den = [x for x in mapped if x[1] in ("PRECISE", "WRONG")]
    n_ok = sum(1 for x in prec_den if x[1] == "PRECISE")
    prec = (n_ok / len(prec_den)) if prec_den else None
    return {"n_labelled": len(verdicts), "n_mapped_labelled": len(prec_den),
            "n_precise": n_ok, "precision": prec,
            "wrong": [{"id": m, "reason": w} for m, v, w in prec_den if v == "WRONG"],
            "abstain_bad": [{"id": m, "reason": w} for m, v, w in verdicts if v == "ABSTAIN-BAD"]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fetch-markets", action="store_true")
    ap.add_argument("--sample", action="store_true")
    ap.add_argument("--sample-offset", type=int, default=0)
    ap.add_argument("--sample-out")
    ap.add_argument("--labels", action="append", default=[],
                    help="hand-label file(s); repeatable, one per audit")
    ap.add_argument("--gate-precision", type=float, default=0.85)
    ap.add_argument("--coverage", action="store_true", help="query the news index for mapped entities")
    ap.add_argument("--max-coverage-queries", type=int, default=400)
    ap.add_argument("--days", type=int, default=NEWS_DAYS)
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()

    if args.self_test:
        return self_test()

    universe = load_universe(refetch=args.fetch_markets)
    rows, support = build_maps(universe)

    if args.sample:
        emit_sample(rows, offset=args.sample_offset, out_path=args.sample_out)
        return 0

    mapped = [r for r in rows if r["reason"] == "mapped"]
    census = Counter(r["reason"] for r in rows)
    summary = {
        "card": "market-to-news-lead-test",
        "stage": "A",
        "universe": {"n": len(rows), "fetched_at": universe["fetched_at"],
                     "order": universe["order"]},
        "ambiguity_max": AMBIGUITY_MAX,
        "census": dict(census),
        "n_mapped": len(mapped),
        "mapped_share": round(len(mapped) / max(1, len(rows)), 4),
        "top_entities": support.most_common(15),
        "entity_distribution": {"n_distinct_entities": len(support),
                                "entities_over_cap": sum(1 for _, c in support.items() if c > AMBIGUITY_MAX)},
    }

    if args.labels:
        audits = []
        for path in args.labels:
            with open(path) as f:
                meta = json.load(f)
            sc = score_labels(rows, path)
            sc["audit"] = meta.get("audit")
            sc["sample"] = meta.get("sample")
            sc["gate"] = args.gate_precision
            sc["passes_gate"] = (sc["precision"] is not None
                                 and sc["precision"] >= args.gate_precision)
            prim = [v for v in meta["labels"].values() if v.get("primary_ok")]
            sc["primary_subject_recovered"] = round(len(prim) / max(1, len(meta["labels"])), 4)
            audits.append(sc)
        summary["precision_audits"] = audits

    if args.coverage:
        win_end = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        win_start = win_end - timedelta(days=args.days)
        per_entity = {}
        ents = sorted({e for r in mapped for e in r["entities"]},
                      key=lambda e: -support[e.lower()])
        ents = ents[: args.max_coverage_queries]
        for i, e in enumerate(ents):
            per_entity[e] = news_count(e, win_start, win_end)
            if i % 25 == 0:
                print(f"  coverage {i}/{len(ents)} {e} -> {per_entity[e]['n_in_window']}", flush=True)
        mrows = []
        for r in mapped:
            hit = {e: per_entity[e]["n_in_window"] for e in r["entities"] if e in per_entity}
            # distinct items per market: sum over its entities (over-counts shared articles,
            # under-counts none); reported as an upper bound per market
            n = sum(hit.values())
            sat = any(per_entity[e]["saturated"] for e in hit)
            mrows.append({"id": r["id"], "question": r["question"], "entities": r["entities"],
                          "items_7d": n, "per_entity": hit, "saturated": sat,
                          "volume24hr": r["volume24hr"]})
        gate_ok = [x for x in mrows if x["items_7d"] >= 5]
        summary["coverage"] = {
            "window": [win_start.strftime("%Y-%m-%dT%H:%M:%SZ"), win_end.strftime("%Y-%m-%dT%H:%M:%SZ")],
            "days": args.days,
            "n_mapped_markets": len(mapped),
            "n_entities_queried": len(ents),
            "n_entities_saturated": sum(1 for e in per_entity.values() if e["saturated"]),
            "n_markets_5plus_items": len(gate_ok),
            "gate_20_markets": len(gate_ok) >= 20,
            "median_items_7d": sorted(x["items_7d"] for x in mrows)[len(mrows) // 2] if mrows else None,
            "top": sorted(mrows, key=lambda x: -x["items_7d"])[:25],
        }
        with open(os.path.join(DATA, "market-news-lead-stage-a.coverage.jsonl"), "w") as f:
            for x in mrows:
                f.write(json.dumps(x) + "\n")

    os.makedirs(DATA, exist_ok=True)
    with open(OUT, "w") as f:
        json.dump(summary, f, indent=1)
    print(json.dumps({k: v for k, v in summary.items() if k not in ("top_entities",)}, indent=1)[:4000])
    print("->", OUT)
    return 0


def self_test():
    """The extractor must be able to REFUSE. Every case below is a real question from the
    live universe or a live failure mode."""
    cases = [
        ("Will Naftali Bennett be the next Prime Minister of Israel?", ["Naftali Bennett"]),
        ("Will Bitcoin be above $80,000 on November 8?", ["Bitcoin"]),
        ("Will Magic win on 2026-11-08?", []),                      # E3: ordinary-word nickname
        ("Will the price of Ethereum reach $2,900 November 2-8?", ["Ethereum"]),
        ("Spread: Liberty (-15.5)", []),                            # E3
        ("Will Trump and Putin not meet?", ["Putin"]),              # E3 drops "Trump" (dict word)
        ("Will Elon Musk post 240+ tweets from November 7 to November 9, 2026?", ["Elon Musk"]),
        ("Miami (FL) vs. Notre Dame", ["Notre Dame"]),              # Miami is an ordinary word
        ("Will Alexandria Ocasio-Cortez win the 2028 Democratic presidential nomination?",
         ["Alexandria Ocasio-Cortez"]),
        ("Will the Fed cut rates in December?", []),                # role noise, no proposition
        # repaired classes, found by audit #1 (see card note)
        ("Devils vs. Islanders: O/U 6.5", []),                      # R1 plural nickname
        ("Giants vs. Eagles: O/U 38.5", []),                        # R1
        ("Will Stephen A. Smith win the nomination?", ["Stephen A. Smith"]),   # R3 initial
        ("Will \"Babydoll \u2013 Dominic Fike\" be the #2 song for 2026?", ["Dominic Fike"]),  # R5
        ("Will Luka Doncic win the 2026-27 NBA MVP?", ["Luka Doncic"]),        # R4 head acronym
        ("Will Christopher Luxon be the next Prime Minister of New Zealand?", ["Christopher Luxon", "New Zealand"]),
        ("Will Gavin Newsom win the 2028 US Presidential Election?", ["Gavin Newsom"]),
        ("Will Javokhir Sindarov win the 2026 World Chess Championship?", ["Javokhir Sindarov"]),
    ]
    bad = 0
    for q, want in cases:
        got = candidate_runs(q)
        if got != want:
            bad += 1
            print(f"FAIL {q!r}\n  want {want}\n  got  {got}")
    # and the ambiguity machinery must CAP a theme-level entity
    uni = {"fetched_at": "test", "order": "test", "markets": [
        {"id": str(i), "question": f"Will Elon Musk post {i} tweets?", "volume24hr": 1} for i in range(5)
    ] + [{"id": "x", "question": "Will Naftali Bennett be prime minister?", "volume24hr": 1}]}
    rows, support = build_maps(uni)
    amb = [r for r in rows if r["reason"] == "ambiguous"]
    ok_cap = len(amb) == 5 and any(r["reason"] == "mapped" for r in rows)
    if not ok_cap:
        bad += 1
        print("FAIL ambiguity cap:", Counter(r["reason"] for r in rows))
    print(f"self-test: {len(cases) + 1 - bad}/{len(cases) + 1} pass")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
