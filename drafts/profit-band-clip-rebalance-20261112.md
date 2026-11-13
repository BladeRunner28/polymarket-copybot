# Clip rebalance, revised — the cap is a risk rail, and the regime CI that justified it has already moved

**LANE A — PROPOSAL ONLY. Nothing applied: no `apply-v*.ts` executed, no write to `prisma/dev.db`,
no RuleSet row created, nothing merged.** Active ruleset this read: **v72** (read-only).
Draft slug: `profit-band-clip-rebalance-20261112` · card: `profit-band-clip-rebalance`
(approvals `apr-profit-band-clip-rebalance`, approved 2026-11-12T16:45:07Z) ·
**supersedes** `drafts/profit-band-clip-rebalance-20261111.md`.
Read with the two commands in §8; every figure below is from that run, today.

---

## 1. Verdict first

**Approve the CAP ($25 on 0.0–0.2, C-200 only, new RuleSet field defaulted EMPTY) — as a
DRAWDOWN RAIL, not as an edge trade. Defer the LIFT.**

Two things changed since the 11-11 read, and the first one is the reason this document exists:

1. **The card's headline number no longer reproduces.** The regime cap delta was quoted at
   **+$790, CI +290…+1,324** — "the only arm whose regime CI excludes zero". On today's book it
   is **+$476.08, CI −661.04…+1,362.64 — it includes zero.** This is not a method change: the
   11-11 number reproduces *exactly* when the population is truncated at the 11-11 read
   (**+$815.25, CI +293.26…+1,376.91**). The difference is **two cheap-band legs that opened on
   11-11**, one of which won **+$552.23** on a $100 clip at 0.153. One leg flipped the CI across
   zero. The regime arm is a 20-leg sample and moves ±$489 on a single leg (§4.7).
2. **The cap still buys what it bought, and that case is intact.** Regime closed-leg max drawdown
   **−$776.58 → −$225.35**; all-time **−$890.49 → −$547.82**; worst day −$439.32 → −$289.32. Its
   all-time cost, **−$2,421.93 (CI −6,320.80…+877.42)**, is indistinguishable from zero and lives
   entirely in ≤5 wallets (**ex-top-5 wallets: +$550.45**, sign flips).

So the honest sentence is: *the cap is worth about zero in expected PnL and a large amount in
drawdown.* That is a variance purchase, and it is only defensible if it is written down as one,
which the card currently does not do.

**What the card gets right and I am keeping:** the cap binds on **BANKROLL_200 alone** (all 69
cheap-band legs above $25 are C-200; STANDARD has **zero**, its clamp is `BOT_LIMITS.STANDARD =
$20.00`), and the lift does not clear its bar in the live window.

**What I am withdrawing from the 11-11 draft:** its framing of the cap as the arm whose regime CI
excludes zero, and (new correction) the card's premise that the clip is inverse to the edge *inside*
the band — see C8 below.

---

## 2. What moved between the 11-11 read and today (every figure that changed)

| figure | 11-11 draft | today (11-12) | why |
|---|---|---|---|
| population (finished, deduped) | 5,680 legs / $64,168 | **5,710 / $64,887** | 30 more finished legs |
| cheap band 0.0–0.2 | 509 legs, +$6,895 book | **521 legs, $12,226, +$6,928 (+56.7%)** | one day of flow + resolutions |
| cheap legs > $25 | 65 legs / $5,656 / +$2,757 / +48.7% | **69 / $6,056 / +$3,176 / +52.4%** | 4 more; largest clip still **$100.00** |
| cap, all-time | −$2,108, CI −9.0…+1.4pp | **−$2,421.93, CI −6,320.80…+877.42** | more capped legs; resolutions revalued rows |
| cap, regime | **+$790, CI +290…+1,324** | **+$476.08, CI −661.04…+1,362.64** | two 11-11 legs, one +$552.23 win |
| cap, regime, 11-11 population | +$790 | **+$815.25, CI +293.26…+1,376.91** | reproduces; the CI was a time slice |
| cap, pre-fix cohort | +$224 | **−$101.87, CI −1,018.22…+536.60** | sign flip on a 62-leg cohort |
| lift $25, all-time | +$2,186 | **+$2,039.47, CI +588.72…+3,611.27** | — |
| lift to $20 (implementable), all-time | +$1,414 | **+$1,318.70, CI +360.50…+2,358.20** | — |
| lift to $20, regime | +$57 | **+$34.67, CI −225.90…+307.11** | still noise |
| max DD all-time (base → cap) | −1,052 → −599 | **−890.49 → −547.82** | both arms re-quoted from one run |
| max DD regime (base → cap) | −938 → −272 | **−776.58 → −225.35** | same |

**Why the drawdown figures moved without a rule change.** The instrument walks the *cumulative*
closed-leg series and takes peak-to-trough. Rows added anywhere before the trough — including legs
that resolved today — change both the peak and the trough. That is why base and arm are always
quoted from the same run, and why the 11-11 numbers must not be mixed with today's.

---

## 3. Measured basis

```
COPYBOT_DB="file:$PWD/prisma/dev.db?mode=ro" python3 scripts/profit-band-clip-preflight.py
COPYBOT_DB="file:$PWD/prisma/dev.db?mode=ro" python3 scripts/profit-band-clip-stability.py
```

- **Cost basis:** `simulatedPositionSize` = **dollars at risk** (never shares, never × price).
- **Dedupe:** first leg per `bot|wallet|market|outcome` within status class.
- **Price:** the wallet's own fill **only** for the INVERTED price-side class; otherwise the booked
  price. PnL rescales linearly in size at a fixed price (so every arm is an *upper bound on thin
  books*, §7).
- **Populations:** all-time **5,710 legs / $64,887**; regime (opened ≥ 2026-10-26, drift gate went
  directional) **274 legs / $5,736**; pre-fix repair cohort (≥ 2026-11-09 09:15:16) **62 legs**.
- **CI:** market-clustered bootstrap, 2,000 draws, on the delta sum.
- **Exposure:** a leg is a risk only if it traded — `unfilled` with a zero payoff is excluded.
- **Not the gate's basis:** the rule's `maxDrawdownPct` (0.20) reads **C-200 net worth vs peak**, not
  this closed-leg series. The drawdown figures below are *closed-leg cumulative* and must not be
  read as the drawdown gate's number.

---

## 4. Evidence

### 4.1 Where the money is (all-time, deduped)

| band | n | avg clip | notional | ntl % | PnL | PnL % | ROI |
|---|---|---|---|---|---|---|---|
| **0.0–0.2** | 521 | **$23.47** | $12,226 | 18.8% | **+$6,928** | **89.7%** | **+56.7%** |
| 0.2–0.4 | 912 | $11.84 | $10,801 | 16.6% | +$1,463 | 18.9% | +13.5% |
| 0.4–0.6 | 1,929 | $9.39 | $18,121 | 27.9% | −$948 | −12.3% | −5.2% |
| 0.6–0.8 | 1,177 | $10.08 | $11,869 | 18.3% | +$245 | 3.2% | +2.1% |
| 0.8–1.0 | 1,171 | $10.14 | $11,871 | 18.3% | +$34 | 0.4% | +0.3% |

**The cap targets the band that earns 9 of every 10 dollars.** Say that out loud before approving:
the $25 cap removes **$4,331 of the cheap band's $12,226 (35% of the band, 7% of the book)** to buy
drawdown. It is not trimming a loser.

### 4.2 Correction C8 — inside the cheap band the clip is NOT inverse to the edge

| 0.0–0.2 clip tier | n | notional | PnL | ROI |
|---|---|---|---|---|
| $0–10 | 171 | $1,326 | +$814 | **+61.4%** |
| $10–15 | 71 | $831 | +$723 | **+87.0%** |
| $15–20 | 118 | $2,173 | +$690 | +31.8% |
| $20–25 | 92 | $1,840 | +$1,525 | **+82.9%** |
| **$25+** | 69 | $6,056 | +$3,176 | **+52.4%** |

The largest clips in the band earn **more per dollar** than the $15–20 tier. If the card's title
("the clip is inverse to edge") were true in-band, the $25+ tier would be the worst; it is second
best. **The inverse-to-edge finding is a CROSS-BAND fact** (cheap band +56.7%, 0.4–0.6 −5.2%, and
the book sizes the dead band *flat*, at $9.39), **not a within-band one**. Capping the cheap band is
therefore a variance trade. It is not "sizing where the edge is".

The same test on the band the lift targets runs the other way:

| 0.2–0.4 clip tier | n | notional | PnL | ROI |
|---|---|---|---|---|
| $0–10 | 488 | $4,060 | +$741 | +18.3% |
| $10–15 | 213 | $2,507 | +$232 | +9.3% |
| $15–20 | 187 | $3,362 | +$453 | +13.5% |
| $20–25 | 12 | $246 | +$151 | +61.5% |
| **$25+** | 12 | $626 | **−$115** | **−18.4%** |

The 0.2–0.4 band's own unclamped tail lost money. That is evidence **against** the lift, from inside
the band the lift is meant to raise.

### 4.3 What the cap binds on — C-200 alone

| lane | cheap-band legs | > $25 | notional > $25 | PnL | ROI | max clip |
|---|---|---|---|---|---|---|
| BANKROLL_200 | 261 | **69** | $6,056 | +$3,176 | +52.4% | **$100.00** |
| STANDARD | 260 | **0** | $0 | $0 | — | $20.00 |

`kellyMaxSizeUsd` = 100 is the only ceiling above $20 on the C-200 Kelly path; `BOT_LIMITS` is
$20.00 for both lanes. A cap of $25 on STANDARD would be a no-op today — and that is what makes the
revert of a lane-scoped field clean.

In the live regime the same 20 legs are the loss:

| pop | n touched | notional | PnL | ROI |
|---|---|---|---|---|
| regime ≥ 2026-10-26 | 20 | $1,900 | **−$563.21** | **−29.6%** |
| pre-fix ≥ 2026-11-09 | 6 | $600 | +$135.83 | +22.6% |

18 of those 20 legs lost money. The two that won: +$222.75 (on $50) and +$552.23 (on $100).

### 4.4 The arms, priced

Delta vs the book as actually sized; pp = delta per dollar at risk; CI on the delta sum.

| pop | arm | delta $ | pp | CI (clustered) | notional old→new |
|---|---|---|---|---|---|
| all-time | **cap $25** | **−2,421.93** | −3.7pp | **−6,320.80 … +877.42** | 64,887 → 60,557 |
| all-time | lift $25 (upper bound) | +2,039.47 | +3.1pp | +588.72 … +3,611.27 | 64,887 → 77,212 |
| all-time | **lift to $20 (implementable)** | **+1,318.70** | +2.0pp | **+360.50 … +2,358.20** | 64,887 → 72,718 |
| all-time | package (cap+lift $25) | −382.45 | −0.6pp | −4,469.42 … +3,005.66 | 64,887 → 72,881 |
| all-time | pkg cap $25 + lift to $20 | −1,103.22 | −1.7pp | −5,184.26 … +2,193.80 | 64,887 → 68,388 |
| **regime** | **cap $25** | **+476.08** | +8.3pp | **−661.04 … +1,362.64** | 5,736 → 4,336 |
| regime | lift $25 | +103.31 | +1.8pp | −304.72 … +525.31 | 5,736 → 6,926 |
| regime | lift to $20 | +34.67 | +0.6pp | −225.90 … +307.11 | 5,736 → 6,441 |
| regime | package | +579.39 | +10.1pp | −583.56 … +1,518.06 | 5,736 → 5,526 |
| pre-fix | cap $25 | −101.87 | −8.0pp | −1,018.22 … +536.60 | 1,281 → 831 |

C-200-only (the cap's actual population — identical delta, its own CI):
regime **+$476.08, CI −544.54…+1,321.10**; all-time **−$2,421.93**; pre-fix −$101.87.

Arm 7b — the lift bounded by what each lane can legally book (legs already > $20 → $25, the rest →
$20, i.e. no `BOT_LIMITS` change): all-time **+$1,318.22** (CI +348.08…+2,358.35), of which C-200
**+$859.27** (CI +171.67…+1,592.97) and STANDARD **+$458.96** (CI −78.56…+1,041.18); regime
**+$34.67** (CI −225.90…+307.11).

### 4.5 Is the delta a tail?

| arm | all-time | regime |
|---|---|---|
| cap | −$2,421.93 → ex-top-1 wallet −$1,654.46, ex-top-2 −$502.56, **ex-top-5 +$550.45** (flips), ex-top-5 markets +$947.60 | +$476.08 → ex-top-1 wallet +$890.25, **ex-top-5 wallets +$777.53**, ex-top-5 markets +$1,001.62 |
| lift $25 | +$2,039.47 → ex-top-5 wallets **+$1,252.47** (61% survives), ex-top-5 markets +$1,887.72 | +$103.31 → ex-top-5 wallets **−$60.17** (flips) |

The cap's all-time "premium" is two wallets' winning draws. That is what a tail-truncating cap is
*supposed* to cost, and it is the strongest thing that can be said for it. The lift's live-window
support is the top five wallets and nothing else.

### 4.6 What the cap buys

| pop | arm | cumulative | worst day | when | max DD |
|---|---|---|---|---|---|
| all-time | book as sized | +$7,721.68 | −$439.32 | 2026-10-26 | −$890.49 |
| all-time | **cap $25** | +$5,299.75 | −$289.32 | 2026-10-26 | **−$547.82 (−38%)** |
| all-time | package | +$7,339.23 | −$289.41 | 2026-09-02 | −$515.63 |
| regime | book as sized | −$37.59 | −$339.83 | 2026-10-26 | −$776.58 |
| regime | **cap $25** | +$438.49 | −$202.43 | 2026-11-04 | **−$225.35 (−71%)** |
| regime | package | +$541.80 | −$321.40 | 2026-11-04 | −$363.04 |

Scale it against the lane's own bankroll: `BotBankroll.BANKROLL_200` principal is **$1,900**, so the
regime drawdown is **41% of principal as sized vs 12% capped**, and a $100 cheap-band clip is **5.3%
of principal at risk per leg** (a $25 clip is 1.3%).

### 4.7 The regime arm's stability — a 20-leg sample, not a measurement

| test | result |
|---|---|
| regime cap delta, today | **+$476.08** |
| leave-one-out, worst removal | +$401.08 |
| leave-one-out, best removal | **+$890.25** |
| spread carried by ONE leg | **+$489.17** |
| same statistic, population cut at 2026-11-11 00:00 | **+$815.25, CI +293.26…+1,376.91** |
| same statistic, population cut at 2026-11-12 00:00 | +$476.08, CI −661.04…+1,362.64 |

Cadence, which sets how long any forward read must wait: **16.1 finished legs/day overall, 3.35/day
in the cheap band** (57 legs in 17 days). A 150-leg pre-registered read therefore lands in about
**45 days** — but only 1.18 cap-touched legs/day arrive, so 150 *touched* legs is **128 days**.

### 4.8 Kelly check — and the honest arithmetic on what $25 assumes

`f* = h − (1−h)·p/(1−p)`, band's own finished record (n=521, hit 20.5%, Wilson-95 lower **17.3%**,
avg price 0.1128, break-even hit rate = 11.3%):

| presumed hit rate | f* | $ at $1,900 principal |
|---|---|---|
| 20.5% (measured) | +10.4% | $198 |
| 17.3% (Wilson lower) | +6.8% | $129 |
| 15.0% | +4.2% | $80 |
| 13.0% | +1.9% | $37 |

Inverted: **$100 is Kelly-consistent if the true hit rate is ≥ 15.9%; $50 at ≥ 13.6%; $25 at ≥
12.4%.** At the measured record — and even at the Wilson lower bound — the current **$100 clips are
not oversized.** So: *a $25 cap is the size that survives the band's hit rate being ~12.5% instead of
~20%*, i.e. it prices in roughly **8pp of hit-rate estimation error** on a 5:1 payoff. That is a
defensible thing to buy. It is not what Kelly says to do.

For the record, the flat allocation the book actually runs is the bigger lever: 0.4–0.6 carries
**27.9% of notional at −5.2%** and the two paying bands carry 35% between them.

---

## 5. Decision rule — what to approve, exactly

### 5.1 The field

**Name:** `c200BandClipCaps`
**Type:** `string` · **default:** `""` (empty = no cap = byte-identical to today)
**Value proposed:** `"0.0-0.2:25"` — comma-separated `lo-hi:capUsd` triples.

Semantics, chosen so they cannot disagree with the two band mechanisms already in the file:

- range parse reuses `parseBandRange` (`src/lib/band-size.ts`): **lo inclusive, hi exclusive**;
- malformed, inverted or unparseable → **disabled** (no throw, no cap);
- the cap **only ever lowers** a size — never raises, never goes below the lane floor;
- **lane-scoped** to `botId === "BANKROLL_200"` at the call site, because that is the only lane that
  can exceed $25 today (§4.3) and because a future `BOT_LIMITS` change on STANDARD should be a
  separate, visible decision.

### 5.2 Where it binds (the patch, not applied)

```
src/lib/rules.ts        interface Rules  + c200BandClipCaps: string;        (default "" in DEFAULT_RULES)
src/lib/band-size.ts    + parseBandClipCaps(s) -> [{lo,hi,capUsd}]          (strict; "" -> [])
                        + applyBandClipCap(usd, price, caps) -> usd        (min only)
src/lib/paper.ts        param bandClipCaps?: string
                        after line 198 `size = clampPaperSize(...)`:
                          if (botId === "BANKROLL_200") {
                            size = applyBandClipCap(size, params.entryPrice, parseBandClipCaps(params.bandClipCaps ?? ""));
                          }
scripts/score-trades.ts next to `bandFactors:` add `bandClipCaps: rules.c200BandClipCaps`
```

Why there and not earlier: `clampPaperSize` (line 198) is the last thing that can *raise* a size;
a cap applied before it would be undone by the `kellyMaxSizeUsd` override. Why it reaches the book:
`openPaperTrade` posts `size` to `:3014/execute`, and the sidecar books
`"simulatedPositionSize": intent.size_usd` verbatim (`rust-sidecar/src/main.rs:194`) — no downstream
re-sizing, so the cap lands on the `PaperTrade` row.

### 5.3 Apply sequence (operator runs; I have executed none of it)

```
# 0. code: the four edits in §5.2 (this IS the rule change; the field alone does nothing)
# 1. dry run (writes nothing, prints the plan):
npx tsx scripts/apply-v73-c200-cheap-band-clip.ts
# 2. apply:
npx tsx scripts/apply-v73-c200-cheap-band-clip.ts --yes
# 3. prove it bound (see §5.4) BEFORE the next monitor cycle
```

`scripts/apply-v73-c200-cheap-band-clip.ts` is written but **has never been run**; it refuses to
write without `--yes`, so an accidental invocation prints the plan and exits.

### 5.4 Enforcement proof required before this is called live

Four checks, all cheap, all required:

1. **Loader spread-merge** — confirmed at `src/lib/rules.ts:508`
   (`{ ...DEFAULT_RULES, ...JSON.parse(rulesJson) }`), so a ruleset that lacks the field arrives as
   `""` → no cap. This is the revert guarantee.
2. **Boundary probe** through loader → field → parser → predicate: price `0.1999 / 0.2000 / 0.2001`,
   clip `24.99 / 25.00 / 25.01`. Expect: 0.1999 capped, 0.2000 **not** capped (hi exclusive), 0.2001
   not capped; 24.99 unchanged, 25.00 unchanged, 25.01 → 25.00.
3. **DEFAULT-empty test** — a ruleset JSON with the field deleted must produce zero capped legs. If
   this ever fails, every ruleset lacking the field silently starts capping: the worst failure mode
   in this class.
4. **Row-level read after one live cycle** — the next `PaperTrade` rows in the band must show
   `simulatedPositionSize <= 25`, and the neighbouring bands must be untouched. Never infer
   enforcement from the absence of a log line (there is none for this path).

### 5.5 Revert

**Delete the field** (or write the previous ruleset version back). Because the default is `""`, a
ruleset without the field is exactly today's behaviour — no code revert, no data migration, no
retro-edit of `PaperTrade` sizing. Revert command: `npx tsx scripts/apply-v73-...ts --revert`
(sets `c200BandClipCaps: ""` and bumps a version).

---

## 6. What would REFUTE this

Pre-registered, on the cap:

- **Cost beats insurance.** On the first **150 settled 0.0-0.2 legs opened after the cap** (~45 days
  at 3.35 legs/day), the shadow on those same legs (actual vs $25-capped) shows a cost above
  **$1,000** with a market-clustered CI excluding zero, **or** the capped band's realised ROI falls
  below **+20%** while a matched uncapped control stays above it → revert.
- **The drawdown does not appear.** Over the next 90 days the capped book's closed-leg max drawdown
  is **not** at least 20% below the uncapped counterfactual on the same legs → the premium was paid
  for nothing → revert.
- **The arm stays unmeasurable.** If the regime delta changes sign again on a single leg across two
  more reads, the arm is not measurable at this flow, and the only defensible basis for the cap is
  the risk-policy one in §1 — which the next read must then confirm explicitly rather than inherit.
- **The binding lane is wrong.** If a forward read shows STANDARD or the legacy C-200 path booking
  cheap-band legs above $25 (impossible today, clamp $20), the scoping in §5 is stale.

On the **lift** — what would reopen it: 150 forward 0.2–0.4 legs with the lift-to-$20 shadow's CI
excluding zero **and** the ex-top-5-wallet delta still positive **and** median realised entry
slippage on the cell ≤ 3.2c (half of ROI@identity × avgP = 20.6% × 0.312 = 6.4c). All three.

On **this document**: if a re-run today of the two commands in §8 does not reproduce §4's tables,
the doc is stale and the decision should wait for a fresh read rather than a remembered number.

---

## 7. What I did NOT verify

- **Fillability of a $100 vs a $25 clip.** Every arm rescales PnL linearly at the *same* price. The
  only in-house evidence on size is booked-vs-intent price — **re-measured today: 206 C-200 legs in
  0.2–0.4 carry `intentPrice`, mean booked − intent = −0.92c (range −2.00…−0.46)**, which is the
  maker credit, not a size effect, and **does not** test a larger clip. The cap's numbers are safer
  than the lift's for this reason alone (it only shrinks), but it is still an assumption.
- **The counterfactual exit path.** Legs are re-sized, not re-exited: a $25 clip that would have
  been closed early at the same time as the $100 leg is an assumption of the instrument.
- **Raising the $20 clamp** — the lift's precondition. Priced (§4.4 arm 7b), not proposed: it is a
  book-wide risk change and belongs in its own card.
- **The drawdown gate's own number.** `maxDrawdownPct` reads C-200 net worth vs peak, not the
  closed-leg series used here. Nothing in this doc claims the gate's state.

---

## 8. Where the numbers come from

| script | role | state |
|---|---|---|
| `scripts/profit-postfix-integrity.py` | the base instrument (edge, sizing, bands, ladder) | **edited today**: reads `COPYBOT_DB` and opens it with `uri=`, so a `file:…?mode=ro` read is provable. Behaviour unchanged when the env var is unset. |
| `scripts/profit-band-clip-preflight.py` | cap/lift arms, per-lane binding, tails, drawdown, per-lane clamp bounds (§4.3–4.6) | **landed today** from the unmerged `t_5d213302` worktree, where the 11-11 read was produced and where it had been left untracked — the 11-11 draft cited a script that was not in the repo |
| `scripts/profit-band-clip-stability.py` | allocation, in-band clip tiers, leave-one-out, cadence, time-slice test (§4.1, 4.2, 4.7) | **new today** |
| ad-hoc: Kelly inversion (§4.8) | hit-rate ↔ clip arithmetic | run from the same loader; the four lines are in the doc and the derivation is reproducible from `f* = h − (1−h)p/(1−p)` |

Reproduce:

```
cd ~/polymarket-copybot
COPYBOT_DB="file:$PWD/prisma/dev.db?mode=ro" python3 scripts/profit-band-clip-preflight.py
COPYBOT_DB="file:$PWD/prisma/dev.db?mode=ro" python3 scripts/profit-band-clip-stability.py
```

Context read used for §4.6 and the ladder line: trailing-7-settled-day PnL (**+$214.04**) against
rung 1's own gate (**250 × 7 = $1,750**) — the ladder is **8.2× short**, so a drawdown on the lane's
$1,900 principal is the binding constraint on advancing, not marginal carry.

**Nothing was applied.** No `apply-v*` run, no `RuleSet` row, no write to `prisma/dev.db` (both
instruments open it `mode=ro` and the run is proven by the `DB:` header line), no commit to `main`,
no `PaperTrade` row touched. `data/approvals.json` untouched by me — the intake cron owns it.

---

## 9. Operator decision

1. **Cap `0.0-0.2` at $25 (C-200 only)** — recommended **YES**, as a risk rail. Expected PnL cost is
   indistinguishable from zero (−$2,421.93 all-time, CI −6,320.80…+877.42; ex-top-5 wallets +$550.45);
   the purchased effect is real (−$776.58 → −$225.35 regime, −$890.49 → −$547.82 all-time).
   *Override to decline if you would rather keep the +52.4% tier uncapped and re-read in 45 days —
   the losing branch's price is the 41%-of-principal regime drawdown.*
2. **Lift `0.2-0.4` to $25** — recommended **DEFER** (+$34.67 implementable in the regime, CI
   −225.90…+307.11; ex-top-5 wallets −$60.17; the band's own ≥$25 tail is −18.4%).
3. **Lane scope: C-200 only** — recommended **YES** (STANDARD cannot reach $25; a lane-scoped field
   keeps that lane byte-identical and keeps any future clamp change a separate decision).
4. **Pre-registered 150-leg re-read at ~2026-12-27** — recommended **YES**, with the §6 refutation
   verbs recorded on the card so the read cannot be re-interpreted after the fact.
