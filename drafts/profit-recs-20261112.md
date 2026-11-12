# Profit review 2026-11-12 — the lane we just tripled is the lane whose fills we can prove are losers

http://localhost:3013/drafts/profit-recs-20261112

**Instrument:** `scripts/profit-fill-cohort.py` (new, read-only, self-tests **4/4**, committed with this
file). It imports `scripts/profit-postfix-integrity.py` for loading and CI so the basis is identical to
yesterday's tables. Run:

```
python3 scripts/profit-fill-cohort.py
```

Cost basis everywhere below: `simulatedPositionSize` = **dollars at risk** (not shares), deduped to the
first leg per `bot|wallet|market|outcome` within status class, price = the price of the token we bought
(INVERTED legs repriced to the wallet's own fill), CIs market-clustered (2,000 draws). Population:
13,226 non-demo rows → **5,842 finished legs, $67,986 at risk**.

---

## 0. What today actually changed

The fill-aware booking flip (`src/lib/paper.ts`, DEFAULT ON since **2026-10-28**) stopped booking PnL on
legs the resolver proved never traded. Nobody has split the book by that class since. Every band table,
the ladder read and the capital series still sum `realizedPnl` across **filled + unfilled + unresolved**
as if they were one population.

They are not. Splitting them, on the C-200 lane that carries 84.7% of post-flip notional:

| era | class | legs | notional | PnL | ROI |
|---|---|---|---|---|---|
| pre | filled | 129 | $1,122 | +$452.20 | +40.3% |
| pre | unfilled | 247 | $2,234 | **+$801.10** | +35.9% |
| pre | unresolved | 1,485 | $12,806 | +$5,023.30 | +39.2% |
| pre | TOTAL | 1,861 | $16,163 | +$6,276.60 | +38.8% |
| post | filled | 60 | $1,103 | **−$515.50** | **−46.7%** |
| post | unfilled | 132 | $3,181 | +$0.00 | 0.0% |
| post | unresolved | 79 | $2,604 | **+$465.90** | +17.9% |
| post | TOTAL | 271 | $6,888 | −$49.70 | −0.7% |

The pre-flip row is the known defect: **$801 of booked profit on legs that never traded — 63.9% of that
era's stamped PnL**, reproducing the 61% in `paper.ts:20-22` (the small gap is the pre-flip legs I dedupe
away). The flip stopped it. What it did not do is tell us what the lane earns now:

- **Proven fills: 60 legs, −$515.50, −46.7%, clustered CI [−70.9, −14.4].**
- **Never-observed fills: 79 legs, +$465.90, +17.9%, CI [−30.7, +80.1].**
- Filled minus unresolved: **−64.6pp, CI [−132.1, −8.0].**

On the strictest basis — naturally resolved legs only, no early closes — it is worse, not better: **225
legs, +$467.10 (+9.1%)**, of which the **51 filled legs are −$401.70 (−43.8%, CI [−70.7,−2.4])** and the
**62 unresolved legs are +$868.80 (+47.7%, CI [−18.1,+131.7])**. The lane's entire positive number lives
in the class where nobody saw the fill.

And it is not one leg. Removing the filled cohort's best legs makes it worse, not better: ex-top-1
−52.5%, ex-top-3 −61.4%, ex-top-5 −69.6%.

---

## 1. The class that decides the lane can never be adjudicated — I checked

Before calling this a case for halting anything I tried to resolve the 79 legs, because "unresolved"
was always meant to be temporary. Dry run of the repository's own resolver
(`DATABASE_URL="file:$PWD/prisma/dev.db" npx tsx scripts/c200-fill-resolve.ts`, **dry by default,
writes nothing**):

```
print-through artifact: 802 distinct intents
VERDICTS (legs with no stamp yet, INSIDE this run's population only):
  filled 0   unfilled 0   unresolved 1   already stamped 582
BASIS: 582 stamped, 2,248 with NO stamp. This run could see 1 of those 2,248;
       2,247 are INVISIBLE here and keep booking at p(fill)=1.
=> resolution coverage 0.0% of 1 (floor 80% was WAIVED)
```

The print-through artifact is a **rolling window**. It holds 802 intents, all already stamped. The 2,247
unstamped legs are outside it permanently, and the venue's book history is not queryable after the fact.
So this is not a backlog to work off — **the unresolved class is undecidable forever, and
`bookedPnl` will keep booking it at p(fill)=1.**

That is the asymmetry that decides my first recommendation. For C-200 the book has two classes of
evidence: a **proven** class that reads −46.7% with a CI excluding zero, and an **unprovable** class that
reads +17.9% with a CI spanning zero. The lane's headline (−0.7%) is the sum of them.

---

## 2. It is not the price we bid, and it is not the clip we bet

I expected the defensible story to be adverse selection: we bid 2c under the wallet, so we only get filled
when the price comes to us. The bid does not support it — entry minus intent is **−0.38c on filled legs
(59)** and **−0.32c on unfilled (111)**. Same discount, different outcome. What differs is whether the
book came to us, not what we offered.

I also expected the pending clip cap to explain it, since the cap's premise is that large cheap clips are
the problem. Post-flip, by clip, on filled legs only:

| clip | legs | notional | PnL | ROI | hit% |
|---|---|---|---|---|---|
| ≤$10 | 37 | $352 | −$53.60 | −15.2% | 37.8 |
| $10–20 | 19 | $351 | −$100.30 | −28.5% | 21.1 |
| >$40 | 4 | $400 | −$361.60 | −90.4% | 0.0 |

Pre-flip the same buckets were **+21.5% / +54.1% / +53.1%**. Post-flip every bucket loses, including the
$10 one. **A $25 cap leaves the lane negative at the sizes it keeps** — it removes some of the loss, it
does not fix the lane. (n is small: 37, 19, 4. Treat the gradient as suggestive and the sign as the
finding.)

By band, post-flip filled: cheap **11 legs, −$480.50 on $535, 0 wins**; 0.2–0.4 31 legs −6.6%; 0.6–0.8 18
legs −5.0%. **The cheap cell's 0-for-11 is not evidence of anything** — at a 13c average price a 0-win
run of 11 happens 28% of the time under a perfectly calibrated book. I am not claiming cheap-band
adverse selection from it.

---

## 3. The mirror: paying up for fills is not the fix either

The obvious response is "bid more, get filled". Repricing the no-fill intents at their own intent price,
held to the mark they ended at (sibling-priced legs excluded, |entry−intent| > 6c — a first draft that
left them in claimed **+$7,247 of forgone profit on 10 legs**, all of it the sibling token's price):

| class | legs | notional | PnL @ own intent | ROI | @ intent + 2c |
|---|---|---|---|---|---|
| unfilled | 111 | $2,183 | −$50.30 | −2.3% | −$268.30 |
| filled | 59 | $1,094 | −$527.00 | −48.2% | −$562.80 |

The trades we did not get would have lost money too, and would lose more if we paid up. **Chasing fills
buys nothing here** — this closes the fillability question for this lane with a measurement rather than
an assumption, and it kills the "we're leaving money on the table by bidding 2c behind" hypothesis I
would otherwise have proposed.

---

## 4. The structural change nobody has priced

Between eras the book changed shape, not just bookkeeping:

| lane | era | legs/day | avg clip | notional | share |
|---|---|---|---|---|---|
| STANDARD | pre | 34.6 | $12.1 | $43,688 | 73.0% |
| STANDARD | post | **7.4** | $11.8 | $1,247 | 15.3% |
| BANKROLL_200 | pre | 19.2 | **$8.7** | $16,163 | 27.0% |
| BANKROLL_200 | post | 18.8 | **$25.4** | $6,888 | **84.7%** |

STANDARD's flow fell **78%**; C-200's clip **tripled**; and the book's notional went from 73% STANDARD to
**85% C-200** — the lane whose proven fills are the ones that lose. Post-flip the whole book is 377 legs,
$8,135, **+$184.80 (+2.3%)** in 14 days.

I am not calling the clip increase the cause: the two changed in the same week as a dozen other things.
I am saying the lane mix and the size both moved at the same moment as the sign, in the same direction,
and the ladder is now advancing on a book that is 85% a lane with a −46.7% proven-fill record.

The other lane is unmeasured, not good. **0 of 3,710 STANDARD legs carry a fill verdict.** Its +18.8%
post-flip is the same p(fill)=1 optimism that was worth **2.87x** on C-200 where it was checked. The two
lanes are not comparable, and no cross-lane allocation should be decided until one of them is checked.

---

## 5. What I am not re-litigating

- **0.2–0.4 stale-exit at 168h** now reads **+$1,106, CI [+28%, +107% of notional]** on 107 settled legs
  (`profit-velocity.py` §V, which I ran and did not write; it is not in my commit). The 2026-10-23 card
  says do not propose there until **one population reaches 150 settled legs**. It is at **107**. I am
  reporting the number and proposing nothing.
- **Gate tuning** stays exhausted; nothing here touches a gate.
- **Exit alpha** stays closed; §2's exit is not an exit-policy question.
- **The pending clip cap** (`profit-band-clip-rebalance`, card in Scheduled) reproduces and its drawdown
  argument stands on its own — max DD −$1,052 → −$599, regime +$790 CI [+$290,+$1,324], as measured in
  that card's own preflight (`scripts/profit-band-clip-preflight.py`); **I did not re-derive those two
  numbers today.** §2 changes only its *edge* rationale, not its insurance rationale.
- **The 0.2–0.4 "only cell that never changed sign"** from yesterday no longer holds on the live window:
  the regime band map (`python3 scripts/profit-postfix-integrity.py --only=C`) now reads **tol −5.1pp on
  139 legs (+14.0% ROI, CI [−13.5,+41.8])** where yesterday it read +7.6pp on 90. The lift was already
  deferred; this is a reason to keep it deferred, and a contradiction I am reporting rather than quietly
  dropping.

---

# Recommendations

Ranked by expected value. Anything that changes what the bot decides or how much it risks is **Lane A —
propose only, nothing applied.**

### 1. Quote, size and advance the ladder on proven fills — C-200 (Lane A, 1h)

- **Hypothesis:** the C-200 lane's post-flip sign is set by a fill class that has never been observed, so
  its booked −0.7% understates the loss and its +17.9% unresolved class is not evidence of anything; the
  lane's real record is its proven fills, which is −46.7%.
- **Measurement:** §0–§1 of `scripts/profit-fill-cohort.py`. Filled 60 legs −$515.50, CI [−70.9,−14.4];
  unresolved 79 legs +$465.90, CI [−30.7,+80.1]; filed − unresolved −64.6pp CI [−132.1,−8.0]. Resolver dry
  run: 2,247 legs unstamped and invisible to it, coverage 0.0% — the class cannot be adjudicated later.
- **Decision rule:** the read path quotes `filled` as the lane's ROI and treats `unfilled`/`unresolved` as
  zero-exposure for sizing and for ladder credit. **No C-200 clip increase and no clip above its pre-flip
  average ($8-10) until the filled cohort reaches 120 legs with a CI that includes zero**; re-read then.
  Four of the post-flip filled legs are already at >$40 (−90.4%, 0 wins).
- **Refutation:** if the venue's archived trade tape (or any surviving book capture) shows **≥70% of the
  79 unresolved legs printed at or below our bid**, they were real positions, the proven-fill cohort is a
  selected minority, and the lane is not negative — I withdraw this.
- **Expected effect:** **$0 in paper today** — the lane is flat. It stops the ladder crediting roughly
  **+$466** of profit no fill ever produced and stops a further clip raise in a lane whose only proven
  record is −46.7%. At the 2027 anchor it is the difference between sizing on evidence and sizing on a
  class that cannot be measured.
- **Cost:** 1h (one flag in the ROI reader + the ladder string). The tape adjudication, if attempted, is
  a separate 2h and is the only thing that can refute it.

### 2. Retire the *edge* premise of the pending clip cap; keep it as insurance (Lane A, 30m to amend)

- **Hypothesis:** the cap's stated mechanism — large cheap clips are the problem — is not what the filled
  data shows; post-flip, filled legs lose at **every** clip size (−15.2% at ≤$10, −28.5% at $10–20), so a
  $25 cap leaves the lane negative at the sizes it keeps.
- **Measurement:** §2 table (filled legs by clip, each era). Pre-flip +21.5/+54.1/+53.1; post-flip
  −15.2/−28.5/−90.4.
- **Decision rule:** amend the card to argue only the drawdown case (max DD −$1,052 → −$599; regime
  +$790 CI [+$290,+$1,324]) and **drop the claim that it fixes the lane**. Do not raise the cap to $0 on
  my numbers — 60 filled legs is not enough to justify a lane-wide zero.
- **Refutation:** a forward 120-leg filled cohort with **≤$20 clips non-negative** while **>$40 stays
  negative** restores the size gradient and makes the cap the right instrument again.
- **Expected effect:** prevents an approval that would read as "lane fixed" while leaving −15% at the clip
  it keeps. $0 direct.
- **Cost:** 30m (card note; I will not edit the RuleSet or any rule row).

### 3. Give STANDARD a fill verdict before any cross-lane allocation (Lane B build, 3–4h)

- **Hypothesis:** STANDARD's +18.8% post-flip carries the same p(fill)=1 optimism that overstated C-200 by
  2.87x, so the book's only positive lane may be an artifact of never having asked the question.
- **Measurement:** §5 — **0 of 3,710 STANDARD legs carry a fill verdict**; 100% of its rows book at
  p(fill)=1. The capture exists for C-200 only (`scripts/c200-fill-resolve.ts` + the print-throughput
  artifact).
- **Decision rule:** capture print-through for STANDARD legs going forward (the same join, the same
  reachability model); if **≥25% of STANDARD's booked notional proves unfilled**, re-price the book and
  freeze allocation changes until it is re-based. Below 10%, the lanes become comparable and I drop the
  caveat.
- **Refutation:** if ≥90% of STANDARD's notional proves filled, the lane's number stands as booked and
  this is a non-issue — which is the outcome I expect, because STANDARD bids at-or-below the wallet's
  price on **57% of 106 post-flip legs (mean −0.79c)** and copies at ~$12 clips.
- **Expected effect:** $0 paper; it decides whether the book has one measured lane or none.
- **Cost:** 3–4h, mostly wiring the capture into the STANDARD scoring path.

---

**IF YOU WEREN'T HERE:** freeze the C-200 clip back to its pre-flip level and stop the ladder crediting
its unresolved class — the only lane with a fill verdict is losing 46.7% on the legs it can prove, and the
book just tripled that lane's clip and handed it 85% of the notional.

---

### Instrument repairs performed directly (Lane B, no approval needed)

- **New `scripts/profit-fill-cohort.py`** — era × fill-class census, proven-fill CI, filled-vs-unresolved
  delta CI, band and clip mechanism tables, the no-fill mirror, mix shift, era-boundary sensitivity, and
  four self-tests (**4/4 pass**: class partition, post-flip unfilled books exactly $0.00, the pre-flip
  phantom share reproducing 63.9% against `paper.ts`'s 61%, and delta-CI antisymmetry under arm swap).
  Read-only URI; no prisma write, no RuleSet read or write, no rule edit.
- **Two of my own basis errors caught before quoting:** (a) the first mirror run reported **+$7,247 of
  forgone profit on 10 legs** — sibling-priced (INVERTED) legs whose `entryPrice` is the other token's
  price; excluded by |entry−intent| > 6c and the whole arm flips to −2.3%; (b) the base loader does not
  select `intentPrice`, so the first §3(b) printed an empty table rather than a wrong one — joined by id
  instead of editing a shared instrument's SQL that a sibling session is working in.
- **Ran, did not write:** `scripts/c200-fill-resolve.ts` (dry by default) and
  `scripts/profit-velocity.py --only-t` (§V's 0.2–0.4 figure is quoted from that run and is **not** in my
  commit; it is flagged as such).
- Nothing else touched: no rule, threshold, gate, size or lane moved; no `apply-v*.ts` run; no card edited.
