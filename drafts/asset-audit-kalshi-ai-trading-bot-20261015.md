# Audit: anglil/kalshi-ai-trading-bot — adoption fit for Medusa CopyBot

**Date:** 2026-10-15 · **Auditor:** Hermes asset-audit cron · **Method:** GitHub API metadata + tree
aggregation (144 blobs) + workflow/README/requirements reads + raw reads of
`src/strategies/portfolio_optimization.py` (1,331 lines) and `src/strategies/unified_trading_system.py`
(867 lines) + `gh search code` call-site check + commit-history read + prior-work grep across `drafts/`
and `data/roadmap.json`. **No clone, no install, no execution of candidate code** — this job forbids it, so
the standing "run their test suite" step is replaced by a workflow-file read (see Caveats). No key, seed or
wallet address was read, copied or pasted.

## Verdict

**DROP** — read-only, and the read was still useful. Four independent blockers: (1) the venue is **retired by
user decision** (Kalshi copy-routing — structurally unsatisfiable venue gate) and every path in this repo
needs a Kalshi RSA **private key**; (2) development is **dead** — 0 human commits since 2026-06-01, the entire
recent history is the repo's own dashboard-publishing Action talking to itself; (3) the architecture is a
five-model LLM ensemble, which duplicates our DeepSeek research bot + local-sentiment lane; (4) the one
genuinely interesting module — a cross-position portfolio optimizer — is fed by an **uncalibrated
hand-weighted similarity score**, never a covariance of returns, and that exact component class was already
graded ❌ in `drafts/clodds-audit.md:44`. Its Kelly module is *algebraically identical to ours* and its extra
filters would veto the only positive-ROI band in our book.

## 1. What it is

An autonomous Kalshi event-contract trading bot, Python 3.12+: ingest (REST + WebSocket + RSS) → decide
(five-model LLM ensemble: Grok-4 30%, Claude Sonnet 4 20%, GPT-4o 20%, Gemini 2.5 Flash 15%, DeepSeek R1
15%) → execute (portfolio-optimised, Kelly-sized orders) → track (P&L, win rate, Sharpe, drawdown), with a
GitHub-Pages dashboard republished by Actions and a "beast mode" install script. Its own GitHub description
says "using Gemini", which does not match the README's five-model ensemble — a small credibility note, not
the reason for the verdict.

| Metadata (GitHub API, 2026-10-15) | |
|---|---|
| Licence | MIT (grant text present in-tree; owner is the apparent author — unlike the Telegram-bot repo audited alongside this one) |
| Stars / forks / open issues / watchers | **9** / 1 / 1 / 0 |
| Created / last push | 2026-02-21 / 2026-10-15 (push = the Action's own commits) |
| Default branch / languages | `main` / Python 95%, HTML 3%, Shell 0% |
| Files / content bytes | 144 blobs · `.py` 1,440 KB / 119 f · `.md` 59 KB / 7 f · HTML 79 KB / 3 f · `.png` 277 KB / 2 f |
| Distribution of code | `src/` 71 f / 1,009 KB · `scripts/` 20 f / 162 KB · `tests/` 13 f / 64 KB · `docs/` 6 f / 44 KB · root 32 f / 588 KB |
| Manifests | `pyproject.toml` (2,515 B) + `requirements.txt`; lockfile present |
| Releases | **0** |
| Structure (anatomy) | tests=yes · ci=yes · lock=yes · env_example=NO · docker=NO — **but see §2(a): the anatomy's `ci=yes` is false in substance** |

## 2. The anatomy facts that drove the verdict

**(a) The `ci=yes` and `tests=yes` flags both fail on inspection.** `.github/workflows/` contains exactly
one file, `dashboard.yml`: `name: Publish Live Dashboard`, `on: schedule: cron '*/5 * * * *'`, `permissions:
contents: write`, which `pip install -r requirements.txt` and then base64-decodes a repo secret:
`KALSHI_PK_B64: ${{ secrets.KALSHI_PRIVATE_KEY }}` → `kalshi_private_key` (chmod 600). Its runs are
`Publish Live Dashboard` + `pages build and deployment`, all `success` — so the repo has a **green CI story
and not one of the 13 test files (64 KB against 1,009 KB of `src/`) is ever executed by it.** There is no
test workflow, no `pytest` step, and therefore no green-suite quality signal available to a reader. The
same job also means a **live trading private key sits in a scheduled, `contents: write` workflow** whose
dependency set is unpinned to the runner's pip resolver — a fork/vendor of this repo inherits that custody
question, which is enough on its own to stop at read-only.

**(b) Development is over.** Every commit since 2026-06-01 is `Auto-update dashboard ... [skip ci]` by
`github-actions[bot]` — measured, not sampled: `gh api ".../commits?since=2026-06-01" | filter(non-auto)` →
**0**, and the newest 100 commits contain **0** non-auto entries. The visible activity (4–5 commits/day) is
the Action republishing `docs/index.html`; `docs/last_updated.txt` and the README tail still carry template
leftovers ("Bot health check Fri Mar 13 16:09:56 UTC 2026", "# Trigger rebuild"). Stars=9 with 0 watchers
matches a project that was pushed once in February and then left running.

**(c) Keys + retired venue.** RSA signing (`cryptography==42.0.0`, `pycryptodome==3.20.0`), `KALSHI_*` env
config, and live order tests (`tests/test_live_order_execution.py`, `tests/test_real_order_placement.py`)
mean the design assumes order placement against Kalshi. Our Kalshi copy-routing is retired by user decision
and the Kalshi lane is shadow/measurement-only (`data/kalshi-macro-quotes.jsonl`); nothing here is adoptable
for a live lane, and we never adopt code that needs keys.

## 3. Verified machinery (read from source, not from the README)

**Kelly sizing — identical to ours, so worth nothing to us.** `src/strategies/portfolio_optimization.py`
`_calculate_kelly_fractions` (~L257–320):

```
odds b = (1 − m) / m                # m = market probability; falls back to 1.0 at the boundary
kelly_standard = (b·p̂ − q) / b      # only if edge > 0 AND p̂ > 0.5, else 0.0
```

Substituting `b` reduces this to `f* = (p̂ − m) / (1 − m)` — **exactly** our `src/lib/kelly.ts`
`f* = (q − p)/(1 − p)` with `p` = price actually paid and `q` = calibrated fair probability. There is no
sizing math here we do not already have, and ours has the better input: our `q` comes from a measured
premium-calibration band (λ̂ from `data/premium-calibration.json`, Wang-transform inversion), theirs is a raw
LLM opinion.

Worse, their extra filters would **delete our edge**. Three unmeasured multipliers stack on top —
`regime_multiplier` (opaque), `time_decay_factor = clamp(TTR_days / 30, 0.1, 1.0)` (~L291, i.e. shrink the
bet linearly as expiry approaches), and `× confidence` (~L296, double-counting what should already live in
`p̂`) — then a 0.25 fractional multiplier and a `max_position_fraction` cap. And the admit gate itself is
`if edge > 0 and win_prob > 0.5` (~L283): it **refuses every sub-50% price bet**, which is precisely the
band that carries our book (C-200 all-time, n=1,679: 0.00–0.20 **+22.5 pp, z=+5.79, +$2,042.61** per
`logs/cron/tuning-review.md` cycle #30, and the only band with positive excess in both sample cuts).
Adopting their sizing filters would zero out the long-shot flow v54/v57-A went out of its way to keep.

**"Correlation matrix" — a similarity score, not co-movement.** `_estimate_pairwise_correlation` (~L357):

```
corr = 0.4·category_corr + 0.2·max(0, 1 − |ΔTTR|/30) + 0.3·LLM_content_similarity + 0.1·max(0, 1 − |Δvol|)
corr = min(self.max_correlation, corr)        # clamped at ≥ 0; exception path returns a flat 0.1
```

then `_ensure_positive_semidefinite` (~L354, identity fallback on exception), and the matrix feeds a
`scipy.optimize.minimize` multi-objective over (return ↑, portfolio volatility ↓, drawdown ↓) (~L487–536).
Two structural defects, stated plainly: every entry is **non-negative by construction**, so negatively
correlated legs — the whole point of a correlation-aware allocator — are unrepresentable; and time-to-expiry
proximity plus volatility proximity are not return co-movement. The 0.4/0.2/0.3/0.1 weights are hand-set
with no measurement in the repo.

**It is a real product component, not a dead module** — so the honest grade is "heuristic math behind a real
stage", not "nothing there": `unified_trading_system.py` imports `run_portfolio_optimization` and constructs
`self.portfolio_optimizer = AdvancedPortfolioOptimizer(self.db_manager, self.kalshi_client, self.xai_client)`;
`scripts/install_beast_mode.py` imports the class; one test file imports a factory from the module.

**Where that lands against our own stack (the gap check, run before grading):** we have per-leg Kelly with
band rails (`src/lib/kelly.ts`, `band-size.ts`), correlation-aware *evidence* aggregation
(`src/lib/forecasting/index.ts`: `mEff = m/(1+(m−1)ρ)`, ρ = 0.6 default), and a cross-position read that
**gates nothing** by design (`tr36-rec1-event-family-concentration`: "the stem is a slug heuristic, not a
contract-level correlation"). We have no *portfolio optimizer* stage — a real absence — but the concept of
supplying one from real covariance is already on file: `drafts/clodds-audit.md:17,:44` graded a donor's
portfolio-Kelly/correlation sizer **❌** with the note "user's portfolio risk should come from real
covariance (C-200 capital work)". So this repo adds a *worse* version of an already-rejected component.
That is a reason to record the pointer, not to re-propose the work.

## 4. Fit table

| Component | Roadmap target | Verdict |
|---|---|---|
| Kelly sizer (`edge/(1−m)` form + fractional 0.25) | `src/lib/kelly.ts` (v49 λ̂ regime, v57-B band rails) | ❌ algebraically identical; extra filters (p̂>0.5 admit gate, TTR decay, ×confidence) would veto the 0.00–0.20 band — the book's measured edge |
| Portfolio optimizer (scipy multi-objective, drawdown ↓) | `v46-equity-exposure-cap`, `tr14-exposure-gate-inloop` — no card asks for an optimizer | ⚪ concept only, and do not take the input: a hand-weighted, non-negative similarity score is exactly the "uncalibrated hand-weighted score" our doctrine says must never enter a composite |
| Correlation estimation (category/TTR/LLM-similarity blend) | `tr36-rec1-event-family-concentration`, `tr48-rec1-event-family-wallet-split`, `v55`, `v58` | ❌ already rejected in kind (`drafts/clodds-audit.md:44`); ours is measured where it counts (λ̂ band, ρ=0.6 cluster discount) |
| Kalshi clients + RSA request signing | Phase Kalshi-1 (parked: data wall), `kalshi-macro-quotes` shadow lane | ❌ venue retired by user decision; requires a private key |
| Five-model LLM ensemble decider + `src/clients/xai_client.py` (36 KB) | research-bot (`deepseek-v4-flash` cron) + local-sentiment shadow lane | ❌ duplicates what we run; adds `openai`/`anthropic`/`xai_sdk` dependency weight and `sentry-sdk` telemetry |
| 13 test files / 64 KB | — | ⚪ no CI runs them; nothing to trust, nothing to run |
| `docs/PERFORMANCE_SYSTEM.md`, `docs/QUICK_FLIP_STRATEGY.md`, README | — | ⚪ not read line-by-line this pass (see Caveats) |

## 5. Integration proposal

None — no adopt, no vendor, no flag. The only action worth taking from this audit is the pointer in §3
(portfolio risk should come from real covariance, already carded as concept in `clodds-audit.md`), and the
concentration axis already has open cards, so **no new card is proposed and no recommendation is recorded**.

## 6. NOT portable

- The whole execution path (Kalshi, keys, live order placement).
- The LLM ensemble layer (five vendor SDKs, LLM-as-forecaster with no calibration step before sizing —
  `win_prob = opp.predicted_probability` is fed straight into Kelly).
- The `dashboard.yml` Action (a live private key in a scheduled workflow; also the reason its commit feed
  overstates activity).
- The tests (never executed anywhere, so they are unverified code, not evidence).
- The optimizer's correlation input (see §3/§4) — take the *question* ("does a covariance term add anything
  over our caps?") at most, and only inside the capital-work axis where it is already recorded.

## 7. Honest caveats

- **No clone, no execution** (job constraint): their test suite was **not** run, and per §2(a) it cannot be
  run by their CI either — so the "green suite" evidence tier is simply unavailable for this repo, rather
  than skipped. Treat every quality statement here as a code-read, not a test result.
- **"Dead" is a commit-feed reading**: 0 non-auto commits since 2026-06-01 and 0 in the newest 100. I did
  not inspect branch activity, wiki, issues (1 open) or forks, so a side channel could hold work I have not
  seen; the public development signal is nonetheless ~5 months stale.
- `pyproject.toml` (test config, dependency-groups) and the three `docs/*.md` were not read; the
  requirements read and the workflow read cover the questions this audit asked.
- The README contains no performance/returns claim in the portions read (head 3,000 chars + tail); the
  rejection is structural, not a hype call.
- Numbers quoted from our own book (band table n=1,679; the slack in the concentration axis) come from the
  fact sheet / `logs/cron/tuning-review.md` (cycle #30), not from this repo.

## 8. Ready-to-paste registry/card block

This run's deliverable is the audit doc + queue record, so no `data/roadmap.json` write was made. If the
parent wants the finding in the registry (it belongs on the exposure/concentration axis, not a new card):

```
AUDIT INPUT (2026-10-15, drop; drafts/asset-audit-kalshi-ai-trading-bot-20261015.md): anglil/kalshi-ai-trading-bot read-only, no adoption. MIT but Kalshi + KALSHI_PRIVATE_KEY (and the repo's only workflow, dashboard.yml, base64-decodes that key inside a */5 contents-write Action) ⇒ never fork/vendor. Development dead: 0 non-auto commits since 2026-06-01, newest 100 commits all 'Auto-update dashboard'; ★9/0 watchers/0 releases; its tests=yes flag is false in substance (13 test files, no test workflow — nothing runs them). Its Kelly module is algebraically identical to src/lib/kelly.ts (f* = (p̂−m)/(1−m)) and its admit gate (p̂ > 0.5) would veto the 0.00–0.20 band = C-200's only positive-excess band (n=1,679, +22.5pp, z=+5.79, +$2,042.61) ⇒ adopting its sizing filters is actively harmful. Its portfolio optimizer (scipy: return↑/vol↓/drawdown↓) is the one real absence in our stack (tr36-rec1's family read gates nothing), but its correlation input is a hand-weighted NON-NEGATIVE similarity blend (0.4 category / 0.2 ΔTTR / 0.3 LLM similarity / 0.1 Δvol) — no covariance, negative correlation unrepresentable — i.e. the same ❌ component class already recorded in drafts/clodds-audit.md:44 ('user's portfolio risk should come from real covariance (C-200 capital work)'). No new card; the covariance question stays inside the exposure/concentration axis (tr36-rec1 · tr48-rec1 · v55 · v58) and must not be re-proposed as new.
```
