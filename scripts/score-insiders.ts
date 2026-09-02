/**
 * score:insiders — compute insider/anomaly scores for tracked wallets and
 * store them in WalletInsiderScore (v40, Homerun-audit feature). Measurement-
 * first: scores are stored + reported; gating copy selection is a later rule.
 */

import { prisma } from "../src/lib/db";
import { computeInsiderScore } from "../src/lib/insider";
import { log, logError } from "../src/lib/redact";
import { sendDiscord } from "../src/lib/discord";

async function main() {
  const tracked = await prisma.walletProfile.findMany({
    where: { status: "track", isDemo: false },
    orderBy: { globalScore: "desc" },
    take: 50,
  });
  if (tracked.length === 0) {
    log("No tracked wallets.");
    return;
  }

  log(`Scoring insider/anomaly for ${tracked.length} tracked wallets…`);
  const results = [];
  for (const w of tracked) {
    try {
      const r = await computeInsiderScore(w.address);
      if (!r) continue;
      await prisma.walletInsiderScore.upsert({
        where: { walletAddress: w.address },
        create: {
          walletAddress: w.address,
          score: r.score,
          flagged: r.flagged,
          watch: r.watch,
          nResolved: r.nResolved,
          componentsJson: JSON.stringify(r.components),
        },
        update: {
          score: r.score,
          flagged: r.flagged,
          watch: r.watch,
          nResolved: r.nResolved,
          componentsJson: JSON.stringify(r.components),
        },
      });
      results.push(r);
    } catch (e) {
      logError(`Insider scoring failed for ${w.address.slice(0, 10)}…: ${e instanceof Error ? e.message : e}`);
    }
  }

  const flagged = results.filter((r) => r.flagged);
  const watch = results.filter((r) => r.watch && !r.flagged);
  const sorted = [...results].sort((a, b) => b.score - a.score);

  for (const r of sorted.slice(0, 10)) {
    const c = r.components;
    log(
      `  ${r.walletAddress.slice(0, 10)}… score=${r.score.toFixed(3)}${r.flagged ? " 🚩FLAGGED" : r.watch ? " ⚠watch" : ""} ` +
        `(n=${r.nResolved}) wr=${c.winRate.toFixed(2)} timing=${c.timingAlpha.toFixed(2)} brier=${c.brier.toFixed(2)} ` +
        `preNews=${c.preNewsTiming.toFixed(2)} cluster=${c.clusterCorrelation.toFixed(2)}`
    );
  }
  log(`Insider scoring complete: ${results.length} scored, ${flagged.length} flagged, ${watch.length} watch.`);

  if (flagged.length > 0 || watch.length > 0) {
    const lines = [
      "🕵️ **Insider/Anomaly Wallet Scan**",
      `Scored ${results.length} tracked wallets (weighted 11-component score; pre-news timing, Brier, timing alpha…).`,
    ];
    for (const r of [...flagged, ...watch]) {
      lines.push(
        `${r.flagged ? "🚩" : "⚠️"} \`${r.walletAddress.slice(0, 6)}…${r.walletAddress.slice(-4)}\` ` +
          `score ${r.score.toFixed(2)} (${r.flagged ? "FLAGGED" : "watch"}, n=${r.nResolved})`
      );
    }
    await sendDiscord(lines.join("\n"));
  }
}

main()
  .catch((e) => {
    logError("score:insiders FAILED:", e);
    process.exit(1);
  })
  .finally(() => prisma.$disconnect());
