# Tuning review #30 — approval execution (all four recs)

**Approved 2026-09-19 in-thread ("I approve").** Applied the same day, CDTs:
earliest action 13:20, last 13:25. RuleSet **v57 → v58**. Commit `d9aacd8` (v57's
code half) + the v58/tooling commit below.

Window under review: 2026-09-18 07:00 → 2026-09-19 06:52 CDT, 95 monitor runs.
Report: `logs/cron/tuning-review.md` (cycle #30).

**Two of the four recommendations rested on premises that this execution
disproved** (rec 2's settlement-lag story, rec 4's telemetry break). Both were
re-derived from the live data before shipping; the corrections are in §C and the
deliverable for those two is the *instrument* the rec asked for, not the code
change its premise implied. Nothing was refused — rec 4's *implied* change was
not shipped because shipping it would have written duplicate journal rows.

---

## A · Rec 1 — per-wallet notional ceiling (SHIPPED, live)

**Problem.** The C-200 book had exactly one concentration rail (v55's per-market
ceiling) and it had just gone non-binding, while a single wallet went from 34 to
59 open rows. Measured at apply time:

| | value |
|---|---|
| C-200 open book | 90 rows / **$1,314.89** / 10 wallets |
| top wallet `0xb0c8c85813…fe7f` | **$1,059.74 = 80.6%** of open cost |
| top-3 | **94.1%** |
| concentration history | 57.4% → 45.0% → 61.2% → 84.6% → 80.6% |
| v55 per-market rail | 10 blocks, **all** 09-18 08:36–08:52 at the pre-growth $125.12 ceiling, 0 since; max 2 legs/market ✅ |
| effective cap | $1,740.34 (`1000 + 0.5 × (3381 − 1900)`, realized basis) |

The v55 rail being *measured and non-binding* is what made the wallet rail
addable: the two no longer confound each other (the precondition #29 set).

**Root cause / where the hole was.** `scripts/score-trades.ts` built
`c200MarketLegs`/`c200MarketNotional` from the open book and gated them per leg,
but the book was never grouped by `walletAddress`, and no rule field existed to
name a wallet limit (`src/lib/rules.ts` had `maxMarketNotionalPctOfCap` only).
The only wallet-scoped limits were `maxCopiesPerWalletPerDay` (count of copies,
not notional) and `minWalletGlobalScore` (quality, not exposure).

**Fix.** A fraction-of-cap field, evaluated exactly like v55's — same loop, same
final-size check, same journal surface:

- `src/lib/rules.ts` — `maxWalletNotionalPctOfCap` (default `0` = legacy/disabled).
- `src/lib/exposure-cap.ts` — pure `walletCapDecision({notionalAlready, sizeUsd, notionalCapUsd})`,
  mirroring `marketCapDecision` (which keeps its leg limit; a wallet leg limit is
  a different rule and was not approved).
- `scripts/score-trades.ts` — `walletAddress` added to the open-book select, a
  `c200WalletNotional` map, `c200WalletNotionalCap = pct × c200ExposureCap`, and a
  per-leg gate immediately after the v55 block on `BANKROLL_200` only
  (`[BANKROLL_200] v58 per-wallet cap (…)` + the same reason on the decision row).
- `tests/wallet-cap.test.ts` — 6 cases (clean pass, boundary inclusive, the live
  84.6% wallet blocked immediately, dust under the ceiling, `0` disables, cap
  scaling). Suite 188 → **194/194**.
- `scripts/apply-v58-wallet-cap.ts` — prints the before-state and the live
  consequence arithmetic, `--dry-run` writes nothing. Applied with changedBy
  `hermes-v58-perwallet-cap-approved`; `RuleChange` audit row
  `cmu8pwm7f000313ljlf1cnjil` (`{"maxWalletNotionalPctOfCap":0}` → `{"…":0.25}`).

**Ceiling live: 0.25 × $1,740.34 = $435.09 per wallet.** The top wallet is
$624.66 over it, so its new legs are blocked until the book unwinds; the #2
wallet ($132.70) has $302.39 of room, and 8 of 10 wallets are untouched.

**Freeze classification** (`references/measurement-window-governance.md`): a NEW
threshold is a rule change and the Kelly window (Sep 8–Oct 8) is pre-registered
as no-rule-change — so this ships on the user's explicit override for cause, and
is recorded as such in the apply script and on the Kelly pre-commit card.

**Verify (7 d, 2026-09-26).** `python3 scripts/audit-wallet-cap.py` →
top-1 share ≤ 25.0% **and** journaled `per-wallet cap` blocks == monitor-log lines
(today: 0 == 0; the reason string is new).

**Revert.** `applyRuleChanges([{field:"maxWalletNotionalPctOfCap", newValue:0}])`.

## B · Rec 2 — phase streak on both bases, convention named (SHIPPED, measurement only)

`query_bankroll.js` now prints, every run:

- `Phase stability (T+0): 0/7` … "- convention: closedAt ?? resolvedAt, read NOW,
  today provisional"
- `Phase stability (settled, T+3): 1/7 … last 3 days excluded while they settle;
  THIS is the basis a phase advance is judged on"
- the 14-day table **with leg counts** (`09-17 +12.36 (31) · 09-16 +743.38 (57) …`)
- a `Reproduce:` line carrying this machine's UTC offset
  (`date((COALESCE(closedAt,resolvedAt)/1000)-18000,'unixepoch')`)
- an as-recorded snapshot per day in `data/phase-streak-history.json` (the one
  thing the DB cannot reconstruct: what a day read *when it ended*), which turns
  the T+0-vs-settled question into a measured quantity instead of a memory test.

No gate, threshold or trading behaviour changed — this is reporting/accounting
only, i.e. EXEMPT under the freeze rules.

## C · Corrections (both premises re-derived, one code change held back)

| Claim in #30 | Measured 2026-09-19 | Verdict |
|---|---|---|
| Sep 17 "banked as a miss at +$12.36 (31), reads +$714.75 (38) now" → settlement lag | Sep 17 **local** = +$12.36 / 31 legs == #29's number exactly; Sep 17 **UTC** = +$714.75 / 38 == #30's number exactly — computed from the *same* rows | **Day-boundary mismatch.** The reviewer's ad-hoc SQL bucketed UTC days; the gate (and the ladder, and the Overview cards) bucket local days |
| Sep 16 (cross-check) | local +$743.38 / 57 == #28; UTC +$31.03 / 51 == #30 | same mechanism, so it is not a one-off |
| "hour-blackout 20:00 ET: 52 log lines vs 26 journal rows = half the blackout invisible" | **52 lines, 26 rows, ratio exactly 2.00 in all four runs**, all 26 rows carrying both books' reasons; 08:00 ET 41 lines == 41 rows | **Artifact.** The line is per LEG, the row per DECISION; 20:00 ET is in the *shared* set (`hour-policy.ts`) so it blocks both books → 2 lines per row by construction |

Rec 4's *implied* fix (write a journal row for the 20:00 path the way the 08:00
path does) was **not** shipped: the 08:00 path writes the *decision* row, so the
only way to make the counts equal is a second row per blocked leg — that would
double-count those decisions in the skip histogram and the calibration refit
sample, i.e. it would have created the class of defect this repo has already
spent three cycles removing (the copy-count trap). Delivered instead:
`scripts/audit-blackout-parity.py` (asserts both identities per run), a Done card,
and a reviewer-cron standing input so the next reviewer *checks* it rather than
"fixing" it.

**The independent check that the T+0 read is not simply lagging on this book:**
Sep 16 local reads +$743.38 / 57 legs today and read the same in #28 two days
earlier — the bucket did not move. The settlement-lag instrument now exists
either way, so the next window can refute or confirm that quantitatively.

## D · Rec 3 — v57's code half committed + the Oct 8 read windowed

- **`d9aacd8`** — "v57 code half (tuning #30 rec 3): commit the rule's code
  alongside RuleSet v57": `src/lib/rules.ts` (drift fields +
  `effectiveDriftTolerance`), `src/lib/scoring/trade.ts`, `src/lib/paper.ts`
  (`applyKellyBandRails` → `[0.20, 0.60)`), `tests/paper-sizing.test.ts` (the v51
  contract change B deliberately reverses), `tests/drift-band.test.ts`,
  `scripts/apply-v57.ts`. No behavior change — the code is what was already
  running. `git status --short src/ tests/` → **0 lines** (the rec's verify line).
- **Kelly pre-commit card** (`precommit-mid-oct-kelly-gate`) now records that
  **v57 and v58 both landed mid-window** and that the Oct 8 verdict is attributed
  **by `ruleSetVersion`** (v55/v56/v57/v58 sub-windows via
  `analyze-calibration.py --since`), never as one total.
- **Tuning-review cron prompt** (job `34d312687d17`, 7,348 → 9,702 chars) gained
  three standing inputs: the daily-attribution convention, the per-leg-vs-per-
  decision parity identity, and the mid-window rule-change attribution rule.
  Backup: `~/.hermes/cron/jobs.json.bak-tuning30-standing-inputs-20260919`.
- Card hygiene: `v56-drawdown-basis-decision` → **Done** (the basis is a real
  RuleSet row: `ddBasis:"realized"`, carried by v57/v58, 0 gate vetoes in-window).

---

## E · Figures that moved (before → after, all re-derived at apply time)

| Figure | #30 read (06:52) | At apply (13:25) | Cause |
|---|---|---|---|
| C-200 open book | 75 rows / $1,179.45 | **90 rows / $1,314.89** | 13 new opens in the thaw, not a rule change |
| Effective cap (realized basis) | $1,734.50 | **$1,740.34** | realized ledger +$5.84 |
| Top-wallet share | 84.6% / $997.38 | **80.6% / $1,059.74** | book grew faster than that wallet |
| RuleSet | v57 | **v58** | rec 1 |
| Wallet ceiling | — (no field) | **$435.09/wallet** | rec 1 |
| Phase streak | 0/7 (single line) | **T+0 0/7 · settled 1/7** | rec 2 (read only) |
| Tests | 188 | **194** | rec 1 |

## F · Verification evidence (run today)

```
RuleSet v58 active  … maxWalletNotionalPctOfCap 0 → 0.25 (ceiling $435.09 on the current cap)
RuleChange cmu8pwm7f000313ljlf1cnjil changedBy=hermes-v58-perwallet-cap-approved
npx tsc --noEmit          → clean
npm test                  → 194/194 (16 → 17 files)
node query_bankroll.js    → both streak lines + reproduce SQL (see §B)
python3 scripts/audit-blackout-parity.py
   20:00 ET 52 lines == 2 × 26 rows (2.00 in all 4 runs) | 08:00 ET 41 == 41
git status --short src/ tests/ → 0 lines
curl :3013/roadmap        → 200; cards v58-perwallet-cap / phase-gate-settled-read /
                            blackout-parity-measurement render
```

**Still open (deliberately):** the v58 block line has not yet appeared in the
monitor log. The first scoring cycle after the apply (run 13:23:46) loaded the new
module and completed clean — `No unscored trades.` — because the tracked whales
have produced **0 new observed trades** since ~13:08, so no copy candidate has
reached the per-leg loop where the gate lives. Evidence shipped instead: the unit
suite pins the boundary, the apply script printed the live consequence for the
actual book, and `scripts/audit-wallet-cap.py` is the standing read. The first
copy candidate from the 80.6% wallet will log
`[BANKROLL_200] v58 per-wallet cap (notional $X > cap $435.09) — skipping copy …`
and journal the same reason; the 7-day gate on the card is the first real sample.

## G · Not done, and why

- Nothing from the "not re-proposed" list touched (cadence axis QUIET, no
  threshold moves beyond rec 1's new field).
- The open *decisions* in the #30 report (v55 ceiling vs Kelly interaction,
  `kellyFraction`, the mid-price gate) were **not** folded into this approval —
  they remain their own cards, queued to the Oct 8 close.
