# C-200 daily report recs — execution (2026-09-20)

**Approved 2026-09-20 04:33 CDT** ("I approve") in reply to the 2026-09-19 18:00
daily report. Applied the same day, 04:40 CDT. RuleSet **v58 → v59**.
Builds on: `drafts/tuning30-approval-execution-20260919.md` (the #30 approvals).

Three items were on the table: **rec 1a** (price the freeze), **rec 1b** (extend the
exit-exemption read to 0.20–0.40 + pre-commit the rule), **rec 2** (fix the v58 rail
basis, override-class). The report's fourth suggestion — `c200LongshotBandFactor`
2.5 → ~4.0 — was explicitly sequenced *behind* rec 2's shadow read by the report
itself, so it stays queued and untouched (§E).

---

## A · Recon — the report's claims, re-derived before acting

| Report claim | Measured | Verdict |
|---|---|---|
| v58 "already binding, not non-binding" | **109 vetoed legs, 1–4 per cycle**, every cycle since 13:25 09-19 (still firing at 04:11 09-20) | ✅ confirmed (the "non-binding" comment referred to the *v55 market* rail, which is still non-binding) |
| "ceiling $433.64 while the wallet holds $1,003.64 = 2.36×" | ceiling **$430.97**, wallet **$987.43** at 04:40 = **2.29×** (both moved; ratio holds) | ✅ confirmed |
| "raise the ceiling 0.25 → 0.40 ($433 → $694) **fixes** it" | at 0.40 the ceiling is **$693.80** and the wallet still holds **$987.43** (1.42×) → **still frozen**, it merely unwinds ~$300 sooner | ❌ **void as a fix** — see §B |

So the approved "either/or" had exactly one working arm. I shipped it and named the
choice; the void arm is recorded on the card so it is not re-proposed.

## B · Rec 2 — the rail basis (SHIPPED, RuleSet v59)

**Problem, precisely.** The v58 rail capped a wallet's *whole* open notional. That
cannot bind gradually: a wallet already above the ceiling is frozen absolutely — it
may not even open a $2 dust leg — and stays dead until its book closes on its own
(~$556 of it, at the observed decay rate days-to-weeks). Measured cost in its first
15 h: **109 vetoes**, 1–4 per cycle, while entries fell from 43 (the morning) to 7.
This is a rail that was supposed to shape *accumulation*, not stop a wallet.

**Fix.** `walletCapBasis: "stock" → "delta"`, with a per-wallet snapshot frozen at
activation:

```
ceiling(wallet) = baseline(wallet) + maxWalletNotionalPctOfCap × effectiveCap
```

- `data/wallet-cap-baseline.json` — 11 wallets / $1,295.80, written once at
  activation (04:40:34 CDT), tagged with the RuleSet version and the cap it was
  computed against. It is **rule state, not a log**: regenerating it would walk the
  grandfather level upward, so the loader treats a missing file as "no grandfather"
  (plain ceiling) rather than recreating it.
- A wallet first seen **after** activation is absent → baseline 0 → plain ceiling.
  That is the intended treatment for new wallets, not a fallback.
- In force now: the top wallet's ceiling is **$1,418.40** ($987.43 grandfathered +
  $430.97 allowance), so it can add one full ceiling of new notional and is gated
  again after that; the ten other wallets are unchanged at exactly $430.97.
- Revert: `walletCapBasis: "stock"` (legacy semantics), or the pct field to 0 (off).

**Freeze classification.** Loosening a rail mid-Kelly-window is still a rule change
(`references/measurement-window-governance.md`): it ships on the user's explicit
approval and is recorded on `precommit-mid-oct-kelly-gate` alongside v57/v58 — the
Oct 8 verdict is attributed **by `ruleSetVersion`**, and the exposure rail is now
one of the sub-windows.

Artifacts: `src/lib/wallet-cap-basis.ts` (loader + `baselineFor`),
`src/lib/rules.ts` (`walletCapBasis`, default `"stock"`),
`scripts/score-trades.ts` (basis-aware ceiling; the log line names the basis and the
split), `tests/wallet-cap-basis.test.ts` (6 cases incl. the frozen-vs-grandfathered
arithmetic), `scripts/apply-v59-wallet-cap-basis.ts` (prints the per-wallet
consequence, `--dry-run` writes nothing). Suite **200/200** (18 files).

## C · Rec 1a — price the freeze (SHIPPED, write-only instrumentation)

`data/wallet-cap-shadow.jsonl` now records every **would-be copy** the ceiling
vetoed: the size it *would* have booked (Kelly/band sizing already applied), its
entry price **and band**, the wallet's notional and the ceiling at that moment,
score/confidence/TTR/spread/liquidity. `scripts/mark-shadow-longshot.ts` (hourly,
:25) marks each candidate to settlement through the adapter → parent-event fallback
and publishes `data/wallet-cap-shadow-summary.json`, split **by band** (the
calibration table's own edges) and **by wallet** — so the read joins directly to the
calibration table and to the per-wallet ROI ranking.

Rationale that the report itself supplied: the veto *count* overstates the cost,
because some would-be copies would have died on the 0.80 entry cap or the drift gate.
Reading `data/wallet-cap-shadow-summary.json` replaces counting log lines.

## D · Rec 1b — the exit-exemption read, extended and pre-committed

`scripts/analyze-band-exit-exemption.ts` gained `--band-min` and window+band-suffixed
outputs (the two arms can no longer clobber each other; the legacy all-time <0.20
file is untouched). Both arms were read today, the Change-2 clock's due date.

| Arm | Cuts | Realized | 1h | 6h | 24h (pre-named) | Settle |
|---|---|---|---|---|---|---|
| <0.20, since 09-13 | 10 | −$191.85 | −$81.08 (5) | −$46.94 (3) | −$25.87 (2) | −$19.95 (1) |
| 0.20–0.40, since 09-13 | 18 | −$48.75 | −$47.18 (11) | −$14.25 (8) | −$4.38 (1) | −$64.18 (9) |
| 0.20–0.40, all-time | 112 | −$75.92 | −$115.28 (34) | −$87.60 (26) | −$8.35 (8) | −$333.83 (41) |

*(n in parentheses = priced tickets at that horizon; the guarantee rule requires ≥20.)*

**Verdict: no exemption ships, and the 0.20–0.40 "exit-side" hypothesis is not
supported where the sample is adequate.** The two buckets that clear the 20-priced
bar (all-time 1h and 6h) are both **worse than the realized exit** — those cut
tickets kept falling, so the cut was right. The 24h hint (−$8.35 vs −$75.92) is 8
tickets; by the card's own pre-existing standard that is noise. The since-09-13 arm
is under-powered in every bucket (10 and 18 cuts).

**Pre-committed decision rule** (written to `exit-exemption-20-40-decision` before
the next read): an exemption ships for a band only if hold-to-horizon at the
**pre-named** horizon (24h for 0.20–0.40, 72h for <0.20) beats the realized PnL of
the cut tickets **on ≥20 priced tickets**, *and* the same direction holds all-time,
*and* ≥20 decisions were cut in the band. Failing the count test means **extend the
clock** — never decide on the near-miss.

## E · Not shipped (deliberate)

- **`c200LongshotBandFactor` 2.5 → ~4.0** — the report sequences it behind rec 2's
  shadow read ("it widens exactly the concentration Rec 2 is capping, so Rec 2's
  shadow read should land first"). The instrument (§C) now exists; the factor stays
  queued to the Oct 8 window close.
- **23:00 ET re-gating** — the report's own calibration says z = −0.79, not
  significant, and the un-gating reason (phantom Kalshi pricing) still holds. No
  action; recorded as a standing input so it stops resurfacing.
- The 0.60–0.80 premium-band gate stays queued to Oct 8 (its own card).

## F · Verification evidence

```
RuleSet v59 active — walletCapBasis "delta", maxWalletNotionalPctOfCap 0.25
RuleChange changedBy=hermes-v59-perwallet-basis-approved (2026-09-20 09:40:34Z)
data/wallet-cap-baseline.json — 11 wallets / $1,295.80, appliedWithRuleSet 59
apply-v59 --dry-run  → per-wallet consequence for stock vs delta (top: FROZEN 2.29x
                       → $430.97 of new notional allowed)
npx tsc --noEmit     → clean
npm test             → 200/200 (18 files)
analyze-band-exit-exemption → 3 arms written to 3 distinct files (table §D)
python3 scripts/audit-wallet-cap.py → 109 log lines == 109 journal rows
cron: c200-daily-report prompt 2,838 → 5,075 chars (standing inputs; backup
      jobs.json.bak-daily-report-standing-inputs-20260920)
roadmap → 200; new cards wallet-cap-shadow-lane (In Progress),
      exit-exemption-20-40-decision (Backlog, pre-committed rule), v58/v59 card
```

**Open / first-sample items.** The first scoring cycle started after the v59 apply
is the load-bearing check: the top wallet should open legs again, and any residual
veto must carry `basis delta: $X grandfathered + $Y allowance`. The shadow feed needs
a few days of settlements before its per-band read means anything (the card's gate
says so explicitly).
