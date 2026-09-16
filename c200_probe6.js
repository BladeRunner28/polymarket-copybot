const { PrismaClient } = require('@prisma/client');
const p = new PrismaClient();
(async()=>{
  for (const d of [1,7,14,30]) {
    const since = new Date(Date.now()-d*86400000);
    const r = await p.paperTrade.aggregate({ where:{ botId:'BANKROLL_200', status:{in:['closed','resolved']}, OR:[{closedAt:{gte:since}},{resolvedAt:{gte:since}}] }, _sum:{ simulatedPositionSize:true, realizedPnl:true }, _count:true });
    console.log(`${d}d: n=${r._count} staked=$${r._sum.simulatedPositionSize.toFixed(0)} realized=$${r._sum.realizedPnl.toFixed(2)} roi=${(100*r._sum.realizedPnl/r._sum.simulatedPositionSize).toFixed(2)}%`);
  }
  const open = await p.paperTrade.findMany({ where:{ botId:'BANKROLL_200', status:'open' } });
  const cost = open.reduce((a,t)=>a+t.simulatedPositionSize,0);
  let mark=0; for (const t of open) { const shares = t.simulatedPositionSize/(t.entryPrice||1); mark += shares*t.currentPrice; }
  const b = await p.botBankroll.findUnique({where:{botId:'BANKROLL_200'}});
  console.log(`open n=${open.length} cost=$${cost.toFixed(2)} mark=$${mark.toFixed(2)} uPnL=$${(mark-cost).toFixed(2)}`);
  console.log(`cash=$${b.cashBalance.toFixed(2)} principal=$${b.principal} netWorth(cash+mark)=$${(b.cashBalance+mark).toFixed(2)} vs principal ${(100*(b.cashBalance+mark-b.principal)/b.principal).toFixed(1)}%`);
  const dd = JSON.parse(require('fs').readFileSync('data/c200-drawdown.json','utf8'));
  const nw = b.cashBalance+mark;
  console.log(`drawdown file peak=$${dd.peak.toFixed(2)} basis=${dd.basis} -> current DD = ${(100*(dd.peak-nw)/dd.peak).toFixed(2)}% (gate 20%)`);
  console.log(`realizedPeak=$${dd.realizedPeak} vs cumulative realized on bankroll row $${b.realizedPnl.toFixed(2)}`);
  // hold time
  const last14 = await p.paperTrade.findMany({ where:{ botId:'BANKROLL_200', status:{in:['closed','resolved']}, OR:[{closedAt:{gte:new Date(Date.now()-14*86400000)}},{resolvedAt:{gte:new Date(Date.now()-14*86400000)}}] }});
  const hrs = last14.map(t=>(((t.closedAt??t.resolvedAt).getTime()-t.openedAt.getTime())/3600000)).sort((a,b)=>a-b);
  console.log('14d hold h: p25', hrs[Math.floor(hrs.length*0.25)].toFixed(1), 'median', hrs[Math.floor(hrs.length/2)].toFixed(1), 'p75', hrs[Math.floor(hrs.length*0.75)].toFixed(1));
  const exits = {}; const res = {};
  for (const t of last14) { if (t.status==='closed') exits[t.realizedPnl>0?'win':'loss']=(exits[t.realizedPnl>0?'win':'loss']||0)+1; else res[t.realizedPnl>0?'win':'loss']=(res[t.realizedPnl>0?'win':'loss']||0)+1; }
  console.log('14d by exit type: closed(early)', JSON.stringify(exits), 'resolved(natural)', JSON.stringify(res));
  const pnlByType = await Promise.all(['closed','resolved'].map(async s => {
    const a = await p.paperTrade.aggregate({ where:{botId:'BANKROLL_200', status:s, OR:[{closedAt:{gte:new Date(Date.now()-14*86400000)}},{resolvedAt:{gte:new Date(Date.now()-14*86400000)}}]}, _sum:{realizedPnl:true, simulatedPositionSize:true}, _count:true });
    return `${s}: n=${a._count} pnl=$${a._sum.realizedPnl.toFixed(2)} staked=$${a._sum.simulatedPositionSize.toFixed(0)}`;
  }));
  console.log(pnlByType.join(' | '));
})().finally(()=>p.$disconnect());
