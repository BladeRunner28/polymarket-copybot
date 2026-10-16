# Asset audit — `mnemox-ai/tradememory-protocol` (2026-10-15)

**Verdict: WATCH — do not adopt the repo (the memory/skip-gate layer failed its own authors'
validation); take exactly one thing: the deflated-Sharpe multiple-testing math, which is a
verified absence in our stack. No card currently asks for it.**

Lead source: `drafts/asset-audit-awesome-trading-agents-20261015.md` §3 (enqueued 2026-10-15 12:25 CDT,
note: "outcome-weighted decision memory + pre-trade brake MCP … likely covered by DecisionJournal +
risksJson + review:outcomes — audit to confirm or refute"). Read-only: no clone, no install, no execution.

## 1. What it is

"Decision audit trail + persistent memory for AI trading agents": pulls a user's own fills, finds where
their history loses money, surfaces that before the next order, and can refuse an order a rule forbids.
Python, MIT, ~2.8 MB of Python across 286 files + a 10 MB TS dashboard + 6 MB of committed research
output. Brokers today: MetaTrader 5 (their `LIMITATIONS.md` says so, not the README).

## 2. Anatomy facts that drove the verdict (deterministic, 2026-10-15)

| Fact | Value |
| --- | --- |
| Licence / archive | MIT · not archived · fork: false |
| Stars / forks / open issues / watchers | ★1,430 · 171 · 7 · 75 |
| Created / last push | 2026-02-23 / **2026-10-09** (alive but slowing; 35 commits since 2026-10-01) |
| Code | 614 files · .py 2,846 KB/286 · .json 6,019 KB/57 (research output) · .md 853 KB/88 |
| Structure | tests=yes ci=yes docker=yes lock=yes · 96 files under `tests/` |
| CI health (read off the API) | `ci.yml` 3/3 recent runs `completed/success` (head `cb599bd`, 2026-10-09T20:14Z) |
| Self-reported honesty | `LIMITATIONS.md` is canonical over README/paper, and it is unusually candid (§3) |

Their own docs, quoted because it is the highest-signal thing in the repo:

- **Phase 5 validation: INVALID.** "100 experiments … showed that the CalibratedAgent skipped 97% of
  trades, so the apparent drawdown reduction came from *not trading*, not from skill. 0/100 DSR PASS.
  Sensitivity sweep collapsed (all 10 hazard rates produced identical 0.9883 reduction)."
- **DQS (Decision Quality Score) "DEAD" at integration level; BOCPD changepoint detector "DEAD"** on
  sparse binary outcomes. Single-tenant SQLite, no auth/RBAC/rate limiting, no HA.
- Repo's own files corroborate: `scripts/research/phase5_results.json` is full of
  `{"verdict": "INSUFFICIENT_DATA"}` DSR entries with raw Sharpes 6.6232 / −27.4562.

## 3. Verified machinery (read from source)

`src/tradememory/strategy_validator.py` (33 KB, self-contained, only optional dep `deflated-sharpe`):

- **`compute_dsr(sharpe_raw, num_obs, num_trials, significance)`** — deflated Sharpe, i.e. a Sharpe
  corrected for selection bias across the number of trials tried. `num_obs < 10` →
  `INSUFFICIENT_DATA`; otherwise delegates to the `deflated_sharpe` package (Bailey / López de Prado);
  verdict bands PASS p<0.05, CAUTION p<0.10. **Fallback bug worth naming:** when the package is absent
  the fallback writes the *t-statistic* into the `dsr` field (`"dsr": round(t_stat, 6)`) and derives p
  from a normal approximation — a labelling bug, not a math bug. Copy the math, not the label.
- **`cpcv_sharpe(daily_returns, n_groups=10, n_test_groups=2, purge_window=5, embargo_window=10)`** —
  C(10,2) = **45 folds**, contiguous test blocks, purge before / embargo after each block, Sharpe per
  fold, `consistency` = fraction of positive folds, PASS ≥ 0.70 / CAUTION ≥ 0.55. Minimum 200 obs
  (`n_groups*(purge+embargo+5)`). Thresholds are admitted defaults, not tuned.
- `walk_forward_validation` / `walk_forward_returns`, `regime_analysis` (S&P annual-return table +
  crisis years), `_max_drawdown`, `_raw_sharpe`.
- **Wired, not test-only (the zero-call-site check):** `src/tradememory/mcp_server.py` imports
  `validate_from_trades`/`validate_from_returns` (MCP tools), `simulation/runner.py` and
  `scripts/research/run_phase5.py` call `compute_dsr`. So the arithmetic comes with a shipping feature.

## 4. Fit table vs our stack

| Component | Our state (verified) | Verdict |
| --- | --- | --- |
| **Deflated Sharpe / multiple-testing correction** | `grep -riE "deflated\|DSR\|bonferroni\|benjamini\|multiple.test\|family-wise\|FDR"` over `src/`, `scripts/`, `drafts/*.md` → **0 hits**; and no card names it | ✅ **adopt the math** (no card asks for it — that is the finding) |
| Purge / embargo / time-ordered splits | DONE and machine-enforced: `src/lib/splits.ts`, `scripts/lib/splits.py`, `scripts/check-split-doctrine.py` (pinned boundary, purge on label timestamp, era provenance, pinned crc32 fold numbers; 0 violations 2026-10-11); card `ml-doctrine-time-and-era-splits` (In Progress) | ⚪ already have — CPCV folds add ~nothing at our n |
| Walk-forward + regime analysis | era splits + `ruleSetVersion` regime reads already live | ⚪ partial overlap |
| Decision memory / pre-trade brake | `DecisionJournal` + `risksJson` skip sets + `review:outcomes` + the rules auto-tuner | ❌ not portable (same primitive, different packaging) |
| OWM 5-factor recall scoring / DQS skip tiers | their own Phase 5 called the integrated gate INVALID (skip 97% of trades) | ❌ do not adopt |
| SHA-256 / Merkle / RFC 3161 audit chain | `RuleSet` + `RuleChange` rows are our audit trail; no external verifier in a paper stack | ❌ not portable |
| MCP memory service, TS dashboard, MT5/Alpaca connectors | we are paper-only; connectors need broker keys | ❌ not portable |
| Their **negative results** as a caution | "apparent drawdown reduction came from not trading" is a live risk for our own skip gates | ⚪ concept (see §6) |

## 5. Why the DSR axis is real here (and what would settle it)

Our stack iterates rules fast and adopts winners per axis: `logs/cron/tuning-review.md` shows RuleSet
v40 → v62 across consecutive cycles, six axes, each cycle proposing/rejecting changes with z-scores,
plus `rule-updater.proposeRuleChanges` + `RuleChange{reason, evidenceSummary}` rows. **Nothing anywhere
deflates those statistics for the number of variants tried.** That is exactly what DSR is for, and the
trial count is *derivable* from our own history (RuleChange rows / per-axis proposals per version) —
which is what makes this a measurement rather than an opinion.

Honest counterweight: our live regime is ~6 weeks old, and the donor's own `compute_dsr` returns
`INSUFFICIENT_DATA` below 10 observations. A deflated read may simply come back
`INSUFFICIENT_DATA`/p≥0.05 — in which case the correct output is a *caveat*, not a claim. That outcome
is written into the decision rule.

## 6. Risks / NOT portable / caveats

- **Never vendor the Python**: reimplement ~40 lines of published math in TS; the dependency is optional
  even in their repo (`deflated_sharpe`), and the fallback path is buggy in its labelling.
- **Copy the math, not their thresholds** (DSR bands, CPCV 0.70/0.55, anti-resonance 0.4/0.2, mSPRT
  tau=0.3) — all admitted as untuned defaults.
- **Do not adopt the brake/skip layer**: its integrated form failed their own validation, and our skip
  gates are already measured by counterfactual labelling (`ml1a-skip-set-labeling-probe`, Done: 77k
  counterfactual labels, skipped signals ~fair-priced overall, slightly +EV live). Their failure mode
  (fewer trades ⇒ less drawdown ⇒ looks like skill) is worth a line in our own gate reviews; it is not a
  new card.
- Their repo expects broker/LLM secrets (`sync alpaca --env-file`), single-tenant, no auth — treat as
  untrusted; no code was executed here (job constraint).
- Nothing in this audit changes a rule, size, gate, or published number.

## 7. Recommendation (recorded in the asset queue)

```
REC — Deflate our rule-selection statistics: count the trials
  Hypothesis:   The standing rule/band/bucket improvements were selected from many variants and we apply
                no multiple-testing correction anywhere, so some adopted thresholds may be selection
                artifacts rather than measured edges.
  Measurement:  read-only: derive n_trials per axis from RuleChange rows / per-cycle proposals in
                logs/cron/tuning-review.md (v40-v62), then compute the deflated Sharpe on the C-200 daily
                net PnL series over the live regime (2026-09-04+) with that trial count; report SR_raw,
                DSR, p, min backtest length. No live change, no threshold touched.
  Decision rule: if p >= 0.05 or the read returns INSUFFICIENT_DATA, the ladder/rule claims carry an
                explicit "not distinguishable from selection" caveat in the daily/weekly line; if p < 0.05,
                record the number as the ladder's significance statement. Either way no rule moves.
  Cost:         ~2 h (reimplement the published DSR formula + trials count in TS); read-only, zero risk
  Reversibility: a report line only — nothing to revert; nothing in the live path reads it
```

**AUDIT INPUT (2026-10-15, watch; drafts/asset-audit-tradememory-protocol-20261015.md)** — no existing card
owns multiple-testing correction (grep: `deflated|DSR|bonferroni|benjamini|FDR` = 0 hits in `src/`,
`scripts/`, `drafts/`; `ml-doctrine-time-and-era-splits` owns the split/purge half, which is DONE and
machine-enforced). Nearest owner is that card's doctrine axis, but the deflation question is a *new* axis —
if a card is wanted, it is a genuinely new work item (unprompted; veto freely). Ready to paste — no
roadmap/registry write was made by this job (recommendations-only constraint); apply deliberately.

## 8. Honest caveats

- No code was executed and no test suite was run here (job constraint: never clone/install/execute
  candidate code). CI state is read off the Actions API (3/3 green, 2026-10-09); the donor claims
  "1,400+ tests" — I counted 96 test files, not the assertions.
- Their star count is a community signal (★1,430) and the repo's last push is 6 days old with a slowing
  cadence; the maintainer's own limitations doc is the reason to trust the rest.
- The one advanced claim I could not verify without executing code is the *numerical* correctness of
  their DSR against the published definition (I read the code path and the delegation, not a value-by-value
  match). Whoever implements it should re-derive from Bailey/López de Prado directly, not from this code.
- Prior work checked: `drafts/` had no tradememory/paper-trader audit; the leads' origin audits are
  `asset-audit-awesome-trading-agents-20261015.md`. `clodds-audit.md` remains the precedent for the
  ❌ "hand-weighted correlation, no covariance" component class — not reopened here.

Dashboard: http://localhost:3013/drafts/asset-audit-tradememory-protocol-20261015
