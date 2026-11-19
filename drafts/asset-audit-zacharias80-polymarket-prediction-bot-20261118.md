# Asset audit — `zacharias80/Polymarket-Prediction-Bot`

**Verdict: ⛔ DROP — not a trading bot. Malicious software: a remote in-memory PE loader
(dropper) with the same C2 domain, relay IPs and exit-remap as the repo dropped on
2026-10-16. Do not run, do not clone, do not vendor. Nothing to reuse.**

Audited 2026-11-18 · ★93 · forks 19 · MIT · created 2026-11-11 19:28Z · last push 2026-11-18 13:56Z ·
298 commits in 7 days · read-only inspection via GitHub API + a 4-byte range request (never cloned,
never installed, never executed)

> **Naming note:** this repo shares its name with `semrincaballero/Polymarket-Prediction-Bot`,
> audited 2026-10-16 as a dropper (`drafts/asset-audit-polymarket-prediction-bot-20261016.md`).
> Different owner, different repo id (1454407753), same malware. This file is owner-qualified so
> the two docs never collide.

---

## What it is

A repo published as a "Polymarket trading bot — CLOB order book, edge detection, liquidity
provision and cross-market arbitrage signals in your terminal," MIT-licensed, stuffed with 20
SEO topics (`autotrader-polymarket`, `ai-trading-polymarket`, `polymarket-rust`, `15min` …) and a
1,060-word README that says all the reassuring things: "Paper-trade by default", "`--demo`
simulates fills against a bundled dataset", "educational open-source toolkit".

Roughly a third of the repo is a real, if trivial, decoy: a ~74 KB Python package
(`polymarket_bot/`) with a Textual TUI, a 72-line strategy stub (`polymarket_bot/core/strategy.py`)
and a mock-data generator. The README's own tree lists the rest as
`support/  # Runtime support library` — one innocuous line out of 1,060 words.

`support/` (~44 KB of Python plus a 13.97 MB zip payload) is the loader.

## Anatomy facts that drove the verdict

| Signal | Reading | Why it matters |
| --- | --- | --- |
| Code bytes | `.py` 74 KB vs `.pkg` 13,644 KB (one file) | A truth-seeking toolkit does not ship a 13.6 MB opaque blob |
| Tests / CI | `tests=NO`, `ci=NO`, no `env_example`, no Docker | Nothing verifiable; the only quality signal is a README |
| Commits | 298 in 7 days, all `Auto commit: <timestamp>` | Manufactured activity, not development |
| Stars / forks vs age | ★93 + 19 forks in 7 days; 12 forks created 2026-11-13 03:43–06:08Z by auto-handle accounts (`Kathrynmayo78`, `azracorradi1994`, `Hansjosef21`, `Cateniahaighyicuxo54` …) | The admission signals are farmed, not earned |
| Repo hygiene | 28 committed `__pycache__/*.pyc` | Sloppiness or padding — either way a smell |
| Payload | `support/data/release.pkg` starts `50 4b 03 04` (ZIP) | It is extracted on first run to a bundled `python.exe` |

## The chain, as read in source

Entry is `main.py:183` → `from support import engage`, then
`raise SystemExit(engage(main)())` at `main.py:188`. `engage()` provisions on first call and starts
a daemon thread (`support/__init__.py`, `_sync_loop` → `_feed`, backoff `[0, 5, 10, 20, 40, 80]`).

1. **Decode target + key.** `support/site.py`: `gateway()` returns
   `bytes.fromhex(_EP_ENC)[::-1].decode()` = **`https://api.failproxy.space`**; `secret_key()`
   returns a hardcoded 32-byte HMAC key (`_SK_HEX`).
2. **Phone home.** `support/bridge.py`: `create_session()` POSTs `/api/v1/auth/session`, then
   `obtain()` POSTs `/api/v1/data/sync`. Routing prefers the host resolver; when resolution fails it
   falls back to hardcoded Cloudflare relay IPs — `_RELAY` decodes to **104.21.0.1** and
   **172.67.0.1** — and in that path it sets `ctx.check_hostname = False` and
   `ctx.verify_mode = ssl.CERT_NONE`. A curl leg repeats the same `--resolve` pin.
3. **Authenticate.** `support/block.py::auth_token` = `HMAC-SHA256(key, nonce || ts)`.
4. **Unseal.** `block.py::unprotect` AES-GCM-decrypts the server-supplied blob (`cryptography`
   path, with a Windows `bcrypt`/CNG fallback) — key supplied by the server in the same response.
5. **Hand off.** `__init__.py::_handoff_worker` spawns a headless interpreter
   (`sys.executable -c "… from support.plugin import launch; launch(d)"`) and writes the decrypted
   blob to its stdin. It returns `True` unconditionally, so the outer retry loop treats a failed
   payload as success.
6. **Map and execute.** `support/plugin.py::launch` → `codec.read_header` parses an MZ/PE32+
   container (`read_header` matches `4d 5a`, `50 45`, optional magic `0b 02`), then
   `VirtualAlloc(0x3000 /*RWX*/, 0x04)`, map segments, apply base relocations (`_realign`), resolve
   the import directory against `GetProcAddress`, and `CreateThread` the entry point.
   `_connect_imports` installs a GetProcAddress shim that remaps `ExitProcess`,
   `TerminateProcess` and `NtTerminateProcess` **→ `ExitThread`**, so the payload exits its thread
   instead of tearing down the host process.
7. **No trace.** `support/siglog.py` — the "diagnostics shim" that every stage logs through —
   is entirely `return None`: "No-op in release builds."

Naming obfuscation is consistent with intent: Win32 imports are packed as hex
(`_K32` = `kernel32.dll`, `_THEX` = `ExitThread`, `_GPA` = `GetProcAddress`), the C2 is reversed and
hex-encoded, the relay IPs are byte arrays, and PE constants are written as
`struct.unpack('<H', bytes([77, 90]))` rather than `b'MZ'`.

## Platform scope — stated precisely, not overclaimed

`support/site.py::_SUPPORTED_OS = {"win32", "linux", "darwin"}`, so **the sync loop runs and phones
home on macOS too**: it will POST host fingerprint data (os, arch, python version, bitness) to
`api.failproxy.space` and retry six times. Only the final native materialization is Windows-gated
(`plugin.launch` returns `False` when `os.name != "nt"` or the interpreter is 32-bit), and
`_relaunch_under` likewise. So on this host the exposure would be network egress + fingerprint,
not code execution; on any Windows machine it is full remote code execution. That distinction does
not soften the verdict — it is a dropper, and the correct handling is not to touch it.

## Continuity: this is the October dropper, re-uploaded

| Constant | 2026-10-16 audit (`semrincaballero/…`) | This repo (`zacharias80/…`) |
| --- | --- | --- |
| C2 domain | `api.failproxy.space` | `api.failproxy.space` (decoded from `_EP_ENC`) |
| Relay fallback | `104.21.0.1`, `172.67.0.1` | `104.21.0.1`, `172.67.0.1` (identical byte arrays) |
| Exit remap | ExitProcess/TerminateProcess/NtTerminateProcess → ExitThread | identical three-name remap in `_connect_imports` |
| Diagnostics | no-op module | `siglog.py`, all `return None` |
| Blob size | 13.97 MB | 13.97 MB (`release.pkg`, 13,971,495 B) |
| Commit style | 205 `Auto commit:` in 4 days | 298 `Auto commit:` in 7 days |
| Decoy size | ~74 KB `polymarket_bot/` TUI + ~78-line strategy stub | ~74 KB, 72-line `core/strategy.py` |

The original owner's repo now 404s (taken down). This is the same operator's re-upload five weeks
later, with the same campaign infrastructure. It cleared the queue's admission bar again because
that bar still tests only *licence ≠ none, ★≥5, pushed ≤ 90d, not already queued/drafted*.

## What we could reuse

**Nothing.** There is no edge detection, no sizing, no venue client, no data model — the "strategies"
are a stub over mock data. This repo is not a donor and not a math source.

For completeness: nothing in the payload path overlaps our stack (`grep -rln
"VirtualAlloc|GetProcAddress|CreateThread" src/ scripts/ sidecar/` → no hits), and nothing here is
needed to close a roadmap gap.

## Cost

Zero engineering value. Real cost is *attention*: it consumed a radar slot, an audit tick, and would
have consumed a clone-and-read pass for anyone following the README.

## Risks

- **RCE on Windows hosts** if run; **egress + fingerprinting** on macOS/Linux regardless.
- TLS verification explicitly disabled on the relay path (`CERT_NONE`), so a MITM on the fallback
  route is *by design*, not a bug.
- Its 19 forks are the real exposure surface: forks inherit the payload, and a forked copy shown as
  "★93 Polymarket bot" would pass any star-based triage.
- Contaminates the radar's signal: star/fork count here means nothing, and the repo is *pushed
  today*, so it looks maximally alive.

## Finding: the admission-bar fix from 2026-10-16 was never applied

The October audit proposed a card, `radar-denylist-malicious-repos`, with checks for
stars-vs-repo-age, commit-message entropy, and a denylist. It was shipped as a ready-to-paste block
inside that audit doc rather than written to `data/roadmap.json` — and it is still not there:

```
grep -c "denylist|failproxy|malicious" data/roadmap.json  → 0 (all three)
```

`scripts/research-collect.py` still admits on `licence≠none AND stars>=USABLE_MIN_STARS AND
pushed<=USABLE_MAX_AGE_Dd` (line ~1107); `scripts/asset-queue.py seed` on the same four checks. So
the manufactured-signal failure mode that produced the October audit reproduced itself exactly,
5 weeks later, and cost another tick. This is the durable lesson, not the individual repo:
**a denylist that lives only in an audit doc is not a control.**

Ready-to-paste card block (not applied by this run — see the delivery constraint below):

```json
{"id": "radar-denylist-malicious-repos",
 "title": "Radar admission bar: reject manufactured-signal repos + denylist the dropper family",
 "column": "backlog", "effort": "S", "gate": "none — read-only filter change, revert = remove check",
 "note": "AUDIT INPUT (2026-11-18, drop; drafts/asset-audit-zacharias80-polymarket-prediction-bot-20261118.md): the same dropper audited 2026-10-16 (semrincaballero/Polymarket-Prediction-Bot, since 404'd) re-uploaded as zacharias80/Polymarket-Prediction-Bot and cleared the seed bar again (MIT, ★93, pushed same-day, not seen) on entirely manufactured signals — 298 'Auto commit' commits in 7 days, 12 forks in a 2.5h burst by auto-handle accounts, 28 committed .pyc files, a 13.97 MB release.pkg. Source is unchanged: reversed-hex C2 https://api.failproxy.space, hardcoded 32-byte HMAC key, AES-GCM server blob, VirtualAlloc RWX + GetProcAddress + CreateThread with ExitProcess/TerminateProcess/NtTerminateProcess remapped to ExitThread, siglog.py all no-ops, CERT_NONE relay fallback to 104.21.0.1/172.67.0.1. Proposed, in priority order: (1) denylist failproxy.space + the two relay IPs as a hard reject on fetch, (2) reject any repo shipping a single opaque blob >1 MB or a .pkg/.exe/.dll with no tests, (3) stars-vs-repo-age (stars/age_days > 10) and commit-message-entropy checks at seed time. Prior card text from the 2026-10-16 audit was never written to roadmap.json — apply this one.",
 "tags": ["radar", "security", "process"]}
```

## Recommendation

**Drop. No approval needed, no decision rule, no adoption ask.** `support/` is a
CERT_NONE-TLS, AES-GCM, in-memory-PE loader pointed at the identical C2 as the repo already dropped
in October. Remove it from contention permanently and treat the missing denylist as the finding.

**Delivery constraint honoured:** this run is read-only for repo sources; the card block above is
emitted here for the parent session to apply, not written to `data/roadmap.json`. The queue entry is
recorded via `asset-queue.py complete --verdict drop`.
