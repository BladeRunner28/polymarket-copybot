# KalshiSharp — Adoption Audit (2026-11-12)

**Repo:** hurley451/KalshiSharp · **Licence:** MIT ✅ · **Verdict:** ❌ **DROP** (no adoption; no recommendation)

Drop is not a quality judgement. The SDK is well built and alive. It is dropped because (a) it is a
C#/.NET client in a Rust + TypeScript + Python stack, (b) it is **auth-first by construction** so it
cannot serve our keyless Kalshi reads, and (c) the Kalshi order-entry surface it exists for was retired
by user decision (`retire-kalshi-copy-routing`, Scheduled). It is also the **third** MIT Kalshi SDK we
have audited — `Reddimus/kalshi-cpp` (`drafts/kalshi-cpp-audit-2026-09-09.md`) and `arshka/pykalshi`
(`drafts/pykalshi-audit.md`) already supply the same contracts, and both were read for exactly this.

---

## 1. Licence — checked first ✅

- `LICENSE` on disk: **MIT**, "Copyright (c) 2026 Matt Hurley". API `license.spdx_id = "MIT"`.
- Grep for directory-scoped carve-outs (`NonCommercial`, `CC BY`, `separately from`, `not licensed under`,
  data disclaimers): **none**. Entire text is stock MIT.
- → Borrowable with attribution. No third-party-data carve-out, no gated assets.

## 2. What it is

.NET 8 SDK for Kalshi's `trade-api/v2`: typed REST clients (exchange, markets/events/series, orders,
portfolio, account, historical, live-data, multivariate, order groups, incentives, communications), a
WebSocket client with reconnect + replay, RSA-PSS request signing, a token-bucket rate limiter split into
read / balance-read / unscoped-write / per-shard-write buckets, Polly resilience pipeline, DI extension,
OpenTelemetry metrics. Published on NuGet; v1.3.0 tagged 2026-10-11.

## 3. Anatomy that drove the verdict

- ★6 · 2 forks · 8 open issues · created 2026-01-10 · **last push 2026-11-12** · 606 KB · C# 100%.
- 269 files: `.cs` 926 KB / 248 files; docs 36 KB / 6 files; 4 CI workflow files; **no** `env.example`,
  no Docker, no lockfile.
- **Tests:** 30 test files, 29 `[Fact]` + 18 `[Theory]` attributes. `KalshiSharp.Tests/Rest/LiveDataClientTests.cs`
  is offline (injected `RecordingHttpClient`, asserts request paths) — the suite needs no credentials or
  network, which is the right shape for an auth-first client.
- **CI (read from the API, not inferred from the code):** `main.yml` runs on `main` and feature branches —
  3 most recent runs all `success`, latest **2026-11-12T13:03Z**, matching the head commit. Separate
  `kalshicore-conformance.yml` also green on the same commit; `release.yml` publishes NuGet.
- 25 commits since 2026-10-01; recent messages are real contract work, not churn
  (`fix: reject omitted trade response collections (#98)`, `feat: add portfolio credit-history reads (#104)`).
- README 2,552 words against 926 KB of C# — the claim/code ratio is fine (no hype markers, no stub markers).
- `docs/SETTLEMENT_AND_ORDERBOOK_CONTRACTS.md` is unusually candid for this beat: it states what it does
  **not** claim ("Unknown future strings still fail deserialization; no forward-compatible tolerance is
  claimed", "Actual exchange mutation testing remains disabled").

## 4. Verified machinery (checked against Kalshi's own docs, fetched 2026-11-12)

| Claim | Venue doc | Verdict |
|---|---|---|
| message = `timestamp_ms + METHOD + path_without_query` (`RsaPssRequestSigner.cs:82-93`) | `docs.kalshi.com/getting_started/quick_start_authenticated_requests` — same concatenation, "without query parameters" | ✅ exact |
| RSA-PSS over SHA-256 | doc requires RSA-PSS/SHA-256, `MGF1(SHA256)`, `salt_length = DIGEST_LENGTH` | ✅ — .NET `RSASignaturePadding.Pss` uses salt = digest length; convention-dependent but matches |
| read bucket default 100 tokens/s, capacity 200 (`KalshiRateLimitOptions.cs`) | Basic tier Read = **200**/s, bucket capacity 3 s | ⚠ conservative, not wrong: refills at half the Basic budget and only banks 1 s instead of 3 s — it under-bursts, it cannot over-spend |
| write bucket 100/s, cap 100 | Basic Write = **100**/s, Basic capacity 1 s | ✅ |
| balance bucket 1/s, capacity 1 (no burst) | "once per second… bucket holds one second of budget, so there is no burst" | ✅ |
| per-shard write buckets keyed on `exchange_index >= 1`; batch → unscoped | same rules verbatim in `rate_limits.md` | ✅ |
| default token cost 10; cancel cost 2 | "Most requests cost the default of 10 tokens"; batch-cancel example bills 2 each | ✅ |
| README "rate-limit discovery" | `IAccountClient.GetApiLimitsAsync` + `GetEndpointCostsAsync` exist and map to `/account/limits` and `/account/endpoint_costs` | ✅ present |

**Two real defects found, neither affecting us:**

1. **No Ed25519 signing.** The venue auth doc now documents two key types — "RSA keys use RSA-PSS with
   SHA-256; Ed25519 keys sign the message directly". The repo has `RsaPssRequestSigner`, a legacy
   `HmacSha256RequestSigner`, and no `Ed25519` occurrence anywhere in 248 C# files. A key created today as
   Ed25519 cannot be used with this SDK.
2. **`Retry-After` plumbing is dead against current venue behaviour.** `KalshiHttpClient.cs:281-290`
   enriches `KalshiRateLimitException.RetryAfter` from `response.Headers.RetryAfter`, but `rate_limits.md`
   says plainly: "429 responses do not currently include `Retry-After` or `X-RateLimit-*` headers."
   The behaviour that follows is still correct (Polly exponential backoff with jitter on 429), so this is a
   stale surface, not a broken one — but "honoring Retry-After" is not a property this client can deliver.

**Not run locally by design.** This job's constraint is read-only: no clone, no install, no execution of
candidate code. So the suite is graded off its **reported** CI state (`success` on the head commit today),
not off a green run I performed. That is the weaker evidence tier and is labelled as such.

## 5. Why it cannot be adopted here — the decisive structural fact

`AddKalshiClient` registers `RsaPssRequestSigner` as `IKalshiRequestSigner` via DI
(`ServiceCollectionExtensions.cs:42`), and that constructor does
`ArgumentException.ThrowIfNullOrWhiteSpace(apiKeyId)` / same for the PEM (`RsaPssRequestSigner.cs:56-57`).
`SigningDelegatingHandler` signs **every** request unconditionally, and the per-area clients are `internal`
and take `IKalshiHttpClient`. There is no keyless mode and no supported bypass: constructing the client
requires a key id + RSA private key.

That is the same auth-first friction that decided the `pykalshi` audit, and it is decisive twice over here:

- Our Kalshi surface is **keyless public market data** (`api.elections.kalshi.com/trade-api/v2`, used by
  `scripts/kalshi-macro-shadow.py`, `kalshi-maker-read.py`, `kalshi-pm-btc-pair-sampler.py`,
  `kalshi-crossvenue-read.py`). An SDK that cannot issue an unsigned GET cannot replace any of them.
- The only part that *does* need a key is order entry, and this repo never handles keys
  (`REAL_EXECUTION_ENABLED=false`, paper only).

## 6. Fit table vs current `data/roadmap.json` (278 cards, read this run)

| Component | Card that asks for it | Verdict |
|---|---|---|
| Authenticated order entry / portfolio / fills clients | `retire-kalshi-copy-routing` (Scheduled — venue gate structurally unsatisfiable; Kalshi leg has taken 0 C-200 copies) | ❌ the lane this exists for is being closed |
| Keyless market/orderbook/trade reads | `kalshi-shadow-score-and-ledger` (In Progress, observability only) — already served keyless in Python | ❌ wrong language, and auth-first blocks the keyless path |
| Kalshi wallet/flow parity | `phase-kalshi1` (Backlog, **parked at a data wall**) — reopens only if a *keyless* surface supplies wallet-attributed flow | ❌ cannot reopen the gate: an auth-first client is the opposite of the one fact that would unpark it |
| Cross-venue arb plumbing | `phase-c` (Backlog) — needs both venues' reads, which we already have keylessly | ⚪ concept only; no code path |
| Kalshi adapter in the sidecar | `tr16-kalshi-adapter` (Done, Rust) | ❌ C# vs Rust, and the adapter is already fixed |
| Rate-limit token-cost model | no card asks for it | ⚪ the venue meters *authenticated* requests; our keyless pulls have no documented budget to model, so the buckets would be modelling something we do not spend |

No card anywhere in the roadmap asks for a C# client, a Kalshi order-entry path, or a Kalshi SDK
replacement. Per the skill's rule: a ✅/⚪ row with no card behind it does not get upgraded.

## 7. What is genuinely reusable (and what is not)

- **Corroboration, not a gap:** the SDK's `docs/SETTLEMENT_AND_ORDERBOOK_CONTRACTS.md` ties its
  `UseYesPrice` flag to Kalshi's `order_direction.md` contract — `book_side` `bid ≡ yes`, `ask ≡ no`,
  always. Our `scripts/kalshi-maker-read.py` already encodes exactly this (`taker SELL fills the YES bid at
  `yes_price``, taker BUY fills the NO bid at `no_price`), i.e. the same lesson as the TR-16 phantom-fill
  fix. Reading the SDK's doc therefore *confirms* our convention against the venue's current contract and
  finds nothing to change.
- **The rate-limit split** (read / balance-read / unscoped-write / per-shard-write, with batch writes billed
  to the unscoped bucket) is the cleanest statement of Kalshi's cost model I have read in code. It is
  relevant only if Kalshi order entry ever returns — which `retire-kalshi-copy-routing` forecloses. Not carded.
- **NOT portable:** the .NET/DI/Polly/OpenTelemetry layer (zero .NET in this repo), the HMAC legacy signer
  (the venue's auth doc lists only RSA-PSS and Ed25519; the HMAC path has no current doc backing —
  `unverified` as a supported scheme), and the NuGet package itself.

## 8. Cost / risk if adopted anyway

- Cost: a new .NET toolchain on the box plus a duplicate Kalshi contract surface in a language nothing else
  here speaks — for a venue whose copy lane is being retired.
- Risk: the SDK's headline capability (signing) requires holding an RSA private key, which this stack is
  built never to do. Adopting it would push against the never-handle-keys rule for zero measured gain.
- Reversibility: n/a — nothing is being added.

## 9. Recommendation

**Drop.** No `--recommend` recorded: there is no measurement that could make this worth a lane, and the
skill's rule is that a recommendation without a decision rule is an opinion. If Kalshi order entry is ever
reopened (it is not on the roadmap), re-read `kalshi-cpp`'s spec-level audit first — it is the same contract
surface in a language closer to the sidecar, already verified at a much higher evidence tier.

No roadmap card added: a drop verdict carries no work item, and the finding is fully captured here plus the
queue entry.

**Registry note (skill step 9 conflict):** this job's constraint forbids repo writes beyond the queue and
`drafts/`, so the dated `AUDIT INPUT` block was not appended to any roadmap card. Nothing to append for a
drop; if the user wants it on the record, paste into `phase-kalshi1`'s note:
`AUDIT INPUT (2026-11-12, drop; drafts/asset-audit-kalshisharp-20261112.md): hurley451/KalshiSharp (MIT, .NET 8) is auth-first by construction — AddKalshiClient registers RsaPssRequestSigner which throws on an empty key — so it cannot serve our keyless Kalshi reads and does not reopen this card's keyless-wallet-data gate. Third MIT Kalshi SDK read; no new capability.`
