const { PrismaClient } = require('@prisma/client');
const p = new PrismaClient();
function dayKey(d){return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`}
(async () => {
  const startOfDay = new Date(); startOfDay.setHours(0,0,0,0);
  const since28 = new Date(startOfDay.getTime() - 27*86400000);
  const fin = await p.paperTrade.findMany({
    where: { botId: 'BANKROLL_200', status: { in: ['closed','resolved'] },
      OR: [{closedAt:{gte:since28}},{resolvedAt:{gte:since28}}] },
  });
  const byDay = {};
  for (const t of fin) {
    const ts = t.closedAt ?? t.resolvedAt; if(!ts) continue;
    const k = dayKey(new Date(Number(ts)));
    byDay[k] = (byDay[k]||0) + (t.realizedPnl||0);
  }
  console.log('DAILY REALIZED last 21d:');
  for (let i=0;i<21;i++){ const d=new Date(startOfDay.getTime()-i*86400000); const k=dayKey(d); console.log(`  ${k}  ${(byDay[k]||0).toFixed(2)}  (n=${fin.filter(t=>dayKey(new Date(Number(t.closedAt??t.resolvedAt)))===k).length})`); }
  console.log('closed in 28d window:', fin.length, 'sum:', fin.reduce((a,t)=>a+(t.realizedPnl||0),0).toFixed(2));

  const open = await p.paperTrade.findMany({ where: { botId:'BANKROLL_200', status:'open' } });
  console.log('\nOPEN:', open.length, 'cost:', open.reduce((a,t)=>a+(t.simulatedPositionSize||0),0).toFixed(2), 'uPnL:', open.reduce((a,t)=>a+(t.unrealizedPnl||0),0).toFixed(2));
  for (const t of open) console.log(`  $${(t.simulatedPositionSize||0).toFixed(2)} cur=${t.currentPrice} conf=${t.confidence} uPnL=${(t.unrealizedPnl||0).toFixed(2)} venue=${t.venue} v=${t.ruleSetVersion} ${String(t.title).slice(0,50)}`);
  const byStatus = await p.paperTrade.groupBy({ by:['status'], where:{botId:'BANKROLL_200'}, _count:true, _sum:{realizedPnl:true, simulatedPositionSize:true} });
  console.log('\nby status:', JSON.stringify(byStatus));
  const rules = await p.ruleSet.findMany({ orderBy:{ version:'desc' }, take:4 });
  console.log('\nRULESETS:', rules.map(r=>`v${r.version} ${JSON.stringify(r).slice(0,200)}`).join('\n'));
})().finally(()=>p.$disconnect());
