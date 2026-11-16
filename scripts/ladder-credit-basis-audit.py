#!/usr/bin/env python3
"""
LADDER CREDIT BASIS AUDIT — the four bases the rung could read, and what each one costs.

WHY THIS FILE EXISTS (2026-11-16, card ladder-credit-confirmed-filled)
---------------------------------------------------------------------
`profit-supply-ladder.py` S6 prints the four bases on the live regime. A proposal that moves the
ladder's CREDIT onto one of them needs three more things this script supplies:

  L2  the rung's OWN population and clock. The advance gate is C-200 only and reads a settled
      rolling 7-day sum over local days T-3..T-9 (query_bankroll.js SETTLE_DAYS=3). A regime-wide
      table does not tell you which phase each basis would clear -- this does.
  L3  the coverage decomposition of the unadjudicated class. "fillStatus IS NULL" is not one
      class: part is a lane that has never had a stamping path (STANDARD, by design), part is a
      leg the resolver could not reach (C-200). Those are different repairs and different risks.
  L4  a PRE-ADJUDICATION of STANDARD's unadjudicated legs from the lane's own booth artifact
      (data/standard-fill-stamp.jsonl). The booth is measurement-only, but its per-leg
      (attainable ask - booked price) already answers the question "would this leg have filled at
      the price we booked?" for every leg it covers. That is the card's own refutation test,
      applied read-only before any write.
  L7  the DECISION surfaces that read the same column (auto-tuner wallet downgrade). A basis that
      changes a published number is one thing; a basis that changes who gets blacklisted is a
      rule change and has to be named as such.

BASES (identical to profit-supply-ladder.py S6, so the two cannot drift)
    booked rows        every settled row, as the realizedPnl column sums it  <- what query_bankroll.js reads
    positions only     booked rows minus fillStatus='unfilled'
    unadjudicated      fillStatus IS NULL   (no fill model has looked at these)
    confirmed filled   fillStatus='filled'  (the only class we can prove we own)

COST BASIS: PaperTrade.simulatedPositionSize = dollars at risk. Never a share count.
SETTLE CLOCK: COALESCE(closedAt, resolvedAt). Regime: DecisionJournal.ruleSetVersion >= 68.

READ-ONLY: DB opened mode=ro, no RuleSet read/write, no prisma write, no apply-v*. The booth file is
read, never written.

USAGE
    python3 scripts/ladder-credit-basis-audit.py
    python3 scripts/ladder-credit-basis-audit.py --regime 68 --target 250
"""
import json
import os
import random
import sqlite3
import sys
import time
import datetime

DB = os.environ.get("COPYBOT_DB", "file:prisma/dev.db?mode=ro")
BOOTH = os.environ.get("COPYBOT_BOOTH", "data/standard-fill-stamp.jsonl")
ARGS = sys.argv[1:]


def arg(name, default):
    for i, a in enumerate(ARGS):
        if a.startswith("--%s=" % name):
            return a.split("=", 1)[1]
        if a == "--%s" % name and i + 1 < len(ARGS):
            return ARGS[i + 1]
    return default


REGIME = int(arg("regime", 68))
TARGET = float(arg("target", 250.0))
PHASES = [250.0, 500.0, 1000.0, 2000.0, 5000.0]
SETTLE_DAYS = 3          # query_bankroll.js SETTLE_DAYS
GATE_WINDOW = 7          # query_bankroll.js GATE_WINDOW_DAYS
MS_DAY = 86400000.0
BASES = ("booked rows", "positions only", "unadjudicated", "confirmed filled")


def usd(x):
    return ("-" if x < 0 else "+") + "$%.1f" % abs(x)


def usd_plain(x):
    return "-$%.1f" % abs(x) if x < 0 else "$%.1f" % x


def pct(x):
    return "%+.1f%%" % (100.0 * x)


def con():
    c = sqlite3.connect(DB, uri=True, timeout=20)
    c.row_factory = sqlite3.Row
    return c


def keep(r, basis):
    fs = r["fs"] or ""
    if basis == "booked rows":
        return True
    if basis == "positions only":
        return fs != "unfilled"
    if basis == "unadjudicated":
        return fs == ""
    return fs == "filled"


def local_day(ms):
    return datetime.date.fromtimestamp(ms / 1000.0)


def phase_for(total, window_len):
    """query_bankroll.js gateFrom(): advance one rung per 7-day window that clears target*7."""
    idx = 0
    for t in PHASES:
        if window_len == GATE_WINDOW and total >= t * GATE_WINDOW:
            idx += 1
        else:
            break
    return min(idx, len(PHASES) - 1)


def load_legs(c, regime_only=True):
    q = """
      SELECT p.id, p.botId AS bot, p.marketId, p.entryPrice, p.fillStatus AS fs, p.fillBasis,
             p.outcome, p.side, p.isDemo,
             p.fillResolvedAt, p.simulatedPositionSize AS cost, COALESCE(p.realizedPnl, 0) AS pnl,
             p.openedAt, COALESCE(p.closedAt, p.resolvedAt) AS endAt, p.decisionJournalId
        FROM PaperTrade p JOIN DecisionJournal d ON d.id = p.decisionJournalId
       WHERE p.status <> 'open'
         AND COALESCE(p.closedAt, p.resolvedAt) IS NOT NULL AND p.realizedPnl IS NOT NULL
    """
    params = ()
    if regime_only:
        q += " AND p.isDemo = 0 AND d.ruleSetVersion >= ?"
        params = (REGIME,)
    rows = [dict(r) for r in c.execute(q, params)]
    rows = [r for r in rows if (r["cost"] or 0) > 0]
    for r in rows:
        r["day"] = local_day(r["endAt"])
    return rows


def table(rows, days, label, lanes=("BANKROLL_200", "STANDARD", None)):
    print("  %-19s %-13s %5s %9s %10s %8s %9s" %
          ("basis", "lane", "n", "cost", "pnl", "ROI", "$/day"))
    for basis in BASES:
        for bot in lanes:
            xs = [r for r in rows if keep(r, basis) and (bot is None or r["bot"] == bot)]
            if not xs:
                continue
            cst = sum(r["cost"] for r in xs)
            p = sum(r["pnl"] for r in xs)
            print("  %-19s %-13s %5d %9s %10s %8s %9s" %
                  (basis, bot or "ALL", len(xs), usd_plain(cst), usd(p),
                   pct(p / cst if cst else 0.0), usd(p / days)))
        print()


def l0_population(rows):
    print("L0. POPULATION (regime = journal.ruleSetVersion >= v%d, settled, cost > 0)" % REGIME)
    for bot in ("BANKROLL_200", "STANDARD", None):
        xs = [r for r in rows if bot is None or r["bot"] == bot]
        if not xs:
            continue
        days = (max(r["endAt"] for r in xs) - min(r["endAt"] for r in xs)) / MS_DAY
        print("  %-13s %5d legs  %9s cost  span %.1fd  first %s  last %s" %
              (bot or "ALL", len(xs), usd_plain(sum(r["cost"] for r in xs)),
               days, min(r["day"] for r in xs).isoformat(), max(r["day"] for r in xs).isoformat()))
    print()


def l1_bases(rows, days):
    print("L1. FOUR BASES -- whole regime, same legs, same clock")
    table(rows, days, "regime")


def l2_rung(rows):
    """The advance gate's own population and clock: C-200, local days T-3 .. T-9."""
    today = datetime.date.today()
    win = {today - datetime.timedelta(days=SETTLE_DAYS + i) for i in range(GATE_WINDOW)}
    lo, hi = min(win), max(win)
    c200 = [r for r in rows if r["bot"] == "BANKROLL_200" and win_hit(r, win)]
    print("L2. THE RUNG'S OWN CLOCK -- C-200 only, settled window %s .. %s (T-3..T-9 local)" %
          (lo.isoformat(), hi.isoformat()))
    print("  this is the window query_bankroll.js sums; the ladder is C-200-only by construction.")
    print("  %-19s %5s %9s %10s %8s %10s %8s %s" %
          ("basis", "n", "cost", "pnl", "ROI", "gate sum", "need 7x", "phase"))
    for basis in BASES:
        xs = [r for r in c200 if keep(r, basis)]
        cst = sum(r["cost"] for r in xs)
        p = sum(r["pnl"] for r in xs)
        need = TARGET * GATE_WINDOW
        print("  %-19s %5d %9s %10s %8s %10s %8s %s" %
              (basis, len(xs), usd_plain(cst), usd(p), pct(p / cst if cst else 0.0),
               usd(p), usd_plain(need), "Phase %d" % (phase_for(p, GATE_WINDOW) + 1)))
    print("  (phase 1 = $250/day rung not cleared; 'gate sum' is the number the advance test reads.)")
    print()
    return c200, win


def l2b_production(prod_rows):
    """The before/after that actually lands: query_bankroll.js's OWN population.

    The production report filters C-200 closed|resolved (no regime filter, no isDemo filter) and
    buckets by America/Chicago local day. This reproduces that window so the proposal can state the
    number the report prints today against the number it would print on each other basis.
    """
    today = datetime.date.today()
    win = {today - datetime.timedelta(days=SETTLE_DAYS + i) for i in range(GATE_WINDOW)}
    lo, hi = min(win), max(win)
    c200 = [r for r in prod_rows if r["bot"] == "BANKROLL_200" and r["day"] in win]
    print("L2b. THE PRODUCTION REPORT'S OWN WINDOW (%s .. %s, C-200, no regime filter)" %
          (lo.isoformat(), hi.isoformat()))
    print("  %-19s %5s %9s %10s %8s %10s %s" %
          ("basis", "n", "cost", "pnl", "ROI", "gate sum", "phase"))
    for basis in BASES:
        xs = [r for r in c200 if keep(r, basis)]
        cst = sum(r["cost"] for r in xs)
        p = sum(r["pnl"] for r in xs)
        print("  %-19s %5d %9s %10s %8s %10s %s" %
              (basis, len(xs), usd_plain(cst), usd(p), pct(p / cst if cst else 0.0), usd(p),
               "Phase %d (need %s)" % (phase_for(p, GATE_WINDOW) + 1, usd_plain(TARGET * GATE_WINDOW))))
    # Parity: the report logs the last 4 days' local buckets on every run. If our day bucketing
    # disagreed with production, this comparison would show it.
    log = os.environ.get("COPYBOT_STREAK_LOG", "data/phase-streak-log.jsonl")
    if os.path.exists(log):
        last = {}
        with open(log, encoding="utf8") as fh:
            for line in fh:
                try:
                    o = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if o.get("day"):
                    last[o["day"]] = o  # last write wins = the most recent re-read
        mine = {}
        for r in c200:
            mine[r["day"].isoformat()] = mine.get(r["day"].isoformat(), 0.0) + r["pnl"]
        print("  PARITY vs data/phase-streak-log.jsonl (production's own day buckets):")
        for d in sorted(win, reverse=True)[:5]:
            k = d.isoformat()
            lg = (last.get(k) or {}).get("localPnl")
            print("    %s  this script %s   report log %s   delta %s" %
                  (k, usd_plain(mine.get(k, 0.0)),
                   "n/a" if lg is None else usd_plain(lg),
                   "n/a" if lg is None else usd_plain(mine.get(k, 0.0) - lg)))
    print()


def l1b_windows(rows):
    print("L1b. ROLLING WINDOWS -- the same four bases at 7d and 14d (settle clock), ALL lanes")
    now = max(r["endAt"] for r in rows)
    for win in (7, 14):
        xs = [r for r in rows if r["endAt"] > now - win * MS_DAY]
        print("  last %dd   %-19s %5s %9s %10s %8s %9s" % (win, "basis", "n", "cost", "pnl", "ROI", "$/day"))
        for basis in BASES:
            ys = [r for r in xs if keep(r, basis)]
            cst = sum(r["cost"] for r in ys)
            p = sum(r["pnl"] for r in ys)
            print("            %-19s %5d %9s %10s %8s %9s" %
                  (basis, len(ys), usd_plain(cst), usd(p), pct(p / cst if cst else 0.0), usd(p / win)))
    print("  (a rolling-window rate is not comparable across reads: the regime-span denominator grows"
          "\n   every day, so a falling $/day can be the denominator rather than the book.)")
    print()


def win_hit(r, win):
    return r["day"] in win


def l3_coverage(c, rows):
    print("L3. THE UNADJUDICATED CLASS IS NOT ONE POPULATION -- coverage decomposition")
    un = [r for r in rows if (r["fs"] or "") == ""]
    print("  unadjudicated total: %d legs  %s cost  %s pnl" %
          (len(un), usd_plain(sum(r["cost"] for r in un)), usd(sum(r["pnl"] for r in un))))
    # C-200: does the leg even have an intent the resolver can reach?
    ids = [r["id"] for r in un if r["bot"] == "BANKROLL_200"]
    linked = set()
    if ids:
        for chunk_start in range(0, len(ids), 400):
            chunk = ids[chunk_start:chunk_start + 400]
            q = "SELECT paperTradeId FROM FillIntent WHERE paperTradeId IN (%s)" % \
                ",".join("?" * len(chunk))
            linked |= {row[0] for row in c.execute(q, chunk)}
    c200un = [r for r in un if r["bot"] == "BANKROLL_200"]
    reach = [r for r in c200un if r["id"] in linked]
    print("  C-200 unadjudicated   %3d legs  %s  | intent-linked (resolver CAN reach): %d legs %s"
          % (len(c200un), usd(sum(r["pnl"] for r in c200un)), len(reach),
             usd(sum(r["pnl"] for r in reach))))
    print("         not linked     %3d legs  %s  <- unreachable BY DEFECT: no FillIntent names the leg"
          % (len(c200un) - len(reach), usd(sum(r["pnl"] for r in c200un if r["id"] not in linked))))
    # Can the missing link be recovered from the natural key? (decisionJournalId, marketId, outcome, side)
    unl = [r for r in c200un if r["id"] not in linked]
    recoverable = []
    for r in unl:
        q = """SELECT COUNT(*) FROM FillIntent f
                WHERE f.decisionJournalId = ? AND f.marketId = ?
                  AND lower(f.outcome) = lower(?) AND f.side = ?"""
        row = c.execute(q, (r["decisionJournalId"], r["marketId"],
                            r["outcome"], r["side"])).fetchone()
        if row and row[0]:
            recoverable.append(r)
    print("         tuple-recoverable %3d legs %s  <- a FillIntent exists on (decisionJournalId, marketId,"
          % (len(recoverable), usd(sum(r["pnl"] for r in recoverable))))
    print("                                    outcome, side); the paperTradeId link is the only thing missing")
    from collections import Counter
    fb = Counter((r["fillBasis"] or "never attempted") for r in un)
    print("  unadjudicated legs by fillBasis: %s" % dict(fb))
    # fillBasis on stamped legs: how the resolver reached its verdicts
    stamped = [r for r in rows if r["fs"]]
    from collections import Counter
    cnt = Counter((r["fs"], r["fillBasis"] or "NULL") for r in stamped)
    print("  stamped legs by (fillStatus, fillBasis):")
    for (fs, fb), n in sorted(cnt.items()):
        print("    %-9s %-16s %4d" % (fs, fb, n))
    stdun = [r for r in un if r["bot"] == "STANDARD"]
    print("  STANDARD unadjudicated %3d legs  %s  <- no stamping path at all (booth writes no rows)"
          % (len(stdun), usd(sum(r["pnl"] for r in stdun))))
    print()
    return un, stdun


def load_booth():
    if not os.path.exists(BOOTH):
        return None
    last = None
    with open(BOOTH, encoding="utf8") as fh:
        for line in fh:
            t = line.strip()
            if not t:
                continue
            try:
                o = json.loads(t)
            except json.JSONDecodeError:
                continue
            if isinstance(o.get("legs"), list):
                last = o
    return last


def l4_pre_adjudication(stdun):
    """Would the unadjudicated STANDARD legs have filled at the price we booked?

    The booth measures, per leg, the lowest best-ask seen inside its lag window against
    PaperTrade.entryPrice. at-or-better (firstAsk <= decisionPrice) means a seller was there at our
    level -> under the C-200 convention that is 'filled'. Anything worse means the level was never
    offered -> 'unfilled', and bookedPnl() books it at 0.
    """
    print("L4. PRE-ADJUDICATION -- the booth's own per-leg read, applied to the unadjudicated STANDARD legs")
    snap = load_booth()
    if not snap:
        print("  booth artifact missing (%s) -- section skipped" % BOOTH)
        print()
        return
    ur = snap.get("unionRefutation") or {}
    print("  booth union: %d legs, %d with a book snapshot, gate %s (n=%s), meanAsk %+.2fc" %
          (len(snap.get("legs") or []), ur.get("n", 0), "MET" if ur.get("gateMet") else "NOT MET",
           ur.get("n"), ur.get("meanAskC") or 0.0))
    print("  lane-wide, the booth already reads: at-or-better %.1f%%, worse-by-1c %.1f%% -- i.e. on the"
          % (100 * (ur.get("shareAtOrBetter") or 0), 100 * (ur.get("shareWorseBy1c") or 0)))
    print("  legs it can see, only %.1f%% had a seller at the booked price inside the window."
          % (100 * (ur.get("shareAtOrBetter") or 0)))
    byid = {}
    for l in snap.get("legs") or []:
        b = l.get("book") or {}
        t = l.get("tape") or {}
        prints = [v.get("price") for v in (t.get("byBucket") or {}).values()
                  if isinstance(v, dict) and v.get("price") is not None]
        byid[l.get("id")] = (l.get("decisionPrice"), b.get("firstAsk"),
                             min(prints) if prints else None)
    # at-or-better uses the booth's OWN tolerance: (ask - decisionPrice)*100 <= 0.01c (merge script).
    seen, ator, worse, tape_seen, tape_hit = [], [], [], [], []
    for r in stdun:
        if r["id"] not in byid:
            continue
        dp, fa, lp = byid[r["id"]]
        if dp is None:
            continue
        if fa is not None:
            seen.append(r)
            (ator if fa <= dp + 1e-4 else worse).append(r)
        if lp is not None:
            tape_seen.append(r)
            if lp <= dp + 1e-4:
                tape_hit.append(r)
    print("  overlap with THIS card's population (book arm = taker at the booked price): %d of %d legs"
          % (len(seen), len(stdun)))
    if not seen:
        print("  -> no overlap; the lane-wide rate above is the only transferable number, and it is a")
        print("     transfer (different legs), not a verdict on this population.")
        print()
        return
    cst = sum(r["cost"] for r in seen)
    print("    at-or-better (would book filled): %3d legs  %s cost  %s pnl" %
          (len(ator), usd_plain(sum(r["cost"] for r in ator)), usd(sum(r["pnl"] for r in ator))))
    print("    worse than booked (would book 0): %3d legs  %s cost  %s pnl  <- these leave the book" %
          (len(worse), usd_plain(sum(r["cost"] for r in worse)), usd(sum(r["pnl"] for r in worse))))
    print("    measured on the overlap: at-or-better %.1f%% (lane-wide %.1f%%)" %
          (100.0 * len(ator) / len(seen), 100 * (ur.get("shareAtOrBetter") or 0)))
    if tape_seen:
        print("  tape arm (MAKER at the booked price -- lowest print <= booked, tape-only legs):")
        print("    %d legs carry prints; %d (%.1f%%) had a print at or below the booked price  %s pnl at stake"
              % (len(tape_seen), len(tape_hit),
                 100.0 * len(tape_hit) / max(1, len(tape_seen)),
                 usd(sum(r["pnl"] for r in tape_hit))))
    print("  SCENARIO if the credit moves to confirmed-filled AND the booth is promoted to stamping:")
    print("    the booked number would not be 'filled only' as measured today -- most of this class")
    print("    would land in UNFILLED and book 0, i.e. the change removes the legs rather than")
    print("    excluding them. That is a different (larger) move than the card describes.")
    print("    The CONVENTION CHOICE decides which arm applies: a taker fill needs the ask to come to")
    print("    the booked price (book arm); a resting maker bid needs a PRINT at or below it (tape arm).")
    print("    C-200's resolver uses the book arm, so adopting its convention for STANDARD is the")
    print("    consistent choice -- and it is the one that removes the most PnL.")
    print()


def l5_robustness(rows):
    print("L5. IS THE FILLED CLASS'S SIGN ROBUST? market-clustered bootstrap, ex-top-N")
    filled = [r for r in rows if r["fs"] == "filled"]
    p = sum(r["pnl"] for r in filled)
    cst = sum(r["cost"] for r in filled)
    print("  filled class: %d legs, %s cost, %s pnl, %s" % (len(filled), usd_plain(cst), usd(p), pct(p / cst)))
    bym = {}
    for r in filled:
        bym.setdefault(r["marketId"], []).append(r)
    print("  markets: %d  largest market by |pnl|: %s" %
          (len(bym), max(bym.items(), key=lambda kv: abs(sum(x["pnl"] for x in kv[1])))[0][:60]))
    for k in (1, 3, 5):
        s = sorted((r["pnl"] for r in filled), reverse=True)
        print("  ex-top-%d legs (best):     %s" % (k, usd(p - sum(s[:k]))))
        s2 = sorted((r["pnl"] for r in filled))
        print("  ex-worst-%d legs:          %s" % (k, usd(p - sum(s2[:k]))))
    top = max(bym.items(), key=lambda kv: sum(x["pnl"] for x in kv[1]))
    print("  ex-largest market:         %s  (%s)" %
          (usd(p - sum(x["pnl"] for x in top[1])), top[0][:50]))
    rng = random.Random(20261116)
    keys = list(bym)
    tots, rois = [], []
    for _ in range(3000):
        smp = []
        for _ in keys:
            smp.extend(bym[rng.choice(keys)])
        t = sum(x["pnl"] for x in smp)
        c = sum(x["cost"] for x in smp)
        tots.append(t)
        rois.append(t / c if c else 0.0)
    tots.sort()
    rois.sort()
    q = lambda a, f: a[int(f * (len(a) - 1))]
    print("  bootstrap (3000x, clustered by market): pnl 95%% CI [%s, %s]; ROI 95%% CI [%s, %s]"
          % (usd(q(tots, 0.025)), usd(q(tots, 0.975)), pct(q(rois, 0.025)), pct(q(rois, 0.975))))
    print()


def l6_decay(rows, days):
    print("L6. THE MECHANISM -- class PnL by settle cohort, and what the resolver has been adding")
    rows = sorted(rows, key=lambda r: r["endAt"])
    t0 = rows[0]["endAt"]
    buckets = {}
    for r in rows:
        wk = int((r["endAt"] - t0) // (7 * MS_DAY))
        buckets.setdefault(wk, []).append(r)
    print("  %-4s %-11s %5s %10s %5s %10s %5s %10s %10s" %
          ("wk", "from", "fil_n", "fil_pnl", "una_n", "una_pnl", "unf_n", "unf_pnl", "posonly/d"))
    for wk in sorted(buckets):
        xs = buckets[wk]
        f = [r for r in xs if r["fs"] == "filled"]
        u = [r for r in xs if (r["fs"] or "") == ""]
        f2 = [r for r in xs if r["fs"] == "unfilled"]
        po = [r for r in xs if (r["fs"] or "") != "unfilled"]
        nd = min(7.0, max(1.0, (max(r["endAt"] for r in xs) - min(r["endAt"] for r in xs)) / MS_DAY))
        print("  %-4d %-11s %5d %10s %5d %10s %5d %10s %10s" %
              (wk + 1, min(r["day"] for r in xs).isoformat(), len(f), usd(sum(r["pnl"] for r in f)),
               len(u), usd(sum(r["pnl"] for r in u)), len(f2), usd(sum(r["pnl"] for r in f2)),
               usd(sum(r["pnl"] for r in po) / nd)))
    # resolver recency: which class the recently-adjudicated legs land in
    now = max(r["endAt"] for r in rows)
    print("  adjudicated BY THE RESOLVER in the last N days (fillResolvedAt), and where they landed:")
    for n in (7, 14, 30):
        cut = now - n * MS_DAY
        xs = [r for r in rows if r["fillResolvedAt"] and r["fillResolvedAt"] > cut]
        f = [r for r in xs if r["fs"] == "filled"]
        u = [r for r in xs if r["fs"] == "unfilled"]
        print("    %2dd: %3d stamped  | filled %3d %s  | unfilled %3d %s" %
              (n, len(xs), len(f), usd(sum(r["pnl"] for r in f)),
               len(u), usd(sum(r["pnl"] for r in u))))
    print()


def l7_decision_surfaces(c):
    print("L7. THE SAME COLUMN ALSO DECIDES -- auto-tuner wallet downgrade (src/lib/rule-updater.ts)")
    q = """
      SELECT walletAddress, SUM(COALESCE(realizedPnl,0)) raw, COUNT(*) n,
             SUM(CASE WHEN fillStatus='unfilled' THEN 0 ELSE COALESCE(realizedPnl,0) END) posonly,
             SUM(CASE WHEN fillStatus='filled' THEN COALESCE(realizedPnl,0) ELSE 0 END) filled
        FROM PaperTrade WHERE status IN ('closed','resolved') AND isDemo=0
       GROUP BY walletAddress HAVING n >= 3
    """
    rows = [dict(r) for r in c.execute(q)]
    today = [r for r in rows if r["raw"] < -10.0]
    on_po = [r for r in rows if r["posonly"] < -10.0]
    on_fill = [r for r in rows if r["filled"] < -10.0]
    new_po = [r for r in on_po if r["raw"] >= -10.0]
    new_fill = [r for r in on_fill if r["posonly"] >= -10.0]
    print("  wallets with >=3 finished legs: %d" % len(rows))
    print("  blacklisted today (raw realizedPnl < -$10): %d" % len(today))
    print("  would ADD under positions-only: %d   under confirmed-filled: %d" % (len(new_po), len(new_fill)))
    for r in sorted(new_fill, key=lambda x: x["filled"])[:5]:
        print("    %s  raw %s  posonly %s  filled %s  (%d legs)  blacklisted today: %s" %
              (r["walletAddress"][:12], usd(r["raw"]), usd(r["posonly"]), usd(r["filled"]), r["n"],
               "yes" if r["raw"] < -10.0 else "no"))
    print("  A basis change here is a RULE change (who gets downgraded), not a reporting change.")
    print()


def l8_all_time(c):
    """The numbers the dashboard header / EOD quote are ALL-TIME, not regime-scoped."""
    print("L8. ALL-TIME (what the dashboard header and the EOD actually print)")
    rows = load_legs(c, regime_only=False)
    for bot in ("BANKROLL_200", "STANDARD", None):
        xs = [r for r in rows if bot is None or r["bot"] == bot]
        if not xs:
            continue
        print("  %-13s %-19s %5s %10s %11s %8s" % (bot or "ALL", "basis", "n", "cost", "pnl", "ROI"))
        for basis in BASES:
            ys = [r for r in xs if keep(r, basis)]
            cst = sum(r["cost"] for r in ys)
            p = sum(r["pnl"] for r in ys)
            print("  %-13s %-19s %5d %10s %11s %8s" %
                  ("", basis, len(ys), usd_plain(cst), usd(p), pct(p / cst if cst else 0.0)))
    print("  BotBankroll.realizedPnl (the rollup the exposure cap reads):")
    for r in c.execute("SELECT botId, principal, cashBalance, realizedPnl FROM BotBankroll"):
        print("    %-13s principal %9s  cash %9s  realizedPnl %10s" %
              (r["botId"], usd_plain(r["principal"] or 0), usd_plain(r["cashBalance"] or 0),
               usd(r["realizedPnl"] or 0)))
    print()


def l9_coverage_by_vintage(c):
    """Can the credit move yet? The stacked bar is COVERAGE of new legs, not of history.

    Pre-instrument legs can never be stamped (no FillIntent, no book window) -- the same
    'unreachable by design' population the 2026-11-13 card counted. So the question the proposal
    must answer is the forward one: of the legs we OPEN now, what share carries a verdict?
    """
    print("L9. ADJUDICATION COVERAGE BY OPEN VINTAGE -- the bar the credit move has to clear")
    rows = load_legs(c, regime_only=False)
    buckets = {}
    for r in rows:
        wk = local_day(r["openedAt"]).isocalendar()[:2]
        buckets.setdefault((r["bot"], wk), []).append(r)
    print("  %-13s %-9s %5s %5s %6s %10s %10s" %
          ("lane", "open wk", "n", "stmp", "cov%", "pnl_stmp", "pnl_unst"))
    for (bot, wk) in sorted(buckets, key=lambda k: (k[0], k[1])):
        if wk < (2026, 41):
            continue
        xs = buckets[(bot, wk)]
        st = [r for r in xs if r["fs"]]
        us = [r for r in xs if not r["fs"]]
        print("  %-13s %4d-W%02d %5d %5d %5.0f%% %10s %10s" %
              (bot, wk[0], wk[1], len(xs), len(st), 100.0 * len(st) / len(xs),
               usd(sum(r["pnl"] for r in st)), usd(sum(r["pnl"] for r in us))))
    # forward denominator: legs opened in the last 14/28 days, PER LANE
    now = max(r["openedAt"] for r in rows)
    for label, cut in (("last 14d opens", 14), ("last 28d opens", 28)):
        xs = [r for r in rows if r["openedAt"] > now - cut * MS_DAY]
        if not xs:
            continue
        for bot in ("BANKROLL_200", "STANDARD", None):
            ys = [r for r in xs if bot is None or r["bot"] == bot]
            if not ys:
                continue
            st = [r for r in ys if r["fs"]]
            print("  %-16s %-13s %5d legs  stamped %5d (%5.1f%%)  unstamped PnL %s" %
                  (label, bot or "ALL", len(ys), len(st), 100.0 * len(st) / len(ys),
                   usd(sum(r["pnl"] for r in ys if not r["fs"]))))
    print()


def main():
    c = con()
    rows = load_legs(c)
    if not rows:
        print("no legs in regime v%d" % REGIME)
        return
    span = (max(r["endAt"] for r in rows) - min(r["endAt"] for r in rows)) / MS_DAY
    # $/day uses the OPEN-clock span, so numerator and denominator describe the same calendar
    # (same convention as profit-supply-ladder.py: leg_days from openedAt).
    days = max(1.0, (max(r["openedAt"] for r in rows) - min(r["openedAt"] for r in rows)) / MS_DAY)
    print("Instrument: ladder-credit-basis-audit.py  regime >= v%d  rung $%.0f/day  read %s" %
          (REGIME, TARGET, time.strftime("%Y-%m-%d %H:%M:%S")))
    print("  open-clock span %.1fd, settle-clock span %.1fd" % (days, span))
    print()
    l0_population(rows)
    l1_bases(rows, days)
    l1b_windows(rows)
    l2_rung(rows)
    l2b_production(load_legs(c, regime_only=False))
    un, stdun = l3_coverage(c, rows)
    l4_pre_adjudication(stdun)
    l5_robustness(rows)
    l6_decay(rows, days)
    l7_decision_surfaces(c)
    l8_all_time(c)
    l9_coverage_by_vintage(c)
    print("READ-ONLY: DB mode=ro, booth file read-only. No RuleSet write, no prisma write, no apply-v*.")


if __name__ == "__main__":
    main()
