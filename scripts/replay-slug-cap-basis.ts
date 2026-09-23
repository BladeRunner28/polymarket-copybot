/**
 * replay-slug-cap-basis — what the v45 15-per-slug cap gates today, and what it
 * would gate if it counted a different bucket. Read-only, evidence for the
 * `slug-cap-token-granularity` card (approved 2026-09-23).
 *
 * THE PROBLEM: rules.maxMarketSlugPositions = 15 is counted per RAW event-slug
 * TOKEN (score-trades.ts c200SlugCounts). Token 'highest' wraps 14,879 distinct
 * marketIds while 'lol' wraps 1,364 — so one mega-bucket consumes a cap that was
 * designed as league-level exposure control. Measured 2026-09-23: 1,002 blocks in
 * the last 7 days, 1,000 of them on token 'highest'.
 *
 * WHAT THIS DOES (the replay-market-cap pattern): re-walk the C-200 legs we
 * actually booked, in open order, maintaining the running OPEN count per bucket
 * under each candidate basis, and report which legs each basis would have
 * blocked and what those legs cost or earned. Entries are unchanged; this is a
 * counterfactual about the CAP, not a strategy backtest. PnL for a leg is its
 * realizedPnl when finished, else its unrealizedPnl at run time.
 *
 *   npx tsx scripts/replay-slug-cap-basis.ts --days 30 --cap 15
 */

import { prisma } from "../src/lib/db";
import { classifyMarketCategory } from "../src/lib/market-category";
import * as fs from "fs";
import { join } from "path";

const OUT = join(__dirname, "..", "data", "slug-cap-basis-replay.json");

function arg(name: string, def: string): string {
  const i = process.argv.indexOf(`--${name}`);
  return i >= 0 && process.argv[i + 1] ? process.argv[i + 1] : def;
}

type Leg = {
  marketId: string;
  openedAt: number;
  endedAt: number | null;
  pnl: number;
  settled: boolean;
  token: string;
  coarse: string;
  fine: string;
  question: string;
};

type Basis = "token" | "fine" | "coarse";

function keyOf(leg: Leg, basis: Basis): string {
  return basis === "token" ? leg.token : basis === "fine" ? leg.fine : leg.coarse;
}

/** Time-ordered replay: returns the blocked legs under `basis` / `cap`. */
function replay(legs: Leg[], basis: Basis, cap: number): { blocked: Leg[]; counts: Map<string, number> } {
  const open = new Map<string, number>();
  const blocked: Leg[] = [];
  // Legs are processed in open order; a bucket is freed when a leg finishes.
  const finishes: Array<{ at: number; key: string }> = [];
  const sorted = [...legs].sort((a, b) => a.openedAt - b.openedAt);
  for (const leg of sorted) {
    while (finishes.length && finishes[0].at <= leg.openedAt) {
      const f = finishes.shift()!;
      open.set(f.key, Math.max(0, (open.get(f.key) ?? 1) - 1));
    }
    const k = keyOf(leg, basis);
    const n = open.get(k) ?? 0;
    if (n + 1 > cap) {
      blocked.push(leg);
      continue;
    }
    open.set(k, n + 1);
    if (leg.endedAt !== null) {
      finishes.push({ at: leg.endedAt, key: k });
      finishes.sort((a, b) => a.at - b.at);
    }
  }
  return { blocked, counts: open };
}

const money = (v: number) => `${v < 0 ? "-" : ""}$${Math.abs(v).toFixed(2)}`;

async function main() {
  const days = Number(arg("days", "30"));
  const cap = Number(arg("cap", "15"));
  const since = new Date(Date.now() - days * 86_400_000);

  const rows = await prisma.paperTrade.findMany({
    where: { botId: "BANKROLL_200", isDemo: false, openedAt: { gte: since } },
    select: {
      marketId: true,
      status: true,
      openedAt: true,
      closedAt: true,
      resolvedAt: true,
      realizedPnl: true,
      unrealizedPnl: true,
      decision: {
        select: { observedTrade: { select: { marketCategory: true, marketQuestion: true } } },
      },
    },
  });

  const legs: Leg[] = rows.map((r) => {
    const ot = r.decision?.observedTrade;
    const cls = classifyMarketCategory(r.marketId, ot?.marketQuestion ?? null);
    const endedAt = r.closedAt ?? r.resolvedAt ?? null;
    return {
      marketId: r.marketId,
      openedAt: r.openedAt.getTime(),
      endedAt: endedAt ? endedAt.getTime() : null,
      pnl: (r.realizedPnl ?? r.unrealizedPnl ?? 0) as number,
      settled: r.status !== "open",
      token: ot?.marketCategory ?? "(unknown)",
      coarse: cls.coarse,
      fine: cls.fine,
      question: ot?.marketQuestion ?? "",
    };
  });

  console.log(
    `C-200 legs opened in the last ${days}d: ${legs.length} | cap under test: ${cap} per bucket | ` +
      `${legs.filter((l) => l.settled).length} settled, ${legs.filter((l) => !l.settled).length} still open (valued at their mark)`
  );

  const out: Record<string, unknown> = { generatedAt: new Date().toISOString(), days, cap, legs: legs.length, bases: {} };
  for (const basis of ["token", "fine", "coarse"] as Basis[]) {
    const { blocked, counts } = replay(legs, basis, cap);
    const pnl = blocked.reduce((a, l) => a + l.pnl, 0);
    const biggest = [...counts.entries()].sort((a, b) => b[1] - a[1]).slice(0, 8);
    console.log(`\n${basis.toUpperCase()} basis`);
    console.log(
      `  would block ${blocked.length}/${legs.length} leg(s); blocked PnL ${money(pnl)} ` +
        `(${blocked.filter((l) => l.pnl > 0).length} winners / ${blocked.filter((l) => l.pnl <= 0).length} losers)`
    );
    const byBucket = new Map<string, { n: number; pnl: number }>();
    for (const l of blocked) {
      const k = keyOf(l, basis);
      const e = byBucket.get(k) ?? { n: 0, pnl: 0 };
      e.n++;
      e.pnl += l.pnl;
      byBucket.set(k, e);
    }
    for (const [k, v] of [...byBucket.entries()].sort((a, b) => b[1].n - a[1].n).slice(0, 6)) {
      console.log(`     ${k.padEnd(18)} ${String(v.n).padStart(4)} leg(s)  ${money(v.pnl)}`);
    }
    console.log(`  buckets at/over the cap when the window ended: ${biggest.map(([k, n]) => `${k}=${n}`).join(", ") || "none"}`);
    out.bases = {
      ...(out.bases as Record<string, unknown>),
      [basis]: {
        blockedLegs: blocked.length,
        blockedPnl: Number(pnl.toFixed(2)),
        blockedWinners: blocked.filter((l) => l.pnl > 0).length,
        blockedLosers: blocked.filter((l) => l.pnl <= 0).length,
        byBucket: Object.fromEntries([...byBucket.entries()].map(([k, v]) => [k, { legs: v.n, pnl: Number(v.pnl.toFixed(2)) }])),
        openAtEnd: Object.fromEntries(biggest),
      },
    };
  }

  fs.writeFileSync(OUT, JSON.stringify(out, null, 2));
  console.log(`\nwrote ${OUT}`);
  console.log("READ: a basis that blocks LOSERS is protecting the lane; one that blocks WINNERS is starving it. The");
  console.log("token basis is production today; the others are counterfactuals, not proposals.");
}

main()
  .catch((e) => {
    console.error(e);
    process.exit(1);
  })
  .finally(() => prisma.$disconnect());
