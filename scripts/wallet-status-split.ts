/**
 * wallet-status-split — READ-ONLY: the C-200 realized-PnL split by the wallet's
 * CURRENT status (tuning review #33 rec 2, user-approved 2026-09-22).
 *
 * Why it exists: the hourly wallet cap re-derives the top-25 every scan, so a
 * wallet can be `track` when it is copied and `watch` a day later. Any verdict
 * that says "the tracked wallets lose and the demoted ones win" is therefore a
 * statement about the CURRENT status of a frozen history — a hypothesis the
 * reviewer should price, not a rule change. Printing it in the EOD makes the
 * claim reproducible on the same day it is quoted.
 *
 * Writes nothing. The realized filter is the TR-15 OR form every daily-PnL
 * query needs (`closedAt IS NOT NULL OR resolvedAt IS NOT NULL` — an early exit
 * books realizedPnl at closedAt and leaves resolvedAt NULL).
 *
 * v62 (tuning review #34 rec 2, user-approved 2026-09-23): the line is an
 * AS-OF-PRINT SNAPSHOT, and says so. It joins WalletProfile.status LIVE, which
 * the hourly wallet cap re-derives, so the same SQL a few hours later returns a
 * different split — measured on the first two reads: track 207 −$432.55 | watch
 * 1,745 +$2,817.90 at the 22:00 EOD vs track 186 −$342.51 | watch 1,770
 * +$2,718.37 at 07:00 (21 legs / $90 reclassified). The EOD print is therefore
 * the immovable record (same convention as data/phase-streak-log.jsonl);
 * #33 rec 2's "equals a same-day re-run" clause is unachievable by construction
 * and is retired.
 *
 * Verify: `grep -c "by wallet status" logs/cron/copybot-eod.log` ≥ 7 (one line
 * per EOD run) and that the newest line carries the `as-of … status is live`
 * marker.
 */
import { prisma } from "../src/lib/db";

const SQL = `SELECT COALESCE(w.status, '<none>') AS wallet_status,
       COUNT(*) AS n,
       ROUND(SUM(p.realizedPnl), 2) AS pnl
FROM PaperTrade p
LEFT JOIN WalletProfile w ON w.address = p.walletAddress
WHERE p.botId = 'BANKROLL_200'
  AND p.isDemo = 0
  AND (p.closedAt IS NOT NULL OR p.resolvedAt IS NOT NULL)
GROUP BY 1
ORDER BY CASE wallet_status WHEN 'track' THEN 0 WHEN 'watch' THEN 1 WHEN 'ignore' THEN 2 ELSE 3 END`;

type Row = { wallet_status: string; n: number | bigint; pnl: number | null };

const money = (v: number) => `${v >= 0 ? "+" : "-"}$${Math.abs(v).toFixed(2)}`;

async function main() {
  const rows = await prisma.$queryRawUnsafe<Row[]>(SQL);
  const total = rows.reduce((s, r) => s + Number(r.pnl ?? 0), 0);
  const n = rows.reduce((s, r) => s + Number(r.n), 0);
  if (rows.length === 0) {
    console.log("C-200 realized by wallet status: no settled trades yet.");
    return;
  }
  const parts = rows.map((r) => `${r.wallet_status} ${money(Number(r.pnl ?? 0))} (${Number(r.n)})`);
  // v62 (tuning #34 rec 2): the marker is the point of the line — `status` is
  // re-derived hourly by the wallet cap, so this print is a snapshot, not a
  // value a later run can reproduce.
  const at = new Date();
  const hhmm = `${String(at.getHours()).padStart(2, "0")}:${String(at.getMinutes()).padStart(2, "0")}`;
  console.log(
    `C-200 realized by wallet status: ${parts.join(" | ")} | total ${money(total)} (${n}) ` +
      `(as-of ${hhmm} print — WalletProfile.status is live, a later re-run of this SQL can differ)`
  );
  console.log(
    `  reproduce: sqlite3 prisma/dev.db "${SQL.replace(/\s+/g, " ").trim()}"`
  );
}

main()
  .catch((e) => {
    console.error("wallet-status-split FAILED:", e);
    process.exit(1);
  })
  .finally(() => prisma.$disconnect());
