/**
 * c200:link-missing-spotcheck — READ-ONLY. Adversarial spot-check of the resolver verdicts that
 * `c200-link-missing-impact.ts` prices, so the proposal is not quoting a resolver nobody audited.
 *
 * Prints, for a sample of the repairable pairs, the exact operand each verdict rests on:
 *   level    = intent − credit(live)      (what the resting bid had to reach)
 *   bookMinAsk                            (lowest ask in our L2 window; ≤ level ⇒ reachable)
 *   tapeReached5/60                       (flat-level tape; false at 60 is a valid NEGATIVE only)
 * and the leg's own booked entry, so a reader can see the credit gap themselves.
 *
 * Also asserts the two invariants the proposal leans on:
 *   1. every pair's leg carries fillStatus NULL today (nothing is being re-stamped);
 *   2. the sum over the "unfilled" bucket + "filled" bucket reproduces the repair's booked PnL.
 *
 * Usage: DATABASE_URL="file:./dev.db" npx tsx scripts/c200-link-missing-spotcheck.ts [--n 8]
 */
import fs from "node:fs";
import path from "node:path";
import { prisma } from "../src/lib/db";
import { log } from "../src/lib/redact";
import { resolveFill, levelFor, creditUsdFor, type ResolutionLeg } from "../src/lib/c200-fill-resolution";

const LANE = "BANKROLL_200";
const ARTIFACT = path.join(process.cwd(), "data", "c200-printthrough.jsonl");
const usd2 = (n: number) => `$${n.toFixed(2)}`;

interface SnapLeg {
  intentId: string;
  intentPrice: number;
  dispatchedAt?: number;
  book?: { minAsk?: number | null; coverStartMs?: number | null; coverEndMs?: number | null } | null;
  tapeSilent?: boolean;
  reached5?: boolean | null;
  reached60?: boolean | null;
  level?: number;
}

function loadLatest(): Map<string, SnapLeg> {
  const out = new Map<string, SnapLeg>();
  for (const line of fs.readFileSync(ARTIFACT, "utf8").split("\n")) {
    if (!line.trim()) continue;
    let s: { legs?: SnapLeg[] };
    try {
      s = JSON.parse(line);
    } catch {
      continue;
    }
    for (const l of s.legs ?? []) if (l?.intentId) out.set(l.intentId, l);
  }
  return out;
}

async function main() {
  const nArg = process.argv.indexOf("--n");
  const n = nArg > 0 ? Number(process.argv[nArg + 1]) : 8;
  const latest = loadLatest();

  const intents = await prisma.fillIntent.findMany({
    where: { botId: LANE },
    select: { id: true, decisionJournalId: true, marketId: true, outcome: true, side: true, intentPrice: true, paperTradeId: true },
  });
  const linked = new Set(intents.filter((i) => i.paperTradeId).map((i) => i.paperTradeId!));
  const legs = await prisma.paperTrade.findMany({
    where: { botId: LANE, isDemo: false },
    select: {
      id: true, decisionJournalId: true, marketId: true, outcome: true, side: true,
      entryPrice: true, realizedPnl: true, simulatedPositionSize: true, status: true, fillStatus: true, openedAt: true,
    },
  });
  const k = (r: { decisionJournalId: string; marketId: string; outcome: string; side: string }) =>
    `${r.decisionJournalId}\u0001${r.marketId}\u0001${r.outcome}\u0001${r.side}`;
  const byKey = new Map<string, typeof legs>();
  for (const l of legs) {
    const key = k(l);
    byKey.set(key, [...(byKey.get(key) ?? []), l]);
  }
  const isInverted = (entry: number, intent: number) =>
    Math.abs(entry - (1 - intent)) <= 0.012 && Math.abs(entry - intent) >= 0.05;

  type Row = { intent: (typeof intents)[number]; leg: (typeof legs)[number]; verdict: string; basis: string; level: number; credit: number; snap?: SnapLeg };
  const rows: Row[] = [];
  const seen = new Set<string>();
  for (const i of intents) {
    if (i.paperTradeId) continue;
    const key = k(i);
    if (seen.has(key)) continue;
    seen.add(key);
    const sameKey = intents.filter((x) => !x.paperTradeId && k(x) === key);
    const cands = (byKey.get(key) ?? []).filter((l) => !linked.has(l.id));
    if (sameKey.length !== 1 || cands.length !== 1) continue;
    if (isInverted(cands[0].entryPrice, i.intentPrice)) continue;
    const s = latest.get(i.id);
    if (!s) continue;
    const rl: ResolutionLeg = {
      intentPrice: Number(s.intentPrice),
      bookMinAsk: s.book && typeof s.book.minAsk === "number" && Number.isFinite(s.book.minAsk) ? s.book.minAsk : null,
      tapeReached5: s.tapeSilent ? null : (s.reached5 ?? null),
      tapeReached60: s.tapeSilent ? null : (s.reached60 ?? null),
    };
    const v = resolveFill(rl, "live");
    rows.push({
      intent: i,
      leg: cands[0],
      verdict: v.basis === "unresolved" ? "unresolved" : v.reachable ? "filled" : "unfilled",
      basis: v.basis,
      level: v.level,
      credit: v.credit,
      snap: s,
    });
  }

  // Invariant 1 — nothing in the population is already stamped.
  const stamped = rows.filter((r) => r.leg.fillStatus !== null);
  log(`population ${rows.length} pairs · already stamped ${stamped.length} (must be 0)${stamped.length ? " *** FAIL ***" : ""}`);

  // Invariant 2 — bucket sums reproduce the repair's own booked-PnL total.
  const tot = rows.reduce((a, r) => a + (r.leg.realizedPnl ?? 0), 0);
  log(`sum of realizedPnl over the population: $${tot.toFixed(2)}`);

  const pick = (want: string) => rows.filter((r) => r.verdict === want).slice(0, n);
  for (const want of ["unfilled", "filled"]) {
    log("");
    log(`--- ${want.toUpperCase()} sample (level = intent − credit) ---`);
    log("  leg                     entry   intent  credit   level  minAsk  tape5/60   basis            leg status/pnl");
    for (const r of pick(want)) {
      const ma = r.snap!.book && typeof r.snap!.book.minAsk === "number" ? r.snap!.book.minAsk.toFixed(3) : "  —  ";
      const tape = `${r.snap!.reached5 === null || r.snap!.reached5 === undefined ? "—" : r.snap!.reached5}/${r.snap!.reached60 === null || r.snap!.reached60 === undefined ? "—" : r.snap!.reached60}`;
      log(
        `  ${r.leg.id.padEnd(24)} ${r.leg.entryPrice.toFixed(3)}  ${r.intent.intentPrice.toFixed(3)}  ${r.credit.toFixed(4)}  ${r.level.toFixed(3)}  ${String(ma).padStart(6)}  ${tape.padEnd(9)}  ${r.basis.padEnd(16)} ` +
          `${r.leg.status}/${(r.leg.realizedPnl ?? 0).toFixed(2)}`
      );
    }
  }

  // A negative must be justified by evidence, never by absence: count how many "unfilled" verdicts
  // rest ONLY on tape silence (reached60 === false with no book) — those are the ones the doc must name.
  const unf = rows.filter((r) => r.verdict === "unfilled");
  const byBasis: Record<string, number> = {};
  for (const r of unf) byBasis[r.basis] = (byBasis[r.basis] ?? 0) + 1;
  log("");
  log(`unfilled verdicts by basis: ${JSON.stringify(byBasis)}`);
  const noBook = unf.filter((r) => !(r.snap!.book && typeof r.snap!.book.minAsk === "number")).length;
  log(`  of which with NO book window (decision rests on the tape lower bound): ${noBook}`);

  // THE REFUTATION, MEASURED. A negative verdict is only as good as the window it rests on: our L2
  // coverage starts a few minutes AFTER the dispatch (the recorder has to be pinned), so a level that
  // was reachable in that gap and never again would read "unfilled" wrongly. Print the lag, the window
  // length, and the distance the ask stayed ABOVE our level, so the size of that hazard is visible
  // instead of asserted. A verdict is FRAGILE if coverage began late (>15 min) or the window is short.
  const lag = (r: (typeof unf)[number]) => {
    const b = r.snap!.book;
    const cs = b && typeof b.coverStartMs === "number" ? b.coverStartMs : null;
    const da = r.snap!.dispatchedAt;
    return cs !== null && typeof da === "number" ? (cs - da) / 60000 : null;
  };
  const win = (r: (typeof unf)[number]) => {
    const b = r.snap!.book;
    if (!b || typeof b.coverStartMs !== "number" || typeof b.coverEndMs !== "number") return null;
    return (b.coverEndMs - b.coverStartMs) / 60000;
  };
  const gaps = unf.map(lag).filter((x): x is number => x !== null).sort((a, b) => a - b);
  const wins = unf.map(win).filter((x): x is number => x !== null).sort((a, b) => a - b);
  const q = (arr: number[], f: number) => (arr.length ? arr[Math.floor(f * (arr.length - 1))] : NaN);
  log("");
  log("EVIDENCE WINDOW the negatives rest on (our L2 coverage starts after the dispatch):");
  log(`  dispatch -> coverage start: median ${q(gaps, 0.5).toFixed(1)} min · p10 ${q(gaps, 0.1).toFixed(1)} · p90 ${q(gaps, 0.9).toFixed(1)} · max ${Math.max(...gaps).toFixed(1)}`);
  log(`  coverage length          : median ${q(wins, 0.5).toFixed(0)} min · p10 ${q(wins, 0.1).toFixed(0)} · min ${Math.min(...wins).toFixed(0)}`);
  const late = unf.filter((r) => (lag(r) ?? 0) > 15).length;
  const shortWin = unf.filter((r) => (win(r) ?? 0) < 10).length;
  log(`  FRAGILE verdicts: coverage began >15 min after dispatch on ${late}, window shorter than 10 min on ${shortWin} (of ${unf.length})`);
  // How far the cheapest ask stayed above the level, as a fraction of the level: a verdict sitting
  // 0.001 from the level is a coin flip on tick granularity; a wide gap is a real negative.
  const rel = unf
    .map((r) => {
      const ma = r.snap!.book?.minAsk;
      return typeof ma === "number" ? (ma - r.level) / r.level : null;
    })
    .filter((x): x is number => x !== null)
    .sort((a, b) => a - b);
  log(`  minAsk - level (relative): median ${(q(rel, 0.5) * 100).toFixed(1)}% · p10 ${(q(rel, 0.1) * 100).toFixed(1)}% · legs within 1% of the level: ${rel.filter((x) => x < 0.01).length}`);
  const marginal = unf.filter((r) => {
    const ma = r.snap!.book?.minAsk;
    return typeof ma === "number" && (ma - r.level) / r.level < 0.01;
  });
  log(
    `  the marginal set (a tick away from "reachable") carries ${usd2(marginal.reduce((a, r) => a + (r.leg.realizedPnl ?? 0), 0))} of realized PnL on ` +
      `${usd2(marginal.reduce((a, r) => a + r.leg.simulatedPositionSize, 0))} notional — the most a stricter test could return`
  );
}

main()
  .catch((e) => {
    log(`FAILED: ${e instanceof Error ? e.message : e}`);
    process.exit(1);
  })
  .finally(() => prisma.$disconnect());
