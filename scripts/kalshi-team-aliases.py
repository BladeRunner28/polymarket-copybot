#!/usr/bin/env python3
"""Kalshi team aliases — the code->name table the cross-venue lane needs (Lane A, approved).

WHY (card kalshi-lane-ontology-not-coverage, option (a) approved 2026-11-23): the strike
parser is already deterministic, so the only thing standing between a Polymarket market and
its contract-equivalent Kalshi market is NAMING. Our market ids are slugs carrying two
3-letter codes (`nba-nop-sas-2026-11-21`); Kalshi titles name the CITY
("New Orleans vs San Antonio", "Los Angeles L", "New York J"). No amount of fuzzy scoring
bridges that, and a scorer that tried is what fabricated the 2026-09-13 "28c venue edge".

TWO TABLES, AND ONLY ONE OF THEM IS TYPED BY HAND:

  * the CODE MAP below (Polymarket slug code -> Kalshi's own team code) is knowledge: the
    two venues abbreviate differently (`gs`/`gsw` vs `GSW`, `no`/`nop` vs `NOP`,
    `mac` vs `MCI`, `che` vs `CFC`);
  * the NAMES are DERIVED from the venue itself: every Kalshi event carries its own codes
    in `sub_title` ("BOS vs GSW (Nov 22)") beside the title it renders ("Boston vs Golden
    State"), so the (code, name) pairs are a transcription of what the venue publishes,
    not what I remember. `--derive` walks 60 days of settled events plus the open book per
    league and writes data/kalshi-team-aliases.json.

`--check` is the safety property that matters: within a sport, no two Polymarket codes may
resolve to the same venue name. That is what keeps `lal`/`lac` ("Los Angeles L"/"Los
Angeles C") and `nyg`/`nyj` ("New York G"/"New York J") — and, in soccer, Manchester
City/United — from collapsing into each other, which a shared-token matcher does.

COLLEGE IS DERIVED, NOT AUTHORED, AND FOR A DIFFERENT REASON. FBS/D1 team codes are
contractions of school names ('vtech', 'washst', 'utrgv', 'smho'), so there is no ~30-row
code map to write -- there are 180 codes in the book and 700 teams at the venue. The code
map for those is DERIVED from the two-sided events themselves: for each of our college
markets (two slug codes + one day) the venue's own events on that day are searched, and an
event votes only when exactly ONE side assignment of BOTH codes survives. Codes that
cannot be placed that way are DROPPED and printed, never guessed -- the ambiguity report is
the deliverable, not a failure to hide (card kalshi-college-alias-tables).

Usage:
  python3 scripts/kalshi-team-aliases.py --derive     # refresh the table from the venue
  python3 scripts/kalshi-team-aliases.py --check      # collisions + coverage, exit 1 on fail
  python3 scripts/kalshi-team-aliases.py --college-report  # what the derivation refused
"""
import argparse
import collections
import json
import os
import re
import sqlite3
import sys
import time
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data", "kalshi-team-aliases.json")
BASE = "https://api.elections.kalshi.com/trade-api/v2"

# Polymarket slug code -> Kalshi's own code. Authored; the NAMES come from the venue.
CODE_MAP = {
    "nba": {
        "atl": "ATL", "bos": "BOS", "bkn": "BKN", "cha": "CHA", "chi": "CHI", "cle": "CLE",
        "dal": "DAL", "den": "DEN", "det": "DET", "gs": "GSW", "gsw": "GSW", "hou": "HOU",
        "ind": "IND", "lac": "LAC", "lal": "LAL", "mem": "MEM", "mia": "MIA", "mil": "MIL",
        "min": "MIN", "no": "NOP", "nop": "NOP", "ny": "NYK", "nyk": "NYK", "okc": "OKC",
        "orl": "ORL", "phi": "PHI", "pho": "PHX", "phx": "PHX", "por": "POR", "sac": "SAC",
        "sa": "SAS", "sas": "SAS", "tor": "TOR", "uta": "UTA", "utah": "UTA", "was": "WAS",
        "wsh": "WAS",
    },
    "nfl": {
        "ari": "ARI", "atl": "ATL", "bal": "BAL", "buf": "BUF", "car": "CAR", "chi": "CHI",
        "cin": "CIN", "cle": "CLE", "dal": "DAL", "den": "DEN", "det": "DET", "gb": "GB",
        "hou": "HOU", "ind": "IND", "jac": "JAC", "jax": "JAC", "kc": "KC", "lac": "LAC",
        "lar": "LAR", "lv": "LV", "lvr": "LV", "mia": "MIA", "min": "MIN", "ne": "NE",
        "no": "NO", "nyg": "NYG", "nyj": "NYJ", "phi": "PHI", "pit": "PIT", "sea": "SEA",
        "sf": "SF", "tb": "TB", "ten": "TEN", "was": "WAS", "wsh": "WAS",
    },
    "nhl": {
        "ana": "ANA", "bos": "BOS", "buf": "BUF", "car": "CAR", "cbj": "CBJ", "cgy": "CGY",
        "chi": "CHI", "col": "COL", "dal": "DAL", "det": "DET", "edm": "EDM", "fla": "FLA",
        "la": "LA", "lak": "LA", "min": "MIN", "mtl": "MTL", "nsh": "NSH", "nshv": "NSH",
        "nj": "NJ", "njd": "NJ", "nyi": "NYI", "nyr": "NYR", "ott": "OTT", "phi": "PHI",
        "pit": "PIT", "sea": "SEA", "sj": "SJ", "sjs": "SJ", "stl": "STL", "tb": "TB",
        "tor": "TOR", "uta": "UTA", "utah": "UTA", "van": "VAN", "vgk": "VGK", "wpg": "WPG",
        "was": "WSH", "wsh": "WSH",
    },
    "mlb": {
        "ari": "AZ", "az": "AZ", "ath": "ATH", "oak": "ATH", "atl": "ATL", "bal": "BAL",
        "bos": "BOS", "chc": "CHC", "chw": "CWS", "cws": "CWS", "cin": "CIN", "cle": "CLE",
        "col": "COL", "det": "DET", "hou": "HOU", "kc": "KC", "laa": "LAA", "lad": "LAD",
        "mia": "MIA", "mil": "MIL", "min": "MIN", "nym": "NYM", "nyy": "NYY", "phi": "PHI",
        "pit": "PIT", "sd": "SD", "sea": "SEA", "sf": "SF", "stl": "STL", "tb": "TB",
        "tex": "TEX", "tor": "TOR", "wsh": "WSH", "was": "WSH",
    },
    "epl": {
        "ars": "ARS", "avl": "AVL", "bou": "BOU", "bre": "BRE", "bri": "BRI", "che": "CFC",
        "cfc": "CFC", "cov": "COV", "cry": "CRY", "eve": "EVE", "ful": "FUL", "hul": "HUL",
        "ips": "IPS", "lee": "LEE", "liv": "LFC", "lfc": "LFC", "mac": "MCI", "mci": "MCI",
        "mun": "MUN", "new": "NEW", "nfo": "NFO", "sun": "SUN", "tot": "TOT",
    },
}
# Series to walk when deriving. One per league, verified against the live API by --derive.
SERIES = {"nba": "KXNBAGAME", "nfl": "KXNFLGAME", "nhl": "KXNHLGAME",
          "mlb": "KXMLBGAME", "epl": "KXEPLGAME"}

# College: no authored code map. The series are the derivation source AND the family that
# the resolver's slug gate matches on ('KXNCAAF' covers GAME/SPREAD/TOTAL).
COLLEGE = {"cfb": "KXNCAAFGAME", "cbb": "KXNCAAMBGAME", "ncaawb": "KXNCAAWBGAME"}
DB = os.path.join(ROOT, "prisma", "dev.db")
DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")


def get(url, tries=3):
    req = urllib.request.Request(url, headers={"accept": "application/json",
                                              "user-agent": "copybot-research/0.1 (paper-only)"})
    for a in range(1, tries + 1):
        try:
            with urllib.request.urlopen(req, timeout=40) as r:
                return json.load(r)
        except Exception:
            if a == tries:
                raise
            time.sleep(1.5 * a)


def walk(series, status, pages=8, settle_days=90, stats=None):
    """Events for one series/status. `stats` (optional) records whether the cursor was
    EXHAUSTED or hit the page cap -- a trivially different walk depth changes any count it
    feeds, so the derivation prints it rather than assuming."""
    out, cursor = [], None
    now = int(time.time())
    for _ in range(pages):
        q = {"series_ticker": series, "status": status, "limit": "200"}
        if status == "settled":
            q["min_close_ts"] = now - settle_days * 86400
            q["max_close_ts"] = now
        if cursor:
            q["cursor"] = cursor
        d = get(f"{BASE}/events?" + urllib.parse.urlencode(q))
        out += d.get("events", [])
        cursor = d.get("cursor")
        if not cursor or not d.get("events"):
            break
    if stats is not None:
        stats[status] = {"pages": pages, "events": len(out), "cursorExhausted": not cursor}
    return out


def venue_names(series):
    """(code -> Counter of rendered side names) from the venue's own title/sub_title pairs."""
    names = collections.defaultdict(collections.Counter)
    for status in ("settled", "open"):
        try:
            evs = walk(series, status)
        except Exception as e:  # a league with no live series must not kill the build
            print(f"  ! {series} {status}: {e}", file=sys.stderr)
            continue
        for e in evs:
            sub = (e.get("sub_title") or "").strip()
            title = (e.get("title") or "").strip()
            m = re.match(r"^([A-Za-z0-9]{2,6})\s+vs\.?\s+([A-Za-z0-9]{2,6})\b", sub)
            if not m:
                continue
            sides = re.split(r"\s+vs\.?\s+", title)
            if len(sides) != 2:
                continue
            a = sides[0].split(":")[-1].strip()
            b = sides[1].split(":")[0].strip()
            if not a or not b:
                continue
            names[m.group(1).upper()][a] += 1
            names[m.group(2).upper()][b] += 1
    return names


def discriminating(names, codes):
    """Drop alias forms that more than one VENUE code renders.

    Measured need: the venue sometimes renders both New York franchises as plain "New York"
    (NFL NYG and NYJ each carried it as a third form), and "A's" collapses to the token
    'as' with the apostrophe stripped. An alias that does not separate two teams inside its
    own league is not an alias — it is exactly the shared-token ambiguity the four-gate
    contract test exists to refuse. Two Polymarket spellings of the SAME team (`gs`/`gsw`)
    share one venue code by design and are therefore not collisions.
    """
    owner = collections.defaultdict(set)
    for venue_code in set(codes.values()):
        for form in names.get(venue_code) or []:
            owner[form].add(venue_code)
    return {f for f, owners in owner.items() if len(owners) == 1}


MONTHS = {"JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6, "JUL": 7,
          "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12}


def ticker_day(ticker):
    """The event's own date, from its ticker ('KXNCAAFGAME-26NOV21LSUTENN').
    Mirrors the resolver's parser; the venue returns no date field on these events."""
    m = re.search(r"-(\d{2})([A-Z]{3})(\d{2})", ticker or "")
    if not m:
        return None
    try:
        return time.mktime((2000 + int(m.group(1)), MONTHS[m.group(2)], int(m.group(3)),
                            12, 0, 0, 0, 0, -1))
    except (KeyError, ValueError, OverflowError):
        return None


def compact(text):
    return re.sub(r"[^a-z0-9]", "", (text or "").lower())


def contraction(code, side):
    """Is `code` an abbreviation of the venue's rendered `side`? Bounded on purpose.

    The code must START with the side's first letter and be a SUBSEQUENCE of the side's
    letters in order. That admits the real college patterns this card names -- vtech ->
    Virginia Tech, washst -> Washington St, utrgv -> UT Rio Grande Valley, smho -> Sam
    Houston, ohiost -> Ohio St -- and it refuses the two fabrications this lane has already
    paid for: a code never matches on a shared word (Espanyol/Barcelona) and never travels
    to a word it does not start with. It is deliberately LOOSE, because a loose code test
    is only dangerous when nothing else bounds it; here the bound is the pair (the OTHER
    code must place on the other side of the SAME event, same day) and the vote.
    """
    c = compact(code)
    n = compact(side)
    if len(c) < 2 or not n or c[0] != n[0]:
        return False
    j = 0
    for ch in c:
        j = n.find(ch, j)
        if j < 0:
            return False
        j += 1
    return True


def slug_codes(market_id):
    """(sport, [code_a, code_b], day_ts) for a COLLEGE market id, else None.

    Same slug grammar the resolver parses (sport-team-team-YYYY-MM-DD-tail); only the
    college sports are returned, because everything else already has an authored map.
    """
    parts = (market_id or "").split("-")
    for i in range(len(parts) - 2):
        m = DATE_RE.match("-".join(parts[i:i + 3]))
        if not m:
            continue
        sport = parts[0]
        if sport not in COLLEGE:
            return None
        teams = [x for x in parts[1:i] if x and not x.isdigit()]
        if len(teams) != 2:
            return None
        try:
            day = time.mktime((int(m.group(1)), int(m.group(2)), int(m.group(3)),
                               12, 0, 0, 0, 0, -1))
        except (ValueError, OverflowError):
            return None
        return sport, [t.lower() for t in teams], day
    return None


def matchup_sig(sides):
    """Order-independent identity of a matchup, so one game listed under several event
    titles (GAME / SPREAD / TOTAL) counts as ONE event, not three votes."""
    return "|".join(sorted(compact(s) for s in sides))


def college_events(series, pages=12, stats=None):
    """Venue college events as (day, [side_a, side_b], [venue_code_a, venue_code_b])."""
    out = []
    for status in ("settled", "open"):
        page_stats = {}
        try:
            evs = walk(series, status, pages=pages, stats=page_stats)
        except Exception as e:  # a walk failure must not silently feed a partial table
            print(f"  ! {series} {status}: {e}", file=sys.stderr)
            continue
        if stats is not None:
            stats[f"{series}/{status}"] = page_stats.get(status, {})
        for e in evs:
            sub = (e.get("sub_title") or "").strip()
            title = (e.get("title") or "").strip()
            m = re.match(r"^([A-Za-z0-9]{2,6})\s+vs\.?\s+([A-Za-z0-9]{2,6})\b", sub)
            if not m:
                continue
            parts = re.split(r"\s+vs\.?\s+", title, flags=re.I)
            if len(parts) != 2:
                continue
            a = parts[0].split(":")[-1].strip()
            b = re.split(r":", parts[1])[0].strip()
            if not a or not b:
                continue
            # the events route names this field `event_ticker`; the index builder renames it
            out.append({"day": ticker_day(e.get("event_ticker") or e.get("ticker") or ""),
                        "sides": [a, b],
                        "codes": [m.group(1).upper(), m.group(2).upper()]})
    return out


def college_votes(pages=12, stats=None):
    """Pair-constrained derivation: (sport, pm_code) -> Counter of (venue_code, name).

    One of our markets votes only when exactly one side assignment of BOTH of its codes
    survives across all of the venue's events on its day, and all surviving events describe
    the SAME matchup. Every refusal is counted and reported under its own reason, because
    'could not place' and 'two events fit' are different answers.
    """
    con = sqlite3.connect(DB)
    ids = [r[0] for r in con.execute(
        "SELECT DISTINCT marketId FROM PaperTrade WHERE isDemo=0")]
    con.close()
    games = [g for g in (slug_codes(m) for m in ids) if g]
    pools = {}
    for series in set(COLLEGE.values()):
        pools[series] = college_events(series, pages=pages, stats=stats)
    votes = collections.defaultdict(collections.Counter)
    refused = collections.Counter()
    for sport, codes, day in games:
        got = vote_event(codes, day, pools.get(COLLEGE[sport]) or [])
        if got is None:
            refused["no-single-same-day-event"] += 1
            continue
        if got == "ambiguous":
            refused["two-different-games-fit"] += 1
            continue
        ev, perm = got
        votes[(sport, codes[0])][(ev["codes"][perm[0]], ev["sides"][perm[0]])] += 1
        votes[(sport, codes[1])][(ev["codes"][perm[1]], ev["sides"][perm[1]])] += 1
    return votes, refused, len(games)


def vote_event(codes, day, events, window=86400):
    """One of our markets -> (event, [side_for_code_1, side_for_code_2]) or a refusal.

    THE PAIR IS THE GUARD. A single code is allowed to be loose ('ga' contracts both
    'Georgia' and 'Georgia St.'); what is NOT allowed is a vote unless exactly one ordered
    assignment of BOTH codes lands on one side each of the SAME event, that event is within
    a day of our slug, and every event that survives describes the same matchup (one game is
    listed as GAME/SPREAD/TOTAL). Returns None for nothing found, "ambiguous" when two
    different games fit.
    """
    surv = []
    for ev in events:
        if not ev or ev.get("day") is None or abs(ev["day"] - day) > window:
            continue
        m1 = [j for j in (0, 1) if contraction(codes[0], ev["sides"][j])]
        m2 = [j for j in (0, 1) if contraction(codes[1], ev["sides"][j])]
        perms = [(x, y) for x in m1 for y in m2 if x != y]
        if len(perms) == 1:
            surv.append((ev, perms[0]))
    if not surv:
        return None
    if len({matchup_sig(ev["sides"]) for ev, _ in surv}) != 1:
        return "ambiguous"
    return surv[0]


def college_tables(votes):
    """Accept a code only when every vote places it on ONE venue code.

    Same venue code + several rendered forms ("St. Bonaventure"/"Saint Bonaventure") is one
    team and is kept as a form list, exactly like the pro-league tables. Two DIFFERENT venue
    codes for one Polymarket code is a contested code and is dropped, which is the card's
    collision property (it is what keeps Georgia from becoming Georgia St.).
    """
    tables, contested = collections.defaultdict(dict), []
    for (sport, pm), counter in sorted(votes.items()):
        vcodes = {vc for (vc, _name) in counter}
        if len(vcodes) != 1:
            contested.append({"sport": sport, "code": pm,
                              "candidates": sorted(f"{vc}:{nm}" for vc, nm in counter)})
            continue
        vcode = vcodes.pop()
        forms = [name for (_vc, name), _n in counter.most_common()]
        tables[sport][pm] = {"forms": forms, "venueCode": vcode,
                             "votes": sum(counter.values())}
    return tables, contested


def self_test():
    """Pure-function arms for the college derivation. Every arm is a mistake this lane has
    already paid for somewhere else, or a property the card's gate names."""
    ok = arms = 0

    def arm(name, cond):
        nonlocal ok, arms
        arms += 1
        print(f"  {'PASS' if cond else 'FAIL'}  {name}")
        if cond:
            ok += 1

    for code, side in (("vtech", "Virginia Tech"), ("washst", "Washington St."),
                       ("utrgv", "UT Rio Grande Valley"), ("smho", "Sam Houston"),
                       ("txst", "Texas St."), ("nichls", "Nicholls St."),
                       ("yngst", "Youngstown St."), ("mdes", "Maryland-Eastern Shore"),
                       ("oregst", "Oregon St."), ("ohiost", "Ohio St.")):
        arm(f"contraction: {code} -> {side}", contraction(code, side))
    arm("contraction REFUSES a code that starts on another letter (washst / Eastern Washington)",
        not contraction("washst", "Eastern Washington"))
    arm("contraction REFUSES a shared word (esp / Barcelona) -- the Espanyol fabrication",
        not contraction("esp", "Barcelona"))
    arm("contraction respects ORDER: 'tech' is not 'Tennessee Tech'",
        not contraction("tehc", "Tennessee Tech"))
    arm("contraction is LOOSE on purpose: 'ga' fits Georgia AND Georgia St. (the pair decides)",
        contraction("ga", "Georgia") and contraction("ga", "Georgia St."))
    arm("slug parses a college id and ignores a non-college one",
        slug_codes("cfb-lsu-tenn-2026-11-21-spread-home-16pt5")[0] == "cfb"
        and slug_codes("nba-por-nyk-2026-11-21-spread-home-7pt5") is None)
    D = 1795000000.0
    ev_lsu = {"day": D, "sides": ["LSU", "Tennessee"], "codes": ["LSU", "TENN"]}
    ev_uga = {"day": D, "sides": ["Georgia", "South Carolina"], "codes": ["UGA", "SCAR"]}
    ev_gst = {"day": D, "sides": ["Georgia St.", "South Carolina St."], "codes": ["GAST", "SCST"]}
    got = vote_event(["lsu", "tenn"], D, [ev_lsu])
    arm("vote places both codes on the right sides",
        bool(got) and got != "ambiguous" and list(got[1]) == [0, 1]
        and got[0]["codes"] == ["LSU", "TENN"])
    arm("vote REFUSES when two different games fit ('ga' + an equally loose partner)",
        vote_event(["ga", "sc"], D, [ev_uga, ev_gst]) == "ambiguous")
    arm("vote ACCEPTS the same game listed as GAME/SPREAD/TOTAL (one matchup, three events)",
        (lambda r: r not in (None, "ambiguous"))(
            vote_event(["ga", "sc"], D, [ev_uga,
                                         {"day": D, "sides": ["Georgia", "South Carolina"],
                                          "codes": ["UGA", "SCAR"]}])))
    arm("vote REFUSES a neighbouring day (a game two days out is not our game)",
        vote_event(["lsu", "tenn"], D + 3 * 86400, [ev_lsu]) is None)
    arm("vote REFUSES when both codes land on the SAME side",
        vote_event(["lsu", "lsu2"], D, [{"day": D, "sides": ["LSU", "Tennessee"],
                                        "codes": ["LSU", "TENN"]}]) is None)
    # the mutation arm: per-code matching WITHOUT the pair would have voted on the ambiguous day
    loose_code = [j for j in (0, 1) if contraction("ga", ev_uga["sides"][j])]
    arm("MUTATION: a per-code matcher would have voted on the ambiguous day, the pair veto does not",
        len(loose_code) == 1 and contraction("ga", ev_gst["sides"][0])
        and vote_event(["ga", "sc"], D, [ev_uga, ev_gst]) == "ambiguous")
    V = {("cfb", "ga"): collections.Counter({("UGA", "Georgia"): 2}),
         ("cfb", "gast"): collections.Counter({("GAST", "Georgia St."): 1}),
         ("cfb", "bad"): collections.Counter({("UGA", "Georgia"): 1, ("GAST", "Georgia St."): 1})}
    tables, contested = college_tables(V)
    arm("two DISTINCT venue codes for one Polymarket code = contested, dropped",
        "bad" not in tables.get("cfb", {}) and len(contested) == 1)
    arm("Georgia and Georgia St. survive as separate teams",
        tables["cfb"]["ga"]["forms"] == ["Georgia"]
        and tables["cfb"]["gast"]["forms"] == ["Georgia St."])
    arm("a code with no votes is not in the table at all",
        "tenn" not in tables.get("cfb", {}))
    print(f"\nself-test {ok}/{arms}")
    return 0 if ok == arms else 1


def derive_college_only():
    """Write ONLY the college sections into the existing table.

    The pro-league sections are pinned basis for every published cross-venue number, so a
    college refresh must not re-derive them: a live re-walk would silently move the NBA/NFL/
    NHL/MLB/EPL arm and make the college lift unmeasurable. Existing keys are preserved
    verbatim; only COLLEGE sports and their _meta.leagues entries are written.
    """
    with open(OUT) as f:
        t = json.load(f)
    meta = (t.get("_meta") or {}).setdefault("leagues", {})
    cstats = {}
    votes, refused, n_games = college_votes(stats=cstats)
    tables, contested = college_tables(votes)
    for sport in sorted(tables):
        t[sport] = {pm: v["forms"] for pm, v in tables[sport].items()}
        meta[sport] = {"series": COLLEGE[sport], "codes": len(t[sport]), "missing": [],
                       "ambiguousFormsDropped": [],
                       "derivation": "pair-constrained vote (both codes on one same-day event)",
                       "venueCodes": {pm: v["venueCode"] for pm, v in tables[sport].items()},
                       "votes": {pm: v["votes"] for pm, v in tables[sport].items()},
                       "contested": [c for c in contested if c["sport"] == sport],
                       "refused": dict(refused),
                       "walk": {k: cstats.get(k, {}) for k in cstats}}
        print(f"{sport}: {len(t[sport])} codes DERIVED from {COLLEGE[sport]} "
              f"({len(tables[sport])} placed, "
              f"{len([c for c in contested if c['sport'] == sport])} contested dropped)")
    t["_meta"]["collegeGeneratedAt"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    t["_meta"]["collegeSource"] = ("pair-constrained vote over our college market ids "
                                   "(both slug codes on one same-day venue event)")
    if refused:
        print("  college votes refused: " +
              ", ".join(f"{k}={v}" for k, v in sorted(refused.items())))
    print(f"  games in the book: {n_games}")
    with open(OUT, "w") as f:
        json.dump(t, f, indent=1, sort_keys=True)
    print(f"wrote {OUT} (college sections only)")
    return 0


def derive():
    table, meta, problems = {}, {}, []
    for sport, series in SERIES.items():
        names = venue_names(series)
        codes = CODE_MAP[sport]
        keep = discriminating(names, codes)
        sport_out, dropped = {}, set()
        for pm_code, venue_code in sorted(codes.items()):
            forms = names.get(venue_code)
            if not forms:
                problems.append(f"{sport}/{pm_code}: no venue events for {venue_code}")
                continue
            picked = [n for n, _ in forms.most_common() if n in keep][:3]
            dropped |= {n for n, _ in forms.most_common() if n not in keep}
            if not picked:
                problems.append(f"{sport}/{pm_code}: every rendered form is ambiguous ({list(forms)})")
                continue
            sport_out[pm_code] = picked
        table[sport] = sport_out
        meta[sport] = {"series": series, "codes": len(sport_out),
                       "missing": sorted({c for c in codes if c not in sport_out}),
                       "ambiguousFormsDropped": sorted(dropped)}
        print(f"{sport}: {len(sport_out)} codes resolved off {series} "
              f"({len(set(codes.values()))} venue codes; dropped {len(dropped)} ambiguous form(s))")

    # --- college: derived by pair-constrained vote, never authored -------------------
    cstats = {}
    votes, refused, n_games = college_votes(stats=cstats)
    tables, contested = college_tables(votes)
    for sport in sorted(tables):
        sport_out = {pm: v["forms"] for pm, v in tables[sport].items()}
        table[sport] = sport_out
        meta[sport] = {"series": COLLEGE[sport], "codes": len(sport_out), "missing": [],
                       "ambiguousFormsDropped": [],
                       "derivation": "pair-constrained vote (both codes on one same-day event)",
                       "venueCodes": {pm: v["venueCode"] for pm, v in tables[sport].items()},
                       "votes": {pm: v["votes"] for pm, v in tables[sport].items()},
                       "contested": [c for c in contested if c["sport"] == sport],
                       "refused": dict(refused),
                       "walk": {k: cstats.get(k, {}) for k in cstats}}
        print(f"{sport}: {len(sport_out)} codes DERIVED from {COLLEGE[sport]} "
              f"({n_games} college games in the book; "
              f"{len([c for c in contested if c['sport'] == sport])} contested code(s) dropped)")
    if refused:
        print("  college votes refused: " +
              ", ".join(f"{k}={v}" for k, v in sorted(refused.items())))
    with open(OUT, "w") as f:
        json.dump({"_meta": {"generatedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                            "source": "Kalshi event title/sub_title pairs (settled 90d + open)",
                            "leagues": meta}, **table}, f, indent=1, sort_keys=True)
    print(f"\nwrote {OUT}")
    for p in problems:
        print(f"  missing: {p}")
    return 0


def check():
    """Collision test (two VENUE codes must never share an alias form) + coverage.

    Two Polymarket spellings of one team (`gs`/`gsw` -> GSW) are the same venue code and are
    not collisions; what must never happen is two DISTINCT venue codes resolving alike,
    which is how "Los Angeles" swallows both LA teams and how a shared-token matcher turned
    "Will Bursaspor win" into a 28c Texas-election edge.
    """
    with open(OUT) as f:
        t = json.load(f)
    meta = (t.get("_meta") or {}).get("leagues") or {}
    sport_codes = dict(CODE_MAP)
    for sport, m in meta.items():
        if sport not in sport_codes:
            sport_codes[sport] = (m or {}).get("venueCodes") or {}
    bad = 0
    for sport in sorted(set(SERIES) | {s for s in t if not s.startswith("_")}):
        forms = t.get(sport) or {}
        if not forms and sport not in SERIES:
            continue
        seen = collections.defaultdict(list)
        for pm_code, names in forms.items():
            for n in names:
                seen[re.sub(r"[^a-z0-9 ]", "", n.lower())].append(pm_code)
        for name, pm_codes in sorted(seen.items()):
            venue_codes = {sport_codes.get(sport, {}).get(c, c) for c in pm_codes}
            if len(venue_codes) > 1:
                print(f"  COLLISION {sport}: {sorted(venue_codes)} all -> {name!r}")
                bad += 1
        for a, b in (("lal", "lac"), ("nyg", "nyj"), ("nyr", "nyi"), ("mac", "mun"), ("mci", "mun")):
            if a in forms and b in forms:
                sa = {x.lower() for x in forms[a]}
                sb = {x.lower() for x in forms[b]}
                if sa & sb:
                    print(f"  COLLISION {sport}: {a}/{b} share {sorted(sa & sb)}")
                    bad += 1
        # college: the derived table must carry ONE venue code per Polymarket code, and no
        # alias form may be claimed by two different venue codes
        vc = (meta.get(sport) or {}).get("venueCodes") or {}
        if vc:
            by_name = collections.defaultdict(set)
            for pm_code, names in forms.items():
                for n in names:
                    by_name[re.sub(r"[^a-z0-9 ]", "", n.lower())].add(vc.get(pm_code))
            for name, codes in sorted(by_name.items()):
                if len({c for c in codes if c}) > 1:
                    print(f"  COLLISION {sport}: derived venue codes {sorted(codes)} both -> {name!r}")
                    bad += 1
            missing_vc = sorted(set(forms) - set(vc))
            if missing_vc:
                print(f"  MISSING venueCode {sport}: {missing_vc}")
                bad += 1
        if not forms:
            print(f"  EMPTY {sport}: no aliases")
            bad += 1
        print(f"  {sport:4} {len(forms):>3} codes, "
              f"{sum(len(v) for v in forms.values()):>3} forms, "
              f"{len(seen):>3} distinct names")
    print(f"\nalias check: {'FAIL' if bad else 'PASS'} ({bad} collision(s))")
    return 1 if bad else 0


def college_report():
    """Read-only: which college codes the derivation did NOT place, and why.

    A code absent from the table is not a missing team -- it is a code whose two codes never
    resolved to one same-day event, and the resolver falls back to the heuristic for it.
    Printed so 'not derived' is never read as 'does not exist'.
    """
    with open(OUT) as f:
        t = json.load(f)
    meta = (t.get("_meta") or {}).get("leagues") or {}
    for sport in sorted(COLLEGE):
        m = meta.get(sport) or {}
        forms = t.get(sport) or {}
        print(f"{sport}: {len(forms)} derived code(s) off {COLLEGE[sport]}; "
              f"refused {m.get('refused') or {}}")
        for c in (m.get("contested") or []):
            print(f"  contested {c['code']}: " + ", ".join(c["candidates"]))
        for pm in sorted(forms):
            print(f"  {pm:8} -> {(m.get('venueCodes') or {}).get(pm, '?'):6} "
                  f"{(forms[pm][0] if forms[pm] else '')!r} "
                  f"(votes {(m.get('votes') or {}).get(pm, 0)})")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--derive", action="store_true")
    ap.add_argument("--derive-college", action="store_true",
                    help="refresh ONLY the college sections; pro sections are preserved")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--college-report", action="store_true",
                    help="print what the college derivation refused (level=code; no write)")
    a = ap.parse_args()
    if a.self_test:
        return self_test()
    if a.college_report:
        return college_report()
    if a.derive_college:
        return derive_college_only()
    if a.derive:
        return derive()
    if a.check:
        return check()
    print(__doc__)
    return 0


if __name__ == "__main__":
    sys.exit(main())
