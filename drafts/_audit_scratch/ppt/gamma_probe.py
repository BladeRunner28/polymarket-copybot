import json, sys, urllib.request

url = "https://gamma-api.polymarket.com/markets?limit=6&active=true&closed=false&order=volume24hr&ascending=false"
req = urllib.request.Request(url, headers={"User-Agent": "copybot-audit/1.0"})
data = json.load(urllib.request.urlopen(req, timeout=30))
print("markets:", len(data))
for m in data[:6]:
    fs = m.get("feeSchedule") or m.get("fee_schedule")
    print("-", m.get("slug"), "| vol24h", m.get("volume24hr"), "| feeSchedule =", json.dumps(fs))
keys = set()
for m in data:
    keys |= set(m.keys())
print("\nhas feeSchedule key in payload:", "feeSchedule" in keys)
print("keys containing 'fee':", [k for k in sorted(keys) if "fee" in k.lower()])
