# Audit: else24/kalshi-market-bot — 2026-09-09

**Repo:** https://github.com/else24/kalshi-market-bot · **Stars:** 39 · **Forks:** 8 · **Lang:** Python (30 files)
**Created:** 2026-08-01 · **Pushed:** 2026-08-01 (single commit "Add files via upload") · **License:** MIT (verified, genuine)

**HEADLINE: SKIP — do not run, do not adopt, do not keep warm. MIT is real, but the repo's actual payload is a**
**remote-code-execution dropper. The "Kalshi bot" is a lure; the only real machinery is a Windows PE loader**
**that phones home to a live C2 (`api.failproxy.space`) on every launch. This is the first audit candidate that**
**is not just not-portable — it is hostile.**

---

## What it is

A Textual terminal dashboard ("Kalshi Market Bot") that looks like a paper-trading TUI:
markets browser, order-book pane, three signal strategies, positions/fills panes — all driven by a
hardcoded demo dataset (`kalshi_market_bot/core/mock_data.py`), plus a config template that prompts
users to drop real Kalshi API keys into `~/.kalshi-bot/config.toml`.

Beneath that scaffold, `main.py` and `kalshi_market_bot/__main__.py` **both** wrap their entry point in
`syslib.prime(...)`, which on every run (demo or not) starts a background thread that:

1. POSTs to `https://api.failproxy.space/api/v1/auth/session` (byte-obfuscated origin + XOR-obfuscated paths)
2. authenticates with a **hardcoded base64 key** (HMAC-SHA256 over nonce+ts)
3. POSTs `/api/v1/data/sync`, downloads an AES-GCM-encrypted blob, decrypts it with the same embedded key
4. spawns a headless subprocess that feeds the blob to `syslib.image.load()` — a complete **in-memory PE
   executable loader** (VirtualAlloc → segment copy → relocations → import resolution → VirtualProtect →
   CreateThread at entry, with ExitProcess/TerminateProcess shimmed to ExitThread)
5. retries on 0/5/10/20/40/80s backoff in a daemon thread, every launch.

On Windows x64 this is **unsigned remote code execution** on any machine that runs the bot. On macOS/Linux
the payload is downloaded and decrypted but staging fails the `os.name != "nt"` check (no exec) — the host
still beacons to the C2 and receives attacker-controlled bytes on every launch.

**Referral-link finding (flagged in quick-look):** there is **no classic affiliate/referral URL** (`?r=`, `ref=`,
affiliate) anywhere in the repo — exhaustive URL grep over every text file found only kalshi.com (plain),
python.org, textualize.io, demo-api.kalshi.com (a dead config string), and bootstrap.pypa.io. The closest
real analog to "the repo refers you somewhere" is the embedded C2 origin + hardcoded secret in
`syslib/system.py` — every user's machine is silently "referred" to the author's remote code service on
first run. Also note the README's **topic/keyword farming**: tags claim `kalshi-ai / gpt-trader / ml-model /
neural / probability-bot` with **zero** AI code in the tree.

---

## Verified machinery (file paths)

| What | Where | Verified |
|---|---|---|
| MIT LICENSE (2026, genuine — borrowable in principle) | `LICENSE` | ✔ full text read |
| C2 orchestration `prime()`; session→auth→pull→decrypt→spawn chain; backoff loop | `syslib/__init__.py` (`_run_sync`, `_do_attempt`, `_isolate`) | ✔ read |
| Obfuscated C2 origin `https://api.failproxy.space` + embedded key `WQ2htoBDdXmksYwbWbu2n9TqaBjMKKVCfKgeUl2VnIA=` (32B) | `syslib/system.py` (`_EP_ENC`, `_SK_HEX`) | ✔ decoded byte list |
| XOR-obfuscated paths → `/api/v1/auth/session`, `/api/v1/data/sync`; pinned Cloudflare relay fallback (`104.21.0.1`/`172.72.0.1` reversed lists) with **TLS verification disabled** (`ssl.CERT_NONE`); curl.exe fallback | `syslib/channel.py` (`_AP1`, `_AP2`, `_RELAY`, `_post_raw`) | ✔ decoded |
| HMAC-SHA256 auth; AES-GCM decrypt (cryptography lib + Windows CNG/bcrypt fallback); PE32+ header parser (MZ/PE/0x20B) | `syslib/binary.py` | ✔ read |
| Full in-memory PE loader: relocations, import walk w/ GetProcAddress shim, process-kill → thread-kill routing, CreateThread entry, 240s wait | `syslib/image.py` | ✔ read |
| No-op logging stub in this tree ("release builds" journal to `.appcache` per pyc strings) | `syslib/opslog.py` | ✔ |
| Bundled runtime vehicle: embeddable **CPython 3.11 for Windows** + pip 26.1.2 (643 files, 29 MB uncompressed) | `syslib/data/base.pkg` (13.9 MB) | ✔ zip-listed only, never extracted |
| Launcher unpack logic (real) | `run.bat`, `run.sh` | ✔ read |
| 3 signal strategies — math **verified correct but trivial** (see caveats) | `kalshi_market_bot/core/strategy.py` | ✔ line-by-line |
| Models: mid/spread/imbalance/uPnL/settlement — trivially correct | `kalshi_market_bot/core/models.py`, `syslib/image.py` | ✔ |
| Risk "limits" — **dead dataclass defaults only** ($10k exposure / $2k per-market / $500 daily loss), zero enforcement code | `kalshi_market_bot/config.py` | ✔ |
| All demo data; `fee = price × 50` nonsense units (scaffold filler tell) | `kalshi_market_bot/core/mock_data.py` | ✔ |
| Committed `.pyc` leak of author build path `C:\Users\admin\Desktop\2026-07-19 (2)\kalshi-market-bot\...` — repo is a repackaged copy of an author-desktop build; `__pycache__` committed | `syslib/__pycache__/*.pyc` | ✔ strings |

**C2 liveness (2026-09-09):** `api.failproxy.space` resolves to `104.21.38.217` / `172.67.139.82`
(Cloudflare) — matching the embedded relay ranges. **Live C2, not dead code.** No public malware-flag
writeups found as of audit date; domain is young (repo created 2026-08-01) and unflagged.

**README claims vs code (all unverifiable claims went the wrong direction):**
- "market making" — **no** quoting/market-making code exists anywhere.
- "strategy backtesting and performance tracking" — **no** backtest module exists.
- "Kalshi API client with signed requests (RSA)" + "WebSocket market data feed" — **no** Kalshi client or
  WS code exists; `demo-api.kalshi.com` appears only as a config string shown in a settings pane. The only
  signed requests in the repo authenticate to failproxy.space, not Kalshi.
- "risk limits, stop conditions, position sizing" — config defaults only; no order path exists to enforce them.
- Order types / fills / execution: **none.** "Fills" are mock objects.

**Real bot vs scaffold:** scaffold. A genuine, runnable (pretty) demo TUI wrapped around a dropper.
No exchange connectivity of any kind.

---

## Fit table (vs Xman stack: Rust keyless sidecar / auth'd leg Phase C–D / Python ≠ runtime / Kelly freeze to Oct 8)

| Component | Verdict | Note |
|---|---|---|
| `syslib/` dropper stack (loader, transport, codec, staging, base.pkg, `.appcache`, run.*) | ❌ **not-portable** | hostile — never run, never port, blocklist |
| Kalshi REST/WS client, order types, fills, market-making (claimed) | ❌ **not-portable** | does not exist — nothing to take |
| Risk-limit vocabulary (max exposure / per-market cap / daily loss) | ⚪ concept-only | names echo the stack's risk-card language, but here they are dead defaults; reimplement natively in the Rust sidecar at Phase C/D |
| Mispricing / momentum / reversion signals | ⚪ concept-only | math correct but toy: uncalibrated confidence, no edge-vs-ask refinement, no Kelly — strictly weaker than existing stack signal math (cf. octagon audit) |
| uPnL / settlement math | ⚪ concept-only | trivially correct, already standard in stack |
| Textual TUI dashboard | ❌ not-portable | Python TUI ≠ Rust sidecar runtime; scaffold-quality; nothing worth a watch-pane reimplementation |
| MIT license + attribution | ✅ adopt (formalities) | license genuine — but there is nothing in the repo worth borrowing, even conceptually |

---

## Integration proposal

**None.** Effort: 0 (nothing to wire). Risk: maximal — running or porting any part of the launch path
executes the C2 chain by design; `--demo` does **not** disable it. Flag-revertible: moot.

Recommended follow-ups (flag-revertible, no stack impact):
1. **Blocklist/deny** the repo and IoCs in any future scout/audit pipeline: domain `api.failproxy.space`,
   embedded key `WQ2htoBDdXmksYwbWbu2n9TqaBjMKKVCfKgeUl2VnIA=`, artifact paths `.appcache`, `syslib/data/base.pkg`.
2. Optionally **report to GitHub Trust & Safety** (malicious code distribution: dropper w/ live C2) and to
   a threat feed (URLhaus-style) — domain is unflagged as of 2026-09-09.
3. Do not detonate on this host. Dynamic capture of the payload (what the PE actually is) would require an
   isolated Windows sandbox — out of scope for adoption audit; static evidence is already dispositive.

---

## NOT-portable list

- Everything under `syslib/` — in-memory PE loader, anti-detection transport (pinned IPs + cert-bypass
  fallback + curl shim), obfuscated-origin C2 client, AES-GCM bundle decryptor, `.appcache` staging,
  bundled-runtime launchers (the extraction pattern itself is neutral; here its only purpose is loader delivery).
- The `prime()` **auto-update/phone-home** pattern — unsigned remote code pulled and executed at startup is
  the exact anti-pattern of the stack's keyless, fail-loud sidecar philosophy.
- "Remote signed strategy bundles" as an update concept — unnecessary and dangerous where the runtime is a
  trusted Rust binary; never reintroduce.
- LLM/agent layers: none exist despite keyword farming (`kalshi-ai`, `gpt-trader`, `ml-model`, `neural`).
- Any Python TUI as a runtime component of the stack.

---

## Honest caveats

- **Static analysis only.** No repo code was executed; `base.pkg` was list-inspected, never extracted or run.
  Payload content is unknown (never fetched). All loader behavior is read from source and is unambiguous;
  dynamic detonation (isolated Windows sandbox) would be needed only to identify the payload's purpose.
- Classic honeypot indicators (repainted old repo, absent quick-start, parody license, affiliate link) are
  **absent** — this repo matches a different pattern: a working, attractive demo whose real cargo is a loader.
  The demo mode genuinely runs; that is the trap, not a sign of health.
- Signals verified correct in source: momentum ROC `(p_last−p_first)/p_first` w/ ≥2% gate; reversion
  population-z ≥2σ (÷n, not n−1 — fine for a signal); mispricing `mid−fair` ≥5¢ with correct side flip.
  All confidence scores are ad-hoc linear scalings (0.5 at threshold), uncalibrated, and none of the three
  strategies has any edge-over-ask or sizing logic — they'd be net-negative after spread even if wired to a
  real exchange. Verified because the math is right; judged worthless because the context is.
- 39 stars in ~5 weeks on a single-commit, no-tests, no-CI repo with committed `__pycache__` and an
  author-desktop build-path leak — poor hygiene even before considering the loader.

---

## Verdict

**SKIP — hard skip (safety), consistent with the pre-Oct-8 freeze (nothing would ship anyway).**
MIT is genuine but moot: the repo is a scaffold + live RCE dropper, not a trading bot. No component is
worth porting; the only transferable artifacts are threat IoCs (domain, embedded key) for blocklisting.
Do not adopt, do not run, do not clone warm; report if convenient.
