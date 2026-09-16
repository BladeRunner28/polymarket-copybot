const { PrismaClient } = require('@prisma/client');
const p = new PrismaClient();
(async()=>{
  const open = await p.paperTrade.findMany({ where:{ botId:'BANKROLL_200', status:'open' } });
  const won = open.filter(t=>t.currentPrice>=0.95);
  console.log('effectively-won open:', won.length, 'cost', won.reduce((a,t)=>a+t.simulatedPositionSize,0).toFixed(0), 'uPnL', won.reduce((a,t)=>a+t.unrealizedPnl,0).toFixed(2));
  const ages = won.map(t=>(Date.now()-t.openedAt.getTime())/86400000);
  console.log('  age days min/max:', Math.min(...ages).toFixed(1), Math.max(...ages).toFixed(1));
  // sample market ids to look up resolution
  const mktIds = [...new Set(won.map(t=>t.marketId))];
  console.log('  distinct markets:', mktIds.length);
  const mk = await p.market.findMany({ where: { id: { in: mktIds } } }).catch(e=>{console.log('NO Market model', e.message.slice(0,80)); return []});
  if (mk.length) { for (const m of mk.slice(0,12)) console.log('  ', JSON.stringify({id:m.id.slice(0,20), slug:(m.slug||'').slice(0,40), endDate:m.endDate, closed:m.closed, resolved:m.resolved})); }
  // gross staked windows
  for (const d of [7,14,30]) {
    const since = new Date(Date.now()-d*86400000);
    const r = await p.paperTrade.aggregate({ where:{ botId:'BANKROLL_200', status:{in:['closed','resolved']}, OR:[{closedAt:{gte:since}},{resolvedAt:{gte:since}}] }, _sum:{ simulatedPositionSize:true, realizedPnl:true }, _count:true });
    console.log(`${d}d: n=${r._count} staked=$${r._sum.simulatedPositionSize.toFixed(0)} realized=$${r._sum.realizedPnl.toFixed(2)} roi=${(100*r._sum.realizedPnl/r._sum.simulatedPositionSize).toFixed(2)}%`);
  }
  const last14 = await p.paperTrade.findMany({ where:{ botId:'BANKROLL_200', status:{in:['closed','resolved']}, OR:[{closedAt:{gte:new Date(Date.now()-14*86400000)}},{resolvedAt:{gte:new Date(Date.now()-14*86400000)}}] }, select:{openedAt:true,closedAt:true,resolvedAt:true} });
  const hrs = last14.map(t=>(((t.closedAt??t.resolvedAt).getTime()-t.openedAt.getTime())/3600000)).sort((a,b)=>a-b);
  console.log('14d hold hours: median', hrs[Math.floor(hrs.length/2)].toFixed(1), 'p25', hrs[Math.floor(hrs.length*0.25)].toFixed(1), 'p75', hrs[Math.floor(hrs.length*0.75)].toFixed(1));
})().finally(()=>p.$disconnect());
