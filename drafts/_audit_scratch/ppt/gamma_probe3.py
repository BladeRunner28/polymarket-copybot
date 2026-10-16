import json, urllib.request, collections

def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "copybot-audit/1.0"})
    return json.load(urllib.request.urlopen(req, timeout=30))

CRYPTO = ["btc", "bitcoin", "eth", "ethereum", "solana", "crypto", "token", "airdrop", "fdv", "market cap"]
POLFIN = ["election", "president", "senate", "congress", "nominee", "parliament", "prime minister",
          "fed", "rate cut", "inflation", "cpi", "gdp", "recession", "tariff", "stock", "nasdaq",
          "s&p", "earnings", "shutdown", "impeach", "poll", "vote", "governor", "mayor"]

def ours(text):
    t = (text or "").lower()
    if any(w in t for w in CRYPTO):
        return 0.07
    if any(w in t for w in POLFIN):
        return 0.04
    return 0.05

def bucket(text):
    t = (text or "").lower()
    if any(w in t for w in CRYPTO):
        return "crypto"
    if any(w in t for w in POLFIN):
        return "pol/fin"
    return "default"

rows = []
for off in range(0, 500, 100):
    try:
        ms = get(f"https://gamma-api.polymarket.com/markets?limit=100&offset={off}&active=true&closed=false&order=volume24hr&ascending=false")
    except Exception as e:
        print("FAIL", off, e); continue
    for m in ms:
        fs = m.get("feeSchedule") or {}
        rows.append({
            "slug": m.get("slug"), "q": m.get("question") or "",
            "rate": fs.get("rate"), "rebate": fs.get("rebateRate"),
            "enabled": m.get("feesEnabled"), "feeType": m.get("feeType"),
            "takerBase": m.get("takerBaseFee"), "makerBase": m.get("makerBaseFee"),
            "ours": ours(m.get("question") or ""), "bucket": bucket(m.get("question") or ""),
            "vol": m.get("volume24hr") or 0,
        })

print("n =", len(rows))
print("\n[1] feeSchedule present vs feesEnabled:")
c = collections.Counter((r["rate"] is not None, bool(r["enabled"]), r["feeType"], r["takerBase"], r["makerBase"]) for r in rows)
for k, v in c.most_common(): print("   rate_present=%s feesEnabled=%s feeType=%s takerBase=%s makerBase=%s -> %d" % (k[0], k[1], k[2], k[3], k[4], v))

print("\n[2] match of our keyword map per our own bucket (only markets WITH a live rate):")
for b in ("crypto", "pol/fin", "default"):
    sub = [r for r in rows if r["bucket"] == b and r["rate"] is not None]
    m = [r for r in sub if r["rate"] == r["ours"]]
    over = [r for r in sub if r["ours"] > r["rate"]]
    under = [r for r in sub if r["ours"] < r["rate"]]
    print(f"   {b:8s} n={len(sub):3d} exact={len(m):3d} overcharge={len(over):3d} undercharge={len(under):3d}"
          + (f"  live_rates={sorted(set(r['rate'] for r in sub))}" if sub else ""))

print("\n[3] fee $/share at p=0.50 (rate*0.25) by observed rate:")
for r in sorted(set(x["rate"] for x in rows if x["rate"] is not None)):
    print(f"   rate {r}: {r*0.25:.5f}/share, 100-share roundtrip diff vs our default 0.05 = {abs(r-0.05)*0.25*100:.4f} USDC")

print("\n[4] volume-weighted share of sample where our map is wrong:", end=" ")
tot = sum(r["vol"] for r in rows if r["rate"] is not None)
wrong = sum(r["vol"] for r in rows if r["rate"] is not None and r["rate"] != r["ours"])
print(f"{wrong/tot*100:.1f}% of 24h volume" if tot else "n/a")
