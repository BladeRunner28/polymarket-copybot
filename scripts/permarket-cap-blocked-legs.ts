/**
 * permarket-cap-blocked-legs — price the legs the v55 per-market rail ACTUALLY
 * refused. Read-only. Evidence for the `permarket-legs-rail-finding` card.
 *
 * WHY NOT THE REPLAY INSTRUMENT: `scripts/replay-market-cap.ts` re-walks the legs
 * AS BOOKED. A refused leg never becomes a PaperTrade, so the replay cannot price
 * the rail's effect at all — re-run 2026-10-30, `--days 30` reports 0 blocked legs
 * while the journal records 46 leg-clause refusals in the same 30 days — and its
 * window counts legs OPENED inside the window, while the rail counts legs OPEN
 * whatever their vintage. The card's `$892.55` cost figure came from that
 * instrument and is not reproducible on either basis.
 *
 * BASIS (stated, never implied): population = C-200, non-demo decisions carrying a
 * v55 per-market-cap refusal in the window; level = one decision (the same
 * market+outcome may be refused more than once by the same or a different wallet,
 * counted each time because each refusal was a separate lost copy); clock =
 * decision `createdAt` in UTC; price = the decision's detectedPrice (where the
 * copy would have entered); settlement = the MARKET's own winning label (adapter
 * → event fallback → OutcomeReview), never a PnL sign. Fee and slippage are 0 —
 * this is the gross per-$1 read, and `--slip` prints the sensitivity.
 *
 * EVERY REFUSAL IS ALSO CLASSIFIED against the true concurrent state of its
 * marketId, reconstructed from the booked legs' own open/close intervals:
 *   genuine = the rail refused a leg that really existed (open legs >= max)
 *   phantom = the seat was held by a copy a LATER gate refused (open legs < max)
 * The seed is `status: "open"` rows only (scripts/score-trades.ts ~line 212), but
 * the seat is taken when a decision PASSES this gate (~line 1059) and released
 * only by a close — so one run can fill both seats with copies that never booked.
 *
 *   npx tsx scripts/permarket-cap-blocked-legs.ts --days 30
 */

import { prisma } from "../src/lib/db";
import { getAdapter } from "../src/lib/adapters";
import { fetchEventResolution } from "../src/lib/dead-market-resolution";
import { settlementValue } from "../src/lib/resolution";
import { perDollarReturn } from "../src/lib/slug-cap-blocks";
import {
  classifyBlock,
  describeBlock,
  parsePerMarketCapBlocks,
  type BlockClass,
  type OpenAtDecision,
} from "../src/lib/permarket-cap-blocks";
import * as fs from "fs";
import { join } from "path";

const OUT = join(__dirname, "..", "data", "permarket-cap-blocked-legs.json");

function arg(name: string, def: string): string {
  const i = process.argv.indexOf(`--${name}`);
  return i >= 0 && process.argv[i + 1] ? process.argv[i + 1] : def;
}

const money = (v: number) => `${v < 0 ? "-" : ""}$${Math.abs(v).toFixed(2)}`;

type Row = {
  decidedAt: string;
  observedTradeId: string | null;
  marketId: string;
  marketQuestion: string;
  outcome: string;
  venue: string;
  why: string;
  clause: "legs" | "notional";
  sizeUsd: number | null;
  openLegsAtDecision: number | null;
  openNotionalAtDecision: number | null;
  blockClass: BlockClass;
  entry: number | null;
  settlement: "market" | "event" | "undetermined";
  won: boolean | null;
  ret: number | null;
  slipRet: number | null;
};

async function main() {
  // --days 0 = the rail's whole lifetime.
  const days = Number(arg("days", "30"));
  const slip = Number(arg("slip", "0.01"));
  const since = days > 0 ? new Date(Date.now() - days * 86_400_000) : new Date(0);

  const rows = await prisma.decisionJournal.findMany({
    where: {
      isDemo: false,
      createdAt: { gte: since },
      risksJson: { contains: "v55 per-market cap" },
    },
    select: {
      createdAt: true,
      marketId: true,
      observedTradeId: true,
      risksJson: true,
      simulatedPositionSize: true,
      venue: true,
      observedTrade: {
        select: {
          marketId: true,
          marketQuestion: true,
          outcome: true,
          side: true,
          detectedPrice: true,
        },
      },
    },
    orderBy: { createdAt: "asc" },
  });

  // Every booked C-200 leg's open/close interval, per marketId — the ground truth
  // for "what did this market actually hold when the decision was refused".
  const booked = await prisma.paperTrade.findMany({
    where: { botId: "BANKROLL_200", isDemo: false },
    select: { marketId: true, openedAt: true, closedAt: true, resolvedAt: true, simulatedPositionSize: true },
  });
  const intervals = new Map<string, Array<{ open: number; end: number | null; notional: number }>>();
  for (const b of booked) {
    const arr = intervals.get(b.marketId) ?? [];
    arr.push({
      open: b.openedAt.getTime(),
      end: (b.closedAt ?? b.resolvedAt)?.getTime() ?? null,
      notional: b.simulatedPositionSize ?? 0,
    });
    intervals.set(b.marketId, arr);
  }
  const openAt = (marketId: string, at: number): OpenAtDecision => {
    const live = (intervals.get(marketId) ?? []).filter(
      (i) => i.open <= at && (i.end === null || i.end > at)
    );
    return { legs: live.length, notional: live.reduce((a, i) => a + i.notional, 0) };
  };

  const adapter = getAdapter();
  const resolutionCache = new Map<string, { v: number | undefined; src: Row["settlement"] }>();

  const out: Row[] = [];
  for (const r of rows) {
    const blocks = parsePerMarketCapBlocks(r.risksJson);
    if (blocks.length === 0) continue;
    const b = blocks[0];
    const ot = r.observedTrade;
    const marketId = ot?.marketId ?? r.marketId;
    if (!marketId) continue;

    if (!resolutionCache.has(marketId)) {
      let v: number | undefined;
      let src: Row["settlement"] = "undetermined";
      try {
        const m = await adapter.fetchMarket(marketId);
        if (m.resolved) {
          v = settlementValue(ot?.outcome, {
            winningLabel: m.winningLabel ?? m.winningOutcome,
            yesPrice: m.yesPrice,
          });
          if (v !== undefined) src = "market";
        }
      } catch {
        /* fall through */
      }
      if (v === undefined) {
        try {
          const ev = await fetchEventResolution(marketId);
          if (ev) {
            v = settlementValue(ot?.outcome, { winningLabel: ev });
            if (v !== undefined) src = "event";
          }
        } catch {
          /* leave undetermined */
        }
      }
      resolutionCache.set(marketId, { v, src });
    }
    const res = resolutionCache.get(marketId)!;
    const won = res.v === undefined ? null : res.v === 1;
    const entry = ot?.detectedPrice ?? null;
    const sizeUsd = r.simulatedPositionSize ?? null;
    const at = r.createdAt.getTime();
    const state = openAt(marketId, at);
    const blockClass = classifyBlock(b, state, sizeUsd);

    out.push({
      decidedAt: r.createdAt.toISOString(),
      observedTradeId: r.observedTradeId ?? null,
      marketId,
      marketQuestion: ot?.marketQuestion ?? "",
      outcome: ot?.outcome ?? "",
      venue: r.venue ?? "",
      why: describeBlock(b),
      clause: b.clause,
      sizeUsd,
      openLegsAtDecision: state.legs,
      openNotionalAtDecision: Math.round(state.notional * 100) / 100,
      blockClass,
      entry,
      settlement: res.src,
      won,
      ret: won === null ? null : perDollarReturn(entry, won),
      // Sensitivity: one cent of entry slippage, the lane's own measured cost of
      // taking the print rather than the quote.
      slipRet:
        won === null || entry === null
          ? null
          : perDollarReturn(Math.min(0.999, entry + slip), won),
    });
  }

  const priced = out.filter((r) => r.ret !== null);
  const pricedGenuine = priced.filter((r) => r.blockClass === "genuine");
  const rets = priced.map((r) => r.ret as number);
  const sumRet = rets.reduce((a, b) => a + b, 0);
  const sorted = [...rets].sort((a, b) => a - b);
  const median = sorted.length ? sorted[Math.floor(sorted.length / 2)] : 0;
  const sortedAsc = [...rets].sort((a, b) => b - a);
  const exTop10 = sortedAsc.slice(10).reduce((a, b) => a + b, 0);
  const markets = [...new Set(out.map((r) => r.marketId))];
  // CONCENTRATION — the discipline the card's own note demands. A refusal count is
  // not a set of independent bets: one market can be refused dozens of times (each
  // a real observed trade) while riding ONE outcome. Both reads are stated so a
  // single resolved match cannot masquerade as a broad edge.
  const outcomeKey = (r: Row) => `${r.marketId}|${r.outcome}`;
  const distinctOutcomes = [...new Set(out.map(outcomeKey))];
  const perOutcome = distinctOutcomes.map((k) => {
    const sub = priced.filter((r) => outcomeKey(r) === k);
    return {
      marketId: k.split("|")[0],
      outcome: k.split("|")[1],
      refusals: out.filter((r) => outcomeKey(r) === k).length,
      sumPerDollar: Math.round(sub.reduce((a, r) => a + (r.ret as number), 0) * 100) / 100,
      won: sub.length ? sub.every((r) => r.won === true) : null,
    };
  });
  const exTopOutcome = perOutcome
    .sort((a, b) => b.sumPerDollar - a.sumPerDollar)
    .slice(1)
    .reduce((a, o) => a + o.sumPerDollar, 0);
  const topMarketShare = Math.max(...markets.map((m) => out.filter((r) => r.marketId === m).length)) / (out.length || 1);

  const byClause = (c: "legs" | "notional") => out.filter((r) => r.clause === c).length;
  const summary = {
    generatedAt: new Date().toISOString(),
    days,
    basis: {
      population: "C-200 non-demo decisions carrying a v55 per-market-cap refusal",
      level: "one decision (each refusal = one lost copy; repeats counted each time)",
      clock: "decision createdAt, UTC",
      price: "detectedPrice at decision time; fee 0, slippage 0 (--slip sensitivity printed)",
      settlement: "market winning label (adapter -> event fallback), else undetermined",
      railSeatBasis: "open C-200 legs per marketId at decision time, from booked open/close intervals",
    },
    refused: out.length,
    distinctMarkets: markets.length,
    distinctOutcomes: distinctOutcomes.length,
    topMarketShareOfRefusals: Math.round(topMarketShare * 10000) / 10000,
    sizesRecorded: out.filter((r) => r.sizeUsd !== null).length,
    clause: { legs: byClause("legs"), notional: byClause("notional") },
    blockClass: {
      genuine: out.filter((r) => r.blockClass === "genuine").length,
      phantom: out.filter((r) => r.blockClass === "phantom").length,
      unknown: out.filter((r) => r.blockClass === "unknown").length,
    },
    settlement: {
      market: out.filter((r) => r.settlement === "market").length,
      event: out.filter((r) => r.settlement === "event").length,
      undetermined: out.filter((r) => r.settlement === "undetermined").length,
    },
    priced: {
      n: priced.length,
      meanPerDollar: priced.length ? Math.round((sumRet / priced.length) * 10000) / 10000 : 0,
      medianPerDollar: Math.round(median * 10000) / 10000,
      sumPerDollar: Math.round(sumRet * 100) / 100,
      exTop10PerDollar: Math.round(exTop10 * 100) / 100,
      exTopOutcomePerDollar: Math.round(exTopOutcome * 100) / 100,
      slipSensitivitySum: Math.round(
        priced.reduce((a, r) => a + (r.slipRet as number), 0) * 100
      ) / 100,
    },
    genuineOnly: {
      n: pricedGenuine.length,
      meanPerDollar: pricedGenuine.length
        ? Math.round(
            (pricedGenuine.reduce((a, r) => a + (r.ret as number), 0) / pricedGenuine.length) * 10000
          ) / 10000
        : 0,
      sumPerDollar:
        Math.round(pricedGenuine.reduce((a, r) => a + (r.ret as number), 0) * 100) / 100,
    },
    perOutcome: perOutcome.sort((a, b) => b.refusals - a.refusals),
    rows: out.sort((a, b) => b.decidedAt.localeCompare(a.decidedAt)),
  };
  fs.writeFileSync(OUT, JSON.stringify(summary, null, 2));

  const label = days > 0 ? `last ${days}d` : "all-time";
  console.log(
    `permarket-cap-blocked-legs — ${label} (${since.toISOString().slice(0, 10)} → ${new Date()
      .toISOString()
      .slice(0, 10)}), population = C-200 non-demo decisions carrying a v55 per-market-cap refusal`
  );
  console.log(
    `  refused ${out.length} legs across ${markets.length} markets | clause: legs ${byClause("legs")} / notional ${byClause(
      "notional"
    )} | class: genuine ${summary.blockClass.genuine} / phantom ${summary.blockClass.phantom} / unknown ${summary.blockClass.unknown}`
  );
  console.log(
    `  settlement known for ${summary.settlement.market + summary.settlement.event}/${
      out.length
    } (market ${summary.settlement.market}, event ${summary.settlement.event}; ${summary.settlement.undetermined} undetermined, NOT guessed)`
  );
  console.log(
    `  priced ${priced.length}: per $1 staked mean ${money(summary.priced.meanPerDollar)} median ${money(
      summary.priced.medianPerDollar
    )} sum ${money(summary.priced.sumPerDollar)} | ex-top-10 ${money(summary.priced.exTop10PerDollar)} | +1c slip sum ${money(
      summary.priced.slipSensitivitySum
    )}`
  );
  console.log(
    `  genuine-seat refusals only: n=${summary.genuineOnly.n} mean ${money(
      summary.genuineOnly.meanPerDollar
    )} sum ${money(summary.genuineOnly.sumPerDollar)}`
  );
  console.log(
    `  CONCENTRATION: ${out.length} refusals ride ${distinctOutcomes.length} distinct market+outcome legs; top market = ${(
      topMarketShare * 100
    ).toFixed(1)}% of refusals; sum per $1 ex-top-outcome ${money(summary.priced.exTopOutcomePerDollar)}`
  );
  console.log(
    `  refused-copy size recorded on ${summary.sizesRecorded}/${out.length} rows — the journal does not persist simulatedPositionSize for a refused copy, so no DOLLAR total is claimed here`
  );
  console.log(`  wrote ${OUT}`);
  process.exit(0);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
