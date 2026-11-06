/**
 * v65-paired-read — READ-ONLY. The 2026-10-22 REC 1 instrument (card `v65-paired-read-instrument`).
 *
 * THE REC: "v65 paired read — 2SE <= $10 per leg at n >= 70 leg pairs". It was named in three
 * consecutive weeklys with no script and no reader, so this card exists to build the reader BEFORE
 * the 2026-11-15 window closes rather than report it lost afterwards.
 *
 * WHAT v65 WAS: RuleSet v65 (2026-10-21T09:16:47Z, audit `hermes-v65-wallet-admission-only`,
 * commit b495e9a) set `walletQualityInSize` 1 -> 0 — wallet quality stops widening size and becomes
 * admission-only. The question the rec wanted answered is whether that change paid or cost.
 *
 * BASIS, all four parts stated because a number without them is not a number:
 *   population  PaperTrade legs, isDemo=0, status closed|resolved, settled clock not null, joined to
 *               DecisionJournal for the ruleset version. Three arms:
 *                 v65 era        = ruleSetVersion 65 exactly (the frozen window's own contents)
 *                 post-v65       = ruleSetVersion >= 65 (the widened arm — v66..v71 changed other
 *                                  things, so it CANNOT attribute anything to v65; printed because
 *                                  a reader that refuses to run at all reads like a lost rec)
 *                 pre-v65        = ruleSetVersion < 65, and the CONTEMPORANEOUS sub-arm v60..64,
 *                                  whose rules are the immediate predecessor and therefore the only
 *                                  honest comparator (earlier eras changed size and exit paths too).
 *   clock       settlement = COALESCE(closedAt, resolvedAt), UTC. Never openedAt: a leg that opens
 *               before the epoch and settles after it belongs to the era it DECIDED in, and the era
 *               is the journal's, not the calendar's.
 *   level       the leg. A pair is one post leg + one pre leg.
 *   price/fee   PnL net of BOTH legs' fees, via feeDecomposition + netTargets
 *               (src/lib/training-export.ts -> the one taker law p*(1-p)*rate). Rate basis is printed
 *               (the text proxy on the market's own question) so it is never hidden in a blend.
 *
 * PAIRING (two bases, never pooled — see src/lib/v65-paired-read.ts):
 *   exact  same lane + market + outcome. Shares the resolution event, so outcome variance cancels.
 *   class  same lane + price band, nearest entry price within 0.10, 1:1 without replacement.
 *          Does NOT cancel the resolution draw; its paired sd is the reason to say so.
 *
 * THE GATE IS PRECISION, NOT SIGNIFICANCE: 2SE <= $10 per leg at n >= 70. A point estimate whose 2SE
 * is $20 cannot distinguish a v65-sized effect from zero, so it is NOT reported as a verdict. The
 * reader prints the pair count 2SE<=$10 would need at the observed paired sd (and the sd ceiling at
 * n=70), so the disposition is arithmetic rather than editorial. Every class read also prints median,
 * trimmed mean and ex-top-3/10: a mean that lives in its top few pairs is a draw, not an effect.
 *
 *   npx tsx scripts/v65-paired-read.ts               # read the book, write data/v65-paired-read.json
 *   npx tsx scripts/v65-paired-read.ts --self-test   # prove the gate can go RED, then read
 */

import { prisma } from "../src/lib/db";
import { Prisma } from "@prisma/client";
import { feeDecomposition, netTargets } from "../src/lib/training-export";
import {
  V65_GATE,
  classPairs,
  diffConcentration,
  exactMates,
  gateVerdict,
  pairedStats,
  priceBand,
  usd,
  type LegPair,
  type PairedLeg,
} from "../src/lib/v65-paired-read";
import * as fs from "fs";
import { join } from "path";

const OUT = join(__dirname, "..", "data", "v65-paired-read.json");
const EPOCH = "2026-10-21T09:16:47Z";
/** Immediate predecessor rulesets — the only pre arm whose rules are comparable to v65's. */
const CONTEMPORANEOUS_FLOOR = 60;

type Row = {
  id: string;
  lane: string;
  marketId: string;
  outcome: string;
  entryPrice: number;
  sizeUsd: number;
  realized: number;
  status: string;
  currentPrice: number | null;
  openedAt: Date;
  settledAt: Date;
  v: number | null;
  question: string | null;
};

async function loadRows(): Promise<Row[]> {
  const raw = await prisma.$queryRaw<
    Array<{
      id: string;
      botId: string;
      marketId: string;
      outcome: string;
      entryPrice: number;
      sizeUsd: number;
      realized: number | null;
      status: string;
      currentPrice: number | null;
      openedAt: bigint | number;
      settledMs: bigint | number;
      v: number | null;
    }>
  >(Prisma.sql`
    SELECT t.id, t.botId, t.marketId, t.outcome, t.entryPrice, t.simulatedPositionSize AS sizeUsd,
           t.realizedPnl AS realized, t.status, t.currentPrice,
           t.openedAt AS openedAt,
           COALESCE(t.closedAt, t.resolvedAt) AS settledMs,
           d.ruleSetVersion AS v
    FROM PaperTrade t
    JOIN DecisionJournal d ON d.id = t.decisionJournalId
    WHERE t.isDemo = 0
      AND t.status IN ('closed','resolved')
      AND COALESCE(t.closedAt, t.resolvedAt) IS NOT NULL
      AND t.realizedPnl IS NOT NULL
  `);
  const markets = Array.from(new Set(raw.map((r) => r.marketId)));
  const questions = new Map<string, string>();
  if (markets.length) {
    const qs = await prisma.$queryRaw<Array<{ marketId: string; question: string }>>(Prisma.sql`
      SELECT marketId, question FROM (
        SELECT marketId, question,
               ROW_NUMBER() OVER (PARTITION BY marketId ORDER BY collectedAt DESC) AS rn
        FROM MarketSnapshot WHERE marketId IN (${Prisma.join(markets)})
      ) WHERE rn = 1
    `);
    for (const q of qs) questions.set(q.marketId, q.question);
  }
  return raw.map((r) => ({
    id: r.id,
    lane: r.botId,
    marketId: r.marketId,
    outcome: r.outcome,
    entryPrice: r.entryPrice,
    sizeUsd: r.sizeUsd,
    realized: r.realized ?? 0,
    status: r.status,
    currentPrice: r.currentPrice,
    openedAt: new Date(Number(r.openedAt)),
    settledAt: new Date(Number(r.settledMs)),
    v: r.v,
    question: questions.get(r.marketId) ?? null,
  }));
}

function toLeg(r: Row): PairedLeg {
  const fees = feeDecomposition({
    entryPrice: r.entryPrice,
    sizeUsd: r.sizeUsd,
    feeText: r.question,
    status: r.status,
    currentPrice: r.currentPrice,
  });
  const net = netTargets({ realizedPnl: r.realized, fees });
  return {
    id: r.id,
    lane: r.lane,
    marketId: r.marketId,
    outcome: r.outcome,
    entryPrice: r.entryPrice,
    sizeUsd: r.sizeUsd,
    pnlNet: net.pnlNetFull,
    pnlGross: r.realized,
    openedAt: r.openedAt,
    settledAt: r.settledAt,
    ruleSetVersion: r.v,
  };
}

function census(legs: PairedLeg[]) {
  const byLane = new Map<string, PairedLeg[]>();
  for (const l of legs) {
    const arr = byLane.get(l.lane) ?? [];
    arr.push(l);
    byLane.set(l.lane, arr);
  }
  return Array.from(byLane.entries())
    .sort((a, b) => a[0].localeCompare(b[0]))
    .map(([lane, xs]) => {
      const bands = new Map<string, number>();
      for (const x of xs) bands.set(priceBand(x.entryPrice), (bands.get(priceBand(x.entryPrice)) ?? 0) + 1);
      return {
        lane,
        n: xs.length,
        distinctSizes: new Set(xs.map((x) => x.sizeUsd.toFixed(2))).size,
        minSize: Math.min(...xs.map((x) => x.sizeUsd)),
        maxSize: Math.max(...xs.map((x) => x.sizeUsd)),
        netPnl: xs.reduce((a, x) => a + x.pnlNet, 0),
        bands: Object.fromEntries([...bands.entries()].sort()),
      };
    });
}

function reportPairs(label: string, pairs: LegPair[], withConcentration = false) {
  const st = pairedStats(pairs);
  const g = gateVerdict(st);
  console.log(
    `  ${label.padEnd(34)} pairs ${String(st.n).padStart(4)}  clusters ${String(st.clusters).padStart(4)}` +
      `  mean ${usd(st.meanDiff).padStart(8)}  sd ${st.sd.toFixed(2).padStart(6)}  2SE ${st.twoSe.toFixed(2).padStart(6)}` +
      `  -> ${g.verdict}`
  );
  let conc = null;
  if (withConcentration && st.n) {
    conc = diffConcentration(pairs);
    console.log(
      `      median ${usd(conc.median)}  trimmed ${usd(conc.trimmedMean)}` +
        conc.exTop.map((e) => `  ex-top-${e.k} ${usd(e.mean)}`).join("") +
        `  top-10 share ${(100 * conc.topShare).toFixed(0)}%`
    );
  }
  return { label, stats: st, gate: g, concentration: conc };
}

async function selfTest() {
  // A gate that cannot go RED is not a gate. Three synthetic pairings: one that must PASS the bar
  // (tight, wide n), one that must be UNRESOLVABLE (same n, real-book variance), one that must be
  // VANISHED-BY-N (empty). If any of the three reads wrongly, the reader is an ornament.
  const leg = (id: string, market: string, pnl: number): PairedLeg => ({
    id,
    lane: "T",
    marketId: market,
    outcome: "Yes",
    entryPrice: 0.5,
    sizeUsd: 10,
    pnlNet: pnl,
    pnlGross: pnl,
    openedAt: new Date(0),
    settledAt: new Date(0),
    ruleSetVersion: 65,
  });
  const tight: LegPair[] = [];
  for (let i = 0; i < 80; i++) tight.push({ basis: "exact", post: leg(`p${i}`, `m${i}`, 1), pre: leg(`q${i}`, `m${i}`, 0), gap: 0 });
  const loose: LegPair[] = [];
  for (let i = 0; i < 80; i++)
    loose.push({ basis: "class", post: leg(`p${i}`, `m${i}`, i % 2 ? 79.6 : -79.6), pre: leg(`q${i}`, `n${i}`, 0), gap: 0.01 });
  const a = gateVerdict(pairedStats(tight));
  const b = gateVerdict(pairedStats(loose));
  const c = gateVerdict(pairedStats([]));
  console.log(`  self-test tight: n=${a.n} 2SE=${a.twoSe.toFixed(2)} -> ${a.verdict}`);
  console.log(`  self-test loose: n=${b.n} 2SE=${b.twoSe.toFixed(2)} -> ${b.verdict}`);
  console.log(`  self-test empty: n=${c.n} -> ${c.verdict}`);
  if (a.verdict !== "RESOLVABLE" || b.verdict !== "UNRESOLVABLE-BY-PRECISION" || c.verdict !== "VANISHED-BY-N") {
    console.error("FAIL: the gate cannot separate RESOLVABLE / UNRESOLVABLE-BY-PRECISION / VANISHED-BY-N");
    process.exit(1);
  }
  // Concentration must also be able to go RED: one pair carrying everything has top-10 share > 1.
  const spike: LegPair[] = [];
  for (let i = 0; i < 20; i++)
    spike.push({ basis: "class", post: leg(`s${i}`, `mm${i}`, i === 0 ? 100 : 0), pre: leg(`t${i}`, `nn${i}`, 0), gap: 0 });
  const conc = diffConcentration(spike);
  console.log(`  self-test spike: mean ${usd(conc.sum / 20)} median ${usd(conc.median)} top-10 share ${(100 * conc.topShare).toFixed(0)}%`);
  if (!(conc.topShare > 0.9 && conc.median === 0)) {
    console.error("FAIL: concentration cannot see a single pair carrying the whole sum");
    process.exit(1);
  }
  console.log("  PASS: gate separates all three verdicts and the concentration block can go RED");
}

async function main() {
  if (process.argv.includes("--self-test")) await selfTest();

  const rows = await loadRows();
  const legs = rows.map(toLeg);
  const v65 = legs.filter((l) => l.ruleSetVersion === 65);
  const post = legs.filter((l) => (l.ruleSetVersion ?? 0) >= 65);
  const preAll = legs.filter((l) => (l.ruleSetVersion ?? 0) < 65);
  const preNear = legs.filter(
    (l) => (l.ruleSetVersion ?? 0) >= CONTEMPORANEOUS_FLOOR && (l.ruleSetVersion ?? 0) < 65
  );

  console.log(`\nv65 PAIRED READ — card v65-paired-read-instrument (read-only, nothing applied)`);
  console.log(`  v65 epoch ${EPOCH}; clock = settlement COALESCE(closedAt,resolvedAt) UTC; isDemo=0; level=leg`);
  console.log(`  PnL net of BOTH legs' fees (p*(1-p)*rate via training-export's feeDecomposition)`);
  console.log(`  gate (pre-registered 2026-10-22): 2SE <= $${V65_GATE.maxTwoSe} per leg pair at n >= ${V65_GATE.minPairs} pairs\n`);

  console.log(`POPULATION (settled legs)`);
  for (const c of census(preAll)) console.log(`  pre-v65 all eras  ${JSON.stringify(c)}`);
  for (const c of census(v65)) console.log(`  v65 era           ${JSON.stringify(c)}`);
  for (const c of census(post)) console.log(`  post-v65 v>=65    ${JSON.stringify(c)}`);

  console.log(`\nPAIRS`);
  const reads: Array<ReturnType<typeof reportPairs>> = [];
  const arms: Array<[string, PairedLeg[], PairedLeg[]]> = [
    ["v65 era | pre all", v65, preAll],
    ["v65 era | pre v60-64", v65, preNear],
    ["post-v65 | pre v60-64", post, preNear],
  ];
  for (const [label, postArm, preArm] of arms) {
    for (const lane of Array.from(new Set(postArm.map((l) => l.lane))).sort()) {
      const p = postArm.filter((l) => l.lane === lane);
      const q = preArm.filter((l) => l.lane === lane);
      reads.push(reportPairs(`${label} ${lane} exact`, exactMates(p, q)));
      reads.push(reportPairs(`${label} ${lane} class`, classPairs(p, q), true));
    }
  }

  // The decisive question for a paired read: on the era being read, is there any TREATED leg at all?
  const flat = (xs: PairedLeg[]) => xs.filter((l) => Math.abs(l.sizeUsd - 18) < 1e-6).length;
  const nearStd = preNear.filter((l) => l.lane === "STANDARD");
  const eraStd = v65.filter((l) => l.lane === "STANDARD");
  const eraC200 = v65.filter((l) => l.lane === "BANKROLL_200");
  console.log(`\nTREATMENT (what v65 could move at all)`);
  console.log(
    `  STANDARD legs on the flat $18 path: v60-64 ${flat(nearStd)}/${nearStd.length}, v65 era ${flat(eraStd)}/${eraStd.length}`
  );
  console.log(`  C-200 legs in the v65 era: ${eraC200.length} (kellySizeForCopy takes no wallet score — C-200 never read the flag)`);

  const eraExact = gateVerdict(pairedStats(exactMates(v65, preAll)));
  const eraClass = gateVerdict(pairedStats(classPairs(v65, preNear)));
  const wideStd = gateVerdict(pairedStats(classPairs(post.filter((l) => l.lane === "STANDARD"), preNear.filter((l) => l.lane === "STANDARD"))));
  const wideC200 = gateVerdict(pairedStats(classPairs(post.filter((l) => l.lane === "BANKROLL_200"), preNear.filter((l) => l.lane === "BANKROLL_200"))));

  console.log(`\nVERDICT (position of the reader, computed, not asserted)`);
  console.log(`  v65-era exact pairing: n=${eraExact.n} -> ${eraExact.verdict}`);
  console.log(`  v65-era class pairing: n=${eraClass.n} -> ${eraClass.verdict}`);
  console.log(
    `  STANDARD widened class read: n=${wideStd.n} -> ${wideStd.verdict}` +
      ` (2SE $${wideStd.twoSe.toFixed(2)}, needs sd <= $${wideStd.requiredSd.toFixed(2)} at n=70)`
  );
  console.log(
    `  C-200 widened class read: n=${wideC200.n} -> ${wideC200.verdict}` +
      ` (2SE $${wideC200.twoSe.toFixed(2)}, at that sd 2SE<=$10 needs ${wideC200.requiredPairs} pairs)`
  );

  const artifact = {
    card: "v65-paired-read-instrument",
    generatedAt: new Date().toISOString(),
    epoch: EPOCH,
    basis: {
      population: "PaperTrade isDemo=0, status closed|resolved, settlement clock not null, journal ruleSetVersion",
      clock: "settled = COALESCE(closedAt, resolvedAt) UTC",
      level: "leg; one pair = one post leg + one pre leg",
      fee: "feeDecomposition + netTargets: p*(1-p)*rate on entry, plus exit fee on early exits; proxy rate from MarketSnapshot.question",
      pairing: "exact = lane+market+outcome; class = lane+price band, nearest entry price within $0.10, 1:1 no replacement",
    },
    gate: V65_GATE,
    population: { preAll: census(preAll), preNear: census(preNear), v65: census(v65), post: census(post) },
    treatment: {
      standardFlatPath: { preNear: `${flat(nearStd)}/${nearStd.length}`, v65: `${flat(eraStd)}/${eraStd.length}` },
      c200V65Legs: eraC200.length,
    },
    reads,
    verdict: { eraExact, eraClass, widenedStandard: wideStd, widenedC200: wideC200 },
  };
  fs.writeFileSync(OUT, JSON.stringify(artifact, null, 2) + "\n");
  console.log(`\nwrote ${OUT}`);
}

main()
  .catch((e) => {
    console.error(e);
    process.exit(1);
  })
  .finally(() => prisma.$disconnect());
