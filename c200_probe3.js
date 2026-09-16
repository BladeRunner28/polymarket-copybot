const { PrismaClient } = require('@prisma/client');
const p = new PrismaClient();
(async()=>{
  const rs = await p.ruleSet.findMany({ orderBy:{version:'asc'} });
  for (const r of rs.slice(-4)) {
    const j = r.rules ? JSON.parse(r.rules) : {};
    console.log(`v${r.version} created=${r.createdAt.toISOString().slice(0,16)} active=${r.isActive} notes=${String(r.notes||r.reason||'').slice(0,180)}`);
    const keys = ['minConfidence','maxPositionSize','minPositionSize','baseExposureCap','exposureCap','maxOpenPositions','longshotBoost','longshot','hourGates','deadZone'];
    for (const k of keys) if (j[k]!==undefined) console.log('   ', k, '=', JSON.stringify(j[k]).slice(0,200));
  }
})().finally(()=>p.$disconnect());
