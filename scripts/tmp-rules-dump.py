import json, sqlite3, sys

con = sqlite3.connect("prisma/dev.db")
row = con.execute("SELECT rulesJson FROM RuleSet WHERE version=70").fetchone()
if not row:
    print("no v70")
    sys.exit(0)
d = json.loads(row[0])
want = [
    "minConfidence", "minCopyScore", "maxWalletNotionalPctOfCap",
    "c200BandSizeFactor", "c200BandSizeFactorRange", "exposureCapBaseUsd",
    "baseSizeUsd", "sizeByConfidence", "maxPositionUsd", "maxOpenPositions",
    "kellyFraction", "maxMarketsPerHour", "bandSizeMultipliers", "longShotSizing",
]
for k in want:
    if k in d:
        print(k, "=", json.dumps(d[k])[:300])
print("--- keys ---")
print(", ".join(sorted(d.keys())))
