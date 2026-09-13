"""Check the resolution of trades booked as losses with a non-binary outcome label.

Reads a TSV of (outcome, conditionId, question, realizedPnl) and asks the keyless
CLOB endpoint for the market's tokens + winner, so 'structurally unresolvable'
can be separated from 'genuinely lost'.
"""
import json
import sys
import urllib.request
import urllib.error

path = sys.argv[1] if len(sys.argv) > 1 else "/tmp/misres.tsv"
rows = [l.rstrip("\n").split("|") for l in open(path) if l.strip()]
print(f"{len(rows)} rows to check\n")

for outcome, cond, q, pnl in rows:
    print(f"-- booked outcome='{outcome}' pnl={pnl}")
    print(f"   q={q[:70]}")
    print(f"   conditionId={cond}")
    url = f"https://clob.polymarket.com/markets/{cond}"
    try:
        with urllib.request.urlopen(url, timeout=25) as r:
            d = json.load(r)
    except urllib.error.HTTPError as e:
        print(f"   CLOB HTTP {e.code} — not resolvable by this conditionId")
        continue
    except Exception as e:
        print(f"   CLOB error: {e}")
        continue
    toks = d.get("tokens") or []
    print(f"   closed={d.get('closed')} question={(d.get('question') or '')[:60]}")
    winners = []
    for t in toks:
        print(f"     token={t.get('outcome')!r} winner={t.get('winner')} price={t.get('price')}")
        if t.get("winner"):
            winners.append(t.get("outcome"))
    print(f"   -> winning token(s): {winners}")
    lab = outcome.strip().upper()
    hit = any(lab and (lab in str(w).upper() or str(w).upper() in lab) for w in winners)
    print(f"   -> label matches winner: {hit}")
