# Re-marking the band/lane record on the token basis — the book is clean, and the 119pp headline is an identity artifact

http://localhost:3013/drafts/profit-outcome-basis-remark-20261119

**Instrument:** `scripts/profit-outcome-basis-remark.py` (new, `--self-test` **18/18**), token truth `data/book-token-truth.json` (1,713 markets fetched keyless from the CLOB archive today), artifact `data/outcome-basis-remark.json`.
**Basis for every figure:** level = one settled `PaperTrade` leg, deduped to the first per `bot|wallet|market|outcome` (**the repo's own dedupe**, so the "as filed" column IS the published band figure); cost = `simulatedPositionSize` (dollars at risk); ROI = notional-weighted; CIs market-clustered. DB opened `mode=ro`.
**Lane:** Lane A — **PROPOSAL ONLY. Nothing applied.** No RuleSet read or write, no prisma write, no `apply-v*.ts`, no merge to main.

---

## Verdict in one line

**Re-marked on the token basis, every band × lane cell in the book agrees with its filed number to within 1.5pp and no cell crosses zero — the card's own refutation clause fires — and the 119pp that started this card is not a labelling defect in the book but an IDENTITY defect in the measurement: 27 of the 409 refused cheap candidates were never cheap, their detection price was the sibling token's price (wallet's own fill: median 1.0c from the LABEL's token mid, 80.5c from the detected one), so yesterday's −12.9pp gap on that cohort reads −1.9pp once the side is identified the way the book's own rows must be.**

---

## 1. What was measured, and how the side is decided

The win test under audit is `outcome_label == venue winner`. Its alternative is "did the token this leg is PRICED ON win", which needs an independent identity for the priced token. Identity here comes from the PRICE — `entryPrice` against the snapshot's two token mids at the open — with three guards, each of which is a finding in itself:

- **the two mids must differ by ≥ 6c** — at a coin flip (0.505 / 0.495) both sides sit ~1c from the price and the vote flips on bid-ask noise. Dropping this guard put 20 *YES/NO* rows into disagreement; with it, **0 of 1,272**.
- **the priced side must win by ≥ 1c** of margin.
- **the mirror test first**: where the booked price is the COMPLEMENT of the wallet's own print (`|entry−wallet| ≥ 0.10` and `|entry−(1−wallet)| ≤ 0.06`), the side is the one at the WALLET's price, because a pre-2026-11-09 positional read booked the sibling token's price. Confined to named labels (on a binary market that relationship can only be a data error).

Coverage on the book's 2,147 resolved legs (deduped):

| class | legs | share |
|---|---:|---:|
| token truth recovered | 2,140 | 99.7% |
| price identity usable | **1,850** | **86.2%** |
| mids too close (coin flip) | 278 | 12.9% |
| no snapshot / no truth | 19 | 0.9% |

Legs without an identity are **kept at their filed value and counted**, never guessed. Only `resolved` legs are re-marked: an early exit books from its exit price, so no outcome label enters — 3,772 of the 5,919 settled legs (63.7%) are structurally immune.

**The filed number IS the label basis**, which is what makes the restatement a restatement and not a new population: among the 7 legs where the bases disagree, **7 of 7** book `realizedPnl` exactly as the label test says (and 0 of 7 as the token test). Across all 1,850, 1,714 reproduce the label booking to the cent and 136 reproduce neither — those 136 are the legs the 2026-11-11 ledger repair re-priced, so their `entryPrice` today is not the entry they were booked at.

---

## 2. The band × lane table

`filed` = the published cell. `restated` = filed with each mislabelled row's verdict corrected (a leg whose bases agree keeps its number exactly, so the delta is the mislabel and nothing else). `named%` and `dis` are over the re-marked resolved rows in the cell.

| lane | band | filed | restated | named% | dis |
|---|---|---:|---:|---:|---:|
| STANDARD | 0.0–0.2 | +45.6% | +45.6% | 18 | 0 |
| STANDARD | 0.2–0.4 | +12.4% | +14.0% | 28 | 1 |
| STANDARD | 0.4–0.6 | −6.0% | −5.7% | 11 | 1 |
| STANDARD | 0.6–0.8 | +2.0% | +2.1% | 18 | 1 |
| STANDARD | 0.8–1.0 | −0.9% | −0.9% | 14 | 0 |
| **STANDARD** | **lane** | **+3.1%** | **+3.4%** | 18 | 3 |
| C-200 | 0.0–0.2 | +44.1% | +44.1% | 55 | 0 |
| C-200 | 0.2–0.4 | +9.4% | +10.9% | 55 | 1 |
| C-200 | 0.4–0.6 | +0.2% | +0.4% | 48 | 3 |
| C-200 | 0.6–0.8 | +2.0% | +2.0% | 26 | 0 |
| C-200 | 0.8–1.0 | +6.4% | +6.4% | 31 | 0 |
| **C-200** | **lane** | **+23.3%** | **+23.7%** | 44 | 4 |
| **ALL** | **all** | **+10.2%** | **+10.5%** | 31 | **7** |

- Whole book: **+10.2% → +10.5%**, i.e. **+$239.92** of settled PnL on $69,696 staked. (The +10.2% reproduces the published all-settled figure in `drafts/profit-research-20261119.md`, on the same 5,919 legs — that is the cross-check that this is the same population.)
- Pure basis gap on re-marked legs only (equal-weight hit rate, label vs token): **+0.2pp** all-lanes; the largest cell is C-200 0.4–0.6 at **−0.6pp**.
- The 7 disagreements are all named, all **pre-2026-11-09**, and the post-fix subset is **0 of 105**.

## 3. The restatement list

**Empty.** No band or lane cell's token-basis ROI falls below its own breakeven where the filed figure was above it; no cell changes sign. Every cell reads "holds" under the card's own rule.

The consumers that carry settled PnL therefore do not move:

| window | filed | restated | delta |
|---|---:|---:|---:|
| 7d all-lanes | −$543 | −$543 | $0 |
| 30d all-lanes | −$762 | −$570 | +$192 |
| 90d all-lanes | +$6,213 | +$6,453 | +$240 |

The 7-day column is the C-200 ladder's advance basis and it moves by **zero**: no disagreeing leg settled in the last week.

## 4. The refutation clause

> if across bands the label and token bases agree within 2pp … the defect is confined to the cheap cohort and this card collapses to a footnote.

**Measured: the largest cell move is 1.5pp (STANDARD and C-200 0.2–0.4), and 11 of 13 cells move by ≤ 0.4pp.** The clause fires. The book-wide re-mark is a footnote, and I am not proposing to restate any published band figure.

## 5. But the 119pp is not what it was said to be — and this part needs correcting in the record

I re-ran §9's own population (refused cheap candidates, `ruleSetVersion ≥ 68`, 0.05 ≤ detected < 0.20, first sighting per market+outcome) inside this instrument, under both identity rules:

| identity rule | n | label hit | token hit | gap | disagree |
|---|---:|---:|---:|---:|---:|
| §9 as filed (detection price, no guard) | 210 | 23.8% | 11.0% | **−12.9pp** | 29 |
| book rule (6c gap + mirror test) | 210 | 23.8% | **21.9%** | **−1.9pp** | **4** |

§9's reading reproduces to 0.1pp — the label/token arithmetic is not in question. What changed is **which token the detection price was pointing at**. On 27 of the 409 refused candidates (6.6%, **all pre-2026-11-09, 0 post-fix**) the detected price is the *complement* of the wallet's own print:

- detected price median **10.5c**, the wallet's own fill median **90.0c**;
- `|wallet print − the LABEL's token mid|` = **1.00c** median;
- `|wallet print − the DETECTED token mid|` = **80.50c** median.

So on those rows the wallet bought the ~0.90 favourite the label names, the detector read the sibling's ~0.10 price, and the candidate entered a "cheap 0.05–0.20" cohort it never belonged to. §9's token basis then scored the sibling token — a bet nobody placed — and that is where the 25 of the 29 disagreements came from. The label basis was, on those rows, the correct test.

Three consequences, stated plainly because one of them corrects yesterday's write-up:

1. **The 2026-11-19 finding is overstated and its mechanism is mis-stated.** The defect is real on the four survivors (wallet prints of 0.53–0.75 against mids of 0.165/0.835 — a stale snapshot, not a framing class), and it is worth **−1.9pp, not −12.9pp**. `drafts/profit-recs-20261119.md` §1–§3 and commit `7d8f0bd` should be annotated: the cheap cohort's label basis is inflated by ~2pp by identity, not by 25pp.
2. **The withdrawal of `profit-cheap-refusal-ask-price` still stands, for a stronger reason.** The population is not merely mislabelled, it is mispriced: 1 in 15 of its candidates was a ~90c buy recorded at ~10c, so *neither* arm of that card's ROI (+112.4% or −6.8%) is the return on a bet anyone could have placed. "No measured edge" becomes "no measurable population".
3. **The second clause of this card's rule should be re-pointed.** "Refuse approval of any card whose population is pre-fix named-outcome" is too weak: the dangerous population is pre-fix *detection-priced*, named or not. The book is barely affected because the 2026-11-11 ledger repair moved the booked entry onto the label's token; the journal-side populations (refused candidates, shadow ladders) never got that repair.

## 6. What I propose (read-path only — nothing that decides or risks anything)

- **P1 — adopt the identity rule in every basis read, not just this one.** `profit-cheap-ask.py` §9 should print its two-basis table under the 6c mid gap and the named-only mirror test, and print the complement-framed share of its cohort beside it. Same for any future instrument that compares a stored price against a venue token list. **Effect:** the §9 figure goes from −12.9pp to −1.9pp. **Cost:** ~40 lines in that file.
- **P2 — annotate yesterday's finding rather than delete it.** One paragraph in `drafts/profit-recs-20261119.md` and a `note` line on the two cards it moved. The withdrawal of the cheap-refusal card is unaffected.
- **P3 — no band/lane restatement.** Nothing to apply; the table above is the record.
- **P4 — the standing rule for approvals becomes "state the price basis".** Any card quoting a band/lane ROI names (a) the population (settled vs filled vs refused), (b) the label basis, and (c) whether the price came from a booking or a detection. This card is why.

## 7. Flags you can override in one line

- **FLAG 1 — the 6c mid-gap guard costs 12.9% of the book.** It excludes 278 resolved legs whose market sat near a coin flip. Relax to 3c and those rows return, but they are exactly the rows that produced 20 phantom YES/NO disagreements. My call: keep 6c. *Revert: `MIN_MID_GAP = 0.03`.*
- **FLAG 2 — I did not restate the C-200 0.4–0.6 naming.** It carries the most named rows (48%) and reads +0.2% → +0.4%. It is the one cell where a name-based error would hide, and it is clean. My call: no change. *Revert: nothing to revert — this is a no-op.*
- **FLAG 3 — the book's 136 re-priced legs are excluded from the arm ROI.** Their `entryPrice` is the 2026-11-11 repair's post-image, so re-pricing them at today's entry mixes a price-column move into a basis read. My call: exclude and print the count. *Revert: include them and the whole-book delta moves from +$240 to +$585, all of it repair, none of it basis.*

## 8. Verification and revert

- `python3 scripts/profit-outcome-basis-remark.py --self-test` → **18/18**, including the defect shape (a label naming the winning sibling books a 9x win, the token basis books −100%), the mirror class, the YES/NO invariance, and the early-exit exemption.
- `python3 scripts/profit-outcome-basis-remark.py --dump` prints all 7 disagreement rows with their identity evidence; the run is reproducible offline from `data/book-token-truth.json`.
- **Revert:** `git revert <commit>` — it adds one read-only script, one cache, one artifact and this write-up. No rule, clip, band, gate, threshold or settlement path is touched, and no figure in the DB changes.

## IF YOU WEREN'T HERE

The book does not need re-marking — 7 legs, +$240, no cell moving 1.5pp. **Do not approve a band-wide restatement.** What does need fixing is the identity rule inside the *measurement*: yesterday's 119pp was 27 refused candidates whose 10c detection price was the 90c favourite's sibling, and the wallet's own fill lands 1c from the label's token and 80c from the detected one. The cheap-refusal withdrawal stands; the reason changes from "stale basis" to "no measurable population".
