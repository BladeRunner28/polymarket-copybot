const { PrismaClient } = require('@prisma/client');
const p = new PrismaClient();
const R = n => Math.round(n * 100) / 100;
(async () => {
  for (const bot of ['BANKROLL_200', 'STANDARD']) {
    const open = await p.paperTrade.findMany({ where: { botId: bot, isDemo: false, status: 'open' } });
    const closed = await p.paperTrade.findMany({ where: { botId: bot, isDemo: false, status: 'closed' } });
    const res = await p.paperTrade.findMany({ where: { botId: bot, isDemo: false, status: 'resolved' } });
    const r = a => a.reduce((s, t) => s + (t.realizedPnl || 0), 0);
    const u = a => a.reduce((s, t) => s + (t.unrealizedPnl || 0), 0);
    const cost = a => a.reduce((s, t) => s + (t.simulatedPositionSize || 0), 0);
    console.log(`== ${bot}`);
    console.log(`  open ${open.length} legs / ${new Set(open.map(t => t.marketId)).size} markets / ${new Set(open.map(t => t.walletAddress)).size} wallets / cost $${R(cost(open))} / unreal $${R(u(open))}`);
    console.log(`  settled ${closed.length + res.length} (closed ${closed.length} $${R(r(closed))} | resolved ${res.length} $${R(r(res))}) realized lifetime $${R(r(closed) + r(res))}`);
    const byW = {};
    for (const t of open) byW[t.walletAddress] = (byW[t.walletAddress] || 0) + t.simulatedPositionSize;
    const sorted = Object.entries(byW).sort((a, b) => b[1] - a[1]);
    const tot = sorted.reduce((s, x) => s + x[1], 0);
    console.log(`  top wallet ${sorted[0][0].slice(0, 10)} $${R(sorted[0][1])} (${(100 * sorted[0][1] / tot).toFixed(1)}%) | top3 ${(100 * sorted.slice(0, 3).reduce((s, x) => s + x[1], 0) / tot).toFixed(1)}%`);
    const keys = {};
    for (const t of open) { const k = `${t.walletAddress}|${t.marketId}|${t.outcome}`; keys[k] = (keys[k] || 0) + 1; }
    const dup = Object.entries(keys).filter(([, c]) => c > 1);
    let extraRows = 0, extraCost = 0;
    for (const [k, c] of dup) { extraRows += c - 1; const g = open.filter(t => `${t.walletAddress}|${t.marketId}|${t.outcome}` === k); extraCost += g.slice(1).reduce((a, t) => a + t.simulatedPositionSize, 0); }
    console.log(`  duplicate keys ${dup.length} / extra rows ${extraRows} / extra cost $${R(extraCost)} (${(100 * extraCost / cost(open)).toFixed(1)}% of open cost)`);
  }
  const q = async (sql) => (await p.$queryRawUnsafe(sql)).map(o => Object.fromEntries(Object.entries(o).map(([k, v]) => [k, typeof v === 'bigint' ? Number(v) : v])));
  console.log('C-200 daily:', JSON.stringify(await q(`SELECT date((COALESCE(closedAt,resolvedAt)/1000)-18000,'unixepoch') d, COUNT(*) n, ROUND(SUM(realizedPnl),2) pnl FROM PaperTrade WHERE botId='BANKROLL_200' AND isDemo=0 AND status IN ('closed','resolved') GROUP BY d ORDER BY d DESC LIMIT 6`)));
  console.log('STANDARD daily:', JSON.stringify(await q(`SELECT date((COALESCE(closedAt,resolvedAt)/1000)-18000,'unixepoch') d, COUNT(*) n, ROUND(SUM(realizedPnl),2) pnl FROM PaperTrade WHERE botId='STANDARD' AND isDemo=0 AND status IN ('closed','resolved') GROUP BY d ORDER BY d DESC LIMIT 4`)));
  const since = new Date(Date.now() - 24 * 3600 * 1000);
  console.log('journal 24h:', JSON.stringify(await q(`SELECT decision, COUNT(*) n FROM DecisionJournal WHERE isDemo=0 AND createdAt > (strftime('%s','now')-86400)*1000 GROUP BY 1`)));
  console.log('ruleSetVersion 24h:', JSON.stringify(await q(`SELECT ruleSetVersion, COUNT(*) n FROM DecisionJournal WHERE isDemo=0 AND createdAt > (strftime('%s','now')-86400)*1000 GROUP BY 1 ORDER BY n DESC LIMIT 6`)));
  console.log('walletProfile:', JSON.stringify(await q(`SELECT status, COUNT(*) n FROM WalletProfile GROUP BY 1`)));
  console.log('counts:', JSON.stringify(await q(`SELECT (SELECT COUNT(*) FROM ObservedTrade) ot, (SELECT COUNT(*) FROM DecisionJournal) dj, (SELECT COUNT(*) FROM PaperTrade) pt, (SELECT COUNT(*) FROM MarketSnapshot) ms, (SELECT COUNT(*) FROM PnlSnapshot) ps, (SELECT COUNT(*) FROM OutcomeReview) orv`)));
  console.log('journal_mode:', JSON.stringify(await q('PRAGMA journal_mode')));
  const j = Date.now() - 24 * 3600 * 1000;
  console.log('C-200 opens 24h:', JSON.stringify(await q(`SELECT COUNT(*) n, ROUND(SUM(simulatedPositionSize),2) cost, ROUND(AVG(simulatedPositionSize),2) avg FROM PaperTrade WHERE botId='BANKROLL_200' AND isDemo=0 AND openedAt > (strftime('%s','now')-86400)*1000`)));
  console.log('STANDARD opens 24h:', JSON.stringify(await q(`SELECT COUNT(*) n, ROUND(SUM(simulatedPositionSize),2) cost FROM PaperTrade WHERE botId='STANDARD' AND isDemo=0 AND openedAt > (strftime('%s','now')-86400)*1000`)));
  console.log('obs 24h:', JSON.stringify(await q(`SELECT observationOnly, COUNT(*) n, COUNT(DISTINCT walletAddress) w FROM ObservedTrade WHERE createdAt > (strftime('%s','now')-86400)*1000 GROUP BY 1`)));
  await p.$disconnect();
})();
