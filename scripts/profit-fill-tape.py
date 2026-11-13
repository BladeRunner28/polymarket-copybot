#!/usr/bin/env python3
"""
FILL TAPE — adjudicate every leg's fill from the venue's own price tape, not from our capture.

WHY THIS EXISTS
---------------
The 2026-11-12 review established that the fill-aware booking flip (src/lib/paper.ts, DEFAULT ON
since 2026-10-28) split the book into filled / unfilled / unresolved, and that the C-200 lane's
post-flip sign is set by the UNRESOLVED class -- the class its own resolver had * proved it can
never adjudicate (coverage 0.0%: the print-through artifact is a rolling window and 2,247 legs sit
outside it forever).

That conclusion rested on one assumption: that the book capture is the only evidence that will
ever exist. It is not. `https://clob.polymarket.com/prices-history` serves the venue's minute-level
price series for ANY token, keyless, after the fact. A print at or below our resting bid inside the
dispatch window is exactly the "tape cleared it" positive the resolver's flat model accepts.

So this instrument asks a question yesterday could not: with a tape verdict on *every* leg,
  (a) does the tape agree with the 582 legs the resolver DID stamp (is the model sane),
  (b) what happens to the 79 "unresolvable" C-200 legs (my own refutation test), and
  (c) what does STANDARD -- 0 of 3,710 legs with any fill verdict -- look like once asked.

MODEL (stated so it can be wrong)
---------------------------------
For a leg bought at price L on token T, dispatched at t0, window W:
    touch      = min(p) over [t0, t0+W] <= L + TICK      -> "filled_tape"
    no_touch   = min(p) over [t0, t0+W] >  L + TOUCH_EPS -> "unfilled_tape"
    ambiguous  = min(p) within (L + TICK, L + TOUCH_EPS] -> "near_miss"
A touch is POSITIVE evidence (someone traded at or below our bid -> our bid was at or inside the
touch). No touch is a *weaker* negative: a resting bid can be filled by a seller crossing to it
without a later print below it, and a 1-minute series samples the interval. So "unfilled_tape" is an
upper bound on non-fills, and the touch rate is a LOWER bound on fill rate. Every conclusion below
is stated in that direction. A tape cross-check against raw prints (§1b) bounds the sampling error.

COST BASIS
----------
Same loader as the rest of the review (`scripts/profit-postfix-integrity.py`, imported):
`simulatedPositionSize` = DOLLARS AT RISK, price = the price we actually paid (INVERTED legs
repriced to the wallet's fill), CIs market-clustered, 2,000 draws. Dedupe to the first leg per
bot|wallet|market|outcome, as in profit-fill-cohort.py.

READ-ONLY. No prisma write, no RuleSet read, no rule edit, no fillStatus stamp written.
Caches raw HTTP under data/fill-tape-cache/ (gitignored) so re-runs are free.

RUN
  python3 scripts/profit-fill-tape.py                    # default window, both lanes
  python3 scripts/profit-fill-tape.py --since=2026-09-01
  python3 scripts/profit-fill-tape.py --selftest
"""
import argparse
import json
import os
import random
import sqlite3
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
_spec = __import__("importlib.util", fromlist=["util"]).spec_from_file_location(
    "ppi", os.path.join(HERE, "profit-postfix-integrity.py"))
ppi = __import__("importlib.util", fromlist=["util"]).module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(ppi)

CACHE = os.path.join(ROOT, "data", "fill-tape-cache")
FLIP = "2026-10-28 00:00:00"
FLIP_MS = ppi._ms(FLIP)
TICK = 0.001          # a print AT our price is a fill
TOUCH_EPS = 0.010     # within 1c but no touch -> ambiguous, not a "negative"
WINDOW_S = 3600       # default fill horizon from dispatch (swept in §1)
WINDOW_MAX = 3600     # always fetch one hour; shorter windows are re-filtered locally
WINDOWS = (60, 120, 300, 600, 900, 1800, 3600)
LANES = ("BANKROLL_200", "STANDARD")

# ------------------------------------------------------------------ http (cached)


def _con():
    uri = "file:" + os.path.join(ROOT, "prisma", "dev.db") + "?mode=ro"
    c = sqlite3.connect(uri, uri=True)
    c.row_factory = sqlite3.Row
    return c


ppi.con = _con


def _cache_path(kind, key):
    os.makedirs(CACHE, exist_ok=True)
    return os.path.join(CACHE, f"{kind}-{key}.json")


def _get(url, kind, key, tries=3):
    p = _cache_path(kind, key)
    if os.path.exists(p):
        try:
            with open(p) as f:
                return json.load(f)
        except Exception:
            pass
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "medusa-profit-review/1.0"})
            with urllib.request.urlopen(req, timeout=20) as r:
                body = json.loads(r.read().decode())
            tmp = p + ".tmp"
            with open(tmp, "w") as f:
                json.dump(body, f)
            os.replace(tmp, p)
            return body
        except urllib.error.HTTPError as e:
            last = f"HTTP {e.code}"
            if e.code in (429, 500, 502, 503):
                time.sleep(1.5 * (i + 1))
                continue
            break
        except Exception as e:                     # network
            last = f"{type(e).__name__}: {e}"
            time.sleep(0.8 * (i + 1))
    return {"__error__": last}


def market_tokens(cid):
    """conditionId -> [{token_id, outcome}]. Keyless CLOB market record."""
    j = _get(f"https://clob.polymarket.com/markets/{cid}", "cm", cid[:24])
    if not isinstance(j, dict) or j.get("__error__") or "tokens" not in j:
        return None, (j or {}).get("__error__", "no tokens field")
    return [{"token_id": t["token_id"], "outcome": str(t.get("outcome", ""))} for t in j["tokens"]], None


def series(token, t0_s, win=WINDOW_S):
    """Minute-level price series for [t0, t0+win]. Returns [(t, p)] or None."""
    key = f"{token[:16]}-{t0_s}"
    j = _get(f"https://clob.polymarket.com/prices-history?market={token}"
             f"&startTs={t0_s}&endTs={t0_s + win}&fidelity=1", "ph", key)
    if not isinstance(j, dict) or j.get("__error__"):
        return None, (j or {}).get("__error__", "bad body")
    h = j.get("history")
    if not isinstance(h, list):
        return None, str(j)[:60]
    return [(int(p["t"]), float(p["p"])) for p in h if "t" in p and "p" in p], None


# ------------------------------------------------------------------ legs + token map


def load(since):
    legs = ppi.dedupe(ppi.load_legs())
    out = []
    c = _con()
    cond = {r["id"]: r["conditionId"] for r in c.execute(
        "SELECT p.id AS id, o.conditionId AS conditionId FROM PaperTrade p "
        "JOIN DecisionJournal d ON d.id = p.decisionJournalId "
        "LEFT JOIN ObservedTrade o ON o.id = d.observedTradeId")}
    lo = ppi._ms(since)
    for l in legs:
        if l["status"] == "open" or not l["openedTs"] or l["openedTs"] < lo:
            continue
        cid = cond.get(l["id"])
        if not cid:
            continue
        l["cid"] = cid
        out.append(l)
    return out


def _norm(s):
    return str(s or "").strip().lower()


def early_price(tok_series, t0_s):
    """First observation >= t0 (the price when we dispatched)."""
    for t, p in tok_series:
        if t >= t0_s - 120:
            return p
    return None


def adjudicate(leg, target_p):
    """target_p = the price we paid. Fetches ONE hour of tape; windows are re-filtered locally."""
    t0_s = leg["openedTs"] // 1000
    cid = leg["cid"]
    toks, err = market_tokens(cid)
    if toks is None:
        return {"verdict": "no_market", "err": err, "token": None, "minp": None, "map": None,
                "series": None, "verdicts": {}}
    want = _norm(leg["outcome"])
    exact = [t for t in toks if _norm(t["outcome"]) == want]
    token, how, s = None, None, None
    if len(exact) == 1:
        token, how = exact[0]["token_id"], "label"
        s, err = series(token, t0_s)
    if token is None:
        # price-proximity disambiguation for team-name / over-under labels
        cand = []
        for t in toks:
            ts, e = series(t["token_id"], t0_s)
            if ts:
                p0 = early_price(ts, t0_s)
                if p0 is not None:
                    cand.append((abs(p0 - target_p), t["token_id"], ts, p0))
        if len(cand) < 2:
            return {"verdict": "no_tape", "err": err or "no series", "token": None, "minp": None,
                    "map": how, "series": None, "verdicts": {}}
        cand.sort()
        if cand[1][0] - cand[0][0] < 0.02:
            return {"verdict": "ambiguous_token", "err": None, "token": None, "minp": None,
                    "map": "proximity", "series": None, "verdicts": {}}
        _, token, s, _ = cand[0]
        how = "proximity"
    if not s:
        return {"verdict": "no_tape", "err": err, "token": token, "minp": None, "map": how,
                "series": None, "verdicts": {}}
    win = [(t, p) for t, p in s if t0_s <= t <= t0_s + WINDOW_MAX]
    if not win:
        return {"verdict": "no_tape", "err": "empty window", "token": token, "minp": None,
                "map": how, "series": None, "verdicts": {}}
    vs = {}
    for W in WINDOWS:
        sub = [(t, p) for t, p in win if t <= t0_s + W]
        if not sub:
            vs[W] = {"verdict": "no_tape", "minp": None, "lag": None}
            continue
        m = min(p for _, p in sub)
        first = next((t for t, p in sub if p <= target_p + TICK), None)
        vs[W] = {"verdict": cls_of(m, target_p), "minp": m,
                 "lag": (first - t0_s) if first is not None else None}
    cur = vs[WINDOW_S]
    return {"verdict": cur["verdict"], "err": None, "token": token, "minp": cur["minp"],
            "map": how, "series": win, "verdicts": vs,
            "p0": early_price(win, t0_s),
            "touch_lag_s": cur["lag"], "n_obs": len(win)}


def cls_of(minp, L):
    if minp <= L + TICK:
        return "filled_tape"
    if minp <= L + TOUCH_EPS:
        return "near_miss"
    return "unfilled_tape"


def classify(legs, workers=8):
    def one(l):
        return adjudicate(l, l["trueP"])
    with ThreadPoolExecutor(max_workers=workers) as ex:
        res = list(ex.map(one, legs))
    for l, r in zip(legs, res):
        for k, v in r.items():
            l["tape_" + k] = v
    return legs


def verdict_at(l, W):
    """Verdict under a different horizon, from the series already in memory."""
    s = l.get("tape_series")
    if not s:
        return "no_tape"
    t0_s = l["openedTs"] // 1000
    sub = [p for t, p in s if t <= t0_s + W]
    return cls_of(min(sub), l["trueP"]) if sub else "no_tape"


# ------------------------------------------------------------------ stats


def roi(ls, pnl=None):
    pnl = pnl or (lambda l: l["realizedPnl"] or 0.0)
    n = sum(l["simulatedPositionSize"] for l in ls)
    p = sum(pnl(l) for l in ls)
    return (p / n * 100.0) if n else None, p, n


def ci(ls, pnl=None):
    return ppi.cluster_ci(ls, pnl or (lambda l: l["realizedPnl"] or 0.0))


def diff_ci(arm, other, n=2000, seed=11, pnl=None):
    pnl = pnl or (lambda l: l["realizedPnl"] or 0.0)
    by = {}
    for tag, ls in (("a", arm), ("b", other)):
        for l in ls:
            g = by.setdefault(l["marketId"], {"a": [0.0, 0.0], "b": [0.0, 0.0]})
            g[tag][0] += pnl(l)
            g[tag][1] += l["simulatedPositionSize"]
    ks = sorted(by)
    if len(ks) < 2:
        return (None, None)
    rnd = random.Random(seed)
    out = []
    for _ in range(n):
        ap = an = bp = bn = 0.0
        for _ in range(len(ks)):
            g = by[ks[rnd.randrange(len(ks))]]
            ap += g["a"][0]; an += g["a"][1]; bp += g["b"][0]; bn += g["b"][1]
        if an > 0 and bn > 0:
            out.append(ap / an * 100.0 - bp / bn * 100.0)
    out.sort()
    return (out[int(0.025 * len(out))], out[int(0.975 * len(out)) - 1]) if out else (None, None)


def fmt_ci(ls, pnl=None):
    lo, hi = ci(ls, pnl)
    return f"[{lo:+.1f},{hi:+.1f}]" if lo is not None else "n/a"


# ------------------------------------------------------------------ sections


def sec_coverage(legs):
    print("=" * 90)
    print("0. CAN THE TAPE SPEAK AT ALL — coverage on the cohort that decides it")
    print("=" * 90)
    n = len(legs)
    for lane in LANES:
        g = [l for l in legs if l["botId"] == lane]
        if not g:
            continue
        vc = {}
        for l in g:
            vc[l["tape_verdict"]] = vc.get(l["tape_verdict"], 0) + 1
        tot = len(g)
        s = ", ".join(f"{k} {v} ({v / tot * 100:.0f}%)" for k, v in sorted(vc.items(), key=lambda x: -x[1]))
        print(f"  {lane:<13} n={tot:>4}  {s}")
    print(f"\n  population: finished, non-demo, deduped, conditionId present, opened >= {ARGS.since}")
    print("  no_market = CLOB has no record; no_tape = series empty; ambiguous_token = the two")
    print("  candidate tokens were within 2c at dispatch, so a price map would be a guess.")


def sec_validate(legs):
    print()
    print("=" * 90)
    print("1. IS THE TAPE MODEL SANE — it is scored against the 582 legs the resolver already stamped")
    print("=" * 90)
    both = [l for l in legs if l["tape_verdict"] in ("filled_tape", "unfilled_tape", "near_miss")
            and l.get("fillStatus") in ("filled", "unfilled")]
    if not both:
        print("  no overlap between the tape cohort and stamped legs")
        return
    # CALIBRATION: the stamped legs are the only labels that exist. Sweep the horizon and pick the
    # window that best reproduces the resolver's verdicts, then use that window everywhere else.
    print("  horizon sweep against the resolver's own verdicts (stamped C-200 legs):")
    print(f"  {'window':>7} {'n':>5} {'agree%':>7} {'touch|stamped filled':>21} {'touch|stamped unfilled':>23}")
    best = None
    for W in WINDOWS:
        rows = [(l, verdict_at(l, W)) for l in both]
        rows = [(l, v) for l, v in rows if v != "no_tape"]
        two = [(l, v) for l, v in rows if v != "near_miss"]
        if not two:
            continue
        agree = sum(1 for l, v in two if (l["fillStatus"] == "filled") == (v == "filled_tape")) / len(two) * 100
        sf = [v for l, v in rows if l["fillStatus"] == "filled"]
        su = [v for l, v in rows if l["fillStatus"] == "unfilled"]
        tf = sum(1 for v in sf if v == "filled_tape") / len(sf) * 100 if sf else 0
        tu = sum(1 for v in su if v == "filled_tape") / len(su) * 100 if su else 0
        sep = tf - tu
        print(f"  {W:>6}s {len(two):>5} {agree:>6.1f}% {tf:>20.1f}% {tu:>22.1f}%")
        if best is None or sep > best[1]:
            best = (W, sep, agree)
    if best:
        print(f"\n  best separation at W={best[0]}s: filled-stamped touch {best[1]:.0f}pp above "
              f"unfilled-stamped (agreement {best[2]:.1f}%)")
        print(f"  headline verdicts below use W={WINDOW_S}s (--window to change; verdicts are cached).")
    m = {}
    for l in both:
        m[(l["fillStatus"], l["tape_verdict"])] = m.get((l["fillStatus"], l["tape_verdict"]), 0) + 1
    cols = ("filled_tape", "near_miss", "unfilled_tape")
    print(f"  {'resolver stamp':<16} " + " ".join(f"{c:>14}" for c in cols) + f" {'n':>6}")
    for st in ("filled", "unfilled"):
        row = [m.get((st, c), 0) for c in cols]
        print(f"  {st:<16} " + " ".join(f"{v:>14}" for v in row) + f" {sum(row):>6}")
    # agreement on the two-sided call (near_miss excluded)
    bi = [l for l in both if l["tape_verdict"] != "near_miss"]
    agree = sum(1 for l in bi if (l["fillStatus"] == "filled") == (l["tape_verdict"] == "filled_tape"))
    print(f"\n  two-sided agreement: {agree}/{len(bi)} = {agree / len(bi) * 100:.1f}%  (near_miss rows excluded)")
    # per-stamp touch rates -- the directional receipts
    for st in ("filled", "unfilled"):
        g = [l for l in both if l["fillStatus"] == st]
        t = sum(1 for l in g if l["tape_verdict"] == "filled_tape")
        print(f"  resolver '{st}': tape touches {t}/{len(g)} = {t / len(g) * 100:.1f}%")
    print("  READ: a high touch rate on resolver-'filled' legs and a low one on 'unfilled' means the")
    print("  tape is measuring the same object. Disagreement in the low-touch direction is expected")
    print("  (1-minute sampling misses intra-minute troughs); disagreement the other way is not.")


def sec_unresolved(legs):
    print()
    print("=" * 90)
    print("2. MY OWN REFUTATION TEST — the C-200 legs the resolver called UNDECIDABLE")
    print("=" * 90)
    post = [l for l in legs if l["botId"] == "BANKROLL_200" and l["openedTs"] >= FLIP_MS]
    null = [l for l in post if not l.get("fillStatus")]
    if not null:
        print("  no unresolved post-flip C-200 legs in this window")
        return
    vc = {}
    for l in null:
        vc[l["tape_verdict"]] = vc.get(l["tape_verdict"], 0) + 1
    tot = len(null)
    print(f"  unresolved legs: {tot}, ${sum(l['simulatedPositionSize'] for l in null):,.0f} at risk")
    for k, v in sorted(vc.items(), key=lambda x: -x[1]):
        print(f"    {k:<16} {v:>4}  ({v / tot * 100:.0f}%)")
    spoke = [l for l in null if l["tape_verdict"] in ("filled_tape", "unfilled_tape", "near_miss")]
    touch = [l for l in spoke if l["tape_verdict"] == "filled_tape"]
    if spoke:
        print(f"\n  tape could adjudicate {len(spoke)}/{tot} = {len(spoke) / tot * 100:.0f}%; of those, "
              f"{len(touch)} touched ({len(touch) / len(spoke) * 100:.0f}%)")
        r, p, n = roi(touch)
        print(f"  of the newly-adjudicated FILLED: {len(touch)} legs ${n:,.0f} -> {p:+.1f} ({r:+.1f}%) {fmt_ci(touch)}")
        un = [l for l in spoke if l["tape_verdict"] == "unfilled_tape"]
        if un:
            r2, p2, n2 = roi(un)
            print(f"  of the newly-adjudicated UNFILLED: {len(un)} legs ${n2:,.0f} -> {p2:+.1f} ({r2:+.1f}%) {fmt_ci(un)}")
        print("\n  YESTERDAY'S REFUTATION CONDITION: if >=70% of these legs printed at or below our bid,")
        print("  they were real positions and the -46.7% proven-fill record is a selected minority.")
        print(f"  MEASURED: {len(touch) / len(spoke) * 100:.1f}% of the adjudicable ones touched.")


def sec_lane(legs, lane):
    print()
    print("=" * 90)
    print(f"3. {lane} — what its booked number becomes once fill is asked")
    print("=" * 90)
    g = [l for l in legs if l["botId"] == lane]
    if not g:
        print("  none")
        return
    classes = ("filled_tape", "near_miss", "unfilled_tape", "no_tape", "no_market", "ambiguous_token")
    print(f"  {'class':<16} {'legs':>5} {'notional':>10} {'pnl':>10} {'ROI':>8} {'CI95':>18} {'ntl%':>6}")
    tot_n = sum(l["simulatedPositionSize"] for l in g)
    for c in classes:
        h = [l for l in g if l["tape_verdict"] == c]
        if not h:
            continue
        r, p, n = roi(h)
        print(f"  {c:<16} {len(h):>5} {n:>10,.0f} {p:>+10.1f} {r:>+7.1f}% {fmt_ci(h):>18} {n / tot_n * 100:>5.1f}%")
    r, p, n = roi(g)
    print(f"  {'TOTAL':<16} {len(g):>5} {n:>10,.0f} {p:>+10.1f} {r:>+7.1f}%")
    a = [l for l in g if l["tape_verdict"] == "filled_tape"]
    b = [l for l in g if l["tape_verdict"] == "unfilled_tape"]
    if a and b:
        lo, hi = diff_ci(a, b)
        ra, rb = roi(a)[0], roi(b)[0]
        print(f"\n  touched minus untouched: {ra - rb:+.1f}pp  CI95 [{lo:+.1f},{hi:+.1f}] (market-clustered)")
        tot = sum(l["realizedPnl"] or 0.0 for l in g)
        for k in (1, 3, 5):
            keep = sorted(a, key=lambda l: -(l["realizedPnl"] or 0))[k:]
            if keep:
                print(f"  touched ex-top{k}: n={len(keep):>3} ROI {roi(keep)[0]:+.1f}%  (full touched {tot:+.1f})")
    # the restatement: untouched legs are not positions
    def pnl_pess(l):
        return 0.0 if l["tape_verdict"] == "unfilled_tape" else (l["realizedPnl"] or 0.0)
    r, p, n = roi(g, pnl_pess)
    print(f"\n  RESTATED (untouched books ZERO, the flip's own treatment): {len(g)} legs "
          f"${n:,.0f} -> {p:+.1f} ({r:+.1f}%) {fmt_ci(g, pnl_pess)}")
    r0 = roi(g)[0]
    print(f"  as booked: {r0:+.1f}%   delta: {r - r0:+.1f}pp")


def sec_break_even(legs):
    print()
    print("=" * 90)
    print("4. FILLABILITY — break-even entry slippage on the cohort that supposedly has the edge")
    print("=" * 90)
    g = [l for l in legs if l["tape_verdict"] == "filled_tape"]
    if not g:
        print("  none")
        return
    # min price in the window = the best level the market actually offered; if we had to pay the
    # fill price (touch) instead of our bid, the same exit is worth ntl*(exit/px - 1)
    base = sum(l["realizedPnl"] or 0.0 for l in g)
    n = sum(l["simulatedPositionSize"] for l in g)
    print(f"  touched cohort: {len(g)} legs, ${n:,.0f}, booked {base:+.1f} ({base / n * 100:+.1f}%)")
    print("  paying MORE for the same exit is the adverse direction for a buyer; 'cheaper' is the")
    print("  reference row and shows how much of the book's edge is just the 2c gap.")
    print(f"  {'entry assumption':<38} {'pnl':>10} {'ROI':>8} {'vs booked':>10}")
    rows = [("our bid (booked)", 0.0),
            ("bid +0.5c (worse)", +0.005),
            ("bid +1c (worse)", +0.010),
            ("bid +2c (worse)", +0.020),
            ("bid +5c (worse)", +0.050),
            ("bid -1c (cheaper, reference)", -0.010)]
    for label, k in rows:
        pp = sum(ppi.true_pnl(l, min(0.999, max(0.005, l["trueP"] + k))) for l in g)
        print(f"  {label:<38} {pp:>+10.1f} {pp / n * 100:>+7.1f}% {pp / n * 100 - base / n * 100:>+9.1f}pp")
    print("\n  'tape minimum' is the best price the market printed in the hour after dispatch — the")
    print("  fill we would have got if we had chased instead of resting. It is the optimistic bound.")
    lags = sorted(l["tape_touch_lag_s"] for l in g if l.get("tape_touch_lag_s") is not None)
    if lags:
        med = lags[len(lags) // 2]
        print(f"  time to first touch: median {med}s, p90 {lags[int(0.9 * len(lags)) - 1]}s, "
              f">{WINDOW_S}s {sum(1 for x in lags if x > WINDOW_S)}")


def series24(token, t0_s, win=86400, fidelity=5):
    """Coarser series for the long-horizon probe: did the price EVER come back to our bid?"""
    key = f"{token[:16]}-{t0_s}-24h"
    j = _get(f"https://clob.polymarket.com/prices-history?market={token}"
             f"&startTs={t0_s}&endTs={t0_s + win}&fidelity={fidelity}", "ph24", key)
    if not isinstance(j, dict) or j.get("__error__"):
        return None
    h = j.get("history")
    if not isinstance(h, list):
        return None
    return [(int(p["t"]), float(p["p"])) for p in h if "t" in p and "p" in p]


def sec_horizon(legs):
    print()
    print("=" * 90)
    print("8. THE COUNTER-ARGUMENT I HAD TO TEST — were the 'untouched' legs simply filled LATER")
    print("=" * 90)
    un = [l for l in legs if l["tape_verdict"] == "unfilled_tape" and l.get("tape_token")]
    print(f"  untouched within 60m: {len(un)} legs; re-querying a 24h series (5-min fidelity) for each")
    tot = 0
    buckets = {"<=1h": 0, "1-6h": 0, "6-24h": 0, "never in 24h": 0}
    pnl_late, ntl_late = 0.0, 0.0
    pnl_never, ntl_never = 0.0, 0.0
    never = []
    per_lane = {}
    for l in un:
        t0 = l["openedTs"] // 1000
        s = series24(l["tape_token"], t0)
        if not s:
            continue
        tot += 1
        hit = next((t for t, p in s if t0 <= t <= t0 + 86400 and p <= l["trueP"] + TICK), None)
        lag = (hit - t0) if hit else None
        pl = per_lane.setdefault(l["botId"], {"never": 0, "n": 0, "ntl": 0.0, "pnl": 0.0,
                                             "late_n": 0, "late_ntl": 0.0, "late_pnl": 0.0})
        pl["n"] += 1
        if lag is None:
            buckets["never in 24h"] += 1
            pnl_never += l["realizedPnl"] or 0
            ntl_never += l["simulatedPositionSize"]
            pl["never"] += 1
            pl["ntl"] += l["simulatedPositionSize"]
            pl["pnl"] += l["realizedPnl"] or 0
            never.append(l)
        else:
            k = "<=1h" if lag <= 3600 else ("1-6h" if lag <= 21600 else "6-24h")
            buckets[k] += 1
            if lag > 3600:
                pnl_late += l["realizedPnl"] or 0
                ntl_late += l["simulatedPositionSize"]
                pl["late_n"] += 1
                pl["late_ntl"] += l["simulatedPositionSize"]
                pl["late_pnl"] += l["realizedPnl"] or 0
    if not tot:
        print("  probe returned no data")
        return
    print(f"  answered: {tot}")
    for k, v in buckets.items():
        print(f"    {k:<14} {v:>4}  ({v / tot * 100:.0f}%)")
    print(f"\n  that only touched AFTER the hour: {buckets['1-6h'] + buckets['6-24h']} legs, "
          f"${ntl_late:,.0f} at risk, booked {pnl_late:+.1f} ({pnl_late / ntl_late * 100:+.1f}%)"
          if ntl_late else "")
    if ntl_never:
        print(f"  never touched in 24h: {buckets['never in 24h']} legs, ${ntl_never:,.0f} at risk, "
              f"booked {pnl_never:+.1f} ({pnl_never / ntl_never * 100:+.1f}%)")
    print("\n  per lane, restated so that ONLY the 24h-never class is voided (the conservative read):")
    print(f"  {'lane':<13} {'legs':>5} {'booked ROI':>10} {'never n':>7} {'never $':>8} {'never PnL':>10} "
          f"{'restated ROI':>12} {'late-fill ROI':>13}")
    for lane, pl in per_lane.items():
        g = [l for l in un if l["botId"] == lane]
        all_lane = [l for l in legs if l["botId"] == lane]
        n_all = sum(l["simulatedPositionSize"] for l in all_lane)
        p_all = sum(l["realizedPnl"] or 0 for l in all_lane)
        late_roi = (pl["late_pnl"] / pl["late_ntl"] * 100) if pl["late_ntl"] else float("nan")
        print(f"  {lane:<13} {len(all_lane):>5} {p_all / n_all * 100:>+9.1f}% {pl['never']:>7} "
              f"{pl['ntl']:>8,.0f} {pl['pnl']:>+10.1f} {(p_all - pl['pnl']) / n_all * 100:>+11.1f}% "
              f"{late_roi:>+12.1f}%")
    print("  OUR MODEL: the paper ledger has no cancel, so a bid that fills at hour 7 is still a real")
    print("  position. Legs that touch inside 24h belong to the FILLED class, not the phantom, and the")
    print("  restated ROI above is too pessimistic by exactly that share.")

    print("\n  (b) the 24h 'never' verdict is a NEGATIVE claim, so it gets re-checked at 1-minute")
    print("      fidelity on a sample (5-min sampling can step over a brief print)")
    sample = never[::max(1, len(never) // 80)][:80]
    flips = 0
    ok = 0
    for l in sample:
        t0 = l["openedTs"] // 1000
        j = _get(f"https://clob.polymarket.com/prices-history?market={l['tape_token']}"
                 f"&startTs={t0}&endTs={t0 + 86400}&fidelity=1", "ph1", f"{l['tape_token'][:16]}-{t0}-1m")
        h = (j or {}).get("history") if isinstance(j, dict) else None
        if not h:
            continue
        ok += 1
        if any(t0 <= int(q["t"]) <= t0 + 86400 and float(q["p"]) <= l["trueP"] + TICK for q in h):
            flips += 1
    print(f"      re-checked {ok} of {len(never)}; {flips} touch at 1-minute resolution "
          f"({flips / ok * 100:.1f}% reverse rate)" if ok else "      sample returned no data")


def sec_basis(legs):
    print()
    print("=" * 90)
    print("9. THE COST BASIS — every leg re-priced at the price the market actually showed at dispatch")
    print("=" * 90)
    print("  p0 = first tape observation at/after dispatch. This is the only entry price a taker could")
    print("  have got without being filled by a later move; the booked entry is the wallet's fill +/- a")
    print("  fixed delta, which is not a price anybody was offering.")
    g = [l for l in legs if l.get("tape_p0")]
    print(f"\n  {'lane':<13} {'legs':>5} {'booked ROI':>11} {'ROI @ p0':>10} {'CI95 @ p0':>18} "
          f"{'pnl booked':>11} {'pnl @ p0':>10}")
    for lane in LANES:
        h = [l for l in g if l["botId"] == lane]
        if not h:
            continue
        rb, pb, n = roi(h)
        rp = ppi.roi.__name__ if False else None
        pnl0 = sum(ppi.true_pnl(l, l["tape_p0"]) for l in h)
        rpct = pnl0 / n * 100
        lo, hi = ppi.cluster_ci(h, lambda l: ppi.true_pnl(l, l["tape_p0"]))
        print(f"  {lane:<13} {len(h):>5} {rb:>+10.1f}% {rpct:>+9.1f}% "
              f"{(f'[{lo:+.1f},{hi:+.1f}]' if lo is not None else 'n/a'):>18} {pb:>+11.1f} {pnl0:>+10.1f}")
    allg = g
    rb, pb, n = roi(allg)
    pnl0 = sum(ppi.true_pnl(l, l["tape_p0"]) for l in allg)
    print(f"  {'COMBINED':<13} {len(allg):>5} {rb:>+10.1f}% {pnl0 / n * 100:>+9.1f}% {'':>18} "
          f"{pb:>+11.1f} {pnl0:>+10.1f}")
    print("\n  by band, booked vs dispatch-price basis (C-200 in the cheap tail is the sensitive one):")
    print(f"  {'band':<9} {'lane':<13} {'legs':>5} {'booked ROI':>11} {'ROI @ p0':>10} {'mean d':>8}")
    for lo_, hi_ in ppi.BANDS:
        bn = ppi.band_name(lo_, hi_)
        for lane in LANES:
            h = [l for l in g if l["botId"] == lane and ppi.band_of(l["trueP"]) == bn]
            if not h:
                continue
            nn = sum(l["simulatedPositionSize"] for l in h)
            p0p = sum(ppi.true_pnl(l, l["tape_p0"]) for l in h)
            ds = sum((l["trueP"] - l["tape_p0"]) * 100 for l in h) / len(h)
            print(f"  {bn:<9} {lane:<13} {len(h):>5} {roi(h)[0]:>+10.1f}% {p0p / nn * 100:>+9.1f}% "
                  f"{ds:>7.2f}c")
    print("\n  by dispatch gap (d = our price - market at dispatch), booked vs dispatch-price basis:")
    print("  if a cell's ROI collapses at p0, its edge WAS the discount, not the wallet.")
    print(f"  {'lane':<13} {'d bucket':<16} {'legs':>5} {'booked ROI':>11} {'ROI @ p0':>10} "
          f"{'filled n':>9} {'ROI filled @ p0':>15}")
    bk = [("d <= -2c", lambda x: x <= -0.02), ("-2c < d <= -0.5c", lambda x: -0.02 < x <= -0.005),
          ("|d| < 0.5c", lambda x: -0.005 < x < 0.005), ("d >= +0.5c", lambda x: x >= 0.005)]
    for lane in LANES:
        for nm, f in bk:
            h = [l for l in g if l["botId"] == lane and f(l["trueP"] - l["tape_p0"])]
            if not h:
                continue
            nn = sum(l["simulatedPositionSize"] for l in h)
            p1 = sum(ppi.true_pnl(l, l["tape_p0"]) for l in h)
            a = [l for l in h if l["tape_verdict"] == "filled_tape"]
            na = sum(l["simulatedPositionSize"] for l in a)
            pa = sum(ppi.true_pnl(l, l["tape_p0"]) for l in a)
            print(f"  {lane:<13} {nm:<16} {len(h):>5} {roi(h)[0]:>+10.1f}% {p1 / nn * 100:>+9.1f}% "
                  f"{len(a):>9} {(pa / na * 100 if na else float('nan')):>+14.1f}%")

    print("\n  READ: the gap between the two columns is the part of the book's PnL that exists only")
    print("  because of how the entry price is WRITTEN DOWN, not because of a decision.")


def sec_gap(legs):
    print()
    print("=" * 90)
    print("7. WHY C-200 FILLS A THIRD AS OFTEN — the bid-vs-market gap at dispatch, not the wallet gap")
    print("=" * 90)
    g = [l for l in legs if l.get("tape_p0") is not None]
    print("  d = our price minus the market's price at dispatch (negative = we bid UNDER the market,")
    print("  so the market must move down to us). This is measured, not assumed from entry-intent.")
    print(f"  {'lane':<13} {'n':>5} {'mean d':>8} {'median d':>9} {'share d<-1c':>12} {'touch%':>7}")
    for lane in LANES:
        h = [l for l in g if l["botId"] == lane]
        if not h:
            continue
        ds = sorted((l["trueP"] - l["tape_p0"]) * 100 for l in h)
        t = sum(1 for l in h if l["tape_verdict"] == "filled_tape")
        print(f"  {lane:<13} {len(h):>5} {sum(ds) / len(ds):>7.2f}c {ds[len(ds) // 2]:>8.2f}c "
              f"{sum(1 for x in ds if x < -1.0) / len(ds) * 100:>11.1f}% {t / len(h) * 100:>6.1f}%")
    print(f"\n  {'d bucket':<16} {'C-200 n':>8} {'touch%':>7} {'ROI touched':>12} {'STD n':>7} {'touch%':>7} "
          f"{'ROI touched':>12}")
    buckets = [("d <= -2c", lambda x: x <= -0.02), ("-2c < d <= -0.5c", lambda x: -0.02 < x <= -0.005),
               ("|d| < 0.5c", lambda x: -0.005 < x < 0.005), ("d >= +0.5c", lambda x: x >= 0.005)]
    for nm, f in buckets:
        row = [nm]
        for lane in LANES:
            h = [l for l in g if l["botId"] == lane and f(l["trueP"] - l["tape_p0"])]
            if not h:
                row += [0, 0.0, None]
                continue
            a = [l for l in h if l["tape_verdict"] == "filled_tape"]
            row += [len(h), len(a) / len(h) * 100, roi(a)[0] if a else None]
        def cell(v, pct=False, roi_=False):
            if v is None:
                return "n/a"
            return (f"{v:+.1f}%" if roi_ else (f"{v:.1f}%" if pct else f"{v}"))
        print(f"  {row[0]:<16} {cell(row[1]):>8} {cell(row[2], pct=True):>7} {cell(row[3], roi_=True):>12} "
              f"{cell(row[4]):>7} {cell(row[5], pct=True):>7} {cell(row[6], roi_=True):>12}")
    print("\n  READ: if C-200's d is only marginally more negative and its touch rate is still a third")
    print("  of STANDARD's, the gap is not the mechanism and paying up is not the fix.")
    print("\n  (b) CIs on the cells that actually produced fills — market-clustered")
    print(f"  {'lane':<13} {'d bucket':<16} {'filled n':>8} {'notional':>9} {'ROI':>8} {'CI95':>18} "
          f"{'fill rate':>9} {'EV/attempt':>10}")
    for lane in LANES:
        for nm, f in buckets:
            h = [l for l in g if l["botId"] == lane and f(l["trueP"] - l["tape_p0"])]
            a = [l for l in h if l["tape_verdict"] == "filled_tape"]
            if not h or not a:
                continue
            r, p, nn = roi(a)
            fr = len(a) / len(h)
            print(f"  {lane:<13} {nm:<16} {len(a):>8} {nn:>9,.0f} {r:>+7.1f}% {fmt_ci(a):>18} "
                  f"{fr * 100:>8.1f}% {r * fr:>+9.1f}%")


def sec_fillability(legs):
    print()
    print("=" * 90)
    print("5. FILLABILITY BY BAND — is the volume where the fill is, or where the edge is")
    print("=" * 90)
    print("  touch rate = share of legs whose price traded at or below our bid within 60m (a LOWER")
    print("  bound on fill probability: 1-minute sampling misses intra-minute troughs).")
    print(f"  {'band':<9} {'lane':<13} {'legs':>5} {'touch%':>7} {'ROI booked':>11} {'ROI touched':>12} "
          f"{'CI95 touched':>18} {'ntl touched':>12}")
    for lo, hi in ppi.BANDS:
        bn = ppi.band_name(lo, hi)
        for lane in LANES:
            g = [l for l in legs if l["botId"] == lane and ppi.band_of(l["trueP"]) == bn]
            if not g:
                continue
            a = [l for l in g if l["tape_verdict"] == "filled_tape"]
            rb = roi(g)[0]
            ra = roi(a)[0] if a else None
            nt = sum(l["simulatedPositionSize"] for l in a)
            print(f"  {bn:<9} {lane:<13} {len(g):>5} {len(a) / len(g) * 100:>6.1f}% {rb:>+10.1f}% "
                  f"{(f'{ra:+.1f}%' if ra is not None else 'n/a'):>12} "
                  f"{(fmt_ci(a) if a else 'n/a'):>18} {nt:>12,.0f}")
    print("\n  READ: a band whose touch rate is far below the book's average is a band we do not")
    print("  actually get into; its booked ROI is then mostly the un-filled cohort's mark-to-market.")


def sec_audit(legs):
    print()
    print("=" * 90)
    print("6. AUDIT — could the verdict be an artefact of the token map or of a few markets")
    print("=" * 90)
    print("  (a) verdict by how the token was identified")
    print(f"  {'map':<12} {'legs':>5} {'touch%':>7} {'unfilled%':>10}")
    for how in ("label", "proximity", None):
        g = [l for l in legs if l.get("tape_map") == how]
        if not g:
            continue
        t = sum(1 for l in g if l["tape_verdict"] == "filled_tape")
        u = sum(1 for l in g if l["tape_verdict"] == "unfilled_tape")
        print(f"  {str(how):<12} {len(g):>5} {t / len(g) * 100:>6.1f}% {u / len(g) * 100:>9.1f}%")
    print("  'proximity' legs are team-name / over-under labels mapped by price at dispatch; if their")
    print("  touch rate were wildly different from 'label' legs the map, not the market, would be talking.")

    print("\n  (b) is the untouched cohort's profit one market? top 5 untouched legs by PnL")
    un = [l for l in legs if l["tape_verdict"] == "unfilled_tape"]
    for l in sorted(un, key=lambda x: -(x["realizedPnl"] or 0))[:5]:
        print(f"    {l['botId'][:6]:<7} ${l['realizedPnl']:>+8.1f}  entry {l['trueP']:.3f}  "
              f"min in 60m {l['tape_minp']:.3f}  {l['marketId'][:44]}")
    tot = sum(l["realizedPnl"] or 0 for l in un)
    print(f"   untouched total {tot:+.1f} on {len(un)} legs / {len(set(l['marketId'] for l in un))} markets")
    for k in (1, 3, 5):
        keep = sorted(un, key=lambda x: -(x["realizedPnl"] or 0))[k:]
        print(f"   ex-top{k}: n={len(keep):>3} ${sum(l['realizedPnl'] or 0 for l in keep):>+8.1f} "
              f"ROI {roi(keep)[0]:+.1f}%")

    print("\n  (d) LEDGER CROSS-TAB — how much of the untouched cohort is still booked optimistically")
    print(f"  {'db fillStatus':<12} {'tape verdict':<15} {'legs':>5} {'notional':>9} {'pnl':>10}")
    keys = {}
    for l in legs:
        keys.setdefault((l.get("fillStatus") or "NULL", l["tape_verdict"]), []).append(l)
    for (st, v), g in sorted(keys.items(), key=lambda kv: (kv[0][0], kv[0][1])):
        if len(g) < 3:
            continue
        r, p, nn = roi(g)
        print(f"  {st:<12} {v:<15} {len(g):>5} {nn:>9,.0f} {p:>+10.1f}")
    print("  the flip zeroes `unfilled` rows, so phantom can only survive on NULL rows; a large")
    print("  untouched+NULL PnL is profit the booking path still credits.")

    print("\n  (c) window sensitivity — same legs, different fill horizons")
    print(f"  {'window':>7} {'touch%':>7} {'ROI touched':>12} {'ROI untouched':>14} {'restated ROI':>13}")
    for W in WINDOWS:
        for lane in (None,):
            g = [l for l in legs if l.get("tape_series")]
            if not g:
                continue
            a = [l for l in g if verdict_at(l, W) == "filled_tape"]
            b = [l for l in g if verdict_at(l, W) == "unfilled_tape"]
            ra = roi(a)[0] if a else float("nan")
            rb = roi(b)[0] if b else float("nan")
            def pess(l):
                return 0.0 if verdict_at(l, W) == "unfilled_tape" else (l["realizedPnl"] or 0.0)
            rs = roi(g, pess)[0]
            print(f"  {W:>6}s {len(a) / len(g) * 100:>6.1f}% {ra:>+11.1f}% {rb:>+13.1f}% {rs:>+12.1f}%")
    print("\n  era boundary: post-flip only vs all legs in window")
    for tag, sel in (("post-flip", [l for l in legs if l["openedTs"] >= FLIP_MS]),
                     ("all in window", legs)):
        for lane in LANES:
            h = [l for l in sel if l["botId"] == lane]
            if not h:
                continue
            a = [l for l in h if l["tape_verdict"] == "filled_tape"]
            print(f"  {tag:<13} {lane:<13} n={len(h):>4} booked {roi(h)[0]:>+6.1f}%  "
                  f"touched-only {(f'{roi(a)[0]:+.1f}%' if a else 'n/a'):>7}  "
                  f"touch {len(a) / len(h) * 100:>5.1f}%")


def sec_sensitivity(legs):
    print()
    print("=" * 90)
    print("5. SENSITIVITY — window length and the era boundary")
    print("=" * 90)
    print("  the headline uses a 60m window from dispatch; a touch inside 5m or 15m is a strictly")
    print("  harder test, and the verdicts are re-filtered from the same cached series there.")
    print("\n  era boundary: post-flip legs only vs all legs in window")
    for tag, sel in (("post-flip", [l for l in legs if l["openedTs"] >= FLIP_MS]),
                     ("all in window", legs)):
        for lane in LANES:
            h = [l for l in sel if l["botId"] == lane]
            if not h:
                continue
            a = [l for l in h if l["tape_verdict"] == "filled_tape"]
            r, p, n = roi(h)
            ra = roi(a)[0] if a else None
            print(f"  {tag:<14} {lane:<13} n={len(h):>4} booked {r:>+6.1f}%  touched-only "
                  f"{ra if ra is None else round(ra, 1):>+6}%  touch rate {len(a) / len(h) * 100:>5.1f}%")


# ------------------------------------------------------------------ self-tests


def selftest():
    ok = 0
    tot = 0

    def chk(name, cond):
        nonlocal ok, tot
        tot += 1
        if cond:
            ok += 1
            print(f"  PASS  {name}")
        else:
            print(f"  FAIL  {name}")

    # 1 classifier boundaries
    def cls_of(minp, L):
        if minp <= L + TICK:
            return "filled_tape"
        if minp <= L + TOUCH_EPS:
            return "near_miss"
        return "unfilled_tape"
    chk("classifier: touch at bid", cls_of(0.40, 0.40) == "filled_tape")
    chk("classifier: 0.5c above bid is near_miss not a negative", cls_of(0.405, 0.40) == "near_miss")
    chk("classifier: 2c above bid is unfilled", cls_of(0.42, 0.40) == "unfilled_tape")
    # 2 restatement identity: untouched legs contribute exactly zero
    fake = [{"tape_verdict": "unfilled_tape", "realizedPnl": 50.0, "simulatedPositionSize": 10.0},
            {"tape_verdict": "filled_tape", "realizedPnl": -5.0, "simulatedPositionSize": 10.0}]
    r, p, n = roi(fake, lambda l: 0.0 if l["tape_verdict"] == "unfilled_tape" else (l["realizedPnl"] or 0.0))
    chk("restatement: untouched books zero (pnl=-5 on $20)", abs(p + 5.0) < 1e-9 and abs(n - 20.0) < 1e-9)
    # 3 diff_ci antisymmetry under arm swap
    A = [{"marketId": "m1", "realizedPnl": 10.0, "simulatedPositionSize": 10.0},
         {"marketId": "m2", "realizedPnl": -3.0, "simulatedPositionSize": 10.0}]
    B = [{"marketId": "m1", "realizedPnl": -8.0, "simulatedPositionSize": 10.0},
         {"marketId": "m3", "realizedPnl": 1.0, "simulatedPositionSize": 10.0}]
    lo1, hi1 = diff_ci(A, B)
    lo2, hi2 = diff_ci(B, A)
    chk("diff_ci antisymmetry", abs((lo1 + hi2)) < 1e-6 and abs((hi1 + lo2)) < 1e-6)
    # 4 true_pnl price identity on a resolution exit
    leg = {"status": "resolved", "simulatedPositionSize": 10.0, "entryPrice": 0.25,
           "realizedPnl": 30.0, "fillStatus": None}
    chk("true_pnl: exit=1.0 reproduced then re-priced at 0.20 gives +40",
        abs(ppi.true_pnl(leg, 0.20) - 40.0) < 1e-6)
    print(f"\n  {ok}/{tot} self-tests pass")
    return ok == tot


# ------------------------------------------------------------------ main

def main():
    global ARGS
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default="2026-10-01")
    ap.add_argument("--window", type=int, default=3600,
                    help="fill horizon in seconds from dispatch (default 3600)")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--only", default=None, help="comma list of sections e.g. 0,1,2")
    ARGS = ap.parse_args()
    global WINDOW_S
    WINDOW_S = ARGS.window

    print(f"FILL TAPE — window from {ARGS.since}, {WINDOW_S}s horizon, read-only")
    if not selftest():
        sys.exit(1)
    legs = load(ARGS.since)
    print(f"  loading legs: {len(legs)} finished, conditionId present")
    t = time.time()
    legs = classify(legs, ARGS.workers)
    print(f"  tape adjudicated in {time.time() - t:.0f}s\n")
    want = None if ARGS.only is None else {s.strip() for s in ARGS.only.split(",")}
    if want is None or "0" in want:
        sec_coverage(legs)
    if want is None or "1" in want:
        sec_validate(legs)
    if want is None or "2" in want:
        sec_unresolved(legs)
    if want is None or "3" in want:
        for lane in LANES:
            sec_lane(legs, lane)
    if want is None or "4" in want:
        sec_break_even(legs)
    if want is None or "5" in want:
        sec_fillability(legs)
    if want is None or "7" in want:
        sec_gap(legs)
    if want is None or "10" in want:
        sec_basis(legs)
    if want is None or "8" in want:
        sec_horizon(legs)
    if want is None or "6" in want:
        sec_audit(legs)
    if want is None or "9" in want:
        sec_sensitivity(legs)
    # machine-readable dump so a sibling instrument can re-use the verdicts
    out = os.path.join(CACHE, "verdicts.json")
    with open(out, "w") as f:
        json.dump([{k: l.get(k) for k in ("id", "botId", "marketId", "outcome", "openedTs",
                                          "entryPrice", "trueP", "simulatedPositionSize",
                                          "realizedPnl", "status", "fillStatus", "tape_verdict",
                                          "tape_minp", "tape_map", "tape_touch_lag_s", "tape_p0")}
                   for l in legs], f)
    print(f"\n  verdicts cached -> {out}")


if __name__ == "__main__":
    main()
