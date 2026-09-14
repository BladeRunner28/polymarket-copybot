# Change 1 applied (08:00 ET C-200 gate) · Change 2 instrumented (band-exemption counterfactual)

**Date:** 2026-09-13 · **Approver:** user, in the C-200 daily-report thread ("I approve")
**Source:** C-200 daily report (job `84e37616f39a`) proposals 1 and 2, both approved.

---

## 1. Change 1 — 08:00 ET C-200 entry blackout: **APPLIED**

| | |
|---|---|
| What | C-200 (BANKROLL_200) new entries stamped 08:00–08:59 ET are skipped |
| Where | `src/lib/hour-policy.ts` → `C200_ONLY_BLACKOUT_HOURS_ET = {8}` + `isHourBlackedOut(botId, etHour)`, called from `scripts/score-trades.ts` |
| Tests | `tests/hour-policy.test.ts` (8 tests; suite 167/167 green, `tsc` clean) |
| Revert | remove `8` from the set — no DB change, picked up on the next score run |

**Scope correction found during recon.** The hour gate in `score-trades.ts` has applied to **both** books since v44. 08:00 ET is C-200-negative but **STANDARD-positive**:

- C-200 08:00 ET: 34 rows, **−$71.12** (raw z = −2.26)
- STANDARD 08:00 ET: 250 rows, **+$1,048.17**

A blanket gate would therefore have removed a winning hour from STANDARD. Shipped as a C-200-only set; the shared 20:00 behaviour is unchanged.

**Two honest caveats.**

1. **20:00 ET was already gated** (v41/v48) — the report's "gate 08 + 20" was half a no-op; in-window 20:00 C-200 volume is 0 by construction.
2. **08:00 loses significance on the decision-level (deduped) sample** — all-time z −2.26 → **−1.77**, in-window N=8. So this is an accepted-risk small gate, not a proven one. Blast radius is genuinely tiny: 8 C-200 entries / $25 staked over 14 days. Applied on user approval; one-line revert if the Oct 8 read says otherwise.

**Verify (7d):** `grep 'hour blackout 8:00 ET' logs/cron/copybot-monitor-score.log` → C-200 lines only, zero STANDARD lines; C-200 08:00 entries = 0.

## 2. Change 2 — `<0.20` exit exemption: **instrumented, not switched**

The report asked to exempt `<0.20` entries from tier-1/hard-age exits *and* log a counterfactual for 7 days, explicitly framed as "measure-first, not flip-the-switch". Implemented as measurement with **zero behaviour change**:

- `data/exit-recovery.jsonl` now carries **72h and 168h** post-cut buckets (was 1h/6h/24h/final), a tracking window of **26h → 192h**, and `entryPrice`/`band` tags on every mark. That makes a cut ticket's recovery measurable *inside the horizon we would actually hold*.
- Reader: `scripts/analyze-band-exit-exemption.ts` → decision-level sample, **hold-to-horizon** vs realized, with **hold-to-settlement** as a secondary line. Writes `data/band-exit-exemption.json`.

**Why settlement is not the primary metric.** Of the 71 all-time decision-level `<0.20` tickets, **43 are unpriced by settlement** — they are long-dated markets (LPL season, MLS cup, UCL winner, WNBA finals) that will not resolve for months. That *is* the capital-lock risk an exemption would create: median `<0.20` life is 25.4h, and 86% of open cost sits in the band.

**Historical read (not decisive):** `tier1_cut` n=43, realized −$179.63, only 13 priced to settlement. The report's headline (+3.2% on 91 rule-closed vs +119.5% on 17 resolved) is partly **survivorship** — the rule cuts what isn't working. The instrument exists to settle this forward rather than relitigate it backward.

**Decision rule (pre-registered):** read at ≥7 days (2026-09-20) using only buckets with **≥20 priced tickets**; exempt `<0.20` from tier-1 only if hold-24h/72h beats realized on that base — and the exemption must name its horizon.

## 3. Finding carried, not acted on

The **shared 20:00 ET blackout blocks a STANDARD-positive hour** (+$887.61 on 252 rows). Same pattern that forced the C-200-only scoping above. It is a re-test item, not a revert: those rows span pre-v44 and pre-v52 mechanics. Card `standord-2000-shared-blackout-finding`; slice it post-v52 at the Oct 8 close.

## 4. Files

- `src/lib/hour-policy.ts`, `scripts/score-trades.ts`, `tests/hour-policy.test.ts` (Change 1)
- `src/lib/exit-recovery.ts`, `scripts/analyze-band-exit-exemption.ts` (Change 2 instrument)
- Roadmap: `change1-c200-0800-blackout` (Done), `change2-longshot-exit-exemption` (In Progress, clock 2026-09-13), `standord-2000-shared-blackout-finding` (Backlog), `change2-oct8-gates` (band gate still queued)
