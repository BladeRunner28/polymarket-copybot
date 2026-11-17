# C-200 clip cap, lane-wide vs band-scoped — measured, and the approval's premise does not survive it

**Card** `profit-c200-clip-cap-25` · **approval** `apr-profit-c200-clip-cap-25` (Lane A, clicked 2026-11-16 16:54Z) ·
**kanban** `t_4eb720b1` · **status: PROPOSAL ONLY — nothing applied, no RuleSet row written, no DB write, no merge**
**instruments (written with this doc, read-only):** `scripts/profit-c200-clip-cap.py` (python, DB `mode=ro`),
`scripts/profit-clip-frame-probe.ts` (ts, calls the scorer's own Kelly + λ̂ functions, writes nothing).
Both are in the working tree uncommitted on purpose — this proposal merges nothing to `main`; the 22:30
`copybot-git-backup` `git add -A` will carry them, or you can commit them with the apply.

---

## 0. Verdict in one paragraph

The approval's headline numbers **reproduce exactly** on its own population. Its **conclusion does not**.
The pending band-scoped cap (`profit-band-clip-rebalance`, `$25` on `0.0-0.2`) buys **+$172.13**; the lane-wide
cap this approval asks for buys **+$102.92** — i.e. **lane-wide is −$69.21 worse than band-scoped** on the same
legs and the same basis, and −$75.66 worse on the edge basis, because the only extra legs a lane-wide cap
reaches are the **profitable** ones (`0.80-1.00`, 7 legs, +$95.18, 7/7 wins). The out-of-band `$100` clips are
not an oversizing problem at all: they are bets the sizing model **would have refused at the price the book
paid** — 13 of the 41 `$100` legs were bought at 0.805-0.94 while their journal records the **0.0-0.2 band's
λ̂ (−0.68/−0.74)**, because the scorer priced the sibling token (`FillIntent.intentPrice` 0.06-0.195 =
`1 − booked`). At the paid price Kelly returns `SKIP: no edge` on every one of them, so the correct clip there
is **$0**, not $25 and not $100. A cap would hide that; the frame fix removes it.
**Recommendation: ship the band-scoped arm only (the card that already exists), and open a frame-fix card.
Do not ship the lane-wide cap.**

---

## 1. What was asked

> "cap C-200's per-leg clip at $25, lane-wide (not band-scoped): the $100 tier is 37% of live notional and the
> only losing dollar tier."

Two claims to test: (a) the `$100` tier is 37% of notional and is **the only losing** tier; (b) therefore the
defect is **clip-shaped, not band-shaped**, so the band-scoped cap under-reaches.

---

## 2. The approval's numbers reproduce exactly (its own basis)

Basis = one settled leg, cost = `simulatedPositionSize` (dollars at risk), population = `fillStatus != 'unfilled'`
(positions only, no dedupe — the basis `scripts/profit-supply-ladder.py` S3 used), `journal.ruleSetVersion >= 68`,
`2026-10-27..11-16`, now 19.7 d / **231** positions (the approval read 222 on 11-15; two days of settlement since).

| tier | legs | dollars at risk | share of regime | PnL | ROI | ROI 95% CI (market-clustered) |
|---|---|---|---|---|---|---|
| **$100** | 16 | $1,600 | **36.3 %** | −$135.65 | **−8.5 %** | [−65 %, +76 %] |
| $40-99 | 3 | $150 | 3.4 % | −$2.36 | −1.6 % | n/a (3 markets) |
| $20-40 | 31 | $620 | 14.1 % | +$189.82 | +30.6 % | [−24 %, +86 %] |
| $12-20 | 49 | $876 | 19.9 % | +$78.04 | +8.9 % | [−33 %, +53 %] |
| <$12 | 132 | $1,159 | 26.3 % | −$58.71 | −5.1 % | [−28 %, +18 %] |
| **book** | 231 | $4,405 | 100 % | **+$71.14** | **+1.6 %** | |

The approval's legs (16), dollars ($1,600), PnL (−$135.6) and ROI (−8.5 %) reproduce to the cent; the **share**
reads 36.3 % today vs the approval's 37.3 % because the book's denominator grew ($4,288 → $4,405) while the tier's
numerator did not. Cap shadow at `$25` on this basis:
**+$102.92 on 19 touched legs, book ROI +1.6 % → +5.6 %** (the 11-15 read printed +3.1 % → +7.9 %; the book has
moved, the delta has not). So the arithmetic in the approval is right. Three of its readings are not.

---

## 3. What does not survive

### 3.1 "the only losing dollar tier" — false on its own table

`<$12` is **−5.1 %** (−$58.71 on $1,159) and `$40-99` is −1.6 %. The `$100` tier is not the only loser; it is the
largest tier by dollars and the largest loser **in dollars**. Those are different statements and the second one
does not imply a clip rule (the `< $12` tier is 132 legs at $8.78 average — a cap cannot reach it).

### 3.2 The lane-wide reach is a COST, not a gain

The two arms differ on exactly one population: legs with `entryPrice >= 0.2` and size > $25. Measured:

| arm at $25 | touched | dollars kept | PnL delta | delta 95 % CI | book ROI |
|---|---|---|---|---|---|
| band-scoped (`<0.2` only) | 12 | $3,555 | **+$172.13** | [−$872, +$913] | +6.8 % |
| lane-wide (every C-200 leg) | 19 | $3,130 | **+$102.92** | [−$949, +$841] | +5.6 % |
| **lane-wide − band-scoped** | 7 | −$425 | **−$69.21** | | |

Same on the edge basis (all settled legs, `ppi.dedupe`): band +$331.60 on 31 legs, lane +$255.95 on 47 legs,
**−$75.66** for the 16 extra legs. The extra legs, by band:

| the oversized legs, by band | legs | dollars | PnL | ROI | win rate |
|---|---|---|---|---|---|
| `<0.20` cheap | 12 | $1,150 | **−$233.19** | −20.3 % | 8 % (1/12, the family's whole PnL is one +$552 win) |
| `0.80-1.00` favourite | 7 | $600 | **+$95.18** | +15.9 % | 100 % (7/7, mean win +$13.6) |
| `0.20-0.60` / `0.60-0.80` | 0 | — | — | — | no leg above $25 |

"Lane-wide" in practice means **cheap + favourite**; there is nothing between them above $25. So the approval's
extra reach is precisely the favourite band, and that band is the profitable half.

### 3.3 The delta is one leg, and its sign is not stable

The cap can only gain on losers (cutting a −$100 to −$25) and only pay on winners (cutting a +$552 to +$138).
Positions basis, 19 touched legs: **losers +$586.30 (11 legs), winners −$483.38 (8 legs)**. One leg — `+$552.23`
at `p=0.153`, opened 2026-11-11 — gives back **−$414.17** of the cap's value on its own. Remove it: **+$517.09**.
Remove the two largest positive contributions instead: **−$47.08** (sign flips). Both arms' CIs span zero by
~$850 on each side. Ex-top-3 wallets **+$548.78**, ex-top-1 market **+$517.09** — the whole number is that leg.

**Window contradiction.** The same cheap-band big-clip cell over the **last 30 d** (deduped, `profit-clip-effect.py`
§2) is **+44.9 % (+$3,260 on $7,256, 82 legs)** and `0.80-1.00 >= $25` is **+7.8 %, CI [+3.4, +12.3], CI excludes
zero**. The regime read (`−8.5 %`) and the 30-day read (`+44.9 %`) describe the same structure with opposite signs.
That is not a robust edge finding in either direction — which is exactly the conclusion the pending v73 write-up
already reached: a cap is a **drawdown rail**, not an edge trade.

---

## 4. The finding that changes the recommendation: the `$100` favourite clips are a PRICE-FRAME defect

Thirteen of the regime's 41 `$100` legs have `entryPrice >= 0.80` (0.805-0.94). Every one of their journal rows
carries a **cheap-band λ̂**:

```
0.825  λ̂=-0.74   intents absent      filled  +$21.21
0.865  λ̂=-0.68   intentPrice 0.135   unfilled
0.805  λ̂=-0.68   intentPrice 0.195   unfilled
0.940  λ̂=-0.68   intentPrice 0.060   unfilled
0.895  λ̂=-0.68   intentPrice 0.085   unfilled
... 13 of 41, all λ̂ ∈ {-0.68, -0.74} (= the 0.0-0.2 band), all booked at 0.805-0.94
```

`booked entry = 1 − intentPrice` on every linked leg, and `ObservedTrade.walletEntryPrice` sits with the **booked**
side (0.82 vs booked 0.825, 0.86 vs booked 0.865), not with the intent. The dispatch log says the same thing in one
line — `[KELLY] ucl-gal-stu-…-spread-home-2pt5 band=[0,0.2) λ̂=-0.680 q=0.336 p=0.135 f*=0.1163 avail=$8188
size=$100.00` — i.e. the scorer priced, banded, gated and **sized** the sibling token at 13.5¢, while the book holds
the token the outcome label names at 86.5¢. Kelly's own parameter doc says *"price: bought token price actually
paid"*. (Where the correct 0.865 enters the row is the fill-chain's own step — the four candidates are the sidecar's
depth guard, the fill adjudicator, an entry re-price and a backfill; **that is the open question this finding
hands to the frame card, and it is not needed to price the cap**: the scorer's inputs are the ones that are 5x off.)

`scripts/profit-clip-frame-probe.ts` runs the scorer's own `kellySizeForCopy` + `getBandLambda` on both frames:

```
scorer frame p=0.135  λ̂=-0.531  q=0.284  f*=0.1718  size=$100.00
book frame   p=0.865  λ̂=+0.413  q=0.755  f*=0.0000  size=$0.00   SKIP: no edge: q=0.755 ≤ price=0.865
… 7 of 7 complement-framed pairs: funded at the scorer's price, SKIP(no edge) at the price actually paid
paid-price frame at 0.75 / 0.80 / 0.85 / 0.90 / 0.94 -> $0.00 on all five
```

So the correct clip on those legs is **$0**, and it is $0 for a reason a cap cannot express: the band's λ̂ says
the favourite is **overpriced** (λ̂ = +0.413), while the sizing ran on a λ̂ that said "underpriced longshot".

Frame census (booked basis, 41 `$100` legs):

| frame | legs | dollars | PnL | bought ≥ 0.80 | cheap-band λ̂ in journal |
|---|---|---|---|---|---|
| COMPLEMENT (`entry = 1 − intent`) | 8 | $800 | **$0.00** (all 8 unfilled) | 8 | 8 |
| consistent | 28 | $2,800 | −$577.89 | 0 | 0 |
| no-intent (pre-FillIntent era) | 5 | $500 | **+$86.49** | 5 | 5 |

Realised cost of the frame defect so far: **$0** — the eight complement legs never filled (our maker bid sat
below the mid and was never hit). That is luck in the fill model, not a defence: the same path sized a
4x-oversized bet on a band the model says to avoid, and five of the no-intent favourites **did** fill and won
+$86.49 on a bet the model would have refused. Population-wide the complement class is 24 legs / $1,075.

**A $25 cap turns a $100 wrong-side bet into a $25 wrong-side bet. The frame fix turns it into no bet.**

---

## 5. What the cap does buy (the honest case for it)

| basis | series | worst day | max drawdown |
|---|---|---|---|
| positions | base | −$254.71 | −$771.51 |
| positions | band $25 | **−$161.52** | **−$324.95** |
| positions | lane $25 | −$163.84 | −$354.76 |
| booked | base | −$327.76 | −$744.69 |
| booked | band $25 | −$202.43 | **−$225.35** |
| booked | lane $25 | −$204.75 | −$255.16 |

Both arms cut worst-day and max drawdown by ~40-70 %; the **band arm gets more of it** (−$324.95 vs −$354.76
positions; −$225.35 vs −$255.16 booked) *and* a better PnL delta. This is the same "drawdown rail, not edge
trade" verdict the pending v73 card already carries — the lane-wide version just pays more for less.

Forward exposure check: **0 open legs above $25** today (32 open legs, $466.98), and `$100` clips arrive at
**0.80/day**. So this is a rule about ~1 leg/day of flow, not about the current book; nothing is "frozen" by
adding it, and nothing is repaired by it either.

---

## 6. The card's own gate, re-read

The roadmap card pre-registered: *apply if the `$25` shadow is `>= +$50` over the regime **and** the
`clip>=18` FE coefficient stays `<= −8 pp` with price and wallet held.* Today:

- shadow at `$25`: lane-wide **+$102.92**, band **+$172.13** → bar (a) passes on both arms;
- `profit-clip-effect.py` §4 FE (band + 2c price bin + wallet, market-clustered): `clip>=18` **−12.0 pp
  (SE 6.3, t −1.91)** and **−15.5 pp (SE 8.4, t −1.84)** → bar (b) passes; at the `$25` threshold itself the
  coefficient is **−4.3 pp (t −0.18) / +5.2 pp (t +0.47)**, i.e. indistinguishable from zero.

So by its own gate the change is *applied-eligible* — but the gate predates the frame finding and never
contemplated that the out-of-band cohort would be the profitable one. **Band-scoped passes the same gate with a
bigger number and without touching the favourite band.** That is the arm the gate supports when read today.

---

## 7. Options (effort / measured cost / measured purchase)

**A — RECOMMENDED. Ship the band-scoped `$25` cap only; do not widen it.** This is exactly the pending
`profit-band-clip-rebalance` / `apply-v73-c200-cheap-band-clip.ts` change (`c200BandClipCaps = "0.0-0.2:25"`,
one new field defaulted `""`). Cost: 5 code edits (Rules interface, `DEFAULT_RULES`, parser + min-only helper in
`src/lib/band-size.ts`, the `openPaperTrade` call site after `clampPaperSize`, the `score-trades.ts` pass-through),
plus the apply run **by you**. Buys +$172 / +$332 and the larger of the two drawdown cuts. Nothing further to write.

**B — the approval as written, via the one existing field.** `kellyMaxSizeUsd 100 → 25`. One field, no code edit,
revert = one field; `KELLY_BOTS = ["BANKROLL_200"]`, so it cannot reach STANDARD (which clamps at $20 anyway) —
"lane-wide" is really "C-200-wide". Buys +$102.92 / +$255.95 and −$354.76 / −$255.16 DD. **Costs −$69 / −$76 of
measured PnL vs A** by capping a band that won 7/7. Choose this only if you want the favourite tail capped
*before* the frame fix lands.

**C — the middle: `kellyMaxSizeUsd 100 → 50`.** Lane-wide at `$50`: +$67.82 (positions) / +$245.70 (booked) vs the
band arm's +$111.07 / +$288.94 at the same level → still −$43 / −$43 behind A, with half the tail insurance.

**D — the real fix (new card, Lane A): size and gate on the price of the token actually booked.** 24 legs / $1,075
are complement-framed regime-wide; 13 of the 41 `$100` legs are its visible symptom, and the same defect makes the
drift gate, the spread gate and the λ̂ band read a price a dollar off. Until this lands, any clip rule is
correcting a symptom.

---

## 8. Pre-registered refutation (write it on the card, so this cannot be re-litigated from prose)

- **Refutes the band arm (A):** on the first 150 forward settled `0.0-0.2` legs opened after the apply, the
  `$25`-capped cohort books **worse than −$300** on the cap-eligible subset, or the lane's `0.0-0.2` ROI goes
  **below −20 %**. (Baseline today: −20.3 % on the 12 oversized cheap legs, +44.9 % on the 30-day ≥$25 cell —
  the two readings that disagree.)
- **Refutes lane-wide (B):** the `0.80-1.00` lane clip stays positive for **30 settled days** with the cap in
  place and the cap-eligible favourite subset books **> +$200**. (Today: +$95.18 on 7/7 wins.)
- **Refutes the frame finding (D):** if a booked-vs-intent recomputation at the booked level finds the intent
  price, not the booked price, is the executable one on those legs, then the sizing was right and the *booking*
  is the defect. Test: re-read `ObservedTrade.walletEntryPrice` (0.82 vs booked 0.825, 0.86 vs 0.865) and the
  sidecar's own fill line on 10 complement legs before writing any rule.

## 9. Revert

- Arm A: `npx tsx scripts/apply-v73-c200-cheap-band-clip.ts --revert` (field back to `""`; no PaperTrade row is
  retro-edited).
- Arm B: `kellyMaxSizeUsd 25 → 100` via the normal `apply-vNN` path; no row is retro-edited — the cap only binds
  on legs opened after the change.

## 10. Reproduce every figure here

```bash
cd ~/polymarket-copybot
COPYBOT_DB="file:$PWD/prisma/dev.db?mode=ro" python3 scripts/profit-c200-clip-cap.py        # §2-§5, §6-§8 of this doc
COPYBOT_DB="file:$PWD/prisma/dev.db?mode=ro" python3 scripts/profit-supply-ladder.py        # the approval's S3 table
python3 scripts/profit-clip-effect.py                                                        # §4 FE, §2 30-day cohort
npx tsx scripts/profit-clip-frame-probe.ts                                                   # §4 Kelly frames
```

Both new scripts are read-only: the DB is opened through `COPYBOT_DB` (`mode=ro`) or not at all, no RuleSet row is
touched, no `PaperTrade` row is written, and `scripts/profit-clip-frame-probe.ts` imports the scorer's Kelly/λ̂
functions without any DB handle.

## 11. Explicitly NOT done

No `apply-vNN` run, no `RuleSet` row written, no `prisma/dev.db` write, no merge to `main`, no roadmap status
change. Nothing in this document changes what the bot decides or how much it risks until you run one of the
options above.

---

### Overridable flags (one line each, with the number that moves)

- `arm = BAND (0.0-0.2 only)` — override to `LANE` to take the approval as written; costs **−$69.21** measured
  PnL vs band and buys **−$29.81** more drawdown relief (positions: −$354.76 vs −$324.95).
- `level = 25` — override to `50` (option C) if you want the favourite tail halved rather than removed: −$43 vs band.
- `frame card = OPEN` — override to `HOLD` if you believe the intent price, not the booked price, is the executable
  side; then re-read §8's refutation test first.
- `cap $100 cheap clips at all` — override to `NO` if you take the 30-day read (+44.9 % on 82 legs) over the
  18-day read (−8.5 % on 16): the whole case for A is a drawdown case, never an edge case.
