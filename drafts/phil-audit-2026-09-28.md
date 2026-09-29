# bennyjo/phil — adoption audit

**Audited:** 2026-09-28 · HEAD `b21f909` ("cycle: 20260928-1816 placed 0 settled 0"), pushed 2026-09-28T18:14:09Z
**Method:** GitHub API metadata → `git clone --depth 1` to `/tmp/phil` → source reads with file:line → ran the repo's own tools offline (`core/validate.py`, `core/score.py --skip-mtm`, `core/replay.py`, `.github/scripts/forward_test.py`) → commit-history point-in-time check via API. Nothing in this repo or in ours was modified except creating this file.
**License claim:** verified, not taken from a badge. API `license.spdx_id = "Apache-2.0"`; `LICENSE` is the 202-line Apache 2.0 text. ✅

---

## What it is

An autonomous short-horizon Polymarket paper trader whose entire *control policy* is a prose procedure (`CYCLE.md`, 342 lines) executed hourly by a headless Claude Code session (`loop.sh:159` `claude -p "$PROMPT" --model $MODEL --allowedTools Read Glob Grep WebSearch WebFetch Edit Write Task … --permission-mode acceptEdits`). The clone is the loop's own working tree: after settling and scoring yesterday's bets, the agent writes a retrospective and **edits its own artifacts in `strategy/`**, commits, and bets again.

The distinguishing move is not the trading — it is that **paying for lessons in paper is the product**, with the git log as the record. `journal/retros/` holds 407 retros; the newest 500 commits comprise 326 `cycle:`, 116 `retro:`, 31 `cycle(triggered):`, 14 `deep-retro:`, 11 `operator:` (1,858 commits total in ~60 days).

Scale/README claims verified: 153 stars, 37 forks, created 2026-07-30, Python, Apache-2.0, `real_trading_enabled: true` in `config/protected.json`.

**Composition (measured, bytes / lines):**

| Bucket | Bytes | Lines |
|---|---|---|
| LLM/agent-written journal (`journal/**` md+jsonl+log) | 48,412,842 | 146,338 |
| Agent-editable strategy prose+config (`strategy/**` md+json) | 582,344 | 7,408 |
| Deterministic Python (all `*.py` incl. `core/`) | 458,567 | 10,253 |
| CI (`*.github/**`) | 41,291 | 525 |
| Agent prompt prose (`CYCLE.md`+`REAL.md`+`CLAUDE.md`) | 27,212 | 435 |

`core/` alone is 9,180 lines of deterministic Python in 21 files (`screen_replay.py` 2,710, `screen.py` 939, `screen_value.py` 830, `counterfactual.py` 631, `watch.py` 562, `score.py` 392, `replay.py` 292, `validate.py` 284). `strategy/playbook.md` alone is 6,911 lines of agent-written prose.

**Zero ML.** `grep import sklearn|xgboost|torch|pandas|numpy` over the repo (excluding journal outputs): no hits. There is no model, no fit, no feature vector. The "self-improving" claim is LLM-authored prose + JSON thresholds, not learning code. Any roadmap card expecting to harvest ML from this repo should be closed now.

---

## Verified machinery (file:line; formulas)

### Paper ledger — real, append-only, single-writer
`core/ledger.py:66-113` (`cmd_place`) is the only writer of `journal/ledger.jsonl`. Rejections are explicit exits: `max_open_positions` 60 (`:70`), `stake > max_stake_usd` 10 (`:72`), `stake > bankroll` (`:74`), duplicate market+outcome (`:77`), market closed (`:82`), no asks (`:87`), fill price outside `[0.02, 0.95]` (`:90`).

Honest fills: `entry_price = best ask` from the live CLOB (`:89`), i.e. a taker crossing the spread. Row fields: `edge = round(est_prob − ask, 4)` (`:104`), `shares = round(stake / ask, 4)` (`:106`), and — worth flagging — `market_prob_at_entry := ask` (`:103`), i.e. the bet-side market baseline is the *ask*, not the mid.

Bankroll arithmetic is real and reproducible (`core/ledger.py:37-45`):
```
cash = 1000 − Σ stake_usd(all non-void-ish rows) + Σ shares(won)      # $1/share par
realized_pnl = Σ (shares − stake) for won, −stake for lost            # :52-54
```
Flat stake only: `strategy/risk.json: "default_stake_usd": 5.0, "sizing": "flat"`; `policy.py:72 STAKE_USD = 5.0`. **There is no Kelly, no fraction, no sizing curve anywhere** — and their own evidence explicitly rejects one (`policy.py:37-40`: "Edge-scaled, Kelly, price-scaled, price-tiered and max-stake sizing all lowered the held-out score"). Risk control is caps-by-fiat, not mathematics.

### Scoring — a real settled-bet ledger and a real scoring function
`core/score.py:31-45` `stats()`:
```
win_rate    = wins / n
roi         = pnl / Σstake
brier_agent = mean( (est_prob − 1{won})² )
brier_market= mean( (market_prob_at_entry − 1{won})² )
brier_delta = brier_agent − brier_market          # headline: <0 = agent beats the market price
```
`core/score.py:229-239` `luck_adjusted()`:
```
z = (actual_wins − Σ est_prob) / sqrt( Σ est_prob·(1 − est_prob) )
```
Output is split `by_edge_class`, `by_category`, `by_strategy_rev` (`score.py:286-300`) — the last one is what makes self-improvement measurable across commits. A parallel stake-free **forecast stream** (`journal/forecasts.jsonl`, recorded for *every* researched candidate including skips, `CYCLE.md:285-297`) is scored the same way against the **mid** (`score.py:48-64`), with the code noting the two sections are deliberately not comparable (`score.py:48-52`).

Also verified, and genuinely good:
- `core/replay.py` — walk-forward replay of a pluggable policy over frozen beliefs, fold 0 train-only (`:225-244`); honest fill model yes-at-ask / no-at-`round(1−best_bid,4)` (`:140-151`); protected caps applied inside the replay (`:131,:149`); selection score `cw_return = roi − stake-weighted SE of per-bet return` (`:173-181`).
- `core/replay.py:208-222` + `:42-47` — the **sealed-cutoff forward test**: `train = settled_ts <= TS`, `test = settled_ts > TS`. "Rows recorded before TS but settled after it count: nobody could have tuned on their outcome. This is the only true out-of-sample score for a policy whose thresholds were chosen by reading the ledger." This is our doctrine written by someone else, in code.
- `core/counterfactual.py` (631 lines) — mechanically prices **every declined** settled row (side = sign(est − market), flat $5, same fill model), keeps token-frame vs question-frame separate, and diffs its mechanical ledger against the hand-kept playbook table (`:58, :391`).
- `core/validate.py` — CI tripwires: hard ceilings `{max_stake_usd: 2.0, daily_stake_cap_usd: 10.0, max_open_positions: 20}` (`:72-73`), screener ceilings 300 batches / 400 pool (`:78-79`), every ledger row's stake ≤ cap and entry price in band (`:173-179`), `est_prob` bounds, all Python compiles (`:272-277`). Ran it: `OK — config, risk policy, schedule, ledger and Python sources all sane`, exit 0.
- `.github/scripts/boundary.sh:13-36` — no commit lacking the `operator:` prefix may touch `core/|config/|.github/|CYCLE.md|REAL.md|loop.sh|CLAUDE.md|LICENSE|README.md`; `loop.sh:194-202` reverts such edits locally too. The boundary is enforced twice, by two mechanisms.

### What I reproduced from stored data (no network)
```
validate.py                      → OK (exit 0)
score.py --skip-mtm              → settled=48  win_rate=0.417  pnl=−$7.92  roi=−0.033
                                   brier agent=0.2903  market=0.2050  delta=+0.0853  (behind market)
                                   luck-adjusted z = −3.93
replay.py (5 folds, 896 rows)    → HELD cw_return=+0.1285  pnl=+118.34  bets 73/716  brier_delta=−0.0065
replay.py --after 2026-09-02T00:14:36Z  (pre-registered forward test)
                                 → cw_return=−0.0730  pnl=+27.35  roi=+0.0912  bets 60/476
forward_test.py --force          → Verdict: FAIL (forward cw_return −0.0730 is not above zero)
forecast stream (computed)       → 1,214 rows, 1,039 settled, brier_delta=+0.0092
```
Both headline numbers are **negative**: paper P&L −$7.92 on 48 settled bets, and the agent's probabilities are worse than the market's prices on both streams, with z = −3.93 (systematic overconfidence, not variance).

---

## The self-rewrite loop, mechanically

**Which artifact changes.** The agent may edit only `strategy/`: `playbook.md` (6,911 lines of judgment), `risk.json` (floors + a ~26KB evidence prose blob in `edge_class_notes`), `policy.py` (the only coded decision rule), `discovery.py` (scan queries), `schedule.json` (pacing + watch items), `screener-filters.json` / `screener-strata.json` / `screener-prompt.md`, `screener-value.json` / `screener-rank.json`, `watchlist.json`, `tools/*.py`. It may not touch `core/`, `config/protected.json`, `CYCLE.md`, `REAL.md`, `loop.sh`, `CLAUDE.md`, `.github/`.

**Mechanism, end to end.** (1) `CYCLE.md:108` settle → (2) `:109` score → (3) `:110-121` write `journal/retros/RETRO-<ts>.md`, then literally "ACTUALLY EDIT `strategy/playbook.md`, `strategy/risk.json`, or `strategy/tools/` to encode them", then `git add -A && git commit -m "retro: <one-line lesson>"` → (4-6) scan/screen/research/bet → (8) `cycle:` commit → (9) push. 116 of the newest 500 commits are `retro:` commits: that is the rewrite cadence, one LLM edit-commit roughly every other cycle.

**What gates a rewrite — the crux.**

| Gate | Type | Evidence |
|---|---|---|
| "Every strategy edit must cite evidence (settled positions, retro findings). No speculative rewrites." | **prose instruction to the LLM** | `CYCLE.md:20-21` |
| "mind small n — do not overreact to fewer than ~15 settlements in a category" | **prose heuristic** | `CYCLE.md:114-115` |
| "no numeric changes (n=16 settled justifies none)" style discipline, repeated daily | **prose, self-applied** | `strategy/risk.json` `edge_class_notes` (e.g. DEEP-2026-08-04, -08-05) |
| Second LLM audits each edit: keep / sharpen / revert | **LLM audit, not a test** | `README.md` ("daily deep-retro agent"); 407 `DEEP-*.md` retro files |
| "Keep a change only if the held-out walk-forward score from `core/replay.py` improves" | **the only quantitative gate** — and it is **in-sample** | `policy.py:5-6, :42-49` ("Replay scores below are IN-SAMPLE … the walk-forward split holds nothing out from the rule selection") |
| Protected caps / operator boundary | **code-enforced, twice** | `ledger.py:70-90`, `validate.py:72-173`, `boundary.sh`, `loop.sh:194-202` |
| Human approval for protected files and for asks in `journal/proposals.md` | **human gate** | `proposals.md` statuses: 9 actioned, 11 endorsed, 20 informational, 4 rejected, 2 open |

Note what is **not** gated: the entry-risk constraints that actually shape the book — `min_edge 0.04`, `min_edge_book_devig 0.07`, `max_spread 0.06`, and the "claimed edge > 0.10 → outside-view veto" — exist only as prose in `playbook.md` and as free text inside `risk.json:edge_class_notes`. Grep for `0.10`/`veto` in code finds only `counterfactual.py` comments and report section headers: **nothing enforces them**. Compliance rests on the LLM obeying its own instruction file. The one coded rule set (`policy.py` bands, `DEAD_ZONE = (0.20, 0.45)`) lives in the very file the agent may rewrite.

So the honest summary: the loop rewrites a **prose playbook + JSON thresholds + one Python decision function**, gated by a prose evidence rule, a "~15 settlements" norm the LLM applies to itself, and a second LLM's audit — with exactly one statistical gate, whose own docstring concedes the selection was in-sample, and which **failed its own out-of-sample test**.

**Maturity note (in their favour):** the process is considerably more disciplined than the phrase "rewrites his own strategy" suggests. Retros pre-register forks ("mechanical-econ fork decision DEEP-2026-08-28/29, not before"), record counterfactual ledgers for vetoed trades, and repeatedly *refuse* to move a threshold on thin n. The agent's asks are quarantined into `proposals.md` and 4 were explicitly rejected by the operator.

---

## Track-record integrity check (point-in-time vs backfilled)

**Verdict: point-in-time. No backfill, no seed, no fabricated history found.**

| Check | Result |
|---|---|
| First ledger row timestamp vs repo creation | `2026-07-30T20:12:42Z` vs repo created `2026-07-30T21:45Z` — same day, cycle 1 |
| Commits touching `journal/ledger.jsonl` (API) | 80 commits across **34 distinct calendar dates**, 2026-07-30 → 2026-09-28, oldest commit in that history `2026-07-30T20:12:54Z` (12 s after the first row's `ts`) |
| Per-row provenance | 42 distinct `strategy_rev` git stamps across 52 rows; 364 across 1,214 forecast rows |
| Bet placement spread | 26 distinct bet days; 11 bets on day 1 — the ledger grew as the run happened, not in one write |
| Resolutions | settled against Polymarket's own gamma `closedTime`/`umaEndDate` (`core/resolve.py:61-63`), so outcomes are not author-asserted |
| One-day backfill / seeded sample | not present |
| README headline numbers | no unbacked number: the README's claims (paper P&L aside) are all reproduced by `score.py`/`replay.py` from stored data |

The repo's actual weak point is not the record's integrity but its **content**: the record is point-in-time and it says the agent has not beaten the market. Brier is worse than the market on bets (+0.0853) and on forecasts (+0.0092); paper P&L is −$7.92 on 48 settled bets; z = −3.93. The one artifact with a genuine quantitative guardrail, `policy.py` v3, shows in-sample cw_return +0.743/+0.1285 collapsing to **−0.0730** on the sealed forward window, with a single bet carrying **145%** of the forward P&L — so it fails the pre-registered single-bet-dominance criterion as well. Their own tool prints `Verdict: FAIL`.

**And the real-money leg is unverified by any artifact.** `journal/real-ledger.jsonl` contains 56 rows, **all of type `settle`** — zero `buy`/fill rows; the recorded settles read "DepositWallet is empty … no positions discovered", "nothing redeemable". Every real-mode cycle in `journal/cycles.log` ends `| real: placed 0 settled 0`, including 2026-09-09 when `real_trading_enabled: true`. The README's "Real money runs alongside it … small capped real stakes via Pearl Connect" is therefore **unverified** — no filled real order exists in the observable record. Treat the "$1/twin" leg as aspirational, not demonstrated.

---

## Fit table vs our roadmap

Baseline for all rows: our data is point-in-time and our lanes are already time-ordered/era-aware with frozen measurement windows. What phil offers is *mechanism*, not results.

| phil component | file:line | Verdict | Reason |
|---|---|---|---|
| Sealed-cutoff forward test (`--after TS`, train=train settled ≤ TS, test=settled > TS) | `core/replay.py:208-222`, `:42-47` | ✅ **adopt** | Exactly our doctrine, already coded: the only true OOS read for thresholds chosen by reading the ledger. Maps to `ml-doctrine-time-and-era-splits`, `precommit-mid-oct-kelly-gate`, `decay-bar-tripped-oct8-decision`. |
| Pre-registered pass criteria incl. single-bet dominance cap | `.github/scripts/forward_test.py:27-40,60-70` | ✅ **adopt** | `MIN_BETS=15`, `cw_return>0`, `no single bet >50% of a positive pnl`, criteria frozen before outcomes. Directly reusable as our shadow-read pass/fail rule; caught phil's own "win" as one-bet-driven. |
| Counterfactual ledger for **declined** decisions, diffed against a hand-kept table | `core/counterfactual.py:1-60, :391, :515-545` | ✅ **adopt** | We already shadow drift/lowconf/per-wallet ceilings, but each with bespoke scripts; this is the general primitive (mechanical side/stake/fill, no thresholds, table-vs-ledger diff). Maps to `drift-gate-counterfactual`, `lowconf-shadow-lane`, `wallet-cap-shadow-lane`. |
| Agent/operator boundary tripwire + cap validator run in CI | `core/validate.py:72-179,272-277`; `boundary.sh:13-36`; `loop.sh:194-202` | ✅ **adopt (pattern)** | Machine-enforced "the frozen thing cannot be touched" — the missing enforcement under our Kelly freeze. Doesn't exist as a card; worth one. |
| Per-decision provenance row recorded for *every* researched candidate incl. skips, with `skip_reason` taxonomy + `strategy_rev` | `CYCLE.md:285-297`; `core/forecast.py:50,62`; `journal/forecasts.jsonl` | ✅ **adopt (pattern)** | Nearly identical to `data2-per-decision-provenance`; their staged-row + supersession-with-materiality idea (`MIN_REVISION_DELTA=0.05`, `EXTREME_DISAGREEMENT=0.40` typo trap) is better than what we have. |
| Flat-stake + cap-only risk model | `risk.json`, `ledger.py:70-90` | ⚪ concept-only | Real arithmetic, but deliberately crude — Kelly was *measured and rejected* by them (`policy.py:37-40`). We are further ahead (Phase B). |
| Brier-delta-vs-market as the headline metric | `core/score.py:36-44` | ⚪ concept-only | We already have calibration + Wang premium; useful as one more lane-level read, not as a new metric. |
| LLM-written 6,911-line playbook as the strategy artifact | `strategy/playbook.md` | ⚪ concept-only | Genuinely interesting as a *journal* of why; unusable as a machine-checkable config, and unenforceable. Never a substitute for `ruleSetVersion` + pre-registered tests. |
| Deep-retro keep/sharpen/**revert** audit of agent edits | README; 407 `DEEP-*.md` | ⚪ concept-only | The audit exists but the revert branch is effectively dead: `REVERT` appears **once** in 407 retros vs 284 `KEEP`. A second LLM rubber-stamping is not a gate. |
| Self-rewriting loop itself | `loop.sh:159`; `CYCLE.md:110-121` | ⚪ concept-only (trialled narrowly, if at all) | See shadow-trial proposal. Only the non-live artifacts, only with our gates bolted on. |
| Screener subagent tier (300 markets/cycle, Haiku) | `core/screen.py`; `screener-prompt.md` | ⚪ concept-only | No ML, no calibrated output; their own `screener-rank-decision.md` concludes a formula can replace it. Maps loosely to `phase-data1`; not a borrow. |
| No ML at all (no fit/features/labels) | repo-wide grep | ❌ not-portable | Nothing to take for `phase-ml1`, `phase-ml2`, `ml-u1`, `ml-u2`. |
| Local-model / fine-tune track | none | ❌ not-portable | No local LLM, no QLoRA, no eval harness → nothing for `llm-ft-track`. |
| Reddit/HF/arXiv idea digest | none | ❌ not-portable | Nothing for `reddit-intel-digest`. |
| Pearl Connect real-money leg | `core/real.py:44,66-89`; `config/protected.json` | ❌ not-portable | Closed hosted signer (valory-xyz/connect, pearl.you) + zero filled orders in the record. |
| Olas mech second opinions (~$0.01 USDC each) | `CYCLE.md:163-284`; `loop.sh:171-181` | ❌ not-portable | Paid closed marketplace, needs Pearl signer; explicitly absent on cloud cycles. |
| the-odds-api benchmark client | `core/odds.py` | ❌ not-portable | Needs `ODDS_API_KEY`; the repo's own operator rejected provisioning a key (2026-08-04). |
| Cloud hourly routine + runner lease | `loop.sh`, `core/lease.py`, `core/ci.py` | ❌ not-portable | The cloud runner config is not in the repo; two-runner lease is an artifact of *their* topology. |
| "In-sample replay score improves → keep the change" as a promotion gate | `policy.py:5-6`, `:42-49` | ❌ **not-portable (anti-pattern)** | Self-declared in-sample; its forward test FAILED. This is the specific failure our `ml-doctrine-time-and-era-splits` card exists to prevent. |

---

## Shadow-trial proposal

**Trial A — measurement convention (recommended; low cost, no new code path).**
Apply the sealed-cutoff forward read + pre-registered pass criteria to shadow feeds we already mark to settlement, at the **Oct 8 window close**, not before.

- **Baselines (three, all required):**
  1. *Probability baseline* — the market mid at decision time (Brier), because that is free and unbeatable-by-assumption;
  2. *Decision baseline* — the incumbent live ruleset replayed on the identical rows with the same fixed clip (`bt-ml-lane` Level-2 parity requirement);
  3. *Fill baseline* — recorded ask for yes / `1 − bid` for no, mirroring `replay.py:140-151`, so shadow P&L is net of the spread like our C-200 book.
- **Sample size:** pre-register **n ≥ 150 settled per arm**, reusing the `>=150 both arms` convention already in our Kalshi card; phil's own trigger (`MIN_SETTLED=100`, `MIN_BETS=15`) is a floor, not sufficient for our purposes given their 60-bet forward read was dominated by one bet.
- **Decision rule (all four must hold):** (a) `cw_return = roi − stake-weighted SE > 0`; (b) top single bet < 50% of positive P&L; (c) market-clustered bootstrap 95% CI on edge/sh excludes 0; (d) the same sign holds in each `ruleSetVersion` era separately (no era-averaging).
- **Kill rule:** if fewer than 15 would-have bets survive, the finding is "too few decisions to price the gate", not a verdict — phil's `forward_test.py:139` handles exactly this case and we should copy it.
- **Cost:** analysis-only, one script, run at window close. No lane behaviour changes.

**Trial B — self-rewriting loop (concept only; do NOT run before Oct 8, and only with gates).**
If our operator wants the concept measured at all, the defensible form is: the "rewriter" may **only** emit proposed diffs to a non-live artifact (a candidate ruleset JSON), never touch the live lane; every proposal must arrive with a sealed-cutoff forward read from Trial A's harness; a machine check (`validate.py`-style, in CI) refuses any diff that lands inside a frozen window or touches a frozen artifact; and promotion requires Trials A's four criteria on a *separate* forward window after the proposal. That is the self-rewriting idea stripped of the unmeasured parts, and it is close enough to what our `rule autotuner` + frozen window already do that the marginal gain is small.

---

## NOT-portable list

1. ❌ **Unaudited LLM edits to thresholds/parameters that shape a live book** (`strategy/risk.json`, `strategy/policy.py`, `strategy/schedule.json`), gated only by prose rules (`CYCLE.md:20-21`) and a second LLM's audit. Nothing machine-checks `min_edge`, `max_spread`, or the >0.10 veto; a silent edit is indistinguishable from a lesson.
2. ❌ **Admitting large claimed edges on LLM narrative.** Their own evidence is 0W/5L, −$25 on claimed-edge >0.10 (`risk.json:edge_class_notes`, DEEP-2026-08-07/-08-30) — a rule against it exists only as prose, so the loop re-litigates it every cycle. Ours must be a code gate.
3. ❌ **In-sample replay improvement as a promotion criterion** (`policy.py:42-49`). It reported +0.743 and delivered −0.0730 forward.
4. ❌ **The real-money leg as designed** (`core/real.py`, Pearl Connect): closed hosted signer, `.claude/skills/connect-polymarket/scripts` wrapper, and zero filled orders in the entire record.
5. ❌ **Olas mech marketplace / Pearl cloud routine dependencies** — paid, closed, signer-dependent; unavailable on their own cloud cycles.
6. ❌ **the-odds-api keyed benchmark client** (`core/odds.py`).
7. ❌ **A 6,911-line LLM-authored playbook as the strategy of record** — unversionable per decision, unenforceable, and the reason their risk rules live outside code.
8. ❌ **Flat $5 stakes with caps as the risk model.** No sizing arithmetic; their own measurement rejected Kelly. Do not import their sizing as "simpler".
9. ❌ **The word "self-improving" as evidence.** 1,858 commits, 407 retros, 2,980+ cycle logs, and the settled ledger is −$7.92 with brier worse than the market on both streams. Volume of activity is not a track record.

---

## Honest caveats + verdict

**Caveats.**
- The **deep-retro agent** and the **hourly cloud routine** are *not in the repo*: no workflow/config defines them (only `ci.yml` and `forward-test.yml`); their prompts live in the author's external infra. From the clone you can reproduce the cycle loop, the scorer, the replay, the counterfactual ledger and the validator — you cannot reproduce the second auditor. Everything I say about "the daily deep retro audits edits" rests on their outputs (407 `DEEP-*.md` files) and the README.
- **No test suite exists.** No `tests/`, no `pyproject.toml`, no `requirements.txt`, no `conftest.py`. The prescribed `uv sync --extra dev && pytest tests/` is impossible; verification is `core/validate.py` + one `score.py` parse + `ruff --select E9,F`, plus the once-only `forward_test.py`. I ran all of what exists. Zero unit tests is itself a finding: a 10k-line deterministic engine with no tests beyond data-shape checks.
- **Definitional drift in the forward trigger:** `forward_test.py` counts 597 rows settled after the cutoff, while `replay.py` scores 476 (superseded rows and rows with no ask are dropped, `replay.py:86-92`). The verdict is unchanged, but the two numbers are not the same quantity.
- **Brier baseline asymmetry (they disclose it):** bet-side `brier_market` uses the ask (`ledger.py:103`), forecast-side uses the mid (`score.py:48-52`). The bet-side +0.0853 is therefore ask-biased; the forecast-side +0.0092 is not, and it points the same way, so the conclusion is robust to the choice.
- **Cosmetic drift:** `validate.py:8-9`'s docstring still says "real_trading_enabled is still false" while `config/protected.json` has `true` and CI passes — the check was generalised after the config changed.
- **Numbers I did not verify:** the screens/pacing in `journal/screener.jsonl`, the Olas mech comparisons, and anything requiring the Odds API key or the Pearl signer — I did not run network paths. The screener rows are asserted at 300/300 per cycle with `cost_usd` recorded as batches; I did not price them.
- Everything above that is a number was produced by a command whose output I have; where I state a claim I could not execute (real fills, cloud cycle provenance), it is labelled **unverified**.

**Verdict: SKIP as a dependency; ADOPT three mechanisms, mapped to existing cards; queue nothing to the live path.**

The repo is not a grift — it is unusually self-critical, its record is genuinely point-in-time, and it publishes its own FAIL. But it is also the clearest available demonstration of *why* our doctrine exists: a system that rewrote its own strategy 116 times on prose evidence, guarded by one statistical gate that was in-sample, and whose own sealed forward test then returned −0.0730 with 145% of the P&L in one bet. Adopt (a) `replay.py`'s sealed-cutoff forward test as our standard lane-read convention, (b) `forward_test.py`'s pre-registered criteria (min bets, cw_return>0, single-bet dominance cap) as the pass/fail rule, and (c) `counterfactual.py` + `validate.py`/`boundary.sh` as primitives for pricing declined gates and for machine-enforcing frozen artifacts. Rationale for the split: (a)–(c) are the parts that *prevent* unmeasured self-rewriting; the self-rewriting LLM loop they were built to contain is precisely the part that must never enter our path before 2027-01-02, and cheaply does not need to.
