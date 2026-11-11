# The per-wallet ceiling counterfactual has never written a row

**Card:** t_bfb9e54c (kanban, medusa) · found while porting the four declined-gate
shadows onto `src/lib/counterfactual-ledger.ts` · Lane B (instrument repair)
**Read:** 2026-11-11 19:00Z · **Rules:** RuleSet v72 active

---

## Verdict

**Neither branch was zero, and nothing in the writer is broken. The rail simply never
bound — and it lost the only race it ever had by 26 minutes.**

`data/wallet-cap-shadow.jsonl` holds zero rows because `appendWalletCapShadow` landed in
commit `88662da` at **2026-09-20 09:42:10Z**, 26 minutes *after* the last of the **109
lifetime vetoes (2026-09-20 09:15:52Z)**, and in the *same commit* that re-based the
ceiling onto the grandfather basis (`walletCapBasis: "delta"`) — which raised that one
wallet's ceiling above everything it held. The instrument was installed into a state where
its trigger could no longer be true.

The lane is therefore **repaired, not retired**. The 2026-10-11 read called the rail
"structurally unreachable" (leader $50.00 against a $976.47 ceiling, 19.5x away); 31 days
later the tightest wallet is at **57.3%** of an **$881.44** ceiling. The book concentrated
~10x in a month. Retiring the lane today would blind it exactly as it becomes reachable.

---

## 1. Which branch never fires — measured

Both candidate causes in the card are **ruled out**:

| Question | Answer | Source |
|---|---|---|
| Is `c200WalletNotionalCap` zero? | **No.** Live pct `0.25` × effective cap `$3,525.76` = **$881.44** (+ frozen baseline, basis `delta`) | RuleSet v72: `maxWalletNotionalPctOfCap 0.25`, `walletCapBasis "delta"`, `maxGrossExposureUsd 1000`, `ddBasis "realized"`; cap = 1000 + 50% × (NW $6,951.52 − principal $1,900) |
| Does `walletCapDecision` ever return `blocked`? | **No — but it did.** 109 blocks, all on 0xb0c85813…, 2026-09-19 19:14:56Z → 2026-09-20 09:15:52Z | `DecisionJournal.risksJson LIKE '%v58 per-wallet cap%'` |
| Blocks in the last 7 days | **0** (and 0 in the 52 days since 2026-09-20 09:15:52Z) | same query, window bound |
| Candidates that reached the check in the last 7 days | **≥188** — every C-200 leg that opened, of which it blocked **0**; the rest of the 188 are ones it *passed* (candidates stopped by an earlier gate never reach this check) | `PaperTrade` opened in window, `botId='BANKROLL_200'` |

So the writer's condition has never been true *in the writer's lifetime*. The card's
hypothesis "the condition has simply never fired since the instrument landed — or
`c200WalletNotionalCap` is 0" resolves to a third fact the card did not have: **the
instrument landed after the gate's only firing episode, and the same commit disarmed it.**

### The race, to the minute

| Time (UTC) | Event | Source |
|---|---|---|
| 2026-09-19 18:25 | v58 ceiling live, `walletCapBasis` **stock** (measured against the wallet's whole book) | roadmap `v58/v59` card |
| 2026-09-19 19:14:56 | first veto | `DecisionJournal` |
| 2026-09-20 09:15:52 | **last** veto — 109 total, one wallet, $1,003.66 against a $431.13 ceiling | `DecisionJournal` |
| 2026-09-20 09:42:10 | `88662da` — adds `appendWalletCapShadow` **and** flips `walletCapBasis → delta` | `git log --follow` on `src/lib/shadow-wallet-cap.ts` |
| after that | the wallet's ceiling becomes $987.43 baseline + $430.97 = **$1,418.40** > the $993.66 it holds → cannot block | `data/wallet-cap-baseline.json` + the same arithmetic in `score-trades.ts:1115` |

The writer was correct on arrival. There was simply no decision left for it to record, and
none in the 52 days since.

---

## 2. How close is it now? — the number that changed the decision

| Read | Ceiling | Tightest open wallet | Distance |
|---|---|---|---|
| 2026-10-11 | $976.47 | $50.00 (5.1%) | 19.5x away |
| **2026-11-11** | **$881.44** | **$505.13 = 57.3%** | **$376.31 headroom = 3.8 max clips** |

The ceiling *fell* (the cap tracks realized net worth, which moved from $7,711 to $6,952)
while the book concentrated. 0x17dd123a… now holds 18 of the 43 open C-200 legs.

`python3 scripts/audit-wallet-cap.py --replay 7` (committed with this note) replays the
predicate per leg over the last 7 days: **188 legs, 16 wallets, max projected ratio 0.695,
median 0.193, 0 legs over the ceiling.** So the silence is genuine for the window too — not
just at the instant sampled. Caveat, printed by the script: the ceiling is held at today's
value, and the cap rises with realized NW, so a lower cap in-window would raise every ratio.
*Adjudicate "did it fire" on the journal count (exact), never on the replay.*

---

## 3. What shipped (Lane B: fix, verify, commit)

The defect the card names is not the empty file — it is that **an empty feed scored 10/10**
and read as evidence. Three artefacts now make silence distinguishable from a clean result,
mechanically and on every future run:

### (a) `scripts/reconcile-counterfactual-ledger.ts` — an empty lane is `EMPTY`, never `match`

- `status: "empty"` for any lane whose feed holds 0 rows. It drops out of `lanesMatching`,
  and the line prints `VACUOUS — the 10-field match below attests the EMPTY path only, not
  the lane`. (The diff still runs; it just cannot be read as a pass.)
- An **ARM CHECK** (`src/lib/wallet-cap-arming.ts`) runs on that lane: *did the gate fire in
  the window* (exact, `DecisionJournal.risksJson`) and *could it fire now* (exact, live
  ceiling vs live open book). `contradiction = feed empty AND (blocks in window OR a wallet
  at/over its ceiling)` → **exit 1**.
- Verdict line becomes `PASS — every POPULATED lane reproduces its golden; empty lane(s)
  reported as EMPTY, not as matches`.

Before / after on the live tree:

```
before:  PASS — port reproduces every golden field: 4/4 lanes match, 0 field mismatch(es)
after:   [EMPTY] per_wallet_cap (walletCap) rows=0
           VACUOUS — the feed holds 0 rows, so the 10-field match attests the EMPTY path only
           arm check: state=DORMANT ceiling=$881.44 (basis delta) blocks/7d=0 breached=0
                      contradiction=false
         PASS — every POPULATED lane reproduces its golden; empty lane(s) reported as EMPTY
         3/4 lanes match, 1 EMPTY (walletCap), 0 field mismatch(es), 0 arm contradiction(s)
```

The probe **can fail** — proved end-to-end against real data, no writes: run the arm check
with a 60-day window and it reproduces the 109 blocks and flags `WRITER BROKEN`
(`state=FIRING blocks=109 contradiction=true`).

### (b) `data/wallet-cap-shadow-summary.json` explains its own zeros

The summary the parent card read now carries a `feedState` block whenever `candidates === 0`
— the gate's note, the arm check, and `armCheckAsOf` (+`stale` past 7 days). The marker
reads it from `data/counterfactual-reconcile.json`, so **the marker still needs no database**.
If no arm check is on disk the note says the emptiness is `UNEXPLAINED` and names the command
to run.

### (c) the hourly marker line says it too

```
shadow-wallet-cap: +0 marked this run (backlog 0). … | . FEED EMPTY: DORMANT (a real zero,
not a missing writer): 0 blocks in 7d, ceiling 0.25 x $3525.76 = $881.44 + frozen baseline
(basis delta). Nearest wallet 0x17dd123a… holds $505.13 = 57.3% of its $881.44 ceiling
($376.31 of headroom = 3.8x the largest clip booked in the window ($100.00)).
```

---

## 4. Reality checks

- **The Sep-19/20 counterfactual still does not exist and cannot be manufactured.** The 109
  vetoes are unpriceable — no entry price was recorded for them. The lane can only answer the
  question *forward*, from the next block. That is unchanged by this card.
- **Retirement was a live option and was rejected on measurement, not taste:** a lane that
  cannot fire must not sit in a reconcile table as if it could — that is now handled by (a)
  without giving up the recording. If the rail goes another window without binding, the
  `DORMANT` arm check is the evidence for retiring it later; the decision no longer rests on
  an empty file.
- **The replay is trajectory, not adjudication.** It approximates the decision-time ceiling
  with today's. The gate's `blocksInWindow` is the exact number and is what fails the build.
- **No rule, sizing, gate value or published PnL figure moved.** `maxWalletNotionalPctOfCap`
  stays `0.25`, `walletCapBasis` stays `delta`, the ceiling is unchanged at $881.44. The only
  published states that change are the reconcile gate's (4/4 → 3/4 + 1 EMPTY) and the
  summary's added `feedState` block — both were reporting a vacuous pass, which is the defect.
- **The writer was not "armed before the fix" either.** Its condition never held in 52 days;
  nothing was added to the write path, so the next real block records exactly as designed.

## 5. Verification

| Check | Result |
|---|---|
| `npm run shadow:reconcile` | `PASS` 3/4 populated lanes, 1 EMPTY, 0 mismatches, 0 contradictions, exit 0 |
| arm check, 7d window (live DB) | `DORMANT`, 0 blocks, 0 breached, tightest 57.3% |
| arm check, 60d window (live DB) | `FIRING`, 109 blocks, `contradiction=true` — the probe fails when it should |
| `DATABASE_URL` bogus | `arm check: UNAVAILABLE — <prisma error>`; gate still exits 0 (no false pass, no false fail) |
| marker (`MARK_LIMIT=1 npx tsx scripts/mark-shadow-longshot.ts`) | summary written with `feedState`, log line prints `FEED EMPTY: …` |
| `npx tsc --noEmit` | clean |
| `npx vitest run` | 91 files / **968 tests** pass (15 new in `tests/wallet-cap-arming.test.ts`) |

## 6. Revert

```bash
git revert <reconcile+marker+shadow-wallet-cap commits>   # returns the lane to a 10/10 pass on an empty feed
```

Nothing else depends on the new fields: `data/counterfactual-reconcile.json` has no other
consumer, and `feedState` is optional on `WalletCapSummary`.

## 7. Reproduce

```bash
npm run shadow:reconcile                                   # gate + arm check
python3 scripts/audit-wallet-cap.py --replay 7             # how close the rail came
sqlite3 prisma/dev.db "SELECT COUNT(*), MAX(datetime(createdAt/1000,'unixepoch')) \
  FROM DecisionJournal WHERE risksJson LIKE '%v58 per-wallet cap%'"   # 109, 2026-09-20 09:15:52
git log --follow --format='%h %ad %s' --date=iso -- src/lib/shadow-wallet-cap.ts
```
