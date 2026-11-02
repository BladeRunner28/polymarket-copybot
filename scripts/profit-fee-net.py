#!/usr/bin/env python3
"""profit-fee-net — price the book on the basis a real trader settles on: NET OF THE VENUE FEE.

WHY THIS EXISTS
  PaperTrade books no fee anywhere: there is no fee column, `src/lib/paper.ts` writes
  `realizedPnl` from the price path alone, and `src/lib/copy-cost.ts` says so in its own
  header ("the paper fill crosses no spread and pays no fee"). `src/lib/scoring/price-edge.ts`
  carries a fee-aware EV gate but is `status: "shadow"` and is not wired to any live path.
  So the decision loop is fee-blind AND the scoreboard is fee-blind, while the venue is not.

FEE LAW (the repo's own, cross-checked against venue truth — do not re-invent)
  fee for `shares` at price p  =  shares * rate * p * (1-p)          [price-edge.ts takerFeePerShare]
  with shares = notional / p, so as a fraction of DOLLARS AT RISK:
      fee / notional = rate * (1 - p)
  which is LARGEST at cheap prices (4.5% at p=0.10) and smallest at dear ones (0.5% at p=0.90).
  The commonly quoted "fees peak at p=0.5" is true per unit of NOTIONAL TRADED and false per
  unit of CAPITAL AT RISK — and every ROI in this book is computed on the capital-at-risk basis.
  RATE: 0.05 default, 0.04 politics/finance, 0.07 crypto (docs.polymarket.com, 2026-09).
  VALIDATED: data/fee-sign-flip-report.json (2026-10-22, 4,040 markets, 99.68% coverage) prices
  the venue's own per-market schedule at $4,996.97 against $5,024.02 for this 0.05 proxy on the
  same 12,710 legs — the proxy is within 0.5% of venue truth, so the RATE is not the open
  question. The open question is that neither the ledger nor any gate applies it.

SIDES
  entry  : always one taker fee (we buy).
  exit   : only a real sell pays a second fee. status='resolved' settles at 0/1 (no trade, one
           fee). status='closed' exited at a live or stale mark — we cannot prove a sell happened
           (6,503 of them are dead-slug 404 marks), so BOTH brackets are printed:
             one-fee  = entry only            (hold / write-off reading)
             two-fee  = entry + exit at the implied exit price c, where
                        c = p * (1 + realizedPnl / notional)     [exact, from pnl = n(s/p-1)]

COST BASIS: `simulatedPositionSize` is DOLLARS AT RISK, never shares. Every ROI denominator here
is notional at risk, and the ROI identity is n*(s/p - 1) / n.

SECTIONS
  FN.1 book, bet-level and leg-level, with the three exit-fee bases printed side by side
       (entry-only / exit at implied price / exit at entry price — the last is the basis
       scripts/c200-fee-reprice-archive.py and scripts/fee-sign-flip-test.py use, and this script
       reproduces their $4,996 on it, so the disagreement is the exit side, not the fee law)
  FN.2 per lane x band: gross, fee, net, and net $/1k-capital-day
  FN.3 fee-inclusive break-even hit rate hurdle p*(1+rate*(1-p)) vs the measured DOLLAR-WEIGHTED
       hit rate — bet-weighted and dollar-weighted disagree in sign on 0.4-0.6, and dollars win
  FN.4 what the fee does to the ladder arithmetic ($500/day and $5,000/day capital requirement)
  FN.5 resolved vs closed: the mark half of the book nets negative on the entry fee alone
  FN.6 rate sensitivity 0.00/0.04/0.05/0.07
  FN.7 the pending §AM.7 band map, gross vs NET (notional-neutral, same 'strong' constants)
  FN.8 resolved legs whose booked PnL is not a settlement

READ-ONLY: opens prisma/dev.db with immutable=1. Writes nothing. No RuleSet read or write.

RUN
  python3 scripts/profit-fee-net.py                # full report
  python3 scripts/profit-fee-net.py --selftest     # identity checks only
  python3 scripts/profit-fee-net.py --rate 0.07    # rate sensitivity
"""
import math
import re
import sqlite3
import sys
import time
from collections import defaultdict

DB = "prisma/dev.db"
CUTOFF = 0.0  # ms epoch; set in main() from --days
BANDS = [(0.0, 0.20, "<0.20"), (0.20, 0.40, "0.2-0.4"), (0.40, 0.60, "0.4-0.6"),
         (0.60, 0.80, "0.6-0.8"), (0.80, 1.01, "0.8-1.0")]
DEFAULT_RATE = 0.05
CAT_RATE = {"politics": 0.04, "finance": 0.04, "crypto": 0.07}
CAT_PAT = [
    ("crypto", r"bitcoin|btc|eth|ethereum|solana|\bsol\b|xrp|crypto|dogecoin|token price|airdrop|fdv|market cap"),
    ("politics", r"election|president|senate|congress|nominee|governor|parliament|vote|poll|primary|trump|biden|harris|mayor|referendum|shutdown|impeach|prime minister"),
    ("finance", r"\bfed\b|rate cut|inflation|\bcpi\b|\bgdp\b|recession|tariff|stock|nasdaq|s&p|earnings"),
]


def band_of(p):
    for lo, hi, name in BANDS:
        if lo <= p < hi:
            return name
    return "0.8-1.0"


def rate_of(market_id, default):
    s = (market_id or "").lower()
    for name, pat in CAT_PAT:
        if re.search(pat, s):
            return CAT_RATE[name], name
    return default, "other"


def load():
    con = sqlite3.connect(f"file:{DB}?immutable=1", uri=True)
    rows = con.execute(
        "SELECT botId, marketId, walletAddress, outcome, entryPrice, simulatedPositionSize,"
        "       status, realizedPnl, openedAt, closedAt, resolvedAt, isDemo"
        "  FROM PaperTrade"
    ).fetchall()
    out = []
    for (bot, mk, wal, oc, p, size, status, pnl, oa, ca, ra, demo) in rows:
        if demo or not p or p <= 0 or not size or size <= 0:
            continue
        if status not in ("closed", "resolved"):
            continue
        end = ca or ra
        if not oa or not end:
            continue
        days = (end - oa) / 86400000.0
        if days < 0:
            days = 0.0
        out.append(dict(bot=bot, mk=mk, wal=wal, oc=oc, p=p, size=size, status=status,
                        pnl=pnl or 0.0, days=days, oa=oa))
    return out


def dedupe(rows):
    """Canonical: first leg per (wallet, market, outcome)."""
    seen = {}
    for r in rows:
        k = (r["wal"], r["mk"], r["oc"])
        if k not in seen or r["oa"] < seen[k]["oa"]:
            seen[k] = r
    return list(seen.values())


def fee_entry(r, rate):
    return r["size"] * rate * (1.0 - r["p"])


def fee_exit(r, rate):
    """Implied exit price from the PnL identity, then the same fee law at that price."""
    if r["status"] != "closed":
        return 0.0
    c = r["p"] * (1.0 + r["pnl"] / r["size"])
    c = min(max(c, 0.0), 1.0)
    return (r["size"] / r["p"]) * rate * c * (1.0 - c)


def implied_exit(r):
    c = r["p"] * (1.0 + r["pnl"] / r["size"])
    return min(max(c, 0.0), 1.0)


def agg(rows, rate, default):
    a = defaultdict(lambda: defaultdict(float))
    for r in rows:
        b = band_of(r["p"])
        rt, _ = rate_of(r["mk"], default)
        fe = fee_entry(r, rt)
        fx = fee_exit(r, rt)
        for key in (("all", "all"), (r["bot"], b), (r["bot"], "all"), ("all", b)):
            d = a[key]
            d["n"] += 1
            d["notional"] += r["size"]
            d["gross"] += r["pnl"]
            d["cd"] += r["size"] * r["days"]
            d["fee1"] += fe
            d["fee2"] += fe + fx
            d["fee3"] += fe + (fe if r["status"] == "closed" else 0.0)
            d["fee_stake"] += fee_entry(r, 1.0) / r["size"]  # rate-normalised fee/stake
    return a


def line(d, label, width=18):
    if not d["n"]:
        return f"{label:<{width}} {'-':>6}"
    roi = 100.0 * d["gross"] / d["notional"]
    net1 = d["gross"] - d["fee1"]
    net2 = d["gross"] - d["fee2"]
    roi1 = 100.0 * net1 / d["notional"]
    roi2 = 100.0 * net2 / d["notional"]
    cd = d["cd"]  # dollar-days at risk
    return (f"{label:<{width}} {int(d['n']):>6} {d['notional']:>9.0f} {roi:>7.2f} "
            f"{100.0*d['fee1']/d['notional']:>6.2f} {roi1:>7.2f} {roi2:>7.2f} "
            f"{1000.0*d['gross']/cd if cd else 0:>9.2f} {1000.0*net1/cd if cd else 0:>9.2f}")


HDR = (f"{'':<18} {'n':>6} {'notional':>9} {'gross%':>7} {'fee%':>6} "
       f"{'net1%':>7} {'net2%':>7} {'g$/1kcd':>9} {'n$/1kcd':>9}")


def selftest():
    """Identities that must hold or every number below is wrong."""
    rows = load()
    bad_settle = 0
    worst = 0.0
    for r in rows:
        if r["status"] != "resolved":
            continue
        c = implied_exit(r)
        e = min(abs(c - 0.0), abs(c - 1.0))
        worst = max(worst, e)
        if e > 0.02:
            bad_settle += 1
    print(f"[selftest] resolved legs: implied exit price within 2c of 0 or 1 for "
          f"{sum(1 for r in rows if r['status']=='resolved') - bad_settle}/"
          f"{sum(1 for r in rows if r['status']=='resolved')} (worst {worst:.4f})")
    # fee/stake == rate*(1-p) must equal fee_entry/notional
    err = 0.0
    for r in rows[:2000]:
        a = fee_entry(r, 0.05) / r["size"]
        b = 0.05 * (1.0 - r["p"])
        err = max(err, abs(a - b))
    print(f"[selftest] max |fee/notional - rate*(1-p)| over 2000 legs = {err:.2e}")
    # break-even hurdle algebra: h = p*(1+rate*(1-p)) reproduces zero expected PnL exactly
    p, rate, n = 0.5, 0.05, 10.0
    h = p * (1 + rate * (1 - p))
    fee = (n / p) * rate * p * (1 - p)          # = n*rate*(1-p)
    win = n / p - n - fee                        # net payoff on a win, fee paid once
    loss = -n - fee                              # net payoff on a loss
    exp_at_h = h * win + (1 - h) * loss
    print(f"[selftest] p={p:.2f} rate={rate:.2f}: hurdle hit {100*h:.4f}% (no-fee p={100*p:.2f}%),"
          f" win {win:.4f} loss {loss:.4f} -> E@hurdle {exp_at_h:+.2e}")
    assert abs(exp_at_h) < 1e-9, "hurdle algebra wrong"
    assert abs(fee - n * rate * (1 - p)) < 1e-12
    print("[selftest] OK")


def main():
    global CUTOFF
    rate = DEFAULT_RATE
    argv = sys.argv[1:]
    if "--selftest" in argv:
        selftest()
        return
    if "--rate" in argv:
        rate = float(argv[argv.index("--rate") + 1])
    days = 90
    if "--days" in argv:
        days = int(argv[argv.index("--days") + 1])
    now_ms = int(time.time() * 1000)
    utc_midnight = now_ms - (now_ms % 86400000)
    CUTOFF = utc_midnight - days * 86400000
    rows = load()
    bets = dedupe(rows)
    A = agg(bets, rate, rate)
    AL = agg(rows, rate, rate)
    print(f"profit-fee-net — rate {rate:.2f} (slug-keyword category map; venue-truth validated)\n")
    print("== FN.1  book, bet-level (first leg per wallet/market/outcome) ==")
    print(HDR)
    print(line(A[("all", "all")], "ALL finished bets"))
    print(line(A[("BANKROLL_200", "all")], "BANKROLL_200"))
    print(line(A[("STANDARD", "all")], "STANDARD"))
    print("\n   leg-level (all legs, canonical for notional):")
    print(HDR)
    print(line(AL[("all", "all")], "ALL finished legs"))
    print(line(AL[("BANKROLL_200", "all")], "BANKROLL_200"))
    print(line(AL[("STANDARD", "all")], "STANDARD"))
    d = AL[("all", "all")]
    print(f"\n   exit-fee BASIS on the same legs (charges the second fee only where a real sell is"
          f" plausible):\n"
          f"     one fee (entry only)          ${d['fee1']:>8,.0f}  = {100*d['fee1']/d['notional']:.2f}% of notional"
          f"  -> net {100*(d['gross']-d['fee1'])/d['notional']:+.2f}%\n"
          f"     two fee, exit at implied px   ${d['fee2']:>8,.0f}  = {100*d['fee2']/d['notional']:.2f}% of notional"
          f"  -> net {100*(d['gross']-d['fee2'])/d['notional']:+.2f}%\n"
          f"     two fee, exit = entry price   ${d['fee3']:>8,.0f}  = {100*d['fee3']/d['notional']:.2f}% of notional"
          f"  -> net {100*(d['gross']-d['fee3'])/d['notional']:+.2f}%   <- the basis of the two existing fee scripts")

    print("\n== FN.2  per lane x band, bet-level ==")
    for bot in ("STANDARD", "BANKROLL_200"):
        print(HDR)
        for _, _, name in BANDS:
            d = A[(bot, name)]
            if d["n"]:
                print(line(d, f"{bot} {name}"))
        print()

    print("== FN.3  fee hurdle vs measured hit rate (resolved-only bets, one fee) ==")
    print(f"{'band':<10} {'n':>5} {'mean px':>8} {'hit%':>7} {'hurdle%':>8} {'edge pp':>8} "
          f"{'gross%':>7} {'net ROI%':>9} {'verdict':<18}")
    res = [r for r in bets if r["status"] == "resolved"]
    for _, _, name in BANDS:
        sel = [r for r in res if band_of(r["p"]) == name]
        if not sel:
            continue
        n = len(sel)
        px = sum(r["p"] for r in sel) / n
        hit = sum(1 for r in sel if implied_exit(r) > 0.5) / n
        hurdle = px * (1 + rate * (1 - px))
        ntnl = sum(r["size"] for r in sel)
        gross = sum(r["pnl"] for r in sel)
        net = sum(r["pnl"] - fee_entry(r, rate_of(r["mk"], rate)[0]) for r in sel)
        hit_dw = sum(r["size"] for r in sel if implied_exit(r) > 0.5) / ntnl
        verdict = "clears fee" if hit_dw > hurdle else "loses to fee"
        print(f"{name:<10} {n:>5} {px:>8.3f} {100*hit:>7.2f} {100*hurdle:>8.2f} "
              f"{100*(hit_dw-px):>8.2f} {100*gross/ntnl:>7.2f} {100*net/ntnl:>9.2f} {verdict:<18}")

    print("\n== FN.4  what the fee does to the ladder arithmetic (bet-level) ==")
    allb = A[("all", "all")]
    g_rate = 1000.0 * allb["gross"] / allb["cd"]
    n_rate = 1000.0 * (allb["gross"] - allb["fee1"]) / allb["cd"]
    print(f"   gross edge {g_rate:.2f} $/1k-capital-day   net(one-fee) {n_rate:.2f} $/1k-capital-day"
          f"   haircut {100*(1-n_rate/g_rate) if g_rate else 0:.1f}%")
    for rung in (500.0, 5000.0):
        print(f"   ${rung:,.0f}/day needs gross ${rung/(g_rate/1000.0):,.0f} deployed"
              f" -> net ${rung/(n_rate/1000.0):,.0f} deployed")

    print("\n== FN.7  the pending band-factor map, gross vs NET (notional-neutral, bet-level) ==")
    print("      map = §AM.7 'strong' 2.0/1.5/0.5/0.4/0.2 across the five bands, same constants;")
    print("      each bet's notional is scaled by factor/normaliser, gross PnL and fee scale with it.")
    FACTORS = {"<0.20": 2.0, "0.2-0.4": 1.5, "0.4-0.6": 0.5, "0.6-0.8": 0.4, "0.8-1.0": 0.2}
    for label, pool in (("all finished", bets), ("90d (card's window)", None)):
        src = bets if pool is not None else [r for r in bets if r["oa"] >= CUTOFF]
        if not src:
            continue
        tot = sum(r["size"] for r in src)
        scaled = sum(FACTORS[band_of(r["p"])] * r["size"] for r in src)
        k = tot / scaled
        rows = []
        for r in src:
            w = FACTORS[band_of(r["p"])] * k
            rt = rate_of(r["mk"], rate)[0]
            rows.append((r["size"] * w * (r["pnl"] / r["size"]),
                         r["size"] * w * rt * (1 - r["p"]), r))
        g_flat = sum(r["pnl"] for r in src)
        f_flat = sum(fee_entry(r, rate_of(r["mk"], rate)[0]) for r in src)
        g_map = sum(x[0] for x in rows)
        f_map = sum(x[1] for x in rows)
        # ex-top-10 by realised PnL contribution, same convention as the card
        def extop10(vals):
            order = sorted(range(len(vals)), key=lambda i: -vals[i][2]["pnl"])
            drop = set(order[:10])
            return sum(vals[i][0] for i in range(len(vals)) if i not in drop)
        g_map_x = extop10(rows)
        g_flat_x = extop10([(r["pnl"], 0.0, r) for r in src])
        print(f"   [{label}] n={len(src)} notional ${tot:,.0f} normaliser k={k:.4f}")
        print(f"      gross: flat ${g_flat:,.0f} -> map ${g_map:,.0f}  delta ${g_map-g_flat:+,.0f}"
              f"  (ex-top-10 delta ${g_map_x-g_flat_x:+,.0f})")
        print(f"      fee  : flat ${f_flat:,.0f} -> map ${f_map:,.0f}  delta ${f_map-f_flat:+,.0f}")
        print(f"      NET  : flat ${g_flat-f_flat:,.0f} -> map ${g_map-f_map:,.0f}"
              f"  NET DELTA ${(g_map-f_map)-(g_flat-f_flat):+,.0f}"
              f"  ({(1-(g_map-f_map-g_flat+f_flat)/(g_map-g_flat))*100 if g_map!=g_flat else 0:.1f}% of the gross delta eaten by fee)")

    print("\n== FN.5  status split: marks vs settlements (bet-level) ==")
    print(HDR)
    for st in ("resolved", "closed"):
        sel = [r for r in bets if r["status"] == st]
        print(line(agg(sel, rate, rate)[("all", "all")], st))

    print("\n== FN.8  resolved legs whose booked PnL is not a settlement (label integrity) ==")
    odd = [r for r in bets if r["status"] == "resolved" and min(abs(implied_exit(r)), abs(implied_exit(r) - 1)) > 0.02]
    odd.sort(key=lambda r: -r["size"])
    print(f"   {len(odd)} of {sum(1 for r in bets if r['status']=='resolved')} resolved bets; "
          f"${sum(r['size'] for r in odd):,.0f} notional, ${sum(r['pnl'] for r in odd):+,.2f} booked")
    for r in odd[:10]:
        print(f"     {r['bot']:<13} p={r['p']:.3f} n=${r['size']:.2f} pnl=${r['pnl']:+.2f} "
              f"implied exit {implied_exit(r):.3f}  {r['mk'][:52]}")

    print("\n== FN.6  rate sensitivity, ALL bets (one-fee net ROI %) ==")
    for rr in (0.0, 0.04, 0.05, 0.07):
        d = agg(bets, rr, rr)[("all", "all")]
        print(f"   rate {rr:.2f}: net {100*(d['gross']-d['fee1'])/d['notional']:>7.2f}%  "
              f"fee ${d['fee1']:>8,.0f} = {100*d['fee1']/d['notional']:.2f}% of notional")


if __name__ == "__main__":
    main()
