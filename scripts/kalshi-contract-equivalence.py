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
MCACHE = os.path.join(ROOT, "data", "cache", "kalshi-event-markets")
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


def subject_match(ours, theirs):
    """Same team/player? Two guards, each bought with a measured false positive:

    (1) the State/St. qualifier must agree on BOTH sides, else "Georgia" matches
        "Georgia St." and "Kansas" matches "Kansas St.";
    (2) the shared tokens must cover >=60% of the CANDIDATE's distinctive tokens,
        else "Georgia" matches "Georgia Southern", "New Mexico" matches "New York"
        and "South Carolina State Bulldogs" matches "Western Carolina".

    Both of those passed a >=1-token rule that this replaces.
    """
    if state_marker(ours) != state_marker(theirs):
        return False, []
    o, t = tokens(ours), tokens(theirs)
    shared = {x for x in (o & t) if len(x) >= 3}
    if not shared or not t:
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


def pick_events(ours, events, day, window_days=10.0):
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
        key = re.sub(r"\s+", " ", title.split(":")[0].lower()).strip()
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


def pick_events_slug(sl, events, window_days=1.0):
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
        a = [i for i, sd in enumerate(sides) if code_match(sl["teams"][0], sd)]
        b = [i for i, sd in enumerate(sides) if code_match(sl["teams"][1], sd)]
        if not any(i != j for i in a for j in b):
            continue
        key = re.sub(r"\s+", " ", title.split(":")[0].lower()).strip()
        prev = out.get(key)
        if prev is None:
            out[key] = (abs(ed - sl["day"]), title, [ticker])
        else:
            out[key] = (min(prev[0], abs(ed - sl["day"])), prev[1],
                        prev[2] + ([ticker] if ticker not in prev[2] else []))
    return sorted(out.values(), key=lambda x: x[0])


def verdict(ours, theirs):
    if not theirs:
        return "NO_CONTRACT"
    if ours["klass"] != theirs["klass"]:
        return "DIFFERENT_CONTRACT"
    if ours["klass"] == "TOTAL":
        return "EQUIV" if abs(ours["line"] - theirs["line"]) < 1e-9 else "DIFFERENT_CONTRACT"
    if ours["klass"] == "SPREAD":
        if abs(ours["line"] - theirs["line"]) >= 1e-9:
            return "DIFFERENT_CONTRACT"
        return "EQUIV" if subject_match(ours["subject"], theirs["subject"])[0] else "DIFFERENT_CONTRACT"
    if ours["klass"] == "MONEYLINE":
        hit = [t for t in ours["teams"] if subject_match(t, theirs["subject"])[0]]
        return "EQUIV" if hit else "DIFFERENT_CONTRACT"
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


ARMS = 26


def self_test():
    ok = 0
    def arm(name, cond):
        nonlocal ok
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
    print(f"\nself-test {ok}/{ARMS}")
    return 0 if ok == ARMS else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--top", type=int, default=14)
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()

    with open(MAP) as f:
        slug = json.load(f)
    with open(INDEX) as f:
        idx = json.load(f)
    print(f"event index: {len(idx['events'])} open events, cursor exhausted={idx['cursorExhausted']}, "
          f"built {idx['generatedAt']}; slug map built {slug['generatedAt']} at minScore {slug['minScore']}")
    try:
        src = open(os.path.join(ROOT, "rust-sidecar", "src", "adapters.rs")).read()
        pages = int(re.search(r"MAX_EVENT_PAGES:\s*usize\s*=\s*(\d+)", src).group(1))
        thr = re.search(r"MATCH_THRESHOLD:\s*f64\s*=\s*([\d.]+)", src).group(1)
        print(f"sidecar depth (read from adapters.rs): {pages} pages x 200 = {pages*200} events at "
              f"threshold {thr} = {100.0*pages*200/len(idx['events']):.1f}% of the open-event inventory")
    except (OSError, AttributeError, ValueError):
        print("sidecar source not readable — depth not stated")

    since_ms = int((time.time() - args.days * 86400) * 1000)
    con = sqlite3.connect(DB)
    rows = con.execute(
        """SELECT t.marketId, o.marketQuestion, ROUND(SUM(t.simulatedPositionSize),2),
                  MAX(o.timestamp) AS ts
           FROM PaperTrade t
           JOIN DecisionJournal d ON d.id = t.decisionJournalId
           JOIN ObservedTrade o ON o.id = d.observedTradeId
           WHERE t.botId='BANKROLL_200' AND t.isDemo=0 AND t.openedAt >= ?
           GROUP BY t.marketId ORDER BY 3 DESC""",
        (since_ms,),
    ).fetchall()
    con.close()
    stake_all = sum(r[2] or 0 for r in rows)
    print(f"\nour C-200 markets, {args.days}d to {time.strftime('%Y-%m-%dT%H:%MZ', time.gmtime())}: "
          f"{len(rows)} markets, ${stake_all:,.2f} stake (level=market, stake=summed simulatedPositionSize)")

    events = [(e.get("ticker", ""), e.get("title") or "", ticker_day(e.get("ticker", "")))
              for e in idx["events"] if e.get("title")]
    print(f"event pool for G1 (level=event, full index): {len(events)} titled open events")

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
                picks, ident = pick_events_slug(sl, events), "slug"
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
                        hit = next((c for c in cands if verdict(ours, c) == "EQUIV"), None)
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
                    hit = next((c for c in cands if verdict(ours, c) == "EQUIV"), None)
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

    with open(OUT, "w") as f:
        json.dump({"generatedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                   "windowDays": args.days, "indexGeneratedAt": idx["generatedAt"],
                   "indexEvents": len(idx["events"]), "indexCursorExhausted": idx["cursorExhausted"],
                   "markets": len(rows), "stakeTotalUsd": round(stake_all, 2),
                   "byOurClass": dict(by_class),
                   "stakeByOurClass": {k: round(v, 2) for k, v in stake_class.items()},
                   "result": dict(res), "stakeByResult": {k: round(v, 2) for k, v in stake_res.items()},
                   "pairs": records}, f, indent=2)
    print(f"\nWrote {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
