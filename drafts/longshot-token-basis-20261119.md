# Long-shot shadow ladder: token basis holds, the multiplicity does not

Card: `profit-longshot-token-basis` · measured 2026-11-19 · **measurement only, nothing applied**
Instrument: `python3 scripts/longshot-token-basis.py --fetch` (self-test 28/28) ·
artifact `data/longshot-token-basis.json` · token cache `data/longshot-token-truth.json`

## Key insight

The card asked whether the ladder's 19.3% win rate survives being re-marked on the
**token** basis instead of the label basis. It does — there are **0 label/token
disagreements on 135 of 135 tickets**, and the venue's own print tape independently
confirms each ticket was priced on the token its label names (135/135).

The number that *does* not survive is the denominator. The ladder logs one ticket per
observed trade, so the same side of the same market is counted up to **16 times**. The
headline is **135 tickets over 64 distinct bets (2.11x)**, and on the bet basis the
"edge" is one long-shot payoff.

## Level / clock / population

- **Level** = one ticket (would-admit candidate joined to its resolve row); separately
  one **bet** = `marketId|outcome`, earliest ticket.
- **Clock** = the resolve row's `ts` (settlement).
- **Population** = `data/longshot-shadow.jsonl`, 155 would-admit rows, 135 settled,
  64 markets, 2026-09-12 → 2026-11-19.
- **Basis** = `clob.polymarket.com/markets/<conditionId>` → `tokens[].outcome/winner`
  (keyless), and `/prices-history` per token ±15 min around the decision for the
  identity vote (entryPrice within 3c).

## What was measured

| arm | n | hit | breakeven | excess | PnL |
|---|---|---|---|---|---|
| tickets, token basis | 135 | 19.3% | 12.9% | +6.4pp | +$1,891.93 |
| YES/NO rows | 74 | 24.3% | 11.5% | +12.8pp | +$1,604.82 |
| NAMED rows | 61 | 13.1% | 14.5% | −1.4pp | +$287.11 |
| pre-2026-11-09 | 95 | 23.2% | 12.2% | +10.9pp | +$1,826.49 |
| post-2026-11-09 | 40 | 10.0% | 14.4% | −4.4pp | +$65.45 |
| **bets, token basis** | **64** | **17.2%** | **11.9%** | **+5.3pp** | **+$939.62** |

Concentration (the reality check):

- tickets: ex-top-1 +$1,599.43 · ex-top-5 +$542.25 · **ex-top-10 −$485.30** · median −$20
- bets: ex-top-1 +$647.12 · ex-top-5 −$344.89 · **ex-top-10 −$977.44** · median −$20
- market-clustered ROI CI: tickets [−42.4%, +210.1%] · bets [−20.2%, +175.2%]

## The ladder's own decision rule

> Promote only if ≥150 further resolved admits clear +5pp of hit-rate excess over their
> actual entry price, on the token basis.

- **n clause: NOT MET** on either basis (135 tickets / 64 bets vs 150 required).
- **excess clause: met on paper** (+6.4pp tickets, +5.3pp bets) — but it is met by the
  pre-fix era (+10.9pp) while the forward era reads **−4.4pp** on 40 tickets, and it is
  met at the ticket level mostly because the same winning leg repeats.
- **Verdict: STAYS A SHADOW.** No rule, size, threshold or gate was touched, so nothing
  is queued for approval.

## Card premise: corrected

- The card's worry — "its record is only as clean as its named share" — is **refuted**.
  Named rows are 61/135 = 45.2% (so the card's own ≥90% YES/NO refutation clause does not
  apply), yet the label basis agrees with the token basis on every one of them, and the
  tape confirms the priced token on 135/135 tickets. The 2026-11-19 25pp inflation was a
  property of the refused-cheap cohort's frame (labels YES/NO on named-token markets),
  not of this ladder's rows.
- The **real** defect found instead: `summarizeShadow` counts tickets, and the EOD/log
  line read like bets. Repaired (Lane B): the summary now publishes
  `perOpportunity {markets, wouldHavePnl, wouldHavePnlPerSignal}` and `ticketsPerMarket`,
  and the marker's log line prints "the 135 above are TICKETS, 2.11/market".

## Re-open condition

Re-measure when **distinct settled bets ≥ 150** (today 64; 10-12 new bets/week settle, so
~2027-01). Until then the ladder is a shadow whose headline is a ticket count over one
winning long-shot, not a track record.
