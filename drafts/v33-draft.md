# DRAFT — v33: Fix Stale-Exit Recycling (hard max-age) + Ops Fixes from Tuning Review #9

**Status:** ✅ IMPLEMENTED (v33 active 2026-08-29 21:14 CT; v34 regulatory clamp + v35 daily-report changes added 21:33 CT; sidecar audit complete — see `sidecar-crash-audit.md`).
**Source:** `copybot-tuning-review-daily` Cycle #9 (2026-08-29 07:13, deepseek). Full text: `~/.hermes/cron/output/3e9805c12911/2026-08-29_07-13-40.md`. Follow-ups: v34/v35 from the 18:07 daily report (implemented; see below).

---

## What the review recommended (6 items)

| # | Recommendation | Disposition |
|---|---|---|
| 1 | `caffeinate`/always-on during trading windows (cadence collapse: 51 runs/day vs 144 scheduled, 65.7% gaps >15.5 min, worst 21.3h) | **Implement** — launchd KeepAlive `caffeinate -imsu` |
| 2 | Sidecar crash root-cause + restart-frequency alert (>3/h → Discord) | **Implement** — restart-rate tracker in watchdog; root-cause noted as follow-up |
| 3 | Hold v32 drift 0.006 + v31 minCopyScore 70; don't tighten until cadence fixed | **No change** — already live (verified: active RuleSet v32) |
| 4 | Fix v29 stale-exit recycling (only 1 recycle fired all window) before raising the 150-cap | **Implement** — v33 `staleExitHardHours` 168 (hard max-age) |
| 5 | Enforce 25-wallet cap at scan-wallets write time (31 marked track vs 25 cap) | **Implement** — demo-track cleanup (the overage is 25 live + 6 stale demo rows) |
| 6 | Keep this review job on deepseek | **No change** — already done (yesterday) |

---

## Why the v29 stale exit can't fire (the core finding)

v29's rule: close a C-200 position when `age ≥ 72h AND winMove < 5%`. Diagnosed against the live DB:

- Open C-200 book: 73 positions aged 24–72h (notional $257.45, unrealized +$27.17) + **80 positions older than 168h** (notional **$202.36**, unrealized **+$112.08**).
- Of the 80 aged ≥72h: **all 80 have winMove ≥ 5%** (min +7.8%, max +136.9%, avg +30.3%) — some are **800–900 hours old (37 days)**.
- Result: the qualifying set for v29 tier-1 (old AND didn't move) is **empty** → 0–1 recycles ever, while the real capital drag — *stuck winners on markets that never resolve* — is immune to the rule and sits in the book forever.

The rule closes losers-that-didn't-move. The actual problem is winners-that-never-resolve. The fix must close on **age alone**, not on lack of movement.

## Change 1 — v33 ruleset: hard max-age recycle (`staleExitHardHours`)

New rule field (Rules interface + DEFAULT_RULES + applied as v33):

| Field | v32 | v33 | Meaning |
|---|---|---|---|
| `staleExitHardHours` | — | **168** | hard max age (h) for open BANKROLL_200 positions; older ⇒ close at last price regardless of winMove |

`scripts/update-pnl.ts` sweep logic becomes two-tier (tier-2 checked first):

```ts
if (t.botId === "BANKROLL_200") {
  const ageHours = (Date.now() - t.openedAt.getTime()) / 3_600_000;
  const winMove = (price - t.entryPrice) / t.entryPrice;
  // v33 tier 2: hard max-age — a C-200 hold past 7 days is dead capital
  // (short-TTR thesis: 2–72h lanes); realize it and recycle the cash.
  if (ageHours >= rules.staleExitHardHours) {
    await closePaperTrade(t.id, price,
      `stale ${ageHours.toFixed(0)}h ≥ ${rules.staleExitHardHours}h hard max-age — v33 capital recycling`);
    recycled++;
  } else if (ageHours >= rules.staleExitHours && winMove < rules.staleExitMinMove) {
    // v29 tier 1 unchanged: 72h + <5% move → close
    await closePaperTrade(t.id, price, /* existing reason */);
    recycled++;
  }
}
```

**Expected first-sweep effect:** ~80 positions closed, **~$202 notional recycled to cash, +$112 unrealized booked as realized** (report-positive: realized PnL is the reporting currency). Open book drops to ~73 positions (~$257), leaving ~77 slots under the 150-cap for fresh sweet-spot/short-TTR copies. After the sweep, any C-200 hold reaching 168h closes on the hourly tick.

**Not changed:** v29 tier-1 (72h/<5%) stays; scoring/drift/copyScore untouched (per review #3, no tightening until cadence is fixed). STANDARD bot exempt (long-dated holds are its thesis).

**Rollback:** deactivate v33 / reactivate v32 (versioned path). Code is additive and gated by the field.

## Change 2 — always-on (review #1)

New launchd agent `com.xsnyde2.copybot-caffeinate` running `/usr/bin/caffeinate -imsu` with `KeepAlive` (idle/system/disk sleep + user-active assertions; display may still sleep — least intrusive while fixing the 21h-gap cadence collapse). Bootstrapped and verified via `pmset -g assertions` (PreventUserIdleSystemSleep).

## Change 3 — watchdog restart-frequency alert (review #2)

`~/.hermes/scripts/copybot-sidecar-watchdog.sh`: append an epoch timestamp per restart to `/tmp/copybot-sidecar-restarts.log`, prune >1h entries, count. If ≥4 restarts in the last hour, prepend a **🔴 CRASH-LOOP** escalation to the Discord alert (fires even when the individual restart succeeds).

## Change 4 — 25-wallet cap truthful (review #5)

The overage is **25 live + 6 stale demo wallets** (demo rows are excluded from the cap query in live mode and never re-scanned). `scripts/scan-wallets.ts` gains a live-mode cleanup: demote any `status: "track" AND isDemo: true` rows to `watch` (inert in live mode; non-destructive). Tracked count becomes exactly 25 on the next scan.

## Verification plan (post-implementation)

1. `tsc --noEmit` clean; `npm test` green (existing 53).
2. `apply-v33` → RuleSet v33 active + RuleChange audit row.
3. Manual `update-pnl` run → completion line shows `recycled = ~80`; DB: 80 closed, realizedPnl sum +$112, BotBankroll cash +~$202, open book ~73.
4. Watchdog: `bash -n` + dry count logic.
5. Launchd: agent loaded, `pgrep caffeinate` alive, assertion present in `pmset -g assertions`.
6. Next hourly scan-wallets tick demotes demo-track rows (verify on next natural run or manual).
