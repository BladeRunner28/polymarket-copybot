# predict-raven audit — Alchemist-X/predict-raven (2026-09-09)

**Repo:** github.com/Alchemist-X/predict-raven · **License:** MIT (clean, Copyright 2026 Alchemist-X) · **72★ / 28 forks** · TypeScript monorepo (pnpm) · created 2026-03-13, pushed 2026-09-08 (active) · default branch `main` · ~457 TS + 76 TSX + 23 PY code files (~556 total as reported) · **125 test files** (124 `.test.ts` + 1 py) colocated with source.

Clone audited: `/tmp/audit_triage/clones/Alchemist-X_predict-raven` (depth-1, HEAD 4061df7, 2026-09-06).

---

## 0. License + referral-flag verdict (checked FIRST)

- **LICENSE = real MIT**, no parody/mutation, spdx `MIT` on GitHub API. **Borrowable with attribution.** No NOASSERTION traps.
- **Referral link: NONE exists — quick-look flag is a false positive.** Every "referral/affiliate" string hit in the tree is one of:
  1. The project's **own compliance rules** forbidding affiliate links (e.g. `docs/marketing/world-cup/landing-copy.en.md`: "the site carries no sportsbook deposit / wagering / affiliate links"; `docs/internal/plan/2026-06-09-world-cup-special-plan.md` bans Polymarket affiliate links in copy) — the *opposite* of a farm tell.
  2. **Invite codes** (`FORECAST_INVITE_CODE=raven-labs`, `x-invite-code` header, `/invite` page, DB stores only hashes) = beta-gating for their hosted forecast app, not monetization.
  3. A 2026-05 product-plan item ("Referral：用户拉新分润") for their own consumer product.
  4. "Raven earns a share of Polymarket's **builder rewards** on each trade" — Polymarket's liquidity-incentive program (paid by Polymarket out of volume), not an affiliate cut.
  - No `?r=`, `polymarket.com/r/`, or handle-referral URLs anywhere in README/code. README's only polymarket.com links are the homepage + their own on-chain profile.
- **Hype-vs-source check (fresh + fast-starred, 72★ in ~6 months):** NOT a farm. Repo age matches topic (Mar 2026), code is dense and self-consistent (monorepo, services run, deploy/ + docker compose, run ledgers with real CSVs, 125 tests, 151+ merged PRs referenced). README is *unusually honest*: it discloses "Live loop paused (last live run 2026-06-10)" and a known search-evidence contamination incident, while the GitHub one-line description ("The first autonomous, continuously-running trading agent… Live on Polymarket") is stale marketing. Same-author pattern, no hijack indicators.

---

## 1. What it is

An **LLM-agent forecasting framework** ("iterative evidence forecaster") wrapped in a product family. One engine capability — an AI agent researches a binary question, weighs *cited* evidence, defends a probability — is reused by:

| Product | What it does | Status (as disclosed) | Code |
|---|---|---|---|
| Polymarket live trading | LLM "Pulse" research → edge vs market-implied → ¼-Kelly → hard risk rules → CLOB orders | **Paused, last live run 2026-06-10** | `services/orchestrator`, `services/executor`, `scripts/pulse-live.ts` |
| World Cup market-blind forecasts | Statistical prior + bounded Bayesian updates, Brier-scored in public, **never reads market prices** | Live, group stage + R32 scored | `packages/sports-model`, `packages/fifa-models`, `scripts/world-cup` |
| Autonomous paper trading | $10k market-blind sim twin, 3 evals/day, self-review w/ Brier skill | Live since 2026-07-03 | `services/paper-agent` |
| Raven Delta / Delta PM | News→stock impact analyzer; autonomous news→shadow-PM over **Hyperliquid tokenized US-stock perps** (hl_perp, pre-IPO perps) | Shadow mode | `apps/raven-delta`, `services/delta-pm` |
| Multi-model fleet / hosted engine | 7×$10k paper books (one per frontier model); hosted forecast console + API + MCP | Live | `scripts/fleet`, `apps/raven`, `services/forecast-api` |

**Trading pipeline (their live line, 4 layers):** Pulse research (LLM + web search over Polymarket listings, `fetch_markets.py`) → decision (`pulse-direct`: regex-parse Pulse markdown into `PulseEntryPlan`; `provider-runtime` legacy spawns Codex/Claude/OpenClaw CLI) → execution/risk (service-layer hard rules, FOK) → state/archive (`@polymarket/clob-client-v2`, clob.polymarket.com, **Polymarket only — no Kalshi**).

---

## 2. Verified machinery (in source, with formulas)

### 2a. Trading line deterministic core (services/orchestrator)
- **Kelly sizer** — `services/orchestrator/src/lib/risk.ts` `calculateQuarterKelly`: `fullKellyPct = (aiProb − marketProb) / (1 − marketProb)`, then `/4`. **This matches the correct binary Kelly `f = edge/(1−p)`** (octagon precedent), with `p = marketProb` (the price you pay). Guards return 0 when `marketProb∉(0,1)` or `aiProb ≤ marketProb`.
  - **Input-assumption flaw (their side):** `aiProb` is the raw LLM probability regex-parsed from Pulse research markdown (`pulse-entry-planner.ts:258 aiProb: Number(match[3])/100`; `full-pulse.ts:364`). Kelly assumes a *calibrated* probability — an uncalibrated model delta is the classic phantom-edge source. They do NOT appear to apply calibration to aiProb before sizing (the World Cup line calibrates; the trading line does not, at least not in the paths read).
- **Trade guards** — same file `applyTradeGuardsDetailed`: per-trade % cap, total-exposure % cap, per-event exposure % cap, max-positions count, liquidity cap, min-trade; returns `bindingConstraint` + headroom per constraint. Sizing is trimmed to the binding constraint.
- **Fees netting** — `lib/fees.ts`: Polymarket V2 taker fee formula `fee_usdc = shares·price·feeRate·(price·(1−price))^exponent` with per-category static schedules (sports 0.03/1, politics 0.04/1, crypto 0.072/1, other 0.2/2 …) or live `getClobMarketInfo` FeeDetails; `calculateNetEdge` nets edge and round-trip fees before Kelly (planner `edgeOverride: netEdge`).
- **Decision ranking** — `pulse-entry-planner.ts`: `monthlyReturn = netEdge / monthsToResolution`, sort desc, **top 4**, batch cap 20% of bankroll; `open` sizing is recomputed programmatically (¼-Kelly) — Markdown suggested sizes are human-audit fields only (`docs/risk-controls.md`).
- **Risk state machine** — HWM drawdown ≥20–30% → `halted`, fail-closed, admin `resume` only; per-position stop-loss at −30% with priority over strategy actions; Pulse staleness / candidate floor / missing clobTokenIds → risk state, no new opens. Service-layer (never prompt-level).
- **Paper agent** — `services/paper-agent`: market-blind dossiers, net-edge exits (`netEdgePp` in ledger), Brier skill self-review vs market, run ledger CSV on disk.

### 2b. Sports statistical core (the repo's best asset — REAL math, zero deps)
- `packages/sports-model` — **`dependencies: {}` (pure TS, zero runtime deps)**, heavily unit-tested:
  - `elo.ts`: `eloExpectedScore = 1/(1 + 10^((ratingB−ratingA)/scale))`, scale 600 (FIFA-SUM); `eloUpdate = rating + K·(actual−expected)`, K=60. **Davidson (1970) ties extension of Bradley–Terry**: `wH=10^((rH+HA)/scale)`, `wA=10^(rA/scale)`, `wD=drawNu·sqrt(wH·wA)` normalized (defaults HA=65, drawNu=0.70).
  - `poisson.ts`: independent-Poisson goal model, **log-space PMF** (`logP = −λ + k·ln λ − ln k!`), full score matrix → 1X2 / O-U / BTTS / correct-score readoffs.
  - `dixon-coles.ts` (time-decay correlation adj.), `xg.ts`, `calibration.ts` (ECE), `ensemble.ts`, `contextual.ts`, `rng.ts` (seeded), `ml/`: hand-rolled decision-tree, random-forest, gradient-boosting, logistic-regression — all with tests.
- `packages/fifa-models` (dep: sports-model only): `bracket.ts` Monte-Carlo bracket sim, `models/fatigue-elo.ts`, `models/tactical-melo.ts`, `models/stacked-ensemble.ts`, `calibration/mcboost.ts` (multicalibration), knockout-draw calibration; CLI `pnpm forecast`. README claims 100,000-tournament MC sims (orchestrator reference found for MCBoost; sim-count claim not re-derived here).
- **Market-blind discipline** — price fields (`outcomePrices/bestBid/bestAsk/…`) stripped at cache-write; snapshot.json shows `priceFieldsStripped` reason "analysis must never see market prices". Enforced by process isolation + env (`FORECAST_MARKET_BLIND=1`).

### 2c. Test/run evidence
- 125 test files; key modules colocated with tests (`risk`, fees path, elo/dixon-coles/poisson/ml, runtime planners, paper-agent reflect). `runtime-artifacts/world-cup/run-ledger/ledger.csv` (121 rows) = real run audit trail. `evaluation/runs/` present. Not a scaffold repo.

---

## 3. Fit table (Xman stack: TS/Rust · Polymarket CLOB · paper-only · v39 Bayesian evidence engine · Kelly Phase B SHIPPED · local-LLM research bots · LLM/agent layers = not-portable by doctrine)

| # | Component | Verdict | Rationale |
|---|---|---|---|
| 1 | `packages/sports-model` (Elo/Davidson/Poisson/Dixon-Coles/xG/calibration/ML) | **✅ ADOPT (conditionally)** | Zero-dep, pure, tested TS soccer modeling core; MIT. **Adopt if/when soccer markets open as a roadmap gap** (Polymarket/Kalshi list WC/league markets); otherwise stays queued. Highest-value asset in the repo. |
| 2 | `packages/fifa-models` (MC bracket sim, stacked ensemble, MCBoost) | **✅ ADOPT (conditionally, with #1)** | Same condition; tournament-structure markets (winner/qualify) only derivable from a sim core like this. |
| 3 | Kelly + fee-net implementation as **reference spec** | ⚪ concept-only (validation) | Xman Kelly already shipped Phase B; formula family identical (`edge/(1−p)`, quarter). Use `lib/risk.ts` + `lib/fees.ts` (category fee exponents, round-trip netting) as a spec cross-check during the Kelly measurement window — no code transfer needed. |
| 4 | Service-layer hard-rule trim w/ binding-constraint reporting, fail-closed HWM halt | ⚪ concept-only | Validates octagon 5-gate risk architecture already in the stack; deterministic + testable pattern worth mirroring in paper ledger, nothing to import. |
| 5 | `monthlyReturn = netEdge / monthsToResolution`, top-4, 20% batch cap | ⚪ concept-only | Return-per-time ranking metric is a usable idea for Xman's recommendation prioritization layer; replace LLM source with v39 engine output. |
| 6 | Market-blind discipline (strip price fields at cache-write, blind mode env) | ⚪ concept-only | Reinforces existing doctrine (independent estimate ≠ restated consensus). |
| 7 | Two-gate news judgment + per-decision audit chain (Delta PM pattern) | ⚪ concept-only | The gating (does it matter / already priced in?) + immutable decision ledger maps to news-driven political/economic markets on Xman's venues. |
| 8 | `services/forecast-engine` LLM evidence forecaster (cluster discounting, disconfirmation pass, saturation) | ❌ NOT-PORTABLE (doctrine) | LLM/agent layer; duplicates v39 Bayesian evidence engine + DeepSeek/local-LLM research bots. |
| 9 | Pulse LLM research → `aiProb` (the actual edge source of their trading line) | ❌ NOT-PORTABLE | LLM probability parsed from markdown; uncalibrated raw delta fed to Kelly = the exact octagon pitfall. Cautionary, not transferable. |
| 10 | provider-runtime (spawns Codex/Claude Code/OpenClaw), Norns tier aliasing | ❌ NOT-PORTABLE (doctrine) | Agent-orchestration layers. |
| 11 | Delta PM venue (Hyperliquid hl_perp tokenized US-stock perps) | ❌ NOT-PORTABLE | Wrong venue class — no Polymarket/Kalshi relevance. |
| 12 | Web apps/console, forecast API/MCP, fleet scripts | ❌ NOT-PORTABLE | Product surfaces duplicating existing dashboards/research-bot tooling. |
| 13 | Anything Kalshi | ❌ N/A | Repo is Polymarket-only (`@polymarket/clob-client-v2`); no Kalshi adapter to mine. |

---

## 4. Integration proposal (conditional, post-freeze)

**If a sports/soccer roadmap card opens (the only adopt trigger):**
- **Vendor** `packages/sports-model` (+ `fifa-models` if tournament markets) as a pure-TS package into the stack. Effort: **S–M** (zero runtime deps; port = copy + attribution header + existing tests; adapters needed for event→market mapping on Polymarket/Kalshi sports slugs). Risk: **low** (pure functions, no I/O, fully unit-tested; math is standard Elo/Davidson/Poisson/Dixon-Coles). Flag-revertible: **yes** — package boundary, delete-and-rollback trivial; gate behind a feature flag; paper-only posture means zero capital exposure during validation.
- **Then**: score the core's forecasts (Brier/ECE) against market-implied on Xman's venues for a full season-cycle before any recommendation use — mirrors their own public track-record approach.
- **Cross-check task during Kelly window (no ship, spec only, ~half a day):** diff Xman's shipped Kelly edge/quote handling against Raven's `edge/(1−p)` + round-trip-fee net + binding-constraint trim; confirm Xman prices edge vs the executable ask (Raven's pulse-direct path nets fees but does not clearly edge-vs-ask — verify before crediting that pattern).

**Effort summary if adopted:** vendor S–M / cross-check XS–S. Nothing ships before Oct 8 by freeze — this is queue-and-prepare work.

---

## 5. NOT-portable list (explicit)

1. LLM forecast engine (`packages/forecast-engine`) — evidence rounds, cluster discounting, disconfirmation pass, saturation logic: all LLM-provider-coupled; duplicates v39/local-LLM bots.
2. Pulse research → aiProb edge source — LLM output parsed as probability; **uncalibrated** (would need calibration + executable-quote handling to even be concept-viable).
3. Agent runtime layers: provider-runtime (Codex/Claude Code/OpenClaw spawning), Norns tier aliases, skill settings.
4. Raven Delta, Delta PM (incl. Hyperliquid perp venue + two-gate LLM analyzers), forecast API/MCP server, Next.js apps/console/web, fleet quota scripts.
5. The "autonomous continuously-running" claim itself — live loop has been paused since 2026-06-10; treat the trading line as an archived experiment, not production software.

---

## 6. Honest caveats + verdict

**Caveats**
- Young + fast-starred (72★, ~6 mo old) but *substance-verified*, not hype: real MIT, honest paused-live disclosure, contamination incident documented, dense tested code, real run ledgers. No farm signals; referral flag is a false positive (beta invite codes + compliance copy).
- Kelly input assumption: raw LLM `aiProb`, no calibration in the trading line, market mid not clearly ask-adjusted → their live PnL (unverified on-chain; I did not confirm the 0x6664… profile) would have been sensitive to exactly the phantom-edge failure mode we already know. Their paper line self-scores Brier, which is the right habit.
- World Cup public Brier/ECE scores are claimed and code/ledger-backed, but the external site was not independently verified in this audit.
- No Kalshi support anywhere → zero value for the Kalshi leg.

**Verdict: QUEUE.** License MIT (borrowable w/ attribution); verified real machinery — correct `edge/(1−p)` quarter-Kelly with fee netting, service-layer hard-rule risk (fail-closed HWM halt, binding-constraint trim), and a genuinely strong zero-dep tested sports statistical core (Elo/Davidson/Poisson/Dixon-Coles/xG/MC-bracket/ML). Top transfers: **sports-model + fifa-models (conditional adopt — only if soccer enters scope; S–M effort, low risk, flag-revertible)** and **Kelly/fee-guard spec cross-check during the Kelly window (XS)**. Everything LLM/agent (forecast-engine, Pulse aiProb, runtimes) is not-portable by doctrine; repo is Polymarket-only. Consistent with the Sep 8–Oct 8 freeze: nothing ships — queue; re-open only if a sports roadmap gap opens or activity suggests a new non-LLM core.
