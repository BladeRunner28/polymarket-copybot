# Re-read: `wallet-cap-shadow-lane` (Rec 1a — price the per-wallet ceiling)

Read date: 2026-10-11 ~11:00 CDT (UTC-5). Live DB: `prisma/dev.db` (opened `?mode=ro`).
Repo: `/Users/xsnyde2/polymarket-copybot`. Read-only; no repo/DB writes.

---

## Card gate text (verbatim)

> GATE: VERIFY: data/wallet-cap-shadow-summary.json reports candidates > 0, marked > 0 once markets
> settle, and per-band/per-wallet would-have PnL; marker line `shadow-wallet-cap:` appears in the
> hourly shadow job log. Do NOT judge the rail on the raw veto count (the log line count overstates
> the cost — some would have died on the 0.80 cap or the drift gate).

DECIDED 2026-10-10 (user approved): option (a) LEAVE THE LANE RUNNING; re-read if the book
concentrates again (**a wallet approaching 25% of the cap**). No rule, no re-scope, no retirement.

---

## 1. LIVE LANE CHECK

### 1a. Summary file

```
$ cat data/wallet-cap-shadow-summary.json
{
  "generatedAt": "2026-10-11T15:33:44.797Z",
  "candidates": 0, "marked": 0, "awaitingResolution": 0,
  "wins": 0, "winRate": null, "wouldHavePnl": 0, "avgPnlPerTrade": null,
  "stakedUsd": 0, "byBand": {}, "byWallet": {},
  "firstCandidateAt": null, "lastCandidateAt": null
}
```

- `data/wallet-cap-shadow.jsonl` **does not exist** (`ls` → absent). The candidate feed has never
  written a row. So there are no per-band / per-wallet would-have PnL values to report — the
  counterfactual is EMPTY, not zero-valued.

### 1b. Marker line (last 24h) — the lane DOES run

Only `logs/cron/copybot-shadow-longshot.log` carries the marker (511 occurrences; **0** in
`copybot-monitor-score.log`, 0 in every other `logs/cron/*.log`). Job is hourly at :25.

Newest, verbatim (run header `=== run 2026-10-11T10:25:26 ===`, ~36 min before this read):

```
shadow-wallet-cap: +0 marked this run (backlog 0). Ceiling counterfactual: 0 would-be entries,
0 settled (0 wins, —), $0.00 on $0.00 staked (—/trade) | . Summary:
/Users/xsnyde2/polymarket-copybot/data/wallet-cap-shadow-summary.json
```

**The lane is running** (marker prints every hour, today included). **The lane is inert** — 0
candidates, 0 marked, 0 vetoes for ~21 days.

---

## 2. CONCENTRATION READ (distance to the re-read trigger)

### 2a. Current cap — read live, not guessed

Active RuleSet = **v61** (`RuleSet.active=1`, max version). Fields read from `rulesJson`:

| field | live value |
|---|---|
| `maxWalletNotionalPctOfCap` | **0.25** |
| `walletCapBasis` | **"delta"** (grandfathered) |
| `maxGrossExposureUsd` (base) | 1000 |
| `ddBasis` | **"realized"** |
| `maxMarketNotionalPctOfCap` | 0.2 |
| `c200MaxEntryPrice` | 0.8 |

`BotBankroll` (`botId='BANKROLL_200'`, updated 2026-10-11 10:04 CST):
`principal = 1900.0`, `cashBalance = 7656.73`, `realizedPnl = 5811.72`.
Open unrealized PnL = −49.42.

v46/v50 formula (`src/lib/exposure-cap.ts`, `ddBasis` selects the basis, here `realized`):

```
effective cap = base + 0.5 × max(0, netWorth − principal)
netWorth(realized) = principal + realizedPnl = 1900 + 5811.72 = 7711.72
effective cap = 1000 + 0.5 × (7711.72 − 1900) = $3,905.86
per-wallet ceiling = 0.25 × 3905.86 = $976.47
```

(The card cites the 2026-10-11 tuning review's **$3,899** → 25% = $975; my live figure is
**$3,905.86** → **$976.47**. The +$7 gap is just `realizedPnl` resolving since the review ran. The
scorer's own `[CAP-SHADOW]` line on 2026-10-11 prints **cap $3906**, agreeing with my derivation.)

### 2b. Largest OPEN wallet notional (right now)

`PaperTrade` **has** a `walletAddress` column (no join needed). Query:
`status='open' AND botId='BANKROLL_200'`, `SUM(simulatedPositionSize)` grouped by wallet.

| wallet | open notional | % of book | % of ceiling ($976.47) |
|---|---|---|---|
| `0x3413c803c3a6efc8d963afbce2dcee48d3738ff2` | **$50.00** | 90.9% | 5.1% |
| `0xfb07f48542d2b655e9d0bf1cc92a8a6feee8e2cc` | $1.25 | 2.3% | 0.1% |
| `0x885ffdf360e5b0b6e6acb963fb3f8ba2344c8ed9` | $1.25 | 2.3% | 0.1% |
| `0x85f031d069de300055900c4055c1baeb6bde3f67` | $1.25 | 2.3% | 0.1% |
| `0x4dd24f21b6c8adc8a059dca1a0346a3aa99214c2` | $1.25 | 2.3% | 0.1% |

Open book: **5 legs / $54.99 / 5 wallets** (all `isDemo=0`).

Top wallet `0x3413c…88ff2` is **absent** from `data/wallet-cap-baseline.json` → delta baseline 0 →
its ceiling is the plain `$976.47`.

### 2c. Distance to trigger — exact numbers

```
ceiling                 = $976.47
largest open wallet     = $50.00
plain-stock distance    = $976.47 − $50.00 = $926.47   (19.5× today's largest wallet)
gate fires when         : notional + new_size > baseline + $976.47
```

For the one wallet that is in the delta baseline and previously carried the book
(`0xb0c858…fe7f`, baseline $987.43): its effective ceiling would be $987.43 + $976.47 =
**$1,963.90** — and it currently holds **$0** open. No grandfather applies to today's leader.

---

## 3. TRAJECTORY — is the book concentrating?

Cap per day taken from the scorer's own `[CAP-SHADOW]` log line (last occurrence per local day) —
this IS the historical cap path, so no substitution was needed. Largest single-wallet notional per
local day, reconstructed from `openedAt` / `COALESCE(closedAt,resolvedAt)` (max over legs open at
any point in the day = intraday-peak proxy; the day-end snapshot is shown beside it).

| local day (UTC-5) | 14d intraday peak wallet $ | day-end peak wallet $ | that day's cap $ | ceiling (25%) $ | peak ÷ ceiling |
|---|---|---|---|---|---|
| 2026-09-28 | 229.97 | 120.00 | 2965 | 741.25 | 31.0% |
| 2026-09-29 | 121.23 | 101.23 | 2928 | 732.00 | 16.6% |
| 2026-09-30 | 101.23 | 100.00 | 2958 | 739.50 | 13.7% |
| 2026-10-01 | 100.00 | 100.00 | 3024 | 756.00 | 13.2% |
| 2026-10-02 | 269.67 | 216.02 | 3059 | 764.75 | 35.3% |
| 2026-10-03 | 259.66 | 100.00 | 3177 | 794.25 | 32.7% |
| 2026-10-04 | 100.00 | 100.00 | 3161 | 790.25 | 12.7% |
| 2026-10-05 | 117.08 | 100.00 | 3458 | 864.50 | 13.5% |
| 2026-10-06 | 239.90 | 239.90 | 3760 | 940.00 | 25.5% |
| 2026-10-07 | 279.90 | 100.00 | 3729 | 932.25 | 30.0% |
| 2026-10-08 | 109.97 | 100.00 | 3778 | 944.50 | 11.6% |
| 2026-10-09 | 232.39 | 176.20 | 3913 | 978.25 | 23.8% |
| 2026-10-10 | 196.12 | 11.22 | 3904 | 976.00 | 20.1% |
| 2026-10-11 | 59.97 | 50.00 | 3906 | 976.50 | **6.1%** |

**Flat, not concentrating.** The peak-wallet figure oscillates $100–280 with no upward trend, and
the denominator (cap) is *rising* ($2,965 → $3,906 over 14d), which pushes the ratio down. Today is
the LOWEST ratio of the window (6.1%). The largest wallet in 14 days ($279.90, 10-07) sat at 30% of
that day's ceiling — i.e. **~4× short of ever firing the gate**, and today's leader is ~16× short.

---

## 4. HISTORICAL BINDING — sanity check (2026-09-19 episode)

Reproduced, with one numeric correction:

- **109** `v58 per-wallet cap` lines in `logs/cron/copybot-monitor-score.log`, spanning
  `2026-09-19T14:10:54` → `2026-09-20T04:11:26` = **14.01 h** (card says "15h" — close enough).
- **Both sources agree, and both exist.** `DecicionJournal.risksJson LIKE '%v58 per-wallet cap%'`
  = **109** rows (same count; `reasonsJson` returns 0 — the reason is stored in `risksJson`, matching
  `scripts/audit-wallet-cap.py`). So the count is not log-only; log line ≡ journal row here (1 line
  per blocked C-200 leg).
- **Correction — the cap at binding:** the logged ceiling lines read
  `notional $1,003.66–1,098.65 > cap $431.13–433.64`, i.e. ceiling ≈ $433 → **exposure cap ≈
  $1,734–1,740**, NOT $1,251. The card's "**$1,251 cap**" is the **2026-09-18** value
  (`[CAP-SHADOW] declared(realized) cap $1251`, monitor log ~line 49389; also
  `drafts/2026-09-18-v56-basis-and-kalshi-lane-measurement.md`). By v58 activation on 09-19 13:25
  the cap had grown to ~$1,734. The episode and its cost are unchanged; only the card's cap label is
  stale. The raw veto count is explicitly **not** the rail's cost (card agrees); the priced
  counterfactual was never captured because `wallet-cap-shadow.jsonl` was created only with the
  rec-1a instrument on 09-20.

Binding stopped the moment the delta basis shipped: `data/wallet-cap-baseline.json`
`declaredAt = 2026-09-20T09:40:34Z` (RuleSet v59). **0 vetoes since 2026-09-20T04:11** — 21 days.

---

## 5. STATUS — one line

**Lane RUNNING but INERT: marker prints hourly today, yet 0 candidates / 0 marked / 0 vetoes for 21
days; today's largest open wallet is $50.00 against a $976.47 ceiling — $926.47 (19.5×) short of the
gate, the widest gap of the 14-day window — so the re-read trigger is NOT approaching, and the
card's gate clauses (`candidates > 0`, `marked > 0`) are INERT (unmet — nothing to mark).**

---

## Commands / SQL used (all read-only)

```sql
-- active ruleset
SELECT version, active FROM RuleSet ORDER BY version DESC LIMIT 3;
SELECT rulesJson FROM RuleSet WHERE active=1 ORDER BY version DESC LIMIT 1;   -- → maxWalletNotionalPctOfCap 0.25, walletCapBasis delta, maxGrossExposureUsd 1000, ddBasis realized

-- bankroll + net worth
SELECT botId, principal, cashBalance, realizedPnl, updatedAt FROM BotBankroll;   -- BANKROLL_200 1900 / 7656.73 / 5811.72
SELECT ROUND(SUM(unrealizedPnl),2) FROM PaperTrade WHERE botId='BANKROLL_200' AND status='open';  -- -49.42

-- concentration
SELECT walletAddress, COUNT(*), ROUND(SUM(simulatedPositionSize),2)
  FROM PaperTrade WHERE botId='BANKROLL_200' AND status='open'
  GROUP BY walletAddress ORDER BY 3 DESC;      -- top1 $50.00

-- veto provenance
SELECT COUNT(*) FROM DecisionJournal WHERE risksJson LIKE '%v58 per-wallet cap%';  -- 109
SELECT COUNT(*) FROM DecisionJournal WHERE reasonsJson LIKE '%v58 per-wallet cap%'; -- 0 (wrong column)
```

```bash
grep -ac "shadow-wallet-cap:" logs/cron/copybot-shadow-longshot.log          # 511
grep -ac "shadow-wallet-cap:" logs/cron/copybot-monitor-score.log           # 0
grep -ac "v58 per-wallet cap" logs/cron/copybot-monitor-score.log           # 109
grep -an "^=== run\|shadow-wallet-cap:" logs/cron/copybot-shadow-longshot.log | tail -4
ls data/wallet-cap-shadow.jsonl                                             # absent
```

Cap-source code confirmed: `src/lib/exposure-cap.ts:26` (`effectiveExposureCap`),
`scripts/score-trades.ts:194-260` (cap, per-wallet map, delta ceiling),
`src/lib/shadow-wallet-cap.ts` (instrument), `src/lib/wallet-cap-basis.ts` (`baselineFor`).

---

## Caveats

1. **Card's "$1,251 cap" is stale** (that was the 09-18 cap; the 09-19 binding ran at ~$1,734). The
   109-veto / ~14h episode reproduces exactly.
2. **Veto count provenance:** 109 comes from BOTH the monitor log AND `DecisionJournal.risksJson`
   (they are equal). It is not a cost figure — the card says so, and no priced counterfactual exists
   because the shadow instrument post-dates the episode.
3. **Trajectory caveat:** the "14d intraday peak" column counts every leg open at any point in the
   day (a leg opened and closed same-day is counted once), so it slightly overstates a simultaneous
   snapshot; the day-end column is the strict snapshot. Both agree on the direction (flat/falling).
4. **Cap basis:** computed on the live `ddBasis="realized"`; the scorer's own `[CAP-SHADOW]` line
   prints cap $3906 today, matching. Historical caps are the logged values, not re-derived.
5. **Basis is `delta` (grandfathered):** the trigger for a *pre-existing* wallet is
   `baseline + $976.47`, not `$976.47`. This raises, not lowers, the bar — the leader today has
   baseline 0, so its trigger is the plain $976.47.
