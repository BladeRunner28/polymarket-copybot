#!/usr/bin/env python3
"""
MARGINAL CELL — is the next dollar going where the edge is?

WHY THIS EXISTS
---------------
Five instruments now agree on the shape of the loss: the book loses -6.7% per intent-dollar at the
ask and -12.2% on the legs it owns, no maker posting depth pays, and the wallet side has no
forward selector (ml-u2b, 2026-11-19: all six wallet features fail, BH q >= 0.134). What none of
them answers is the ALLOCATION question the ladder actually turns on:

    for each (lane x band) cell: how much intent notional per day goes in, what fraction of it we
    own, what that owned fraction returns, and therefore how many EV dollars per day that cell
    contributes -- and what happens to the daily EV if that cell is zeroed or clip-capped?

The band tables to date report ROI PER DOLLAR RISKED inside the cell. That is a rate, not a
weight, so a losing band with 60% of the notional looks the same as a losing band with 6%. This
instrument multiplies the rate by the weight and reports the product: EV dollars per day, by cell,
on the tape-adjudicated ownership basis. That product is the thing a rule can move.

BASIS (stated once, used everywhere)
------------------------------------
population : PaperTrade isDemo=0, opened >= 2026-09-01, DecisionJournal.ruleSetVersion >= MIN_RULE,
             settled (status != open), deduped to the first leg per bot|wallet|market|outcome.
cost       : simulatedPositionSize = DOLLARS AT RISK, not shares. Every ROI is PnL/notional.
price      : the BOOKED entry (what we paid). The ask arm re-prices the same exit at the quoted ask
             at dispatch (MarketSnapshot, +/-300s), which is the taker price and the fillability
             check. Slippage is then added on top of the ask.
ownership  : clob.polymarket.com minute tape, touch = min(p) <= entry + 0.001 inside 3600s of
             dispatch -> filled_tape. POSITIVE evidence only; near_miss (+1c) is excluded from both
             arms, unfilled_tape is an UPPER bound on non-fill (a resting bid can be lifted
             without a later print). Same model as scripts/profit-fill-tape.py, reused verbatim.
EV         : EV per intent-dollar = (PnL of the tape-owned legs) / (intent notional of ALL legs).
             A leg we never owned contributes zero PnL but its notional still counts as the
             capacity that cell consumed. ROI on filled is reported separately; EV/intent is what
             compares cells of different fill rates.
CIs        : market-clustered bootstrap (resample marketId), 1500 draws.
READ-ONLY  : DB mode=ro, no prisma write, no RuleSet read/write.

RUN
  python3 scripts/profit-marginal-cell.py
  python3 scripts/profit-marginal-cell.py --min-rule 0 --since 2026-09-01
  python3 scripts/profit-marginal-cell.py --selftest
"""
import argparse
import importlib.util
import os
import random
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def _mod(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(m)
    return m


ppi = _mod("ppi", os.path.join(HERE, "profit-postfix-integrity.py"))
ft = _mod("ft", os.path.join(HERE, "profit-fill-tape.py"))
te = _mod("te", os.path.join(HERE, "profit-taker-entry.py"))

BANDS = ((0.0, 0.20), (0.20, 0.40), (0.40, 0.60), (0.60, 0.80), (0.80, 1.01))
NAMES = ("0.00-0.20", "0.20-0.40", "0.40-0.60", "0.60-0.80", "0.80-1.01")
FAIL = []


def chk(label, ok, detail=""):
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}" + (f" — {detail}" if detail else ""))
    if not ok:
        FAIL.append(label)
    return ok


def band_of(p):
    for (lo, hi), nm in zip(BANDS, NAMES):
        if p is not None and lo <= p < hi:
            return nm
    return None


def ntl(l):
    return l.get("simulatedPositionSize") or 0.0


def owned(l):
    return l.get("tv") == "filled_tape"


def pnl_at(l, p):
    """PnL of the same exit entered at price p, same dollars at risk. 0 if never owned."""
    if not owned(l):
        return 0.0
    return te.pnl_at(l, p) or 0.0


def agg(ls, key):
    """(n, notional, pnl) for a list of legs, key = price function."""
    n = len(ls)
    n_ = sum(ntl(l) for l in ls)
    p = sum(pnl_at(l, key(l)) for l in ls)
    return n, n_, p


def ev_intent(ls, key):
    _, n_, p = agg(ls, key)
    return (p / n_) if n_ else 0.0


def ev_dollars(ls, key):
    _, _, p = agg(ls, key)
    return p


def boot_ev(ls, key, reps=1500, seed=7):
    """Market-clustered CI on EV per intent-dollar."""
    if not ls:
        return (0.0, 0.0)
    by = {}
    for l in ls:
        by.setdefault(l["marketId"], []).append(l)
    keys = list(by)
    rnd = random.Random(seed)
    xs = []
    for _ in range(reps):
        samp = []
        for _k in range(len(keys)):
            samp.extend(by[keys[rnd.randrange(len(keys))]])
        xs.append(ev_intent(samp, key))
    xs.sort()
    return xs[int(0.025 * len(xs))], xs[int(0.975 * len(xs)) - 1]


def roi_filled(ls, key):
    f = [l for l in ls if owned(l)]
    if not f:
        return None
    return ev_dollars(f, key) / sum(ntl(l) for l in f)


def fill_rate(ls):
    adj = [l for l in ls if l.get("tv") in ("filled_tape", "near_miss", "unfilled_tape")]
    if not adj:
        return None
    return sum(1 for l in adj if owned(l)) / len(adj)


def censored_pool(min_rule, allow_fetch=True):
    """Skipped decisions at price >= 0.85, one per (conditionId, outcome), marked to the venue winner.

    These rows are never acted and never marked, so no PnL surface has ever included them. The
    winner comes from the CLOB archive (tokens[].winner) via the same cached reader the cheap-tail
    instrument uses; the decision's own `outcome` string names the side, so label == winner is the
    correct test here (unlike the cheap cohort, where the label names the OTHER side).
    """
    pca = _mod("pca", os.path.join(HERE, "profit-cheap-ask.py"))
    c = ft._con()
    rows = c.execute(
        "SELECT d.id, o.conditionId AS cid, o.outcome AS outcome, d.priceAtDecision AS px,"
        "       o.marketCategory AS cat "
        "FROM DecisionJournal d JOIN ObservedTrade o ON o.id = d.observedTradeId "
        "WHERE d.isDemo=0 AND d.ruleSetVersion>=? AND d.decision!='paper_copy'"
        "  AND d.priceAtDecision>=0.85", (min_rule,)).fetchall()
    seen, out = set(), []
    for r in rows:
        cid, oc = r["cid"], str(r["outcome"] or "").strip().lower()
        if not cid or not oc or (cid, oc) in seen:
            continue
        seen.add((cid, oc))
        win, _cached = pca.fetch_winner(cid, allow_fetch)
        out.append({"cid": cid, "px": float(r["px"]), "cat": r["cat"],
                    "winner": win, "win": bool(win) and str(win).strip().lower() == oc})
    return out


def load(since, min_rule):
    legs = ft.load(since)
    legs = [l for l in legs if (l.get("rv") or 0) >= min_rule]
    for l in legs:
        l["closedTs"] = ppi._ms(l["closedAt"]) if l.get("closedAt") else None
        l["resolvedTs"] = ppi._ms(l["resolvedAt"]) if l.get("resolvedAt") else None
    return legs


def span_days(legs):
    ts = [l["openedTs"] for l in legs if l.get("openedTs")]
    if not ts:
        return 0.0
    return max(1e-9, (max(ts) - min(ts)) / 86400000.0)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default="2026-09-01")
    ap.add_argument("--min-rule", type=int, default=68)
    ap.add_argument("--window", type=int, default=3600)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--no-fetch", action="store_true", help="cache-only for the censored pool")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()

    print("=" * 96)
    print("MARGINAL CELL — EV dollars per day by lane x band, on the tape-adjudicated ownership basis")
    print("=" * 96)

    legs = load(a.since, a.min_rule)
    print(f"\n  loaded+deduped regime legs (ruleSetVersion >= {a.min_rule}, opened >= {a.since}): {len(legs)}")
    legs = [l for l in legs if l["status"] != "open"]
    print(f"  settled: {len(legs)}  span {span_days(legs):.1f} days")

    print("\n  adjudicating against the cached venue tape and the dispatch snapshot ...")
    ft.classify(legs, workers=a.workers)
    for l in legs:
        l["tv"] = ft.verdict_at(l, a.window)

    enriched, stats = te.enrich(legs, 300)
    print(f"  snapshot-mapped legs: {len(enriched)} of {len(legs)}"
          f"  (dropped: no_snap {stats['no_snap']}, ambiguous {stats['ambiguous']}, bad_book {stats['bad_book']})")
    for l in enriched:
        l["band"] = band_of(l["entryPrice"])

    # ---------------------------------------------------------------- S1
    print("\n" + "-" * 96)
    print("S1. COVERAGE — what the tape can and cannot speak to")
    print("-" * 96)
    cov = {}
    for l in enriched:
        cov[l["tv"]] = cov.get(l["tv"], 0) + 1
    for k in sorted(cov, key=lambda x: -cov[x]):
        print(f"  {k:<16} {cov[k]:>4}")
    adj = [l for l in enriched if l.get("tv") in ("filled_tape", "near_miss", "unfilled_tape")]
    chk("tape adjudicates >= 80% of the snapshot-mapped book",
        len(adj) >= 0.80 * len(enriched), f"{len(adj)}/{len(enriched)}")
    tot_ntl = sum(ntl(l) for l in enriched)
    print(f"  intent notional in the mapped book: ${tot_ntl:,.0f}"
          f"  (unmapped ${sum(ntl(l) for l in legs) - tot_ntl:,.0f} is excluded, and the exclusion"
          f" is a COVERAGE bias, not a random one)")

    days = span_days(enriched)
    # ---------------------------------------------------------------- S2
    print("\n" + "-" * 96)
    print("S2. CELL TABLE — rate AND weight. EV$ = intent notional x EV per intent-dollar")
    print("-" * 96)
    hdr = (f"  {'lane':<14}{'band':<11}{'n':>4}{'intent$':>10}{'$/day':>8}{'fill':>7}"
           f"{'ROI@own':>9}{'ROI@ask':>9}{'EV/int':>9}{'EV$/day':>9}  CI(EV/int)")
    print(hdr)
    cells = {}
    for lane in ("BANKROLL_200", "STANDARD"):
        for nm in NAMES:
            ls = [l for l in enriched if l["botId"] == lane and l["band"] == nm]
            if not ls:
                continue
            cells[(lane, nm)] = ls
            n, n_, p = agg(ls, lambda l: l["entryPrice"])
            ev = ev_intent(ls, lambda l: l["entryPrice"])
            lo, hi = boot_ev(ls, lambda l: l["entryPrice"])
            rf = roi_filled(ls, lambda l: l["entryPrice"])
            ra = roi_filled(ls, lambda l: l["mkt_ask"])
            fr = fill_rate(ls)
            print(f"  {lane:<14}{nm:<11}{n:>4}{n_:>10,.0f}{n_ / days:>8.1f}"
                  f"{(100 * fr if fr is not None else float('nan')):>6.0f}%"
                  f"{(100 * rf if rf is not None else 0):>8.1f}%"
                  f"{(100 * ra if ra is not None else 0):>8.1f}%"
                  f"{100 * ev:>8.1f}%{p / days:>9.1f}  [{100 * lo:+.1f},{100 * hi:+.1f}]")
    for lane in ("BANKROLL_200", "STANDARD"):
        ls = [l for l in enriched if l["botId"] == lane]
        n, n_, p = agg(ls, lambda l: l["entryPrice"])
        ev = ev_intent(ls, lambda l: l["entryPrice"])
        print(f"  {lane + ' TOTAL':<25}{n:>4}{n_:>10,.0f}{n_ / days:>8.1f}"
              f"{(100 * fill_rate(ls)):>6.0f}%{100 * roi_filled(ls, lambda l: l['entryPrice']):>8.1f}%"
              f"{100 * roi_filled(ls, lambda l: l['mkt_ask']):>8.1f}%{100 * ev:>8.1f}%{p / days:>9.1f}")

    # ---------------------------------------------------------------- S3
    print("\n" + "-" * 96)
    print("S3. THE ALLOCATION MISMATCH — share of intent dollars vs share of EV dollars")
    print("-" * 96)
    tot_ev = sum(ev_dollars(ls, lambda l: l["entryPrice"]) for ls in cells.values())
    tot_ev_d = sum(ev_dollars(ls, lambda l: l["entryPrice"]) / days for ls in cells.values())
    print(f"  daily EV of the mapped book: ${tot_ev_d:+.2f}/day on ${tot_ntl / days:,.0f}/day of intent notional")
    print(f"  {'cell':<26}{'$ share':>9}{'EV$ share':>11}{'EV$/day':>10}{'EV/int':>9}")
    rows = []
    for k, ls in cells.items():
        _, n_, p = agg(ls, lambda l: l["entryPrice"])
        rows.append((f"{k[0]}/{k[1]}", n_ / tot_ntl, (p / tot_ev) if tot_ev else 0.0, p / days,
                     (p / n_) if n_ else 0.0))
    for r in sorted(rows, key=lambda r: r[3]):
        print(f"  {r[0]:<26}{100 * r[1]:>8.1f}%{100 * r[2]:>10.1f}%{r[3]:>10.2f}{100 * r[4]:>8.1f}%")

    # ---------------------------------------------------------------- S4
    print("\n" + "-" * 96)
    print("S4. SHADOWS — what closing or capping the losing cells is worth per day (no re-selection)")
    print("-" * 96)
    base = tot_ev_d
    losers = sorted(rows, key=lambda r: r[3])[:3]
    print(f"  baseline: ${base:+.2f}/day\n")
    for nm, _, _, evd, _evi in losers:
        lane, band = nm.split("/")
        ls = cells[(lane, band)]
        _, n_, p = agg(ls, lambda l: l["entryPrice"])
        print(f"  zero the cell  {nm:<26} drops ${n_ / days:>6.0f}/day of intent,"
              f" EV {evd:+.2f} -> 0.00  = {-evd:+.2f}/day")
        # clip cap shadow: linear rescale of every clip above the cap
        for cap in (25.0, 15.0):
            if not any(ntl(l) > cap for l in ls):
                continue
            # rescale each leg's stake to min(size, cap): pnl scales linearly
            p_cap = sum(pnl_at(l, l["entryPrice"]) * (min(ntl(l), cap) / ntl(l)) for l in ls if ntl(l))
            n_cap = sum(min(ntl(l), cap) for l in ls)
            print(f"  cap clips @${cap:<5.0f} {nm:<26} drops ${(n_ - n_cap) / days:>6.0f}/day of intent,"
                  f" EV {evd:+.2f} -> {p_cap / days:+.2f}  = {(p_cap - p) / days:+.2f}/day")
    best = max(rows, key=lambda r: r[3])
    print(f"\n  best cell by EV$/day: {best[0]}  ({best[3]:+.2f}/day on "
          f"${sum(ntl(l) for l in cells[tuple(best[0].split('/'))]) / days:,.0f}/day)")

    # ---------------------------------------------------------------- S5
    print("\n" + "-" * 96)
    print("S5. CAPITAL VELOCITY — capital-days consumed vs EV returned (owned legs only)")
    print("-" * 96)
    print(f"  {'band':<12}{'owned':>7}{'cost':>9}{'EV$':>9}{'cap-days':>10}{'$/cap-day':>11}{'hold d':>8}")
    for nm in NAMES:
        ls = [l for l in enriched if l.get("band") == nm and owned(l)]
        if not ls:
            continue
        cost = sum(ntl(l) for l in ls)
        p = sum(pnl_at(l, l["entryPrice"]) for l in ls)
        cd = 0.0
        for l in ls:
            end = l.get("closedTs") or l.get("resolvedTs") or l["openedTs"]
            cd += ntl(l) * max(1.0 / 24.0, (end - l["openedTs"]) / 86400000.0)
        print(f"  {nm:<12}{len(ls):>7}{cost:>9,.0f}{p:>9.1f}{cd:>10,.0f}"
              f"{(p / cd if cd else 0):>11.2f}{(cd / cost if cost else 0):>8.1f}")

    # ---------------------------------------------------------------- S6
    print("\n" + "-" * 96)
    print("S6. STABILITY — same cells, first half vs second half of the window by openedAt")
    print("-" * 96)
    ts = sorted(l["openedTs"] for l in enriched)
    mid = ts[len(ts) // 2]
    print(f"  split at {__import__('datetime').datetime.utcfromtimestamp(mid / 1000).strftime('%Y-%m-%d %H:%M')} UTC")
    print(f"  {'band':<12}{'n1':>5}{'EV1':>8}{'n2':>5}{'EV2':>8}   read")
    for nm in NAMES:
        a1 = [l for l in enriched if l.get("band") == nm and l["openedTs"] < mid]
        a2 = [l for l in enriched if l.get("band") == nm and l["openedTs"] >= mid]
        if not a1 and not a2:
            continue
        e1 = 100 * ev_intent(a1, lambda l: l["entryPrice"]) if a1 else float("nan")
        e2 = 100 * ev_intent(a2, lambda l: l["entryPrice"]) if a2 else float("nan")
        sign = "same sign" if (e1 == e1 and e2 == e2 and (e1 >= 0) == (e2 >= 0)) else "SIGN FLIP"
        print(f"  {nm:<12}{len(a1):>5}{e1:>7.1f}%{len(a2):>5}{e2:>7.1f}%   {sign}")

    # ---------------------------------------------------------------- S7
    print("\n" + "-" * 96)
    print("S7. FILLABILITY — ROI on the owned class at the ask, then +1c/+2c/+3c of slippage")
    print("-" * 96)
    print(f"  {'band':<12}{'owned':>7}{'@ask':>9}{'+1c':>9}{'+2c':>9}{'+3c':>9}   breakeven slip")
    for nm in NAMES:
        ls = [l for l in enriched if l.get("band") == nm]
        f = [l for l in ls if owned(l)]
        if not f:
            continue
        r = []
        for k in (0.0, 0.01, 0.02, 0.03):
            p = sum(te.pnl_at(l, min(0.999, l["mkt_ask"] + k)) for l in f)
            r.append(100 * p / sum(ntl(l) for l in f))
        be = "n/a"
        for i in range(1, 4):
            if r[0] > 0 >= r[i]:
                be = f"~+{i}c"
                break
        print(f"  {nm:<12}{len(f):>7}{r[0]:>8.1f}%{r[1]:>8.1f}%{r[2]:>8.1f}%{r[3]:>8.1f}%   {be}")

    # ---------------------------------------------------------------- S8
    print("\n" + "-" * 96)
    print("S8. THE CENSORED POOL — candidates the entry-price ceiling refuses (never acted, never marked)")
    print("-" * 96)
    try:
        pca = _mod("pca", os.path.join(HERE, "profit-cheap-ask.py"))
        cens = censored_pool(a.min_rule, allow_fetch=not a.no_fetch)
        if cens:
            print(f"  skipped decisions at price >= 0.85 in the regime: {len(cens)}")
            res = [x for x in cens if x["winner"]]
            print(f"  resolvable against the venue archive: {len(res)} of {len(cens)}"
                  f"  ({len(res) / len(cens) * 100:.0f}%)")
            for tag, ls in (("all", res),
                            ("0.85-0.90", [x for x in res if x["px"] < 0.90]),
                            ("0.90-0.95", [x for x in res if 0.90 <= x["px"] < 0.95]),
                            ("0.95+", [x for x in res if x["px"] >= 0.95])):
                if not ls:
                    continue
                w = sum(1 for x in ls if x["win"])
                avgp = sum(x["px"] for x in ls) / len(ls)
                ev = sum(((1 - x["px"]) / x["px"]) if x["win"] else -1.0 for x in ls) / len(ls)
                ev1 = sum(((1 - min(0.999, x["px"] + 0.01)) / min(0.999, x["px"] + 0.01))
                          if x["win"] else -1.0 for x in ls) / len(ls)
                print(f"  {tag:<10} n={len(ls):>3}  hit {100 * w / len(ls):>5.1f}%  avg price {avgp:.3f}"
                      f"  breakeven {100 * avgp:>5.1f}%  EV/$1 {100 * ev:>+6.1f}%  at +1c {100 * ev1:>+6.1f}%")
            print("  read: EV/$1 > 0 with hit > price means the ceiling censors a paying population;"
                  " EV/$1 <= 0 means the ceiling is doing its job.")
        else:
            print("  none found (no skips above 0.85 with a resolvable market)")
    except Exception as exc:  # noqa: BLE001 - instrument must not die on a fetch failure
        print(f"  SKIPPED: {exc}")

    # ---------------------------------------------------------------- S9
    print("\n" + "-" * 96)
    print("S9. INSIDE THE WORST CELL — C-200 0.00-0.20 by clip tier (owned only, tape)")
    print("-" * 96)
    cheap = [l for l in enriched if l["botId"] == "BANKROLL_200" and l.get("band") == "0.00-0.20"]
    print(f"  {'tier':<12}{'legs':>6}{'owned':>7}{'cost':>9}{'EV$':>9}{'EV/int':>9}{'hit':>7}{'avg p':>8}")
    for tag, lo, hi in (("<$25", 0.0, 25.0), ("$25-50", 25.0, 50.0), (">=$50", 50.0, 1e9)):
        ls = [l for l in cheap if lo <= ntl(l) < hi]
        if not ls:
            continue
        _, n_, p = agg(ls, lambda l: l["entryPrice"])
        own = [l for l in ls if owned(l)]
        w = sum(1 for l in own if (te.pnl_at(l, l["entryPrice"]) or 0) > 0)
        avgp = sum(l["entryPrice"] for l in own) / len(own) if own else 0.0
        print(f"  {tag:<12}{len(ls):>6}{len(own):>7}{n_:>9,.0f}{p:>9.1f}"
              f"{100 * (p / n_ if n_ else 0):>8.1f}%{(100 * w / len(own) if own else 0):>6.0f}%{avgp:>8.3f}")
    print("  cap shadow with the tail removed (linear rescale above the cap, same legs):")
    for cap in (25.0, 15.0):
        rows_c = [(l, min(ntl(l), cap) / ntl(l)) for l in cheap if ntl(l)]
        contrib = sorted((pnl_at(l, l["entryPrice"]) * f for l, f in rows_c), reverse=True)
        p_cap = sum(contrib)
        ex3 = sum(contrib[3:])
        print(f"    cap ${cap:<4.0f}  EV {p_cap / days:+.2f}/day  ex-top-3 {ex3 / days:+.2f}/day"
              f"  ({(p_cap - sum(pnl_at(l, l['entryPrice']) for l in cheap)) / days:+.2f}/day vs actual)")

    # ---------------------------------------------------------------- selftests
    print("\n" + "=" * 96)
    uniq = len({(l["botId"], l["walletAddress"], l["marketId"], l["outcome"]) for l in enriched})
    chk("population is deduped (one leg per bot|wallet|market|outcome)", uniq == len(enriched),
        f"{uniq} unique of {len(enriched)}")
    ident = max((abs(pnl_at(l, l["entryPrice"]) - (l["realizedPnl"] or 0.0)) for l in enriched
                 if owned(l) and l.get("fillStatus") != "unfilled"), default=0.0)
    chk("re-pricing at the booked entry reproduces booked PnL on owned, unmasked legs",
        ident < 1e-6, f"max |diff| {ident:.2e}")
    shares = sum(r[1] for r in rows)
    chk("intent shares sum to 1", abs(shares - 1.0) < 1e-9, f"{shares:.12f}")
    zero = sum(ev_dollars(ls, lambda l: l["entryPrice"]) for ls in cells.values())
    chk("cell EV sums to the book EV", abs(zero - tot_ev) < 1e-6, f"{zero:.6f} vs {tot_ev:.6f}")
    chk("no cell was assigned a band it cannot have",
        all(l["band"] is not None for l in enriched))
    print("=" * 96)
    print(f"self-checks: {'all PASS' if not FAIL else str(len(FAIL)) + ' FAIL'}")
    return 0 if not FAIL else 1


def selftest():
    """Synthetic checks of the arithmetic, independent of the DB."""
    print("MARGINAL CELL — self-test")
    leg = lambda size, entry, exit_p, tv="filled_tape", mkt="m1": dict(
        simulatedPositionSize=size, entryPrice=entry, exit_px=exit_p, tv=tv, marketId=mkt,
        realizedPnl=size * (exit_p / entry - 1.0), status="resolved",
        fillStatus=None if tv == "filled_tape" else "unfilled")
    ls = [leg(100, 0.20, 0.0), leg(100, 0.80, 1.0), leg(50, 0.50, 0.0, tv="unfilled_tape")]
    # owned: -100 (0.20 -> 0) and +25 (0.80 -> 1.0) = -75 ; all intent notional 250
    chk("EV/intent = owned PnL / all intent notional",
        abs(ev_intent(ls, lambda l: l["entryPrice"]) + 75.0 / 250.0) < 1e-9,
        f"{ev_intent(ls, lambda l: l['entryPrice']):.4f}")
    chk("an unowned leg contributes no PnL",
        abs(pnl_at(ls[2], 0.5)) < 1e-12)
    chk("fill rate uses adjudicable legs only",
        abs(fill_rate(ls) - 2 / 3) < 1e-9, f"{fill_rate(ls):.4f}")
    chk("band_of boundaries", band_of(0.20) == "0.20-0.40" and band_of(0.0) == "0.00-0.20"
        and band_of(0.80) == "0.80-1.01" and band_of(1.0) == "0.80-1.01")
    # clip cap rescale: cap at $25 halves both stakes -> owned pnl -25 + 6.25 = -18.75
    cap = 25.0
    p_cap = sum(pnl_at(l, l["entryPrice"]) * (min(ntl(l), cap) / ntl(l)) for l in ls if ntl(l))
    chk("clip-cap shadow rescales linearly", abs(p_cap - (-18.75)) < 1e-9, f"{p_cap:+.2f}")
    chk("market-clustered CI is ordered", (lambda ci: ci[0] <= ci[1])(boot_ev(ls, lambda l: l["entryPrice"], reps=50)))
    print(f"self-checks: {'all PASS' if not FAIL else str(len(FAIL)) + ' FAIL'}")
    return 0 if not FAIL else 1


if __name__ == "__main__":
    sys.exit(main())
