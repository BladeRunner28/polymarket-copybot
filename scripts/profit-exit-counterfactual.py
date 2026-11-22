#!/usr/bin/env python3
"""
EXIT COUNTERFACTUAL — the book's entire loss sits on the 63 legs the exit closed. Is the exit wrong?

WHY THIS EXISTS
---------------
Every band table in the last month splits legs by price, tenor, clip or wallet. None of them splits
by WHO CLOSED THE POSITION. Today's clip-tier cut shows why that is the missing axis:

    resolved (market decided the leg)  495 legs  $8,853  +4.6%
    closed   (our stale-exit closed it) 63 legs  $2,455  -22.7%

That is not evidence the exit is wrong. The exit only fires on legs that have already gone against
us (`v53 adverse-only`: staleExitHours old AND winMove <= staleExitAdverseMove), so the closed class
is selected for losers by construction. The honest question is the COUNTERFACTUAL, and the venue's
minute tape answers it retroactively: for each leg our exit closed, what was the same position worth
at +24h, at +7d, and at resolution?

  * if holding was worse  -> the exit is doing its job; the loss is ADMISSION and the fix is upstream.
  * if holding was better -> the exit is selling the bottom of a convex bet; the fix is the exit.

BASIS
-----
population : PaperTrade isDemo=0, status='closed' at v68+ (deduped first leg per bot|wallet|market|outcome).
cost       : simulatedPositionSize = dollars at risk. Entry = the BOOKED price = what we paid.
arms       : actual   = the booked realizedPnl.
             hold_24h = the same dollars at risk, exited at the last tape print <= closedAt + 24h.
             hold_7d  = the same, at the last print <= closedAt + 7d.
             resolve  = the same, at the venue's own outcome (1.0 / 0.0) when the market has one.
             pnl_arm  = ntl * (p_arm / entry - 1)   [dollars at risk held constant, share count implied]
delta      : hold - actual, positive = the exit cost us money.
CIs        : one leg per market here (63 markets / 63 legs), so a market-clustered bootstrap is a
             plain bootstrap over legs; 2000 draws.
tape       : clob.polymarket.com/prices-history, keyless, retroactive, fidelity 5 (24h) / 60 (7d),
             cached under data/fill-tape-cache by scripts/profit-fill-tape.py's reader.
READ-ONLY  : DB mode=ro. No RuleSet read/write, no prisma write, no apply-v*.

RUN
  python3 scripts/profit-exit-counterfactual.py
  python3 scripts/profit-exit-counterfactual.py --selftest
  python3 scripts/profit-exit-counterfactual.py --no-fetch     (cache only; reports coverage)
"""
import argparse
import importlib.util
import json
import os
import random
import sqlite3
import sys
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DB = os.environ.get("COPYBOT_DB") or os.path.join(ROOT, "prisma", "dev.db")
if DB.startswith("file:") and "mode=ro" not in DB:
    DB = DB + "?mode=ro"
FAIL = []


def _mod(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(m)
    return m


ppi = _mod("ppi", os.path.join(HERE, "profit-postfix-integrity.py"))
ft = _mod("ft", os.path.join(HERE, "profit-fill-tape.py"))

HOUR = 3600
DAY = 86400


def chk(label, ok, detail=""):
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}" + (f" — {detail}" if detail else ""))
    if not ok:
        FAIL.append(label)
    return ok


def con():
    c = sqlite3.connect(DB, uri=DB.startswith("file:"))
    c.row_factory = sqlite3.Row
    return c


def load(min_rule):
    c = con()
    rows = c.execute(
        """select p.id, p.botId bot, p.walletAddress wallet, p.marketId market, p.outcome,
                  p.entryPrice px, p.simulatedPositionSize ntl, p.realizedPnl pnl,
                  p.openedAt ms, p.closedAt cms, p.status, o.conditionId cid
             from PaperTrade p
             join DecisionJournal j on j.id = p.decisionJournalId
             left join ObservedTrade o on o.id = j.observedTradeId
            where p.isDemo = 0 and p.status = 'closed' and p.realizedPnl is not null
              and j.ruleSetVersion >= ?""",
        (min_rule,),
    ).fetchall()
    seen, out = set(), []
    for r in rows:
        if not r["px"] or r["px"] <= 0 or not r["ntl"] or r["ntl"] <= 0 or not r["cms"]:
            continue
        k = (r["bot"], r["wallet"], r["market"], r["outcome"])
        if k in seen:
            continue
        seen.add(k)
        out.append(dict(id=r["id"], bot=r["bot"], wallet=r["wallet"], market=r["market"],
                        outcome=r["outcome"], px=float(r["px"]), ntl=float(r["ntl"]),
                        pnl=float(r["pnl"]), ms=r["ms"], cms=r["cms"], cid=r["cid"]))
    return out


def reasons():
    """id -> close reason text, from the exit's own log (data/close-reasons.jsonl)."""
    p = os.path.join(ROOT, "data", "close-reasons.jsonl")
    out = {}
    if not os.path.exists(p):
        return out
    with open(p, "r") as f:
        for line in f:
            try:
                j = json.loads(line)
            except Exception:
                continue
            if j.get("id"):
                out[j["id"]] = str(j.get("reason") or "")
    return out


def market(cid):
    """conditionId -> (tokens[token_id,outcome,winner], market_closed_flag)."""
    if not cid:
        return None
    j = ft._get(f"https://clob.polymarket.com/markets/{cid}", "cm", cid[:24])
    if not isinstance(j, dict) or j.get("__error__") or "tokens" not in j:
        return None
    toks = [dict(token_id=t["token_id"], outcome=str(t.get("outcome", "")),
                 winner=t.get("winner")) for t in j["tokens"]]
    return toks


def series(token, t0_s, win, fidelity=5):
    key = f"{token[:16]}-{t0_s}-f{fidelity}"
    j = ft._get(f"https://clob.polymarket.com/prices-history?market={token}"
                f"&startTs={t0_s}&endTs={t0_s + win}&fidelity={fidelity}", "ph", key)
    if not isinstance(j, dict) or j.get("__error__"):
        return None
    h = j.get("history")
    if not isinstance(h, list):
        return None
    return [(int(p["t"]), float(p["p"])) for p in h if "t" in p and "p" in p]


def price_at(s, t_s):
    """Last print at or before t_s (carry-forward), else None."""
    best = None
    for t, p in s:
        if t <= t_s:
            best = p
        else:
            break
    return best


def token_for(leg, toks):
    want = str(leg["outcome"] or "").strip().lower()
    ex = [t for t in toks if str(t["outcome"]).strip().lower() == want]
    if len(ex) == 1:
        return ex[0], "label"
    # proximity disambiguation on the tape at open, same rule as profit-fill-tape.py
    cand = []
    for t in toks:
        s = series(t["token_id"], leg["ms"] // 1000, 3600, fidelity=5)
        if not s:
            continue
        p0 = ft.early_price(s, leg["ms"] // 1000)
        if p0 is not None:
            cand.append((abs(p0 - leg["px"]), t, p0))
    if len(cand) < 2:
        return None, "no_candidate"
    cand.sort(key=lambda x: x[0])
    if cand[1][0] - cand[0][0] < 0.02:
        return None, "ambiguous"
    return cand[0][1], "proximity"


def one(leg, allow_fetch=True):
    toks = market(leg["cid"]) if allow_fetch else None
    if not toks:
        return dict(leg, ok=False, why="no_market")
    tk, how = token_for(leg, toks)
    if tk is None:
        return dict(leg, ok=False, why=how)
    c_s = leg["cms"] // 1000
    s = series(tk["token_id"], c_s, 8 * DAY, fidelity=60)
    if not s:
        s = series(tk["token_id"], c_s, 8 * DAY, fidelity=5)
    if not s:
        return dict(leg, ok=False, why="no_tape")
    p24 = price_at(s, c_s + DAY)
    p7d = price_at(s, c_s + 7 * DAY)
    w = tk.get("winner")
    resolved = w is not None and str(w).strip() != ""
    pres = None
    if resolved:
        win = str(w).strip().lower() in ("true", "1", "yes")
        pres = 1.0 if win else 0.0
    n, e = leg["ntl"], leg["px"]
    arm = lambda p: (n * (p / e - 1.0)) if p is not None else None
    return dict(leg, ok=True, how=how, token=tk["token_id"], p24=p24, p7d=p7d,
                pres=pres, resolved=resolved,
                a24=arm(p24), a7=arm(p7d), ares=arm(pres) if pres is not None else None,
                last_p=s[-1][1], last_t=s[-1][0])


def scope_load(min_rule, bot):
    """Settled legs for one bot: what the exit rule actually had to work on."""
    c = con()
    rows = c.execute(
        """select p.id, p.botId bot, p.walletAddress wallet, p.marketId market, p.outcome,
                  p.entryPrice px, p.simulatedPositionSize ntl, p.realizedPnl pnl,
                  p.openedAt ms, p.closedAt cms, p.resolvedAt rms, p.status,
                  o.conditionId cid
             from PaperTrade p
             join DecisionJournal j on j.id = p.decisionJournalId
             left join ObservedTrade o on o.id = j.observedTradeId
            where p.isDemo = 0 and p.status in ('closed','resolved')
              and p.realizedPnl is not null and p.botId = ? and j.ruleSetVersion >= ?""",
        (bot, min_rule),
    ).fetchall()
    seen, out = set(), []
    for r in rows:
        if not r["px"] or r["px"] <= 0 or not r["ntl"] or r["ntl"] <= 0:
            continue
        k = (r["bot"], r["wallet"], r["market"], r["outcome"])
        if k in seen:
            continue
        seen.add(k)
        out.append(dict(id=r["id"], bot=r["bot"], wallet=r["wallet"], market=r["market"],
                        outcome=r["outcome"], px=float(r["px"]), ntl=float(r["ntl"]),
                        pnl=float(r["pnl"]), ms=r["ms"], cms=r["cms"], cid=r["cid"],
                        end=r["rms"] or r["cms"] or r["ms"]))
    return out


def replay(leg, allow_fetch=True, hours=24, adverse=0.15):
    """Simulate the v53 rule: at entry+hours, if the price is >=adverse under our entry, exit there."""
    toks = market(leg["cid"]) if allow_fetch else None
    if not toks:
        return dict(leg, ok=False, why="no_market")
    tk, how = token_for(leg, toks)
    if tk is None:
        return dict(leg, ok=False, why=how)
    t0 = leg["ms"] // 1000
    s = series(tk["token_id"], t0, (hours + 6) * HOUR, fidelity=5)
    if not s:
        res = series(tk["token_id"], t0, 8 * DAY, fidelity=60)
        s = res
    if not s:
        return dict(leg, ok=False, why="no_tape")
    p = price_at(s, t0 + hours * HOUR)
    if p is None:
        return dict(leg, ok=False, why="no_print_at_mark")
    # THE RULE CANNOT CLOSE A POSITION THAT IS ALREADY GONE. A leg that resolved or was closed
    # before the mark keeps its booked result. Without this the replay fires on 199 of 410
    # settled C-200 legs (49%) instead of the 63 (15%) the live rule actually closed, because it
    # prices short-TTR legs on a tape that is already post-resolution.
    if leg.get("end") and leg["end"] <= leg["ms"] + hours * HOUR * 1000:
        return dict(leg, ok=True, how=how, p=p, fired=False, sim=leg["pnl"], gone=True)
    fired = p <= leg["px"] * (1.0 - adverse)
    sim = leg["ntl"] * (p / leg["px"] - 1.0) if fired else leg["pnl"]
    return dict(leg, ok=True, how=how, p=p, fired=fired, sim=sim)


def roi(ls, key):
    n = sum(l["ntl"] for l in ls if l.get(key) is not None)
    p = sum(l[key] for l in ls if l.get(key) is not None)
    return (p / n * 100.0 if n else None), p, n


def boot_delta(ls, key, n=2000, seed=13):
    """Bootstrap CI on (arm - actual) per dollar at risk."""
    rows = [l for l in ls if l.get(key) is not None]
    if len(rows) < 5:
        return (None, None)
    rnd = random.Random(seed)
    out = []
    for _ in range(n):
        sp = sn = 0.0
        for _ in range(len(rows)):
            l = rows[rnd.randrange(len(rows))]
            sp += l[key] - l["pnl"]
            sn += l["ntl"]
        if sn > 0:
            out.append(sp / sn * 100.0)
    out.sort()
    return (out[int(0.025 * len(out))], out[int(0.975 * len(out)) - 1])


def boot_pair(ls, n=2000, seed=17):
    """Bootstrap CI on mean (sim - booked) per dollar at risk."""
    rows = [l for l in ls if l.get("sim") is not None]
    if len(rows) < 5:
        return (None, None)
    rnd = random.Random(seed)
    out = []
    for _ in range(n):
        sp = sn = 0.0
        for _ in range(len(rows)):
            l = rows[rnd.randrange(len(rows))]
            sp += l["sim"] - l["pnl"]
            sn += l["ntl"]
        if sn > 0:
            out.append(sp / sn * 100.0)
    out.sort()
    return (out[int(0.025 * len(out))], out[int(0.975 * len(out)) - 1])


def money(v):
    return f"{v:+,.2f}" if v is not None else "n/a"

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-rule", type=int, default=68)
    ap.add_argument("--no-fetch", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()

    legs = load(a.min_rule)
    rs = reasons()
    for l in legs:
        l["reason"] = rs.get(l["id"], "")
    print(f"\nEXIT COUNTERFACTUAL — {len(legs)} early-closed legs, {len(set(l['market'] for l in legs))} markets, v{a.min_rule}+")
    print("  fetching the venue tape after each exit (cached) ...")
    with ThreadPoolExecutor(max_workers=6) as ex:
        legs = list(ex.map(lambda l: one(l, allow_fetch=not a.no_fetch), legs))
    ok = [l for l in legs if l["ok"]]
    cov = len(ok) / max(len(legs), 1)
    print(f"  priced on the tape: {len(ok)}/{len(legs)} = {cov*100:.0f}%\n")
    if not ok:
        print("  NO TAPE — nothing to read.")
        return 1

    # ---------------------------------------------------------------- S1
    print("S1  ACTUAL vs HOLD ARMS  (dollars at risk held constant; positive delta = the exit cost us)")
    act_roi, act_pnl, act_n = roi(ok, "pnl")
    print(f"  actual exit          ${act_n:>8,.0f}  {money(act_pnl):>10}  {act_roi:+.1f}%")
    for key, nm in (("a24", "hold +24h"), ("a7", "hold +7d"), ("ares", "hold to resolution")):
        r, p, n = roi(ok, key)
        lo, hi = boot_delta(ok, key)
        cnt = sum(1 for l in ok if l.get(key) is not None)
        cig = f"[{lo:+.1f},{hi:+.1f}]" if lo is not None else "[n/a]"
        print(f"  {nm:<20} ${n:>8,.0f}  {money(p):>10}  {r:+.1f}%  delta CI {cig:>16}  n={cnt}")
    print()

    # ---------------------------------------------------------------- S2
    print("S2  BY PRICE BAND  (the cheap tail is where a %-based exit is a tick-based exit)")
    for nm, sel in (("px < 0.20", lambda l: l["px"] < 0.20),
                    ("0.20-0.40", lambda l: 0.20 <= l["px"] < 0.40),
                    ("0.40-0.60", lambda l: 0.40 <= l["px"] < 0.60),
                    ("px >= 0.60", lambda l: l["px"] >= 0.60)):
        sub = [l for l in ok if sel(l)]
        if not sub:
            continue
        ar, ap, an = roi(sub, "pnl")
        r7, p7, n7 = roi(sub, "a7")
        lo, hi = boot_delta(sub, "a7")
        rr, pr, nr = roi(sub, "ares")
        cig = f"[{lo:+.1f},{hi:+.1f}]" if lo is not None else "[n/a]"
        print(f"  {nm:<10} n={len(sub):>3} ${an:>7,.0f}  actual {ap:>8,.2f} ({ar:+.1f}%)  "
              f"+7d {p7:>8,.2f} ({r7:+.1f}%) deltaCI {cig:>16}  "
              f"resolve {pr:>8,.2f} ({rr if rr is not None else 0:+.1f}%)")
    print()

    # ---------------------------------------------------------------- S3
    print("S3  BY EXIT REASON")
    for nm, sel in (("adverse (tier1)", lambda l: "adverse" in l["reason"]),
                    ("hard max-age", lambda l: "hard" in l["reason"] or "max-age" in l["reason"]),
                    ("other/unknown", lambda l: "adverse" not in l["reason"]
                     and "hard" not in l["reason"] and "max-age" not in l["reason"])):
        sub = [l for l in ok if sel(l)]
        if not sub:
            continue
        ar, ap, an = roi(sub, "pnl")
        r7, p7, n7 = roi(sub, "a7")
        lo, hi = boot_delta(sub, "a7")
        cig = f"[{lo:+.1f},{hi:+.1f}]" if lo is not None else "[n/a]"
        print(f"  {nm:<16} n={len(sub):>3} ${an:>7,.0f}  actual {ar:+.1f}%  "
              f"+7d {r7 if r7 is not None else 0:+.1f}%  deltaCI {cig}")
    print()

    # ---------------------------------------------------------------- S4
    print("S4  HOW MANY LEGS THE TAPE SAYS WE SOLD A WINNER")
    recov = [l for l in ok if l.get("p7d") is not None and l["p7d"] > l["px"]]
    worse = [l for l in ok if l.get("p7d") is not None and l["p7d"] < l["px"]]
    print(f"  price back above our entry by +7d: {len(recov)} of {len(recov)+len(worse)} priced legs "
          f"({len(recov)/max(len(recov)+len(worse),1)*100:.0f}%)")
    if recov:
        r7, p7, n7 = roi(recov, "a7")
        ar, ap, an = roi(recov, "pnl")
        print(f"    those legs: actual {ap:+.2f} ({ar:+.1f}%) vs +7d {p7:+.2f} ({r7:+.1f}%)  "
              f"= {p7-ap:+.2f} left on the table")
    print()

    # ---------------------------------------------------------------- S5
    print("S5  RESOLUTION ARM ONLY (venue-decided markets, no tape interpretation)")
    res = [l for l in ok if l.get("ares") is not None]
    if res:
        ar, ap, an = roi(res, "pnl")
        rr, rp, rn = roi(res, "ares")
        lo, hi = boot_delta(res, "ares")
        cig = f"[{lo:+.1f},{hi:+.1f}]" if lo is not None else "[n/a]"
        won = sum(1 for l in res if l["pres"] == 1.0)
        print(f"  n={len(res)} ${an:,.0f}  actual {ap:+.2f} ({ar:+.1f}%)  "
              f"hold-to-resolution {rp:+.2f} ({rr:+.1f}%)  deltaCI {cig}  "
              f"(held outcome won {won}/{len(res)})")
        hit_bk = sum(l["px"] for l in res) / len(res)
        print(f"  break-even hit rate on this cohort = mean price {hit_bk*100:.1f}%; "
              f"actual {won/len(res)*100:.1f}%")
    print()

    # ---------------------------------------------------------------- S6
    print("S6  CONTROLS")
    allres = con().execute(
        """select count(*) n, sum(p.simulatedPositionSize) c, sum(p.realizedPnl) p
             from PaperTrade p join DecisionJournal j on j.id = p.decisionJournalId
            where p.isDemo = 0 and p.status = 'resolved' and p.realizedPnl is not null
              and j.ruleSetVersion >= ?""", (a.min_rule,)).fetchone()
    print(f"  legs the MARKET closed (resolved, not deduped): n={allres['n']} "
          f"${allres['c']:,.0f} {money(allres['p'])} "
          f"({allres['p']/allres['c']*100:+.1f}%)")
    print(f"  legs OUR exit closed: n={len(ok)} ${act_n:,.0f} {money(act_pnl)} ({act_roi:+.1f}%)")
    print(f"  selection is the whole difference — the arms above, not this line, decide the rule.")
    print()

    # ---------------------------------------------------------------- S7
    print("S7  THE RULE, REPLAYED ON THE LANE THE RULE CANNOT REACH (STANDARD)")
    print("    v53 adverse-only exit = close when age >= 24h AND move <= -15% of entry.")
    print("    Replay: price the leg at entry+24h; if it is 15% under our entry, exit there,")
    print("    else keep the booked result (which for STANDARD IS the hold, resolution/dead-slug only).")
    scope_rows = []
    for nm, bot in (("BANKROLL_200 (has the rule)", "BANKROLL_200"),
                    ("STANDARD (no rule)", "STANDARD")):
        ls = scope_load(a.min_rule, bot)
        with ThreadPoolExecutor(max_workers=6) as ex:
            ls = list(ex.map(lambda l: replay(l, allow_fetch=not a.no_fetch), ls))
        good = [l for l in ls if l["ok"]]
        if not good:
            print(f"  {nm:<28} no priced legs")
            continue
        cost = sum(l["ntl"] for l in good)
        act = sum(l["pnl"] for l in good)
        sim = sum(l["sim"] for l in good)
        fired = [l for l in good if l["fired"]]
        d = sim - act
        lo, hi = boot_pair(good)
        cig = f"[{lo:+.1f},{hi:+.1f}]" if lo is not None else "[n/a]"
        print(f"  {nm:<28} n={len(good):>4} ${cost:>7,.0f}  actual {act:+8,.2f}  "
              f"rule {sim:+8,.2f}  delta {d:+8,.2f} ({d/cost*100:+5.1f}%) CI {cig:>16}  "
              f"fired {len(fired)}/{len(good)}")
        ex3 = sorted(good, key=lambda l: -(l["sim"] - l["pnl"]))[3:]
        d3 = sum(l["sim"] - l["pnl"] for l in ex3)
        print(f"  {'':<28} ex-top-3 delta {d3:+.2f}   coverage {len(good)}/{len(ls)}")
        scope_rows.append((bot, len(good), cost, act, sim, d))
    print()

    # ---------------------------------------------------------------- S8
    print("S8  SELF-CHECKS")
    chk("every priced leg has a token and a tape point", all(l["token"] and l["last_p"] is not None for l in ok))
    chk("dedupe: one leg per (bot,wallet,market,outcome)",
        len(legs) == len(set((l['bot'], l['wallet'], l['market'], l['outcome']) for l in legs)))
    l = ok[0]
    chk("arm arithmetic reproduces the booked PnL when the arm price is our exit price",
        abs((l["ntl"] * ((l["px"] * (1 + l["pnl"] / l["ntl"])) / l["px"] - 1)) - l["pnl"]) < 1e-6)
    chk("price_at carries forward, never looks ahead",
        price_at([(0, 0.5), (10, 0.4), (20, 0.3)], 15) == 0.4)
    chk("coverage is high enough to read (>=70%)", cov >= 0.70, f"{cov*100:.0f}%")
    print()
    print(f"  {'ALL CHECKS PASS' if not FAIL else 'FAILED: ' + ', '.join(FAIL)}")
    return 1 if FAIL else 0


def selftest():
    print("\nSELF-TEST")
    chk("+24h arm on a 0.20 entry at 0.25 is +25%",
        abs(100 * (0.25 / 0.20 - 1) - 25) < 1e-9)
    chk("resolution arm on a loss is -100%", abs(100 * (0.0 / 0.20 - 1) + 100) < 1e-9)
    chk("carry-forward picks the last print at or before t", price_at([(0, .5), (5, .2)], 9) == .2)
    chk("carry-forward with no prior print is None", price_at([(50, .2)], 9) is None)
    chk("winner string parsing", (str("true").lower() in ("true", "1", "yes")) is True)
    print(f"  {'ALL CHECKS PASS' if not FAIL else 'FAILED: ' + ', '.join(FAIL)}")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
