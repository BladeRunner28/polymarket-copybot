# Audit — Superior-Trade/superior-skills

**Date:** 2026-09-28 · **Mode:** read-only · **Clone:** `/tmp/superior-skills` (`--depth 1`)
**Repo:** https://github.com/Superior-Trade/superior-skills — "Open agent skills and tool schemas for Superior Trade — build, backtest, and deploy trading strategies on Hyperliquid"

---

## What it is (tree census)

| Fact | Value | Source |
| --- | --- | --- |
| Stars | 213 | GitHub API |
| License | **MIT** — `spdx_id: "MIT"` from API **and** `LICENSE` line 1 `MIT License` (Copyright (c) 2026 Superior Trade) | API + `LICENSE:1` |
| Pushed | 2026-09-10T03:54:44Z (created 2026-03-08) | GitHub API |
| Default branch | `main`, not archived, 3 open issues | GitHub API |
| Language (API) | JavaScript | GitHub API |
| Files (excl `.git`) | **75** | `os.walk` |
| Total bytes | **428,569** | `os.walk` |
| By ext | `.md` 54 files / 331,268 B · `.mjs` 10 / 48,707 · `.json` 7 / 44,296 · no-ext 3 / 1,133 · `.sh` 1 / 3,165 | `os.walk` |
| **Skills** | **30** (`skills/<name>/SKILL.md`) + 1 root `SKILL.md` | `os.listdir` |

The pack is a **vendor skill bundle** for "Superior Trade", a hosted trading platform (NautilusTrader/Freqtrade execution on GKE, managed wallets). It is ~77% markdown by byte count; the runnable code is repo tooling (validators, QR builders), not trading logic.

---

## Verified machinery (file:line evidence, real vs stub)

**Nothing is a stub.** Stub scan (case-insensitive `TODO|FIXME|not implemented|stub|placeholder|coming soon|mock`) across every `.mjs`/`.sh` returned **zero** hits. The JS is real, self-contained Node ESM:

- `package.json:7-12` defines `test` / `validate` / `lint` scripts.
- `scripts/validate-skills.mjs` (199 lines) — Agent-Skills-spec + context-budget linter: checks the 6 allowed frontmatter keys (`:18-25`), `name`==dir (`:126`), description cap 1536 / target 400 (`:29-30`), body limits 500 lines / 5000 tokens (`:33-34`), orphaned `references/` detection (`:161-175`).
- `scripts/audit-endpoints.mjs` (126 lines) — parses `scripts/api-contract/unified.json`, extracts every `METHOD /path` claim taught in the markdown, and fails if any taught route is absent from the contract (`:104-119`). It also rejects "legacy" routes.
- `scripts/api-contract/unified.json` — **OpenAPI 3.1.0 snapshot, version 0.2.0, 38 paths / 45 operations** (+ synthetic `GET /openapi.json` = 46 routes).
- `skills/deposit-qr/scripts/create-deposit-qr.mjs` (192 lines) — real EIP-681 payment-URI + quickchart QR builder.

**I ran the toolchain** (Node v26.0.0, throwaway, no install):

| Command | Result |
| --- | --- |
| `node --test scripts/*.test.mjs skills/*/scripts/*.test.mjs` | **12 tests, 12 pass, 0 fail** (`521ms`) |
| `node scripts/validate.mjs` | `Validated 30 Superior skills.` |
| `node scripts/validate-skills.mjs` | **0 errors, 0 warnings**; 31 SKILL.md; listing footprint ~8,738 chars (~2,185 tokens) |
| `node scripts/audit-endpoints.mjs` | `contract: Unified API 46 routes · skill claims 46` — **0 errors** |

**Genuine, quotable numbers** (the only real methodology in the pack):
- Trade-count bar — `<30` "Coincidence, not a strategy"; 30-50 marginal; 50-200 useful; 200+ "statistical confidence" (`skills/backtesting/SKILL.md:22-27`).
- Edge-to-fee ratio `edge_to_fee = avg_per_trade_pnl_bp / (round_trip_fee_bp + slippage_bp)` (`skills/fees-optimizations/SKILL.md:165`).
- Hyperliquid fee table — maker 1 bp / taker 4.5 bp default, builder-code 5 bp on volume (`skills/fees-optimizations/SKILL.md:26-40`).
- Shares conversion `shares = dollars / price` (`skills/polymarket/SKILL.md:56`; `references/strategy-authoring.md:133-140`).
- Polymarket rate limits: ~30 orders/min, ~100 data req/min (`skills/polymarket/SKILL.md:180`).

**No implementation behind the contract.** `unified.json` is a **client-side snapshot of a hosted API**; there is no server, engine, or fill simulator in the repo. The claimed "$50 backtest server" is remote and unverified (no API key; live behaviour **unverified**).

---

## Polymarket-vs-Hyperliquid relevance split

| Class | Skills | SKILL.md bytes |
| --- | --- | --- |
| **Hyperliquid / crypto-perp** | 14 — `hyperliquid, funding-rate-arbitrage, funding-squeeze, basis-arb, breakout, scalping, grid-trading, mean-reversion, bollinger-reverter-4h, donchian-strong-regime, dca-weekly, regime-overlay, fees-optimizations, dsl-exit-engine` | 122,501 |
| **Polymarket (prediction-market)** | 7 — `polymarket, probability-momentum, probability-mean-reversion, deadline-drift, related-market-spread, large-fill-pressure, catalyst-confirmation` | 32,811 |
| Other venues (Aerodrome/Base spot, Lighter, Lighter-Robinhood) | 3 | 17,400 |
| Wallet/funding plumbing (EVM) | 2 — `deposit-qr, external-deposit` | 11,047 |
| Generic / onboarding | 4 — `backtesting, trade-thesis, intelligence, superior-trade` | 30,798 |

**Headline venue is Hyperliquid.** Per its own description and the byte split (~3.7× more HL than Polymarket content), most of the pack targets a **crypto-perp / perp-DEX lane this stack does not have and cannot use (no live capital).** The 7 Polymarket skills are real but thin (~25% of content) and explicitly self-label as scaffolding ("starting points, not validated strategies" — `skills/polymarket/SKILL.md:251`).

---

## Fit table

| Component | Verdict | One-line reason |
| --- | --- | --- |
| `backtesting/SKILL.md` | ⚪ concept-only | Venue-neutral discipline (trade-count bar, 3-variant sweep, zero-trade escalation, exit-reason mix, walk-forward) — real thresholds, but generic and partly duplicates our existing doctrine; fold bullets, don't port file |
| 6 Polymarket archetype skills | ⚪ concept-only | Their own config knobs (`momentum_threshold 0.02`, `entry_deviation 0.08`) are un-tuned defaults; they say "not a proven edge" and carry **no fee or fill model** |
| `polymarket/SKILL.md` | ⚪ concept-only | Honest limitation "backtests from filled TradeTick … cannot model queue position or liquidity" (`:54`) matches our `phase-d2-fill-model` gap but **supplies no p(fill) model** |
| `unified.json` backtest API shape | ⚪ concept-only | Submit-queues/poll-status/logs + `Idempotency-Key` naming agree with our design; the payload itself is a hosted-GKE cloud contract we'd never call |
| `scripts/audit-endpoints.mjs` | ⚪ concept-only | Doc-vs-contract *linter* idea is transferable; the code depends on their OpenAPI snapshot |
| `validate-skills.mjs` context budgets | ⚪ concept-only | A useful check we could reuse generically for Hermes skills — not trading |
| `fees-optimizations/SKILL.md` | ❌ not-portable | Crypto-perp fee tiers + Freqtrade config; our `paper-ledger-fee-fidelity` card already has the **more precise** Polymarket fee law `C×feeRate×p(1−p)` |
| `dsl-exit-engine`, Freqtrade config keys | ❌ not-portable | `order_types`/`entry_pricing`/ROI-ladder are Freqtrade-specific |
| NautilusTrader strategy code (`strategy-authoring.md`) | ❌ not-portable | `subscribe_trade_ticks`/`order_factory` — we run Node Signal Brain + Rust sidecar, not Nautilus |
| `deposit-qr`, `external-deposit` | ❌ not-portable | EVM wallet funding + Relay bridge QR; we hold no wallet, no live capital |
| `aerodrome`, `lighter`, `lighter-robinhood` | ❌ not-portable | Venues we don't trade |
| 14 Hyperliquid skills collectively | ❌ not-portable | Perp/DEX lane with no analogue in a paper-only prediction-market stack |

---

## Integration proposal

Distinguish **"port a skill"** (copy/mimic content) from **"mimic a tool schema"** (copy an interface):

- **Port a skill — the only candidate.** A trimmed, venue-neutral *backtest discipline* checklist derived from `backtesting/SKILL.md` (trade-count bar, 3-variant sweep shape-reading, zero-trade 2-strike escalation, exit-reason distortion table, walk-forward OOS protocol). Fold into the **existing** `prediction-market-trading` / `trading-data-integrity` Hermes skill as a reference section — **do not** create 30 new skills.
  - **Effort:** ~1 h (docs only). **Risk:** low — a skill file changes no runtime behaviour.
  - **Flag-revertible:** yes, purely additive markdown; delete the section to revert.
  - **Timing:** the frozen measurement window closes **2026-10-08** and nothing may change scoring behaviour before then. This is doctrine-only, so it is compatible, but **card it only after the window** (and only with user approval — no `data/roadmap.json` edit was made).
- **Mimic a tool schema — nothing worth copying.** Our Rust sidecar + Node ledger + `scripts/archive-*` pipeline already exceed this repo's surface (it ships no engine, only a hosted-client contract). The submit→poll→logs lifecycle and `Idempotency-Key` semantics are the only ideas, and they match what we already do.

Maps to open roadmap gaps: `backtesting` bullets give *conceptual* support to `ml-doctrine-time-and-era-splits` (walk-forward to a different period/pair — never re-validate on the same window, `:65-69`) and to `ml-u1-conditional-fill-model` (its own "cannot model queue position" caveat), but **neither is filled** — no split code, no hazard/p(fill) formula. `phase-c` cross-venue arb: nothing here. `live-execution-reference`: nothing here (Hyperliquid side irrelevance overlaps `phase-d2`).

---

## NOT portable (summary list)

1. All 14 Hyperliquid / crypto-perp skills (`funding-squeeze`, `basis-arb`, `funding-rate-arbitrage`, `scalping`, `grid-trading`, `regime-overlay`, `dsl-exit-engine`, …).
2. `fees-optimizations` fee tiers + builder-code upsell (perp-specific; our fee law is ahead).
3. NautilusTrader strategy code and Freqtrade config keys.
4. `aerodrome`, `lighter`, `lighter-robinhood` venue skills.
5. `deposit-qr` / `external-deposit` EVM wallet-funding scripts.
6. The `unified.json` hosted-API contract as an execution spec.

---

## Honest caveats + verdict

- **Unverified:** the live Superior Trade API's behaviour, the "213 stars"-implied community trust, and any PnL/backtest claim in the pack (no key → no calls). The `unified.json` is a *snapshot*; its accuracy is the vendor's claim, not mine.
- **Vendor-inflated genericity:** the pack is 30 skills that are ~77% generic prose. Two-thirds are for venues we can't touch. Several ("use Bollinger mean-reversion on the 4h") restate textbook advice with no numbers.
- The MIT license is genuine and the tooling runs clean, so **adaptation with attribution is legal and easy** — but legality is not the bar. The bar is context cost: 30 skills at ~2,185 tokens of always-loaded listing + per-skill bodies is a large context tax for a paper-only, Polymarket-only stack.
- **Verdict: queue — not adopt-now, do not skip outright.** Do **not** copy the MIT skills into `~/.hermes/skills/` wholesale: 24/30 are Hyperliquid/other-venue/generic and are either venue-wrong or too generic to be worth the context cost. Adapt **one** artifact — the venue-neutral `backtesting` discipline bullets — into an existing skill **with MIT attribution** to `Superior-Trade/superior-skills`, and consider it *after* the 2026-10-08 frozen-window close. Everything else: read-only reference, skip.
