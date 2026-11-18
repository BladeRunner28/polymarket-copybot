#!/usr/bin/env python3
"""
FAST ADVERSE-STOP REPLAY — is the +5m / down>=8% stop a rule, or a timing artifact?

WHY THIS EXISTS
---------------
drafts/profit-recs-20261118.md R1 proposes exiting an owned leg when the leg-side bid at +5m is
>=8% below the fill, measured at +$630 / 21 days in-sample. That number comes from
scripts/profit-taker-entry.py S10. This script does not re-propose it: it re-derives the SAME
cell and then tries to break it, because a stop of this shape (fast, unconditional, priced at a
mark) fails in four specific ways and each one is measurable:

  1. POPULATION   the cell can only speak for legs that have tape; if the no-tape owned legs
                  carry a different PnL, "+0.6% on the owned class" is an extrapolation.
  2. HORIZON      the mark at "+5m" is the last tape point at or before t0+300s. If that point is
                  usually 10s after the fill, the rule is "exit immediately on a tick", not
                  "the damage accrues over 5 minutes".
  3. TAIL         a stop that pays only because three legs collapsed is a tail cut.
  4. EXIT PRICE   the exit is priced at mid - half the quoted spread with zero slippage and no
                  taker fee. A stop is an aggressive sell; price it 1c and 2c worse.

Every figure is read-only: DB mode=ro, no RuleSet write, no prisma write. Reuses the fill-tape
cache (data/fill-tape-cache) via scripts/profit-fill-tape.py.

RUN
  python3 scripts/profit-fast-stop-replay.py
  python3 scripts/profit-fast-stop-replay.py --lag=300 --thr=0.08
  python3 scripts/profit-fast-stop-replay.py --selftest
"""
import argparse
import importlib.util
import os
import random
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
te = _mod("te", os.path.join(HERE, "profit-taker-entry.py"))

BANDS = ((0.0, 0.10), (0.10, 0.20), (0.20, 0.40), (0.40, 0.60), (0.60, 0.80), (0.80, 1.01))
FAIL = []


def chk(label, ok, detail=""):
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}" + (f" — {detail}" if detail else ""))
    if not ok:
        FAIL.append(label)
    return ok


def flag(label, detail=""):
    """A finding about the RULE, not a defect in the instrument. Never affects the exit code."""
    print(f"  [FLAG] {label}" + (f" — {detail}" if detail else ""))
    return False


# ------------------------------------------------------------------ the stop, priced three ways

def mark_at(l, lag_s):
    """Last tape midpoint at or before t0+lag, minus half the quoted spread = the leg-side bid.

    Identical to profit-taker-entry.py S10 so the headline reproduces rather than re-inventing.
    """
    s = l.get("tape_series")
    if not s:
        return None
    t0s = l["openedTs"] // 1000
    sub = [p for t, p in s if t <= t0s + lag_s]
    if len(sub) < 2:
        return None
    return max(0.001, min(0.999, sub[-1] - l["mkt_spread"] / 2.0))


def mark_age(l, lag_s):
    """How far BEFORE the nominal horizon the mark actually sits, in seconds."""
    s = l.get("tape_series")
    if not s:
        return None
    t0s = l["openedTs"] // 1000
    sub = [t for t, p in s if t <= t0s + lag_s]
    if len(sub) < 2:
        return None
    return sub[-1] - t0s


def stop_value(l, lag_s, thr, slip=0.0, basis="bid", always=False, trig="bid"):
    """Value of the leg under the stop rule.

    `trig` is the price the -thr test is read on: "bid" (the carded form: mid - half the quoted
    spread) or "mid" (a real adverse MOVE). `basis` is the price the exit books at. The two are
    separate because on a wide book the bid sits well under the mid before anything moves.
    """
    m = mark_at(l, lag_s)
    if m is None:
        return te.pnl_at(l, l["trueP"]), False, None
    trig_px = m + l["mkt_spread"] / 2.0 if trig == "mid" else m
    fired = always or trig_px <= l["trueP"] * (1.0 - thr)
    if not fired:
        return te.pnl_at(l, l["trueP"]), False, m
    px = m + l["mkt_spread"] / 2.0 if basis == "mid" else m
    px = max(0.001, min(0.999, px - slip))
    return l["simulatedPositionSize"] * (px / l["trueP"] - 1.0), True, m


def delta_ci(legs, lag_s, thr, n=2000, seed=13, **kw):
    """Market-clustered paired bootstrap on the DELTA (stop minus hold), in dollars."""
    by = {}
    for l in legs:
        g = by.setdefault(l["marketId"], [0.0, 0.0])
        g[0] += stop_value(l, lag_s, thr, **kw)[0]
        g[1] += te.pnl_at(l, l["trueP"])
    ks = list(by)
    if len(ks) < 2:
        return None, None, len(ks)
    rnd = random.Random(seed)
    out = []
    for _ in range(n):
        d = 0.0
        for _ in range(len(ks)):
            s, h = by[ks[rnd.randrange(len(ks))]]
            d += s - h
        out.append(d)
    out.sort()
    return out[int(0.025 * len(out))], out[int(0.975 * len(out)) - 1], len(ks)


def sum_pnl(rows):
    return sum(v for _, v, _, _ in rows)


def hold_pnl(legs):
    return sum(te.pnl_at(l, l["trueP"]) for l in legs)


def pct(a, b):
    return f"{(a / b * 100.0):+.1f}%" if b else "n/a"


# ------------------------------------------------------------------ main

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lag", type=int, default=300)
    ap.add_argument("--thr", type=float, default=0.08)
    ap.add_argument("--min-rule", type=int, default=68)
    ap.add_argument("--workers", type=int, default=8)
    a = ap.parse_args()

    print("=" * 96)
    print("FAST ADVERSE-STOP REPLAY — re-derive the +5m/-8% cell, then try to break it")
    print("=" * 96)

    legs = [l for l in ft.load("2026-09-01") if (l.get("rv") or 0) >= a.min_rule]
    ft.classify(legs, workers=a.workers)
    settled = [l for l in legs if l["status"] != "open"]
    S, stats = te.enrich(settled, 300)
    P = [l for l in S if l["is_pos"]]
    owned = [l for l in P if l.get("tape_series") and l.get("exit_px") is not None]
    ts = sorted(l["openedTs"] for l in settled)
    days = max((ts[-1] - ts[0]) / 86400000.0, 0.5)
    print(f"\n  regime v{a.min_rule}+, deduped, non-demo: {len(legs)} legs, window {days:.1f} days")
    print(f"  settled {len(settled)} · quoted book mapped {len(S)} · positions {len(P)} "
          f"(${sum(l['simulatedPositionSize'] for l in P):,.0f}) · owned with tape+exit {len(owned)}")

    hold_all = hold_pnl(owned)
    cost_all = sum(l["simulatedPositionSize"] for l in owned)

    # ---------------------------------------------------------------- C1 population
    print("\n" + "-" * 96)
    print("C1. POPULATION — who can the stop even speak for?")
    print("-" * 96)
    no_tape = [l for l in P if not (l.get("tape_series") and l.get("exit_px") is not None)]
    print(f"  owned legs WITH tape+exit     {len(owned):>4}  cost ${cost_all:>7.0f}  "
          f"hold {hold_all:>+9.1f}  {pct(hold_all, cost_all)}")
    if no_tape:
        nt = sum(l["simulatedPositionSize"] for l in no_tape)
        hp = sum((l.get("realizedPnl") or 0.0) for l in no_tape)
        print(f"  owned legs WITHOUT tape/exit  {len(no_tape):>4}  cost ${nt:>7.0f}  "
              f"hold {hp:>+9.1f}  {pct(hp, nt)}")
    print(f"  positions the resolver ever stamped unfilled are excluded upstream: "
          f"{sum(1 for l in S if not l['is_pos'])} legs")
    chk("the stoptable population covers >=90% of owned cost",
        cost_all >= 0.90 * sum(l["simulatedPositionSize"] for l in P),
        f"{cost_all / max(1e-9, sum(l['simulatedPositionSize'] for l in P)) * 100:.1f}% of cost")
    zero = [l for l in owned if abs(l.get("realizedPnl") or 0.0) < 1e-9]
    print(f"  rows booking EXACTLY $0 PnL (hold is valued at the booked entry, so a real outcome")
    print(f"  would be invisible): {len(zero)} of {len(owned)}"
          + (f" — resolving={sum(1 for l in zero if l['status'] == 'resolved')}" if zero else ""))
    if zero:
        chk("no position leg is valued at a convention-zero exit", len(zero) <= 0.02 * len(owned),
            f"{len(zero)}/{len(owned)} at $0")

    # ---------------------------------------------------------------- C2 the horizon
    print("\n" + "-" * 96)
    print(f"C2. THE HORIZON — where does the '+{a.lag // 60}m' mark actually sit?")
    print("-" * 96)
    ages = sorted(x for x in (mark_age(l, a.lag) for l in owned) if x is not None)
    if ages:
        def q(p):
            return ages[min(len(ages) - 1, int(p * len(ages)))]
        print(f"  n={len(ages)}  mark age after fill: p10 {q(0.1)}s  median {q(0.5)}s  "
              f"p90 {q(0.9)}s  max {ages[-1]}s")
        print(f"  share of marks <60s after the fill: {sum(1 for x in ages if x < 60) / len(ages) * 100:.0f}%"
              f"   <120s: {sum(1 for x in ages if x < 120) / len(ages) * 100:.0f}%"
              f"   >=240s: {sum(1 for x in ages if x >= 240) / len(ages) * 100:.0f}%")
        stale = sum(1 for x in ages if x < 60)
        chk("the '+5m' mark is a +5m mark on the legs it prices (age >=240s)",
            sum(1 for x in ages if x >= 240) >= 0.5 * len(ages),
            f"{sum(1 for x in ages if x >= 240) / len(ages) * 100:.0f}% at >=240s, "
            f"{stale / len(ages) * 100:.0f}% <60s")

    # ---------------------------------------------------------------- C3 headline + CI
    print("\n" + "-" * 96)
    print(f"C3. HEADLINE — stop at +{a.lag // 60}m / down>={a.thr * 100:.0f}%, priced at the bid")
    print("-" * 96)
    rows = []
    for l in owned:
        v, fired, m = stop_value(l, a.lag, a.thr)
        rows.append((l, v, fired, m))
    stop_p = sum_pnl(rows)
    delta = stop_p - hold_all
    lo, hi, nmk = delta_ci(owned, a.lag, a.thr)
    nfire = sum(1 for _, _, f, _ in rows if f)
    print(f"  hold to the leg's own exit   {len(rows):>4} legs  ${cost_all:>7.0f}  "
          f"{hold_all:>+9.1f}  {pct(hold_all, cost_all)}")
    print(f"  with the stop                {len(rows):>4} legs  ${cost_all:>7.0f}  "
          f"{stop_p:>+9.1f}  {pct(stop_p, cost_all)}")
    print(f"  DELTA                        {nfire:>4} stopped ({nfire / len(rows) * 100:.1f}%)  "
          f"{delta:>+9.1f}  {pct(delta, cost_all)}  "
          f"market-clustered 95% CI [{lo:+.0f},{hi:+.0f}] over {nmk} markets")
    print(f"  per 21.1 days at this window: {delta / days * 21.1:+.1f}   per day: {delta / days:+.2f}")
    chk("the delta's market-clustered CI excludes zero", lo is not None and lo > 0,
        f"[{lo:+.0f},{hi:+.0f}]" if lo is not None else "n/a")
    print("  a CI that includes zero is not a refutation by itself at n=250 — it is the reason the")
    print("  pre-registered forward leg count exists. It IS a reason not to quote '+$630' as a fact.")

    # ---------------------------------------------------------------- C4 tail
    print("\n" + "-" * 96)
    print("C4. TAIL — is the delta three legs or a class?")
    print("-" * 96)
    d_legs = sorted(((v - te.pnl_at(l, l["trueP"]), l) for l, v, _, _ in rows),
                    key=lambda t: -t[0])
    tot = sum(d for d, _ in d_legs)
    for k in (1, 3, 5, 10):
        print(f"  ex-top-{k:<2} delta {sum(d for d, _ in d_legs[k:]):>+9.1f}  "
              f"({sum(d for d, _ in d_legs[k:]) / max(1e-9, abs(tot)) * 100:>5.0f}% of the delta)")
    print(f"  profitable-vs-losing contributions: positive deltas {sum(d for d, _ in d_legs if d > 0):+.1f} "
          f"on {sum(1 for d, _ in d_legs if d > 0)} legs, negative {sum(d for d, _ in d_legs if d < 0):+.1f} "
          f"on {sum(1 for d, _ in d_legs if d < 0)} legs")
    print("\n  the five legs the stop helped most (a rule that rests on these is a tail cut):")
    print(f"  {'market':<18} {'lane':<13} {'entry':>6} {'+5m bid':>8} {'final exit':>10} "
          f"{'ntl':>6} {'delta':>8}")
    for d, l in d_legs[:5]:
        v, fired, m = stop_value(l, a.lag, a.thr)
        print(f"  {str(l['marketId'])[:18]:<18} {l['botId']:<13} {l['trueP']:>6.3f} "
              f"{(m if m is not None else float('nan')):>8.3f} {l['exit_px']:>10.3f} "
              f"{l['simulatedPositionSize']:>6.1f} {d:>+8.1f}")

    # ---------------------------------------------------------------- C5 the stopped legs
    print("\n" + "-" * 96)
    print("C5. THE STOPPED LEGS — was the stop right on each one?")
    print("-" * 96)
    fired = [(l, v, m) for l, v, f, m in rows if f]
    helped = [(l, v, m) for l, v, m in fired if v > te.pnl_at(l, l["trueP"]) + 1e-9]
    hurt = [(l, v, m) for l, v, m in fired if v <= te.pnl_at(l, l["trueP"]) + 1e-9]
    print(f"  stopped {len(fired)}  ·  stop beat holding on {len(helped)}  ·  stop cost money on "
          f"{len(hurt)}  ({len(hurt) / max(1, len(fired)) * 100:.0f}% of fires wrong)")
    print(f"  sum helped {sum(v - te.pnl_at(l, l['trueP']) for l, v, _ in helped):>+9.1f}  "
          f"sum hurt {sum(v - te.pnl_at(l, l['trueP']) for l, v, _ in hurt):>+9.1f}")
    wins = [l for l, v, m in fired if l["exit_px"] is not None and l["exit_px"] >= 0.995]
    print(f"  stopped legs that went on to WIN at settlement (exit>=0.995): {len(wins)}"
          + (f" — cost {sum(l['simulatedPositionSize'] * (1.0 / l['trueP'] - 1.0) * -1 for l in wins):+.1f} "
             f"of forgone PnL" if wins else ""))
    if fired:
        ex = sorted(l["exit_px"] for l, _, _ in fired if l["exit_px"] is not None)
        mk = sorted(m for _, _, m in fired)
        print(f"  stopped legs' final exit price: p10 {ex[int(0.1 * len(ex))]:.3f}  "
              f"median {ex[len(ex) // 2]:.3f}  p90 {ex[int(0.9 * len(ex))]:.3f}"
              f"   (their +5m marks: median {mk[len(mk) // 2]:.3f})")

    # ---------------------------------------------------------------- C5b trigger anatomy
    print("\n" + "-" * 96)
    print("C5b. TRIGGER ANATOMY — is '-8% at the bid' an adverse MOVE, or is it the spread?")
    print("-" * 96)
    print("  the trigger is read at mid - half the quoted spread, so on a wide book the bid sits")
    print("  below the fill before anything moves. Decompose each stopped leg:")
    print(f"  {'entry':>6} {'+5m mid':>8} {'mid move':>9} {'half-spread':>12} {'trigger':>8} "
          f"{'final':>6} {'ntl':>6}")
    mid_moves = []
    for l, v, m in fired:
        mid5 = min(0.999, m + l["mkt_spread"] / 2.0)
        mv = mid5 / l["trueP"] - 1.0
        hs = (l["mkt_spread"] / 2.0) / l["trueP"]
        mid_moves.append(mv)
        print(f"  {l['trueP']:>6.3f} {mid5:>8.3f} {mv * 100:>+8.1f}% {hs * 100:>11.1f}% "
              f"{(m / l['trueP'] - 1.0) * 100:>+7.1f}% {(l['exit_px'] or 0):>6.3f} "
              f"{l['simulatedPositionSize']:>6.0f}")
    if mid_moves:
        mm = sorted(mid_moves)
        print(f"  median MID move at +5m on stopped legs: {mm[len(mm) // 2] * 100:+.1f}%  "
              f"(median half-spread {sorted((l['mkt_spread'] / 2.0) / l['trueP'] for l, _, _ in fired)[len(fired) // 2] * 100:.1f}%)")
        nonmove = sum(1 for x in mid_moves if x > -a.thr)
        print(f"  stopped legs whose MID did NOT move {a.thr * 100:.0f}% (trigger is pure spread): "
              f"{nonmove} of {len(mid_moves)}")
        flag("the -8% trigger fires on the SPREAD on a large share of its legs, not on a move",
             f"{nonmove}/{len(mid_moves)} of the fires are spread-only — read the rule as 'sell a "
             f"cheap leg at its bid', not 'cut a mover'") if nonmove > 0.25 * len(mid_moves) else None
        if nonmove <= 0.25 * len(mid_moves):
            print("  [PASS] the -8% trigger is a real mid move on most stopped legs")

    # ---------------------------------------------------------------- C5c clip size
    print("\n" + "-" * 96)
    print("C5c. CLIP SIZE — how much of the delta is the $100 C-200 clip rather than the rule?")
    print("-" * 96)
    for lo_c, hi_c in ((0.0, 25.0), (25.0, 60.0), (60.0, 100.1)):
        sub = [(l, v) for l, v, f, _ in rows if lo_c <= l["simulatedPositionSize"] < hi_c]
        if not sub:
            continue
        h = sum(te.pnl_at(l, l["trueP"]) for l, _ in sub)
        s = sum(v for _, v in sub)
        nf = sum(1 for l, v, f, _ in rows if f and lo_c <= l["simulatedPositionSize"] < hi_c)
        c = sum(l["simulatedPositionSize"] for l, _ in sub)
        print(f"  clip ${lo_c:.0f}-{hi_c:.0f}   legs {len(sub):>4}  cost ${c:>6.0f}  hold {h:>+8.1f}  "
              f"stop {s:>+8.1f}  delta {s - h:>+8.1f}  ({nf} stopped)  "
              f"delta per $1 risked {(s - h) / c * 100:>+6.1f}%")
    print("  the delta scales linearly with clip size, so a rule that pays on a $100 mis-sized leg")
    print("  would pay a tenth as much on a $13 one: quote the delta per $1 of risk, not the total.")
    uni = 13.0
    d_uni = sum((v - te.pnl_at(l, l["trueP"])) * uni / l["simulatedPositionSize"] for l, v, _, _ in rows)
    c_uni = uni * len(rows)
    print(f"  normalised to a uniform ${uni:.0f} clip ({len(rows)} legs, ${c_uni:,.0f} of risk): "
          f"delta {d_uni:+.1f} = {d_uni / c_uni * 100:+.1f}% of risk  "
          f"(vs {delta:+.1f} = {delta / cost_all * 100:+.1f}% on the book as actually sized)")
    print("  THAT is what the rule is worth once the $100 C-200 clip is fixed — the two levers are")
    print("  substitutes on the same legs, not additive.")

    # ---------------------------------------------------------------- C13 trigger basis
    print("\n" + "-" * 96)
    print("C13. TRIGGER BASIS — the carded test is read at the BID; what if it is read at the MID?")
    print("-" * 96)
    print(f"  {'trigger basis':<30} {'exit books at':<14} {'fired':>6} {'pnl':>9} {'delta':>9} {'CI':>16}")
    for tag, trig, basis in (("bid  (as carded)", "bid", "bid"),
                             ("mid  (a real move)", "mid", "bid"),
                             ("mid  (a real move)", "mid", "mid")):
        rr = [stop_value(l, a.lag, a.thr, trig=trig, basis=basis) for l in owned]
        p5 = sum(v for v, _, _ in rr)
        lo5, hi5, _ = delta_ci(owned, a.lag, a.thr, trig=trig, basis=basis)
        print(f"  {tag:<30} {basis:<14} {sum(1 for _, f, _ in rr if f):>6} {p5:>+9.1f} "
              f"{p5 - hold_all:>+9.1f} {(f'[{lo5:+.0f},{hi5:+.0f}]' if lo5 is not None else 'n/a'):>16}")
    print("  the mid-trigger row is the honest test of the HYPOTHESIS ('the loss accrues fast');")
    print("  the bid-trigger row also fires on the half-spread, which is not a loss, it is a quote.")
    rr = [stop_value(l, a.lag, a.thr, trig="mid") for l in owned]
    fires = [(l, s[0]) for l, s in zip(owned, rr) if s[1]]
    hel = sum(1 for l, v in fires if v > te.pnl_at(l, l["trueP"]) + 1e-9)
    winc = sum(1 for l, _ in fires if l["exit_px"] is not None and l["exit_px"] >= 0.995)
    d_mid_u = sum((s[0] - te.pnl_at(l, l["trueP"])) * 13.0 / l["simulatedPositionSize"]
                  for l, s in zip(owned, rr))
    print(f"  mid-trigger discipline: {len(fires)} fires, stop beat hold on {hel}, "
          f"winners cut {winc}; delta at a uniform $13 clip {d_mid_u:+.1f} "
          f"({d_mid_u / (13.0 * len(owned)) * 100:+.1f}% of risk)")

    print("\n" + "-" * 96)
    print("C6. SCOPE — the delta by entry band and by lane (a stop that pays in one band only is a band rule)")
    print("-" * 96)
    print(f"  {'band':<12} {'legs':>4} {'fired':>6} {'hold':>9} {'d_bid':>8} {'CI':>16} "
          f"{'d_mid':>8} {'CI':>16} {'spread%':>8}")
    for lo_b, hi_b in BANDS:
        sub = [l for l in owned if lo_b <= l["trueP"] < hi_b]
        if len(sub) < 5:
            continue
        rr = [(l, v, f, m) for l, v, f, m in rows if lo_b <= l["trueP"] < hi_b]
        h = hold_pnl(sub)
        s = sum_pnl(rr)
        clo, chi, _ = delta_ci(sub, a.lag, a.thr)
        rm = [stop_value(l, a.lag, a.thr, trig="mid") for l in sub]
        sm = sum(v for v, _, _ in rm)
        mlo, mhi, _ = delta_ci(sub, a.lag, a.thr, trig="mid")
        sp = sorted(l["mkt_spread"] / l["trueP"] for l in sub)[len(sub) // 2]
        print(f"  {lo_b:.2f}-{hi_b:.2f}    {len(sub):>4} {sum(1 for _, _, f, _ in rr if f):>6} "
              f"{h:>+9.1f} {s - h:>+10.1f} "
              f"{(f'[{clo:+.0f},{chi:+.0f}]' if clo is not None else 'n/a'):>16} "
              f"{sm - h:>+10.1f} "
              f"{(f'[{mlo:+.0f},{mhi:+.0f}]' if mlo is not None else 'n/a'):>16} "
              f"{sp * 100:>7.1f}%")
    print("  delta(bid-) = trigger read at the bid (carded);  delta(mid-) = trigger read at the mid")
    print("\n  by lane:")
    for lane in ("BANKROLL_200", "STANDARD"):
        sub = [l for l in owned if l["botId"] == lane]
        if not sub:
            continue
        rr = [(l, v, f, m) for l, v, f, m in rows if l["botId"] == lane]
        h, s = hold_pnl(sub), sum_pnl(rr)
        clo, chi, _ = delta_ci(sub, a.lag, a.thr)
        print(f"    {lane:<14} legs {len(sub):>4}  hold {h:>+8.1f}  with stop {s:>+8.1f}  "
              f"delta {s - h:>+7.1f}  ({sum(1 for _, _, f, _ in rr if f)} stopped)  "
              f"CI {(f'[{clo:+.0f},{chi:+.0f}]' if clo is not None else 'n/a')}")

    # ---------------------------------------------------------------- C7 exit price
    print("\n" + "-" * 96)
    print("C7. EXIT PRICE — the stop is an aggressive sell; what does 1c of slippage do?")
    print("-" * 96)
    print(f"  {'exit assumption':<34} {'pnl':>9} {'delta vs hold':>14} {'CI on delta':>18}")
    for tag, slip, basis in (("bid (mid - half spread)   [base]", 0.0, "bid"),
                             ("bid - 1c slippage", 0.01, "bid"),
                             ("bid - 2c slippage", 0.02, "bid"),
                             ("mid (no spread paid) — optimistic ceiling", 0.0, "mid")):
        r2 = [stop_value(l, a.lag, a.thr, slip=slip, basis=basis) for l in owned]
        p2 = sum(v for v, _, _ in r2)
        lo2, hi2, _ = delta_ci(owned, a.lag, a.thr, slip=slip, basis=basis)
        print(f"  {tag:<34} {p2:>+9.1f} {p2 - hold_all:>+14.1f} "
              f"{(f'[{lo2:+.0f},{hi2:+.0f}]' if lo2 is not None else 'n/a'):>18}")
    print("  every row keeps the SAME trigger (the bid mark); only the exit price moves, so the")
    print("  rows measure execution quality. A taker fee on the exit is not in any row: the venue")
    print("  charges C*rate*p*(1-p) per share (~0.5c of price at p=0.45, rate 0.02), so the -1c row")
    print("  is the conservative proxy for fee + slippage together, not for slippage alone.")

    # ---------------------------------------------------------------- C8 trigger vs timing
    print("\n" + "-" * 96)
    print("C8. TRIGGER OR TIMING — how much of the delta is the threshold and how much is the clock?")
    print("-" * 96)
    for tag, lagx, thrx in ((f"exit EVERYTHING at +{a.lag // 60}m", a.lag, a.thr),
                            (f"stop +{a.lag // 60}m / >={a.thr * 100:.0f}%", a.lag, a.thr)):
        rr = [stop_value(l, lagx, thrx, always=(tag.startswith("exit EVERYTHING"))) for l in owned]
        p3 = sum(v for v, _, _ in rr)
        print(f"  {tag:<34} {p3:>+9.1f}  delta {p3 - hold_all:>+8.1f}  "
              f"({sum(1 for _, f, _ in rr if f)} fired)")
    print("  the difference between those two rows is what the -8% TRIGGER adds over a blanket")
    print("  5-minute exit; if the blanket exit carries most of it, the rule is 'flatten fast'.")

    # ---------------------------------------------------------------- C9 exits before the mark
    print("\n" + "-" * 96)
    print("C9. EXITS THAT PRECEDE THE MARK — a leg already closed before +5m cannot be stopped at +5m")
    print("-" * 96)
    early = []
    for l in owned:
        cl = ppi._ms(l["closedAt"]) if l.get("closedAt") else None
        rs = ppi._ms(l["resolvedAt"]) if l.get("resolvedAt") else None
        ex = min([x for x in (cl, rs) if x is not None], default=None)
        l["_exitTs"] = ex
        if ex is not None and ex - l["openedTs"] < a.lag * 1000:
            early.append(l)
    print(f"  owned legs whose own exit landed inside the {a.lag // 60}m window: {len(early)} of {len(owned)}")
    if early:
        rr = [(l, v, f, m) for l, v, f, m in rows if l not in early]
        p4 = sum(v for _, v, _, _ in rr)
        h4 = hold_pnl([l for l, _, _, _ in rr])
        print(f"  excluding them: hold {h4:+.1f}  with stop {p4:+.1f}  delta {p4 - h4:+.1f} "
              f"({sum(1 for _, _, f, _ in rr if f)} stopped)")
        print("  (those legs' stop arm re-prices an exit that had already happened — treat their")
        print("   contribution as unearned if the exclusion moves the delta materially.)")

    # ---------------------------------------------------------------- C10 does the mark predict
    print("\n" + "-" * 96)
    print("C10. DOES THE +5m MARK PREDICT THE FINAL EXIT? — the mechanism, not the arithmetic")
    print("-" * 96)
    pairs = [(mark_at(l, a.lag), l["exit_px"]) for l in owned
             if mark_at(l, a.lag) is not None and l["exit_px"] is not None]
    if len(pairs) > 20:
        n = len(pairs)
        mx = sum(p[0] for p in pairs) / n
        my = sum(p[1] for p in pairs) / n
        cov = sum((x - mx) * (y - my) for x, y in pairs)
        sx = sum((x - mx) ** 2 for x, _ in pairs) ** 0.5
        sy = sum((y - my) ** 2 for _, y in pairs) ** 0.5
        r = cov / (sx * sy) if sx and sy else None
        print(f"  Pearson r(+5m mark, final exit price) = {r:+.3f} on {n} legs")
        f_marks = [m for _, _, f, m in rows if f]
        f_ex = [l["exit_px"] for l, _, f, _ in rows if f]
        nf_marks = [m for l, _, f, m in rows if not f and m is not None]
        nf_ex = [l["exit_px"] for l, _, f, _ in rows if not f]
        print(f"  stopped legs   mean +5m mark {sum(f_marks) / len(f_marks):.3f}  "
              f"mean final exit {sum(f_ex) / len(f_ex):.3f}")
        print(f"  other legs     mean +5m mark {sum(nf_marks) / len(nf_marks):.3f}  "
              f"mean final exit {sum(nf_ex) / len(nf_ex):.3f}")
        chk("the +5m mark carries information about the final exit (|r| >= 0.30)", r is not None and abs(r) >= 0.30,
            f"r={r:+.3f}" if r is not None else "n/a")

    # ---------------------------------------------------------------- C11 stability
    print("\n" + "-" * 96)
    print("C11. STABILITY — is the delta one week, or the window?")
    print("-" * 96)
    t_mid = sorted(l["openedTs"] for l in owned)[len(owned) // 2]
    for tag, f in (("first half", lambda l: l["openedTs"] < t_mid),
                   ("second half", lambda l: l["openedTs"] >= t_mid)):
        sub = [l for l in owned if f(l)]
        rr = [(l, v, fi, m) for l, v, fi, m in rows if f(l)]
        h, s = hold_pnl(sub), sum_pnl(rr)
        print(f"  {tag:<12} legs {len(sub):>4}  hold {h:>+8.1f}  with stop {s:>+8.1f}  "
              f"delta {s - h:>+8.1f}  ({sum(1 for _, _, fi, _ in rr if fi)} stopped)")

    # ---------------------------------------------------------------- C12 multiplicity
    print("\n" + "-" * 96)
    print("C12. THE GRID WAS SEARCHED — 16 cells, and the best one was quoted")
    print("-" * 96)
    cells = []
    for lagx in (300, 900, 1800, 3600):
        for thrx in (0.03, 0.05, 0.08, 0.15):
            rr = [stop_value(l, lagx, thrx) for l in owned]
            cells.append((sum(v for v, _, _ in rr) - hold_all, lagx, thrx))
    pos = [c for c in cells if c[0] > 0]
    best = max(cells)
    print(f"  {len(pos)} of {len(cells)} cells positive; best +{best[1] // 60}m/{best[2] * 100:.0f}% "
          f"= {best[0]:+.1f}; the 60m row is {sum(1 for c in cells if c[1] == 3600 and c[0] > 0)}/4 positive")
    print("  the quoted cell is the MAX of 16 correlated cells. Its in-sample delta is optimistically")
    print("  biased by construction; only the pre-registered forward read settles it. State the cell")
    print("  as one of 16, never as a single hypothesis that was tested once.")

    print("\n" + "=" * 96)
    print(f"self-checks: {len(FAIL)} FAIL" if FAIL else "self-checks: all PASS")
    print("=" * 96)
    return 1 if FAIL else 0


def selftest():
    print("self-test: mark arithmetic, trigger boundary, slippage direction")
    leg = {"tape_series": [(1000, 0.50), (1300, 0.40), (1700, 0.60)],
           "openedTs": 1000 * 1000, "mkt_spread": 0.02, "trueP": 0.50,
           "simulatedPositionSize": 10.0, "exit_px": 1.0}
    # 8% of 0.50 = 0.54; bid at 0.40 - 0.01 = 0.39 -> fires
    v, fired, m = stop_value(leg, 300, 0.08)
    assert fired and abs(m - 0.39) < 1e-9, (fired, m)
    assert abs(v - 10.0 * (0.39 / 0.50 - 1.0)) < 1e-9
    # boundary: exactly 8% down must fire (<=), one tick better must not
    leg2 = dict(leg, tape_series=[(1000, 0.50), (1300, 0.46)])
    assert stop_value(leg2, 300, 0.08)[1] is True      # 0.45 == 0.50*0.92 -> fires
    leg3 = dict(leg, tape_series=[(1000, 0.50), (1300, 0.475)])
    assert stop_value(leg3, 300, 0.08)[1] is False     # bid 0.465 > 0.46 -> no fire
    # slippage makes the exit worse, never better
    leg4 = dict(leg, exit_px=0.20)
    assert stop_value(leg4, 300, 0.08, slip=0.02)[0] < stop_value(leg4, 300, 0.08)[0]
    # a leg with no tape can never fire
    assert stop_value(dict(leg, tape_series=[]), 300, 0.08)[1] is False
    # a mark before the horizon is the LAST point at or before it, never a later one
    assert abs(mark_at(dict(leg, tape_series=[(1000, 0.50), (1290, 0.41), (1900, 0.10)]), 300) - 0.40) < 1e-9
    print("  selftest OK")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
    else:
        sys.exit(main())
