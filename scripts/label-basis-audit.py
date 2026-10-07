"""Label-basis audit: which target is each measurement arm actually scoring?

Read-only. Card `measurement-label-integrity`. A leg can carry three different targets:

  * `market outcome`  — did the token we hold resolve as the winner (`didOutcomeWin()`), the correct
    target for a probability arm (Brier/AUC on p).
  * `realizedPnl > 0` — did OUR leg make money. Depends on the exit policy under test, so an arm
    labelled this way measures "was this leg profitable", not "did the signal predict the outcome".
  * `resolvedAt IS NOT NULL` — the naturally-settled subset only. 73.9% of finished legs close early,
    so this subset is not the book and it is winner-skewed.

This prints the populations, the price arm's Brier/AUC under each basis and lane, and the
PnL-vs-outcome disagreement rate over legs that carry both.

Run: python3 scripts/label-basis-audit.py
"""
import sqlite3

DB = "prisma/dev.db"
con = sqlite3.connect("file:%s?mode=ro" % DB, uri=True)


def auc(ps, ys):
    pairs = sorted(zip(ps, ys))
    ranks, i, r = [], 0, 1
    while i < len(pairs):
        j = i
        while j + 1 < len(pairs) and pairs[j + 1][0] == pairs[i][0]:
            j += 1
        avg = (r + (r + (j - i))) / 2
        for _ in range(i, j + 1):
            ranks.append(avg)
        r += j - i + 1
        i = j + 1
    pos = [k for k, (_, y) in zip(ranks, pairs) if y == 1]
    neg = [k for k, (_, y) in zip(ranks, pairs) if y == 0]
    if not pos or not neg:
        return float("nan")
    return (sum(pos) / len(pos) - (len(pos) + 1) / 2) / len(neg)


def brier(ps, ys):
    return sum((p - y) ** 2 for p, y in zip(ps, ys)) / len(ys)


print("POPULATIONS (PaperTrade, isDemo=0)")
for label, q in [
    ("all legs", "SELECT COUNT(*) FROM PaperTrade WHERE isDemo=0"),
    ("finished (closed or resolved)", "SELECT COUNT(*) FROM PaperTrade WHERE isDemo=0 AND realizedPnl IS NOT NULL"),
    ("  of which resolvedAt is not null", "SELECT COUNT(*) FROM PaperTrade WHERE isDemo=0 AND resolvedAt IS NOT NULL"),
    ("  of which early exit (closedAt only)", "SELECT COUNT(*) FROM PaperTrade WHERE isDemo=0 AND resolvedAt IS NULL AND closedAt IS NOT NULL"),
    ("still open", "SELECT COUNT(*) FROM PaperTrade WHERE isDemo=0 AND resolvedAt IS NULL AND closedAt IS NULL"),
    ("carrying an OutcomeReview", "SELECT COUNT(DISTINCT paperTradeId) FROM OutcomeReview WHERE paperTradeId IS NOT NULL"),
]:
    print(f"  {label:38s} {list(con.execute(q))[0][0]:7d}")

rows = list(
    con.execute(
        """SELECT p.botId, o.detectedPrice, p.entryPrice, p.realizedPnl,
                  (p.resolvedAt IS NOT NULL) res, (p.closedAt IS NOT NULL) clo
           FROM PaperTrade p
           JOIN DecisionJournal d ON d.id = p.decisionJournalId
           JOIN ObservedTrade o ON o.id = d.observedTradeId
           WHERE p.isDemo = 0 AND p.realizedPnl IS NOT NULL"""
    )
)
print("\nPRICE ARM (p = detection mid, label = realizedPnl>0) BY POPULATION BASIS")
print(f"  {'subset':32s} {'n':>6s} {'base wr':>8s} {'Brier':>7s} {'AUC':>7s}")


def show(name, sub):
    if not sub:
        return
    ps = [(m if m is not None else e) for _, m, e, _, _, _ in sub]
    ys = [1 if pnl > 0 else 0 for _, _, _, pnl, _, _ in sub]
    print(f"  {name:32s} {len(sub):6d} {sum(ys)/len(ys):8.3f} {brier(ps, ys):7.4f} {auc(ps, ys):7.4f}")


show("all finished", rows)
show("resolvedAt only", [r for r in rows if r[4]])
show("closedAt only (early exit)", [r for r in rows if r[5] and not r[4]])
for lane in ("BANKROLL_200", "STANDARD"):
    sub = [r for r in rows if r[0] == lane]
    show(f"{lane} all finished", sub)
    show(f"{lane} resolvedAt only", [r for r in sub if r[4]])
    show(f"{lane} closed only", [r for r in sub if r[5] and not r[4]])
print(f"\n  early-exit share of finished legs: "
      f"{sum(1 for r in rows if r[5] and not r[4])/len(rows):.3f}")

# PnL label vs outcome label: only where both exist
both = list(
    con.execute(
        """SELECT p.realizedPnl, r.finalOutcome, p.outcome
           FROM PaperTrade p JOIN OutcomeReview r ON r.paperTradeId = p.id
           WHERE p.isDemo = 0 AND p.realizedPnl IS NOT NULL AND r.finalOutcome IS NOT NULL"""
    )
)
disagree = sum(
    1
    for pnl, final, out in both
    if (1 if pnl > 0 else 0) != (1 if (out or "").strip().lower() == (final or "").strip().lower() else 0)
)
print(f"\nLABEL DISAGREEMENT (legs carrying both a realizedPnl and an OutcomeReview.finalOutcome)")
print(f"  n={len(both)}  PnL sign disagrees with the outcome-label comparison: {disagree} "
      f"({disagree/len(both):.3f})")
print("  -> those are early exits profiting on a losing token (and the reverse): a PnL-labelled arm")
print("     scores a point there that has nothing to do with the model's probability.")
print("\nINSTRUMENTS: scripts/mark-shadow-jev.ts and scripts/mark-shadow-longshot.ts label by market")
print("outcome through didOutcomeWin() (correct target). scripts/analyze-score-separation.py uses")
print("status IN ('closed','resolved') with a realizedPnl label (right population, exit-contaminated")
print("label). scripts/rag-vs-price-baseline.py quotes resolvedAt-only arms and states the caveat.")
