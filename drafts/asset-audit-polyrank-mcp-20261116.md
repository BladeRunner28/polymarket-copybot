# Asset audit — `polyrank/PolyRank-MCP`

**Date:** 2026-11-16 · **Queue id:** `polyrank/PolyRank-MCP` · **Source:** research agent, "possible external cross-check for the wallet-rank shadow arm"

## Verdict

**WATCH — the repo contains no portable code.** It is a typed MCP *client* for a commercial SaaS; every metric it advertises is computed server-side and none of it is published as a formula. Value available to us: **one keyless read-only cross-check**, at the shadow arm's natural read, and a metric vocabulary worth keeping as a checklist. **Not a dependency, not a vendor, not a lane input.**

## What it is

TypeScript MCP server (v0.5.1) exposing 36 tools over `api.polyrank.app` (free/public) and `api-agent.polyrank.app` (x402 pay-per-call). Advertised as skill analytics for Polymarket wallets: composite skill rank, Brier/calibration, alpha-vs-mid, risk-adjusted return, "copyability & max copyable clip, true slippage, copier-realized return, copy verdict".

**What it actually is, verified in source:** a transport + tool-schema layer. `src/index.ts` is 1,615 lines and `src/http.ts` 37.6 KB, and the only work they do is `fetch` to the two vendor hosts — `grep -E "Math\.(sqrt|log)"` over `index.ts` returns **zero hits**, and there is no local `brier`/`calibration`/`logLoss`/`ECE` function anywhere in 221 KB of TS. The 84 metrics and the Brier decomposition live behind their API (`/v1/public/trader/<address>/calibration` returns a pre-computed 10-bin diagram). So there is no arithmetic to re-derive, no thresholds to inspect, and no methodology to audit — the claims are unfalsifiable from outside.

Vendor-owned: `LICENSE` is "Copyright (c) 2026 Polyrank (DefiScout LLC)", and the org is the product's own.

## Anatomy facts that drove the verdict

| Fact | Read |
| --- | --- |
| MIT, full standard text, **no carve-out** (`NonCommercial`/`separately`/`not licensed` all absent); no bundled data assets | Licence is a non-issue — but there is nothing worth copying |
| ★2 · forks 0 · issues 0 · created 2026-07-07 | No community, no bug reports, no maintenance signal |
| **6 commits total**, last push today but all six are release/marketing: `README: LobeHub badge`, `Add Polyrank icon`, `0.5.1: … sign-in instructions`, `0.5.0: 36 tools`, `v0.4.0`, `v0.2.0` | Alive only as an API-wrapper bump; "pushed today" here means a badge, not engineering |
| **0 CI workflows** (`actions/workflows` → `total_count: 0`), no lockfile | No gated suite; `npm install` resolves latest |
| 15 vitest spec files, ~124 KB of tests (`oauth.spec`, `http_transport.spec`, `tool_inventory.spec`, …) | Genuinely unusual diligence for a 2-star repo — **unverified here**: read-only cron, no clone, so I did not run it and I will not call it green |
| Free tier = 17 read-only tools, no key; **paid plan gates the interesting half** — the deep grid ("copyability & max copyable clip, true slippage, hold-time split, copier-realized return, copy verdict") is paid x402 per `index.ts:482` | The free tier ends exactly where copy-trading relevance begins |

## Capability gap — proved in OUR repo before asserting one

The lead was "external cross-check for the wallet-rank shadow arm (`hard_q`)". That lane already exists and already owns this question:

- `src/lib/insider.ts` — 11-component wallet score that **already carries a `brier` term at 0.12 weight** (with `timing_alpha` 0.16, `entry_resolution_edge` 0.10, `market_selection_edge` 0.08 …).
- `scripts/wallet-rank-shadow.py` — two pre-registered arms (`hard-q`: `n_eff ≥ 8 ∧ BH q ≤ 0.10 ∧ band-excess > 0`; `shrunk`: empirical-Bayes band-excess with market-clustered SE and τ² shrinkage) against a frozen keep-the-set baseline, with a 200-forward-bet decision rule and a documented refutation. Card `crowdintel-wallet-fdr-audit`, approval card `t_7c91b4a1`.
- `src/lib/shadow-wallet-cap.ts` + `wallet-cap-shadow-lane` — already prices the copyable clip (would-be copies marked to settlement).
- `drafts/scoring-repos-audit-20260913.md` — a prior 16-repo audit already source-verifies a **better** calibration donor: `nexiumito/polycopy`'s `calibration = 1 − brier_wallet / brier_baseline_pool` (`factors/calibration.py`), MIT, formula in hand.

So the gap this repo was proposed to fill — calibration-based wallet ranking — is **already implemented, already measured against a frozen baseline, and already has a sourced formula from a stronger donor**. Nothing here moves it.

## Fit table

| Component | Verdict | Card / reason |
| --- | --- | --- |
| Brier / calibration math | ❌ not portable | Not in the repo (server-side). Formula already in hand from `nexiumito/polycopy` via the 2026-09-13 audit; `brier` term live in `insider.ts` |
| Wallet skill ranking (composite) | ❌ not portable | Black box. Our ranking is measured by `wallet-rank-shadow.py` under a pre-registered rule (`crowdintel-wallet-fdr-audit`) — a vendor score would be an uncalibrated second opinion, not an input |
| Copyability / max copyable clip / copier-realized return | ⚪ concept only, **gated to paid x402** | `wallet-cap-shadow-lane` + `wallet-cap-shadow-lane`-adjacent `wallet-copy-cap-measured-no-change` already own the measurement. The vendor's versions are the free tier's *excluded* half |
| 10-bin reliability diagram per wallet | ⚪ concept only | Cheap shape to mirror if we ever publish our own calibration read; no card asks for it |
| MCP server / tool schemas / transport | ❌ not portable | Node/TS MCP surface; our research stack is a Python collector + DeepSeek bot. Duplicates plumbing, adds a runtime |
| PostHog telemetry (`src/analytics.ts`) | ❌ avoid | No-op in stdio mode, but the hosted HTTP path fingerprints callers and the **vendor's own request log sees which wallets we query** |
| **Free-tier public endpoints as an external benchmark** | ⚪ **watch — the only real item** | Keyless, read-only, one-off Spearman against our own ordering. See REC |

## Recommendation (pre-registered)

```
REC — Cross-check the wallet-rank shadow's ordering against Polyrank's public rank, once
  Hypothesis:   Our shrunk-arm ordering of wallets and Polyrank's public composite/calibration
                rank agree materially on the wallets both cover — i.e. an independent shop using
                Brier-style skill lands on the same wallets we measure as band-excess positive.
  Measurement:  Read-only. At the shadow arm's natural read (>=200 forward bets, per the frozen
                rule), take the ~25-54 wallets with n_eff >= 8 that Polyrank's free tier covers
                (GET /v1/public/trader/<address>/calibration + leaderboard, no key), and compute
                Spearman rho between our shrunk-arm band-excess ordering and their public
                composite rank. Market-clustered bootstrap 95% CI on rho. Write the number to
                drafts/wallet-rank-shadow-<date>.md as a footnote. No lane, rule, size or config
                touched; no dependency added.
  Decision rule: if rho >= 0.5 with a bootstrap 95% CI excluding 0 by the next shadow read
                (<=2026-12-16) then keep Polyrank as a standing corroboration source and cite it
                in the shadow verdict; else record "no external agreement" and drop the source
                from the queue — our metric is ours, and a disagreement refutes neither arm.
  Cost:         ~1-2 h read-only, zero compute, zero live risk.
  Reversibility: delete the footnote; nothing else exists to revert.
```

**Note on the fork:** neither branch changes trading behaviour, and that is deliberate — the shadow arms are already the falsifiable test, and a third party's ordering cannot substitute for the 200-bet read. A high rho buys corroboration; a low rho buys a closed lead. Both are cheap.

## NOT portable

- Any metric arithmetic (none is in the repo).
- The AI Lab / backtest / paper-trade tools — `polyrank_run_backtest`, `polyrank_start_paper`, strategy CRUD: these 16 tools need `POLYRANK_API_KEY` on a **paid plan**, spend plan AI credits, and their results are labelled SIMULATED. Building a copy-strategy backtest inside a vendor's account duplicates `pm-hftbacktest` / our own replay machinery, with our book's data leaving the building.
- The MCP server itself, the HTTP transport, the OAuth surface, the tool schemas.
- The PostHog analytics path.

## Honest caveats

1. **The interesting half is paid.** Free = P&L / win-rate / volume / percentiles + a reliability diagram. Copy-relevant metrics (clip, true slippage, copier-realized, copy verdict) are x402-gated, so the free tier cannot answer a copyability question at all.
2. **Unfalsifiable methodology.** 84 metrics, zero published formulas, zero methodology doc in the repo. Their ranking cannot be reproduced or checked against our labels — the only check available is rank agreement, which is what the REC does.
3. **2 stars, 0 forks, 0 issues, 6 commits, no CI.** This is a marketing surface for a SaaS (LobeHub badge as the newest commit), not a maintained library. The 15 spec files are the one genuinely good signal and I did **not** run them.
4. **Disclosure cost.** Querying `/v1/public/trader/<address>/calibration` tells a commercial third party which wallets we are profiling, over our IP. Free-tier rate limits are not documented in the README ("your plan's limits"); a 25-54 wallet one-off is fine, a live loop would not be.
5. **No local execution.** Read-only cron constraint: nothing cloned, no test suite run, no numeric verification performed because there is no numeric code to verify.

## Registry block (not applied)

Per the audit procedure this finding belongs on the existing lane card. This run's constraint (recommendations-only, no repo source edits) and the concurrent-writer risk on `data/roadmap.json` mean it ships here for deliberate application:

```
AUDIT INPUT (2026-11-16, pending approval; drafts/asset-audit-polyrank-mcp-20261116.md):
polyrank/PolyRank-MCP → WATCH, no portable code (MIT but a pure client: 0 local metric math,
all fetch to api.polyrank.app). Calibration-ranking gap already closed here — brier term in
src/lib/insider.ts, arms pre-registered in scripts/wallet-rank-shadow.py, better donor formula
(1 - brier_wallet/brier_baseline_pool) already sourced from nexiumito/polycopy in
drafts/scoring-repos-audit-20260913.md. Free tier ends where copyability begins (clip/slippage/
copier-realized are paid x402). Residual value = one read-only Spearman cross-check at the
>=200-bet read; rho >= 0.5 (CI excl 0) => cite as corroboration, else drop the source.
No dependency, no lane input, no code.
```
