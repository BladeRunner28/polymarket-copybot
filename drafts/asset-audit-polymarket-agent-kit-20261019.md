# Asset audit — `crowdintel-xyz/polymarket-agent-kit`

**Verdict: AUDIT (concept + one read-only measurement), adopt no code.**
Audited 2026-10-19 · MIT · ★0 · 87 KB · 5 commits · free-tier REST key required
`drafts/asset-audit-polymarket-agent-kit-20261019.md`

---

## 1. What it is

A **documentation and spec kit for a hosted service**, not a library. The repo contains 24 files:
4 JSON (179 KB, almost all the vendored `openapi.json`), 14 Markdown (40 KB: README, `docs/metrics.md`,
`docs/pitfalls.md`, `docs/comparison.md`, `docs/tools.md`, 4 Agent `SKILL.md` prompts, quickstarts),
1 PNG logo (36 KB), 2 CI YAML (3 KB), **one 2.6 KB TypeScript example and one 2.5 KB Python example**.
No source tree, no lockfile, no Dockerfile, no `.env.example`.

Every number the product sells (`ev_ci_low`, `effective_n`, `trader_kind`, insider score, funding
clusters) is computed **server-side at `mcp.crowdintel.xyz` / `crowdintel.xyz/api/v1`** behind a bearer
token (`cint_api_…`). The repo has nothing to vendor, clone or read beyond its prose.

The valuable part is that prose. `docs/metrics.md` (5.5 KB) and `docs/pitfalls.md` (3.3 KB) are an
unusually honest statement of *how wallet-skill statistics should be constructed* — and they
independently converge on conclusions this repo already measured for itself in September.

## 2. Anatomy facts that drove the verdict

| Claim | Reality (from the API/tree) |
|---|---|
| "Maintained path" | **5 commits total.** 2 on 2026-08-13 (v0), 3 on 2026-10-12 (content dump), then a weekly `chore: weekly freshness stamp` written by `crowdintel-bot`. The last push (2026-10-19) is that bot. Activity is machine-generated. |
| "tests=yes, ci=yes" | No logic is tested because there is no logic. `smoke.yml` curls `mcp.crowdintel.xyz/health` for 200 and optionally `tools/list` with a repo secret; `freshness.yml` asserts the endpoint answers 401/200, re-downloads `openapi.json` and commits a timestamp. CI tests **the vendor's uptime**, not the repo. |
| Community | ★0, 1 fork, 2 open issues — #1 "we issue them capability certificates" (spam), #2 an unsolicited C++20 engine port proposal. Neither is answered. |
| "Successor to Polymarket/agents" | True: `Polymarket/agents` is `archived: true`, last push 2024-11-05, 3.8k★ (the README says "archived in May 2026"; the archive *date* is not exposed by the API). |
| "1.88B indexed fills" (`docs/metrics.md`, "coverage as of 2026-08-16") | The **CI-refreshed** `openapi.json` in the same repo says "unfiltered scans of the **1.3B-row** trades table". The two vendor artifacts disagree by 580M rows. Coverage is **unverified**. |
| "Free key, no credit card, MCP free on every plan" | `openapi.json` securityScheme: "Mint at /settings/api (**Terminal $99+**)". Pricing page (read 2026-10-19): "Every endpoint is free to test", "50,000 REST calls/mo (**100x free**)" ⇒ free ≈ **500 calls/month**; "$29/mo unlocks MCP server access". So: free **REST** key, **MCP behind Pro**, and the README's "free on every plan" is stale. |

Endpoint surface is real and broad — 38 paths, all tagged `Min tier: free` with free-tier caps
(top-25 leaderboards, page size 25, `wallet_stats`-only dossier). `/v1/status/parity` publishes nightly
PnL parity against Polymarket's own profit API; `/v1/backtest/run` enqueues a server-side replay.

500 calls/month is a **one-shot cross-section, not a monitoring lane**: one snapshot of ~500 wallets
costs the entire month's allowance.

## 3. What we could reuse (ideas only — no code to copy)

Verified against this repo's own source, not against the README:

| Idea in the donor | Our baseline (verified) | Verdict |
|---|---|---|
| **Rank by a confidence-interval lower bound**, never by win rate or a point estimate | `src/lib/scoring/wallet.ts` ranks on a hand-weighted `globalScore`; its `consistencyScore` contains the literal term `winRate*130 − 20`. `drafts/scoring-fix-methods-20260913.md` §3 #4 already specifies the fix ("emit posterior mean **and** lower bound; gate on the lower bound") and §2 measured the composite at **AUC 0.417** vs price-only 0.747 on 9,642 copies. *Unimplemented-by-plan, not missing — no roadmap card names it.* | ⚪ concept already owned by our own design doc |
| **Kish effective n with positions inside one event counted as fully correlated** ("a 50-leg date ladder is one bet, not fifty") | Our ICC/design-effect work lives in the pilot scripts and is measured **dataset-wide** (ICC(wallet) 0.225 → effective N 784 → MDE $1.29/trade). Nothing computes it **per wallet at ranking time**: `minResolvedTrades = 5` counts legs, so a date ladder clears the gate as five bets. | ✅ adopt the arithmetic (≈20 lines, our own implementation) |
| **Benjamini–Hochberg q-values across the tested wallet universe** | **Zero hits** for `benjamini|fdr|qvalue` in `src/` or `scripts/`. We screen ~500 wallets and take the top of the composite — exactly the selection the q-value corrects. Cheapest genuine delta in the whole repo. | ✅ adopt; no card asks for it today (new work item) |
| **`trader_kind` bot / maker / human, with maker rebates ≥5× taker as the maker rule**, rendered "Unclassified" when missing | **Zero hits** for `traderKind|isMaker|makerRebate` anywhere. `scan-wallets.ts` cannot distinguish an exchange-funded market maker from a sharp human; `copyabilityScore` is the only proxy and it looks at liquidity/spread, not the wallet's own fill mix. | ⚪ concept; data availability unverified (needs a check that sidecar fills carry maker/taker) |
| **Insider score: gate first (only entries ≤35¢ score), then score; delete signals that measured negative rather than down-weighting them; score is per-alert, never per-wallet; require corroboration** | `src/lib/insider.ts` is 11 homerun-derived weighted components with fixed thresholds (0.60/0.72), **not** entry-price-gated, and its `fundingOverlap` component is a literal "no data → neutral 0.5". `phase-d-insider-gating` is an open Backlog card. | ✅ design → that card. **Weights ❌** — fit on ~6,800 of *their* resolved alerts, unverifiable. |
| **Infrastructure funders must *penalise* a cluster, not boost it** (Polymarket's own proxy factory funds tens of thousands of wallets) | Our `fundingOverlap` is neutral-by-default and `cluster_correlation` is symmetric — nothing penalises a known infra funder. | ⚪ concept for `phase-d-insider-gating` |
| **90-day half-life decay on z/EV** | We use hard 30-day windows (`roi30d`, `winRate30d`) plus `regime-cleanliness-baseline` era splits. Decay is a different smoothing, not a better one, at our N. | ❌ not portable / not needed |
| **The API itself** (`ev_ci_low`, `trader_kind`, funding graph as a service) | Would add a token, a vendor, and a 500-call/month ceiling; coverage claim self-contradicts. Never a lane dependency. | ❌ reject as a dependency |
| The prose itself (`docs/pitfalls.md`: proxy nonces are always 1, so "fresh wallet" is meaningless; volume is the easiest number to fake; win rate may filter but never sort) | Useful as a **checklist to re-verify**, not as new knowledge — every item is either already respected here or already measured. | ⚪ reference only |

## 4. Integration proposal (if the user approves)

**Change:** one new read-only script, `scripts/wallet-skill-fdr.py` (Python, numpy/scipy already in
`venv-calib`), that:

1. pulls every wallet `scan:wallets` has screened with a resolved-trade count and PnL (read-only);
2. recomputes a per-wallet excess-return statistic from `PaperTrade` labels we already hold;
3. applies the **event-clustered effective n** (positions sharing a market/event count once) and a
   **BH correction across the whole screened universe**, then reports how many currently `track`
   wallets survive at q ≤ 0.10.

**Effort:** ~half a day, read-only. **Risk:** none to the live lane — no rule, size, threshold, gate or
config is touched, and nothing from the donor is copied or imported. **Reversibility:** delete one
script; nothing to revert.

**Then, only if the measurement says so:** a shadow column (`effectiveN`, `skillQ`) next to
`globalScore`, gated behind a flag, before any change to `walletStatus()`.

## 5. NOT portable

- Any code: there is none (two example scripts that call their API).
- The four `skills/*/SKILL.md` files: agent-prompt marketing for a paid service, duplicating the job
  our research bot + `polymarket` skill already do.
- Insider-score **weights** and the "6,800 resolved alerts" fit: unverifiable, and fitted to a
  different wallet population.
- The hosted API as a runtime dependency: token required, 500 calls/month free, MCP behind $29/mo,
  and a coverage figure that contradicts itself.

## 6. Honest caveats

- **0★, 5 commits, weekly bot stamps.** The "maintained" framing is a CI cron job. Treat the prose as a
  design essay by an interested party, not as an audited methodology.
- **Nothing here is testable from outside.** No tests of any formula exist in the repo because no
  formula exists in the repo. Contrast with our own pilots, which are reproducible in one command
  (`scripts/pilot-score-separation-papers.py` → JSON artifacts).
- **Two internal contradictions** (1.88B vs 1.3B fills; "free on every plan" vs "$29/mo for MCP" /
  "Terminal $99+"): the docs, the spec and the pricing page are three different vintages.
- **The one thing that would be genuinely new to us (BH q-values) is also the cheapest thing to write
  ourselves** — which is the argument for reading this repo and then closing it.
- Our own September measurement stands as the stronger evidence: the wallet composite is
  **anti-predictive** (AUC 0.417), the price alone is 0.747, and v1 price-edge failed its
  pre-registered test and shipped shadow-only. Nothing in this repo overturns any of that; its
  contribution is the *sample-size discipline*, which we had already specified and not yet wired.

## 7. Registry / card block (ready to paste — not applied by this job)

```
AUDIT INPUT (2026-10-19, verdict audit; drafts/asset-audit-polymarket-agent-kit-20261019.md):
crowdintel-xyz/polymarket-agent-kit (MIT, ★0, 5 commits, docs+OpenAPI only, token-gated hosted API).
Transferable: BH-FDR across the screened wallet universe + event-clustered effective n per wallet +
trader_kind (maker/taker rebate ratio). Verified absent here: benjamini/fdr/qvalue = 0 hits;
traderKind/isMaker/makerRebate = 0 hits. Lower-bound ranking is already specified in
drafts/scoring-fix-methods-20260913.md §3 #4 (unimplemented-by-plan). Proposal: read-only
scripts/wallet-skill-fdr.py over already-screened wallets; no rule/size/gate change.
Decision rule: if >=30% of currently `track` wallets fall below q=0.10 (or effective n < 8) then
propose q-gated shadow ranking; else drop. Effort ~0.5 day. No code adopted.
```
