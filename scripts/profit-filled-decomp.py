#!/usr/bin/env python3
"""
FILLED-CLASS DECOMPOSITION — stop waiting for a forward fill sample; the tape is retrospective.

WHY THIS EXISTS
---------------
The 2026-11-16 review left the book measured four ways and did not pick one:
  booked rows        +$406.3 (+4.4%)
  positions only      +$35.5 (+0.8%)
  unadjudicated      +$490.9 (141 legs, fillStatus NULL)
  confirmed filled   -$455.4 (-21.6%, 89 legs)
and it pre-registered a *forward* test: adjudicate 150 future unadjudicated legs and see if >=60%
fill. That wait is unnecessary. `clob.polymarket.com/prices-history` serves minute tape for any token
after the fact (keyless, cached), so the 141 legs can be adjudicated TODAY. This instrument does it
and then asks the only question that matters for allocation:

    among legs we can PROVE we owned, is there any cell that earns?

MODEL (inherited verbatim from scripts/profit-fill-tape.py so there is one definition)
---------------------------------------------------------------------------------------
touch = min(p) over [t0, t0+W] <= L + 0.001  -> filled_tape   (POSITIVE evidence)
near  = min(p) <= L + 0.010                  -> near_miss     (ambiguous, excluded from both)
else                                         -> unfilled_tape (a WEAKER negative: a resting bid can be
                                                filled by a seller crossing without a later print)
=> touch rate is a LOWER bound on fill and unfilled_tape is an UPPER bound on non-fill. Every
conclusion is stated in that direction.

COST BASIS: PaperTrade.simulatedPositionSize = DOLLARS AT RISK (~$10-13 clip), NOT shares.
PnL = realizedPnl as booked (the exit is basis-independent). CIs market-clustered, 2,000 draws.
Dedupe: first leg per bot|wallet|market|outcome. Regime: DecisionJournal.ruleSetVersion >= 68.

READ-ONLY: DB mode=ro, no prisma write, no RuleSet read/write, no fillStatus stamp written.

RUN
  python3 scripts/profit-filled-decomp.py                # regime v68+, W=3600s
  python3 scripts/profit-filled-decomp.py --window=600
  python3 scripts/profit-filled-decomp.py --selftest
"""
import argparse
import importlib.util
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def _mod(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(m)
    return m


ppi = _mod("ppi", os.path.join(HERE, "profit-postfix-integrity.py"))
ft = _mod("ft", os.path.join(HERE, "profit-fill-tape.py"))

MIN_RULE = 68
BANDS = ((0.0, 0.20), (0.20, 0.40), (0.40, 0.60), (0.60, 0.80), (0.80, 1.01))
FAIL = []


def chk(label, ok, detail=""):
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}" + (f" — {detail}" if detail else ""))
    if not ok:
        FAIL.append(label)
    return ok


# ------------------------------------------------------------------ stats helpers

def agg(ls):
    n = sum(l["simulatedPositionSize"] for l in ls)
    p = sum(l["realizedPnl"] or 0.0 for l in ls)
    return len(ls), n, p, (p / n * 100.0 if n else None)


def cistr(ls):
    if len(ls) < 2:
        return "n/a"
    lo, hi = ppi.cluster_ci(ls, lambda l: l["realizedPnl"] or 0.0)
    if lo is None:
        return "n/a"
    return f"[{lo:+.1f},{hi:+.1f}]"


def line(tag, ls, width=26):
    n, ntl, p, r = agg(ls)
    rr = f"{r:+.1f}%" if r is not None else "   n/a"
    print(f"  {tag:<{width}} {n:>4} {ntl:>9.0f} {p:>+10.1f} {rr:>8}  {cistr(ls):>18}")


def band_of(p):
    for lo, hi in BANDS:
        if lo <= p < hi or (hi >= 1.01 and p >= lo):
            return f"{lo:.2f}-{hi:.2f}"
    return "?"


def ex_top(ls, k):
    """PnL with the k biggest winners removed, and the ROI of what is left."""
    s = sorted(ls, key=lambda l: -(l["realizedPnl"] or 0.0))
    return s[k:]


def days(ls):
    ts = [l["openedTs"] for l in ls if l.get("openedTs")]
    if len(ts) < 2:
        return 0.0
    return max((max(ts) - min(ts)) / 86400000.0, 0.5)


def age_days(l):
    """Holding period: opened -> closed/resolved (open legs measured to the newest leg)."""
    if not l.get("openedTs"):
        return None
    end = l.get("closedTs") or l.get("resolvedTs")
    if not end:
        return None
    return max((end - l["openedTs"]) / 86400000.0, 0.0)


# ------------------------------------------------------------------ load

def load_regime(min_rule):
    legs = ft.load("2026-09-01")
    for l in legs:
        l["closedTs"] = ppi._ms(l["closedAt"]) if l.get("closedAt") else None
        l["resolvedTs"] = ppi._ms(l["resolvedAt"]) if l.get("resolvedAt") else None
    return [l for l in legs if (l.get("rv") or 0) >= min_rule]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--window", type=int, default=3600)
    ap.add_argument("--min-rule", type=int, default=MIN_RULE)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()

    print("=" * 92)
    print("FILLED-CLASS DECOMPOSITION — adjudicating the ambiguous class against the venue tape")
    print("=" * 92)

    legs = load_regime(a.min_rule)
    print(f"\n  regime: DecisionJournal.ruleSetVersion >= {a.min_rule}, deduped first leg per")
    print(f"  bot|wallet|market|outcome, opened >= 2026-09-01, non-demo: {len(legs)} legs")

    print("\n  adjudicating against cached venue tape ...")
    ft.classify(legs, workers=a.workers)

    W = a.window
    for l in legs:
        l["tv"] = ft.verdict_at(l, W)
    settled = [l for l in legs if l["status"] != "open"]
    print(f"  settled legs: {len(settled)}  (open: {len(legs) - len(settled)})")

    # ---------------------------------------------------------------- S1 coverage
    print("\n" + "-" * 92)
    print("S1. COVERAGE — can the tape speak to the regime at all?")
    print("-" * 92)
    cov = {}
    for l in settled:
        cov[l["tv"]] = cov.get(l["tv"], 0) + 1
    for k in sorted(cov, key=lambda x: -cov[x]):
        print(f"  {k:<16} {cov[k]:>4}  ({cov[k] / len(settled) * 100:.1f}%)")
    adjudicable = [l for l in settled if l["tv"] in ("filled_tape", "near_miss", "unfilled_tape")]
    chk("tape adjudicates >=90% of settled regime legs",
        len(adjudicable) >= 0.90 * len(settled),
        f"{len(adjudicable)}/{len(settled)} = {len(adjudicable) / len(settled) * 100:.1f}%")

    # ---------------------------------------------------------------- S2 validation
    print("\n" + "-" * 92)
    print("S2. VALIDATION — does the tape agree with the resolver where the resolver has spoken?")
    print("-" * 92)
    res = {"filled": [], "unfilled": [], "NULL": []}
    for l in settled:
        res["filled" if l.get("fillStatus") == "filled"
            else "unfilled" if l.get("fillStatus") == "unfilled" else "NULL"].append(l)
    print(f"  {'resolver':<12} {'legs':>5} {'tape filled':>12} {'near':>6} {'tape unfilled':>14} {'no tape':>8}")
    for k in ("filled", "unfilled", "NULL"):
        ls = res[k]
        tf = sum(1 for l in ls if l["tv"] == "filled_tape")
        nm = sum(1 for l in ls if l["tv"] == "near_miss")
        tu = sum(1 for l in ls if l["tv"] == "unfilled_tape")
        nt = len(ls) - tf - nm - tu
        print(f"  {k:<12} {len(ls):>5} {tf:>12} {nm:>6} {tu:>14} {nt:>8}")
    f_ls = [l for l in res["filled"] if l["tv"] in ("filled_tape", "unfilled_tape")]
    agree = sum(1 for l in f_ls if l["tv"] == "filled_tape")
    if f_ls:
        print(f"\n  agreement on resolver-FILLED legs: {agree}/{len(f_ls)} = "
              f"{agree / len(f_ls) * 100:.1f}% called filled by the tape")
        chk("tape confirms >=70% of resolver-filled legs", agree >= 0.70 * len(f_ls),
            "the tape model is sane on the class we already trust")
    u_ls = [l for l in res["unfilled"] if l["tv"] == "filled_tape"]
    if res["unfilled"]:
        print(f"  resolver-UNFILLED legs the tape says DID touch: {len(u_ls)}/{len(res['unfilled'])}"
              f" = {len(u_ls) / len(res['unfilled']) * 100:.1f}%")

    # ---------------------------------------------------------------- S2b degeneracy of the touch test
    print("\n" + "-" * 92)
    print("S2b. IS THE TOUCH TEST INFORMATIVE? (min(p) over the window includes the dispatch snapshot)")
    print("-" * 92)
    print("  If we paid the market price, the tape is AT our price at t0, so a 0-lag touch is guaranteed.")
    print("  Re-test with a lag floor: does the series print <= our price AFTER we were resting?")
    print(f"  {'resolver class':<12} {'n':>4} " + " ".join(f"{'lag>=' + str(s) + 's':>10}" for s in (0, 60, 300, 900)))

    def touch_at(l, floor_s):
        s = l.get("tape_series")
        if not s:
            return False
        t0 = l["openedTs"] // 1000
        return any(p <= l["trueP"] + 0.001 for t, p in s if t >= t0 + floor_s)

    floors = (0, 60, 300, 900)
    for k in ("filled", "unfilled", "NULL"):
        ls = [l for l in res[k] if l.get("tape_series")]
        if not ls:
            continue
        rates = [sum(1 for l in ls if touch_at(l, f)) / len(ls) * 100 for f in floors]
        print(f"  {k:<12} {len(ls):>4} " + " ".join(f"{r:>9.1f}%" for r in rates))
    print("  read: a class whose rate decays with the lag floor was touching at dispatch, not filling.")

    # ---------------------------------------------------------------- S3 the ambiguous class
    print("\n" + "-" * 92)
    print("S3. THE QUESTION YESTERDAY DEFERRED — what does the unadjudicated class actually do?")
    print("-" * 92)
    null_ls = res["NULL"]
    null_adj = [l for l in null_ls if l["tv"] in ("filled_tape", "unfilled_tape")]
    null_fill = [l for l in null_adj if l["tv"] == "filled_tape"]
    print(f"  unadjudicated (fillStatus NULL): {len(null_ls)} legs, ${sum(l['simulatedPositionSize'] for l in null_ls):.0f}"
          f", booked {sum(l['realizedPnl'] or 0 for l in null_ls):+.1f}")
    if null_adj:
        print(f"  tape-adjudicable: {len(null_adj)}  tape-filled: {len(null_fill)}  "
              f"touch rate {len(null_fill) / len(null_adj) * 100:.1f}%  (LOWER bound on fill)")
        line("of which tape-FILLED", null_fill)
        line("of which tape-NOT-filled", [l for l in null_adj if l["tv"] == "unfilled_tape"])
        nf = [l for l in null_adj if l["tv"] == "unfilled_tape"]
        if nf:
            print(f"  booked PnL stranded in tape-NOT-filled legs: "
                  f"{sum(l['realizedPnl'] or 0 for l in nf):+.1f} on ${sum(l['simulatedPositionSize'] for l in nf):.0f}")
            for k in (1, 3, 5, 10):
                e = ex_top(nf, k)
                n6, ntl6, p6, r6 = agg(e)
                if not n6:
                    continue
                rr6 = f"{r6:>+7.1f}%" if r6 is not None else "    n/a"
                print(f"    ex-top-{k:<2} {n6:>4} legs ${ntl6:>7.0f} {p6:>+9.1f} {rr6}")
            pos = [l for l in nf if (l["realizedPnl"] or 0) > 0]
            print(f"    {len(pos)} of {len(nf)} legs are positive")

    # ---------------------------------------------------------------- S4 whole-book verdict
    print("\n" + "-" * 92)
    print("S4. THE BOOK, ON ONE BASIS — every settled leg, valued the way the tape says it happened")
    print("-" * 92)
    # reachable basis: a leg counts only if the resolver stamped it filled OR the tape proves a touch.
    # tape-NOT-filled legs that the resolver left NULL are booked at ZERO exposure.
    reach = []
    for l in settled:
        if l.get("fillStatus") == "filled":
            reach.append(l)
        elif l.get("fillStatus") == "unfilled":
            continue
        elif l["tv"] == "filled_tape":
            reach.append(l)
    print("  basis key: filled = resolver stamp; NULL = tape touch; unfilled = excluded.")
    line("booked (all rows)", settled)
    line("positions only (non-unfilled)", [l for l in settled if l.get("fillStatus") != "unfilled"])
    line("confirmed filled (resolver)", [l for l in settled if l.get("fillStatus") == "filled"])
    line("REACHABLE (stamp OR tape touch)", reach)
    d = days(reach)
    n, ntl, p, r = agg(reach)
    if ntl:
        print(f"  reachable window {d:.1f}d -> {p / d:+.1f} $/day on ${ntl:.0f} = "
              f"{p / d / ntl * 1000:+.2f} $/1k-capital-day")

    # ---------------------------------------------------------------- S5 where the money is
    print("\n" + "-" * 92)
    print("S5. DECOMPOSITION OF THE REACHABLE BOOK — is any cell positive? (cost = dollars at risk)")
    print("-" * 92)
    print(f"  {'cell':<26} {'legs':>4} {'cost':>9} {'pnl':>10} {'ROI':>8}  {'cluster CI':>18}")
    for lane in ("BANKROLL_200", "STANDARD"):
        sub = [l for l in reach if l["botId"] == lane]
        if sub:
            line(lane, sub)
    print()
    for lo, hi in BANDS:
        sub = [l for l in reach if lo <= l["entryPrice"] < hi or (hi >= 1.01 and l["entryPrice"] >= lo)]
        if sub:
            line(f"band {lo:.2f}-{hi:.2f}", sub)
    print()
    for lane in ("BANKROLL_200", "STANDARD"):
        for lo, hi in BANDS:
            sub = [l for l in reach if l["botId"] == lane and (lo <= l["entryPrice"] < hi)]
            if len(sub) >= 8:
                line(f"{lane[:4]} {lo:.2f}-{hi:.2f}", sub)
    print()
    wb = {}
    for l in reach:
        wb.setdefault(l["walletAddress"], []).append(l)
    for w, ls in sorted(wb.items(), key=lambda kv: -len(kv[1]))[:10]:
        line(f"wallet {w[:10]}", ls, width=22)

    # concentration
    print()
    for k in (1, 3, 5, 10):
        ex = ex_top(reach, k)
        n2, ntl2, p2, r2 = agg(ex)
        print(f"  ex-top-{k:<2} {n2:>4} legs ${ntl2:>7.0f} {p2:>+9.1f} {r2:>+8.1f}%")
    top1 = ex_top(reach, 1)
    print(f"  the single biggest leg carries {sum((l['realizedPnl'] or 0) for l in reach) - sum((l['realizedPnl'] or 0) for l in top1):+.1f}")

    # ---------------------------------------------------------------- S6 capital velocity
    print("\n" + "-" * 92)
    print("S6. CAPITAL VELOCITY — what the reachable book actually earns per capital-day")
    print("-" * 92)
    ages = [age_days(l) for l in reach if age_days(l) is not None]
    if ages:
        ages.sort()
        print(f"  holding period (opened->closed/resolved): n={len(ages)} median {ages[len(ages) // 2]:.1f}d "
              f"mean {sum(ages) / len(ages):.1f}d  p90 {ages[int(0.9 * len(ages))]:.1f}d")
        capdays = sum(l["simulatedPositionSize"] * age_days(l) for l in reach if age_days(l) is not None)
        pnl = sum(l["realizedPnl"] or 0.0 for l in reach)
        if capdays:
            print(f"  capital-days = sum(cost x hold) = {capdays:,.0f}  ->  "
                  f"{pnl / capdays * 1000:+.3f} $/1k-capital-day")
            print(f"  at $500/day a capital base of ${500 / (pnl / capdays) / 1000:.0f}k is required"
                  if pnl > 0 else "  a negative rate has no required capital — it has a required sign")

    # ---------------------------------------------------------------- S7 turnover-normalised bands
    print("\n" + "-" * 92)
    print("S7. BAND x SPEED — edge where it is, weighted by how fast it recycles")
    print("-" * 92)
    print(f"  {'band':<12} {'legs':>4} {'ROI':>8} {'median hold':>12} {'$/1k-cap-day':>13}")
    for lo, hi in BANDS:
        sub = [l for l in reach if lo <= l["entryPrice"] < hi]
        ag = [age_days(l) for l in sub if age_days(l) is not None]
        if not sub or not ag:
            continue
        n2, ntl2, p2, r2 = agg(sub)
        cd = sum(l["simulatedPositionSize"] * age_days(l) for l in sub if age_days(l) is not None)
        ag.sort()
        rate = p2 / cd * 1000 if cd else 0.0
        print(f"  {lo:.2f}-{hi:.2f}     {n2:>4} {r2:>+7.1f}% {ag[len(ag) // 2]:>11.1f}d {rate:>+13.3f}")

    # ---------------------------------------------------------------- S8 dispatch gap
    print("\n" + "-" * 92)
    print("S8. HOW WE GOT FILLED — bid vs market at dispatch decides the sign")
    print("-" * 92)
    print("  gap = price we paid - market price at dispatch (tape p0).")
    print("  gap < 0 = resting bid UNDER the market (we waited); gap > 0 = we paid up (we crossed).")
    ed = [l for l in reach if l.get("tape_p0") is not None]
    print(f"  legs with a dispatch-market price: {len(ed)}/{len(reach)}")
    buckets = ((-9.9, -0.05, "gap <= -5c (deep rest)"),
               (-0.05, -0.02, "gap -5..-2c"),
               (-0.02, 0.0, "gap -2..0c"),
               (0.0, 0.02, "gap 0..+2c (paid up)"),
               (0.02, 9.9, "gap >= +2c (crossed)"))
    for lo, hi, label in buckets:
        sub = [l for l in ed if lo < (l["trueP"] - l["tape_p0"]) <= hi]
        if sub:
            line(label, sub, width=24)
    print()
    for lane in ("BANKROLL_200", "STANDARD"):
        neg = [l for l in ed if l["botId"] == lane and (l["trueP"] - l["tape_p0"]) <= -0.02]
        pos = [l for l in ed if l["botId"] == lane and (l["trueP"] - l["tape_p0"]) > -0.02]
        if neg:
            line(f"{lane[:4]} rested <=-2c", neg, width=24)
        if pos:
            line(f"{lane[:4]} paid >=-2c", pos, width=24)
    # the split that the fill stamps actually encode
    print()
    agg_gap = {}
    for l in ed:
        k = "rested (gap<=-2c)" if (l["trueP"] - l["tape_p0"]) <= -0.02 else "at/above (gap>-2c)"
        agg_gap.setdefault(k, []).append(l)
    for k, ls in agg_gap.items():
        line(k, ls, width=24)

    # ---------------------------------------------------------------- S8b detection lag
    print("\n" + "-" * 92)
    print("S8b. IS PAYING UP A SYMPTOM OF STALE DETECTION? (wallet trade -> our dispatch lag)")
    print("-" * 92)
    dl = [l for l in reach if l.get("ots") and l.get("openedTs")]
    for l in dl:
        l["det_lag_s"] = max(0.0, (l["openedTs"] - l["ots"]) / 1000.0)
    if dl:
        dl.sort(key=lambda l: l["det_lag_s"])
        med = dl[len(dl) // 2]["det_lag_s"]
        print(f"  n={len(dl)}  median detection lag {med:.0f}s  "
              f"p90 {dl[int(0.9 * len(dl))]['det_lag_s']:.0f}s")
        print(f"  {'cell':<26} {'legs':>4} {'cost':>9} {'pnl':>10} {'ROI':>8}")
        for lo, hi, label in ((-1.0, 0.0, "paid at/below"), (0.0, 9.9, "paid up")):
            for a, b, tag in ((0, 120, "lag<2m"), (120, 600, "2-10m"), (600, 10 ** 9, "lag>10m")):
                sub = [l for l in dl if lo < (l["trueP"] - l["tape_p0"]) <= hi
                       and a <= l["det_lag_s"] < b]
                if sub:
                    line(f"{label} {tag}", sub, width=26)

    # ---------------------------------------------------------------- S9 touch lag
    print("\n" + "-" * 92)
    print("S9. TIME TO TOUCH — does a fast fill mean a bad fill?")
    print("-" * 92)
    lag_b = ((0, 60, "touch <=60s"), (60, 300, "60-300s"), (300, 1800, "300-1800s"),
             (1800, 3600, "1800-3600s"), (3600, 10 ** 9, "never / >1h"))
    for lo, hi, label in lag_b:
        sub = [l for l in reach if l.get("tape_touch_lag_s") is not None
               and lo <= l["tape_touch_lag_s"] < hi]
        if hi > 3600:
            sub = [l for l in reach if l.get("tape_touch_lag_s") is None]
        if sub:
            line(label, sub, width=24)

    # ---------------------------------------------------------------- S10 the resolver's false negatives
    print("\n" + "-" * 92)
    print("S10. THE RESOLVER'S FALSE NEGATIVES — 191 legs are stamped 'unfilled' and the tape says many traded")
    print("-" * 92)
    un = res["unfilled"]
    un_adj = [l for l in un if l["tv"] in ("filled_tape", "unfilled_tape")]
    un_hit = [l for l in un_adj if l["tv"] == "filled_tape"]
    print(f"  stamped unfilled: {len(un)} legs ${sum(l['simulatedPositionSize'] for l in un):.0f} "
          f"booked {sum(l['realizedPnl'] or 0 for l in un):+.1f}")
    if un_adj:
        print(f"  tape-adjudicable {len(un_adj)}; tape says TOUCHED {len(un_hit)} "
              f"= {len(un_hit) / len(un_adj) * 100:.1f}% FALSE-NEGATIVE rate (lower bound)")
        line("those 80-odd legs, booked", un_hit, width=26)
        line("same lane split: BANK", [l for l in un_hit if l["botId"] == "BANKROLL_200"], width=22)
        line("same lane split: STAN", [l for l in un_hit if l["botId"] == "STANDARD"], width=22)
    # one basis that the tape supports: stamp-filled + tape-touched (incl. those stamped unfilled)
    tape_book = list(reach)
    for l in un_hit:
        tape_book.append(l)
    line("TApe BOOK (stamp|touch, all)", tape_book, width=26)
    n3, ntl3, p3, r3 = agg(tape_book)
    d3 = days(tape_book)
    if ntl3:
        print(f"  tape book: {p3 / d3:+.1f} $/day over {d3:.1f}d; ex-top-1 "
              f"{agg(ex_top(tape_book, 1))[2]:+.1f}")

    # ---------------------------------------------------------------- S11 the one CI-positive cell
    print("\n" + "-" * 92)
    print("S11. INSIDE THE ONLY CELL WITH A CI EXCLUDING ZERO (band 0.80-1.01)")
    print("-" * 92)
    fav = [l for l in reach if l["entryPrice"] >= 0.80]
    mk = {l["marketId"] for l in fav}
    wl = {l["walletAddress"] for l in fav}
    print(f"  {len(fav)} legs / {len(mk)} markets / {len(wl)} wallets, "
          f"${sum(l['simulatedPositionSize'] for l in fav):.0f} cost")
    for l in sorted(fav, key=lambda x: -(x["realizedPnl"] or 0)):
        print(f"    {l['botId'][:4]:<5} p={l['entryPrice']:.3f} ntl={l['simulatedPositionSize']:>6.1f} "
              f"pnl={l['realizedPnl'] or 0:>+8.2f} {l['status']:<9} {l['marketId'][:44]}")

    # ---------------------------------------------------------------- S12 post-fix cohort + counterfactual
    print("\n" + "-" * 92)
    print("S12. THE PAID-UP CELL, POST PRICE-SIDE FIX (card profit-fill-never-reachable P3, 150-leg bar)")
    print("-" * 92)
    FIX = ppi._ms("2026-11-09 09:15:16")
    post = [l for l in reach if l["openedTs"] >= FIX]
    print(f"  legs opened after the 2026-11-09 price-side fix: {len(post)}")
    for lo, hi, label in ((-9.9, 0.0, "paid at/below market"), (0.0, 9.9, "PAID ABOVE market")):
        sub = [l for l in post if lo < (l["trueP"] - l["tape_p0"]) <= hi]
        if sub:
            line(label, sub, width=24)
    pu_post = [l for l in post if (l["trueP"] - l["tape_p0"]) > 0.0]
    print(f"  bar progress: {len(pu_post)}/150 post-fix paid-up legs; a live dispatch rule ships at 150")
    print()
    print("  COUNTERFACTUAL — the reachable book with the paid-up class not dispatched at all:")
    pu = [l for l in reach if (l["trueP"] - l["tape_p0"]) > 0.0]
    rest = [l for l in reach if (l["trueP"] - l["tape_p0"]) <= 0.0]
    line("as traded (reachable)", reach, width=26)
    line("paid-up class removed", rest, width=26)
    n4, ntl4, p4, r4 = agg(rest)
    d4 = days(rest)
    if ntl4:
        print(f"  -> {r4:+.1f}% vs {agg(reach)[3]:+.1f}%, {p4 / d4:+.1f} $/day vs {agg(reach)[2] / d:.1f} $/day")
    print(f"  paid-up class by lane: BANK {len([l for l in pu if l['botId'] == 'BANKROLL_200'])} legs "
          f"/ ${sum(l['simulatedPositionSize'] for l in pu if l['botId'] == 'BANKROLL_200'):.0f}, "
          f"STAN {len([l for l in pu if l['botId'] == 'STANDARD'])} legs "
          f"/ ${sum(l['simulatedPositionSize'] for l in pu if l['botId'] == 'STANDARD'):.0f}")

    # ---------------------------------------------------------------- S13 what the rung reads
    print("\n" + "-" * 92)
    print("S13. WHAT THE RUNG READS — trailing settled sums on each basis (settle clock = closed|resolved)")
    print("-" * 92)
    def settled_between(ls, lo_ms, hi_ms):
        out = []
        for l in ls:
            t = l.get("closedTs") or l.get("resolvedTs")
            if t and lo_ms <= t < hi_ms:
                out.append(l)
        return out
    import time as _t
    now_ms = int(_t.time() * 1000)
    D = 86400000
    for win, rung in ((7, 1750), (14, 1750)):
        lo = now_ms - win * D
        print(f"  last {win}d (rung 1 needs +${rung} per 7d = ${rung / 7:.0f}/day):")
        for label, pop in (("booked rows", settled),
                           ("positions only", [l for l in settled if l.get("fillStatus") != "unfilled"]),
                           ("confirmed filled", [l for l in settled if l.get("fillStatus") == "filled"]),
                           ("REACHABLE (tape)", reach)):
            sub = settled_between(pop, lo, now_ms)
            n5, ntl5, p5, r5 = agg(sub)
            need = rung * win / 7
            print(f"    {label:<18} {n5:>4} legs ${ntl5:>7.0f} {p5:>+9.1f}  "
                  f"{p5 / (need) * 100:>6.1f}% of the bar")
            if win == 7 and sub:
                e1 = ex_top(sub, 1)
                big = max(sub, key=lambda l: l["realizedPnl"] or 0)
                print(f"      {'':<16} ex-top-1 {agg(e1)[2]:>+8.1f}; biggest leg "
                      f"{big['realizedPnl'] or 0:+.1f} ({big['marketId'][:38]})")
        print()

    print("\n" + "=" * 92)
    print(f"self-checks: {len(FAIL)} FAIL" if FAIL else "self-checks: all PASS")
    print("=" * 92)
    return 1 if FAIL else 0


def selftest():
    print("self-test: band edges, aggregation identity, ex-top")
    assert band_of(0.0) == "0.00-0.20"
    assert band_of(0.1999) == "0.00-0.20"
    assert band_of(0.20) == "0.20-0.40"
    assert band_of(0.999) == "0.80-1.01"
    assert band_of(1.0) == "0.80-1.01"
    legs = [{"simulatedPositionSize": 10.0, "realizedPnl": 5.0, "openedTs": 0, "marketId": "a"},
            {"simulatedPositionSize": 10.0, "realizedPnl": -5.0, "openedTs": 1, "marketId": "b"}]
    n, ntl, p, r = agg(legs)
    assert (n, ntl, p, abs(r) < 1e-9) == (2, 20.0, 0.0, True)
    assert len(ex_top(legs, 1)) == 1 and ex_top(legs, 1)[0]["realizedPnl"] == -5.0
    print("  selftest OK")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
    else:
        sys.exit(main())
