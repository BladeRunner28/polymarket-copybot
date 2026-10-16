# Audit: LLMQuant/awesome-trading-agents — adoption fit for Medusa CopyBot

**Date:** 2026-10-15 · **Auditor:** Hermes asset-audit cron · **Method:** GitHub API metadata for the
repo and for **every prediction-market-relevant entry it lists** (resolved off the API today, not off
the descriptions), README read in full, entry census computed from the file, then each PM entry
cross-checked against `drafts/` and `data/roadmap.json` for prior work. No clone, no install, no
execution.

## Verdict

**DROP as an asset** — it is a docs-only curated index (8 `.md`, no code, no tests) and 94% of it is
outside our lane. **The deliverable it produced is a triage**: 7 of its 126 entries touch prediction
markets, 3 of those are already in our record, 2 fail on licence/activity, and **2 are genuinely new
leads** (below), one of which is worth the audit pipeline.

## 1. What it is

"Awesome Trading Agents — the Trading Agentic Stack": a CC0-1.0 list of open-source projects where
LLMs research markets, decide, or connect agents to data/execution, grouped as Agents / MCPs / Skills.

| Metadata (GitHub API, 2026-10-15) | |
|---|---|
| Licence | **CC0-1.0** → content reusable without restriction (no code to reuse anyway) |
| Stars / forks / open issues | 896 / 146 / 24 |
| Created / last push | 2026-04-22 / **2026-08-13** (~2 months stale) |
| Content | 19 files: 8 `.md` (105 KB), 5 `.png` (2.9 MB), 2 `.yml`, 1 `.svg`; `docs=NO`, `tests=NO` |
| Entry census (computed from the README) | **126 entries** |

**Claim vs substance:** the README asserts *"We still check recent activity before adding or updating
a project"*. Verified — **partly**. Entries carry no dates and no licences, and two of its
prediction-market entries are ≥5 months stale (`jvnhaoWen/PolyAgent` last push 2026-03-24;
`Polymarket/agent-skills` 2026-02-19). Its own weekly refresh commits stop at *"refresh 2026-W28
alpha entries"* (mid-July) — the cadence died before the last push.

**Scope by lane (126 entries):** 28 multi-agent systems, 17 market-data MCPs, 9 brokerage/exchange
MCPs, 9 single-agent traders, 7 equity-research skill packs, 6 research copilots, 5 research/analysis
MCPs, 4 crypto/DeFi skills, 4 benchmarks, 3 strategy-coding agents, 3 prediction-market specialists,
2 prediction-market MCPs, 1 PM skill pack, plus 1 PM round-up entry. **Prediction-market-relevant =
7/126 ≈ 5.6%.** Its centre of mass is US-equity research copilots and A-share/crypto data plumbing —
not wallet copy-trading or PM microstructure.

## 2. Triage of every prediction-market entry (claim → primary source → verdict)

| Entry | API facts (2026-10-15) | Our record | Verdict |
|---|---|---|---|
| `OctagonAI/kalshi-trading-bot-cli` | MIT, ★379 | **audited** — `drafts/octagon-audit.md` (Kelly sizer, 5-gate engine = Phase B reference) | known |
| `caiovicentino/polymarket-mcp-server` | MIT, ★694, pushed 2026-09-20 | **audited** — `drafts/polymarket-mcp-server-audit-2026-09-07.md` | known |
| `YichengYang-Ethan/oracle3` | (multi-venue Wang-Transform + Kelly + arb) | **already used** — we *vendor* its WangMLE (`scripts/vendor/oracle3/wang_mle.py`) as Phase A calibration substrate (`drafts/wang-calibration-audit.md`) | known |
| `ryanfrigo/kalshi-ai-trading-bot` | **MIT, ★620, pushed 2026-10-13** (alive) | none | new — but Kalshi copy-routing is retired and our Kalshi lane is shadow/measurement-only; only its portfolio-optimizer math could be worth a later audit |
| `jvnhaoWen/PolyAgent` | MIT, ★91, last push **2026-03-24** (~7 months dead), 2.1 MB | none | ❌ reject on activity |
| `Polymarket/agent-skills` | **NO LICENCE** (spdx `null`), ★192, last push 2026-02-19, 25 KB | none | ❌ first-party but all-rights-reserved ⇒ read-only; its subject matter (auth, orders, WS, bridging, gasless flows) is live-execution surface we never touch (paper only, never keys) |
| `agent-next/polymarket-paper-trader` | **MIT, ★499, forks 65, pushed 2026-10-15 (today)**, Python, PyPI + MCP + `PROVENANCE.md` + benchmark harness | none | ✅ **new lead — enqueued** |

**Adjacent entry checked on purpose** (not PM-labelled, but it touches our second axis, decision
memory): `mnemox-ai/tradememory-protocol` — MIT, ★1,430, pushed 2026-10-09, MCP "+pre-trade brake":
pulls your own fills, finds where your history loses money, surfaces it before the next order. Our
`DecisionJournal` + `risksJson` skip-set labelling + `review:outcomes` + the rules auto-tuner already
implement the primitive in rule form (v48 band floors, hour blackouts, category blacklists, slug caps).
**Enqueued as a second lead rather than asserted as a gap** — the honest statement is "same primitive,
different packaging; verify before believing it adds anything".

## 3. What we could reuse

- **Nothing as code** (there is no code). The one transferable artifact is its *curation criteria*
  ("public code or artifacts, clear LLM-driven behaviour, recent activity, useful documentation,
  distinct role, visible adoption") — and our `github-scout` + the `drafts/` dedupe already implement
  a stricter version of it (licence gate, activity gate, tested-substance gate).
- **The value of the run is the 2 new leads**, not the list: it is a *dedupe target* — re-processing
  it later would re-surface 3 repos we have already read.

## 4. Recommendations

1. **Drop it as an asset; do not add it to the radar rotation.** 5.6% lane relevance and a dead
   refresh cadence do not justify a slot; its PM subset is now fully triaged here, so a future
   re-surface is one grep away.
2. **Two queue-adds** (done — the leads die without them):

```bash
cd ~/polymarket-copybot && python3 scripts/asset-queue.py add --id agent-next/polymarket-paper-trader \
  --stars 499 --license MIT \
  --note "via LLMQuant/awesome-trading-agents (asset-audit 2026-10-15): PM paper-trading simulator + live order books + claimed official fee model + fill-fidelity benchmark harness (Brier/calibration/alpha) + PROVENANCE.md; Python/PyPI/MCP; alive (pushed 2026-10-15)"

cd ~/polymarket-copybot && python3 scripts/asset-queue.py add --id mnemox-ai/tradememory-protocol \
  --stars 1430 --license MIT \
  --note "via LLMQuant/awesome-trading-agents (asset-audit 2026-10-15): outcome-weighted decision memory + pre-trade brake MCP (17 tools / 35+ REST); second axis (decision memory), likely covered by DecisionJournal+risksJson+review:outcomes — audit to confirm or refute"
```

## 5. Honest caveats

- **A curated list is not evidence about any listed project.** No entry carries a date, licence, or
  verification of its claims ("5-gate risk engine", "portfolio optimization"); every row above was
  re-resolved off the GitHub API, and the two rejects are rejected on *their* facts, not on ours.
- The two new leads are **leads only** — neither was read here. `agent-next/polymarket-paper-trader`
  advertises "official fees, verified fill fidelity", which is exactly the kind of claim that needs
  our measured fee law (`bt-fee-maker-calibration`, Done) pointed at it before anything is believed.
- `Polymarket/agent-skills` being first-party does **not** grant a licence; spdx `null` =
  all-rights-reserved regardless of who publishes it.
- Staleness bound: metadata read 2026-10-15; the list's own last push is 2026-08-13, so its
  "recent activity" claims are at least 2 months behind reality by construction.

## 6. Registry block (prepared, NOT applied — this job is recommendations-only)

```
AUDIT INPUT (2026-10-15, asset-audit cron; drafts/asset-audit-awesome-trading-agents-20261015.md):
list triaged, not adopted (CC0-1.0, docs-only, 7/126 PM-relevant, refresh cadence dead since ~2026-W28).
Of its 7 PM entries: 2 already audited (octagon, caiovicentino MCP), 1 already vendored (oracle3
WangMLE), 2 rejected (PolyAgent dead since 2026-03-24; Polymarket/agent-skills = no licence +
live-execution surface), 1 low-fit (ryanfrigo/kalshi-ai-trading-bot, MIT/alive, Kalshi lane retired),
1 new lead enqueued (agent-next/polymarket-paper-trader, MIT/★499/alive). 2 new leads queued total.
```

Dashboard: http://localhost:3013/drafts/asset-audit-awesome-trading-agents-20261015
