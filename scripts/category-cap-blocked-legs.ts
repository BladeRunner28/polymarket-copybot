/**
 * category-cap-blocked-legs — price the copies the v41 per-category rail ACTUALLY
 * refused, and classify each refusal against the category's true open book.
 * Read-only. Evidence for the `category-seats-never-released` card.
 *
 * THE DEFECT THIS MEASURES: `c200CategoryCounts` is seeded from the C-200 open
 * rows once per run (~L262 of scripts/score-trades.ts) and incremented when a
 * candidate PASSES the category check (~L678). Nothing decrements it, so every
 * later refusal in the same run leaves the seat consumed. The printed
 * `would be 41/40` therefore describes seats consumed by PASSING CANDIDATES, not
 * open positions, and it seeds from C-200 rows while blocking a decision that is
 * scored for both lanes.
 *
 * BASIS (stated, never implied): population = non-demo decisions carrying a
 * category-concentration refusal in the window; level = one decision (each refusal
 * = one lost copy; repeats counted each time); clock = decision `createdAt` in UTC;
 * price = the decision's detectedPrice (where the copy would have entered);
 * settlement = the MARKET's own winning label (adapter -> event fallback), never a
 * PnL sign; fee and slippage are 0 (gross per-$1 read).
 *
 * EVERY REFUSAL IS CLASSIFIED against the true concurrent state of its RESEARCH
 * CATEGORY, reconstructed from the booked C-200 legs' own open/close intervals:
 *   genuine = the category really held >= maxCategoryPositions open legs
 *   phantom = it held fewer, so a later-refused copy was holding the seat
 * and the rail's REACHABILITY is measured separately: the lifetime peak concurrent
 * open legs per category (above the cap, the rail can never bind on a true basis).
 *
 *   npx tsx scripts/category-cap-blocked-legs.ts            # all-time
 *   npx tsx scripts/category-cap-blocked-legs.ts --days 30
 */

import { prisma } from "../src/lib/db";
import { getAdapter } from "../src/lib/adapters";
import { fetchEventResolution } from "../src/lib/dead-market-resolution";
import { settlementValue } from "../src/lib/resolution";
import { perDollarReturn } from "../src/lib/slug-cap-blocks";
import { researchCategoryFor } from "../src/lib/research-categories";
import {
  classifyCategoryBlock,
  describeCategoryBlock,
  maxConcurrentLegsAt,
  openLegsAt,
  parseCategoryCapBlocks,
  type BlockClass,
  type Interval,
} from "../src/lib/category-cap-blocks";
import * as fs from "fs";
import { join } from "path";

const OUT = join(__dirname, "..", "data", "category-cap-blocked-legs.json");

function arg(name: string, def: string): string {
  const i = process.argv.indexOf(`--${name}`);
  return i >= 0 && process.argv[i + 1] ? process.argv[i + 1] : def;
}

const money = (v: number) => `${v < 0 ? "-" : ""}$${Math.abs(v).toFixed(2)}`;

type Row = {
  decidedAt: string;
  decisionJournalId: string;
  observedTradeId: string | null;
  marketId: string;
  marketQuestion: string;
  category: string;
  wouldBe: number;
  cap: number;
  basisForm: "attempts" | "attempts-labelled";
  openLegsAtDecision: number | null;
  blockClass: BlockClass;
  otherDecisionLevelBlockers: string[];
  entry: number | null;
  settlement: "market" | "event" | "undetermined";
  won: boolean | null;
  ret: number | null;
};

async function main() {
  const days = Number(arg("days", "0")); // 0 = whole lifetime
  const since = days > 0 ? new Date(Date.now() - days * 86_400_000) : new Date(0);

  const rows = await prisma.decisionJournal.findMany({
    where: {
      isDemo: false,
      createdAt: { gte: since },
      risksJson: { contains: "category concentration" },
    },
    select: {
      id: true,
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
          marketCategory: true,
          outcome: true,
          side: true,
          detectedPrice: true,
        },
      },
    },
    orderBy: { createdAt: "asc" },
  });

  // Every booked C-200 leg's open/close interval, keyed by RESEARCH CATEGORY —
  // the same mapping the rail seeds itself from (researchCategoryFor(question, slug)).
  const booked = await prisma.paperTrade.findMany({
    where: { botId: "BANKROLL_200", isDemo: false },
    select: {
      marketId: true,
      openedAt: true,
      closedAt: true,
      resolvedAt: true,
      decision: {
        select: {
          observedTrade: { select: { marketQuestion: true, marketCategory: true } },
        },
      },
    },
  });
  const byCategory = new Map<string, Interval[]>();
  let unmappedLegs = 0;
  for (const b of booked) {
    const ot = b.decision?.observedTrade;
    const cat = researchCategoryFor(ot?.marketQuestion, ot?.marketCategory);
    if (!cat) {
      unmappedLegs += 1;
      continue;
    }
    const arr = byCategory.get(cat) ?? [];
    arr.push({ open: b.openedAt.getTime(), end: (b.closedAt ?? b.resolvedAt)?.getTime() ?? null });
    byCategory.set(cat, arr);
  }

  const adapter = getAdapter();
  const resolutionCache = new Map<string, { v: number | undefined; src: Row["settlement"] }>();

  const otherBlockerRe =
    /daily loss limit|gross exposure cap|token circuit breaker|drawdown gate/;

  const out: Row[] = [];
  for (const r of rows) {
    const blocks = parseCategoryCapBlocks(r.risksJson);
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
        /* fall through to the event fallback */
      }
      if (v === undefined) {
        try {
          const ev = await fetchEventResolution(marketId);
          if (ev) {
            v = settlementValue(ot?.outcome, { winningLabel: ev });
            if (v !== undefined) src = "event";
          }
        } catch {
          /* leave undetermined — never guess */
        }
      }
      resolutionCache.set(marketId, { v, src });
    }
    const res = resolutionCache.get(marketId)!;
    const won = res.v === undefined ? null : res.v === 1;
    const entry = ot?.detectedPrice ?? null;
    const at = r.createdAt.getTime();
    const intervals = byCategory.get(b.category) ?? [];
    const openLegs = byCategory.has(b.category) ? openLegsAt(intervals, at) : 0;

    out.push({
      decidedAt: r.createdAt.toISOString(),
      decisionJournalId: r.id,
      observedTradeId: r.observedTradeId ?? null,
      marketId,
      marketQuestion: ot?.marketQuestion ?? "",
      category: b.category,
      wouldBe: b.wouldBe,
      cap: b.cap,
      basisForm: b.basis,
      openLegsAtDecision: openLegs,
      blockClass: classifyCategoryBlock(b, openLegs),
      otherDecisionLevelBlockers: (r.risksJson ?? "").match(otherBlockerRe) ? ["yes"] : [],
      entry,
      settlement: res.src,
      won,
      ret: won === null ? null : perDollarReturn(entry, won),
    });
  }

  // When did this rail start existing? A peak that predates v41 says nothing about
  // whether the rail binds, so the clock travels with the number.
  const v41 = await prisma.ruleSet.findFirst({ where: { version: 41 }, select: { createdAt: true } });
  const v41At = v41?.createdAt?.getTime() ?? null;
  const reachability = [...byCategory.entries()]
    .map(([category, ivs]) => {
      const peak = maxConcurrentLegsAt(ivs);
      return {
        category,
        lifetimeLegs: ivs.length,
        peakConcurrentOpen: peak.legs,
        peakAt: peak.at === null ? null : new Date(peak.at).toISOString(),
        peakPostRailActivation: peak.at !== null && v41At !== null ? peak.at >= v41At : null,
        peakPostActivationLegs:
          v41At === null ? null : maxConcurrentLegsAt(ivs.filter((i) => i.open >= v41At)).legs,
      };
    })
    .sort((a, b) => b.peakConcurrentOpen - a.peakConcurrentOpen);

  const cap = out.length ? out[0].cap : 0;
  const priced = out.filter((r) => r.ret !== null);
  const rets = priced.map((r) => r.ret as number);
  const sum = rets.reduce((a, b) => a + b, 0);
  const sortedAsc = [...rets].sort((a, b) => b - a);
  const phantom = out.filter((r) => r.blockClass === "phantom");
  const genuine = out.filter((r) => r.blockClass === "genuine");
  const noOtherBlocker = out.filter((r) => r.otherDecisionLevelBlockers.length === 0);
  const distinctOutcomes = [...new Set(out.map((r) => `${r.marketId}|${r.marketQuestion}`))];
  // Same-run burst test: refusals landing in the same second are one scoring run
  // filling the counter with candidates, which is the defect's signature.
  const bySecond = new Map<string, number>();
  for (const r of out) bySecond.set(r.decidedAt, (bySecond.get(r.decidedAt) ?? 0) + 1);
  const largestBurst = Math.max(0, ...bySecond.values());

  const summary = {
    generatedAt: new Date().toISOString(),
    days,
    basis: {
      population: "non-demo decisions carrying a v41 category-concentration refusal",
      level: "one decision (each refusal = one lost copy; repeats counted each time)",
      clock: "decision createdAt, UTC",
      price: "detectedPrice at decision time; fee 0, slippage 0",
      settlement: "market winning label (adapter -> event fallback), else undetermined",
      seatBasis:
        "open C-200 legs in the same research category at decision time, from booked open/close intervals",
      reachability: "lifetime peak concurrent open C-200 legs per research category",
    },
    capInForce: cap,
    refused: out.length,
    distinctOutcomes: distinctOutcomes.length,
    basisForm: {
      attempts: out.filter((r) => r.basisForm === "attempts").length,
      attemptsLabelled: out.filter((r) => r.basisForm === "attempts-labelled").length,
    },
    blockClass: {
      genuine: genuine.length,
      phantom: phantom.length,
      unknown: out.filter((r) => r.blockClass === "unknown").length,
    },
    sameRunBurst: { largestRefusalsInOneSecond: largestBurst, distinctSeconds: bySecond.size },
    admissions: {
      noOtherDecisionLevelBlocker: noOtherBlocker.length,
      withOtherBlocker: out.length - noOtherBlocker.length,
    },
    settlement: {
      market: out.filter((r) => r.settlement === "market").length,
      event: out.filter((r) => r.settlement === "event").length,
      undetermined: out.filter((r) => r.settlement === "undetermined").length,
    },
    priced: {
      n: priced.length,
      meanPerDollar: priced.length ? Math.round((sum / priced.length) * 10000) / 10000 : 0,
      sumPerDollar: Math.round(sum * 100) / 100,
      exTop10PerDollar: Math.round(sortedAsc.slice(10).reduce((a, b) => a + b, 0) * 100) / 100,
      wins: priced.filter((r) => r.won === true).length,
    },
    reachability,
    unmappedBookedLegs: unmappedLegs,
    rows: out.sort((a, b) => b.decidedAt.localeCompare(a.decidedAt)),
  };
  fs.writeFileSync(OUT, JSON.stringify(summary, null, 2));

  const label = days > 0 ? `last ${days}d` : "all-time";
  console.log(
    `category-cap-blocked-legs — ${label} (${since.toISOString().slice(0, 10)} -> ${new Date()
      .toISOString()
      .slice(0, 10)}), cap = ${cap} open C-200 positions per research category`
  );
  console.log(
    `  refused ${out.length} copies across ${distinctOutcomes.length} distinct market+question outcomes | class: genuine ${summary.blockClass.genuine} / phantom ${summary.blockClass.phantom} / unknown ${summary.blockClass.unknown}`
  );
  console.log(
    `  basis form on those rows: attempts-unlabelled ${summary.basisForm.attempts} / labelled ${summary.basisForm.attemptsLabelled}`
  );
  console.log(
    `  same-run burst: ${largestBurst} refusals inside ONE second over ${bySecond.size} distinct second(s)`
  );
  console.log(
    `  other decision-level blocker present on ${summary.admissions.withOtherBlocker}/${out.length} refused rows -> releasing the seat alone would admit ${summary.admissions.noOtherDecisionLevelBlocker}`
  );
  console.log(
    `  settlement known for ${summary.settlement.market + summary.settlement.event}/${out.length} (market ${summary.settlement.market}, event ${summary.settlement.event}; ${summary.settlement.undetermined} undetermined, NOT guessed)`
  );
  console.log(
    `  priced ${priced.length}: per $1 staked mean ${money(summary.priced.meanPerDollar)} sum ${money(
      summary.priced.sumPerDollar
    )} ex-top-10 ${money(summary.priced.exTop10PerDollar)} wins ${summary.priced.wins}`
  );
  if (reachability.length) {
    const top = reachability.slice(0, 5);
    console.log(
      `  REACHABILITY (lifetime peak concurrent open legs per category, cap ${cap}): ` +
        top.map((r) => `${r.category} ${r.peakConcurrentOpen} @${(r.peakAt ?? "n/a").slice(0, 10)}`).join(", ") +
        ` / max post-activation peak (v41 ${v41At === null ? "n/a" : new Date(v41At).toISOString().slice(0, 10)}) = ${Math.max(0, ...reachability.map((r) => r.peakPostActivationLegs ?? 0))} vs cap ${cap}`
    );
  }
  if (out.length) {
    console.log("  refusals:");
    for (const r of out) {
      console.log(
        `    ${r.decidedAt} ${describeCategoryBlock({
          category: r.category,
          wouldBe: r.wouldBe,
          cap: r.cap,
          basis: r.basisForm,
        })} | true open ${r.openLegsAtDecision} | ${r.blockClass} | entry ${
          r.entry ?? "n/a"
        } | won ${r.won === null ? "undetermined" : r.won} | other blocker ${
          r.otherDecisionLevelBlockers.length ? "yes" : "no"
        }`
      );
    }
  }
  console.log(`  wrote ${OUT}`);
  process.exit(0);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
