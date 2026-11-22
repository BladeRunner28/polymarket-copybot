/**
 * c200-fill-aware-pnl — READ-ONLY: the C-200 lane's PnL as BOOKED versus as a
 * resting bid would have OWNED it (roadmap card `c200-maker-fill-assumption`,
 * item 1 of `approved-work-queue-20261026`).
 *
 * WHAT WAS WRONG WITH THE PUBLISHED NUMBER
 * Every C-200 figure the report prints is a sum over BOOKED legs, and a leg is
 * booked for every dispatched intent at `entry = intent − credit`. That books
 * `p(fill) = 1`. The pre-registered print-through instrument (same population,
 * same clock) says the level was reachable on 18/339 legs within 5 min and
 * 65/339 within 1 h at the flat-2¢ rest, and better but still far from 1 at the
 * credit the sidecar books today. A leg that never filled is not a small loss —
 * it is not a position, so its notional was never at risk and its PnL is $0.
 *
 * 2026-11-22 (Lane B instrument repair, card `profit-c200-reachability-stamp`):
 * THE POPULATION IS THE UNION, NOT THE LAST TICK. The booth appends a snapshot
 * per run and each tick re-stamps only the legs it can reach — the tick of
 * 2026-11-22T14:40Z held FOUR legs. Reading the last line made this instrument
 * print `booked +$0.00, 0 settled` while 955 stamped intents sat underneath it;
 * the approved decision's own evidence base was unreadable. Same defect class as
 * `standard-fill-union-verdict` (an unfalsifiable probe). `--last-snapshot`
 * reproduces the old behaviour on purpose, so the repair is verifiable.
 *
 * WHAT THIS PRINTS
 *  1. the UNION census: snapshots, distinct intents, evidence coverage, and
 *     reach per arm (own book vs public tape) by clock window — this is the
 *     population the card's `>=200 stamped legs` gate is read on.
 *  2. booked vs fill-aware PnL, total and BY BAND, under BOTH credit models:
 *     `flat` (what was booked before 2026-10-10) and `live` (what books now).
 *  3. the maker-vs-taker delta per dollar of INTENDED copy with a
 *     market-clustered bootstrap CI (`marketClusteredDelta`).
 *  4. concentration: median leg and ex-top-10, so a single leg cannot be read
 *     as a lane edge.
 * Basis for every number: population = dispatched C-200 intents in the
 * print-through union, joined to their booked leg; clock = reach is judged over
 * our L2 coverage window after the dispatch; level = intent − credit(mode),
 * clamped at $0.01. The tape arm is always at the FLAT level (the artifact is
 * computed with a 2¢ delta) and is never pooled with the book arm.
 *
 * CAVEAT THAT MUST TRAVEL: a best ask at/below the level is REACHABILITY, not a
 * fill — no queue position, no size. So `fill-aware` is an upper bound on what
 * the lane would own, and `booked` is what it claims to own today.
 *
 * READS ONLY. Writes no DB row, no RuleSet, no published figure. The booking
 * change is a Lane A decision (card `c200-maker-fill-assumption`, awaiting
 * approval) — this script is the evidence it is decided on.
 *
 * Usage: npx tsx scripts/c200-fill-aware-pnl.ts [--artifact P] [--last-snapshot] [--json] [--md drafts/x.md]
 */
import fs from "fs";
import path from "path";
import readline from "readline";
import { prisma } from "../src/lib/db";
import {
  type ClusteredDelta,
  type CreditMode,
  type FillAwareLeg,
  StampUnionFolder,
  creditUsdFor,
  levelFor,
  marketClusteredDelta,
  pct,
  renderFillAware,
  summariseFillAware,
  usd,
} from "../src/lib/c200-fill-resolution";

const ARTIFACT = path.join(process.cwd(), "data", "c200-printthrough.jsonl");

/** The card's own unlock: `>=200 stamped C-200 legs` inside a 30-day clock. */
const GATE_LEGS = 200;
const DAY_MS = 86_400_000;
const CLOCKS: Array<{ label: string; ms: number }> = [
  { label: "7d", ms: 7 * DAY_MS },
  { label: "30d", ms: 30 * DAY_MS },
  { label: "90d", ms: 90 * DAY_MS },
  { label: "all", ms: Number.POSITIVE_INFINITY },
];

interface ArtifactLeg {
  intentId: string;
  intentPrice: number;
  dispatchedAt?: number;
  sizeUsd?: number;
  status?: string;
  reached5?: boolean | null;
  reached60?: boolean | null;
  tapeSilent?: boolean | null;
  marketId?: string;
  book?: { minAsk?: number | null; askAtLevel?: boolean | null } | null;
}

interface ArtifactRow {
  ranAt?: number;
  legs?: ArtifactLeg[];
}

interface CensusRow {
  window: string;
  legs: number;
  /** Legs carrying ANY evidence (book or tape) — the card's gate counts these. */
  stamped: number;
  bookEvidence: number;
  tapeEvidence: number;
  bookReach: number;
  tapeReach60: number;
}

/** Stream the append-only artifact once, folding it into a union. */
async function readUnion(file: string): Promise<{
  folder: StampUnionFolder<ArtifactLeg>;
  lastLegs: ArtifactLeg[] | null;
  lastRanAt: number | null;
  torn: number;
}> {
  const folder = new StampUnionFolder<ArtifactLeg>();
  let lastLegs: ArtifactLeg[] | null = null;
  let lastRanAt: number | null = null;
  let torn = 0;
  const rl = readline.createInterface({
    input: fs.createReadStream(file, { encoding: "utf8" }),
    crlfDelay: Infinity,
  });
  for await (const line of rl) {
    const t = line.trim();
    if (!t) continue;
    let o: ArtifactRow;
    try {
      o = JSON.parse(t) as ArtifactRow;
    } catch {
      torn++; // a torn line is not a snapshot
      continue;
    }
    if (!Array.isArray(o.legs)) continue;
    const ranAt = typeof o.ranAt === "number" && Number.isFinite(o.ranAt) ? o.ranAt : 0;
    folder.add({ ranAt, legs: o.legs });
    lastLegs = o.legs;
    lastRanAt = ranAt;
  }
  return { folder, lastLegs, lastRanAt, torn };
}

function census(legs: ArtifactLeg[], now: number, mode: CreditMode): CensusRow[] {
  return CLOCKS.map((c) => {
    const sel = legs.filter(
      (l) =>
        typeof l.dispatchedAt === "number" &&
        Number.isFinite(l.dispatchedAt) &&
        now - l.dispatchedAt <= c.ms
    );
    let stamped = 0;
    let bookEvidence = 0;
    let tapeEvidence = 0;
    let bookReach = 0;
    let tapeReach60 = 0;
    for (const l of sel) {
      const minAsk = l.book && typeof l.book.minAsk === "number" ? l.book.minAsk : null;
      const tapeOk = !l.tapeSilent && typeof l.reached60 === "boolean";
      if (minAsk !== null) {
        bookEvidence++;
        if (minAsk <= levelFor(l.intentPrice, mode) + 1e-9) bookReach++;
      }
      if (tapeOk) {
        tapeEvidence++;
        if (l.reached60) tapeReach60++;
      }
      // ANY evidence, counted once — the arms overlap and must never be summed.
      if (minAsk !== null || tapeOk) stamped++;
    }
    return { window: c.label, legs: sel.length, stamped, bookEvidence, tapeEvidence, bookReach, tapeReach60 };
  });
}

interface DbRow {
  id: string;
  pnl: number | null;
  sz: number | null;
  entry: number | null;
  status: string | null;
  marketId: string | null;
}

const SQL_COLUMNS = `SELECT fi.id AS id, p.realizedPnl AS pnl, p.simulatedPositionSize AS sz,
            p.entryPrice AS entry, p.status AS status, p.marketId AS marketId
     FROM FillIntent fi JOIN PaperTrade p ON p.id = fi.paperTradeId`;

async function main() {
  const args = process.argv.slice(2);
  const json = args.includes("--json");
  const legacy = args.includes("--last-snapshot");
  const aIdx = args.indexOf("--artifact");
  const file = aIdx >= 0 ? path.resolve(args[aIdx + 1]) : ARTIFACT;
  const mIdx = args.indexOf("--md");
  const mdPath = mIdx >= 0 ? path.resolve(args[mIdx + 1]) : null;

  if (!fs.existsSync(file)) {
    console.error(`[c200-fill-aware] no artifact at ${file} — run python3 scripts/c200-printthrough.py first`);
    process.exit(1);
  }
  const { folder, lastLegs, lastRanAt, torn } = await readUnion(file);
  const union = folder.result();
  const snapLegs = legacy ? lastLegs : union.legs;
  if (!snapLegs || snapLegs.length === 0) {
    console.error(`[c200-fill-aware] no stamped legs in ${file}`);
    process.exit(1);
  }

  const ids = snapLegs.map((l) => l.intentId).filter((x): x is string => typeof x === "string" && !!x);
  const by = new Map<string, DbRow>();
  const CHUNK = 400;
  for (let i = 0; i < ids.length; i += CHUNK) {
    const part = ids.slice(i, i + CHUNK);
    const q = part.map(() => "?").join(",");
    const rows = await prisma.$queryRawUnsafe<DbRow[]>(`${SQL_COLUMNS} WHERE fi.id IN (${q})`, ...part);
    for (const r of rows) by.set(r.id, r);
  }

  const legs: FillAwareLeg[] = [];
  let linked = 0;
  for (const l of snapLegs) {
    const r = by.get(l.intentId);
    if (!r || !r.entry) continue;
    linked++;
    const settled = (r.status === "closed" || r.status === "resolved") && r.pnl !== null;
    legs.push({
      leg: {
        intentPrice: l.intentPrice,
        bookMinAsk:
          l.book && typeof l.book.minAsk === "number" && Number.isFinite(l.book.minAsk)
            ? l.book.minAsk
            : null,
        tapeReached5: l.tapeSilent ? null : (l.reached5 ?? null),
        tapeReached60: l.tapeSilent ? null : (l.reached60 ?? null),
      },
      realizedPnl: settled ? Number(r.pnl) : null,
      sizeUsd: Number(r.sz ?? l.sizeUsd ?? 0),
      marketId: r.marketId ?? l.marketId ?? undefined,
    });
  }

  const now = Date.now();
  const withBook = legs.filter((l) => l.leg.bookMinAsk !== null).length;
  const withTape = legs.filter((l) => l.leg.tapeReached60 !== null).length;
  const settledN = legs.filter((l) => l.realizedPnl !== null).length;
  const rows = census(snapLegs, now, "live");
  const win30 = rows.find((r) => r.window === "30d");
  const gateMet = !!win30 && win30.stamped >= GATE_LEGS;
  const ranAt = lastRanAt === null ? "n/a" : new Date(lastRanAt).toISOString();
  const firstAt = union.firstRanAt === null ? "n/a" : new Date(union.firstRanAt).toISOString();

  const summaries = (["flat", "live"] as CreditMode[]).map((mode) => ({
    mode,
    summary: summariseFillAware(legs, mode),
  }));
  const clustered: ClusteredDelta[] = (["flat", "live"] as CreditMode[]).map((mode) =>
    marketClusteredDelta(legs, mode)
  );

  const head: string[] = [];
  head.push(
    `[c200-fill-aware] artifact ${path.relative(process.cwd(), file)} · ${union.rows} snapshots ` +
      `(${union.rowsWithLegs} carrying legs${torn ? `, ${torn} torn lines skipped` : ""}) · ` +
      `ranAt ${firstAt} .. ${ranAt} · POPULATION = ${legacy ? "LAST SNAPSHOT (legacy)" : "UNION"}`
  );
  head.push(
    `[c200-fill-aware] union: ${union.distinctLegs} distinct intents · evidence rule newer-wins-except-absence ` +
      `(kept older evidence ${union.keptOldEvidence}, upgraded ${union.upgraded}, newer kept ${union.newerWins})`
  );
  head.push(
    `[c200-fill-aware] joined to a booked leg ${linked}/${snapLegs.length} · settled ${settledN} · ` +
      `book evidence ${withBook} · tape evidence ${withTape}`
  );
  head.push(`[c200-fill-aware] CENSUS (clock = dispatchedAt, now ${new Date(now).toISOString()}; level = intent − live credit)`);
  head.push("[c200-fill-aware]   window   legs  stamped  bookEvid  tapeEvid  bookReach  tapeReach@1h(flat)");
  for (const r of rows) {
    head.push(
      `[c200-fill-aware]   ${r.window.padEnd(6)}  ${String(r.legs).padStart(5)}  ${String(r.stamped).padStart(7)}  ${String(r.bookEvidence).padStart(8)}  ` +
        `${String(r.tapeEvidence).padStart(8)}  ${pct(r.bookEvidence ? (100 * r.bookReach) / r.bookEvidence : null).padStart(9)}  ` +
        `${pct(r.tapeEvidence ? (100 * r.tapeReach60) / r.tapeEvidence : null).padStart(18)}`
    );
  }
  head.push(
    `[c200-fill-aware] GATE (card profit-c200-reachability-stamp: >=${GATE_LEGS} stamped legs inside 30d) = ` +
      `${gateMet ? "MET" : "NOT MET"} — 30d stamped ${win30 ? win30.stamped : 0} of ${win30 ? win30.legs : 0} dispatched ` +
      `(book ${win30 ? win30.bookEvidence : 0}, tape ${win30 ? win30.tapeEvidence : 0}; overlapping arms, never summed)`
  );

  const deltaLines = clustered.map((c) => {
    const ci =
      c.ciLoPct === null || c.ciHiPct === null
        ? "CI n/a"
        : `95% CI [${c.ciLoPct.toFixed(1)}, ${c.ciHiPct.toFixed(1)}]pp`;
    return (
      `[c200-fill-aware] maker-vs-taker delta mode=${c.mode}: booked ${pct(c.bookedRoiPct)} vs fill-aware ` +
      `${pct(c.fillAwareRoiPct)} per $1 intended = ${c.deltaPct === null ? "n/a" : `${c.deltaPct.toFixed(1)}pp`} ` +
      `(${ci}; market-clustered bootstrap, ${c.settledMarkets} settled markets, ${c.reps} reps, seed ${c.seed})`
    );
  });

  if (json) {
    console.log(
      JSON.stringify(
        {
          artifact: file,
          population: legacy ? "last-snapshot" : "union",
          snapshotAt: ranAt,
          union: {
            snapshots: union.rows,
            rowsWithLegs: union.rowsWithLegs,
            distinctLegs: union.distinctLegs,
            keptOldEvidence: union.keptOldEvidence,
            upgraded: union.upgraded,
            newerWins: union.newerWins,
            torn,
          },
          census: rows,
          gate: { legs: GATE_LEGS, met: gateMet, window30d: win30 ?? null },
          joined: { artifactLegs: snapLegs.length, linkedLegs: linked, settledLegs: settledN, bookCovered: withBook, tapeCovered: withTape },
          byMode: summaries,
          clusteredDelta: clustered,
        },
        null,
        2
      )
    );
  } else {
    for (const l of head) console.log(l);
    console.log(
      `[c200-fill-aware] level = intent − credit(mode), clamped $0.01; flat credit ${(
        creditUsdFor(0.5, "flat") * 100
      ).toFixed(2)}c, live credit ${(creditUsdFor(0.5, "live") * 100).toFixed(2)}c at $0.50 ` +
        `(${(levelFor(0.5, "flat") * 100).toFixed(2)}c / ${(levelFor(0.5, "live") * 100).toFixed(2)}c)`
    );
    for (const { mode, summary } of summaries) {
      console.log("");
      for (const line of renderFillAware(
        summary,
        mode === "flat"
          ? "booked entry = intent − 2c: the model until 2026-10-10"
          : "booked entry = intent − 2c × measured reach share: what books now"
      ))
        console.log(line);
      const t = summary.total;
      console.log(
        `[c200-fill-aware]   concentration: median leg booked ${usd(
          t.medianBookedPnlUsd
        )} vs fill-aware ${usd(t.medianFillAwarePnlUsd)} · booked ex-top-10 ${usd(
          t.exTop10BookedUsd
        )} vs fill-aware ex-top-10 ${usd(t.exTop10FillAwareUsd)} (null = fewer than 11 legs)`
      );
    }
    console.log("");
    for (const l of deltaLines) console.log(l);
    console.log("");
    console.log(
      "[c200-fill-aware] NOTHING APPLIED: the report still publishes booked figures. Booking fewer " +
        "legs changes capital allocation and every C-200 headline — Lane A, on the card awaiting approval."
    );
    console.log("[c200-fill-aware] reproduce SQL:");
    console.log(`${SQL_COLUMNS}\nWHERE p.botId = 'BANKROLL_200' AND p.isDemo = 0;`);
  }

  if (mdPath) {
    const lines: string[] = [];
    lines.push(`# C-200 fill-aware booking — union read (${new Date(now).toISOString()})`);
    lines.push("");
    lines.push("Read-only instrument: `npx tsx scripts/c200-fill-aware-pnl.ts`. Nothing applied.");
    lines.push("");
    lines.push("```");
    for (const l of head) lines.push(l);
    for (const { mode, summary } of summaries) {
      lines.push("");
      for (const l of renderFillAware(summary, `mode=${mode}`)) lines.push(l);
    }
    lines.push("");
    for (const l of deltaLines) lines.push(l);
    lines.push("```");
    lines.push("");
    lines.push(
      "Attainable = REACHABILITY, not a fill: a best ask at/below the level ignores queue position and size."
    );
    fs.mkdirSync(path.dirname(mdPath), { recursive: true });
    fs.writeFileSync(mdPath, lines.join("\n") + "\n");
    console.log(`[c200-fill-aware] draft written ${path.relative(process.cwd(), mdPath)}`);
  }
}

main()
  .then(() => prisma.$disconnect())
  .catch(async (e) => {
    console.error(e);
    await prisma.$disconnect();
    process.exit(1);
  });
