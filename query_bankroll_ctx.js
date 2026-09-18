const { PrismaClient } = require('@prisma/client');
const prisma = new PrismaClient();
function dayKey(d){return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`;}
async function main(){
  const startOfDay = new Date(); startOfDay.setHours(0,0,0,0);
  const since14 = new Date(startOfDay.getTime()-13*86400000);
  const fin = await prisma.paperTrade.findMany({
    where:{botId:'BANKROLL_200', status:{in:['closed','resolved']}, OR:[{closedAt:{gte:since14}},{resolvedAt:{gte:since14}}]},
    select:{realizedPnl:true, closedAt:true, resolvedAt:true, venue:true, entryPrice:true, simulatedPositionSize:true, status:true}
  });
  const byDay=new Map(), byDayN=new Map(), byDayV=new Map();
  for(const t of fin){const ts=t.closedAt??t.resolvedAt; if(!ts)continue; const k=dayKey(new Date(ts));
    byDay.set(k,(byDay.get(k)??0)+(t.realizedPnl??0)); byDayN.set(k,(byDayN.get(k)??0)+1);
    const v=byDayV.get(k)??{}; v[t.venue]=(v[t.venue]??0)+(t.realizedPnl??0); byDayV.set(k,v);}
  console.log('--- LAST 14 DAYS (realized | closes | by venue) ---');
  let cum=0;
  for(let i=13;i>=0;i--){const d=new Date(startOfDay.getTime()-i*86400000);const k=dayKey(d);
    const p=byDay.get(k)??0; cum+=p;
    console.log(`${k}  pnl=${p.toFixed(2)}  closes=${byDayN.get(k)??0}  ${JSON.stringify(byDayV.get(k)??{})}`);}
  console.log('14d total realized =', cum.toFixed(2));

  const open = await prisma.paperTrade.findMany({where:{botId:'BANKROLL_200',status:'open'},
    select:{venue:true,entryPrice:true,simulatedPositionSize:true,unrealizedPnl:true,openedAt:true,marketId:true,decision:{select:{confidence:true,walletAddress:true}}}});
  const tot = open.reduce((a,t)=>a+(t.simulatedPositionSize??0),0);
  const totU = open.reduce((a,t)=>a+(t.unrealizedPnl??0),0);
  console.log(`\n--- OPEN BOOK: n=${open.length} deployed=$${tot.toFixed(2)} unrealized=$${totU.toFixed(2)} ---`);
  const byVenue={}; for(const t of open){byVenue[t.venue]=(byVenue[t.venue]??0)+1;}
  console.log('by venue:', JSON.stringify(byVenue));
  const bands={};
  for(const t of open){const p=t.entryPrice??0; const b=p<0.2?'<0.20':p<0.4?'0.20-0.40':p<0.6?'0.40-0.60':p<0.8?'0.60-0.80':'0.80+';
    bands[b]=bands[b]??{n:0,size:0,u:0}; bands[b].n++; bands[b].size+=t.simulatedPositionSize??0; bands[b].u+=t.unrealizedPnl??0;}
  for(const [k,v] of Object.entries(bands)) console.log(` band ${k}: n=${v.n} size=$${v.size.toFixed(2)} unreal=$${v.u.toFixed(2)}`);
  console.log('sizes:', JSON.stringify(open.map(t=>+(t.simulatedPositionSize??0).toFixed(2))));
  const old = open.filter(t=>t.openedAt && t.openedAt.getTime() < startOfDay.getTime()-7*86400000);
  console.log(`open positions older than 7d: ${old.length}`);
  const ages = open.map(t=>Math.round((Date.now()-t.openedAt.getTime())/86400000)).sort((a,b)=>b-a);
  console.log('age days desc:', JSON.stringify(ages));

  const todayNew = await prisma.paperTrade.findMany({where:{botId:'BANKROLL_200',openedAt:{gte:startOfDay}},select:{venue:true,simulatedPositionSize:true,entryPrice:true,status:true,decision:{select:{confidence:true}}}});
  console.log(`\n--- OPENED TODAY: n=${todayNew.length} ---`);
  for(const t of todayNew) console.log(` ${t.venue} size=${(t.simulatedPositionSize??0).toFixed(2)} entry=${(t.entryPrice??0).toFixed(3)} conf=${t.decision?t.decision.confidence:'-'} ${t.status}`);

  const last24 = new Date(Date.now()-86400000);
  const dj = await prisma.decisionJournal.findMany({where:{createdAt:{gte:last24}},select:{decision:true,confidence:true}});
  const dec={}; for(const d of dj) dec[d.decision]=(dec[d.decision]??0)+1;
  console.log('\ndecisionJournal last24h:', JSON.stringify(dec), 'n=', dj.length);

  const rules = await prisma.ruleSet.findMany({orderBy:{version:'desc'},take:3,select:{version:true,createdAt:true,active:true}});
  console.log('recent RuleSets:', JSON.stringify(rules));
  const active = await prisma.ruleSet.findFirst({where:{active:true},select:{version:true,rulesJson:true}});
  if(active){const r=JSON.parse(active.rulesJson); console.log('ACTIVE ruleset v'+active.version+':', JSON.stringify(r).slice(0,1400));}
  const br = await prisma.botBankroll.findUnique({where:{botId:'BANKROLL_200'}});
  console.log('bankroll:', JSON.stringify(br));
  await prisma.$disconnect();
}
main().catch(e=>{console.error(e.message);process.exit(1)});
