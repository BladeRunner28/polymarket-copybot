# The exit-exemption read was priced on a minority sample — corrected on 94–100% of cuts, the hypothesis loses its evidence in both bands and no exemption ships

http://localhost:3013/drafts/band-exit-settlement-regeneration-20261123

**Instrument:** `scripts/analyze-band-exit-exemption.ts` (unchanged — the resolver fix landed 2026-10-29; only the six held artifacts were regenerated).
**Basis for every figure:** level = decision (one row per `marketId|outcome`, dedupe-collapsed; raw rows differ), `BANKROLL_200`, entry band `[lo, hi)`, cost = `simulatedPositionSize` (dollars at risk), DB opened `DATABASE_URL="file:./dev.db?immutable=1"`, `DATA_MODE=live`.
**Lane:** the regeneration was **approved** (`apr-exit-exemption-20-40-decision`, operator clicked 2026-11-23T13:22Z). The exemption itself is a Lane A rule change and **is not proposed here** — the verdict below is that none qualifies.

---

## Verdict in one line

**On the full population the 0.20–0.40 band's cuts and a hold-to-settlement are the same trade (−$8.33 apart on 97 window cuts, +$0.38 apart on 190 all-time cuts) where the stale column implied a $15–25 gap, the pre-named 24h bucket is still 5 priced tickets short of the guarantee, and the `<0.20` arm that motivated the whole exemption **reverses sign** once settlement is priced from the market — so both bands are NO EXEMPTION, the 0.20–0.40 clock extends, and the `<0.20` hypothesis is retracted rather than left standing on a minority sample and one +$812 longshot mark.**

---

## 1. What shipped

Six tracked artifacts carried **pre-fix** settlement values (generated 2026-09-14 … 09-27, before the `didOutcomeWin`/`settlementValue` repair). They were regenerated today and committed:

| file | arm | generated |
|---|---|---|
| `data/band-exit-exemption.json` | all-time, entry `[0, 0.20)` | 2026-11-23T13:26:16Z |
| `data/band-exit-exemption-20260913-0-0.2.json` | since 2026-09-13, `[0, 0.20)` | 2026-11-23T13:26:46Z |
| `data/band-exit-exemption-alltime-0.2-0.4.json` | all-time, `[0.20, 0.40)` | 2026-11-23T13:27:40Z |
| `data/band-exit-exemption-20260913-0.2-0.4.json` | since 2026-09-13, `[0.20, 0.40)` | 2026-11-23T13:24:54Z |
| `data/band-exit-exemption-0.2-0.4.json` | duplicate of the line above (legacy band-suffixed name, same `since`) | 2026-11-23T13:24:54Z |
| `data/band-exit-exemption-20260913-0.4-0.6.json` | since 2026-09-13, `[0.40, 0.60)` | 2026-11-23T13:28:27Z |

Commands (one per arm, ~1 min each):

```bash
export DATABASE_URL="file:./dev.db?immutable=1"
npx tsx scripts/analyze-band-exit-exemption.ts                                              # all-time  <0.20
npx tsx scripts/analyze-band-exit-exemption.ts --since 2026-09-13                            # window    <0.20
npx tsx scripts/analyze-band-exit-exemption.ts --band-min 0.20 --band-max 0.40               # all-time  0.20-0.40
npx tsx scripts/analyze-band-exit-exemption.ts --since 2026-09-13 --band-min 0.20 --band-max 0.40
npx tsx scripts/analyze-band-exit-exemption.ts --since 2026-09-13 --band-min 0.40 --band-max 0.60
```

## 2. The correction, arm by arm

`settle` is the hold-to-settlement counterfactual priced from the market's own resolution; `n` is PRICED tickets (the card's guarantee bar is 20).

| arm | cuts n | realized | settle BEFORE | settle AFTER |
|---|---:|---:|---|---|
| all-time `<0.20` | 43 → **116** | −$179.63 → **−$989.68** | −$38.82 (n=5) | **−$1,543.29 (n=103)** |
| since 09-13 `<0.20` | 10 → **74** | −$191.85 → **−$203.78** | −$19.95 (n=1) | **−$621.39 (n=62)** |
| all-time `0.20–0.40` | 112 → **190** | −$75.92 → **−$378.73** | −$333.83 (n=41) | **−$379.11 (n=181)** |
| since 09-13 `0.20–0.40` | 18 → **97** | −$48.75 → **−$346.36** | −$64.18 (n=9) | **−$338.03 (n=91)** |
| since 09-13 `0.40–0.60` | 66 → **95** | −$51.65 → **−$70.61** | −$83.57 (n=41) | **−$62.11 (n=95)** |

Two things moved at once and they must be read separately: **the population grew** (the files were 2–10 weeks old) and **the settlement label was repaired** (pre-fix, 106 of 107 market-settlement rows were valued 0 by a raw-label compare). The priced share says which one caused a given move — it went from **10–62% to 84–100%** of cut tickets:

- all-time `<0.20` 5/43 → 103/116 · window `<0.20` 1/10 → 62/74
- all-time `0.20–0.40` 41/112 → 181/190 · window `0.20–0.40` 9/18 → 91/97
- window `0.40–0.60` 41/66 → 95/95

`settlementSource` on the regenerated rows is `market-settlement` for 279/304, 214/230, 523/534, 396/403 and 340/340 rows respectively; **no `own-resolution` label survives in any file** (`grep` over all six returns nothing), which is the fix's own acceptance test.

## 3. What the corrected column does to the decision

**0.20–0.40 — cutting and holding to settlement are the same trade.** Window arm: realized −$346.36 vs hold-to-settlement −$338.03, i.e. the cut cost **$8.33 more** than holding on 97 decisions. All-time: −$378.73 vs −$379.11, **$0.38 apart on 190**. Every priced horizon in the window arm is worse than the cuts we actually took — 1h −$264.15 (n=64), 6h −$186.90 (n=29), 24h −$95.12 (n=15), 72h −$62.01 (n=9), 168h −$47.19 (n=7) — so on the population we run in, holding bought nothing.

**`<0.20` — the motivating read reverses sign.** Pre-fix, all-time settlement read −$38.82 on 5 tickets against −$179.63 realized: holding looked **$141 better**. Corrected on 103 tickets it is −$1,543.29 against −$989.68: holding is **$554 worse**, and the window arm agrees at every horizon (1h −$1,386.92 n=56, 6h −$567.10 n=38, 24h −$575.34 n=24, 72h −$444.57 n=18,168h −$642.34 n=17 vs −$203.78 realized).

**The one arm that still "wins" is one leg.** All-time `<0.20` at 24h prints +$156.73 (n=31) — a hold-to-horizon read that beats the cut by $1,146. It is dominated by a single mark: `will-russia-target-kyiv-on-september-7-2026`, entry $0.034, $100 clip, cut at +28.1h for −$4.41, +24h mark $0.31 → **+$811.76**, and it then **settled at zero** (−$100). Ex-top-3 the bucket is **−$728.80**; 3 of 20 positive at 72h; 8 of 31 at 24h. So the all-time arm is not a direction the window arm contradicts — it is one unrealised spike, and the leg proves the mark is not a fill.

**`0.40–0.60` — same shape, no story.** −$70.61 realized vs −$62.11 settlement on 95 priced: cutting cost ≈$8.50 across a whole band.

## 4. The pre-registered rule, applied

Rule (in the card, binding since 2026-09-20): exemption ships ONLY IF, on the band's own sample, (1) hold-to-horizon at the pre-named horizon beats realized on a bucket with **≥20 priced** tickets, AND (2) the direction also holds in the all-time arm, AND (3) **≥20 decisions were cut**.

| | 0.20–0.40 (pre-named 24h) | `<0.20` (pre-named 72h) |
|---|---|---|
| (1) window arm, ≥20 priced | **FAILS** — 15 priced, 5 short. Direction favourable (−$95.12 vs −$346.36) but the count gate has no exceptions | **FAILS on both** — 18 priced, and direction unfavourable (−$444.57 vs −$203.78) |
| (2) all-time direction | holds (−$99.09 on 22 vs −$378.73) | nominally holds (−$411.39 on 20 vs −$989.68) but is one leg (ex-top-3 −$489.40) |
| (3) ≥20 cuts in band | passes (97) | passes (74) |
| **verdict** | **NO EXEMPTION — EXTEND THE CLOCK** | **NO EXEMPTION — hypothesis retracted** |

For 0.20–0.40 the count test is the binding clause and nothing else is: the 24h bucket was also 15 priced tickets at the 2026-11-20 read, so it has not advanced in three days.

**Why that bucket fills slowly — by design, not a defect.** `src/lib/exit-recovery.ts` sweeps only `status='closed'` trades inside a 192h window and stops tracking a ticket once it carries a `168h` or `final` mark. A cut whose market resolves before +24h therefore leaves the bucket on its `final` mark. Of the 97 window-band cuts, 91 have already settled and only 15 carry a 24h mark (9 of those settled *later* than +24h, 6 still unpriced). The 24h population is exactly "cuts whose market was still live 24h later", which is the right frame for the question — but at ~1.4 cuts/day × ~15% survival it accumulates ~0.2 priced tickets/day, so ≥20 is ~3–4 weeks out and the tracker itself is alive (last mark written 2026-11-23, ~7h before this read).

## 5. Verification

- **The refuter in the approval ask does not fire.** It said the artifacts must not ship if a regenerated file disagrees with the 2026-11-20 probe **on the same clock**. Re-read against `data/band-exit-exemption-probe-*-20261120.json`: settle −$318.09 (n=89) → −$338.03 (n=91); all-time −$359.17 (n=179) → −$379.11 (n=181); `<0.20` all-time −$1,403.29 (n=100) → −$1,543.29 (n=103); `<0.20` window −$481.39 (n=59) → −$621.39 (n=62); `0.40–0.60` −$62.11 (n=95) → −$62.11 (n=95). Every arm moved by 1–3 priced tickets and $0–140 in the direction the extra flow implies; the 24h/72h counts moved by 0–3. No contradiction.
- **Label integrity:** `settlementSource` histogram per file printed above; `own-resolution` count = 0 across all six.
- **Basis preserved:** each file's `botId`/`bandMin`/`bandMax`/`since`/`dedupeCollapsed` header still describes the arm it is named for; the duplicate `-0.2-0.4.json` is the window `0.20–0.40` read under its legacy name (byte-identical to `-20260913-0.2-0.4.json`), so a reader of either path gets the same corrected numbers.
- **Before state recoverable:** all six pre-fix files are in git history (blobs unchanged from `HEAD` before this run), so the old columns stay quotable as history and `git revert` restores them.

## 6. Rollback

`git revert <regeneration commit>` — restores the six pre-fix artifacts and the card note. Nothing in the live lane moved: no RuleSet read or write, no `apply-v*.ts`, no `prisma` write, no exit-rule change. The exemption itself stays unimplemented, which is what this card decided twice before.

## 7. Files changed

- `data/band-exit-exemption.json`, `-20260913-0-0.2.json`, `-alltime-0.2-0.4.json`, `-20260913-0.2-0.4.json`, `-0.2-0.4.json`, `-20260913-0.4-0.6.json` (regenerated)
- `data/roadmap.json` — card `exit-exemption-20-40-decision` closed with the corrected numbers; standing weekly re-read moved to `exit-exemption-20-40-reread`
- `drafts/band-exit-settlement-regeneration-20261123.md` (this document)
