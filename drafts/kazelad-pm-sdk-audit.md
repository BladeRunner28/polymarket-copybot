# kazelad/prediction-market-trade-sdk — audit (2026-09-09)

**Verdict: ❌ SKIP — unauthorized, MODIFIED republish of pmxt-dev/pmxt with changes in auth/execution files. Never use; if pmxt is ever wanted, use the upstream repo only.**

## What it actually is
- This repo is a **mirror of `pmxt-dev/pmxt`** ("PMXT — the CCXT for prediction markets"): LICENSE says *Copyright (c) 2026 pmxt.dev*, README badges/stats links point at pmxt-dev/pmxt and the pmxtjs npm package, `core/` = `pmxt-core` v2.17.1 (identical package.json), `fifa.py` identical.
- **Metadata scam-signal:** kazelad repo = 142★ / **1,109 forks** (fork:star ≈ 8:1). Upstream pmxt = 2,140★ / 266 forks (healthy ~12%). The kazelad fork count is fork-farmed — bots forking to launder the repo's apparent popularity. Last commit message ("update original insert", 2026-09-03) = automated sync of an "original".
- **The mirror is NOT a faithful copy.** Recursive diff vs upstream (pmxt-dev/pmxt @ 2026-07-18) shows divergence in exactly the files that matter: `core/src/BaseExchange.ts`, exchange implementations (`probable/auth.ts`, `limitless/index.ts` + `utils.ts`, `hyperliquid/index.ts`, `baozi/errors.ts`, `rain/index.ts`), `router/types.ts`, `server/openapi.yaml`, `method-verbs.json`, `changelog.md`, `readme.md`. Auth and order-execution paths modified in an anonymous mirror = **cannot rule out tampering** (credential theft or order-manipulation insertions are the failure mode of such forks).

## Additional hygiene findings
- `fifa.py` at repo root contains a **committed live-looking pmxt API key** (`pmxt_d4b072cf…`) — whoever pushed this example left a real key in public history.
- Upstream pmxt itself was last pushed 2026-07-18; the mirror's 09-03 content is *newer* than upstream's public HEAD — unverifiable provenance.

## Fit vs roadmap
| Component | Assessment | Verdict |
|---|---|---|
| Anything from the kazelad repo | Modified/unverifiable copy of a third party's SDK | ❌ |
| pmxt (upstream, the underlying product) | Hosted unified PM API (Polymarket/Kalshi/Limitless/Probable/Baozi). Phase C data decision already picked **ccxt** (self-hosted lib) over hosted-API class; hosted trading = venue credentials to a third party, conflicts with the user's self-custody / own-book stance | ❌ (concept already covered) |
| dr-manhattan-rust (Rust CCXT-style PM API) | Noted in ccxt audit as the Rust-sidecar alternative | ⚪ untouched |

## Action
- **Do not clone, run, or npm-install from kazelad.** If a unified PM SDK is ever wanted, use upstream `pmxt-dev/pmxt` (MIT, real product, healthy stats) or the already-carded ccxt decision.
- Add the pattern to scout triage: **fork:star ratio > 2:1 on a repo with upstream = fork-farm mirror; diff core auth files against upstream before any consideration.**
