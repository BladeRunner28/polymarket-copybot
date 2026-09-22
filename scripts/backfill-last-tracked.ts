/**
 * backfill:last-tracked — one-shot seed of `WalletProfile.lastTrackedAt`, the
 * anchor of the v61 observation universe (tuning review #33 rec 1,
 * user-approved 2026-09-22).
 *
 * `lastTrackedAt` is maintained by scan:wallets from the moment it ships: every
 * scan that leaves a wallet at status='track' stamps it. The bootstrap is needed
 * because the wallets ALREADY demoted have no such stamp — without it the
 * observation set would only start filling as new demotions occur.
 *
 * Proxy used for the pre-v61 rows: MAX(ObservedTrade.createdAt), i.e. the last
 * time the monitor actually stored a fill for that wallet. The monitor only ever
 * fetched `status='track'` wallets over the last 24h, so that timestamp is the
 * last moment the wallet was demonstrably in the copy set.
 *
 * Read-only unless `--apply` is passed; idempotent (only touches NULL rows).
 *   npx tsx scripts/backfill-last-tracked.ts            # plan
 *   npx tsx scripts/backfill-last-tracked.ts --apply    # write
 */
import { prisma } from "../src/lib/db";
import { copyWalletSet, observeOnlyWallets, OBSERVE_LOOKBACK_DAYS } from "../src/lib/wallet-universe";

const APPLY = process.argv.includes("--apply");
const fmt = (ms: number | bigint) => new Date(Number(ms)).toISOString().slice(0, 19).replace("T", " ");

async function main() {
  const cutoff = Date.now() - OBSERVE_LOOKBACK_DAYS * 86_400_000;

  const trackedNull = await prisma.walletProfile.count({
    where: { status: "track", isDemo: false, lastTrackedAt: null },
  });

  const demoted = await prisma.$queryRaw<Array<{ address: string; lastSeen: number; n: number }>>`
    SELECT o.walletAddress AS address, MAX(o.createdAt) AS lastSeen, COUNT(*) AS n
    FROM ObservedTrade o
    JOIN WalletProfile w ON w.address = o.walletAddress
    WHERE w.status <> 'track' AND w.isDemo = 0 AND w.lastTrackedAt IS NULL
      AND o.createdAt >= ${cutoff}
    GROUP BY o.walletAddress
    ORDER BY lastSeen DESC`;

  console.log(`backfill:last-tracked — window ${OBSERVE_LOOKBACK_DAYS}d (cutoff ${fmt(cutoff)})`);
  console.log(`  currently status=track, lastTrackedAt NULL : ${trackedNull} (stamp = now)`);
  console.log(`  demoted with stored fills inside the window : ${demoted.length}`);
  for (const r of demoted.slice(0, 40)) {
    console.log(`    ${r.address}  lastStoredFill=${fmt(r.lastSeen)}  rows=${r.n}`);
  }
  if (demoted.length > 40) console.log(`    … ${demoted.length - 40} more`);

  if (!APPLY) {
    console.log("PLAN ONLY — pass --apply to write these stamps.");
    return;
  }

  const now = new Date();
  const t = await prisma.walletProfile.updateMany({
    where: { status: "track", isDemo: false, lastTrackedAt: null },
    data: { lastTrackedAt: now },
  });
  let d = 0;
  for (const r of demoted) {
    const res = await prisma.walletProfile.updateMany({
      where: { address: r.address, lastTrackedAt: null },
      data: { lastTrackedAt: new Date(Number(r.lastSeen)) },
    });
    d += res.count;
  }
  console.log(`Applied: ${t.count} tracked stamped now, ${d} demoted stamped with their last stored fill.`);

  const copy = await copyWalletSet(false);
  const observe = await observeOnlyWallets(false);
  console.log(`Copy set: ${copy.length} | observation set: ${observe.length}`);
  console.log(
    `Observation-only wallets: ${
      observe.map((w) => `${w.address.slice(0, 10)}@${w.lastTrackedAt?.toISOString().slice(0, 10)}`).join(", ") || "(none)"
    }`
  );
}

main()
  .catch((e) => {
    console.error("backfill:last-tracked FAILED:", e);
    process.exit(1);
  })
  .finally(() => prisma.$disconnect());
