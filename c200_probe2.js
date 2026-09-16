const { PrismaClient } = require('@prisma/client');
const p = new PrismaClient();
(async () => {
  const open = await p.paperTrade.findMany({ where: { botId:'BANKROLL_200', status:'open' } });
  const buckets = {};
  for (const t of open) {
    const b = t.currentPrice>=0.95?'>=0.95 (effectively won)': t.currentPrice>=0.8?'0.80-0.95': t.currentPrice>=0.6?'0.60-0.80': t.currentPrice>=0.4?'0.40-0.60': t.currentPrice>=0.2?'0.20-0.40': t.currentPrice>=0.05?'0.05-0.20':'<0.05 (effectively lost)';
    buckets[b] = buckets[b] || {n:0,cost:0,u:0};
    buckets[b].n++; buckets[b].cost += t.simulatedPositionSize||0; buckets[b].u += t.unrealizedPnl||0;
  }
  console.log('OPEN BOOK by mark price:');
  for (const [k,v] of Object.entries(buckets)) console.log(`  ${k.padEnd(24)} n=${v.n} cost=$${v.cost.toFixed(0)} uPnL=$${v.u.toFixed(0)}`);
  const top = [...open].sort((a,b)=>(b.unrealizedPnl||0)-(a.unrealizedPnl||0));
  console.log('\nTOP 6 uPnL:'); for (const t of top.slice(0,6)) console.log(`  +$${t.unrealizedPnl.toFixed(2)} cost=$${t.simulatedPositionSize.toFixed(0)} entry=${t.entryPrice} cur=${t.currentPrice} opened=${t.openedAt.toISOString().slice(0,10)} ${t.outcome}`);
  console.log('BOTTOM 4 uPnL:'); for (const t of top.slice(-4)) console.log(`  $${t.unrealizedPnl.toFixed(2)} cost=$${t.simulatedPositionSize.toFixed(0)} entry=${t.entryPrice} cur=${t.currentPrice} opened=${t.openedAt.toISOString().slice(0,10)}`);
  // age of open book
  const now = Date.now();
  const ages = open.map(t => (now - t.openedAt.getTime())/86400000);
  console.log('\nopen age days: min', Math.min(...ages).toFixed(1), 'median', ages.sort((a,b)=>a-b)[Math.floor(ages.length/2)].toFixed(1), 'max', Math.max(...ages).toFixed(1));
  const old = open.filter(t=>(now-t.openedAt.getTime())/86400000 > 14);
  console.log('open >14d:', old.length, 'uPnL $', old.reduce((a,t)=>a+(t.unrealizedPnl||0),0).toFixed(2));
  // realized per trade last 7d, by price band
  const since7 = new Date(Date.now()-7*86400000);
  const fin = await p.paperTrade.findMany({ where:{ botId:'BANKROLL_200', status:{in:['closed','resolved']}, OR:[{closedAt:{gte:since7}},{resolvedAt:{gte:since7}}] } });
  const band = (ep)=> ep<0.2?'<0.20':ep<0.4?'0.20-0.40':ep<0.6?'0.40-0.60':ep<0.8?'0.60-0.80':'>0.80';
  const agg = {};
  for (const t of fin) { const b=band(t.entryPrice); const a=agg[b]=agg[b]||{n:0,pnl:0,cost:0}; a.n++; a.pnl+=t.realizedPnl||0; a.cost+=t.simulatedPositionSize||0; }
  console.log('\nLAST 7D realized by entry band:');
  for (const [k,v] of Object.entries(agg)) console.log(`  ${k.padEnd(10)} n=${v.n} cost=$${v.cost.toFixed(0)} pnl=$${v.pnl.toFixed(2)} roi=${(100*v.pnl/v.cost).toFixed(1)}%`);
  const w7 = await p.paperTrade.aggregate({ where:{ botId:'BANKROLL_200', status:{in:['closed','resolved']}, OR:[{closedAt:{gte:since7}},{resolvedAt:{gte:since7}}] }, _sum:{realizedPnl:true}, _count:true });
  console.log('7d total realized:', w7._sum.realizedPnl.toFixed(2), 'n=', w7._count);
  const w14 = await p.paperTrade.aggregate({ where:{ botId:'BANKROLL_200', status:{in:['closed','resolved']}, OR:[{closedAt:{gte:new Date(Date.now()-14*86400000)}},{resolvedAt:{gte:new Date(Date.now()-14*86400000)}}] }, _sum:{realizedPnl:true}, _count:true });
  console.log('14d total realized:', w14._sum.realizedPnl.toFixed(2), 'n=', w14._count);
  console.log('bot updatedAt:', (await p.botBankroll.findUnique({where:{botId:'BANKROLL_200'}})).updatedAt.toISOString());
})().finally(()=>p.$disconnect());
