/**
 * Shared loader for the capital series (2026-09-20).
 *
 * WHY A LOADER: three consumers must show the same numbers — the `/capital`
 * page, the Overview chart card, and scripts/capital-deposits-report.ts (which
 * writes the markdown report and feeds the daily Discord cron). They all call
 * this one function, so a definition change can never drift between the chart,
 * the table and the Discord message.
 */

import { prisma } from "./db";
import { readFileSync } from "fs";
import { join } from "path";
import { buildCapitalSeries, type CapitalLedgerEntry, type CapitalSeries } from "./capital";

export const CAPITAL_BOT = "BANKROLL_200";

export interface CapitalState {
  series: CapitalSeries;
  ledger: CapitalLedgerEntry[];
  /** BotBankroll.principal — the standing principal (no history; see the ledger). */
  principal: number;
  /** BotBankroll.realizedPnl — every finished trade, early exits included. */
  realized: number;
  /** Σ unrealized over open positions (mark-to-market). */
  openUnreal: number;
  /** Σ position size over open positions. */
  openNotional: number;
  openCount: number;
  /** principal + realized + open MTM — the Overview's own Total Capital definition. */
  liveTotalCapital: number;
  /** principal + realized — finished trades only, the basis of the chart/table. */
  bookedCapital: number;
}

export function readCapitalLedger(): CapitalLedgerEntry[] {
  try {
    const raw = JSON.parse(readFileSync(join(process.cwd(), "data", "capital-ledger.json"), "utf8"));
    return Array.isArray(raw?.entries) ? (raw.entries as CapitalLedgerEntry[]) : [];
  } catch {
    return [];
  }
}

export async function loadCapitalState(opts: { days: number; nowMs?: number }): Promise<CapitalState> {
  const [bankroll, finished, openAgg] = await Promise.all([
    prisma.botBankroll.findUnique({ where: { botId: CAPITAL_BOT } }),
    prisma.paperTrade.findMany({
      where: { botId: CAPITAL_BOT, status: { in: ["closed", "resolved"] } },
      select: { closedAt: true, resolvedAt: true, realizedPnl: true },
    }),
    prisma.paperTrade.aggregate({
      where: { botId: CAPITAL_BOT, status: "open" },
      _sum: { unrealizedPnl: true, simulatedPositionSize: true },
      _count: true,
    }),
  ]);

  const principal = bankroll?.principal ?? 0;
  const realized = bankroll?.realizedPnl ?? 0;
  const openUnreal = openAgg._sum.unrealizedPnl ?? 0;
  const openNotional = openAgg._sum.simulatedPositionSize ?? 0;
  const ledger = readCapitalLedger();

  const series = buildCapitalSeries({
    principal,
    rows: finished.map((r) => ({
      closedAt: r.closedAt ? new Date(r.closedAt as unknown as string).getTime() : null,
      resolvedAt: r.resolvedAt ? new Date(r.resolvedAt as unknown as string).getTime() : null,
      realizedPnl: r.realizedPnl,
    })),
    ledger,
    days: opts.days,
    todayMs: opts.nowMs ?? Date.now(),
  });

  return {
    series,
    ledger,
    principal,
    realized,
    openUnreal,
    openNotional,
    openCount: typeof openAgg._count === "number" ? openAgg._count : 0,
    liveTotalCapital: principal + realized + openUnreal,
    bookedCapital: principal + realized,
  };
}
