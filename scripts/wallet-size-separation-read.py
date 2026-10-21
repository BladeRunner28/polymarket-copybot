"""Dry-run: what changes if wallet quality stops setting SIZE (admission-only)?

Reconstructs each stored paper_copy decision's size from its OWN stored components,
then recomputes it with the wallet term removed and the remaining weights renormalised
(0.30 wallet / 0.70 other -> other*1.0). Writes nothing.

Weights from src/lib/scoring/trade.ts:147-154:
  wallet*0.30 + catFit*0.15 + entryTiming*0.20 + spread*0.10 + liquidity*0.15 + thesis*0.10
"""
import json
import sqlite3

DB = "/Users/xsnyde2/polymarket-copybot/prisma/dev.db"
ROOT = "/Users/xsnyde2/polymarket-copybot"

# --- active rules (read the live row, not DEFAULT_RULES) ---
con = sqlite3.connect(DB)
con.row_factory = sqlite3.Row
row = con.execute("SELECT rulesJson, version FROM RuleSet WHERE active=1").fetchone()
R = json.loads(row["rulesJson"])
print("active RuleSet v%s" % row["version"])
KEYS = ["highScoreCapMin", "sweetSpotMinScore", "sweetSpotSizeUsd", "highScoreCapUsd",
        "baseSizeUsd", "confidenceSizeBonus", "deadZoneSizeFactor", "longshotSizeFactor",
        "deadZoneMinPrice", "deadZoneMaxPrice", "longshotMaxPrice"]
for k in KEYS:
    print("  %-22s %s" % (k, R.get(k)))

W = {"wallet": 0.30, "cat": 0.15, "entry": 0.20, "spread": 0.10, "liq": 0.15, "thesis": 0.10}
assert abs(sum(W.values()) - 1.0) < 1e-9
OTHER = 1.0 - W["wallet"]


def clamp(v, lo=0.0, hi=100.0):
    return max(lo, min(hi, v))


def clamp_size(v):
    return max(0.25, min(20.0, v))


def bucket_size(score, confidence):
    if score >= R["highScoreCapMin"]:
        return R["highScoreCapUsd"]
    if score >= R["sweetSpotMinScore"] and score < R["highScoreCapMin"]:
        return R["sweetSpotSizeUsd"]
    return R["baseSizeUsd"] + max(0.0, confidence - 0.5) * R["confidenceSizeBonus"]


q = """
SELECT d.id, d.copyScore, d.confidence, d.walletQualityScore, d.categoryFitScore,
       d.entryTimingScore, d.spreadScore, d.liquidityScore, d.thesisScore,
       d.simulatedPositionSize, p.botId
FROM DecisionJournal d
JOIN PaperTrade p ON p.decisionJournalId = d.id
WHERE d.decision = 'paper_copy' AND d.isDemo = 0
  AND d.simulatedPositionSize > 0
  AND d.walletQualityScore IS NOT NULL
  AND p.botId != 'BANKROLL_200'
"""
rows = con.execute(q).fetchall()
print("\nSTANDARD paper_copy legs with full components: %d" % len(rows))

exact, adjustable = [], []
for r in rows:
    comp_sum = (r["walletQualityScore"] * W["wallet"] + r["categoryFitScore"] * W["cat"]
                + r["entryTimingScore"] * W["entry"] + r["spreadScore"] * W["spread"]
                + r["liquidityScore"] * W["liq"] + r["thesisScore"] * W["thesis"])
    # copyScore is rounded to 0.1 AFTER genuine additive adjustments (cluster +25,
    # regulatory caps, sentiment). Rows whose composite does not reconstruct are
    # those adjusted rows; they are reported, not silently folded in.
    if abs(comp_sum - r["copyScore"]) <= 0.15:
        exact.append((r, comp_sum))
    else:
        adjustable.append((r, comp_sum))

print("  reconstruct exactly (no extra adjustment): %d" % len(exact))
print("  carry an extra adjustment (excluded):      %d" % len(adjustable))

shift = {"same": 0, "up": 0, "down": 0}
tot_old = tot_new = 0.0
moves = []
for r, comp in exact:
    new_score = clamp((comp - r["walletQualityScore"] * W["wallet"]) / OTHER)
    new_conf = max(0.0, min(1.0, (new_score - R["watchlistScore"]) / (100 - R["watchlistScore"])))
    old_sz = r["simulatedPositionSize"]
    new_sz = clamp_size(bucket_size(new_score, new_conf))
    tot_old += old_sz
    tot_new += new_sz
    if abs(new_sz - old_sz) < 0.005:
        shift["same"] += 1
    else:
        shift["down" if new_sz < old_sz else "up"] += 1
        moves.append((r["id"], r["walletQualityScore"], comp, r["copyScore"], new_score, old_sz, new_sz))

print("\n--- size effect on the %d exact rows ---" % len(exact))
print("  unchanged %d | reduced %d | increased %d" % (shift["same"], shift["down"], shift["up"]))
print("  notional old $%.2f -> new $%.2f  (delta $%+.2f, %+.1f%%)"
      % (tot_old, tot_new, tot_new - tot_old, 100 * (tot_new - tot_old) / max(tot_old, 1e-9)))
if moves:
    print("\n  sample moves (id | walletScore | comp | copyScore | newScore | old$ -> new$):")
    for m in moves[:12]:
        print("   %s | %5.1f | %5.2f | %5.1f | %5.1f | $%.2f -> $%.2f" % m)

# component-sum residual across ALL paper_copy rows, for the write-up
res = con.execute("""
SELECT COUNT(*) FROM DecisionJournal
WHERE decision='paper_copy' AND isDemo=0 AND walletQualityScore IS NOT NULL
""").fetchone()[0]
print("\nall STANDARD+other paper_copy rows with components: %d (exact %d = %.1f%%)"
      % (res, len(exact), 100.0 * len(exact) / max(res, 1)))
