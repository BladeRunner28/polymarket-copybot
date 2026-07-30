# SAFETY.md

## Why version one is paper trading only

This system's entire premise is unproven until data says otherwise. Copy trading
leaderboard wallets *sounds* profitable; most implementations lose money to spread,
slippage, late entries, and survivorship bias. Version one exists to measure the edge
honestly — with simulated $.25–$20 positions — before a single real dollar is considered.
If the paper record can't beat blind copying (or can't stay positive), there is nothing
worth automating with real money.

## Why real execution is disabled

- `REAL_EXECUTION_ENABLED` in `src/lib/safety.ts` is a hard-coded `false` constant —
  not an environment variable, not a config flag. Changing it requires a deliberate
  code edit and a new version.
- Every function that creates/updates/resolves paper trades calls `assertPaperOnly()`
  as a runtime tripwire.
- The market adapter is read-only: it issues only HTTP GETs to public endpoints.
  There is no order-placement code, no CLOB client, no signing library in the
  dependency tree.
- Tests assert all of the above and fail CI if execution paths appear.

## How autonomy could be added later (deliberately)

1. Paper trading accumulates ≥ 3 months of resolved decisions with a stable, positive
   edge vs. blind copy.
2. A separate, isolated execution service is designed — never inside this codebase —
   with its own keys held in a hardware wallet or KMS, spending caps, and a kill switch.
3. The research system emits *signals only*; the execution service independently
   validates them. This app never holds the keys.
4. Start with the minimum viable size, monitored daily, with automatic shutdown on
   drawdown limits.

## Risks of stale data

Prices move constantly; a signal detected 30 minutes late may already be worthless.
Paper PnL here uses hourly snapshots — real fills would differ. Treat all paper results
as an optimistic upper bound, and treat any dashboard number as potentially minutes-to-
hours old. The system stores `detectedPrice` separately from `walletEntryPrice`
specifically to measure this decay.

## Risks of low liquidity

A leaderboard wallet can profitably trade a market with $800 of liquidity; a copier
cannot. Entering moves the price against you; exiting may be impossible at any fair
price. That's why `minLiquidity` is a hard gate and illiquid wallets score low on
copyability.

## Risks of wide spreads

Buying at the ask and (eventually) selling at the bid costs the full spread. A 5-cent
spread on a 50-cent outcome is a 10% round-trip tax that the wallet you're copying may
not be paying (they may be makers, you'd be a taker). `maxSpread` gates this, and the
rule updater tightens it if spread-heavy trades underperform.

## Risks of copy trading generally

- **You see the entry, not the reasoning.** The wallet may be hedging elsewhere.
- **You see the entry late.** Their edge may be speed you cannot copy.
- **They can exit silently.** You learn about exits with the same delay as entries.
- **Position sizing is invisible.** $10k from a whale is not the same signal as
  $10k from a $12k account.

## Why leaderboard wallets can be misleading

- **Survivorship bias:** the leaderboard shows this month's winners, not last month's
  identical gamblers who blew up.
- **One-hit wonders:** a single lucky longshot can top the PnL rankings; that's why
  the one-hit-wonder penalty exists.
- **Volume ≠ skill:** high-volume market makers appear profitable in aggregate but
  are uncopyable by definition.
- **Insider/latency edges:** some wallets win on information or speed a copier
  structurally cannot replicate.

## Why private keys must never be stored in this app

This is a research tool with a web dashboard, network calls, and dependencies — a large
attack surface. A key stored here (env var, database, config) is one dependency
compromise or one leaked log away from total loss of funds. Keys belong in
purpose-built, isolated signers with spending limits — never in an analytics app.
This codebase contains a test that fails if key-handling code appears.
