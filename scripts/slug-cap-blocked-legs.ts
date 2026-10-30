/**
 * slug-cap-blocked-legs — price the legs the v45 per-slug cap ACTUALLY refused.
 * Read-only. Evidence for the `slug-cap-token-granularity` card.
 *
 * WHY NOT THE REPLAY INSTRUMENT: `scripts/replay-slug-cap-basis.ts` re-walks the
 * legs AS BOOKED, so it is structurally blind to the legs the cap blocked (a
 * blocked leg never becomes a PaperTrade) and it is not cap-activation aware (it
 * re-counts the pre-v45 stock — token 'highest' ran to 80 concurrent open legs
 * before v45 activated 2026-09-03T06:43:59Z — as if the cap had blocked them).
 * Its incumbent arm therefore prints ~0 on a window in which the journal recorded
 * 105 blocks. This script reads the population the rail actually touched:
 * DecisionJournal rows whose risksJson carries
 *   `BANKROLL_200: v45 market-slug cap (<token> would be 16/15)`.
 *
 * BASIS (stated, never implied): population = C-200, non-demo decisions carrying
 * a slug-cap block in the window; level = one decision (the same market+outcome
 * may be refused more than once by the same or a different wallet, counted each
 * time because each refusal was a separate lost copy); clock = decision
 * `createdAt` in UTC; price = the decision's detectedPrice (the copy would have
 * entered there); settlement = the MARKET's own winning label (adapter → event
 * fallback → OutcomeReview), never a PnL sign. Fee and slippage are 0 — this is
 * the gross per-$1 read, and `--slip` prints the sensitivity.
 *
 * THE FINDING THIS MEASURES (2026-10-30): the counter behind this rail
 * (`c200SlugCounts` in scripts/score-trades.ts, line ~778) is incremented when a
 * decision PASSES the cap check and is never decremented when a LATER gate
 * refuses the copy. Inside one scoring run, fifteen same-token decisions that all
 * die at the kelly / band / wallet gates leave the bucket reading 15/15 with zero
 * positions open, and every following decision of that token is journalled as
 *   "v45 market-slug cap (<token> would be 16/15)"
 * - a printed basis that says fifteen positions are open. So every block is also
 * classified against the TRUE concurrent open count for its token, reconstructed
 * from the booked legs' own open/close intervals:
 *   genuine = true open >= cap   (the rail refused a 16th leg that existed)
 *   phantom = true open <  cap   (the bucket was filled by refused attempts)
 *
 *   npx tsx scripts/slug-cap-blocked-legs.ts --days 30
 */

import { prisma } from "../src/lib/db";
import { getAdapter } from "../src/lib/adapters";
import { fetchEventResolution } from "../src/lib/dead-market-resolution";
import { settlementValue } from "../src/lib/resolution";
import { parseSlugCapBlocks, perDollarReturn, summarizeReturns } from "../src/lib/slug-cap-blocks";
import * as fs from "fs";
import { join } from "path";

const OUT = join(__dirname, "..", "data", "slug-cap-blocked-legs.json");

function arg(name: string, def: string): string {
  const i = process.argv.indexOf(`--${name}`);
  return i >= 0 && process.argv[i + 1] ? process.argv[i + 1] : def;
}

const pct = (v: number) => `${(v * 100).toFixed(1)}%`;
const money = (v: number) => `${v < 0 ? "-" : ""}$${Math.abs(v).toFixed(2)}`;

type Row = {
  decidedAt: string;
  token: string;
  wouldBe: number;
  cap: number;
  marketId: string;
  marketQuestion: string;
  outcome: string;
  side: string;
  entry: number | null;
  /** true concurrent open legs in this token at decision time (booked legs only) */
  openAtDecision: number;
  /** genuine = rail refused a real 16th leg; phantom = bucket was full of refusals */
  blockClass: "genuine" | "phantom";
  settlement: "market" | "event" | "review" | "undetermined";
  won: boolean | null;
  ret: number | null;
  slipRet: number | null;
};

async function main() {
  const days = Number(arg("days", "30"));
  const slip = Number(arg("slip", "0.01"));
  const since = new Date(Date.now() - days * 86_400_000);

  const rows = await prisma.decisionJournal.findMany({
    where: {
      isDemo: false,
      createdAt: { gte: since },
      risksJson: { contains: "v45 market-slug cap" },
    },
    select: {
      createdAt: true,
      marketId: true,
      risksJson: true,
      decision: true,
      observedTrade: {
        select: { marketId: true, marketQuestion: true, outcome: true, side: true, detectedPrice: true, marketCategory: true },
      },
    },
    orderBy: { createdAt: "asc" },
  });

  // Every booked C-200 leg's open/close interval, per token — the ground truth
  // for "how many positions were actually open when this decision was refused".
  const booked = await prisma.paperTrade.findMany({
    where: { botId: "BANKROLL_200", isDemo: false },
    select: {
      openedAt: true,
      closedAt: true,
      resolvedAt: true,
      decision: { select: { observedTrade: { select: { marketCategory: true } } } },
    },
  });
  const intervals = new Map<string, Array<{ open: number; end: number | null }>>();
  for (const b of booked) {
    const tok = b.decision?.observedTrade?.marketCategory;
    if (!tok) continue;
    const arr = intervals.get(tok) ?? [];
    arr.push({ open: b.openedAt.getTime(), end: (b.closedAt ?? b.resolvedAt)?.getTime() ?? null });
    intervals.set(tok, arr);
  }
  const openAt = (tok: string, at: number) =>
    (intervals.get(tok) ?? []).filter((i) => i.open <= at && (i.end === null || i.end > at)).length;

  const adapter = getAdapter();
  const resolutionCache = new Map<string, { v: number | undefined; src: Row["settlement"] }>();

  const out: Row[] = [];
  for (const r of rows) {
    const blocks = parseSlugCapBlocks(r.risksJson);
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
          v = settlementValue(ot?.outcome, { winningLabel: m.winningLabel ?? m.winningOutcome, yesPrice: m.yesPrice });
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

    const at = r.createdAt.getTime();
    const openAtDecision = openAt(b.token, at);
    out.push({
      decidedAt: r.createdAt.toISOString(),
      token: b.token,
      wouldBe: b.wouldBe,
      cap: b.cap,
      openAtDecision,
      blockClass: openAtDecision >= b.cap ? "genuine" : "phantom",
      marketId,
      marketQuestion: ot?.marketQuestion ?? "",
      outcome: ot?.outcome ?? "",
      side: ot?.side ?? "",
      entry,
      settlement: res.src,
      won,
      ret: won === null ? null : perDollarReturn(entry, won),
      // Sensitivity: one cent of entry slippage, the lane's own measured cost of
      // taking the print rather than the quote.
      slipRet: won === null || entry === null ? null : perDollarReturn(Math.min(0.999, entry + slip), won),
    });
  }

  const priced = out.filter((r) => r.ret !== null);
  const tokens = [...new Set(out.map((r) => r.token))].sort();
  const summary = {
    generatedAt: new Date().toISOString(),
    days,
    basis: {
      population: "C-200 non-demo decisions carrying a v45 slug-cap block",
      level: "one decision (each refusal = one lost copy)",
      clock: "decision createdAt, UTC",
      price: "detectedPrice at decision time; fee 0, slippage 0",
      settlement: "market winning label (adapter -> event fallback), else undetermined",
    },
    blocked: out.length,
    phantom: out.filter((r) => r.blockClass === "phantom").length,
    phantomShare: out.length ? out.filter((r) => r.blockClass === "phantom").length / out.length : 0,
    priced: priced.length,
    undetermined: out.length - priced.length,
    overall: summarizeReturns(priced.map((r) => r.ret!)),
    byClass: Object.fromEntries(
      (["genuine", "phantom"] as const).map((cls) => {
        const legs = priced.filter((r) => r.blockClass === cls);
        return [
          cls,
          { blocked: out.filter((r) => r.blockClass === cls).length, ...summarizeReturns(legs.map((r) => r.ret!)) },
        ];
      })
    ),
    slipOverall: summarizeReturns(priced.map((r) => r.slipRet!).filter((v) => v !== null)),
    byToken: Object.fromEntries(
      tokens.map((t) => {
        const legs = priced.filter((r) => r.token === t);
        return [t, { blocked: out.filter((r) => r.token === t).length, ...summarizeReturns(legs.map((r) => r.ret!)) }];
      })
    ),
    rows: out,
  };

  console.log(
    `slug-cap blocks, last ${days}d (${since.toISOString().slice(0, 10)} -> now): ${out.length} decisions | ` +
      `${priced.length} priced to settlement, ${out.length - priced.length} undetermined (never counted as losses)`
  );
  const o = summary.overall;
  if (o.n > 0) {
    console.log(
      `ALL TOKENS  n=${o.n}  win ${pct(o.winRate)}  per-$1 mean ${money(o.mean)}  median ${money(o.median)}  ` +
        `trimmed ${money(o.trimmedMean)}  sum ${money(o.sum)}  ex-top-10 ${money(o.exTop10Sum)}`
    );
    console.log(`  +1c entry slippage: mean ${money(summary.slipOverall.mean)}  sum ${money(summary.slipOverall.sum)}`);
  }
  for (const t of tokens) {
    const s = summary.byToken[t];
    console.log(
      `  ${t.padEnd(10)} blocked ${String(s.blocked).padStart(3)}  priced ${String(s.n).padStart(3)}  win ${pct(s.winRate).padStart(5)}  ` +
        `mean ${money(s.mean).padStart(7)}  median ${money(s.median).padStart(7)}  sum ${money(s.sum).padStart(8)}`
    );
  }
  for (const cls of ["genuine", "phantom"] as const) {
    const c = summary.byClass[cls];
    console.log(
      `  ${cls.padEnd(8)} blocked ${String(c.blocked).padStart(3)}  priced ${String(c.n).padStart(3)}  win ${pct(c.winRate).padStart(5)}  ` +
        `mean ${money(c.mean).padStart(7)}  median ${money(c.median).padStart(7)}  sum ${money(c.sum).padStart(8)}  ex-top-10 ${money(c.exTop10Sum)}`
    );
  }
  const phantomShare = summary.phantomShare ?? 0;
  console.log(
    `  PHANTOM blocks (true concurrent open < cap): ${summary.phantom} / ${out.length} = ${pct(phantomShare)} — ` +
      `the bucket was filled by attempts a LATER gate refused, not by open positions`
  );
  const pressure = out.filter((r) => r.wouldBe > r.cap).length;
  console.log(`  blocks where the cap was the ONLY thing standing between the wallet and a copy: ${pressure}/${out.length}`);
  fs.writeFileSync(OUT, JSON.stringify(summary, null, 2));
  console.log(`wrote ${OUT}`);
  console.log(
    "READ: a negative mean on priced blocks says the rail PROTECTED the lane (it refused losers); " +
      "a positive mean says it STARVED it. Medians and the ex-top-10 column decide whether the sign is real."
  );
}

main()
  .catch((e) => {
    console.error(e);
    process.exit(1);
  })
  .finally(() => prisma.$disconnect());
