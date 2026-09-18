# 2026-09-18: freeze cleared (v56) · Kalshi lane measured — it's ontology, not coverage

**Approver:** user — "I approve recommendation 1 with `--basis realized` and recommendation 2 with reviving the cross venue lane."
**Outcome:** rec 1 applied and verified. Rec 2 executed as far as the evidence allows — and the
evidence says reviving, as scoped, will not work. That's the finding below, with the numbers.

---

## 1. Rec 1 — drawdown basis → `realized` — **APPLIED, freeze cleared**

```
before   basis=mtm      26.5%  (peak $3409, NW $2507)   ← gate fires >20%, both lanes frozen
after    basis=realized  1.6%  (peak $2442, NW $2402)   ← clear
[CAP-SHADOW] declared(realized) cap $1251 vs realized-only cap $1251 … gap $0
```

Effective on the next scorer cycle, no restart; `note` + `basisDeclaredAt` recorded in
`data/c200-drawdown.json` (per #26 rec 2). Cap on the realized basis is $1,251.18 against a $471
book — nothing binds. Revert: `--basis mtm`, or `--reseed-peak` to keep MTM and re-seat the peak.

## 2. Rec 2 — revive the cross-venue lane: **built the matcher, and the measurement says don't**

The shadow book blamed matcher coverage (0% verified cross-listings). I built the instrumentation to
test that claim, and the claim is **half right — and the wrong half is the binding one**.

**What's true (a real defect):** Kalshi has **14,766 open events** (cursor exhausted over 74 pages —
`scripts/kalshi-slug-matcher.py`). The sidecar's `resolve_kalshi_match` walks
`MAX_EVENT_PAGES = 25 × 200 = 5,000` — **34% of the inventory** — at `MATCH_THRESHOLD = 0.55`.

**Why fixing that buys nothing:** scored against the **complete** index, our 202 in-window markets:

| band | markets |
|---|---|
| no shared distinctive token | 19 |
| 0.01–0.24 | 39 |
| 0.25–0.39 | 116 |
| 0.40–0.59 | 28 |
| **≥0.60** | **0** |

144 of 202 clear 0.25 (**62.9% of stake**) — and almost all of it is **wrong**. Eyeballed samples:

- "highest temperature in **Moscow** / Shanghai / Guangzhou / Amsterdam" → all match **KXHIGHTTTN (Trenton)**
- MLB "Atlanta Braves vs Chicago Cubs" → **KXWNBAGAME** Chicago vs Atlanta (different league)
- KHL "Traktor vs Lokomotiv Yaroslavl" → KXKHLGAME **Barys** vs Lokomotiv (different game)
- "West Ham spread" → Millwall vs West Ham (different fixture)

**Where genuine counterparts exist, they are different contracts:**

- Kalshi `KXFED-26OCT/DEC` are rate-**level** markets; ours is a **25bp-move** question → scores 0.25
- Kalshi's Bolsonaro market is **vote-percentage**; ours is a **win** question → 0.50
- Kalshi's Emmy events are **Daytime**; ours is a primetime series → 0.14
- Kalshi's Valorant events are **tournament-winner**; ours is a **head-to-head** match → 0.07

**So the constraint is contract ontology, not coverage.** A perfect index with a token matcher
returns either nothing (threshold 0.55, which is why the shadow reads 0%) or garbage (lower the
threshold and Trenton wins Moscow). Reviving it needs **semantic mapping plus strike-level contract
parsing**, evaluated on **verified contract-equivalent pairs** — not on coverage %.

**Recommendation: park the lane as an execution path** (the shadow costs nothing and keeps
accumulating). If you want it revived properly, scope it as that semantic build and I'll write the
plan — the acceptance test is "N verified equivalent pairs with a real edge", not a coverage figure.

## Artifacts

- `scripts/kalshi-coverage-probe.py` — first probe (market-level; reproduced the 0% illusion at a
  25k-market cap — kept as the cautionary case).
- `scripts/kalshi-slug-matcher.py` — complete event index (cached, TTL) + stricter matcher →
  `data/kalshi-slug-map.json`, `data/kalshi-event-index.json`.
- `data/roadmap.json` — cards `v56-drawdown-basis-realized` (Done),
  `kalshi-lane-ontology-not-coverage` (decision).
