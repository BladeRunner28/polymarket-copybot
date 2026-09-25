const { PrismaClient } = require('@prisma/client');
const p = new PrismaClient();
(async () => {
  const q = async (sql) => (await p.$queryRawUnsafe(sql)).map(o => Object.fromEntries(Object.entries(o).map(([k, v]) => [k, typeof v === 'bigint' ? Number(v) : v])));
  console.log('C-200 open by wallet status:', JSON.stringify(await q(`SELECT COALESCE(w.status,'<none>') s, COUNT(*) legs, ROUND(SUM(t.simulatedPositionSize),2) cost, ROUND(SUM(t.unrealizedPnl),2) unreal FROM PaperTrade t LEFT JOIN WalletProfile w ON w.address=t.walletAddress WHERE t.botId='BANKROLL_200' AND t.isDemo=0 AND t.status='open' GROUP BY 1 ORDER BY cost DESC`)));
  console.log('C-200 open top wallets:', JSON.stringify(await q(`SELECT t.walletAddress, COALESCE(w.status,'none') s, COUNT(*) legs, ROUND(SUM(t.simulatedPositionSize),2) cost FROM PaperTrade t LEFT JOIN WalletProfile w ON w.address=t.walletAddress WHERE t.botId='BANKROLL_200' AND t.isDemo=0 AND t.status='open' GROUP BY 1,2 ORDER BY cost DESC LIMIT 5`)));
  console.log('C-200 legs opened 24h:', JSON.stringify(await q(`SELECT COUNT(*) n, ROUND(SUM(simulatedPositionSize),2) cost, ROUND(AVG(simulatedPositionSize),2) avg, ROUND(MIN(simulatedPositionSize),2) mn, ROUND(MAX(simulatedPositionSize),2) mx FROM PaperTrade WHERE botId='BANKROLL_200' AND isDemo=0 AND openedAt > (strftime('%s','now')-86400)*1000`)));
  console.log('C-200 legs opened 24h by size bucket:', JSON.stringify(await q(`SELECT CASE WHEN simulatedPositionSize < 2.5 THEN '<2.50' WHEN simulatedPositionSize < 10 THEN '2.5-10' WHEN simulatedPositionSize < 20 THEN '10-20' ELSE '>=20' END b, COUNT(*) n FROM PaperTrade WHERE botId='BANKROLL_200' AND isDemo=0 AND openedAt > (strftime('%s','now')-86400)*1000 GROUP BY 1`)));
  await p.$disconnect();
})();
