/**
 * Name the positions behind the ML export's reconciliation drift (card
 * `export-reconciliation-localisable`, Lane B instrument repair).
 *
 * THE CARD'S OPEN FINDING: the manifest stores sums only, so a drift can be announced but not
 * located, and the card recorded localisation as impossible — "the pre-change currentPrice is not
 * stored anywhere". That is false for the fee legs: `data/decision-dataset.csv` is a PER-POSITION
 * snapshot (fee_rate / fee_entry_usd / fee_exit_usd / pnl_gross|net_entry|net_full per trade_id),
 * and the exit fee inverts to the exit mark the artifact was priced against. So drift can be
 * attributed to named positions right now — no re-baselining, no change to the manifest's shape,
 * and the frozen file is only ever read.
 *
 * BASIS, stated because a number is only as good as its basis: population = the positions of the
 * frozen artifact (3,516 rows, generated 2026-09-13); level = one PaperTrade; clock = the artifact's
 * own generated_at (the CSV is a snapshot, not a live date filter — that is what "frozen" means).
 *
 * Usage: npx tsx scripts/decision-dataset-drift-localise.ts [--top N] [--json <path>]
 * ROLLBACK: delete this script + src/lib/decision-dataset-drift.ts + tests/decision-dataset-drift.test.ts
 * + the npm alias. Nothing else reads them; the export path only gained a log line.
 */
import * as fs from "fs";
import { Prisma } from "@prisma/client";
import { prisma } from "../src/lib/db";
import { dedupeFirstPerPosition, feeDecomposition, netTargets } from "../src/lib/training-export";
import {
  localiseFrozenPositions,
  parseFrozenCsv,
  type CurrentPosition,
} from "../src/lib/decision-dataset-drift";

const FROZEN_CSV = "data/decision-dataset.csv";
const MANIFEST = "data/decision-dataset.manifest.json";

const num = (v: unknown): number | null =>
  v === null || v === undefined || v === "" ? null : Number(v);
const money = (v: number): string => `${v < 0 ? "-" : "+"}$${Math.abs(v).toFixed(4)}`;

/** Same reader as scripts/export-training-data.ts, kept local so the exporter's basis cannot move. */
function loadFeeRateTruth(path: string): Map<string, number> {
  const out = new Map<string, number>();
  if (!fs.existsSync(path)) return out;
  for (const line of fs.readFileSync(path, "utf8").split("\n")) {
    const t = line.trim();
    if (!t) continue;
    try {
      const o = JSON.parse(t) as { slug?: unknown; resolvedRate?: unknown; feeSchedule?: { rate?: unknown } };
      const rate = o.resolvedRate ?? o.feeSchedule?.rate;
      if (o.slug && typeof rate === "number" && Number.isFinite(rate)) out.set(String(o.slug), rate);
    } catch {
      /* skip a malformed line rather than failing the read */
    }
  }
  return out;
}

async function main() {
  const argv = process.argv.slice(2);
  const topFlag = argv.indexOf("--top");
  const topN = topFlag >= 0 && Number(argv[topFlag + 1]) >= 0 ? Number(argv[topFlag + 1]) : 10;
  const jsonAt = argv.includes("--json") ? argv[argv.indexOf("--json") + 1] : null;

  const manifest = JSON.parse(fs.readFileSync(MANIFEST, "utf8")) as {
    generated_at: string;
    pnl_gross: number;
    pnl_net_full: number;
  };
  const asOf = Date.parse(manifest.generated_at);
  const truth = loadFeeRateTruth("data/fee-schedules.jsonl");

  const { positions: frozen, unparsed } = parseFrozenCsv(fs.readFileSync(FROZEN_CSV, "utf8"));
  const frozenById = new Map(frozen.map((f) => [f.tradeId, f]));

  // The live book, priced through the export's OWN fee model — no second cost model anywhere.
  const raw = await prisma.$queryRaw<any[]>(Prisma.sql`
    SELECT pt.id AS paperTradeId, pt.marketId, pt.botId, pt.walletAddress, pt.outcome,
           pt.entryPrice, pt.currentPrice, pt.simulatedPositionSize AS sizeUsd,
           pt.realizedPnl, pt.status, COALESCE(pt.closedAt, pt.resolvedAt) AS terminalAt,
           t.marketQuestion
    FROM PaperTrade pt
    JOIN DecisionJournal d ON d.id = pt.decisionJournalId
    JOIN ObservedTrade t ON t.id = d.observedTradeId
    WHERE pt.status IN ('closed','resolved') AND pt.isDemo = 0
      AND pt.realizedPnl IS NOT NULL AND pt.entryPrice > 0 AND pt.entryPrice < 1
    ORDER BY pt.openedAt ASC
  `);

  const priceOf = (r: any): CurrentPosition => {
    const entry = Number(r.entryPrice);
    const sizeUsd = Number(r.sizeUsd ?? 10);
    const fees = feeDecomposition({
      entryPrice: entry,
      sizeUsd,
      feeText: `${r.marketQuestion ?? ""} ${r.marketId ?? ""}`,
      feeRateTruth: truth.get(String(r.marketId)) ?? null,
      status: String(r.status),
      currentPrice: num(r.currentPrice),
    });
    // Both sides of the diff are priced on the FROZEN artifact's own fee model (the keyword
    // proxy). The labelled decomposition is only consulted for the label, so a venue-rate row
    // can neither be dropped nor read as a fee-basis move.
    const proxyFees = feeDecomposition({
      entryPrice: entry,
      sizeUsd,
      feeText: `${r.marketQuestion ?? ""} ${r.marketId ?? ""}`,
      feeRateTruth: null,
      status: String(r.status),
      currentPrice: num(r.currentPrice),
    });
    const t = netTargets({ realizedPnl: Number(r.realizedPnl), fees: proxyFees });
    return {
      tradeId: String(r.paperTradeId),
      marketId: String(r.marketId),
      status: String(r.status),
      entryPrice: entry,
      sizeUsd,
      realizedPnl: Number(r.realizedPnl),
      feeRate: proxyFees.feeRate,
      feeRateSource: fees.feeRateSource,
      feeEntryUsd: proxyFees.feeEntryUsd,
      feeExitUsd: proxyFees.feeExitUsd,
      pnlNetEntry: t.pnlNetEntry,
      pnlNetFull: t.pnlNetFull,
    };
  };

  const currentById = new Map<string, CurrentPosition>();
  for (const r of raw) currentById.set(String(r.paperTradeId), priceOf(r));

  const loc = localiseFrozenPositions(frozen, (id) => currentById.get(id) ?? null, unparsed);

  // Reproduce the manifest-level check in the same run: the localisation is COMPLETE only if the
  // per-position sum equals the drift the exporter announces.
  const asOfDedup = dedupeFirstPerPosition(
    raw
      .map((r) => ({
        botId: String(r.botId),
        walletAddress: String(r.walletAddress),
        marketId: String(r.marketId),
        outcome: String(r.outcome),
        raw: r,
      }))
      .filter((x) => {
        const t = num(x.raw.terminalAt);
        return t !== null && t <= asOf;
      }),
  );
  // Every in-window position, priced on the proxy — the SAME scope the exporter's reconcile block
  // now uses, so the two can never disagree about what "drift" means.
  let g = 0, nf = 0, n = 0;
  for (const x of asOfDedup) {
    const p = currentById.get(String(x.raw.paperTradeId));
    if (!p) continue;
    n += 1;
    g += p.realizedPnl;
    nf += p.pnlNetFull;
  }
  const wantGross = manifest.pnl_gross;
  const wantNetFull = manifest.pnl_net_full;

  console.log("Drift localisation — frozen decision dataset vs the live book");
  console.log(
    `  basis: population = ${frozen.length} positions of ${FROZEN_CSV} (artifact generated ` +
      `${manifest.generated_at.slice(0, 10)}); level = one PaperTrade; read ${new Date().toISOString()}`,
  );
  console.log(
    `  coverage: joined ${loc.deltas.length}/${frozen.length} | missing from the DB ${loc.missing.length} | ` +
      `truth-labelled (compared on the proxy, not dropped) ${loc.truthLabelled} | rate-basis changed ${loc.rateChanged} | unparsed lines ${loc.unparsed}`,
  );
  console.log(
    `  moved positions: ${loc.summary.moved} (gross only ${loc.summary.byCause.gross}, ` +
      `fee only ${loc.summary.byCause.fee}, both ${loc.summary.byCause.both})`,
  );
  console.log(
    `  Σ delta over joined rows: gross ${money(loc.summary.sum.dGross)} | fee_entry ${money(loc.summary.sum.dFeeEntry)} | ` +
      `fee_exit ${money(loc.summary.sum.dFeeExit)} | net_entry ${money(loc.summary.sum.dNetEntry)} | ` +
      `net_full ${money(loc.summary.sum.dNetFull)}`,
  );
  console.log(
    `  manifest-level check, reproduced here: proxy scope ${n} positions; export side gross $${g.toFixed(4)} ` +
      `vs manifest $${wantGross.toFixed(4)} = Δ ${money(g - wantGross)} | net_full $${nf.toFixed(4)} ` +
      `vs $${wantNetFull.toFixed(4)} = Δ ${money(nf - wantNetFull)}`,
  );
  console.log(
    `  COMPLETE only if the per-position Σ equals the manifest-level Δ: gross ${money(loc.summary.sum.dGross)} ` +
      `vs ${money(g - wantGross)} | net_full ${money(loc.summary.sum.dNetFull)} vs ${money(nf - wantNetFull)}`,
  );
  console.log(
    `  concentration: the largest single position carries ${loc.summary.topSharePct.toFixed(1)}% of Σ|Δ net_full|`,
  );
  if (loc.moved.length > 0) {
    console.log(`  top ${Math.min(topN, loc.moved.length)} movers:`);
    for (const d of loc.moved.slice(0, topN)) {
      const marks =
        d.frozenExitMarks === null
          ? "no frozen exit mark (settled, not sold)"
          : `frozen exit mark ${d.frozenExitMarks.join("|")}`;
      console.log(
        `    ${d.tradeId} [${d.cause}] ${d.question.slice(0, 52)} | Δgross ${money(d.dGross)} ` +
          `Δfee_entry ${money(d.dFeeEntry)} Δfee_exit ${money(d.dFeeExit)} -> Δnet_full ${money(d.dNetFull)} | ${marks}`,
      );
    }
  }
  if (jsonAt) {
    fs.writeFileSync(
      jsonAt,
      JSON.stringify(
        {
          generated_at: new Date().toISOString(),
          basis: { frozen_csv: FROZEN_CSV, manifest_generated_at: manifest.generated_at, level: "position" },
          coverage: {
            frozen: frozen.length,
            joined: loc.deltas.length,
            missing: loc.missing,
            truth_labelled: loc.truthLabelled,
            rate_changed: loc.rateChanged,
            unparsed: loc.unparsed,
          },
          manifest_level: {
            proxy_positions: n,
            export_gross: g,
            export_net_full: nf,
            want_gross: wantGross,
            want_net_full: wantNetFull,
          },
          summary: loc.summary,
          moved: loc.moved.slice(0, 100),
        },
        null,
        2,
      ),
    );
    console.log(`  artifact: ${jsonAt}`);
  }
}

main()
  .catch((e) => {
    console.error(e);
    process.exitCode = 1;
  })
  .finally(() => prisma.$disconnect());
