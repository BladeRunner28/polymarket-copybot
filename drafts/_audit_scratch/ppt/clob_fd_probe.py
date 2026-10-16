import json, urllib.request

def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "copybot-audit/1.0"})
    return urllib.request.urlopen(req, timeout=30)

# 1) live active market from gamma, take conditionId, then ask CLOB for the market
g = json.load(get("https://gamma-api.polymarket.com/markets?limit=3&active=true&closed=false&order=volume24hr&ascending=false"))
cid = g[0].get("conditionId")
print("gamma sample feeSchedule:", json.dumps(g[0].get("feeSchedule")), "| feeType:", g[0].get("feeType"))
print("conditionId:", cid)

for url in (f"https://clob.polymarket.com/markets/{cid}",
            f"https://clob.polymarket.com/clob-markets/{cid}"):
    try:
        raw = get(url).read().decode()
        d = json.loads(raw)
        print("\nURL", url, "-> keys:", sorted(d.keys())[:25])
        print("   fd block:", json.dumps(d.get("fd")))
        print("   fee-ish fields:", {k: v for k, v in d.items() if "fee" in k.lower() or k in ("fd",)})
    except Exception as e:
        print("\nURL", url, "FAILED:", e)
