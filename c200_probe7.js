const { PrismaClient } = require('@prisma/client');
const p = new PrismaClient();
const V53 = new Date('2026-09-13T09:34:36Z');
(async()=>{
  const rows = await p.paperTrade.findMany({ where:{ botId:'BANKROLL_200', status:{in:['closed','resolved']} }});
  const after = rows.filter(t => (t.closedAt ?? t.resolvedAt) >= V53);
  const agg = (arr) => { const s=arr.reduce((a,t)=>a+t.simulatedPositionSize,0); const v=arr.reduce((a,t)=>a+(t.realizedPnl||0),0); return {n:arr.length, staked:s, pnl:+v.toFixed(2), roi:+(s?100*v/s:0).toFixed(2)}; };
  console.log('POST-v53 since 2026-09-13T09:34Z:', JSON.stringify(agg(after)));
  const e = after.filter(t=>t.status==='closed'), r = after.filter(t=>t.status==='resolved');
  console.log('  early exits:', JSON.stringify(agg(e)));
  console.log('  natural resolutions:', JSON.stringify(agg(r)));
  const hrs = after.map(t=>(((t.closedAt??t.resolvedAt).getTime()-t.openedAt.getTime())/3600000)).sort((a,b)=>a-b);
  if (hrs.length) console.log('  hold h p25/med/p75:', hrs[Math.floor(hrs.length*0.25)].toFixed(1), hrs[Math.floor(hrs.length/2)].toFixed(1), hrs[Math.floor(hrs.length*0.75)].toFixed(1));
  const mv = {};
  for (const t of e) { const m = (t.currentPrice - t.entryPrice)/t.entryPrice; const k = m<=-0.15?'<=-15pct': m<=-0.05?'-15..-5pct': m<0.05?'-5..+5pct': m<0.15?'+5..15pct':'>+15pct'; mv[k]=mv[k]||{n:0,pnl:0,staked:0}; mv[k].n++; mv[k].pnl+=(t.realizedPnl||0); mv[k].staked+=t.simulatedPositionSize; }
  console.log('  post-v53 early exits by move bucket:', JSON.stringify(mv));
  const band = (ep)=> ep<0.2?'0.00-0.20':ep<0.4?'0.20-0.40':ep<0.6?'0.40-0.60':ep<0.8?'0.60-0.80':'0.80-1.01';
  const all = {};
  for (const t of rows) { const b=band(t.entryPrice); all[b]=all[b]||{n:0,staked:0,pnl:0}; all[b].n++; all[b].staked+=t.simulatedPositionSize; all[b].pnl+=(t.realizedPnl||0); }
  console.log('ALL-TIME by entry band:'); for (const [k,v] of Object.entries(all)) console.log(`  ${k} n=${v.n} staked=$${v.staked.toFixed(0)} pnl=$${v.pnl.toFixed(2)} roi=${(100*v.pnl/v.staked).toFixed(2)}pct`);
  const s14 = Date.now()-14*86400000; const a14 = {};
  for (const t of rows) { const ts=t.closedAt??t.resolvedAt; if (ts.getTime()<s14) continue; const b=band(t.entryPrice); a14[b]=a14[b]||{n:0,staked:0,pnl:0}; a14[b].n++; a14[b].staked+=t.simulatedPositionSize; a14[b].pnl+=(t.realizedPnl||0); }
  console.log('14d by entry band:'); for (const [k,v] of Object.entries(a14)) console.log(`  ${k} n=${v.n} staked=$${v.staked.toFixed(0)} pnl=$${v.pnl.toFixed(2)} roi=${(100*v.pnl/v.staked).toFixed(2)}pct`);
  const open = await p.paperTrade.findMany({ where:{botId:'BANKROLL_200', status:'open'} });
  let mark=0; for (const t of open) mark += (t.simulatedPositionSize/(t.entryPrice||1))*t.currentPrice;
  const b = await p.botBankroll.findUnique({where:{botId:'BANKROLL_200'}});
  const nw = b.cashBalance + mark;
  const dd = JSON.parse(require('fs').readFileSync('data/c200-drawdown.json','utf8'));
  console.log(`\nnetWorth $${nw.toFixed(2)} = ${(100*(nw-b.principal)/b.principal).toFixed(1)}pct above principal; DD vs peak $${dd.peak.toFixed(2)} = ${(100*(dd.peak-nw)/dd.peak).toFixed(2)}pct (gate 20pct); trip level $${(dd.peak*0.8).toFixed(2)}, headroom $${(nw-dd.peak*0.8).toFixed(2)}`);
  console.log(`exposure cap = $1000 + 50pct*max(0,${nw.toFixed(0)}-1900) = $${(1000+0.5*Math.max(0,nw-1900)).toFixed(0)}; open cost $${open.reduce((a,t)=>a+t.simulatedPositionSize,0).toFixed(0)}`);
  console.log('now:', new Date().toISOString());
})().finally(()=>p.$disconnect());
