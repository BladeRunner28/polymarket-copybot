# Asset audit — `JamesANZ/prediction-market-mcp` (2026-10-15)

**VERDICT: `drop` — clean, MIT, alive, keyless… and superseded by what we already run. Nothing here
replaces or accelerates a component of our stack; two of its design habits are worth remembering as
concepts (evidence warnings and an explicit movement basis), and one install-time side effect makes it
something we would only ever run containerised.**

Queue id: `JamesANZ/prediction-market-mcp` · audit worker run 2026-10-15 09:26 CDT · read-only: no
clone, no install, no execution of candidate code.

---

## 1. What it is

A ~100 KB TypeScript **MCP server** that exposes keyless prediction-market data to an LLM client
(Cursor / Claude Desktop): multi-venue market search, keyword-or-direct market resolution, and a
"gather market movement evidence" tool that assembles recent price movement plus retrieved context
items into a ranked, deduplicated evidence envelope. Transports: stdio (npm bin `prediction-markets`)
and an HTTP bridge (`http-bridge.mjs`) with a Dockerfile. Venues: Polymarket (gamma + CLOB price
history), Kalshi (candlesticks), PredictIt.

## 2. Anatomy facts that drove the verdict

| Fact | Value |
| --- | --- |
| Licence | **MIT** — vendorable, which is precisely why the claim-vs-substance read matters |
| Stars / forks / issues | ★37 · 15 forks · 1 open issue |
| Created / last push | 2025-07-08 / **2026-10-12** (4 days before this audit — alive) |
| Size | 144 KB, 37 files; `.ts` 101 KB/26f, `.json` 63 KB/3f (mostly the lockfile) |
| Structure | tests=yes · **CI=NO** · docker=yes · lockfile=yes · no `.env.example` (nothing to configure) |
| Keys required | **no** — README's "No API Keys" claim holds for the market-data paths |
| Telemetry markers | none detected |
| Dependencies | `@modelcontextprotocol/sdk`, `superagent`, `zod` — light, no exotic tree |

**Substance roughly matches the description** — it is a thin wrapper, and it says so. It is not a
claim-only README: 26 source files with a real module split (`markets/`, `evidence/`, `providers/`,
`tools/`), and 4 test files (~25 KB) covering evidence ranking, movement, provider and tool behaviour,
run with `node --import tsx --test test/*.test.ts`. **But there is no CI** (`ci=NO`), so those tests are
run by hand and nothing enforces them — a green suite here would be evidence, an unrunnable-by-anyone
suite is a caveat, so the tests were not treated as a quality gate.

## 3. What we could reuse — and why each one is already here

| Primitive (donor file) | What it does | Our baseline | Verdict |
| --- | --- | --- | --- |
| Keyless venue fetch (`markets/polymarket.ts`, `markets/kalshi.ts`, `markets/predictit.ts`) | Polymarket gamma + price history, Kalshi candlesticks, PredictIt snapshot | we already run keyless Polymarket (gamma/data-api + CLOB) and Kalshi (`external-api.kalshi.com`, TR-16 adapter fix) clients via `scripts/research-collect.py` and the adapters | ❌ nothing to take; PredictIt is a venue we do not trade and it has no price-history API at all (their own warning says so) |
| Market resolution (`markets/resolve.ts`) | `platform:id` direct reference, else keyword search, candidates capped at 5, every failure returns a warning string rather than throwing | our research collector resolves markets by slug/conditionId and already treats a dead source as a finding | ⚪ concept only (the "never throw, always warn" shape is a good habit we already follow) |
| Evidence dedupe + rank (`evidence/rank.ts`) | canonical-URL dedupe, Jaccard title near-dup at > 0.8, `0.7·recency + 0.3·lexical-overlap`, `STALE_CAP = 3` pre-window items, then explicit warnings ("Removed N duplicate evidence items", "Omitted N lower-ranked items") | `jaccard` already exists in our repo (`scripts/kalshi-slug-matcher.py`, `scripts/kalshi-coverage-probe.py`) for venue matching; our evidence lanes are carded (`phase-a2` Done — Bayesian log-odds aggregation in `src/lib/forecasting`; `phase-gdelt` In Progress) | ⚪ **concept only.** The 0.7/0.3 weights are hand-set and uncalibrated — under our own standing rule that must never enter a composite; the transferable half is the *warnings* discipline (every dedupe/omission is reported to the caller), not the score |
| Movement summariser (`markets/movement.ts`, `tools/gather-market-movement-evidence.ts`) | from/to/high/low/change over a window, with `basis: "trade_history" \| "previous_close"` and an `observations` count | we hold venue snapshots and the sidecar's tape, but no such labelled movement primitive | ⚪ concept: the **basis label** is the good part — it refuses to present a previous-close pair as if it were a lookback series (they say this out loud for PredictIt) |
| Evidence retrieval providers (`providers/agent-reach.ts`) | shells out to the third-party **Agent Reach 1.5.0** toolchain (`exa_search`, `twitter`, `reddit`, `youtube`) | we have our own collectors: `scripts/research-collect.py`, the GDELT lane, the local-LLM sentiment lane | ❌ not portable — a second retrieval stack for the lane we already run |
| MCP/HTTP transport + Dockerfile | agent-facing tool surface | our agent already has the `polymarket` skill and the injected fact sheet | ❌ not needed |

**No card asks for any row above.** The two that come closest — `market-to-news-lead-test` (Backlog:
does coverage intensity on a market's own proposition lead its price?) and `phase-gdelt` (In Progress) —
are both about *our* news sources, not about an MCP wrapper; this repo would add no measurement they
do not already have.

## 4. Risks (why even the free parts would not be adopted as-is)

- **Install-time side effect.** `package.json` runs `"postinstall": "node scripts/setup-claude.js"` —
  installing it mutates the host's MCP client configuration. Not malicious, but our untrusted-code
  hygiene says an installer that edits client config is run in a container (`--ignore-scripts`) or not
  at all, and never on the live box.
- **"No API keys" is true of half the repo.** The market-data paths are genuinely keyless; the evidence
  search path requires the Agent Reach toolchain wrapping third-party CLIs (X, Reddit, Exa, YouTube).
  Anyone reading only the README would over-claim the repo's reach.
- **No CI.** Tests exist; nothing runs them. For a 100 KB dependency that is a minor risk, and it is
  the reason the fit table above grades habits rather than code.
- **Dependency weight is otherwise fine** (3 runtime deps), and there is no telemetry.

## 5. Recommendation

**None — `drop`.** A recommendation without a decision rule is an opinion, and there is no measurement
here worth a pre-registration: the data path duplicates clients we already run, the ranker is an
uncalibrated hand-weighted score, and the retrieval provider is a parallel stack to our own collectors.
Nothing is queued for approval from this audit.

If an evidence lane ever needs the two habits above, reimplement them behind our own gates:
(I) report every dedupe/omission as a warning in the artifact, and (II) stamp each movement/aggregate
with the basis it was computed on. Both are a few lines, and both need a test that the warning fires.

## 6. Honest caveats

- Verdict is **`drop` on adoption fit**, not on quality: the repo is licensed, alive, honest about its
  limits and small enough to vendor. It simply answers a question we have already answered.
- No CI means the test suite is unverified by a third party; we did not run it (candidate-code hygiene:
  no install, no execution).
- The README's "Real-time Data" framing is marketing; the implementation is polling the same public
  endpoints our collectors use.

## 7. Registry block (NOT applied — see the note)

This run is constrained to the audit draft plus the queue record, so nothing was written to
`data/roadmap.json` and no card was created. If you want the finding recorded:

```
AUDIT INPUT (2026-10-15, audit worker; drafts/asset-audit-prediction-market-mcp-20261015.md):
JamesANZ/prediction-market-mcp (MIT, ★37, keyless MCP server) — DROP on fit, no action. Data path
duplicates our keyless Polymarket/Kalshi clients; its evidence ranker is an uncalibrated hand-weighted
0.7·recency + 0.3·lexical-overlap score (must never enter a composite); its search path needs the
third-party Agent Reach toolchain and the npm package mutates client config on postinstall. Two habits
worth reimplementing only if an evidence lane asks for them: warn on every dedupe/omission, and label
each aggregate with the basis it was computed on. No recommendation, nothing awaiting approval.
```

Dashboard: http://localhost:3013/drafts/asset-audit-prediction-market-mcp-20261015
