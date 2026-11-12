# C-200 orphaned FillIntents — link the 201, restate the proven-unfilled, rebase the peak

**Lane A · PROPOSAL ONLY · 2026-11-12**
Approval: `apr-c200-intent-link-repair` (clicked 2026-11-12T20:08:00Z) · source card `roadmap:c200-intent-link-repair`
Board card: kanban `t_bb9577ae`

> **Nothing has been applied.** `prisma/dev.db` was opened read-only for every measurement below, no
> `scripts/apply-vNN.ts` was run, no RuleSet was written (still **v72**), `data/c200-drawdown.json` is untouched,
> no branch was merged. The apply step is §9 and it is yours.

---

## Verdict

**The link is approved and it is safe — but on its own it moves $6.84.** Everything the title claims
(`restates … booked PnL`, `moves netWorth → the exposure cap → the drawdown gate`) requires a **second write that
does not exist yet**: a realized-PnL restatement. Linking only makes a leg *reachable* by the resolver; booking reads
`fillStatus` at the moment a mark or settlement is **written**, so legs that settled while unstamped keep the
optimistic `realizedPnl` they booked, and nothing moves (measured, §4):

| step | what it writes | PnL that moves |
|---|---|---|
| 1 — link 201 pairs *(approved)* | `FillIntent.paperTradeId`, `PaperTrade.intentPrice` | **$0.00** |
| 2 — resolver stamps 201 legs | `PaperTrade.fillStatus` → 131 unfilled / 70 filled | **−$6.84** (2 open legs, next hourly mark) |
| 3 — restate realized PnL | `PaperTrade.realizedPnl` + `BotBankroll.realizedPnl` + `cashBalance` | **−$1,471.12** on these 129 legs — *not part of the approved step* |

**And the downstream direction is the reverse of what the title implies.** The drawdown gate is **already shut** —
`DD 31.9% > 20%` on the declared `realized` basis, `[PRE-LOOP HALT]` printed **95** times, **0** C-200 legs opened in
24 h (last: 2026-11-11 18:10:56 UTC). The restatement pushes net worth **down** $1,471.12, so against the stored
watermark it moves DD **31.9% → 45.2%**: it does not "move" the gate, it **deepens a gate that has already stopped the
lane**. The only ordering that leaves the lane tradeable is restating *and* rebasing the watermark in one release:
**DD 11.3%, gate open** (§6).

**A second defect class turned up while pricing this one, and it is bigger than the card.** 247 legs are *already*
stamped `unfilled` and still book **$828.66** of realized PnL — they settled before their stamp landed, so
fill-aware booking never saw it. All 247 re-verify as still-unfilled against the current artifact (§5). Leaving them
means the ledge invariant `fillStatus='unfilled' ⇒ realizedPnl=0` stays violated on 247 rows, which is exactly the
contradiction later reads quote phantom numbers from.

**Recommendation — Option B, scope = the whole class:** one release, four steps in this order — link 201 → resolver
apply → **restate 376 legs (−$2,299.78)** (legs + bankroll + cash in one transaction) → rebase `realizedPeak`
11,068.58 → **5,935.46**. It also **amends the pending peak-rebase card `t_12711fe0`**, whose approved-but-unapplied
target of **7,987.32** is computed on a ledger that still contains this phantom PnL: apply that first and then this
repair and the gate **re-trips at 24.0%** (§6, row 4). That interaction is why these cannot be two independent repairs.

---

## 1. Three corrections to what the approval text assumes

1. **"restates … +$1,115.18 of booked PnL"** — $1,115.18 is the *net booked PnL of the population before* the repair,
   not the delta. On these 201 pairs the delta is **−$1,471.12**: 131 legs carrying +$1,471.12 of profit are proven
   never-reachable, while 70 legs with −$355.94 *were* reachable and keep their loss. After the repair the population
   books **−$355.94**.
2. **"moves netWorth → the exposure cap → the drawdown gate"** — true only through step 3. Linking alone leaves
   `realizedPnl` untouched (those legs are already written), so netWorth, the cap and the gate do not move; the sole
   immediate effect is 2 open legs (−$6.84).
3. **"these 219 book at p(fill)=1 permanently"** — 219 unlinked intents = **201 repairable 1:1 pairs + 18 refused on
   the complement frame** ($776.89 notional, +$101.13 booked). The 18 stay at p(fill)=1 *by design* — linking them
   would hand the resolver a level a dollar away from the booked one. Separate measurement (§10).

---

## 2. The population

`DATABASE_URL="file:./dev.db" npx tsx scripts/c200-link-missing.ts` (dry run, read-only):

```
C-200 intent links — 802 intents, 2830 legs
  already linked          : 583
  unlinked intents        : 219
  REPAIRABLE 1:1 pairs    : 201   notional $3728.02   booked PnL $1115.18   settled 198
  ambiguous (refused)     : 0 keys
  unlinked intent, no leg : 0
  REFUSED, complement frame: 18 pairs  notional $776.89  booked PnL $101.13
```

Preconditions, all verified read-only (`scripts/c200-link-missing-impact.ts`, which **fails loudly if its pair
count/sums drift** from the tool above):

| check | measured | why it matters |
|---|---|---|
| parity vs `c200-link-missing.ts` | 201 / $3,728.02 / $1,115.18 — **exact** | the two tools describe the same book |
| pairs whose intent is in `data/c200-printthrough.jsonl` | **201 / 201** (artifact holds 802 distinct intents = the entire instrument era) | a linked intent the artifact never saw would sit `fillStatus NULL` forever |
| pairs already carrying a `fillStatus` | **0** | nothing is re-stamped over an existing verdict |
| ambiguous key tuples | **0** | no guessed pairing |

## 3. What the resolver says (and why the negatives are trustworthy)

Resolver mode `live` — the credit the sidecar books today. These are the verdicts it will write on its next run once
the links exist:

| bucket | pairs | notional | realized | unrealized | open |
|---|---|---|---|---|---|
| unfilled (proven not reachable) | 131 | $2,306.97 | **+$1,471.12** | $6.84 | 2 |
| filled (reachable) | 70 | $1,421.05 | −$355.94 | $35.17 | 1 |
| unresolved (no evidence either way) | **0** | — | — | — | — |
| invisible (intent absent from artifact) | **0** | — | — | — | — |

Five quality checks, because a negative the ledger acts on has to be earned:

1. **Every negative rests on a book window; none on tape silence.** Basis tally `{book-window: 131}`, 0 legs without
   book coverage. (Tape silence is the weaker, indirect negative and decides nothing here.)
2. **The window covers the decision moment.** dispatch → coverage start: median **0.2 min** (p90 0.4, max 0.8);
   coverage length median **130 min** (min 33). **0** fragile verdicts (none started >15 min late; none <10 min long).
3. **The gaps are not tick-sized.** `minAsk − level` median **+3.1%** (p10 +1.3%); only **4** legs sit within 1% of the
   level and those carry **−$9.98** of realized PnL on $58.09 — a stricter boundary test would *add* $9.98. The repair
   does not hinge on arguing about a tick.
4. **The population behaves like the rest of the instrument:** 131/201 = **65.2%** proven-unfilled against **66.8%**
   (389/582) among already-stamped legs.
5. **Spot-check** (`scripts/c200-link-missing-spotcheck.ts`) prints the operands behind each verdict, e.g.
   `intent 0.070 → level 0.069 (credit $0.0006) · minAsk 0.080 · book-window → unfilled · resolved/+$380.00`.

**Caveat that must travel:** a best ask at or below the level is **reachability**, not a fill (no queue position, no
size). "Unfilled" is a solid negative; the 70 "filled" legs keep `p(fill)=1`, so the book stays an **upper bound** —
just a much less inflated one.

## 4. What moves, by write path

| surface | rows | today | 129-leg scope | 376-leg scope (recommended) | who reads it |
|---|---|---|---|---|---|
| `PaperTrade.realizedPnl` | 129 / 376 | +$1,471.12 / +$2,299.78 | $0.00 | $0.00 | ladder, daily report, rollups |
| `PaperTrade.unrealizedPnl` (2 open) | 2 | $6.84 | $0.00 at next mark | $0.00 | dashboard, MTM shadow |
| `BotBankroll.realizedPnl` | 1 | $5,638.38 | $4,167.26 | **$3,338.60** | netWorth, DD gate, exposure cap |
| `BotBankroll.cashBalance` | 1 | $7,120.66 | $5,649.54 | **$4,820.88** | **Kelly's available bankroll** |
| realized net worth (`principal 1,900 + realized`) | — | $7,538.38 | $6,067.26 | **$5,238.60** | DD gate, exposure cap |
| equity-linked exposure cap (`1000 + 50%·(NW−1900)`) | — | $3,819.19 | $3,083.63 | **$2,669.30** | gross-exposure ceiling |
| drawdown, stored watermark kept | — | 31.9% | **45.2%** TRIPPED | **49.0%** TRIPPED | entry gate |
| drawdown, watermark rebased (§6) | — | 31.9% | **11.3%** open | **11.7%** open | entry gate |

Identity, so the restatement cannot be half-applied: today `principal 1,900 + realized 5,638.38 − open notional 417.72
= cash 7,120.66`. The three fields move together or the book stops reconciling — which is why §9 puts the bankroll and
cash delta in the same transaction as the leg rows.

## 5. The second class: stamped `unfilled`, still booking an *un*realized PnL

A leg can be proven never-a-position *after* it settled. `bookedPnl()` only runs at write time, so its settlement had
already written the optimistic number and nothing revisits it:

| | legs | realized PnL | notional | settled in |
|---|---|---|---|---|
| stamped `unfilled`, still non-zero | **247** of 383 stamped-settled | **+$828.66** (84 legs +$2,175.35 / 163 legs −$1,346.69) | $2,234.47 | Sep 40 / Oct 207 / **Nov 0** |

- **Re-verified against the current artifact, current resolver:** still unfilled **247 ($828.66)**, now *reachable*
  **0**, unresolved **0**, no-linked-intent **0**, intent-absent **0**. The class is coherent — including it does not
  import a stale verdict.
- **It is not still accruing:** zero legs settled in November carry this defect, so this is a closed backlog, not a
  live leak (contrast the link race, which is dormant only because the lane is halted — §10).
- Both classes are the *same* correction: a retrospective application of today's fill model to bookings made under
  `p(fill)=1`. One write, one manifest, one revert.
- Leaving the 247 in place would mean 247 rows violate `fillStatus='unfilled' ⇒ realizedPnl=0` and every later read
  that pairs those two columns yields a contradiction — one of which is the ladder's own 7-day sum.
- The 6 *open* stamped-unfilled legs are not in this class: their `unrealizedPnl` is already $0.00 ($329.82 notional),
  because the hourly mark zeroed them the first time it ran after the stamp. Only *settled* legs were written past.

## 6. The watermark interaction — why the two approved repairs cannot run independently

`realizedPeak` is a **monotone ratchet** (`score-trades.ts:154-166`): nothing lowers it, and it was ratcheted from the
same `realizedPnl` these legs contributed to. So a downward restatement measured against the stored peak double-counts
the correction, and a rebase computed *before* this repair measures new net worth against a high-water mark that still
contains the phantom PnL. Corrected realized curves (principal + cumulative `realizedPnl`, ordered
`closedAt ?? resolvedAt`, all peaking 2026-10-18 19:10 UTC):

- ledger as it stands → **$7,987.32** ← *the target of the pending rebase card*
- ledger with the 129 zeroed → **$6,839.46**
- ledger with the whole class (376) zeroed → **$5,935.46**

| ordering | peak | net worth | DD | gate |
|---|---|---|---|---|
| today | 11,068.58 | 7,538.38 | 31.9% | TRIPPED |
| restate only (peak kept) | 11,068.58 | 6,067.26 | **45.2%** | TRIPPED — worse |
| peak rebase only (`t_12711fe0` target) | 7,987.32 | 7,538.38 | 5.6% | open |
| **rebase to 7,987.32, THEN restate** | 7,987.32 | 6,067.26 | **24.0%** | **TRIPPED — re-closes a gate that just opened** |
| restate 129 + rebase on that ledger | 6,839.46 | 6,067.26 | 11.3% | open, 8.7pp headroom |
| **restate 376 + rebase on that ledger** | **5,935.46** | **5,238.60** | **11.7%** | **open, 8.3pp headroom** |

Row 4 is the trap: both repairs are individually approved and individually correct, and their composition in the
obvious order shuts the lane again. **`t_12711fe0`'s 7,987.32 is superseded the moment this card is approved.**

Scale of the halt, for context: `[PRE-LOOP HALT]` × 95, **0** C-200 legs in 24 h, last leg 2026-11-11 18:10:56 UTC,
`[DRAWDOWN-SHADOW] basis=realized 31.9% (peak $11069, NW $7538)`. The block is a portfolio gate
(`isPortfolioGate()`), so it fires before the leg loop and nothing else in the lane can be diagnosed while it holds.

## 7. The published figure: the ladder's 7-day gate sum

GOAL POLICY v2 clears a phase when the trailing 7 settled days SUM ≥ target × 7. Trailing-7d, `closedAt ?? resolvedAt`:

| | legs | sum | vs the $250/day rung's $1,750 |
|---|---|---|---|
| today | 177 | **+$190.03** | 10.9% |
| after either restatement scope | 152 | **−$53.55** | −3.1% |

25 phantom legs sit in the window carrying $243.58 (the 247-class contributes nothing — nothing in November). **The
rung does not change** (Phase 1 either way), but the published 7-day figure **flips from positive to negative**: under
fill-aware booking the last week was a loss. Anyone quoting "+$190 on the week" after this repair is quoting a retired
number.

## 8. Options, recommendation first

| | what you sign | ledger | DD after | gate |
|---|---|---|---|---|
| **B — recommended** | link + restate **376** + rebase `realizedPeak → 5,935.46`, one release | honest, invariant holds | **11.7%** | open, 8.3pp headroom |
| B₁ | link + restate **129** + rebase `→ 6,839.46` | honest for this card only | 11.3% | open, 8.7pp headroom |
| A | link + resolver only (what the approval literally says) | overstated $1,471.12 (+$828.66 elsewhere) | 31.9% | still TRIPPED |
| C | link + restate, watermark untouched | honest | 45.2% / **52.7%** | TRIPPED deeper, no recovery path |
| D | link + restate + rebase to the standing 7,987.32 | honest | 24.0% | TRIPPED again |

- **A** is safe and incomplete: it buys future resolver coverage and nothing else.
- **C** is a trap: the lane is halted, so it cannot earn its way back — NW would have to reach **$8,854.86** (peak ×
  0.8), i.e. **+$3,616.26** from $5,238.60, more than the lane's entire remaining realized PnL, with entries forbidden.
- **D** is the ordering hazard above.
- **B₁ vs B** differ by $828.66 of the same defect. B leaves no row contradicting its own `fillStatus`.

**Pre-registered refutation.** B is wrong if the negatives are an artifact of coverage that began after dispatch. That
was measured, not assumed: 0 of 131 verdicts start >15 min late, median lag 0.2 min, median gap 3.1% above the level,
and the marginal set (within 1% of the level) is −$9.98, i.e. a stricter test would *add* money. **Stop and re-measure**
if, after the resolver stamps, the basis tally gains tape-only negatives, if the lag p90 exceeds 15 min, or if any of
the 247 re-verifies as reachable at apply time. **Second falsifier:** if `SUM(leg realizedPnl) ≠ BotBankroll.realizedPnl`
after the apply, the restatement was half-applied (§4 identity).

## 9. The apply path (yours — and one tool in it does not exist yet)

Step 3 has no tool: `c200-link-missing.ts` writes only the link. A realized restatement needs a new Lane-A script
(**`scripts/c200-link-restate.ts`**), specified here rather than shipped — a write that moves realized PnL, bankroll,
cash and a gate figure is not handed over pre-wired.

```
# 1. link (approved; no figure changes)                                    ~1 min
DATABASE_URL="file:./dev.db" npx tsx scripts/c200-link-missing.ts --apply

# 2. stamp the verdicts (cron copybot-c200-fill-chain does this; hand-run for immediacy)
DATABASE_URL="file:./dev.db" npx tsx scripts/c200-fill-resolve.ts --apply
#    expect over the new population: filled 70 / unfilled 131 / unresolved 0

# 3. restate (NEW — must be written before it can be run)
python3 scripts/c200-link-restate.ts                     # dry run: 376 rows + the three bankroll deltas
python3 scripts/c200-link-restate.ts --apply --confirm 2299.78

# 4. rebase the watermark onto the corrected ledger
python3 scripts/c200-drawdown-rebase.py --apply --confirm 5935.46
```

**`c200-link-restate.ts` spec** (Lane A, flag-gated, no default action):
- population = (a) legs whose `FillIntent.linkedAt` post-dates this repair **and** `fillStatus='unfilled'`, plus
  (b) legs already `fillStatus='unfilled'` with non-zero `realizedPnl` — i.e. 129 + 247 = 376; never the 6 open
  stamped-unfilled legs and never any `filled` leg;
- **re-verifies every leg against the current artifact at apply time** and refuses any leg that now reads reachable or
  unresolved (measured today: 0 and 0);
- writes `PaperTrade.realizedPnl = 0` for those rows **and** `BotBankroll.realizedPnl −= Σ`,
  `cashBalance −= Σ` in the same transaction, guarded on the full pre-image (`WHERE id=? AND realizedPnl=?`);
- dry run by default; `--confirm <sum>` must match the pre-image sum exactly ($2,299.78 today) or it aborts;
- per-row pre-image manifest → `data/repair-manifests/c200-link-restate-<ts>.jsonl`; `--rollback <manifest>` reverses
  it, then `c200-drawdown-rebase.py --confirm <previous peak>` restores the watermark;
- leaves `PnlSnapshot` marks alone (2,997 rows / $29,771.19 on the 129 legs) — repricing chart marks is a different
  published series and a separate card (`restate-pnl-marks.py`'s class);
- **revert:** per row by manifest. The link step itself reverts by re-nulling `FillIntent.paperTradeId`/`linkedAt` and
  `PaperTrade.intentPrice`.

**Verification after the apply** — all five must hold:
`SUM(realizedPnl)` over the 376 = 0 · `BotBankroll.realizedPnl` = $3,338.60 · `cashBalance` = $4,820.88 ·
`[DRAWDOWN-SHADOW]` reads `basis=realized 11.7% (peak $5935, NW $5239)` · no `[PRE-LOOP HALT]` line once candidates exist.

## 10. What this does NOT fix

- **18 complement-frame pairs** ($776.89 notional, +$101.13): refused by design. Re-framed (`level = (1 − intent) −
  credit`) **14 read unreachable, $78.25 on $508.90 notional** — but the artifact's tape column was computed at the
  booked frame and is invalid there, so that is a book-window-only estimate, not a verdict. Follow-on card (§12).
- **2,028 pre-instrument legs**: no `FillIntent` ever existed; unresolvable by design, no backfill.
- **The 70 reachable legs** keep `p(fill)=1`; the book remains an upper bound.
- **Historical `PnlSnapshot` marks** on the restated legs stay as they are (report surface, separate card).
- **The live leak's write path**: `stampIntentLink` retries and logs a miss (`src/lib/fill-intent.ts`, commit
  `f93274d`), and the rebuilt `.next` bundle contains it — but the **running dashboard started 10:54:12, before the
  13:41 build**, so the served code is pre-fix. It is **dormant, not fixed**: the lane is halted, no new intents exist
  (latest `FillIntent` 2026-11-11 17:15:56 UTC) and `logs/dashboard.log` carries no `[fill-intent] link MISSED`. Any
  restart/redeploy picks the fix up; until then, do not restart.
- **Recurrence of the §5 class** is not fixed by a restatement: a leg that settles before its stamp will book
  p(fill)=1 again. It has not accrued since October, so the current ordering is adequate — but the durable fix
  (settle-time reconciliation, or resolving before settlement) is card **`t_c9312d68`**, and this repair decays slowly
  without it.

## 11. Flags needing your word

1. **Scope** — restate the whole class (**376 legs, −$2,299.78**, recommended) or only the legs this card links
   (**129 legs, −$1,471.12**). Everything else in §9 is identical.
2. **The rebase target** — 5,935.46 (whole class) supersedes 7,987.32 on `t_12711fe0`. Keeping 7,987.32 and restating
   later re-trips the gate at 24.0%.
3. **Cash/Kelly side-effect** — the restatement takes `cashBalance` to $4,820.88, which is Kelly's
   `c200AvailableBankroll`. It changes nothing today (the gate holds entries) but it is a sizing input the moment the
   gate opens.

## 12. Reproduce

```
DATABASE_URL="file:./dev.db" npx tsx scripts/c200-link-missing.ts            # the population (dry run)
DATABASE_URL="file:./dev.db" npx tsx scripts/c200-link-missing-impact.ts     # every figure in §2-§7 (read-only)
DATABASE_URL="file:./dev.db" npx tsx scripts/c200-link-missing-spotcheck.ts --n 6   # verdict operands + window audit
python3 scripts/c200-intent-link-coverage.py                                 # link coverage by class (read-only)
grep -h "PRE-LOOP HALT" logs/cron/copybot-monitor-score.log | tail -1        # the halt as production prints it
```

## 13. Follow-on cards (created, gated behind this one)

- **`t_1f579e82`** — *Complement-frame C-200 intent links: re-frame and price the 18 refused pairs* ($776.89 notional,
  +$101.13 booked). Measurement, Lane A: the level tested must be `(1 − intent) − credit`, and the artifact's tape
  column recomputed at that frame before any verdict is quoted. Created so the $776.89 does not sit in the "unlinked"
  bucket looking repaired.
- **`t_c9312d68`** — *C-200 legs that settle before their fill stamp keep an optimistic realizedPnl* (247 legs,
  $828.66; see §5). Owns the recurrence and the durable fix, not the backlog.
