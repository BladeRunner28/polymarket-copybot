# Recorder audit against an external prediction-market corpus (2026-11-16)

**Card:** `ml-feed-recorder-audit-external-pm` (Lane B, measurement)
**Instrument:** `scripts/pm-v2-corpus-audit.py` (`--self-test` 13/13, mutation arms RED) → `data/pm-v2-corpus-audit.json`
**Read:** 2026-11-16T20:0xZ · **Nothing applied.** No rule, size, threshold or gate touched.

## Verdict first

The card's own decision rule **refutes** the recorder concern, on the only corpus reachable from
this host: our settled verdicts agree with the venue on **713 / 715 knowable legs (99.72%)** over
**537 markets**. The single disputed market resolves to a **corpus** error, not ours.

`0.28%` of legs / `0.19%` of markets disagree, against a `0.5%` refutation floor and a `2%`
investigate trigger, on 537 markets (the card's floor is 100).

## What the card asked for, and what had to change

| Card's named corpus | Status from this host (probed 20:00Z) |
|---|---|
| manja316/crypto-prediction-market-signals | Kaggle **403** (`datasets.get was denied`, no `~/.kaggle/kaggle.json`) |
| thomaswmitch/kalshi-prediction-markets-* | Kaggle **403**; GitHub path **404** |
| lowskillcoding/pdata-prediction-markets | GitHub **404** |
| iiiitips/prediction-market-pro-stats | reachable (HF) but **aggregate-only** — band/sport win rates + leaderboard, no per-market rows |

Our own archive is not a substitute: Polymarket-v1 ends **2026-04-28**, our first paper trade is
**2026-06-18**.

The corpus that works: **TimeSeventeen/Polymarket-v2** (HF, CC BY 4.0, mirror `xfox25/Polymarket-v2`).
`OrderFilled` to 2026-11-12, cleaned `daily_aligned` to 2026-11-10, per fill: `condition_id`,
`market_slug`, `outcome_label`, `winning_outcome_label`, `resolution_status`, `price`, `usdc_amount`,
`fee_usdc`. 87 partitions cached at `/Volumes/Storage/pm-data/v2-audit-cache` (2.9 GB, outside the repo).

Also corrected: the card's cited **$0.0496 `pnl_net_full` drift** was already measured on
`export-reconciliation-localisable` (2026-10-29) and localised to the exit-side fee leg of
early-closed rows. Not re-derived here.

## The numbers, each with its basis

Population `PaperTrade isDemo=0`, status resolved/closed · join `market_slug` · level = leg ·
clock = `resolvedAt` (verdict) / `openedAt` (price) · window 2026-08-15..2026-11-10 · 87 partitions.

- **Coverage** 1,531 / 12,863 legs (11.9%) and 863 / 4,361 markets (19.8%). The corpus only carries
  markets that traded on the v2 contract in its window; our book is mostly esports/politics/niche
  sports. This is the arm's real limit.
- **Verdict** 715 legs / 537 markets knowable → 713 agree, 2 disagree.
- **Settlement PnL** booked **$984.06** on that population; replaying our own `computePnl` with the
  corpus verdict moves it **$0.00** — the two disagreeing legs cancel (below).
- **Price** recorded `entryPrice` vs the venue's own print on the same token at/before `openedAt`
  (staleness ≤ 900 s, no look-ahead; n = 1,014 legs; diff = ours minus tape, in cents):
  - `BANKROLL_200` n=598 · median **−0.87c** · mean −0.70c · within 1c 39.0%
  - `STANDARD` n=416 · median **+0.50c** · mean +0.12c · within 1c 62.3%
  Both signs are the **design**: C-200 books `intent − 2c` (the maker model on
  `c200-maker-fill-assumption`), STANDARD books the quote a taker then pays above.
- **Labels** 11 legs carry a label no corpus token matches; only **1 is definitive** — in the other
  10 the other side simply never printed, and absence cannot prove a label defect.

## The corpus is not assumed correct

A seeded random 40-market draw (seed 20261116) was re-read from the **venue** (CLOB
`/markets/<conditionId>` → `tokens[].winner`, keyless): **40/40 agree**, 0 unreadable.

## The one dispute, resolved to the venue

`ufc-jon5-jos27-2026-11-07`. The corpus labels the condition's two tokens *Jonny Parsons* +
*Jose Henrique* and calls *Jose Henrique* the winner. The venue's CLOB for the same `condition_id`
returns *Jonny Parsons* + *Jose Souza* with winner **_Jose Souza_**.

Two consequences:

1. The corpus is wrong on this market (it carries a retired token label).
2. **Our book holds both labels as separate legs on ONE token** — opened 88 minutes apart by one
   wallet, both at 0.685 for $9.00: `JOSE HENRIQUE` booked **−$9.00**, `JOSE SOUZA` booked **+$4.14**.
   Settlement compares labels (`didOutcomeWin`), so the renamed leg became a **phantom loss**.

That is a real recorder defect, worth **1 leg / $9.00** — carded as
`token-label-alias-phantom-loss` with a pre-registered trigger (≥ $100 booked or ≥ 5 legs) and a
stated fix (identity join, which would be Lane A). **No restatement proposed at this magnitude.**

The PnL reading was `$0.00` precisely because a corpus label error and our label defect cancelled —
which is exactly the kind of clean-looking number this audit exists to catch.

## Printed, not fixed (Lane A)

221 of the joined legs are `fillStatus='unfilled'` yet still carry **$1,500.31** of booked
`realizedPnl` (pre-flag rows). That is the fill-aware-booking question already sitting on
`c200-maker-fill-assumption`.

## Reproduce

```
/Volumes/Storage/pm-data/.venv/bin/python scripts/pm-v2-corpus-audit.py --self-test
/Volumes/Storage/pm-data/.venv/bin/python scripts/pm-v2-corpus-audit.py --validate 40
```

The run **fails loud** when the corpus cache is absent — an empty join is not a refutation.
Instrument defects found and fixed in this pass: an ASCII-only SQL normaliser manufactured 10 phantom
label misses on diacritics (Leviatan / Turkiye / Vaxjo); and the first draft's pair guard was a no-op
expression.
