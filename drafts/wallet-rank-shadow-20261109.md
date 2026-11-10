# Wallet-rank shadow (Lane A, approved 2026-11-09): armed — and the set the audit measured has already been replaced

Card: `t_7c91b4a1` → roadmap `crowdintel-wallet-fdr-audit` (parent measurement `t_2d407fb6`,
2026-10-29). Operator approved the **shadow build only** on 2026-11-09: two ranking arms
(`hard-q`, `shrunk`) plus a coverage gate, no live selection change.
Served at <http://localhost:3013/drafts/wallet-rank-shadow-20261109>.

**Status: ARMED, not measured.** `shadow_start = 2026-11-09T18:13:32Z`, forward window 0 bets, both
arms `PENDING`. Nothing about what the bot copies, holds or risks changed.

---

## 1. The key insight: the parent's +2.59pp reproduces exactly — on a set that no longer exists

The proposal was built on one sentence from 2026-10-29: the tracked SET is pooled **+2.59pp over its
own entry bands** (t +2.61, p 0.0046, 2,630 bets / 2,367 markets), which is why a second arm was
added to preserve BREADTH rather than gate down to an elite. That number is not a measurement
artifact — **it reproduces to the decimal today**, on the parent's own 25-wallet set and its own
truth join (band baselines reproduce to 0.01pp: 2.39 / 4.07 / −0.30 / −2.21 / −2.08). What changed is
the SET:

| set (truth join) | wallets | bets | markets | band-excess | raw |
|---|---|---|---|---|---|
| parent-era set, parent join (8,619 mkts) | 25 | 2,630 | 2,367 | **+2.59pp** (t +2.61, p 0.0046) | +3.16pp |
| parent-era set, today's join (25,269 mkts) | 25 | 3,306 | 2,917 | +1.59pp (t +1.79, p 0.037) | +2.49pp |
| **frozen set at arm, today's join** | **34** | 16,511 | 15,539 | **+0.09pp** (t +0.29, p 0.387) | +0.23pp |
| frozen set at arm, parent join | 34 | 3,074 | 2,568 | −1.12pp (t −1.34) | −0.59pp |

Splitting the parent-era set by what the scanner did to it since makes the swing explicit:

| cohort | wallets | parent join | today's join |
|---|---|---|---|
| **dropped since 10-29** (now `status='watch'`) | 14 | **+4.95pp** (t +4.16, p < 0.0001) | **+3.98pp** (t +3.57, p 0.0002) |
| kept in both sets | 11 | −2.04pp (t −1.18) | −1.91pp (t −1.35) |
| added since 10-29 | 23 | −0.66pp (t −0.71) | +0.25pp (t +0.79) |

**The entire positive pooled read lives in the 14 wallets the screen has since demoted to `watch`;
the 11 wallets that survived both sets read negative on both joins.** 14 of 25 wallets (56%) were
replaced in ten days — and the churn is live: the set held 25 wallets at 17:56Z today, 34 at 18:13Z,
and the demotions' `updatedAt` runs through the present hour.

Why it matters for this card, and why it is not a re-litigation: the proposal's premise was a
statement about *a particular 25 wallets over a particular window*, and the live selection has since
discarded most of them. That is precisely the failure mode the card's own baseline rule guards
against — **freeze the set at arm time**, because "keep the current track set" is a moving object.

And it changes what the two arms are testing, in a concrete way:

| arm | admits (of 1,132 coverage-eligible) | of the 14 demoted | of the 11 kept | of the 23 added |
|---|---|---|---|---|
| `hard-q` (BH q ≤ 0.10, n_eff ≥ 8, excess > 0) | 54 | **0** | 0 | 2 |
| `shrunk` (EB-shrunk excess > 0) | 589 | **10** | 3 | 10 |

The breadth arm re-admits 10 of the 14 wallets that carry the +4.95pp; the membership arm re-admits
none of them. **Caveat, stated plainly:** that +4.95pp is measured on the same data that selected
those wallets, so it is evidence about what the current process discarded — not a forward claim.
The shadow is what prices it forward.

The scanner's own columns say why they were dropped: the demoted cohort carries a **lower**
`globalScore` (median 76.8 vs 91.6 for the kept) and lower `roi30d` (0.471 vs 0.598) while having
*more* resolved trades (103.5 vs 48). Whether that score is reading marks rather than settled
outcomes is exactly the question card `label-integrity-wallet-win-filter` owns — named here as a
mechanism to test, not asserted.

## 2. What shipped (shadow only)

| artifact | what it is |
|---|---|
| `scripts/wallet-rank-shadow.py` | the shadow: two arms, coverage gate, forward scoring, pre-registration freeze, harness self-test |
| `scripts/wallet-fdr-cohort-split.py` | read-only decomposition of the cohort read by print time / join membership |
| `data/wallet-rank-shadow-state.json` | the **frozen pre-registration**: `shadow_start_ms`, rule text, the 34-wallet baseline snapshot, both admitted sets, instrument hashes, truth-at-arm |
| `data/wallet-rank-shadow.json` | this run's full read (arms, coverage gate, forward read, verdicts) |
| `data/wallet-rank-shadow-history.jsonl` | one line per run (the cron appends here) |
| `data/wallet-rank-shadow-selftest.json` | harness proof on a historical split (§6) |
| `data/wallet-fdr-audit-20261109.json` | today's audit machine table on the widened truth (the parent's 10-29 table is untouched) |
| `data/wallet-fdr-truth.json` | settlement truth cache, widened 9,851 → 29,338 markets |
| `scripts/cron-scripts/copybot-wallet-rank-shadow.sh` | daily driver: `--fetch 1500`, appends history, silent unless an arm leaves PENDING |
| `~/.hermes/scripts/copybot-wallet-rank-shadow.sh` | cron shim (execs the repo copy; exits 0 with a log line until the branch is merged) |

The arms, frozen at arm time and never re-chosen by a later refit:

- **hard-q** — admit iff `n_eff ≥ 8` AND BH `q ≤ 0.10` AND band-excess > 0. The membership arm: it
  tests whether the screen's value is in the wallets it can NAME.
- **shrunk** — rank by empirical-Bayes band-excess shrunk toward the band prior by `n_eff`
  (`τ² = max(0, var(x) − mean(se²))`), admit every coverage-eligible wallet with shrunk excess > 0.
  The breadth arm.
- **baseline** — "keep the current track set": the 34 `status='track'` wallets snapshotted at
  `shadow_start`, so a later status edit cannot move the goalpost.
- **coverage gate** — no ranking decision on a wallet with `n_eff < 8`, none on a wallet with no
  settled print; applied to both arms, never to the baseline.

## 3. The shadow at arming (what today's fit freezes)

| item | measured at `shadow_start` |
|---|---|
| join | 436,193 first-print bets over 1,535 wallets; 25,269 settled markets (6.35% of 398,069 conditionIds) |
| BH family | m = 1,352 wallets (n_eff ≥ 3, finite t; 4 degenerate cluster sets excluded, q < p violations 0) |
| coverage-eligible | 1,132 wallets with n_eff ≥ 8 (403 screened out thin) |
| EB shrink | τ = 4.77pp (var(x) 79.27, mean(se²) 56.49) |
| **hard-q admits** | **54** wallets (2 of the frozen 34) |
| **shrunk admits** | **589** wallets (13 of the frozen 34) |
| baseline | 34 track wallets, frozen |
| coverage gate on the frozen set | 28 measured · 3 with n_eff < 8 · 6 with no settled print |
| selection hash | `cbff41b4a168279c` |
| instruments at arm | audit `ba799721…96f79`, shadow hash recorded in the state file |

## 4. The decision rule (unchanged, pre-registered)

On the forward window (every print at/after `shadow_start`), same bands, same market-clustered read
for both arms: an arm ships out of shadow only if it (a) **beats "keep the current track set" on
forward band-excess per market** and (b) has a **market-clustered bootstrap 95% CI excluding zero**,
on **≥ 200 forward settled bets**. A tie or a loss kills it and the null is recorded. Fewer than 200
forward bets ⇒ `PENDING`, never `PASS`.

Recorded beside the binding rule, non-binding: the arm-minus-baseline **difference** CI. The card's
wording ("a market-clustered CI excluding zero") admits both readings; the binding one is applied
literally and the stricter one is printed next to it so a PASS cannot be read without it.

**Refutation:** if neither arm beats keep-the-set, wallet selection is worth keeping as-is, no
ranking product gets built, and that null is recorded — no re-slicing.

## 5. Where the observation lands (Lane A — recommendation only)

Both arms stay armed, as approved. The prior going in is **not** the one the proposal was written
with: the breadth arm's reason (+2.59pp for the set) is a property of a set that is 56% gone, and on
the current set the pooled read is +0.09pp. What the breadth arm retains is a *different*, concrete
reason: it is the only one of the two that re-admits the demoted cohort (10 of 14) instead of
discarding it (0 of 14).

**Recommendation, not applied — one line for the operator:** let both arms run to the 200-bet read
as pre-registered; the forward window is the only thing that can distinguish "the screen's score
discarded real edge" from "the demoted cohort was selected on its own noise". If the breadth arm is
to be retired early, that is a one-line change to the state's scored selection.

A second finding is worth its own card rather than being folded here (created as
`crowdintel-track-churn-inversion`, Backlog, measurement): the 56%/10-day turnover of
`WalletProfile.status='track'` and its inverse relation to measured band-excess. It needs a
pre-registered read (churn rate per week and the dropped cohort's forward band-excess), not an
assumption.

## 6. Harness proof: the scoring path works on a real forward window

`--selftest-split 2026-08-20` runs the identical code on a historical split (fit before the date,
score after it), touching neither the state nor the history. Both arms failed the pre-registered
rule on that window, which is the expected outcome of a working verdict function rather than a
smoke test that cannot fail:

| arm | forward bets / markets | band-excess | 95% CI | vs keep-the-set | verdict |
|---|---|---|---|---|---|
| baseline (track set) | 14,859 / 14,154 | +0.23pp | — | — | — |
| hard_q (4 admitted) | 6,962 / 6,117 | −0.70pp | [−1.57, +0.18] | −0.93pp | **FAIL** (CI includes zero) |
| shrunk (36 admitted) | 27,727 / 12,531 | −0.39pp | [−1.01, +0.23] | −0.62pp | **FAIL** (CI includes zero) |

Reference: the measurable-only baseline on that window (1,932 bets / 1,857 markets) read +1.47pp — the
unmeasured wallets drag the keep-the-set number down, which is why the baseline is reported both ways.

## 7. Limits, stated

- **Coverage is 6.35%** (25,269 settled of 398,069 conditionIds), and the fetch order is not random:
  track-wallet markets first, then markets by distinct-wallet count. The daily job spends 1,500 more
  fetches, forward markets first.
- **The cohort read is join-dependent and now set-dependent.** The parent's figure reproduces only on
  the parent's set; quoting any pooled tracked-set number without its set snapshot and truth-cache
  size is meaningless — the same instrument spans +2.59pp to +0.09pp across those two axes.
- **The tracked set is a moving target** (25 → 34 wallets inside 20 minutes today). The frozen
  snapshot is what makes the forward comparison well defined; it also means the baseline is "the set
  as of 18:13Z", not "the set".
- **Overlap between arms and baseline is small** (2 hard-q wallets, 13 shrunk wallets are tracked).
- **The demoted cohort's +4.95pp is in-sample** — it was used to select them. Treat it as a
  statement about what was discarded, not a forecast.

## 8. Ops and revert

- Daily: `copybot-wallet-rank-shadow` (05:50, `no_agent`, silent unless an arm leaves `PENDING` or the
  run fails). It runs `python3 scripts/wallet-rank-shadow.py --fetch 1500` from the primary checkout;
  until this branch merges the shim logs `repo copy absent … nothing run` and exits 0.
- Manual read: `python3 scripts/wallet-rank-shadow.py` → `data/wallet-rank-shadow.json`;
  `python3 scripts/wallet-fdr-cohort-split.py --split 2026-10-29 --parent-truth <cache snapshot>`
  → the decomposition in §1.
- Widen truth by hand: `python3 scripts/wallet-fdr-audit.py --fetch 20000` took 15 min for 19,765
  markets at ~22/s (235 failed, retried later); it rewrites `data/wallet-fdr-truth.json` only.
- **Revert (nothing live to roll back):** delete `data/wallet-rank-shadow-state.json` (the arming
  record; the next run re-arms) and remove the cron job. No `WalletProfile.status`, no RuleSet, no
  size, no gate was touched — the instrument opens `prisma/dev.db` `mode=ro` and writes only
  `data/wallet-rank-shadow*` and the truth cache.
- If a gated ranking ever ships LIVE, the rollback is the pre-live `WalletProfile.status` snapshot,
  taken before the first live run — that step is not part of this card and remains Lane A.
