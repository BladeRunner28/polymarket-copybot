/**
 * Exit-recovery logger (2026-09-05 — observability ONLY, no behavior change).
 *
 * Why: the exit-regime question ("do early-exited positions recover after we
 * leave?") could only be answered on 211/984 historical trades because
 * post-exit token prices were never captured (PnlSnapshot stops at close;
 * OutcomeReviews exist only post-resolution). This module records the market
 * token price at ~+1h / +6h / +24h after every early exit — and the final
 * 0/1 once the market resolves — appended to data/exit-recovery.jsonl.
 *
 * Mechanics: swept from paper:update-pnl (hourly). It only READS closed
 * trades and fetches market prices; it never mutates trade state, so it
 * cannot affect behavior or the Kelly measurement window (Sep 15–Oct 15).
 * Dedupe key = (tradeId, bucket) read back from the log file, so missed or
 * duplicate hourly runs are safe.
 *
 * Scope: BANKROLL_200 Polymarket early exits closed within the last 26h.
 * Limitation: if update-pnl is down >26h the tail of that window is lost.
 */
import * as fs from "fs";
import { join } from "path";
import { prisma } from "./db";
import { log, logError } from "./redact";
import { fetchEventResolution } from "./dead-market-resolution";

export const EXIT_RECOVERY_LOG =
  process.env.EXIT_RECOVERY_LOG ??
  join(__dirname, "..", "..", "data", "exit-recovery.jsonl");

const TRACK_HOURS = 26;
// [bucket, min elapsed hours since close] — hourly cadence makes these
// ±1h approximations, which is all the recovery question needs.
const BUCKETS: Array<[string, number]> = [
  ["1h", 0.9],
  ["6h", 5.9],
  ["24h", 23.9],
];

type TradeLite = {
  id: string;
  marketId: string;
  outcome: string;
  currentPrice: number;
  closedAt: Date;
};

function readDone(): Map<string, Set<string>> {
  const done = new Map<string, Set<string>>();
  try {
    for (const line of fs.readFileSync(EXIT_RECOVERY_LOG, "utf-8").split("\n")) {
      if (!line.trim()) continue;
      try {
        const j = JSON.parse(line);
        if (j.type === "mark" && typeof j.tradeId === "string") {
          if (!done.has(j.tradeId)) done.set(j.tradeId, new Set());
          done.get(j.tradeId)!.add(j.bucket);
        }
      } catch {
        /* skip malformed lines */
      }
    }
  } catch {
    /* no log yet */
  }
  return done;
}

function append(line: object) {
  try {
    fs.appendFileSync(EXIT_RECOVERY_LOG, JSON.stringify(line) + "\n");
  } catch (e) {
    logError(`exit-recovery: append failed: ${e}`);
  }
}

export async function sweepExitRecovery(adapter: {
  fetchMarket(marketId: string): Promise<any>;
}): Promise<void> {
  try {
    const done = readDone();
    const since = new Date(Date.now() - TRACK_HOURS * 3_600_000);
    const closed = await prisma.paperTrade.findMany({
      where: {
        botId: "BANKROLL_200",
        venue: "Polymarket",
        isDemo: false,
        status: "closed",
        closedAt: { gte: since },
      },
      select: {
        id: true,
        marketId: true,
        outcome: true,
        currentPrice: true,
        closedAt: true,
      },
    });
    const withClose = closed.filter((t): t is TradeLite => t.closedAt !== null);
    const eligible = withClose.filter((t) => {
      const have = done.get(t.id);
      return !(have?.has("24h") || have?.has("final"));
    });
    if (eligible.length === 0) return;

    const now = Date.now();
    // marketId -> trades needing a mark at this sweep
    const byMarket = new Map<string, TradeLite[]>();
    const due = new Map<string, Set<string>>(); // tradeId -> buckets due
    for (const t of eligible) {
      const have = done.get(t.id) ?? new Set();
      const elHours = (now - t.closedAt.getTime()) / 3_600_000;
      const want = BUCKETS.filter(([b, minH]) => elHours >= minH && !have.has(b)).map(([b]) => b);
      if (want.length === 0) continue;
      if (!byMarket.has(t.marketId)) byMarket.set(t.marketId, []);
      byMarket.get(t.marketId)!.push(t);
      due.set(t.id, new Set(want));
    }
    if (byMarket.size === 0) return;
    log(
      `exit-recovery: ${eligible.length} recently-closed trade(s) tracked, ${byMarket.size} market(s) due marks this run.`
    );

    for (const [marketId, trades] of [...byMarket.entries()]) {
      let m: any = null;
      let resolution: string | null = null;
      try {
        m = await adapter.fetchMarket(marketId);
      } catch (e) {
        const msg = e instanceof Error ? e.message : String(e);
        if (/404|not found/i.test(msg)) {
          try {
            resolution = await fetchEventResolution(marketId);
          } catch {
            /* resolution path also failed — retry next run */
          }
        } else {
          log(`exit-recovery: fetch failed ${marketId} (${msg.slice(0, 100)}) — retry next run`);
          continue;
        }
      }
      for (const t of trades) {
        const want = due.get(t.id);
        if (!want) continue;
        const marks: object[] = [];
        if (resolution || (m && m.resolved && m.winningOutcome)) {
          const winner = resolution ?? (m as any).winningOutcome;
          marks.push({
            type: "mark",
            tradeId: t.id,
            bucket: "final",
            tokenPrice: winner === t.outcome ? 1 : 0,
            priceAt: Date.now(),
            resolved: true,
          });
        } else if (m) {
          const price = t.outcome === "NO" ? m.noPrice : m.yesPrice;
          if (price === undefined) continue;
          for (const b of want) {
            marks.push({
              type: "mark",
              tradeId: t.id,
              bucket: b,
              tokenPrice: price,
              priceAt: Date.now(),
              resolved: false,
            });
          }
        }
        for (const mk of marks) append(mk);
      }
    }
  } catch (e) {
    logError(`exit-recovery: sweep failed: ${e instanceof Error ? e.message : e}`);
  }
}
