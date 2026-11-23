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

Usage:
  python3 scripts/kalshi-team-aliases.py --derive     # refresh the table from the venue
  python3 scripts/kalshi-team-aliases.py --check      # collisions + coverage, exit 1 on fail
"""
import argparse
import collections
import json
import os
import re
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


def walk(series, status, pages=8, settle_days=90):
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
    bad = 0
    for sport in SERIES:
        forms = t.get(sport) or {}
        seen = collections.defaultdict(list)
        for pm_code, names in forms.items():
            for n in names:
                seen[re.sub(r"[^a-z0-9 ]", "", n.lower())].append(pm_code)
        for name, pm_codes in sorted(seen.items()):
            venue_codes = {CODE_MAP[sport][c] for c in pm_codes}
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
        if not forms:
            print(f"  EMPTY {sport}: no aliases")
            bad += 1
        print(f"  {sport:4} {len(forms):>3} codes, "
              f"{sum(len(v) for v in forms.values()):>3} forms, "
              f"{len(seen):>3} distinct names")
    print(f"\nalias check: {'FAIL' if bad else 'PASS'} ({bad} collision(s))")
    return 1 if bad else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--derive", action="store_true")
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    if a.derive:
        return derive()
    if a.check:
        return check()
    print(__doc__)
    return 0


if __name__ == "__main__":
    sys.exit(main())
