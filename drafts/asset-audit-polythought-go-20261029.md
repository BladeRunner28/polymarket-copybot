# Asset audit — `lein3000zzz/polythought-go`

**Verdict: WATCH — ideas only. Licence blocks the code AND blocks running it commercially; live mode requires a wallet private key. One transferable idea survives, and it is a *new* (uncarded) measurement.**

- Audited: 2026-10-29 · by copybot-asset-audit (read-only: no clone, no install, no execution)
- Dashboard: http://localhost:3013/drafts/asset-audit-polythought-go-20261029
- Donor: https://github.com/lein3000zzz/polythought-go

---

## 1. What it is

A self-hosted **workflow-automation server for Polymarket**: a node canvas (or type-checked
TypeScript-as-workflow) whose triggers are schedules, market activity, followed traders' trades, your
own orders and Telegram; whose nodes read Polymarket data, call LLMs, transform/filter, and **place
orders on paper or live**. Plus an MCP server so Claude Code/Codex can build and run workflows, a
plugin host, and a QuickJS-in-WASM sandbox (wazero + landlock + seccomp) for user-supplied node code.

That is a close neighbour of what we already run — copy detection, copy sizing, risk caps, paper
book, PnL — implemented as a general workflow engine rather than a fixed pipeline. The overlap is
the reason to read it and the reason not to adopt it.

## 2. Anatomy facts that drove the verdict

| Fact | Reading |
| - | - |
| Licence **PolyForm Noncommercial 1.0.0** (`NOASSERTION`; LICENSE carries a Required Notice) | **Noncommercial only.** Not OSI. Blocks vendoring *and* blocks the usual fallback for service-class candidates ("run it in its own container and read the files it writes") — trading for profit is commercial use. Read-for-ideas only. |
| ★10 · forks 0 · issues 0 · created 2026-10-08 · last push 2026-10-29 | 21 days old, single author, no community surface. Alive, but bus factor 1 and no external validation. |
| 1,538 files · 6.7 MB Go (955 files) · **324 `_test.go`** · hexagonal (456 adapters / 406 core) | Substantive, not a claim-only README. The biggest code mass in anything audited on this beat recently. |
| CI: 4 workflows; `ci.yml` **success on main today** (08:07Z); e2e workflow present; race detector, sharded jobs, golangci-lint, actions pinned by SHA | The maintenance signal is real *and* reported by GitHub, not inferred from my own green run (I ran nothing). |
| `keys.go`, `sessionkeys.go`, `approvals.go`, `geoblock.go`, `go-ethereum` dep; README "wallet" | Live mode holds and signs with a **private key** and posts USDC approvals. Hard no for our never-handle-keys rule; paper mode needs none. |
| Releases v0.0.3 (10-28), v0.0.4 (10-29); commits same day | High velocity for a 3-week-old repo → plausibly AI-assisted large-scale generation. Treat its thresholds as untested-in-production, because there is no evidence anyone trades live on it. |

## 3. Verified machinery (re-derived, not README-quoted)

### 3.1 Taker fee — `services/trading/paper.go:142-155`

```go
base := price * (1 - price)
if e := s.Exponent; e != 0 && e != 1 { base = pow(base, e) }
return shares * s.Rate * base    // round 5dp
```

Their own test pins `fee(100 shares, p=0.50, rate=0.07) == "1.75"`. I re-derived the venue's
published **Crypto, 100 shares** table (docs.polymarket.com/trading/fees, fetched today) against both
candidate laws:

- `C·rate·p(1−p)` — matches **21/21 rows within $0.0025** (cent rounding); exact at every 0.05 step.
- `C·rate·min(p,1−p)` — matches 2/21, off by up to **$1.75 (+100%) at p=0.50**.

So the donor's fee arithmetic agrees with the venue's own table, and `Exponent` is **not** invented
generality: the venue publishes `feeSchedule.exponent` per market (market-details docs; today's
example is `exponent: 1`, i.e. linear). **Our `takerFeePerShare` (src/lib/scoring/price-edge.ts:56)
is the same law**, and `scripts/fee-sign-flip-test.py:58` already records the $1.75-vs-$3.50
discrimination. Net: **corroboration of our model, zero delta to adopt.** The one carry-over is a
cheap guard — if the venue ever publishes `exponent ≠ 1`, our linear model silently under-charges.
Not worth a change today; worth a line in the fee card.

### 3.2 Taker fill simulator — `services/trading/paper.go:127-183` (the useful one)

`fill()` walks real book levels in price order within the limit, per level:
`take = min(remaining, level.size)`, cost at the level price, **taker fee computed per fill**, then
FOK (all-or-nothing, else unfilled with a reason) vs FAK (keep the partial, cancel the rest),
with "wholly filled" defined as *dollars remaining < one cent's worth at the last price*. Unfilled
paths return a human reason string. It is wired into the paper path (`service.go:232`), not
test-only.

**This is the half of the fill question our stack cannot currently answer.** Verified absences in our
repo (greps, not assumptions):

- `scripts/c200-printthrough.py:270 l2_scan()` tests only whether the **best ask crossed a price
  level** over the window — no depth, no size, no cost. Its own docstring is explicit: *"the level
  was reachable, never 'we would have been filled'"*.
- The string `marketable` appears **nowhere** in `src/` or `scripts/` (only in an unrelated lumibot
  audit and a scratch file under `drafts/_audit_scratch/`).
- `phase-d2-fill-model` owns the **maker** arm (Cox-PH `P(fill within Δt)` from book context) and its
  gate is trade-at-level flow — an input we don't capture. **The taker arm does not need that input**:
  displayed L2 depth is sufficient to bound what a marketable order would have paid. So D2's blocker
  does not apply to this slice, and no card asks for it.

### 3.3 Copy sizing — `core/nodes/trading/copysize.go`

Three buy modes: `fixed` (dollars), `multiple` (× what they spent, further scaled by the trader's
`Size ×` and capped by their `Max $`), `proportional` (their spent ÷ their total portfolio value,
capped at 1, × our worth — mirror-weights). Buys limited by `slippage` (default $0.02) as a **limit
price**: buy `price+slip` snapped **down** to tick, sell `price−slip` snapped **up** — i.e. the budget
rounds toward the tighter price, and clamped into `[tick, 1−tick]`. Partial copying via
`chance.Taken(wf, node, txHash, pct)` — sha256 over `wf\x1fnode\x1ftxHash`, top 53 bits → uniform, so a
re-run or restart takes the *same* trades (idempotent partial copying); sells are always copied so no
copy outlives theirs. Sell sizing infers their pre-sale holding as `sold + (their holding now)` and
copies `ourHeld × sold/(sold + now)`.

Two things I checked against our side:
- Their tick/clamp discipline: **already satisfied** — `rust-sidecar/src/main.rs:319` asserts
  `max(0.01, price − credit) == 0.01`, i.e. our booked entry floors at 1¢.
- Their sell inference is only correct if the Data API read is *post*-trade. A lagged read returns
  the pre-sale size, so the fraction becomes `sold/(pre+sold)` and small sells are under-copied by
  up to 2×. That is a fragility to know about, not a technique to import.

### 3.4 Risk guard — `core/nodes/trading/guard.go`

Per-workflow caps: max $ per copy / per market / per 24 h, min & max price, category allow-deny.
Structurally the same idea as our exposure cap, but flat per workflow rather than netWorth-scaled —
**our v50 cap (`$1,000 + 50%·max(0, netWorth−principal)`) is strictly more general.** Superseded.

## 4. Fit table vs `data/roadmap.json`

| Donor component | Card that asks for it | Verdict |
| - | - | - |
| `fill()` book-walk taker simulator + per-level taker fee + FOK/FAK partial semantics | **none** — `phase-d2-fill-model` asks only for the maker `P(fill)` arm; `c200-maker-fill-assumption` asks the reachability question `c200-printthrough.py` already answers | ⚪ **concept only** — reimplement ~80 LOC over our own `data/l2/` behind our gates. No wiring to copy: their caller is their paper pipeline, ours does not exist |
| `fee()` + `FeeSchedule{rate, exponent}` | `paper-ledger-fee-fidelity`, `paper-trader-archived-fee-reprice` (Done) | ❌ no delta — same law we already ship; `exponent` is venue-real but 1 today |
| `feesEnabled` per-market gate | live admission infers the rate by keyword in `price-edge.ts:65 categoryFeeRate()` (its own comment: stopgap because `MarketSnapshot.category` is NULL) | ⚪ **concept** — the venue publishes `feesEnabled`/`feeType` **keyless on gamma** (confirmed today: `"feesEnabled":false,"feeType":null`). Our keyword map can never return 0, and geopolitics is fee-free, so at p=0.5 it books a phantom ≥1.25¢/share on fee-free markets. See §7 note — I did **not** verify whether an existing fee card already owns this |
| Copy sizing (fixed / multiple / proportional) | Kelly regime v49+ (settled; not re-litigable) | ❌ not portable — no edge term, no calibration input, uncapped by probability. `proportional` is mirror-weights, a different (uncalibrated) regime |
| Sell-share inference `sold/(sold+now)` | our exit path | ⚪ concept — real Data-API lag failure mode; not needed while exits mirror their sell |
| `chance.Taken()` hash-sampled Take % | none | ❌ not needed — our lanes admit/skip deterministically by band; no partial-copy-by-hash mechanism |
| Risk guard caps | `c200` exposure cap v50 | ❌ superseded (theirs is flat, ours is netWorth-scaled) |
| Workflow canvas + engine, MCP server, wazero/QuickJS sandbox, LLM agent nodes, Telegram/mail integrations, live signing | — | ❌ not portable (see §6) |

## 5. Integration proposal (if approved)

Only §3.2 is proposed, and it is **not an integration** — it is a read-only replay:

`REC — price the taker entry arm on booked C-200 legs`

- **Hypothesis:** a marketable (FAK) entry at dispatch would have cost at least the $0.02 maker credit
  we book, so the maker convention is not obviously wrong on cost alone.
- **Measurement:** for each joined C-200 BUY intent (`c200-printthrough.py` already joins 374 on the
  2026-10-26 population), take the first `data/l2/` snapshot at/after `dispatchedAt`, walk the ask
  side level-by-level to fill the leg's dollar size, and report: VWAP premium over `intentPrice`,
  shares obtainable within `intent + 2¢`, and the share of legs with premium ≤ 2¢. Median L2 start lag
  is 0.2 min post-v62, so the dispatch-time book is covered. Expected n ≈ 350, falling to the subset
  with a snapshot inside the first minute.
- **Decision rule:** if premium ≤ 2¢ on **≥50%** of covered legs → open a maker-vs-taker entry
  comparison (before/after on booked PnL) as a v-next lane-A proposal; **else** close the taker arm
  permanently and record the maker convention as defended on cost, not only on reachability.
- **Cost:** ~2 h, read-only, artifact only. Compute: none beyond reading `data/l2/`.
- **Reversibility:** nothing in the trade path is touched; delete the artifact and the card.

Effort/risk if someone ever argued for the *code*: zero — the licence forbids it. That is the point.

## 6. NOT portable

- The workflow canvas, node engine, expression language, TypeScript-as-workflow compiler, plugin host.
- The sandbox (wazero + landlock + seccomp) and the MCP server — genuinely good engineering, but they
  solve "run untrusted user code safely", a problem we do not have. Our equivalent surface is the
  LLM/agent layer, which already duplicates our DeepSeek research bot + local-sentiment lane.
- LLM agent nodes, Telegram/mail/webhook/GitHub integrations.
- **Anything live**: private-key custody, USDC approvals, order signing, geoblock handling.
- Their paper-fill *assumption* is not transferable either — it fills at the book, which is right for
  a taker workflow and wrong for our resting-bid lane.

## 7. Honest caveats + prepared (NOT applied) registry block

- **I did not run their suite.** This cron is read-only (no clone, no install, no execution). The
  green-CI claim is GitHub's report (`ci.yml` success on main, 2026-10-29 08:07Z), not my verification.
  What I *did* verify independently is the fee arithmetic, against the venue's own published table.
- Their `fill()` has a clean-room-copy risk: it is short enough that a reimplementation will resemble
  it. Reimplement from the *semantics* in §3.2, not from their source. PolyForm Noncommercial permits
  neither copying nor commercial running.
- **The geopolitics/fee-free observation in §4 is an observation, not a recommendation.** Before anyone
  acts on it, check `paper-ledger-fee-fidelity` and `timeseventeen-fee-incidence-prereg` — 2 minutes
  of reading I did not spend, and asserting an uncarded gap on a grep of card *ids* would be exactly
  the mistake this audit warns about elsewhere.

Registry writes: this job's constraint is "no repo source, rules, or config edits", and its registry is
`data/research-asset-queue.json` (updated via `scripts/asset-queue.py`). The roadmap card block is
therefore **prepared here, not applied** — and the card is a **new** work item, flagged for veto:

```json
{
  "id": "c200-marketable-entry-cost",
  "title": "Price the taker entry arm: what would a marketable FAK at dispatch have cost?",
  "column": "Backlog",
  "effort": "~2 h",
  "gate": "existing data/l2/ corpus (no new capture); ≥150 joined C-200 BUY legs with a snapshot < 60 s after dispatch",
  "note": "AUDIT INPUT (2026-10-29, watch; drafts/asset-audit-polythought-go-20261029.md): NEW CARD, proposed unprompted so it can be vetoed. The donor (lein3000zzz/polythought-go, PolyForm Noncommercial, read-only) shows the missing half of the fill question in ~55 lines (services/trading/paper.go fill()): walk ask levels within the limit, per-level taker fee, FOK all-or-nothing vs FAK partial-with-reason. Verified absent here: c200-printthrough.py l2_scan() tests only best-ask crossing with no size or cost, and 'marketable' appears nowhere in src/ or scripts/. phase-d2-fill-model's gate (trade-at-level flow) does NOT apply to the taker arm - displayed L2 depth bounds a marketable order. REC decision rule: if premium <= 2c on >=50% of covered legs, open a maker-vs-taker before/after; else close the taker arm and record the maker convention as defended on cost. Read-only; nothing in the trade path is touched.",
  "tags": ["fill-model", "l2", "c200", "audit-input"]
}
```

## 8. Recommendation

**Queue it, don't audit it further, don't touch its code.** Nothing here needs a second pass: the
licence will not change, the keys requirement will not change, and the repo's own direction (a
general workflow platform for retail self-hosters) diverges from ours (a fixed, calibrated,
measured pipeline). Take the one idea in §3.2, pre-register it as above, and let the number settle
whether the maker convention survives on cost as well as reachability.

Roadmap order check: this sits in **Phase D2 territory**, which is Backlog and gate-satisfied — so
it is queued behind the C-200 ladder reads, not ahead of them. It competes with nothing live.
