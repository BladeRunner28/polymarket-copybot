#!/usr/bin/env python3
"""
REACHABLE-BASIS PREFLIGHT — read-only pricing of the *booking* change the fill-tape review implies.

WHAT THIS ANSWERS (and what it refuses to answer)
-------------------------------------------------
`scripts/profit-fill-tape.py` established, from the venue's own minute tape, that 96% of C-200's
booked profit sits on legs whose level the market never brought to our bid inside 24h. The booking
path (`src/lib/paper.ts::bookedPnl`) cannot see that: it zeroes only rows the resolver explicitly
stamped `unfilled`, and 562 rows carrying +$5,765.4 are `fillStatus NULL` with no touch.

This instrument prices the THREE places a verdict could be applied, so the proposal can be approved
one surface at a time instead of as one number:

  P1  READ PATH     — restate the *reported* figure only (no ledger write, no cap move).
  P2  BOOKING PATH  — stamp the verdict and re-book settled rows (moves realizedPnl, BotBankroll
                      and the equity-linked exposure cap).
  P3  DISPATCH RULE — suppress the d >= +0.5c cell (paper: intent recorded, zero booked).

It also audits the two ways the tape verdict itself could be wrong, because a negative claim ("never
printed") needs its failure modes named:
  (a) HORIZON ADEQUACY — a leg opened less than 24h ago has an incomplete window; "never in 24h" is
      then a statement about the sampling, not about the market. Such legs are excluded from the
      void class and reported.
  (b) POST-SETTLEMENT TOUCHES — the 24h query is not clipped at resolution. A lost market prints 0
      after it settles, which registers as a touch. That biases the void class in the CONSERVATIVE
      direction (a phantom leg is never created by it) but it makes the touched class's cost look
      worse than it was, so it is counted and disclosed.

READ-ONLY: opens prisma/dev.db with `mode=ro`, writes no row, reads no RuleSet through the app,
runs no apply-v*.ts. Reuses the committed loader and tape verdict cache so the basis is identical
to the review's.

RUN
  python3 scripts/reachable-basis-preflight.py
  python3 scripts/reachable-basis-preflight.py --since=2026-09-01 --json=/tmp/preflight.json
"""
import argparse
import importlib.util
import json
import os
import sqlite3
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
_util = importlib.util


def _load(name, path):
    spec = _util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    mod = _util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ppi = _load("ppi", os.path.join(HERE, "profit-postfix-integrity.py"))
tape = _load("tape", os.path.join(HERE, "profit-fill-tape.py"))

DB = os.path.join(ROOT, "prisma", "dev.db")
LANES = ("BANKROLL_200", "STANDARD")
TICK = tape.TICK
NEVER = "never_24h"


def con():
    c = sqlite3.connect("file:" + DB + "?mode=ro", uri=True)
    c.row_factory = sqlite3.Row
    return c


def money(v):
    return f"{v:+,.2f}"


def roi(legs, pnl_of=None):
    pnl_of = pnl_of or (lambda l: l["realizedPnl"] or 0)
    ntl = sum(l["simulatedPositionSize"] for l in legs)
    p = sum(pnl_of(l) for l in legs)
    return (p, ntl, (100.0 * p / ntl) if ntl else 0.0)


def ci(legs, pnl_of=None):
    return ppi.cluster_ci(legs, pnl_of or (lambda l: l["realizedPnl"] or 0))


# ---------------------------------------------------------------- 24h verdicts (cached)


def horizon_verdict(l, now_s):
    """(verdict, lag_s, window_complete) for the 24h window [t0, t0+24h]."""
    t0 = l["openedTs"] // 1000
    tok = l.get("tape_token")
    if not tok:
        return ("no_token", None, True)
    s = tape.series24(tok, t0)
    if not s:
        return ("no_data", None, True)
    hit = next((t for t, p in s if t0 <= t <= t0 + 86400 and p <= l["trueP"] + TICK), None)
    complete = (now_s - t0) >= 86400
    if hit is not None:
        return ("touched", hit - t0, complete)
    return (NEVER, None, complete)


def settlement_ts(l):
    ts = l.get("closedAt") or l.get("resolvedAt")
    return int(ts) / 1000.0 if ts else None


# ---------------------------------------------------------------- sections


def sec_audit(legs, now_s):
    print("=" * 92)
    print("A. AUDIT OF THE NEGATIVE CLAIM — horizon adequacy and post-settlement touches")
    print("=" * 92)
    untouched = [l for l in legs if l["tape_verdict"] == "unfilled_tape" and l.get("tape_token")]
    incomplete = [l for l in untouched if (now_s - l["openedTs"] // 1000) < 86400]
    print(f"  candidates for the never-class (60m untouched, token known): {len(untouched)}")
    print(f"  of those, opened < 24h ago (window INCOMPLETE -> excluded):  {len(incomplete)}")
    if incomplete:
        i_p, i_n, i_r = roi(incomplete)
        print(f"    excluded legs: ${i_n:,.0f} at risk, booked {money(i_p)} ({i_r:+.1f}%)")

    never, late = [], []
    for l in untouched:
        v, lag, complete = horizon_verdict(l, now_s)
        l["v24"] = v
        l["lag24"] = lag
        l["v24_complete"] = complete
        if v == NEVER:
            (never if complete else late).append(l)
    print(f"  never in 24h, window COMPLETE (the void class): {len(never)}")
    print(f"  never so far, window INCOMPLETE (not voidable): {len(late)}")

    # post-settlement touches inside the touched class
    touched = [l for l in untouched if l.get("v24") == "touched"]
    post = []
    for l in touched:
        st = settlement_ts(l)
        if st and l["lag24"] is not None and (l["openedTs"] // 1000 + l["lag24"]) > st:
            post.append(l)
    print(f"  touched-in-24h legs: {len(touched)}; of those the FIRST touch lands AFTER the leg")
    print(f"  settled (post-resolution print, not evidence we filled): {len(post)}")
    if post:
        p_p, p_n, p_r = roi(post)
        print(f"    booked PnL on those: {money(p_p)} on ${p_n:,.0f} ({p_r:+.1f}%) — counted as")
        print("    filled, i.e. their loss is booked; this overstates the touched class's cost.")
    for lane in LANES:
        n = [l for l in never if l["botId"] == lane]
        if not n:
            continue
        p, ntl, r = roi(n)
        print(f"  void class {lane:<13} n={len(n):>4} ${ntl:>8,.0f} booked {money(p)} ({r:+.1f}%)")
    return never, late


def sec_basis(legs, never):
    print()
    print("=" * 92)
    print("B. THREE BASES PER LANE — what each surface would publish")
    print("=" * 92)
    never_ids = {l["id"] for l in never}
    print(f"  {'lane':<13} {'basis':<26} {'legs':>5} {'notional':>9} {'pnl':>10} {'ROI':>9} {'CI95':>20}")
    rows = {}
    for lane in LANES:
        g = [l for l in legs if l["botId"] == lane]

        def emit(label, pnl_of):
            p, ntl, r = roi(g, pnl_of)
            c = ci(g, pnl_of)
            ctxt = ("[%+.1f,%+.1f]" % c) if (c and c[0] is not None and c[1] is not None) else "n/a"
            print(f"  {lane:<13} {label:<26} {len(g):>5} {ntl:>9,.0f} {money(p):>10} {r:>+8.1f}% "
                  f"{ctxt:>20}")
            rows[(lane, label)] = {"legs": len(g), "notional": round(ntl, 2),
                                   "pnl": round(p, 2), "roi": round(r, 2),
                                   "ci": [round(x, 2) for x in c] if (c and c[0] is not None) else None}

        emit("booked (p(fill)=1)", lambda l: l["realizedPnl"] or 0)
        emit("resolver-filled only", lambda l: (l["realizedPnl"] or 0) if l["fillStatus"] == "filled" else 0)
        emit("tape 60m void (NULL only)",
             lambda l: 0 if (l["fillStatus"] is None and l["tape_verdict"] == "unfilled_tape") else (l["realizedPnl"] or 0))
        emit("reachable: NULL-only rule (card)",
             lambda l: 0 if (l["fillStatus"] is None and l["id"] in never_ids) else (l["realizedPnl"] or 0))
        emit("reachable: full contract",
             lambda l: 0 if ((l["fillStatus"] is None and l["id"] in never_ids) or l["fillStatus"] == "unfilled")
             else (l["realizedPnl"] or 0))
        emit("tape void ALL 24h-never (review §3)",
             lambda l: 0 if l["id"] in never_ids else (l["realizedPnl"] or 0))
        print()
    return rows


def sec_ledger(legs, never, rows):
    print("=" * 92)
    print("C. WHAT A BOOKING-PATH RESTATEMENT (P2) WOULD WRITE, AND WHAT IT MOVES")
    print("=" * 92)
    never_ids = {l["id"] for l in never}
    stamp = [l for l in legs if l["fillStatus"] is None and l["id"] in never_ids]
    p, ntl, r = roi(stamp)
    print(f"  rows to stamp never-reachable: {len(stamp)}  notional ${ntl:,.0f}  booked PnL removed {money(p)}")
    c = con()
    ids = [l["id"] for l in stamp]
    q = ",".join("?" * len(ids))
    rows_db = c.execute(
        f"SELECT COUNT(*) n, COALESCE(ROUND(SUM(simulatedPositionSize),2),0) ntl, "
        f"COALESCE(ROUND(SUM(IFNULL(realizedPnl,0)),2),0) pnl "
        f"FROM PaperTrade WHERE id IN ({q})", ids).fetchone() if ids else {"n": 0, "ntl": 0.0, "pnl": 0.0}
    print(f"  cross-check straight from the DB: n={rows_db['n']} notional ${rows_db['ntl']:,.2f} "
          f"pnl {money(rows_db['pnl'])}")

    residue = c.execute(
        "SELECT COUNT(*) n, COALESCE(ROUND(SUM(realizedPnl),2),0) pnl FROM PaperTrade "
        "WHERE botId='BANKROLL_200' AND isDemo=0 AND fillStatus='unfilled' AND IFNULL(realizedPnl,0)<>0"
    ).fetchone()
    ov_ids = [l["id"] for l in legs if l["fillStatus"] == "unfilled" and l["id"] in never_ids]
    ov = c.execute(
        f"SELECT COUNT(*) n, COALESCE(ROUND(SUM(IFNULL(realizedPnl,0)),2),0) pnl FROM PaperTrade "
        f"WHERE id IN ({','.join('?' * len(ov_ids))})", ov_ids).fetchone() if ov_ids else {"n": 0, "pnl": 0.0}
    total_removal = rows_db["pnl"] + residue["pnl"] - ov["pnl"]
    print(f"  SEPARATE HOLE — rows already stamped 'unfilled' that still book PnL "
          f"({residue['n']} rows, {money(residue['pnl'])}): the stamp landed AFTER the leg settled, so")
    print("  bookedPnl() never re-ran on them. A restatement job must sweep these too")
    print(f"  ({ov['n']} rows / {money(ov['pnl'])} are ALSO in the never class — counted once).")
    print(f"  TOTAL removed by a full-contract restatement: {money(total_removal)}")

    b = c.execute("SELECT principal, cashBalance, realizedPnl FROM BotBankroll WHERE botId='BANKROLL_200'").fetchone()
    open_n = c.execute("SELECT ROUND(SUM(simulatedPositionSize),2) FROM PaperTrade "
                       "WHERE botId='BANKROLL_200' AND isDemo=0 AND status='open'").fetchone()[0] or 0.0
    open_u = c.execute("SELECT ROUND(SUM(IFNULL(unrealizedPnl,0)),2) FROM PaperTrade "
                       "WHERE botId='BANKROLL_200' AND isDemo=0 AND status='open'").fetchone()[0] or 0.0
    rset = c.execute("SELECT version, rulesJson FROM RuleSet ORDER BY version DESC LIMIT 1").fetchone()
    base = float((json.loads(rset["rulesJson"]) or {}).get("maxGrossExposureUsd") or 0)
    nw = b["principal"] + b["realizedPnl"] + open_u
    cap_now = base + 0.5 * max(0.0, nw - b["principal"])
    rp_after = b["realizedPnl"] - total_removal
    nw_after = b["principal"] + rp_after + open_u
    cap_after = base + 0.5 * max(0.0, nw_after - b["principal"])
    print()
    print(f"  live RuleSet v{rset['version']}: maxGrossExposureUsd (base) = ${base:,.0f}")
    print(f"  BotBankroll BANKROLL_200: principal ${b['principal']:,.2f}  cash ${b['cashBalance']:,.2f}  "
          f"realized ${b['realizedPnl']:,.2f}")
    print(f"  open C-200 notional ${open_n:,.2f} / {open_u:+.2f} unrealized  =>  netWorth ${nw:,.2f}")
    print(f"  effective cap NOW      = ${cap_now:,.2f}")
    print(f"  effective cap AFTER P2 = ${cap_after:,.2f}   (realized {b['realizedPnl']:,.2f} -> {rp_after:,.2f})")
    print(f"  cap headroom used: ${open_n:,.2f} of ${cap_after:,.2f} = {100.0 * open_n / cap_after if cap_after else 0:.1f}%"
          f"  (now {100.0 * open_n / cap_now if cap_now else 0:.1f}%)")
    print("  READ: P2 does not freeze the lane TODAY — open notional stays under the post-restatement")
    print("  cap — but it TRIPLES the share of the cap already used (9.8% -> 24.4%) on a lane that has")
    print("  been cycling ~$1k/day of notional. That is the number the operator is actually approving")
    print("  when they approve a ledger restatement, and the reason P2 is priced separately from P1.")
    return {"stamp_rows": rows_db["n"], "stamp_pnl": rows_db["pnl"], "residue_rows": residue["n"],
            "residue_pnl": residue["pnl"], "cap_now": round(cap_now, 2),
            "cap_after": round(cap_after, 2), "open_notional": open_n,
            "realized_now": b["realizedPnl"], "realized_after": round(rp_after, 2)}


def sec_sweep_dryrun(since_iso):
    """Dry run of the P2 sweep over EVERY finished C-200 row (not the deduped measurement set).

    The deduction tables above are on the review's deduped population; a write touches ROWS. This
    section adjudicates each row, refuses the ones it must not guess on (complement-frame legs and
    rows with no conditionId), and reports exactly what a stamp would remove from the ledger.
    """
    print()
    print("=" * 92)
    print("F. P2 DRY RUN OVER EVERY ROW (writes nothing) — what the sweep would stamp")
    print("=" * 92)
    c = con()
    since_ms = ppi._ms(since_iso)
    q = """SELECT p.id, p.entryPrice, p.openedAt, p.realizedPnl, p.simulatedPositionSize,
                  p.fillStatus, p.marketId, p.outcome, o.conditionId AS cid, o.walletEntryPrice AS w
             FROM PaperTrade p
             JOIN DecisionJournal d ON d.id = p.decisionJournalId
             LEFT JOIN ObservedTrade o ON o.id = d.observedTradeId
            WHERE p.botId='BANKROLL_200' AND p.isDemo=0 AND p.openedAt >= ?
              AND (p.closedAt IS NOT NULL OR p.resolvedAt IS NOT NULL)"""
    rows = [dict(r) for r in c.execute(q, (since_ms,)).fetchall()]
    no_cid = [r for r in rows if not r["cid"]]
    inv = []
    usable = []
    for r in rows:
        w = r["w"]
        # complement-frame guard: a leg booked on the sibling token must not be adjudicated here
        if w is not None and abs(r["entryPrice"] - (1.0 - w)) + 0.01 < abs(r["entryPrice"] - w) and 0 < w < 1:
            inv.append(r)
        elif r["cid"]:
            usable.append(r)
    print(f"  finished C-200 rows since {since_iso}: {len(rows)}")
    print(f"  refused — no conditionId (cannot locate a token):        {len(no_cid)} "
          f"(${sum(r['simulatedPositionSize'] for r in no_cid):,.2f})")
    print(f"  refused — complement-frame (booked on the sibling token): {len(inv)} "
          f"(${sum(r['simulatedPositionSize'] for r in inv):,.2f})")

    legs = [{"openedTs": int(r["openedAt"]), "cid": r["cid"], "outcome": r["outcome"],
             "trueP": r["entryPrice"], "simulatedPositionSize": r["simulatedPositionSize"],
             "realizedPnl": r["realizedPnl"], "id": r["id"]} for r in usable]
    legs = tape.classify(legs)
    now_s = int(time.time())
    stamp, sweep, keep_filled, untouched_other = [], [], [], []
    for l in legs:
        if l["tape_verdict"] == "unfilled_tape" and l.get("tape_token"):
            v, lag, complete = horizon_verdict(l, now_s)
            never = (v == NEVER and complete)
        else:
            never = False
        l["_never"] = never
    by_id = {r["id"]: r for r in usable}
    for l in legs:
        r = by_id[l["id"]]
        if l["_never"] and r["fillStatus"] is None:
            stamp.append(l)
        elif r["fillStatus"] == "unfilled" and (r["realizedPnl"] or 0) != 0:
            sweep.append(l)
        elif l["_never"]:
            keep_filled.append(l)
    sp = sum(l["realizedPnl"] or 0 for l in stamp)
    sn = sum(l["simulatedPositionSize"] for l in stamp)
    rp = sum(l["realizedPnl"] or 0 for l in sweep)
    rn = sum(l["simulatedPositionSize"] for l in sweep)
    kp = sum(l["realizedPnl"] or 0 for l in keep_filled)
    print(f"\n  STAMP  NULL + never-24h      : {len(stamp):>4} rows  ${sn:>8,.2f}  PnL removed {sp:+,.2f}")
    print(f"  SWEEP  'unfilled' + PnL left : {len(sweep):>4} rows  ${rn:>8,.2f}  PnL removed {rp:+,.2f}")
    print(f"  KEEP   stamped 'filled' + never (resolver's positive evidence beats tape silence): "
          f"{len(keep_filled)} rows, {kp:+,.2f} left booked")
    removed = sp + rp
    booked_all = sum(r["realizedPnl"] or 0 for r in rows)
    print(f"\n  these rows' booked PnL today: {booked_all:+,.2f}; removed: {removed:+,.2f}; "
          f"after: {booked_all - removed:+,.2f}")

    b = c.execute("SELECT principal, realizedPnl FROM BotBankroll WHERE botId='BANKROLL_200'").fetchone()
    open_u = c.execute("SELECT COALESCE(ROUND(SUM(IFNULL(unrealizedPnl,0)),2),0) FROM PaperTrade "
                       "WHERE botId='BANKROLL_200' AND isDemo=0 AND status='open'").fetchone()[0] or 0.0
    open_n = c.execute("SELECT COALESCE(ROUND(SUM(simulatedPositionSize),2),0) FROM PaperTrade "
                       "WHERE botId='BANKROLL_200' AND isDemo=0 AND status='open'").fetchone()[0] or 0.0
    rset = c.execute("SELECT version, rulesJson FROM RuleSet ORDER BY version DESC LIMIT 1").fetchone()
    base = float((json.loads(rset["rulesJson"]) or {}).get("maxGrossExposureUsd") or 0)
    cap_now = base + 0.5 * max(0.0, b["realizedPnl"] + open_u)
    realized_after = b["realizedPnl"] - removed
    cap_after = base + 0.5 * max(0.0, realized_after + open_u)
    print(f"  BotBankroll.realizedPnl {b['realizedPnl']:+,.2f} -> {realized_after:+,.2f}")
    print(f"  effective exposure cap  ${cap_now:,.2f} -> ${cap_after:,.2f} "
          f"(open notional ${open_n:,.2f} = {100.0 * open_n / cap_after if cap_after else 0:.1f}% used)")
    print("  READ-ONLY: this is a dry run. Nothing was stamped; no apply-v*.ts, no prisma write.")
    return {"rows": len(rows), "no_cid": len(no_cid), "complement": len(inv),
            "stamp_rows": len(stamp), "stamp_pnl": round(sp, 2), "sweep_rows": len(sweep),
            "sweep_pnl": round(rp, 2), "keep_rows": len(keep_filled), "keep_pnl": round(kp, 2),
            "removed": round(removed, 2), "booked_all": round(booked_all, 2),
            "realized_after": round(realized_after, 2), "cap_now": round(cap_now, 2),
            "cap_after": round(cap_after, 2), "open_notional": open_n}


def sec_ladder(legs, never):
    print()
    print("=" * 92)
    print("D. THE LADDER — the 14-day settled series under each basis (GOAL POLICY v2, 7d sum)")
    print("=" * 92)
    never_ids = {l["id"] for l in never}
    c200 = [l for l in legs if l["botId"] == "BANKROLL_200"]

    def day_key(ms):
        return time.strftime("%Y-%m-%d", time.localtime(int(ms) / 1000.0))

    days = {}
    for l in c200:
        ts = l.get("closedAt") or l.get("resolvedAt")
        if not ts:
            continue
        k = day_key(ts)
        e = days.setdefault(k, {"booked": 0.0, "reach": 0.0})
        e["booked"] += l["realizedPnl"] or 0
        if not (l["fillStatus"] is None and l["id"] in never_ids):
            e["reach"] += l["realizedPnl"] or 0
    order = sorted(days, reverse=True)[:14]
    print(f"  {'day':<12} {'booked':>10} {'24h-voided':>12} {'delta':>10}")
    for d in order:
        b, r = days[d]["booked"], days[d]["reach"]
        print(f"  {d:<12} {b:>+10.2f} {r:>+12.2f} {r - b:>+10.2f}")
    settled = order[1:8]          # SETTLE_DAYS=1, GATE_WINDOW_DAYS=7 (query_bankroll.js)
    sb = sum(days[d]["booked"] for d in settled)
    sr = sum(days[d]["reach"] for d in settled)
    print(f"\n  settled 7d window {settled[-1]}..{settled[0]}: booked {sb:+,.2f} | 24h-voided {sr:+,.2f}")
    for target in (250, 500, 1000, 2000, 5000):
        need = target * 7
        print(f"    rung ${target:>5}/day needs {need:>7,}: booked {'CLEARS' if sb >= need else 'fails'}"
              f" | voided {'CLEARS' if sr >= need else 'fails'}")
    return {"settled_window": [settled[-1], settled[0]], "booked": round(sb, 2), "voided": round(sr, 2)}


def sec_dispatch(legs):
    print()
    print("=" * 92)
    print("E. THE DISPATCH RULE (P3) — suppressing entries priced above the market at dispatch")
    print("=" * 92)
    c200 = [l for l in legs if l["botId"] == "BANKROLL_200" and l.get("tape_p0") is not None]
    print(f"  C-200 legs with a dispatch price: {len(c200)}")
    for label, pred in (
            ("d >= +0.5c (suppress)", lambda l: (l["trueP"] - l["tape_p0"]) >= 0.005),
            ("d >= 0 (at or above)", lambda l: (l["trueP"] - l["tape_p0"]) >= 0.0),
            ("|d| < 0.5c (keep)", lambda l: abs(l["trueP"] - l["tape_p0"]) < 0.005),
            ("d < 0 (deep bids, keep)", lambda l: (l["trueP"] - l["tape_p0"]) < -0.005),
    ):
        g = [l for l in c200 if pred(l)]
        if not g:
            continue
        p, ntl, r = roi(g)
        c = ci(g)
        print(f"  {label:<26} n={len(g):>4} ${ntl:>8,.0f} booked {money(p)} ({r:+.1f}%) "
              f"{('[%+.1f,%+.1f]' % c) if c else ''}")
    sup = [l for l in c200 if (l["trueP"] - l["tape_p0"]) >= 0.005]
    kept_p, kept_n, kept_r = roi([l for l in c200 if (l["trueP"] - l["tape_p0"]) < 0.005])
    sp, sn, sr_ = roi(sup)
    print(f"\n  kept arm  : n={len(c200) - len(sup)} ${kept_n:,.0f} booked {money(kept_p)} ({kept_r:+.1f}%)")
    print(f"  suppressed: n={len(sup)} ${sn:,.0f} booked {money(sp)} ({sr_:+.1f}%)")
    print(f"  lane booked PnL if the rule had been live on this history: {money(kept_p)} "
          f"(vs {money(kept_p + sp)} booked)")

    # ERA SPLIT — is the losing cell a pre-fix artifact? price-side-inversion shipped 2026-11-09.
    for label, cutoff in (("pre 2026-11-09", "2026-11-09"), ("on/after 2026-11-09", None)):
        if cutoff:
            g = [l for l in sup if time.strftime("%Y-%m-%d", time.localtime(l["openedTs"] / 1000.0)) < cutoff]
        else:
            g = [l for l in sup if time.strftime("%Y-%m-%d", time.localtime(l["openedTs"] / 1000.0)) >= "2026-11-09"]
        if not g:
            print(f"  suppressed cell {label}: n=0")
            continue
        p, ntl, r = roi(g)
        c = ci(g)
        print(f"  suppressed cell {label:<18} n={len(g):>3} ${ntl:>7,.0f} booked {money(p)} ({r:+.1f}%) "
              f"{('[%+.1f,%+.1f]' % c) if (c and c[0] is not None) else ''}")
    return {"suppressed_n": len(sup), "suppressed_pnl": round(sp, 2), "kept_pnl": round(kept_p, 2)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default="2026-09-01")
    ap.add_argument("--json", default=None)
    a = ap.parse_args()

    legs = tape.load(a.since)
    legs = tape.classify(legs)
    legs = [l for l in legs if l.get("tape_verdict") in ("filled_tape", "near_miss", "unfilled_tape")]
    now_s = int(time.time())
    print(f"REACHABLE-BASIS PREFLIGHT — legs opened >= {a.since}, deduped, tape-adjudicated: {len(legs)}")
    print(f"  notional ${sum(l['simulatedPositionSize'] for l in legs):,.0f} · "
          f"booked PnL {money(sum(l['realizedPnl'] or 0 for l in legs))} · read-only\n")

    never, late = sec_audit(legs, now_s)
    basis = sec_basis(legs, never)
    ledger = sec_ledger(legs, never, basis)
    sweep = sec_sweep_dryrun("2000-01-01")
    ladder = sec_ladder(legs, never)
    dispatch = sec_dispatch(legs)

    out = {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
           "since": a.since, "legs": len(legs),
           "never_24h_complete": len(never), "never_window_incomplete": len(late),
           "basis": {f"{k[0]}|{k[1]}": v for k, v in basis.items()},
           "ledger": ledger, "sweep_dryrun": sweep, "ladder": ladder, "dispatch": dispatch}
    if a.json:
        with open(a.json, "w") as f:
            json.dump(out, f, indent=1)
        print(f"\n  wrote {a.json}")


if __name__ == "__main__":
    main()
