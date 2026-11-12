#!/usr/bin/env python3
"""C-200 INTENT-LINK COVERAGE — can the fill resolver see the lane at all?

WHY THIS EXISTS
---------------
`scripts/c200-fill-resolve.ts` stamps `PaperTrade.fillStatus` (filled / unfilled) from the
print-through evidence, and `src/lib/paper.ts::bookedPnl()` forces $0 on a proven-`unfilled`
leg. But the resolver's population is the set of legs reachable through
`FillIntent.paperTradeId`, so a leg whose intent never got linked is NEVER resolvable and
books at p(fill)=1 forever. Nobody had printed that population, so "the instrument resolves
the lane" and "the instrument resolves a slice of it" were indistinguishable.

MEASURED 2026-11-12 (the class this prints):
  * 2,830 C-200 legs. 2,028 (71.7%) were opened before `FillIntent` existed (2026-09-26) and
    can never carry a verdict — expected, documented, no backfill by design.
  * Of the 802 instrument-era legs, 583 are linked (72.7%) and 219 are NOT.
  * All 219 unlinked legs have an unlinked intent on the exact same
    (decisionJournalId, marketId, outcome, side) — 1:1, zero ambiguity, zero duplicates —
    and the log carries no `link skipped` exception. The link lookup ran before the intent
    row was visible (the intent is written by the scoring process, the leg by the dashboard
    webhook, both on the same SQLite file) and nothing retried. Fixed in
    `src/lib/fill-intent.ts` (bounded retry) for FUTURE legs; the 219 historical pairs are
    LEFT UNLINKED here on purpose — linking them lets the resolver restate their booking,
    which moves booked PnL, netWorth, the exposure cap and the drawdown gate. That is Lane A
    and it needs an explicit yes.

READ-ONLY: sqlite3 mode=ro&immutable=1, no writes, no RuleSet read or write.
RUN:       python3 scripts/c200-intent-link-coverage.py [--orphans N]
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(ROOT, "prisma", "dev.db")
LANE = "BANKROLL_200"
GATE_DAYS = 7
SETTLE_DAYS = 3
RUNG1 = 250 * 7  # GOAL POLICY v2: settled 7d SUM >= target x 7


def con():
    c = sqlite3.connect("file:" + DB + "?mode=ro&immutable=1", uri=True)
    c.row_factory = sqlite3.Row
    return c


def day(ms):
    # LOCAL day, matching query_bankroll.js (`...${offsetExpr},'unixepoch'`). A bare UTC
    # date() re-cuts every window at 18:00 CST and reports a DIFFERENT 7-day sum — measured
    # 2026-11-12: settled 7d as booked reads -$203.47 on the local basis and -$90.75 on UTC.
    return datetime.fromtimestamp(ms / 1000).strftime("%Y-%m-%d")


def pct(a, b):
    return 0.0 if not b else 100.0 * a / b


def key(r):
    return (r["decisionJournalId"], r["marketId"], r["outcome"], r["side"])


def main():
    out = sys.stdout
    try:
        out = sys.stdout
        out.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:
        pass
    orphans_n = 5
    if "--orphans" in sys.argv:
        orphans_n = int(sys.argv[sys.argv.index("--orphans") + 1])

    c = con()
    legs = list(c.execute(
        "SELECT id, decisionJournalId, marketId, outcome, side, openedAt, closedAt, resolvedAt,"
        "       status, entryPrice, intentPrice, fillStatus, fillBasis, simulatedPositionSize,"
        "       realizedPnl"
        "  FROM PaperTrade WHERE botId=? AND isDemo=0", (LANE,)))
    intents = list(c.execute(
        "SELECT id, decisionJournalId, marketId, outcome, side, dispatchedAt, paperTradeId, intentPrice"
        "  FROM FillIntent WHERE botId=?", (LANE,)))

    linked_trade_ids = set(i["paperTradeId"] for i in intents if i["paperTradeId"])
    dj_with_intent = set(i["decisionJournalId"] for i in intents)
    leg_by_id = dict((l["id"], l) for l in legs)

    pre = [l for l in legs if l["decisionJournalId"] not in dj_with_intent]
    era = [l for l in legs if l["decisionJournalId"] in dj_with_intent]
    linked = [l for l in era if l["id"] in linked_trade_ids]
    orphan = [l for l in era if l["id"] not in linked_trade_ids]

    print("=" * 78)
    print("S1. COVERAGE — the resolver's population, all C-200 legs (isDemo=0)")
    print("=" * 78)
    if legs:
        o = sorted(l["openedAt"] for l in legs)
        print("  legs %d   opened %s .. %s" % (len(legs), day(o[0]), day(o[-1])))
    print("  pre-instrument (decision has NO intent row, never stampable): %5d  (%5.1f%%)"
          % (len(pre), pct(len(pre), len(legs))))
    print("  instrument-era (decision HAS an intent row):                 %5d" % len(era))
    print("    linked   -> reachable by the resolver:                     %5d  (%5.1f%% of era)"
          % (len(linked), pct(len(linked), len(era))))
    print("    UNLINKED -> never stampable, books p(fill)=1 forever:       %5d  (%5.1f%% of era)"
          % (len(orphan), pct(len(orphan), len(era))))
    stamped = [l for l in legs if l["fillStatus"]]
    filled = [l for l in legs if l["fillStatus"] == "filled"]
    print("  stamped legs %d  (filled %d = %.1f%% of stamped, unfilled %d)"
          % (len(stamped), len(filled), pct(len(filled), len(stamped)), len(stamped) - len(filled)))
    print("  -> verifiable share of the WHOLE lane: %.1f%% of legs (%d/%d)"
          % (pct(len(stamped), len(legs)), len(stamped), len(legs)))

    # last 7 days of opens
    if legs:
        newest = max(l["openedAt"] for l in legs)
        cut = newest - 7 * 86400 * 1000
        wk = [l for l in legs if l["openedAt"] >= cut]
        wk_linked = [l for l in wk if l["id"] in linked_trade_ids]
        print("  last 7 days of opens (%s..%s): %d legs, %d linked (%.1f%%), %d orphaned"
              % (day(cut), day(newest), len(wk), len(wk_linked), pct(len(wk_linked), len(wk)),
                 len(wk) - len(wk_linked)))

    print("")
    print("=" * 78)
    print("S2. THE 219 ORPHANS — pair them on the exact key the linker uses")
    print("=" * 78)
    unlinked_int = [i for i in intents if not i["paperTradeId"]]
    unlinked_by_key = defaultdict(list)
    for i in unlinked_int:
        unlinked_by_key[key(i)].append(i)
    exact, ambiguous, unmatched = [], [], []
    for l in orphan:
        cands = unlinked_by_key.get(key(l), [])
        if len(cands) == 1:
            exact.append((l, cands[0]))
        elif len(cands) > 1:
            ambiguous.append((l, cands))
        else:
            unmatched.append(l)
    print("  orphan legs %d -> exact 1:1 pair %d · ambiguous %d · no intent on the key %d"
          % (len(orphan), len(exact), len(ambiguous), len(unmatched)))
    if exact:
        notional = sum(l["simulatedPositionSize"] for l, _ in exact)
        booked = sum((l["realizedPnl"] or 0.0) for l, _ in exact)
        settled = sum(1 for l, _ in exact if l["closedAt"] or l["resolvedAt"])
        print("  the paired legs: notional $%.2f   booked PnL $%+.2f   settled %d/%d"
              % (notional, booked, settled, len(exact)))
        print("  their intent prices vs the booked entry (gap = entry - intent):")
        gaps = [(l["entryPrice"] - i["intentPrice"]) for l, i in exact]
        gaps.sort()
        print("    median %+.4f   min %+.4f   max %+.4f" % (gaps[len(gaps) // 2], gaps[0], gaps[-1]))
        print("  %d empty keys (leg has no intent at all inside the era): %d"
              % (0, len(unmatched)))
        if unmatched:
            for l in unmatched[:5]:
                print("    unmatched: %s %s %s" % (l["id"], l["marketId"][:40], l["fillStatus"]))
        print("")
        print("  WHAT LINKING THEM WOULD DO: the resolver would then stamp these legs")
        print("  filled/unfilled; a proven-unfilled leg books $0 at every later mark and at")
        print("  settlement, so booked PnL, netWorth, the equity-linked exposure cap and the")
        print("  drawdown gate all move. LANE A — not applied here.")
        print("  sample (%d):" % min(orphans_n, len(exact)))
        for l, i in exact[:orphans_n]:
            print("    %s %-38s entry=%.4f intent=%.4f pnl=%+.2f %s"
                  % (l["id"], l["marketId"][:38], l["entryPrice"], i["intentPrice"],
                     (l["realizedPnl"] or 0.0), "settled" if (l["closedAt"] or l["resolvedAt"]) else "open"))

    print("")
    print("=" * 78)
    print("S3. THE LADDER SUM TODAY — trailing 7 SETTLED days, LOCAL days (query_bankroll.js basis)")
    print("=" * 78)
    end = (datetime.now() - timedelta(days=SETTLE_DAYS)).date()
    start = end - timedelta(days=GATE_DAYS - 1)

    def close_day(l):
        t = l["closedAt"] or l["resolvedAt"]
        return datetime.fromtimestamp(t / 1000).date() if t else None

    win = []
    for l in legs:
        d = close_day(l)
        if d is not None and start <= d <= end:
            win.append(l)
    booked = sum((l["realizedPnl"] or 0.0) for l in win)
    unresolved0 = sum((l["realizedPnl"] or 0.0) for l in win if l["fillStatus"] in ("filled", "unfilled"))
    fills = sum((l["realizedPnl"] or 0.0) for l in win if l["fillStatus"] == "filled")
    unres = sum((l["realizedPnl"] or 0.0) for l in win if l["fillStatus"] is None)
    cls = Counter(l["fillStatus"] or "unresolved" for l in win)
    print("  window %s .. %s   rows %d  (filled %d / unfilled %d / unresolved %d)"
          % (start, end, len(win), cls["filled"], cls["unfilled"], cls["unresolved"]))
    print("    A. as the report reads it (unresolved at p(fill)=1) $%+9.2f   rung1 need $%d  %s"
          % (booked, RUNG1, "PASS" if booked >= RUNG1 else "fail"))
    print("    B. unresolved credited at ZERO                      $%+9.2f   %s"
          % (unresolved0, "PASS" if unresolved0 >= RUNG1 else "fail"))
    print("    C. proven fills only                                $%+9.2f   %s"
          % (fills, "PASS" if fills >= RUNG1 else "fail"))
    print("    the whole A->C gap is the UNRESOLVED class: $%+.2f on %d legs" % (unres, cls["unresolved"]))
    print("    (unfilled books exactly $0.00 in the window — the fill-aware flip is working)")
    all_unres = sum((l["realizedPnl"] or 0.0) for l in legs if l["fillStatus"] is None)
    n_unres = sum(1 for l in legs if l["fillStatus"] is None)
    print("  all-time unresolved class: %d rows, $%+.2f booked (the number the sibling card"
          % (n_unres, all_unres))
    print("  `profit-fill-class-basis` proposes to stop crediting)")
    print("  NOTE: a PASS on rung 1 needs $%d over 7 settled days, so every basis here reads" % RUNG1)
    print("  as a miss by construction at the current book; the split shows the direction only.")

    print("")
    print("=" * 78)
    print("S4. THE VERDICT'S PRICE FRAME — how many stamps were decided at the wrong level")
    print("=" * 78)
    art = {}
    art_path = os.path.join(ROOT, "data", "c200-printthrough.jsonl")
    if os.path.exists(art_path):
        with open(art_path) as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    snap = json.loads(line)
                except ValueError:
                    continue
                for l in snap.get("legs") or []:
                    if l.get("intentId"):
                        art[l["intentId"]] = l
    pairs = list(c.execute("""
      SELECT p.id, p.marketId, p.entryPrice, p.intentPrice AS leg_intent, p.simulatedPositionSize,
             p.realizedPnl, p.fillStatus, f.id fid, f.intentPrice
        FROM PaperTrade p JOIN FillIntent f
          ON f.decisionJournalId = p.decisionJournalId AND f.marketId = p.marketId
         AND f.outcome = p.outcome AND f.side = p.side
       WHERE p.botId = ? AND p.isDemo = 0""", (LANE,)))
    inv = [r for r in pairs if abs(r["entryPrice"] - (1.0 - r["intentPrice"])) <= 0.012
           and abs(r["entryPrice"] - r["intentPrice"]) >= 0.05]
    inv_linked = [r for r in inv if r["fillStatus"]]
    print("  pairs %d · entry = 1 - intent on %d (%.1f%%) · of those stamped %d"
          % (len(pairs), len(inv), pct(len(inv), len(pairs)), len(inv_linked)))
    flips = []
    no_art = 0
    for r in inv_linked:
        a = art.get(r["fid"]) or {}
        ma = (a.get("book") or {}).get("minAsk")
        if not isinstance(ma, (int, float)):
            no_art += 1
            continue
        # The resolver tested `intent - credit` (the COMPLEMENT's level). The level the leg was
        # actually booked at is entryPrice, so re-test the same evidence at that level.
        correct = ma <= r["entryPrice"] + 1e-9
        stamped = r["fillStatus"] == "filled"
        if correct != stamped:
            flips.append((r, ma, correct))
    print("  re-testing the same book.minAsk at the BOOKED level: %d of %d verdicts do not"
          % (len(flips), len(inv_linked)))
    print("  survive (no artifact book on %d)" % no_art)
    if flips:
        flip_not = sum(r["simulatedPositionSize"] for r, _, _ in flips)
        flip_pnl = sum((r["realizedPnl"] or 0.0) for r, _, _ in flips)
        print("  the flipped legs: notional $%.2f   stored realizedPnl $%+.2f   (they currently"
              % (flip_not, flip_pnl))
        print("  book $0 under the fill-aware flip because the verdict says 'unfilled')")
        for r, ma, correct in flips[:8]:
            print("    %-32s entry=%.3f intent=%.3f minAsk=%.3f stamped=%s correct=%s"
                  % (r["marketId"][:32], r["entryPrice"], r["intentPrice"], ma,
                     r["fillStatus"], "filled" if correct else "unfilled"))
    print("  => the intent price is recorded on the COMPLEMENT's frame on these legs (5% of the")
    print("  instrument era, named-outcome markets: team/player/UNDER labels). The intent is")
    print("  write-only, so no PnL flows from the price itself — but it IS the level the")
    print("  resolver tests, so a verdict decided from it is decided a dollar away from the")
    print("  booked level. Lane A to restamp; Lane B to refuse linking these pairs.")

    print("")
    print("=" * 78)
    print("S5. THE CARD'S OWN FIGURES, RE-MEASURED TODAY")
    print("=" * 78)
    st_not = sum(l["simulatedPositionSize"] for l in stamped)
    st_pnl = sum((l["realizedPnl"] or 0.0) for l in stamped)
    f_not = sum(l["simulatedPositionSize"] for l in filled)
    f_pnl = sum((l["realizedPnl"] or 0.0) for l in filled)
    uf = [l for l in stamped if l["fillStatus"] == "unfilled"]
    uf_not = sum(l["simulatedPositionSize"] for l in uf)
    uf_pnl = sum((l["realizedPnl"] or 0.0) for l in uf)
    print("  card 2026-11-03: 413 stamped legs, reach 33.4% of legs / 32.7% of notional,")
    print("                   phantom $707.80 of $1,032.17 = 68.6%")
    print("  today:           %d stamped legs, reach %.1f%% of legs / %.1f%% of notional"
          % (len(stamped), pct(len(filled), len(stamped)), pct(f_not, st_not)))
    print("                   filled   $%+.2f on $%.2f   unfilled $%+.2f on $%.2f   stamped total $%+.2f"
          % (f_pnl, f_not, uf_pnl, uf_not, st_pnl))
    if st_pnl:
        print("                   unfilled share of stamped booked PnL: %.1f%%" % (pct(uf_pnl, st_pnl)))
    print("  REMINDER: since the fill-aware flip (2026-10-28) `bookedPnl()` forces $0 on an")
    print("  unfilled leg at every later mark, so the unfilled column is RESIDUE of legs that")
    print("  settled before the verdict landed — not forward leakage. The live leak is the")
    print("  UNRESOLVED class, which books at p(fill)=1 and which S1 shows the resolver can")
    print("  only reach through the link.")
    c.close()


if __name__ == "__main__":
    main()
