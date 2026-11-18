# Paid-up entry cohort — the executable rule the card asked for is NOT the rule that produces the effect

**Lane A — PROPOSAL ONLY. Nothing applied.** No `apply-vNN`, no `prisma/dev.db` write, no RuleSet
field, no dispatch code touched, no merge. Every figure below is reproduced by
`python3 scripts/paid-up-book-gap.py` (read-only, DB `mode=ro`), committed in the same change.

Measured 2026-11-18 against card `paid-up-entry-cohort` (roadmap) / kanban `t_45c78307`.

---

## Verdict in three lines

1. **The class is real but the card's numbers no longer reproduce**: today the tape-reachable book is
   **−$724.6 (−4.1%)** and removing the paid-up legs gives **+$433.3 (+3.1%)** — the card says
   −1.9% → +5.5%. Direction unchanged, magnitude ~40% smaller.
2. **The gate's own caveat resolves to "do not write this rule".** The executable form —
   *entry above the best ask at dispatch* — fires on **41 legs / $439** ever and on **1 leg** post the
   2026-11-09 price-side fix. It captures 10.6% of the class. A rule that fires once in 8.8 days is
   not a rule.
3. **The loss is not "we paid up" — it is "the quote was moving at dispatch".** Where the snapshot
   book and the venue tape agree within 0.5c (68.5% of legs), paying up 0..+2c returns **+0.3%** and
   ≥+2c returns **+52%**. All of the loss sits where the two mid bases disagree by ≥1c, in *both*
   directions (over-paid −29.7%, under-paid −36.4%). That is the signature of a moving/flickering
   book, and no quantity the scorer holds at dispatch separates it at our sample size.

**Recommendation: do not enforce an entry-price rail. Ship the write-only `[PAID-UP]` shadow with the
*executable* fields, and re-register the 150-leg bar on the class the shadow can actually act on.**

---

## 1. What was carded

The card carries three claims: paying above the market at dispatch loses monotonically
(−17.7% at 0..+2c, −41.6% at ≥+2c), removing the class moves the tape book from −1.9% to +5.5%
(+$1,055.9 on 22% of notional), and the pre-registered bar (150 post-fix paid-up legs at ≤ −10% ROI
with a market-clustered CI excluding zero) stands at 19/150 so **no live change ships today** —
only a write-only `[PAID-UP]` line per cycle.

The card's `gate` field adds the caveat that decides the implementation: *"gap is measured against a
print price, not the book the bot saw; the executable form is 'entry above the best ask at dispatch'
and the mapping from print-gap to book-gap is unmeasured — measure that join before writing the rule."*

That join is what this document measures.

## 2. The card's headline, re-cut today

Tape basis, unchanged definition (`gap = booked price we paid − prices-history midpoint at dispatch`;
`tape_p0` = first print at/after dispatch−120s; **0% of p0 prints predate dispatch, median +31s**, so
the p0 basis is sound — that hypothesis is excluded rather than asserted).

| class | legs | cost | PnL | ROI | cluster CI |
|---|---|---|---|---|---|
| as traded (tape-reachable) | 1,143 | $17,851 | −$724.6 | −4.1% | [−17.6,+10.8] |
| paid at/below print | 890 | $13,763 | +$433.3 | +3.1% | [−13.0,+22.6] |
| **paid up (print > 0)** | **253** | **$4,088** | **−$1,157.9** | **−28.3%** | **[−46.5,−5.5]** |

The swing is $1,157.9 on 22.9% of notional. The paid-up class's CI now excludes zero on the full
reachable book — the card reported [−42.5,+13.6] on the 0..+2c arm.

**What moved since the 2026-11-17 read**, and it is not an entry-price effect: 19 new reachable legs
landed, and 13 of them are at/below-market legs that cost **−$292.6 on $346 (−84.6%)**. They are
Dota 2 and BTC-bracket legs booked at $100 clips (`dota2-lgd-pari-2026-11-17` ×2, `will-bitcoin-dip-to-62k`):
esports outcomes going to zero, not entries paid up. That is what pulled the at/below class from
+5.5% to +3.1%. **A headline whose sign survives a 13-leg esports week is not yet a stable number** —
one more reason not to enforce on it.

Split by lane (unchanged story): 134 C-200 legs / $1,969 and 119 STANDARD legs / $2,119. It is a
booking problem in both lanes, as the card already says.

## 3. The join the card demanded — print gap vs the quoted book at dispatch

Book at dispatch = `MarketSnapshot` bestBid/bestAsk (the same keyless collector `profit-taker-entry.py`
uses), joined ±300s and side-mapped on the leg's own token against the tape.

- coverage: **1,078 / 1,143 = 94.3%** (no snapshot 10, side-ambiguous 55, bad book 0)
- snapshot age at dispatch: median **24s**, p90 129s
- `|book mid − tape mid|`: median **0.00c**, p90 3.0c, 16.2% above 2c → the two bases are comparable,
  not two different animals

### 3a. Where the booked entry sat in the quoted book

| print bucket | entry ≤ mid | mid..ask | through ask |
|---|---|---|---|
| gap ≤ −2c (rested) | 144 (98.6%) | 0 | 2 (1.4%) |
| gap −2..0c | 666 (95.6%) | 17 (2.4%) | 14 (2.0%) |
| gap 0..+2c (paid up) | 134 (**89.3%**) | 3 (2.0%) | 13 (8.7%) |
| gap ≥ +2c (crossed) | 71 (83.5%) | 2 (2.4%) | 12 (14.1%) |

Of the 235 book-mapped print-paid-up legs, **25 (10.6%) were through the offer** and **30 (12.8%) were
above the book mid** at dispatch. The other ~87% were at or below the mid of the book the bot could see.

### 3b. Where the loss lives — 2×2 of the two bases

| cell | legs | cost | PnL | ROI | CI | med det→dispatch lag |
|---|---|---|---|---|---|---|
| A print>0 **and** above book mid ("real" paid-up) | 30 | $243 | +$12.9 | +5.3% | [−41.5,+52.6] | 466s |
| **B print>0, book says ≤ mid** | **205** | **$3,650** | **−$1,082.9** | **−29.7%** | **[−49.5,−5.1]** | 308s |
| **C print≤0, book says above mid** | **33** | **$569** | **−$207.3** | **−36.4%** | **[−64.1,−5.3]** | 503s |
| D neither (both say rested) | 810 | $12,703 | +$662.4 | +5.2% | [−11.5,+24.1] | 401s |

Both disagreement cells lose with a CI excluding zero. The "real paid-up" cell — the one an
entry-price rule would target — is **flat positive**.

### 3c. Agreement-conditioned (kills the basis-noise explanation)

Where the book mid and the tape mid agree within 0.5c (738 legs, 68.5%):

| print class | legs | cost | PnL | ROI |
|---|---|---|---|---|
| at/below | 674 | $10,708 | +$270.8 | +2.5% |
| paid 0..+2c | 55 | $813 | +$2.5 | **+0.3%** |
| paid ≥+2c | 9 | $96 | +$50.0 | **+52.3%** |

At ≤1c agreement (849 legs) the 0..+2c arm reads −17.6% but the ≥+2c arm reads **+26.7%**. The
monotone dose-response the card reports exists **only across legs where the two mid sources disagree**.
It is not a stable property of the entry price.

## 4. The executable rules, priced

| rule (fires = skip these) | legs | cost | PnL | ROI | CI | book after removal |
|---|---|---|---|---|---|---|
| skip entry **through the ask** | 41 | $439 | −$114.7 | −26.1% | [−59.0,+9.3] | −$500.3 (−3.0%) |
| skip entry **above the book mid** | 63 | $812 | −$194.4 | −23.9% | [−48.3,+2.3] | −$420.6 (−2.6%) |
| skip entry **above the tape mid** (print basis) | 235 | $3,893 | −$1,070.0 | −27.5% | [−46.4,−5.0] | +$455.1 (+3.4%) |

Only the third arm produces the card's effect, and it is the one **the bot cannot evaluate at dispatch**
(the tape series does not exist in-process; the book does).

### The live proxies the scorer already holds

`profit-taker-entry.py` shows the mapped book is coherent (bid ≤ mid ≤ ask on 450/450 v68+ legs,
booked entry at/below the ask on 99.8%). Attempting to build a dispatch-time rule from what the scorer
actually sees:

| proxy | best bucket | worst bucket | verdict |
|---|---|---|---|
| quoted spread at dispatch | ≤1.5c: +2.0% (615) | 2.5–5c: −19.2% (189) | suggestive, not clean; CIs all span zero |
| snapshot age at dispatch | 30–60s: +9.5% (91) | ≤30s: −10.2% (560) | no ordering |
| \|entry − book mid\| | 0.5–1c: +21.1% (35) | >5c: −56.1% (19) | non-monotone |

**No proxy the scorer holds separates the losing legs at our sample size.** Naming that plainly is the
finding: an entry-price rail written today would be a coin flip dressed as a rule.

## 5. What this means (and how it squares with the addendum)

The card's 2026-11-18 addendum already closed the mechanism half: crossing the spread loses
(−6.8% per intent-dollar) and the depth ladder is negative at every level. This measurement says the
*same thing from the other side*: the print-gap class is not "we crossed"; it is "our entry level was
set from a read that the market had left". It is adverse selection showing up in the entry price rather
than in the fill, and it is the effect `profit-fast-adverse-stop` monetises through the exit.

So the honest status of this card's aim ("do not pay up") is: **the aim is right, the entry-side lever
is empty.** The effect exists; the dispatch-time instrument that would capture it does not.

## 6. The motion — three parts

### P1 (default) — do NOT write the entry rail; keep the card measurement-only
The executable form fires once post-fix. Writing it would add a gate, a RuleSet field and a piece of
prose to maintain, for a population of one leg. The card's own decision rule already says no live
change; this document only removes the option that was waiting behind the bar.

### P2 (default) — ship the write-only `[PAID-UP]` shadow, on the EXECUTABLE fields
One line per cycle, no decision, no RuleSet field, no size effect. It costs nothing extra: the scorer
already fetches the book for every leg it prices (`scripts/score-trades.ts:515`, `adapter.fetchMarket`
returns `bestBid`/`bestAsk` — `src/lib/adapters/polymarket.ts:710`).

Sketch (the actual code change, ~12 lines, at one site):

```ts
// next to `spread`/`liquidity` declarations (score-trades.ts ~:495)
let bookBid: number | undefined, bookAsk: number | undefined;
// inside the existing try (after `const m = await adapter.fetchMarket(...)` ~:515)
bookBid = m.bestBid; bookAsk = m.bestAsk;
// immediately before `await openPaperTrade({...})` (~:1247)
const legBid = outcomeIsYesSide ? bookBid : 1 - (bookAsk as number);   // complement frame,
const legAsk = outcomeIsYesSide ? bookAsk : 1 - (bookBid as number);   // see §3a of the card
if (legBid !== undefined && legAsk !== undefined) {
  const mid = (legBid + legAsk) / 2;
  log(`[PAID-UP] ${t.marketId} p=${currentPrice.toFixed(3)} bid=${legBid.toFixed(3)} ` +
      `mid=${mid.toFixed(3)} ask=${legAsk.toFixed(3)} gap_mid=${((currentPrice - mid) * 100).toFixed(1)}c ` +
      `gap_ask=${((currentPrice - legAsk) * 100).toFixed(1)}c spread=${(spread ?? 0).toFixed(3)}`);
}
```

**Frame trap, and it is the whole reason this is Lane A:** `bestBid`/`bestAsk` are the venue's
reference token, exactly like `yesPrice`/`noPrice` — 728 of 1,078 mapped legs are complement-framed.
A print that omits `isYesSideOutcome` would report a 0.90 book for a 0.10 leg and manufacture a fake
"we underpaid by 80c" class. Same defect the 2026-11-09 price-side fix removed from the booking path.

Revert: delete the block (or gate it on `PAID_UP_SHADOW=1` in `.env` + `launchctl kickstart`, no
rebuild). Nothing reads the line, so the revert is one edit and cannot move a number.

### P3 (needs your decision) — re-register the bar
The current bar (150 **post-fix print-paid-up** legs at ≤ −10% ROI, CI excluding zero) is a bar for a
rule that cannot be executed. At 2.62 legs/day it matures in ~48 days and, when it trips, the operator
will be asked to ship a rule that fires on 1 leg per 8.8 days.

Proposed replacement, pre-registered now:

- **population**: post-fix legs whose `gap_mid` (entry − best mid at dispatch, leg-token frame) is
  **> 0** — i.e. the class the shadow can see and act on at dispatch;
- **bar**: 150 such legs, ROI ≤ −10% of dollars at risk, market-clustered CI excluding zero;
- **flow floor (new, and it is the part that matters)**: enforcement also requires ≥ 3 flagged
  legs/week. A class maturing at <0.5 legs/week cannot be enforced even if it is real;
- **while it accrues**: the print-basis class keeps being measured on the same run (it is free and it
  is the diagnostic), but it gates nothing.

**Refutation, written before the result:** if at 150 post-fix proxy legs the class reads ≥ 0% ROI with
a CI excluding zero, the entry-side idea is withdrawn permanently and the card routes to
`profit-fast-adverse-stop`. Second condition: if the shadow shows the proxy class firing < 0.5 legs/week
over 30 days, the rule is cosmetic and is withdrawn regardless of its ROI.

## 7. Overridable flags

- **FLAG-1 Keep the old print-basis bar running in parallel** — cost: nothing (one log line); it is how
  we learn whether the print class re-converges. Default: keep both. *Turns off by dropping the
  print-basis counter from the shadow line.*
- **FLAG-2 Shadow scope: both lanes or C-200 only** — the class splits 134/119, so C-200-only halves
  the sample. Default: **both lanes**. *Turns off by `botId === "BANKROLL_200"` in the log condition.*
- **FLAG-3 Shadow writes `data/paid-up-shadow.jsonl` (a corpus) or log line only** — the tape join is
  retrospective and free, so a file adds a gitignored artifact without adding signal. Default:
  **log line only**. *Turns on by appending one `fs.appendFileSync`; must then be added to
  `.backup-exclusions.json`.*

## 8. Reproduction and limits

```
python3 scripts/paid-up-book-gap.py            # all sections, cached tape, ~90s
python3 scripts/paid-up-book-gap.py --selftest
python3 scripts/profit-filled-decomp.py --min-rule 0   # S8/S8b/S12, the card's own read
```

Both read-only (`DB mode=ro`). Every table above is a section of the first script: S0 coverage/classes,
S1 mapping, S1b p0 timing, S1c 2×2, S1d agreement-conditioned, S2 rules priced, S3/S3b proxies,
S4 decomposition, S5 bar accrual.

Limits, stated rather than buried:
- The book join covers 94.3% of tape-reachable legs; 55 legs are side-ambiguous and are excluded from
  every book-basis table (they are included in the print-basis tables).
- `MarketSnapshot` is ~24s old at dispatch (p90 129s). On a fast market that is itself a mid that has
  moved; the 16.2% of legs disagreeing by >2c are exactly that. The 2×2 is conditional on it, which is
  why the agreement-conditioned cut in §3c is the load-bearing table, not the headline.
- PnL is `realizedPnl` as booked (the exit is basis-independent), cost = `simulatedPositionSize`
  (dollars at risk), CIs are market-clustered 2,000 draws.
- I did not re-litigate the C-200/STANDARD split or the ≥0.80-band contradiction; both are other cards.

**The one number that would change the answer**: a post-fix cohort of ≥150 legs where the entry sat
above the book mid at dispatch, reading ≤ −10% with a CI excluding zero. Today that cohort is one leg.
