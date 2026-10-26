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
 * WHAT THIS PRINTS
 *  1. coverage, so no rate is quoted over a population that cannot carry it:
 *     legs with book evidence, tape evidence, neither (excluded from rates).
 *  2. booked vs fill-aware PnL, total and BY BAND, under BOTH credit models:
 *     `flat` (what was booked before 2026-10-10) and `live` (what books now).
 *  3. concentration: median leg and ex-top-10, so a single leg cannot be read
 *     as a lane edge.
 * Basis for every number: population = dispatched C-200 intents in the latest
 * print-through snapshot joined to their booked leg; clock = reach is judged
 * over our L2 coverage window after the dispatch (~1 h median, lag printed by
 * the instrument); level = intent − credit(mode), clamped at $0.01.
 *
 * CAVEAT THAT MUST TRAVEL: a best ask at/below the level is REACHABILITY, not a
 * fill — no queue position, no size. So `fill-aware` is an upper bound on what
 * the lane would own, and `booked` is what it claims to own today.
 *
 * READS ONLY. Writes no DB row, no RuleSet, no published figure. Channel the
 * booking change is a Lane A decision (card `c200-maker-fill-assumption`,
 * awaiting approval) — this script is the evidence it is decided on.
 *
 * Usage: npx tsx scripts/c200-fill-aware-pnl.ts [--artifact P] [--json]
 */
import fs from "fs";
import path from "path";
import { prisma } from "../src/lib/db";
import {
  type CreditMode,
  type FillAwareLeg,
  creditUsdFor,
  levelFor,
  renderFillAware,
  summariseFillAware,
  usd,
} from "../src/lib/c200-fill-resolution";

const ARTIFACT = path.join(process.cwd(), "data", "c200-printthrough.jsonl");

interface ArtifactLeg {
  intentId: string;
  intentPrice: number;
  sizeUsd?: number;
  status?: string;
  reached5?: boolean | null;
  reached60?: boolean | null;
  tapeSilent?: boolean;
  book?: { minAsk?: number | null } | null;
}

interface ArtifactRow {
  ranAt: number;
  legs: ArtifactLeg[];
  summary?: { legs?: number; bookAnalysable?: number; tapeAnalysable?: number };
}

/** The latest snapshot in the append-only artifact (last line wins). */
function readSnapshot(file: string): ArtifactRow | null {
  if (!fs.existsSync(file)) return null;
  let last: ArtifactRow | null = null;
  for (const line of fs.readFileSync(file, "utf8").split("\n")) {
    const t = line.trim();
    if (!t) continue;
    try {
      const o = JSON.parse(t) as ArtifactRow;
      if (Array.isArray(o.legs)) last = o;
    } catch {
      /* a torn line is not a snapshot */
    }
  }
  return last;
}

const REPRODUCE_SQL = `
-- population: dispatched C-200 intents in the print-through artifact joined to their leg
SELECT fi.id, fi.intentPrice, p.entryPrice, p.simulatedPositionSize, p.realizedPnl, p.status,
       p.openedAt
FROM FillIntent fi JOIN PaperTrade p ON p.id = fi.paperTradeId
WHERE p.botId = 'BANKROLL_200' AND p.isDemo = 0;
-- coverage counters (the >=50-leg gate's clause (b))
SELECT (SELECT COUNT(*) FROM FillIntent) AS intents,
       (SELECT COUNT(*) FROM FillIntent WHERE paperTradeId IS NULL) AS unlinked;
`.trim();

async function main() {
  const args = process.argv.slice(2);
  const json = args.includes("--json");
  const aIdx = args.indexOf("--artifact");
  const file = aIdx >= 0 ? path.resolve(args[aIdx + 1]) : ARTIFACT;

  const snap = readSnapshot(file);
  if (!snap) {
    console.error(`[c200-fill-aware] no snapshot in ${file} — run python3 scripts/c200-printthrough.py first`);
    process.exit(1);
  }

  const ids = snap.legs.map((l) => l.intentId).filter(Boolean);
  const q = ids.map(() => "?").join(",");
  const rows = await prisma.$queryRawUnsafe<
    Array<{
      id: string;
      pnl: number | null;
      sz: number | null;
      entry: number | null;
      status: string | null;
    }>
  >(
    `SELECT fi.id AS id, p.realizedPnl AS pnl, p.simulatedPositionSize AS sz,
            p.entryPrice AS entry, p.status AS status
     FROM FillIntent fi JOIN PaperTrade p ON p.id = fi.paperTradeId
     WHERE fi.id IN (${q})`,
    ...ids
  );
  const by = new Map(rows.map((r) => [r.id, r]));

  const legs: FillAwareLeg[] = [];
  let linked = 0;
  for (const l of snap.legs) {
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
    });
  }

  const withBook = legs.filter((l) => l.leg.bookMinAsk !== null).length;
  const withTape = legs.filter((l) => l.leg.tapeReached60 !== null).length;
  const settledN = legs.filter((l) => l.realizedPnl !== null).length;
  const ranAt = new Date(snap.ranAt).toISOString();

  const summaries = (["flat", "live"] as CreditMode[]).map((mode) => ({
    mode,
    summary: summariseFillAware(legs, mode),
  }));

  if (json) {
    console.log(
      JSON.stringify(
        {
          artifact: file,
          snapshotAt: ranAt,
          population: {
            artifactLegs: snap.legs.length,
            joinedLegs: linked,
            settledLegs: settledN,
            bookCovered: withBook,
            tapeCovered: withTape,
          },
          byMode: summaries,
        },
        null,
        2
      )
    );
  } else {
    console.log(
      `[c200-fill-aware] artifact ${path.relative(process.cwd(), file)} snapshot ${ranAt} · ` +
        `population: ${snap.legs.length} dispatched intents, ${linked} joined to a booked leg, ` +
        `${settledN} settled (PNL columns), book evidence ${withBook}, tape evidence ${withTape}`
    );
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
    console.log(
      "[c200-fill-aware] NOTHING APPLIED: the report still publishes booked figures. Booking fewer " +
        "legs changes capital allocation and every C-200 headline — Lane A, on the card awaiting approval."
    );
    console.log("[c200-fill-aware] reproduce SQL:");
    console.log(REPRODUCE_SQL);
  }
}

main()
  .then(() => prisma.$disconnect())
  .catch(async (e) => {
    console.error(e);
    await prisma.$disconnect();
    process.exit(1);
  });
