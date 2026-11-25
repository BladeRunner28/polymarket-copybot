#!/usr/bin/env python3
"""Kalshi contract equivalence — the card's own acceptance test (pairs, not coverage %).

WHY (2026-11-21): the 2026-09-18 read on this lane concluded "0% verified, the
binding constraint is contract ONTOLOGY, so park". That read was taken on a
September book (elections/politics). Two months later the C-200 book is sports and
the event matcher returns genuine same-game counterparts at high score, so the open
question is no longer "does a counterpart exist" but "does an equivalent CONTRACT
exist at the same STRIKE" — what this script measures. It never asserts coverage:
a pair counts only when the event is name-verified, the class agrees, and (where a
line exists) the line is identical.

Three gates, in order, and every verdict names the gate that failed:
  G1 EVENT   the matched event's title must name our subject(s): both teams for
             MONEYLINE/TOTAL, the subject for SPREAD. A title that shares naming
             with us AND is dated within 2 days of our own trade timestamp.
  G2 CLASS   MONEYLINE / SPREAD / TOTAL must agree; derived Kalshi contracts
             (1st half, quarter, team total, correct score, series/map) never count.
  G3 STRIKE  spread/total line must be identical (half-point grids, so exact).

Classes understood:
  MONEYLINE  "A vs. B"                 <- "<Team> wins"
  SPREAD     "Spread: <Team> (-5.5)"   <- "<Team> wins by over 5.5 points"
  TOTAL      "A vs. B: O/U 43.5"       <- "Full Game: over 43.5 points scored?"
  OTHER      barriers ("Will BTC dip to X"), series games, politics, player props

Usage:
  python3 scripts/kalshi-contract-equivalence.py --days 7
  python3 scripts/kalshi-contract-equivalence.py --self-test
"""
import argparse
import json
import os
import re
import sqlite3
import sys
import time
import urllib.parse
import urllib.request
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(ROOT, "prisma", "dev.db")
INDEX = os.path.join(ROOT, "data", "kalshi-event-index.json")
MAP = os.path.join(ROOT, "data", "kalshi-slug-map.json")
OUT = os.path.join(ROOT, "data", "kalshi-contract-equivalence.json")
ALIASES = os.path.join(ROOT, "data", "kalshi-team-aliases.json")
MCACHE = os.path.join(ROOT, "data", "cache", "kalshi-event-markets")
WCACHE = os.path.join(ROOT, "data", "cache", "kalshi-window-events")
BASE = "https://api.elections.kalshi.com/trade-api/v2"
MONTHS = {"JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6, "JUL": 7,
          "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12}
PRO_LEAGUES = ("KXNFL", "KXNBA", "KXNHL", "KXEPL", "KXMLB")

GENERIC = {
    "will", "the", "of", "in", "on", "at", "by", "to", "for", "be", "is", "are",
    "and", "or", "vs", "spread", "over", "under", "score", "scored", "points",
    "point", "goals", "goal", "runs", "run", "full", "game", "match", "wins", "win",
    "more", "than", "total", "fc", "sc", "club", "city", "united", "utd", "state",
    "university", "univ", "college", "main", "card", "night", "fight", "ufc", "half",
    "st", "sr", "jr", "de", "la", "el", "ii", "iii",
}


def tokens(text):
    text = (text or "").lower().replace("'", "")
    out = set()
    for w in re.findall(r"[a-z0-9]+", text):
        if not w or w in GENERIC or re.fullmatch(r"\d+", w):
            continue
        out.add(w)
    return out


def state_marker(text):
    """Does the name carry a State/St. qualifier? 'Georgia' and 'Georgia St.' are
    different schools, while 'Morgan State' and 'Morgan St.' are the same one."""
    return bool(re.search(r"\bstate\b|\bst\.?\b", (text or ""), re.I))


CLUB_PREFIX = {"rcd", "fc", "cf", "ca", "csyd", "cd", "sc", "ac", "as", "sv", "sk", "bk", "fk",
               "if", "aik", "ss", "ssc", "us", "uc", "rc", "club"}


def head_token(name):
    """The token that identifies a team: its first distinctive word, skipping club prefixes
    ('RCD Espanyol de Barcelona' -> espanyol, not rcd)."""
    for t in re.findall(r"[a-z0-9]+", (name or "").lower().replace("'", "")):
        if t in GENERIC or re.fullmatch(r"\d+", t) or t in CLUB_PREFIX:
            continue
        return t
    return ""


def subject_match(ours, theirs):
    """Same team/player? Three guards, each bought with a measured false positive:

    (1) the State/St. qualifier must agree on BOTH sides, else "Georgia" matches
        "Georgia St." and "Kansas" matches "Kansas St.";
    (2) the shared tokens must cover >=60% of the CANDIDATE's distinctive tokens,
        else "Georgia" matches "Georgia Southern", "New Mexico" matches "New York"
        and "South Carolina State Bulldogs" matches "Western Carolina";
    (3) a ONE-token candidate must be our team's identifying HEAD token: a club's name
        carries its city, so "RCD Espanyol de Barcelona" matched a single-token "Barcelona"
        (the opponent) at 100% of the candidate's tokens and fabricated a La Liga
        "equivalent" 2.4 days from our trade. "Marquette" vs "Marquette Golden Eagles"
        still matches, because 'marquette' IS the head.
    """
    if state_marker(ours) != state_marker(theirs):
        return False, []
    o, t = tokens(ours), tokens(theirs)
    shared = {x for x in (o & t) if len(x) >= 3}
    if not shared or not t:
        return False, []
    if len(t) == 1 and head_token(ours) not in shared:
        return False, []
    return len(shared) / len(t) >= 0.6, sorted(shared)


def split_sides(title):
    """A two-sided event title -> [side A, side B], or None.

    Split on ' vs ' FIRST and only then trim ':' tails: Kalshi titles carry a prefix
    ("Fight Night: X vs Y", "College Basketball (W): X vs Y") whose colon is not
    where the matchup starts. Splitting on ':' first made every UFC event look
    single-sided and silently moved 6 verified pairs into the unverified bucket.
    """
    parts = re.split(r"\s+vs\.?\s+", title or "", flags=re.I)
    if len(parts) != 2:
        return None
    a = parts[0].split(":")[-1].strip()
    b = re.split(r":", parts[1])[0].strip()
    return [a, b] if a and b else None


def teams_verified(teams, title):
    """Our two sides must map to two DISTINCT sides of the event title."""
    sides = split_sides(title)
    if not sides or len(teams) != 2:
        return False
    a = [i for i, sd in enumerate(sides) if subject_match(teams[0], sd)[0]]
    b = [i for i, sd in enumerate(sides) if subject_match(teams[1], sd)[0]]
    return any(i != j for i in a for j in b)


OUR_SPREAD = re.compile(r"^spread:\s*(.+?)\s*\(([+-]?\d+(?:\.\d+)?)\)\s*$", re.I)
OUR_TOTAL = re.compile(r"^(.+?)\s+vs\.?\s+(.+?):\s*(?:1h\s+)?(?:o/u|over/under)\s*(\d+(?:\.\d+)?)\s*([^0-9]*)$", re.I)
OUR_ML = re.compile(r"^(?:[^:]{2,40}:\s*)?(.+?)\s+(?:vs\.?|v\.?)\s+(.+?)(?:\s*\([^)]*\))?\s*$", re.I)

K_ML = re.compile(r"^(.+?)\s+wins?$", re.I)
K_SPREAD = re.compile(r"^(.+?)\s+wins? by over\s+(\d+(?:\.\d+)?)\s+points?$", re.I)
K_TOTAL = re.compile(r"^(?:full game:\s*)?over\s+(\d+(?:\.\d+)?)\s+(?:points?|goals?|runs?)\s+scored\s*\??$", re.I)
PARTIAL = re.compile(r"^(1st half|2nd half|1st quarter|2nd quarter|3rd quarter|4th quarter|"
                     r"[1-4][hq]\b|first half|second half|team total|correct score|"
                     r"series|map \d|game \d|to win the series)", re.I)


def teams_from_pair(txt):
    m = OUR_ML.match((txt or "").strip())
    return [m.group(1), m.group(2)] if m else []


def our_contract(q):
    q = (q or "").strip()
    m = OUR_SPREAD.match(q)
    if m:
        return {"klass": "SPREAD", "subject": m.group(1), "line": abs(float(m.group(2))), "teams": []}
    # Both-teams-to-score, corners, cards, clean sheets and player props are NOT the two named
    # result sides. Without this gate "Belgium vs. Italy: Both Teams to Score" parsed as a
    # MONEYLINE on the two named teams and matched a Kalshi "Belgium wins" contract.
    # The card clause must be 'yellow/red card(s)', never a bare 'card': a UFC question is
    # suffixed "(Middleweight, Main Card)" and a bare \bcard\b reclassified four real pairs.
    if re.search(r"\bbtts\b|both teams to score|\bcorner|\b(yellow|red) cards?\b|total cards|"
                 r"clean sheet|first goal|anytime|\bplayer prop", q, re.I):
        return {"klass": "OTHER", "teams": []}
    m = OUR_TOTAL.match(q)
    if m:
        # "A vs B: O/U n" and nothing after the line. A team total
        # ("...: Tottenham Hotspur FC O/U 2.5"), corners, cards and player props all
        # fail that shape and are OTHER, not a game total.
        if re.search(r"\b1h\b|first half|1st half", q, re.I) or (m.group(4) or "").strip():
            return {"klass": "OTHER", "teams": []}
        return {"klass": "TOTAL", "subject": None, "line": float(m.group(3)),
                "teams": [m.group(1).strip(), m.group(2).strip()]}
    m = OUR_ML.match(q)
    if m and not re.search(r"\b(game \d|bo3|group|map \d|winner of)\b", q, re.I) \
            and not re.search(r"o/u|over/under", q, re.I):
        # an O/U question that did not match OUR_TOTAL is a team total, a corner
        # count or a player prop: never a moneyline on the two named sides.
        return {"klass": "MONEYLINE", "subject": None, "teams": [m.group(1), m.group(2)]}
    return {"klass": "OTHER", "teams": []}


def kalshi_contract(title, sub=""):
    raw_title = (title or "").strip()
    for t in [title, sub]:
        t = (t or "").strip()
        if not t:
            continue
        if PARTIAL.match(t):
            return {"klass": "PARTIAL", "raw": t, "raw_title": t}
        m = K_SPREAD.match(t)
        if m:
            return {"klass": "SPREAD", "subject": m.group(1), "line": float(m.group(2)), "raw_title": t}
        m = K_TOTAL.match(t)
        if m:
            return {"klass": "TOTAL", "line": float(m.group(1)), "raw_title": t}
        m = K_ML.match(t)
        if m:
            return {"klass": "MONEYLINE", "subject": m.group(1), "raw_title": t}
    return {"klass": "OTHER", "raw": raw_title, "raw_title": raw_title}


def event_verified(ours, event_title):
    if ours["klass"] in ("MONEYLINE", "TOTAL"):
        return len(ours["teams"]) == 2 and teams_verified(ours["teams"], event_title)
    if ours["klass"] == "SPREAD":
        sides = split_sides(event_title)
        return bool(sides) and any(subject_match(ours["subject"], sd)[0] for sd in sides)
    return False


def pick_events(ours, events, day, window_days=1.0):
    """Name-verified GAME candidates, as (gapSeconds, title, [event tickers]).

    One game is listed as several Kalshi events (GAME / SPREAD / TOTAL each carry the
    same matchup title), so candidates are keyed by their title and the tickers are
    grouped: otherwise every game looks ambiguous against itself.

    Guards, each load-bearing:
      * a 'vs' title only — a season-long market ("LSU Regular Season Wins",
        "Colorado presidential election winner?") names our subject and, having no
        date in its ticker, used to win every comparison;
      * a ticker date within window_days — the same subject plays repeatedly;
      * no derived family (1H/2H/Q/team-total) — those are DIFFERENT contracts.
    """
    out = {}
    for ticker, title, ed in events:
        fam = (ticker or "").split("-")[0]
        if re.search(r"(TEAMTOTAL|(^|\D)(1H|2H|1Q|2Q|3Q|4Q)(SPREAD|TOTAL)?$)", fam):
            continue
        if " vs " not in (title or "").lower():
            continue
        if not event_verified(ours, title):
            continue
        if ed is None or day is None:
            continue
        gap = abs(ed - day)
        if gap > window_days * 86400:
            continue
        # one game is listed as GAME / SPREAD / TOTAL / ... with the same matchup and
        # a ": <contract>" tail: key on the matchup, not the tail
        key = matchup_key(title)
        prev = out.get(key)
        if prev is None:
            out[key] = (gap, title, [ticker])
        else:
            # every contract family of the same game must keep its ticker; only the
            # distance and the display title follow the closest one
            out[key] = (min(prev[0], gap), prev[1], prev[2] + ([ticker] if ticker not in prev[2] else []))
    return sorted(out.values(), key=lambda x: x[0])


SPORT_FAMILY = {
    "cfb": ["KXNCAAF"], "cbb": ["KXNCAAMB"], "ncaawb": ["KXNCAAWB"],
    "nba": ["KXNBA"], "nfl": ["KXNFL"], "nhl": ["KXNHL"], "mlb": ["KXMLB"],
    "wnba": ["KXWNBA"], "epl": ["KXEPL"], "efl": ["KXEFL"], "ucl": ["KXUCL"],
    "uel": ["KXUEL"], "nwsl": ["KXNWSL"], "ufc": ["KXUFC"], "atp": ["KXATP"],
    "wta": ["KXWTA"], "arg": ["KXARGPREMDIV"], "bel1": ["KXBELGIANPL"],
    "bun": ["KXBUNDESLIGA"], "bl2": ["KXBUNDESLIGA"], "liga": ["KXLALIGA"],
    "seriea": ["KXSERIEA"], "ligue1": ["KXLIGUE1"], "dota2": ["KXDOTA"],
    "cs2": ["KXCS2"], "lol": ["KXLOL"],
}

DATE_PART = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")


def parse_slug(market_id):
    """PM market ids ARE slugs: <sport>-<team>-<team>-<YYYY-MM-DD>-<type>-<line>.

    This is the identity the question TEXT does not carry: which sport, which two
    teams, which day. Without it a one-team spread question ("Spread: LSU (-14.5)")
    cannot say whether LSU means football or basketball, and 13 of 115 markets came
    back AMBIGUOUS for exactly that reason.
    """
    parts = (market_id or "").split("-")
    if len(parts) < 5:
        return None
    for i in range(len(parts) - 2):
        m = DATE_PART.match("-".join(parts[i:i + 3]))
        if not m:
            continue
        teams = [x for x in parts[1:i] if x and not x.isdigit()]
        if len(teams) != 2:
            return None
        try:
            day = time.mktime((int(m.group(1)), int(m.group(2)), int(m.group(3)),
                               12, 0, 0, 0, 0, -1))
        except (ValueError, OverflowError):
            return None
        tail = parts[i + 3:]
        line = None
        for t in tail:
            lm = re.match(r"^(\d+)pt(\d+)$", t)
            if lm:
                line = float(f"{lm.group(1)}.{lm.group(2)}")
        return {"sport": parts[0], "teams": teams, "day": day, "tail": tail, "line": line,
                "families": SPORT_FAMILY.get(parts[0], [])}
    return None


def code_match(code, side):
    """Slug team code vs one side of an event title: 'tenn' ~ Tennessee, 'lsu' ~ LSU."""
    code = (code or "").lower()
    if len(code) < 3:
        return False
    for t in tokens(side):
        if t.startswith(code) or code.startswith(t) or (len(t) >= 3 and t in code):
            return True
    return False


LEAGUE_LABEL = {"fc", "afc", "sc", "cf", "club", "the", "vs", "v", "and", "ac", "ss", "ssc"}


def atokens(text):
    """Tokens that KEEP the words which distinguish a split city.

    `tokens()` drops 'city', 'united', 'state' and 'st' as generic because question text
    pads team names with them — correct for scoring free text, fatal for aliases: it makes
    'Manchester City' and 'Manchester United' the same one-token team, and 'New York' the
    same for both Knicks and Islanders. An alias carries the venue's OWN rendered name, so
    only competition labels are stripped here.
    """
    text = (text or "").lower().replace("'", "").replace("\u2019", "")
    return {w for w in re.findall(r"[a-z0-9]+", text) if w not in LEAGUE_LABEL}


def alias_match(sport, code, side, aliases):
    """Slug code vs a venue side name, through the derived table. None = no entry, so the
    caller may fall back to the heuristic in `code_match`."""
    forms = ((aliases or {}).get(sport) or {}).get((code or "").lower())
    if not forms:
        return None
    st = atokens(side)
    for form in forms:
        ft = atokens(form)
        if ft and ft <= st and state_marker(form) == state_marker(side):
            return True
    return False


def team_match(sport, code, side, aliases):
    """Alias first, heuristic only for codes the table does not cover (college, cups)."""
    am = alias_match(sport, code, side, aliases)
    if am is not None:
        return am
    return code_match(code, side)


def team_index(subject, sl, aliases):
    """Which of the slug's two teams does `subject` name? None when it is neither or both."""
    if not sl or not subject:
        return None
    hits = [i for i, c in enumerate(sl["teams"])
            if team_match(sl["sport"], c, subject, aliases)]
    return hits[0] if len(hits) == 1 else None


def matchup_key(title):
    """Group a game's contract families under ONE key.

    The venue lists the same game under several event TITLES — "Liverpool vs Manchester
    United: Total Goals" and "Liverpool FC vs Manchester United: Correct Score" — so keying
    on the raw title made a single game AMBIGUOUS AGAINST ITSELF (2 rows in the first shadow
    run, both soccer). The key is the matchup's identity tokens, order-independent, with
    competition labels ("FC", "SC", "Club") dropped.
    """
    sides = split_sides(title)
    if not sides:
        return re.sub(r"\s+", " ", (title or "").split(":")[0].lower()).strip()
    bag = set()
    for sd in sides:
        bag |= atokens(sd)
    return "|".join(sorted(bag))


def pick_events_slug(sl, events, aliases=None, window_days=1.0):
    """Event candidates constrained by slug sport family + slug day + both team codes."""
    out = {}
    for ticker, title, ed in events:
        fam = (ticker or "").split("-")[0]
        if re.search(r"(TEAMTOTAL|(^|\D)(1H|2H|1Q|2Q|3Q|4Q)(SPREAD|TOTAL)?$)", fam):
            continue
        if not any(ticker.startswith(f) for f in sl["families"]):
            continue
        if " vs " not in (title or "").lower():
            continue
        if ed is None or abs(ed - sl["day"]) > window_days * 86400:
            continue
        sides = split_sides(title)
        if not sides:
            continue
        a = [i for i, sd in enumerate(sides) if team_match(sl["sport"], sl["teams"][0], sd, aliases)]
        b = [i for i, sd in enumerate(sides) if team_match(sl["sport"], sl["teams"][1], sd, aliases)]
        if not any(i != j for i in a for j in b):
            continue
        key = matchup_key(title)
        prev = out.get(key)
        if prev is None:
            out[key] = (abs(ed - sl["day"]), title, [ticker])
        else:
            out[key] = (min(prev[0], abs(ed - sl["day"])), prev[1],
                        prev[2] + ([ticker] if ticker not in prev[2] else []))
    return sorted(out.values(), key=lambda x: x[0])


def spread_index(sl):
    """Which slug team a SPREAD question is about. PM encodes it in the id tail
    ('...-spread-home-13pt5' / '...-spread-away-5pt5'), so the answer is deterministic
    rather than inferred from a nickname the venue never uses."""
    tail = (sl or {}).get("tail") or []
    if "home" in tail:
        return 1
    if "away" in tail:
        return 0
    return None


SIDE_CHECK = Counter()


def verdict(ours, theirs, sl=None, aliases=None):
    if not theirs:
        return "NO_CONTRACT"
    if ours["klass"] != theirs["klass"]:
        return "DIFFERENT_CONTRACT"
    if ours["klass"] == "TOTAL":
        return "EQUIV" if abs(ours["line"] - theirs["line"]) < 1e-9 else "DIFFERENT_CONTRACT"
    if ours["klass"] == "SPREAD":
        if abs(ours["line"] - theirs["line"]) >= 1e-9:
            return "DIFFERENT_CONTRACT"
        idx = spread_index(sl)
        ti = team_index(theirs.get("subject"), sl, aliases)
        if idx is not None and ti is not None:
            # Cross-check the id tail against our own question's subject whenever the subject
            # names one of the slug teams (true for college codes). Agreement is the norm;
            # a disagreement means the side encoding moved and NO claim should be made.
            osi = team_index(ours.get("subject"), sl, aliases)
            if osi is None:
                SIDE_CHECK["undetermined"] += 1
            elif osi == idx:
                SIDE_CHECK["agree"] += 1
            else:
                SIDE_CHECK["disagree"] += 1
                print(f"  ! spread side disagreement: {ours.get('subject')!r} vs "
                      f"{sl['teams']}/{sl['tail']}", file=sys.stderr)
                return "DIFFERENT_CONTRACT"
            return "EQUIV" if ti == idx else "DIFFERENT_CONTRACT"
        return "EQUIV" if subject_match(ours["subject"], theirs["subject"])[0] else "DIFFERENT_CONTRACT"
    if ours["klass"] == "MONEYLINE":
        hit = [t for t in ours["teams"] if subject_match(t, theirs["subject"])[0]]
        if hit:
            return "EQUIV"
        # The venue names the city, our question names the nickname: attribute the contract
        # subject to a slug team instead of comparing two vocabularies.
        return "EQUIV" if team_index(theirs.get("subject"), sl, aliases) is not None else "DIFFERENT_CONTRACT"
    return "DIFFERENT_CONTRACT"


def ticker_day(ticker):
    m = re.search(r"-(\d{2})([A-Z]{3})(\d{2})", ticker or "")
    if not m:
        return None
    try:
        return time.mktime((2000 + int(m.group(1)), MONTHS[m.group(2)], int(m.group(3)),
                            12, 0, 0, 0, 0, -1))
    except (KeyError, ValueError, OverflowError):
        return None


def get(url, tries=4):
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


def event_markets(event_ticker, ttl_hours=12.0):
    os.makedirs(MCACHE, exist_ok=True)
    path = os.path.join(MCACHE, event_ticker.replace("/", "_") + ".json")
    if os.path.exists(path) and (time.time() - os.path.getmtime(path)) / 3600.0 < ttl_hours:
        with open(path) as f:
            return json.load(f)
    d = get(f"{BASE}/markets?" + urllib.parse.urlencode({"event_ticker": event_ticker, "limit": "200"}))
    ms = [{"ticker": m.get("ticker", ""), "title": m.get("title", ""),
           "yes_sub_title": m.get("yes_sub_title", "")} for m in d.get("markets", [])]
    with open(path, "w") as f:
        json.dump(ms, f)
    return ms




def window_pool(from_ms, to_ms, max_pages=250, ttl_hours=24.0):
    """Every event the venue CLOSED inside the window.

    WHY THIS EXISTS — an instrument defect found while executing this card's approved
    change. `data/kalshi-event-index.json` is a snapshot of events that were OPEN when it was
    built, so a trailing 7d read asks "was there a counterpart?" against a pool that has
    already DELETED the counterparts: a game that settled yesterday is gone. On the
    2026-11-14..21 window, 6 of the 9 naming-blocked NBA markets had no event anywhere in
    the open index — their games had finished — so they were being counted as
    NO_EVENT_MATCH ("naming unverified") when nothing about the naming was at issue.
    The venue keeps closed events queryable, so the pool is rebuilt for the window and
    cached per window: same clock, same pool, re-runnable.
    """
    os.makedirs(WCACHE, exist_ok=True)
    key = f"{int(from_ms/86400000)}_{int(to_ms/86400000)}_p{max_pages}"
    path = os.path.join(WCACHE, key + ".json")
    if os.path.exists(path) and (time.time() - os.path.getmtime(path)) / 3600.0 < ttl_hours:
        with open(path) as f:
            return json.load(f)
    events, cursor, pages = [], None, 0
    while pages < max_pages:
        q = {"status": "settled", "limit": "200",
             "min_close_ts": int(from_ms / 1000), "max_close_ts": int(to_ms / 1000)}
        if cursor:
            q["cursor"] = cursor
        d = get(f"{BASE}/events?" + urllib.parse.urlencode(q))
        ev = d.get("events", [])
        pages += 1
        for e in ev:
            if e.get("event_ticker"):
                events.append({"ticker": e["event_ticker"], "title": e.get("title") or ""})
        cursor = d.get("cursor")
        if not cursor or not ev:
            break
    # A truncated walk silently hides a whole slice of the window, so say which happened:
    # the first build of this pool capped at 90 pages and reported nothing.
    print(f"window pool: {len(events)} closed events over {pages} pages — "
          f"cursor {'EXHAUSTED' if not cursor else 'TRUNCATED (raise --pool-pages)'}, "
          f"cache {os.path.basename(path)}")
    with open(path, "w") as f:
        json.dump(events, f)
    return events


def self_test():
    ok = 0
    arms = 0

    def arm(name, cond):
        nonlocal ok, arms
        arms += 1
        print(f"  {'PASS' if cond else 'FAIL'}  {name}")
        if cond:
            ok += 1
    o = our_contract("Spread: Colorado (-17.5)")
    arm("our spread parse", o["klass"] == "SPREAD" and o["line"] == 17.5 and "Colorado" in o["subject"])
    o = our_contract("Warriors vs. Grizzlies: O/U 201.5")
    arm("our total parse carries both teams", o["klass"] == "TOTAL" and len(o["teams"]) == 2)
    arm("1H total is not a full-game total", our_contract("Warriors vs. Grizzlies: 1H O/U 105.5")["klass"] == "OTHER")
    o = our_contract("Will Bitcoin dip to $62,000 on November 17?")
    arm("barrier market is OTHER", o["klass"] == "OTHER")
    arm("series game is not a moneyline",
        our_contract("Dota 2: LGD Gaming vs PARIVISION - Game 2 Winner")["klass"] == "OTHER")

    arm("kalshi spread parse", kalshi_contract("Colorado wins by over 17.5 points")["line"] == 17.5)
    arm("kalshi total parse", kalshi_contract("Full Game: over 201.5 points scored?")["klass"] == "TOTAL")
    arm("title-free market falls back to yes_sub_title",
        kalshi_contract("Full Game total", "over 43.5 points scored?")["line"] == 43.5)
    arm("quarter total is PARTIAL", kalshi_contract("1st Quarter: over 51.5 points scored?")["klass"] == "PARTIAL")

    arm("same line + same team = EQUIV",
        verdict(our_contract("Spread: Colorado (-17.5)"),
                kalshi_contract("Colorado wins by over 17.5 points")) == "EQUIV")
    arm("one cent of line = DIFFERENT_CONTRACT",
        verdict(our_contract("Spread: Colorado (-17.5)"),
                kalshi_contract("Colorado wins by over 16.5 points")) == "DIFFERENT_CONTRACT")
    arm("short team name LSU matches (>=3 chars)",
        subject_match("LSU", "LSU wins by over 14.5 points")[0])
    arm("abbrev tolerated",
        verdict(our_contract("Morgan State vs. North Carolina Central"),
                kalshi_contract("Morgan St. wins")) == "EQUIV")
    arm("one named side is enough INSIDE a verified event",
        verdict(our_contract("Pelicans vs. Spurs"), kalshi_contract("Pelicans wins")) == "EQUIV")
    arm("event gate needs both teams",
        not event_verified(our_contract("Pelicans vs. Spurs"), "Lahti Pelicans vs Vaasan Sport"))
    arm("event gate passes on both teams",
        event_verified(our_contract("UT Rio Grande Valley vs. Houston Christian"),
                       "UT Rio Grande Valley vs Houston Christian"))
    arm("total line mismatch = DIFFERENT_CONTRACT",
        verdict(our_contract("Warriors vs. Grizzlies: O/U 201.5"),
                kalshi_contract("Full Game: over 202.5 points scored?")) == "DIFFERENT_CONTRACT")
    arm("ticker date parsed", ticker_day("KXNCAAFSPREAD-26NOV21LSUTENN") is not None)
    arm("prefixed title splits on vs, not on ':'",
        split_sides("Fight Night: Shamil Gaziev vs Tallison Teixeira") == ["Shamil Gaziev", "Tallison Teixeira"])
    arm("slug code matches its side", code_match("tenn", "Tennessee"))
    arm("Georgia is not Georgia St.", not subject_match("Georgia", "Georgia St.")[0])
    arm("Morgan State IS Morgan St.", subject_match("Morgan State", "Morgan St.")[0])
    arm("team total is not a moneyline",
        our_contract("Tottenham Hotspur FC vs. Ipswich Town FC: Tottenham Hotspur FC O/U 2.5")["klass"] == "OTHER")
    arm("total corners is not a goal total",
        our_contract("Athletic Club vs. RCD Espanyol de Barcelona: O/U 11.5 Total Corners")["klass"] == "OTHER")
    arm("player-prop total is not a game total",
        our_contract("Devin Booker: Points O/U 29.5")["klass"] == "OTHER")
    _ev = [("KXPRESSTATE-CO-28", "Colorado presidential election winner?", ticker_day("KXPRESSTATE-CO-28")),
           ("KXNCAAFSPREAD-26NOV21COLOCIN", "Colorado vs Cincinnati: Spread", ticker_day("KXNCAAFSPREAD-26NOV21COLOCIN"))]
    _day = ticker_day("KXNCAAFSPREAD-26NOV21COLOCIN")
    arm("season-long/undated event never wins a game question",
        [p[2] for p in pick_events(our_contract("Spread: Colorado (-17.5)"), _ev, _day)] == [["KXNCAAFSPREAD-26NOV21COLOCIN"]])

    # --- alias table: the approved change (code -> venue name), one arm per failure it prevents
    AL = {"nba": {"nop": ["New Orleans"], "sas": ["San Antonio"], "lal": ["Los Angeles L"],
                  "lac": ["Los Angeles C"], "det": ["Detroit"], "tor": ["Toronto"]},
          "epl": {"mac": ["Manchester City"], "mun": ["Manchester United"]}}
    arm("alias resolves the city the venue publishes",
        alias_match("nba", "nop", "New Orleans", AL) is True)
    arm("alias keeps the two LA teams apart",
        alias_match("nba", "lal", "Los Angeles C", AL) is False
        and alias_match("nba", "lal", "Los Angeles L", AL) is True)
    arm("alias keeps Manchester City from matching Manchester United",
        alias_match("epl", "mac", "Manchester United", AL) is False
        and alias_match("epl", "mac", "Manchester City", AL) is True)
    arm("alias table ABSTAINS on a code it does not list (falls back to the heuristic)",
        alias_match("cfb", "tenn", "Tennessee", AL) is None and team_match("cfb", "tenn", "Tennessee", AL))
    # --- college (2026-11-25): the derived table, not an authored one -----------------
    # The derivation (scripts/kalshi-team-aliases.py --derive-college) places a code by
    # voting over same-day two-sided venue events; what the RESOLVER must now do is use it.
    ALC = {"cfb": {"vtech": ["Virginia Tech"], "washst": ["Washington St."],
                   "ga": ["Georgia"], "gast": ["Georgia St."], "smho": ["Sam Houston"]},
           "cbb": {"vtech": ["Virginia Tech"], "nw": ["Northwestern"]}}
    arm("college alias resolves a contracted code (vtech -> Virginia Tech)",
        alias_match("cfb", "vtech", "Virginia Tech", ALC) is True)
    arm("college alias keeps Georgia off Georgia St.",
        alias_match("cfb", "ga", "Georgia St.", ALC) is False
        and alias_match("cfb", "ga", "Georgia", ALC) is True)
    arm("college alias places a 2-char code the heuristic cannot (nw -> Northwestern)",
        alias_match("cbb", "nw", "Northwestern", ALC) is True
        and code_match("nw", "Northwestern") is False)
    arm("college moneyline EQUIV through the derived table",
        verdict(our_contract("Virginia Tech Hokies vs. Northwestern Wildcats"),
                kalshi_contract("Virginia Tech wins"),
                {"sport": "cbb", "teams": ["vtech", "nw"], "day": 0, "tail": []}, ALC) == "EQUIV")
    arm("college moneyline naming the OPPONENT is the same CONTRACT (the held side is separate)",
        verdict(our_contract("Virginia Tech Hokies vs. Northwestern Wildcats"),
                kalshi_contract("Northwestern wins"),
                {"sport": "cbb", "teams": ["vtech", "nw"], "day": 0, "tail": []}, ALC) == "EQUIV")
    arm("college moneyline naming a SCHOOL OUTSIDE our slug is refused",
        verdict(our_contract("Virginia Tech Hokies vs. Northwestern Wildcats"),
                kalshi_contract("Georgia St. wins"),
                {"sport": "cbb", "teams": ["vtech", "nw"], "day": 0, "tail": []}, ALC)
        == "DIFFERENT_CONTRACT")
    arm("college spread EQUIV on the side the slug tail names",
        verdict(our_contract("Spread: Georgia (-9.5)"),
                kalshi_contract("Georgia wins by over 9.5 points"),
                {"sport": "cfb", "teams": ["ga", "sc"], "day": 0,
                 "tail": ["spread", "away", "9pt5"]}, ALC) == "EQUIV")
    _sl_home = {"sport": "nba", "teams": ["tor", "det"], "day": 0, "tail": ["spread", "home", "13pt5"]}
    _sl_away = {"sport": "nba", "teams": ["nop", "sas"], "day": 0, "tail": ["spread", "away", "5pt5"]}
    arm("spread side is read from the id tail",
        spread_index(_sl_home) == 1 and spread_index(_sl_away) == 0)
    arm("moneyline EQUIV through the alias where the nickname never meets the city",
        verdict(our_contract("Pelicans vs. Spurs"), kalshi_contract("New Orleans wins"),
                {"sport": "nba", "teams": ["nop", "sas"], "day": 0, "tail": []}, AL) == "EQUIV")
    arm("moneyline NOT EQUIV when the contract names a team outside our slug",
        verdict(our_contract("Pelicans vs. Spurs"), kalshi_contract("New Orleans wins"),
                {"sport": "epl", "teams": ["mac", "mun"], "day": 0, "tail": []}, AL) == "DIFFERENT_CONTRACT")
    arm("spread EQUIV on the home side the slug names",
        verdict(our_contract("Spread: Pistons (-13.5)"), kalshi_contract("Detroit wins by over 13.5 points"),
                _sl_home, AL) == "EQUIV")
    arm("spread DIFFERENT when the contract names the other side of the same game",
        verdict(our_contract("Spread: Pistons (-13.5)"), kalshi_contract("Toronto wins by over 13.5 points"),
                _sl_home, AL) == "DIFFERENT_CONTRACT")
    arm("alias tokens keep the words that separate a split city",
        atokens("Manchester City") == {"manchester", "city"} and not atokens("Manchester City") <= atokens("Manchester United"))
    arm("one game listed under two titles is ONE candidate",
        matchup_key("Liverpool vs Manchester United: Total Goals")
        == matchup_key("Liverpool FC vs Manchester United: Correct Score")
        and matchup_key("Liverpool vs Manchester United: Total Goals")
        != matchup_key("Liverpool vs Arsenal: Total Goals"))
    arm("a club's city does not match the OPPONENT (Espanyol de Barcelona vs Barcelona)",
        not subject_match("RCD Espanyol de Barcelona", "Barcelona")[0])
    arm("a one-token candidate that IS our head still matches (Marquette)",
        subject_match("Marquette Golden Eagles", "Marquette")[0])
    arm("both-teams-to-score is not a moneyline on the two named sides",
        our_contract("Belgium vs. Italy: Both Teams to Score")["klass"] == "OTHER")
    arm("a UFC 'Main Card' suffix is STILL a moneyline (a bare \\bcard\\b rule ate 4 real pairs)",
        our_contract("UFC Fight Night: Jared Cannonier vs. Ikram Aliskerov (Middleweight, Main Card)"
                     )["klass"] == "MONEYLINE")
    # --- side_yes (repaired 2026-11-23: the spread tail is the MARKET's side, not ours)
    sl_bkn = parse_slug("nba-phi-bkn-2026-11-16")
    sl_hou = parse_slug("cbb-hou-kan-2026-11-19-spread-home-1pt5")
    sp_ours = our_contract("Spread: Kansas Jayhawks (-1.5)")
    sp_k = kalshi_contract("Kansas wins by over 1.5 points")
    arm("side_yes: a SPREAD holder of the NON-subject team is the NO side",
        side_yes(sp_ours, sp_k, "HOUSTON COUGARS", sl_hou, {}) is False)
    arm("side_yes: a SPREAD holder of the subject team is the YES side",
        side_yes(sp_ours, sp_k, "KANSAS JAYHAWKS", sl_hou, {}) is True)
    arm("side_yes MUTATION: the retired tail rule answers YES on the same fixture",
        spread_index(sl_hou) == team_index(sp_k["subject"], sl_hou, {}))
    arm("side_yes: a MONEYLINE nickname maps to the city subject",
        side_yes(our_contract("76ers vs. Nets"), kalshi_contract("Brooklyn wins"),
                 "NETS", sl_bkn, {"nba": {"bkn": ["Brooklyn"], "phi": ["Philadelphia"]}}) is True)
    # the case that matters in practice: our outcome is the venue's NICKNAME, the contract
    # carries the CITY, and the alias table only stores the city -- a partial overlap must
    # abstain, because guessing here prices the wrong token
    arm("side_yes: a nickname/city overlap the alias table cannot place abstains",
        side_yes(our_contract("Spread: NY Knicks (-7.5)"),
                 kalshi_contract("New York wins by over 7.5 points"),
                 "KNICKS", parse_slug("nba-por-nyk-2026-11-21-spread-home-7pt5"), {}) is None)
    arm("side_yes: a label that shares nothing with the subject is the opponent's side",
        side_yes(our_contract("Spread: Kansas Jayhawks (-1.5)"),
                 kalshi_contract("Kansas wins by over 1.5 points"),
                 "TRAIL BLAZERS", None, {}) is False)

    print(f"\nself-test {ok}/{arms}")
    return 0 if ok == arms else 1


def market_quote(ticker):
    """Two-sided quote for ONE Kalshi market, in dollars, plus the fields we store for audit.

    The venue's `*_dollars` fields are STRINGS ("0.2700") and the legacy `yes_bid`/`yes_ask`
    are integer cents — a float-only parser reads a live book as "no quote", which is how the
    first test of this path returned price=null on a live market.
    """
    d = get(f"{BASE}/markets/{urllib.parse.quote(ticker)}")
    m = d.get("market") or {}

    def usd(*keys):
        for k in keys:
            v = m.get(k)
            scale = 1.0 if k.endswith("_dollars") else 100.0
            if isinstance(v, bool) or v is None:
                continue
            if isinstance(v, (int, float)):
                return float(v) / scale
            if isinstance(v, str) and v.strip():
                try:
                    return float(v) / scale
                except ValueError:
                    continue
        return None

    return {"ticker": m.get("ticker", ticker), "title": m.get("title") or "",
            "yesSubtitle": m.get("yes_sub_title") or "",
            "yesBid": usd("yes_bid_dollars", "yes_bid"),
            "yesAsk": usd("yes_ask_dollars", "yes_ask"),
            "lastPrice": usd("last_price_dollars", "last_price"),
            "rulesPrimary": (m.get("rules_primary") or "")[:400],
            "status": m.get("status") or ""}


def side_yes(ours, theirs, outcome, sl, aliases):
    """Is OUR side of the trade the YES side of the matched Kalshi contract?

    True / False / None. None = cannot tell, and then no price is booked (never guess).

    FIXED 2026-11-23: the SPREAD branch used the QUESTION's spread tail
    (`spread_index`) as our side. That tail names the team the line is written on, which
    is the contract's own subject on every EQUIV pair, so the function answered YES for
    every spread trade -- including the 13 of 37 settled pairs where we held the
    opponent, which made the settlement audit unreadable (see
    scripts/kalshi-pair-settlement-read.py and its mutation arm). Our side is now the
    position of OUR OWN outcome, in whichever vocabulary it is written.

    Three vocabularies meet here: the slug carries CODES ("nyk"), the contract carries
    CITIES ("New York"), our outcome carries the venue's LABEL ("KNICKS"). The index is
    therefore taken from the side that can actually be read, never from the market.
    """
    o = (outcome or "").strip().lower()
    if ours["klass"] == "TOTAL":
        if o.startswith("over") or o in ("yes", "up"):
            return True
        if o.startswith("under") or o in ("no", "down"):
            return False
        return None
    if not o or o in ("yes", "no", "up", "down"):
        return None
    subject = theirs.get("subject") or ""
    if subject_match(outcome, subject)[0]:
        return True
    if ours["klass"] == "SPREAD":
        # The question names ONE team and that team IS the contract subject (verdict()
        # cross-checks this through the id tail). Our outcome and that name are BOTH venue
        # labels, so they compare directly -- and a name pair that shares no distinctive
        # token at all is the opponent, because a spread market has exactly two sides.
        # Anything in between (partial overlap: "NEW YORK KNICKS" vs "NY Knicks") abstains
        # rather than guess a side, because a wrong side prices the wrong token.
        q_subj = ours.get("subject") or ""
        if q_subj:
            if subject_match(outcome, q_subj)[0]:
                return True
            if not (tokens(outcome) & tokens(q_subj)):
                return False
        oi = team_index(outcome, sl, aliases) if sl else None
        ti = team_index(subject, sl, aliases) if sl else None
        if oi is not None and ti is not None:
            return oi == ti
        return None
    # MONEYLINE (and anything else that names both sides): our outcome's position among
    # our own two named teams vs the contract subject's slug position.
    oi = next((k for k, t in enumerate(ours.get("teams") or [])
               if t and subject_match(outcome, t)[0]), None)
    ti = team_index(subject, sl, aliases) if sl else None
    if oi is not None and ti is not None:
        return oi == ti
    return False


def resolve(req_path, out_path=None):
    """Shadow-lane resolver: contract-equivalent pairs for a batch of OUR trades.

    This is the wiring the card asked for — the shipped parser feeds the venue shadow lane
    (observation only: no execution, no sizing, no capital). It is the SAME functions the
    measurement uses, so a pair that the report counts is a pair the lane can price.
    Input : [{"marketId", "question", "dayMs", "outcome"}]
    Output: [{"marketId", "verdict", "ticker", "kalshiTitle", "yesBid", "yesAsk", "price", ...}]
    """
    with open(req_path) as f:
        reqs = json.load(f)
    if not reqs:
        print("[]")
        return 0
    try:
        with open(ALIASES) as f:
            aliases = {k: v for k, v in json.load(f).items() if not k.startswith("_")}
    except (OSError, ValueError):
        aliases = {}
    with open(INDEX) as f:
        idx = json.load(f)
    days = [r.get("dayMs") or 0 for r in reqs if r.get("dayMs")]
    lo, hi = (min(days), max(days)) if days else (time.time() * 1000, time.time() * 1000)
    events = [(e.get("ticker", ""), e.get("title") or "", ticker_day(e.get("ticker", "")))
              for e in idx["events"] if e.get("title")]
    seen = {e[0] for e in events}
    for e in window_pool(lo - 2 * 86400_000, hi + 2 * 86400_000):
        if e["ticker"] not in seen:
            seen.add(e["ticker"])
            events.append((e["ticker"], e["title"], ticker_day(e["ticker"])))

    out, cache = [], {}
    for r in reqs:
        mid = r.get("marketId") or ""
        ours = our_contract(r.get("question"))
        sl = parse_slug(mid)
        # `outcome` is ECHOED, not inferred: the caller keys its answer map by
        # (marketId, outcome), because one Polymarket market can carry two of our legs
        # (one per outcome) and a marketId-only key stamps both with the same answer.
        rec = {"marketId": mid, "outcome": r.get("outcome"),
               "verdict": "OTHER_CLASS" if ours["klass"] == "OTHER" else "NO_EVENT_MATCH",
               "ticker": None, "kalshiTitle": None, "yesBid": None, "yesAsk": None,
               "price": None, "line": ours.get("line"), "class": ours["klass"]}
        if ours["klass"] != "OTHER" and sl and sl["families"]:
            picks = pick_events_slug(sl, events, aliases)
            if len(picks) == 1:
                # Collect EVERY equivalent contract in the event, then prefer the one whose
                # side is OURS: a two-sided game lists one market per team and both are
                # "equivalent" to a moneyline question, so taking the first one books the
                # wrong side of our own trade.
                cands = []
                for ct in picks[0][2]:
                    if ct not in cache:
                        try:
                            cache[ct] = event_markets(ct)
                        except Exception:
                            cache[ct] = []
                    for m in cache[ct]:
                        t = kalshi_contract(m["title"], m["yes_sub_title"])
                        if verdict(ours, t, sl, aliases) != "EQUIV":
                            continue
                        yes = side_yes(ours, t, r.get("outcome"), sl, aliases)
                        cands.append((yes is True, ct, m, t, yes))
                if cands:
                    _ok, ct, m, t, yes = sorted(cands, key=lambda c: not c[0])[0]
                    rec.update({"verdict": "EQUIV", "ticker": m.get("ticker") or ct,
                                "event": ct, "kalshiTitle": t.get("raw_title"),
                                "ourSideIsYes": yes})
                    try:
                        q = market_quote(m.get("ticker") or ct)
                    except Exception as e:
                        rec["note"] = f"quote failed: {e}"
                        q = None
                    if q:
                        price = None
                        if yes is True and q["yesAsk"] is not None:
                            price = q["yesAsk"]
                        elif yes is False and q["yesBid"] is not None:
                            price = round(1.0 - q["yesBid"], 4)
                        # A settled market still answers with 0/1 — a "price" of 1.00 is a
                        # resolved outcome, not a quote, and must never enter a book.
                        if q["status"] not in ("active", "open") or price is None \
                                or not (0.0 < price < 1.0):
                            rec["note"] = f"not_tradeable:{q['status'] or 'unknown'}"
                            price = None
                        rec.update({"yesBid": q["yesBid"], "yesAsk": q["yesAsk"],
                                    "lastPrice": q["lastPrice"], "price": price,
                                    "tickerStatus": q["status"], "rulesPrimary": q["rulesPrimary"]})
            elif len(picks) > 1:
                rec["verdict"] = "AMBIGUOUS_EVENT"
        out.append(rec)
    body = json.dumps(out, indent=1)
    if out_path:
        with open(out_path, "w") as f:
            f.write(body)
    print(body)
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--top", type=int, default=14)
    ap.add_argument("--out", default=OUT, help="artifact path (arms write side-by-side without "
                                               "overwriting the canonical artifact)")
    ap.add_argument("--as-of", default=None,
                    help="pin the clock, e.g. 2026-11-21T15:13Z — makes a window RE-RUNNABLE")
    ap.add_argument("--no-alias", action="store_true",
                    help="baseline arm: ignore data/kalshi-team-aliases.json (measures its lift)")
    ap.add_argument("--pool", choices=("open", "both"), default="both",
                    help="event pool: the open-index snapshot only, or the snapshot plus the "
                         "venue's CLOSED events in the window (default: both)")
    ap.add_argument("--pool-pages", type=int, default=250,
                    help="page cap for the closed-event walk (200 events/page); the log says "
                         "whether the cursor was EXHAUSTED or TRUNCATED")
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--resolve", default=None,
                    help="shadow-lane mode: JSON file of [{marketId,question,dayMs,outcome}] -> "
                         "contract-equivalent pairs with a two-sided venue quote")
    ap.add_argument("--resolve-out", default=None)
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    if args.resolve:
        return resolve(args.resolve, args.resolve_out)

    aliases = {}
    if not args.no_alias:
        try:
            with open(ALIASES) as f:
                aliases = {k: v for k, v in json.load(f).items() if not k.startswith("_")}
        except (OSError, ValueError) as e:
            print(f"  ! alias table unreadable ({e}) — running the baseline arm", file=sys.stderr)

    if args.as_of:
        as_of = time.mktime(time.strptime(args.as_of, "%Y-%m-%dT%H:%MZ")) - time.timezone
    else:
        as_of = time.time()
    with open(MAP) as f:
        slug = json.load(f)
    with open(INDEX) as f:
        idx = json.load(f)
    print(f"event index: {len(idx['events'])} open events, cursor exhausted={idx['cursorExhausted']}, "
          f"built {idx['generatedAt']}; slug map built {slug['generatedAt']} at minScore {slug['minScore']}")
    print(f"clock: {time.strftime('%Y-%m-%dT%H:%MZ', time.gmtime(as_of))} "
          f"(window={args.days}d); aliases: {'OFF (baseline arm)' if not aliases else 'on, ' + str(sum(len(v) for v in aliases.values())) + ' codes'}")
    try:
        src = open(os.path.join(ROOT, "rust-sidecar", "src", "adapters.rs")).read()
        pages = int(re.search(r"MAX_EVENT_PAGES:\s*usize\s*=\s*(\d+)", src).group(1))
        thr = re.search(r"MATCH_THRESHOLD:\s*f64\s*=\s*([\d.]+)", src).group(1)
        print(f"sidecar depth (read from adapters.rs): {pages} pages x 200 = {pages*200} events at "
              f"threshold {thr} = {100.0*pages*200/len(idx['events']):.1f}% of the open-event inventory")
    except (OSError, AttributeError, ValueError):
        print("sidecar source not readable — depth not stated")

    since_ms = int((as_of - args.days * 86400) * 1000)
    con = sqlite3.connect(DB)
    rows = con.execute(
        """SELECT t.marketId, o.marketQuestion, ROUND(SUM(t.simulatedPositionSize),2),
                  MAX(o.timestamp) AS ts
           FROM PaperTrade t
           JOIN DecisionJournal d ON d.id = t.decisionJournalId
           JOIN ObservedTrade o ON o.id = d.observedTradeId
           WHERE t.botId='BANKROLL_200' AND t.isDemo=0 AND t.openedAt >= ? AND t.openedAt < ?
           GROUP BY t.marketId ORDER BY 3 DESC""",
        (since_ms, int(as_of * 1000)),
    ).fetchall()
    con.close()
    stake_all = sum(r[2] or 0 for r in rows)
    print(f"\nour C-200 markets, {args.days}d to {time.strftime('%Y-%m-%dT%H:%MZ', time.gmtime(as_of))}: "
          f"{len(rows)} markets, ${stake_all:,.2f} stake (level=market, stake=summed simulatedPositionSize)")

    events = [(e.get("ticker", ""), e.get("title") or "", ticker_day(e.get("ticker", "")))
              for e in idx["events"] if e.get("title")]
    n_open = len(events)
    if args.pool == "both":
        # closed counterparts are the majority of a trailing window; see window_pool()
        seen_tickers = {e[0] for e in events}
        for e in window_pool(since_ms - 86400_000, int(as_of * 1000), max_pages=args.pool_pages):
            if e["ticker"] not in seen_tickers:
                seen_tickers.add(e["ticker"])
                events.append((e["ticker"], e["title"], ticker_day(e["ticker"])))
    print(f"event pool: {len(events)} titled events for G1 "
          f"(open-index snapshot {n_open}, +{len(events)-n_open} closed inside the window)")

    by_class, stake_class = Counter(), Counter()
    res, stake_res = Counter(), Counter()
    records, ev_cache = [], {}
    for market_id, question, stake, ts in rows:
        ours = our_contract(question)
        by_class[ours["klass"]] += 1
        stake_class[ours["klass"]] += stake or 0
        loose = (slug.get("map") or {}).get(market_id)
        ident = None
        nomatch_reason = None
        day = None
        if ts:
            day = ts / 1000.0 if ts > 1e12 else ts
        if ours["klass"] == "OTHER":
            v, k, gate, t, title, gap_d = "OTHER_CLASS", None, None, None, None, None
        else:
            sl = parse_slug(market_id)
            if sl and sl["families"]:
                picks, ident = pick_events_slug(sl, events, aliases), "slug"
            else:
                picks, ident = pick_events(ours, events, day), "text"
            if not picks:
                v, k, gate, t, title, gap_d = "NO_EVENT_MATCH", None, "G1", None, None, None
                nomatch_reason = ("no-slug" if not sl
                                  else "sport-unmapped" if not sl["families"]
                                  else "naming-unverified")
            elif len(picks) > 1:
                # Several events carry our subject on our day. That is only a problem
                # if it changes the ANSWER, so evaluate all of them: identical
                # equivalent contracts across every candidate resolve it, differing
                # ones stay AMBIGUOUS and no claim is made.
                hits, saw_class, first_t = [], False, picks[0][2][0]
                for gap, ctitle, tickers in picks:
                    for ct in tickers:
                        if ct not in ev_cache:
                            try:
                                ev_cache[ct] = event_markets(ct)
                            except Exception as e:
                                ev_cache[ct] = []
                                print(f"  ! {ct}: {e}", file=sys.stderr)
                        cands = [kalshi_contract(m["title"], m["yes_sub_title"]) for m in ev_cache[ct]]
                        if any(c["klass"] == ours["klass"] for c in cands):
                            saw_class = True
                        hit = next((c for c in cands if verdict(ours, c, sl, aliases) == "EQUIV"), None)
                        if hit:
                            hits.append((ct, hit))
                keys = {(h[1].get("klass"), h[1].get("line"), h[1].get("subject")) for h in hits}
                if hits and len(keys) == 1:
                    v, k, gate, t = "EQUIV", hits[0][1], None, hits[0][0]
                    title, gap_d = picks[0][1], round(picks[0][0] / 86400.0, 1)
                elif hits:
                    v, k, gate, t, title = "AMBIGUOUS_EVENT", None, "G1-ambiguous", first_t, picks[0][1]
                    gap_d = round(picks[0][0] / 86400.0, 1)
                elif saw_class:
                    v, k, gate, t, title = "DIFFERENT_CONTRACT", None, "G2/G3", first_t, picks[0][1]
                    gap_d = round(picks[0][0] / 86400.0, 1)
                else:
                    v, k, gate, t, title, gap_d = "NO_EVENT_MATCH", None, "G1", None, None, None
                    nomatch_reason = "naming-unverified"
            else:
                gap, title, tickers = picks[0]
                v, k, gate = "DIFFERENT_CONTRACT", None, "G2/G3"
                t, gap_d = tickers[0], round(gap / 86400.0, 1)
                saw_class = False
                for ct in tickers:
                    if ct not in ev_cache:
                        try:
                            ev_cache[ct] = event_markets(ct)
                        except Exception as e:
                            ev_cache[ct] = []
                            print(f"  ! {ct}: {e}", file=sys.stderr)
                    cands = [kalshi_contract(m["title"], m["yes_sub_title"]) for m in ev_cache[ct]]
                    if any(c["klass"] == ours["klass"] for c in cands):
                        saw_class = True
                    hit = next((c for c in cands if verdict(ours, c, sl, aliases) == "EQUIV"), None)
                    if hit:
                        v, k, gate, t = "EQUIV", hit, None, ct
                        break
                if v == "DIFFERENT_CONTRACT" and not saw_class:
                    v, t, title, gap_d = "NO_EVENT_MATCH", None, None, None
                    nomatch_reason = "naming-unverified"
        res[v] += 1
        stake_res[v] += stake or 0
        records.append({"marketId": market_id, "question": question, "stake": stake,
                        "ourClass": ours["klass"], "event": t, "eventTitle": title,
                        "dayGap": gap_d, "ident": ident, "looseMatcherEvent": loose and loose.get("ticker"),
                        "looseMatcherScore": loose and loose.get("score"),
                        "verdict": v, "gate": gate, "nomatchReason": nomatch_reason,
                        "kalshi": None if not k else (k.get("subject") or k.get("raw")),
                        "kalshiTitle": None if not k else k.get("raw_title")})

    ident_used = Counter(r["ident"] for r in records if r["ident"])
    print(f"\nidentity basis (level=market): " + ", ".join(f"{k}={v}" for k, v in ident_used.items()))

    print("\ncontract class of OUR book:")
    for c in ["MONEYLINE", "SPREAD", "TOTAL", "OTHER"]:
        if by_class[c]:
            print(f"  {c:10} {by_class[c]:>4} markets  ${stake_class[c]:>9,.2f}  "
                  f"({100.0*stake_class[c]/max(1e-9,stake_all):5.1f}% of stake)")
    print("\nresult (level=market, '$' = share of the whole 7d book):")
    for v in ["EQUIV", "DIFFERENT_CONTRACT", "AMBIGUOUS_EVENT", "EVENT_UNVERIFIED",
              "NO_EVENT_MATCH", "OTHER_CLASS"]:
        if res[v]:
            print(f"  {v:20} {res[v]:>4} markets  ${stake_res[v]:>9,.2f}  "
                  f"({100.0*stake_res[v]/max(1e-9,stake_all):5.1f}%)")

    equiv = [r for r in records if r["verdict"] == "EQUIV"]
    es = sorted((r["stake"] or 0 for r in equiv))
    if es:
        med = es[len(es)//2] if len(es) % 2 else (es[len(es)//2-1] + es[len(es)//2]) / 2
        print(f"\nEQUIVALENT pairs: {len(equiv)} markets, ${sum(es):,.2f} stake | median ${med:,.2f} | "
              f"top-1 {100.0*max(es)/max(1e-9,sum(es)):.1f}% of that stake | "
              f"trim5 mean ${sum(es[5:])/max(1,len(es[5:])):,.2f}")
    print("\nverified pairs by stake (eyeball every one):")
    for r in sorted(equiv, key=lambda r: -(r["stake"] or 0))[: args.top]:
        print(f"  ${r['stake']:>7.2f}  {r['ourClass']:9} {r['question'][:56]}")
        print(f"             -> {r['event']}  [{r['kalshiTitle']}]  dayGap {r['dayGap']}")

    nomatch = [r for r in records if r["verdict"] == "NO_EVENT_MATCH"]
    reasons = Counter(r["nomatchReason"] for r in nomatch)
    reason_stake = Counter()
    for r in nomatch:
        reason_stake[r["nomatchReason"]] += r["stake"] or 0
    print("  why they failed (population=the NO_EVENT_MATCH rows, level=market);"
          " naming-unverified is an INSTRUMENT LIMIT, not a measured absence:")
    for k in ["naming-unverified", "sport-unmapped", "no-slug"]:
        if reasons[k]:
            print(f"    {k:15} {reasons[k]:>3} markets  ${reason_stake[k]:>8,.2f}")
    print(f"\nG1 failures (no name-verified event for this market's sport and day): "
          f"{len(nomatch)} markets, ${sum(r['stake'] or 0 for r in nomatch):,.2f}")
    print("  the loose matcher's top hit for these (shown to prove it was a DIFFERENT event, not a missing one):")
    for r in sorted(nomatch, key=lambda r: -(r["stake"] or 0))[:6]:
        print(f"  ${r['stake']:>7.2f}  {r['question'][:46]} -> {r['looseMatcherEvent']} "
              f"score {r['looseMatcherScore']}")

    if SIDE_CHECK:
        print(f"spread side cross-check: " + ", ".join(f"{k}={v}" for k, v in sorted(SIDE_CHECK.items())))
    print(f"\nEQUIV share of the window's stake: "
          f"{100.0*stake_res['EQUIV']/max(1e-9,stake_all):.1f}% "
          f"(${stake_res['EQUIV']:,.2f} of ${stake_all:,.2f})")

    with open(args.out, "w") as f:
        json.dump({"generatedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                   "windowDays": args.days,
                   "asOf": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(as_of)),
                   "windowFrom": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(as_of - args.days * 86400)),
                   "aliasTable": {"loaded": bool(aliases),
                                  "codes": sum(len(v) for v in aliases.values()) if aliases else 0},
                   "pool": {"events": len(events), "openIndex": n_open,
                            "closedInWindow": len(events) - n_open},
                   "spreadSideCheck": dict(SIDE_CHECK),
                   "indexGeneratedAt": idx["generatedAt"],
                   "indexEvents": len(idx["events"]), "indexCursorExhausted": idx["cursorExhausted"],
                   "markets": len(rows), "stakeTotalUsd": round(stake_all, 2),
                   "byOurClass": dict(by_class),
                   "stakeByOurClass": {k: round(v, 2) for k, v in stake_class.items()},
                   "result": dict(res), "stakeByResult": {k: round(v, 2) for k, v in stake_res.items()},
                   "equivSharePct": round(100.0 * stake_res["EQUIV"] / max(1e-9, stake_all), 2),
                   "pairs": records}, f, indent=2)
    print(f"\nWrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
