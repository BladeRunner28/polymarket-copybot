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
  // The take:50 cap used to be invisible: the log said "Scoring … for N tracked
  // wallets" where N was the CAPPED length, so a 60-wallet track pool would have
  // read as 50 and the 10 never examined would have left no trace. 25 today, so
  // no number changes now — the count is read so it cannot silently understate.
  const trackedTotal = await prisma.walletProfile.count({ where: { status: "track", isDemo: false } });
  if (tracked.length === 0) {
    log("No tracked wallets.");
    return;
  }

  log(`Scoring insider/anomaly for ${tracked.length} tracked wallets${tracked.length < trackedTotal ? ` (of ${trackedTotal} — the read takes the top ${tracked.length} by globalScore)` : ""}…`);
  const results = [];
  let skippedNoLegs = 0;
  let failed = 0;
  for (const w of tracked) {
    try {
      const r = await computeInsiderScore(w.address);
      // null = this wallet has ZERO settled paper legs, so there is nothing to
      // score. That used to vanish: the summary printed "16 scored, 0 flagged,
      // 0 watch" for 25 tracked wallets, and a reader cannot tell 9 were never
      // examined. A flag count over 16 of 25 is not a clean bill of health.
      if (!r) {
        skippedNoLegs++;
        continue;
      }
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
      failed++;
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
  log(
    `Insider scoring complete: ${results.length}/${trackedTotal} tracked scored` +
      `${skippedNoLegs ? ` · ${skippedNoLegs} UNSCORED (0 settled paper legs for that wallet — nothing to score)` : ""}` +
      `${failed ? ` · ${failed} FAILED (see errors above)` : ""}` +
      ` — ${flagged.length} flagged, ${watch.length} watch OF THE ${results.length} SCORED.` +
      ` Basis: n = OUR settled copies of the wallet (status closed|resolved, isDemo=0), not the wallet's own record;` +
      ` wr/brier read the market outcome where known, never the exit PnL.`
  );

  if (flagged.length > 0 || watch.length > 0) {
    const lines = [
      "🕵️ **Insider/Anomaly Wallet Scan**",
      `Scored ${results.length} of ${trackedTotal} tracked wallets (weighted 11-component score; pre-news timing, Brier, timing alpha…). Flags describe the scored set only.`,
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
