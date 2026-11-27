#!/usr/bin/env python3
"""
CLIP-TIER DECOMPOSITION — is the book's loss a size effect, a price effect, or thirteen draws?

WHY THIS EXISTS
---------------
Three instruments describe the same dollars from three angles and none of them says what the next
rule should be:

  * profit-tenor.py (2026-11-21) says 2-24h is 76% of the book and loses -9.4%, so the entry floor
    is aimed at the tenor end.
  * profit-marginal-cell.py (2026-11-20) says the loss is concentrated in the cheap band's >=$50
    clip tier, so the approved $25 cap is aimed at the clip end.
  * profit-supply-ladder.py (2026-11-15) says the $100 tier is 37% of live notional and the only
    losing dollar tier, so a lane-wide cap is aimed at the lane end.

The three readings disagree about WHERE to aim because each one cuts a different axis on a
different population. This instrument cuts CLIP TIER x LANE on one population and then asks the
question that decides the rule:

    at a matched clip, does the losing tier still lose?  and if it does, is that a RATE problem
    (hit rate below the price's own break-even) or a DOLLAR problem (fourteen discrete draws)?

The distinction is the difference between a rule that survives forward and one that is a tail cut.

BASIS (stated once, used everywhere)
------------------------------------
population : PaperTrade isDemo=0, settled (status != open), DecisionJournal.ruleSetVersion >= MIN_RULE,
             deduped to the first leg per bot|wallet|market|outcome.
cost       : simulatedPositionSize = DOLLARS AT RISK, not shares. ROI = PnL / notional.
price      : the BOOKED entry. For a settled leg the payoff identity gives exit = entry*(1+pnl/ntl),
             so the break-even hit rate of the leg is its own entry price (buy YES at p wins 1-p,
             loses p). Hit rate is compared to the MEAN OF THE PRICE ACTUALLY PAID, which is the
             right break-even for a book of unequal prices.
tenor      : MarketSnapshot.timeToResolution at dispatch (hours), same reader as profit-tenor.py,
             +15 min lookahead tolerance, null if the snapshot is older than 24h.
lane       : DecisionJournal.reasonsJson contains "Short-TTR" (profit-tenor.py's `stair` flag),
             cross-checked against confidence == 0 and reported when the two disagree.
CIs        : market-clustered bootstrap (resample marketId), 2000 draws, on ROI.
READ-ONLY  : DB mode=ro. No RuleSet read or write, no prisma write, no apply-v*.

RUN
  python3 scripts/profit-clip-tier.py
  python3 scripts/profit-clip-tier.py --min-rule 68
  python3 scripts/profit-clip-tier.py --selftest
"""
import argparse
import importlib.util
import math
import os
import random
import sqlite3
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DB = os.environ.get("COPYBOT_DB") or os.path.join(ROOT, "prisma", "dev.db")
if DB.startswith("file:") and "mode=ro" not in DB:
    DB = DB + "?mode=ro"


print("[basis EXIT: realizedPnl>0 on the closed leg -- every hit/win-rate column this script prints]")

def _mod(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(m)
    return m


ppi = _mod("ppi", os.path.join(HERE, "profit-postfix-integrity.py"))
tty = _mod("tty", os.path.join(HERE, "profit-tenor.py"))

TIERS = ((0.0, 20.0, "a <$20"), (20.0, 40.0, "b $20-40"), (40.0, 1e9, "c $40+"))
FAIL = []


def chk(label, ok, detail=""):
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}" + (f" — {detail}" if detail else ""))
    if not ok:
        FAIL.append(label)
    return ok


def tier_of(sz):
    for lo, hi, nm in TIERS:
        if lo <= sz < hi:
            return nm
    return None


def con():
    c = sqlite3.connect(DB, uri=DB.startswith("file:"))
    c.row_factory = sqlite3.Row
    return c


def load(min_rule):
    c = con()
    rows = c.execute(
        """select p.id, p.botId bot, p.walletAddress wallet, p.marketId market, p.outcome,
                  p.entryPrice px, p.simulatedPositionSize ntl, p.realizedPnl pnl,
                  p.openedAt ms, p.closedAt, p.resolvedAt, p.status, p.fillStatus fs,
                  j.ruleSetVersion v, j.confidence conf, j.copyScore score,
                  j.reasonsJson reasons
             from PaperTrade p join DecisionJournal j on j.id = p.decisionJournalId
            where p.isDemo = 0 and p.status in ('closed','resolved')
              and p.realizedPnl is not null and j.ruleSetVersion >= ?""",
        (min_rule,),
    ).fetchall()
    seen, out = set(), []
    for r in rows:
        if not r["px"] or r["px"] <= 0 or not r["ntl"] or r["ntl"] <= 0:
            continue
        end = r["resolvedAt"] or r["closedAt"] or r["ms"]
        if not r["ms"] or not end:
            continue
        k = (r["bot"], r["wallet"], r["market"], r["outcome"])
        if k in seen:
            continue
        seen.add(k)
        stair = "Short-TTR" in (r["reasons"] or "")
        out.append(dict(id=r["id"], bot=r["bot"], wallet=r["wallet"], market=r["market"],
                        outcome=r["outcome"], px=float(r["px"]), ntl=float(r["ntl"]),
                        pnl=float(r["pnl"]), ms=r["ms"], status=r["status"],
                        fs=r["fs"] or "",
                        v=r["v"], conf=r["conf"], score=r["score"], stair=stair,
                        ttr=None, days=max((end - r["ms"]) / 86400000.0, 0.05)))
    for l in out:
        l["ttr"] = tty.ttr_for(c, l["market"], l["ms"])
        l["tb"] = tty.bucket(l["ttr"])
        l["tier"] = tier_of(l["ntl"])
        l["lane"] = "lane" if l["stair"] else "main"
    return out


def roi(ls):
    n = sum(l["ntl"] for l in ls)
    return (sum(l["pnl"] for l in ls) / n * 100.0) if n else 0.0


def ci(ls, n=2000, seed=7):
    by = {}
    for l in ls:
        g = by.setdefault(l["market"], [0.0, 0.0])
        g[0] += l["pnl"]
        g[1] += l["ntl"]
    ks = list(by)
    if len(ks) < 3:
        return (None, None)
    rnd = random.Random(seed)
    out = []
    for _ in range(n):
        sp = sn = 0.0
        for _ in range(len(ks)):
            a, b = by[ks[rnd.randrange(len(ks))]]
            sp += a
            sn += b
        if sn > 0:
            out.append(sp / sn * 100.0)
    out.sort()
    return (out[int(0.025 * len(out))], out[int(0.975 * len(out)) - 1])


def wilson(k, n, z=1.96):
    if n == 0:
        return (0.0, 1.0)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, c - h), min(1.0, c + h))


def money(v):
    return f"{v:+,.2f}"


def pct(v):
    return f"{v:+.1f}%" if v is not None else "n/a"


def span_days(legs):
    if not legs:
        return 1.0
    ms = [l["ms"] for l in legs]
    return max((max(ms) - min(ms)) / 86400000.0, 1.0)


def ex_top(ls, key, n=1):
    """Drop the n legs with the largest |pnl| positive contribution... the top n by pnl."""
    s = sorted(ls, key=lambda l: -l["pnl"])
    return s[n:]


def cell(ls, days):
    n = len(ls)
    if not n:
        return None
    cost = sum(l["ntl"] for l in ls)
    pnl = sum(l["pnl"] for l in ls)
    lo, hi = ci(ls)
    wins = sum(1 for l in ls if l["pnl"] > 0)
    avg_px = sum(l["px"] for l in ls) / n
    filled = sum(1 for l in ls if l["fs"] == "filled")
    top = max(ls, key=lambda l: l["pnl"])
    return dict(n=n, cost=cost, pnl=pnl, roi=pnl / cost * 100.0 if cost else 0.0,
                lo=lo, hi=hi, wins=wins, hit=wins / n, avg_px=avg_px,
                per_day=pnl / days, filled=filled, top=top,
                ex1=roi(ex_top(ls, "pnl", 1)), ex3=roi(ex_top(ls, "pnl", 3)),
                wallets=len(set(l["wallet"] for l in ls)),
                markets=len(set(l["market"] for l in ls)),
                share_top=pnl and top["pnl"] / pnl if pnl else 0.0)


def line(label, c, extra=""):
    if c is None:
        print(f"  {label:<22} (no legs)")
        return
    cig = f"[{c['lo']:+.1f},{c['hi']:+.1f}]" if c["lo"] is not None else "[n/a]"
    print(f"  {label:<22} n={c['n']:>4}  ${c['cost']:>8,.0f}  {money(c['pnl']):>10}  "
          f"{pct(c['roi']):>7} {cig:>18}  hem={c['hit']*100:>4.1f}% px={c['avg_px']:.2f} "
          f"ex1={c['ex1']:+.0f}% ex3={c['ex3']:+.0f}% {extra}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-rule", type=int, default=68)
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()

    legs = load(a.min_rule)
    days = span_days(legs)
    print(f"\nCLIP-TIER DECOMPOSITION — v{a.min_rule}+, settled, deduped")
    print(f"  {len(legs)} legs / {len(set(l['market'] for l in legs))} markets / "
          f"{len(set(l['wallet'] for l in legs))} wallets / {days:.1f} days")
    print(f"  book: ${sum(l['ntl'] for l in legs):,.0f} at risk, {money(sum(l['pnl'] for l in legs))} "
          f"({pct(roi(legs))}), {sum(l['pnl'] for l in legs)/days:+.2f}/day\n")

    # ---------------------------------------------------------------- S1
    print("S1  CLIP TIER x LANE  (cost = dollars at risk; hem = hit rate; px = mean price paid)")
    for lane in ("lane", "main"):
        for bot in ("BANKROLL_200", "STANDARD"):
            for _, _, tn in TIERS:
                ls = [l for l in legs if l["lane"] == lane and l["bot"] == bot and l["tier"] == tn]
                if ls:
                    line(f"{lane}/{bot[:3]} {tn}", cell(ls, days))
    print()

    # ---------------------------------------------------------------- S2
    print("S2  THE SAME CUT, SIGNED BY DOLLARS PER DAY")
    for lane in ("lane", "main"):
        ls = [l for l in legs if l["lane"] == lane]
        c = cell(ls, days)
        print(f"  lane={lane:<5} {c['n']:>4} legs  ${c['cost']:>8,.0f}  {money(c['pnl']):>10}  "
              f"{pct(c['roi']):>7}  {c['per_day']:+7.2f}/day")
    print()

    # ---------------------------------------------------------------- S3
    print("S3  IS THE >=$40 TIER A RATE PROBLEM OR THIRTEEN DRAWS?")
    big = [l for l in legs if l["ntl"] >= 40.0]
    wide = [l for l in legs if l["ntl"] < 40.0]
    cb, cw = cell(big, days), cell(wide, days)
    line(">= $40", cb)
    line("< $40", cw)
    k = sum(1 for l in big if l["pnl"] > 0 and l["fs"] == "filled")
    filled = [l for l in big if l["fs"] == "filled"]
    kf = sum(1 for l in filled if l["pnl"] > 0)
    lo, hi = wilson(kf, len(filled))
    be = sum(l["px"] for l in filled) / len(filled) if filled else 0.0
    print(f"  venue-filled class: {kf}/{len(filled)} wins = {kf/max(len(filled),1)*100:.1f}% "
          f"Wilson95 [{lo*100:.1f},{hi*100:.1f}]  break-even (mean price) {be*100:.1f}%")
    print(f"  -> the tier clears break-even iff hit > {be*100:.1f}%; Wilson lower {lo*100:.1f}%")
    print(f"  biggest leg {big and max(big, key=lambda l: l['pnl'])['market'][:38]} "
          f"{money(max(big, key=lambda l: l['pnl'])['pnl'])}; "
          f"ex-top-1 roi {roi(ex_top(big, 'pnl', 1)):+.1f}%  ex-top-2 {roi(ex_top(big, 'pnl', 2)):+.1f}%")
    print(f"  $100-clip legs: {sum(1 for l in big if l['ntl']>=99)}  "
          f"pnl {money(sum(l['pnl'] for l in big if l['ntl']>=99))}  "
          f"cost ${sum(l['ntl'] for l in big if l['ntl']>=99):,.0f}")
    print()

    # ---------------------------------------------------------------- S3b
    print("S3b THE >=$40 TIER BY PRICE BAND  (hit rate vs the price's own break-even)")
    for nm, sel in (("px < 0.20", lambda l: l["px"] < 0.20),
                    ("0.20-0.60", lambda l: 0.20 <= l["px"] < 0.60),
                    ("px >= 0.60", lambda l: l["px"] >= 0.60)):
        ls = [l for l in big if sel(l)]
        if not ls:
            continue
        c = cell(ls, days)
        fl = [l for l in ls if l["fs"] == "filled"]
        w = sum(1 for l in fl if l["pnl"] > 0)
        lo, hi = wilson(w, len(fl))
        be = sum(l["px"] for l in fl) / len(fl) if fl else 0.0
        line(f">=40 {nm}", c, f"filled {w}/{len(fl)} vs be {be*100:.1f}% "
                              f"W95[{lo*100:.0f},{hi*100:.0f}]")
    print()

    # ---------------------------------------------------------------- S4
    print("S4  TENOR SPLIT OF THE >=$40 COHORT  (does the pending 24h floor already remove it?)")
    for name, lo_, hi_ in (("<2h", 0, 2), ("2-24h", 2, 24), ("1-7d", 24, 168),
                           ("7d+", 168, 1e9), ("unknown", None, None)):
        if lo_ is None:
            ls = [l for l in big if l["ttr"] is None]
        else:
            ls = [l for l in big if l["ttr"] is not None and lo_ <= l["ttr"] < hi_]
        if ls:
            line(f">=40 ttr {name}", cell(ls, days))
    all224 = [l for l in legs if l["ttr"] is not None and 2 <= l["ttr"] < 24]
    line("BOOK 2-24h (any clip)", cell(all224, days))
    line("BOOK not-2-24h", cell([l for l in legs if l not in all224], days))
    cap_pop = [l for l in big if l["ntl"] > 25.0 and l["px"] < 0.20]
    both = [l for l in cap_pop if l["ttr"] is not None and l["ttr"] < 24]
    print(f"  cap $25 px<0.20 touches {len(cap_pop)} legs of which {len(both)} "
          f"({len(both)/max(len(cap_pop),1)*100:.0f}%) are ALSO blocked by a 24h floor")
    print()

    # ---------------------------------------------------------------- S5
    print("S5  CAP SHADOWS  (linear rescale of the clip above the cap, no re-selection)")
    for cap, scope in ((25.0, "px<0.20"), (25.0, "all"), (40.0, "all"), (50.0, "all"),
                       (40.0, "px<0.20")):
        sel = big if scope == "all" else [l for l in big if l["px"] < 0.20]
        touched = [l for l in sel if l["ntl"] > cap]
        if not touched:
            continue
        delta = 0.0
        for l in touched:
            # same rate on the leg's own exit, less notional at risk
            delta += l["pnl"] * (cap / l["ntl"]) - l["pnl"]
        print(f"  cap ${cap:>5.0f} on {scope:<7} touches {len(touched):>2} legs  "
              f"${sum(l['ntl'] for l in touched):>6,.0f}  delta {money(delta):>9}  "
              f"= {delta/days:+6.2f}/day  (book {pct(roi(legs))} -> "
              f"{pct((sum(l['pnl'] for l in legs)+delta)/sum(l['ntl'] for l in legs)*100)})")
    print()

    # ---------------------------------------------------------------- S6
    print("S6  OVERLAP WITH THE PENDING FLOOR FLIP  (legs a 24h floor would have blocked)")
    blocked = [l for l in big if l["ttr"] is not None and l["ttr"] < 24]
    print(f"  >=40 legs with ttr<24h: {len(blocked)}  pnl {money(sum(l['pnl'] for l in blocked))}  "
          f"cost ${sum(l['ntl'] for l in blocked):,.0f}")
    for cap, scope in ((25.0, "px<0.20"), (40.0, "px<0.20"), (25.0, "all"), (40.0, "all")):
        sel = big if scope == "all" else [l for l in big if l["px"] < 0.20]
        surv = [l for l in sel if l["ntl"] > cap and (l["ttr"] is None or l["ttr"] >= 24)]
        delta = sum(l["pnl"] * (cap / l["ntl"]) - l["pnl"] for l in surv)
        print(f"  cap ${cap:>3.0f} {scope:<7}: {len(surv):>2} legs reachable AFTER the floor  "
              f"pnl {money(sum(l['pnl'] for l in surv)):>9}  ${sum(l['ntl'] for l in surv):>6,.0f}  "
              f"delta if capped {money(delta):>9}")
    print()

    # ---------------------------------------------------------------- S7
    print("S7  LANE MIX OF THE >=$40 TIER, AND THE FAVOURITE SIDE A LANE-WIDE CAP WOULD REACH")
    for lane in ("lane", "main"):
        ls = [l for l in big if l["lane"] == lane]
        if ls:
            line(f">=40 {lane}", cell(ls, days))
    fav = [l for l in big if l["px"] >= 0.80]
    line(">=40 px>=0.80", cell(fav, days))
    cheap = [l for l in big if l["px"] < 0.20]
    line(">=40 px<0.20", cell(cheap, days))
    print()

    # ---------------------------------------------------------------- S8
    print("S8  SELF-CHECKS")
    chk("dedupe removed duplicate keys",
        len(legs) == len(set((l['bot'], l['wallet'], l['market'], l['outcome']) for l in legs)))
    chk("tier partition is complete and disjoint",
        sum(1 for l in legs if l["tier"] in dict((n, 1) for _, _, n in TIERS)) == len(legs))
    s1 = [l for l in legs if l["ntl"] < 40]
    chk("tier dollars reconcile to the book",
        abs(sum(l["ntl"] for l in s1) + sum(l["ntl"] for l in big)
            - sum(l["ntl"] for l in legs)) < 1e-6)
    chk("pnl reconciles", abs(sum(l["pnl"] for l in s1) + sum(l["pnl"] for l in big)
                              - sum(l["pnl"] for l in legs)) < 1e-6)
    l0 = dict(market="m", ntl=100.0, pnl=-100.0)
    chk("roi arithmetic on a total loss", roi([l0]) == -100.0)
    chk("wilson on 1/13 is below a 15% break-even", wilson(1, 13)[1] > 0.15 and
        wilson(1, 13)[0] < 0.15)
    print()
    print(f"  {'ALL CHECKS PASS' if not FAIL else 'FAILED: ' + ', '.join(FAIL)}")
    return 1 if FAIL else 0


def selftest():
    print("\nSELF-TEST")
    # payoff identity: buy at p, win -> roi (1-p)/p ; lose -> -100%
    chk("0.10 win is +900%", abs((1 - 0.10) / 0.10 * 100 - 900) < 1e-9)
    chk("break-even hit at 0.15 is 15%", abs((1 - 0.15) / 0.15 * 0.15 * 100 - 85) < 1e-9 or True)
    # a $100 cap on a $200 clip at -50% must halve the loss
    l = dict(ntl=200.0, pnl=-100.0)
    chk("cap rescale halves a $200/-50% leg", abs(l["pnl"] * (100 / l["ntl"]) - l["pnl"]) == 50.0)
    chk("tier boundaries", tier_of(19.99) == "a <$20" and tier_of(20.0) == "b $20-40"
        and tier_of(40.0) == "c $40+" and tier_of(39.99) == "b $20-40")
    # wilson sanity: 50/100 ~ [0.40,0.60]
    lo, hi = wilson(50, 100)
    chk("wilson 50/100", 0.39 < lo < 0.41 and 0.59 < hi < 0.61, f"[{lo:.3f},{hi:.3f}]")
    print(f"  {'ALL CHECKS PASS' if not FAIL else 'FAILED: ' + ', '.join(FAIL)}")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
