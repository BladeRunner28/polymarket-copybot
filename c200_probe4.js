const { PrismaClient } = require('@prisma/client');
const p = new PrismaClient();
(async()=>{
  const rs = await p.ruleSet.findMany({ orderBy:{version:'desc'}, take:1 });
  const r = rs[0];
  console.log('COLUMNS:', Object.keys(r).join(','));
  const j = JSON.stringify(r);
  console.log(j.length);
  console.log(j.slice(0,4000));
  const active = await p.ruleSet.findMany({ where:{ isActive:true } });
  console.log('\nACTIVE:', active.map(a=>`v${a.version}`).join(','));
})().finally(()=>p.$disconnect());
