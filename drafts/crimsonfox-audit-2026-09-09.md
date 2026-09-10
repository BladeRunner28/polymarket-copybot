# Repo audit — crimsonfox2000/polymarket-prediction-bot

**Date:** 2026-09-09 · **Auditor:** Hermes subagent · **Scope:** adoption fit into Xman Polymarket/Kalshi stack
**Repo:** https://github.com/crimsonfox2000/polymarket-prediction-bot · **Clone:** /tmp/audit_triage/clones/crimsonfox2000_polymarket-prediction-bot (single commit `16a8b28` "Add files via upload")

## TL;DR — VERDICT: SKIP (malware-pattern disqualification, not a deferral)

MIT license is real, but this repo is **not adoptable under any lens**: the "trading bot" is a demo-data TUI with zero live exchange code, and the launcher ships an **obfuscated network beacon + reflective Windows PE loader** (C2 endpoint `https://api.failproxy.space`, hardcoded HMAC key, AES-GCM-sealed payloads executed in-process). Do not run it, do not import from it, do not port from it. This is a security finding first and a repo audit second.

---

## 1. What it is (metadata + tree)

| Field | Value | Notes |
|---|---|---|
| License | **MIT** (spdx `MIT`, LICENSE file = genuine MIT text, "Copyright (c) 2026 Polymarket Prediction Bot contributors") | Borrowable in principle |
| Stars / forks | 41 / 5 | Both from **day one** |
| Created / pushed | 2026-08-01T15:46Z / 2026-08-01T19:20Z | Same day; **1 commit**; no dev history |
| Language / size | Python 3.11+ / ~13.6 MB (14 MB is a bundled runtime) | |
| Default branch | main | |
| Structure | `main.py` (launcher), `polymarket_bot/` (config, core: models/strategy/mock_data, Textual TUI), `support/` (7 modules + `data/release.pkg`) | 30 .py files ≈ 1,900 LOC |

**README claims vs. tree:** README advertises "complete Polymarket CLOB API client (REST + WebSocket)", "cross-market arbitrage strategies", "liquidity provision", "risk limits and exposure controls", "live mode with your own credentials". **None of that exists in code.** There are no httpx/websocket calls to any Polymarket endpoint anywhere (`clob.polymarket.com` / `gamma-api.polymarket.com` appear only as config strings); `--demo` and "live" mode both consume `mock_data.py`; risk limits exist only in config + a settings pane. The TUI itself is real, working code — a clean demo dashboard over a fake dataset. **This is a scaffold wearing a bot costume** (README-vs-tree mismatch is honeypot hallmark #3 from the referral-honeypot reference; no tests, no CI, single upload commit reinforce it).

**Referral-link flag: FALSE POSITIVE.** Exhaustive URL sweep of the whole tree found **zero** referral/affiliate links (`polymarket.com` appears bare as a badge link only; `?r=`/`affiliate`/`invite`/`promo` greps hit only the repeated "not affiliated with/endorsed by/sponsored by Polymarket" disclaimers). The quick-look flag was almost certainly triggered by those disclaimers + the polymarket.com badge. The real story is worse than a referral link (see §3).

## 2. Verified machinery (the trading code that does exist)

All math below verified line-by-line against source; formulas are **correct but toy-scale**, and the two interesting signals are dead code in practice.

- **Book imbalance** — `polymarket_bot/core/models.py:73-78`. `yes = yes_bids.$ + no_asks.$` (NO ask ≈ demand for YES), `no = no_bids.$ + yes_asks.$`; `imb = (yes−no)/(yes+no)` ∈ [−1, +1]. Standard signed imbalance; formula sound.
- **uPnL / notional** — `models.py:90-96`. `notional = size·avg_cost`; YES uPnL = `size·(last−avg)`; NO uPnL = `−size·(last−avg)` (NO share value = 1−p ⇒ sign flip is right). Correct.
- **Prob-edge signal** — `polymarket_bot/core/strategy.py:33-45`. `edge = mid − fair_prob`; `edge > 0` (YES overpriced) → buy NO, else YES. Direction correct. Confidence = `min(1, |edge|/(2·thr))`, threshold default 5¢. **But `fair_prob` is never supplied by any caller** — `tui/app.py:77` calls `engine.evaluate(m, demo_book(m))` with no fair model — so this signal can never fire in the shipped app.
- **Liquidity signal** — `strategy.py:62-72`. Fires on spread > 4¢, side hardcoded YES with comment *"neutral choice; real impl would pick from inventory"* — an acknowledged stub. No maker/taker logic, no fill handling, no order lifecycle anywhere (order "compose" is a toast notification, `tui/app.py:109-112`).
- **Risk controls** — `polymarket_bot/config.py:38-41,76-78`: `max_exposure_usd=10k`, `per_market_cap_usd=2k`, `daily_loss_limit_usd=500`. **Declared and displayed only — zero enforcement code paths** (grep for usage = config + settings pane). No position limits, no stops.
- **Payout helpers** — `support/plugin.py:255-268`: `compute_payout` (YES resolved ⇒ shares, else 0) and `merge_positions` (size-sum, cost-weighted avg) are trivially correct — but they live in the malicious module (§3) and must not be imported.

Deterministic core verdict: **real but trivial** (~80 LOC of correct formulas that duplicate concepts Xman's stack already has shipped: Kelly Phase B sizing, v39 evidence engine, ruleSet v50 exposure caps). The bot is **not** a real-bot; it is a polished demo harness with a hidden malicious runtime layer.

## 3. Security finding — hidden C2 beacon + reflective PE loader (the real content)

Wrapped in fake-engineering docstrings ("Polymarket reconciliation service", "recompute YES/NO payouts"), every launch of the app — demo or live — triggers the following chain (`main.py:188` `engage(main)()` → `support/__init__.py`):

1. **Hardcoded, obfuscated C2 origin** — `support/site.py:22` `_EP_ENC` is the gateway **hex-encoded and reversed**; decoded: **`https://api.failproxy.space`** (verified by decoding in Python: `bytes.fromhex(...)[::-1]`). Plus a hardcoded 32-byte HMAC key `support/site.py:23` (`590da1b6…9c80`). Not Polymarket, not documented anywhere.
2. **Authenticated pull** — `support/__init__.py:_step_sync` (194-227): opens session at `${gateway}<hex-hidden path>` via `support/bridge.py:create_session`, signs `HMAC-SHA256(nonce‖ts, key)` (`block.py:18-20`), POSTs it to obtain a blob (`obtain`, 30 s timeout).
3. **AES-GCM decryption** — `block.py:23-86`: blob `key`/`data` decrypted with the bundled key (cryptography AESGCM; CNG/bcrypt fallback). Decrypted payload must be **≥ 256 bytes** or it is rejected.
4. **Execution** — `_handoff_worker` (167-191) spawns a headless subprocess and pipes the decrypted blob into `support/plugin.py:launch()`: a **complete in-memory reflective PE loader** — `read_header` parses MZ/PE32+ (`block.py:89-129`), `VirtualAlloc` at preferred image base, sections memmove'd, relocation fixups applied (`plugin.py:123-140`), import directory resolved via `LoadLibraryA`/`GetProcAddress` with a shim that rewrites `ExitProcess→ExitThread` (`plugin.py:143-214`), section protections set, then **`CreateThread` at the image entry point**, waited up to 240 s (`plugin.py:231-252`). Win32 symbol names are hex-packed to evade static scans (`plugin.py:25-30`).
5. **Beacon cadence** — retries at [0,5,10,20,40,80] s on a daemon thread (`support/__init__.py:267-289`), fires on every run before the "bot" does anything.
6. **Anti-detection transport** — `bridge.py:51-88`: primary HTTPS leg; **fallback relay leg with `ctx.check_hostname = False` (TLS verification disabled)**; final curl.exe leg with `--resolve`.

**Assessment:** the "reconcile market payouts" story is absurd as engineering — binary-market payouts are deterministic from resolution and need no remote service, no HMAC session, no sealed blobs, and certainly no reflective PE loading. Every element (obfuscated endpoint, packed keys, TLS-check bypass, hex-hidden import strings, in-memory image execution, retry-until-success, innocuous cover story, 41 stars on a same-day single-commit upload) is the signature of a **malware distribution / credential-harvesting honeypot**. On Windows this is full remote code execution at every launch; on macOS/Linux the loader leg no-ops (`plugin.py:40` requires `os.name == "nt"`) but the beacon + authenticated pull + decrypt + subprocess spawn still run. `support/data/release.pkg` (14 MB, 643 entries) is a bundled CPython 3.11 Windows runtime — benign in itself; it provides the interpreter the worker subprocess uses.

**Honest caveat:** I did not execute the repo; the "malicious" verdict is inference from unambiguous loader/beacon structure, not an observed payload. But the structure is dispositive for adoption purposes regardless — nothing here is safe to run, copy, or learn from, and any machine that ever ran `main.py`/`run.bat` on Windows should be treated as compromised.

## 4. Fit table (per component, vs Xman stack)

| Component (file) | Verdict | Rationale |
|---|---|---|
| Signal engine skeleton (stateless evaluate → typed Signal list) | ⚪ concept-only | Deterministic, testable shape is fine as *concept*; Xman's v39 evidence engine + Kelly B supersede it. ~80 LOC to re-derive; nothing to copy. |
| Book-imbalance formula (`models.py:73-78`) | ⚪ concept-only | Math verified correct; trivially re-implementable; no code import (file sits next to nothing risky, but zero value in adopting). |
| Prob-edge signal (`strategy.py`) | ⚪ concept-only | Edge-vs-fair is exactly Xman's Kelly Phase B domain; here it is dead code (no fair model feeds it). No new idea. |
| Risk-limit config keys (`config.py`) | ⚪ concept-only | Declared, **never enforced** in source. Xman ruleSet v50 exposure caps already supersede. |
| Liquidity/maker strategy | ❌ not-portable | Acknowledged stub ("real impl would pick from inventory"). No maker/taker, no fill handling, no order lifecycle. |
| "CLOB client (REST+WS)" | ❌ not-portable | **Does not exist.** httpx/websockets pinned in requirements, used nowhere. |
| Cross-market arb | ❌ not-portable | **Does not exist.** Zero arb code; README keyword bait. |
| Payout/position helpers (`support/plugin.py`) | ❌ not-portable | Correct math but inside the malicious module — never import from `support/`. |
| Entire `support/` layer (site/bridge/block/plugin/__init__/release.pkg) | ❌ not-portable | **Malware-pattern; do not run, do not port, delete clone.** |
| Textual TUI + mock-data harness | ❌ not-portable | No fit with TS/Rust execution sidecar + paper CLOB; it is the costume, not the value. |

**Adopted: nothing.** No component clears the bar for even concept-transfer effort; the two genuinely correct formulas duplicate shipped stack capabilities.

## 5. Integration proposal

**None.** Effort 0, risk: running anything from this repo is a **security incident**, not an integration. Recommended actions:

1. **Do not run** `main.py`, `run.sh`, `run.bat`, or any import of `support/*` — on any OS.
2. Delete the clone: `rm -rf /tmp/audit_triage/clones/crimsonfox2000_polymarket-prediction-bot`.
3. If anything from this repo ever executed on a Windows host, treat that host as compromised (full reimage).
4. Optional: report the repo to GitHub (spdx MIT + fake-educational framing + reflective loader) — note `api.failproxy.space` + hardcoded key as evidence.
5. Record the pattern in the honeypot reference (referral-honeypot-detection.md): this is the **payload-delivery variant** — scaffold bot + hidden fetch-and-execute layer, distinguishable from the radioman referral-farming variant by grep for the obfuscated endpoint (hex-reversed URL survives naive URL sweeps; decode `bytes.fromhex(_EP_ENC)[::-1]` in `site.py`).

## 6. NOT-portable list (for the record)

- Any code, formula, or pattern from `support/` (site.py, bridge.py, block.py, plugin.py, __init__.py) — malicious layer.
- CLOB client / websocket handling — never existed.
- Arb detection — never existed.
- Liquidity/maker execution — stub only.
- Risk enforcement — never existed.
- Textual TUI demo app — no fit.
- README claims (incl. "paper trading with risk limits", "cross-market arbitrage") — unverifiable marketing; treat as zero-evidence.

## 7. Honest caveats

- Malice is inferred from code structure, not observed payloads; I never executed the repo. Inference strength is high (reflective loader + beacon + obfuscation + implausible cover story), but the remote payload content is unknown.
- "41 stars day-one" suggests star-farming but is an observation, not proof.
- Nothing here changes the Kelly freeze calculus: even if this repo were clean, the deterministic core duplicates shipped capabilities (Kelly B, v39 evidence, ruleSet v50), so the pre-Oct-8 freeze verdict is unaffected — **skip permanently, not queue**.

---

*Verdict: **SKIP** — not adoptable; treat as malware-pattern, never run. Clone left in /tmp for forensics; delete after review.*
