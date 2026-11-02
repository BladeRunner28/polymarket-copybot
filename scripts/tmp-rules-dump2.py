import json, sqlite3

con = sqlite3.connect("prisma/dev.db")
d = json.loads(con.execute("SELECT rulesJson FROM RuleSet WHERE version=70").fetchone()[0])
want = [
    "baseSizeUsd", "confidenceSizeBonus", "sweetSpotSizeUsd", "sweetSpotMinScore",
    "sweetSpotMaxScore", "shortTtrSizeUsd", "whaleSizeUsd", "highScoreCapUsd",
    "highScoreCapMin", "kellyMaxSizeUsd", "kellyMaxBankrollPct", "kellyMinEdgePct",
    "c200LongshotBandFactor", "c200LongshotBandFloor", "longshotSizeFactor",
    "longshotMaxPrice", "deadZoneSizeFactor", "c200DeadZoneBandFactor",
    "maxGrossExposureUsd", "maxCopiesPerCycle", "maxCopiesPerWalletPerDay",
    "shortTtrMaxCopiesPerCycle", "maxMarketNotionalPctOfCap", "walletCapBasis",
    "minTimeToResolutionHours", "maxEntryPrice", "c200MaxEntryPrice",
]
for k in want:
    if k in d:
        print(f"{k} = {json.dumps(d[k])}")
