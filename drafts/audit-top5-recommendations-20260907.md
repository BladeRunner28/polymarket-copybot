# Top-5 Repo-Scout Audit — combined recommendations (post-Oct-8 Kelly window)

Audited 2026-09-07 (parallel deep audits; per-repo docs below). All five
verdicts respect the Kelly measurement window (Sep 8–Oct 8): **nothing ships
before Oct 8**. Everything here is an adoption *recommendation* for after the
window closes — approval required per standing workflow.

| # | Repo | License | Verdict | Top transfer |
|---|---|---|---|---|
| 1 | YichengYang-Ethan/oracle3 | Apache-2.0 | **QUEUE → ADOPT at Phase C kickoff** | `coinjure/matching` staged PM↔Kalshi matcher |
| 2 | livetennisapi/polymarket-tennis | MIT | **QUEUE → ADOPT (pattern)** | generic sports market→match matcher |
| 3 | aulekator/Polymarket-BTC-15-Minute | NO-LICENSE | QUEUE (concept donor) | late-window trend tape test |
| 4 | komako-workshop/digital-oracle | MIT | QUEUE (narrow) | CFTC COT provider + test harness |
| 5 | caiovicentino/polymarket-mcp-server | MIT | **SKIP** | confirmation-gate semantics (doc-only) |

Per-repo: `drafts/oracle3-audit-2026-09-07.md` ·
`drafts/polymarket-tennis-audit-2026-09-07.md` ·
`drafts/btc15min-audit-2026-09-07.md` ·
`drafts/digital-oracle-audit-2026-09-07.md` ·
`drafts/polymarket-mcp-server-audit-2026-09-07.md`

---

## Ranked implementation list (after Oct 8)

### 1. oracle3 → Phase C kickoff: staged PM↔Kalshi market matcher — ADOPT (top priority)
`coinjure/matching` is a self-contained 5-stage staged matcher
(category·date·template·text·resolution → HIGH/MED/LOW confidence) whose
template-field checks reject WIN-vs-TIE and cumulative-date false matches — it
supersedes the fuzzy ticker-grouping approach and fills the **core dependency
of Phase C (constraint arb)**. Effort ~0.5–1 dev-day incl. PMA validation, LOW
risk, flag-revertible (detection/shadow lane first). Also concept-only: the
relations-lifecycle + ValidationResult violation-stats → Phase C shadow journal
and λ̂-refit reporting (~0.5d). **Vendored `wang_mle.py` is byte-identical to
upstream — no upgrade needed.** NOT-portable: LLM layer, Solana/DFlow
execution, their PaperTrader fill model (cruder than our Phase D2 Cox-PH plan).

### 2. polymarket-tennis → generic sports market-matching module — ADOPT (pattern)
`matching.py` (~250 LOC of pure functions, 94/94 tests green): name+date
matching with fold normalization, similarity ladder, both-players-must-agree
via `min`, ±1-day date bonus, >1-day hard reject, ambiguity margin → returns
None rather than guessing, doubles rejected. **Feed-agnostic** — needs only
`{players, scheduled_time, status, winner}`; plugs any feed incl. our Odds API
(Data-1). Re-parametrize per sport for the short-TTR lane (esports alias
caveat: "NaVi" unhandled). ~1 dev-day + half-day wiring, LOW risk.
Also as a pattern: staleness-aware joined-view discipline → ML-2 labeling.
Not a signal source — plumbing only (vendor marketing repo, zero predictive
code, no Kelly/edge anywhere).

### 3. BTC-15min → late-window trend tape test — QUEUE (concept donor, read-only license)
The real bot (source, not README) is late-window trend-following: trades only
minutes 13–14 of each 15-min interval, price >0.60→YES / <0.40→NO. Its "~75%
win rate" is an RNG-rigged sim artifact (`uniform(−0.02,+0.08)`); the "7-phase
pipeline" and "self-learning" are unexercised scaffold. **Nothing copyable**
(NO-LICENSE). Transferable: the **late-window persistence hypothesis** —
tape-test `P(resolve | mid ≥0.60 at T−60..120s)` against the 692M-trade PMA
tape (~1 dev-day, analysis-only) to de-risk any short-TTR BTC lane; plus the
deterministic 15-min slug-universe convention and the probability-space
threshold taxonomy as ML-2 feature-registry ideas.

### 4. digital-oracle → two narrow adopts — QUEUE
No aggregation/calibration math exists in code (the "13-source calibrated
answer" is LLM prompt heuristics — v39's Bayesian log-odds engine dominates
it). Adopt: **(a) CFTC COT provider** — the only genuinely new *non-price*
evidence class; keyless, weekly, C-tier → v39 evidence webhook, ~1–2 days,
flag-revertible; **(b) record/replay snapshot HTTP test harness** (246 tests in
0.22s, fixture replay) → research-bot fetcher CI. Kalshi/Treasury/BIS/Deribit
breadth is concept-only: under the v39 market-firewall doctrine price-derived
data is the prior, not evidence (a doctrine decision, not a port). CME FedWatch
provider is dead (403).

### 5. polymarket-mcp-server → SKIP (code); borrow two concepts (doc-only, ~2–4h)
2 of 45 tools are stubs (`get_price_history`, `get_market_holders` return
hardcoded error dicts); all 7 realtime tools are dead in HEAD (dispatch to a
nonexistent handler); no Kelly/edge math. Genuine substance = the **safety
layer semantics**: hard-block confirmation gate (`confirmation_required` →
re-issue with `confirm=true`), pre-trade gates (order/exposure/per-market/
liquidity/spread) with correct SELL-reduces-by-`min(order_value,pos_value)`
and no-position-SELL-adds-exposure handling. Borrow those edge cases into the
Rust sidecar's risk-gate spec at Phase C — concept only, trivially revertible.
Read-side tooling = redundant with `src/lib/adapters/polymarket.ts`; Hermes MCP
= thin + prompt-injection surface + violates paper-only posture if write tools
are enabled.

---

## What this means in roadmap order (post-Oct-8)

1. **Phase C build (early Oct)** — start with the oracle3 matcher (item 1); it
   is the arb-detection prerequisite. MCP safety semantics (item 5) fold into
   the sidecar risk-gate spec for the same build.
2. **Short-TTR lane / Data-1** — generic sports matcher (item 2) wires the Odds
   API feed into the lane; do the BTC late-window tape test (item 3) *before*
   committing to a BTC short-TTR lane.
3. **Research-bot / evidence** — CFTC COT + snapshot test harness (item 4) land
   whenever the research side has a free cycle.

All five audits note the same discipline: source-verified machinery only,
nothing pre-Oct-8, and every integration is flag-revertible behind a shadow
lane or webhook. Verdicts: **1–2 are genuine adopts, 3–4 are queue-narrow,
5 is skip-with-concepts.**
