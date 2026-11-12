# C-200 settle-vs-stamp ordering — is the class still accruing, and what does a reconciliation pass cost?

**Status:** LANE A PROPOSAL. Nothing applied, no `prisma/dev.db` write, no `data/c200-drawdown.json` write,
no RuleSet change, no merge. Every number below comes from `scripts/c200-fill-ordering-audit.py`
(read-only, `mode=ro`), committed with this document.
**Measured:** 2026-11-12T20:20:39Z (DB mtime 2026-11-12T20:15:52Z).
**Card:** t_c9312d68 · parent t_bb9577ae (`drafts/c200-intent-link-repair-20261112.md`) · sibling t_12711fe0.

---

## 0. The headline, in the order the card asked for it

1. **The class is not accruing. It has not accrued since 2026-10-30.** Re-measured today: **247 legs /
   +$828.66** on $2,234.47 notional, settled **Sep 40 (−$67.10) / Oct 207 (+$895.76) / Nov 0**. Last member:
   a leg that settled **2026-10-30T18:43:04Z** and was stamped 38 minutes later. Thirteen days, zero additions.
2. **But the 247 is not evidence that the ordering was ever fixed — 246 of the 247 are one backfill pass.**
   Every fill stamp in the DB was written on/after **2026-10-28**; 385 landed that day in the resolver's first
   `--apply` over a three-week backlog of legs that had **already settled** (median stamp lag from settlement
   **498.9 h**, max **766.8 h**). Those legs never raced anything — the instrument arrived after they finished.
3. **The only live event is one leg, +$27.57.** Since the backfill (`settle date ≥ 2026-10-29`): **3 settle-first
   legs out of 275 settled** — 1 stamped `unfilled` (+$27.57, enters the class) and 2 stamped `filled`
   (−$117.99, booking was correct anyway).
4. **It is not "a slow month".** November is not quiet — 275 legs settled since 2026-10-29 and 187 new stamps
   landed in its first 11 days — and the stamp-before-settle path is demonstrably working at volume: **136 legs
   were stamped `unfilled` and then settled, booking $0** where the old ordering would have booked **+$172.28**.
   The 0 is a real effect of the stamp generally arriving hours before the market resolves, not an absence of
   settlements — but it is a property of **timing**, not an invariant the code enforces.
5. **The mechanism is still unsafe, and the channel that keeps it unsafe is not the race — it is the missing
   link.** `resolvePaperTrade()` reads `fillStatus` once, at write time, and nothing ever revisits it;
   `c200-fill-resolve.ts` can only stamp legs its `FillIntent.paperTradeId` points at. **100% of the 84 legs
   opened since the flip that carry no stamp are unlinked** (216 settled unlinked legs in the intent era,
   +$1,216.31 booked). They cannot be stamped late, so they are never restated. They are not in the class only
   because the class is defined by the stamp.
6. **Option (b) as written is already the code, and would not have caught the one live event.** The evidence the
   verdict needs is produced by the same 2-hourly chain: for that leg the first print-through snapshot
   containing its intent is stamped **19:21:41Z — 38 minutes after settlement**. A synchronous settle-time
   consult returns "no evidence → book optimistically" exactly as today. Only a pass that runs **when the stamp
   lands** (option (a)) can close the class.

---

## 1. The defect, in code

| site | what it does | why it matters |
|---|---|---|
| `src/lib/paper.ts:47-51` `bookedPnl()` | `if (leg.fillStatus === "unfilled") return 0` | reads the stamp **at write time only** |
| `src/lib/paper.ts:374-405` `resolvePaperTrade()` | `if (trade.status === "resolved") return trade` (line 379), then books `realizedPnl = bookedPnl(...)` | an already-resolved leg is **never re-booked**, so a stamp that lands afterwards cannot correct it |
| `src/lib/paper.ts:488-529` `closePaperTrade()` | `if (trade.status !== "open") return trade` | same for early exits |
| `scripts/c200-fill-resolve.ts:174-180` | writes **only** `fillStatus` / `fillBasis` / `fillResolvedAt` | the resolver deliberately never touches PnL — so "stamped later" never means "re-booked" |
| `scripts/update-pnl.ts` | the **only** settler (`resolvePaperTrade` at :145/:193/:217, `closePaperTrade` at :154/:258/:271); runs every **60 m** | settlement has no opinion about the evidence; it reads whatever stamp exists |
| `scripts/cron-scripts/copybot-c200-fill-chain.sh` | stage 1 `c200-printthrough.py` (134 MB artifact), stage 2 `c200-fill-resolve.ts --apply`; `no_agent`, **every 120 m** (job id `974a391c2598`) | the stamp's whole latency budget |

Consequence: `fillStatus='unfilled' ⇒ realizedPnl=0` is a **write-time coincidence**, not a stored invariant.
Violated on 247 rows today. Between them and the next violation there is nothing but scheduling luck.

---

## 2. The 247, re-measured (dated 2026-11-12T20:20:39Z)

| | legs | booked | notional |
|---|---|---|---|
| **class total** | **247** | **+$828.66** | **$2,234.47** |
| winners | 84 | +$2,175.35 | |
| losers | 163 | −$1,346.69 | |
| settled Sep | 40 | −$67.10 | |
| settled Oct | 207 | +$895.76 | |
| settled **Nov** | **0** | **$0.00** | |

Card's figures reproduce exactly (247 / +$828.66 / $2,234.47 / 84 / 163). Card's month split differs in detail:
it reports Oct **207 / Nov 0** by *settle* month; measured Sep 40, Oct 207, Nov 0 — same.

### 2a. Composition — one backfill, one live tick

| stamped on | legs | booked | median lag, stamp − settle | max |
|---|---|---|---|---|
| **2026-10-28** (first `--apply` pass, 385 stamps total) | **246** | **+$801.09** | **498.9 h (20.8 d)** | 766.8 h (31.9 d) |
| any later tick | **1** | **+$27.57** | 0.64 h | 0.64 h |

The one live row: dispatch `2026-10-30T17:14:52Z` → settled `18:43:04Z` → stamped `19:21:42Z`.

---

## 3. Is the ordering safe now? — the windows, enumerated

A leg can be booked optimistically in four distinct windows. Only the first is a race; the other three are
structural and larger.

**W1 — evidence-production lag (the race).** A new intent gets its first print-through snapshot at the next
chain tick. Measured over the 196 live-stamped legs: **dispatch → stamp min 0.1 h · median 1.5 h · p90 2.4 h ·
max 2.6 h**. Inside that window a leg has no stamp, so if it settles it books at p=1. A market must resolve
within hours of being copied for this to fire — rare here (book median time-to-resolution is ~115 days) but not
impossible, and exactly what happened on 10-30.

**W2 — the link race (never stamped at all).** The resolver reaches a leg only through
`FillIntent.paperTradeId`. 219 of 802 intents (27.3%) never got it written (`t_bb9577ae` §2). Those legs stay
`fillStatus NULL` **forever**, which means the fill-aware model never governs them, no matter how long they sit
settled. They carry +$1,216.31 of optimistic booking today; 100% of the post-flip unstamped population (84 legs,
$2,751.94, +$456.02) is this class. **A late stamp would put them in the class; there will be no late stamp.**

**W3 — evidence gap.** Linked, but the artifact holds no verdict (neither book window nor tape). The resolver
correctly refuses to stamp. **1 leg today** ($20.00, −$20.00, opened 2026-10-03). Small, permanent.

**W4 — scope boundary, not a defect.** 2,028 C-200 legs predate the instrument and have no `FillIntent` at all
($15,955.20 notional, +$3,708.05 booked at p=1). Only **802 of 2,830** C-200 legs hold an intent record at all,
so a stamp is reachable for at most **28.3%** of the book. Any claim that "the C-200 book is fill-aware" is true
of that slice.

### 3a. Per-week ledger since the flip (UTC settle weeks, C-200 non-demo)

| settle week | settled | stamp_first | settle_first | unstamped | class (n) | class ($) |
|---|---|---|---|---|---|---|
| 2026-W42 (Oct 19–25) | 40 | 0 | 32 | 8 | 22 | −$48.82 |
| 2026-W43 (Oct 26–Nov 1) | 46 | 18 | 14 | 14 | 9 | +$5.93 |
| 2026-W44 (Nov 2–8) | 140 | 91 | **0** | 49 | **0** | $0.00 |
| 2026-W45 (Nov 9–15) | 111 | 86 | 2 | 23 | **0** | $0.00 |

W43's 14 `settle_first` legs are the backfill, not races (they settled on 10-26/27 and were stamped on 10-28).
Daily, from the backfill onward, `settle_first` is 0 on every day except **2026-10-30 (1)** and
**2026-11-10 (2)**.

### 3b. "November shows 0 — real fix, or slow month?" → real effect, wrong reason

- **Not slow.** 275 legs settled since 2026-10-29; 11 days of November carry 187 new stamps.
- **The safe ordering is real and load-bearing:** **136 legs** were stamped `unfilled` *before* settling and
  booked **$0** — under the old ordering they would have booked **+$172.28** on $3,244.60 of notional. That is
  ~21% of the entire class's PnL, avoided in 15 days.
- **But it is scheduling luck, not code.** No commit changed the ordering since the flip (`c6222f7` only
  defaulted `FILL_AWARE_BOOKING` on; `98459a6`/`f9fa392`/`9884684` are rules and reporting fixes). The ordering
  is safe because **stamp latency (median 1.5 h) ≪ time-to-resolution (days)**, and because the backlog was
  drained in one pass. The two settle-first legs on 2026-11-10 (32-minute lag) prove the window is still open;
  they happened to be `filled`, so the optimistic booking was also the correct one.

---

## 4. If it recurs, which fix? — priced

### (a) Reconciliation pass appended to the fill chain — **recommend**

Predicate written as the **invariant**, not a delta:
`botId='BANKROLL_200' AND fillStatus='unfilled' AND realizedPnl<>0` → set `realizedPnl=0`.
Per row, inside one transaction: re-read the row, if it still matches, write 0 and move
`BotBankroll.realizedPnl` and `cashBalance` by **−row.realizedPnl**; else skip. Idempotent by construction
(after the write the row no longer matches; a second run finds 0 rows).

| | today | after the pass |
|---|---|---|
| legs restated | — | **247** |
| `realizedPnl` (row sum = bankroll, drift $0.00) | 5,638.38 | **4,809.72** |
| `cashBalance` | 7,120.66 | **6,292.00** |
| accounting identity `principal + realized − open notional (417.72)` | 7,120.66 ✓ | **6,292.00 ✓** |
| net worth (realized basis) | 7,538.38 | **6,709.72** |
| trailing-7d settled PnL (ladder input) | +$190.03 | **+$190.03 (unchanged — 0 class legs in the window)** |
| effective exposure cap | 3,819.19 | **3,404.86** |

Cost: ~120 lines TS (or 60 Python next to the chain), dry-run default, backup JSON, one log line appended
**after** the chain's report line, runtime ~1–2 s for 247 rows. Risk: it moves realized PnL, cash and net worth
→ published figures → Lane A, and it must land **with** a watermark decision (§5). Race-safety with the
concurrent `update-pnl` is the only real engineering point: re-read inside the write transaction, never
decrement by a pre-computed batch total.

### (b) "Make settlement consult the stamp synchronously" — **already the code; cannot close the class**

- `resolvePaperTrade` *does* consult the stamp at settle time (`paper.ts:381`). There is nothing to add there.
- A genuine strengthen-the-consult version would resolve the verdict inline from the artifact. For the one live
  event that is provably useless: **the first artifact snapshot containing that intent is
  `2026-10-30T19:21:41Z`, 38 minutes after the leg settled**. At settle time the evidence did not exist, so the
  answer is "unresolved" and the leg books at p=1 anyway — identically to today.
- The two variants that *would* remove the class are both bigger than they look:
  - **b1 — defer the booking:** settle the leg but leave `realizedPnl` NULL until a stamp exists. Blast radius:
    `BotBankroll` increments at settle, the dashboard, `capital-data`, `report`, `rule-updater`
    (`realizedPnl: { not: null }`) — rows would silently vanish from sums; ~10 read sites to audit. **High cost,
    and it changes published figures at settle time rather than in a controlled pass.**
  - **b2 — re-book when the stamp lands:** that *is* (a), triggered from the resolver instead of the chain.
    No separate design.

Cost of (b) as specified: **zero, because it is already implemented**. Cost of b1: high. b2: = (a).

### (c) Both — **the honest version of "both" is (a) + the link repair**

(a) is the safety net for anything that gets stamped late. The population that can never be stamped late
(W2) belongs to `t_bb9577ae`'s approved scope (link 201 pairs, restate 376 legs, rebase the peak), not to an
ordering change. Neither (a) nor (b) reaches those 216 legs.

### Recommendation

1. **(a), shipped inside the `t_bb9577ae` release**, with the invariant as its predicate — it then restates the
   247 of that release's 376 rows idempotently and finds 0 rows the moment the release lands. Do not ship it as
   a separate earlier restatement: the operator would be asked to approve the same $828.66 twice.
2. **Do not ship (b) as specified** — it is a no-op. Record the finding so the next session doesn't re-propose it.
3. **Pre-register the trigger for b1** (deferred booking) instead of building it now: revisit if settle-first
   `unfilled` legs exceed **2 per week** measured over two consecutive weeks, or any single event books >$50.
   Current rate: 1 event in 15 days, $27.57.
4. **A Lane B companion is available and cheap:** teach the existing `copybot-c200-intent-watch` watchdog to
   report `count(fillStatus='unfilled' AND realizedPnl<>0)` and the unlinked-intent count. It changes no figure,
   so it is a repair, not a proposal — it makes the invariant observable between releases. Not shipped here
   because this card is a proposal; say the word and it is a one-block change.

---

## 5. Interaction with `t_12711fe0` (drawdown watermark) — measured

The gate's basis is **realized** (`RuleSet` v72: `ddBasis='realized'`, `maxDrawdownPct=0.20`,
`maxGrossExposureUsd=1000`), so net worth = principal + realized = **7,538.38**. The watermark is a monotone
ratchet: `data/c200-drawdown.json` holds `realizedPeak = 11,068.58` (`peak = 11,458.63`), while the ledger's own
high-water mark recomputed from `PaperTrade` is **7,987.32 @ 2026-10-18T19:10:41Z**.

| scenario | net worth | peak used | DD | 20% gate |
|---|---|---|---|---|
| today | 7,538.38 | 11,068.58 (stored) | **31.89%** | TRIPPED |
| (a) restatement only, **no rebase** | 6,709.72 | 11,068.58 (stored) | **39.38%** | TRIPPED (deeper) |
| (a) + rebase to the standing ledger HWM | 6,709.72 | 7,987.32 | **16.00%** | **open** |
| (a) + rebase to the corrected HWM (class zeroed) | 6,709.72 | 7,083.32 | **5.27%** | **open** |

So: **a restatement without a rebase re-closes a gate that is already shut** — exactly the trap the sibling
card exists to prevent. The gate is currently shut for the whole portfolio (0 C-200 opens since
2026-11-11T18:10:56Z), so the practical cost of "no rebase" is zero *today* and permanent the moment the lane
is otherwise cleared.

Two facts that make the sequencing cheap:
- **The trailing-7d ladder does not move.** 177 legs / +$190.03 settled in the last 7 days; **0** of them are
  class members. Restating history leaves the phase gate where it is.
- **The corrected HWM for this scope is 7,083.32**, not the 5,935.46 in the parent's 376-leg release. Restating
  247 rows alone lowers the HWM by $904.00 (the class PnL that had accrued by 2026-10-18), so the two scopes
  need different rebase targets — another reason to land them as one release rather than two.

---

## 6. What I did not touch

`prisma/dev.db` opened `mode=ro` only; `data/c200-drawdown.json` not written (md5 unchanged, mtime 2026-11-10);
no `apply-vNN` run; RuleSet still v72; no resolver `--apply`; no merge. The only `--apply`-capable command in
this document is the operator's, and it is not written out here because the release sequence is `t_bb9577ae`'s
call, not this card's.

---

## 7. Overridable flags (each carries the number that changes)

1. **Ship (a) inside the `t_bb9577ae` release, not before it** — carrying *$828.66 of a $2,299.78 release*;
   splitting them asks for the same restatement twice and produces two different rebase targets
   (**7,083.32** vs **5,935.46**).
2. **(b) is not a fix — it is already the code** — carrying *0 of 247 rows closed*; the evidence for the only
   live event arrived 38 minutes after settlement, so no settle-time consult could have caught it.
3. **Trigger for deferred booking (b1), not a build** — carrying *>2 settle-first unfilled legs per week over
   two weeks, or a single event >$50*; measured rate today is 1 event / 15 days / $27.57.
4. **Rebase target if (a) ever ships alone** — *16.00% vs the standing HWM 7,987.32* (5.27% against the
   corrected 7,083.32); without any rebase the pass lands at **39.38%**, deeper than today's 31.89%.

## 8. What would refute this

- A settle-first `unfilled` leg appearing **without** a >1 h lag (i.e. the stamp lost a same-tick race) →
  the window is wider than the chain cadence and (a)'s cadence assumption is wrong.
- Any post-2026-10-30 class member → the "class stopped accruing" claim is stale; re-run §1/§2 first.
- A `FillIntent.paperTradeId` backfill that turns the 216 unlinked settled legs into stamps → the W2 population
  moves into the class and the restatement scope changes again (this is `t_bb9577ae`'s applying).

## Reproduction

```bash
cd ~/polymarket-copybot && python3 scripts/c200-fill-ordering-audit.py          # full read-only report
cd ~/polymarket-copybot && python3 scripts/c200-fill-ordering-audit.py --json   # + machine-readable tail
```
Sections: §1 class re-measure · §2 stamp composition (backfill vs live) · §3 ordering ledger · §4 live stamp
cadence · §5 counterfactual saved · §6 residual channels · §7 pass economics & gate · §8 bottom line.
