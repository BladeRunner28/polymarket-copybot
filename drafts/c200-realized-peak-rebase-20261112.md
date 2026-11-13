# C-200 realized drawdown watermark — rebase proposal

**Lane A · PROPOSAL ONLY · 2026-11-12**
Approval: `apr-c200-realized-peak-rebase` (clicked 2026-11-12T16:45:09Z) · source card `roadmap:c200-realized-peak-rebase`
Board card: kanban `t_12711fe0` · **rev 2 — review round 1 answered (§11): the apply path now writes the number it
confirms, and no longer moves the era baseline.**

> **Nothing has been applied.** `data/c200-drawdown.json` is untouched, `prisma/dev.db` was opened read-only
> (`mode=ro`) for every measurement below, no `scripts/apply-vNN.ts` was run, no RuleSet was written (still **v72**),
> no branch was merged. The apply step is §7 and it is yours.

---

## Verdict

**C-200 is halted by a denominator that no longer exists, and it cannot restart itself.** The approved ledger repair
`d974287` removed **$3,843.89** of C-200 `realizedPnl` that had been booked on sibling-complement prices. The drawdown
gate divides by a watermark that was ratcheted from the *pre-repair* prices, and that watermark can only ever ratchet
**up** — so the correction pushed the lane over the 20% gate and nothing inside the lane can push it back.

Measured now (2026-11-12 16:50 UTC):

- gate basis `realized`, **DD 31.95%** vs `maxDrawdownPct` 0.20 (RuleSet v72) — the live log prints `DD 32.0%`
- net worth would have to reach **$8,854.86** to clear it: **+$1,322.92** while the gate forbids opening a single leg
- that is **23.5%** on top of the lane's entire lifetime realized PnL ($5,631.94) — unreachable by waiting
- **0** C-200 copies since 2026-11-11 18:43 UTC (22h 07m), **81** `[PRE-LOOP HALT]` lines, **384** gate-blocked
  decisions today, last one 16:43:56 UTC. The sidecar is up (`POST :3014/execute` → 422, last
  `Skipped execution` 2026-09-02), so **the gate is the only thing holding the lane shut.**
- **The halt is not C-200's alone.** The block is pushed into `riskGates` in the shared `paper_copy` path
  (`score-trades.ts:651-720`) and matched by `isPortfolioGate()`, so it fires for **both books**: STANDARD's last open is
  **2026-11-11 17:15:56 UTC** and it has opened **0** legs since, against 5–14/day on the preceding week, with
  **409 open legs / $4,483.12** sitting untouched. Waiting on option D therefore costs the whole stack's flow, not
  just the halted lane's.

**Recommendation: rebase `realizedPeak` 11,068.58 → 7,987.32** — the corrected ledger's own realized high-water mark.
That restores DD to **5.70%** (gate open, 14.3pp of headroom) and keeps a real watermark instead of erasing one.

**Two corrections to the approved item, both flagged in §8:**
1. The card's **7,548.21** is *today's realized net worth at the 12:07 UTC close*, not a watermark; NW has since moved to
   **7,531.94** (15:10 close). Rebasing to today's NW sets DD to 0.00% and makes the peak a function of *when an operator
   last intervened* — the file's own `peakRule` calls a reset "a deliberate act". **Flag 1.**
2. The approved number is also **$439.11 below what the ledger supports**: under the corrected ledger the book's highest
   realized equity was **$7,987.32** (2026-10-18 19:10 UTC). That is the number that restores the gate rather than
   neutering it. **Flag 1.**

---

## 1. What the gate does, and why a rebase is the only exit

`scripts/score-trades.ts`:

| line | what it does |
|---|---|
| 101–107 | C-200 net worth = `principal + BotBankroll.realizedPnl` (+ open unrealized on the MTM basis); peak persisted in `data/c200-drawdown.json` |
| 154–166 | loads the state file, then **ratchets**: `if (realizedOnlyNW > realizedPeak) realizedPeak = realizedOnlyNW` — monotone, nothing lowers it |
| 188–191 | declared basis (`rules.ddBasis` → `realized`) picks `basisPeak` / `basisNetWorth`; `DD = (peak − NW) / peak` |
| 695–697 | trips when `DD > rules.maxDrawdownPct`; journals `drawdown gate [realized] (net worth $… vs peak $… = …% > 20%)` |
| 720 + `src/lib/exposure-cap.ts:122` | `isPortfolioGate()` ⇒ the block fires **before** the per-leg loop: no copies, no leg-block reasons |
| 1382–1407 | `[PRE-LOOP HALT]` line every halted cycle + one Discord alert per 6h |

Consequence, and it is the whole card: **a ledger correction is one-directional and the gate is not.** `d974287` moved
`realizedPnl` down by $3,843.89 and posted the same delta to the bankroll (verified in the pre-image manifest:
`BANKROLL_200` pre `realizedPnl 8,913.40 / cash 9,603.64` → post `5,069.51 / 5,759.75`). The watermark stayed at 11,068.58.
The only ways out are (a) earn back $1,322.92 with the lane halted, or (b) correct the watermark. (a) is not a plan.

**No existing lever can do (b).** `scripts/apply-v56-drawdown-basis.ts:99-102` is the documented reseed path
(`--reseed-peak`) and it writes `realizedPeak = Math.max(realizedNW, realizedPeak)` — a floor, so a downward rebase is
inert: run today it would leave the watermark at 11,068.58 with a refreshed `updatedAt` and the lane still halted. That
is why the apply needs a new, purpose-built lever (§7) rather than a flag on the old one.

## 2. Timeline, from the log (not from the card)

| UTC | run | declared basis | DD | NW | state |
|---|---|---|---|---|---|
| 2026-11-11 18:33:43 | 12:33 CST, last pre-repair | realized | **2.3%** | $10,813 | open |
| 18:39–18:43 | `d974287` applied (233 rows repriced, bankroll delta posted, 196 snapshots corrected) | | | | |
| 18:43:43 | 12:43 CST, first post-repair | realized | **37.0%** | $6,970 | **HALTED** |
| 2026-11-12 16:43:43 | 10:43 CST, latest | realized | **32.0%** | $7,532 | HALTED |

Verbatim, lines 169430 / 169449 of `logs/cron/copybot-monitor-score.log`:

```
[DRAWDOWN-SHADOW] basis=realized 2.3% (peak $11069, NW $10813) | MTM 5.2% (peak $11459, NW $10863) vs realized-only 2.3%
[DRAWDOWN-SHADOW] basis=realized 37.0% (peak $11069, NW $6970)  | MTM 38.7% (peak $11459, NW $7019) vs realized-only 37.0%
```

The card's "one tick" claim is exactly right: the repair and the first halt are the same 12:43 minute. The flat $11,069
peak across both lines is the ratchet doing what it is designed to do — and the NW recovering from $6,970 to $7,532
(11 legs closing while halted) has moved DD only from 37.0% to 32.0%.

## 3. What the corrected ledger says the watermark is

**The verdict comes from the repo's own instrument, not from a new one.**
`python3 scripts/c200-drawdown-attribution.py` was written for exactly this question ("is the gap between `realizedPeak`
and current realized NW settled losses, or a restatement artifact?"), is read-only, and is already committed. Its output
today (2026-11-12 16:52 UTC):

```
S1  STATE
    principal              $   1900.00
    BotBankroll.realizedPnl $   5631.94   cash $7104.30
    PaperTrade ledger sum   $   5631.94   (2819 settled legs)
    drift (row vs ledger)   $      0.00   <- non-zero means the row is not the sum of its rows
    declared basis          realized   (basisDeclaredAt 2026-09-18T10:05:42.444Z)
    watermark realizedPeak  $  11068.58   (peak mtm $11458.63, updatedAt 2026-11-10T08:26:53.686Z)
    realized NW             $   7531.94
    drawdown on that basis    32.0%   gate at 20.0%
    clears when NW >=       $   8854.86   (gap $1322.92)

S2  WATERMARK PROVENANCE (repaired ledger, current realizedPnl values)
    watermark implies cumulative realized PnL      $   9168.58
    ledger peak cumulative PnL                    $   6087.32  (at 2026-10-18T19:10:41Z)
    ledger current cumulative PnL                  $   5631.94
    corrected high-water mark NW                  $   7987.32
    corrected drawdown today                              5.70%
    watermark ABOVE the ledger's own high-water mark     $   3081.26
    VERDICT: the watermark is inflated by $3081.26 — the drawdown it reports is an
             artifact of a ledger restatement, not settled losses.

    realized-basis era (since 2026-09-18T10:05:42.444Z): 1057 settle events, corrected max drawdown 13.53% at 2026-11-11T08:40:53Z
    -> on a clean ledger the gate WOULD NOT have fired in this era.
    whole-life corrected max drawdown 28.62% at 2026-08-04T15:54:52Z (before the era this gate read MTM)

S3  DISCONTINUITY SCAN  (copybot-monitor-score.log, 7464 runs with a shadow line)
    2026-11-11T12:32:43      10813.00      6970.00     -3843.00   [2026-11-11T12:43:43]
    2026-09-25T12:29:15       4299.00      4099.00      -200.00   [2026-09-25T12:40:15]
    ...
    largest step is 19.2x the next largest -> a single-event discontinuity (restatement or re-basing), not a settlement batch
```

That is the whole case in one page: the watermark implies **$9,168.58** of cumulative realized PnL; the repaired ledger's
own peak is **$6,087.32**; the excess is **$3,081.26**; and the monitor's own series shows the fall arriving as a single
**−$3,843** step, **19.2×** the next largest one-cycle move — real losses do not settle in one tick.

**Independently corroborated.** Card `t_02fb099d` (Lane A) asked for exactly this attribution and shipped the instrument
plus `drafts/c200-drawdown-attribution-20261112.md`; reaching the corrected peak of **$7,987.32** there and here is two
sessions measuring the same number from the same ledger. That session also re-measured the roadmap card's note for
`c200-realized-peak-rebase`, which is why the target on the card is now the corrected peak rather than the net-worth
reading this proposal started from (**Flag 1**).

`scripts/c200-drawdown-rebase.py` (new, shipped with this proposal, `python3 scripts/c200-drawdown-rebase.py`, dry-run,
writes nothing) is the **apply-side companion**: it recomputes the same corrected high-water mark, prints the proposed
state file, and is the only thing that would ever write it. Full output in §10. Additional checks it adds:

**Ledger integrity first — a watermark is only worth the ledger under it:**

| check | measured | verdict |
|---|---|---|
| Σ finished-leg `realizedPnl` vs `BotBankroll.realizedPnl` | $5,631.94 vs $5,631.94 | offset **$0.00** |
| cash identity `principal + realized − open notional` | 1,900 + 5,631.94 − 427.64 = $7,104.30 vs stored $7,104.30 | ✓ |
| finished C-200 legs contributing to the curve | 2,819 | — |
| duplicate `(decisionJournalId, marketId, outcome)` groups | **0** | curve not inflated by sweep duplicates |
| distinct end timestamps | 2,819 of 2,819 | peak is **order-invariant** (no tie to shuffle) |

**The corrected realized equity curve** (principal + cumulative realized, ordered by each leg's own end time —
`closedAt`, else `resolvedAt`):

| figure | value |
|---|---|
| high-water mark | **$7,987.32** at 2026-10-18 19:10 UTC |
| current | $7,531.94 → **5.70%** |
| deepest drawdown, all history | 28.62% (2026-08-04, on a $1,910 young-lane book) |
| since `basisDeclaredAt` 2026-09-18, by settlement date (56 dates) | median **2.9%**, p90 **8.1%**, max **13.53%** (2026-11-11), **0** dates over 20%, 2 over 10% |

So on the prices that are now the ledger's truth, **the 20% gate has never been breached since the realized basis was
declared**, and today's 5.70% sits inside the normal range (median 2.9%, p90 8.1%). The stored watermark of $11,068.58 is
not reproducible from any corrected-basis statistic; on the same definition the corrected ledger's maximum is $7,987.32.
($11,068.58 *was* reproducible pre-repair — it is 1,900 + a `realizedPnl` of 9,168.58 that the ledger no longer contains.)

## 4. Candidate targets

| | target | DD now | 20% trip line | un-halts? | note |
|---|---|---|---|---|---|
| **B — recommended** | **7,987.32** | **5.70%** | $6,389.86 | **yes**, 14.3pp headroom | corrected ledger high-water mark; measured, order-invariant, reproducible |
| A (as approved) | 7,548.21 | 0.22% | $6,038.57 | yes | a net-worth reading (12:07 UTC close), already stale; gives back 5.48pp of real drawdown. Reachable on purpose: `--apply --confirm 7548.21 --force` writes exactly this (§11) |
| A′ (today's live NW) | 7,531.94 | 0.00% | $6,025.55 | yes | maximally generous; makes the watermark an intervention timestamp |
| C (naive subtraction) | 11,068.58 − 3,843.89 = 7,224.69 | — | — | yes | **degenerate**: below NW, so the next run ratchets it to 7,531.94 and it collapses into A′ |
| D (do nothing) | 11,068.58 | 31.95% | $8,854.86 | **no** | needs +$1,322.92 with 0 new legs — the deadlock |

Why B and not A/A′:

1. **B is exactly "watermark minus the inflation the instrument measures".** `c200-drawdown-attribution.py` puts the
   excess at **$3,081.26**; B removes **$3,081.26**. A′ removes **$3,536.64**, i.e. $455.38 more than the artifact —
   that difference is **real drawdown the book actually took** from 10-18 to now, and writing it off makes the watermark
   a function of when an operator last looked.
2. **Precedent here resets to a seeded/measured baseline, never to "current".** The 2026-09-18 correction switched the
   basis because the MTM gate froze both lanes while "the realized ledger never breached ~3%"; the kalshi reprice
   corrected rows. Neither wrote "whatever NW is right now" into the peak.
3. **It costs the lane nothing operationally.** B un-halts immediately with 6.8pp more headroom than the worst corrected
   drawdown ever observed (13.53%). A′ buys $455.38 of extra risk budget (A $439.11) for a dishonest denominator.
4. **It is verifiable.** `--confirm` must match the computed peak to the cent when you take the default, and the
   written value is always the confirmed one — a `--force`d number is still re-checked against the gate and against
   NW before anything is written (§7, §11). A′ requires trusting a hand-typed number that will be stale within the
   hour (it already is).

## 5. Before/after — every figure that moves

| figure | now | after B | basis of the number |
|---|---|---|---|
| `data/c200-drawdown.json` `realizedPeak` | 11,068.58 | **7,987.32** | state file |
| `peakResetAt` / `peakResetFrom` (audit, new keys) | absent | **added** — apply timestamp / 11,068.58 | state file; the scorer spreads unknown keys forward, so they survive |
| `basisDeclaredAt` (era baseline) | 2026-09-18T10:05:42.444Z | **unchanged** | the basis does not change; re-stamping it forward empties the `since basisDeclaredAt` series and crashes the instrument (§11.2) |
| gate DD, declared basis `realized` | **31.95%** | **5.70%** | `(peak − 7,531.94)/peak` |
| gate state on next cycle | HALT (384 blocks today) | **open** | `score-trades.ts:695` |
| NW needed to clear the gate | $8,854.86 (+$1,322.92) | **none** (5.70% vs 20%) | `peak × 0.8` |
| 20% trip line | $8,854.86 | **$6,389.86** | `peak × 0.8` |
| exposure cap (equity-linked, NW-based) | $3,815.97 | **$3,815.97** | `1,000 + 0.5 × (NW − 1,900)`; peak is not an input |
| C-200 `principal` / `realizedPnl` / `cash` | 1,900 / 5,631.94 / 7,104.30 | unchanged | DB untouched |
| MTM peak (`peak` field) and MTM DD | 11,458.63 / 33.83% | **unchanged** (see 6.1) | shadow line only under `basis=realized` |
| dashboard drawdown card | TRIPPED 33.8% | **still TRIPPED 33.8%** until 6.1 is fixed | `src/app/page.tsx:143-146` reads `.peak` |
| `[PRE-LOOP HALT]` lines | 1 per halted cycle | stop on the next cycle | log |
| `kelly-window-report` line (`drawdown X% vs 20% gate ✓/✗`) | **33.8% ✗** (MTM) | **still 33.8% ✗** until 6.1 is fixed | `scripts/kelly-window-report.ts:37-38,54-66` reads `peak` + MTM NW |

The only **decision-feeding** consumer of `realizedPeak` is `scripts/score-trades.ts`. Report-only readers:
`c200-drawdown-attribution.py`, `c200-ladder-fill-basis.py`, and the apply script itself. The dashboard
(`src/app/page.tsx`), `kelly-window-report.ts` and `backfill-misresolved.ts` read the MTM `peak` field instead.

## 6. Reality checks — what this proposal does *not* fix

### 6.1 Two published surfaces read the MTM peak, not the enforced basis — companion fix at apply time (**Flag 2**)

The scorer enforces `ddBasis = realized`. **Two reporting surfaces still compute the old MTM basis** and will keep saying
TRIPPED after the rebase:

| surface | what it reads | prints today | after B |
|---|---|---|---|
| `src/app/page.tsx:143-146` (dashboard gate card) | `peak` 11,458.63 + MTM NW | TRIPPED **33.83%** | TRIPPED 33.83% (unchanged) |
| `scripts/kelly-window-report.ts:37-38,54-66` (`drawdown X% vs 20% gate`) | `peak` + `principal+realized+unrealized` | 33.8% ✗ | 33.8% ✗ (unchanged) |

```ts
// src/app/page.tsx
c200Peak = JSON.parse(readFileSync(… "c200-drawdown.json")).peak ?? 0;   // MTM peak, never realizedPeak
const c200DrawdownPct = Math.max(0, (c200Peak - c200NetWorth) / c200Peak); // MTM NW
```

So the dashboard already contradicts the gate today (**33.83%** drawn vs **31.95%** enforced), and after any rebase of
`realizedPeak` both surfaces keep printing TRIPPED while copies resume — the first look after the apply reads as
"the rebase failed". This is a display that lies about the live gate (Lane B repair in kind), but it moves a *published
gate state*, so I did not ship it. Recommended companion change (~10 lines, two files): read `realizedPeak` and honour
`rules.ddBasis`, falling back to `peak`/MTM when the basis is `mtm` — i.e. mirror `score-trades.ts:185-191` exactly.
Then verify the rendered value against the log line (`curl :3013 | grep -o 'TRIPPED [0-9.]*%'`).

### 6.2 The class of bug recurs on the next ledger repair (**Flag 3**)

Storing a *derived, ratcheting* statistic of a mutable ledger guarantees this deadlock every time `realizedPnl` is
corrected downward. The structural fix is to recompute the watermark from the ledger each run (clamped so it never
exceeds the observed NW), keeping the stored value only as a floor — i.e. exactly what `scripts/c200-drawdown-rebase.py`
computes, inside the scorer. That is a live-lane change (it changes a risk gate's own input), so it is **its own Lane A
card, not this one**. Without it, every future repair repeats today's 22-hour halt.

### 6.3 Residual ledger defects carried out of `d974287` (unchanged, quoted from its own commit)

- 2,484 **pre-fix `PnlSnapshot` marks** still carry the sibling PnL (restatement was not approved)
- 32 of 120 `DailyReport` statements stale; 15 `needs_review` rows still on the complement price
- 25 unfilled rows repriced without PnL

None of them touch `PaperTrade.realizedPnl`, which is the whole input to the watermark (§3 reconciles to $0.00). They do
mean **the marks-based (MTM) numbers stay untrustworthy** — another reason not to touch the MTM peak.

### 6.4 Taken on trust, not measured by me

- That the 233 repriced legs are *correct* (the repair's own verification: 233/233 post-image in place, class 233 → 0
  inverted of 12,785 fill-bearing rows, second `--apply` refused). I re-verified only the arithmetic that reaches the
  watermark: Σ rows == bankroll, cash identity, 0 duplicate groups.
- The card's `NW 7,548.21 against the 8,854.86 line (+1,306.65 needed) with 12 open legs / $527.64` — **re-measured and
  it has moved**: NW $7,531.94, gap $1,322.92, **11** open legs / **$427.64** (+$50.56 unrealized). One leg ended at the
  15:10 UTC close. The arithmetic in the card is internally consistent (7,548.21 + 1,306.65 = 8,854.86 = 0.8 × 11,068.58).

### 6.5 What the rebase does *not* do

It does not restore the $3,843.89 (the repair was right — that PnL was never earned), it does not re-open the 233
corrected legs for review, and it does not change the 20% threshold or the `realized` basis. It only makes the
denominator equal to what the corrected ledger actually reached.

## 7. Apply recipe (operator) — one command, verified, reversible

```bash
cd ~/polymarket-copybot

# 1. dry run (writes nothing) — re-measures everything in this document
python3 scripts/c200-drawdown-rebase.py

# 2. apply the recommendation (the corrected ledger's own high-water mark)
python3 scripts/c200-drawdown-rebase.py --apply --confirm 7987.32

# 2'. or apply the number that was actually approved (7,548.21).
#     --force makes the confirmed value the target; every guard is then
#     evaluated against THAT value, and that value is what gets written.
python3 scripts/c200-drawdown-rebase.py --apply --confirm 7548.21 --force
```

Guards, evaluated against the value that would be **written** (not against the computed peak):

| guard | refuses when |
|---|---|
| target above current NW | `target ≤ realized NW` — the ratchet would lift it on the next run |
| DD after rebase under the gate | `(target − NW)/target > 20%` — the write would leave the lane halted |
| confirm is the written target | `--confirm` ≠ target (to the cent) |
| confirm matches the computed peak | **only without `--force`**: `--confirm` ≠ the measured HWM |

Then it copies `data/c200-drawdown.json` to `.bak-<ts>`, writes `realizedPeak = <confirmed>`, `peakResetAt`,
`peakResetFrom` and the appended note, **reads the file back, and restores the backup if the written value is not the
confirmed one**, then prints `verify: realizedPeak=… DD=… basisDeclaredAt=…`.

What it does **not** touch: `basis` (still `realized`), `peakRule`, the MTM `peak` 11,458.63, and `basisDeclaredAt` —
the basis is unchanged, and re-stamping the era baseline is what broke the instrument in review round 1 (§11.2). Every
other key is preserved byte-for-byte, and a backup lands beside the file as
`data/c200-drawdown.json.bak-<UTC timestamp>`.

One caveat the script now prints: after a `--force`d reset, the **default** dry run proposes the computed HWM
(7,987.32) and applying it would raise the peak again. The run prints a `NOTE` line with the recipe to keep the stored
value — `--confirm <stored> --force`.

**Verify (next cycle, ~10 min):**

```bash
grep 'DRAWDOWN-SHADOW' logs/cron/copybot-monitor-score.log | tail -1
#   expect: basis=realized 5.7% (peak $7987, NW $7532)
grep -c 'PRE-LOOP HALT' logs/cron/copybot-monitor-score.log   # must not increase
sqlite3 prisma/dev.db "SELECT COUNT(*) FROM PaperTrade WHERE botId='BANKROLL_200' AND openedAt > strftime('%s','now','-20 minutes')*1000"
```

The watermark **sticks**: NW ($7,531.94) < target ($7,987.32), so `score-trades.ts:166` sees `realizedOnlyNW < realizedPeak`
and leaves the file alone (it only rewrites when dirty). No race with an in-flight run either — the run's own write is
conditioned on being dirty.

**Revert:** restore the `.bak-<ts>` file (`cp data/c200-drawdown.json.bak-<ts> data/c200-drawdown.json`) — the lane
re-halts on the next cycle. Nothing else was touched, so there is nothing else to undo.

## 8. Overridable flags (one line each)

- **Flag 1 — watermark target.** I propose **7,987.32** (corrected-ledger high-water mark) instead of the approved
  **7,548.21** (a net-worth reading, stale by one close). Override with
  `--apply --confirm 7548.21 --force` — **verified on a sandbox ledger copy (§11.1): it writes 7,548.21**, DD **0.22%**
  instead of **5.70%**, trip line **$6,038.57** instead of **$6,389.86**, i.e. the gate lets NW fall **$351.29**
  further before it trips ($439.11 lower peak). That extra room is yours to grant or refuse; the script prints it on the
  `trip line vs computed` line before it writes. Any value at or below $7,531.94 is refused (the ratchet would lift it on
  the next run).
- **Flag 2 — the two MTM surfaces.** Recommended: fix `src/app/page.tsx:143-146` **and** `scripts/kelly-window-report.ts:37-38,54-66`
  to read `realizedPeak`/`ddBasis` when you apply, otherwise `:3013` and the Kelly report keep printing "TRIPPED 33.8%"
  while the lane trades. Alternative: leave them and read the gate state from `logs/cron/copybot-monitor-score.log`.
  Revert: `git checkout src/app/page.tsx scripts/kelly-window-report.ts`.
- **Flag 3 — structural fix.** Recommended: card "drawdown watermark derived from the ledger each run" (Lane A, own card).
  Alternative: accept this deadlock as a known cost of every future repair. No change ships either way from this card.

## 9. Freeze / approval classification

- **Class: data-state correction (drawdown-peak reset)** — `references/measurement-window-governance.md` §5 puts the
  drawdown-peak reset in the EXEMPT band (as with the 2026-09-18 basis switch and the kalshi reprice), because it restores
  the gate's denominator rather than weakening its threshold. The 20% threshold, the `realized` basis and every admission
  gate are untouched.
- It **does** change live behaviour (halt → open), so it is not self-authorising: it carries an explicit operator approval
  (`apr-c200-realized-peak-rebase`), which is the override either classification needs.
- No lane-wide measurement window is open (the only `FROZEN` prereg is `entry-floor-a`, a sub-$0.05 ROI cell unrelated to
  this gate). No RuleSet change, so no `apply-vNN` and no 48h auto-tune lockout is triggered.

## 10. Probe log (everything above, reproducible)

| # | command | result |
|---|---|---|
| 1 | `cat data/c200-drawdown.json` | `realizedPeak 11068.58`, `peak 11458.63`, `basis realized`, `basisDeclaredAt 2026-09-18T10:05:42Z`, `updatedAt 2026-11-10T08:26:53Z` |
| 2 | `grep -n "drawdown\|peak" src/lib/rules.ts scripts/score-trades.ts` | ratchet at `:154-166`, basis math `:188-191`, trip `:695-697`, halt report `:1382-1407` |
| 3 | `sqlite3 prisma/dev.db "SELECT version,active FROM RuleSet WHERE active=1"` + `json_extract` | v72 · `maxDrawdownPct 0.20` · `ddBasis realized` · `maxGrossExposureUsd 1000` |
| 4 | `sqlite3 … "SELECT principal,cashBalance,realizedPnl FROM BotBankroll WHERE botId='BANKROLL_200'"` | 1,900.00 / 7,104.30 / 5,631.94 |
| 5 | `sqlite3 … "… status='open'"` | 11 legs, $427.64 notional, $50.56 unrealized |
| 6 | `sqlite3 … "MAX(openedAt) …"` | last C-200 open **2026-11-11 18:10:56 UTC** (card ✓) |
| 7 | `git show --stat d974287` | 233 rows, C-200 Δ **−3,843.89**, bankroll `8,913.40 → 5,069.51`, 196 snapshots, class 233 → 0 |
| 8 | pre-image `data/repair-manifests/ledger-price-side-preimage-20261111T123934.json` | 233 rows; C-200 pre-sum $3,965.37 → post $121.48; `botBankroll.BANKROLL_200.pre.realizedPnl 8,913.40` |
| 9 | `python3 scripts/c200-drawdown-attribution.py --top 6` (pre-existing instrument) | watermark implies $9,168.58 cumulative vs ledger peak $6,087.32 ⇒ **inflated $3,081.26**; corrected DD **5.70%**; era max 13.53%, "gate WOULD NOT have fired"; largest one-cycle step −$3,843 = **19.2×** the next |
| 10 | `python3 scripts/c200-drawdown-rebase.py` (new, dry run) | full output below |
| 11 | guard matrix (`--state`/`--db` overrides, sandbox copies) | **§11.3** — 8 invocations: mismatch, below-NW, above-gate, missing `--confirm`, double-apply all refused or no-op with exit codes; live state file md5 `aa6d80c7…` unchanged throughout |
| 12 | `grep 'DRAWDOWN-SHADOW' logs/cron/copybot-monitor-score.log` | 2.3% → 37.0% at the repair minute; 32.0% now |
| 13 | `grep -c 'PRE-LOOP HALT'` / `grep 'drawdown gate' DecisionJournal` | 81 halt lines; 384 blocked decisions today, last 16:43:56 UTC |
| 14 | `sqlite3 … PaperTrade.openedAt > repair` | **0** rows in any lane since the repair; 1,070 `skip` + 495 `watchlist` decisions |
| 15 | `curl -X POST :3014/execute -d '{}'` | **422** = sidecar alive; last `Skipped execution` 2026-09-02 |
| 16 | `sqlite3 … opens last 7d vs prior 7d` | 188 legs / $4,766.98 vs 91 / $2,478.46 ⇒ ~26.9 legs/day, so the 22h 07m halt has forgone ≈25 legs / ≈$630 of notional (**flow, not a PnL claim**) |
| 17 | duplicate check `GROUP BY decisionJournalId,marketId,outcome HAVING n>1` | 0 groups |
| 18 | `grep -rn "realizedPeak" src scripts tests` | `score-trades.ts` is the only **decision-feeding** reader; `c200-drawdown-attribution.py` + `c200-ladder-fill-basis.py` are report-only; `page.tsx`, `kelly-window-report.ts`, `backfill-misresolved.ts` read the MTM `peak` |
| 19 | `curl -o /dev/null -w %{http_code}` on `:3013` for this draft | 200 at `http://127.0.0.1:3013/drafts/c200-realized-peak-rebase-20261112` |
| 20 | `curl -s :3013/ \| grep -o "TRIPPED [0-9.]*% off peak"` | **`TRIPPED 33.8% off peak`** rendered live — §6.1's first row, verified on the running dashboard, not inferred from source |
| 21 | `sed -n '99,102p' scripts/apply-v56-drawdown-basis.ts` | `next.realizedPeak = Math.max(s.realizedNW, s.st.realizedPeak)` — the documented `--reseed-peak` lever **cannot** rebase downward (§1) |
| 22 | `sqlite3 … MAX(openedAt) WHERE botId='STANDARD'` + per-day opens | last STANDARD open **2026-11-11 17:15:56 UTC**, 0 since (5–14/day before), 409 open legs / $4,483.12 ⇒ the drawdown halt is **portfolio-wide** (`score-trades.ts:651-720`, `isPortfolioGate`) |

Command 10 output (dry run, 2026-11-12T16:59:49Z, rev 2):

```
RuleSet                  : v72  maxDrawdownPct=0.20  ddBasis='realized'
principal                : $1900.00
BotBankroll.realizedPnl  : $5631.94   (sum of finished rows $5631.94, offset $0.00)
BotBankroll.cashBalance  : $7104.30   (principal + realized - open notional = $7104.30)
open legs                : 11  notional $427.64  unrealized $50.56
last C-200 open          : 2026-11-11 18:10:56 UTC
realized NW              : $7531.94
MTM NW                   : $7582.50

corrected realised curve : 2819 finished legs, 2819 distinct end timestamps
  high-water mark        : $7987.32 at 2026-10-18 19:10:41 UTC
  current                : $7531.94  -> drawdown 5.70%
  deepest (all history)  : 28.62% at 2026-08-04 15:54:52 UTC (peak then $1909.74)
  since basisDeclaredAt  : 1057 observations, median 3.14%, p90 9.31%, max 13.53%, over-20% days 0

stored watermark         : $11068.58 (updatedAt 2026-11-10T08:26:53.686Z, basisDeclaredAt 2026-09-18T10:05:42.444Z)
stored -> DD on realized basis : 31.95%   gate 20.00%  -> HALTED
  NW needed to clear it  : $8854.86 (+$1322.92 from inside the lane)
  exposure cap (NW-based): $3815.97  (unaffected by the peak)

PROPOSED watermark       : $7987.32  -> DD 5.70%  gate 20.00% -> OPEN
  target source          : computed corrected-ledger high-water mark
  20% trip line          : $6389.86
  sticks?                : yes (NW $7531.94 < peak $7987.32)

GUARDS
  [PASS] target above current NW            NW $7531.94 < target $7987.32
  [PASS] DD after rebase under gate         5.70% vs 20.00% gate
  [--] confirm is the written target      no --confirm given (dry run)
  [--] confirm matches the computed peak  computed peak $7987.32; pass --confirm to test it
```

(`[--]` = not tested in the dry run; on `--apply` every `[--]` must be `[PASS]` or the write is refused.)

(`1057 observations` = one per close since 2026-09-18; the 56-settlement-date read in §3 is the day-bucketed version of
the same series — median 2.9%, p90 8.1%, max 13.53%, 0 dates over 20%.)

---

## 11. Review round 1 — what changed in the apply half

Review round 1 reproduced the measurement and blocked on two defects **in the apply path** (the apply command *is* the
deliverable). Both are fixed in `scripts/c200-drawdown-rebase.py`; nothing in the analysis moved — HWM 7,987.32 @
2026-10-18 19:10:41Z, NW 7,531.94, DD 5.70%, the −$3,843.89 preimage, RuleSet v72 and state-file md5 `aa6d80c7` all
re-derive unchanged, and nothing was applied.

### 11.1 Defect 1 — the documented override wrote a different number than it said

`--confirm` was only a *guard*: the value written was hard-wired as `target = stats["peak"]`
(`1163d66:scripts/c200-drawdown-rebase.py:182,229`). So `--apply --confirm 7548.21 --force` wrote **7,987.32**, and no
shipped path could produce the approved 7,548.21 — while §4 row A and Flag 1 promised DD 0.22% / trip line $6,038.57.

**Fix.** `--force` now makes `--confirm` the target; every guard is evaluated against that value, the write is verified
against it, and the backup is restored if the file does not match. Dry run and apply now agree, and the approved number
is reachable:

```
$ python3 scripts/c200-drawdown-rebase.py --confirm 7548.21 --force        # dry run
PROPOSED watermark       : $7548.21  -> DD 0.22%  gate 20.00% -> OPEN
  target source          : --confirm (forced by operator): 7548.21 vs computed HWM 7987.32 (-439.11)
  trip line vs computed  : $6038.57 vs $6389.86 (-351.29 of room)
  20% trip line          : $6038.57
  sticks?                : yes (NW $7531.94 < peak $7548.21)
GUARDS
  [PASS] target above current NW            NW $7531.94 < target $7548.21
  [PASS] DD after rebase under gate         0.22% vs 20.00% gate
  [PASS] confirm is the written target      confirm 7548.21 vs target 7548.21

$ python3 scripts/c200-drawdown-rebase.py --apply --confirm 7548.21 --force   # sandbox state file
wrote /…/c200sb-105923/state.json (backup /…/c200sb-105923/state.json.bak-20261112T165923)
verify: realizedPeak=7548.21  DD=0.22%  gate 20.00% -> OPEN  basisDeclaredAt=2026-09-18T10:05:42.444Z
```

### 11.2 Defect 2 — the apply moved the era baseline and crashed the instrument on its next run

The old apply did `after["basisDeclaredAt"] = iso_now()` even though the basis does not change (`realized` → `realized`;
only the peak moves). Every settlement predates the new stamp, so the `since basisDeclaredAt` series came back empty: the
next dry run died at `dds[-1]` (`IndexError`, line 208 of the old file) and `c200-drawdown-attribution.py`'s era line
degenerated into a zero-event window that vacuously printed "gate WOULD NOT have fired" — at exactly the moment you would
re-run it.

**Fix.** `basisDeclaredAt` is left untouched. The reset is recorded by `peakResetAt`, the new `peakResetFrom` and the
appended note (the state file's own `peakRule` asks for a note, not a new era). The era print also handles an empty
series instead of crashing. Verified after the sandbox apply above:

```
$ python3 scripts/c200-drawdown-rebase.py --state <post-apply sandbox>
  since basisDeclaredAt  : 1057 observations, median 3.14%, p90 9.31%, max 13.53%, over-20% days 0

$ python3 scripts/c200-drawdown-attribution.py --dd-file <post-apply sandbox>
    realized-basis era (since 2026-09-18T10:05:42.444Z): 1057 settle events, corrected max drawdown 13.53% at 2026-11-11T08:40:53Z
    -> on a clean ledger the gate WOULD NOT have fired in this era.

$ python3 scripts/c200-drawdown-rebase.py --state <state with basisDeclaredAt forced to 2099-01-01>   # empty-series guard
  since basisDeclaredAt  : 0 settle events since 2099-01-01T00:00:00.000Z — era statistics unavailable
  exit 0
```

### 11.3 Guard matrix, re-run end to end (sandbox state files, real DB, `mode=ro`)

| invocation | result |
|---|---|
| `--apply` (no confirm) | `REFUSED: --apply needs --confirm <peak> — the target you intend to write`, exit 2 |
| `--apply --confirm 7500` | `REFUSED: failed guard(s): confirm is the written target, confirm matches the computed peak`, exit 2 |
| `--apply --confirm 8000.00` | same refusal (8,000 ≠ 7,987.32 and no `--force`), exit 2 |
| `--apply --confirm 7987.32 --force` | wrote 7,987.32, `verify: DD=5.70% … OPEN`, exit 0 |
| `--apply --confirm 11068.58 --force` | `REFUSED: failed guard(s): DD after rebase under gate` (31.95% > 20%), exit 2 |
| `--apply --confirm 7000 --force` | `REFUSED: failed guard(s): target above current NW`, exit 2 |
| `--force` (no confirm) | `REFUSED: --force needs --confirm <peak> — there is no target to write`, exit 2 |
| repeat on an already-reset file | `already rebased to 7548.21 — nothing to do`, exit 0 |

The **live** state file was never a target: `md5 data/c200-drawdown.json` is still
`aa6d80c775f36e47be586c90a38e2d17` (mtime 2026-11-10), `data/` holds no `.bak-*`, RuleSet is still **v72**. Sandbox files
live under `~/.hermes/cache/scratch/c200sb-105923/`. The script gained `--db` / `--state` overrides so this can be
reproduced without touching the live files.

### 11.4 Non-blocking notes from the review

- The `$351.29` of extra trip-line room (peak −$439.11) is now printed by the dry run *before* the write
  (`trip line vs computed`), so the operator sees the cost of opting for the clicked 7,548.21.
- `82` halt lines vs `81` is a moving counter, not an error; §2/§3's figures are a snapshot at 16:50 UTC.
- The two MTM reporting surfaces (§6.1, Flag 2) are unchanged and still report TRIPPED after any rebase — that companion
  fix is deliberately not shipped by this card.


---

**Added with this proposal:** `scripts/c200-drawdown-rebase.py` (new; read-only unless `--apply`) and
`drafts/c200-realized-peak-rebase-20261112.md` (this file) in `1163d66`; rev 2 fixes the apply path per §11 (the script
now writes the confirmed value, refuses on every failed guard, verifies its own write, and leaves `basisDeclaredAt`
alone). `scripts/c200-drawdown-attribution.py` was used unchanged. Nothing else is in those commits: no DB write, no
state-file write, no RuleSet change, no dashboard edit, nothing merged beyond the doc and its report-only script.

---

## 12. Re-measure 2026-11-12T17:22Z — the analysis holds; the *card* did not

Re-run on the live DB (`mode=ro`) one tick later, and on the roadmap card that feeds the approval queue. Two results: the
measurement re-derives to the cent, and the **card the operator approves was still carrying the superseded instruction**.

### 12.1 Every figure re-derives (drift only in the moving parts)

| figure | §3/§5 snapshot (16:50Z) | now (17:21:48Z) | Δ |
|---|---|---|---|
| `BotBankroll.realizedPnl` | 5,631.94 | **5,638.38** | +6.44 (one settlement) |
| ledger sum / drift | — | **5,638.38 / $0.00** | row still equals its rows |
| realized NW | 7,531.94 | **7,538.38** | +6.44 |
| stored watermark | 11,068.58 | **11,068.58** | **unchanged** |
| DD on the stored watermark | 31.95% | **31.89%** | gate 20% → still HALTED |
| NW to clear it | 8,854.86 (+1,322.92) | **8,854.86 (+1,316.48)** | deadlock intact |
| corrected HWM | 7,987.32 @ 10-18 19:10:41 | **7,987.32 @ 2026-10-18T19:10:41Z** | **identical** |
| corrected DD | 5.70% | **5.62%** | the doc's 5.70% was that close's NW |
| era max DD (since `basisDeclaredAt`) | 13.53% | **13.53%**, 1,058 settle events | identical |
| watermark excess over the ledger's own peak | 3,081.26 | **3,081.26** | identical |
| discontinuity scan | −3,843.89 @ 12:43:43, 19.2× the next | **−3,843.00, 19.2×**, 7,467 runs | **identical** |
| `[PRE-LOOP HALT]` lines | 81 | **84** | a moving counter (§11.4) |

**0 opens on either book since the halt**, now measured directly rather than inferred:

```
$ CUT=$(sqlite3 -readonly prisma/dev.db "SELECT CAST(strftime('%s','2026-11-11T18:43:00Z') AS INTEGER)*1000;")
$ sqlite3 -readonly prisma/dev.db "SELECT botId, COUNT(*) FROM PaperTrade WHERE openedAt > $CUT GROUP BY botId;"
   (no rows — 0 for BANKROLL_200 and 0 for STANDARD)
$ SELECT botId, MAX(openedAt) … GROUP BY botId;
   BANKROLL_200|2026-11-11 18:10:56     STANDARD|2026-11-11 17:15:56
```

Nothing was applied: `md5 data/c200-drawdown.json` is still `aa6d80c775f36e47be586c90a38e2d17` (mtime 2026-11-10), `data/`
holds no `.bak-*`, RuleSet is still **v72**, and the dry run prints
`PROPOSED watermark : $7987.32 -> DD 5.62% gate 20.00% -> OPEN` with all four guards `[PASS]` on the value it would write.

### 12.2 The defect this round: the card said the superseded thing

The roadmap card is the approval surface, and it had been updated only in its `note` — the fields an approver actually reads
were still round-1's. Three defects, all now corrected in `data/roadmap.json` (title, `dates`, `decision_rule`; `tags`
untouched, `awaiting-approval` still on the card):

1. **Title carried the wrong target** — `… 11,068.58 -> 7,548.21`, i.e. the number §4 rejects. Now
   `-> 7,987.32 (corrected-ledger high-water mark, NOT today's NW)`.
2. **`decision_rule` said "rebase to current realized NW with a note and a fresh basisDeclaredAt".** Both halves are wrong:
   the target is the one §4/Flag 1 argues against, and re-stamping `basisDeclaredAt` is **the change that crashes the
   instrument** (§11.2) — the rule would have instructed an approver to reintroduce the round-1 defect on purpose.
3. **`decision_rule`'s refutation self-refutes on success.** It read "REFUTED IF … the next DRAWDOWN-SHADOW read still
   reports the old basis **or a non-zero drawdown**". After a *correct* rebase the drawdown is 5.62% — non-zero by design,
   since the correct watermark is above current NW by $448.94. A gate that "refutes" its own correct outcome cannot fail,
   which means it cannot pass either.

The card now carries the original rule marked `SUPERSEDED … ORIGINAL:` for the record and a governing **REV 2 RULE** with
four refutation arms:

- **(a)** the next `DRAWDOWN-SHADOW` line does not print `basis=realized`, peak **7987.32**, DD **5.5–5.7%** — what was
  written is not what the gate reads;
- **(b)** `[PRE-LOOP HALT]` keeps rising after the rebase cycle — the watermark was not what was gating the lane;
- **(c)** 0 new `BANKROLL_200` opens in the 24h after the rebase **while at least one candidate passes the per-leg rules** —
  the halt was necessary but not sufficient;
- **(d)** the corrected HWM recomputed later is not within **$1** of 7,987.32 — the measurement, not the gate, was broken.

**Explicitly not a refutation:** a non-zero drawdown after the rebase. 5.62% is the right value and the era's own maximum
is 13.53%, so any reading above 20% (the only value that would matter) is already excluded by arm (a).

### 12.3 What would still change the recommendation

Nothing in this re-measure moved it. The two ways this proposal dies are unchanged and both are cheap to test **before**
applying: (i) if `c200-drawdown-rebase.py` stops reproducing 7,987.32 @ 2026-10-18T19:10:41Z on a re-run, the HWM is not
order-invariant and the target reverts to the clicked 7,548.21 (`--force`); (ii) if the lane is **not** in fact gated by this
watermark — e.g. a cycle opens with DD above 20%, or the halt persists with the peak at 7,987.32 — then the gate is
downstream of something else and the card is refuted by arm (b), not by the analysis.
