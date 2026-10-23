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

/**
 * The ML lane (2026-10-20, user request). Its paper book is capital-identical to C-200 --
 * same Kelly fields, same $2,500-style standing principal, same daily-deposit definition --
 * so any difference between the two books is attributable to the SIGNAL, not to the capital
 * machinery. The rule VALUES are shared, never duplicated: the scorer reads C-200's own
 * fields, because two copies of a number drift apart (see the BotBankroll maxPositionSize
 * false rail, fixed the same day).
 */
export const ML_BOT = "ML_LANE";

/** Ledger entries with no botId belong to the original C-200 book (they predate lanes). */
export function ledgerEntryBelongsTo(entry: { botId?: string }, botId: string): boolean {
  if (entry.botId) return entry.botId === botId;
  return botId === CAPITAL_BOT;
}

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
  /** Non-null when data/capital-ledger.json exists but could not be read. */
  ledgerError: string | null;
}

export interface CapitalLedgerRead {
  entries: CapitalLedgerEntry[];
  /**
   * Non-null when the ledger could not be READ as a ledger (missing file, invalid
   * JSON, `entries` not an array). Distinct from "read fine, has no entries": a
   * broken file used to return [] and every downstream number stayed plausible
   * while silently dropping every recorded injection (see ledgerLine in
   * scripts/capital-deposits-report.ts). Callers must surface this, never absorb it.
   */
  error: string | null;
  path: string;
}

export function readCapitalLedgerResult(botId: string = CAPITAL_BOT): CapitalLedgerRead {
  const path = join(process.cwd(), "data", "capital-ledger.json");
  let raw: unknown;
  try {
    raw = JSON.parse(readFileSync(path, "utf8"));
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e);
    return { entries: [], error: `cannot read ${path}: ${msg}`, path };
  }
  const entries = (raw as { entries?: unknown })?.entries;
  if (!Array.isArray(entries)) {
    return { entries: [], error: `${path} has no \`entries\` array (got ${typeof entries})`, path };
  }
  return {
    entries: (entries as CapitalLedgerEntry[]).filter((e) => ledgerEntryBelongsTo(e, botId)),
    error: null,
    path,
  };
}

export function readCapitalLedger(botId: string = CAPITAL_BOT): CapitalLedgerEntry[] {
  return readCapitalLedgerResult(botId).entries;
}

export async function loadCapitalState(opts: {
  days: number;
  nowMs?: number;
  /** Lane to load. Defaults to C-200 so every existing caller is unchanged. */
  botId?: string;
}): Promise<CapitalState> {
  const bot = opts.botId ?? CAPITAL_BOT;
  const [bankroll, finished, openAgg] = await Promise.all([
    prisma.botBankroll.findUnique({ where: { botId: bot } }),
    prisma.paperTrade.findMany({
      where: { botId: bot, status: { in: ["closed", "resolved"] } },
      select: { closedAt: true, resolvedAt: true, realizedPnl: true },
    }),
    prisma.paperTrade.aggregate({
      where: { botId: bot, status: "open" },
      _sum: { unrealizedPnl: true, simulatedPositionSize: true },
      _count: true,
    }),
  ]);

  const principal = bankroll?.principal ?? 0;
  const realized = bankroll?.realizedPnl ?? 0;
  const openUnreal = openAgg._sum.unrealizedPnl ?? 0;
  const openNotional = openAgg._sum.simulatedPositionSize ?? 0;
  const ledgerRead = readCapitalLedgerResult(bot);
  const ledger = ledgerRead.entries;
  // A broken ledger must reach series.warnings (the /capital page renders those) —
  // otherwise seed silently falls back to the principal and the reconciliation line
  // passes with every recorded injection missing.
  const ledgerWarning = ledgerRead.error
    ? `capital ledger ${ledgerRead.error} — injections are UNKNOWN, every deposit number below assumes none`
    : null;

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
    series: ledgerWarning ? { ...series, warnings: [...series.warnings, ledgerWarning] } : series,
    ledger,
    ledgerError: ledgerRead.error,
    principal,
    realized,
    openUnreal,
    openNotional,
    openCount: typeof openAgg._count === "number" ? openAgg._count : 0,
    liveTotalCapital: principal + realized + openUnreal,
    bookedCapital: principal + realized,
  };
}
