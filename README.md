<div align="center">

<h1>🐉 PolyHydra CopyBot</h1>
<p><i>A Multi-Bot, Multi-Strategy Polymarket Copy-Trading Engine</i></p>

```text
      /^|^\
     / / \ \
   _/ /   \ \_
  / | |   | | \
 / /| |   | |\ \
| | | |   | | | |
| | | |   | | | |
 \ \| |   | |/ /
  \ \ |   | / /
   \ \|   |/ /
    \ \   / /
     \ \ / /
      \   /
       | |
```

**v1.0 Multi-Bot Engine**

</div>

## Overview

A Hermes-operated research system that studies Polymarket's top wallets, scores their
copyability, **paper trades** the best signals with simulated $.25–$20 positions, learns
from outcomes, and reports daily.

> **This is not financial advice. Version 1 never places real trades.**

## What the bot does

- Pulls the Polymarket leaderboard (top 500 wallets by 30-day PnL).
- Profiles each wallet: ROI, consistency, copyability, one-hit-wonder penalty,
  category strengths, liquidity/spread profile.
- Ranks wallets globally and by category; assigns `track` / `watch` / `ignore`.
- Monitors tracked wallets for new trades.
- Scores every new trade against versioned rules → `paper_copy` / `watchlist` / `skip`.
- **Multi-Bot Execution**: Opens **simulated** positions simultaneously across multiple portfolios:
  - `STANDARD`: Infinite pool, $.25–$20 sizing.
  - `BANKROLL_200`: Compounding $200 principal, $.10–$10 sizing.
- Updates paper PnL hourly; resolves trades when markets resolve.
- Reviews past decisions: missed winners, avoided losers, bad copies, good skips.
- Benchmarks the bot-filtered strategy vs. blindly copying leaderboard wallets.
- **Updates its own rules** from evidence — every change versioned and explained.
- Generates an end-of-day report (optionally delivered to Discord by Hermes).

## What the bot does NOT do

- ❌ Place real trades (hard-coded off; see `src/lib/safety.ts` and [SAFETY.md](./SAFETY.md))
- ❌ Ask for, store, or touch private keys
- ❌ Sign transactions
- ❌ Spend money
- ❌ Fake data — if an API fails you see the real error, and the run stops

## Safety

`REAL_EXECUTION_ENABLED = false` is a hard-coded constant. Every trade-creating code
path calls `assertPaperOnly()`. The market adapter only performs HTTP GETs against
public endpoints. Tests fail if order-placement or key-handling code appears.
Read [SAFETY.md](./SAFETY.md) for the full rationale.

## Setup

```bash
git clone <this repo> && cd polymarket-copybot
npm install
cp .env.example .env      # defaults are fine for local use
npm run db:migrate        # creates SQLite DB + seeds [DEMO] data
npm run dev               # dashboard at http://localhost:3000
```

## Environment variables

| Variable | Required | Purpose |
| -------- | -------- | ------- |
| `DATABASE_URL` | yes | `file:./dev.db` locally; a hosted DB URL on Vercel |
| `DATA_MODE` | no | `live` (default, public Polymarket APIs) or `demo` (offline synthetic data, clearly labeled) |
| `DISCORD_WEBHOOK_URL` | no | If set, daily reports are POSTed to Discord. Redacted from all logs. |
| `API_DELAY_MS` | no | Delay between public API calls (default 250) |
| `LEADERBOARD_LIMIT` | no | Wallets to pull per leaderboard scan (default 500) |
| `WALLET_SCAN_LIMIT` | no | Wallets to profile per scan run (default 25) |
| `MONITOR_HOURS` | no | Lookback for new-trade detection (default 24) |

No paid services are required. All Polymarket endpoints used are public and keyless.

## Commands

```bash
npm run dev               # dashboard
npm run db:migrate        # create/upgrade schema (+ seed on first run)
npm run seed              # seed [DEMO]-labeled data
npm run scan:leaderboard  # pull top-500 leaderboard
npm run scan:wallets      # profile + score wallets (rotates through backlog)
npm run monitor:trades    # detect new trades from tracked wallets
npm run score:trades      # score signals; open paper trades
npm run paper:update-pnl  # hourly PnL refresh + resolution
npm run review:outcomes   # judge past decisions
npm run update:rules      # evidence-based automatic rule update
npm run report:daily      # end-of-day report (+ Discord if configured)
npm run test              # full test suite
```

Typical first live session:

```bash
npm run scan:leaderboard
WALLET_SCAN_LIMIT=25 npm run scan:wallets   # repeat to work through the backlog
npm run monitor:trades && npm run score:trades
npm run paper:update-pnl
```

## How the leaderboard scan works

`data-api.polymarket.com/v1/leaderboard` is paged (50/request) up to
`LEADERBOARD_LIMIT`. Each wallet is upserted as a `WalletProfile` stub; profiling
happens separately (`scan:wallets`) so a full 500-wallet scan doesn't hammer APIs.

## How wallet scoring works

Profiling uses the positions APIs (`/closed-positions` both tails + `/positions`) —
the raw activity feed is useless for hyperactive wallets. Scores (0–100):

- **ROI 30d** — realized PnL / invested.
- **Consistency** — win-rate strength + PnL volatility (coefficient of variation) +
  sample-size bonus. Steady beats streaky.
- **Copyability** — liquidity, typical spread, share of extreme-price entries.
- **One-hit-wonder penalty** — share of total profit from the single best trade.
  A wallet whose fortune came from one longshot is luck until proven otherwise.
- **Global score** = weighted blend (weights are rules, so the bot can retune them),
  scaled down by the penalty, hard-capped at 40 for wallets with fewer than
  `minResolvedTrades` resolved positions.

`track` (score ≥ threshold+10, low penalty) → monitored for signals.
`watch` → re-scored on future scans. `ignore` → skipped.

## How paper trading works

For each tracked-wallet trade that passes all rule gates and scores ≥ `minCopyScore`,
the engine opens a `PaperTrade` at the **current** market price (not the wallet's
better entry — honesty about copy lag). Size is $.25–$20, scaled by confidence.
`paper:update-pnl` snapshots hourly PnL; when a market resolves, the trade realizes
at $1 or $0. Nothing is bought or sold anywhere.

## How self-improvement works

`update:rules` analyzes resolved paper trades (min 6 samples) and applies changes like:

- tighten `maxSpread` when wide-spread trades underperform
- raise `minLiquidity` when low-liquidity trades lose
- reduce `maxPriceDrift` when late entries lose
- raise/lower `minCopyScore` based on overall performance
- downgrade wallets with poor paper results

Changes apply **without approval** (paper only!) but every change creates a new
versioned `RuleSet` plus a `RuleChange` row with reason, evidence, and before/after —
all visible on the Rules page and in daily reports.

## How to interpret the dashboard

- **Overview** answers: are we profitable on paper, what's open, what changed?
- **Wallet Rankings** — sortable scoreboard. Watch the one-hit penalty column;
  high ROI + high penalty = lucky, not good.
- **Trade Signals** — every detected trade and why it was copied/watched/skipped.
- **Paper Trades** — the simulated book.
- **Decision Journal** — full score breakdowns and hindsight judgments.
- **Performance** — the honest section: bot vs. blind copy, missed winners vs.
  avoided losers. If blind copy consistently beats the bot, the filters are wrong.
- **Rules** — current thresholds and the full audit trail of self-changes.
- **Reports** — daily/weekly summaries.
- Anything seeded shows an explicit **[DEMO]** badge/label.

## Deploying to Vercel

SQLite files don't persist on Vercel, so use a hosted database:

1. Create a Postgres DB (Vercel Postgres/Neon — free tiers work).
2. In `prisma/schema.prisma` change `provider = "sqlite"` → `"postgresql"`.
3. `vercel` (or import the repo in the Vercel UI).
4. Set env vars in Vercel: `DATABASE_URL`, optionally `DATA_MODE`.
5. `npx prisma migrate deploy` against the hosted DB.
6. The build command is already Vercel-ready (`prisma generate && next build`).

Run the operational scripts from your local machine / a small VPS / Hermes — they
write to the same hosted DB the dashboard reads.

## Adding to Max HQ

The dashboard is a standard Next.js app with a dark, compact theme designed to sit
in an iframe or tab inside Max HQ. Point Max HQ at the deployed Vercel URL (or
`http://localhost:3000` locally). Every page is server-rendered and read-only —
no auth-sensitive mutations exist in the UI.

## How Hermes operates it

See [HERMES.md](./HERMES.md) for the full operator guide: the scheduled loop,
cron prompt examples, alerting policy (EOD report daily; extra alerts only for
high-confidence trades, major rule changes, wallet status jumps, drawdowns),
and the weekly summary prompt.
