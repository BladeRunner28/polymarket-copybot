#!/usr/bin/env python3
"""Build the wallet/token lists the archive joins need (idempotent, read-only).

  /tmp/our_wallets.txt   every wallet we track, observe or have copied (WalletProfile u ObservedTrade u PaperTrade)
  /tmp/copied_wallets.txt  the subset we have actually copied
  /tmp/our_assets.txt    every CLOB token id in our L2 asset map (data/l2-asset-map.jsonl)
"""
import json
import os
import sqlite3

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
W = "/tmp/our_wallets.txt"
C = "/tmp/copied_wallets.txt"
A = "/tmp/our_assets.txt"


def build_lists(force: bool = False) -> None:
    if force or not os.path.exists(W):
        con = sqlite3.connect(f"file:{ROOT}/prisma/dev.db?mode=ro", uri=True)
        rows = con.execute("""
            SELECT DISTINCT address FROM WalletProfile
            UNION SELECT DISTINCT walletAddress FROM ObservedTrade
            UNION SELECT DISTINCT walletAddress FROM PaperTrade""").fetchall()
        with open(W, "w") as fh:
            fh.write("\n".join(sorted(str(r[0]).lower() for r in rows if r[0])) + "\n")
        rows = con.execute("SELECT DISTINCT walletAddress FROM PaperTrade WHERE isDemo=0").fetchall()
        with open(C, "w") as fh:
            fh.write("\n".join(sorted(str(r[0]).lower() for r in rows if r[0])) + "\n")
        con.close()
    if force or not os.path.exists(A):
        ids = set()
        with open(os.path.join(ROOT, "data", "l2-asset-map.jsonl")) as fh:
            for line in fh:
                try:
                    ids.update(str(x) for x in json.loads(line).get("assetIds", []))
                except Exception:
                    pass
        with open(A, "w") as fh:
            fh.write("\n".join(sorted(ids)) + "\n")


if __name__ == "__main__":
    build_lists(force=True)
    for p in (W, C, A):
        print(p, sum(1 for _ in open(p)))
