# Asset audit — `semrincaballero/Polymarket-Prediction-Bot`

**Verdict: ⛔ DROP — not a trading bot. Malicious software (in-memory PE loader / dropper). Do not run, do not clone, do not vendor. Nothing to reuse.**

Audited 2026-10-16 · ★149 · forks 26 · MIT · created 2026-10-12 · last push 2026-10-16 13:07Z · 205 commits in 4 days · read-only inspection via GitHub API (never cloned, never executed)

---

## What it is

A repo published as a "Polymarket trading bot — CLOB order book, edge detection and arbitrage
signals in your terminal," MIT-licensed, keyword-stuffed with 15 topics (`defi-arb-bot`,
`autotrader-polymarket`, `btc-updown`, `copy-trade`, `5min`/`15min` …) and a 1,000-word SEO README.
Roughly one third of the repo is a genuine, if trivial, decoy: a ~74 KB Python package
(`polymarket_bot/`) containing a Textual TUI, a 78-line strategy stub and a mock-data generator.

The other two thirds is a **loader**. `support/` (~60 KB of Python plus a 13.97 MB binary blob) is
described in its docstrings as "reconciliation" and "resolution-worker" plumbing, and reads like
plausible exchange integration — that register is the attack, because the code underneath is a
textbook remote in-memory native-code loader pointed at a look-alike C2 domain.

The delivery story in the README is self-consistent and reassuring ("Paper-trade by default",
"Keys local only, mode 0600, never logged"). Both claims are false for anything outside the decoy
package: the loader never touches a key because it does not need one — it fetches and executes
native code.

## The chain, as read in source

Entry: `run.bat` / `run.sh` / `main.py` / `python -m polymarket_bot`. `main.py:183` and
`polymarket_bot/__main__.py:12` both `from support import engage`; `engage()` is a decorator
(`support/__init__.py:292`) that fires a background `_sync_loop()` on the host's **first** decorated
call. Running the bot in `--demo` mode triggers it — there is no opt-in and no flag that avoids it.

1. **`support/__init__.py` — `_setup_runtime()`**: extracts the bundled `support/data/release.pkg`
   zip into `.data/` and executes the dropped `python.exe`. The blob's central directory shows it is
   a real python-build-standalone-shaped distribution (`Lib/site-packages/pip-26.1.2.dist-info/…`,
   `libcrypto-3.dll`, `build=dfde71fb…`), i.e. an **unsigned portable Python runtime dropped from an
   opaque blob in the repo and run**. `run.bat`/`run.sh` do the same with `tar`/`powershell`/`unzip`.
2. **`support/bridge.py` — the transport.** `support/site.py:gateway()` returns the byte-reversed,
   hex-packed constant `_EP_ENC` → **`https://api.failproxy.space`** (a look-alike of a plausible
   vendor host; real Polymarket origins are `clob.`/`gamma-api.`/`data-api.polymarket.com`). Requests
   go to `/api/v1/auth/session` then `/api/v1/data/sync` (both hex-packed to keep the strings out of
   plain source). When DNS does not resolve the origin, `_find_route()` **fails over to two hardcoded
   relay IPs** — `104.21.0.1`, `172.67.0.1`, stored as ASCII-code arrays — and on that path
   `ctx.check_hostname = False` with **`ssl.CERT_NONE`**: TLS verification is switched off while the
   real `Host` header is still sent. `_curl_leg()` repeats the same pinning via
   `curl.exe --resolve`. Hardcoded fallback IPs plus disabled certificate validation is C2
   resilience, not exchange integration.
3. **`support/block.py` — the decryptor.** `unprotect(blob["key"], blob["data"])` AES-GCM-decrypts a
   blob **supplied by the server** (the key arrives in the response body; a 32-byte AES-256
   constant embedded in `site.py:_SK_HEX` HMAC-signs the request via `auth_token`). A native
   Bcrypt/CNG fallback exists for when `cryptography` is absent.
4. **`support/plugin.py` — the loader.** `read_header()` parses an MZ/PE32+ container out of the
   decrypted bytes and walks its sections, import directory and relocations. `_launch_image()` then
   `VirtualAlloc`s memory, `memmove`s the segments in, applies base relocations, resolves imports
   against `kernel32` via `GetProcAddress`, and calls the entry point on a thread. Kernel32 names are
   hex-packed (`_K32`, `_GPA`, `_THEX`) so the literals never appear in source — and three
   termination imports are deliberately remapped: `ExitProcess` / `TerminateProcess` /
   `NtTerminateProcess` → `ExitThread`, documented in the docstring as *"so a returning worker exits
   its thread rather than tearing down the bot."* That is payload containment for the host process.
5. **`support/__init__.py:217` → `_handoff_worker()`** executes the loader in a **child
   interpreter** (`from support.plugin import launch; launch(d)`), isolating a payload crash from the
   bot.
6. **`support/siglog.py`** — every stage in the chain above calls `_j.append(...)`, and `append()`
   is a **no-op that returns None**. The extensive instrumentation is dead code in the shipped build:
   the audit trail is decorative. It exists so that a reader skimming the source sees a
   well-instrumented, transparent system.

Net: **run the "bot" → fetch from an unverified-TLS look-alike host → AES-decrypt a server-supplied
blob → map and execute it as native code in memory inside a child process, with anti-teardown
imports remapped and no file ever written to disk.** That is a loader. The 64-bit Windows gate
(`os.name == "nt"` and `calcsize("P") == 8` in `plugin.py`; `_should_relaunch()` in `__init__.py`)
means macOS is not the target — but "inert on this host" is not a reason to keep it, and the
`run.sh` path still extracts and executes the bundled runtime on Linux/macOS.

## Anatomy facts that drove the verdict

- **Claim vs code**: README promises "edge detection, liquidity provision and cross-market
  arbitrage"; `polymarket_bot/core/strategy.py` is 78 lines of textbook stubs — `min(1.0, abs(edge)/(thr*2))` confidence, a `book.imbalance` skew, a spread threshold, and the author's own comment
  `# neutral choice; real impl would pick from inventory`. Markets and books in `--demo` come from
  `core/mock_data.py`. There is no CLOB client, no order path, no risk engine.
- **Size inversion**: 13.97 MB of the 13.96 MB repo (as measured by GitHub) is the single
  `support/data/release.pkg`; all Python totals ~74 KB and the "bot" is ~28 KB of it.
- **205 commits in 4 days**, every ~27 minutes, all by `Lucas <username@users.noreply.github.com>`
  with the single message pattern `Auto commit: <timestamp>` — an activity pump, not development.
- **Star/fork farming**: created 2026-10-12, ★149 and 26 forks by 2026-10-16. Ten forks were created
  inside a **77-minute window** on 2026-10-14 by accounts with auto-generated handles
  (`douadmia2002`, `ronremandilidia47`, `karenhillu83`, `gorklu1984`, …) — secondary distribution.
  Open issues 0, subscribers 0.
- **No tests, no CI, no `docker`, no `.env.example`.** `requirements.txt` is an ordinary harmless
  list (`textual`, `rich`, `httpx`, `websockets`, `pydantic`, `numpy` …) — the dependencies are
  decoy-consistent; the payload does not come from PyPI.
- **Repo hygiene**: 28 committed `__pycache__/*.pyc` files including compiled copies of the module
  that the `.py` files shadow — consistent with an auto-commit dumper, but also worth noting: the
  `.pyc` blobs are a second, easily-overlooked delivery surface if any of them ever diverges from
  its source.
- **MIT licence is not a safety signal.** `LICENSE` is a stock MIT text, authored "2026 Polymarket
  Prediction Bot contributors". A permissive licence on a dropper grants *permission*, not
  *safety* — it is exactly what let it clear the radar's admission bar.

## Why it cleared our radar (the part worth our attention)

The research agent's candidate bar is *licence ≠ none, ★≥5, pushed ≤90d, not already seen*. This
repo passes all four **because each signal is manufactured**: the MIT text is the licence, the stars
and forks are farmed, and the ≤90-day push date is a 27-minute cron. It is also aimed squarely at
this stack's domain, so it will keep appearing in the GitHub radar block until something denylists
it. That is a process finding, not just a repo finding — see the recommendation below.

## What we could reuse

**Nothing.** The only nominally transferable artefact is the decoy `strategy.py` signal set
(probability-edge at 5¢ vs a supplied `fair_prob`, book-imbalance at 0.30 skew, resting-limit
liquidity at a 4¢ spread) — three constants and a `min(1.0, …)` confidence ramp. We already hold
strictly stronger versions of all three (Kelly-sized edge vs the executable quote, the C-200 band
policy, the Rust sidecar's book handling), and this version's `fair_prob` is an input it never
computes. Adopting even a threshold from it would be a downgrade. There is no maths to verify and no
test suite to run — the reference implementation of everything this repo claims is in our own tree.

## Cost / risk

- **Cost if adopted: not applicable.** No configuration makes this safe; the loader is wired into
  every entrypoint and fires on first call.
- **Risk if run once, on Windows**: arbitrary remote code execution in the user's session, with TLS
  verification disabled on the delivery path and the payload never touching disk; on this robot's
  hosts it additionally means an unsigned 14 MB portable Python extracted and executed from an
  unwatched `.data/` directory. Nothing about the C2 domain, the relays, the payload contents, or its
  post-exploitation behaviour can be characterised without executing it, which is not done here.
- **Risk of the repo continuing to surface**: re-enqueuement in the radar / research-agent pipeline,
  and the reputational hazard of a farmed, MIT-licensed, Polymarket-branded dropper circulating in a
  domain this project monitors.

## Recommendation

**Drop, permanently.** No fit row, no roadmap card, no adoption of any component at any effort
level; nothing here maps to an open `data/roadmap.json` card, and the queue's `dropped` state is the
right terminal one. Recorded in `data/research-asset-queue.json` as `drop` with this report.

**Follow-up flagged for the daily/weekly brief (not an approval ask, and not applied here):**

1. Treat the repo and its owner as a **denylist entry** for the radar/asset pipeline so it cannot be
   re-seeded by the licence/star/push bar that it games. The queue's dedupe against already-read
   repos should now cover it, but the bar itself is the vulnerability.
2. If any host in the fleet has ever run a downloaded copy of this repo, treat it as **compromised**:
   the delivery domain (`api.failproxy.space`), the two relay IPs (`104.21.0.1`, `172.67.0.1`) and
   the look-alike-name pattern are worth a block rule at the gateway and an egress review. No host
   under this project's control pulled it in — the radar only ever fetched metadata via the API.
3. Cheap process hardening worth a card: the radar's admission bar currently counts a star count as
   a quality signal, which is exactly what a fork/star farm manufactures. Adding a
   *stars-vs-repo-age* and *commit-message-entropy* check (205 identical commits in 4 days is a
   one-line heuristic) would have caught this before it took an audit slot.

**No roadmap or registry write was made for this entry** (per the audit worker's constraint). If the
denylist or radar-bar item in (1)/(3) is wanted, it needs a card — deliberately left to the user.

---

## Ready-to-paste registry / card blocks (not applied — constraint: audit doc + queue only)

```json
{"id": "radar-denylist-malicious-repos", "title": "Radar admission bar: reject manufactured-signal repos + denylist", "column": "backlog", "effort": "S", "gate": "none — read-only filter change, revert = remove check", "note": "AUDIT INPUT (2026-10-16, drop; drafts/asset-audit-polymarket-prediction-bot-20261016.md): semrincaballero/Polymarket-Prediction-Bot cleared the candidate bar (MIT/★149/pushed today/not seen) because all four signals are manufactured — stock MIT text, farmed stars+forks (10 forks in 77 min by auto-handle accounts), 205 'Auto commit: <ts>' commits in 4 days. Repo is a dropper: support/ fetches https://api.failproxy.space over CERT_NONE TLS with two hardcoded Cloudflare relay IPs (104.21.0.1, 172.67.0.1), AES-GCM-decrypts a server-supplied blob, and maps/executes it as native PE in memory via VirtualAlloc+GetProcAddress+CreateThread with ExitProcess/TerminateProcess/NtTerminateProcess remapped to ExitThread; the diagnostics module that logs every stage is a no-op. Proposed: add stars-vs-repo-age and commit-message-entropy checks to the radar admission bar, and denylist this repo/owner so it cannot be re-seeded.", "tags": ["radar", "security", "process"]}
```

```text
AUDIT INPUT (2026-10-16, drop; drafts/asset-audit-polymarket-prediction-bot-20261016.md):
semrincaballero/Polymarket-Prediction-Bot — MALICIOUS, not a trading bot. In-memory PE
loader wired into every entrypoint via support.engage(). No reuse at any level. See card
above for the radar-bar / denylist follow-up.
```
