# Hermes Agent Operator Guide

Hermes Agent is Layer 1 of this system: it runs the operational loop on a schedule,
interprets results, and reports. The app itself (scripts + dashboard) is Layer 2.

## Ground rules for Hermes

- **Paper trading only.** Never attempt real execution. `REAL_EXECUTION_ENABLED` is
  hard-coded to `false`; do not modify `src/lib/safety.ts`.
- **Never ask for or handle private keys.** There is nothing to sign.
- **If an API fails, report the real error.** Never fabricate market data.
- Rule changes are autonomous (no approval needed) but must always be visible in the
  Rules page and daily report.
- Keep Discord quiet: one EOD report daily; extra alerts only for genuinely
  important events.

## Operational loop

All commands run from the project root with `DATA_MODE=live`.

| Cadence            | Command                                          | Purpose |
| ------------------ | ------------------------------------------------ | ------- |
| Daily 06:00        | `npm run scan:leaderboard`                       | Refresh top-500 leaderboard |
| Every 2h           | `WALLET_SCAN_LIMIT=25 npm run scan:wallets`      | Profile/rescore wallets (rotates through backlog) |
| Every 30m          | `npm run monitor:trades`                         | Detect new trades from tracked wallets |
| Every 30m (after)  | `npm run score:trades`                           | Score signals, open paper trades |
| Hourly             | `npm run paper:update-pnl`                       | Refresh PnL, resolve finished markets |
| Every 6h           | `npm run review:outcomes`                        | Judge past decisions |
| Daily 21:30        | `npm run update:rules`                           | Self-improvement pass |
| Daily 22:00        | `npm run report:daily`                           | EOD report → Discord |

## Hermes cron examples

Create these with the `cronjob` tool (adjust paths):

```
# Leaderboard scan, daily 06:00
schedule: "0 6 * * *"
prompt: "Run `cd ~/polymarket-copybot && npm run scan:leaderboard` and report the wallet count.
If the command fails, report the exact error output — do not retry more than once."

# Trade monitoring + scoring, every 30 minutes
schedule: "*/30 * * * *"
prompt: "Run `cd ~/polymarket-copybot && npm run monitor:trades && npm run score:trades`.
Only report if new paper trades were opened or an error occurred."

# Hourly PnL
schedule: "0 * * * *"
prompt: "Run `cd ~/polymarket-copybot && npm run paper:update-pnl`. Stay silent unless a trade
resolved or the command failed."

# Outcome review, every 6 hours
schedule: "0 */6 * * *"
prompt: "Run `cd ~/polymarket-copybot && npm run review:outcomes` and stay silent unless errors."

# Rules + EOD report, daily 21:30/22:00
schedule: "30 21 * * *"
prompt: "Run `cd ~/polymarket-copybot && npm run update:rules`. If rules changed, note the new
version and reason for the daily report."

schedule: "0 22 * * *"
prompt: "Run `cd ~/polymarket-copybot && npm run report:daily`. Relay the printed report. If
DISCORD_WEBHOOK_URL is unset, deliver the report content directly to the user instead."
```

## Alerting policy (important events only)

Send an immediate alert (outside the EOD report) only when:

1. **Very high-confidence paper trade** — a new paper trade with confidence ≥ 0.85.
2. **Major rule change** — a threshold moved by ≥ 25% in one update.
3. **Wallet status jump** — a wallet moved track→ignore or ignore→track in one scan.
4. **Drawdown warning** — total paper PnL dropped by more than $50 (or 20%) in 24h.

Everything else waits for the EOD report.

## Weekly summary (Sundays)

Prompt suggestion:

```
Read the last 7 DailyReport rows from the dashboard database
(`npx tsx -e` with Prisma, or the Reports page). Summarize: week PnL, win rate trend,
whether the bot beat blind copying, top 3 wallets, rule evolution (versions + reasons),
and one concrete hypothesis to test next week. Send to Discord.
```
