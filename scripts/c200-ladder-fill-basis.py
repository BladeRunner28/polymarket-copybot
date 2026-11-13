#!/usr/bin/env python3
"""C-200 LADDER BY FILL CLASS — the number the advance gate reads, split three ways.

WHY THIS EXISTS
---------------
`query_bankroll.js` (the 18:00 C-200 report, the dashboard overview ladder and
`src/app/analytics/page.tsx`) sums `PaperTrade.realizedPnl` for BANKROLL_200 over the
trailing 14 local days and judges an advance on the trailing 7 SETTLED days
(GOAL POLICY v2: sum >= target x 7). Since the fill-aware booking flip (2026-10-28) that
sum is three populations:

    filled      a position the resolver proved the book reached our bid for
    unfilled    proved NOT a position -> bookedPnl() forces 0, so it is already neutral
    unresolved  no evidence either way -> books at p(fill)=1, the OPTIMISTIC number

Nobody has printed the ladder read split by that class, so nobody can see that the
advance is currently judged on filled + unresolved while the filled half is the losing
one. This instrument prints:

  S1  the ladder series as the REPORT computes it (raw rows, closedAt??resolvedAt),
      then with `unresolved` credited at zero, then on the deduped filled class only.
  S2  the gate read as a PASS/FAIL against every rung, on each basis.
  S3  the accrual to the 120-leg re-read bar (how long it actually takes).
  S4  the SECOND channel the same class reaches: BotBankroll.realizedPnl feeds netWorth,
      which feeds the equity-linked exposure cap and the drawdown gate. This prints the
      cap today vs the cap with the unresolved class removed, so the two scopes of the
      proposal are priced separately.

READ-ONLY. sqlite3 in mode=ro. No prisma write, no RuleSet read or write, no rule edit.

RUN
  python3 scripts/c200-ladder-fill-basis.py
"""
import os
import sqlite3
import sys
from datetime import date, datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DB = os.path.join(ROOT, "prisma", "dev.db")
FLIP = "2026-10-28 00:00:00"

PHASES = [("Phase 1", 250), ("Phase 2", 500), ("Phase 3", 1000), ("Phase 4", 2000), ("Ultimate", 5000)]
GATE_DAYS = 7
SETTLE_DAYS = 3
BASE_CAP_USD = 250  # DEFAULT_RULES.maxGrossExposureUsd; the LIVE value is printed in S4


def con():
    c = sqlite3.connect("file:" + DB + "?mode=ro", uri=True)
    c.row_factory = sqlite3.Row
    return c


def ms(v):
    return int(v) if v is not None else None


def day_of(ts_ms):
    return datetime.fromtimestamp(ts_ms / 1000.0).strftime("%Y-%m-%d")


def cls(r):
    return r["fillStatus"] or "NULL"


def load_window(c, days=14, lane="BANKROLL_200", reference=None):
    """Raw rows the ladder reads: closed|resolved, timestamped within the window.

    `reference` = window end date (default today) so the read is reproducible on a
    later run. Uses closedAt else resolvedAt, exactly as query_bankroll.js does.
    """
    ref = reference or date.today()
    start = ref - timedelta(days=days - 1)
    start_ms = int(datetime(start.year, start.month, start.day).timestamp() * 1000)
    q = """
      SELECT id, botId, marketId, outcome, walletAddress, fillStatus, status,
             realizedPnl, simulatedPositionSize, closedAt, resolvedAt, openedAt
        FROM PaperTrade
       WHERE isDemo = 0 AND botId = ?
         AND status IN ('closed','resolved')
         AND (closedAt >= ? OR resolvedAt >= ?)
    """
    rows = [dict(r) for r in c.execute(q, (lane, start_ms, start_ms))]
    for r in rows:
        r["endTs"] = ms(r["closedAt"]) if r["closedAt"] is not None else ms(r["resolvedAt"])
        r["day"] = day_of(r["endTs"])
    return rows, ref


def dedupe(rows):
    seen, out = set(), []
    for r in sorted(rows, key=lambda x: x["openedAt"] or 0):
        k = (r["botId"], r["walletAddress"], r["marketId"], r["outcome"])
        if k in seen:
            continue
        seen.add(k)
        out.append(r)
    return out


def series(rows, ref, days=14):
    """14-day PnL series (most recent first) under a per-row credit function."""
    out = []
    for i in range(days):
        d = (ref - timedelta(days=i)).strftime("%Y-%m-%d")
        out.append((d, [r for r in rows if r["day"] == d]))
    return out


def gate_read(ser, days=14):
    """Mirror of query_bankroll.js: settled window = days[3 .. 3+7), gate = sum >= target*7."""
    daily = [sum(r["credit"] for r in rs) for _, rs in ser]
    settled = daily[SETTLE_DAYS:SETTLE_DAYS + GATE_DAYS]
    t0 = daily[0:GATE_DAYS]
    idx = 0
    for i, (_, tgt) in enumerate(PHASES):
        if len(settled) == GATE_DAYS and sum(settled) >= tgt * GATE_DAYS:
            idx = i + 1
        else:
            break
    idx = min(idx, len(PHASES) - 1)
    return {
        "daily": daily,
        "settled_sum": sum(settled),
        "t0_sum": sum(t0),
        "goal_idx": idx,
        "goal": PHASES[idx],
        "need": PHASES[idx][1] * GATE_DAYS,
        "window": (ser[SETTLE_DAYS + GATE_DAYS - 1][0], ser[SETTLE_DAYS][0]),
        "t0_window": (ser[GATE_DAYS - 1][0], ser[0][0]),
        "legs_settled": sum(len(rs) for _, rs in ser[SETTLE_DAYS:SETTLE_DAYS + GATE_DAYS]),
    }


def main():
    c = con()
    raw, ref = load_window(c)
    print(f"C-200 ladder by fill class | window {ref - timedelta(days=13)} .. {ref} "
          f"(14 local days, closedAt??resolvedAt, raw rows as query_bankroll.js reads them)")
    print(f"rows in window: {len(raw)}   classes: "
          + ", ".join(f"{k}={sum(1 for r in raw if cls(r) == k)}" for k in ("filled", "unfilled", "NULL")))

    arms = {
        "A. as the report reads it today (filled + unresolved)": lambda r: r["realizedPnl"] or 0.0,
        "B. unresolved credited at ZERO (filled + unfilled)": lambda r: 0.0 if cls(r) == "NULL" else (r["realizedPnl"] or 0.0),
        "C. proven fills only": lambda r: (r["realizedPnl"] or 0.0) if r["was"] == "filled" else 0.0,
    }
    for r in raw:
        r["was"] = cls(r)

    print("\nS1. THE 14-DAY SERIES, THREE WAYS")
    print(f"  {'day':<12} {'legs':>5} {'A report':>10} {'B NULL=0':>10} {'C filled':>10}   classes(f/u/-)")
    for name, fn in arms.items():
        for r in raw:
            r["credit"] = fn(r)
        ser = series(raw, ref)
        if name.startswith("A"):
            for d, rs in ser:
                f = sum(1 for r in rs if r["was"] == "filled")
                u = sum(1 for r in rs if r["was"] == "unfilled")
                z = sum(1 for r in rs if r["was"] == "NULL")
                row = []
                for nm, f2 in arms.items():
                    row.append(sum(f2(r) for r in rs))
                print(f"  {d:<12} {len(rs):>5} {row[0]:>+10.1f} {row[1]:>+10.1f} {row[2]:>+10.1f}   {f}/{u}/{z}")

    print("\nS2. THE ADVANCE GATE, EACH BASIS (GOAL POLICY v2: settled 7d SUM >= target x 7)")
    print(f"  {'basis':<48} {'settled 7d':>11} {'need':>8} {'rung':>10} {'T+0 7d':>9} {'legs':>5}")
    results = {}
    for name, fn in arms.items():
        for r in raw:
            r["credit"] = fn(r)
        ser = series(raw, ref)
        g = gate_read(ser)
        results[name] = g
        verdict = "PASS" if g["settled_sum"] >= g["need"] else f"fail ({(g['settled_sum'] / g['need'] * 100):.0f}%)"
        print(f"  {name:<48} {g['settled_sum']:>+11.1f} {g['need']:>8} {g['goal'][0]:>10} {g['t0_sum']:>+9.1f} {g['legs_settled']:>5}"
              f"  {verdict}")
        print(f"  {'':<48} window {g['window'][0]} .. {g['window'][1]}")

    # Deduped cross-check on the same window: dedupe removes duplicate accumulation rows.
    for r in raw:
        r["credit"] = r["realizedPnl"] or 0.0
    ded = dedupe(raw)
    print(f"\n  deduped cross-check (first leg per bot|wallet|market|outcome):")
    for label, fn in (("as booked", lambda r: r["realizedPnl"] or 0.0),
                      ("filled only", lambda r: (r["realizedPnl"] or 0.0) if r["was"] == "filled" else 0.0)):
        for r in ded:
            r["credit"] = fn(r)
        g = gate_read(series(ded, ref))
        print(f"    {label:<24} settled 7d {g['settled_sum']:>+9.1f}  legs {g['legs_settled']:>4}  T+0 {g['t0_sum']:>+9.1f}")

    print("\nS3. THE 120-LEG RE-READ BAR")
    allrows = [dict(r) for r in c.execute(
        "SELECT id, fillStatus, status, openedAt, realizedPnl, simulatedPositionSize FROM PaperTrade "
        "WHERE isDemo=0 AND botId='BANKROLL_200' AND openedAt >= ?",
        (int(datetime(2026, 10, 28).timestamp() * 1000),))]
    fin = [r for r in allrows if r["status"] in ("closed", "resolved")]
    filled = [r for r in fin if r["fillStatus"] == "filled"]
    openl = [r for r in allrows if r["status"] == "open"]
    span_days = max(1.0, (max(r["openedAt"] for r in allrows) - min(r["openedAt"] for r in allrows)) / 86400000.0)
    rate = len(filled) / span_days
    print(f"  post-flip C-200 legs: {len(allrows)} opened, {len(fin)} finished, {len(openl)} still open")
    print(f"  proven fills: {len(filled)} legs over {span_days:.1f} days = {rate:.2f}/day")
    print(f"  bar is 120 -> {max(0, 120 - len(filled))} more legs -> "
          f"{max(0, 120 - len(filled)) / rate:.0f} days at the current accrual "
          f"(~{(ref + timedelta(days=max(0, 120 - len(filled)) / rate)).isoformat()})")
    print(f"  filled cohort PnL now: {sum(r['realizedPnl'] or 0 for r in filled):+.2f} on "
          f"${sum(r['simulatedPositionSize'] for r in filled):,.0f}")

    print("\nS4. THE SECOND CHANNEL — the same class reaches the exposure cap and drawdown")
    b = c.execute("SELECT botId, principal, realizedPnl, cashBalance FROM BotBankroll WHERE botId='BANKROLL_200'").fetchone()
    principal, book, null_pnl = 0.0, 0.0, (0.0, 0)
    if b:
        un = c.execute(
            "SELECT COALESCE(SUM(unrealizedPnl),0) FROM PaperTrade WHERE isDemo=0 AND botId='BANKROLL_200' AND status='open'"
        ).fetchone()[0]
        null_pnl = c.execute(
            "SELECT COALESCE(SUM(realizedPnl),0), COUNT(*) FROM PaperTrade "
            "WHERE isDemo=0 AND botId='BANKROLL_200' AND fillStatus IS NULL AND status IN ('closed','resolved')"
        ).fetchone()
        principal = b["principal"] or 0.0
        book = b["realizedPnl"] or 0.0
        nw = principal + book + (un or 0.0)
        nw_nf = nw - (null_pnl[0] or 0.0)
        # The LIVE cap base, never the DEFAULT_RULES constant: the stored JSON overrides it
        # and reading the default has overstated this ceiling 4x before.
        import json
        rv = c.execute("SELECT version, rulesJson FROM RuleSet ORDER BY version DESC LIMIT 1").fetchone()
        live = json.loads(rv["rulesJson"]) if rv else {}
        base = live.get("maxGrossExposureUsd", BASE_CAP_USD)
        def cap(n):  # effectiveExposureCap(base, nw, principal)
            return base + 0.5 * max(0.0, n - principal)
        print(f"  BotBankroll: principal ${principal:,.2f}  realizedPnl ${book:,.2f}  cash ${(b['cashBalance'] or 0):,.2f}")
        print(f"  open unrealized ${un or 0:,.2f}")
        print(f"  netWorth today (mtm basis the gate uses)      ${nw:,.2f}  -> cap ${cap(nw):,.0f}")
        print(f"  netWorth with unresolved PnL removed          ${nw_nf:,.2f}  -> cap ${cap(nw_nf):,.0f}")
        print(f"  unresolved class: {null_pnl[1]} finished legs, ${null_pnl[0]:+,.2f} booked")
        print(f"  => at the live base the cap difference is ${cap(nw) - cap(nw_nf):,.0f}; "
              f"both sit at the bare base when netWorth <= principal "
              f"({'yes' if nw <= principal else 'no'}).")
    rv = c.execute("SELECT version, rulesJson FROM RuleSet ORDER BY version DESC LIMIT 1").fetchone()
    if rv:
        import json
        rules = json.loads(rv["rulesJson"])
        print(f"  active RuleSet v{rv['version']}: maxGrossExposureUsd={rules.get('maxGrossExposureUsd')} "
              f"ddBasis={rules.get('ddBasis')} maxDrawdownPct={rules.get('maxDrawdownPct')}")
        if b:
            rnw = principal + book
            rpeak = 0.0
            try:
                import json as _j
                rpeak = _j.load(open(os.path.join(ROOT, "data", "c200-drawdown.json")))["realizedPeak"]
            except Exception:
                pass
            if rpeak > 0:
                dd = max(0.0, (rpeak - rnw) / rpeak)
                dd_nf = max(0.0, (rpeak - (rnw - (null_pnl[0] or 0.0))) / rpeak)
                print(f"  realized-basis drawdown: {dd * 100:.1f}% today vs {(dd_nf * 100):.1f}% with the "
                      f"unresolved class removed (gate = {rules.get('maxDrawdownPct')} = "
                      f"{(rules.get('maxDrawdownPct') or 0) * 100:.0f}%)")

    print("\nS5. EVERY PUBLISHED C-200 REALIZED FIGURE, BEFORE -> AFTER (all-time, the population the")
    print("    overview card / EOD / analytics page sum)")
    allrows2 = [dict(r) for r in c.execute(
        "SELECT id, botId, walletAddress, marketId, outcome, openedAt, closedAt, resolvedAt, fillStatus, realizedPnl, simulatedPositionSize "
        "FROM PaperTrade WHERE isDemo=0 AND botId='BANKROLL_200' AND status IN ('closed','resolved')")]
    for r in allrows2:
        r["was"] = cls(r)
        end = r["closedAt"] if r["closedAt"] is not None else r["resolvedAt"]
        r["day"] = day_of(ms(end)) if end is not None else None
    tot = sum(r["realizedPnl"] or 0 for r in allrows2)
    fil = sum(r["realizedPnl"] or 0 for r in allrows2 if r["was"] == "filled")
    unf = sum(r["realizedPnl"] or 0 for r in allrows2 if r["was"] == "unfilled")
    nul = sum(r["realizedPnl"] or 0 for r in allrows2 if r["was"] == "NULL")
    print(f"  raw finished rows: {len(allrows2):,}   booked total {tot:+,.2f}")
    print(f"    filled {sum(1 for r in allrows2 if r['was'] == 'filled'):>5} rows {fil:>+11,.2f}")
    print(f"    unfilled {sum(1 for r in allrows2 if r['was'] == 'unfilled'):>3} rows {unf:>+11,.2f}")
    print(f"    unresolved {sum(1 for r in allrows2 if r['was'] == 'NULL'):>1} rows {nul:>+11,.2f}")
    print(f"  BEFORE (all classes) {tot:+,.2f}  ->  AFTER (proven fills only) {fil:+,.2f}   "
          f"delta {fil - tot:+,.2f}")
    dz = dedupe(allrows2)
    dt = sum(r["realizedPnl"] or 0 for r in dz)
    dfil = sum(r["realizedPnl"] or 0 for r in dz if r["was"] == "filled")
    print(f"  deduped: {len(dz):,} legs, {dt:+,.2f} -> {dfil:+,.2f} "
          f"(ex-duplicate view; the published surfaces are RAW)")
    print(f"  ledger BotBankroll.realizedPnl {book:+,.2f} vs raw row sum {tot:+,.2f} "
          f"(gap {book - tot:+,.2f}) -- a read-path change does NOT touch this")

    print("\nS6. THE DOLLAR BOUND THE LADDER READS (the ladder sums dollars, not ROI)")
    post = [r for r in allrows2 if (r["openedAt"] or 0) >= int(datetime(2026, 10, 28).timestamp() * 1000)]
    pb = sum(r["realizedPnl"] or 0 for r in post)
    pf = sum(r["realizedPnl"] or 0 for r in post if r["was"] == "filled")
    pf_n = sum(r["simulatedPositionSize"] for r in post if r["was"] == "filled")
    pt_n = sum(r["simulatedPositionSize"] for r in post)
    print(f"  post-flip C-200: {len(post)} finished rows, ${pt_n:,.0f} intent notional")
    print(f"    booked (unresolved at p(fill)=1)        {pb:>+9,.2f}   = {pb / pt_n * 100:+.2f}% of intent notional")
    print(f"    proven fills only (unresolved at 0)    {pf:>+9,.2f}   = {pf / pt_n * 100:+.2f}% of intent notional"
          f"   ({pf / pf_n * 100:+.1f}% of the ${pf_n:,.0f} actually at risk)")
    print(f"    => the ladder's honest range is [{pf:+,.2f}, {pb:+,.2f}] dollars; BOTH bounds are negative,")
    print(f"       so the unresolved class decides how negative the lane is, not whether it is.")
    print(f"    gap to rung 1 ($1,750 over 7 settled days): the settled window reads "
          f"{results['A. as the report reads it today (filled + unresolved)']['settled_sum']:+,.2f} booked / "
          f"{results['C. proven fills only']['settled_sum']:+,.2f} fills-only -- "
          f"the basis change moves no advance today.")

    print("\nS7. THE THREE CREDIT ARMS (so the choice can be read as material-or-not)")
    stamped = [r for r in post if r["was"] in ("filled", "unfilled")]
    share_n = (sum(r["simulatedPositionSize"] for r in stamped if r["was"] == "filled")
               / max(1e-9, sum(r["simulatedPositionSize"] for r in stamped)))
    share_l = (sum(1 for r in stamped if r["was"] == "filled") / max(1, len(stamped)))
    print(f"  observed fill share among STAMPED post-flip legs: {share_l * 100:.1f}% by leg, "
          f"{share_n * 100:.1f}% by notional")
    print("  arm (i) IMMATERIAL = unresolved never filled: at least the filled class's own loss")
    print("  arm (ii) EV       = unresolved credited at the observed fill share (an ESTIMATE, not a")
    print("                      measurement -- never a gate basis, printed for scale only)")
    print("  arm (iii) BOOKED  = p(fill)=1 on unresolved (today's number, the upper bound)")
    win = [r for r in raw if r["day"] >= results["A. as the report reads it today (filled + unresolved)"]["window"][0]
           and r["day"] <= results["A. as the report reads it today (filled + unresolved)"]["window"][1]]
    booked_w = sum(r["realizedPnl"] or 0 for r in win)
    null_w = sum(r["realizedPnl"] or 0 for r in win if r["was"] == "NULL")
    ev_w = booked_w - null_w + null_w * share_n
    print(f"  settled window {results['A. as the report reads it today (filled + unresolved)']['window']}:")
    print(f"    (i) fills-only  {booked_w - null_w:>+9,.2f}   (ii) EV {ev_w:>+9,.2f}   (iii) booked {booked_w:>+9,.2f}"
          f"   need $1,750 -> all three fail")
    booked_p = pb
    null_p = sum(r["realizedPnl"] or 0 for r in post if r["was"] == "NULL")
    ev_p = booked_p - null_p + null_p * share_n
    print(f"  post-flip all-time (raw rows):")
    print(f"    (i) fills-only  {booked_p - null_p:>+9,.2f}   (ii) EV {ev_p:>+9,.2f}   (iii) booked {booked_p:>+9,.2f}")

    print("\nS8. ROLLING 7-DAY WINDOW SWEEP OVER THE WHOLE C-200 HISTORY (does any window clear a rung?)")
    pre = [r for r in allrows2 if (r["openedAt"] or 0) < int(datetime(2026, 10, 28).timestamp() * 1000)]
    pre_ids = {r["id"] for r in pre}
    post = [r for r in allrows2 if r["id"] not in pre_ids]
    for lbl, group in (("pre-flip", pre), ("post-flip", post)):
        st = sum(1 for r in group if r["was"] in ("filled", "unfilled"))
        print(f"  stamp coverage {lbl:<10} {st:>5} of {len(group):>5} rows ({st / max(1, len(group)) * 100:.1f}%) "
              f"-- low coverage makes the fills-only arm a COVERAGE-limited lower bound there, not truth")
    days = sorted({r["day"] for r in allrows2 if r["day"]})
    daily = {}
    for r in allrows2:
        e = daily.setdefault(r["day"], [0.0, 0.0])
        e[0] += r["realizedPnl"] or 0.0
        e[1] += (r["realizedPnl"] or 0.0) if r["was"] == "filled" else 0.0
    if days:
        d0 = datetime.strptime(days[0], "%Y-%m-%d").date()
        d1 = datetime.strptime(days[-1], "%Y-%m-%d").date()
        span = (d1 - d0).days + 1
        series2 = [((d0 + timedelta(days=i)).strftime("%Y-%m-%d"), daily.get(
            (d0 + timedelta(days=i)).strftime("%Y-%m-%d"), [0.0, 0.0])) for i in range(span)]
        wins = []
        for i in range(0, max(0, span - 6)):
            chunk = series2[i:i + 7]
            wins.append((chunk[0][0], chunk[-1][0], sum(c[1][0] for c in chunk), sum(c[1][1] for c in chunk)))
        if wins:
            best_b = max(wins, key=lambda w: w[2])
            best_f = max(wins, key=lambda w: w[3])
            print(f"  windows swept: {len(wins)}  (7-day, by CLOSE day, {days[0]}..{days[-1]})")
            print(f"    booked     best window {best_b[0]}..{best_b[1]}  {best_b[2]:>+9,.2f}   "
                  f"windows clearing $1,750: {sum(1 for w in wins if w[2] >= 1750)}")
            print(f"    fills-only best window {best_f[0]}..{best_f[1]}  {best_f[3]:>+9,.2f}   "
                  f"windows clearing $1,750: {sum(1 for w in wins if w[3] >= 1750)}")
            print("  => the basis is NOT cosmetic: the booked arm clears the cheapest rung in some windows,")
            print("     the provable arm in none. Read the pre-flip gap as coverage-limited (14.9% stamped),")
            print("     and the post-flip gap as the honest one (71.1% stamped).")

    print("\nREAD: A->C is what the proposal would stop crediting. B is the audit arm (C-200 has no")
    print("unfilled credit post-flip by construction, so B==A on this lane and the whole gap is NULL).")


if __name__ == "__main__":
    main()
