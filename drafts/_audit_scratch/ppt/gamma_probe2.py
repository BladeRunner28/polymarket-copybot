import json, urllib.request, collections

def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "copybot-audit/1.0"})
    return json.load(urllib.request.urlopen(req, timeout=30))

CRYPTO = ["btc", "bitcoin", "eth", "ethereum", "solana", "crypto", "token", "airdrop", "fdv", "market cap"]
POLFIN = ["election", "president", "senate", "congress", "nominee", "parliament", "prime minister",
          "fed", "rate cut", "inflation", "cpi", "gdp", "recession", "tariff", "stock", "nasdaq",
          "s&p", "earnings", "shutdown", "impeach", "poll", "vote", "governor", "mayor"]

def our_rate(text):
    t = (text or "").lower()
    if any(w in t for w in CRYPTO):
        return 0.07
    if any(w in t for w in POLFIN):
        return 0.04
    return 0.05

rows = []
for off in (0, 100, 200, 300):
    try:
        ms = get(f"https://gamma-api.polymarket.com/markets?limit=100&offset={off}&active=true&closed=false&order=volume24hr&ascending=false")
    except Exception as e:
        print("FAIL offset", off, e); continue
    for m in ms:
        fs = m.get("feeSchedule") or {}
        rows.append({
            "slug": m.get("slug"), "q": (m.get("question") or "")[:70],
            "rate": fs.get("rate"), "exp": fs.get("exponent"), "takerOnly": fs.get("takerOnly"),
            "rebate": fs.get("rebateRate"), "feesEnabled": m.get("feesEnabled"),
            "feeType": m.get("feeType"), "takerBase": m.get("takerBaseFee"), "makerBase": m.get("makerBaseFee"),
            "ours": our_rate(m.get("question") or ""),
        })

print("sampled markets:", len(rows))
c = collections.Counter((r["rate"], r["rebate"], r["takerOnly"], r["exp"]) for r in rows)
print("\nfeeSchedule distribution (rate, rebateRate, takerOnly, exponent) -> n:")
for k, v in c.most_common():
    print("  ", k, "->", v)

mismatch = [r for r in rows if r["rate"] != r["ours"]]
print(f"\nour keyword map MISMATCHES live rate: {len(mismatch)}/{len(rows)}")
for r in mismatch[:20]:
    print(f"   live={r['rate']} ours={r['ours']} rebate={r['rebate']} | {r['slug']} | {r['q']}")
