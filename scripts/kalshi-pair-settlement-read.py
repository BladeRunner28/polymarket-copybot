#!/usr/bin/env python3
"""Kalshi cross-venue SETTLEMENT check — the card's own refutation clause.

WHY (2026-11-23): the alias table proves the CONTRACT matches; it does not prove the
SETTLEMENT matches. Two venues can list the same team, the same strike and the same
class and still settle differently on a postponement, an overtime, or a stat
correction. The card's pre-registered rule: on the first 20 contract-equivalent pairs
that settle, the venue's settlement must agree with ours on >=19. Two or more
disagreements PARKS the lane.

WHAT IT READS (all keyless):
  * pairs        data/kalshi-venue-shadow.jsonl rows with detVerdict == EQUIV
  * Kalshi truth GET /trade-api/v2/markets/<detTicker>       -> result (yes|no)
  * PM truth     GET clob.polymarket.com/markets/<conditionId> -> tokens[].winner
                 (conditionId joined from ObservedTrade / MarketSnapshot, read-only)

WHY IT DOES NOT USE THE LEDGER's `won`: that field is `realizedPnl > 0`, the EXIT sign.
A leg that exits early at break-even writes won=False whatever the market settled, and a
leg that exits at +$0.01 writes won=True whatever happened later. It is the right column
for a PnL book and the wrong column for a settlement audit, so the audit prices both
venues' OWN settlement and prints the ledger's exit-sign reading beside it.

The side question ("does our outcome name the Kalshi YES side?") is derived here from
OUR OUTCOME, never from the market's own spread tail: a spread question names the team
the line is written on, which is by construction the contract subject, so the old
`spread_index`-based rule answered YES for every spread pair including the ones where we
held the other team. That defect is pinned by a self-test arm below (the mutation arm
asserts the old rule returns YES on the fixture the new rule calls NO).

Usage:
  python3 scripts/kalshi-pair-settlement-read.py                 # read + report
  python3 scripts/kalshi-pair-settlement-read.py --gate 20       # gate size (default 20)
  python3 scripts/kalshi-pair-settlement-read.py --self-test
  python3 scripts/kalshi-pair-settlement-read.py --json out.json
"""
import argparse
import importlib.util
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
LEDGER = os.path.join(ROOT, "data", "kalshi-venue-shadow.jsonl")
KCE_PATH = os.path.join(ROOT, "scripts", "kalshi-contract-equivalence.py")
ALIASES = os.path.join(ROOT, "data", "kalshi-team-aliases.json")
DB = os.path.join(ROOT, "prisma", "dev.db")
OUT = os.path.join(ROOT, "data", "kalshi-pair-settlement.json")
CACHE = os.path.join(ROOT, "data", "cache", "kalshi-pair-settlement")
KALSHI_BASE = "https://api.elections.kalshi.com/trade-api/v2"
PM_BASE = "https://clob.polymarket.com"
UA = {"User-Agent": "medusa-copybot/1.0", "Accept": "application/json"}


def load_kce():
    spec = importlib.util.spec_from_file_location("kce", KCE_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


KCE = load_kce()


def get(url, tries=4):
    last = None
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=40) as r:
                return json.load(r)
        except Exception as e:  # 429/5xx/network — a failed fetch is never a verdict
            last = e
            time.sleep(0.6 * (i + 1))
    raise last


def retired_side_yes(ours, theirs, outcome, sl, aliases):
    """The rule that shipped until 2026-11-23, kept ONLY as a mutation control.

    It read the spread side off the QUESTION's id tail (`spread_index`), which is the
    contract's own subject on every verified pair, so it answered YES for every spread
    trade -- including the ones where we held the other team. The self-test asserts this
    function returns YES on the fixture where the live rule returns NO; if a future edit
    reinstates that shape, the arm goes RED.
    """
    o = (outcome or "").strip().lower()
    if ours.get("klass") == "TOTAL":
        if o.startswith("over") or o in ("yes", "up"):
            return True
        if o.startswith("under") or o in ("no", "down"):
            return False
        return None
    if not o or o in ("yes", "no", "up", "down"):
        return None
    if KCE.subject_match(outcome, theirs.get("subject") or "")[0]:
        return True
    if sl:
        idx = KCE.spread_index(sl) if ours.get("klass") == "SPREAD" else next(
            (k for k, t in enumerate(ours.get("teams") or [])
             if t and KCE.subject_match(outcome, t)[0]), None)
        subj = KCE.team_index(theirs.get("subject"), sl, aliases)
        if idx is not None and subj is not None:
            return idx == subj
    return False


def _norm(s):
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def token_index(tokens, label):
    """Which venue token carries `label`? Exact first, then the team bridge."""
    labels = [_norm(t.get("outcome")) for t in tokens or []]
    want = _norm(label)
    if want and want in labels:
        return labels.index(want)
    hits = [i for i, l in enumerate(labels) if KCE.subject_match(label, l)[0]]
    return hits[0] if len(hits) == 1 else None


def our_side_yes(ours, theirs, outcome, sl, aliases, tokens=None):
    """Is OUR held outcome the YES side of the matched Kalshi contract?

    True / False / None (None = cannot tell; the caller then reports UNDETERMINED and
    never counts the pair as agreement).

    Three vocabularies meet here: our slug carries CODES ("nyk"), the Kalshi contract
    carries CITIES ("New York"), and our outcome carries the venue's own LABEL
    ("KNICKS"). So the index is always taken from the side we can actually read:

      MONEYLINE  our outcome's position among the QUESTION's two named teams (the same
                 order as the slug, verified by the pair's own EQUIV verdict) vs the
                 contract subject's slug position through the city alias table.
      SPREAD     the question names ONE team and that team IS the contract subject (the
                 verdict's own cross-check), so the outcome is compared against it
                 directly, with the venue token list as the tie-break. The spread id
                 tail is NEVER used: it is the market's own side, so it equals the
                 subject on every verified pair and called every spread trade YES --
                 including the ones holding the opponent (pinned by a self-test arm).
    """
    o = _norm(outcome)
    if ours.get("klass") == "TOTAL":
        if o.startswith("over") or o in ("yes", "up"):
            return True
        if o.startswith("under") or o in ("no", "down"):
            return False
        return None
    subject = theirs.get("subject")
    if not subject:
        return None

    if ours.get("klass") == "MONEYLINE" and ours.get("teams"):
        oi = next((k for k, t in enumerate(ours["teams"])
                   if t and KCE.subject_match(outcome, t)[0]), None)
        ti = KCE.team_index(subject, sl, aliases) if sl else None
        if oi is not None and ti is not None:
            return oi == ti
        if KCE.subject_match(outcome, subject)[0]:
            return True
        return None

    q_subject = ours.get("subject") or subject
    if KCE.subject_match(outcome, q_subject)[0]:
        return True
    if tokens:
        mine = token_index(tokens, outcome)
        subj = token_index(tokens, q_subject)
        if mine is not None and subj is not None:
            return mine == subj
        if mine is not None and subj is None:
            oi = KCE.team_index(outcome, sl, aliases) if sl else None
            ti = KCE.team_index(subject, sl, aliases) if sl else None
            if oi is not None and ti is not None:
                return oi == ti
            return None
    oi = KCE.team_index(outcome, sl, aliases) if sl else None
    ti = KCE.team_index(subject, sl, aliases) if sl else None
    if oi is not None and ti is not None:
        return oi == ti
    return None


def pm_token_winner(tokens, outcome):
    """The venue's OWN winner flag for the token our outcome names. None = not found."""
    want = (outcome or "").strip().lower().replace("'", "")
    for t in tokens:
        got = (t.get("outcome") or "").strip().lower().replace("'", "")
        if got == want and t.get("winner") is not None:
            return bool(t["winner"])
    # second pass: team-name bridge for rows whose PM label carries a city the venue drops
    for t in tokens:
        if t.get("winner") is None:
            continue
        if KCE.subject_match(outcome, t.get("outcome") or "")[0]:
            return bool(t["winner"])
    return None


def classify(pm_win, kalshi_result, side_yes):
    """One pair -> AGREE / DISAGREE / VOID / UNDETERMINED. Pure, and pinned by self-test."""
    if kalshi_result not in ("yes", "no"):
        return "VOID"
    if pm_win is None or side_yes is None:
        return "UNDETERMINED"
    kalshi_side_won = (kalshi_result == "yes") if side_yes else (kalshi_result == "no")
    return "AGREE" if kalshi_side_won == pm_win else "DISAGREE"


def gate_verdict(verdicts, gate):
    """The card's pre-registered rule, as code: >=19 of the first 20 settled pairs agree.

    Only AGREE/DISAGREE count toward the denominator; VOID and UNDETERMINED are reported
    beside the verdict and never quietly improve it.
    """
    scored = [v for v in verdicts[:gate] if v in ("AGREE", "DISAGREE")]
    dis = sum(1 for v in scored if v == "DISAGREE")
    if len(scored) < gate:
        return {"verdict": "INSUFFICIENT_N", "scored": len(scored), "disagree": dis}
    return {"verdict": "PASS" if dis <= 1 else "PARK", "scored": len(scored), "disagree": dis}


def load_pairs(path=LEDGER):
    rows = [json.loads(l) for l in open(path) if l.strip()]
    eq = [r for r in rows if r.get("detVerdict") == "EQUIV" and r.get("detTicker")]
    seen, out = set(), []
    for r in sorted(eq, key=lambda x: x.get("openedMs") or 0):
        key = (r.get("marketId"), r.get("outcome"), r.get("detTicker"))
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
    return out


def cond_id(con, market_id):
    for q in ("SELECT conditionId FROM ObservedTrade WHERE marketId=? AND conditionId IS NOT NULL LIMIT 1",
              "SELECT conditionId FROM MarketSnapshot WHERE marketId=? AND conditionId IS NOT NULL LIMIT 1"):
        r = con.execute(q, (market_id,)).fetchone()
        if r and r[0]:
            return r[0]
    return None


def cached(kind, key, fn):
    os.makedirs(CACHE, exist_ok=True)
    p = os.path.join(CACHE, f"{kind}-{re.sub(r'[^A-Za-z0-9_.-]', '_', key)}.json")
    if os.path.exists(p) and time.time() - os.path.getmtime(p) < 7 * 86400:
        try:
            return json.load(open(p))
        except ValueError:
            pass
    v = fn()
    if v is not None:
        with open(p, "w") as f:
            json.dump(v, f)
    return v


def kalshi_read(ticker):
    d = get(f"{KALSHI_BASE}/markets/{urllib.parse.quote(ticker)}")
    m = d.get("market") or {}
    return {"ticker": m.get("ticker"), "status": m.get("status"), "result": m.get("result"),
            "expirationValue": m.get("expiration_value"),
            "rulesPrimary": m.get("rules_primary") or "",
            "openTime": m.get("open_time"), "closeTime": m.get("close_time")}


def pm_read(cond):
    d = get(f"{PM_BASE}/markets/{urllib.parse.quote(cond)}")
    return {"question": d.get("question"), "closed": d.get("closed"),
            "tokens": [{"outcome": t.get("outcome"), "winner": t.get("winner")}
                       for t in (d.get("tokens") or [])]}


def run(gate=20):
    aliases = {}
    try:
        with open(ALIASES) as f:
            aliases = {k: v for k, v in json.load(f).items() if not k.startswith("_")}
    except (OSError, ValueError) as e:
        print(f"  ! alias table unreadable ({e}) — side attribution runs on the heuristic only",
              file=sys.stderr)
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    pairs = load_pairs()
    print(f"pairs: {len(pairs)} contract-equivalent legs "
          f"(level = one ledger leg: marketId|outcome|detTicker; clock = openedAt)\n")
    recs = []
    for r in pairs:
        mid, outcome, tick = r["marketId"], r.get("outcome") or "", r["detTicker"]
        ours = KCE.our_contract(r.get("question") or "")
        theirs = KCE.kalshi_contract(r.get("detTitle") or "", r.get("detTitle") or "")
        sl = KCE.parse_slug(mid)
        cid = cond_id(con, mid)
        rec = {"marketId": mid, "outcome": outcome, "class": ours.get("klass"),
               "kalshiTicker": tick, "detTitle": r.get("detTitle"),
               "openedAt": r.get("openedAt"), "openedMs": r.get("openedMs"),
               "conditionId": cid,
               "storedSideYes": r.get("detOurSideIsYes"),
               "ledgerWon": r.get("won")}
        try:
            k = cached("kalshi", tick, lambda: kalshi_read(tick))
        except Exception as e:
            k = None
            rec["kalshiError"] = str(e)
        try:
            p = cached("pm", cid, lambda: pm_read(cid)) if cid else None
        except Exception as e:
            p = None
            rec["pmError"] = str(e)
        side = our_side_yes(ours, theirs, outcome, sl, aliases, (p or {}).get("tokens"))
        rec["sideYes"] = side
        pm_win = pm_token_winner(p["tokens"], outcome) if p else None
        rec["pmWinner"] = pm_win
        rec["kalshiResult"] = (k or {}).get("result")
        rec["kalshiStatus"] = (k or {}).get("status")
        rec["pmClosed"] = (p or {}).get("closed")
        rec["rulesStored"] = (r.get("detRules") or "")[:400]
        rec["rulesLive"] = ((k or {}).get("rulesPrimary") or "")[:400]
        rec["rulesChanged"] = bool(rec["rulesStored"] and rec["rulesLive"]
                                   and rec["rulesStored"].strip() != rec["rulesLive"].strip())
        rec["verdict"] = classify(pm_win, rec["kalshiResult"], side)
        recs.append(rec)

    verds = [x["verdict"] for x in recs]
    counts = Counter(verds)
    g = gate_verdict(verds, gate)
    side_defect = [x for x in recs if x["storedSideYes"] is not None and x["sideYes"] is not None
                   and x["storedSideYes"] != x["sideYes"]]
    won_defect = [x for x in recs if x["pmWinner"] is not None and x["verdict"] == "AGREE"
                  and x["ledgerWon"] is not None and bool(x["ledgerWon"]) != bool(x["pmWinner"])]
    relabel = [x for x in recs if x["ledgerWon"] is not None and x["pmWinner"] is not None
               and bool(x["ledgerWon"]) != bool(x["pmWinner"])]
    rules_changed = [x for x in recs if x["rulesChanged"]]

    print(f"{'market':<52} {'class':<9} {'ours':<20} {'side':<4} {'K':<3} {'PM':<4} verdict")
    for x in recs:
        print(f"{x['marketId'][:52]:<52} {str(x['class'])[:8]:<9} {x['outcome'][:20]:<20} "
              f"{str(x['sideYes']):<4} {str(x['kalshiResult'])[:3]:<3} {str(x['pmWinner']):<4} "
              f"{x['verdict']}{'  RULES-CHANGED' if x['rulesChanged'] else ''}")
    print(f"\ncounts: {dict(counts)}")
    print(f"GATE ({gate}): {g['verdict']} — {g['scored']} scored, {g['disagree']} disagreed")
    print(f"side-flag defect (stored detOurSideIsYes != our outcome's side): "
          f"{len(side_defect)} of {sum(1 for x in recs if x['sideYes'] is not None)} determinable")
    print(f"ledger `won` (EXIT sign) vs PM settlement, relabelled: {len(relabel)} of "
          f"{sum(1 for x in recs if x['pmWinner'] is not None)}")
    print(f"rules_primary changed between our stamp and now: {len(rules_changed)}")
    for x in recs:
        if x["verdict"] == "DISAGREE":
            print(f"  DISAGREE {x['marketId']} {x['outcome']} | K={x['kalshiResult']} "
                  f"PM={x['pmWinner']} sideYes={x['sideYes']}")

    body = {"generatedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "population": {"level": "ledger leg (marketId|outcome|detTicker)",
                           "clock": "openedAt", "pairs": len(recs),
                           "distinctTickers": len({x["kalshiTicker"] for x in recs})},
            "gate": {"size": gate, **g},
            "counts": dict(counts),
            "sideFlagDefect": len(side_defect),
            "ledgerExitSignRelabels": len(relabel),
            "rulesChanged": [x["marketId"] for x in rules_changed],
            "pairs": recs}
    with open(OUT, "w") as f:
        json.dump(body, f, indent=1)
    print(f"\nWrote {OUT}")
    return 0 if g["verdict"] in ("PASS", "INSUFFICIENT_N", "PARK") else 1


def self_test():
    arms = 0
    ok = 0

    def arm(name, cond):
        nonlocal arms, ok
        arms += 1
        if cond:
            ok += 1
        else:
            print(f"  FAIL {name}")

    aliases = {"nba": {"gsw": ["Golden State Warriors", "Warriors", "Golden State"],
                       "bos": ["Boston Celtics", "Celtics"],
                       "nyk": ["New York Knicks", "Knicks"],
                       "por": ["Portland Trail Blazers", "Trail Blazers"],
                       "bkn": ["Brooklyn"], "phi": ["Philadelphia"]},
               "cbb": {"hou": ["Houston Cougars", "Houston"], "kan": ["Kansas Jayhawks", "Kansas"]}}
    spread_ours = KCE.our_contract("Spread: Kansas Jayhawks (-1.5)")
    spread_k = KCE.kalshi_contract("Kansas wins by over 1.5 points")
    sl_cbb = KCE.parse_slug("cbb-hou-kan-2026-11-19-spread-home-1pt5")

    # --- the defect this file was written against: our outcome is the OTHER team
    arm("SPREAD, our outcome is the non-subject team -> NO side",
        our_side_yes(spread_ours, spread_k, "HOUSTON COUGARS", sl_cbb, aliases) is False)
    arm("MUTATION: the RETIRED rule answers YES on that same fixture (arm is RED under it)",
        retired_side_yes(spread_ours, spread_k, "HOUSTON COUGARS", sl_cbb, aliases) is True)
    arm("SPREAD, our outcome IS the subject team -> YES side",
        our_side_yes(spread_ours, spread_k, "KANSAS JAYHAWKS", sl_cbb, aliases) is True)

    # --- moneyline: subject through the alias bridge, both directions
    ml = KCE.our_contract("Celtics vs. Warriors")
    ml_k = KCE.kalshi_contract("Golden State wins")
    sl_nba = KCE.parse_slug("nba-bos-gsw-2026-11-22")
    arm("MONEYLINE, holders of the subject win YES",
        our_side_yes(ml, ml_k, "WARRIORS", sl_nba, aliases) is True)
    arm("MONEYLINE, holders of the opponent are NO",
        our_side_yes(ml, ml_k, "CELTICS", sl_nba, aliases) is False)
    # the vocabulary that broke the first draft: our label is the NICKNAME, the alias table
    # carries the CITY, the slug carries the CODE
    ml_bkn = KCE.our_contract("76ers vs. Nets")
    ml_bkn_k = KCE.kalshi_contract("Brooklyn wins")
    sl_bkn = KCE.parse_slug("nba-phi-bkn-2026-11-16")
    arm("MONEYLINE: nickname 'NETS' resolves to the CITY/CODE subject (Brooklyn/bkn)",
        our_side_yes(ml_bkn, ml_bkn_k, "NETS", sl_bkn, aliases) is True)
    # spread side with the venue token list as tie-break
    toks_sp = [{"outcome": "Knicks", "winner": False}, {"outcome": "Trail Blazers", "winner": True}]
    sp_ours = KCE.our_contract("Spread: Knicks (-7.5)")
    sp_k = KCE.kalshi_contract("New York wins by over 7.5 points")
    sl_por = KCE.parse_slug("nba-por-nyk-2026-11-21-spread-home-7pt5")
    arm("SPREAD: holder of the question's subject is YES",
        our_side_yes(sp_ours, sp_k, "KNICKS", sl_por, aliases, toks_sp) is True)
    arm("SPREAD: holder of the opponent is NO, via the token tie-break",
        our_side_yes(sp_ours, sp_k, "TRAIL BLAZERS", sl_por, aliases, toks_sp) is False)

    # --- totals
    tot = KCE.our_contract("Brentford FC vs. Everton FC: O/U 3.5")
    tot_k = KCE.kalshi_contract("Over 3.5 goals scored")
    arm("TOTAL over is YES", our_side_yes(tot, tot_k, "OVER", None, aliases) is True)
    arm("TOTAL under is NO", our_side_yes(tot, tot_k, "UNDER", None, aliases) is False)
    arm("TOTAL with an unreadable outcome is UNKNOWN, never guessed",
        our_side_yes(tot, tot_k, "DRAW", None, aliases) is None)

    # --- the classifier, both directions and both sides
    arm("AGREE: YES side, venue yes, PM won", classify(True, "yes", True) == "AGREE")
    arm("DISAGREE: YES side, venue yes, PM lost", classify(False, "yes", True) == "DISAGREE")
    arm("AGREE: NO side, venue no, PM won", classify(True, "no", False) == "AGREE")
    arm("DISAGREE: NO side, venue no, PM lost", classify(False, "no", False) == "DISAGREE")
    arm("VOID venue settlement is its own bucket", classify(True, None, True) == "VOID")
    arm("an unknown side is UNDETERMINED, not a disagreement",
        classify(True, "yes", None) == "UNDETERMINED")
    arm("a missing PM token is UNDETERMINED",
        classify(None, "yes", True) == "UNDETERMINED")

    # --- PM token match
    toks = [{"outcome": "Kansas Jayhawks", "winner": False},
            {"outcome": "Houston Cougars", "winner": True}]
    arm("PM token match is case-insensitive on the venue's own label",
        pm_token_winner(toks, "HOUSTON COUGARS") is True)
    arm("PM token match refuses an absent outcome",
        pm_token_winner(toks, "DRAKE BULLDOGS") is None)
    arm("a PM token with no winner flag yet is not a settlement",
        pm_token_winner([{"outcome": "Over", "winner": None}], "OVER") is None)

    # --- the gate, at its own boundary
    arm("gate PASS at 19/20", gate_verdict(["AGREE"] * 19 + ["DISAGREE"], 20)["verdict"] == "PASS")
    arm("gate PARK at 18/20", gate_verdict(["AGREE"] * 18 + ["DISAGREE"] * 2, 20)["verdict"] == "PARK")
    arm("gate refuses to score a short population",
        gate_verdict(["AGREE"] * 12, 20)["verdict"] == "INSUFFICIENT_N")
    arm("VOID rows do not fill the denominator",
        gate_verdict(["AGREE"] * 19 + ["VOID"] * 5, 20)["verdict"] == "INSUFFICIENT_N")

    print(f"\nself-test {ok}/{arms}")
    return 0 if ok == arms else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--gate", type=int, default=20)
    ap.add_argument("--json", default=None, help="artifact path (default data/kalshi-pair-settlement.json)")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args()
    if a.self_test:
        return self_test()
    global OUT
    if a.json:
        OUT = a.json
    return run(a.gate)


if __name__ == "__main__":
    sys.exit(main())
