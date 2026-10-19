/**
 * Sentiment features for the training population — the corpus→training bridge.
 *
 * WHY THIS EXISTS
 *   The live scorer computes a calibrated sentiment delta per decision
 *   (src/lib/rules.ts → copyScore += delta·sentimentScale) and then THROWS IT AWAY:
 *   DecisionJournal records only the adjective ("Regulatory sentiment aligns strongly"),
 *   never the number. The training export (scripts/export-training-data.ts) therefore has
 *   zero sentiment columns, so no model can ever learn from the signal — the operator's
 *   stated purpose for the sentiment lane.
 *
 * WHAT IT DOES
 *   Re-derives, per LABELLED trade, the sentiment aggregate that was knowable AT the
 *   decision instant (no look-ahead), using the production aggregation itself
 *   (aggregateSentimentForCategory with the new `asOf` door — the same code the gate
 *   judges), and writes a joinable feature file on trade_id.
 *
 *   Mirrors production exactly:
 *     yesPrice       = outcome === "NO" ? 1 - entryPrice : entryPrice
 *     delta_signed   = sideSign * outcomeSign * agg.delta      (sideSign: SELL=-1)
 *   and additionally the PRICE-FREE frame (prior = 0.5) so the feature is comparable
 *   across markets regardless of where the price sat — the one a model should use.
 *
 *   Read-only: writes one CSV, touches no table.
 *
 * Usage: npx tsx scripts/export-sentiment-features.ts [--out data/sentiment-features.csv]
 */
import * as fs from "fs";
import { prisma } from "../src/lib/db";
import { researchCategoryFor } from "../src/lib/research-categories";
import { aggregateSentimentForCategory } from "../src/lib/forecasting/sentiment";

type Raw = {
  trade_id: string;
  outcome: string;
  side: string;
  entry_price: number;
  opened_at: number | null;
  closed_at: number | null;
  resolved_at: number | null;
  question: string;
  category: string | null;
  rules_version: number | null;
};

const iso = (ms: number | null) => (ms ? new Date(ms).toISOString() : "");
const f = (v: number | null | undefined, d = 5) => (v === null || v === undefined ? "" : v.toFixed(d));

async function main() {
  const outArg = process.argv.indexOf("--out");
  const out = outArg > -1 ? process.argv[outArg + 1] : "data/sentiment-features.csv";

  const rows = await prisma.$queryRawUnsafe<Raw[]>(`
    SELECT pt.id AS trade_id, pt.outcome, pt.side, pt.entryPrice AS entry_price,
           pt.openedAt AS opened_at, pt.closedAt AS closed_at, pt.resolvedAt AS resolved_at,
           ot.marketQuestion AS question, ot.marketCategory AS category,
           dj.ruleSetVersion AS rules_version
    FROM PaperTrade pt
    JOIN DecisionJournal dj ON dj.id = pt.decisionJournalId
    JOIN ObservedTrade ot ON ot.id = dj.observedTradeId
    WHERE pt.closedAt IS NOT NULL OR pt.resolvedAt IS NOT NULL
    ORDER BY pt.openedAt ASC
  `);

  // No signal exists before this instant, so anything earlier is null by construction.
  const firstSignal = await prisma.regulatorySignal.findFirst({
    orderBy: { processedAt: "asc" },
    select: { processedAt: true },
  });
  const firstSignalMs = firstSignal?.processedAt?.getTime() ?? Number.POSITIVE_INFINITY;
  console.log(`labelled trades: ${rows.length}`);
  console.log(`first RegulatorySignal: ${firstSignal ? firstSignal.processedAt.toISOString() : "NONE"}`);

  const header = [
    "trade_id", "opened_at", "terminal_at", "category", "outcome", "side", "entry_price",
    "rules_version", "sentiment_n", "sentiment_clusters", "sentiment_prior", "sentiment_post",
    "sentiment_delta_yes", "sentiment_delta_signed", "sentiment_pts", "sentiment_delta_50",
    "has_sentiment",
  ];
  const lines = [header.join(",")];

  let covered = 0, noCat = 0, preSignal = 0, nullAgg = 0;
  let minD = Infinity, maxD = -Infinity, sumD = 0;
  const byMonth: Record<string, { n: number; cov: number }> = {};

  for (const r of rows) {
    const openedMs = r.opened_at ? Number(r.opened_at) : null;
    const month = openedMs ? new Date(openedMs).toISOString().slice(0, 7) : "unknown";
    byMonth[month] ??= { n: 0, cov: 0 };
    byMonth[month].n++;

    const cat = researchCategoryFor(r.question, r.category);
    let n = "", clusters = "", prior = "", post = "", dYes = "", dSigned = "", pts = "", d50 = "";
    let has = 0;

    if (!cat) {
      noCat++;
    } else if (openedMs === null || openedMs < firstSignalMs) {
      preSignal++;
    } else {
      const asOf = new Date(openedMs);
      const entry = Number(r.entry_price);
      const yesPrice = r.outcome === "NO" ? 1 - entry : entry;
      const agg = await aggregateSentimentForCategory(cat, yesPrice, { asOf });
      const agg50 = await aggregateSentimentForCategory(cat, 0.5, { asOf });
      if (!agg) {
        nullAgg++;
      } else {
        const sideSign = r.side === "SELL" ? -1 : 1;
        const outcomeSign = r.outcome === "NO" ? -1 : 1;
        const signed = sideSign * outcomeSign * agg.delta;
        n = String(agg.n);
        clusters = String(agg.clusterCount);
        prior = f(agg.prior, 4);
        post = f(agg.pAware, 4);
        dYes = f(agg.delta);
        dSigned = f(signed);
        pts = f(agg.delta * 100, 3);
        d50 = agg50 ? f(agg50.delta) : "";
        has = 1;
        covered++;
        byMonth[month].cov++;
        if (signed < minD) minD = signed;
        if (signed > maxD) maxD = signed;
        sumD += signed;
      }
    }

    lines.push([
      r.trade_id, iso(openedMs), iso(r.resolved_at ? Number(r.resolved_at) : r.closed_at ? Number(r.closed_at) : null),
      cat ?? "", r.outcome, r.side, String(r.entry_price), r.rules_version === null ? "" : String(r.rules_version),
      n, clusters, prior, post, dYes, dSigned, pts, d50, String(has),
    ].join(","));
  }

  fs.writeFileSync(out, lines.join("\n") + "\n");
  const pct = (x: number) => ((100 * x) / rows.length).toFixed(1);
  console.log(`\nwrote ${out} (${lines.length - 1} rows)`);
  console.log(`  with sentiment feature : ${covered} (${pct(covered)} %)`);
  console.log(`  no research category   : ${noCat} (${pct(noCat)} %)`);
  console.log(`  predates first signal  : ${preSignal} (${pct(preSignal)} %)`);
  console.log(`  category but agg null  : ${nullAgg} (${pct(nullAgg)} %)`);
  if (covered > 0) {
    console.log(`  delta_signed: min ${minD.toFixed(4)} · mean ${(sumD / covered).toFixed(4)} · max ${maxD.toFixed(4)}`);
  }
  console.log(`\ncoverage by month (opened):`);
  for (const m of Object.keys(byMonth).sort()) {
    const v = byMonth[m];
    console.log(`  ${m}  ${String(v.cov).padStart(5)} / ${String(v.n).padStart(5)}  (${((100 * v.cov) / v.n).toFixed(1)} %)`);
  }
}

main()
  .catch((e) => { console.error(e); process.exit(1); })
  .finally(async () => { await prisma.$disconnect(); });
