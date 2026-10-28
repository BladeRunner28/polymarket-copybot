#!/usr/bin/env python3
"""ML-1 declined-arm coverage + label-basis check. READ-ONLY on the database.

Card `ml1-declined-arm-coverage` asks for the declined arms (skip + watchlist) as an explicit
labelled population. The artifact ALREADY EXISTS -- `scripts/build-ml-dataset.py` writes
data/ml/decisions.csv, "one row per entry OPPORTUNITY (first decision per wallet x market x
outcome x side), acted AND declined". What was missing is a NUMBER: the only declined-arm label
figure in circulation was the OutcomeReview coverage (0.76%), which is a different population AND
a different label basis from the training set. This script prints both levels side by side so
they can never be confused again.

WHAT IT MEASURES (each with its own basis -- population, clock, level):

  1. COVERAGE AT TRAINING GRAIN. Unit = ENTRY OPPORTUNITY (first decision per wallet x market x
     outcome x side). Read twice: (a) the committed data/ml/decisions.csv, clock = that build's
     built_at; (b) the live DB with the same dedup key and the same 0.90/0.10 label rule
     recomputed now. A gap between (a) and (b) is ARTIFACT STALENESS, not a label change.
  2. THE CARD'S OWN REFUTATION FLOOR: "refuted if the declined arm's market-outcome label cannot
     be derived for >=50% of watchlist rows", printed as a per-arm verdict.
  3. LABEL BASIS ON THE DECLINED POPULATION. The export labels a market from its LAST non-demo
     MarketSnapshot (yesPrice >= 0.90 -> YES, <= 0.10 -> NO, else abstain); that rule was
     validated only on ACTED positions (report.json's 99.50%). Whether it holds where we never
     took a position is the open question for a counterfactual arm, so it is measured per arm
     against OutcomeReview.finalOutcome.
     SCOPE LIMIT, do not drop it: only 64% of reviewed markets carry a Yes/No finalOutcome; the
     rest carry a winning TOKEN NAME (player / team / "Over"), which a yes/no market label cannot
     be validated against at all. Those are counted and excluded, never mapped onto YES/NO.

Run: python3 scripts/ml1-declined-arm-read.py
"""
import csv, json, os, sqlite3, time
from collections import Counter, defaultdict

ROOT = os.path.expanduser("~/polymarket-copybot")
DB = os.path.join(ROOT, "prisma/dev.db")
CSV = os.path.join(ROOT, "data/ml/decisions.csv")
REPORT = os.path.join(ROOT, "data/ml/report.json")
DECLINED = ("skip", "watchlist")
FLOOR = 0.50


def pct(a, b):
    return 100.0 * a / b if b else 0.0


def cov_table(counts, indent="   "):
    print(f"{indent}{'decision':<12}{'rows':>9}{'labelled':>10}{'pct_labelled':>14}")
    for d in sorted(counts, key=lambda k: -counts[k]["n"]):
        c = counts[d]
        print(f"{indent}{d:<12}{c['n']:>9,}{c['labelled']:>10,}{pct(c['labelled'], c['n']):>13.2f}%")
    dec_n = sum(counts[d]["n"] for d in DECLINED if d in counts)
    dec_l = sum(counts[d]["labelled"] for d in DECLINED if d in counts)
    print(f"{indent}{'DECLINED':<12}{dec_n:>9,}{dec_l:>10,}{pct(dec_l, dec_n):>13.2f}%")


def main():
    print("=" * 96)
    print("ML-1 DECLINED-ARM COVERAGE + LABEL BASIS  (read-only; paper trading)")
    print("=" * 96)
    print("\n1. COVERAGE AT TRAINING GRAIN -- unit = ENTRY OPPORTUNITY")
    print("   (first decision per wallet x market x outcome x side. The 337k raw declined DECISIONS")
    print("    dedupe to ~77k OPPORTUNITIES; every training number is opportunity-grain.)")

    built = "unknown"
    if os.path.exists(REPORT):
        try:
            built = json.load(open(REPORT)).get("built_at", "unknown")
        except Exception:
            pass
    print(f"\n   1a. committed artifact data/ml/decisions.csv -- build clock {built}")
    if os.path.exists(CSV):
        counts = defaultdict(Counter)
        rows = 0
        for r in csv.DictReader(open(CSV, newline="")):
            rows += 1
            c = counts[r["decision"] or "?"]
            c["n"] += 1
            if r["y_side_win"] in ("0", "1"):
                c["labelled"] += 1
        print(f"       {rows:,} rows; labelled = y_side_win non-null (0.90/0.10 rule, abstain = NULL)")
        cov_table(counts)
    else:
        print(f"       MISSING -- run scripts/build-ml-dataset.py")

    # ---- 1b. live DB, same dedup key, same label rule ----
    db = sqlite3.connect("file:%s?mode=ro" % DB, uri=True)
    db.row_factory = sqlite3.Row
    t0 = time.time()
    opp = db.execute("""
    WITH first_seen AS (
      SELECT d.decision, d.marketId m,
             ROW_NUMBER() OVER (PARTITION BY d.walletAddress, d.marketId, o.outcome, o.side
                                ORDER BY d.createdAt ASC, d.id ASC) rn
      FROM DecisionJournal d JOIN ObservedTrade o ON o.id = d.observedTradeId
      WHERE d.isDemo = 0
    )
    SELECT decision, m, COUNT(*) n FROM first_seen WHERE rn = 1 GROUP BY decision, m
    """).fetchall()
    last = {}
    counts = defaultdict(Counter)
    for r in opp:
        d, m, n = r["decision"], r["m"], r["n"]
        if m not in last:
            s = db.execute("SELECT yesPrice FROM MarketSnapshot WHERE marketId=? AND isDemo=0 "
                           "ORDER BY collectedAt DESC LIMIT 1", (m,)).fetchone()
            if s is None or s["yesPrice"] is None:
                last[m] = None
            else:
                p = float(s["yesPrice"])
                last[m] = 1 if p >= 0.90 else (0 if p <= 0.10 else None)
        counts[d]["n"] += n
        if last[m] is not None:
            counts[d]["labelled"] += n
    print(f"\n   1b. live DB -- clock {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}, "
          f"same dedup key and label rule recomputed ({time.time()-t0:.1f}s)")
    cov_table(counts)
    print("       A gap between 1a and 1b is artifact staleness: the committed CSV is not rebuilt")
    print("       by ml-daily.sh, so it drifts from the book it describes.")

    # ---- 2. the card's own gate ----
    print("\n2. THE CARD'S REFUTATION FLOOR -- 'label derivable for >=50% of declined rows'")
    for d in DECLINED:
        n, l = counts[d]["n"], counts[d]["labelled"]
        if not n:
            continue
        ok = (l / n) >= FLOOR
        print(f"   {d:<11}{l:>8,}/{n:<8,} = {pct(l, n):5.2f}%   -> "
              f"{'FLOOR MET (premise refuted)' if ok else 'FLOOR MISSED (card stands)'}")

    # ---- 3. label basis, per arm ----
    print("\n3. LABEL BASIS ON THE DECLINED POPULATION -- last-snapshot 0.90/0.10 proxy vs")
    print("   OutcomeReview.finalOutcome (the venue's own resolved label), BINARY markets only")
    mk = {}
    for r in db.execute("""
        SELECT j.marketId m, o.finalOutcome fo, j.decision dec
        FROM DecisionJournal j JOIN OutcomeReview o ON o.decisionJournalId = j.id
        WHERE j.isDemo = 0 AND o.finalOutcome IS NOT NULL
        GROUP BY j.marketId, o.finalOutcome, j.decision"""):
        e = mk.setdefault(r["m"], {"fo": r["fo"].strip().lower(), "acted": False, "declined": False})
        if r["dec"] == "paper_copy":
            e["acted"] = True
        else:
            e["declined"] = True
    binary = {m: v for m, v in mk.items() if v["fo"] in ("yes", "no")}
    print(f"   reviewed markets {len(mk):,}: binary Yes/No {len(binary):,} "
          f"({pct(len(binary), len(mk)):.1f}%) | token-named, unlabelable this way "
          f"{len(mk)-len(binary):,} ({pct(len(mk)-len(binary), len(mk)):.1f}%)")

    def check(sub, label):
        ag = dg = ab = 0
        for m in sub:
            s = db.execute("SELECT yesPrice FROM MarketSnapshot WHERE marketId=? AND isDemo=0 "
                           "ORDER BY collectedAt DESC LIMIT 1", (m,)).fetchone()
            if s is None or s["yesPrice"] is None:
                ab += 1
                continue
            p = float(s["yesPrice"])
            y = 1 if p >= 0.90 else (0 if p <= 0.10 else None)
            if y is None:
                ab += 1
                continue
            if (y == 1) == (sub[m]["fo"] == "yes"):
                ag += 1
            else:
                dg += 1
        n = ag + dg
        print(f"   {label:<18} markets={len(sub):>5,} determinable={n:>5,} agree={ag:>5,} "
              f"disagree={dg:>4,} abstain/no-snapshot={ab:>4,} agreement={pct(ag, n):6.2f}%")

    check(binary, "all binary")
    check({m: v for m, v in binary.items() if v["acted"] and not v["declined"]}, "acted-only")
    check({m: v for m, v in binary.items() if v["declined"]}, "declined-touched")

    print("\n   READ: the acted arm reproduces the documented 99.5%; the declined arm now carries")
    print("   its own number instead of inheriting it. Abstentions are NULL labels, never 0 -- an")
    print("   open market must not be trained as a loss.")


if __name__ == "__main__":
    main()
