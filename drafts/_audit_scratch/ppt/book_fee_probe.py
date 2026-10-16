import json, sqlite3, urllib.request, urllib.error

DB = "/Users/xsnyde2/polymarket-copybot/prisma/dev.db"
con = sqlite3.connect(DB)
con.row_factory = sqlite3.Row
cur = con.cursor()

# recent C-200 trades (botId partitions portfolios)
cur.execute("""
  select t.marketId, t.entryPrice, t.simulatedPositionSize, t.status, t.outcome,
         (select conditionId from MarketSnapshot s where s.marketId = t.marketId order by s.collectedAt desc limit 1) as cond
  from PaperTrade t
  where t.botId = 'BANKROLL_200'
  order by t.openedAt desc limit 25
""")
rows = [dict(r) for r in cur.fetchall()]
print("trades sampled:", len(rows), "| with conditionId:", sum(1 for r in rows if r.get("cond")))

def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "copybot-audit/1.0"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode())

CRYPTO = ["btc", "bitcoin", "eth", "ethereum", "solana", "crypto", "token", "airdrop", "fdv", "market cap"]
POLFIN = ["election", "president", "senate", "congress", "nominee", "parliament", "prime minister",
          "fed", "rate cut", "inflation", "cpi", "gdp", "recession", "tariff", "stock", "nasdaq",
          "s&p", "earnings", "shutdown", "impeach", "poll", "vote", "governor", "mayor"]
def proxy(text):
    t = (text or "").lower()
    if any(w in t for w in CRYPTO): return 0.07
    if any(w in t for w in POLFIN): return 0.04
    return 0.05

out = []
for r in rows:
    cid = r.get("cond")
    rec = {"marketId": r["marketId"], "entry": r["entryPrice"], "size_usd": r["simulatedPositionSize"], "status": r["status"]}
    if not cid:
        rec["note"] = "no conditionId in MarketSnapshot"; out.append(rec); continue
    # gamma by conditionId
    g = None
    try:
        g = fetch(f"https://gamma-api.polymarket.com/markets?condition_ids={cid}")
        g = g[0] if isinstance(g, list) and g else None
    except Exception as e:
        rec["gamma_err"] = type(e).__name__
    rec["gamma_live"] = bool(g)
    rec["gamma_feeType"] = (g or {}).get("feeType")
    gs = (g or {}).get("feeSchedule") or {}
    rec["gamma_rate"] = gs.get("rate") if isinstance(gs, dict) else None
    # clob-markets fd
    fd = None
    try:
        c = fetch(f"https://clob.polymarket.com/clob-markets/{cid}")
        fd = c.get("fd")
    except Exception as e:
        rec["clob_err"] = type(e).__name__
    rec["clob_fd"] = fd
    rec["venue_rate"] = (fd or {}).get("r") if isinstance(fd, dict) else rec.get("gamma_rate")
    q = (g or {}).get("question") or r["marketId"]
    rec["proxy_rate"] = proxy(q)
    out.append(rec)

print(json.dumps(out, indent=1)[:4000])
with open("book_fee_probe.json", "w") as f:
    json.dump(out, f, indent=1)

nv = [r for r in out if r.get("venue_rate") is not None or r.get("gamma_live")]
print("\n--- summary ---")
print("trades probed:", len(out))
print("gamma still serves:", sum(1 for r in out if r.get("gamma_live")))
print("clob fd resolved:", sum(1 for r in out if r.get("clob_fd")))
diffs = [r for r in out if r.get("venue_rate") is not None and r["venue_rate"] != r["proxy_rate"]]
print("proxy != venue:", len(diffs), "of", sum(1 for r in out if r.get("venue_rate") is not None))
