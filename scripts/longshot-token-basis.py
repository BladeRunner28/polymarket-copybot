#!/usr/bin/env python3
"""longshot-token-basis.py -- re-mark the long-shot shadow ladder on the token basis
and on a one-bet-per-market basis, then ask whether its promote gate can be met.

Roadmap card: profit-longshot-token-basis (Backlog, MEASUREMENT, 2026-11-19).
The card's premise: the ladder is marked by `didOutcomeWin(outcome, {winningLabel})`
(src/lib/resolution.ts:73), a pure LABEL compare, and the 2026-11-19 review measured
that basis inflating hit rate by 25pp on NAMED rows before 2026-11-09 -- so the
ladder's record "is only as clean as its named share".  NOT MEASURED YET (card's own
words): the named share and the token-basis win rate.  This file measures both.

LEVEL / CLOCK / POPULATION
  level      = ONE TICKET (a would-admit candidate joined to its resolve record),
               and, separately, ONE BET (marketId|outcome, earliest ticket).
  clock      = the resolve row's ts (when the market settled).
  population = data/longshot-shadow.jsonl: every candidate the relaxed ladder
               (drift<=0.01, spread<=0.08, conf>=0.50, 0.05<=price<0.20) would admit.
  basis      = for each ticket, the venue's OWN token table (CLOB
               /markets/<conditionId> -> tokens[].outcome/winner), not a label.

SO THAT THE LABEL BASIS CANNOT BE "PROVEN CLEAN BY CONSTRUCTION", the token identity
is checked against the venue's PRINT TAPE (CLOB /prices-history per token, +/-15 min
around the decision): the ticket is priced at entryPrice, so the token whose prints
sit within 3c of entryPrice at decision time is the token the ticket actually bought.
Classification per ticket:
  label_token   = the tape agrees the ticket was priced on the token its LABEL names
  sibling_token = the tape says the ticket was priced on the OTHER token (a frame
                  defect: the label basis would then be scoring the wrong side)
  ambiguous     = neither token's prints are near entryPrice (left undetermined)

SECTIONS
  0 the ladder as filed, and what "135 resolved" is counting
  1 identity: label -> token, and the tape's independent vote
  2 the basis comparison: label vs token, per label class and per era
  3 concentration: the headline is a handful of long-shot payoffs
  4 the ladder's own decision rule, evaluated
  5 what the ticket basis overstates relative to the bet basis

Run:
  python3 scripts/longshot-token-basis.py            # cached truth, no network
  python3 scripts/longshot-token-basis.py --fetch    # refresh CLOB truth + tape
  python3 scripts/longshot-token-basis.py --self-test
"""
import json
import os
import random
import sqlite3
import statistics
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

LEDGER = os.path.join("data", "longshot-shadow.jsonl")
SUMMARY = os.path.join("data", "longshot-shadow-summary.json")
DB = "prisma/dev.db"
TRUTH = os.path.join("data", "longshot-token-truth.json")
ARTIFACT = os.path.join("data", "longshot-token-basis.json")
CLOB = "https://clob.polymarket.com"
UA = "medusa-copybot/1.0 (paper-trading-only)"
STAKE = 20.0
PRICE_SIDE_FIX_ISO = "2026-11-09"       # the fbf9073 write fix; the frame-defect era boundary
IDENT_TOL = 0.03                        # entryPrice tolerance for the tape's identity vote
SEED = 20261119


# ----------------------------------------------------------------------------- helpers
def norm(s):
    return "".join(ch for ch in str(s).upper() if ch.isalnum())


def iso_to_epoch(ts):
    return datetime.fromisoformat(str(ts).replace("Z", "+00:00")).timestamp()


def pnl_of(entry, won, stake=STAKE):
    """A ticket bought at `entry` paying 1 on a win, 0 on a loss (counterfactualPnl)."""
    if not (entry and entry > 0):
        return 0.0
    return ((1.0 if won else 0.0) - entry) / entry * stake


def dedupe_by_key(legs, key):
    """Earliest ticket per key -- the ledger's own one-ticket-per-opportunity rule."""
    out = {}
    for leg in legs:
        k = key(leg)
        if k not in out or leg["decided_at"] < out[k]["decided_at"]:
            out[k] = leg
    return list(out.values())


def concentration(legs):
    """Ex-top-k PnL and the median leg. A headline that dies ex-top-10 is one bet."""
    pnls = sorted((pnl_of(l["entry"], l["won"]) for l in legs), reverse=True)
    return {
        "n": len(pnls),
        "sum": round(sum(pnls), 2),
        "ex_top_1": round(sum(pnls[1:]), 2) if len(pnls) > 1 else None,
        "ex_top_5": round(sum(pnls[5:]), 2) if len(pnls) > 5 else None,
        "ex_top_10": round(sum(pnls[10:]), 2) if len(pnls) > 10 else None,
        "median": round(statistics.median(pnls), 2) if pnls else None,
        "max": round(pnls[0], 2) if pnls else None,
    }


def block(legs):
    """Hit rate, breakeven hit rate (= mean entry price), and excess in pp."""
    if not legs:
        return {"n": 0, "wins": 0, "hit": None, "breakeven": None, "excess_pp": None,
                "pnl": None, "roi": None}
    wins = sum(1 for l in legs if l["won"])
    hit = wins / len(legs)
    be = statistics.mean(l["entry"] for l in legs)
    pnl = sum(pnl_of(l["entry"], l["won"]) for l in legs)
    return {
        "n": len(legs),
        "wins": wins,
        "hit": round(100 * hit, 2),
        "breakeven": round(100 * be, 2),
        "excess_pp": round(100 * (hit - be), 2),
        "pnl": round(pnl, 2),
        "roi": round(100 * pnl / (STAKE * len(legs)), 2),
    }


def cluster_ci(legs, reps=2000, seed=SEED):
    """Market-clustered bootstrap of ROI per ticket: resample MARKETS, not tickets."""
    clusters = {}
    for l in legs:
        clusters.setdefault(l["marketId"], []).append(pnl_of(l["entry"], l["won"]))
    keys = list(clusters)
    if not keys:
        return None, None
    rnd = random.Random(seed)
    out = []
    for _ in range(reps):
        pick = [rnd.choice(keys) for _ in keys]
        tot = sum(v for k in pick for v in clusters[k])
        n = sum(len(clusters[k]) for k in pick)
        out.append(100 * tot / (STAKE * n))
    out.sort()
    return round(out[int(0.025 * reps)], 1), round(out[int(0.975 * reps) - 1], 1)


def label_class(outcome):
    return "YES/NO" if str(outcome).upper() in ("YES", "NO") else "named"


def token_for_label(tokens, outcome):
    """The (idx, label, winner) entry whose label matches `outcome`, or None."""
    want = norm(outcome)
    hit = [(i, t[0], bool(t[1])) for i, t in enumerate(tokens) if norm(t[0]) == want]
    return hit[0] if len(hit) == 1 else None


def classify_identity(label_best, sibling_best, tol=IDENT_TOL):
    """Which token the ticket was PRICED on, from the tape's distance to entryPrice."""
    near_label = label_best is not None and label_best <= tol
    near_sib = sibling_best is not None and sibling_best <= tol
    if near_label and not near_sib:
        return "label_token"
    if near_sib and not near_label:
        return "sibling_token"
    if near_label and near_sib:
        return "label_token" if label_best <= sibling_best else "sibling_token"
    return "ambiguous"


def identity_vote(tokens, idx, best_by_token_id, tol=IDENT_TOL):
    """(vote, label_best, sibling_best) for the token at `tokens[idx]`.

    `tokens` is [[label, winner, token_id], ...]; `idx` is the index the row's LABEL
    resolved to. Keeping this pure is the point: the earlier draft compared
    token_for_label()'s WINNER boolean against token ids, which made every ticket
    either ambiguous or a sibling -- a vote that could not be right.
    """
    label_tid = tokens[idx][2]
    sib_tid = tokens[1 - idx][2] if len(tokens) == 2 else None
    lab = best_by_token_id.get(label_tid)
    sib = best_by_token_id.get(sib_tid) if sib_tid is not None else None
    return classify_identity(lab, sib, tol), lab, sib


def evaluate_rule(bets_token_basis):
    """The card's own promote gate, applied verbatim to a bet-basis population."""
    n = len(bets_token_basis)
    b = block(bets_token_basis)
    excess = b["excess_pp"]
    return {
        "n_resolved_bets": n,
        "n_required": 150,
        "excess_pp": excess,
        "excess_required_pp": 5.0,
        "n_met": n >= 150,
        "excess_met": excess is not None and excess >= 5.0,
        "promotable": bool(n >= 150 and excess is not None and excess >= 5.0),
    }


# ------------------------------------------------------------------------------- reads
def read_ledger(path=LEDGER):
    rows = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def build_population(rows):
    """Join would-admit candidates to their resolve rows -> tickets with won/filed value."""
    resolves = {}
    for r in rows:
        if r.get("type") == "resolve":
            resolves[(r["marketId"], str(r["outcome"]))] = r
    legs = []
    for r in rows:
        if r.get("type") != "candidate" or r.get("wouldAdmit") is not True:
            continue
        key = (r["marketId"], str(r["outcome"]))
        res = resolves.get(key)
        if not res:
            continue
        legs.append({
            "marketId": r["marketId"],
            "outcome": str(r["outcome"]),
            "entry": float(r["entryPrice"]),
            "filed": int(res["value"]),          # the label basis, as filed
            "decided_at": str(r["ts"]),
            "settled_at": str(res["ts"]),
            "cls": label_class(r["outcome"]),
            "era": "post" if str(res["ts"]) >= PRICE_SIDE_FIX_ISO else "pre",
        })
    return legs


def condition_ids(market_ids):
    con = sqlite3.connect("file:%s?mode=ro" % DB, uri=True)
    out = {}
    for m in market_ids:
        row = con.execute(
            "SELECT conditionId FROM MarketSnapshot WHERE marketId=? AND conditionId IS NOT NULL "
            "ORDER BY collectedAt DESC LIMIT 1", (m,)).fetchone()
        out[m] = row[0] if row else None
    con.close()
    return out


def _get(url, attempts=3):
    for a in range(attempts):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=20) as f:
                return json.loads(f.read().decode())
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            time.sleep(1.2 * (a + 1))
        except Exception:
            time.sleep(0.6 * (a + 1))
    return None


def refresh_truth(legs, cache):
    """Fetch the venue's token table per market and the tape's identity vote per ticket."""
    markets = cache.setdefault("markets", {})
    tape = cache.setdefault("tape", {})
    cids = condition_ids(sorted({l["marketId"] for l in legs}))
    for m, cid in cids.items():
        if m in markets or not cid:
            continue
        js = _get("%s/markets/%s" % (CLOB, cid))
        time.sleep(0.2)
        if not js:
            markets[m] = {"conditionId": cid, "error": "unfetchable"}
            continue
        markets[m] = {
            "conditionId": cid,
            "tokens": [[str(t.get("outcome")), bool(t.get("winner")), t.get("token_id")]
                       for t in (js.get("tokens") or [])],
        }
    for leg in legs:
        key = "%s|%s" % (leg["marketId"], leg["outcome"])
        if key in tape:
            continue
        mk = markets.get(leg["marketId"]) or {}
        toks = mk.get("tokens") or []
        mine = token_for_label(toks, leg["outcome"])
        if not mine or len(toks) != 2:
            tape[key] = {"identity": "ambiguous", "reason": "token table unusable"}
            continue
        t0 = int(iso_to_epoch(leg["decided_at"]))
        best = {}
        for t in toks:
            js = _get("%s/prices-history?market=%s&startTs=%d&endTs=%d&fidelity=1"
                      % (CLOB, t[2], t0 - 900, t0 + 900))
            time.sleep(0.15)
            pts = [p for p in ((js or {}).get("history") or []) if "p" in p]
            if pts:
                best[t[2]] = min(abs(float(p["p"]) - leg["entry"]) for p in pts)
        vote, lab_best, sib_best = identity_vote(toks, mine[0], best)
        tape[key] = {
            "identity": vote,
            "label_best": None if lab_best is None else round(lab_best, 4),
            "sibling_best": None if sib_best is None else round(sib_best, 4),
        }
    cache["generatedAt"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    with open(TRUTH, "w") as f:
        json.dump(cache, f)
    return cache


def load_truth():
    if os.path.exists(TRUTH):
        with open(TRUTH) as f:
            return json.load(f)
    return {"markets": {}, "tape": {}}


def apply_token_basis(legs, truth):
    """Attach the token-basis win to each ticket; None where truth is unavailable."""
    markets = truth.get("markets") or {}
    tape = truth.get("tape") or {}
    for leg in legs:
        mk = markets.get(leg["marketId"]) or {}
        toks = mk.get("tokens") or []
        hit = token_for_label(toks, leg["outcome"]) if toks else None
        leg["token_won"] = bool(hit[2]) if hit else None
        leg["token_label"] = hit[1] if hit else None
        leg["token_id_found"] = hit is not None
        ident = (tape.get("%s|%s" % (leg["marketId"], leg["outcome"])) or {})
        leg["identity"] = ident.get("identity", "unmeasured")
    return legs


def with_basis(legs, pick):
    """Project tickets onto one basis: 'filed' (label) or 'token'."""
    out = []
    for l in legs:
        won = l["filed"] if pick == "filed" else l.get("token_won")
        if won is None:
            continue
        c = dict(l)
        c["won"] = int(won)
        out.append(c)
    return out


# ------------------------------------------------------------------------------- main
def report(legs, truth, filed_summary):
    res = {}
    print("=" * 92)
    print("LONG-SHOT SHADOW LADDER -- ON THE TOKEN BASIS AND ON A PER-BET BASIS")
    print("=" * 92)

    # --- 0
    print("\n0. THE LADDER AS FILED")
    print("  summary artifact: %s" % filed_summary)
    print("  tickets: %d would-admit rows joined to a resolve row" % len(legs))
    bets = dedupe_by_key(legs, lambda l: (l["marketId"], l["outcome"]))
    print("  DISTINCT BETS (market|outcome, earliest ticket): %d  -> %.2f tickets per bet"
          % (len(bets), len(legs) / len(bets) if bets else 0))
    res["tickets"] = len(legs)
    res["distinct_bets"] = len(bets)
    res["tickets_per_bet"] = round(len(legs) / len(bets), 2) if bets else None

    # --- 1
    print("\n1. IDENTITY -- is the label's token the token the ticket was PRICED on?")
    ident = {}
    for l in legs:
        ident[l["identity"]] = ident.get(l["identity"], 0) + 1
    matched = sum(1 for l in legs if l.get("token_id_found"))
    print("  label -> venue token is 1:1 on %d of %d tickets (%.1f%%); %d markets"
          % (matched, len(legs), 100.0 * matched / len(legs) if legs else 0,
             len({l["marketId"] for l in legs})))
    print("  tape vote (a token print within %.0fc of entryPrice at decision +/-15m): %s"
          % (100 * IDENT_TOL, ", ".join("%s %d" % (k, v) for k, v in sorted(ident.items()))))
    res["identity"] = ident
    res["label_token_1to1"] = matched
    if ident.get("sibling_token"):
        print("  WARNING: %d ticket(s) priced on the SIBLING -- the label basis scores the"
              % ident["sibling_token"])
        print("  wrong side there. Reported below, not silently re-marked.")

    # --- 2
    print("\n2. THE BASIS COMPARISON")
    tok = with_basis(legs, "token")
    disagree = [l for l in tok if l["filed"] != l["token_won"]]
    print("  tickets with token truth: %d of %d" % (len(tok), len(legs)))
    for label, xs in (("ALL", tok),
                      ("  label YES/NO", [l for l in tok if l["cls"] == "YES/NO"]),
                      ("  label NAMED", [l for l in tok if l["cls"] == "named"]),
                      ("  pre-2026-11-09", [l for l in tok if l["era"] == "pre"]),
                      ("  post-2026-11-09", [l for l in tok if l["era"] == "post"])):
        b = block(xs)
        if not b["n"]:
            continue
        print("  %-18s n=%3d  hit %5.1f%%  breakeven %5.1f%%  excess %+5.1fpp  PnL $%+8.2f  ROI %+7.1f%%"
              % (label, b["n"], b["hit"], b["breakeven"], b["excess_pp"], b["pnl"], b["roi"]))
    print("  LABEL vs TOKEN disagreements: %d of %d tickets (%.1f%%)"
          % (len(disagree), len(tok), 100.0 * len(disagree) / len(tok) if tok else 0))
    yn = [l for l in tok if l["cls"] == "YES/NO"]
    yn_dis = sum(1 for l in yn if l["filed"] != l["token_won"])
    print("  INVARIANT on YES/NO rows (both bases must agree): %d rows, %d disagreements %s"
          % (len(yn), yn_dis, "OK" if yn_dis == 0 else "FAIL - token join broken, do not read past"))
    res["disagreements"] = len(disagree)
    res["yesno_invariant_failures"] = yn_dis
    res["ticket_basis"] = {k: block(v) for k, v in (
        ("all", tok),
        ("yesno", yn),
        ("named", [l for l in tok if l["cls"] == "named"]),
        ("pre_fix", [l for l in tok if l["era"] == "pre"]),
        ("post_fix", [l for l in tok if l["era"] == "post"]),
    )}

    # --- 3
    print("\n3. CONCENTRATION -- is the headline a book or a lottery ticket?")
    for label, xs in (("TICKET basis", tok), ("BET basis", with_basis(bets, "token"))):
        c = concentration(xs)
        lo, hi = cluster_ci(xs)
        print("  %-11s n=%3d  sum $%+9.2f  ex-top-1 $%+8.2f  ex-top-5 $%+8.2f  ex-top-10 $%+8.2f  median $%+7.2f"
              % (label, c["n"], c["sum"], c["ex_top_1"], c["ex_top_5"], c["ex_top_10"], c["median"]))
        print("  %-11s market-clustered ROI/ticket CI [%+.1f%%, %+.1f%%] (2,000 resamples of MARKETS)"
              % ("", lo, hi))
        res.setdefault("concentration", {})[label] = dict(c, ci_lo=lo, ci_hi=hi)

    # --- 4
    print("\n4. THE LADDER'S OWN DECISION RULE (card profit-longshot-token-basis)")
    print("  '>=150 further resolved admits clear +5pp of hit-rate excess over their actual")
    print("   entry price, measured on the token basis'")
    for label, xs in (("ticket basis", tok), ("bet basis", with_basis(bets, "token"))):
        r = evaluate_rule(xs)
        print("  %-12s n=%3d (need >=%d: %s)  excess %+.1fpp (need >=+5.0: %s)  -> %s"
              % (label, r["n_resolved_bets"], r["n_required"], "met" if r["n_met"] else "NOT MET",
                 r["excess_pp"], "met" if r["excess_met"] else "NOT MET",
                 "PROMOTABLE" if r["promotable"] else "STAYS A SHADOW"))
        res.setdefault("rule", {})[label] = r

    # --- 5
    print("\n5. WHAT THE TICKET BASIS OVERSTATES")
    tb = block(tok)
    bb = block(with_basis(bets, "token"))
    if tb["n"] and bb["n"]:
        print("  ticket basis: %d tickets, %d wins, $%+.2f on $%d staked"
              % (tb["n"], tb["wins"], tb["pnl"], int(STAKE * tb["n"])))
        print("  bet basis   : %d bets,    %d wins, $%+.2f on $%d staked"
              % (bb["n"], bb["wins"], bb["pnl"], int(STAKE * bb["n"])))
        print("  %.2fx tickets per bet at the ticket level; the beat-breakeven excess falls"
              % (tb["n"] / bb["n"]))
        print("  %+.1fpp -> %+.1fpp." % (tb["excess_pp"], bb["excess_pp"]))
        res["overstatement"] = {
            "ticket_pnl": tb["pnl"], "bet_pnl": bb["pnl"],
            "ticket_excess_pp": tb["excess_pp"], "bet_excess_pp": bb["excess_pp"],
        }
    print("\n  This file changes no rule, size, threshold or gate.")
    return res


def main(argv):
    fetch = "--fetch" in argv
    if "--self-test" in argv:
        return self_test()
    rows = read_ledger()
    legs = build_population(rows)
    truth = load_truth()
    if fetch or not truth.get("markets"):
        truth = refresh_truth(legs, truth)
    legs = apply_token_basis(legs, truth)
    filed = "data/longshot-shadow-summary.json (missing)"
    if os.path.exists(SUMMARY):
        with open(SUMMARY) as f:
            s = json.load(f)
        filed = ("data/longshot-shadow-summary.json generatedAt %s: %s admits, %s resolved, "
                 "%s wins, %.1f%%, $%.2f"
                 % (s.get("generatedAt"), s.get("wouldAdmit"), s.get("resolved"), s.get("wins"),
                    100.0 * (s.get("winRate") or 0), s.get("totalPnl") or 0))
    res = report(legs, truth, filed)
    res["generatedAt"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    res["basis"] = {
        "level": "one ticket (marketId|outcome candidate joined to its resolve row); bet = marketId|outcome",
        "clock": "resolve row ts (UTC); identity tape read +/-15 min around the decision ts",
        "population": "data/longshot-shadow.jsonl would-admit candidates, all-time",
        "token_truth": "clob.polymarket.com/markets/<conditionId> tokens[].outcome/winner (keyless)",
    }
    with open(ARTIFACT, "w") as f:
        json.dump(res, f, indent=2)
    print("\n  artifact: %s" % ARTIFACT)
    return 0


# ---------------------------------------------------------------------------- self-test
def self_test():
    ok = tot = 0

    def chk(name, cond, extra=""):
        nonlocal ok, tot
        tot += 1
        if cond:
            ok += 1
        else:
            print("  FAIL %s %s" % (name, extra))

    print("SELF-TEST")
    chk("pnl win at 0.10 pays 9x stake", abs(pnl_of(0.10, 1) - 180.0) < 1e-9, pnl_of(0.10, 1))
    chk("pnl loss is the stake", pnl_of(0.10, 0) == -20.0, pnl_of(0.10, 0))
    chk("YES is binary", label_class("yes") == "YES/NO")
    chk("team is named", label_class("Team Liquid") == "named")
    chk("label-only near -> label_token", classify_identity(0.01, 0.70, 0.03) == "label_token")
    chk("sibling-only near -> sibling_token", classify_identity(0.70, 0.01, 0.03) == "sibling_token")
    chk("neither near -> ambiguous", classify_identity(0.50, 0.60, 0.03) == "ambiguous")
    chk("MUTATION: swapping the distances flips the vote",
        classify_identity(0.01, 0.70, 0.03) != classify_identity(0.70, 0.01, 0.03))
    chk("closest wins when both are near", classify_identity(0.02, 0.01, 0.03) == "sibling_token")
    toks2 = [["Team A", False, "ta"], ["Team B", True, "tb"]]
    v, lb, sb = identity_vote(toks2, 0, {"ta": 0.01, "tb": 0.62})
    chk("identity_vote votes on the LABEL token id", v == "label_token" and lb == 0.01 and sb == 0.62, (v, lb, sb))
    v2, _, _ = identity_vote(toks2, 0, {"ta": 0.62, "tb": 0.01})
    chk("MUTATION: moving the tape to the sibling flips the vote", v2 == "sibling_token", v2)
    chk("MUTATION: the winner boolean is not used as a token id",
        identity_vote(toks2, 1, {"ta": 0.7, "tb": 0.02})[0] == "label_token")
    chk("a one-token table has no sibling to blame",
        identity_vote([["Yes", True, "solo"]], 0, {"solo": 0.5})[0] == "ambiguous")
    toks = [["Yes", True, "t0"], ["No", False, "t1"]]
    chk("label maps to its token", token_for_label(toks, "YES")[1] == "Yes")
    chk("unknown label maps to nothing", token_for_label(toks, "Under") is None)
    chk("duplicate labels are ambiguous, not guessed",
        token_for_label([["A", True, "0"], ["A", False, "1"]], "A") is None)
    ls = [{"marketId": "m", "outcome": "o", "entry": 0.2, "won": 1, "decided_at": "2026-01-02"},
          {"marketId": "m", "outcome": "o", "entry": 0.1, "won": 1, "decided_at": "2026-01-01"}]
    d = dedupe_by_key(ls, lambda l: (l["marketId"], l["outcome"]))
    chk("dedupe keeps the EARLIEST ticket", len(d) == 1 and d[0]["entry"] == 0.1, d)
    legs = [{"marketId": "a", "outcome": "o", "entry": 0.1, "won": 1},
            {"marketId": "b", "outcome": "o", "entry": 0.1, "won": 0},
            {"marketId": "c", "outcome": "o", "entry": 0.1, "won": 0}]
    c = concentration(legs)
    chk("ex-top-1 removes the single winner", c["ex_top_1"] == -40.0, c)
    chk("sum equals the three legs", c["sum"] == 140.0, c)
    b = block([{"marketId": "m", "outcome": "o", "entry": 0.25, "won": 1},
               {"marketId": "n", "outcome": "o", "entry": 0.25, "won": 0}])
    chk("hit 50%% vs breakeven 25%% = +25pp" % (),
        b["hit"] == 50.0 and b["breakeven"] == 25.0 and b["excess_pp"] == 25.0, b)

    def mk(n, wins, entry):
        return [{"marketId": "m%d" % i, "outcome": "o", "entry": entry,
                 "won": 1 if i < wins else 0} for i in range(n)]

    chk("n=160, hit 20%% vs 10%% -> promotable" % (), evaluate_rule(mk(160, 32, 0.10))["promotable"] is True)
    chk("excess below 5pp -> not promotable", evaluate_rule(mk(160, 12, 0.10))["promotable"] is False)
    chk("n below 150 -> not promotable even with excess",
        evaluate_rule(mk(140, 30, 0.10))["promotable"] is False)
    chk("MUTATION: a big n alone cannot pass the gate",
        evaluate_rule(mk(400, 40, 0.10))["promotable"] is False)
    ls = [{"marketId": "m", "outcome": "o", "entry": 0.1, "filed": 1, "token_won": None, "won": 1},
          {"marketId": "n", "outcome": "o", "entry": 0.1, "filed": 1, "token_won": 0, "won": 1}]
    chk("token basis drops unmeasured tickets", len(with_basis(ls, "token")) == 1)
    chk("label basis keeps them", len(with_basis(ls, "filed")) == 2)
    xs = [{"marketId": "m%d" % (i // 7), "outcome": "o", "entry": 0.08 + 0.02 * ((i * 3) % 9), "won": 1 if (i * 7) % 11 < 2 else 0}
          for i in range(70)]
    lo, hi = cluster_ci(xs)
    chk("cluster CI is ordered", lo < hi, (lo, hi))
    chk("cluster CI is deterministic", cluster_ci(xs) == (lo, hi))
    print("SELF-TEST %d/%d" % (ok, tot))
    return 0 if ok == tot else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
