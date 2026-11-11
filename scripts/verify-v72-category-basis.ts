/**
 * verify:v72 — prove the wallet category basis swap on REAL wallet samples (read-only).
 *
 * For a handful of wallets that hold a settled leg it runs the SAME adapter call the scanner runs
 * (fetchWalletActivity, 30d) and scores the sample twice — token basis (legacy) and class basis
 * (v72) — then prints what actually moves: bucket keys, bucket density, bestCategory, and the
 * per-observation win rate that categoryFitScore would receive for one stored ObservedTrade row.
 *
 * Writes nothing. Exit code is non-zero only on a real inconsistency (payload round-trip loss, a
 * class-keyed map reading a token, or a live rule value outside the closed vocabulary).
 *
 * Usage:
 *   npx tsx scripts/verify-v72-category-basis.ts            # live ruleset, 5 wallets
 *   npx tsx scripts/verify-v72-category-basis.ts --limit 12
 */
import { prisma } from "../src/lib/db";
import { getAdapter } from "../src/lib/adapters";
import { getActiveRules, DEFAULT_RULES } from "../src/lib/rules";
import {
  scoreWallet,
  encodeCategoryStrengths,
  decodeCategoryStrengths,
  categoryWinRateFor,
} from "../src/lib/scoring/wallet";

const LIMIT = (() => {
  const i = process.argv.indexOf("--limit");
  const n = i >= 0 ? Number(process.argv[i + 1]) : NaN;
  return Number.isFinite(n) && n > 0 ? n : 5;
})();

function pct(n: number, d: number): string {
  return d > 0 ? `${((n / d) * 100).toFixed(1)}%` : "n/a";
}

async function main() {
  const adapter = getAdapter();
  const { rules, version } = await getActiveRules();
  console.log(
    `active ruleset v${version}: walletCategoryBasis = ${rules.walletCategoryBasis} | ` +
      `DEFAULT (shipped) = ${DEFAULT_RULES.walletCategoryBasis}`
  );
  if (rules.walletCategoryBasis !== "token" && rules.walletCategoryBasis !== "class") {
    throw new Error(`walletCategoryBasis is outside the closed vocabulary: ${rules.walletCategoryBasis}`);
  }

  // Wallets that actually hold a settled leg — the population the feature is read on.
  const legWallets = await prisma.paperTrade.findMany({
    where: { isDemo: false, status: { in: ["closed", "resolved"] }, realizedPnl: { not: null } },
    select: { walletAddress: true },
    distinct: ["walletAddress"],
    take: LIMIT,
    orderBy: { openedAt: "desc" },
  });
  const addresses = legWallets.map((w) => w.walletAddress);
  if (addresses.length === 0) {
    console.log("no wallet holds a settled leg — nothing to verify");
    return;
  }

  let roundTripFailures = 0;
  let legacyBadKeyReads = 0;
  let classKeyedTrades = 0;
  let totalTrades = 0;
  let storedClassKeyed = 0;

  for (const address of addresses) {
    const trades = await adapter.fetchWalletActivity(address, 30);
    const tokenScore = scoreWallet(trades, { ...rules, walletCategoryBasis: "token" });
    const classScore = scoreWallet(trades, { ...rules, walletCategoryBasis: "class" });
    const live = rules.walletCategoryBasis === "class" ? classScore : tokenScore;

    totalTrades += trades.length;
    classKeyedTrades += trades.filter((t) => (t.marketCategoryClass ?? "").length > 0).length;

    // Round-trip: what the scanner stores must decode back to the same map and basis.
    const encoded = encodeCategoryStrengths(live);
    const decoded = decodeCategoryStrengths(encoded);
    if (decoded.basis !== live.categoryBasis || JSON.stringify(decoded.strengths) !== JSON.stringify(live.categoryStrengths)) {
      roundTripFailures++;
    }

    console.log("");
    console.log(`wallet ${address}`);
    console.log(`  sample: ${trades.length} trades, ${pct(trades.filter((t) => (t.marketCategoryClass ?? "").length > 0).length, trades.length)} carry a class`);
    console.log(
      `  token basis: ${Object.keys(tokenScore.categoryStrengths).length} buckets | bestCategory ${tokenScore.bestCategory ?? "—"}`
    );
    console.log(
      `  class basis: ${Object.keys(classScore.categoryStrengths).length} buckets | bestCategory ${classScore.bestCategory ?? "—"} | ` +
        `uncategorized ${classScore.categoryStrengths.uncategorized?.trades ?? 0} trade(s)`
    );
    console.log(`  LIVE (v${version}): keyed on ${live.categoryBasis}`);

    // The live lookup must read the field that belongs to its own basis. One stored row of this
    // wallet is the witness: under the class basis it can only answer if the row carries a class.
    const row = await prisma.observedTrade.findFirst({
      where: { walletAddress: address },
      orderBy: { timestamp: "desc" },
      select: { marketCategory: true, marketCategoryClass: true, marketId: true },
    });
    if (row) {
      const payload = decoded;
      const wr = categoryWinRateFor(payload, row);
      console.log(
        `  lookup on ${row.marketId}: token=${row.marketCategory ?? "—"} class=${row.marketCategoryClass ?? "—"} -> ` +
          `winRate ${wr === undefined ? "undefined (neutral 50)" : wr.toFixed(3)}`
      );
      // A class-keyed payload must never answer from the token field.
      if (payload.basis === "class" && !row.marketCategoryClass && wr !== undefined) legacyBadKeyReads++;
    }

    // The PRODUCTION read path: score-trades reads the STORED payload off WalletProfile, not a
    // fresh fetch. Prove the same resolution works on what the hourly scan actually wrote.
    const profile = await prisma.walletProfile.findUnique({
      where: { address },
      select: { categoryStrengthsJson: true, bestCategory: true, lastScannedAt: true },
    });
    const stored = decodeCategoryStrengths(profile?.categoryStrengthsJson);
    const storedRow = row ?? null;
    const storedWr = storedRow ? categoryWinRateFor(stored, storedRow) : undefined;
    console.log(
      `  STORED (scanned ${profile?.lastScannedAt?.toISOString() ?? "never"}): basis ${stored.basis}, ` +
        `bestCategory ${profile?.bestCategory ?? "—"}, ` +
        `lookup -> ${storedWr === undefined ? "undefined (neutral 50)" : storedWr.toFixed(3)}`
    );
    if (stored.basis === "class") storedClassKeyed++;
  }

  console.log("");
  console.log(
    `class coverage across the sample: ${pct(classKeyedTrades, totalTrades)} of ${totalTrades} trades | ` +
      `round-trip failures ${roundTripFailures} | class map read from a token ${legacyBadKeyReads}`
  );
  console.log(
    `stored payloads: ${storedClassKeyed}/${addresses.length} class-keyed (the rest are legacy token rows ` +
      `the hourly rotation has not re-scored yet — both read correctly)`
  );
  if (roundTripFailures > 0 || legacyBadKeyReads > 0) {
    throw new Error("v72 verification FAILED");
  }
  console.log("verify:v72 OK");
}

main()
  .catch((e) => {
    console.log(`FAILED: ${e instanceof Error ? e.message : e}`);
    process.exit(1);
  })
  .finally(() => prisma.$disconnect());
